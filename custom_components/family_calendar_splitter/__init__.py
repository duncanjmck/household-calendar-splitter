"""Set up Household Calendar Splitter."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.typing import ConfigType

from .config import build_household, household_to_storage, source_calendars
from .const import DOMAIN
from .coordinator import FamilyCalendarCoordinator
from .migration import migrated_unique_id
from .models import Household, HouseholdError
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.CALENDAR]

type FamilyCalendarConfigEntry = ConfigEntry[FamilyCalendarCoordinator]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register actions once, independent of config entries."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: FamilyCalendarConfigEntry) -> bool:
    """Set up derived family calendars from the selected source calendars."""
    try:
        household = build_household(
            entry.options, [(s.subentry_type, s.data) for s in entry.subentries.values()]
        )
    except HouseholdError as err:
        _LOGGER.error("Invalid household configuration: %s", err)
        return False
    for alias in household.common_word_aliases():
        _LOGGER.info(
            "%r is also an everyday word and may match unrelated events; consider "
            "case-sensitive matching or a stricter match mode",
            alias,
        )

    coordinator = FamilyCalendarCoordinator(
        hass, source_calendars(entry.options, entry.data), household
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    # Reload when options change or people/groups are added, edited or removed.
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_reload(hass: HomeAssistant, entry: FamilyCalendarConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: FamilyCalendarConfigEntry) -> bool:
    """Unload a splitter config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entries.

    v1 -> v2: entity unique IDs move from the source-calendar list to the
    config entry ID.
    v2 -> v3: source calendars move to options; people and groups become
    sub-entries managed from the integration page.
    """
    if entry.version > 3:
        # Downgraded from a newer release; refuse rather than corrupt.
        return False

    if entry.version == 1:

        @callback
        def _update(entity_entry: er.RegistryEntry) -> dict[str, Any] | None:
            new_id = migrated_unique_id(entity_entry.unique_id, entry.entry_id)
            return {"new_unique_id": new_id} if new_id else None

        await er.async_migrate_entries(hass, entry.entry_id, _update)
        hass.config_entries.async_update_entry(entry, version=2)
        _LOGGER.info("Migrated Household Calendar Splitter entry to version 2")

    if entry.version == 2:
        _migrate_v2_to_v3(hass, entry)
        _LOGGER.info("Migrated Household Calendar Splitter entry to version 3")

    return True


def _migrate_v2_to_v3(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Move source calendars to options and start with an empty household.

    Versions before 0.4 had no configurable household, so people and groups
    are added afterwards from the integration page.
    """
    options, _subentries = household_to_storage(
        Household(people=()), source_calendars(entry.options, entry.data)
    )
    hass.config_entries.async_update_entry(entry, data={}, options=options, version=3)
