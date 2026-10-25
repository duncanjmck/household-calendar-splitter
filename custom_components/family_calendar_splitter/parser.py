"""Deterministically assign family calendar events without changing their meaning.

Pure Python: depends only on ``models`` so it can be tested without Home
Assistant.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from .models import Household, MatchMode

# Characters that separate a name from the rest of a title, e.g. "Oscar - swim"
# or "Boys: footy". Only removed when they touch a recognised name.
_SEPARATORS = r"[-–—:;,|]"
# Symbols that always join several names: "Oscar, Felix & Rose", "Oscar/Felix".
_JOINER_SYMBOLS = (",", "&", "+", "/")
# Straight and typographic apostrophes count as part of a word, so "O'Neil"
# never matches "Neil" and "Oscar's" is the possessive of "Oscar".
_APOSTROPHES = "'’"
_POSSESSIVE = re.compile(rf"[{_APOSTROPHES}]s$", re.IGNORECASE)

_SENTINEL = "\x00"


@dataclass(frozen=True, slots=True)
class ParsedTitle:
    """A source event title assigned to one or more people."""

    people: tuple[str, ...]
    summary: str


def _words(words: tuple[str, ...]) -> str:
    return "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))


class TitleMatcher:
    """Classify event titles for one household."""

    def __init__(self, household: Household) -> None:
        self.household = household
        self.settings = household.settings

        self._exact: dict[str, tuple[str, ...]] = {}
        self._folded: dict[str, tuple[str, ...]] = {}
        alternatives: list[tuple[str, str]] = []
        for term, targets, case_sensitive in household.iter_terms():
            if case_sensitive:
                self._exact[term] = targets
                alternatives.append((term, rf"(?-i:{re.escape(term)})"))
            else:
                self._folded[term.casefold()] = targets
                alternatives.append((term, re.escape(term)))
        alternatives.sort(key=lambda item: len(item[0]), reverse=True)

        # The alternation MUST be grouped, otherwise the boundary assertions
        # only apply to the first and last alternatives.
        name = (
            rf"(?<![\w{_APOSTROPHES}])(?:{'|'.join(alt for _, alt in alternatives)})"
            rf"(?:[{_APOSTROPHES}]s)?(?![\w{_APOSTROPHES}])"
        )
        joiner_parts = [re.escape(s) for s in _JOINER_SYMBOLS]
        if self.settings.joiner_words:
            joiner_parts.append(rf"\b(?:{_words(self.settings.joiner_words)})\b")
        joiner = rf"\s*(?:{'|'.join(joiner_parts)})\s*"
        run = rf"{name}(?:{joiner}{name})*"
        leading = (
            rf"(?:\b(?:{_words(self.settings.leading_words)})\s+)?"
            if self.settings.leading_words
            else ""
        )

        flags = re.IGNORECASE
        self._name = re.compile(name, flags)
        self._anywhere = re.compile(rf"{leading}{run}", flags)
        self._leading = re.compile(rf"^\s*{run}", flags)
        self._tag_prefix = re.compile(rf"^\s*{run}\s*:", flags)
        self._tag_bracket = re.compile(rf"\[\s*{run}\s*\]", flags)
        # The sentinel left by a removed name, plus separators touching it.
        self._hole = re.compile(
            rf"(?P<left>\s*{_SEPARATORS}*\s*){_SENTINEL}(?P<right>\s*{_SEPARATORS}*\s*)"
        )

    # ----- matching ------------------------------------------------------

    def _targets(self, token: str) -> tuple[str, ...]:
        token = _POSSESSIVE.sub("", token)
        if token in self._exact:
            return self._exact[token]
        return self._folded.get(token.casefold(), ())

    def _spans(self, title: str) -> list[re.Match[str]]:
        mode = self.settings.mode
        if mode is MatchMode.ANYWHERE:
            return list(self._anywhere.finditer(title))
        if mode is MatchMode.LEADING:
            match = self._leading.match(title)
            return [match] if match else []
        spans = list(self._tag_bracket.finditer(title))
        prefix = self._tag_prefix.match(title)
        if prefix and not any(s.start() < prefix.end() for s in spans):
            spans.insert(0, prefix)
        return spans

    def parse(self, title: str) -> ParsedTitle | None:
        """Extract known people and produce a clean, readable derived title.

        Only separators and connectors directly attached to a recognised name
        are removed; everything else in the title is kept verbatim. The
        original title is kept when removing the names would leave nothing
        meaningful, or when name stripping is turned off.
        """
        spans = self._spans(title)
        people: list[str] = []
        for span in spans:
            for match in self._name.finditer(span.group(0)):
                for person in self._targets(match.group(0)):
                    if person not in people:
                        people.append(person)
        if not people:
            return None
        if not self.settings.strip_names:
            return ParsedTitle(tuple(people), title.strip())

        pieces: list[str] = []
        last = 0
        for span in spans:
            pieces.append(title[last : span.start()])
            pieces.append(_SENTINEL)
            last = span.end()
        pieces.append(title[last:])
        remainder = "".join(pieces)

        def close_hole(match: re.Match[str]) -> str:
            if match.start() == 0 or match.end() == len(remainder):
                return ""
            left = match.group("left").strip()
            right = match.group("right").strip()
            # "Swim - Oscar - 4pm" -> "Swim - 4pm": keep one separator when
            # the name sat between two of them.
            return f" {left[0]} " if left and right else " "

        previous = None
        while previous != remainder:
            previous = remainder
            remainder = self._hole.sub(close_hole, remainder, count=1)

        remainder = re.sub(r"\s+", " ", remainder).strip()
        remainder = re.sub(rf"^(?:{_SEPARATORS}|\s)+|(?:{_SEPARATORS}|\s)+$", "", remainder)
        summary = remainder if re.search(r"\w", remainder) else title.strip()
        return ParsedTitle(tuple(people), summary)
