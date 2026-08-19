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

"""Repository for research documents and their rendered pages.

``research_documents`` is soft-deleted, and is not registered with the
global soft-delete event listener in ``src.common.events`` (that listener is
scoped to a fixed list of models), so every query here filters
``deleted_at IS NULL`` explicitly rather than relying on it.
"""

import datetime
from typing import Any

from fastapi import Depends
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.base_repository import BaseRepository
from src.common.dto.pagination_response_dto import PaginationResponseDto
from src.database import get_db
from src.research_library.schema.research_document_model import (
    ResearchDocStatus,
    ResearchDocument,
    ResearchDocumentModel,
    ResearchDocumentPage,
    ResearchDocumentPageModel,
)


class ResearchDocumentRepository(
    BaseRepository[ResearchDocument, ResearchDocumentModel]
):
    """Handles database operations for research documents and their pages."""

    def __init__(self, db: AsyncSession = Depends(get_db)):
        super().__init__(
            model=ResearchDocument, schema=ResearchDocumentModel, db=db
        )

    async def find_by_sha256(
        self, sha256: str
    ) -> ResearchDocumentModel | None:
        """Finds an active (non-deleted) document by its content hash."""
        result = await self.db.execute(
            select(self.model)
            .where(self.model.sha256 == sha256)
            .where(self.model.deleted_at.is_(None))
            .limit(1),
        )
        document = result.scalar_one_or_none()
        if not document:
            return None
        return self.schema.model_validate(document)

    async def find_active_by_id(
        self, document_id: int
    ) -> ResearchDocumentModel | None:
        """Fetches a document by ID, treating a soft-deleted row as absent.

        Used as the tombstone check before a background worker performs its
        terminal write, so a delete-during-processing race never resurrects
        a deleted document.
        """
        result = await self.db.execute(
            select(self.model)
            .where(self.model.id == document_id)
            .where(self.model.deleted_at.is_(None)),
        )
        document = result.scalar_one_or_none()
        if not document:
            return None
        return self.schema.model_validate(document)

    async def list_documents(
        self,
        limit: int = 20,
        offset: int = 0,
    ) -> PaginationResponseDto[ResearchDocumentModel]:
        """Lists active documents, newest first."""
        base_query = select(self.model).where(self.model.deleted_at.is_(None))

        count_result = await self.db.execute(
            select(func.count()).select_from(base_query.subquery()),
        )
        total_count = count_result.scalar_one()

        query = (
            base_query.order_by(self.model.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.db.execute(query)
        documents = result.scalars().all()
        data = [self.schema.model_validate(d) for d in documents]

        page = (offset // limit) + 1 if limit else 1
        total_pages = (total_count + limit - 1) // limit if limit else 1

        return PaginationResponseDto[ResearchDocumentModel](
            count=total_count,
            page=page,
            page_size=limit,
            total_pages=total_pages,
            data=data,
        )

    async def find_stalled(
        self,
        cutoff: datetime.datetime,
        limit: int,
    ) -> list[ResearchDocumentModel]:
        """Documents stuck in PROCESSING with no progress since ``cutoff``.

        Oldest upload first, so a recovered backlog drains in the order it
        was uploaded.
        """
        result = await self.db.execute(
            select(self.model)
            .where(self.model.status == ResearchDocStatus.PROCESSING.value)
            .where(self.model.deleted_at.is_(None))
            .where(self.model.updated_at < cutoff)
            .order_by(self.model.created_at.asc())
            .limit(limit),
        )
        return [
            self.schema.model_validate(d) for d in result.scalars().all()
        ]

    async def claim_stalled(
        self,
        document_id: int,
        new_run_id: str,
        cutoff: datetime.datetime,
    ) -> bool:
        """Atomically takes ownership of a stalled document for a new run.

        The ``updated_at < cutoff`` predicate doubles as the lock: the first
        writer bumps the timestamp, so a second instance sweeping the same
        document updates no rows and moves on. Returns whether this caller
        won the document.

        Claiming deliberately does NOT touch ``ingest_attempts`` — see
        ``begin_attempt``.
        """
        result = await self.db.execute(
            update(self.model)
            .where(self.model.id == document_id)
            .where(self.model.status == ResearchDocStatus.PROCESSING.value)
            .where(self.model.deleted_at.is_(None))
            .where(self.model.updated_at < cutoff)
            .values(
                ingest_run_id=new_run_id,
                error_message=None,
                failed_pages=[],
                updated_at=func.now(),
            ),
        )
        await self.db.commit()
        return result.rowcount == 1

    async def begin_attempt(self, document_id: int) -> None:
        """Records that a worker has actually started on this document.

        The attempt counter is raised here rather than when the document is
        claimed, because being claimed is not the same as being run: a
        document can sit in an executor queue behind a slow one, beat no
        heartbeat, and get re-claimed — which would burn its retries without
        anything ever having gone wrong. Only a real start counts against
        ``MAX_INGEST_ATTEMPTS``.
        """
        await self.db.execute(
            update(self.model)
            .where(self.model.id == document_id)
            .values(
                ingest_attempts=self.model.ingest_attempts + 1,
                updated_at=func.now(),
            ),
        )
        await self.db.commit()

    async def touch(self, document_id: int) -> None:
        """Heartbeat marking a document as still being worked on.

        Nothing else in the ingest pipeline writes to the document row until
        it finishes, so without this a long-running document would look
        stalled to the sweeper and be re-queued underneath its own worker.
        """
        await self.db.execute(
            update(self.model)
            .where(self.model.id == document_id)
            .values(updated_at=func.now()),
        )
        await self.db.commit()

    async def upsert_page(
        self,
        document_id: int,
        page_no: int,
        **fields: Any,
    ) -> ResearchDocumentPageModel:
        """Creates or updates the page row for (document_id, page_no)."""
        result = await self.db.execute(
            select(ResearchDocumentPage)
            .where(ResearchDocumentPage.document_id == document_id)
            .where(ResearchDocumentPage.page_no == page_no),
        )
        page = result.scalar_one_or_none()

        if page:
            for key, value in fields.items():
                setattr(page, key, value)
        else:
            page = ResearchDocumentPage(
                document_id=document_id,
                page_no=page_no,
                **fields,
            )
            self.db.add(page)

        await self.db.commit()
        await self.db.refresh(page)
        return ResearchDocumentPageModel.model_validate(page)

    async def list_pages(
        self, document_id: int
    ) -> list[ResearchDocumentPageModel]:
        """Lists all page rows for a document, in page order."""
        result = await self.db.execute(
            select(ResearchDocumentPage)
            .where(ResearchDocumentPage.document_id == document_id)
            .order_by(ResearchDocumentPage.page_no.asc()),
        )
        pages = result.scalars().all()
        return [ResearchDocumentPageModel.model_validate(p) for p in pages]

    async def get_page(
        self, document_id: int, page_no: int
    ) -> ResearchDocumentPageModel | None:
        """Returns one page row of a document, if it exists."""
        result = await self.db.execute(
            select(ResearchDocumentPage)
            .where(ResearchDocumentPage.document_id == document_id)
            .where(ResearchDocumentPage.page_no == page_no),
        )
        page = result.scalar_one_or_none()
        if not page:
            return None
        return ResearchDocumentPageModel.model_validate(page)
