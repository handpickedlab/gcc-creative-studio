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

resource "random_id" "db_name_suffix" {
  byte_length = 4
}

resource "google_sql_database_instance" "default" {
  name             = "creative-studio-db-${random_id.db_name_suffix.hex}"
  database_version = "POSTGRES_18" # Latest stable version
  region           = var.region
  project          = var.project_id

  settings {
    # Shared-core g1-small (1 shared vCPU / 1.7 GiB) instead of the
    # upstream Enterprise Plus db-perf-optimized-N-2 (2 vCPU / 16 GiB).
    # Cloud SQL cannot scale to zero, so this is the 24/7 hosting bill.
    tier              = var.db_tier
    edition           = var.db_edition
    availability_type = "ZONAL"

    # Enable IAM Authentication for better security (optional but recommended)
    database_flags {
      name  = "cloudsql.iam_authentication"
      value = "on"
    }

    ip_configuration {
      ipv4_enabled = true # Easy connectivity from Cloud Run without VPC peering complexity
    }
  }
  
  deletion_protection = false # Set to true for production
}

resource "google_sql_database" "default" {
  name     = var.db_name
  instance = google_sql_database_instance.default.name
  project  = var.project_id
}

resource "google_sql_user" "default" {
  name     = var.db_user
  instance = google_sql_database_instance.default.name
  password = var.db_password
  project  = var.project_id
}
