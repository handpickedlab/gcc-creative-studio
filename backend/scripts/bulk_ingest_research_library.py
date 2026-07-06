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

"""Bulk-ingest a folder of research documents through the public API.

Drives the same endpoints the frontend uses (signed-URL upload -> finalize ->
poll), so everything the pipeline enforces (dedupe, format rejection, page
caps) applies. Prints a page/cost estimate and asks for confirmation BEFORE
spending money on extraction.

Usage:
    uv run python scripts/bulk_ingest_research_library.py \
        --dir "/path/to/corpus" \
        --base-url http://localhost:8080 \
        --token "$(cat /tmp/id_token)"        # browser: authService token

    Add --yes to skip the confirmation, --dry-run for the estimate only.

Notes:
- .msg files are skipped locally (the API would reject them anyway; skipping
  keeps the report clean). .csv/.xlsx belong to the sheet warehouse — upload
  those via the data-query "Load sheet" button instead.
- Office formats (docx/ppt/pptx/odp) need LibreOffice on the BACKEND —
  ingest them against the deployed container, not a bare macOS dev backend.
"""

import argparse
import json
import mimetypes
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

SKIP_EXTENSIONS = {".msg"}
SHEET_EXTENSIONS = {".csv", ".xlsx", ".xlsm", ".xls"}
OFFICE_EXTENSIONS = {".docx", ".ppt", ".pptx", ".odp"}
ACCEPTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"} | OFFICE_EXTENSIONS

MAX_PAGES_CAP = 250  # keep in sync with RL_MAX_PAGES
DEFAULT_OFFICE_PAGE_ESTIMATE = 35

# tokens/page ~ 6 image tiles (258 each) + ~300 prompt/schema; ~600 output.
INPUT_TOKENS_PER_PAGE = 1850
OUTPUT_TOKENS_PER_PAGE = 600
PRICES_PER_M = {  # (input, output) USD per 1M tokens, standard online tier
    "pro": (1.25, 10.0),
    "flash": (0.30, 2.50),
}

TERMINAL = {"completed", "completed_with_errors", "failed", "rejected"}


def count_pdf_pages(path: Path) -> int | None:
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(path))
        try:
            return len(pdf)
        finally:
            pdf.close()
    except Exception:
        return None


def classify(files: list[Path]) -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = {
        "ingest": [], "sheets": [], "skipped": [], "unsupported": [],
    }
    for path in sorted(files):
        ext = path.suffix.lower()
        if ext in SKIP_EXTENSIONS:
            groups["skipped"].append(path)
        elif ext in SHEET_EXTENSIONS:
            groups["sheets"].append(path)
        elif ext in ACCEPTED_EXTENSIONS:
            groups["ingest"].append(path)
        else:
            groups["unsupported"].append(path)
    return groups


def estimate(files: list[Path]) -> tuple[int, dict[str, float]]:
    total_pages = 0
    for path in files:
        if path.suffix.lower() == ".pdf":
            pages = count_pdf_pages(path) or DEFAULT_OFFICE_PAGE_ESTIMATE
        elif path.suffix.lower() in OFFICE_EXTENSIONS:
            pages = DEFAULT_OFFICE_PAGE_ESTIMATE
        else:
            pages = 1
        total_pages += min(pages, MAX_PAGES_CAP)

    costs = {}
    for tier, (input_price, output_price) in PRICES_PER_M.items():
        costs[tier] = total_pages * (
            INPUT_TOKENS_PER_PAGE * input_price
            + OUTPUT_TOKENS_PER_PAGE * output_price
        ) / 1_000_000
    return total_pages, costs


class Client:
    def __init__(self, base_url: str, token: str):
        self.api = httpx.Client(
            base_url=f"{base_url.rstrip('/')}/api/research-library",
            headers={"Authorization": f"Bearer {token}"},
            timeout=120,
        )
        self.raw = httpx.Client(timeout=600)

    def upload(self, path: Path) -> dict:
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        handshake = self.api.post(
            "/generate-upload-url",
            json={
                "filename": path.name,
                "mimeType": mime,
                "sizeBytes": path.stat().st_size,
            },
        )
        handshake.raise_for_status()
        upload_url = handshake.json()["uploadUrl"]
        gcs_uri = handshake.json()["gcsUri"]

        with path.open("rb") as fh:
            put = self.raw.put(
                upload_url, content=fh.read(), headers={"Content-Type": mime}
            )
        put.raise_for_status()

        finalize = self.api.post(
            "/finalize-upload",
            json={"gcsUri": gcs_uri, "filename": path.name, "mimeType": mime},
        )
        finalize.raise_for_status()
        return finalize.json()

    def documents(self) -> list[dict]:
        response = self.api.get("/documents", params={"limit": 500})
        response.raise_for_status()
        return response.json().get("data") or []

    def reprocess(self, document_id: int) -> None:
        self.api.post(f"/documents/{document_id}/reprocess").raise_for_status()

    def bootstrap_canonicalization(self) -> dict:
        response = self.api.post(
            "/canonicalize/bootstrap", json={}, timeout=1800
        )
        response.raise_for_status()
        return response.json()


