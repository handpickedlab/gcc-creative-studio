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

"""Tests for tag/metric canonicalization."""

import json
from collections import Counter
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.research_library.canonicalization_service import (
    apply_aliases,
    bootstrap,
    greedy_cluster,
    load_vocabulary,
    name_clusters,
    resolve_all_claims,
)
from src.research_library.schema.research_document_model import TagAliasModel


class TestGreedyCluster:
    def test_near_synonyms_cluster_and_distinct_concepts_do_not(self):
        embeddings = {
            "smartphone": [1.0, 0.0, 0.05],
            "m-commerce": [0.98, 0.0, 0.1],
            "sustainability": [0.0, 1.0, 0.0],
        }
        frequencies = {"smartphone": 10, "m-commerce": 4, "sustainability": 8}

        clusters = greedy_cluster(embeddings, frequencies, threshold=0.9)

        clusters_as_sets = [set(c) for c in clusters]
        assert {"smartphone", "m-commerce"} in clusters_as_sets
        assert {"sustainability"} in clusters_as_sets

    def test_most_frequent_tag_anchors_the_cluster(self):
        embeddings = {
            "mobiel": [1.0, 0.0],
            "smartphone": [1.0, 0.01],
        }
        frequencies = {"mobiel": 2, "smartphone": 30}

        clusters = greedy_cluster(embeddings, frequencies, threshold=0.9)

        assert clusters == [["smartphone", "mobiel"]]


class TestNameClusters:
    def test_single_member_clusters_skip_the_llm(self):
        client = MagicMock()

        mapping = name_clusters(client, "m", [["sustainability"]])

        assert mapping == {"sustainability": "sustainability"}
        client.models.generate_content.assert_not_called()

    def test_multi_member_clusters_get_canonical_names(self):
        client = MagicMock()
        response = MagicMock()
        response.text = json.dumps(
            {"clusters": [{"cluster_id": 0, "canonical": "Mobile-Commerce "}]},
        )
        client.models.generate_content.return_value = response

        mapping = name_clusters(
            client, "m", [["smartphone", "m-commerce"], ["inflation"]]
        )

        assert mapping["smartphone"] == "mobile-commerce"
        assert mapping["m-commerce"] == "mobile-commerce"
        assert mapping["inflation"] == "inflation"


class TestApplyAliases:
    def test_resolves_known_and_falls_back_for_unknown(self):
        alias_map = {"mobiel": "mobile-commerce"}

        canonical = apply_aliases(
            ["Mobiel", "duurzaamheid"], "online share", alias_map
        )

        assert canonical == ["mobile-commerce", "duurzaamheid", "online share"]

    def test_deduplicates(self):
        alias_map = {"mobiel": "mobile-commerce", "smartphone": "mobile-commerce"}

        canonical = apply_aliases(["mobiel", "smartphone"], None, alias_map)

        assert canonical == ["mobile-commerce"]


class TestResolveAllClaims:
    @pytest.mark.anyio
    async def test_rewrites_every_claims_canonical_tags(self):
        repo = AsyncMock()
        repo.list_aliases.return_value = [
            TagAliasModel(raw="mobiel", canonical="mobile-commerce"),
        ]
        repo.iter_claim_tag_rows.return_value = [
            (1, ["mobiel"], None),
            (2, ["anders"], "share"),
        ]
        repo.bulk_update_canonical_tags.side_effect = lambda u: len(u)

        updated = await resolve_all_claims(repo)

        assert updated == 2
        updates = repo.bulk_update_canonical_tags.call_args.args[0]
        assert updates[1] == ["mobile-commerce"]
        assert updates[2] == ["anders", "share"]


class TestBootstrap:
    @pytest.mark.anyio
    async def test_bootstrap_writes_aliases_and_reresolves(self):
        repo = AsyncMock()
        repo.distinct_raw_tags.return_value = (
            Counter({"smartphone": 5, "m-commerce": 2}),
            Counter(),
        )
        repo.list_aliases.return_value = []
        repo.iter_claim_tag_rows.return_value = []
        repo.bulk_update_canonical_tags.side_effect = lambda u: len(u)

        client = MagicMock()
        naming_response = MagicMock()
        naming_response.text = json.dumps(
            {"clusters": [{"cluster_id": 0, "canonical": "mobile-commerce"}]},
        )
        client.models.generate_content.return_value = naming_response

        with patch(
            "src.research_library.canonicalization_service"
            ".embedding_service.embed_text",
            side_effect=lambda client, text, task_type: [1.0, 0.0],
        ):
            summary = await bootstrap(client, "m", repo, threshold=0.9)

        assert summary["aliases"] == 2
        assert summary["clusters"][0]["canonical"] == "mobile-commerce"
        assert repo.upsert_alias.await_count == 2


class TestLoadVocabulary:
    def test_only_tag_kind_and_deduplicated(self):
        aliases = [
            TagAliasModel(raw="mobiel", canonical="mobile-commerce", kind="tag"),
            TagAliasModel(
                raw="smartphone", canonical="mobile-commerce", kind="tag"
            ),
            TagAliasModel(raw="share", canonical="share", kind="metric"),
        ]

        assert load_vocabulary(aliases) == ["mobile-commerce"]
