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

"""Proof-of-concept: translate a .docx annual report with layout preserved.

Dry-run mode (default) uses the deterministic pseudo-translator — no API
calls, no credentials — and proves the parse -> reinject -> save pipeline
keeps the document intact. Live mode translates with Gemini on Vertex
(requires the app's Vertex env: VERTEX_PROJECT_ID / VERTEX_CREDENTIALS_FILE).

Usage:
    uv run python scripts/translate_docx_poc.py report.docx out.docx
    uv run python scripts/translate_docx_poc.py report.docx out.docx \
        --live --target "Dutch (Netherlands)" --section "Right-of-use" \
        --model gemini-2.5-pro
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.translations.documents import qa
from src.translations.documents.docx_engine import DocxTranslationEngine
from src.translations.documents.translator import (
    GeminiSegmentTranslator,
    GlossaryEntry,
    PseudoTranslator,
    translate_tree,
)

# Minimal seed for the PoC; the real run reads the financial glossary domain
# from the database.
POC_GLOSSARY = [
    GlossaryEntry(source="impairment", target="bijzondere waardevermindering"),
    GlossaryEntry(source="fair value", target="reële waarde"),
    GlossaryEntry(source="right-of-use asset", target="gebruiksrecht-actief"),
    GlossaryEntry(source="lease liabilities", target="leaseverplichtingen"),
    GlossaryEntry(source="deferred tax", target="latente belastingen"),
]
POC_DO_NOT_TRANSLATE = [
    "Hunkemöller",
    "Shero Holdco B.V.",
    "Together Tomorrow",
    "EBITDA",
    "IFRS",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument(
        "--live",
        action="store_true",
        help="use Gemini (default: offline pseudo-translation)",
    )
    parser.add_argument("--target", default="Dutch (Netherlands)")
    parser.add_argument(
        "--model", default=None, help="Gemini model id (default: app config)"
    )
    parser.add_argument(
        "--section",
        default=None,
        help="only translate sections whose path contains this substring",
    )
    args = parser.parse_args()

    started = time.time()
    engine = DocxTranslationEngine(args.input)
    print(f"Parsed in {time.time() - started:.1f}s — {engine.tree.stats()}")

    segments = engine.tree.translatable
    if args.section:
        needle = args.section.lower()
        segments = [
            s
            for s in segments
            if any(needle in part.lower() for part in s.section_path)
        ]
        print(f"Section filter: {len(segments)} segments selected")
    if not segments:
        print("Nothing to translate.")
        return 1

    if args.live:
        from src.config.config_service import config_service
        from src.multimodal.schema.gemini_model_setup import GeminiModelSetup

        translator = GeminiSegmentTranslator(
            client=GeminiModelSetup.get_client(),
            model_id=args.model or config_service.GEMINI_MODEL_ID,
            target_language=args.target,
            glossary=POC_GLOSSARY,
            do_not_translate=POC_DO_NOT_TRANSLATE,
        )
    else:
        translator = PseudoTranslator()

    failed = translate_tree(segments, translator)
    applied = engine.apply()
    engine.save(args.output)
    print(
        f"Translated {len(segments) - len(failed)}/{len(segments)} segments "
        f"({len(failed)} failed), applied {applied}, "
        f"total {time.time() - started:.1f}s"
    )

    findings = qa.run_all(
        segments,
        glossary=POC_GLOSSARY if args.live else None,
        do_not_translate=POC_DO_NOT_TRANSLATE if args.live else None,
    )
    errors = [f for f in findings if f.severity == qa.Severity.ERROR]
    warnings = [f for f in findings if f.severity == qa.Severity.WARNING]
    print(f"QA: {len(errors)} errors, {len(warnings)} warnings")
    for f in (errors + warnings)[:20]:
        print(f"  [{f.severity.value}] seg {f.segment_id} {f.check}: {f.detail}")
    return 0 if not errors and not failed else 2


if __name__ == "__main__":
    sys.exit(main())
