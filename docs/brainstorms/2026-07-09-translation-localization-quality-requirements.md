---
date: 2026-07-09
topic: translation-localization-quality
---

# Translation Localization Quality (HKM)

## Problem Frame
Translators for Dutch (8), German (7) and French (8) report that the
localization tool is *correct but too literal* — it reads as a 1-to-1
translation rather than localized copy. Root cause (confirmed in code): there
is **one shared prompt for all 14 markets**; only the language name and any
glossary hits vary. The single tone control is a global, Dutch-centric
informal/formal toggle applied to every selected market at once — which is
why French came out with **tu** instead of **vous**. On top of that,
several concrete defects hurt trust: German ALL-CAPS CTAs (SHOP NOW) lose
their casing, collection/brand names (e.g. *cashmere*) get translated
word-for-word, and blank "push copy" rows can't be translated. Two latent
gaps also surfaced: the form's "Notes (context, tone of voice, brand
guidelines)" field is saved but **never sent to the model**, and the
brand-guidelines module (wired into image/video prompts) is absent here.

Audience: the per-language content owners/translators (Roxanne NL, Greta DE,
Lea FR) who want to steer output themselves and have it stick.

## Requirements
- R1. **Per-language localization profile** — one persistent profile per
  target language, editable by anyone with access (shared, not per-user).
  Each profile holds: (a) a **formality** setting appropriate to that
  language (e.g. FR vous/tu, DE Sie/du, NL informeel/formeel; languages
  without the distinction get a sensible default), (b) a **preserve-casing**
  toggle, and (c) a **free-text tone/style guidance** field. The profile is
  injected into the translation prompt for that market so output is steered
  per language.
- R2. **Formality is profile-driven per language**, replacing the single
  global informal/formal toggle. Selecting multiple markets in one job no
  longer forces one shared formality across all of them (fixes FR → vous).
- R3. **Preserve ALL-CAPS CTAs** — when a source segment is entirely
  uppercase (typical for CTA buttons), the translation is rendered in the
  same all-caps style (e.g. SHOP NOW → JETZT SHOPPEN).
- R4. **Do-not-translate terms** — the dictionary/glossary supports a
  "keep exactly as-is" term type for brand/collection/product names (e.g.
  *cashmere*, collection names), applied per language. Entered manually in
  v1.
- R5. **Translatable push-copy / blank rows** — the user can add and
  translate push-copy (and other intentionally-added lines) that the current
  pipeline silently skips because the source cell is blank.
- R6. **Wire the "Notes" field into the prompt** — the existing
  context/tone/brand-guidelines note is actually sent to the model and
  influences the translation (today it is decorative only).

## Success Criteria
- The three reported issues are gone: French uses vous by default, German
  ALL-CAPS CTAs stay all-caps, and terms like *cashmere*/collection names are
  preserved.
- A translator can adjust their language's tone/style guidance once and every
  later translation for that language reflects it, without re-entering it.
- Push copy added under a request can be translated (not silently skipped).
- Text placed in "Notes" measurably changes the output.
- Perceived quality: the language owners rate the output as more "localized,
  natural" than the current 7–8 baseline on a re-test of representative copy.

## Scope Boundaries
- **No per-user configs** — profiles are shared per language.
- **No automatic sourcing of collection/product names from the website** in
  v1 — do-not-translate terms are entered manually (website/product-feed
  sourcing is a later step).
- **No change to the review/feedback (QA) loop** itself.
- **No post-hoc AI verification** that the model obeyed the glossary/rules
  (beyond preserving casing) in v1.
- Not building a full brand-voice engine; per-language free-text guidance +
  the Notes field cover tone for now.

## Key Decisions
- **Structured + free-text per-language profile**: fixed settings (formality,
  casing) for the hard rules that must be reliable, plus a free-text guidance
  box for the nuance that makes copy sound natural. Rationale: the naturalness
  complaints need flexible steering, but tu/vous and casing are deterministic
  rules that shouldn't depend on prose phrasing.
- **Shared per-language, persistent, editable by anyone with access**:
  matches how the feedback is already organized (one owner per language) and
  avoids output drift between colleagues.
- **Replace the global tone toggle with profile-driven formality** rather than
  keeping a per-run toggle, since the global toggle is what produced the
  French tu bug.
- **All four concrete fixes (R3–R6) ship in v1** alongside the profile — they
  are individually small and each maps directly to reported feedback.

## Dependencies / Assumptions
- Builds on the existing translations module (briefing flow) and the existing
  glossary/dictionary (already per-language, already able to force fixed
  terms). The brand-guidelines module exists and could later feed tone, but
  is not required for v1.
- Content input from the language owners will be needed to seed the initial
  per-language guidance/formality — but the feature must ship with sensible
  defaults so it is usable before that.

## Outstanding Questions

### Resolve Before Planning
- (none — scope and behavior are settled; the items below are implementation
  or content questions that do not block planning.)

### Deferred to Planning
- [Affects R1][Technical] Where the per-language profile is stored — a
  dedicated per-language table (mirroring the glossary pattern) vs a JSON blob
  under the existing system settings.
- [Affects R2][Needs input] The exact formality options per language and their
  defaults (e.g. FR default vous) — sensible defaults chosen during planning,
  refined with the language owners.
- [Affects R3][Technical] Casing preservation via prompt instruction vs
  deterministic post-processing (detect all-caps source → uppercase target).
- [Affects R4][Technical] Do-not-translate matching robustness (word-boundary,
  avoid false positives) and how it is distinguished from normal glossary
  entries in the dictionary UI.
- [Affects R5][Needs design] How push copy is added in the briefing UI (extra
  segment row vs a dedicated push-copy field) and how it flows to export.
- [Affects R1/R6][Technical] Whether both prompt builders (the briefing flow
  and the legacy single-string path) adopt the per-language logic, or the
  work consolidates on the briefing flow.

## Next Steps
→ `/ce:plan` for structured implementation planning.
