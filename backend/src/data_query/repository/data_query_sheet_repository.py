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

"""Repository for the durable data-query sheet catalog."""

import datetime

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.base_repository import BaseRepository
from src.data_query.schema.data_query_sheet_model import (
    DataQuerySheet,
    DataQuerySheetModel,
)
from src.database import get_db


class DataQuerySheetRepository(
    BaseRepository[DataQuerySheet, DataQuerySheetModel]
):
    """Database operations for the uploaded-sheet catalog."""

    def __init__(self, db: AsyncSession = Depends(get_db)):
        super().__init__(
            model=DataQuerySheet, schema=DataQuerySheetModel, db=db
        )

    async def list_active(self) -> list[DataQuerySheetModel]:
        """All non-deleted sheets, newest first."""
        result = await self.db.execute(
            select(self.model)
            .where(self.model.deleted_at.is_(None))
            .order_by(self.model.created_at.desc(), self.model.id.desc()),
        )
        return [self.schema.model_validate(r) for r in result.scalars().all()]

    async def find_active_by_id(
        self, sheet_id: int
    ) -> DataQuerySheetModel | None:
        result = await self.db.execute(
            select(self.model)
            .where(self.model.id == sheet_id)
            .where(self.model.deleted_at.is_(None)),
        )
        row = result.scalar_one_or_none()
        return self.schema.model_validate(row) if row else None

    async def deactivate_table(self, table_name: str) -> None:
        """Soft-delete any active rows for a table name (pre-upload cleanup)."""
        result = await self.db.execute(
            select(self.model)
            .where(self.model.table_name == table_name)
            .where(self.model.deleted_at.is_(None)),
        )
        for row in result.scalars().all():
            row.deleted_at = datetime.datetime.now(datetime.UTC)
        await self.db.commit()

    async def gcs_uri_still_used(
        self, gcs_uri: str, exclude_id: int
    ) -> bool:
        """Whether another active row still references this raw file."""
        result = await self.db.execute(
            select(self.model.id)
            .where(self.model.gcs_uri == gcs_uri)
            .where(self.model.deleted_at.is_(None))
            .where(self.model.id != exclude_id),
        )
        return result.first() is not None
