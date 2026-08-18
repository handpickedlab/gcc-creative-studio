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

"""Stateless localization helpers shared by both translation entry points.

The briefing flow (`briefing_service`) and the legacy free-text path
(`translation_service`) both build Gemini prompts and post-process casing. These
pure helpers keep that behavior consistent between them: formality register
instructions, ALL-CAPS detection/preservation, and splitting glossary terms into
normal hints vs. do-not-translate (verbatim) names.
"""

import re

from src.translations.schema.language_config_model import FormalityEnum

# Cap on how many glossary hints we inject into a single prompt.
MAX_GLOSSARY_HINTS = 60


def formality_instruction(formality: str | None) -> str | None:
    """Language-agnostic register instruction from a formality setting.

    Returns None for `default`/unknown so the language's natural register
    stands (e.g. English, Scandinavian languages without a clean split).
    """
    if formality == FormalityEnum.FORMAL.value:
        return (
            "- Address the reader using the FORMAL register for the target "
            "language (e.g. vous in French, Sie in German, u in Dutch)."
        )
    if formality == FormalityEnum.INFORMAL.value:
        return (
            "- Address the reader using the INFORMAL register for the "
            "target language (e.g. tu in French, du in German, je in Dutch)."
        )
    return None


def is_all_caps_source(text: str) -> bool:
    """True when the source is a fully-uppercase line (typical of CTAs).

    HTML tags and [placeholders] are ignored; there must be at least one cased
    letter and no lowercase letter among the remaining text.
    """
    stripped = re.sub(r"<[^>]+>", "", text)
    stripped = re.sub(r"\[[^\]]+\]", "", stripped)
    letters = [c for c in stripped if c.isalpha()]
    if not letters:
        return False
    return all(c.isupper() for c in letters)


def apply_caps(source: str, translated: str) -> str:
    """Uppercase `translated` when `source` was an all-caps line (R3)."""
    if translated and is_all_caps_source(source):
        return translated.upper()
    return translated


def split_glossary_terms(
    terms: list, text: str, limit: int = MAX_GLOSSARY_HINTS
) -> tuple[list, list]:
    """Splits matching glossary terms into (normal, do-not-translate).

    A term matches when its `source` appears in `text` on a word boundary (not
    a naive substring), which avoids short/generic terms false-matching inside
    unrelated words. Terms flagged `do_not_translate` go into the second list.
    """
    normal, dnt = [], []
    for t in terms:
        source = getattr(t, "source", None)
        if not source:
            continue
        if not re.search(rf"\b{re.escape(source)}\b", text, re.I):
            continue
        target = dnt if getattr(t, "do_not_translate", False) else normal
        target.append(t)
    return normal[:limit], dnt[:limit]
