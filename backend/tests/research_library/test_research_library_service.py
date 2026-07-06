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

"""Tests for ResearchLibraryService."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from src.research_library import config
from src.research_library.dto.research_library_dto import (
    FinalizeUploadDto,
    GenerateUploadUrlDto,
    UpdateDocumentDto,
)
from src.research_library.research_library_service import (
    ResearchLibraryService,
)
from src.research_library.schema.research_document_model import (
    PriorityTierEnum,
    ResearchDocStatus,
    ResearchDocumentModel,
)


@pytest.fixture(name="mock_repo")
def fixture_mock_repo():
    """Provides a mocked ResearchDocumentRepository."""
    return AsyncMock()


@pytest.fixture(name="mock_gcs_service")
def fixture_mock_gcs_service():
    """Provides a mocked GcsService with a fixed bucket name."""
    gcs = MagicMock()
    gcs.bucket_name = "test-bucket"
    gcs.client = MagicMock()
    gcs.client.list_blobs.return_value = []
    return gcs


@pytest.fixture(name="mock_iam_signer")
def fixture_mock_iam_signer():
    """Provides a mocked IamSignerCredentials."""
    signer = MagicMock()
    signer.generate_v4_upload_signed_url.return_value = (
        "https://signed.example/upload",
        "gs://test-bucket/research-library/global/uuid1/deck.pdf",
    )
    return signer


@pytest.fixture(name="service")
def fixture_service(mock_repo, mock_gcs_service, mock_iam_signer):
    """Provides a ResearchLibraryService with mocked dependencies."""
    return ResearchLibraryService(
        repo=mock_repo,
        gcs_service=mock_gcs_service,
        iam_signer_credentials=mock_iam_signer,
    )


def make_document(**kwargs) -> ResearchDocumentModel:
    defaults = {
        "id": 1,
        "filename": "original.pdf",
        "mime_type": "application/pdf",
        "sha256": "hash-abc",
        "gcs_uri": "gs://test-bucket/research-library/global/uuid0/original.pdf",
        "status": ResearchDocStatus.COMPLETED,
    }
    defaults.update(kwargs)
    return ResearchDocumentModel(**defaults)


class TestGenerateUploadUrl:
    """Tests for ResearchLibraryService.generate_upload_url."""

    @pytest.mark.anyio
    async def test_rejects_msg(self, service):
        request_dto = GenerateUploadUrlDto(
            filename="notes.msg",
            mime_type="application/vnd.ms-outlook",
            size_bytes=1024,
        )

        with pytest.raises(HTTPException) as exc_info:
            await service.generate_upload_url(request_dto)

        assert exc_info.value.status_code == 400
        assert "MSG" in exc_info.value.detail

    @pytest.mark.anyio
    async def test_rejects_unknown_extension(self, service):
        request_dto = GenerateUploadUrlDto(
            filename="archive.zip",
            mime_type="application/zip",
            size_bytes=1024,
        )

        with pytest.raises(HTTPException) as exc_info:
            await service.generate_upload_url(request_dto)

        assert exc_info.value.status_code == 400
        assert "Unsupported file format" in exc_info.value.detail

    @pytest.mark.anyio
    async def test_rejects_oversized_file(self, service):
        request_dto = GenerateUploadUrlDto(
            filename="monster.pdf",
            mime_type="application/pdf",
            size_bytes=config.MAX_UPLOAD_BYTES + 1,
        )

        with pytest.raises(HTTPException) as exc_info:
            await service.generate_upload_url(request_dto)

        assert exc_info.value.status_code == 413

    @pytest.mark.anyio
    async def test_accepts_supported_format_and_mints_signed_url(
        self, service, mock_iam_signer
    ):
        request_dto = GenerateUploadUrlDto(
            filename="deck.pdf",
            mime_type="application/pdf",
            size_bytes=1024,
        )

        result = await service.generate_upload_url(request_dto)

        assert result.upload_url == "https://signed.example/upload"
        assert result.gcs_uri.startswith("gs://test-bucket/")
        mock_iam_signer.generate_v4_upload_signed_url.assert_called_once()


class TestFinalizeUpload:
    """Tests for ResearchLibraryService.finalize_upload."""

    @pytest.mark.anyio
    async def test_duplicate_creates_rejected_row_without_new_processing_row(
        self, service, mock_repo, mock_gcs_service
    ):
        mock_gcs_service.download_stream_from_gcs.return_value = iter(
            [b"same-bytes"]
        )
        existing = make_document(id=1, filename="original.pdf")
        mock_repo.find_by_sha256.return_value = existing

        captured = {}

        async def fake_create(model):
            captured["model"] = model
            return model.model_copy(update={"id": 99})

        mock_repo.create.side_effect = fake_create
        executor = MagicMock()

        request_dto = FinalizeUploadDto(
            gcs_uri="gs://test-bucket/research-library/global/uuid9/dup.pdf",
            filename="dup.pdf",
            mime_type="application/pdf",
        )

        result = await service.finalize_upload(request_dto, executor)

        assert result.status == ResearchDocStatus.REJECTED
        assert "original.pdf" in result.error_message
        assert "id 1" in result.error_message
        # No second PROCESSING row: create() was called exactly once, for
        # the REJECTED marker, with no sha256 set on it.
        mock_repo.create.assert_called_once()
        assert captured["model"].sha256 is None
        assert captured["model"].status == ResearchDocStatus.REJECTED
        # No worker queued for a rejected duplicate.
        executor.submit.assert_not_called()
        # The duplicate-content blob is cleaned up best-effort.
        mock_gcs_service.delete_blob_from_uri.assert_called_once_with(
            request_dto.gcs_uri
        )

    @pytest.mark.anyio
    async def test_new_document_gets_default_tier_and_queues_worker(
        self, service, mock_repo, mock_gcs_service
    ):
        mock_gcs_service.download_stream_from_gcs.return_value = iter(
            [b"fresh-bytes"]
        )
        mock_repo.find_by_sha256.return_value = None

        async def fake_create(model):
            return model.model_copy(update={"id": 42})

        mock_repo.create.side_effect = fake_create
        executor = MagicMock()

        request_dto = FinalizeUploadDto(
            gcs_uri="gs://test-bucket/research-library/global/uuid2/deck.pdf",
            filename="deck.pdf",
            mime_type="application/pdf",
        )

        result = await service.finalize_upload(request_dto, executor)

        assert result.id == 42
        assert result.status == ResearchDocStatus.PROCESSING
        assert result.priority_tier == PriorityTierEnum.PRIMARY
        assert result.ingest_run_id
        executor.submit.assert_called_once()
        _, submit_kwargs = executor.submit.call_args
        assert submit_kwargs["document_id"] == 42


class TestUpdateDocument:
    """Tests for ResearchLibraryService.update_document (tier PATCH)."""

    @pytest.mark.anyio
    async def test_persists_new_tier(self, service, mock_repo):
        existing = make_document(id=5, priority_tier=PriorityTierEnum.PRIMARY)
        mock_repo.find_active_by_id.return_value = existing
        updated = existing.model_copy(
            update={"priority_tier": PriorityTierEnum.BACKGROUND}
        )
        mock_repo.update.return_value = updated

        request_dto = UpdateDocumentDto(priority_tier=PriorityTierEnum.BACKGROUND)
        result = await service.update_document(5, request_dto)

        assert result.priority_tier == PriorityTierEnum.BACKGROUND
        mock_repo.update.assert_called_once_with(
            5, {"priority_tier": "background"}
        )

    @pytest.mark.anyio
    async def test_not_found(self, service, mock_repo):
        mock_repo.find_active_by_id.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await service.update_document(
                999, UpdateDocumentDto(priority_tier=PriorityTierEnum.SUPPORTING)
            )

        assert exc_info.value.status_code == 404
        mock_repo.update.assert_not_called()


class TestDeleteDocument:
    """Tests for ResearchLibraryService.delete_document."""

    @pytest.mark.anyio
    async def test_soft_deletes_and_cleans_up_gcs_prefix(
        self, service, mock_repo, mock_gcs_service
    ):
        existing = make_document(
            id=7,
            gcs_uri="gs://test-bucket/research-library/global/uuid7/f.pdf",
        )
        mock_repo.find_active_by_id.return_value = existing
        mock_repo.soft_delete.return_value = True

        await service.delete_document(7)

        mock_repo.soft_delete.assert_called_once_with(7)
        mock_gcs_service.client.list_blobs.assert_called_once_with(
            "test-bucket",
            prefix="research-library/global/uuid7/",
        )

    @pytest.mark.anyio
    async def test_not_found(self, service, mock_repo):
        mock_repo.find_active_by_id.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await service.delete_document(404)

        assert exc_info.value.status_code == 404
        mock_repo.soft_delete.assert_not_called()


class TestReprocessDocument:
    """Tests for ResearchLibraryService.reprocess_document."""

    @pytest.mark.anyio
    async def test_resets_status_and_run_id(self, service, mock_repo):
        existing = make_document(
            id=3,
            status=ResearchDocStatus.FAILED,
            ingest_run_id="old-run",
        )
        mock_repo.find_active_by_id.return_value = existing
        mock_repo.update.return_value = existing.model_copy(
            update={
                "status": ResearchDocStatus.PROCESSING,
                "ingest_run_id": "new-run",
            },
        )
        executor = MagicMock()

        result = await service.reprocess_document(3, executor)

        assert result.status == ResearchDocStatus.PROCESSING
        assert result.ingest_run_id == "new-run"
        executor.submit.assert_called_once()
        update_call_args = mock_repo.update.call_args[0]
        assert update_call_args[0] == 3
        assert update_call_args[1]["status"] == ResearchDocStatus.PROCESSING.value
        assert update_call_args[1]["ingest_run_id"] != "old-run"

    @pytest.mark.anyio
    async def test_guards_against_reprocessing_while_processing(
        self, service, mock_repo
    ):
        existing = make_document(id=3, status=ResearchDocStatus.PROCESSING)
        mock_repo.find_active_by_id.return_value = existing
        executor = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await service.reprocess_document(3, executor)

        assert exc_info.value.status_code == 409
        mock_repo.update.assert_not_called()
        executor.submit.assert_not_called()

    @pytest.mark.anyio
    async def test_not_found(self, service, mock_repo):
        mock_repo.find_active_by_id.return_value = None
        executor = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await service.reprocess_document(999, executor)

        assert exc_info.value.status_code == 404
