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
"""Unit 2: per-language profile + Notes injected into the prompt."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.translations import localization
from src.translations.briefing_service import BriefingService
from src.translations.dto.briefing_dto import BriefingInputDto
from src.translations.schema.briefing_model import BriefingMeta, BriefingSegment
from src.translations.schema.glossary_term_model import GlossaryTermModel
from src.translations.schema.language_config_model import (
    FormalityEnum,
    TranslationLanguageConfigModel,
)


def test_formality_instruction_formal_mentions_vous():
    line = localization.formality_instruction("formal")
    assert line and "FORMAL" in line and "vous" in line


def test_formality_instruction_informal_mentions_tu():
    line = localization.formality_instruction("informal")
    assert line and "INFORMAL" in line and "tu" in line


def test_formality_instruction_default_is_none():
    assert localization.formality_instruction("default") is None
    assert localization.formality_instruction(None) is None


def _service():
    return BriefingService(
        repo=AsyncMock(),
        glossary_repo=AsyncMock(),
        gemini_service=MagicMock(),
        language_config_repo=AsyncMock(),
    )


def _term(source, target=None, do_not_translate=False):
    return GlossaryTermModel(
        id=1,
        language="FR",
        source=source,
        target=target or source,
        do_not_translate=do_not_translate,
    )


def test_build_market_prompt_includes_all_profile_signals():
    svc = _service()
    profile = TranslationLanguageConfigModel(
        language="FR",
        formality=FormalityEnum.FORMAL,
        guidance="Luxe, elegant, understated tone.",
    )
    segments = [
        BriefingSegment(field="Body", label="Body", text="Shop the collection")
    ]
    prompt = svc._build_market_prompt(
        segments,
        "FR",
        glossary=[_term("sale", target="soldes")],
        do_not_translate=[_term("cashmere", do_not_translate=True)],
        profile=profile,
        notes="Spring 2026 launch, keep it premium.",
    )

    assert "French (France)" in prompt  # language label from markets.py
    assert "vous" in prompt  # formality register
    assert "Luxe, elegant" in prompt  # free-text guidance
    assert "Spring 2026 launch" in prompt  # R6 notes wired in
    assert "cashmere" in prompt  # do-not-translate block
    assert "soldes" in prompt  # normal glossary block
    assert "ALL CAPS" in prompt  # casing rule hint


def test_build_market_prompt_neutral_without_profile():
    svc = _service()
    segments = [BriefingSegment(field="Body", label="Body", text="Hello")]
    prompt = svc._build_market_prompt(segments, "NL", glossary=[])
    # No formality line leaks when there is no profile.
    assert "FORMAL register" not in prompt
    assert "INFORMAL register" not in prompt


@pytest.mark.anyio
async def test_translate_briefing_uses_distinct_profile_per_market():
    svc = _service()
    svc.glossary_repo.get_by_languages = AsyncMock(return_value=[])
    svc.language_config_repo.get_by_languages = AsyncMock(
        return_value={
            "FR": TranslationLanguageConfigModel(
                language="FR", formality=FormalityEnum.FORMAL
            ),
            "DE": TranslationLanguageConfigModel(
                language="DE", formality=FormalityEnum.INFORMAL
            ),
        }
    )

    prompts: list[str] = []

    def fake_generate(prompt, *args, **kwargs):
        prompts.append(prompt)
        return '{"0": "traduction"}'

    svc.gemini_service.generate_text.side_effect = fake_generate

    briefing = BriefingInputDto(
        name="Campaign",
        meta=BriefingMeta(notes="Spring launch"),
        segments=[
            BriefingSegment(field="Body", label="Body", text="New collection")
        ],
    )

    results = await svc.translate_briefing(briefing, ["FR", "DE"])

    assert {r.market for r in results} == {"FR", "DE"}
    assert len(prompts) == 2
    fr_prompt = next(p for p in prompts if "French (France)" in p)
    de_prompt = next(p for p in prompts if "German (Germany)" in p)
    assert "vous" in fr_prompt  # FR formal
    assert "du" in de_prompt  # DE informal
    # R6: Notes reaches every market prompt.
    assert all("Spring launch" in p for p in prompts)


@pytest.mark.anyio
async def test_translate_briefing_skips_source_market():
    svc = _service()
    svc.glossary_repo.get_by_languages = AsyncMock(return_value=[])
    svc.language_config_repo.get_by_languages = AsyncMock(return_value={})
    svc.gemini_service.generate_text.return_value = '{"0": "x"}'

    briefing = BriefingInputDto(
        name="Campaign",
        segments=[BriefingSegment(field="Body", label="Body", text="Hi")],
    )

    results = await svc.translate_briefing(briefing, ["EN", "NL"])

    assert [r.market for r in results] == ["NL"]
