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

"""Schema-integrity tests for the intake definitions.

These guard the invariants the UI and brief builder rely on: stable keys, a
complete lookup table, and a stepper that covers every field exactly once.
"""

from src.deep_research.agent.intake import (
    CUSTOMER_LENSES,
    FIELDS_BY_KEY,
    INTAKE_FIELDS,
    SEGMENTS,
    STEPPER_GROUPS,
)


def test_field_keys_are_unique():
    keys = [f.key for f in INTAKE_FIELDS]
    assert len(keys) == len(set(keys)), "intake field keys must be unique"


def test_fields_by_key_covers_every_field():
    assert set(FIELDS_BY_KEY) == {f.key for f in INTAKE_FIELDS}
    assert all(FIELDS_BY_KEY[f.key] is f for f in INTAKE_FIELDS)


def test_stepper_covers_each_field_exactly_once():
    stepped = [key for _title, keys in STEPPER_GROUPS for key in keys]
    assert sorted(stepped) == sorted(FIELDS_BY_KEY), (
        "every intake field must appear in exactly one stepper group"
    )
    assert len(stepped) == len(set(stepped)), "no field may appear in two groups"


def test_stepper_references_only_known_keys():
    for _title, keys in STEPPER_GROUPS:
        for key in keys:
            assert key in FIELDS_BY_KEY, f"unknown field key in stepper: {key}"


def test_customer_lenses_embed_the_segments():
    assert all(segment in CUSTOMER_LENSES for segment in SEGMENTS)
