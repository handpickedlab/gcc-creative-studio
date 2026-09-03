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
"""Tests for translation memory: keying, reuse estimates and prefill."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.translations.documents import memory as tm
from src.translations.documents.dto.document_translation_dto import (
    StartTranslationDto,
    UpdateSegmentDto,
)
from src.translations.documents.schema.document_translation_model import (
    DocumentTranslationJobModel,
    DocumentTranslationSegmentModel,
)
from src.translations.documents.service import DocumentTranslationService


class TestKeying:
    def test_whitespace_differences_still_match(self):
        a = "The Group recognised an impairment of EUR 1,234."
        b = "The Group  recognised an\nimpairment of EUR 1,234."
        assert tm.source_hash(a) == tm.source_hash(b)

    def test_non_breaking_space_matches_a_plain_space(self):
        assert tm.source_hash("EUR\xa01,234") == tm.source_hash("EUR 1,234")

    def test_case_is_significant(self):
        assert tm.source_hash("TOTAL ASSETS") != tm.source_hash("Total assets")

    def test_different_wording_does_not_match(self):
        assert tm.source_hash("Total assets") != tm.source_hash("Total equity")


def _segment(index: int, text: str, **overrides):
    defaults = dict(
        id=index + 1,
        job_id="job-1",
        seg_index=index,
        kind="prose",
        source_text=text,
        status="pending",
    )
    defaults.update(overrides)
    return DocumentTranslationSegmentModel(**defaults)


def _service(rows):
    jobs = AsyncMock()
    segments = AsyncMock()
    segments.find_by_job.return_value = rows
    memory = AsyncMock()
    gcs = MagicMock()
    gcs.bucket_name = "test-bucket"
    service = DocumentTranslationService(
        jobs=jobs, segments=segments, memory=memory, gcs=gcs
    )
    jobs.get_by_id.return_value = DocumentTranslationJobModel(
        id="job-1",
        filename="FS 2025-2026.docx",
        status="uploaded",
        target_market="NL",
    )
    # Re-checking an edited segment reads the market's glossary through its
    # own session; these tests are about memory, not terminology.
    service._load_glossary = AsyncMock(return_value=([], []))
    return service


@pytest.mark.anyio
async def test_estimate_reports_the_share_already_approved():
    rows = [
        _segment(0, "Total assets"),
        _segment(1, "Total equity"),
        _segment(2, "Deferred tax assets"),
        _segment(3, "Brand new sentence"),
    ]
    service = _service(rows)
    service.memory.find_matches.return_value = {
        tm.source_hash("Total assets"): SimpleNamespace(
            translation="Totaal activa"
        ),
        tm.source_hash("Total equity"): SimpleNamespace(
            translation="Totaal eigen vermogen"
        ),
    }

    estimate = await service.estimate_reuse("job-1", "NL")

    assert estimate == {"total": 4, "reusable": 2, "pct": 50}


@pytest.mark.anyio
async def test_estimate_rejects_an_unknown_market():
    service = _service([])
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await service.estimate_reuse("job-1", "XX")
    assert exc.value.status_code == 400


@pytest.mark.anyio
async def test_prefill_marks_matches_approved_with_tm_provenance():
    rows = [
        _segment(0, "Total assets"),
        _segment(1, "Brand new sentence"),
    ]
    service = _service(rows)
    service.memory.find_matches.return_value = {
        tm.source_hash("Total assets"): SimpleNamespace(
            translation="Totaal activa"
        )
    }

    reused = await service._prefill_from_memory("job-1", "NL")

    assert reused == 1
    kwargs = service.segments.set_translations.call_args.kwargs
    args = service.segments.set_translations.call_args.args
    assert args[1] == {0: "Totaal activa"}
    assert kwargs == {"status": "approved", "provenance": "tm"}


@pytest.mark.anyio
async def test_prefill_skips_segments_already_approved():
    rows = [_segment(0, "Total assets", status="approved")]
    service = _service(rows)

    reused = await service._prefill_from_memory("job-1", "NL")

    assert reused == 0
    service.memory.find_matches.assert_awaited_once_with([], "NL")
    service.segments.set_translations.assert_not_called()


@pytest.mark.anyio
async def test_starting_a_run_reports_what_memory_covered():
    rows = [_segment(0, "Total assets"), _segment(1, "New text")]
    service = _service(rows)
    service.memory.find_matches.return_value = {
        tm.source_hash("Total assets"): SimpleNamespace(
            translation="Totaal activa"
        )
    }
    service._build_translator = AsyncMock(return_value=MagicMock())
    service._run_translation = AsyncMock()
    service.jobs.update.side_effect = lambda job_id, values: (
        DocumentTranslationJobModel(
            id=job_id, filename="f.docx", **{"status": values["status"]}
        )
    )

    await service.start_translation(
        "job-1", StartTranslationDto(target_market="NL")
    )

    values = service.jobs.update.call_args.args[1]
    assert values["progress"] == {"reused": 1}
    assert values["target_market"] == "NL"


@pytest.mark.anyio
async def test_approving_a_segment_records_it_in_memory():
    rows = [_segment(0, "Total assets", translation="Totaal activa")]
    service = _service(rows)
    service.segments.update_segment.return_value = _segment(
        0, "Total assets", translation="Totaal activa", status="approved"
    )

    await service.update_segment("job-1", 0, UpdateSegmentDto(status="approved"))

    kwargs = service.memory.upsert.call_args.kwargs
    assert kwargs["source_hash"] == tm.source_hash("Total assets")
    assert kwargs["target_market"] == "NL"
    assert kwargs["translation"] == "Totaal activa"
    assert kwargs["origin_filename"] == "FS 2025-2026.docx"


@pytest.mark.anyio
async def test_editing_without_approving_does_not_record_memory():
    rows = [_segment(0, "Total assets", translation="Totaal activa")]
    service = _service(rows)
    service.segments.update_segment.return_value = _segment(
        0, "Total assets", translation="anders", status="translated"
    )

    await service.update_segment("job-1", 0, UpdateSegmentDto(translation="anders"))

    service.memory.upsert.assert_not_called()
