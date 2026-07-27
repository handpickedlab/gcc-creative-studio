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

"""Background ingest worker for the research library.

Follows the ``brand_guidelines`` worker pattern: a module-level function
submitted to the dedicated ``app.state.research_ingest_executor``, running
its own event loop with a per-thread ``WorkerDatabase()`` engine.

Pipeline per document: download from GCS -> (LibreOffice-convert office
formats to PDF) -> render pages one at a time -> per page: upload image +
thumbnail, Gemini claim extraction, per-claim embedding, persist. Network
work (upload/extract/embed) runs concurrently in small batches; database
writes stay strictly sequential because an ``AsyncSession`` must never be
shared across concurrent tasks.

Failure semantics:
- A page that fails after retries is recorded in ``failed_pages`` and
  skipped; the document ends as COMPLETED_WITH_ERRORS, keeping every page
  that DID succeed (re-extracting 6,500 corpus pages costs real money).
- A document-level error ends as FAILED with the reason.
- Terminal writes are guarded twice: against deletion while processing
  (tombstone) and against a newer reprocess run having superseded this one.
- On success, claims from older ingest runs are deleted only AFTER the new
  run has fully written (the reprocess atomic swap).
- The document row is touched after every page batch. Nothing else writes
  to it mid-run, so that heartbeat is what tells ``stalled_sweeper`` this
  document is alive rather than orphaned by a reaped instance.
"""

import asyncio
import logging
import os
import sys
import tempfile
from dataclasses import dataclass, field

from google.cloud.logging import Client as LoggerClient
from google.cloud.logging.handlers import CloudLoggingHandler

from src.common.storage_service import GcsService
from src.multimodal.schema.gemini_model_setup import GeminiModelSetup
from src.research_library import canonicalization_service, config
from src.research_library.ingest import (
    conversion_service,
    embedding_service,
    extraction_service,
    ingest_queue,
    rendering_service,
)
from src.research_library.repository.research_claim_repository import (
    ResearchClaimRepository,
)
from src.research_library.repository.research_document_repository import (
    ResearchDocumentRepository,
)
from src.research_library.repository.tag_alias_repository import (
    TagAliasRepository,
)
from src.research_library.schema.research_document_model import (
    DocKindEnum,
    ResearchClaimModel,
    ResearchDocStatus,
)

logger = logging.getLogger(__name__)

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}


@dataclass
class _PageResult:
    """Everything produced for one page before it is written to the DB."""

    page_no: int
    image_gcs_uri: str | None = None
    thumb_gcs_uri: str | None = None
    extraction: extraction_service.PageExtraction | None = None
    embeddings: list[list[float]] = field(default_factory=list)
    error: str | None = None


def run_ingest(document_id: int) -> None:
    """Entry point submitted to the dedicated research-ingest executor."""
    worker_logger = logging.getLogger(f"research_library_worker.{document_id}")
    worker_logger.setLevel(logging.INFO)

    if worker_logger.hasHandlers():
        worker_logger.handlers.clear()
    if os.getenv("ENVIRONMENT") == "production":
        handler = CloudLoggingHandler(
            LoggerClient(),
            name=f"research_library_worker.{document_id}",
        )
    else:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s - [RESEARCH_LIBRARY_WORKER] - %(levelname)s"
                " - %(message)s",
            ),
        )
    worker_logger.addHandler(handler)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(
            _run_ingest_pipeline(document_id, worker_logger),
        )
    except Exception:
        worker_logger.error(
            "Research library ingest worker crashed for document %s.",
            document_id,
            exc_info=True,
        )
    finally:
        loop.close()
        # Frees this document's slot in the process-local ingest queue even
        # when the run crashed, so the sweeper may pick it up again later.
        ingest_queue.release(document_id)


