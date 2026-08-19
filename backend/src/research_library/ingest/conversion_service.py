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

"""Office-format -> PDF conversion via headless LibreOffice.

DOCX/PPT/PPTX/ODP uploads are normalized to PDF before page rendering.
LibreOffice is the only converter that handles both word-processing and
presentation formats faithfully; it runs headless with a per-invocation
isolated user profile because two soffice processes sharing a profile
directory hang or fail. A conversion that times out is retried once with a
fresh profile (a corrupt profile from a killed run must not poison the
retry).
"""

import logging
import os
import shutil
import subprocess
import tempfile
import uuid

logger = logging.getLogger(__name__)

# Formats that need LibreOffice before they can be rendered.
CONVERTIBLE_EXTENSIONS = {".docx", ".ppt", ".pptx", ".odp"}

_SOFFICE_TIMEOUT_SECONDS = int(os.getenv("RL_SOFFICE_TIMEOUT_SECONDS", "120"))


class ConversionError(Exception):
    """Raised when an office document could not be converted to PDF."""


def needs_conversion(filename: str) -> bool:
    """Whether this file must go through LibreOffice before rendering."""
    return os.path.splitext(filename)[1].lower() in CONVERTIBLE_EXTENSIONS


def convert_to_pdf(
    input_path: str,
    output_dir: str,
    timeout_seconds: int = _SOFFICE_TIMEOUT_SECONDS,
) -> str:
    """Converts an office document to PDF and returns the output path.

    Runs ``soffice --headless`` with an isolated user profile and a hard
    timeout, retrying once with a fresh profile on timeout or failure.
    """
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            return _convert_once(input_path, output_dir, timeout_seconds)
        except ConversionError as e:
            last_error = e
            logger.warning(
                "LibreOffice conversion attempt %s failed for %s: %s",
                attempt + 1,
                input_path,
                e,
            )
    raise ConversionError(
        f"Could not convert {os.path.basename(input_path)} to PDF: "
        f"{last_error}"
    )


def _convert_once(
    input_path: str,
    output_dir: str,
    timeout_seconds: int,
) -> str:
    """A single soffice invocation with its own throwaway user profile."""
    profile_dir = os.path.join(
        tempfile.gettempdir(), f"lo-profile-{uuid.uuid4()}"
    )
    command = [
        "soffice",
        "--headless",
        "--nologo",
        "--nodefault",
        "--norestore",
        "--nolockcheck",
        f"-env:UserInstallation=file://{profile_dir}",
        "--convert-to",
        "pdf",
        "--outdir",
        output_dir,
        input_path,
    ]
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as e:
        # Not retryable and worth a distinct message: the binary is absent
        # from the container image, not a problem with this document.
        raise ConversionError(
            "LibreOffice (soffice) is not installed in this environment."
        ) from e
    except subprocess.TimeoutExpired as e:
        raise ConversionError(
            f"conversion timed out after {timeout_seconds}s"
        ) from e
    except subprocess.CalledProcessError as e:
        raise ConversionError(
            f"soffice exited with {e.returncode}: {e.stderr or e.stdout}"
        ) from e
    finally:
        shutil.rmtree(profile_dir, ignore_errors=True)

    base = os.path.splitext(os.path.basename(input_path))[0]
    output_path = os.path.join(output_dir, f"{base}.pdf")
    if not os.path.exists(output_path):
        # soffice sometimes exits 0 without producing output (e.g. password
        # protected or unreadable input).
        raise ConversionError(
            f"soffice produced no output PDF ({result.stdout or 'no output'})"
        )
    return output_path
