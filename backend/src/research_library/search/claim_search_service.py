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

"""Semantic claim search for the hybrid ask-agent.

The ask endpoint streams from a synchronous generator (FastAPI runs it on a
worker thread), while claims live behind async SQLAlchemy — so this module
exposes a synchronous entry point that owns a short-lived event loop and a
per-call ``WorkerDatabase`` engine, exactly like the ingest worker does for
its thread. One ask typically triggers 1-3 searches, so the per-call engine
setup is acceptable for the PoC.

Ranking: candidates come back from pgvector ordered by cosine similarity
(hard filters applied in SQL first), then the document's priority tier is
applied as a score multiplier in Python — a "background" document needs a
meaningfully better semantic match to outrank a "primary" one.
"""

import asyncio
import logging
from typing import Any

from sqlalchemy import text

from src.research_library import config
from src.research_library.ingest import embedding_service
from src.research_library.schema.research_document_model import (
    PriorityTierEnum,
)

logger = logging.getLogger(__name__)

# How many candidates to pull from pgvector before tier re-ranking. Must
# comfortably exceed max_results so a boosted lower-similarity claim can
# still make the cut.
_CANDIDATE_POOL = 50

_SEARCH_SQL = """
SELECT
    c.id AS claim_id,
    c.document_id,
    c.page_no,
    c.statement,
    c.metric,
    c.value,
    c.unit,
    c.segment,
    c.geography,
    c.period,
    c.claim_type,
    c.source_citation,
    c.sample,
    d.filename,
    d.priority_tier,
    d.period AS document_period,
    1 - (c.embedding <=> CAST(:query_embedding AS vector)) AS similarity
FROM research_claims c
JOIN research_documents d ON d.id = c.document_id
WHERE d.deleted_at IS NULL
  AND c.embedding IS NOT NULL
  AND (CAST(:document_ids AS int[]) IS NULL
       OR c.document_id = ANY(CAST(:document_ids AS int[])))
  AND (CAST(:tags AS text[]) IS NULL
       OR jsonb_exists_any(c.canonical_tags, CAST(:tags AS text[]))
       OR jsonb_exists_any(c.raw_tags, CAST(:tags AS text[])))
ORDER BY c.embedding <=> CAST(:query_embedding AS vector)
LIMIT :pool
"""

# NB: geography and period are deliberately NOT hard SQL filters. Both are
# free-text fields ("The Netherlands" vs a "NL" filter, "Q1 2025" vs "2025")
# where a substring match silently EXCLUDES the right claims. Instead they
# fold into the embedding query as soft hints (see search_claims_sync); the
# statement text already carries geography/period, so similarity ranks them
# well, and the agent reads each result's period field for conflict handling.


def search_claims_sync(
    client,
    query: str,
    tags: list[str] | None = None,
    period: str | None = None,
    geography: str | None = None,
    allowed_documents: list[int] | None = None,
    max_results: int = 8,
) -> dict[str, Any]:
    """Searches the claim library; safe to call from the sync agent loop."""
    max_results = max(1, min(int(max_results or 8), 25))
    # geography/period are soft hints: fold them into the embedded query text
    # rather than filtering on the free-text columns (which silently excludes
    # e.g. "The Netherlands" when the agent passes "NL").
    augmented = " ".join(p for p in (query, geography, period) if p)
    try:
        query_embedding = embedding_service.embed_text(
            client, augmented, embedding_service.TASK_QUERY
        )
        rows = asyncio.run(
            _fetch_candidates(
                query_embedding,
                tags=tags,
                allowed_documents=allowed_documents,
            ),
        )
    except Exception as e:
        logger.error("Claim search failed for %r: %s", query, e)
        return {"error": f"claim search failed: {e}"}

    ranked = rank_candidates(rows, config.TIER_WEIGHTS)[:max_results]
    return {
        "count": len(ranked),
        "results": [_format_result(row) for row in ranked],
    }


