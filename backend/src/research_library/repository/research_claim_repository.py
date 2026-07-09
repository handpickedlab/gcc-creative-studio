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

import json
from typing import Any

from fastapi import Depends
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.base_repository import BaseRepository
from src.database import get_db
from src.research_library.schema.research_document_model import (
    ResearchClaim,
    ResearchClaimModel,
)

# Keyword browse over the fact library: substring match on the claim text +
# metric, optional document/tag/period filters, with a window-function total
# for pagination. Facts join their document for the filename shown in the UI.
_BROWSE_SQL = """
SELECT
    c.id, c.document_id, c.page_no, c.statement, c.metric, c.value, c.unit,
    c.segment, c.geography, c.period, c.claim_type, c.source_citation,
    c.sample, c.canonical_tags, d.filename,
    count(*) OVER() AS total_count
FROM research_claims c
JOIN research_documents d ON d.id = c.document_id
WHERE d.deleted_at IS NULL
  AND (CAST(:q AS text) IS NULL
       OR c.statement ILIKE '%' || :q || '%'
       OR c.metric ILIKE '%' || :q || '%')
  AND (CAST(:document_id AS int) IS NULL OR c.document_id = :document_id)
  AND (CAST(:tag AS text) IS NULL
       OR c.canonical_tags @> CAST(:tag_json AS jsonb)
       OR c.raw_tags @> CAST(:tag_json AS jsonb))
  AND (CAST(:period AS text) IS NULL OR c.period ILIKE '%' || :period || '%')
ORDER BY c.document_id, c.page_no, c.id
LIMIT :limit OFFSET :offset
"""


class ResearchClaimRepository(BaseRepository[ResearchClaim, ResearchClaimModel]):
    """Handles database operations for research claims."""

    def __init__(self, db: AsyncSession = Depends(get_db)):
        super().__init__(model=ResearchClaim, schema=ResearchClaimModel, db=db)

    async def browse(
        self,
        q: str | None = None,
        document_id: int | None = None,
        tag: str | None = None,
        period: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Paginated keyword browse over the fact library. Returns
        (rows, total_matches)."""
        result = await self.db.execute(
            text(_BROWSE_SQL),
            {
                "q": q or None,
                "document_id": document_id,
                "tag": tag or None,
                "tag_json": json.dumps([tag]) if tag else None,
                "period": period or None,
                "limit": max(1, min(limit, 200)),
                "offset": max(0, offset),
            },
        )
        rows = [dict(r) for r in result.mappings().all()]
        total = rows[0]["total_count"] if rows else 0
        for r in rows:
            r.pop("total_count", None)
        return rows, total

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

    async def delete_claims_except_run(
        self,
        document_id: int,
        ingest_run_id: str,
    ) -> int:
        """Deletes a document's claims from every run EXCEPT the given one.

        The worker calls this after a run finished writing successfully; the
        reprocess flow assigns the new run id before the worker starts, so
        "everything that isn't the current run" is exactly the superseded
        claims (including runs whose id was lost to an interim failure).
        """
        result = await self.db.execute(
            delete(self.model)
            .where(self.model.document_id == document_id)
            .where(self.model.ingest_run_id != ingest_run_id),
        )
        await self.db.commit()
        return result.rowcount or 0
