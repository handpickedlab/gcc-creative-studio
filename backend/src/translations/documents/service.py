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
"""Document translation jobs: upload/preflight, background translation with
poll-able progress, segment review, and layout-preserving export.

Follows the data_query poll pattern: the start endpoint returns immediately,
a background task translates section batches and flushes progress to the
job row through short-lived sessions, and the client polls GET /{id}.
"""

from __future__ import annotations

import asyncio
import io
import logging
import uuid

from fastapi import Depends, HTTPException, status

from src.common.storage_service import GcsService
from src.config.config_service import config_service
from src.database import async_session_local
from src.translations import markets
from src.translations.documents import qa
from src.translations.documents.docx_engine import DocxTranslationEngine
from src.translations.documents.dto.document_translation_dto import (
    StartTranslationDto,
    UpdateSegmentDto,
)
from src.translations.documents.model import Segment, SegmentKind
from src.translations.documents.repository.document_translation_repository import (
    DocumentTranslationJobRepository,
    DocumentTranslationSegmentRepository,
)
from src.translations.documents.schema.document_translation_model import (
    DocumentTranslationJobModel,
    DocumentTranslationSegment,
    DocumentTranslationSegmentModel,
)
from src.translations.documents.translator import (
    GeminiSegmentTranslator,
    GlossaryEntry,
    SegmentTranslator,
    iter_batches,
)
from src.translations.repository.glossary_repository import GlossaryRepository

logger = logging.getLogger(__name__)

_DOCX_MIME = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
_GCS_PREFIX = "document-translations"

# Protected names for annual reports; becomes glossary-domain data later.
DO_NOT_TRANSLATE = [
    "Hunkemöller",
    "Shero Holdco B.V.",
    "Together Tomorrow",
    "For Every Woman In You",
    "EBITDA",
    "IFRS",
]

# Keeps background tasks alive (see data_query: the loop only holds weak refs).
_JOB_TASKS: set[asyncio.Task] = set()


def _row_to_segment(row: DocumentTranslationSegmentModel) -> Segment:
    return Segment(
        id=row.seg_index,
        text=row.source_text,
        kind=SegmentKind(row.kind),
        paragraph=None,
        section_path=tuple(row.section_path or ()),
    )