_TAGS_SQL = """
SELECT tag, COUNT(*) AS n
FROM research_claims c
JOIN research_documents d ON d.id = c.document_id
CROSS JOIN LATERAL jsonb_array_elements_text(c.canonical_tags) AS tag
WHERE d.deleted_at IS NULL
  AND c.canonical_tags IS NOT NULL
  AND jsonb_typeof(c.canonical_tags) = 'array'
  AND (CAST(:document_ids AS int[]) IS NULL
       OR c.document_id = ANY(CAST(:document_ids AS int[])))
GROUP BY tag
ORDER BY n DESC
LIMIT :limit
"""


def list_tags_sync(
    allowed_documents: list[int] | None = None,
    limit: int = 300,
) -> dict[str, Any]:
    """The corpus's canonical topic vocabulary with per-tag claim counts.

    Lets the agent orient itself — see WHICH topics the library actually
    covers (brand awareness, competitors, NPS, ...) — before/instead of
    guessing a single search query. Safe to call from the sync agent loop.
    """
    try:
        rows = asyncio.run(_fetch_tags(allowed_documents, limit))
    except Exception as e:
        logger.error("list_tags failed: %s", e)
        return {"error": f"list_tags failed: {e}"}
    return {
        "count": len(rows),
        "tags": [{"tag": r["tag"], "claims": r["n"]} for r in rows],
    }


async def _fetch_tags(
    allowed_documents: list[int] | None, limit: int
) -> list[dict[str, Any]]:
    """Distinct canonical tags + claim counts on a fresh worker engine."""
    from src.database import WorkerDatabase

    async with WorkerDatabase() as db_factory:
        async with db_factory() as db:
            result = await db.execute(
                text(_TAGS_SQL),
                {"document_ids": allowed_documents, "limit": limit},
            )
            return [dict(row) for row in result.mappings().all()]


async def _fetch_candidates(
    query_embedding: list[float],
    tags: list[str] | None,
    allowed_documents: list[int] | None,
) -> list[dict[str, Any]]:
    """Runs the pgvector similarity query on a fresh worker engine."""
    from src.database import WorkerDatabase

    embedding_literal = "[" + ",".join(str(v) for v in query_embedding) + "]"
    async with WorkerDatabase() as db_factory:
        async with db_factory() as db:
            result = await db.execute(
                text(_SEARCH_SQL),
                {
                    "query_embedding": embedding_literal,
                    "document_ids": allowed_documents,
                    "tags": tags,
                    "pool": _CANDIDATE_POOL,
                },
            )
            return [dict(row) for row in result.mappings().all()]


def rank_candidates(
    rows: list[dict[str, Any]],
    tier_weights: dict[str, float],
) -> list[dict[str, Any]]:
    """Applies the priority-tier multiplier and re-sorts.

    Hard filters already happened in SQL; this is pure scoring, kept as a
    separate function so it can be tested without Postgres.
    """
    default_weight = tier_weights.get(PriorityTierEnum.PRIMARY.value, 1.0)
    scored = []
    for row in rows:
        weight = tier_weights.get(
            row.get("priority_tier") or "", default_weight
        )
        scored.append({**row, "score": float(row["similarity"]) * weight})
    return sorted(scored, key=lambda r: r["score"], reverse=True)


def _format_result(row: dict[str, Any]) -> dict[str, Any]:
    """The shape the agent (and the frontend's sources event) receives."""
    return {
        "claim_id": row["claim_id"],
        "statement": row["statement"],
        "metric": row.get("metric"),
        "value": row.get("value"),
        "unit": row.get("unit"),
        "segment": row.get("segment"),
        "geography": row.get("geography"),
        "period": row.get("period"),
        "claim_type": row.get("claim_type"),
        "source_citation": row.get("source_citation"),
        "sample": row.get("sample"),
        "document_id": row["document_id"],
        "document": row["filename"],
        "document_period": row.get("document_period"),
        "page": row["page_no"],
        "tier": row.get("priority_tier"),
        "score": round(row["score"], 4),
    }
