# Copyright 2025 Google LLC
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

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from src.auth.auth_guard import RoleChecker, get_current_user
from src.common.dto.pagination_response_dto import PaginationResponseDto
from src.common.schema.media_item_model import JobStatusEnum
from src.deep_research.deep_research_service import DeepResearchService
from src.deep_research.dto.deep_research_search_dto import DeepResearchSearchDto
from src.deep_research.dto.intake_schema_dto import IntakeSchemaDto
from src.deep_research.dto.start_deep_research_dto import StartDeepResearchDto
from src.deep_research.schema.deep_research_model import DeepResearchReportModel
from src.users.user_model import UserModel, UserRoleEnum

user_only = Depends(
    RoleChecker(allowed_roles=[UserRoleEnum.USER, UserRoleEnum.ADMIN])
)

router = APIRouter(
    prefix="/api/deep-research",
    tags=["Deep Research"],
    dependencies=[user_only],
)


@router.post(
    "/",
    response_model=DeepResearchReportModel,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a Consumer Sentiment Scan",
)
async def start_research(
    request: Request,
    request_dto: StartDeepResearchDto,
    current_user: UserModel = Depends(get_current_user),
    service: DeepResearchService = Depends(),
):
    """Assemble the research brief from the intake, persist a placeholder report
    and kick off the multi-agent deep-research pipeline in the background.

    Returns the placeholder immediately (status ``processing``); poll
    ``GET /{report_id}`` for the finished report.
    """
    executor = request.app.state.executor
    return await service.start_research(
        dto=request_dto,
        current_user=current_user,
        executor=executor,
    )


@router.get(
    "/intake-schema",
    response_model=IntakeSchemaDto,
    summary="Get the intake field schema",
)
async def get_intake_schema(
    service: DeepResearchService = Depends(),
):
    """Return the intake fields and stepper grouping so the client can render
    the Consumer Sentiment Scan wizard.
    """
    return service.get_intake_schema()


@router.get(
    "/",
    response_model=PaginationResponseDto[DeepResearchReportModel],
    summary="List your deep research reports",
)
async def list_reports(
    limit: int = Query(default=12, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    report_status: JobStatusEnum | None = Query(default=None, alias="status"),
    current_user: UserModel = Depends(get_current_user),
    service: DeepResearchService = Depends(),
):
    """List the current user's reports, newest first."""
    search_dto = DeepResearchSearchDto(
        limit=limit, offset=offset, status=report_status
    )
    return await service.list_reports(search_dto, current_user)


@router.get(
    "/{report_id}",
    response_model=DeepResearchReportModel,
    summary="Get a single deep research report",
)
async def get_report(
    report_id: int,
    current_user: UserModel = Depends(get_current_user),
    service: DeepResearchService = Depends(),
):
    """Retrieve one report by ID (owner or admin only)."""
    report = await service.get_report(report_id, current_user)
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deep research report not found.",
        )
    return report


@router.delete(
    "/{report_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a deep research report",
)
async def delete_report(
    report_id: int,
    current_user: UserModel = Depends(get_current_user),
    service: DeepResearchService = Depends(),
):
    """Delete a report by ID (owner or admin only)."""
    await service.delete_report(report_id, current_user)
