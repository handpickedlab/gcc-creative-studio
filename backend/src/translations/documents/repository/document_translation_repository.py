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
"""Repositories for document translation jobs and segments."""

from fastapi import Depends
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.base_repository import BaseStringRepository
from src.database import get_db
from src.translations.documents.schema.document_translation_model import (
    DocumentTranslationJob,
    DocumentTranslationJobModel,
    DocumentTranslationSegment,
    DocumentTranslationSegmentModel,
)


class DocumentTranslationJobRepository(
    BaseStringRepository[DocumentTranslationJob, DocumentTranslationJobModel]
):
    def __init__(self, db: AsyncSession = Depends(get_db)):
        super().__init__(
            model=DocumentTranslationJob,
            schema=DocumentTranslationJobModel,
            db=db,
        )

    async def find_recent(
        self, limit: int = 50
    ) -> list[DocumentTranslationJobModel]:
        result = await self.db.execute(
            select(DocumentTranslationJob)
            .order_by(DocumentTranslationJob.created_at.desc())
            .limit(limit)
        )
        return [
            DocumentTranslationJobModel.model_validate(row)
            for row in result.scalars().all()
        ]


class DocumentTranslationSegmentRepository:
    def __init__(self, db: AsyncSession = Depends(get_db)):
        self.db = db

    async def bulk_create(
        self, rows: list[DocumentTranslationSegment]
    ) -> None:
        self.db.add_all(rows)
        await self.db.commit()

    async def find_by_job(
        self,
        job_id: str,
        status: str | None = None,
        translatable_only: bool = False,
        section_id: str | None = None,
        review_filter: str | None = None,
    ) -> list[DocumentTranslationSegmentModel]:
        query = (
            select(DocumentTranslationSegment)
            .where(DocumentTranslationSegment.job_id == job_id)
            .order_by(DocumentTranslationSegment.seg_index)
        )
        if status:
            query = query.where(DocumentTranslationSegment.status == status)
        if translatable_only:
            query = query.where(
                DocumentTranslationSegment.kind.in_(
                    ["heading", "prose", "table_label"]
                )
            )
        if section_id:
            query = query.where(
                DocumentTranslationSegment.section_id == section_id
            )
        # Mirrors the review workspace's exception filters.
        if review_filter == "attention":
            query = query.where(
                DocumentTranslationSegment.finding.isnot(None),
                DocumentTranslationSegment.status != "approved",
            )
        elif review_filter == "ai":
            query = query.where(
                DocumentTranslationSegment.provenance == "ai",
                DocumentTranslationSegment.status != "approved",
            )
        elif review_filter == "edited":
            query = query.where(
                DocumentTranslationSegment.provenance == "edited"
            )
        result = await self.db.execute(query)
        return [
            DocumentTranslationSegmentModel.model_validate(row)
            for row in result.scalars().all()
        ]

    async def set_translations(
        self,
        job_id: str,
        translations: dict[int, str],
        status: str,
        provenance: str = "ai",
    ) -> None:
        """Writes a batch of model results keyed by seg_index."""
        for seg_index, text in translations.items():
            await self.db.execute(
                update(DocumentTranslationSegment)
                .where(
                    DocumentTranslationSegment.job_id == job_id,
                    DocumentTranslationSegment.seg_index == seg_index,
                )
                .values(
                    translation=text, status=status, provenance=provenance
                )
            )
        await self.db.commit()

    async def set_findings(
        self, job_id: str, findings: dict[int, dict]
    ) -> None:
        """Replaces the per-segment findings for a job.

        Clears every stale finding first so a re-run of QA can only ever
        shrink the set — a resolved finding must not linger.
        """
        await self.db.execute(
            update(DocumentTranslationSegment)
            .where(
                DocumentTranslationSegment.job_id == job_id,
                DocumentTranslationSegment.finding.isnot(None),
            )
            .values(finding=None)
        )
        for seg_index, finding in findings.items():
            await self.db.execute(
                update(DocumentTranslationSegment)
                .where(
                    DocumentTranslationSegment.job_id == job_id,
                    DocumentTranslationSegment.seg_index == seg_index,
                )
                .values(finding=finding)
            )
        await self.db.commit()

    async def mark_failed(self, job_id: str, seg_indexes: list[int]) -> None:
        if not seg_indexes:
            return
        await self.db.execute(
            update(DocumentTranslationSegment)
            .where(
                DocumentTranslationSegment.job_id == job_id,
                DocumentTranslationSegment.seg_index.in_(seg_indexes),
            )
            .values(status="failed")
        )
        await self.db.commit()

    async def update_segment(
        self,
        job_id: str,
        seg_index: int,
        values: dict,
    ) -> DocumentTranslationSegmentModel | None:
        result = await self.db.execute(
            select(DocumentTranslationSegment).where(
                DocumentTranslationSegment.job_id == job_id,
                DocumentTranslationSegment.seg_index == seg_index,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        for key, value in values.items():
            setattr(row, key, value)
        await self.db.commit()
        await self.db.refresh(row)
        return DocumentTranslationSegmentModel.model_validate(row)
