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

from src.common.base_dto import BaseDto


class IntakeFieldDto(BaseDto):
    """One intake question, for the frontend to render the wizard."""

    key: str
    label: str
    type: str
    brief_label: str
    options: list[str] = []
    example: str = ""
    help: str = ""


class IntakeStepDto(BaseDto):
    """One step of the intake wizard: a title and the field keys it groups."""

    title: str
    field_keys: list[str]


class IntakeSchemaDto(BaseDto):
    """The full intake schema: all fields plus the stepper grouping."""

    fields: list[IntakeFieldDto]
    steps: list[IntakeStepDto]
