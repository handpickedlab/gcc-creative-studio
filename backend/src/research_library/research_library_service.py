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

"""Business logic for the research document library.

Upload flow mirrors ``brand_guidelines``: the client asks for a v4 signed
GCS PUT URL, uploads directly to storage, then calls ``finalize_upload`` to
register the document and queue the background ingest worker on the
dedicated ``research_ingest_executor``.
"""

import asyncio
import hashlib
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import Depends, HTTPException, status

from src.auth.iam_signer_credentials_service import IamSignerCredentials
from src.common.dto.pagination_response_dto import PaginationResponseDto
from src.common.storage_service import GcsService
from src.research_library import config
from src.research_library.dto.research_library_dto import (
    FinalizeUploadDto,
    GenerateUploadUrlDto,
    GenerateUploadUrlResponseDto,
    UpdateDocumentDto,
)
from src.research_library.ingest.ingest_worker import run_ingest
from src.research_library.repository.research_document_repository import (
    ResearchDocumentRepository,
)
from src.research_library.schema.research_document_model import (
    PriorityTierEnum,
    ResearchDocStatus,
    ResearchDocumentModel,
)

logger = logging.getLogger(__name__)

# Accepted upload formats -> the MIME type we mint the signed URL with.
# Office formats are converted to PDF later in the pipeline (Unit 2);
# PNG/JPEG are treated as single-page documents.
ACCEPTED_EXTENSIONS: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": (
        "application/vnd.openxmlformats-officedocument"
        ".wordprocessingml.document"
    ),
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": (
        "application/vnd.openxmlformats-officedocument"
        ".presentationml.presentation"
    ),
    ".odp": "application/vnd.oasis.opendocument.presentation",
    ".png": "image/png",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
}

# Explicitly called out as unsupported (rather than falling through to the
# generic "unsupported format" message) so the reason is unambiguous.
_MSG_EXTENSION = ".msg"


def _extension_of(filename: str) -> str:
    """Returns the lowercased file extension, including the leading dot."""
    return os.path.splitext(filename)[1].lower()


