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
"""Tests for the financial glossary seed and the domain split."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.translations import markets
from src.translations.documents import financial_glossary as fg
from src.translations.documents.service import DocumentTranslationService
from src.translations.schema.glossary_term_model import GlossaryTermModel


class TestSeed:
    def test_every_term_pair_is_populated_and_unique(self):
        sources = [s for s, _ in fg.FINANCIAL_TERMS_NL]
        assert len(sources) == len(set(sources)), "duplicate source terms"
        assert all(s.strip() and t.strip() for s, t in fg.FINANCIAL_TERMS_NL)

    def test_ifrs_terms_map_to_their_dutch_equivalents(self):
        terms = dict(fg.FINANCIAL_TERMS_NL)
        assert terms["impairment"] == "bijzondere waardevermindering"
        assert terms["fair value"] == "reële waarde"
        assert terms["deferred tax assets"] == "latente belastingvorderingen"
        assert terms["going concern"] == "continuïteit"
        # Dutch statutory bodies, not literal translations.
        assert terms["Supervisory Board"] == "Raad van Commissarissen"
        assert terms["large company regime"] == "structuurregime"

    def test_dutch_markets_get_terms_and_protected_names(self):
        entries = fg.seed_entries("NL")
        assert all(e["domain"] == "financial" for e in entries)
        assert all(e["language"] == "NL" for e in entries)
        terms = [e for e in entries if not e["do_not_translate"]]
        protected = [e for e in entries if e["do_not_translate"]]
        assert len(terms) == len(fg.FINANCIAL_TERMS_NL)
        assert len(protected) == len(fg.DO_NOT_TRANSLATE)
        assert all(e["source"] == e["target"] for e in protected)

    def test_flemish_shares_the_dutch_terminology(self):
        assert len(fg.seed_entries("BENL")) == len(fg.seed_entries("NL"))

    def test_unvetted_markets_get_protected_names_only(self):
        """We do not invent terminology for languages we haven't vetted."""
        entries = fg.seed_entries("DE")
        assert entries
        assert all(e["do_not_translate"] for e in entries)

    def test_every_target_market_can_be_seeded(self):
        for market in markets.TARGET_MARKETS:
            assert fg.seed_entries(market), f"no entries for {market}"

    def test_standards_and_metrics_are_never_translated(self):
        for name in ("IFRS", "EBITDA", "Hunkemöller", "Together Tomorrow"):
            assert name in fg.DO_NOT_TRANSLATE


def _service(terms):
    repo = MagicMock()
    repo.find_by_domain = AsyncMock(return_value=terms)
    service = DocumentTranslationService(
        jobs=AsyncMock(),
        segments=AsyncMock(),
        memory=AsyncMock(),
        gcs=MagicMock(),
        signer=MagicMock(),
    )
    return service, repo


def _term(source, target, domain="financial", dnt=False):
    return GlossaryTermModel(
        id=1,
        language="NL",
        source=source,
        target=target,
        domain=domain,
        do_not_translate=dnt,
    )


@pytest.mark.anyio
async def test_loading_a_glossary_splits_terms_from_protected_names(
    monkeypatch,
):
    terms = [
        _term("impairment", "bijzondere waardevermindering"),
        _term("EBITDA", "EBITDA", dnt=True),
    ]
    service, repo = _service(terms)
    monkeypatch.setattr(
        "src.translations.documents.service.GlossaryRepository",
        lambda db: repo,
    )

    glossary, protected = await service._load_glossary("NL")

    assert [(g.source, g.target) for g in glossary] == [
        ("impairment", "bijzondere waardevermindering")
    ]
    assert protected == ["EBITDA"]
    assert repo.find_by_domain.await_args.args[0] == "financial"
    assert repo.find_by_domain.await_args.kwargs == {"language": "NL"}


@pytest.mark.anyio
async def test_an_unseeded_market_still_protects_names(monkeypatch):
    service, repo = _service([])
    monkeypatch.setattr(
        "src.translations.documents.service.GlossaryRepository",
        lambda db: repo,
    )

    glossary, protected = await service._load_glossary("SE")

    assert glossary == []
    assert protected == fg.DO_NOT_TRANSLATE
