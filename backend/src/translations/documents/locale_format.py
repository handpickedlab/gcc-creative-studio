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
"""Deterministic figure and date notation for translated documents.

The model never touches numbers: it is told to reproduce every figure, date
and note reference exactly as written, and QA verifies that it did. Writing
them the way the target market writes them is therefore a separate,
deterministic step — ``319,915`` becomes ``319.915`` in Dutch, ``January 31,
2026`` becomes ``31 januari 2026``.

Two properties matter more than coverage here:

* **A value never changes.** Every rewrite is built from the digits it
  parsed and checked against them afterwards, so the worst case is a figure
  left in English notation — never a figure that reads differently.
* **A cross-reference is never renotated.** "Note 2.19" and "IFRS 16" are
  not quantities. A period-decimal is only converted where the English
  source makes its meaning unambiguous: not in a heading (where "2.19" is
  the section number), not in the shapes a reference takes (see
  `_is_reference`), and not in a locked numeric cell, where a bare "2.19"
  is as likely a note reference as a ratio. Comma-grouped figures
  ("20,913") are unambiguous everywhere — English never groups a reference
  number. The cost of that caution is a decimal here and there left in
  English notation; the alternative is a corrupted cross-reference.

Currency placement (``€1,234`` vs ``€ 1.234``) and all-numeric dates
(``31/01/2026``, ``2026-01-31``) are deliberately left alone: both already
read correctly in the target markets, and both are ambiguous to rewrite.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Thin space before a percent sign and inside French/Nordic figure groups:
# a normal space would let Word break the line in the middle of a number.
NBSP = " "


@dataclass(frozen=True)
class LocaleFormat:
    """How one target market writes figures and dates."""

    thousands: str
    decimal: str
    # Target-language month names, January first.
    months: tuple[str, ...]
    # Templates over {day}, {month}, {year}.
    date: str
    month_year: str
    percent_space: bool = False
    # French writes the first of the month as "1er".
    ordinal_first_day: bool = False


_MONTHS_NL = (
    "januari",
    "februari",
    "maart",
    "april",
    "mei",
    "juni",
    "juli",
    "augustus",
    "september",
    "oktober",
    "november",
    "december",
)
_MONTHS_DE = (
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
)
_MONTHS_FR = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)
_MONTHS_DA = (
    "januar",
    "februar",
    "marts",
    "april",
    "maj",
    "juni",
    "juli",
    "august",
    "september",
    "oktober",
    "november",
    "december",
)
_MONTHS_ES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)
_MONTHS_SV = (
    "januari",
    "februari",
    "mars",
    "april",
    "maj",
    "juni",
    "juli",
    "augusti",
    "september",
    "oktober",
    "november",
    "december",
)
_MONTHS_NB = (
    "januar",
    "februar",
    "mars",
    "april",
    "mai",
    "juni",
    "juli",
    "august",
    "september",
    "oktober",
    "november",
    "desember",
)

# Date conventions per language, reused across that language's markets.
_DUTCH = dict(
    months=_MONTHS_NL, date="{day} {month} {year}", month_year="{month} {year}"
)
_GERMAN = dict(
    months=_MONTHS_DE,
    date="{day}. {month} {year}",
    month_year="{month} {year}",
)
_FRENCH = dict(
    months=_MONTHS_FR,
    date="{day} {month} {year}",
    month_year="{month} {year}",
    ordinal_first_day=True,
)
_DANISH = dict(
    months=_MONTHS_DA,
    date="{day}. {month} {year}",
    month_year="{month} {year}",
)
_SPANISH = dict(
    months=_MONTHS_ES,
    date="{day} de {month} de {year}",
    month_year="{month} de {year}",
)
_SWEDISH = dict(
    months=_MONTHS_SV, date="{day} {month} {year}", month_year="{month} {year}"
)
_NORWEGIAN = dict(
    months=_MONTHS_NB,
    date="{day}. {month} {year}",
    month_year="{month} {year}",
)

# Figure notation per market. English targets (EN, UK) are absent on
# purpose: their notation is the source's, so there is nothing to do.
_FORMATS: dict[str, LocaleFormat] = {
    "NL": LocaleFormat(thousands=".", decimal=",", **_DUTCH),
    "BENL": LocaleFormat(thousands=".", decimal=",", **_DUTCH),
    "DE": LocaleFormat(
        thousands=".", decimal=",", percent_space=True, **_GERMAN
    ),
    "AT": LocaleFormat(
        thousands=".", decimal=",", percent_space=True, **_GERMAN
    ),
    # Switzerland groups with an apostrophe and keeps the decimal point.
    "CHDE": LocaleFormat(
        thousands="'", decimal=".", percent_space=True, **_GERMAN
    ),
    "CHFR": LocaleFormat(
        thousands="'", decimal=".", percent_space=True, **_FRENCH
    ),
    "FR": LocaleFormat(
        thousands=NBSP, decimal=",", percent_space=True, **_FRENCH
    ),
    "BEFR": LocaleFormat(
        thousands=NBSP, decimal=",", percent_space=True, **_FRENCH
    ),
    "LU": LocaleFormat(
        thousands=NBSP, decimal=",", percent_space=True, **_FRENCH
    ),
    "DK": LocaleFormat(
        thousands=".", decimal=",", percent_space=True, **_DANISH
    ),
    "ES": LocaleFormat(
        thousands=".", decimal=",", percent_space=True, **_SPANISH
    ),
    "SE": LocaleFormat(
        thousands=NBSP, decimal=",", percent_space=True, **_SWEDISH
    ),
    "NO": LocaleFormat(
        thousands=NBSP, decimal=",", percent_space=True, **_NORWEGIAN
    ),
}


def for_market(market: str | None) -> LocaleFormat | None:
    """The market's notation, or None when it needs no renotation."""
    return _FORMATS.get(market or "")


