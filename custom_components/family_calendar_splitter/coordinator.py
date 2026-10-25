"""Polling coordinator for derived family calendars."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Mapping
from datetime import datetime, timedelta
import logging
import time
from typing import Any

from homeassistant.components.calendar import CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    LOOKAHEAD,
    LOOKBACK,
    RANGE_CACHE_SIZE,
    RANGE_CACHE_TTL,
    SOURCE_TIMEOUT,
    UPDATE_INTERVAL,
)
from .models import Household
from .parser import TitleMatcher
from .splitter import DerivedEvent, split_events

_LOGGER = logging.getLogger(__name__)

RawEvents = dict[str, list[Mapping[str, Any]]]
Split = dict[str, list[CalendarEvent]]


def _to_calendar_event(event: DerivedEvent) -> CalendarEvent:
    return CalendarEvent(
        start=event.start,
        end=event.end,
        summary=event.summary,
        description=event.description,
        location=event.location,
        uid=event.uid,
    )


def _overlapping(events: list[CalendarEvent], start: datetime, end: datetime) -> list[CalendarEvent]:
    return [e for e in events if e.end_datetime_local > start and e.start_datetime_local < end]


class FamilyCalendarCoordinator(DataUpdateCoordinator[Split]):
    """Fetch source calendars and split their events into person calendars."""

    def __init__(
        self, hass: HomeAssistant, source_calendars: list[str], household: Household
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="Household Calendar Splitter",
            update_interval=UPDATE_INTERVAL,
        )
        self.source_calendars = source_calendars
        self.household = household
        self.matcher = TitleMatcher(household)
        #: Sources that failed on the last refresh (their previous events are
        #: still shown).
        self.failed_sources: set[str] = set()
        self._last_good: RawEvents = {}
        self._window: tuple[datetime, datetime] | None = None
        self._ranges: OrderedDict[tuple[datetime, datetime], tuple[float, Split]] = OrderedDict()
        self._inflight: dict[tuple[datetime, datetime], asyncio.Task[Split]] = {}

    # ----- fetching -------------------------------------------------------

    async def _async_fetch_source(
        self, source: str, start: datetime, end: datetime
    ) -> list[Mapping[str, Any]]:
        async with asyncio.timeout(SOURCE_TIMEOUT.total_seconds()):
            result = await self.hass.services.async_call(
                "calendar",
                "get_events",
                {"start_date_time": start.isoformat(), "end_date_time": end.isoformat()},
                target={"entity_id": source},
                blocking=True,
                return_response=True,
            )
        response = result.get("response", result) if isinstance(result, Mapping) else {}
        payload = response.get(source) if isinstance(response, Mapping) else None
        if not isinstance(payload, Mapping) or not isinstance(payload.get("events"), list):
            raise HomeAssistantError(f"{source} returned no events list")
        return [e for e in payload["events"] if isinstance(e, Mapping)]

    async def _async_fetch(self, start: datetime, end: datetime) -> tuple[RawEvents, dict[str, str]]:
        """Fetch every source separately. Returns (events by source, errors by source)."""
        results = await asyncio.gather(
            *(self._async_fetch_source(s, start, end) for s in self.source_calendars),
            return_exceptions=True,
        )
        raw: RawEvents = {}
        errors: dict[str, str] = {}
        for source, result in zip(self.source_calendars, results):
            if isinstance(result, BaseException):
                if isinstance(result, asyncio.CancelledError):
                    raise result
                errors[source] = (
                    "timed out" if isinstance(result, TimeoutError) else str(result) or type(result).__name__
                )
            else:
                raw[source] = result
        return raw, errors

    def _build(self, raw: RawEvents) -> Split:
        # Keep sources in configured order so the same copy of a duplicate wins.
        ordered = {s: raw[s] for s in self.source_calendars if s in raw}
        derived = split_events(
            ordered,
            self.matcher,
            remove_duplicates=self.household.settings.remove_duplicates,
            to_local=dt_util.as_local,
        )
        split: Split = {}
        for key, events in derived.items():
            converted = [_to_calendar_event(e) for e in events]
            converted.sort(key=lambda item: item.start_datetime_local)
            split[key] = converted
        return split

    # ----- scheduled refresh ---------------------------------------------

    async def _async_update_data(self) -> Split:
        if not self.source_calendars:
            self._window = None
            return {}

        now = dt_util.now()
        start = dt_util.start_of_local_day(now - LOOKBACK)
        end = now + LOOKAHEAD
        raw, errors = await self._async_fetch(start, end)

        stale = [s for s in errors if s in self._last_good]
        if len(errors) == len(self.source_calendars) and not stale:
            raise UpdateFailed(
                "Unable to read any source calendar: "
                + "; ".join(f"{s}: {e}" for s, e in errors.items())
            )

        for source, error in errors.items():
            if source not in self.failed_sources:
                _LOGGER.warning(
                    "Could not read %s (%s); %s",
                    source,
                    error,
                    "showing its last received events" if source in stale else "its events are missing",
                )
            if source in self._last_good:
                raw[source] = self._last_good[source]
        for source in self.failed_sources - errors.keys():
            _LOGGER.info("%s is readable again", source)

        self._last_good.update({s: raw[s] for s in raw if s not in errors})
        self.failed_sources = set(errors)
        self._window = (start, end)
        self._ranges.clear()
        return self._build(raw)

    # ----- reads ----------------------------------------------------------

    async def async_events(self, key: str, start: datetime, end: datetime) -> list[CalendarEvent]:
        """Events for one derived calendar overlapping [start, end)."""
        if self._window and self.data is not None:
            window_start, window_end = self._window
            if start >= window_start and end <= window_end:
                return _overlapping(self.data.get(key, []), start, end)
        split = await self._async_range(start, end)
        return _overlapping(split.get(key, []), start, end)

    async def _async_range(self, start: datetime, end: datetime) -> Split:
        # Whole local days, so nearby requests share a cache entry.
        range_start = dt_util.start_of_local_day(start)
        range_end = dt_util.start_of_local_day(end) + timedelta(days=1)
        cache_key = (range_start, range_end)

        cached = self._ranges.get(cache_key)
        if cached and time.monotonic() - cached[0] < RANGE_CACHE_TTL.total_seconds():
            self._ranges.move_to_end(cache_key)
            return cached[1]

        task = self._inflight.get(cache_key)
        if task is None:
            task = self.hass.async_create_task(
                self._async_fetch_range(range_start, range_end),
                "family_calendar_splitter range fetch",
            )
            self._inflight[cache_key] = task
            task.add_done_callback(lambda _t: self._inflight.pop(cache_key, None))
        return await asyncio.shield(task)

    async def _async_fetch_range(self, start: datetime, end: datetime) -> Split:
        raw, errors = await self._async_fetch(start, end)
        if errors and not raw:
            raise HomeAssistantError(
                "Unable to read any source calendar: "
                + "; ".join(f"{s}: {e}" for s, e in errors.items())
            )
        for source, error in errors.items():
            _LOGGER.debug("Range fetch: could not read %s (%s)", source, error)
        split = self._build(raw)
        self._ranges[(start, end)] = (time.monotonic(), split)
        while len(self._ranges) > RANGE_CACHE_SIZE:
            self._ranges.popitem(last=False)
        return split
