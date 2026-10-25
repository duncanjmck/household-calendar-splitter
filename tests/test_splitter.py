"""Tests for splitting and de-duplication. No Home Assistant install required.

Run with ``pytest tests`` or ``python tests/test_splitter.py``.
"""

from __future__ import annotations

from datetime import date
import hashlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _support import SAMPLE_HOUSEHOLD, load  # noqa: E402

splitter = load("splitter")
parser = load("parser")
models = load("models")

MATCHER = parser.TitleMatcher(models.Household.from_dict(SAMPLE_HOUSEHOLD))
A, B = "calendar.tom_google", "calendar.isla_google"


def ev(summary, start="2026-10-26T10:00:00+10:30", end="2026-10-26T11:00:00+10:30", **extra):
    return {"summary": summary, "start": start, "end": end, **extra}


def counts(split):
    return {k: len(v) for k, v in sorted(split.items())}


def test_same_event_on_both_sources_kept_once_per_person() -> None:
    raw = {A: [ev("Felix - dentist")], B: [ev("Felix - dentist")]}
    assert counts(splitter.split_events(raw, MATCHER)) == {"felix": 1}


def test_two_person_event_stays_two_events() -> None:
    # The frame shows pairs side by side, one per person: that must survive.
    raw = {A: [ev("Oscar and Felix - swim")], B: [ev("Oscar and Felix - swim")]}
    split = splitter.split_events(raw, MATCHER)
    assert counts(split) == {"felix": 1, "oscar": 1}
    assert split["oscar"][0].summary == split["felix"][0].summary == "swim"


def test_everyone_and_unassigned_duplicates() -> None:
    raw = {A: [ev("Everyone - beach"), ev("Bin night")], B: [ev("Everyone - beach"), ev("Bin night")]}
    split = splitter.split_events(raw, MATCHER)
    assert counts(split) == {"tom": 1, "isla": 1, "family": 1, "felix": 1, "oscar": 1, "rose": 1}


def test_only_true_duplicates_are_removed() -> None:
    raw = {
        A: [ev("Felix - dentist")],
        B: [
            ev("Felix - dentist", start="2026-10-26T10:30:00+10:30"),  # different time
            ev("Felix - dentist", location="Clinic B"),  # different place
            ev("felix -   DENTIST"),  # same after normalising case/space
        ],
    }
    assert counts(splitter.split_events(raw, MATCHER)) == {"felix": 3}


def test_duplicate_keeps_first_but_fills_missing_description() -> None:
    raw = {A: [ev("Rose - ballet")], B: [ev("Rose - ballet", description="Bring shoes")]}
    (kept,) = splitter.split_events(raw, MATCHER)["rose"]
    assert kept.source == A and kept.description == "Bring shoes"


def test_duplicates_can_be_kept() -> None:
    raw = {A: [ev("Felix - dentist")], B: [ev("Felix - dentist")]}
    split = splitter.split_events(raw, MATCHER, remove_duplicates=False)
    assert counts(split) == {"felix": 2}


def test_all_day_and_malformed_events() -> None:
    raw = {
        A: [
            ev("Oscar's birthday", start="2026-10-27", end="2026-10-28"),
            {"summary": "no times"},
            ev("bad", start="not a date"),
            "not a mapping",
        ]
    }
    split = splitter.split_events(raw, MATCHER)
    assert counts(split) == {"oscar": 1}
    assert split["oscar"][0].start == date(2026, 10, 27)
    assert split["oscar"][0].summary == "birthday"


def test_uid_unchanged_from_earlier_versions() -> None:
    event = ev("Felix - dentist")
    material = "\x1f".join((A, "felix", event["summary"], event["start"], event["end"]))
    (kept,) = splitter.split_events({A: [event]}, MATCHER)["felix"]
    assert kept.uid == hashlib.sha256(material.encode()).hexdigest()


def test_settings_round_trip_includes_remove_duplicates() -> None:
    settings = models.MatchSettings.from_dict({"remove_duplicates": False})
    assert settings.remove_duplicates is False
    assert models.MatchSettings.from_dict(settings.to_dict()) == settings
    assert models.MatchSettings.from_dict({}).remove_duplicates is True


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
