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

"""Scopes GenMedia/Vertex AI calls to a dedicated project and credential.

The rest of the application authenticates via Application Default Credentials
(ADC) against the deployment project. Only the Vertex/GenMedia clients use these
helpers, so they can optionally target a different project (e.g. a client's
project) using a dedicated service-account key — without repointing the whole
application's credentials.

When ``VERTEX_CREDENTIALS_FILE`` is unset (the local-dev default), both helpers
fall back to ADC and the deployment project, so behaviour is unchanged.
"""

import logging

from google.oauth2 import service_account

from src.config.config_service import config_service

logger = logging.getLogger(__name__)

# Vertex AI requires the broad cloud-platform scope.
_VERTEX_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

_credentials: service_account.Credentials | None = None
_loaded = False


def get_vertex_project() -> str:
    """Returns the project that Vertex/GenMedia calls should target.

    Defaults to the application ``PROJECT_ID`` (resolved in ConfigService).
    """
    return config_service.VERTEX_PROJECT_ID or config_service.PROJECT_ID


def get_vertex_credentials() -> service_account.Credentials | None:
    """Returns dedicated service-account credentials for Vertex AI.

    Loads the key referenced by ``VERTEX_CREDENTIALS_FILE`` once and caches it.
    Returns ``None`` when no key is configured, signalling clients to fall back
    to Application Default Credentials.
    """
    global _credentials, _loaded
    if _loaded:
        return _credentials

    key_file = config_service.VERTEX_CREDENTIALS_FILE
    if key_file:
        logger.info(
            "Loading dedicated Vertex AI credentials from %s (project '%s')",
            key_file,
            get_vertex_project(),
        )
        _credentials = service_account.Credentials.from_service_account_file(
            key_file, scopes=_VERTEX_SCOPES
        )
    else:
        _credentials = None
    _loaded = True
    return _credentials
