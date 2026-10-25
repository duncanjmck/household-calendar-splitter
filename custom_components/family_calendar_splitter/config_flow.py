"""Config, options and sub-entry flows for Household Calendar Splitter."""

from __future__ import annotations

from collections.abc import Mapping
import dataclasses
from typing import Any

import voluptuous as vol

from homeassistant.components.calendar import DOMAIN as CALENDAR_DOMAIN
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentry,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    IconSelector,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
)

from .config import SubentryItem, build_household, household_to_storage, source_calendars
from .config import subentry_title_for_group
from .const import (
    CONF_ALIASES,
    CONF_CASE_SENSITIVE,
    CONF_EVERYONE,
    CONF_ICON,
    CONF_JOINER_WORDS,
    CONF_LEADING_WORDS,
    CONF_MEMBERS,
    CONF_MODE,
    CONF_NAME,
    CONF_PEOPLE,
    CONF_REMOVE_DUPLICATES,
    CONF_SETTINGS,
    CONF_SOURCE_CALENDARS,
    CONF_STRIP_NAMES,
    CONF_UNASSIGNED_NAME,
    CONF_WORDS,
    DEFAULT_UNASSIGNED_NAME,
    DOMAIN,
    SUBENTRY_GROUP,
    SUBENTRY_PERSON,
)
from .models import (
    COMMON_WORDS,
    Group,
    Household,
    HouseholdError,
    MatchMode,
    MatchSettings,
    Person,
    unique_key,
)

_SOURCES_SELECTOR = EntitySelector(EntitySelectorConfig(domain=CALENDAR_DOMAIN, multiple=True))
_LIST_SELECTOR = TextSelector(TextSelectorConfig(multiple=True))


def _subentry_items(
    entry: ConfigEntry,
    *,
    replace: str | None = None,
    add: SubentryItem | None = None,
) -> list[SubentryItem]:
    """The entry's sub-entries, optionally with one replaced or added."""
    items: list[SubentryItem] = [
        (sub.subentry_type, sub.data)
        for sub_id, sub in entry.subentries.items()
        if sub_id != replace
    ]
    if add is not None:
        items.append(add)
    return items


def _check(options: Mapping[str, Any], items: list[SubentryItem]) -> str | None:
    """Return an error message if the resulting household would be invalid."""
    try:
        build_household(options, items)
    except HouseholdError as err:
        return str(err)
    return None


def _clean_list(values: Any) -> list[str]:
    return [str(v).strip() for v in values or [] if str(v).strip()]


class FamilyCalendarSplitterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Initial setup: source calendars and (optionally) the first people."""

    # v1: original release. v2: entry-based unique IDs. v3: household stored in
    # options and sub-entries. See __init__.async_migrate_entry.
    VERSION = 3

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return FamilyCalendarOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_PERSON: PersonSubentryFlow, SUBENTRY_GROUP: GroupSubentryFlow}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        errors: dict[str, str] = {}
        placeholders = {"error": ""}
        if user_input is not None:
            keys: list[str] = []
            people: list[Person] = []
            for name in _clean_list(user_input.get(CONF_PEOPLE)):
                key = unique_key(name, keys)
                keys.append(key)
                people.append(Person(key=key, name=name))
            try:
                household = Household(people=tuple(people))
            except HouseholdError as err:
                errors["base"] = "invalid_household"
                placeholders["error"] = str(err)
            else:
                options, subentries = household_to_storage(
                    household, list(user_input[CONF_SOURCE_CALENDARS])
                )
                return self.async_create_entry(
                    title="Household Calendar Splitter",
                    data={},
                    options=options,
                    subentries=subentries,
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_SOURCE_CALENDARS): _SOURCES_SELECTOR,
                vol.Optional(CONF_PEOPLE, default=[]): _LIST_SELECTOR,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
            description_placeholders=placeholders,
        )


class FamilyCalendarOptionsFlow(OptionsFlow):
    """Household-wide settings: sources and how titles are matched."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self.config_entry
        errors: dict[str, str] = {}
        placeholders = {"error": ""}

        if user_input is not None:
            settings = MatchSettings.from_dict(
                {
                    "mode": user_input[CONF_MODE],
                    "joiner_words": _clean_list(user_input.get(CONF_JOINER_WORDS)),
                    "leading_words": _clean_list(user_input.get(CONF_LEADING_WORDS)),
                    "strip_names": user_input[CONF_STRIP_NAMES],
                    "remove_duplicates": user_input[CONF_REMOVE_DUPLICATES],
                }
            )
            options = {
                CONF_SOURCE_CALENDARS: list(user_input[CONF_SOURCE_CALENDARS]),
                CONF_SETTINGS: settings.to_dict(),
                CONF_UNASSIGNED_NAME: user_input[CONF_UNASSIGNED_NAME].strip()
                or DEFAULT_UNASSIGNED_NAME,
            }
            if error := _check(options, _subentry_items(entry)):
                errors["base"] = "invalid_household"
                placeholders["error"] = error
            else:
                return self.async_create_entry(data=options)

        current = MatchSettings.from_dict(entry.options.get(CONF_SETTINGS) or {})
        suggested = user_input or {
            CONF_SOURCE_CALENDARS: source_calendars(entry.options, entry.data),
            CONF_MODE: current.mode.value,
            CONF_JOINER_WORDS: list(current.joiner_words),
            CONF_LEADING_WORDS: list(current.leading_words),
            CONF_STRIP_NAMES: current.strip_names,
            CONF_REMOVE_DUPLICATES: current.remove_duplicates,
            CONF_UNASSIGNED_NAME: entry.options.get(CONF_UNASSIGNED_NAME)
            or DEFAULT_UNASSIGNED_NAME,
        }
        schema = vol.Schema(
            {
                vol.Required(CONF_SOURCE_CALENDARS): _SOURCES_SELECTOR,
                vol.Required(CONF_MODE, default=MatchMode.ANYWHERE.value): SelectSelector(
                    SelectSelectorConfig(
                        options=[mode.value for mode in MatchMode],
                        translation_key=CONF_MODE,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
                vol.Optional(CONF_JOINER_WORDS, default=[]): _LIST_SELECTOR,
                vol.Optional(CONF_LEADING_WORDS, default=[]): _LIST_SELECTOR,
                vol.Required(CONF_STRIP_NAMES, default=True): BooleanSelector(),
                vol.Required(CONF_REMOVE_DUPLICATES, default=True): BooleanSelector(),
                vol.Required(CONF_UNASSIGNED_NAME, default=DEFAULT_UNASSIGNED_NAME): TextSelector(),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
            description_placeholders=placeholders,
        )


class PersonSubentryFlow(ConfigSubentryFlow):
    """Add or edit a household member."""

    def __init__(self) -> None:
        self._pending: tuple[Person, ConfigSubentry | None] | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        return await self._async_step_person("user", user_input, None)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_step_person(
            "reconfigure", user_input, self._get_reconfigure_subentry()
        )

    async def _async_step_person(
        self,
        step_id: str,
        user_input: dict[str, Any] | None,
        subentry: ConfigSubentry | None,
    ) -> SubentryFlowResult:
        entry = self._get_entry()
        errors: dict[str, str] = {}
        placeholders = {"error": ""}

        if user_input is not None:
            if subentry is not None:
                key = str(subentry.data["key"])  # keep the key so entity IDs survive renames
            else:
                key = unique_key(
                    user_input[CONF_NAME],
                    (s.data.get("key", "") for s in entry.get_subentries_of_type(SUBENTRY_PERSON)),
                )
            person = Person.from_dict(
                {
                    "key": key,
                    "name": user_input[CONF_NAME],
                    "aliases": _clean_list(user_input.get(CONF_ALIASES)),
                    "icon": user_input.get(CONF_ICON),
                    "case_sensitive": user_input.get(CONF_CASE_SENSITIVE, False),
                }
            )
            items = _subentry_items(
                entry,
                replace=subentry.subentry_id if subentry else None,
                add=(SUBENTRY_PERSON, person.to_dict()),
            )
            if error := _check(entry.options, items):
                errors["base"] = "invalid_household"
                placeholders["error"] = error
            else:
                self._pending = (person, subentry)
                mode = MatchSettings.from_dict(entry.options.get(CONF_SETTINGS) or {}).mode
                if (
                    not person.case_sensitive
                    and mode is MatchMode.ANYWHERE
                    and any(t.casefold() in COMMON_WORDS for t in person.terms)
                ):
                    return await self.async_step_common_word()
                return self._async_finish(person, subentry)

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): TextSelector(),
                vol.Optional(CONF_ALIASES, default=[]): _LIST_SELECTOR,
                vol.Optional(CONF_ICON, default="mdi:calendar-account"): IconSelector(),
                vol.Optional(CONF_CASE_SENSITIVE, default=False): BooleanSelector(),
            }
        )
        suggested = user_input or (dict(subentry.data) if subentry else {})
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_common_word(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Offer case-sensitive matching for names that are everyday words."""
        assert self._pending is not None
        person, subentry = self._pending
        if user_input is not None:
            if user_input[CONF_CASE_SENSITIVE]:
                person = dataclasses.replace(person, case_sensitive=True)
            return self._async_finish(person, subentry)

        words = ", ".join(t for t in person.terms if t.casefold() in COMMON_WORDS)
        return self.async_show_form(
            step_id="common_word",
            data_schema=vol.Schema({vol.Required(CONF_CASE_SENSITIVE, default=True): BooleanSelector()}),
            description_placeholders={"words": words},
        )

    @callback
    def _async_finish(self, person: Person, subentry: ConfigSubentry | None) -> SubentryFlowResult:
        if subentry is None:
            return self.async_create_entry(
                title=person.name, data=person.to_dict(), unique_id=person.key
            )
        return self.async_update_and_abort(
            self._get_entry(), subentry, title=person.name, data=person.to_dict()
        )


class GroupSubentryFlow(ConfigSubentryFlow):
    """Add or edit a group word such as "kids" or "everyone"."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        return await self._async_step_group("user", user_input, None)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_step_group(
            "reconfigure", user_input, self._get_reconfigure_subentry()
        )

    async def _async_step_group(
        self,
        step_id: str,
        user_input: dict[str, Any] | None,
        subentry: ConfigSubentry | None,
    ) -> SubentryFlowResult:
        entry = self._get_entry()
        people = [Person.from_dict(s.data) for s in entry.get_subentries_of_type(SUBENTRY_PERSON)]
        errors: dict[str, str] = {}
        placeholders = {"error": ""}

        if user_input is not None:
            words = _clean_list(user_input.get(CONF_WORDS))
            members = list(user_input.get(CONF_MEMBERS) or [])
            everyone = bool(user_input.get(CONF_EVERYONE))
            if not words:
                errors[CONF_WORDS] = "no_words"
            elif not everyone and not members:
                errors[CONF_MEMBERS] = "no_members"
            else:
                group = Group.from_dict(
                    {
                        "aliases": words,
                        "members": None if everyone else members,
                        "case_sensitive": user_input.get(CONF_CASE_SENSITIVE, False),
                    }
                )
                items = _subentry_items(
                    entry,
                    replace=subentry.subentry_id if subentry else None,
                    add=(SUBENTRY_GROUP, group.to_dict()),
                )
                if error := _check(entry.options, items):
                    errors["base"] = "invalid_household"
                    placeholders["error"] = error
                else:
                    title = subentry_title_for_group(group, people)
                    if subentry is None:
                        return self.async_create_entry(
                            title=title, data=group.to_dict(), unique_id=words[0].casefold()
                        )
                    return self.async_update_and_abort(
                        entry, subentry, title=title, data=group.to_dict()
                    )

        schema = vol.Schema(
            {
                vol.Required(CONF_WORDS): _LIST_SELECTOR,
                vol.Optional(CONF_EVERYONE, default=False): BooleanSelector(),
                vol.Optional(CONF_MEMBERS, default=[]): SelectSelector(
                    SelectSelectorConfig(
                        options=[SelectOptionDict(value=p.key, label=p.name) for p in people],
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
                vol.Optional(CONF_CASE_SENSITIVE, default=False): BooleanSelector(),
            }
        )
        if user_input is not None:
            suggested: dict[str, Any] = user_input
        elif subentry is not None:
            members = subentry.data.get("members")
            suggested = {
                CONF_WORDS: list(subentry.data.get("aliases", [])),
                CONF_EVERYONE: members is None,
                CONF_MEMBERS: list(members or []),
                CONF_CASE_SENSITIVE: subentry.data.get("case_sensitive", False),
            }
        else:
            suggested = {}
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
            description_placeholders=placeholders,
        )
