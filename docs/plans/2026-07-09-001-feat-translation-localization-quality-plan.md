---
title: "feat: Translation localization quality (per-language profiles + fixes)"
type: feat
status: completed
date: 2026-07-09
origin: docs/brainstorms/2026-07-09-translation-localization-quality-requirements.md
---

# feat: Translation Localization Quality

## Overview

Make the localization tool produce *localized* copy instead of literal 1-to-1
translations, and fix the concrete defects translators reported (French
tu/vous, German ALL-CAPS CTAs, word-for-word collection names, un-translatable
push copy, an ignored Notes field). The core change is a **persistent
per-language localization profile** (formality + casing rule + free-text tone
guidance) that is injected into the translation prompt for each market,
replacing today's single global informal/formal toggle and one-size-fits-all
prompt. Four targeted fixes ship alongside it.

## Problem Frame

Translators rated the tool 7–8 but "correct, not localized." Root cause (from
the brainstorm code map): `backend/src/translations/briefing_service.py`
builds **one shared prompt for all 14 markets** — only the language name and
glossary hits vary — and the only tone control is a global, Dutch-centric
`informeel/formeel` toggle applied to every selected market at once (hence
French → *tu*). Additional defects: no ALL-CAPS preservation, collection/brand
names translated word-for-word, blank "push copy" rows silently skipped, and
the "Notes (context, tone of voice, brand guidelines)" field saved but never
sent to the model. Full context: see origin doc.

## Requirements Trace

- R1. Per-language localization profile (formality, preserve-casing, free-text
  guidance), persistent, shared per language, injected into the prompt → Units 1, 2, 6
- R2. Formality is profile-driven per language, replacing the global toggle
  (fixes FR → vous) → Units 2, 6
- R3. Preserve ALL-CAPS CTAs (SHOP NOW → JETZT SHOPPEN) → Unit 3
- R4. Do-not-translate terms for brand/collection/product names → Unit 4
- R5. Translatable push-copy / added lines (no longer silently skipped) → Unit 5
- R6. Wire the existing "Notes" field into the prompt → Unit 2
- Success criteria (naturalness re-test, persistence, push copy, Notes effect) → all units; validated in Unit 6

## Scope Boundaries

- No per-user configs — profiles are shared per language.
- No automatic sourcing of collection/product names from the website — manual
  do-not-translate entries in v1.
- No change to the review/feedback (QA) loop.
- No post-hoc AI verification that the model obeyed rules (except the
  deterministic casing pass in R3).
- Not building a full brand-voice engine; per-language guidance + Notes cover
  tone. (Wiring the existing brand_guidelines module into translations is
  noted as a future option, not in scope.)

## Context & Research

External research skipped: this extends well-established in-repo patterns
(per-language glossary, system settings, the prompt builder). No new tech.

### Relevant Code and Patterns

- `backend/src/translations/briefing_service.py` — THE chokepoint.
  `_build_market_prompt(segments, market, glossary, tone)` assembles the single
  prompt; `_translate_market()` calls `GeminiService.generate_text()`, parses
  JSON, and **excludes blank-source segments** (`idx_with_text`); the JSON path
  falls back to per-segment prompts. `translate_briefing()` loops markets. The
  `tone` param threads through all three.
- `backend/src/translations/markets.py` — `MARKETS: dict[str, str]` (code →
  locale label), `SOURCE_MARKET="EN"`, `TARGET_MARKETS`, `language_for_market()`.
- `backend/src/translations/schema/glossary_term_model.py` — `GlossaryTerm`
  (`language`, `source`, `target`), unique `(language, source)`; Pydantic +
  SQLAlchemy in one file (house style). `_relevant_glossary()` in
  briefing_service does naive lowercased substring matching, capped at
  `_MAX_GLOSSARY_HINTS=60`.
- `backend/src/translations/repository/glossary_repository.py` —
  `get_by_languages()`, `bulk_upsert()`, `get_by_language_and_source()`
  (repository pattern to mirror for the new config).
- `backend/src/system_settings/` — `SystemSetting` model/repo/service; existing
  lightweight global-config mechanism (used by glossary seed guard).
