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

"""Repository for per-language translation profiles."""

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.base_repository import BaseRepository
from src.database import get_db
from src.translations.schema.language_config_model import (
    TranslationLanguageConfig,
    TranslationLanguageConfigModel,
)


class LanguageConfigRepository(
    BaseRepository[TranslationLanguageConfig, TranslationLanguageConfigModel]
):
    """Database operations for the per-language localization profiles."""

    def __init__(self, db: AsyncSession = Depends(get_db)):
        super().__init__(
            model=TranslationLanguageConfig,
            schema=TranslationLanguageConfigModel,
            db=db,
        )

    async def list_all(self) -> list[TranslationLanguageConfigModel]:
        result = await self.db.execute(select(self.model))
        return [self.schema.model_validate(i) for i in result.scalars().all()]

    async def get_by_language(
        self, language: str
    ) -> TranslationLanguageConfigModel | None:
        result = await self.db.execute(
            select(self.model).where(self.model.language == language),
        )
        item = result.scalar_one_or_none()
        return self.schema.model_validate(item) if item else None

    async def get_by_languages(
        self, languages: list[str]
    ) -> dict[str, TranslationLanguageConfigModel]:
        """Returns a {language: profile} map for the given markets."""
        if not languages:
            return {}
        result = await self.db.execute(
            select(self.model).where(self.model.language.in_(languages)),
        )
        return {
            i.language: self.schema.model_validate(i)
            for i in result.scalars().all()
        }

    async def upsert(
        self, language: str, data: dict
    ) -> TranslationLanguageConfigModel:
        """Creates or updates the single profile row for a language."""
        result = await self.db.execute(
            select(self.model).where(self.model.language == language),
        )
        row = result.scalar_one_or_none()
        if row:
            for key, value in data.items():
                if key != "language":
                    setattr(row, key, value)
        else:
            row = self.model(language=language, **{
                k: v for k, v in data.items() if k != "language"
            })
            self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return self.schema.model_validate(row)
