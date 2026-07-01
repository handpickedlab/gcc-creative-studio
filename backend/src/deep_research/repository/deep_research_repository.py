# Copyright 2025 Google LLC
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
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.base_repository import BaseRepository
from src.common.dto.pagination_response_dto import PaginationResponseDto
from src.database import get_db
from src.deep_research.dto.deep_research_search_dto import DeepResearchSearchDto
from src.deep_research.schema.deep_research_model import (
    DeepResearchReport,
    DeepResearchReportModel,
)


class DeepResearchRepository(
    BaseRepository[DeepResearchReport, DeepResearchReportModel]
):
    """Database operations for the 'deep_research_reports' table."""

    def __init__(self, db: AsyncSession = Depends(get_db)):
        super().__init__(
            model=DeepResearchReport,
            schema=DeepResearchReportModel,
            db=db,
        )

    async def query(
        self,
        search_dto: DeepResearchSearchDto,
        user_id: int,
    ) -> PaginationResponseDto[DeepResearchReportModel]:
        """Return a user's reports, newest first, paginated."""
        query = select(self.model).where(self.model.user_id == user_id)

        if search_dto.status is not None:
            query = query.where(self.model.status == search_dto.status.value)

        count_query = select(func.count()).select_from(query.subquery())
        total_count = (await self.db.execute(count_query)).scalar_one()

        query = (
            query.order_by(self.model.created_at.desc())
            .offset(search_dto.offset)
            .limit(search_dto.limit)
        )
        result = await self.db.execute(query)
        reports = result.scalars().all()

        data = [self.schema.model_validate(r) for r in reports]

        page_size = search_dto.limit
        page = (search_dto.offset // page_size) + 1
        total_pages = (total_count + page_size - 1) // page_size

        return PaginationResponseDto[DeepResearchReportModel](
            count=total_count,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            data=data,
        )
