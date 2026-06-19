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
"""Tests for FeedbackService — focused on the security-critical paths:
token validation (fail-closed), share-link minting/hashing, and the
market-scoped, PII-free public view."""

import datetime
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.translations.feedback_service import FeedbackService
from src.translations.schema.feedback_model import FeedbackTicketModel


def _make():
    repo = AsyncMock()
    briefing_repo = AsyncMock()
    return (
        FeedbackService(repo=repo, briefing_repo=briefing_repo),
        repo,
        briefing_repo,
    )


def _briefing(texts, name="Campaign"):
    segs = [
        SimpleNamespace(
            block=None, field=f"f{i}", label=f"L{i}", char_limit=None, text=t
        )
        for i, t in enumerate(texts)
    ]
    return SimpleNamespace(id=1, name=name, segments=segs)


def _translation(market, texts):
    return SimpleNamespace(
        market=market, segments=[SimpleNamespace(text=t) for t in texts]
    )


def _future():
    return datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=1)


def _past():
    return datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=1)


def _import_httpexc():
    from fastapi import HTTPException

    return HTTPException


# --- validate_share_token: fail-closed ----------------------------------


@pytest.mark.anyio
async def test_validate_token_unknown_is_404():
    svc, repo, _ = _make()
    repo.get_request_by_token.return_value = None
    with pytest.raises(_import_httpexc()) as exc:
        await svc.validate_share_token("nope")
    assert exc.value.status_code == 404


@pytest.mark.anyio
async def test_validate_token_revoked_is_410():
    svc, repo, _ = _make()
    repo.get_request_by_token.return_value = SimpleNamespace(
        briefing_id=1,
        market="NL",
        token_hash="h",
        revoked_at=_past(),
        expires_at=_future(),
    )
    with pytest.raises(_import_httpexc()) as exc:
        await svc.validate_share_token("tok")
    assert exc.value.status_code == 410


@pytest.mark.anyio
async def test_validate_token_expired_is_410():
    svc, repo, _ = _make()
    repo.get_request_by_token.return_value = SimpleNamespace(
        briefing_id=1,
        market="NL",
        token_hash="h",
        revoked_at=None,
        expires_at=_past(),
    )
    with pytest.raises(_import_httpexc()) as exc:
        await svc.validate_share_token("tok")
    assert exc.value.status_code == 410


@pytest.mark.anyio
async def test_validate_token_active_returns_context_and_hashes():
    svc, repo, _ = _make()
    repo.get_request_by_token.return_value = SimpleNamespace(
        briefing_id=42,
        market="NL",
        token_hash="h",
        revoked_at=None,
        expires_at=_future(),
    )
    briefing_id, market = await svc.validate_share_token("the-raw-token")
    assert (briefing_id, market) == (42, "NL")
    # Lookup is by sha256(token), never the raw token.
    called_hash = repo.get_request_by_token.call_args.args[0]
    assert called_hash == hashlib.sha256(b"the-raw-token").hexdigest()


# --- request_feedback ----------------------------------------------------


@pytest.mark.anyio
async def test_request_feedback_requires_translation():
    svc, repo, briefing_repo = _make()
    briefing_repo.get_briefing.return_value = _briefing(["a", "b"])
    briefing_repo.get_translations.return_value = []  # NL not translated
    with pytest.raises(_import_httpexc()) as exc:
        await svc.request_feedback(1, "NL")
    assert exc.value.status_code == 400


@pytest.mark.anyio
async def test_request_feedback_rejects_source_market():
    svc, _, briefing_repo = _make()
    with pytest.raises(_import_httpexc()) as exc:
        await svc.request_feedback(1, "EN")
    assert exc.value.status_code == 400


@pytest.mark.anyio
async def test_request_feedback_mints_hashed_token_and_marks_in_review():
    svc, repo, briefing_repo = _make()
    briefing_repo.get_briefing.return_value = _briefing(["a"])
    briefing_repo.get_translations.return_value = [_translation("NL", ["x"])]

    async def echo(bid, market, values):
        return SimpleNamespace(briefing_id=bid, market=market, **values)

    repo.upsert_request.side_effect = echo

    result = await svc.request_feedback(1, "NL")

    values = repo.upsert_request.call_args.args[2]
    assert values["review_state"] == "in_review"
    assert values["revoked_at"] is None
    # Only the hash is stored; it must match the returned raw token.
    assert (
        values["token_hash"]
        == hashlib.sha256(result.token.encode()).hexdigest()
    )
    assert result.token  # a real, copyable token is returned


# --- create_ticket -------------------------------------------------------


