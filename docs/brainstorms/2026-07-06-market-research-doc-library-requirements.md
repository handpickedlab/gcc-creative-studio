---
date: 2026-07-06
topic: market-research-doc-library
---

# Market Research Document Library (slide decks + sheets)

## Problem Frame
The market research feature (`data_query`) today only accepts CSV/XLSX, loaded
into DuckDB and queried with exact SQL by a Gemini agent. The client now wants
to feed it **50+ slide decks (PDF, some DOCX)** — chart-heavy research decks
(e.g. Thuiswinkel Markt Monitor / NIQ) with lots of statistics and very little
plain text. Text-layer extraction is useless on these; naive chunk-RAG would
retrieve meaningless fragments. The insights are **hard facts** (percentages,
market shares, forecasts) that users need to find, combine and trust across
documents — together with the spreadsheet data that is already there, and with
slide decks taking (adjustable) priority over other sources.

This is a **PoC**: one global library, optimized for proving the extraction +
hybrid-answer loop, not for multi-tenant management.

## Requirements

### Ingest
- R1. Users can upload **PDF, DOCX, PPT/PPTX/ODP and standalone image files
  (PNG/JPEG)** into a **global document library**, alongside the existing
  CSV/XLSX upload (XLSX/CSV keep routing to the existing sheet warehouse).
  Office formats are converted to PDF before processing. Unsupported formats
  (e.g. Outlook MSG) are **rejected with a visible reason**, never silently
  skipped. Batch upload (many files at once) with per-document async
  processing status (processing / completed / completed-with-errors / failed).
- R9. **Exact duplicates are detected at upload** (content hash) and not
  re-ingested; near-duplicate editions (e.g. "v2", translated copies) are
  flagged in the library view but allowed.
- R2. Every deck page is rendered as an **image** and processed by a
  multimodal model into **atomic insight claims**: a self-contained statement
  plus structured fields (metric, value, segment, period, geography, source
  citation incl. sample size, theme/entity tags), each linked to its
  document + slide number + stored slide image.
- R3. Claims are **semantically searchable** across the whole library
  (embedding similarity + tag/metadata filters such as theme, year, category,
  source), so cross-document questions work over 50+ decks.

### Answering
- R4. The existing `ask` chat becomes a **hybrid agent** with two retrieval
  tools: claim search (facts from decks/documents) and DuckDB SQL (exact
  numbers from sheets). One question can combine both in a single answer.
- R5. Every fact in an answer cites **document + slide number**, and the user
  can open the **original slide image** as evidence next to the answer.
- R6. When claims conflict across documents (e.g. 2024 vs 2025 edition of the
  same monitor), the agent prefers the most recent but **names the conflict**
  explicitly (both values + years) instead of silently picking one.

### Source priority
- R7. Every document has a **priority tier** (e.g. primary / supporting /
  background) with defaults per file type (slide decks → primary). The tier is
  adjustable per document and weighs into retrieval ranking and the agent's
  answer instructions.

### Library management
- R8. A library view lists all documents with type, processing status and
  priority tier; documents can be deleted and re-processed.

## Success Criteria
- A question like "hoe ontwikkelt het online aandeel in Health & Beauty zich
  richting 2030?" returns the correct figures from the right slide, with a
  clickable slide image as evidence.
- A cross-document question pulls claims from multiple decks and cites each.
- A question needing computation over uploaded sheets still produces exact
  DuckDB-computed numbers (no regression on the current `data_query` behavior).
- Changing a document's priority tier visibly changes which sources dominate
  an answer.
- All 50+ documents process without manual intervention at acceptable time and
  cost per deck.

## Scope Boundaries
- **Global library only** — no workspace scoping or permissions (PoC).
- **No knowledge-graph database** — graph-style navigation comes from shared
  entity/theme tags and metadata filters, not explicit edges.
- **No standalone browsable insight-library UI** — the slide viewer exists as
  citation evidence in chat; browsing/filtering insights directly is a later
  iteration.
- **No deep-research integration yet** — the retrieval layer can later serve
  the deep-research pipeline as an internal source, but v1 lands in chat only.
