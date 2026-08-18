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
"""Unit 5: push copy is a normal segment — translated and exported."""

import io
from unittest.mock import AsyncMock, MagicMock

import openpyxl

from src.translations.briefing_export import build_briefing_xlsx
from src.translations.briefing_service import BriefingService
from src.translations.schema.briefing_model import BriefingSegment


def _service():
    return BriefingService(
        repo=AsyncMock(),
        glossary_repo=AsyncMock(),
        gemini_service=MagicMock(),
        language_config_repo=AsyncMock(),
    )


def _all_cell_values(content: bytes) -> list[str]:
    wb = openpyxl.load_workbook(io.BytesIO(content))
    ws = wb.active
    return [str(c.value) for row in ws.iter_rows() for c in row if c.value]


def test_push_segment_is_translated_not_skipped():
    svc = _service()
    svc.gemini_service.generate_text.return_value = (
        '{"0": "New collection", "1": "Beperkte tijd!"}'
    )
    segments = [
        BriefingSegment(field="Body", label="Body", text="New collection"),
        BriefingSegment(
            block="Push", field="push_copy", label="Push copy",
            text="Limited time!",
        ),
    ]

    out = svc._translate_market(segments, "NL", [])

    assert out[1].text == "Beperkte tijd!"


def test_empty_push_line_is_ignored_gracefully():
    svc = _service()
    svc.gemini_service.generate_text.return_value = '{"0": "New collection"}'
    segments = [
        BriefingSegment(field="Body", label="Body", text="New collection"),
        BriefingSegment(
            block="Push", field="push_copy", label="Push copy", text=""
        ),
    ]

    out = svc._translate_market(segments, "NL", [])

    assert out[1].text == ""  # blank stays blank, no crash


def test_push_segment_round_trips_into_xlsx():
    briefing = {
        "name": "Spring drop",
        "meta": {},
        "segments": [
            {"block": None, "field": "Body", "label": "Body",
             "text": "New collection"},
            {"block": "Push", "field": "push_copy", "label": "Push copy",
             "text": "Limited time!"},
        ],
    }
    translations = [
        {
            "market": "NL",
            "segments": [
                {"field": "Body", "label": "Body", "text": "Nieuwe collectie"},
                {"field": "push_copy", "label": "Push copy",
                 "text": "Beperkte tijd!"},
            ],
        }
    ]

    content = build_briefing_xlsx(briefing, translations)
    values = _all_cell_values(content)

    assert "Push copy" in values
    assert "Limited time!" in values  # source push copy
    assert "Beperkte tijd!" in values  # translated push copy
