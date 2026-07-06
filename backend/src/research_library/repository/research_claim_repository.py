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

"""Repository for extracted research claims.

Claims are append-only during ingest; ``delete_claims_by_run`` exists for the
Unit 3 reprocess flow's atomic swap (a new ``ingest_run_id`` is written in
full before the previous run's claims are deleted, so a failed reprocess
never leaves a document with zero claims).
"""

from fastapi import Depends
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.base_repository import BaseRepository
from src.database import get_db
from src.research_library.schema.research_document_model import (
    ResearchClaim,
    ResearchClaimModel,
)


class ResearchClaimRepository(BaseRepository[ResearchClaim, ResearchClaimModel]):
    """Handles database operations for research claims."""

    def __init__(self, db: AsyncSession = Depends(get_db)):
        super().__init__(model=ResearchClaim, schema=ResearchClaimModel, db=db)

    async def bulk_insert_claims(
        self,
        claims: list[ResearchClaimModel],
    ) -> list[ResearchClaimModel]:
        """Inserts a batch of claims in one transaction."""
        if not claims:
            return []

        db_claims = [
            ResearchClaim(**claim.model_dump(exclude={"id"}, exclude_unset=True))
            for claim in claims
        ]
        self.db.add_all(db_claims)
        await self.db.commit()
        for db_claim in db_claims:
            await self.db.refresh(db_claim)
        return [self.schema.model_validate(c) for c in db_claims]

    async def list_by_document(
        self, document_id: int
    ) -> list[ResearchClaimModel]:
        """Lists all claims for a document, regardless of ingest run."""
        result = await self.db.execute(
            select(self.model).where(self.model.document_id == document_id),
        )
        claims = result.scalars().all()
        return [self.schema.model_validate(c) for c in claims]

    async def delete_claims_by_run(
        self,
        document_id: int,
        ingest_run_id: str,
    ) -> int:
        """Deletes all claims for a document belonging to one ingest run.

        Used to drop a superseded run's claims once a reprocess's new run has
        finished writing successfully (the atomic swap).
        """
        result = await self.db.execute(
            delete(self.model)
            .where(self.model.document_id == document_id)
            .where(self.model.ingest_run_id == ingest_run_id),
        )
        await self.db.commit()
        return result.rowcount or 0
