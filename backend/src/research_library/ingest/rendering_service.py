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

"""PDF/image -> page-image rendering for the research library.

Pages render via pypdfium2 (PDFium, permissively licensed) to PNG at a
target long-edge pixel size rather than a fixed DPI: the corpus mixes A4
prose reports and 16:9 slide decks whose physical page sizes differ, and a
long-edge target gives both a comparable, chart-legible resolution.

Rendering is a generator that yields one page at a time so the caller can
encode -> upload -> discard without ever accumulating bitmaps for a
100+ page document in memory. ``pypdfium2`` is imported lazily inside the
functions (like ``duckdb`` in ``data_query.duckdb_store``) so the app still
imports before dependencies are synced.
"""

import io
import logging
from dataclasses import dataclass
from typing import Iterator

from PIL import Image

logger = logging.getLogger(__name__)

# Upscaling guard: a tiny physical page (e.g. a cropped export) should not
# explode into a giant bitmap chasing the long-edge target.
_MAX_RENDER_SCALE = 10.0


class RenderingError(Exception):
    """Raised when a document's pages could not be rendered."""


@dataclass
class RenderedPage:
    """One rendered page: full-size PNG bytes plus a thumbnail."""

    page_no: int  # 1-based
    image_bytes: bytes
    thumb_bytes: bytes
    width: int
    height: int


def pdf_page_count(pdf_path: str) -> int:
    """Returns the number of pages without rendering anything."""
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(pdf_path)
    except Exception as e:
        raise RenderingError(f"could not open PDF: {e}") from e
    try:
        return len(pdf)
    finally:
        pdf.close()


def render_pdf_pages(
    pdf_path: str,
    long_edge: int,
    thumb_long_edge: int,
    max_pages: int,
) -> Iterator[RenderedPage]:
    """Yields rendered pages of a PDF, one at a time, up to ``max_pages``.

    Opens the document by path so PDFium can lazily materialize pages
    instead of holding the whole (potentially 185MB) file in memory.
    """
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(pdf_path)
    except Exception as e:
        raise RenderingError(f"could not open PDF: {e}") from e

    try:
        total = len(pdf)
        for index in range(min(total, max_pages)):
            page = pdf[index]
            try:
                width_pt, height_pt = page.get_size()
                scale = min(
                    long_edge / max(width_pt, height_pt),
                    _MAX_RENDER_SCALE,
                )
                bitmap = page.render(scale=scale)
                try:
                    image = bitmap.to_pil()
                finally:
                    bitmap.close()
            except Exception as e:
                raise RenderingError(
                    f"could not render page {index + 1}: {e}"
                ) from e
            finally:
                page.close()

            yield _to_rendered_page(image, index + 1, thumb_long_edge)
    finally:
        pdf.close()


def render_image_file(
    image_path: str,
    long_edge: int,
    thumb_long_edge: int,
) -> RenderedPage:
    """Treats a standalone PNG/JPEG upload as a single-page document.

    Downscales to the long-edge target when the source is larger (never
    upscales a small image) and produces the same thumbnail as PDF pages.
    """
    try:
        with Image.open(image_path) as source:
            image = source.convert("RGB")
    except Exception as e:
        raise RenderingError(f"could not open image: {e}") from e

    if max(image.size) > long_edge:
        image.thumbnail((long_edge, long_edge), Image.LANCZOS)
    return _to_rendered_page(image, 1, thumb_long_edge)


def _to_rendered_page(
    image: Image.Image,
    page_no: int,
    thumb_long_edge: int,
) -> RenderedPage:
    """Encodes a PIL image into full-size + thumbnail PNG bytes."""
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")

    full_buffer = io.BytesIO()
    image.save(full_buffer, format="PNG")

    thumbnail = image.copy()
    thumbnail.thumbnail((thumb_long_edge, thumb_long_edge), Image.LANCZOS)
    thumb_buffer = io.BytesIO()
    thumbnail.save(thumb_buffer, format="PNG")

    return RenderedPage(
        page_no=page_no,
        image_bytes=full_buffer.getvalue(),
        thumb_bytes=thumb_buffer.getvalue(),
        width=image.width,
        height=image.height,
    )