- **No document versioning or auto-refresh** — re-upload replaces.
- **Outlook MSG files are out of scope for v1** — the corpus contains 6 FYI
  e-mail forwards; the underlying reports are mostly present as standalone
  files. Rejected visibly at upload.

## Key Decisions
- **Page-as-image multimodal extraction**, not PDF text-layer parsing: the
  decks are infographics; the slide title usually *is* the takeaway and the
  source footnote (incl. n=) is on-slide. Mirrors the existing brand-guidelines
  PDF pattern (pages → Gemini with `response_schema`).
- **Atomic claim records + entity tags + embeddings ("GraphRAG-lite")** instead
  of chunk-RAG (fragments of slides are meaningless) or a full knowledge graph
  (heavy carrying cost; tags + filters give the same cross-deck navigation at
  PoC scale of ~5–10k claims).
- **Hybrid agent, two tools**: claims for deck facts, DuckDB SQL for exact
  table math — preserves the "exact numbers" property of the current feature.
- **Priority = per-document tier with type-based defaults**, not a hardcoded
  rule or per-query UI.
- **Chat/Q&A is the v1 surface**, extending the existing `data_query` ask flow.
- **Tags/metrics: decouple extraction from canonicalization.** Claims keep the
  model's free-form raw tags permanently; the canonical taxonomy is a separate
  raw→canonical mapping table that can be rebuilt cheaply without re-extracting.
  Bootstrap the taxonomy *from* the 50-deck corpus (free extraction → embed +
  cluster distinct tags → LLM names each cluster → one human review pass of the
  ~50–100 resulting tags). Later ingests receive the canonical vocabulary in
  the extraction prompt ("prefer these; propose new only if nothing fits");
  proposed-new tags are embedding-matched against existing ones (close match →
  auto-alias, else added). No taxonomy-management UI for the PoC.
- **Dimensions never live in metric names**: metric = "online share of
  spending"; segment/period/geography are separate claim fields — enforced via
  the extraction schema. This is what makes cross-year/cross-deck comparison a
  filter instead of string matching.

## Dependencies / Assumptions
- Builds on the `data_query` module in the working fork
  (`gcc-creative-studio-handpickedlab`), not the upstream clone.
- Vertex AI Gemini (existing setup) is capable enough for chart/infographic
  extraction when given page images; brand-guidelines pipeline proves the
  plumbing.
- The real corpus was surveyed on 2026-07-06 (see
  `2026-07-06-market-research-corpus-inventory.json`): **151 files,
  ~6,500 pages** — 127 PDF (79 with NO text layer), 8 DOCX, 7 PPT/PPTX,
  1 ODP, 6 MSG, 1 XLSX, 1 PNG; 92 slide decks vs 44 prose reports;
  languages EN (105) / NL (35) / DE (4); 17 duplicate pairs. Estimated
  ~20–40k claims; retrieval does not need heavy vector infrastructure.

## Outstanding Questions

### Resolve Before Planning
- (none)

### Deferred to Planning
- [Affects R3][Technical] Where claims + embeddings live: pgvector on the
  existing Postgres, or something simpler at this scale (even brute-force
  similarity or DuckDB) — pick the cheapest thing that works for a PoC.
- [Affects R2][Technical] DOCX handling: convert to PDF → page images (same
  pipeline) vs. a separate path.
- [Affects R3][Technical] Tag canonicalization mechanics: clustering threshold
  for the bootstrap consolidation, embedding-match threshold for auto-aliasing
  new tags, and where the mapping table lives (approach itself is decided —
  see Key Decisions).
- [Affects R2][Needs research] Extraction cost/latency per deck and the right
  model tier (Flash vs Pro) for slide extraction.
- [Affects R5][Technical] Slide image storage + serving (GCS signed URLs,
  thumbnail sizes).
- [Affects R4][Technical] Whether the hybrid agent reuses the existing
  streaming `ask` agent loop or adopts the ADK pattern from deep-research.

## Next Steps
→ `/ce:plan` for structured implementation planning