class ResearchLibraryService:
    """Handles upload, listing, tier updates, deletion and reprocessing of
    research documents.
    """

    def __init__(
        self,
        repo: ResearchDocumentRepository = Depends(),
        gcs_service: GcsService = Depends(),
        iam_signer_credentials: IamSignerCredentials = Depends(),
    ):
        self.repo = repo
        self.gcs_service = gcs_service
        self.iam_signer_credentials = iam_signer_credentials

    async def generate_upload_url(
        self,
        request_dto: GenerateUploadUrlDto,
    ) -> GenerateUploadUrlResponseDto:
        """Validates the upload and mints a v4 signed PUT URL.

        Unsupported formats (MSG and anything not in ``ACCEPTED_EXTENSIONS``)
        and oversized files are rejected here, before a URL is ever issued,
        so no orphan blob is created for a file we will refuse to process.
        """
        extension = _extension_of(request_dto.filename)

        if extension == _MSG_EXTENSION:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "MSG email files are not supported by the research "
                    "library."
                ),
            )

        if extension not in ACCEPTED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Unsupported file format "
                    f"'{extension or request_dto.filename}'. Accepted "
                    "formats: PDF, DOCX, PPT, PPTX, ODP, PNG, JPEG."
                ),
            )

        if request_dto.size_bytes > config.MAX_UPLOAD_BYTES:
            max_mb = config.MAX_UPLOAD_BYTES // (1024 * 1024)
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File is too large. Maximum size is {max_mb}MB.",
            )

        file_uuid = uuid.uuid4()
        destination_blob_name = (
            f"research-library/global/{file_uuid}/{request_dto.filename}"
        )

        signed_url, gcs_uri = await asyncio.to_thread(
            self.iam_signer_credentials.generate_v4_upload_signed_url,
            destination_blob_name,
            request_dto.mime_type,
            self.gcs_service.bucket_name,
        )

        if not signed_url or not gcs_uri:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "Could not generate upload URL.",
            )

        return GenerateUploadUrlResponseDto(
            upload_url=signed_url, gcs_uri=gcs_uri
        )

    async def _hash_uploaded_blob(self, gcs_uri: str) -> str:
        """Streams the uploaded blob to compute its SHA-256 hash without
        loading the whole (up to ``RL_MAX_UPLOAD_BYTES``) file into memory.
        """

        def _hash() -> str:
            hasher = hashlib.sha256()
            for chunk in self.gcs_service.download_stream_from_gcs(gcs_uri):
                hasher.update(chunk)
            return hasher.hexdigest()

        try:
            return await asyncio.to_thread(_hash)
        except Exception as e:
            logger.error(
                "Failed to hash uploaded blob at %s: %s", gcs_uri, e
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not read the uploaded file from storage.",
            ) from e

    async def finalize_upload(
        self,
        request_dto: FinalizeUploadDto,
        executor: ThreadPoolExecutor,
    ) -> ResearchDocumentModel:
        """Registers an uploaded file and queues its ingest, or rejects it.

        Dedupe policy (Unit 1 decision): on a SHA-256 collision with an
        existing active document, we do NOT create a second PROCESSING row
        and do NOT queue a worker. Instead we create and return a new
        document row with status=REJECTED whose ``error_message`` points at
        the existing document ("Duplicate of <filename> (id <id>)"), so the
        duplicate is visible in the library list (R9) rather than silently
        dropped. The newly uploaded (duplicate-content) blob is then removed
        best-effort, since its bytes already exist under the original's
        ``gcs_uri``. The REJECTED row's own ``sha256`` is left NULL so it
        never collides with the active-row-scoped unique index on
        ``research_documents.sha256``.
        """
        sha256 = await self._hash_uploaded_blob(request_dto.gcs_uri)

        existing = await self.repo.find_by_sha256(sha256)
        if existing:
            await asyncio.to_thread(
                self.gcs_service.delete_blob_from_uri, request_dto.gcs_uri
            )
            rejected = ResearchDocumentModel(
                filename=request_dto.filename,
                mime_type=request_dto.mime_type,
                sha256=None,
                gcs_uri=request_dto.gcs_uri,
                status=ResearchDocStatus.REJECTED,
                error_message=(
                    f"Duplicate of {existing.filename} (id {existing.id})"
                ),
                priority_tier=PriorityTierEnum.PRIMARY,
            )
            return await self.repo.create(rejected)

        placeholder = ResearchDocumentModel(
            filename=request_dto.filename,
            mime_type=request_dto.mime_type,
            sha256=sha256,
            gcs_uri=request_dto.gcs_uri,
            status=ResearchDocStatus.PROCESSING,
            # Kind detection lands in Units 2/3; every accepted format
            # defaults to PRIMARY until then.
            priority_tier=PriorityTierEnum.PRIMARY,
            ingest_run_id=str(uuid.uuid4()),
        )
        created = await self.repo.create(placeholder)

        executor.submit(run_ingest, document_id=created.id)
        logger.info(
            "Research library ingest queued for document %s", created.id
        )

        return created

    async def list_documents(
        self,
        limit: int = 20,
        offset: int = 0,
    ) -> PaginationResponseDto[ResearchDocumentModel]:
        """Lists active (non-deleted) documents, newest first."""
        return await self.repo.list_documents(limit=limit, offset=offset)

    async def update_document(
        self,
        document_id: int,
        request_dto: UpdateDocumentDto,
    ) -> ResearchDocumentModel:
        """Applies a tier change (currently the only mutable field)."""
        document = await self.repo.find_active_by_id(document_id)
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Research document not found.",
            )

        updated = await self.repo.update(
            document_id,
            {"priority_tier": request_dto.priority_tier.value},
        )
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update research document.",
            )
        return updated

    async def get_page_image(
        self,
        document_id: int,
        page_no: int,
        thumb: bool = False,
    ) -> bytes:
        """Returns the rendered page image (or thumbnail) bytes for a
        citation viewer.
        """
        document = await self.repo.find_active_by_id(document_id)
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Research document not found.",
            )

        page = await self.repo.get_page(document_id, page_no)
        gcs_uri = (page.thumb_gcs_uri if thumb else page.image_gcs_uri) if page else None
        if not gcs_uri:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Page image not found.",
            )

        image_bytes = await asyncio.to_thread(
            self.gcs_service.download_bytes_from_gcs, gcs_uri
        )
        if not image_bytes:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Page image could not be read from storage.",
            )
        return image_bytes

    def _delete_document_assets_best_effort(self, gcs_uri: str) -> None:
        """Deletes every blob under a document's GCS prefix.

        Best-effort: covers the originally uploaded file plus any page and
        thumbnail images written under the same ``{uuid}/`` prefix by the
        ingest pipeline (Units 2/3). Failures are logged, never raised, so a
        GCS hiccup can't block the (already-committed) soft delete.
        """
        try:
            _, blob_name = gcs_uri.replace("gs://", "").split("/", 1)
            prefix = blob_name.rsplit("/", 1)[0]
            blobs = list(
                self.gcs_service.client.list_blobs(
                    self.gcs_service.bucket_name, prefix=f"{prefix}/"
                ),
            )
            for blob in blobs:
                blob.delete()
        except Exception as e:
            logger.warning(
                "Best-effort GCS cleanup failed for %s: %s", gcs_uri, e
            )

    async def delete_document(self, document_id: int) -> None:
        """Soft-deletes a document and best-effort cleans up its GCS assets."""
        document = await self.repo.find_active_by_id(document_id)
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Research document not found.",
            )

        await self.repo.soft_delete(document_id)
        await asyncio.to_thread(
            self._delete_document_assets_best_effort, document.gcs_uri
        )

    async def reprocess_document(
        self,
        document_id: int,
        executor: ThreadPoolExecutor,
    ) -> ResearchDocumentModel:
        """Resets a document to PROCESSING under a new ingest run and
        resubmits it to the worker pool.

        Guarded against re-triggering a run that is already in flight; the
        actual atomic swap of claims (new run written, old run deleted only
        on success) is implemented by the Unit 2/3 pipeline body.
        """
        document = await self.repo.find_active_by_id(document_id)
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Research document not found.",
            )

        if document.status == ResearchDocStatus.PROCESSING:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Document is already processing.",
            )

        new_run_id = str(uuid.uuid4())
        updated = await self.repo.update(
            document_id,
            {
                "status": ResearchDocStatus.PROCESSING.value,
                "ingest_run_id": new_run_id,
                "error_message": None,
                "failed_pages": [],
            },
        )
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to reprocess research document.",
            )

        executor.submit(run_ingest, document_id=document_id)
        logger.info(
            "Research library reprocess queued for document %s (run %s)",
            document_id,
            new_run_id,
        )

        return updated