async def _run_ingest_pipeline(
    document_id: int,
    worker_logger: logging.Logger,
) -> None:
    from src.database import WorkerDatabase

    async with WorkerDatabase() as db_factory:
        async with db_factory() as db:
            doc_repo = ResearchDocumentRepository(db)
            claim_repo = ResearchClaimRepository(db)
            tag_alias_repo = TagAliasRepository(db)

            document = await doc_repo.find_active_by_id(document_id)
            if not document:
                worker_logger.warning(
                    "Document %s no longer exists; aborting ingest.",
                    document_id,
                )
                return
            run_id = document.ingest_run_id
            # Counts as an attempt only now that work really begins, and
            # doubles as the first heartbeat of this run.
            await doc_repo.begin_attempt(document_id)

            gcs_service = GcsService()
            client = GeminiModelSetup.init()

            # Canonical vocabulary steers the extraction prompt toward
            # existing tags; the alias map resolves canonical_tags at write
            # time (unseen tags fall back to themselves until the next
            # canonicalization bootstrap re-resolves everything).
            aliases = await tag_alias_repo.list_aliases()
            alias_map = {a.raw: a.canonical for a in aliases}
            vocabulary = canonicalization_service.load_vocabulary(aliases)

            try:
                summary = await _ingest_document(
                    document,
                    doc_repo,
                    claim_repo,
                    gcs_service,
                    client,
                    worker_logger,
                    vocabulary=vocabulary,
                    alias_map=alias_map,
                )
            except Exception as e:
                worker_logger.error(
                    "Ingest failed for document %s: %s",
                    document_id,
                    e,
                    exc_info=True,
                )
                await _finalize(
                    doc_repo,
                    claim_repo,
                    document_id,
                    run_id,
                    worker_logger,
                    updates={
                        "status": ResearchDocStatus.FAILED.value,
                        "error_message": str(e),
                    },
                )
                return

            status = (
                ResearchDocStatus.COMPLETED_WITH_ERRORS.value
                if summary["failed_pages"]
                else ResearchDocStatus.COMPLETED.value
            )
            await _finalize(
                doc_repo,
                claim_repo,
                document_id,
                run_id,
                worker_logger,
                updates={
                    "status": status,
                    "error_message": summary["note"],
                    "failed_pages": summary["failed_pages"],
                    "page_count": summary["page_count"],
                    "doc_kind": summary["doc_kind"],
                    "language": summary["language"],
                    # This run got there, so a future stall starts counting
                    # its retries from zero again.
                    "ingest_attempts": 0,
                },
                swap_claims=True,
            )
            worker_logger.info(
                "Document %s ingested: %s pages, %s claims, %s failed pages.",
                document_id,
                summary["page_count"],
                summary["claim_count"],
                len(summary["failed_pages"]),
            )


async def _finalize(
    doc_repo: ResearchDocumentRepository,
    claim_repo: ResearchClaimRepository,
    document_id: int,
    run_id: str | None,
    worker_logger: logging.Logger,
    updates: dict,
    swap_claims: bool = False,
) -> None:
    """Terminal write, guarded against deletion and superseded runs."""
    current = await doc_repo.find_active_by_id(document_id)
    if not current:
        worker_logger.warning(
            "Document %s was deleted during ingest; skipping terminal write.",
            document_id,
        )
        return
    if current.ingest_run_id != run_id:
        worker_logger.warning(
            "Document %s was superseded by a newer ingest run; "
            "abandoning run %s.",
            document_id,
            run_id,
        )
        return

    await doc_repo.update(document_id, updates)
    if swap_claims and run_id:
        deleted = await claim_repo.delete_claims_except_run(
            document_id, run_id
        )
        if deleted:
            worker_logger.info(
                "Removed %s claims from superseded runs of document %s.",
                deleted,
                document_id,
            )


async def _ingest_document(
    document,
    doc_repo: ResearchDocumentRepository,
    claim_repo: ResearchClaimRepository,
    gcs_service: GcsService,
    client,
    worker_logger: logging.Logger,
    vocabulary: list[str] | None = None,
    alias_map: dict[str, str] | None = None,
) -> dict:
    """Runs the convert -> render -> extract -> embed -> persist pipeline."""
    extension = os.path.splitext(document.filename)[1].lower()
    gcs_prefix = _blob_prefix(document.gcs_uri, gcs_service.bucket_name)

    claim_count = 0
    failed_pages: list[int] = []
    page_languages: list[str] = []
    doc_kind: str | None = None
    note: str | None = None

    with tempfile.TemporaryDirectory(prefix="research-ingest-") as workdir:
        local_path = os.path.join(workdir, document.filename)
        downloaded = await asyncio.to_thread(
            gcs_service.download_from_gcs,
            _blob_path(document.gcs_uri, gcs_service.bucket_name),
            local_path,
        )
        if not downloaded:
            raise RuntimeError(
                f"could not download source file {document.gcs_uri}"
            )

        if extension in _IMAGE_EXTENSIONS:
            doc_kind = DocKindEnum.IMAGE.value
            page_iter = iter(
                [
                    await asyncio.to_thread(
                        rendering_service.render_image_file,
                        local_path,
                        config.RENDER_LONG_EDGE,
                        config.THUMB_LONG_EDGE,
                    ),
                ],
            )
            total_pages = 1
        else:
            pdf_path = local_path
            if conversion_service.needs_conversion(document.filename):
                worker_logger.info(
                    "Converting %s to PDF.", document.filename
                )
                pdf_path = await asyncio.to_thread(
                    conversion_service.convert_to_pdf, local_path, workdir
                )
            total_pages = await asyncio.to_thread(
                rendering_service.pdf_page_count, pdf_path
            )
            page_iter = rendering_service.render_pdf_pages(
                pdf_path,
                long_edge=config.RENDER_LONG_EDGE,
                thumb_long_edge=config.THUMB_LONG_EDGE,
                max_pages=config.MAX_PAGES,
            )

        # Downloading and converting a large deck can take minutes; beat
        # before the first page so the sweeper doesn't call this stalled.
        await doc_repo.touch(document.id)

        page_count = min(total_pages, config.MAX_PAGES)
        if total_pages > config.MAX_PAGES:
            note = (
                f"Processed the first {config.MAX_PAGES} of {total_pages} "
                "pages (RL_MAX_PAGES cap)."
            )
            worker_logger.warning(
                "Document %s truncated: %s", document.id, note
            )

        while True:
            batch = await asyncio.to_thread(
                _next_batch, page_iter, config.EXTRACT_CONCURRENCY
            )
            if not batch:
                break

            if doc_kind is None:
                first = batch[0]
                doc_kind = (
                    DocKindEnum.SLIDE_DECK.value
                    if first.width > first.height
                    else DocKindEnum.PROSE_REPORT.value
                )

            results = await asyncio.gather(
                *(
                    _process_page_network(
                        page,
                        document,
                        gcs_prefix,
                        gcs_service,
                        client,
                        worker_logger,
                        vocabulary=vocabulary,
                    )
                    for page in batch
                ),
            )

            for result in results:
                claim_count += await _persist_page(
                    result, document, doc_repo, claim_repo, alias_map
                )
                if result.error:
                    failed_pages.append(result.page_no)
                elif result.extraction and result.extraction.language:
                    page_languages.append(result.extraction.language)

            await doc_repo.touch(document.id)

    language = (
        max(set(page_languages), key=page_languages.count)
        if page_languages
        else None
    )
    return {
        "page_count": page_count,
        "claim_count": claim_count,
        "failed_pages": failed_pages,
        "doc_kind": doc_kind or DocKindEnum.OTHER.value,
        "language": language,
        "note": note,
    }


