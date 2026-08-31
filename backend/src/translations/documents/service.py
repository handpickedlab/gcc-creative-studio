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
import datetime
import io
import logging
import os
import re
import uuid
import zipfile

from fastapi import Depends, HTTPException, status

from src.auth.iam_signer_credentials_service import IamSignerCredentials
from src.common.storage_service import GcsService
from src.config.config_service import config_service
from src.database import async_session_local
from src.translations import markets
from src.translations.documents import financial_glossary, qa
from src.translations.documents.docx_engine import DocxTranslationEngine
from src.translations.documents.dto.document_translation_dto import (
    FinalizeUploadDto,
    GenerateUploadUrlDto,
    GenerateUploadUrlResponseDto,
    StartTranslationDto,
    UpdateSegmentDto,
)
from src.translations.documents.model import Segment, SegmentKind
from src.translations.documents import memory as tm
from src.translations.documents.repository.document_translation_repository import (
    DocumentTranslationJobRepository,
    DocumentTranslationSegmentRepository,
    TranslationMemoryRepository,
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

# Generous cap: the branded FY25-26 annual report alone is 55MB.
MAX_UPLOAD_BYTES = 150 * 1024 * 1024

# Keeps background tasks alive (see data_query: the loop only holds weak refs).
_JOB_TASKS: set[asyncio.Task] = set()

# A run flushes progress to the job row after every section batch and
# `updated_at` carries onupdate=now(), so the row beats like a heartbeat. Going
# quiet for longer than this while still "translating" means the worker is gone
# rather than slow: the task lives inside one Cloud Run instance and the service
# scales to zero, so an instance reclaimed mid-run (or replaced by a deploy)
# takes the task with it WITHOUT raising — the except branch never runs, and the
# job would otherwise sit at its last percentage forever with no way out.
_STALL_AFTER_S = float(os.getenv("DOC_TRANSLATION_STALL_AFTER_S", "600"))


def _doc_properties(content: bytes) -> dict[str, int]:
    """Pages/words from docProps/app.xml (Word's own extended properties)."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            xml = zf.read("docProps/app.xml").decode("utf-8", "ignore")
        props = {}
        for key in ("Pages", "Words"):
            match = re.search(rf"<{key}>(\d+)</{key}>", xml)
            if match:
                props[key.lower()] = int(match.group(1))
        return props
    except Exception:  # missing part, corrupt zip: cosmetic, never fatal
        return {}


def _is_stalled(job: DocumentTranslationJobModel) -> bool:
    """True when a translating job has stopped beating (see _STALL_AFTER_S)."""
    if job.status != "translating" or job.updated_at is None:
        return False
    beat = job.updated_at
    if beat.tzinfo is None:  # older rows may come back naive
        beat = beat.replace(tzinfo=datetime.UTC)
    age = (datetime.datetime.now(datetime.UTC) - beat).total_seconds()
    return age > _STALL_AFTER_S


def _flag_stalled(job: DocumentTranslationJobModel) -> DocumentTranslationJobModel:
    """Stamps the computed `stalled` flag the review UI offers Resume on."""
    job.stalled = _is_stalled(job)
    return job


def _row_to_segment(row: DocumentTranslationSegmentModel) -> Segment:
    return Segment(
        id=row.seg_index,
        text=row.source_text,
        kind=SegmentKind(row.kind),
        paragraph=None,
        section_path=tuple(row.section_path or ()),
        section_id=row.section_id or "",
        translation=row.translation,
    )


def _finding_payload(finding) -> dict:
    return {
        "segmentIndex": finding.segment_id,
        "type": finding.check,
        "severity": finding.severity.value,
        "msg": finding.detail,
        "term": finding.term,
        "expected": finding.expected,
        "found": finding.found,
    }


class DocumentTranslationService:
    def __init__(
        self,
        jobs: DocumentTranslationJobRepository = Depends(),
        segments: DocumentTranslationSegmentRepository = Depends(),
        memory: TranslationMemoryRepository = Depends(),
        gcs: GcsService = Depends(),
        signer: IamSignerCredentials = Depends(),
    ):
        self.jobs = jobs
        self.segments = segments
        self.memory = memory
        self.gcs = gcs
        self.signer = signer

    # --- intake -----------------------------------------------------------

    def _require_docx(self, filename: str) -> None:
        if not filename.lower().endswith(".docx"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only .docx sources are supported; the PDF is a "
                "signed artifact — upload the Word source instead.",
            )

    async def generate_upload_url(
        self, dto: GenerateUploadUrlDto
    ) -> GenerateUploadUrlResponseDto:
        """Mints a signed PUT URL so the browser uploads straight to GCS.

        An annual report can run to tens of megabytes — the branded FY25-26
        report is 55MB — well past what a Cloud Run request body may carry,
        so the file must bypass the backend entirely.
        """
        self._require_docx(dto.filename)
        if dto.size_bytes > MAX_UPLOAD_BYTES:
            max_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"File is too large. Maximum size is {max_mb}MB.",
            )
        blob_name = (
            f"{_GCS_PREFIX}/uploads/{uuid.uuid4()}/{dto.filename}"
        )
        upload_url, gcs_uri = await asyncio.to_thread(
            self.signer.generate_v4_upload_signed_url,
            blob_name,
            _DOCX_MIME,
            self.gcs.bucket_name,
        )
        if not upload_url or not gcs_uri:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not create an upload URL.",
            )
        return GenerateUploadUrlResponseDto(
            upload_url=upload_url, gcs_uri=gcs_uri
        )

    async def finalize_upload(
        self, dto: FinalizeUploadDto, user_email: str | None
    ) -> DocumentTranslationJobModel:
        """Registers a file the client PUT to the signed URL."""
        self._require_docx(dto.filename)
        content = await asyncio.to_thread(
            self.gcs.download_bytes_from_gcs, dto.gcs_uri
        )
        if not content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file not found; upload it again.",
            )
        return await self._register(
            filename=dto.filename,
            content=content,
            source_gcs_uri=dto.gcs_uri,
            user_email=user_email,
        )

    async def create_job(
        self, filename: str, content: bytes, user_email: str | None
    ) -> DocumentTranslationJobModel:
        """Registers a file posted directly, for documents small enough."""
        self._require_docx(filename)
        job_id = str(uuid.uuid4())
        source_uri = f"{_GCS_PREFIX}/{job_id}/source.docx"
        await asyncio.to_thread(
            self.gcs.upload_bytes_to_gcs, content, source_uri, _DOCX_MIME
        )
        return await self._register(
            filename=filename,
            content=content,
            source_gcs_uri=f"gs://{self.gcs.bucket_name}/{source_uri}",
            user_email=user_email,
            job_id=job_id,
        )

    async def _register(
        self,
        filename: str,
        content: bytes,
        source_gcs_uri: str,
        user_email: str | None,
        job_id: str | None = None,
    ) -> DocumentTranslationJobModel:
        """Parses the document and persists the job with all its segments."""
        try:
            engine = await asyncio.to_thread(
                DocxTranslationEngine, io.BytesIO(content)
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Could not parse document: {e}",
            )

        job_id = job_id or str(uuid.uuid4())
        job = await self.jobs.create(
            DocumentTranslationJobModel(
                id=job_id,
                filename=filename,
                status="uploaded",
                source_gcs_uri=source_gcs_uri,
                stats={
                    **engine.tree.stats(),
                    **_doc_properties(content),
                    "tracked_changes": engine.tracked_changes(),
                    "chapters": engine.tree.outline(),
                },
                created_by=user_email,
            )
        )
        rows = [
            DocumentTranslationSegment(
                job_id=job_id,
                seg_index=seg.id,
                kind=seg.kind.value,
                section_id=seg.section_id,
                table_index=seg.table_index,
                row_index=seg.row_index,
                heading_level=seg.heading_level,
                bold=seg.bold,
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
        return [_flag_stalled(j) for j in await self.jobs.find_recent()]

    async def get_job(self, job_id: str) -> DocumentTranslationJobModel:
        job = await self.jobs.get_by_id(job_id)
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Job not found.",
            )
        return _flag_stalled(job)

    async def estimate_reuse(
        self, job_id: str, target_market: str
    ) -> dict[str, int]:
        """How much of this document a previous approval already covers."""
        await self.get_job(job_id)
        if not markets.is_valid_market(target_market):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown target market '{target_market}'.",
            )
        rows = await self.segments.find_by_job(job_id, translatable_only=True)
        matches = await self.memory.find_matches(
            [tm.source_hash(r.source_text) for r in rows], target_market
        )
        reusable = len(
            [r for r in rows if tm.source_hash(r.source_text) in matches]
        )
        total = len(rows)
        return {
            "total": total,
            "reusable": reusable,
            "pct": round(100 * reusable / total) if total else 0,
        }

    async def start_translation(
        self, job_id: str, dto: StartTranslationDto
    ) -> DocumentTranslationJobModel:
        job = await self.get_job(job_id)
        if job.status == "translating" and not job.stalled:
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
        reused = await self._prefill_from_memory(job_id, dto.target_market)
        job = await self.jobs.update(
            job_id,
            {
                "status": "translating",
                "target_market": dto.target_market,
                "model_id": model_id,
                "error_message": None,
                "progress": {"reused": reused},
            },
        )
        translator = await self._build_translator(dto.target_market, model_id)
        self._launch(job_id, translator)
        return job

    def _launch(
        self, job_id: str, translator: SegmentTranslator, resume: bool = False
    ) -> None:
        task = asyncio.create_task(
            self._run_translation(job_id, translator, resume=resume)
        )
        _JOB_TASKS.add(task)
        task.add_done_callback(_JOB_TASKS.discard)

    async def resume_translation(
        self, job_id: str
    ) -> DocumentTranslationJobModel:
        """Pick a stalled or failed run back up where it stopped.

        Unlike starting over, this keeps every segment the dead run already
        translated and only sends the gaps to the model — on a 1,300-segment
        annual report that is the difference between minutes and re-paying for
        work already done. Same market and model by definition: resuming with
        different settings would mix two translations in one document, so that
        case belongs to `start_translation`.
        """
        job = await self.get_job(job_id)
        if job.status == "translating" and not job.stalled:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Job is still translating.",
            )
        if job.status not in ("translating", "failed"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Nothing to resume: job is '{job.status}'.",
            )
        if not job.target_market:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This job never started, so there is nothing to resume.",
            )
        # Read the settings off the row we just validated, not off the row the
        # update returns: the market decides the language every remaining
        # segment is translated into, and it must be the one checked above.
        target_market = job.target_market
        model_id = job.model_id or config_service.GEMINI_MODEL_ID
        logger.info(
            "Resuming translation job %s (%s, was '%s')",
            job_id,
            target_market,
            job.status,
        )
        # No memory prefill: that ran when the job first started, and the
        # progress dict is left alone so the bar carries on from where the
        # dead run left it instead of snapping back to zero.
        job = await self.jobs.update(
            job_id, {"status": "translating", "error_message": None}
        )
        translator = await self._build_translator(target_market, model_id)
        self._launch(job_id, translator, resume=True)
        return _flag_stalled(job)

    async def _prefill_from_memory(
        self, job_id: str, target_market: str
    ) -> int:
        """Fills segments an approved translation already covers.

        Reused segments arrive approved — they were reviewed once already —
        so the run only spends money on what is genuinely new, and the
        reviewer only sees what needs judgement.
        """
        rows = await self.segments.find_by_job(job_id, translatable_only=True)
        open_rows = [r for r in rows if r.status != "approved"]
        matches = await self.memory.find_matches(
            [tm.source_hash(r.source_text) for r in open_rows], target_market
        )
        hits = {
            r.seg_index: matches[tm.source_hash(r.source_text)].translation
            for r in open_rows
            if tm.source_hash(r.source_text) in matches
        }
        if hits:
            await self.segments.set_translations(
                job_id, hits, status="approved", provenance="tm"
            )
        return len(hits)

    async def _remember(
        self,
        job: DocumentTranslationJobModel,
        rows: list[DocumentTranslationSegmentModel],
    ) -> None:
        """Records approved segments so later documents can reuse them."""
        if not job.target_market:
            return
        for row in rows:
            if not row.translation:
                continue
            await self.memory.upsert(
                source_hash=tm.source_hash(row.source_text),
                target_market=job.target_market,
                source_text=row.source_text,
                translation=row.translation,
                origin_job_id=job.id,
                origin_filename=job.filename,
            )

    async def _build_translator(
        self,
        target_market: str,
        model_id: str,
        instruction: str | None = None,
    ) -> SegmentTranslator:
        # Late import: pulls in google.genai + Vertex credential wiring.
        from src.multimodal.schema.gemini_model_setup import GeminiModelSetup

        glossary, protected = await self._load_glossary(target_market)
        return GeminiSegmentTranslator(
            client=GeminiModelSetup.get_client(),
            model_id=model_id,
            target_language=markets.language_for_market(target_market),
            glossary=glossary,
            do_not_translate=protected,
            instruction=instruction,
        )

    async def _load_glossary(
        self, market: str
    ) -> tuple[list[GlossaryEntry], list[str]]:
        """The market's financial dictionary, split into terms and names.

        Annual reports use the financial domain: "impairment" must land on
        its IFRS equivalent, not on whatever reads well in campaign copy.
        """
        async with async_session_local() as db:
            terms = await GlossaryRepository(db).find_by_domain(
                financial_glossary.DOMAIN, language=market
            )
        glossary = [
            GlossaryEntry(source=t.source, target=t.target)
            for t in terms
            if not t.do_not_translate
        ]
        protected = [t.source for t in terms if t.do_not_translate]
        return glossary, protected or list(financial_glossary.DO_NOT_TRANSLATE)

    async def _run_translation(
        self, job_id: str, translator: SegmentTranslator, resume: bool = False
    ) -> None:
        """Background worker: fresh short-lived sessions only."""
        try:
            async with async_session_local() as db:
                rows = await DocumentTranslationSegmentRepository(
                    db
                ).find_by_job(job_id, translatable_only=True)
            todo = [r for r in rows if r.status != "approved"]
            if resume:
                # Keep what the dead run produced; only the gaps go to the
                # model again.
                carried = [r for r in todo if r.translation]
                pending = [
                    _row_to_segment(r) for r in todo if not r.translation
                ]
            else:
                carried = []
                pending = [_row_to_segment(r) for r in todo]
                for seg in pending:
                    seg.translation = None  # a restart replaces prior output
            total = len(todo)
            # Seeding the count with what is already translated keeps the
            # progress bar continuing from where it froze.
            done = len(carried)
            failed_all: list[int] = []
            # Section states drive the tree during a run: queued -> run ->
            # done/fail. Batches never span sections (iter_batches).
            sections = {s.section_id: "queued" for s in pending}
            for row in carried:
                # A section the dead run finished must not flip back to queued.
                sections.setdefault(row.section_id or "", "done")
            for batch in iter_batches(pending):
                key = batch[0].section_id
                sections[key] = "run"
                results = await asyncio.to_thread(
                    translator.translate_batch, batch
                )
                missing = [s.id for s in batch if s.id not in results]
                for seg in batch:
                    if seg.id in results:
                        seg.translation = results[seg.id]
                failed_all.extend(missing)
                done += len(batch)
                remaining = any(
                    s.translation is None and s.id not in failed_all
                    for s in pending
                    if s.section_id == key
                )
                if not remaining:
                    sections[key] = "fail" if missing else "done"
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
                                "sections": dict(sections),
                            }
                        },
                    )
            # Re-read the document before QA: `set_findings` clears every
            # prior finding, so judging only this pass would erase the findings
            # for whatever an earlier, interrupted pass had translated.
            async with async_session_local() as db:
                final_rows = await DocumentTranslationSegmentRepository(
                    db
                ).find_by_job(job_id, translatable_only=True)
            reviewed = [
                _row_to_segment(r)
                for r in final_rows
                if r.status != "approved" and r.translation
            ]
            # Check against the very terms the model was instructed to use.
            findings = qa.run_all(
                reviewed,
                glossary=getattr(translator, "glossary", None),
                do_not_translate=getattr(translator, "do_not_translate", None),
            )
            payloads = [_finding_payload(f) for f in findings]
            async with async_session_local() as db:
                # One finding per segment in the review workspace; the job's
                # list keeps them all for the QA report. run_all orders
                # errors first, and reversing makes that first entry the one
                # that survives the dict collapse.
                await DocumentTranslationSegmentRepository(db).set_findings(
                    job_id,
                    {f["segmentIndex"]: f for f in reversed(payloads)},
                )
                await DocumentTranslationJobRepository(db).update(
                    job_id,
                    {"status": "review", "qa_findings": payloads},
                )
        except Exception as e:
            logger.exception("Translation job %s failed", job_id)
            async with async_session_local() as db:
                await DocumentTranslationJobRepository(db).update(
                    job_id, {"status": "failed", "error_message": str(e)}
                )

    # --- review -----------------------------------------------------------

    async def list_segments(
        self,
        job_id: str,
        status_filter: str | None = None,
        section_id: str | None = None,
        review_filter: str | None = None,
    ) -> list[DocumentTranslationSegmentModel]:
        await self.get_job(job_id)
        if review_filter and review_filter not in (
            "attention",
            "ai",
            "edited",
            "all",
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown review filter '{review_filter}'.",
            )
        return await self.segments.find_by_job(
            job_id,
            status=status_filter,
            section_id=section_id,
            review_filter=None if review_filter == "all" else review_filter,
        )

    async def approve_section(
        self, job_id: str, section_id: str
    ) -> dict[str, int]:
        """Approves every translated segment left open in a section."""
        job = await self.get_job(job_id)
        rows = await self.segments.find_by_job(
            job_id, section_id=section_id, translatable_only=True
        )
        open_rows = [
            r
            for r in rows
            if r.status not in ("approved", "pending") and r.translation
        ]
        for row in open_rows:
            await self.segments.update_segment(
                job_id, row.seg_index, {"status": "approved"}
            )
        await self._remember(job, open_rows)
        return {"approved": len(open_rows)}

    async def update_segment(
        self, job_id: str, seg_index: int, dto: UpdateSegmentDto
    ) -> DocumentTranslationSegmentModel:
        job = await self.get_job(job_id)
        values: dict = {}
        if dto.translation is not None:
            values["translation"] = dto.translation
            # A human touched it: provenance changes, review state doesn't.
            values["provenance"] = "edited"
            values["status"] = "translated"
        if dto.status is not None:
            if dto.status not in ("translated", "approved"):
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
        if updated.status == "approved":
            await self._remember(job, [updated])
        return updated

    async def retranslate_segment(
        self, job_id: str, seg_index: int, instruction: str | None
    ) -> DocumentTranslationSegmentModel:
        """One synchronous Gemini call, optionally steered by the reviewer."""
        job = await self.get_job(job_id)
        if not job.target_market:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Job has not been translated yet.",
            )
        rows = await self.segments.find_by_job(job_id)
        row = next((r for r in rows if r.seg_index == seg_index), None)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Segment not found.",
            )
        translator = await self._build_translator(
            job.target_market,
            job.model_id or config_service.GEMINI_MODEL_ID,
            instruction=instruction,
        )
        segment = _row_to_segment(row)
        results = await asyncio.to_thread(
            translator.translate_batch, [segment]
        )
        if seg_index not in results:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="The model returned no translation; try again.",
            )
        updated = await self.segments.update_segment(
            job_id,
            seg_index,
            {
                "translation": results[seg_index],
                "status": "translated",
                "provenance": "ai",
                "finding": None,
            },
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
            if r.translation and r.status in ("translated", "approved")
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