# A run of digits held together by figure punctuation: "319,915",
# "1,234,567.89", "2.19", "2026".
_TOKEN = re.compile(r"\d+(?:[.,]\d+)*")

# Text that turns the figure behind it into a reference rather than a
# quantity, including the tail of a list ("Notes 2.19, 2.20 and 2.21").
_REFERENCE = re.compile(
    r"\b(?:notes?|sections?|paragraphs?|articles?|clauses?|appendix|"
    r"annexe?s?|chapters?|pages?|items?|ifrs|ias|ifric|sic)\.?\s*"
    r"(?:\d[\d.,]*\s*(?:,|and|&|to|through|[-–])\s*)*$",
    re.IGNORECASE,
)

_PERCENT = re.compile(r"(?<=\d)%")


def _touches_word(text: str, match: re.Match) -> bool:
    """True when the figure is part of an identifier ("FY2025", "IFRS16")."""
    before = text[match.start() - 1] if match.start() else ""
    after = text[match.end()] if match.end() < len(text) else ""
    return before.isalnum() or after.isalnum()


def _is_reference(text: str, match: re.Match) -> bool:
    """True when a bare decimal reads as a cross-reference, not a quantity.

    Three shapes say "reference" in an English annual report: a reference
    word in front ("see note 2.19"), the figure alone between brackets
    ("Right-of-use assets (2.19)"), and the numbering prefix of a labelled
    paragraph ("2.19 Right-of-use assets") — which Word often renders from
    list numbering without a heading style. Prose that means a quantity
    introduces it ("an amount of 4.6 million") rather than opening with it.
    """
    before, after = text[: match.start()], text[match.end() :]
    if _REFERENCE.search(before):
        return True
    if before.rstrip().endswith("(") and after.lstrip().startswith(")"):
        return True
    return not before.strip() and after[:1].isspace()


def _parse_english_figure(token: str) -> tuple[str, str, bool] | None:
    """``(integer digits, fraction digits, grouped)`` for an English figure.

    None when the token is not an unambiguous English figure: several
    periods (a reference like "2.19.1"), or comma groups that are not
    thousands ("12,34" — a figure already written the continental way).
    """
    parts = token.split(".")
    if len(parts) > 2:
        return None
    integer, fraction = parts[0], parts[1] if len(parts) == 2 else ""
    grouped = "," in integer
    if grouped:
        head, *groups = integer.split(",")
        if not 1 <= len(head) <= 3 or any(len(g) != 3 for g in groups):
            return None
        integer = head + "".join(groups)
    if not integer.isdigit() or not (fraction == "" or fraction.isdigit()):
        return None
    return integer, fraction, grouped


def _render(
    integer: str, fraction: str, *, grouped: bool, fmt: LocaleFormat
) -> str:
    if grouped:
        out = []
        for offset, char in enumerate(reversed(integer)):
            if offset and offset % 3 == 0:
                out.append(fmt.thousands)
            out.append(char)
        integer = "".join(reversed(out))
    return f"{integer}{fmt.decimal}{fraction}" if fraction else integer


def _same_value(before: str, after: str) -> bool:
    """A renotation may move separators around, never digits."""
    return re.sub(r"\D", "", before) == re.sub(r"\D", "", after)


