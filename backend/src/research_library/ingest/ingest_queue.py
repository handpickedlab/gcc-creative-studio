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

"""Bounded, process-local reservations for documents queued for ingest.

The ingest executor lives inside the API process, so everything still in its
queue dies with the instance. Two things follow, and both live here:

- the queue is capped (``config.MAX_QUEUED``), so a bulk upload leaves its
  backlog in the database as PROCESSING rows instead of in memory, and
- the process knows which documents it has accepted, so the stalled-ingest
  sweeper can tell "queued right here" apart from "abandoned by a dead
  instance" and never submits the same document twice.

Reservations are taken by whoever submits (upload, reprocess, sweeper) and
released by the worker itself, in a ``finally``, so a crashed run frees its
slot.
"""

import logging
import threading

from src.research_library import config

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_reserved: set[int] = set()


def try_reserve(document_id: int) -> bool:
    """Takes a queue slot for a document.

    Returns False when the queue is full or this process has already
    accepted the document — in both cases the caller must leave the document
    in PROCESSING and let the sweeper come back to it.
    """
    with _lock:
        if document_id in _reserved:
            return False
        if len(_reserved) >= config.MAX_QUEUED:
            return False
        _reserved.add(document_id)
        return True


def release(document_id: int) -> None:
    """Frees a document's queue slot. Safe to call for an unreserved id."""
    with _lock:
        _reserved.discard(document_id)


def reserved_ids() -> set[int]:
    """A snapshot of the documents this process currently has in flight."""
    with _lock:
        return set(_reserved)


def free_slots() -> int:
    """How many more documents this process may accept right now."""
    with _lock:
        return max(0, config.MAX_QUEUED - len(_reserved))


def reset() -> None:
    """Drops every reservation. For shutdown and for test isolation."""
    with _lock:
        _reserved.clear()
