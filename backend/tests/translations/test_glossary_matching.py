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
"""Unit 4: do-not-translate terms + word-boundary glossary matching."""

from src.translations import localization
from src.translations.schema.glossary_term_model import GlossaryTermModel


def _term(source, target=None, do_not_translate=False, id=1):
    return GlossaryTermModel(
        id=id,
        language="DE",
        source=source,
        target=target or source,
        do_not_translate=do_not_translate,
    )


def test_do_not_translate_term_goes_to_verbatim_list():
    terms = [_term("cashmere", do_not_translate=True)]
    normal, dnt = localization.split_glossary_terms(
        terms, "Discover our cashmere collection"
    )
    assert normal == []
    assert [t.source for t in dnt] == ["cashmere"]


def test_normal_term_goes_to_glossary_list():
    terms = [_term("sale", target="Ausverkauf")]
    normal, dnt = localization.split_glossary_terms(terms, "Big sale this week")
    assert [t.source for t in normal] == ["sale"]
    assert dnt == []


def test_word_boundary_prevents_substring_false_positive():
    # "cat" must not match inside "category".
    terms = [_term("cat")]
    normal, dnt = localization.split_glossary_terms(
        terms, "Browse the category page"
    )
    assert normal == [] and dnt == []


def test_matching_is_case_insensitive():
    terms = [_term("Cashmere", do_not_translate=True)]
    _, dnt = localization.split_glossary_terms(terms, "our CASHMERE line")
    assert len(dnt) == 1


def test_non_matching_term_is_excluded():
    terms = [_term("linen")]
    normal, dnt = localization.split_glossary_terms(terms, "our wool sweaters")
    assert normal == [] and dnt == []


def test_empty_source_is_skipped():
    terms = [_term("")]
    normal, dnt = localization.split_glossary_terms(terms, "anything")
    assert normal == [] and dnt == []


def test_limit_caps_each_list():
    terms = [_term(f"term{i}", id=i) for i in range(5)]
    text = " ".join(f"term{i}" for i in range(5))
    normal, _ = localization.split_glossary_terms(terms, text, limit=2)
    assert len(normal) == 2
