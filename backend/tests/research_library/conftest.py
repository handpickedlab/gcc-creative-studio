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

"""Shared fixtures for the research library tests."""

import pytest

from src.research_library.ingest import ingest_queue


@pytest.fixture(autouse=True)
def clear_ingest_queue():
    """Empties the process-local ingest queue around every test.

    Reservations are module state released by the worker, which these tests
    mock away — without this, queued document ids leak between tests and the
    queue eventually reports itself full.
    """
    ingest_queue.reset()
    yield
    ingest_queue.reset()
