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

"""Tests for the research library ingest worker pipeline."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.research_library.ingest.extraction_service import (
    ExtractionError,
    ExtractedClaim,
    PageExtraction,
)
from src.research_library.ingest.rendering_service import RenderedPage
from src.research_library.ingest.ingest_worker import _run_ingest_pipeline
from src.research_library.schema.research_document_model import (
    ResearchDocStatus,
    ResearchDocumentModel,
)


def _document(**kwargs) -> ResearchDocumentModel:
    defaults = {
        "id": 7,
        "filename": "deck.pdf",
        "mime_type": "application/pdf",
        "sha256": "hash",
        "gcs_uri": "gs://test-bucket/research-library/global/u1/deck.pdf",
        "status": ResearchDocStatus.PROCESSING,
        "ingest_run_id": "run-1",
    }
    defaults.update(kwargs)
    return ResearchDocumentModel(**defaults)


def _page(page_no: int, landscape=True) -> RenderedPage:
    return RenderedPage(
        page_no=page_no,
        image_bytes=b"png-bytes",
        thumb_bytes=b"thumb-bytes",
        width=1800 if landscape else 1200,
        height=1200 if landscape else 1800,
    )


def _extraction(statement: str) -> PageExtraction:
    return PageExtraction(
        takeaway=statement,
        language="nl",
        claims=[
            ExtractedClaim(
                statement=statement,
                tags=["e-commerce"],
            ),
        ],
    )


def _worker_database(db) -> MagicMock:
    session_cm = MagicMock()
    session_cm.__aenter__ = AsyncMock(return_value=db)
    session_cm.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=session_cm)
    wd_cm = MagicMock()
    wd_cm.__aenter__ = AsyncMock(return_value=factory)
    wd_cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=wd_cm)


@pytest.fixture(name="gcs")
def fixture_gcs():
    gcs = MagicMock()
    gcs.bucket_name = "test-bucket"
    gcs.download_from_gcs.side_effect = lambda blob, dest: dest
    gcs.upload_bytes_to_gcs.side_effect = (
        lambda content, blob, mime: f"gs://test-bucket/{blob}"
    )
    return gcs


@pytest.fixture(name="doc_repo")
def fixture_doc_repo():
    repo = AsyncMock()
    repo.find_active_by_id.return_value = _document()
    return repo


@pytest.fixture(name="claim_repo")
def fixture_claim_repo():
    repo = AsyncMock()
    repo.bulk_insert_claims.side_effect = lambda claims: claims
    repo.delete_claims_except_run.return_value = 0
    return repo


def _run(doc_repo, claim_repo, gcs, pages, extractions, page_count=None):
    """Runs the pipeline with every external dependency patched."""
    with (
        patch("src.database.WorkerDatabase", _worker_database(MagicMock())),
        patch(
            "src.research_library.ingest.ingest_worker."
            "ResearchDocumentRepository",
            return_value=doc_repo,
        ),
        patch(
            "src.research_library.ingest.ingest_worker."
            "ResearchClaimRepository",
            return_value=claim_repo,
        ),
        patch(
            "src.research_library.ingest.ingest_worker.GcsService",
            return_value=gcs,
        ),
        patch(
            "src.research_library.ingest.ingest_worker."
            "GeminiModelSetup.init",
            return_value=MagicMock(),
        ),
        patch(
            "src.research_library.ingest.rendering_service.pdf_page_count",
            return_value=page_count if page_count is not None else len(pages),
        ),
        patch(
            "src.research_library.ingest.rendering_service.render_pdf_pages",
            return_value=iter(pages),
        ),
        patch(
            "src.research_library.ingest.extraction_service.extract_page",
            side_effect=extractions,
        ),
        patch(
            "src.research_library.ingest.embedding_service.embed_texts",
            side_effect=lambda client, texts, task_type: [
                [1.0] + [0.0] * 767 for _ in texts
            ],
        ),
    ):
        import asyncio

        asyncio.run(
            _run_ingest_pipeline(7, MagicMock()),
        )


class TestIngestPipeline:
    def test_happy_path_completes_and_swaps_claims(
        self, doc_repo, claim_repo, gcs
    ):
        _run(
            doc_repo,
            claim_repo,
            gcs,
            pages=[_page(1), _page(2)],
            extractions=[_extraction("claim A"), _extraction("claim B")],
        )

        update_kwargs = doc_repo.update.call_args.args[1]
        assert update_kwargs["status"] == ResearchDocStatus.COMPLETED.value
        assert update_kwargs["page_count"] == 2
        assert update_kwargs["failed_pages"] == []
        assert update_kwargs["doc_kind"] == "slide-deck"
        assert update_kwargs["language"] == "nl"
        assert claim_repo.bulk_insert_claims.await_count == 2
        claim_repo.delete_claims_except_run.assert_awaited_once_with(
            7, "run-1"
        )
        # Page rows were written for both pages.
        assert doc_repo.upsert_page.await_count == 2

    def test_failed_page_is_recorded_and_rest_kept(
        self, doc_repo, claim_repo, gcs
    ):
        _run(
            doc_repo,
            claim_repo,
            gcs,
            pages=[_page(1), _page(2)],
            extractions=[
                _extraction("claim A"),
                ExtractionError("page 2 exploded"),
            ],
        )

        update_kwargs = doc_repo.update.call_args.args[1]
        assert (
            update_kwargs["status"]
            == ResearchDocStatus.COMPLETED_WITH_ERRORS.value
        )
        assert update_kwargs["failed_pages"] == [2]
        assert claim_repo.bulk_insert_claims.await_count == 1

    def test_deleted_document_aborts_without_writes(
        self, doc_repo, claim_repo, gcs
    ):
        doc_repo.find_active_by_id.return_value = None

        _run(doc_repo, claim_repo, gcs, pages=[], extractions=[])

        doc_repo.update.assert_not_awaited()
        claim_repo.delete_claims_except_run.assert_not_awaited()

    def test_superseded_run_never_writes_terminal_state(
        self, doc_repo, claim_repo, gcs
    ):
        doc_repo.find_active_by_id.side_effect = [
            _document(ingest_run_id="run-1"),
            _document(ingest_run_id="run-2"),
        ]

        _run(
            doc_repo,
            claim_repo,
            gcs,
            pages=[_page(1)],
            extractions=[_extraction("claim A")],
        )

        doc_repo.update.assert_not_awaited()
        claim_repo.delete_claims_except_run.assert_not_awaited()

    def test_download_failure_marks_document_failed(
        self, doc_repo, claim_repo, gcs
    ):
        gcs.download_from_gcs.side_effect = lambda blob, dest: None

        _run(doc_repo, claim_repo, gcs, pages=[], extractions=[])

        update_kwargs = doc_repo.update.call_args.args[1]
        assert update_kwargs["status"] == ResearchDocStatus.FAILED.value
        assert "download" in update_kwargs["error_message"]

    def test_truncation_note_on_max_pages_cap(
        self, doc_repo, claim_repo, gcs
    ):
        with patch(
            "src.research_library.ingest.ingest_worker.config.MAX_PAGES", 1
        ):
            _run(
                doc_repo,
                claim_repo,
                gcs,
                pages=[_page(1)],
                extractions=[_extraction("claim A")],
                page_count=700,
            )

        update_kwargs = doc_repo.update.call_args.args[1]
        assert update_kwargs["page_count"] == 1
        assert "700" in update_kwargs["error_message"]
