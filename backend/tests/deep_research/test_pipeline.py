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

"""Tests for the reusable pipeline runner's public contract.

The standalone repo's ``slugify``/``save_report`` file helpers were dropped in
the backend port -- the service persists reports to the database instead -- so
this covers the contract that remains: the package's re-exports and the
server-side session identifiers.
"""

import inspect

from src.deep_research.agent import build_root_agent, pipeline, run_pipeline


def test_package_reexports_builder_and_runner():
    assert callable(build_root_agent)
    assert callable(run_pipeline)


def test_run_pipeline_is_async():
    assert inspect.iscoroutinefunction(run_pipeline)


def test_backend_session_identifiers():
    # The port runs the pipeline server-side, not as a local CLI user.
    assert pipeline.APP_NAME == "deep_research"
    assert pipeline.USER_ID == "backend"
