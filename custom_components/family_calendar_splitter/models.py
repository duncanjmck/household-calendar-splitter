"""Household configuration model (pure Python, no Home Assistant imports).

A ``Household`` describes who lives in the house, which words in an event
title refer to them, and how strictly titles are matched. It round-trips
through plain dicts so it can be stored in a config entry's options.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
import re
import unicodedata
from typing import Any

# Calendar key for events that mention nobody. Kept as "family" so existing
# entity unique IDs stay valid.
UNASSIGNED_KEY = "family"

_KEY_RE = re.compile(r"^[a-z0-9_]+$")

# Aliases that are also everyday English words. Not an error, but setup should
# warn and suggest case-sensitive matching or a stricter match mode.
COMMON_WORDS = frozenset(
    """
    all april art august bill bob crystal dawn faith frank grace guy hope
    iris ivy jack jade jay joy june kit lily mark may mike miles nick olive
    pat penny pearl rich rob rose ruby sage sky summer sunny terry rose
    will win
    """.split()
)


class MatchMode(StrEnum):
    """How names are recognised in a title."""

    #: A name anywhere in the title ("Swim with Oscar").
    ANYWHERE = "anywhere"
    #: Only names at the very start of the title ("Oscar and Felix - swim").
    LEADING = "leading"
    #: Only explicitly tagged names: "Oscar: swim" or "[Oscar] swim" /
    #: "Swim [Oscar, Felix]".
    TAGGED = "tagged"


class HouseholdError(ValueError):
    """Raised when a household configuration is invalid."""


def slugify(name: str) -> str:
    """Make a calendar key from a display name ("Mary-Jane" -> "mary_jane")."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_name.casefold()).strip("_")
    return slug or "person"


def unique_key(name: str, existing: Iterable[str]) -> str:
    """A calendar key for ``name`` that isn't reserved or already taken."""
    taken = {*existing, UNASSIGNED_KEY}
    base = slugify(name)
    key, n = base, 2
    while key in taken:
        key, n = f"{base}_{n}", n + 1
    return key


def _clean_aliases(values: Iterable[str]) -> tuple[str, ...]:
    seen: list[str] = []
    for value in values:
        value = str(value).strip()
        if value and value.casefold() not in {s.casefold() for s in seen}:
            seen.append(value)
    return tuple(seen)


@dataclass(frozen=True, slots=True)
class Person:
    """A household member who gets their own derived calendar."""

    key: str
    name: str
    aliases: tuple[str, ...] = ()
    icon: str = "mdi:calendar-account"
    #: Only match aliases with exactly the capitalisation given ("Will", not
    #: "will"). Useful when a name is also an ordinary word.
    case_sensitive: bool = False

    @property
    def terms(self) -> tuple[str, ...]:
        """Words that refer to this person: the display name plus aliases."""
        return _clean_aliases((self.name, *self.aliases))

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "aliases": list(self.aliases),
            "icon": self.icon,
            "case_sensitive": self.case_sensitive,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Person:
        name = str(data["name"]).strip()
        return cls(
            key=str(data.get("key") or slugify(name)),
            name=name,
            aliases=_clean_aliases(data.get("aliases", ())),
            icon=str(data.get("icon") or "mdi:calendar-account"),
            case_sensitive=bool(data.get("case_sensitive", False)),
        )


@dataclass(frozen=True, slots=True)
class Group:
    """A word that stands for several people ("boys", "kids", "everyone")."""

    aliases: tuple[str, ...]
    #: Person keys; ``None`` means every person in the household.
    members: tuple[str, ...] | None = None
    case_sensitive: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "aliases": list(self.aliases),
            "members": None if self.members is None else list(self.members),
            "case_sensitive": self.case_sensitive,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Group:
        members = data.get("members")
        return cls(
            aliases=_clean_aliases(data.get("aliases", ())),
            members=None if members is None else tuple(str(m) for m in members),
            case_sensitive=bool(data.get("case_sensitive", False)),
        )


