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
"""Domain logic for the translator feedback loop.

Security-critical pieces live here:

* ``request_feedback`` mints a fresh high-entropy token, stores only its sha256
  (rotate-on-request: each call supersedes the prior link so the content
  manager always gets a copyable URL — a hashed token cannot be re-displayed).
* ``validate_share_token`` is fail-closed: unknown -> 404, revoked/expired ->
  410, and every rejection raises ``HTTPException`` so the global catch-all
  cannot turn a token failure into a 500.
* ``get_public_view`` returns ONLY the token's market via a whitelisted DTO —
  never ``briefing.meta`` and never a ticket's ``resolution_note``.
"""

import datetime
import hashlib
import secrets

from fastapi import Depends, HTTPException, status

from src.translations.dto.feedback_dto import (
    BriefingFeedbackDto,
    MarketCountsDto,
    MarketOverviewDto,
    PublicFeedbackItemDto,
    PublicFeedbackViewDto,
    PublicTicketDto,
    ShareLinkResponseDto,
)
from src.translations.markets import (
    SOURCE_MARKET,
    is_valid_market,
    language_for_market,
)
from src.translations.repository.briefing_repository import BriefingRepository
from src.translations.repository.feedback_repository import FeedbackRepository
from src.translations.schema.feedback_model import (
    AuthorRole,
    FeedbackTicketModel,
    ReviewState,
    TicketStatus,
)

SHARE_LINK_TTL_DAYS = 3


