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

"""Repository for the raw -> canonical tag/metric alias mapping.

The mapping is deliberately separate from claims (claims keep their raw tags
forever) so canonicalization can be rebuilt at any time without re-running
any LLM extraction.
"""

from collections import Counter

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.base_repository import BaseRepository
from src.database import get_db
from src.research_library.schema.research_document_model import (
    ResearchClaim,
    TagAlias,
    TagAliasModel,
)


class TagAliasRepository(BaseRepository[TagAlias, TagAliasModel]):
    """Handles database operations for tag/metric aliases."""

    def __init__(self, db: AsyncSession = Depends(get_db)):
        super().__init__(model=TagAlias, schema=TagAliasModel, db=db)

    async def list_aliases(self) -> list[TagAliasModel]:
        result = await self.db.execute(select(self.model))
        return [
            self.schema.model_validate(alias)
            for alias in result.scalars().all()
        ]

    async def upsert_alias(
        self, raw: str, canonical: str, kind: str
    ) -> TagAliasModel:
        result = await self.db.execute(
            select(self.model).where(self.model.raw == raw),
        )
        alias = result.scalar_one_or_none()
        if alias:
            alias.canonical = canonical
            alias.kind = kind
        else:
            alias = TagAlias(raw=raw, canonical=canonical, kind=kind)
            self.db.add(alias)
        await self.db.commit()
        await self.db.refresh(alias)
        return self.schema.model_validate(alias)

    async def distinct_raw_tags(self) -> tuple[Counter, Counter]:
        """Returns (tag_counts, metric_counts) across all claims."""
        result = await self.db.execute(
            select(ResearchClaim.raw_tags, ResearchClaim.metric),
        )
        tag_counts: Counter = Counter()
        metric_counts: Counter = Counter()
        for raw_tags, metric in result.all():
            for tag in raw_tags or []:
                tag_counts[tag.strip().lower()] += 1
            if metric:
                metric_counts[metric.strip().lower()] += 1
        return tag_counts, metric_counts

    async def iter_claim_tag_rows(self) -> list[tuple[int, list, str | None]]:
        """(claim_id, raw_tags, metric) for every claim, for re-resolution."""
        result = await self.db.execute(
            select(
                ResearchClaim.id,
                ResearchClaim.raw_tags,
                ResearchClaim.metric,
            ),
        )
        return [tuple(row) for row in result.all()]

    async def bulk_update_canonical_tags(
        self, updates: dict[int, list[str]]
    ) -> int:
        """Applies {claim_id: canonical_tags} in one transaction."""
        if not updates:
            return 0
        for claim_id, canonical_tags in updates.items():
            await self.db.execute(
                ResearchClaim.__table__.update()
                .where(ResearchClaim.id == claim_id)
                .values(canonical_tags=canonical_tags),
            )
        await self.db.commit()
        return len(updates)
