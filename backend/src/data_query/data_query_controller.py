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

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from src.auth.auth_guard import RoleChecker
from src.data_query.data_query_service import DataQueryService
from src.data_query.dto.data_query_dto import AskRequestDto
from src.data_query.schema.data_query_run_model import DataQueryRunModel
from src.data_query.schema.data_query_sheet_model import DataQuerySheetModel
from src.users.user_model import UserRoleEnum

router = APIRouter(
    prefix="/api/data-query",
    tags=["Data Query"],
    responses={404: {"description": "Not found"}},
    dependencies=[
        Depends(
            RoleChecker(
                allowed_roles=[
                    UserRoleEnum.ADMIN,
                    UserRoleEnum.USER,
                ],
            ),
        ),
    ],
)


MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB


@router.post("/upload", summary="Upload a .csv/.xlsx sheet into the warehouse")
async def upload_sheet(
    file: UploadFile = File(...),
    service: DataQueryService = Depends(),
):
    # Read in 1 MB chunks and bail out early so an oversized file can't OOM the
    # container before we ever look at it.
    data = b""
    while chunk := await file.read(1024 * 1024):
        data += chunk
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="File too large (max 25 MB).",
            )
    return {"loaded": await service.ingest(file.filename or "upload", data)}


@router.get("/sources", summary="List the uploaded tables (query sidebar)")
async def list_sources(service: DataQueryService = Depends()):
    return {"tables": await service.list_sources()}


@router.get(
    "/sheets",
    response_model=list[DataQuerySheetModel],
    summary="List uploaded sheets with metadata (manage page)",
)
async def list_sheets(service: DataQueryService = Depends()):
    return await service.list_sheets()


@router.delete(
    "/sheets/{sheet_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an uploaded sheet (catalog + warehouse + raw file)",
)
async def delete_sheet(sheet_id: int, service: DataQueryService = Depends()):
    if not await service.delete_sheet(sheet_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Sheet not found."
        )


@router.post(
    "/ask",
    response_model=DataQueryRunModel,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a background ask over the data; poll GET /ask/{id}",
)
async def ask(body: AskRequestDto, service: DataQueryService = Depends()):
    """Kick the agent off in the background and return the run immediately.

    Deep retrieval can run longer than the hosting rewrite's ~60s timeout on a
    buffered streaming response, so the answer is built in the background and
    the client polls ``GET /ask/{id}`` for accumulating steps + the final
    answer.
    """
    history = (
        [t.model_dump() for t in body.history] if body.history else None
    )
    return await service.start_ask(
        body.question,
        body.allowed_tables,
        body.allowed_documents,
        history=history,
    )


@router.get(
    "/ask/{run_id}",
    response_model=DataQueryRunModel,
    summary="Poll a background ask run for progress + the final answer",
)
async def get_ask(run_id: str, service: DataQueryService = Depends()):
    run = await service.get_run(run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Run not found."
        )
    return run
