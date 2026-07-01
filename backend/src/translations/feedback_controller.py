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
"""Authenticated feedback endpoints for the content manager.

Router-level ``RoleChecker`` keeps these behind the normal app auth — the
translator-facing counterpart lives in ``public_feedback_controller`` with no
guard.
"""

from fastapi import APIRouter, Depends, status

from src.auth.auth_guard import RoleChecker, get_current_user
from src.translations.dto.feedback_dto import (
    BriefingFeedbackDto,
    CreateTicketDto,
    MarketOverviewDto,
    SetReviewStateDto,
    ShareLinkResponseDto,
    UpdateTicketStatusDto,
)
from src.translations.feedback_service import FeedbackService
from src.translations.schema.feedback_model import FeedbackTicketModel
from src.users.user_model import UserModel, UserRoleEnum

router = APIRouter(
    prefix="/api/briefings",
    tags=["Feedback"],
    responses={404: {"description": "Not found"}},
    dependencies=[
        Depends(
            RoleChecker(allowed_roles=[UserRoleEnum.ADMIN, UserRoleEnum.USER])
        )
    ],
)


@router.get("/{briefing_id}/feedback", response_model=BriefingFeedbackDto)
async def get_feedback(briefing_id: int, service: FeedbackService = Depends()):
    """Per-market review state + all tickets for the briefing."""
    return await service.get_feedback_overview(briefing_id)


@router.post(
    "/{briefing_id}/markets/{market}/tickets",
    response_model=FeedbackTicketModel,
    status_code=status.HTTP_201_CREATED,
)
async def create_ticket(
    briefing_id: int,
    market: str,
    dto: CreateTicketDto,
    current_user: UserModel = Depends(get_current_user),
    service: FeedbackService = Depends(),
):
    """Content manager leaves a ticket on an item (author = current user)."""
    return await service.create_ticket(
        briefing_id,
        market,
        dto.segment_index,
        current_user.name or current_user.email,
        "content_manager",
        dto.body,
    )


@router.patch("/tickets/{ticket_id}", response_model=FeedbackTicketModel)
async def update_ticket(
    ticket_id: int,
    dto: UpdateTicketStatusDto,
    service: FeedbackService = Depends(),
):
    """Move a ticket through Open -> Opgepakt -> Opgelost (reopen allowed)."""
    return await service.update_ticket_status(
        ticket_id, dto.status, dto.resolution_note
    )


@router.patch(
    "/{briefing_id}/markets/{market}/review-state",
    response_model=MarketOverviewDto,
)
async def set_review_state(
    briefing_id: int,
    market: str,
    dto: SetReviewStateDto,
    service: FeedbackService = Depends(),
):
    return await service.set_review_state(briefing_id, market, dto.review_state)


@router.post(
    "/{briefing_id}/markets/{market}/share-link",
    response_model=ShareLinkResponseDto,
    status_code=status.HTTP_201_CREATED,
)
async def create_share_link(
    briefing_id: int, market: str, service: FeedbackService = Depends()
):
    """'Vraag feedback aan': mint a fresh 3-day translator link for this
    market (rotates any previous link) and mark the market in review."""
    return await service.request_feedback(briefing_id, market)


@router.delete(
    "/{briefing_id}/markets/{market}/share-link",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_share_link(
    briefing_id: int, market: str, service: FeedbackService = Depends()
):
    """Kill an active translator link before its TTL."""
    await service.revoke_link(briefing_id, market)