class DocumentTranslationService:
    def __init__(
        self,
        jobs: DocumentTranslationJobRepository = Depends(),
        segments: DocumentTranslationSegmentRepository = Depends(),
        gcs: GcsService = Depends(),
    ):
        self.jobs = jobs
        self.segments = segments
        self.gcs = gcs

    # --- intake -----------------------------------------------------------

    async def create_job(
        self, filename: str, content: bytes, user_email: str | None
    ) -> DocumentTranslationJobModel:
        if not filename.lower().endswith(".docx"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only .docx sources are supported; the PDF is a "
                "signed artifact — upload the Word source instead.",
            )
        try:
            engine = await asyncio.to_thread(
                DocxTranslationEngine, io.BytesIO(content)
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Could not parse document: {e}",
            )

        job_id = str(uuid.uuid4())
        source_uri = f"{_GCS_PREFIX}/{job_id}/source.docx"
        await asyncio.to_thread(
            self.gcs.upload_bytes_to_gcs, content, source_uri, _DOCX_MIME
        )

        sections = [
            {
                "title": node.title,
                "level": node.level,
                "segments": len(node.segments),
            }
            for node in engine.tree.root.walk()
            if node.level > 0
        ]
        job = await self.jobs.create(
            DocumentTranslationJobModel(
                id=job_id,
                filename=filename,
                status="uploaded",
                source_gcs_uri=f"gs://{self.gcs.bucket_name}/{source_uri}",
                stats={**engine.tree.stats(), "sections": sections},
                created_by=user_email,
            )
        )
        rows = [
            DocumentTranslationSegment(
                job_id=job_id,
                seg_index=seg.id,
                kind=seg.kind.value,
                section_path=list(seg.section_path),
                source_text=seg.text,
                status="pending" if seg.kind.translatable else "locked",
            )
            for seg in engine.tree.segments
        ]
        await self.segments.bulk_create(rows)
        return job

    # --- job lifecycle ----------------------------------------------------

    async def list_jobs(self) -> list[DocumentTranslationJobModel]:
        return await self.jobs.find_recent()

    async def get_job(self, job_id: str) -> DocumentTranslationJobModel:
        job = await self.jobs.get_by_id(job_id)
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Job not found.",
            )
        return job

    async def start_translation(
        self, job_id: str, dto: StartTranslationDto
    ) -> DocumentTranslationJobModel:
        job = await self.get_job(job_id)
        if job.status == "translating":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Job is already translating.",
            )
        if not markets.is_valid_market(dto.target_market):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown target market '{dto.target_market}'.",
            )
        model_id = dto.model_id or config_service.GEMINI_MODEL_ID
        job = await self.jobs.update(
            job_id,
            {
                "status": "translating",
                "target_market": dto.target_market,
                "model_id": model_id,
                "error_message": None,
            },
        )
        translator = await self._build_translator(dto.target_market, model_id)
        task = asyncio.create_task(
            self._run_translation(job_id, translator)
        )
        _JOB_TASKS.add(task)
        task.add_done_callback(_JOB_TASKS.discard)
        return job

    async def _build_translator(
        self, target_market: str, model_id: str
    ) -> SegmentTranslator:
        # Late import: pulls in google.genai + Vertex credential wiring.
        from src.multimodal.schema.gemini_model_setup import GeminiModelSetup

        glossary = await self._load_glossary(target_market)
        return GeminiSegmentTranslator(
            client=GeminiModelSetup.get_client(),
            model_id=model_id,
            target_language=markets.language_for_market(target_market),
            glossary=glossary,
            do_not_translate=DO_NOT_TRANSLATE,
        )

    async def _load_glossary(self, market: str) -> list[GlossaryEntry]:
        """Reuses the briefing glossary for the market's dictionary.

        A dedicated financial domain is a follow-up; until then the shared
        dictionary at least keeps brand terms consistent.
        """
        async with async_session_local() as db:
            terms = await GlossaryRepository(db).find_all(limit=1000)
        return [
            GlossaryEntry(source=t.source, target=t.target)
            for t in terms
            if t.language == market
        ]

    async def _run_translation(
        self, job_id: str, translator: SegmentTranslator
    ) -> None:
        """Background worker: fresh short-lived sessions only."""
        try:
            async with async_session_local() as db:
                rows = await DocumentTranslationSegmentRepository(
                    db
                ).find_by_job(job_id, translatable_only=True)
            pending = [
                _row_to_segment(r) for r in rows if r.status != "approved"
            ]
            total = len(pending)
            done = 0
            failed_all: list[int] = []
            for batch in iter_batches(pending):
                results = await asyncio.to_thread(
                    translator.translate_batch, batch
                )
                missing = [s.id for s in batch if s.id not in results]
                for seg in batch:
                    if seg.id in results:
                        seg.translation = results[seg.id]
                failed_all.extend(missing)
                done += len(batch)
                async with async_session_local() as db:
                    seg_repo = DocumentTranslationSegmentRepository(db)
                    await seg_repo.set_translations(
                        job_id, results, status="translated"
                    )
                    await seg_repo.mark_failed(job_id, missing)
                    await DocumentTranslationJobRepository(db).update(
                        job_id,
                        {
                            "progress": {
                                "translated": done - len(failed_all),
                                "failed": len(failed_all),
                                "total": total,
                            }
                        },
                    )
            findings = qa.run_all(
                pending, do_not_translate=DO_NOT_TRANSLATE
            )
            async with async_session_local() as db:
                await DocumentTranslationJobRepository(db).update(
                    job_id,
                    {
                        "status": "review",
                        "qa_findings": [
                            {
                                "segment_index": f.segment_id,
                                "check": f.check,
                                "severity": f.severity.value,
                                "detail": f.detail,
                            }
                            for f in findings
                        ],
                    },
                )
        except Exception as e:
            logger.exception("Translation job %s failed", job_id)
            async with async_session_local() as db:
                await DocumentTranslationJobRepository(db).update(
                    job_id, {"status": "failed", "error_message": str(e)}
                )

    # --- review -----------------------------------------------------------

    async def list_segments(
        self, job_id: str, status_filter: str | None = None
    ) -> list[DocumentTranslationSegmentModel]:
        await self.get_job(job_id)
        return await self.segments.find_by_job(job_id, status=status_filter)

    async def update_segment(
        self, job_id: str, seg_index: int, dto: UpdateSegmentDto
    ) -> DocumentTranslationSegmentModel:
        await self.get_job(job_id)
        values: dict = {}
        if dto.translation is not None:
            values["translation"] = dto.translation
            values["status"] = "edited"
        if dto.status is not None:
            if dto.status not in ("translated", "edited", "approved"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid segment status '{dto.status}'.",
                )
            values["status"] = dto.status
        if not values:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Nothing to update.",
            )
        updated = await self.segments.update_segment(
            job_id, seg_index, values
        )
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Segment not found.",
            )
        return updated

    # --- export -----------------------------------------------------------

    async def export(self, job_id: str) -> tuple[str, bytes]:
        """Rebuilds the docx with all reviewed translations applied."""
        job = await self.get_job(job_id)
        if job.status not in ("review", "completed"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Job is not ready for export.",
            )
        blocking = [
            f
            for f in (job.qa_findings or [])
            if f.get("severity") == "error"
        ]
        if blocking:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"{len(blocking)} blocking QA findings must be "
                "resolved before export.",
            )
        content = await asyncio.to_thread(
            self.gcs.download_bytes_from_gcs, job.source_gcs_uri
        )
        if not content:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Source document is no longer available.",
            )
        rows = await self.segments.find_by_job(job_id)
        translations = {
            r.seg_index: r.translation
            for r in rows
            if r.translation and r.status in ("translated", "edited", "approved")
        }
        engine = await asyncio.to_thread(
            DocxTranslationEngine, io.BytesIO(content)
        )
        for seg in engine.tree.segments:
            if seg.id in translations:
                seg.translation = translations[seg.id]
        engine.apply()
        out = io.BytesIO()
        engine.save(out)
        data = out.getvalue()

        output_uri = f"{_GCS_PREFIX}/{job_id}/translated.docx"
        await asyncio.to_thread(
            self.gcs.upload_bytes_to_gcs, data, output_uri, _DOCX_MIME
        )
        await self.jobs.update(
            job_id,
            {
                "status": "completed",
                "output_gcs_uri": f"gs://{self.gcs.bucket_name}/{output_uri}",
            },
        )
        stem = job.filename.rsplit(".", 1)[0]
        market = job.target_market or "translated"
        return f"{stem} ({market}).docx", data
