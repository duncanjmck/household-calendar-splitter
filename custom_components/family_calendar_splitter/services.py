"""Actions provided by Household Calendar Splitter."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er

from .const import DOMAIN
from .models import UNASSIGNED_KEY

SERVICE_PREVIEW_TITLE = "preview_title"
ATTR_TITLE = "title"

PREVIEW_SCHEMA = vol.Schema({vol.Required(ATTR_TITLE): cv.string})


def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's actions (once, from async_setup)."""

    async def _async_preview_title(call: ServiceCall) -> ServiceResponse:
        entries = [
            entry
            for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.state is ConfigEntryState.LOADED
        ]
        if not entries:
            raise ServiceValidationError("Household Calendar Splitter is not loaded")
        entry = entries[0]
        coordinator = entry.runtime_data
        household = coordinator.household

        title = call.data[ATTR_TITLE]
        parsed = coordinator.matcher.parse(title)
        keys = parsed.people if parsed else (UNASSIGNED_KEY,)
        names = {p.key: p.name for p in household.people}
        ent_reg = er.async_get(hass)

        return {
            "matched": parsed is not None,
            "people": [names.get(k, k) for k in keys if k != UNASSIGNED_KEY],
            "calendars": [
                ent_reg.async_get_entity_id("calendar", DOMAIN, f"{entry.entry_id}:{k}") or k
                for k in keys
            ],
            "summary": parsed.summary if parsed else title.strip(),
            "mode": household.settings.mode.value,
        }

    hass.services.async_register(
        DOMAIN,
        SERVICE_PREVIEW_TITLE,
        _async_preview_title,
        schema=PREVIEW_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
