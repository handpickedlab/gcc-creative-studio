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

variable "project_id" {}
variable "region" {}
variable "db_name" { default = "creative_studio" }
variable "db_user" { default = "studio_user" }
variable "db_password" { sensitive = true }

variable "db_tier" {
  type        = string
  description = "Cloud SQL machine type. Shared-core db-g1-small is the cheapest dedicated-enough SKU; Enterprise Plus db-perf-optimized-N-* is ~8x that and stays billed 24/7."
  default     = "db-g1-small"
}

variable "db_edition" {
  type        = string
  description = "ENTERPRISE is enough for this app. ENTERPRISE_PLUS is required only for db-perf-optimized-* / C4 machine series."
  default     = "ENTERPRISE"

  validation {
    condition     = contains(["ENTERPRISE", "ENTERPRISE_PLUS"], var.db_edition)
    error_message = "db_edition must be ENTERPRISE or ENTERPRISE_PLUS."
  }
}
