# Corpus Ingest Runbook — Research Library

Bulk-ingest of the 151-file trend-report corpus
("Sources 2 input Astrid - general trend reports") into the research
library, plus the golden-question evaluation that proves the origin doc's
success criteria.

## Prerequisites

- Backend running WITH LibreOffice in the image (the deployed Cloud Run
  container, or local Docker) — a bare macOS dev backend cannot convert the
  15 office files. PDFs/PNG work anywhere.
- The `research_library` migration applied (`vector` extension enabled —
  Cloud SQL instance runs Postgres 18, supported).
- Vertex access healthy: one manual upload through the UI should reach
  COMPLETED before firing 145 files. A 403 on `generateContent` means the
  client-project SA lost `roles/aiplatform.user` again (known regression).
- An identity token: log into the app, grab the `Authorization: Bearer`
  value from any API request in devtools.

## Expected corpus behavior

From the corpus inventory (`docs/brainstorms/2026-07-06-market-research-corpus-inventory.json`):

| Group | Count | Expectation |
|---|---|---|
| PDF | 127 | ingest (79 have no text layer — irrelevant, pages render as images) |
| DOCX/PPT/PPTX/ODP | 16 | LibreOffice-converted, then ingest |
| PNG | 1 | single-page document |
| XLSX | 1 | Ruigrok tabellenset → upload via data-query "Load sheet" instead |
| MSG | 6 | skipped by the script (visibly REJECTED if uploaded via UI) |
| Duplicates | 17 pairs | second upload of identical bytes → REJECTED "Duplicate of …" |
| 700-page Euromonitor Passport export | 1 | truncated at RL_MAX_PAGES=250 with a visible note |

~6,500 pages total → **estimated one-time extraction cost ≈ $55–85 (Pro) or
$13–20 (Flash)**, embeddings < $1. The model is `RL_EXTRACT_MODEL`
(default: app-wide `GEMINI_MODEL_ID`).

## Steps

```bash
cd backend

# 1. Estimate only (no spend):
uv run python scripts/bulk_ingest_research_library.py \
  --dir "/Users/niek/Downloads/Sources 2 input Astrid - general trend reports" \
  --base-url https://<backend-url> --token "<idtoken>" --dry-run

# 2. Full run (asks for confirmation before spending):
uv run python scripts/bulk_ingest_research_library.py \
  --dir "/Users/niek/Downloads/Sources 2 input Astrid - general trend reports" \
  --base-url https://<backend-url> --token "<idtoken>" --canonicalize

# 3. Upload the Ruigrok XLSX via the data-query "Load sheet" button.

# 4. Review the canonicalization summary in bulk_ingest_report.json:
#    read the cluster list (~5 min), fix any over/under-merge via
#    PATCH /api/research-library/tags {"raw": ..., "canonical": ...}.
```

## Golden-question evaluation

Score by hand in the data-query UI; a question passes when the answer is
factually right, cites the right document + page, and the slide viewer
shows a page that actually supports the claim. Target: **≥ 8/10**.

| # | Question (ask verbatim) | Expected |
|---|---|---|
| 1 | Hoeveel procent van de online aankopen wordt in 2030 naar verwachting via de smartphone gedaan? | 46%, forecast, Thuiswinkel Toekomst/Markt Monitor, cited with page |
| 2 | Wat was de totale online besteding in Nederland in Q1 2025 en hoeveel groei was dat? | €9,3 mld, +4% vs Q1 2024 (Thuiswinkel Markt Monitor Q1 2025) |
| 3 | Welk aandeel van de online bestedingen gaat naar buitenlandse websites, en welke landen zijn het grootst? | 13% cross-border; Duitsland en Frankrijk bovenaan |
| 4 | What are Euromonitor's top global consumer trends for 2026? | Trend list from the 2026 Euromonitor decks, cited per trend |
| 5 | Hoe ontwikkelde het iDEAL-aandeel in online betalingen zich? Noem de cijfers per periode en bron. | Multiple figures with periods named side by side (conflict handling) |
| 6 | Wat zegt de ARD/ZDF Medienstudie 2024 over mediagebruik in Duitsland? | Facts from the German deck answered in Dutch (cross-language) |
| 7 | What do the reports say about Gen Z shopping behavior? | Claims from ≥2 different publishers, each cited |
| 8 | (na XLSX-upload) Hoeveel rijen heeft elke tabel uit de Ruigrok-tabellenset? | Exact counts via run_sql — DuckDB path regression check |
| 9 | Combineer: wat zegt de Ruigrok-tabellenset over <kolom X> en wat zeggen de rapporten erover? | One answer using BOTH run_sql and search_claims |
| 10 | Wat zeggen de rapporten over de vismarkt in Japan? | Honest "geen data" from both sources — no invention |

Extra (tier check): set one Thuiswinkel monitor to `background`, re-ask #2,
confirm a different (primary) source now dominates; restore the tier.

## Results (fill in after the run)

- Date/operator:
- Final statuses:
- Total duration / wall-clock:
- Actual cost (Vertex billing delta):
- Golden-question score: /10
- Canonicalization: #clusters, corrections made:
- Follow-ups:
