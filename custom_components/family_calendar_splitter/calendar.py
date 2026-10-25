"""Read-only derived person calendars."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, SUBENTRY_PERSON
from .coordinator import FamilyCalendarCoordinator
from .models import UNASSIGNED_KEY, Person

if TYPE_CHECKING:
    from . import FamilyCalendarConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FamilyCalendarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the unassigned calendar and one calendar per person sub-entry."""
    coordinator = entry.runtime_data
    household = coordinator.household
    async_add_entities(
        [
            FamilyPersonCalendar(
                coordinator,
                entry.entry_id,
                UNASSIGNED_KEY,
                household.unassigned_name,
                household.unassigned_icon,
            )
        ]
    )
    for subentry in entry.get_subentries_of_type(SUBENTRY_PERSON):
        person = Person.from_dict(subentry.data)
        async_add_entities(
            [FamilyPersonCalendar(coordinator, entry.entry_id, person.key, person.name, person.icon)],
            config_subentry_id=subentry.subentry_id,
        )


class FamilyPersonCalendar(CalendarEntity):
    """Expose the coordinator cache as a standard, read-only calendar."""

    _attr_has_entity_name = True
    # The entity takes its name from its device (the person).
    _attr_name = None

    def __init__(
        self,
        coordinator: FamilyCalendarCoordinator,
        entry_id: str,
        person: str,
        name: str,
        icon: str,
    ) -> None:
        self.coordinator = coordinator
        self.person = person
        # Stable across changes to the source calendars and to the person's
        # display name (see migration.py).
        self._attr_unique_id = f"{entry_id}:{person}"
        self._attr_icon = icon
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_{person}")},
            name=name,
            entry_type=DeviceEntryType.SERVICE,
            manufacturer="Household Calendar Splitter",
            model="Household calendar" if person == UNASSIGNED_KEY else "Person calendar",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.coordinator.async_add_listener(self.async_write_ha_state))

    @property
    def event(self) -> CalendarEvent | None:
        now = datetime.now().astimezone()
        for event in (self.coordinator.data or {}).get(self.person, []):
            if event.end_datetime_local >= now:
                return event
        return None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return events overlapping the requested range.

        Ranges inside the refreshed window come from memory; anything earlier
        or later is fetched from the source calendars on demand.
        """
        return await self.coordinator.async_events(self.person, start_date, end_date)
