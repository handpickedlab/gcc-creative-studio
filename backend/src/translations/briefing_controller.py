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

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status

from src.auth.auth_guard import RoleChecker
from src.translations.briefing_service import BriefingService
from src.translations.dto.briefing_dto import (
    BriefingInputDto,
    MarketInfo,
    ParseResultDto,
    SaveBriefingRequestDto,
    TmImportResultDto,
    TranslateBriefingRequestDto,
    TranslateBriefingResponseDto,
)
from src.translations.markets import MARKETS
from src.translations.schema.briefing_model import BriefingModel
from src.users.user_model import UserRoleEnum

router = APIRouter(
    prefix="/api/briefings",
    tags=["Briefings"],
    responses={404: {"description": "Not found"}},
    dependencies=[
        Depends(
            RoleChecker(allowed_roles=[UserRoleEnum.ADMIN, UserRoleEnum.USER])
        )
    ],
)


@router.get("/markets", response_model=list[MarketInfo])
async def list_markets():
    return [MarketInfo(code=code, label=label) for code, label in MARKETS.items()]


@router.post("/upload", response_model=ParseResultDto)
async def upload_briefing(
    file: UploadFile = File(...),
    sheet_name: str | None = Form(None),
    request_index: int | None = Form(None),
    service: BriefingService = Depends(),
):
    """Parses an uploaded xlsx. Without a request_index it returns the sheets
    and the requests found; with one it returns the parsed briefing."""
    content = await file.read()
    return service.parse_upload(content, sheet_name, request_index)


@router.post("/import-tm", response_model=TmImportResultDto)
async def import_translation_memories(
    file: UploadFile = File(...),
    service: BriefingService = Depends(),
):
    content = await file.read()
    return await service.import_translation_memories(content)


@router.post("/translate", response_model=TranslateBriefingResponseDto)
async def translate_briefing(
    request: TranslateBriefingRequestDto,
    service: BriefingService = Depends(),
):
    translations = await service.translate_briefing(
        request.briefing, request.markets
    )
    return TranslateBriefingResponseDto(translations=translations)


@router.post("/export")
async def export_briefing(
    dto: SaveBriefingRequestDto,
    service: BriefingService = Depends(),
):
    """Builds an xlsx (Copy Sheet layout) from a briefing + its translations."""
    content = service.export_xlsx(dto.briefing, dto.translations)
    safe_name = (dto.briefing.name or "briefing").replace("/", "-")[:60]
    return Response(
        content=content,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}.xlsx"'
        },
    )


@router.post("", response_model=BriefingModel, status_code=status.HTTP_201_CREATED)
async def save_briefing(
    dto: SaveBriefingRequestDto,
    service: BriefingService = Depends(),
):
    return await service.save_briefing(dto)


@router.get("", response_model=list[BriefingModel])
async def list_briefings(service: BriefingService = Depends()):
    return await service.list_briefings()


@router.get("/{briefing_id}")
async def get_briefing(briefing_id: int, service: BriefingService = Depends()):
    return await service.get_briefing_with_translations(briefing_id)