def _ensure_aware(dt: datetime.datetime | None) -> datetime.datetime | None:
    """Treats a naive datetime as UTC (the columns are timezone-aware, but be
    defensive so an expiry comparison can never raise)."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=datetime.UTC)
    return dt


class FeedbackService:
    def __init__(
        self,
        repo: FeedbackRepository = Depends(),
        briefing_repo: BriefingRepository = Depends(),
    ):
        self.repo = repo
        self.briefing_repo = briefing_repo

    # --- small helpers ---------------------------------------------------

    @staticmethod
    def _now() -> datetime.datetime:
        return datetime.datetime.now(datetime.UTC)

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _content_hash(field: str, source: str, translation: str) -> str:
        normalized = "".join(
            [
                (field or "").strip(),
                (source or "").strip(),
                (translation or "").strip(),
            ]
        )
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @classmethod
    def _link_status(cls, row, now: datetime.datetime) -> str:
        if row is None or not getattr(row, "token_hash", None):
            return "none"
        if row.revoked_at is not None:
            return "revoked"
        expires = _ensure_aware(row.expires_at)
        if expires is None or expires <= now:
            return "expired"
        return "active"

    def _validate_target_market(self, market: str) -> None:
        if not is_valid_market(market) or market == SOURCE_MARKET:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown or non-target market: {market}",
            )

    async def _get_briefing_or_404(self, briefing_id: int):
        briefing = await self.briefing_repo.get_briefing(briefing_id)
        if not briefing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Briefing {briefing_id} not found.",
            )
        return briefing

    async def _translation_for(self, briefing_id: int, market: str):
        translations = await self.briefing_repo.get_translations(briefing_id)
        for t in translations:
            if t.market == market:
                return t
        return None

    def _current_hash(self, briefing, translation, idx: int) -> str | None:
        if idx < 0 or idx >= len(briefing.segments):
            return None
        seg = briefing.segments[idx]
        tr_segs = translation.segments if translation else []
        tr_text = tr_segs[idx].text if idx < len(tr_segs) else ""
        return self._content_hash(seg.field, seg.text, tr_text)

    # --- share links -----------------------------------------------------

    async def request_feedback(
        self, briefing_id: int, market: str
    ) -> ShareLinkResponseDto:
        """Marks the market 'in_review' and mints a fresh link (rotate)."""
        self._validate_target_market(market)
        await self._get_briefing_or_404(briefing_id)
        translation = await self._translation_for(briefing_id, market)
        if translation is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Translate this market before requesting feedback "
                    "— there is nothing for the translator to review yet."
                ),
            )

        now = self._now()
        token = secrets.token_urlsafe(32)
        expires_at = now + datetime.timedelta(days=SHARE_LINK_TTL_DAYS)
        row = await self.repo.upsert_request(
            briefing_id,
            market,
            {
                "review_state": "in_review",
                "requested_at": now,
                "token_hash": self._hash_token(token),
                "expires_at": expires_at,
                "revoked_at": None,
            },
        )
        return ShareLinkResponseDto(token=token, expires_at=row.expires_at)

    async def revoke_link(self, briefing_id: int, market: str) -> None:
        row = await self.repo.get_request(briefing_id, market)
        if row is None or not row.token_hash:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active link for this market.",
            )
        # Clear the credential but keep the durable review_state.
        await self.repo.upsert_request(
            briefing_id,
            market,
            {"token_hash": None, "revoked_at": self._now()},
        )

    async def validate_share_token(self, token: str) -> tuple[int, str]:
        """Resolves a raw token to (briefing_id, market). Fail-closed."""
        row = await self.repo.get_request_by_token(self._hash_token(token))
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invalid or unknown link.",
            )
        if row.revoked_at is not None:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="This link is no longer available.",
            )
        expires = _ensure_aware(row.expires_at)
        if expires is None or expires <= self._now():
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="This link has expired.",
            )
        return row.briefing_id, row.market

    async def set_review_state(
        self, briefing_id: int, market: str, state: ReviewState
    ) -> MarketOverviewDto:
        self._validate_target_market(market)
        await self._get_briefing_or_404(briefing_id)
        row = await self.repo.upsert_request(
            briefing_id, market, {"review_state": state}
        )
        tickets = await self.repo.list_tickets(briefing_id, market)
        return MarketOverviewDto(
            market=market,
            review_state=row.review_state,
            link_status=self._link_status(row, self._now()),
            expires_at=row.expires_at,
            counts=self._count(tickets),
        )

    # --- tickets ---------------------------------------------------------

    async def create_ticket(
        self,
        briefing_id: int,
        market: str,
        segment_index: int,
        author_name: str,
        author_role: AuthorRole,
        body: str,
    ) -> FeedbackTicketModel:
        briefing = await self._get_briefing_or_404(briefing_id)
        if segment_index < 0 or segment_index >= len(briefing.segments):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="segment_index is out of range for this briefing.",
            )
        name = (author_name or "").strip()
        text = (body or "").strip()
        if not name or not text:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Both a name and a non-empty comment are required.",
            )

        translation = await self._translation_for(briefing_id, market)
        seg = briefing.segments[segment_index]
        tr_segs = translation.segments if translation else []
        tr_text = (
            tr_segs[segment_index].text if segment_index < len(tr_segs) else ""
        )
        return await self.repo.create_ticket(
            {
                "briefing_id": briefing_id,
                "market": market,
                "segment_index": segment_index,
                "field_snapshot": seg.label or seg.field,
                "source_snapshot": seg.text,
                "content_hash": self._content_hash(
                    seg.field, seg.text, tr_text
                ),
                "author_name": name,
                "author_role": author_role,
                "body": text,
                "status": "open",
            }
        )

    async def update_ticket_status(
        self,
        ticket_id: int,
        new_status: TicketStatus,
        resolution_note: str | None,
    ) -> FeedbackTicketModel:
        existing = await self.repo.get_ticket(ticket_id)
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Ticket {ticket_id} not found.",
            )
        values: dict = {
            "status": new_status,
            "status_changed_at": self._now(),
        }
        if resolution_note is not None:
            note = resolution_note.strip()
            values["resolution_note"] = note or None
        updated = await self.repo.update_ticket(ticket_id, values)
        return updated

    # --- read models -----------------------------------------------------

    @staticmethod
    def _count(tickets: list[FeedbackTicketModel]) -> MarketCountsDto:
        counts = MarketCountsDto()
        for t in tickets:
            if t.status == "open":
                counts.open += 1
            elif t.status == "in_progress":
                counts.in_progress += 1
            elif t.status == "resolved":
                counts.resolved += 1
        return counts

    async def get_feedback_overview(
        self, briefing_id: int
    ) -> BriefingFeedbackDto:
        briefing = await self._get_briefing_or_404(briefing_id)
        requests = await self.repo.list_requests(briefing_id)
        tickets = await self.repo.list_tickets(briefing_id)
        translations = await self.briefing_repo.get_translations(briefing_id)
        tr_by_market = {t.market: t for t in translations}
        now = self._now()

        # Flag drift (re-translation) per ticket.
        for t in tickets:
            current = self._current_hash(
                briefing, tr_by_market.get(t.market), t.segment_index
            )
            t.item_changed = bool(
                t.content_hash and current and t.content_hash != current
            )

        req_by_market = {r.market: r for r in requests}
        markets = {r.market for r in requests} | {t.market for t in tickets}
        overview = []
        for market in sorted(markets):
            row = req_by_market.get(market)
            mkt_tickets = [t for t in tickets if t.market == market]
            overview.append(
                MarketOverviewDto(
                    market=market,
                    review_state=(row.review_state if row else "draft"),
                    link_status=self._link_status(row, now),
                    expires_at=(row.expires_at if row else None),
                    counts=self._count(mkt_tickets),
                )
            )
        return BriefingFeedbackDto(markets=overview, tickets=tickets)

    async def get_public_view(
        self, briefing_id: int, market: str
    ) -> PublicFeedbackViewDto:
        """Single-market, whitelisted view for the account-less translator."""
        briefing = await self._get_briefing_or_404(briefing_id)
        translation = await self._translation_for(briefing_id, market)
        tr_segs = translation.segments if translation else []

        items = []
        for i, seg in enumerate(briefing.segments):
            tr_text = tr_segs[i].text if i < len(tr_segs) else ""
            items.append(
                PublicFeedbackItemDto(
                    index=i,
                    block=seg.block,
                    field=seg.field,
                    label=seg.label,
                    char_limit=seg.char_limit,
                    source=seg.text,
                    translation=tr_text,
                )
            )

        tickets = await self.repo.list_tickets(briefing_id, market)
        public_tickets = []
        for t in tickets:
            current = self._current_hash(briefing, translation, t.segment_index)
            public_tickets.append(
                PublicTicketDto(
                    id=t.id,
                    segment_index=t.segment_index,
                    author_name=t.author_name,
                    author_role=t.author_role,
                    body=t.body,
                    status=t.status,
                    created_at=t.created_at,
                    item_changed=bool(
                        t.content_hash and current and t.content_hash != current
                    ),
                )
            )

        return PublicFeedbackViewDto(
            briefing_name=briefing.name,
            market=market,
            market_label=language_for_market(market),
            items=items,
            tickets=public_tickets,
        )
