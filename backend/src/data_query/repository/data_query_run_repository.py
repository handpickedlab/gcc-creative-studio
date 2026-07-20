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

"""Repository for background data-query ``/ask`` runs."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.base_repository import BaseStringRepository
from src.data_query.schema.data_query_run_model import (
    DataQueryRun,
    DataQueryRunModel,
)
from src.database import get_db


class DataQueryRunRepository(
    BaseStringRepository[DataQueryRun, DataQueryRunModel]
):
    """Database operations for background ask runs (UUID string ids)."""

    def __init__(self, db: AsyncSession = Depends(get_db)):
        super().__init__(
            model=DataQueryRun, schema=DataQueryRunModel, db=db
        )
