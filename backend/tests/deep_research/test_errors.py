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

"""Tests for unwrapping a pipeline exception to its real cause."""

from src.deep_research.errors import describe_exception


def test_plain_exception_is_typed_and_messaged():
    assert describe_exception(ValueError("boom")) == "ValueError: boom"


def test_task_group_is_unwrapped_to_its_leaf():
    # What ADK's ParallelAgent actually raises: the leaf cause is buried in a
    # group whose own str() is the unhelpful "unhandled errors in a task group".
    group = ExceptionGroup("unhandled errors in a task group", [RuntimeError("429 RESOURCE_EXHAUSTED")])
    assert describe_exception(group) == "RuntimeError: 429 RESOURCE_EXHAUSTED"


def test_nested_groups_are_flattened():
    inner = ExceptionGroup("inner", [TimeoutError("read timed out")])
    outer = ExceptionGroup("outer", [inner])
    assert describe_exception(outer) == "TimeoutError: read timed out"


def test_identical_concurrent_failures_collapse():
    # Every slot hitting the same 429 should read as one cause, not four.
    group = ExceptionGroup(
        "task group",
        [RuntimeError("429 quota exceeded") for _ in range(4)],
    )
    assert describe_exception(group) == "RuntimeError: 429 quota exceeded"


def test_distinct_failures_are_all_listed():
    group = ExceptionGroup(
        "task group",
        [RuntimeError("429 quota exceeded"), ValueError("bad request")],
    )
    assert describe_exception(group) == (
        "RuntimeError: 429 quota exceeded | ValueError: bad request"
    )
