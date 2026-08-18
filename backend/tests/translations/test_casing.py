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
"""Unit 3: preserve ALL-CAPS CTAs (deterministic post-process)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.translations import localization
from src.translations.briefing_service import BriefingService
from src.translations.schema.briefing_model import BriefingSegment
from src.translations.schema.language_config_model import (
    TranslationLanguageConfigModel,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("SHOP NOW", True),  # classic all-caps CTA
        ("Shop now", False),  # mixed case
        ("shop now", False),  # lower case
        ("SHOP [Name]", True),  # placeholder ignored, rest is caps
        ("<b>SHOP NOW</b>", True),  # html tags ignored
        ("Shop <b>NOW</b>", False),  # a lowercase letter remains
        ("123 !!! [X]", False),  # no cased letters at all
        ("", False),  # empty
    ],
)
def test_is_all_caps_source(text, expected):
    assert localization.is_all_caps_source(text) is expected


def test_apply_caps_uppercases_when_source_all_caps():
    assert localization.apply_caps("SHOP NOW", "jetzt shoppen") == "JETZT SHOPPEN"


def test_apply_caps_leaves_mixed_case_untouched():
    assert localization.apply_caps("Shop now", "Jetzt shoppen") == "Jetzt shoppen"


def test_apply_caps_handles_empty_translation():
    # Never crash on an empty model result.
    assert localization.apply_caps("SHOP NOW", "") == ""


def _service():
    return BriefingService(
        repo=AsyncMock(),
        glossary_repo=AsyncMock(),
        gemini_service=MagicMock(),
        language_config_repo=AsyncMock(),
    )


def test_translate_market_forces_caps_on_cta():
    svc = _service()
    svc.gemini_service.generate_text.return_value = '{"0": "jetzt shoppen"}'
    segs = [BriefingSegment(field="CTA", label="CTA", text="SHOP NOW")]

    out = svc._translate_market(segs, "DE", [])

    assert out[0].text == "JETZT SHOPPEN"


def test_translate_market_respects_preserve_casing_off():
    svc = _service()
    svc.gemini_service.generate_text.return_value = '{"0": "jetzt shoppen"}'
    segs = [BriefingSegment(field="CTA", label="CTA", text="SHOP NOW")]
    profile = TranslationLanguageConfigModel(
        language="DE", preserve_casing=False
    )

    out = svc._translate_market(segs, "DE", [], profile)

    assert out[0].text == "jetzt shoppen"