@pytest.mark.anyio
async def test_create_ticket_rejects_out_of_range_index():
    svc, repo, briefing_repo = _make()
    briefing_repo.get_briefing.return_value = _briefing(["a", "b"])
    with pytest.raises(_import_httpexc()) as exc:
        await svc.create_ticket(1, "NL", 5, "Sanne", "translator", "hi")
    assert exc.value.status_code == 400
    repo.create_ticket.assert_not_called()


@pytest.mark.anyio
async def test_create_ticket_stores_snapshot_and_hash():
    svc, repo, briefing_repo = _make()
    briefing_repo.get_briefing.return_value = _briefing(["source0", "source1"])
    briefing_repo.get_translations.return_value = [
        _translation("NL", ["t0", "t1"])
    ]
    await svc.create_ticket(1, "NL", 1, "  Sanne ", "translator", "  te lang ")

    values = repo.create_ticket.call_args.args[0]
    assert values["segment_index"] == 1
    assert values["source_snapshot"] == "source1"
    assert values["author_name"] == "Sanne"  # trimmed
    assert values["body"] == "te lang"  # trimmed
    assert values["author_role"] == "translator"
    assert values["content_hash"]  # computed


@pytest.mark.anyio
async def test_create_ticket_rejects_blank_body():
    svc, repo, briefing_repo = _make()
    briefing_repo.get_briefing.return_value = _briefing(["a"])
    with pytest.raises(_import_httpexc()) as exc:
        await svc.create_ticket(1, "NL", 0, "Sanne", "translator", "   ")
    assert exc.value.status_code == 400


# --- get_public_view: scope + no PII + drift -----------------------------


@pytest.mark.anyio
async def test_public_view_is_market_scoped_and_pii_free():
    svc, repo, briefing_repo = _make()
    briefing_repo.get_briefing.return_value = _briefing(["s0", "s1"], name="Q3")
    briefing_repo.get_translations.return_value = [
        _translation("NL", ["nl0", "nl1"]),
        _translation("FR", ["fr0", "fr1"]),
    ]
    repo.list_tickets.return_value = []

    view = await svc.get_public_view(1, "NL")
    dumped = view.model_dump(by_alias=True)

    assert view.briefing_name == "Q3"
    assert view.market == "NL"
    assert [i.translation for i in view.items] == ["nl0", "nl1"]  # NL only
    # Tickets were fetched scoped to this market only.
    repo.list_tickets.assert_awaited_once_with(1, "NL")
    # No internal/PII keys leak through the public DTO.
    assert "meta" not in dumped
    assert not any("resolution" in k.lower() for k in str(dumped).split())


@pytest.mark.anyio
async def test_public_view_flags_item_changed_on_drift():
    svc, repo, briefing_repo = _make()
    briefing_repo.get_briefing.return_value = _briefing(["s0"])
    briefing_repo.get_translations.return_value = [_translation("NL", ["nl0"])]
    stale = FeedbackTicketModel(
        id=1,
        briefing_id=1,
        market="NL",
        segment_index=0,
        author_name="Sanne",
        author_role="translator",
        body="b",
        status="open",
        content_hash="a-stale-hash-that-will-not-match",
    )
    repo.list_tickets.return_value = [stale]

    view = await svc.get_public_view(1, "NL")
    assert view.tickets[0].item_changed is True


# --- link status + revoke -----------------------------------------------


def test_link_status_variants():
    now = datetime.datetime.now(datetime.UTC)
    assert FeedbackService._link_status(None, now) == "none"
    assert (
        FeedbackService._link_status(
            SimpleNamespace(token_hash=None, revoked_at=None, expires_at=None),
            now,
        )
        == "none"
    )
    assert (
        FeedbackService._link_status(
            SimpleNamespace(
                token_hash="h", revoked_at=now, expires_at=_future()
            ),
            now,
        )
        == "revoked"
    )
    assert (
        FeedbackService._link_status(
            SimpleNamespace(
                token_hash="h", revoked_at=None, expires_at=_past()
            ),
            now,
        )
        == "expired"
    )
    assert (
        FeedbackService._link_status(
            SimpleNamespace(
                token_hash="h", revoked_at=None, expires_at=_future()
            ),
            now,
        )
        == "active"
    )


@pytest.mark.anyio
async def test_revoke_clears_token_keeps_state():
    svc, repo, _ = _make()
    repo.get_request.return_value = SimpleNamespace(
        briefing_id=1, market="NL", token_hash="h"
    )
    await svc.revoke_link(1, "NL")
    values = repo.upsert_request.call_args.args[2]
    assert values["token_hash"] is None
    assert values["revoked_at"] is not None


@pytest.mark.anyio
async def test_revoke_404_when_no_link():
    svc, repo, _ = _make()
    repo.get_request.return_value = None
    with pytest.raises(_import_httpexc()) as exc:
        await svc.revoke_link(1, "NL")
    assert exc.value.status_code == 404
