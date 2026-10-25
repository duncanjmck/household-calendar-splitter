"""Tests for title classification. No Home Assistant install required.

Run with ``pytest tests`` or ``python tests/test_parser.py``.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _support import SAMPLE_HOUSEHOLD, load  # noqa: E402

parser = load("parser")
migration = load("migration")
models = load("models")
const = load("const")
config = load("config")

DEFAULT = parser.TitleMatcher(models.Household.from_dict(SAMPLE_HOUSEHOLD))


def household(people, groups=(), **settings):
    """Build a matcher from compact test data."""
    return parser.TitleMatcher(
        models.Household.from_dict(
            {"people": list(people), "groups": list(groups), "settings": settings}
        )
    )

ALL = ("oscar", "felix", "isla", "rose", "tom")

# (title, expected people or None, expected summary)
CASES: list[tuple[str, tuple[str, ...] | None, str | None]] = [
    # Existing documented behaviour
    ("Oscar and Felix — swimming", ("oscar", "felix"), "swimming"),
    ("Boys: footy", ("oscar", "felix"), "footy"),
    ("Everyone - beach", ALL, "beach"),
    ("Izzy", ("isla",), "Izzy"),
    ("OZZIE swim", ("oscar",), "swim"),
    ("Oscar/Felix swim", ("oscar", "felix"), "swim"),
    ("Oscar, Felix & Rose - Nan's", ("oscar", "felix", "rose"), "Nan's"),
    # Word boundaries: none of these mention a household member
    ("Cowboys v Broncos", None, None),
    ("Tomboys screening", None, None),
    ("Isabella's visit", None, None),
    ("Tomorrow's trip", None, None),
    ("Rosemary concert", None, None),
    ("Ozzieland", None, None),
    ("O'Oscar", None, None),
    ("Mum & Dad's anniversary", None, None),
    ("", None, None),
    # Possessives (straight and typographic)
    ("Oscar's birthday party", ("oscar",), "birthday party"),
    ("Oscar’s birthday party", ("oscar",), "birthday party"),
    ("Grandmother - everyone's welcome", ALL, "Grandmother welcome"),
    # Separators/connectors not touching a name are preserved
    ("Felix 3:30 dentist", ("felix",), "3:30 dentist"),
    ("Rose - Year 5/6 assembly", ("rose",), "Year 5/6 assembly"),
    ("Dinner with Nan and Pop - Tom", ("tom",), "Dinner with Nan and Pop"),
    ("Tom drop-off", ("tom",), "drop-off"),
    ("Rock & roll night with Isla", ("isla",), "Rock & roll night"),
    ("Lunch with Isla", ("isla",), "Lunch"),
    ("Swim - Oscar - 4:15pm", ("oscar",), "Swim - 4:15pm"),
    ("Pick up Felix from school", ("felix",), "Pick up from school"),
    ("Oscar: Felix: swim", ("oscar", "felix"), "swim"),
    ("Oscar swim, Felix footy", ("oscar", "felix"), "swim footy"),
]


def test_cases() -> None:
    failures = []
    for title, people, summary in CASES:
        result = DEFAULT.parse(title)
        got = None if result is None else (result.people, result.summary)
        want = None if people is None else (people, summary)
        if got != want:
            failures.append(f"{title!r}: got {got}, want {want}")
    assert not failures, "\n".join(failures)


def test_custom_household() -> None:
    matcher = household(
        [{"name": "Will", "case_sensitive": True}, {"name": "May", "aliases": ["Maisie"]}],
        [{"aliases": ["kids"], "members": ["will", "may"]}],
    )
    P = parser.ParsedTitle
    assert matcher.parse("Kids - dentist") == P(("will", "may"), "dentist")
    assert matcher.parse("Maisie piano") == P(("may",), "piano")
    assert matcher.parse("Willow pruning") is None
    # Case-sensitive person: "Will" matches, the verb "will" does not.
    assert matcher.parse("Will - footy") == P(("will",), "footy")
    assert matcher.parse("Plumber will call") is None
    assert matcher.parse("WILL footy") is None
    # Group words with capitals still resolve.
    upper = household([{"name": "Ann"}], [{"aliases": ["The Girls"], "members": ["ann"]}])
    assert upper.parse("the girls: ballet") == P(("ann",), "ballet")


def test_everyone_group_tracks_people() -> None:
    matcher = household(
        [{"name": "Ann"}, {"name": "Bo"}, {"name": "Cy"}], [{"aliases": ["all of us"]}]
    )
    assert matcher.parse("All of us - picnic").people == ("ann", "bo", "cy")


def test_leading_mode() -> None:
    m = household([{"name": "Oscar"}, {"name": "Felix"}], mode="leading")
    P = parser.ParsedTitle
    assert m.parse("Oscar and Felix - swim") == P(("oscar", "felix"), "swim")
    assert m.parse("Swim with Oscar") is None
    # Only the leading run counts; later names stay in the title.
    assert m.parse("Oscar - dinner at Felix's") == P(("oscar",), "dinner at Felix's")


def test_tagged_mode() -> None:
    m = household([{"name": "Oscar"}, {"name": "Felix"}], mode="tagged")
    P = parser.ParsedTitle
    assert m.parse("Oscar: swim") == P(("oscar",), "swim")
    assert m.parse("Oscar & Felix: swim") == P(("oscar", "felix"), "swim")
    assert m.parse("[Oscar] swim") == P(("oscar",), "swim")
    assert m.parse("Swim [Oscar, Felix]") == P(("oscar", "felix"), "Swim")
    assert m.parse("Oscar swim") is None
    assert m.parse("Pick up Oscar: 3pm") is None
    assert m.parse("[Draft] swim") is None


def test_configurable_words_and_stripping() -> None:
    german = household(
        [{"name": "Lena"}, {"name": "Jonas"}], joiner_words=["und"], leading_words=["mit"]
    )
    P = parser.ParsedTitle
    assert german.parse("Lena und Jonas - Schwimmen") == P(("lena", "jonas"), "Schwimmen")
    assert german.parse("Essen mit Lena") == P(("lena",), "Essen")
    assert german.parse("Lena and Jonas swim").summary == "and swim"
    keep = household([{"name": "Ann"}], strip_names=False)
    assert keep.parse("Ann - ballet") == P(("ann",), "Ann - ballet")


def test_household_validation() -> None:
    bad = [
        {"people": [{"name": "Ann"}, {"name": "Ann"}]},
        {"people": [{"name": "Ann", "aliases": ["Bo"]}, {"name": "Bo"}]},
        {"people": [{"name": "Ann"}, {"name": "Bo"}], "groups": [{"aliases": ["ann"], "members": ["ann", "bo"]}]},
        {"people": [{"name": "Ann"}], "groups": [{"aliases": ["kids"], "members": ["zed"]}]},
        {"people": [{"name": "Family"}]},
        {"people": [{"name": "Ann"}], "settings": {"mode": "fuzzy"}},
        {"people": [{"aliases": ["x"]}]},
    ]
    for data in bad:
        try:
            models.Household.from_dict(data)
        except models.HouseholdError:
            continue
        raise AssertionError(f"accepted invalid household: {data}")


def test_household_round_trip_and_warnings() -> None:
    h = models.Household.from_dict(SAMPLE_HOUSEHOLD)
    assert models.Household.from_dict(h.to_dict()) == h
    assert list(h.calendars()) == ["family", "oscar", "felix", "isla", "rose", "tom"]
    assert h.common_word_aliases() == ["Rose"]
    assert models.slugify("Mary-Jane O'Neil") == "mary_jane_o_neil"


def test_storage_round_trip() -> None:
    h = models.Household.from_dict(SAMPLE_HOUSEHOLD)
    options, subs = config.household_to_storage(h, ["calendar.a", "calendar.b"])
    assert options["source_calendars"] == ["calendar.a", "calendar.b"]
    assert [s["unique_id"] for s in subs] == [
        "oscar", "felix", "isla", "rose", "tom", "boys", "everyone"
    ]
    assert subs[5]["title"] == "boys (Oscar, Felix)"
    assert subs[6]["title"] == "everyone (all)"
    items = [(s["subentry_type"], s["data"]) for s in subs]
    assert config.build_household(options, items) == h


def test_build_household_drops_removed_people() -> None:
    items = [
        ("person", {"key": "ann", "name": "Ann"}),
        ("group", {"aliases": ["kids"], "members": ["ann", "bo"]}),
        ("group", {"aliases": ["twins"], "members": ["bo", "cy"]}),
    ]
    h = config.build_household({}, items)
    assert h.groups == (models.Group(("kids",), ("ann",)),)
    assert h.unassigned_name == "Household events"
    # A household with no people is allowed (everything is unassigned).
    assert config.build_household({}, []).people == ()


def test_source_calendars_fallback() -> None:
    assert config.source_calendars({}, {"source_calendars": ["calendar.x"]}) == ["calendar.x"]
    assert config.source_calendars({"source_calendars": ["calendar.y"]}, {}) == ["calendar.y"]


def test_unique_key() -> None:
    assert models.unique_key("Ann", []) == "ann"
    assert models.unique_key("Ann", ["ann"]) == "ann_2"
    assert models.unique_key("Ann", ["ann", "ann_2"]) == "ann_3"
    assert models.unique_key("Family", []) == "family_2"
    assert models.unique_key("Zoë", []) == "zoe"
    assert models.unique_key("李", []) == "person"


def test_unique_id_migration() -> None:
    old = "['calendar.calendar', 'calendar.someone_example_com']:oscar"
    assert migration.migrated_unique_id(old, "ENTRY") == "ENTRY:oscar"
    assert migration.migrated_unique_id("ENTRY:oscar", "ENTRY") is None
    assert migration.migrated_unique_id("['calendar.x']:any_person", "ENTRY") == "ENTRY:any_person"
    assert migration.migrated_unique_id("['calendar.x']:Not A Key", "ENTRY") is None
    assert migration.migrated_unique_id("garbage", "ENTRY") is None


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
