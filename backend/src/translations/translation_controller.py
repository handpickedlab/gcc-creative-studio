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

from fastapi import APIRouter, Depends, status

from src.auth.auth_guard import RoleChecker
from src.translations.dto.translation_dto import (
    GlossaryTermCreateDto,
    GlossaryTermUpdateDto,
    TranslateRequestDto,
    TranslateResponseDto,
)
from src.translations.schema.glossary_term_model import GlossaryTermModel
from src.translations.translation_service import TranslationService
from src.users.user_model import UserRoleEnum

router = APIRouter(
    prefix="/api/translations",
    tags=["Translations"],
    responses={404: {"description": "Not found"}},
    dependencies=[
        Depends(
            RoleChecker(
                allowed_roles=[
                    UserRoleEnum.ADMIN,
                    UserRoleEnum.USER,
                ],
            ),
        ),
    ],
)


@router.post(
    "/translate",
    response_model=TranslateResponseDto,
    summary="Translate text into one or more languages using Gemini",
)
async def translate_endpoint(
    request: TranslateRequestDto,
    service: TranslationService = Depends(),
):
    """Translates the given text into each requested language, applying the
    stored glossary as strict term overrides."""
    return await service.translate(request)


@router.get(
    "/glossary",
    response_model=list[GlossaryTermModel],
    summary="List all glossary terms",
)
async def list_glossary(service: TranslationService = Depends()):
    return await service.list_terms()


@router.post(
    "/glossary",
    response_model=GlossaryTermModel,
    status_code=status.HTTP_201_CREATED,
    summary="Create a glossary term",
)
async def create_glossary_term(
    dto: GlossaryTermCreateDto,
    service: TranslationService = Depends(),
):
    return await service.create_term(dto)


@router.put(
    "/glossary/{term_id}",
    response_model=GlossaryTermModel,
    summary="Update a glossary term",
)
async def update_glossary_term(
    term_id: int,
    dto: GlossaryTermUpdateDto,
    service: TranslationService = Depends(),
):
    return await service.update_term(term_id, dto)


@router.delete(
    "/glossary/{term_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a glossary term",
)
async def delete_glossary_term(
    term_id: int,
    service: TranslationService = Depends(),
):
    await service.delete_term(term_id)
