# Ingestion Analysis: Astrid's Research File Dump into "Ask Your Data"

This analyzes whether Astrid (Hunkemöller's Market Research Manager) can indiscriminately drop her ~21 research files — brand trackers, concept tests, product tests, and raw survey exports spanning 2025-2026 — into the "Ask your data" system and have every one of them process and persist correctly. Each file was probed individually against the pipeline's actual size caps, timeouts, and parsing heuristics; this document turns those 21 probe findings plus 8 derived multi-hop questions into a single reference.

## How ingestion works

"Ask your data" has **two separate ingestion paths**, chosen entirely by which upload widget the user picks — there is no auto-routing between them:

- **(A) research-library** (documents): `.pdf`, `.docx`, `.ppt`, `.pptx`, `.odp`, `.png`, `.jpg`. Office formats are converted to PDF via LibreOffice under a **hard 120-second timeout** (1 retry), pages are rendered to images, and Gemini vision extracts atomic claims which are then embedded. Caps: **300 MiB** and **250 pages**. A document that yields 0 claims on some or all pages still silently ends "complete" — it just isn't searchable.
- **(B) data-query** (tables): `.xlsx`, `.xlsm`, `.xls`, `.csv`. Parsed via pandas/DuckDB. Cap: **hard 25 MB**. The header row is auto-detected (picks whichever of the first 8 rows has the most non-null cells) — this is fragile on multi-row banner/crosstab survey tables. `.xlsm` macros are never executed; only cached values are read. Uploading an unsupported type to this widget produces an ugly, unhandled 500.

Because routing is manual and the two widgets have completely different failure modes, picking the wrong widget for a given file is itself a risk, not just a file-property risk.

## Per-file verdicts

| File | Type | Size | Routes to | Process | Persist | Bottom line |
|---|---|---|---|---|---|---|
| 1. Presentation Customer Segments 2026.pptx | .pptx (65 slides, 80MB embedded video) | 136 MB | research_library | ⚠️ | ❌ | 80MB embedded video + large images/SVGs across 65 slides make it a strong candidate to blow the 120s LibreOffice conversion timeout and end permanently FAILED |
| 2. HKM_Brandbook.pdf | Native PDF (brand guidelines) | 148 MB | research_library | ✅ | ✅ | Native PDF skips conversion entirely; under both caps; slow but should ingest cleanly, with a few zero-claim divider pages |
| 3a. Results - Research Brand promise DE 8-8-2025.pptx | .pptx (34 slides, text-dense) | 4.9 MB | research_library | ✅ | ✅ | Small, light media, text-rich — should convert, render, and yield claims cleanly |
| 3b. Results - Research brand promise x HKM buyer 1-9-2025.xlsx | .xlsx (33-sheet crosstab) | 2.19 MB | data_query | ⚠️ | ⚠️ | Under size cap so it won't hard-fail, but ~2/3 of sheets are multi-row-header banner/crosstab tables the naive header-detector will mis-parse — silent per-sheet corruption |
| 4a. Conversation Studio - Survey Results - The Bra Shopping Experience 10-9-2025.pdf | Native PDF | 2.9 MB | research_library | ✅ | ✅ | Confirmed real text layer, well under caps — clean ingest |
| 4b. Conversation Studio - Results AI interviews - Deep Dive Bra Shopping 10-9-2025.pdf | Native PDF | 0.85 MB | research_library | ✅ | ✅ | Text-rich, trivial size — clean ingest |
| 4c. Conversation Studio - Raw Data HKM.xlsx | .xlsx (flat respondent table) | 0.95 MB | data_query | ✅ | ✅ | Single unambiguous header row (318 cols x 629 rows) — clean ingest, only cosmetic CRLF-in-header risk |
| 5a. Report - Brand & Campaign tracker - Spring Q1 2026.pptx | .pptx (83 slides) | 45.2 MB | research_library | ⚠️ | ⚠️ | Several multi-MB EMF chart exports are a known LibreOffice slow path — plausible (not certain) 120s timeout risk |
| 5b. Tabellen - Brand & Campaign tracker - Spring Q1 2026.xlsm | .xlsm (3-sheet crosstab, no real macros) | 0.63 MB | data_query | ⚠️ | ✅ | Uploads fine, but 2 of 3 sheets are stacked-banner tables; header-detector picks a totals/N-count row — silent semantic mis-parse, not a hard failure |
| 6a. Report - Brand & Campaign tracker - Holiday Q4 2025.pptx | .pptx (121 slides, 122 native charts) | 87 MB | research_library | ⚠️ | ⚠️ | 122 embedded charts + several 5-19MB images make this a strong candidate to exceed the 120s conversion timeout |
| 6b. Tabellen - Brand & Campaign tracker - Holiday Q4 2025.xlsm | .xlsm (10-sheet crosstab, no real macros) | 1.15 MB | data_query | ⚠️ | ⚠️ | Uploads fine, but essentially every sheet is a stacked-banner crosstab — workbook-wide mis-parse risk |
| 7a. Report - Brand & Campaign tracker - FEWIY+Cashmere Q3 2025.pptx | .pptx (118 slides) | 89.2 MB | research_library | ⚠️ | ⚠️ | ~85MB of embedded media (several 4-8.6MB images) — strong timeout candidate |
| 7b. Tabellen - Brand & Campaign tracker - FEWIY+Cashmere Q3 2025.xlsx | .xlsx (6-sheet SPSS banner export) | 1.2 MB | data_query | ⚠️ | ⚠️ | All 6 sheets are SPSS banner/crosstab exports with heavy merged cells — near-certain header mis-detection, ingests "successfully" into garbled columns |
| 8a. Report - Brand & Campaign tracker - SWIM Q2 2025.pptx | .pptx (90 slides) | 94 MB | research_library | ⚠️ | ⚠️ | 92.6MB media incl. several 8-22MB images across only 90 slides — strong timeout candidate |
| 8b. Tabellen - Brand & Campaign tracker - SWIM Q2 2025.xlsx | .xlsx (2-sheet Google Sheets crosstab) | 0.38 MB | data_query | ⚠️ | ✅ | Uploads fine; 7-row stacked header loses country/campaign context, and sheet2's stacked sub-tables beyond the first are only partially parsed |
| 1a. Results - Concept test - Loungewear innovations 19-2-2026.pptx | .pptx (31 slides, text-rich) | 6.05 MB | research_library | ✅ | ✅ | Well within all limits, text-dense — clean ingest |
| 1b. Tabellen - Concept test - Loungewear innovations 19-2-2026.xlsx | .xlsx (31-sheet multi-block crosstab) | 0.24 MB | data_query | ⚠️ | ✅ | Uploads fine; sheet1 stacks dozens of question blocks below row 8 — header-detector only ever catches the first block, rest reads as garbage |
| 2a. Results - Product test - Super Comfort bra 15-5-2026.pptx | .pptx (19 slides, product photos + charts) | 12.6 MB | research_library | ✅ | ✅ | Moderate complexity but well outside the timeout danger zone — should ingest cleanly |
| 2b. Data - Product test Super Comfort Bra.xlsx | .xlsx (2-row stacked header) | 0.084 MB | data_query | ⚠️ | ⚠️ | Header-detector picks the sub-label row over the question-text row; 4+ columns collapse into duplicate "Response" names |
| 3a. Results - Pre-test TVC - Super Soft World 7-4-2026.pptx | .pptx (18 slides) | 5.0 MB | research_library | ✅ | ✅ | Small, text-rich, far from timeout risk — clean ingest |
| 3b. Data - Pre-test TVC - Super Soft World 7-4-2026.xlsx | .xlsx (flat respondent table) | 0.06 MB | data_query | ✅ | ✅ | Single clean header row, no banner structure — clean ingest |

## Systemic risks

### 1. Large decks vs. the 120-second LibreOffice conversion timeout
The single biggest failure mode across the dump. Every `.pptx` over roughly 45MB with heavy embedded media is flagged as risky-to-certain for hitting the hard 120s/1-retry conversion budget and ending permanently FAILED with zero claims extracted:
- **1. Presentation Customer Segments 2026.pptx** (136MB, 80MB embedded MP4 video) — the single worst offender; only file marked outright ❌ on persistence.
- **5a. Brand & Campaign tracker - Spring Q1 2026.pptx** (45.2MB, multiple 5-6.5MB EMF chart exports)
- **6a. Brand & Campaign tracker - Holiday Q4 2025.pptx** (87MB, 122 native embedded charts, images up to 19MB)
- **7a. Brand & Campaign tracker - FEWIY+Cashmere Q3 2025.pptx** (89.2MB, images up to 8.6MB)
- **8a. Brand & Campaign tracker - SWIM Q2 2025.pptx** (94MB, images up to 21.9MB)

All five are the large quarterly tracker decks plus the one Customer Segments deck — every deck over ~45MB in the dump is affected, none of the sub-15MB decks are.

### 2. The 25 MB hard cap on the data-query path
No file in this dump actually exceeds 25MB (largest sheet file is 2.19MB), so this cap is not currently triggered by anything Astrid has — but it remains a latent risk for any future larger export (e.g. a full raw respondent-level dump with hundreds of variables).

### 3. Banner/crosstab table mis-parsing (multi-row survey headers)
The second-biggest failure mode, and the most pervasive: the header-auto-detect heuristic (pick whichever of the first 8 rows has the most non-null cells) systematically breaks on stacked/banner-style survey exports, producing tables that ingest without error but are semantically wrong or unusable for querying:
- **3b. Research brand promise x HKM buyer 1-9-2025.xlsx** — 3-row stacked crosstab header
- **5b. Tabellen - Spring Q1 2026.xlsm** — header-detector picks a totals/N-count row
- **6b. Tabellen - Holiday Q4 2025.xlsm** — workbook-wide, essentially every sheet affected
- **7b. Tabellen - FEWIY+Cashmere Q3 2025.xlsx** — SPSS banner exports with heavy merged cells, all 6 sheets
- **8b. Tabellen - SWIM Q2 2025.xlsx** — 7-row stacked header loses country/segment context; second sheet has multiple stacked sub-tables only the first of which is parsed
- **1b. Tabellen - Loungewear innovations.xlsx** — dozens of stacked question blocks on one sheet, only the first is captured
- **2b. Data - Super Comfort Bra.xlsx** — 2-row header (question text vs. scale anchors); detector picks the wrong row, collapsing multiple columns into duplicate names

Seven of the eight spreadsheet files that route to data-query exhibit this failure mode in some form; only **4c. Raw Data HKM.xlsx** and **3b. Data - Pre-test TVC Super Soft World.xlsx** have single, unambiguous header rows.

### 4. `.xlsm` macros / cached-values-only
Two files carry the `.xlsm` extension (5b, 6b), but in both cases the underlying archive contains no `vbaProject.bin` — they're Google Sheets exports re-saved as `.xlsm`, not real macro workbooks. So the "macro-computed values may come back blank" risk from the pipeline facts is **flagged but does not actually materialize** for either file in this dump; their real problem is the banner-table header issue above, not macros.

### 5. Zero-claim, silently-useless documents
Several otherwise-clean PDFs/decks have individual pages/slides that will legitimately yield 0 claims (section dividers, cover slides, pure-photo pages) while the document as a whole still ends "COMPLETED." This is a minor, page-level effect on most files (e.g. **2. HKM_Brandbook.pdf** divider pages, cover slides on **1a**, **2a**, **8a**) rather than a whole-document failure — but it is silent and would not be visible to Astrid without manually checking claim counts per page.

### 6. The two-widget wrong-routing UX trap
Because routing is manual and by extension only, a researcher who doesn't know the rules could easily send a `.xlsx`/`.xlsm` file to the document widget (instant 400, extension not allowlisted) or a `.pptx`/`.pdf` to the sheet widget (ugly 500, unsupported type). None of the 21 files in this dump were actually mis-routed by Astrid — each finding confirms the "correct" widget for its extension — but the analysis repeatedly notes this as a standing trap for any researcher who doesn't already know which widget matches which extension family (e.g. finding for **3b. Data - Pre-test TVC Super Soft World 7-4-2026.xlsx** explicitly flags that sending it to the document widget "would get an instant 400 rejection").

## Recommendation

**Ingest cleanly as-is (9 of 21 files):** 2. HKM_Brandbook.pdf, 3a. Research Brand promise DE, 4a. Bra Shopping Experience, 4b. Deep Dive Bra Shopping, 4c. Raw Data HKM.xlsx, 1a. Loungewear innovations (deck), 2a. Super Comfort bra (deck), 3a. Pre-test TVC Super Soft World (deck), 3b. Data - Pre-test TVC Super Soft World.xlsx. These can be dumped indiscriminately today with no special handling.

**Need pre-processing before upload (12 of 21 files):**
- The five large tracker/segments decks (1, 5a, 6a, 7a, 8a) should have embedded video stripped and/or be pre-converted to PDF locally (e.g. via a local LibreOffice/PowerPoint export) before upload, bypassing the pipeline's own 120s conversion step entirely.
- The seven banner/crosstab spreadsheets (3b, 5b, 6b, 7b, 8b, 1b, 2b) need their multi-row headers flattened to a single header row (or split into one sheet per logical table) before upload if the researcher wants trustworthy query results; as-is they will "persist" but silently mislead.

**Pipeline changes that would make indiscriminate dumping actually safe:**
1. **A single auto-routing dropzone** that inspects the file extension and sends it to the correct widget itself, removing the two-widget manual-choice trap entirely.
2. **A pre-upload size/complexity guard with a clear error**, e.g. estimate conversion cost from embedded-media size/count before attempting LibreOffice conversion, and reject upfront with an actionable message ("this file is likely to exceed the 120s conversion timeout — strip large video/images or pre-convert to PDF") rather than silently failing after the fact.
3. **A visible 0-claims warning** surfaced per-document (or per-page) after ingestion completes, so a document that "completed" but extracted nothing is flagged rather than silently indistinguishable from a fully successful ingest.
4. **A banner-table detector** for the data-query path — even a simple heuristic that flags sheets with merged cells or multiple non-null "header-candidate" rows in the first 8 rows as "needs manual header review" would surface most of the crosstab mis-parses in this dump before they silently corrupt query results.
