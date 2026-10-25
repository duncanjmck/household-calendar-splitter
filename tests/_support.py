"""Shared test helpers. Loads the integration's pure modules without Home Assistant."""

from __future__ import annotations

import importlib
from pathlib import Path
import sys
import types

_PKG_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "family_calendar_splitter"
_pkg = types.ModuleType("hcs_under_test")
_pkg.__path__ = [str(_PKG_DIR)]
sys.modules.setdefault("hcs_under_test", _pkg)


def load(name: str):
    """Import one of the integration's modules, e.g. load("parser")."""
    return importlib.import_module(f"hcs_under_test.{name}")


# A fictional household used throughout the tests.
SAMPLE_HOUSEHOLD: dict = {
    "people": [
        {"key": "oscar", "name": "Oscar", "aliases": ["Ozzie"]},
        {"key": "felix", "name": "Felix"},
        {"key": "isla", "name": "Isla", "aliases": ["Izzy", "Isa"]},
        {"key": "rose", "name": "Rose"},
        {"key": "tom", "name": "Tom"},
    ],
    "groups": [
        {"aliases": ["boys"], "members": ["oscar", "felix"]},
        {"aliases": ["everyone"], "members": None},
    ],
    "settings": {"mode": "anywhere"},
}
