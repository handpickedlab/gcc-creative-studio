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

"""Turn a pipeline exception into a message that names the real cause.

ADK's ``ParallelAgent`` runs the web researchers inside an ``asyncio.TaskGroup``;
when a sub-agent raises, the group re-raises an ``ExceptionGroup`` whose ``str()``
is the unhelpful ``"unhandled errors in a task group (N sub-exceptions)"``.
Persisting that verbatim as a report's ``error_message`` (and surfacing it to the
user) hides what actually failed -- almost always a Vertex 429/5xx from a
researcher. ``describe_exception`` flattens the (possibly nested) group down to
its leaf exceptions so the stored message points at the root cause.
"""

from __future__ import annotations


def describe_exception(exc: BaseException) -> str:
    """A readable, de-duplicated summary of ``exc``'s real cause(s).

    Plain exceptions are returned as ``"Type: message"``. Exception groups are
    unwrapped to their leaves; identical concurrent failures (e.g. every slot
    hitting the same 429) collapse to one entry, order preserved.
    """
    leaves = _leaf_exceptions(exc)
    seen: set[str] = set()
    unique: list[str] = []
    for leaf in leaves:
        text = f"{type(leaf).__name__}: {leaf}".strip()
        if text not in seen:
            seen.add(text)
            unique.append(text)
    return " | ".join(unique) if unique else f"{type(exc).__name__}: {exc}"


def _leaf_exceptions(exc: BaseException) -> list[BaseException]:
    """Depth-first list of the non-group exceptions inside ``exc``."""
    if isinstance(exc, BaseExceptionGroup):
        leaves: list[BaseException] = []
        for sub in exc.exceptions:
            leaves.extend(_leaf_exceptions(sub))
        return leaves
    return [exc]
