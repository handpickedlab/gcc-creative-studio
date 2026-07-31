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
"""Tests for the document translation job service (upload/review/export)."""

import io
from unittest.mock import AsyncMock, MagicMock

import pytest
from docx import Document
from fastapi import HTTPException

from src.translations.documents.dto.document_translation_dto import (
    UpdateSegmentDto,
)
from src.translations.documents.schema.document_translation_model import (
    DocumentTranslationJobModel,
    DocumentTranslationSegmentModel,
)
from src.translations.documents.service import DocumentTranslationService


def _fixture_docx_bytes() -> bytes:
    doc = Document()
    doc.add_heading("2.19 Right-of-use assets", level=1)
    doc.add_paragraph("The Group recognised an impairment of EUR 1,234.")
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def _service() -> DocumentTranslationService:
    jobs = AsyncMock()
    segments = AsyncMock()
    gcs = MagicMock()
    gcs.bucket_name = "test-bucket"
    return DocumentTranslationService(jobs=jobs, segments=segments, gcs=gcs)


def _job_model(**overrides) -> DocumentTranslationJobModel:
    defaults = dict(
        id="job-1",
        filename="report.docx",
        status="review",
        target_market="NL",
        source_gcs_uri="gs://test-bucket/document-translations/job-1/source.docx",
    )
    defaults.update(overrides)
    return DocumentTranslationJobModel(**defaults)


@pytest.mark.anyio
async def test_create_job_rejects_non_docx():
    service = _service()
    with pytest.raises(HTTPException) as exc:
        await service.create_job("report.pdf", b"%PDF-", "n@hp.com")
    assert exc.value.status_code == 400
    assert "Word source" in exc.value.detail


@pytest.mark.anyio
async def test_create_job_parses_stores_and_persists_segments():
    service = _service()
    service.jobs.create.side_effect = lambda model: model

    job = await service.create_job(
        "report.docx", _fixture_docx_bytes(), "n@hp.com"
    )

    assert job.status == "uploaded"
    assert job.stats["translatable"] == 2  # heading + prose
    assert job.stats["sections"][0]["title"] == "2.19 Right-of-use assets"
    service.gcs.upload_bytes_to_gcs.assert_called_once()
    rows = service.segments.bulk_create.call_args.args[0]
    assert {r.status for r in rows} == {"pending"}
    assert rows[0].job_id == job.id


@pytest.mark.anyio
async def test_update_segment_rejects_unknown_status():
    service = _service()
    service.jobs.get_by_id.return_value = _job_model()
    with pytest.raises(HTTPException) as exc:
        await service.update_segment(
            "job-1", 3, UpdateSegmentDto(status="wonky")
        )
    assert exc.value.status_code == 400


@pytest.mark.anyio
async def test_update_segment_edit_marks_edited():
    service = _service()
    service.jobs.get_by_id.return_value = _job_model()
    service.segments.update_segment.return_value = (
        DocumentTranslationSegmentModel(
            id=1,
            job_id="job-1",
            seg_index=3,
            kind="prose",
            source_text="x",
            translation="y",
            status="edited",
        )
    )
    await service.update_segment(
        "job-1", 3, UpdateSegmentDto(translation="y")
    )
    values = service.segments.update_segment.call_args.args[2]
    assert values == {"translation": "y", "status": "edited"}


@pytest.mark.anyio
async def test_export_blocked_by_qa_errors():
    service = _service()
    service.jobs.get_by_id.return_value = _job_model(
        qa_findings=[{"severity": "error", "check": "numbers"}]
    )
    with pytest.raises(HTTPException) as exc:
        await service.export("job-1")
    assert exc.value.status_code == 409
    assert "QA findings" in exc.value.detail


@pytest.mark.anyio
async def test_export_applies_reviewed_translations():
    service = _service()
    service.jobs.get_by_id.return_value = _job_model()
    service.gcs.download_bytes_from_gcs.return_value = _fixture_docx_bytes()
    service.segments.find_by_job.return_value = [
        DocumentTranslationSegmentModel(
            id=1,
            job_id="job-1",
            seg_index=1,
            kind="prose",
            source_text="The Group recognised an impairment of EUR 1,234.",
            translation=(
                "De Groep heeft een bijzondere waardevermindering van "
                "EUR 1,234 opgenomen."
            ),
            status="approved",
        ),
        DocumentTranslationSegmentModel(
            id=2,
            job_id="job-1",
            seg_index=0,
            kind="heading",
            source_text="2.19 Right-of-use assets",
            translation=None,  # untranslated: must stay English
            status="pending",
        ),
    ]

    filename, data = await service.export("job-1")

    assert filename == "report (NL).docx"
    exported = Document(io.BytesIO(data))
    texts = [p.text for p in exported.paragraphs]
    assert any("bijzondere waardevermindering" in t for t in texts)
    assert "2.19 Right-of-use assets" in texts
    service.gcs.upload_bytes_to_gcs.assert_called_once()
    update_values = service.jobs.update.call_args.args[1]
    assert update_values["status"] == "completed"
