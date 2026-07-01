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

"""Tests for the DeepResearchService business logic (repo + executor mocked)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from src.common.schema.media_item_model import JobStatusEnum
from src.deep_research.agent.intake import INTAKE_FIELDS, STEPPER_GROUPS
from src.deep_research.deep_research_service import DeepResearchService
from src.deep_research.dto.start_deep_research_dto import (
    INTAKE_KEYS,
    StartDeepResearchDto,
)
from src.deep_research.schema.deep_research_model import DeepResearchReportModel
from src.users.user_model import UserModel, UserRoleEnum


def _user(user_id: int = 1, roles=None) -> UserModel:
    return UserModel(
        id=user_id,
        email=f"user{user_id}@example.com",
        roles=roles or [UserRoleEnum.USER],
        name="User",
        picture="",
    )


def _report(report_id: int = 5, user_id: int = 1) -> DeepResearchReportModel:
    return DeepResearchReportModel(
        id=report_id,
        user_id=user_id,
        topic="Comfort bras",
        status=JobStatusEnum.PROCESSING,
        intake={"research_topic": "Comfort bras"},
    )


@pytest.fixture(name="repo")
def fixture_repo():
    return AsyncMock()


@pytest.fixture(name="service")
def fixture_service(repo):
    return DeepResearchService(repo=repo)


# --- intake / DTO contract --------------------------------------------------


def test_intake_keys_match_engine_schema():
    # Guards drift between the request DTO and the engine's intake fields.
    assert set(INTAKE_KEYS) == {f.key for f in INTAKE_FIELDS}


def test_intake_values_excludes_max_iterations():
    dto = StartDeepResearchDto(research_topic="x", max_iterations=5)
    values = dto.intake_values()
    assert set(values) == set(INTAKE_KEYS)
    assert "max_iterations" not in values


def test_get_intake_schema_matches_engine(service):
    schema = service.get_intake_schema()
    assert [f.key for f in schema.fields] == [f.key for f in INTAKE_FIELDS]
    assert [s.title for s in schema.steps] == [t for t, _ in STEPPER_GROUPS]


# --- start_research ---------------------------------------------------------


@pytest.mark.anyio
async def test_start_research_persists_placeholder_and_queues_job(
    service, repo
):
    repo.create.return_value = _report(report_id=7)
    executor = MagicMock()
    dto = StartDeepResearchDto(research_topic="Comfort bras", market="Germany")

    result = await service.start_research(dto, _user(1), executor)

    # A placeholder is created with PROCESSING status and an assembled brief.
    repo.create.assert_awaited_once()
    placeholder = repo.create.call_args.args[0]
    assert placeholder.topic == "Comfort bras"
    assert placeholder.user_id == 1
    assert placeholder.status == JobStatusEnum.PROCESSING
    assert placeholder.brief and "Germany" in placeholder.brief
    assert placeholder.intake["research_topic"] == "Comfort bras"

    # The pipeline is dispatched to the background executor for the new row.
    executor.submit.assert_called_once()
    assert executor.submit.call_args.kwargs["report_id"] == 7
    assert result.id == 7


# --- ownership checks -------------------------------------------------------


@pytest.mark.anyio
async def test_get_report_returns_owned_report(service, repo):
    repo.get_by_id.return_value = _report(user_id=1)
    result = await service.get_report(5, _user(1))
    assert result is not None


@pytest.mark.anyio
async def test_get_report_forbidden_for_other_user(service, repo):
    repo.get_by_id.return_value = _report(user_id=1)
    with pytest.raises(HTTPException) as exc:
        await service.get_report(5, _user(2))
    assert exc.value.status_code == 403


@pytest.mark.anyio
async def test_get_report_allows_admin(service, repo):
    repo.get_by_id.return_value = _report(user_id=1)
    result = await service.get_report(5, _user(2, roles=[UserRoleEnum.ADMIN]))
    assert result is not None


@pytest.mark.anyio
async def test_get_report_returns_none_when_missing(service, repo):
    repo.get_by_id.return_value = None
    assert await service.get_report(999, _user(1)) is None


@pytest.mark.anyio
async def test_delete_report_forbidden_for_other_user(service, repo):
    repo.get_by_id.return_value = _report(user_id=1)
    with pytest.raises(HTTPException) as exc:
        await service.delete_report(5, _user(2))
    assert exc.value.status_code == 403
    repo.delete.assert_not_called()


@pytest.mark.anyio
async def test_delete_report_deletes_for_owner(service, repo):
    repo.get_by_id.return_value = _report(report_id=5, user_id=1)
    await service.delete_report(5, _user(1))
    repo.delete.assert_awaited_once_with(5)


@pytest.mark.anyio
async def test_delete_report_noop_when_missing(service, repo):
    repo.get_by_id.return_value = None
    await service.delete_report(999, _user(1))
    repo.delete.assert_not_called()
