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

from src.common.dto.base_search_dto import BaseSearchDto
from src.common.schema.media_item_model import JobStatusEnum


class DeepResearchSearchDto(BaseSearchDto):
    """Query parameters for listing a user's deep research reports."""

    status: JobStatusEnum | None = None
