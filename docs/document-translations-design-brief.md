# Design Brief — Document Translations (Annual Reports)

> For the design agent. Goal: design a polished, production-quality experience
> for translating **long-form documents** (annual reports, ~100 pages) inside
> GCC Creative Studio's Translations area. This brief is self-contained — you
> don't need the codebase. It is a sibling of
> `translations-design-brief.md` (campaign briefings); reuse its design
> language, don't duplicate its scope.

---

## 1. Product context

GCC Creative Studio is an internal tool for a lingerie/fashion retailer. Its
**Translations** feature currently translates short campaign briefings (email
copy) into 15 markets. We are extending it with a second, structurally
different capability: translating **entire annual reports**.

What an annual report is, concretely:

- A **.docx of ~100–110 pages**, ~22–24k words, **60–80 financial tables**,
  produced yearly by finance. English source.
- Three content layers: a prose **Management Board Report** (brand story, CEO
  statement, ESG), the **consolidated financial statements** (dense numeric
  tables), and ~35 **notes** (mixed prose + tables, heavy IFRS/legal jargon).
- The output must be a **.docx with identical layout** — the pipeline
  translates text nodes inside the file and never touches styling, tables, or
  images. **The user never edits layout in our UI.** This is a text-review
  product, not a document editor.

The engine works on a **document tree**: document → sections/notes →
segments (a paragraph, heading, or table-label cell). Every segment has a
status and provenance. Numbers are never sent through AI — numeric cells are
locked and verified by deterministic checks.

Two engine features shape the UX:

- **Translation memory (TM):** annual reports repeat heavily year-over-year.
  Segments identical to a previously *approved* translation are pre-filled and
  pre-approved. Expect the majority of a follow-up year to arrive "already
  done" — the UI must make review-by-exception the default posture.
- **QA checks:** after translation the system verifies numbers match the
  source exactly, glossary terms were applied consistently, and
  do-not-translate names survived. Findings are attached to segments.

---

## 2. Users & jobs-to-be-done

- **Finance / comms operator** (primary): "I have this year's annual report in
  Word; I need a Dutch (or German/French) version with the exact same layout,
  and I need to trust that no number changed." Non-technical, deadline-driven
  (filing dates), works in Word today or pays an agency.
- **Reviewer** (finance lead / native speaker): "Show me only what needs my
  judgement — new or risky segments — not 3,000 rows. Let me fix a term once
  and see it corrected everywhere."
- **Admin**: maintains the **financial glossary** (IFRS terminology,
  EN → target term pairs) — a separate domain from the marketing dictionary.

Core flow: upload `.docx` → preflight (outline + counts detected) → configure
target language(s) + options → translate (long-running, minutes) → review per
section → resolve QA findings → approve → export translated `.docx`.

---

## 3. Design system to respect (this is inside an existing app)

Same shell and system as the briefings page — match it, don't invent:

- **Theme:** dark. App background ~`#2E3031`; cards `#282838`; glassmorphism
  surfaces (`rgba(40,40,56,0.55)`, `backdrop-blur`, 1px subtle light border,
  ~20px radius, soft shadow).
- **Text:** near-white `#E8E8ED`; muted `rgba(232,232,237,0.6)`.
- **Accent gradient** (primary buttons, highlights):
  `linear-gradient(to right, #3b82f6, #8b5cf6, #f87171)`.
- **Typography:** Google Sans (fallback Helvetica/Arial).
- **Navigation:** floating circular icon menu fixed left — keep left margin.
- **Components:** Angular Material (dark theme) + Tailwind; pill buttons;
  gradient = primary, outlined ghost = secondary.
- **Tone of UI copy:** concise, confident, English.

---

## 4. Information architecture

Documents live alongside briefings in the Translations area. Propose the IA —
e.g. a "Briefings | Documents" switch at the top of Translations, or a shared
library with a type column. Required content:

1. **Documents library** — uploaded reports with status, progress, target
   languages, last activity.
2. **Intake / preflight** — upload; parsed outline with counts; target
   language + options; start.
3. **Translation progress** — live, per-section, for a job that takes minutes.
4. **Review workspace** (the heart of the product) — tree navigation +
   segment review + QA findings.
5. **Glossary manager** — the existing dictionary manager gains a **domain**
   dimension (Marketing / Financial); financial terms are what this feature
   uses.
6. **Export** — download translated `.docx`, with a QA summary.

---

## 5. Feature requirements (must cover all of these)

### A. Intake & preflight
- Upload `.docx` (drag & drop). PDF is explicitly not accepted — show a
  helpful rejection ("upload the Word source; the PDF is a signed artifact").