- `backend/src/translations/schema/briefing_model.py` — `Briefing.meta`
  (`BriefingMeta` incl. `notes`), `Briefing.segments` (list of
  `BriefingSegment{block, field, label, char_limit, text}`),
  `BriefingTranslation`.
- `backend/src/translations/briefing_parser.py` — `parse_request()` skips rows
  with no field label; keeps field-labelled rows even when EN text is empty.
- `backend/src/translations/briefing_export.py` — `build_briefing_xlsx()`
  rebuilds the sheet (push-copy segments must round-trip through here).
- `backend/src/multimodal/gemini_service.py` — `generate_text(prompt, model_id)`;
  plain text-in/out, no `system_instruction`/temperature exposed today.
- Frontend: `frontend/src/app/translations/translations.component.ts` / `.html`
  — global `tone: 'informeel'|'formeel'` toggle, `notes` textarea (saved, unused
  by the model), `service.translate(briefing, markets, tone)` calls;
  `frontend/src/app/services/translation.service.ts`.
- Migration conventions: `backend/alembic/versions/<hash>_<desc>.py` additive;
  register new models in `backend/alembic/env.py`. Recent example in-repo:
  the research-library and data-query-sheets migrations.

### Institutional Learnings

- Additive-only migrations, auto-run at startup; re-pin `down_revision` to the
  real head at merge; import new models in `alembic/env.py`.
- Backend tests: `uv sync --extra dev`, async tests need `@pytest.mark.anyio`;
  Gemini mocked per `tests/multimodal/test_gemini_service.py`.
- Deploy is manual (BuildKit cloudbuild → `run deploy --no-traffic --tag` →
  verify migration in logs → route traffic); frontend prod build MUST use
  `ng build --configuration production` (the `build-prd` script omits the env
  fileReplacement) and inject Firebase/GOOGLE_CLIENT_ID + firebase.json
  placeholders, then restore placeholders (never commit secrets).

## Key Technical Decisions

- **Dedicated per-language config table**, not a system_settings JSON blob:
  the profile is user-editable with a UI and naturally one row per language, so
  it mirrors the established `GlossaryTerm` table/repository pattern (clean
  CRUD, upsert, queryable) rather than overloading the flat key/value settings
  store.
- **Formality as a small enum** (`formal | informal | default`) interpreted
  per language in the prompt (e.g. "use the formal register (vous)"), plus the
  free-text guidance for nuance. Rationale: tu/vous must be deterministic, not
  dependent on prose phrasing; the free-text field covers naturalness.
- **Profile replaces the global toggle** (rather than adding a per-run
  override): the global toggle is what produced the FR tu bug; the profile is
  the single source of truth. A per-run override is deferred.
- **ALL-CAPS preserved deterministically** (post-process) plus a prompt hint:
  if a source segment (minus HTML tags/`[placeholders]`) is entirely
  uppercase, uppercase the translated value. A prompt instruction alone is not
  reliable enough for a trust-sensitive rule.
- **Do-not-translate via a flag on `GlossaryTerm`** (`do_not_translate`), not a
  separate table: reuses the per-language dictionary the translators already
  manage; the prompt gets a dedicated, stronger "never translate these names,
  keep them verbatim incl. casing" block, and matching gains a word-boundary
  check to avoid false positives.
- **Push copy as explicit user-added segments** in the UI (not fragile parser
  heuristics on the source sheet): a dedicated "Push copy" input per request
  produces normal segments that translate and export like any other.
- **Briefing flow is primary**; the legacy single-string
  `translation_service.py` path adopts the same per-language profile + casing +
  do-not-translate for consistency (notes/push-copy are briefing-only).

## Open Questions

### Resolved During Planning

- Storage of the profile → dedicated `translation_language_config` table (see decisions).
- Formality representation → `formal|informal|default` enum interpreted per language; FR defaults to `formal`.
- Global toggle fate → removed, replaced by profile-driven formality.
- Casing mechanism → deterministic post-process + prompt hint.
- Do-not-translate home → `do_not_translate` flag on `GlossaryTerm`.

