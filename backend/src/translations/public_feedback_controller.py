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
"""Unauthenticated, token-gated feedback endpoints for the translator.

This is the ONLY unauthenticated ``/api`` surface. It deliberately has NO
``RoleChecker``; every route is gated by ``share_token_context``, which
fail-closes on an unknown/expired/revoked token. The briefing id and market are
derived ONLY from the token — never from the path/query/body — so a valid token
for one market cannot reach another market or briefing (IDOR invariant).
"""

from fastapi import APIRouter, Depends, status

from src.translations.dto.feedback_dto import (
    PublicCreateTicketDto,
    PublicFeedbackViewDto,
    PublicTicketDto,
)
from src.translations.feedback_service import FeedbackService

router = APIRouter(
    prefix="/api/public/feedback",
    tags=["Public Feedback"],
)


async def share_token_context(
    token: str, service: FeedbackService = Depends()
) -> tuple[int, str]:
    """Resolves the path token to (briefing_id, market), fail-closed."""
    return await service.validate_share_token(token)


@router.get("/{token}", response_model=PublicFeedbackViewDto)
async def public_view(
    context: tuple[int, str] = Depends(share_token_context),
    service: FeedbackService = Depends(),
):
    briefing_id, market = context
    return await service.get_public_view(briefing_id, market)


@router.post(
    "/{token}/tickets",
    response_model=PublicTicketDto,
    status_code=status.HTTP_201_CREATED,
)
async def public_create_ticket(
    dto: PublicCreateTicketDto,
    context: tuple[int, str] = Depends(share_token_context),
    service: FeedbackService = Depends(),
):
    briefing_id, market = context
    ticket = await service.create_ticket(
        briefing_id,
        market,
        dto.segment_index,
        dto.author_name,
        "translator",
        dto.body,
    )
    return PublicTicketDto(
        id=ticket.id,
        segment_index=ticket.segment_index,
        author_name=ticket.author_name,
        author_role=ticket.author_role,
        body=ticket.body,
        status=ticket.status,
        created_at=ticket.created_at,
        item_changed=False,
    )