- After parsing, show a **preflight summary**: detected document outline
  (sections/notes), counts (sections, segments, tables, words), detected
  source language, estimated TM reuse ("~62% matches last year's approved
  translation") when a prior year exists.
- Configuration before starting: **target language(s)** (same 15-market list;
  typical run is 1–2 targets, e.g. NL, DE), **glossary domain** (defaults to
  Financial), **number localisation** toggle (`319,915 → 319.915`,
  `January 31, 2026 → 31 januari 2026`) — off by default, and a
  **translation-disclaimer page** toggle ("the English version is leading").

### B. Translation run (long-running job)
- This takes **minutes, not seconds**: thousands of segments across ~40
  sections, translated section-by-section.
- Show progress **on the document tree**: per-section state
  (queued / translating / done / failed) plus overall % and segment counts.
- The user can leave and come back — the library shows the running state.
- Sections that fail can be **retried individually** without restarting.
- Cancel is available and safe (everything completed so far is kept).

### C. Review workspace — design this as the core screen
- **Left rail: the document tree.** Sections and notes with status rollups
  (e.g. "2.19 Right-of-use assets — 3 to review / 41 approved"). The tree is
  the primary navigation and the progress instrument.
- **Main panel: segments of the selected section**, source (EN) vs target,
  row-per-segment. Tables render *as tables*: label cells editable, numeric
  cells visibly **locked** (never editable, never AI-touched).
- **Per-segment status + provenance badges:** `TM` (reused from approved
  memory) / `AI` (machine translated) / `edited` (human touched) /
  `needs attention` (QA finding or low confidence) / `approved`.
- **Review-by-exception:** default filter shows what needs a human. Filters:
  needs attention · AI-new · edited · all; plus free-text search across
  source and target.
- **Inline edit** of any target segment; **re-translate segment** with an
  optional instruction ("more formal", "use 'reële waarde'").
- **Glossary term highlighting** in both columns; a mismatch (glossary says X,
  translation used Y) is a visible finding on the segment.
- **Term fix at scale:** from any segment, "apply this term everywhere" —
  show how many segments it affects before confirming.
- Approve per segment and **per section** ("approve remaining 38 in this
  section"); approving all sections completes the document.

### D. QA report
- A dedicated view (or panel) listing findings by type: **number mismatch**
  (critical — blocks export), **glossary inconsistency**, **do-not-translate
  violation**, **length expansion warning** (target much longer than source).
- Each finding deep-links to its segment in the review workspace.
- Show the "all clear" state proudly — this is the trust moment of the
  product ("2,913 numbers verified identical").

### E. Glossary (financial domain)
- Same manager as briefings, scoped by domain. Financial glossary rows:
  `impairment → bijzondere waardevermindering`, `fair value → reële waarde`…
- Do-not-translate list is shared: brand/program names ("Together Tomorrow",
  "For Every Woman In You"), entity names, standard references (IFRS 16,
  EBITDA).

### F. Translation memory
- Surface TM as a **benefit, not a concept**: "1,847 segments reused from
  FY2024-25 (approved)" in preflight and in the completed summary.
- Per-segment `TM` badge with a hover/detail showing which document/year it
  came from. Reused segments arrive pre-approved but remain editable.

### G. Export & handoff
- Export translated `.docx` (layout identical, table of contents re-rendered,
  optional disclaimer page included).
- Blocked while critical QA findings are open — the blocked state must say
  exactly what to resolve.
- Completed state: download + QA summary + "translated by GCC Studio,
  reviewed by <user>" metadata.

---

## 6. Key screens & states to design

1. **Documents library** — list with statuses (parsing / translating /
   in review / approved / exported), progress, and its empty state.
2. **Preflight** — parsed outline, counts, TM-reuse estimate, config, Start.
3. **Translating** — tree with mixed section states, overall progress, one
   failed section with retry.
4. **Review workspace** (multiple states):
   a. prose section with mixed badges (TM / AI / edited / needs attention);
   b. a **table-heavy section** with locked numeric cells;
   c. the exception filter active ("14 segments need attention");
   d. re-translate-with-instruction on a single segment.
5. **QA report** — findings list incl. one critical number mismatch; and the
   all-clear state.
6. **Export** — blocked-by-QA state and the happy completed state.
7. **Errors** — unparseable docx, PDF rejected, one section failed while the
   rest succeeded.

Desktop-first (internal power tool), usable to ~1024px. Mobile out of scope.

---

## 7. Interaction & quality bar

- **Scale honestly:** a report has thousands of segments. Never present a
  3,000-row wall — the tree + rollups + exception filters are how a human
  survives this. Virtualized lists; sticky section context while scrolling.
- **Trust is the product.** Locked numbers, verified-counts messaging, and
  provenance badges must be legible at a glance; the QA all-clear should feel
  like the reward.
- **Review velocity:** keyboard-friendly (next/prev segment, approve, edit),
  autosave-feel edits, no modal churn in the main loop.
- Loading, empty, partial-failure, and long-running states are first-class.
- Accessibility: contrast on dark theme, keyboard navigation, focus states.
- Density over whitespace — scannable, calm, on-brand.

---

## 8. Out of scope (for now)

- PDF ingestion or translation (docx is the only source).
- Layout/WYSIWYG editing — layout fidelity is guaranteed by the engine.
- Editing the English source document.
- Batch-translating multiple documents at once.
- Mobile layouts.

---

## 9. Deliverables

- High-fidelity designs for the screens/states in §6, on the dark GCC theme.
- A short component inventory (document tree with rollups, segment row,
  provenance/status badges, locked table cell, QA finding row, progress
  states) consistent with Angular Material.
- Notes on the IA choice (how Documents sits next to Briefings) and on the
  review-by-exception pattern so engineering can implement without ambiguity.

> Constraint: ships as an Angular + Angular Material + Tailwind page inside an
> existing dark app. Beautiful but buildable — reuse existing patterns from the
> briefings redesign, don't introduce a parallel design language.
