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
"""Persistence for feedback requests (per-market) and tickets (per-item).

Both are keyed on ``(briefing_id, market[, segment_index])`` rather than the
``briefing_translations`` row, which is delete+inserted on every save — so
tickets and links survive re-saves and re-translation.
"""

from typing import Any

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.translations.schema.feedback_model import (
    BriefingFeedbackRequest,
    BriefingFeedbackTicket,
    FeedbackTicketModel,
)


class FeedbackRepository:
    """Data access for the translator feedback loop."""

    def __init__(self, db: AsyncSession = Depends(get_db)):
        self.db = db

    # --- Feedback requests (per-market review state + link credential) ---

    async def get_request(
        self, briefing_id: int, market: str
    ) -> BriefingFeedbackRequest | None:
        """Returns the ORM row (carries token_hash for internal logic)."""
        result = await self.db.execute(
            select(BriefingFeedbackRequest).where(
                BriefingFeedbackRequest.briefing_id == briefing_id,
                BriefingFeedbackRequest.market == market,
            )
        )
        return result.scalar_one_or_none()

    async def get_request_by_token(
        self, token_hash: str
    ) -> BriefingFeedbackRequest | None:
        """Looks up the active-link row by token hash (unique index)."""
        result = await self.db.execute(
            select(BriefingFeedbackRequest).where(
                BriefingFeedbackRequest.token_hash == token_hash
            )
        )
        return result.scalar_one_or_none()

    async def upsert_request(
        self, briefing_id: int, market: str, values: dict[str, Any]
    ) -> BriefingFeedbackRequest:
        """Creates the (briefing, market) row if absent, applies ``values``.

        Returns the ORM row (the service needs token_hash/expiry for link-state
        logic; the safe DTOs are built in the service)."""
        row = await self.get_request(briefing_id, market)
        if row is None:
            row = BriefingFeedbackRequest(
                briefing_id=briefing_id, market=market
            )
            self.db.add(row)
        for key, value in values.items():
            setattr(row, key, value)
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def list_requests(
        self, briefing_id: int
    ) -> list[BriefingFeedbackRequest]:
        result = await self.db.execute(
            select(BriefingFeedbackRequest).where(
                BriefingFeedbackRequest.briefing_id == briefing_id
            )
        )
        return list(result.scalars().all())

    # --- Tickets ---------------------------------------------------------

    async def create_ticket(
        self, values: dict[str, Any]
    ) -> FeedbackTicketModel:
        item = BriefingFeedbackTicket(**values)
        self.db.add(item)
        await self.db.commit()
        await self.db.refresh(item)
        return FeedbackTicketModel.model_validate(item)

    async def list_tickets(
        self, briefing_id: int, market: str | None = None
    ) -> list[FeedbackTicketModel]:
        query = select(BriefingFeedbackTicket).where(
            BriefingFeedbackTicket.briefing_id == briefing_id
        )
        if market is not None:
            query = query.where(BriefingFeedbackTicket.market == market)
        query = query.order_by(BriefingFeedbackTicket.created_at.asc())
        result = await self.db.execute(query)
        return [
            FeedbackTicketModel.model_validate(t)
            for t in result.scalars().all()
        ]

    async def get_ticket(self, ticket_id: int) -> BriefingFeedbackTicket | None:
        result = await self.db.execute(
            select(BriefingFeedbackTicket).where(
                BriefingFeedbackTicket.id == ticket_id
            )
        )
        return result.scalar_one_or_none()

    async def update_ticket(
        self, ticket_id: int, values: dict[str, Any]
    ) -> FeedbackTicketModel | None:
        row = await self.get_ticket(ticket_id)
        if row is None:
            return None
        for key, value in values.items():
            setattr(row, key, value)
        await self.db.commit()
        await self.db.refresh(row)
        return FeedbackTicketModel.model_validate(row)