### Deferred to Implementation

- [Affects R2][Needs input] The seeded default formality/guidance per language
  (sensible defaults chosen at implementation; refined later with the language
  owners). FR=formal is the one firm default.
- [Affects R5][Needs design] Exact push-copy UI affordance (repeatable text
  rows under a request) and how push segments are labelled so
  `briefing_export.build_briefing_xlsx()` places them sensibly.
- [Affects R4][Technical] Word-boundary matching approach for do-not-translate
  terms across languages (incl. non-Latin scripts) and how the dictionary UI
  distinguishes a do-not-translate entry from a normal glossary row.
- [Affects R1][Technical] Whether to also pass the profile guidance as a
  `system_instruction` / lower temperature on `generate_text` (nice-to-have;
  prompt injection is the baseline).

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

Per-market prompt assembly after this change — everything converges in
`_build_market_prompt`, with a deterministic casing pass after the model call:

```
translate_briefing(briefing, markets)
  for each market:
    profile   = language_config_repo.get(market)      # formality, casing, guidance
    glossary  = relevant_glossary(market)             # normal terms
    dnt_terms = relevant_do_not_translate(market)     # keep-verbatim terms
    prompt = build_market_prompt(
        segments, language_label(market),
        formality  = profile.formality,        # → "use the formal register (vous)"
        guidance   = profile.guidance,         # free-text, per language
        notes      = briefing.meta.notes,      # R6: now actually included
        glossary   = glossary,
        do_not_translate = dnt_terms,          # "never translate, keep verbatim"
        preserve_casing  = profile.preserve_casing,
    )
    out = generate_text(prompt) → JSON map
    for each segment:
      if source_is_all_caps(segment) and profile.preserve_casing:   # R3
        out[segment] = out[segment].upper()
```

## Implementation Units

- [x] **Unit 1: Per-language config — model, migration, repository, API**

**Goal:** A persistent, editable per-language localization profile exists and
is reachable over the API.

**Requirements:** R1

**Dependencies:** none

**Files:**
- Create: `backend/src/translations/schema/language_config_model.py`
  (`TranslationLanguageConfig` SQLAlchemy + `TranslationLanguageConfigModel`
  Pydantic, house style), `backend/src/translations/repository/language_config_repository.py`
- Create: `backend/alembic/versions/<hash>_add_translation_language_config.py`
- Modify: `backend/alembic/env.py` (import new model),
  `backend/src/translations/translations_controller.py` (or the existing
  translations/briefings router — GET all, GET one, PUT/upsert per language)
- Test: `backend/tests/translations/test_language_config_repository.py`

**Approach:**
- Columns: `language` (unique), `formality` (`formal|informal|default`,
  default `default`), `preserve_casing` (bool, default true), `guidance` (text,
  nullable), timestamps. One row per target market code.
- Repository mirrors `glossary_repository` (`get_by_language`, `list_all`,
  `upsert`). Additive migration; re-pin down_revision at merge.
- Endpoints role-guarded like the other translations routes.

**Patterns to follow:** `glossary_term_model.py` + `glossary_repository.py`.

**Test scenarios:** upsert creates then updates a language row; list returns
all; unknown language returns empty/none; formality constrained to the enum.

**Verification:** migration applies from current head on Postgres; CRUD works
via the FastAPI test client; a config round-trips.

- [x] **Unit 2: Inject the per-language profile + Notes into the prompt**

**Goal:** Translations are steered per language; the Notes field influences
output; the global tone param is gone.

**Requirements:** R1, R2, R6

**Dependencies:** Unit 1

**Files:**
- Modify: `backend/src/translations/briefing_service.py`
  (`_build_market_prompt`, `_translate_market`, `translate_briefing` — fetch the
  per-market config, drop the `tone` param, add formality/guidance/notes blocks),
  `backend/src/translations/translation_service.py` (legacy path: same profile
  lookup for consistency)
- Modify: `backend/src/translations/dto/*` and the translate endpoint (remove
  the global `tone` input; accept `notes` if not already passed through)
