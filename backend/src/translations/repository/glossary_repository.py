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

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.common.base_repository import BaseRepository
from src.database import get_db
from src.translations.schema.glossary_term_model import (
    GlossaryTerm,
    GlossaryTermModel,
)


class GlossaryRepository(BaseRepository[GlossaryTerm, GlossaryTermModel]):
    """Handles database operations for GlossaryTerm objects."""

    def __init__(self, db: AsyncSession = Depends(get_db)):
        super().__init__(model=GlossaryTerm, schema=GlossaryTermModel, db=db)

    async def get_by_language_and_source(
        self, language: str, source: str
    ) -> GlossaryTermModel | None:
        """Finds a glossary term by its unique (language, source) pair."""
        query = select(self.model).where(
            self.model.language == language,
            self.model.source == source,
        )
        result = await self.db.execute(query)
        item = result.scalar_one_or_none()
        if not item:
            return None
        return self.schema.model_validate(item)
