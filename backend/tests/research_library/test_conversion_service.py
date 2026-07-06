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

"""Tests for research_library.ingest.conversion_service.

LibreOffice itself is not exercised (it is absent from dev machines and CI);
these tests pin down the invocation contract: command shape, isolated
profiles, timeout handling, and the retry-once-with-fresh-profile behavior.
"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from src.research_library.ingest.conversion_service import (
    ConversionError,
    convert_to_pdf,
    needs_conversion,
)


def _completed(returncode=0):
    result = MagicMock()
    result.returncode = returncode
    result.stdout = "convert ok"
    result.stderr = ""
    return result


class TestNeedsConversion:
    def test_office_formats_need_conversion(self):
        assert needs_conversion("deck.pptx")
        assert needs_conversion("Report.DOCX")
        assert needs_conversion("old-deck.ppt")
        assert needs_conversion("slides.odp")

    def test_pdf_and_images_do_not(self):
        assert not needs_conversion("report.pdf")
        assert not needs_conversion("infographic.png")


class TestConvertToPdf:
    @patch("src.research_library.ingest.conversion_service.subprocess.run")
    def test_builds_isolated_headless_command(self, mock_run, tmp_path):
        input_path = str(tmp_path / "deck.pptx")
        output_pdf = tmp_path / "deck.pdf"
        output_pdf.write_bytes(b"%PDF-1.4")
        mock_run.return_value = _completed()

        result = convert_to_pdf(input_path, str(tmp_path))

        assert result == str(output_pdf)
        command = mock_run.call_args.args[0]
        assert command[0] == "soffice"
        assert "--headless" in command
        assert any(
            arg.startswith("-env:UserInstallation=file://") for arg in command
        )
        assert command[-1] == input_path
        assert mock_run.call_args.kwargs["timeout"] == 120

    @patch("src.research_library.ingest.conversion_service.subprocess.run")
    def test_timeout_retries_once_with_fresh_profile(self, mock_run, tmp_path):
        input_path = str(tmp_path / "deck.pptx")
        (tmp_path / "deck.pdf").write_bytes(b"%PDF-1.4")
        mock_run.side_effect = [
            subprocess.TimeoutExpired(cmd="soffice", timeout=1),
            _completed(),
        ]

        result = convert_to_pdf(input_path, str(tmp_path), timeout_seconds=1)

        assert result.endswith("deck.pdf")
        assert mock_run.call_count == 2
        first_profile = next(
            arg
            for arg in mock_run.call_args_list[0].args[0]
            if arg.startswith("-env:UserInstallation")
        )
        second_profile = next(
            arg
            for arg in mock_run.call_args_list[1].args[0]
            if arg.startswith("-env:UserInstallation")
        )
        assert first_profile != second_profile

    @patch("src.research_library.ingest.conversion_service.subprocess.run")
    def test_persistent_failure_raises_conversion_error(
        self, mock_run, tmp_path
    ):
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=77, cmd="soffice", stderr="boom"
        )

        with pytest.raises(ConversionError, match="77"):
            convert_to_pdf(str(tmp_path / "deck.docx"), str(tmp_path))
        assert mock_run.call_count == 2

    @patch("src.research_library.ingest.conversion_service.subprocess.run")
    def test_missing_binary_raises_clear_error(self, mock_run, tmp_path):
        mock_run.side_effect = FileNotFoundError("soffice")

        with pytest.raises(ConversionError, match="not installed"):
            convert_to_pdf(str(tmp_path / "deck.docx"), str(tmp_path))

    @patch("src.research_library.ingest.conversion_service.subprocess.run")
    def test_silent_no_output_is_a_failure(self, mock_run, tmp_path):
        mock_run.return_value = _completed()

        with pytest.raises(ConversionError, match="no output"):
            convert_to_pdf(str(tmp_path / "deck.docx"), str(tmp_path))
