"""Translate between config entry storage and the household model.

Pure Python (no Home Assistant imports) so it can be unit tested.

Storage layout:

* ``entry.options``: source calendars, match settings and the unassigned
  calendar's name.
* one ``person`` sub-entry per household member: ``Person.to_dict()``.
* one ``group`` sub-entry per group word set: ``Group.to_dict()``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import logging
from typing import Any

from .const import (
    CONF_SETTINGS,
    CONF_SOURCE_CALENDARS,
    CONF_UNASSIGNED_NAME,
    DEFAULT_UNASSIGNED_NAME,
    SUBENTRY_GROUP,
    SUBENTRY_PERSON,
)
from .models import Group, Household, MatchSettings, Person

_LOGGER = logging.getLogger(__name__)

#: (sub-entry type, sub-entry data)
SubentryItem = tuple[str, Mapping[str, Any]]


def source_calendars(options: Mapping[str, Any], data: Mapping[str, Any]) -> list[str]:
    """Source calendars from options, falling back to v1/v2 entry data."""
    return list(options.get(CONF_SOURCE_CALENDARS) or data.get(CONF_SOURCE_CALENDARS) or [])


def build_household(options: Mapping[str, Any], subentries: Iterable[SubentryItem]) -> Household:
    """Build the household stored in a config entry.

    Lenient about references that have gone stale (a group member whose person
    sub-entry was deleted): those are dropped rather than failing setup.
    Raises ``HouseholdError`` for anything else that is invalid.
    """
    items = list(subentries)
    people = tuple(Person.from_dict(data) for kind, data in items if kind == SUBENTRY_PERSON)
    keys = {p.key for p in people}

    groups: list[Group] = []
    for kind, data in items:
        if kind != SUBENTRY_GROUP:
            continue
        group = Group.from_dict(data)
        if group.members is not None:
            members = tuple(m for m in group.members if m in keys)
            if members != group.members:
                _LOGGER.debug("Group %s: dropping removed members", group.aliases)
            if not members:
                continue
            group = Group(group.aliases, members, group.case_sensitive)
        groups.append(group)

    return Household(
        people=people,
        groups=tuple(groups),
        settings=MatchSettings.from_dict(options.get(CONF_SETTINGS) or {}),
        unassigned_name=str(options.get(CONF_UNASSIGNED_NAME) or DEFAULT_UNASSIGNED_NAME),
    )


def subentry_title_for_group(group: Group, people: Iterable[Person]) -> str:
    """A readable title such as "boys (Oscar, Felix)" or "everyone (all)"."""
    names = {p.key: p.name for p in people}
    who = "all" if group.members is None else ", ".join(names.get(m, m) for m in group.members)
    return f"{group.aliases[0]} ({who})"


def household_to_storage(household: Household, sources: list[str]) -> tuple[dict, list[dict]]:
    """Options and sub-entry definitions that store ``household``.

    Sub-entries are returned as dicts with the keys Home Assistant's
    ``ConfigSubentryData`` expects: data, subentry_type, title, unique_id.
    """
    options = {
        CONF_SOURCE_CALENDARS: list(sources),
        CONF_SETTINGS: household.settings.to_dict(),
        CONF_UNASSIGNED_NAME: household.unassigned_name,
    }
    subentries = [
        {
            "data": person.to_dict(),
            "subentry_type": SUBENTRY_PERSON,
            "title": person.name,
            "unique_id": person.key,
        }
        for person in household.people
    ]
    subentries.extend(
        {
            "data": group.to_dict(),
            "subentry_type": SUBENTRY_GROUP,
            "title": subentry_title_for_group(group, household.people),
            "unique_id": group.aliases[0].casefold(),
        }
        for group in household.groups
    )
    return options, subentries
