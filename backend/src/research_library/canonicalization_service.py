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

"""Tag & metric canonicalization for the research library.

Claims permanently keep the model's free-form ``raw_tags``; searchable
``canonical_tags`` come from a rebuildable raw -> canonical mapping
(``research_tag_aliases``). The bootstrap derives that mapping FROM the
corpus instead of a hand-designed taxonomy:

1. collect distinct raw tags/metrics across all claims,
2. embed them (CLUSTERING task type) and greedily cluster on cosine
   similarity — "smartphone", "mobiel", "m-commerce" end up together,
3. one structured Gemini call names every multi-member cluster with a
   canonical lowercase English tag,
4. write the alias mapping, then RE-RESOLVE canonical_tags on every claim
   (a cheap batch update — no LLM re-extraction), so re-running the
   bootstrap after new ingest batches keeps old claims searchable.

A claim's canonical metric name is appended to its ``canonical_tags`` so
metric-level filtering works through the same tag filter without a schema
change.

The bootstrap returns a human-reviewable summary (cluster -> members ->
chosen name); manual fixes go through the alias upsert endpoint followed by
a re-resolve.
"""

import json
import logging
import math
from typing import Any

from google.genai import types
from pydantic import BaseModel, Field

from src.research_library.ingest import embedding_service
from src.research_library.schema.research_document_model import (
    TagAliasKindEnum,
)

logger = logging.getLogger(__name__)

# Cosine similarity above which two tags are considered the same concept.
# Tuned on the real corpus during the bootstrap run (deliberately
# conservative: a missed merge is recoverable, an over-merge pollutes).
DEFAULT_CLUSTER_THRESHOLD = 0.75

# Tags rarer than this still get aliased (to themselves) but are not worth
# an LLM naming slot of their own.
_MAX_VOCABULARY = 200


class _ClusterName(BaseModel):
    cluster_id: int
    canonical: str = Field(description="lowercase English canonical tag")


class _ClusterNames(BaseModel):
    clusters: list[_ClusterName] = Field(default_factory=list)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def greedy_cluster(
    embeddings: dict[str, list[float]],
    frequencies: dict[str, int],
    threshold: float,
) -> list[list[str]]:
    """Clusters tags by cosine similarity to a cluster's first member.

    Tags are visited most-frequent-first so cluster anchors are the corpus's
    dominant phrasings; each tag joins the first anchor above the threshold
    or starts its own cluster. O(n * clusters), fine for a few hundred tags.
    """
    anchors: list[str] = []
    clusters: dict[str, list[str]] = {}
    for tag in sorted(
        embeddings, key=lambda t: (-frequencies.get(t, 0), t)
    ):
        best_anchor, best_similarity = None, threshold
        for anchor in anchors:
            similarity = _cosine(embeddings[tag], embeddings[anchor])
            if similarity >= best_similarity:
                best_anchor, best_similarity = anchor, similarity
        if best_anchor is None:
            anchors.append(tag)
            clusters[tag] = [tag]
        else:
            clusters[best_anchor].append(tag)
    return list(clusters.values())


def name_clusters(client, model: str, clusters: list[list[str]]) -> dict[str, str]:
    """Returns {member_tag: canonical} for every clustered tag.

    Single-member clusters keep their own (lowercased) tag; multi-member
    clusters are named by one structured Gemini call.
    """
    mapping: dict[str, str] = {}
    multi = []
    for cluster in clusters:
        if len(cluster) == 1:
            mapping[cluster[0]] = cluster[0]
        else:
            multi.append(cluster)

    if not multi:
        return mapping

    listing = "\n".join(
        f"{i}: {', '.join(cluster)}" for i, cluster in enumerate(multi)
    )
    prompt = (
        "Each numbered line lists tag variants that mean the same concept "
        "in market research documents (mixed English/Dutch/German). For "
        "each cluster pick ONE canonical tag: lowercase English, short, "
        "generic.\n\n" + listing
    )
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=_ClusterNames,
            temperature=0,
        ),
    )
    named = _ClusterNames.model_validate(json.loads(response.text or "{}"))
    names = {c.cluster_id: c.canonical.strip().lower() for c in named.clusters}

    for i, cluster in enumerate(multi):
        canonical = names.get(i) or cluster[0]
        for member in cluster:
            mapping[member] = canonical
    return mapping


def apply_aliases(
    raw_tags: list[str] | None,
    metric: str | None,
    alias_map: dict[str, str],
) -> list[str]:
    """Resolves a claim's canonical_tags from its raw tags + metric.

    Unknown raw tags fall back to themselves (lowercased): a claim ingested
    between bootstraps stays findable and the next bootstrap re-resolves it
    properly.
    """
    canonical: list[str] = []
    for tag in raw_tags or []:
        cleaned = tag.strip().lower()
        if not cleaned:
            continue
        resolved = alias_map.get(cleaned, cleaned)
        if resolved not in canonical:
            canonical.append(resolved)
    if metric:
        cleaned = metric.strip().lower()
        resolved = alias_map.get(cleaned, cleaned)
        if resolved not in canonical:
            canonical.append(resolved)
    return canonical


async def bootstrap(
    client,
    model: str,
    tag_alias_repo,
    threshold: float = DEFAULT_CLUSTER_THRESHOLD,
) -> dict[str, Any]:
    """Rebuilds the alias mapping from the corpus and re-resolves all claims."""
    tag_counts, metric_counts = await tag_alias_repo.distinct_raw_tags()

    summary_clusters = []
    for counts, kind in (
        (tag_counts, TagAliasKindEnum.TAG.value),
        (metric_counts, TagAliasKindEnum.METRIC.value),
    ):
        if not counts:
            continue
        vocabulary = [tag for tag, _ in counts.most_common(_MAX_VOCABULARY)]
        embeddings = {
            tag: embedding_service.embed_text(
                client, tag, task_type="CLUSTERING"
            )
            for tag in vocabulary
        }
        clusters = greedy_cluster(embeddings, dict(counts), threshold)
        mapping = name_clusters(client, model, clusters)

        for raw, canonical in mapping.items():
            await tag_alias_repo.upsert_alias(raw, canonical, kind)
        for cluster in clusters:
            summary_clusters.append(
                {
                    "kind": kind,
                    "canonical": mapping.get(cluster[0], cluster[0]),
                    "members": cluster,
                    "occurrences": sum(counts.get(t, 0) for t in cluster),
                },
            )

    updated = await resolve_all_claims(tag_alias_repo)
    return {
        "clusters": sorted(
            summary_clusters, key=lambda c: -c["occurrences"]
        ),
        "aliases": sum(len(c["members"]) for c in summary_clusters),
        "updated_claims": updated,
    }


async def resolve_all_claims(tag_alias_repo) -> int:
    """Re-computes canonical_tags for every claim from the alias mapping."""
    aliases = await tag_alias_repo.list_aliases()
    alias_map = {alias.raw: alias.canonical for alias in aliases}

    updates: dict[int, list[str]] = {}
    for claim_id, raw_tags, metric in await tag_alias_repo.iter_claim_tag_rows():
        updates[claim_id] = apply_aliases(raw_tags, metric, alias_map)
    return await tag_alias_repo.bulk_update_canonical_tags(updates)


def load_vocabulary(aliases: list) -> list[str]:
    """Distinct canonical tags for the extraction prompt, most useful first."""
    seen: list[str] = []
    for alias in aliases:
        if alias.kind == TagAliasKindEnum.TAG.value and alias.canonical not in seen:
            seen.append(alias.canonical)
    return seen[:_MAX_VOCABULARY]
