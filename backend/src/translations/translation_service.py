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

import logging

from fastapi import Depends, HTTPException, status

from src.multimodal.gemini_service import GeminiService
from src.translations.dto.translation_dto import (
    GlossaryTermCreateDto,
    GlossaryTermUpdateDto,
    TranslateRequestDto,
    TranslateResponseDto,
    TranslationResult,
)
from src.translations.repository.glossary_repository import GlossaryRepository
from src.translations.schema.glossary_term_model import GlossaryTermModel

logger = logging.getLogger(__name__)


class TranslationService:
    """Business logic for text translation and glossary management."""

    def __init__(
        self,
        repo: GlossaryRepository = Depends(),
        gemini_service: GeminiService = Depends(),
    ):
        self.repo = repo
        self.gemini_service = gemini_service

    # --- Glossary CRUD ---------------------------------------------------

    async def list_terms(self) -> list[GlossaryTermModel]:
        return await self.repo.find_all(limit=1000)

    async def create_term(
        self, dto: GlossaryTermCreateDto
    ) -> GlossaryTermModel:
        existing = await self.repo.get_by_language_and_source(
            dto.language, dto.source
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"A glossary term for '{dto.source}' already exists "
                    f"in the {dto.language} dictionary."
                ),
            )
        return await self.repo.create(dto)

    async def update_term(
        self, term_id: int, dto: GlossaryTermUpdateDto
    ) -> GlossaryTermModel:
        updated = await self.repo.update(term_id, dto)
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Glossary term {term_id} not found.",
            )
        return updated

    async def delete_term(self, term_id: int) -> None:
        deleted = await self.repo.delete(term_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Glossary term {term_id} not found.",
            )

    # --- Translation -----------------------------------------------------

    def _build_prompt(
        self,
        text: str,
        language: str,
        glossary: list[GlossaryTermModel],
        tone: str | None,
    ) -> str:
        """Builds the Gemini prompt for a single target language."""
        lines = [
            f"Translate the following text into {language}.",
            "Return ONLY the translated text, with no explanations, "
            "quotes, or extra commentary.",
        ]
        if tone:
            lines.append(f"Use a {tone} tone.")
        if glossary:
            lines.append(
                "Apply this glossary strictly. Whenever a source term "
                "appears, translate it exactly as specified (adjust "
                "grammar/inflection to fit the sentence naturally):"
            )
            for term in glossary:
                lines.append(f'- "{term.source}" -> "{term.target}"')
        lines.append("")
        lines.append("Text to translate:")
        lines.append(text)
        return "\n".join(lines)

    async def translate(
        self, request: TranslateRequestDto
    ) -> TranslateResponseDto:
        all_terms = await self.repo.find_all(limit=1000)

        results: list[TranslationResult] = []
        for language in request.target_languages:
            # Each language uses only its own dictionary.
            glossary = [t for t in all_terms if t.language == language]
            prompt = self._build_prompt(
                request.text, language, glossary, request.tone
            )
            try:
                translation = self.gemini_service.generate_text(prompt)
            except Exception as e:
                logger.error("Translation to %s failed: %s", language, e)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Translation to {language} failed: {e}",
                )
            results.append(
                TranslationResult(language=language, translation=translation)
            )

        return TranslateResponseDto(results=results)
