# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Turns the corpus's free-text periods into one sortable key.

Extraction records a claim's period exactly as the slide phrased it, which
across this corpus means 2,749 distinct spellings: bare years, ``Q2 2025``,
``H2 2022``, ``HY1 2024``, ``P10 2024`` and ``2025 P1`` (Hunkemöller's
12-period retail calendar, both word orders), ``OCT 2025``/``Oct 2025``/
``October 2025``, ranges like ``January-February 2025`` and ``August 22 -
September 5, 2025``, and relative phrases like ``past 12 months``. Nothing
can be ordered or compared in that state, so "what is the most recent NPS"
is unanswerable — it returned 2023 figures.

Everything resolvable becomes ``YYYY-MM``, zero-padded so plain string
comparison orders it correctly, with ``MM = 00`` meaning "that year, no finer
granularity". A range collapses to its START. Relative phrases with no date
anywhere resolve to ``None`` on purpose: they name a span relative to an
unknown writing date, so inventing a point in time would fabricate
precision — but one that does name an anchor ("Last 12 months ending 28
September 2025") files under that anchor.

The retail-period mapping ``Pn -> month n`` is an approximation — HKM periods
are four-weekly, so they drift against calendar months — but it is monotonic,
which is all the ordering needs. The original text is always kept alongside
the key, so nothing here is ever shown to a user as fact.
"""

import re

# Sentinel month for "whole year, no finer granularity".
_YEAR_ONLY = 0

_MONTHS = {
    "jan": 1, "january": 1, "januari": 1,
    "feb": 2, "february": 2, "februari": 2,
    "mar": 3, "march": 3, "maart": 3, "mrt": 3,
    "apr": 4, "april": 4,
    "may": 5, "mei": 5,
    "jun": 6, "june": 6, "juni": 6,
    "jul": 7, "july": 7, "juli": 7,
    "aug": 8, "august": 8, "augustus": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "okt": 10, "oktober": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

# Phrases that describe a span relative to an unstated "now". Deliberately
# unresolvable: the writing date is not recorded per claim.
_RELATIVE = re.compile(
    r"\b(next|past|last|coming|previous|upcoming|recent|forward|"
    r"komende|afgelopen|vorige|laatste)\b",
    re.IGNORECASE,
)

_YEAR = r"(?:19|20)\d{2}"
# A year written in full, or shortened as "'24" / "-24" as the decks do
# ("Q1'24", "P4-24"). Bare two-digit numbers are NOT accepted: "P4 24" is
# far more likely to be a page or sample number than a year.
_YEAR_LOOSE = rf"(?:{_YEAR}|(?<=['\-])\d{{2}})"

# Order matters: the most specific spelling that matches wins.
_RETAIL_PERIOD = re.compile(
    rf"\bP\s?(?P<n>[1-9]|1[0-2])\b['\-\s/,]*(?P<year>{_YEAR_LOOSE})"
    rf"|(?P<year2>{_YEAR})[\s\-/,]*\bP\s?(?P<n2>[1-9]|1[0-2])\b",
    re.IGNORECASE,
)
_QUARTER = re.compile(
    rf"\bQ\s?(?P<n>[1-4])\b['\-\s/,]*(?P<year>{_YEAR_LOOSE})"
    rf"|\b(?P<n2>[1-4])\s?Q\b['\-\s/,]*(?P<year2>{_YEAR_LOOSE})"
    rf"|(?P<year3>{_YEAR})[\s\-/,]*\bQ\s?(?P<n3>[1-4])\b",
    re.IGNORECASE,
)
_HALF = re.compile(
    rf"\b(?:H|HY|HJ)\s?(?P<n>[12])\b['\-\s/,]*(?P<year>{_YEAR_LOOSE})"
    rf"|(?P<year2>{_YEAR})[\s\-/,]*\b(?:H|HY|HJ)\s?(?P<n2>[12])\b",
    re.IGNORECASE,
)
# Bare granularity, no year in sight ("P10", "Q3") — resolvable only against
# the document's own vintage year.
_BARE_RETAIL_PERIOD = re.compile(r"^\s*P\s?([1-9]|1[0-2])\s*$", re.IGNORECASE)
_BARE_QUARTER = re.compile(r"^\s*Q\s?([1-4])\s*$", re.IGNORECASE)
_MONTH_WORD = re.compile(r"[A-Za-z]{3,9}")
_NUMERIC_DATE = re.compile(
    r"\b(?P<day>0?[1-9]|[12]\d|3[01])[-/.](?P<month>0?[1-9]|1[0-2])"
    r"[-/.](?P<year>(?:19|20)\d{2}|\d{2})\b",
)
_COMPACT_DATE = re.compile(
    r"\b(?P<year>(?:19|20)\d{2})(?P<month>0[1-9]|1[0-2])"
    r"(?P<day>0[1-9]|[12]\d|3[01])\b",
)
_ANY_YEAR = re.compile(_YEAR)


def _key(year: int, month: int) -> str:
    """The sortable form: zero-padded ``YYYY-MM``."""
    return f"{year:04d}-{month:02d}"


def _two_digit_year(raw: str) -> int:
    """Expands a 2-digit year, assuming this century for 00-79."""
    value = int(raw)
    if len(raw) == 4:
        return value
    return 2000 + value if value < 80 else 1900 + value


def normalize_period(
    raw: str | None,
    default_year: int | None = None,
) -> str | None:
    """Maps a free-text period onto a sortable ``YYYY-MM`` key.

    ``default_year`` supplies the year for text that names a granularity but
    no year — a satisfaction deck's slide says just "P10" because the whole
    deck is the 2024 edition. Pass the document's vintage year and those
    resolve; without it they stay None.

    Returns None when the text names no resolvable point in time: a relative
    phrase ("past 12 months"), or a granularity with no year available from
    either the text or ``default_year``.
    """
    if not raw:
        return None
    text = raw.strip()
    if not text:
        return None
    # A relative phrase with no year anywhere is unresolvable ("past 2
    # years"). One that names an anchor date is not: "Last 12 months ending
    # 28 September 2025" files under that anchor, since an anchored window is
    # normally reported by the date it ends on.
    if _RELATIVE.search(text) and not _ANY_YEAR.search(text):
        return None

    # Explicit dates first: they are the least ambiguous, and a caption may
    # also carry an unrelated year further along.
    if m := _COMPACT_DATE.search(text):
        return _key(int(m.group("year")), int(m.group("month")))
    if m := _NUMERIC_DATE.search(text):
        return _key(
            _two_digit_year(m.group("year")), int(m.group("month"))
        )

    if m := _RETAIL_PERIOD.search(text):
        n = m.group("n") or m.group("n2")
        year = m.group("year") or m.group("year2")
        return _key(_two_digit_year(year), int(n))
    if m := _QUARTER.search(text):
        n = m.group("n") or m.group("n2") or m.group("n3")
        year = m.group("year") or m.group("year2") or m.group("year3")
        return _key(_two_digit_year(year), (int(n) - 1) * 3 + 1)
    if m := _HALF.search(text):
        n = m.group("n") or m.group("n2")
        year = m.group("year") or m.group("year2")
        return _key(_two_digit_year(year), 1 if int(n) == 1 else 7)

    # Month names: pair the LEFTMOST one with the year, so a range collapses
    # to its start ("24 January and 7 February 2025" -> January 2025).
    years = [int(y) for y in _ANY_YEAR.findall(text)]
    months = [
        _MONTHS[w.group().lower()]
        for w in _MONTH_WORD.finditer(text)
        if w.group().lower() in _MONTHS
    ]
    year = max(years) if years else default_year
    if months and year:
        return _key(year, months[0])

    # Nothing finer than a year: take the LATEST year mentioned, so a
    # retrospective ("1975 versus 2025") dates as the year it was written.
    if years:
        return _key(max(years), _YEAR_ONLY)

    # A bare granularity, dated by the document it came from.
    if default_year:
        if m := _BARE_RETAIL_PERIOD.match(text):
            return _key(default_year, int(m.group(1)))
        if m := _BARE_QUARTER.match(text):
            return _key(default_year, (int(m.group(1)) - 1) * 3 + 1)
    return None


def label_for_key(key: str | None) -> str | None:
    """A short human label for a key, e.g. ``2024-10`` -> ``October 2024``."""
    if not key:
        return None
    try:
        year, month = key.split("-")
        year_i, month_i = int(year), int(month)
    except (ValueError, AttributeError):
        return None
    if month_i == _YEAR_ONLY:
        return str(year_i)
    names = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ]
    if 1 <= month_i <= 12:
        return f"{names[month_i - 1]} {year_i}"
    return str(year_i)


def parse_filename_vintage(filename: str) -> str | None:
    """The document's own vintage, read from its filename.

    The corpus names files consistently enough for this to be reliable
    ("Customer Satisfaction Survey - P10 2024.pptx", "Beauty market - Desk
    research 9-1-2025.pptx", "Euromonitor - Consumer types may 2026.ppt"),
    and it is the only per-document date the pipeline can know without
    trusting the upload time — which says when someone dragged the file in,
    not what the file is about.
    """
    if not filename:
        return None
    stem = filename.rsplit(".", 1)[0]
    # Underscores are word separators in several exports
    # ("The_State_of_Fashion_2024").
    return normalize_period(stem.replace("_", " "))