- Test: `backend/tests/translations/test_briefing_prompt.py`

**Approach:**
- `_build_market_prompt` gains formality → an explicit register instruction
  per language (e.g. formal → "address the reader formally (vous/Sie/u)"),
  appends the free-text guidance, and appends a "Campaign context / notes"
  block from `BriefingMeta.notes` when present.
- Formality comes from the profile per market; multiple markets in one job no
  longer share one tone.

**Execution note:** Build `_build_market_prompt` prompt-assembly under a unit
test first — it is pure and multi-branch (formality × guidance × notes ×
glossary present/absent).

**Test scenarios:** FR profile `formal` yields a vous/formal instruction; two
markets with different formality in one call get different prompts; notes text
appears in the prompt; empty profile falls back to neutral defaults; the old
global tone no longer affects output.

**Verification:** unit tests assert the assembled prompt contains the expected
per-language instructions; a mocked end-to-end `translate_briefing` uses the
right profile per market.

- [x] **Unit 3: Preserve ALL-CAPS CTAs**

**Goal:** Fully-uppercase source segments stay uppercase after translation.

**Requirements:** R3

**Dependencies:** Unit 2

**Files:**
- Modify: `backend/src/translations/briefing_service.py` (post-process in
  `_translate_market`; small pure helper `is_all_caps_source`),
  `backend/src/translations/translation_service.py` (same helper for the legacy path)
- Test: `backend/tests/translations/test_casing.py`

**Approach:**
- Helper decides "source is all-caps" after stripping HTML tags and
  `[placeholders]` and ignoring non-letters; if true and the profile's
  `preserve_casing` is on, uppercase the translated value. Also add a prompt
  hint. Deterministic pass is the guarantee.

**Execution note:** Pure helper — write its table of cases test-first (all-caps
CTA, mixed case, caps with a `[placeholder]`, caps inside `<b>` tags, digits/symbols only).

**Test scenarios:** "SHOP NOW" → uppercased target; "Shop now" untouched;
"SHOP [Name]" keeps placeholder and uppercases the rest; preserve_casing off →
no change.

**Verification:** helper unit tests pass; a mocked translation of an all-caps
CTA returns an all-caps target.

- [x] **Unit 4: Do-not-translate terms (brand/collection/product names)**

**Goal:** Named terms like *cashmere* and collection names are kept verbatim.

**Requirements:** R4

**Dependencies:** Unit 2

**Files:**
- Modify: `backend/src/translations/schema/glossary_term_model.py` (add
  `do_not_translate` bool), `backend/alembic/versions/<hash>_add_glossary_do_not_translate.py`,
  `backend/src/translations/briefing_service.py` (`_relevant_glossary` split:
  normal hints vs do-not-translate; word-boundary match; dedicated prompt block),
  glossary repository/DTO if needed for the flag
- Modify (frontend): the dictionary/glossary management UI to expose a
  "keep as-is" toggle (see Unit 6 for placement)
- Test: `backend/tests/translations/test_glossary_matching.py`

**Approach:**
- Do-not-translate rows may omit `target`. The prompt gets a separate, stronger
  instruction: "Never translate the following brand/product/collection names;
  reproduce them exactly, including casing: …". Matching uses word boundaries
  to avoid false positives (the current lowercased substring match is a known
  pitfall).

**Test scenarios:** "cashmere" flagged do-not-translate appears in the verbatim
block and not the normal glossary block; word-boundary prevents matching inside
an unrelated word; a normal glossary term still works.

**Verification:** migration applies; matching unit tests pass; a mocked
translation keeps a flagged term unchanged.

- [x] **Unit 5: Push copy / added translatable lines**

**Goal:** Translators can add push-copy lines to a request and have them
translated and exported.

**Requirements:** R5

**Dependencies:** Unit 2

**Files:**
- Modify (frontend): `frontend/src/app/translations/translations.component.ts` /
  `.html` (a repeatable "Push copy" input per request that adds segments)
- Modify (backend): `backend/src/translations/briefing_service.py` (ensure
  user-added non-empty segments translate — they already will once present),
  `backend/src/translations/briefing_export.py` (place push segments in the
  exported sheet), segment model/labelling as needed
