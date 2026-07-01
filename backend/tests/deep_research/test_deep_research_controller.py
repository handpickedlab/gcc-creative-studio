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

"""Tests for the Deep Research controller (service mocked)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import status

from main import app
from src.common.dto.pagination_response_dto import PaginationResponseDto
from src.common.schema.media_item_model import JobStatusEnum
from src.deep_research.deep_research_service import DeepResearchService
from src.deep_research.schema.deep_research_model import DeepResearchReportModel


def _report(
    report_id: int = 1,
    user_id: int = 1,
    job_status: JobStatusEnum = JobStatusEnum.PROCESSING,
    report: str | None = None,
) -> DeepResearchReportModel:
    return DeepResearchReportModel(
        id=report_id,
        user_id=user_id,
        topic="Comfort bras",
        status=job_status,
        intake={"research_topic": "Comfort bras"},
        report=report,
    )


@pytest.fixture(name="mock_service")
def fixture_mock_service():
    return AsyncMock()


@pytest.fixture(name="override_service", autouse=True)
def fixture_override_service(mock_service):
    app.dependency_overrides[DeepResearchService] = lambda: mock_service
    yield
    app.dependency_overrides.pop(DeepResearchService, None)


class TestStartResearch:
    """POST /api/deep-research/."""

    def test_start_success(self, api_client, mock_service):
        mock_service.start_research.return_value = _report()
        response = api_client.post(
            "/api/deep-research/",
            json={"researchTopic": "Comfort bras", "market": "Germany"},
        )
        assert response.status_code == status.HTTP_202_ACCEPTED
        data = response.json()
        assert data["topic"] == "Comfort bras"
        assert data["status"] == "processing"

    def test_start_requires_topic(self, api_client):
        response = api_client.post(
            "/api/deep-research/", json={"market": "Germany"}
        )
        assert response.status_code == 422


class TestListReports:
    """GET /api/deep-research/."""

    def test_list_success(self, api_client, mock_service):
        mock_service.list_reports.return_value = PaginationResponseDto[
            DeepResearchReportModel
        ](
            count=1,
            page=1,
            page_size=12,
            total_pages=1,
            data=[_report(job_status=JobStatusEnum.COMPLETED, report="# R")],
        )
        response = api_client.get("/api/deep-research/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["count"] == 1
        assert data["data"][0]["status"] == "completed"


class TestGetReport:
    """GET /api/deep-research/{report_id}."""

    def test_get_found(self, api_client, mock_service):
        mock_service.get_report.return_value = _report(report_id=5, report="# R")
        response = api_client.get("/api/deep-research/5")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["id"] == 5

    def test_get_not_found(self, api_client, mock_service):
        mock_service.get_report.return_value = None
        response = api_client.get("/api/deep-research/999")
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestDeleteReport:
    """DELETE /api/deep-research/{report_id}."""

    def test_delete_success(self, api_client, mock_service):
        mock_service.delete_report.return_value = None
        response = api_client.delete("/api/deep-research/5")
        assert response.status_code == status.HTTP_204_NO_CONTENT


class TestIntakeSchema:
    """GET /api/deep-research/intake-schema."""

    def test_intake_schema(self, api_client, mock_service):
        # get_intake_schema is synchronous; use the real service to build a
        # valid payload and hand it back via a plain (non-async) mock.
        real_schema = DeepResearchService(
            repo=AsyncMock()
        ).get_intake_schema()
        mock_service.get_intake_schema = MagicMock(return_value=real_schema)

        response = api_client.get("/api/deep-research/intake-schema")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["fields"]) == 11
        assert data["fields"][0]["key"] == "research_topic"
        assert len(data["steps"]) == 4
