"""Turn raw source-calendar events into per-person derived events.

Pure Python (no Home Assistant imports) so it can be unit tested.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime
import hashlib
import logging
from typing import Any

from .models import UNASSIGNED_KEY
from .parser import TitleMatcher

_LOGGER = logging.getLogger(__name__)

When = datetime | date


@dataclass(frozen=True, slots=True)
class DerivedEvent:
    """One event as it appears on one derived calendar."""

    start: When
    end: When
    summary: str
    description: str | None
    location: str | None
    uid: str
    source: str


def parse_when(value: Any, to_local: Callable[[datetime], datetime] = lambda d: d) -> When:
    """Decode a calendar.get_events start/end value (date or ISO datetime)."""
    text = str(value)
    if "T" not in text:
        return date.fromisoformat(text)
    return to_local(datetime.fromisoformat(text.replace("Z", "+00:00")))


def stable_uid(source: str, event: Mapping[str, Any], person: str) -> str:
    """A stable, read-only UID for a derived occurrence (unchanged since 0.1)."""
    original = str(event.get("uid") or "")
    if original:
        return f"{source}:{original}:{person}"
    material = "\x1f".join(
        (
            source,
            person,
            str(event.get("summary", "")),
            str(event.get("start", "")),
            str(event.get("end", "")),
        )
    )
    return hashlib.sha256(material.encode()).hexdigest()


def _normal(text: str | None) -> str:
    return " ".join(str(text or "").split()).casefold()


def _duplicate_key(event: DerivedEvent) -> tuple[Any, ...]:
    return (_normal(event.summary), event.start, event.end, _normal(event.location))


def split_events(
    raw: Mapping[str, Iterable[Mapping[str, Any]]],
    matcher: TitleMatcher,
    *,
    remove_duplicates: bool = True,
    to_local: Callable[[datetime], datetime] = lambda d: d,
) -> dict[str, list[DerivedEvent]]:
    """Classify every source event onto the derived calendars.

    ``raw`` maps source calendar entity IDs to their events, in priority order.
    With ``remove_duplicates``, an event that appears more than once on the
    SAME derived calendar (e.g. one Google event present on two people's
    source calendars) is kept once. The same event on different people's
    calendars is never merged: that's how shared events are shown.
    """
    split: dict[str, list[DerivedEvent]] = {}
    seen: dict[str, dict[tuple[Any, ...], int]] = {}

    for source, events in raw.items():
        for event in events:
            if not isinstance(event, Mapping):
                continue
            try:
                start = parse_when(event["start"], to_local)
                end = parse_when(event["end"], to_local)
            except (KeyError, TypeError, ValueError) as err:
                _LOGGER.debug("Skipping malformed source event %s: %s", event, err)
                continue

            original = str(event.get("summary") or "").strip()
            parsed = matcher.parse(original)
            # Unclassified events stay intact on the unassigned calendar;
            # classified events go only to their people's calendars.
            destinations = parsed.people if parsed else (UNASSIGNED_KEY,)
            summary = parsed.summary if parsed else original
            description = event.get("description") or None
            location = event.get("location") or None

            for person in destinations:
                derived = DerivedEvent(
                    start=start,
                    end=end,
                    summary=summary,
                    description=description,
                    location=location,
                    uid=stable_uid(source, event, person),
                    source=source,
                )
                bucket = split.setdefault(person, [])
                if remove_duplicates:
                    index_of = seen.setdefault(person, {})
                    key = _duplicate_key(derived)
                    if key in index_of:
                        kept = bucket[index_of[key]]
                        if not kept.description and derived.description:
                            # Keep the first copy but don't lose details only
                            # the second copy has.
                            bucket[index_of[key]] = replace(kept, description=derived.description)
                        continue
                    index_of[key] = len(bucket)
                bucket.append(derived)
    return split
