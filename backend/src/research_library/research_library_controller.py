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

"""API routes for the research document library."""

from fastapi import APIRouter, Depends, Request, Response, status

from src.auth.auth_guard import RoleChecker
from src.common.dto.pagination_response_dto import PaginationResponseDto
from src.research_library.dto.research_library_dto import (
    FinalizeUploadDto,
    GenerateUploadUrlDto,
    GenerateUploadUrlResponseDto,
    UpdateDocumentDto,
)
from src.research_library.research_library_service import (
    ResearchLibraryService,
)
from src.research_library.schema.research_document_model import (
    ResearchDocumentModel,
)
from src.users.user_model import UserRoleEnum

router = APIRouter(
    prefix="/api/research-library",
    tags=["Research Library"],
    dependencies=[
        Depends(
            RoleChecker(
                allowed_roles=[UserRoleEnum.ADMIN, UserRoleEnum.USER],
            ),
        ),
    ],
)


@router.post(
    "/generate-upload-url",
    response_model=GenerateUploadUrlResponseDto,
    summary="Get a signed URL for direct upload to the research library",
)
async def generate_upload_url(
    request_dto: GenerateUploadUrlDto,
    service: ResearchLibraryService = Depends(),
):
    """Generates a secure, short-lived URL that the client can use to upload
    a research document directly to Google Cloud Storage.
    """
    return await service.generate_upload_url(request_dto)


@router.post(
    "/finalize-upload",
    response_model=ResearchDocumentModel,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Finalize an upload and start (or skip) ingest",
)
async def finalize_upload(
    request: Request,
    request_dto: FinalizeUploadDto,
    service: ResearchLibraryService = Depends(),
):
    """Called after the client has successfully PUT the file to the signed
    URL. Registers the document (or a REJECTED duplicate marker) and, for a
    new document, queues the background ingest worker.
    """
    executor = request.app.state.research_ingest_executor
    return await service.finalize_upload(request_dto, executor)


@router.get(
    "/documents",
    response_model=PaginationResponseDto[ResearchDocumentModel],
    summary="List research documents",
)
async def list_documents(
    limit: int = 20,
    offset: int = 0,
    service: ResearchLibraryService = Depends(),
):
    """Lists active documents, newest first."""
    return await service.list_documents(limit=limit, offset=offset)


@router.patch(
    "/documents/{document_id}",
    response_model=ResearchDocumentModel,
    summary="Update a research document's priority tier",
)
async def update_document(
    document_id: int,
    request_dto: UpdateDocumentDto,
    service: ResearchLibraryService = Depends(),
):
    return await service.update_document(document_id, request_dto)


@router.delete(
    "/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a research document",
)
async def delete_document(
    document_id: int,
    service: ResearchLibraryService = Depends(),
):
    await service.delete_document(document_id)


@router.post(
    "/documents/{document_id}/reprocess",
    response_model=ResearchDocumentModel,
    summary="Re-run ingest for a research document",
)
async def reprocess_document(
    request: Request,
    document_id: int,
    service: ResearchLibraryService = Depends(),
):
    executor = request.app.state.research_ingest_executor
    return await service.reprocess_document(document_id, executor)


@router.get(
    "/documents/{document_id}/pages/{page_no}/image",
    summary="The rendered page image (or thumbnail) behind a citation",
)
async def get_page_image(
    document_id: int,
    page_no: int,
    thumb: bool = False,
    service: ResearchLibraryService = Depends(),
):
    """Streams the rendered page image so the frontend can show the original
    slide next to a cited claim.
    """
    image_bytes = await service.get_page_image(document_id, page_no, thumb)
    return Response(
        content=image_bytes,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=3600"},
    )
