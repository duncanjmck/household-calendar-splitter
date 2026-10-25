"""Constants for Household Calendar Splitter."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "family_calendar_splitter"

# Config entry options
CONF_SOURCE_CALENDARS = "source_calendars"
CONF_SETTINGS = "settings"
CONF_UNASSIGNED_NAME = "unassigned_name"

# Sub-entry types
SUBENTRY_PERSON = "person"
SUBENTRY_GROUP = "group"

# Form fields
CONF_NAME = "name"
CONF_PEOPLE = "people"
CONF_ALIASES = "aliases"
CONF_ICON = "icon"
CONF_CASE_SENSITIVE = "case_sensitive"
CONF_WORDS = "words"
CONF_EVERYONE = "everyone"
CONF_MEMBERS = "members"
CONF_MODE = "mode"
CONF_JOINER_WORDS = "joiner_words"
CONF_LEADING_WORDS = "leading_words"
CONF_STRIP_NAMES = "strip_names"
CONF_REMOVE_DUPLICATES = "remove_duplicates"

DEFAULT_UNASSIGNED_NAME = "Household events"

UPDATE_INTERVAL = timedelta(minutes=15)
# Window kept in memory and refreshed on the interval above. Requests inside it
# (e.g. a wall display asking for a week back and three ahead) are answered
# instantly.
LOOKBACK = timedelta(days=14)
LOOKAHEAD = timedelta(days=60)
# Requests outside that window are fetched from the sources on demand, and the
# result is cached briefly so several calendars asking at once share one fetch.
RANGE_CACHE_TTL = timedelta(minutes=5)
RANGE_CACHE_SIZE = 8
# Give up on a single source calendar after this long.
SOURCE_TIMEOUT = timedelta(seconds=60)
