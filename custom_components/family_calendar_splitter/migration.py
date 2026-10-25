"""Pure helpers for config entry migrations (no Home Assistant imports)."""

from __future__ import annotations

import re

_KEY_RE = re.compile(r"^[a-z0-9_]+$")


def migrated_unique_id(old_unique_id: str, entry_id: str) -> str | None:
    """Map a v1 unique ID to the v2 format, or return None if no change applies.

    v1 IDs were ``"<str(list of source calendars)>:<calendar key>"``, which
    changed whenever the source calendars changed. v2 IDs are
    ``"<config entry id>:<calendar key>"``.
    """
    prefix, sep, key = old_unique_id.rpartition(":")
    if not sep or not prefix.startswith("[") or not _KEY_RE.match(key):
        return None
    return f"{entry_id}:{key}"