- Test: `backend/tests/translations/test_push_copy_export.py`

**Approach:**
- Push copy becomes normal `BriefingSegment`s (e.g. `block="Push"`,
  `field="push_copy"`) added from the UI, not parsed from the sheet — avoiding
  fragile parser heuristics. They flow through translate + review + export.

**Test scenarios:** a push segment with text is translated (not skipped); it
round-trips into the exported XLSX; an empty push line is ignored gracefully.

**Verification:** adding push copy in the UI yields a translated push line in
review and in the exported sheet.

- [x] **Unit 6: Frontend — per-language profile editor + wire-up**

**Goal:** Translators can edit each language's profile; the global toggle is
replaced; Notes is actually used.

**Requirements:** R1, R2, R6; success criteria

**Dependencies:** Units 1–5

**Files:**
- Create: a language-settings view/section (e.g.
  `frontend/src/app/translations/language-settings/…`) listing target languages
  with formality (select), preserve-casing (toggle) and guidance (textarea),
  saving via the Unit 1 API
- Modify: `frontend/src/app/translations/translations.component.ts` / `.html`
  (remove the global Informal/Formal toggle; keep Notes and ensure it is sent),
  `frontend/src/app/services/translation.service.ts` (config CRUD methods; drop
  the `tone` arg), plus the dictionary UI toggle from Unit 4
- Test: `frontend/src/app/translations/language-settings/*.spec.ts`

**Approach:**
- Per-language editor is the persistent home for tone/formality/casing. The
  translate action no longer sends a global tone; formality is resolved
  server-side per market from the profile.

**Test scenarios:** editing a language's guidance persists and reloads; saving
formality reflects on next translate; Notes entered on a briefing changes
output (verified against the backend).

**Verification:** end-to-end in the browser (logged in): set FR formality to
formal + a German guidance note, run a translation, confirm vous and the
German steering; add a do-not-translate term and confirm it is kept.

## System-Wide Impact

- **Interaction graph:** `translate_briefing → _translate_market →
  _build_market_prompt` all lose the `tone` param and gain a per-market config
  fetch; the legacy `translation_service.translate` path mirrors it. The
  translate endpoint DTO changes (drop global tone) — update the frontend
  service in lockstep.
- **Error propagation:** a missing per-language profile must degrade to neutral
  defaults, never error the translation job.
- **State lifecycle risks:** none significant; the config table is additive and
  independent. Do-not-translate flag is additive on an existing table.
- **API surface parity:** both prompt builders (briefing + legacy) must apply
  the profile so the two entry points stay consistent.
- **Integration coverage:** prompt-assembly and casing/matching helpers are
  unit-tested; the profile→prompt→output path is the cross-layer scenario to
  verify in Unit 6.

## Risks & Dependencies

- **Prompt quality is judgment-based**: "more natural" is subjective; validate
  with the language owners on representative copy rather than only unit tests.
- **Formality across 14 markets**: the enum must map sensibly to languages
  without a clean tu/vous split (default → neutral instruction).
- **Do-not-translate false positives**: mitigated by word-boundary matching;
  still verify on real collection names.
- **Deploy**: backend migration auto-runs on boot; frontend needs the correct
  production build recipe (see learnings). Create a feature branch before
  implementing — currently on `main`.

## Documentation / Operational Notes

- Seed sensible default profiles (esp. FR=formal) so the feature is usable
  before the language owners tune it; document how to edit profiles for the
  translators.
- Backend migration + a container redeploy; frontend redeploy. No new external
  services or cost.

## Sources & References

- **Origin document:** `docs/brainstorms/2026-07-09-translation-localization-quality-requirements.md`
- Related code: `backend/src/translations/` (briefing_service, markets,
  glossary_*, briefing_parser, briefing_export), `backend/src/system_settings/`,
  `frontend/src/app/translations/`
- Related prior work: research-library / data-query-sheets migrations and the
  frontend prod-deploy recipe (this repo, 2026-07).