@dataclass(frozen=True, slots=True)
class MatchSettings:
    """Household-wide matching behaviour."""

    mode: MatchMode = MatchMode.ANYWHERE
    #: Words that join several names: "Oscar and Felix". The symbols
    #: , & + / always join names.
    joiner_words: tuple[str, ...] = ("and",)
    #: Words removed when left dangling before a name: "Lunch with Isla".
    leading_words: tuple[str, ...] = ("with", "and")
    #: Remove recognised names from the derived event title.
    strip_names: bool = True
    #: Keep only one copy of an event that appears more than once on the same
    #: person's calendar (e.g. present on two source calendars).
    remove_duplicates: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "joiner_words": list(self.joiner_words),
            "leading_words": list(self.leading_words),
            "strip_names": self.strip_names,
            "remove_duplicates": self.remove_duplicates,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MatchSettings:
        defaults = cls()
        return cls(
            mode=MatchMode(data.get("mode", defaults.mode)),
            joiner_words=_clean_aliases(data.get("joiner_words", defaults.joiner_words)),
            leading_words=_clean_aliases(data.get("leading_words", defaults.leading_words)),
            strip_names=bool(data.get("strip_names", defaults.strip_names)),
            remove_duplicates=bool(data.get("remove_duplicates", defaults.remove_duplicates)),
        )


@dataclass(frozen=True, slots=True)
class Household:
    """Everything needed to split events into per-person calendars.

    A household with no people is valid: every event goes to the unassigned
    calendar until people are added.
    """

    people: tuple[Person, ...]
    groups: tuple[Group, ...] = ()
    settings: MatchSettings = field(default_factory=MatchSettings)
    unassigned_name: str = "Household events"
    unassigned_icon: str = "mdi:calendar-heart"

    def __post_init__(self) -> None:
        self.validate()

    # ----- derived views -------------------------------------------------

    @property
    def person_keys(self) -> tuple[str, ...]:
        return tuple(p.key for p in self.people)

    def group_members(self, group: Group) -> tuple[str, ...]:
        return self.person_keys if group.members is None else group.members

    def calendars(self) -> dict[str, tuple[str, str]]:
        """Calendar key -> (display name, icon), unassigned calendar first."""
        result = {UNASSIGNED_KEY: (self.unassigned_name, self.unassigned_icon)}
        result.update({p.key: (p.name, p.icon) for p in self.people})
        return result

    def common_word_aliases(self) -> list[str]:
        """Case-insensitive aliases that are also everyday words (for warnings)."""
        found: list[str] = []
        for term, _targets, case_sensitive in self.iter_terms():
            if not case_sensitive and term.casefold() in COMMON_WORDS:
                found.append(term)
        return found

    def iter_terms(self) -> Iterable[tuple[str, tuple[str, ...], bool]]:
        """Yield (alias, person keys it refers to, case sensitive)."""
        for person in self.people:
            for term in person.terms:
                yield term, (person.key,), person.case_sensitive
        for group in self.groups:
            for term in group.aliases:
                yield term, self.group_members(group), group.case_sensitive

    # ----- validation ----------------------------------------------------

    def validate(self) -> None:
        keys: set[str] = set()
        for person in self.people:
            if not _KEY_RE.match(person.key):
                raise HouseholdError(f"Invalid key {person.key!r}: use a-z, 0-9 and _")
            if person.key == UNASSIGNED_KEY:
                raise HouseholdError(f"{person.key!r} is reserved for the unassigned calendar")
            if person.key in keys:
                raise HouseholdError(f"Duplicate person key {person.key!r}")
            if not person.name:
                raise HouseholdError("Every person needs a name")
            keys.add(person.key)

        for group in self.groups:
            if not group.aliases:
                raise HouseholdError("Every group needs at least one word")
            if group.members is not None:
                unknown = set(group.members) - keys
                if unknown:
                    raise HouseholdError(
                        f"Group {group.aliases[0]!r} has unknown members: {sorted(unknown)}"
                    )
                if not group.members:
                    raise HouseholdError(f"Group {group.aliases[0]!r} has no members")

        owners: dict[str, tuple[str, ...]] = {}
        for term, targets, _case in self.iter_terms():
            folded = term.casefold()
            if folded in owners and owners[folded] != targets:
                raise HouseholdError(f"{term!r} is used for more than one person or group")
            owners[folded] = targets

    # ----- serialisation -------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "people": [p.to_dict() for p in self.people],
            "groups": [g.to_dict() for g in self.groups],
            "settings": self.settings.to_dict(),
            "unassigned_name": self.unassigned_name,
            "unassigned_icon": self.unassigned_icon,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Household:
        try:
            return cls(
                people=tuple(Person.from_dict(p) for p in data.get("people", ())),
                groups=tuple(Group.from_dict(g) for g in data.get("groups", ())),
                settings=MatchSettings.from_dict(data.get("settings", {})),
                unassigned_name=str(data.get("unassigned_name") or "Household events"),
                unassigned_icon=str(data.get("unassigned_icon") or "mdi:calendar-heart"),
            )
        except (KeyError, TypeError, ValueError) as err:
            if isinstance(err, HouseholdError):
                raise
            raise HouseholdError(f"Invalid household configuration: {err}") from err