async def _process_page_network(
    page: rendering_service.RenderedPage,
    document,
    gcs_prefix: str,
    gcs_service: GcsService,
    client,
    worker_logger: logging.Logger,
    vocabulary: list[str] | None = None,
) -> _PageResult:
    """The network-only half of one page: upload images, extract, embed.

    No database access happens here, so several pages can run concurrently
    on one worker's event loop.
    """
    result = _PageResult(page_no=page.page_no)
    try:
        result.image_gcs_uri = await asyncio.to_thread(
            gcs_service.upload_bytes_to_gcs,
            page.image_bytes,
            f"{gcs_prefix}/pages/{page.page_no:04d}.png",
            "image/png",
        )
        result.thumb_gcs_uri = await asyncio.to_thread(
            gcs_service.upload_bytes_to_gcs,
            page.thumb_bytes,
            f"{gcs_prefix}/thumbs/{page.page_no:04d}.png",
            "image/png",
        )
        if not result.image_gcs_uri or not result.thumb_gcs_uri:
            raise RuntimeError("could not upload page images to GCS")

        result.extraction = await asyncio.to_thread(
            extraction_service.extract_page,
            client,
            config.EXTRACT_MODEL,
            result.image_gcs_uri,
            vocabulary,
        )
        statements = [c.statement for c in result.extraction.claims]
        if statements:
            result.embeddings = await asyncio.to_thread(
                embedding_service.embed_texts,
                client,
                statements,
                embedding_service.TASK_DOCUMENT,
            )
    except Exception as e:
        worker_logger.warning(
            "Page %s of document %s failed: %s",
            page.page_no,
            document.id,
            e,
        )
        result.error = str(e)
    return result


async def _persist_page(
    result: _PageResult,
    document,
    doc_repo: ResearchDocumentRepository,
    claim_repo: ResearchClaimRepository,
    alias_map: dict[str, str] | None = None,
) -> int:
    """The sequential database half of one page. Returns claims written."""
    await doc_repo.upsert_page(
        document_id=document.id,
        page_no=result.page_no,
        image_gcs_uri=result.image_gcs_uri,
        thumb_gcs_uri=result.thumb_gcs_uri,
        status=(
            ResearchDocStatus.FAILED.value
            if result.error
            else ResearchDocStatus.COMPLETED.value
        ),
        error=result.error,
    )
    if result.error or not result.extraction:
        return 0

    claims = [
        ResearchClaimModel(
            document_id=document.id,
            page_no=result.page_no,
            statement=claim.statement,
            metric=claim.metric,
            value=claim.value,
            unit=claim.unit,
            segment=claim.segment,
            geography=claim.geography,
            period=claim.period,
            claim_type=claim.claim_type,
            source_citation=claim.source_citation,
            sample=claim.sample,
            raw_tags=claim.tags,
            canonical_tags=canonicalization_service.apply_aliases(
                claim.tags, claim.metric, alias_map or {}
            ),
            embedding=embedding,
            ingest_run_id=document.ingest_run_id,
        )
        for claim, embedding in zip(
            result.extraction.claims, result.embeddings
        )
    ]
    await claim_repo.bulk_insert_claims(claims)
    return len(claims)


def _next_batch(iterator, size: int) -> list:
    """Pulls up to ``size`` items from a sync iterator (run in a thread)."""
    batch = []
    for _ in range(size):
        try:
            batch.append(next(iterator))
        except StopIteration:
            break
    return batch


def _blob_path(gcs_uri: str, bucket_name: str) -> str:
    """gs://bucket/a/b/file.pdf -> a/b/file.pdf"""
    return gcs_uri.replace(f"gs://{bucket_name}/", "", 1)


def _blob_prefix(gcs_uri: str, bucket_name: str) -> str:
    """gs://bucket/a/b/file.pdf -> a/b"""
    return _blob_path(gcs_uri, bucket_name).rsplit("/", 1)[0]
