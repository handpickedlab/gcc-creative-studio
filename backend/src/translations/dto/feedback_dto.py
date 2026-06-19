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
"""DTOs for the translator feedback loop.

The *public* DTOs are the security boundary for the unauthenticated translator
view: they whitelist exactly what an account-less translator may see and send.
They never carry ``briefing.meta`` (internal/PII) or a ticket's
``resolution_note`` (content-manager only).
"""

import datetime

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from src.translations.schema.feedback_model import (
    AuthorRole,
    FeedbackTicketModel,
    ReviewState,
    TicketStatus,
)

# Length caps for translator-supplied input on the unauthenticated surface.
MAX_AUTHOR_NAME = 120
MAX_BODY = 4000


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# --- Content-manager request/response DTOs ------------------------------


class CreateTicketDto(_CamelModel):
    """A ticket created by the content manager (author name comes from the
    authenticated user, not the body)."""

    segment_index: int = Field(ge=0)
    body: str = Field(min_length=1, max_length=MAX_BODY)


class UpdateTicketStatusDto(_CamelModel):
    status: TicketStatus
    resolution_note: str | None = Field(default=None, max_length=MAX_BODY)


class SetReviewStateDto(_CamelModel):
    review_state: ReviewState


class ShareLinkResponseDto(_CamelModel):
    """Returned once when a link is minted. ``token`` is the raw token; the
    frontend composes the URL as ``{origin}/feedback/{token}``."""

    token: str
    expires_at: datetime.datetime


class MarketCountsDto(_CamelModel):
    open: int = 0
    in_progress: int = 0
    resolved: int = 0


class MarketOverviewDto(_CamelModel):
    """Per-market feedback overview for the content manager."""

    market: str
    review_state: ReviewState = "draft"
    # active | expired | revoked | none — derived, not the review state.
    link_status: str = "none"
    expires_at: datetime.datetime | None = None
    counts: MarketCountsDto = Field(default_factory=MarketCountsDto)


class BriefingFeedbackDto(_CamelModel):
    """Full feedback state for a briefing (content-manager view): per-market
    overview plus all tickets (the UI groups them by market + segment)."""

    markets: list[MarketOverviewDto] = Field(default_factory=list)
    tickets: list[FeedbackTicketModel] = Field(default_factory=list)


# --- Public (translator) DTOs -------------------------------------------


class PublicCreateTicketDto(_CamelModel):
    """Body for an account-less translator creating a ticket. Deliberately has
    NO market/briefingId — both come from the validated token, never the
    client (IDOR invariant)."""

    segment_index: int = Field(ge=0)
    author_name: str = Field(min_length=1, max_length=MAX_AUTHOR_NAME)
    body: str = Field(min_length=1, max_length=MAX_BODY)


class PublicFeedbackItemDto(_CamelModel):
    """One reviewable item: source + this market's translation, side by side."""

    index: int
    block: str | None = None
    field: str
    label: str
    char_limit: int | None = None
    source: str = ""
    translation: str = ""


class PublicTicketDto(_CamelModel):
    """A ticket as seen on the public page. Excludes ``resolution_note``."""

    id: int
    segment_index: int
    author_name: str
    author_role: AuthorRole
    body: str
    status: TicketStatus
    created_at: datetime.datetime | None = None
    item_changed: bool = False


class PublicFeedbackViewDto(_CamelModel):
    """Everything an account-less translator may see for their one market.

    Whitelisted on purpose: no ``meta``, no other markets, no internal notes.
    """

    briefing_name: str
    market: str
    market_label: str
    items: list[PublicFeedbackItemDto] = Field(default_factory=list)
    tickets: list[PublicTicketDto] = Field(default_factory=list)