def number_plan(
    text: str, fmt: LocaleFormat, *, conservative: bool = False
) -> dict[str, str]:
    """Maps the figures in `text` to how the target market writes them.

    Figures whose English reading is not unambiguous are left out, so
    applying a plan can never renotate a cross-reference. `conservative`
    (headings, locked numeric cells) restricts the plan to comma-grouped
    figures, the only shape that cannot be a reference number.
    """
    plan: dict[str, str] = {}
    for match in _TOKEN.finditer(text):
        token = match.group()
        if token in plan or _touches_word(text, match):
            continue
        parsed = _parse_english_figure(token)
        if parsed is None:
            continue
        integer, fraction, grouped = parsed
        if not grouped:
            # A plain integer ("2026", "16") reads the same everywhere.
            if not fraction:
                continue
            if conservative or _is_reference(text, match):
                continue
        localised = _render(integer, fraction, grouped=grouped, fmt=fmt)
        if localised != token and _same_value(token, localised):
            plan[token] = localised
    return plan


def apply_plan(text: str, plan: dict[str, str]) -> str:
    """Rewrites whole figures of `text` that the plan covers."""
    if not plan:
        return text

    def swap(match: re.Match) -> str:
        token = match.group()
        if _touches_word(text, match):
            return token
        return plan.get(token, token)

    return _TOKEN.sub(swap, text)


_EN_MONTHS = (
    ("january", "jan"),
    ("february", "feb"),
    ("march", "mar"),
    ("april", "apr"),
    ("may",),
    ("june", "jun"),
    ("july", "jul"),
    ("august", "aug"),
    ("september", "sept", "sep"),
    ("october", "oct"),
    ("november", "nov"),
    ("december", "dec"),
)
_MONTH_INDEX = {
    name: index
    for index, names in enumerate(_EN_MONTHS)
    for name in names
}
_MONTH_ALTERNATION = "|".join(
    sorted(_MONTH_INDEX, key=len, reverse=True)
)

_DAY = r"(\d{1,2})(?:st|nd|rd|th)?"
_MONTH = rf"({_MONTH_ALTERNATION})\.?"
_YEAR = r"(\d{4})"

_MONTH_FIRST = re.compile(
    rf"\b{_MONTH}\s+{_DAY},?\s+{_YEAR}\b", re.IGNORECASE
)
_DAY_FIRST = re.compile(
    rf"\b{_DAY}\s+{_MONTH},?\s+{_YEAR}\b", re.IGNORECASE
)
_MONTH_YEAR = re.compile(rf"\b{_MONTH}\s+{_YEAR}\b", re.IGNORECASE)


def _month_name(english: str, fmt: LocaleFormat) -> str:
    return fmt.months[_MONTH_INDEX[english.lower().rstrip(".")]]


def _format_date(day: str, month: str, year: str, fmt: LocaleFormat) -> str:
    number = str(int(day))
    if fmt.ordinal_first_day and int(day) == 1:
        number = "1er"
    return fmt.date.format(
        day=number, month=_month_name(month, fmt), year=year
    )


def localise_dates(text: str, fmt: LocaleFormat) -> str:
    """Rewrites English month-name dates into the target language.

    Only dates spelled with an English month name are touched, which makes
    the reading unambiguous and the pass idempotent: once rewritten, the
    target month name no longer matches.
    """
    out = _MONTH_FIRST.sub(
        lambda m: _format_date(m.group(2), m.group(1), m.group(3), fmt), text
    )
    out = _DAY_FIRST.sub(
        lambda m: _format_date(m.group(1), m.group(2), m.group(3), fmt), out
    )
    return _MONTH_YEAR.sub(
        lambda m: fmt.month_year.format(
            month=_month_name(m.group(1), fmt), year=m.group(2)
        ),
        out,
    )


def _localise_percent(text: str, fmt: LocaleFormat) -> str:
    if not fmt.percent_space:
        return text
    return _PERCENT.sub(f"{NBSP}%", text)


def localise_translation(
    source: str,
    translation: str,
    fmt: LocaleFormat,
    *,
    conservative: bool = False,
) -> str:
    """Renotates a translation, deciding on the English source.

    Which figures are quantities is legible in the source ("see note 2.19")
    and not always in the translation, so the plan is read there and then
    applied to the translation. Figures the model or a reviewer already
    localised simply are not in the plan, which makes this safe to run over
    hand-edited text.
    """
    out = apply_plan(
        translation, number_plan(source, fmt, conservative=conservative)
    )
    return _localise_percent(localise_dates(out, fmt), fmt)


def localise_locked(text: str, fmt: LocaleFormat) -> str:
    """Renotates a locked numeric cell, which is never translated.

    The cell holds figures and nothing else — a month name would have made
    it prose — so only grouping, decimals and percent spacing apply.
    """
    out = apply_plan(text, number_plan(text, fmt, conservative=True))
    return _localise_percent(out, fmt)
