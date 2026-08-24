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
(hard filters applied in SQL first), then two multipliers are applied in
Python — the document's priority tier (a "background" document needs a
meaningfully better semantic match to outrank a "primary" one) and the age of
the claim's CONTENT, taken from its normalized period, never from the upload
timestamp.
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
    c.period_key,
    c.claim_type,
    c.source_citation,
    c.sample,
    d.filename,
    d.priority_tier,
    d.period AS document_period,
    d.vintage_key AS document_vintage_key,
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
  AND (CAST(:min_period AS text) IS NULL
       OR COALESCE(c.period_key, d.vintage_key) >= CAST(:min_period AS text))
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
    min_period: str | None = None,
) -> dict[str, Any]:
    """Searches the claim library; safe to call from the sync agent loop."""
    max_results = max(1, min(int(max_results or 8), 25))
    # geography/period are soft hints: fold them into the embedded query text
    # rather than filtering on the free-text columns (which silently excludes
    # e.g. "The Netherlands" when the agent passes "NL").
    # min_period is the opposite: a hard YYYY-MM cutoff from the user's
    # recency control, applied in SQL so old editions cannot leak through.
    augmented = " ".join(p for p in (query, geography, period) if p)
    cutoff = _normalize_min_period(min_period)
    try:
        query_embedding = embedding_service.embed_text(
            client, augmented, embedding_service.TASK_QUERY
        )
        rows = asyncio.run(
            _fetch_candidates(
                query_embedding,
                tags=tags,
                allowed_documents=allowed_documents,
                min_period=cutoff,
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


# The distinct values the agent can actually filter/aim a search at, per facet.
# Geography/segment/period/claim_type are free-text on the claim; this shows
# what values EXIST so the agent knows whether e.g. Belgium is even covered —
# a genuine miss vs. a wrong query.
_FACETS_SQL = """
SELECT facet, value, COUNT(*) AS n
FROM (
    SELECT 'geography'  AS facet, NULLIF(TRIM(c.geography), '')  AS value
    FROM research_claims c JOIN research_documents d ON d.id = c.document_id
    WHERE d.deleted_at IS NULL
      AND (CAST(:document_ids AS int[]) IS NULL OR c.document_id = ANY(CAST(:document_ids AS int[])))
    UNION ALL
    SELECT 'segment', NULLIF(TRIM(c.segment), '')
    FROM research_claims c JOIN research_documents d ON d.id = c.document_id
    WHERE d.deleted_at IS NULL
      AND (CAST(:document_ids AS int[]) IS NULL OR c.document_id = ANY(CAST(:document_ids AS int[])))
    UNION ALL
    SELECT 'period', NULLIF(TRIM(c.period), '')
    FROM research_claims c JOIN research_documents d ON d.id = c.document_id
    WHERE d.deleted_at IS NULL
      AND (CAST(:document_ids AS int[]) IS NULL OR c.document_id = ANY(CAST(:document_ids AS int[])))
    UNION ALL
    SELECT 'claim_type', NULLIF(TRIM(c.claim_type), '')
    FROM research_claims c JOIN research_documents d ON d.id = c.document_id
    WHERE d.deleted_at IS NULL
      AND (CAST(:document_ids AS int[]) IS NULL OR c.document_id = ANY(CAST(:document_ids AS int[])))
) s
WHERE value IS NOT NULL
GROUP BY facet, value
ORDER BY facet, n DESC
"""

_DOCS_SQL = """
SELECT d.id AS document_id, d.filename AS document, COUNT(c.id) AS n
FROM research_documents d
LEFT JOIN research_claims c
       ON c.document_id = d.id AND c.embedding IS NOT NULL
WHERE d.deleted_at IS NULL
  AND (CAST(:document_ids AS int[]) IS NULL OR d.id = ANY(CAST(:document_ids AS int[])))
GROUP BY d.id, d.filename
ORDER BY n DESC
LIMIT 150
"""


def list_facets_sync(
    allowed_documents: list[int] | None = None,
    limit_per_facet: int = 60,
) -> dict[str, Any]:
    """The searchable landscape of the corpus: which geographies, segments,
    periods, claim types and documents actually exist (with claim counts).

    Lets the agent see whether a value it wants (a market, a period) is even
    present before searching, so "not in the data" is a real absence rather
    than a mis-phrased query. Safe to call from the sync agent loop.
    """
    try:
        facet_rows, doc_rows = asyncio.run(
            _fetch_facets(allowed_documents)
        )
    except Exception as e:
        logger.error("list_facets failed: %s", e)
        return {"error": f"list_facets failed: {e}"}

    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in facet_rows:
        grouped.setdefault(r["facet"], [])
        if len(grouped[r["facet"]]) < limit_per_facet:
            grouped[r["facet"]].append(
                {"value": r["value"], "claims": r["n"]}
            )
    return {
        "geographies": grouped.get("geography", []),
        "segments": grouped.get("segment", []),
        "periods": grouped.get("period", []),
        "claim_types": grouped.get("claim_type", []),
        "documents": [
            {
                "document_id": r["document_id"],
                "document": r["document"],
                "claims": r["n"],
            }
            for r in doc_rows
        ],
    }


async def _fetch_facets(
    allowed_documents: list[int] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Distinct facet values + the document list on a fresh worker engine."""
    from src.database import WorkerDatabase

    async with WorkerDatabase() as db_factory:
        async with db_factory() as db:
            facet_res = await db.execute(
                text(_FACETS_SQL), {"document_ids": allowed_documents}
            )
            facet_rows = [dict(row) for row in facet_res.mappings().all()]
            doc_res = await db.execute(
                text(_DOCS_SQL), {"document_ids": allowed_documents}
            )
            doc_rows = [dict(row) for row in doc_res.mappings().all()]
            return facet_rows, doc_rows


async def _fetch_candidates(
    query_embedding: list[float],
    tags: list[str] | None,
    allowed_documents: list[int] | None,
    min_period: str | None = None,
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
                    "min_period": min_period,
                    "pool": _CANDIDATE_POOL,
                },
            )
            return [dict(row) for row in result.mappings().all()]


def _normalize_min_period(raw: str | None) -> str | None:
    """Accepts ``YYYY-MM`` or a free-text year/period and returns a key."""
    if not raw:
        return None
    text = raw.strip()
    if not text:
        return None
    if len(text) == 7 and text[4] == "-" and text[:4].isdigit() and text[5:].isdigit():
        return text
    from src.research_library import period_service

    return period_service.normalize_period(text)


def _month_ordinal(key: str | None) -> int | None:
    """A ``YYYY-MM`` period key as a comparable month count."""
    if not key:
        return None
    try:
        year, month = key.split("-")
        return int(year) * 12 + int(month)
    except (ValueError, AttributeError):
        return None


def _recency_factors(rows: list[dict[str, Any]]) -> dict[int, float]:
    """Map each row index -> a recency multiplier in [1, 1 + RECENCY_WEIGHT].

    Recency means the age of the CONTENT, not of the upload: a claim is dated
    by its own period, falling back to its document's edition date. Weighting
    on the upload timestamp (as this once did) ranked a 2023 figure above a
    2026 one whenever its file happened to be added later — which is how "the
    most recent NPS" came back as 2023.

    Rows with no resolvable date, and pools where every row shares one date,
    get a neutral 1.0.
    """
    stamps = {}
    for i, r in enumerate(rows):
        ordinal = _month_ordinal(r.get("period_key")) or _month_ordinal(
            r.get("document_vintage_key")
        )
        if ordinal is not None:
            stamps[i] = ordinal
    if len(stamps) < 2:
        return {i: 1.0 for i in range(len(rows))}
    oldest, newest = min(stamps.values()), max(stamps.values())
    span = newest - oldest
    factors: dict[int, float] = {}
    for i in range(len(rows)):
        ordinal = stamps.get(i)
        if ordinal is None or span <= 0:
            factors[i] = 1.0
        else:
            norm = (ordinal - oldest) / span  # 0 oldest → 1 newest
            factors[i] = 1.0 + config.RECENCY_WEIGHT * norm
    return factors


def rank_candidates(
    rows: list[dict[str, Any]],
    tier_weights: dict[str, float],
) -> list[dict[str, Any]]:
    """Applies the priority-tier and recency multipliers, then re-sorts.

    Hard filters already happened in SQL; this is pure scoring, kept as a
    separate function so it can be tested without Postgres.
    """
    default_weight = tier_weights.get(PriorityTierEnum.PRIMARY.value, 1.0)
    recency = _recency_factors(rows)
    scored = []
    for i, row in enumerate(rows):
        weight = tier_weights.get(
            row.get("priority_tier") or "", default_weight
        )
        scored.append({
            **row,
            "score": float(row["similarity"]) * weight * recency[i],
        })
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
        # Sortable form of the period, so the agent can tell which of two
        # near-identical claims is the newer one. NULL when the source's
        # phrasing names no point in time ("past 12 months").
        "period_key": row.get("period_key"),
        "claim_type": row.get("claim_type"),
        "source_citation": row.get("source_citation"),
        "sample": row.get("sample"),
        "document_id": row["document_id"],
        "document": row["filename"],
        "document_period": row.get("document_period"),
        "document_vintage_key": row.get("document_vintage_key"),
        "page": row["page_no"],
        "tier": row.get("priority_tier"),
        "score": round(row["score"], 4),
    }
