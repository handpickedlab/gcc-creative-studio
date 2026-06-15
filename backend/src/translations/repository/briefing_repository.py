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
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from src.database import get_db
from src.translations.schema.briefing_model import (
    Briefing,
    BriefingModel,
    BriefingTranslation,
    BriefingTranslationModel,
)


class BriefingRepository:
    """Persistence for briefings and their per-market translations."""

    def __init__(self, db: AsyncSession = Depends(get_db)):
        self.db = db

    async def create_briefing(
        self, name: str, source_market: str, meta: dict, segments: list[dict]
    ) -> BriefingModel:
        item = Briefing(
            name=name,
            source_market=source_market,
            meta=meta,
            segments=segments,
        )
        self.db.add(item)
        await self.db.commit()
        await self.db.refresh(item)
        return BriefingModel.model_validate(item)

    async def upsert_translation(
        self, briefing_id: int, market: str, segments: list[dict]
    ) -> None:
        # Replace any existing translation for this (briefing, market).
        await self.db.execute(
            delete(BriefingTranslation).where(
                BriefingTranslation.briefing_id == briefing_id,
                BriefingTranslation.market == market,
            )
        )
        self.db.add(
            BriefingTranslation(
                briefing_id=briefing_id, market=market, segments=segments
            )
        )

    async def commit(self) -> None:
        await self.db.commit()

    async def list_briefings(self, limit: int = 100) -> list[BriefingModel]:
        result = await self.db.execute(
            select(Briefing).order_by(Briefing.created_at.desc()).limit(limit)
        )
        return [BriefingModel.model_validate(b) for b in result.scalars().all()]

    async def get_briefing(self, briefing_id: int) -> BriefingModel | None:
        result = await self.db.execute(
            select(Briefing).where(Briefing.id == briefing_id)
        )
        item = result.scalar_one_or_none()
        return BriefingModel.model_validate(item) if item else None

    async def get_translations(
        self, briefing_id: int
    ) -> list[BriefingTranslationModel]:
        result = await self.db.execute(
            select(BriefingTranslation).where(
                BriefingTranslation.briefing_id == briefing_id
            )
        )
        return [
            BriefingTranslationModel.model_validate(t)
            for t in result.scalars().all()
        ]
