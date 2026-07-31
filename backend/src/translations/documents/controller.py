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
"""REST endpoints for document translation jobs (annual reports)."""

import io
import urllib.parse

from fastapi import APIRouter, Depends, File, UploadFile, status
from fastapi.responses import StreamingResponse

from src.auth.auth_guard import RoleChecker, get_current_user
from src.translations.documents.dto.document_translation_dto import (
    StartTranslationDto,
    UpdateSegmentDto,
)
from src.translations.documents.schema.document_translation_model import (
    DocumentTranslationJobModel,
    DocumentTranslationSegmentModel,
)
from src.translations.documents.service import DocumentTranslationService
from src.users.user_model import UserModel, UserRoleEnum

router = APIRouter(
    prefix="/api/document-translations",
    tags=["Document Translations"],
    dependencies=[
        Depends(
            RoleChecker(
                allowed_roles=[UserRoleEnum.ADMIN, UserRoleEnum.USER]
            )
        )
    ],
)

_DOCX_MIME = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


@router.post(
    "",
    response_model=DocumentTranslationJobModel,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a .docx and create a translation job (preflight)",
)
async def create_job(
    file: UploadFile = File(...),
    service: DocumentTranslationService = Depends(),
    user: UserModel = Depends(get_current_user),
):
    content = await file.read()
    return await service.create_job(
        filename=file.filename or "document.docx",
        content=content,
        user_email=user.email,
    )


@router.get(
    "",
    response_model=list[DocumentTranslationJobModel],
    summary="List recent document translation jobs",
)
async def list_jobs(service: DocumentTranslationService = Depends()):
    return await service.list_jobs()


@router.get(
    "/{job_id}",
    response_model=DocumentTranslationJobModel,
    summary="Poll a job for status, progress and QA findings",
)
async def get_job(
    job_id: str, service: DocumentTranslationService = Depends()
):
    return await service.get_job(job_id)


@router.post(
    "/{job_id}/translate",
    response_model=DocumentTranslationJobModel,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start translating in the background; poll the job for progress",
)
async def start_translation(
    job_id: str,
    dto: StartTranslationDto,
    service: DocumentTranslationService = Depends(),
):
    return await service.start_translation(job_id, dto)


@router.get(
    "/{job_id}/segments",
    response_model=list[DocumentTranslationSegmentModel],
    summary="List a job's segments for review (optionally by status)",
)
async def list_segments(
    job_id: str,
    status_filter: str | None = None,
    service: DocumentTranslationService = Depends(),
):
    return await service.list_segments(job_id, status_filter)


@router.patch(
    "/{job_id}/segments/{seg_index}",
    response_model=DocumentTranslationSegmentModel,
    summary="Edit or approve one segment's translation",
)
async def update_segment(
    job_id: str,
    seg_index: int,
    dto: UpdateSegmentDto,
    service: DocumentTranslationService = Depends(),
):
    return await service.update_segment(job_id, seg_index, dto)


@router.post(
    "/{job_id}/export",
    summary="Apply reviewed translations and download the translated .docx",
)
async def export(
    job_id: str, service: DocumentTranslationService = Depends()
):
    filename, data = await service.export(job_id)
    quoted = urllib.parse.quote(filename)
    return StreamingResponse(
        io.BytesIO(data),
        media_type=_DOCX_MIME,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quoted}"
        },
    )
