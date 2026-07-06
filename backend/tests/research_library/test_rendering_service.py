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

"""Tests for research_library.ingest.rendering_service."""

import io

import pytest
from PIL import Image

from src.research_library.ingest.rendering_service import (
    RenderingError,
    pdf_page_count,
    render_image_file,
    render_pdf_pages,
)


def _make_pdf(path, page_sizes):
    """Writes an image-based PDF with one page per (width, height) tuple."""
    pages = [
        Image.new("RGB", size, color=(200, 30 * i % 255, 90))
        for i, size in enumerate(page_sizes)
    ]
    pages[0].save(path, save_all=True, append_images=pages[1:])


def _png_size(png_bytes):
    with Image.open(io.BytesIO(png_bytes)) as img:
        return img.size


class TestRenderPdfPages:
    def test_portrait_and_landscape_pages_hit_long_edge_target(self, tmp_path):
        pdf_path = str(tmp_path / "mixed.pdf")
        _make_pdf(pdf_path, [(1000, 1400), (1600, 900)])

        pages = list(
            render_pdf_pages(
                pdf_path, long_edge=700, thumb_long_edge=100, max_pages=10
            )
        )

        assert [p.page_no for p in pages] == [1, 2]
        for page in pages:
            width, height = _png_size(page.image_bytes)
            assert max(width, height) == pytest.approx(700, abs=2)
            thumb_w, thumb_h = _png_size(page.thumb_bytes)
            assert max(thumb_w, thumb_h) == pytest.approx(100, abs=2)

    def test_respects_max_pages_cap(self, tmp_path):
        pdf_path = str(tmp_path / "capped.pdf")
        _make_pdf(pdf_path, [(400, 400)] * 5)

        pages = list(
            render_pdf_pages(
                pdf_path, long_edge=200, thumb_long_edge=50, max_pages=3
            )
        )

        assert len(pages) == 3
        assert pdf_page_count(pdf_path) == 5

    def test_corrupt_pdf_raises_rendering_error(self, tmp_path):
        pdf_path = tmp_path / "broken.pdf"
        pdf_path.write_bytes(b"this is not a pdf at all")

        with pytest.raises(RenderingError):
            list(
                render_pdf_pages(
                    str(pdf_path),
                    long_edge=200,
                    thumb_long_edge=50,
                    max_pages=3,
                )
            )


class TestRenderImageFile:
    def test_single_page_downscaled_to_long_edge(self, tmp_path):
        image_path = str(tmp_path / "infographic.png")
        Image.new("RGB", (2400, 1200), color=(10, 120, 200)).save(image_path)

        page = render_image_file(
            image_path, long_edge=600, thumb_long_edge=100
        )

        assert page.page_no == 1
        width, height = _png_size(page.image_bytes)
        assert max(width, height) == 600

    def test_small_image_is_not_upscaled(self, tmp_path):
        image_path = str(tmp_path / "small.png")
        Image.new("RGB", (300, 200), color=(10, 120, 200)).save(image_path)

        page = render_image_file(
            image_path, long_edge=1800, thumb_long_edge=100
        )

        assert _png_size(page.image_bytes) == (300, 200)

    def test_unreadable_image_raises_rendering_error(self, tmp_path):
        image_path = tmp_path / "not-an-image.png"
        image_path.write_bytes(b"nope")

        with pytest.raises(RenderingError):
            render_image_file(
                str(image_path), long_edge=600, thumb_long_edge=100
            )