def wait_until_settled(client: Client, poll_seconds: int = 15) -> list[dict]:
    while True:
        docs = client.documents()
        processing = [d for d in docs if d["status"] not in TERMINAL]
        done = len(docs) - len(processing)
        print(f"  {done}/{len(docs)} settled, {len(processing)} processing…")
        if not processing:
            return docs
        time.sleep(poll_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", required=True, type=Path)
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--token", required=True)
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--retry-failed", action="store_true", default=True)
    parser.add_argument("--canonicalize", action="store_true",
                        help="run the tag bootstrap after ingest settles")
    parser.add_argument("--report", type=Path,
                        default=Path("bulk_ingest_report.json"))
    args = parser.parse_args()

    files = [p for p in args.dir.iterdir() if p.is_file()]
    groups = classify(files)
    pages, costs = estimate(groups["ingest"])

    print(f"Corpus: {len(files)} files in {args.dir}")
    print(f"  to ingest    : {len(groups['ingest'])}")
    print(f"  sheet files  : {len(groups['sheets'])} (upload via data-query)")
    print(f"  skipped (msg): {len(groups['skipped'])}")
    print(f"  unsupported  : {len(groups['unsupported'])}")
    print(f"Estimated pages: ~{pages}")
    print("Estimated extraction cost (online tier): "
          f"pro ≈ ${costs['pro']:.0f} · flash ≈ ${costs['flash']:.0f}")
    print("(embeddings add < $1; duplicates the backend rejects cost nothing)")

    if args.dry_run:
        return 0
    if not args.yes:
        answer = input("Proceed with upload + extraction? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            print("Aborted.")
            return 1

    client = Client(args.base_url, args.token)
    results = []
    for i, path in enumerate(groups["ingest"], 1):
        print(f"[{i}/{len(groups['ingest'])}] {path.name}")
        try:
            doc = client.upload(path)
            results.append({"file": path.name, "id": doc.get("id"),
                            "status": doc.get("status"),
                            "note": doc.get("errorMessage")})
            if doc.get("status") == "rejected":
                print(f"    rejected: {doc.get('errorMessage')}")
        except Exception as e:
            results.append({"file": path.name, "id": None,
                            "status": "upload_failed", "note": str(e)})
            print(f"    UPLOAD FAILED: {e}")

    print("Waiting for ingest to settle…")
    docs = wait_until_settled(client)

    failed = [d for d in docs if d["status"] == "failed"]
    if failed and args.retry_failed:
        print(f"Retrying {len(failed)} failed document(s) once…")
        for doc in failed:
            try:
                client.reprocess(doc["id"])
            except Exception as e:
                print(f"    reprocess {doc['id']} failed: {e}")
        docs = wait_until_settled(client)

    summary: dict[str, int] = {}
    for doc in docs:
        summary[doc["status"]] = summary.get(doc["status"], 0) + 1
    print("Final statuses:", json.dumps(summary, indent=2))

    canonicalization = None
    if args.canonicalize:
        print("Running tag canonicalization bootstrap…")
        canonicalization = client.bootstrap_canonicalization()
        print(f"  {len(canonicalization.get('clusters', []))} clusters, "
              f"{canonicalization.get('updatedClaims')} claims re-resolved")

    args.report.write_text(json.dumps({
        "run_at": datetime.now(timezone.utc).isoformat(),
        "uploads": results,
        "final_documents": docs,
        "summary": summary,
        "skipped_msg": [p.name for p in groups["skipped"]],
        "sheet_files": [p.name for p in groups["sheets"]],
        "canonicalization": canonicalization,
    }, indent=2))
    print(f"Report written to {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
