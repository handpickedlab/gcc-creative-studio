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

import json
import logging
import re

from fastapi import Depends, HTTPException, status

from src.multimodal.gemini_service import GeminiService
from src.translations import briefing_parser as parser
from src.translations import localization
from src.translations.briefing_export import build_briefing_xlsx
from src.translations.dto.briefing_dto import (
    BriefingInputDto,
    MarketTranslationDto,
    ParseResultDto,
    SaveBriefingRequestDto,
    TmImportResultDto,
)
from src.translations.markets import (
    SOURCE_MARKET,
    is_valid_market,
    language_for_market,
)
from src.translations.repository.briefing_repository import BriefingRepository
from src.translations.repository.glossary_repository import GlossaryRepository
from src.translations.repository.language_config_repository import (
    LanguageConfigRepository,
)
from src.translations.schema.briefing_model import (
    BriefingMeta,
    BriefingSegment,
)
from src.translations.schema.language_config_model import (
    TranslationLanguageConfigModel,
)

logger = logging.getLogger(__name__)


class BriefingService:
    def __init__(
        self,
        repo: BriefingRepository = Depends(),
        glossary_repo: GlossaryRepository = Depends(),
        gemini_service: GeminiService = Depends(),
        language_config_repo: LanguageConfigRepository = Depends(),
    ):
        self.repo = repo
        self.glossary_repo = glossary_repo
        self.gemini_service = gemini_service
        self.language_config_repo = language_config_repo

    # --- Per-language localization profiles ------------------------------

    async def list_language_configs(
        self,
    ) -> list[TranslationLanguageConfigModel]:
        return await self.language_config_repo.list_all()

    async def upsert_language_config(
        self, language: str, data: dict
    ) -> TranslationLanguageConfigModel:
        if not is_valid_market(language) or language == SOURCE_MARKET:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown target market: {language}",
            )
        return await self.language_config_repo.upsert(language, data)

    # --- Upload / parsing ------------------------------------------------

    def parse_upload(
        self,
        file_bytes: bytes,
        sheet_name: str | None,
        request_index: int | None,
    ) -> ParseResultDto:
        try:
            sheets = parser.list_sheets(file_bytes)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Could not read workbook: {e}",
            )

        if not sheet_name:
            # Default to a sheet that looks like a copy sheet, else first.
            sheet_name = "Copy Sheet" if "Copy Sheet" in sheets else sheets[0]

        if sheet_name not in sheets:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Sheet '{sheet_name}' not found.",
            )

        try:
            requests = parser.find_requests(file_bytes, sheet_name)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Could not parse sheet '{sheet_name}': {e}",
            )

        req_infos = []
        for r in requests:
            filled = 0
            try:
                parsed = parser.parse_request(file_bytes, sheet_name, r["index"])
                filled = sum(1 for s in parsed["segments"] if s.get("text"))
            except Exception:
                filled = 0
            req_infos.append(
                {"index": r["index"], "label": r["label"], "filled": filled}
            )

        result = ParseResultDto(
            sheets=sheets, selected_sheet=sheet_name, requests=req_infos
        )

        if request_index is not None and requests:
            try:
                parsed = parser.parse_request(
                    file_bytes, sheet_name, request_index
                )
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Could not parse request {request_index}: {e}",
                )
            result.briefing_name = parsed["name"]
            result.meta = BriefingMeta(**parsed["meta"])
            result.segments = [BriefingSegment(**s) for s in parsed["segments"]]

        return result

    async def import_translation_memories(
        self, file_bytes: bytes
    ) -> TmImportResultDto:
        try:
            entries = parser.parse_translation_memories(file_bytes)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Could not parse Translation Memories sheet: {e}",
            )
        # Store market code in the glossary `language` column.
        rows = [
            {"language": e["market"], "source": e["source"], "target": e["target"]}
            for e in entries
        ]
        inserted = await self.glossary_repo.bulk_upsert(rows)
        markets = sorted({e["market"] for e in entries})
        return TmImportResultDto(imported=inserted, markets=markets)

    # --- Translation -----------------------------------------------------

    @staticmethod
    def _extract_json(text: str):
        cleaned = text.strip()
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("no JSON object found")
        return json.loads(cleaned[start : end + 1])

    def _relevant_glossary(
        self, segments: list[BriefingSegment], terms: list
    ) -> tuple[list, list]:
        """Splits matching glossary terms into (normal, do-not-translate)."""
        joined = " \n ".join(s.text for s in segments if s.text)
        return localization.split_glossary_terms(terms, joined)

    def _build_market_prompt(
        self,
        segments: list[BriefingSegment],
        market: str,
        glossary: list,
        do_not_translate: list | None = None,
        profile: "TranslationLanguageConfigModel | None" = None,
        notes: str | None = None,
    ) -> str:
        language = language_for_market(market)
        lines = [
            f"You are a senior marketing copy translator localizing for "
            f"{language}. Localize (do not translate literally) the following "
            f"email campaign copy from English.",
            "Rules:",
            "- Prioritize natural, on-brand, idiomatic phrasing over a literal "
            "1-to-1 translation; adapt wording so it reads as if written by a "
            "native marketer.",
            "- Preserve any HTML tags (e.g. <b>) and placeholders such as "
            "[Name] exactly as-is.",
            "- Preserve the casing style of the source: if a value is written "
            "in ALL CAPS (e.g. a CTA), keep the translation in ALL CAPS.",
            "- Respect the max character limit when one is given.",
            "- Do not translate the field names; only the text values.",
        ]
        formality_line = localization.formality_instruction(
            profile.formality if profile else None
        )
        if formality_line:
            lines.append(formality_line)
        if profile and profile.guidance:
            lines.append(f"- Tone & style guidance for {language}: {profile.guidance}")
        if notes and notes.strip():
            lines.append(f"- Campaign context / notes from the requester: {notes.strip()}")
        if do_not_translate:
            lines.append(
                "- Never translate the following brand / product / collection "
                "names; reproduce each exactly as written, including casing:"
            )
            for t in do_not_translate:
                lines.append(f'    "{t.source}"')
        if glossary:
            lines.append(
                "- Use these established translations for specific terms:"
            )
            for t in glossary:
                lines.append(f'    "{t.source}" -> "{t.target}"')
        lines.append("")
        lines.append(
            'Return ONLY a JSON object mapping each item index (as a string) '
            'to its translated text. Example: {"0": "...", "1": "..."}.'
        )
        lines.append("")
        lines.append("Items to translate:")
        for i, s in enumerate(segments):
            limit = f" (max {s.char_limit} chars)" if s.char_limit else ""
            field = f"{s.block}/{s.field}" if s.block else s.field
            lines.append(f'{i}. [{field}{limit}]: {s.text}')
        return "\n".join(lines)

    def _apply_casing(
        self,
        source_segments: list[BriefingSegment],
        out: list[BriefingSegment],
        idx: list[int],
    ) -> None:
        """Force ALL-CAPS on translations whose source was all-caps (R3)."""
        for seg_i in idx:
            out[seg_i].text = localization.apply_caps(
                source_segments[seg_i].text, out[seg_i].text
            )

    def _translate_market(
        self,
        segments: list[BriefingSegment],
        market: str,
        terms: list,
        profile: "TranslationLanguageConfigModel | None" = None,
        notes: str | None = None,
    ) -> list[BriefingSegment]:
        # Indices that actually have source text.
        idx_with_text = [i for i, s in enumerate(segments) if s.text.strip()]
        out = [s.model_copy(update={"text": ""}) for s in segments]
        if not idx_with_text:
            return out

        translatable = [segments[i] for i in idx_with_text]
        glossary, dnt = self._relevant_glossary(translatable, terms)
        prompt = self._build_market_prompt(
            translatable, market, glossary, dnt, profile, notes
        )

        try:
            raw = self.gemini_service.generate_text(prompt)
            data = self._extract_json(raw)
            for local_i, seg_i in enumerate(idx_with_text):
                val = data.get(str(local_i))
                out[seg_i].text = (
                    str(val).strip() if val is not None else segments[seg_i].text
                )
        except Exception as e:
            logger.warning(
                "Batched translation for %s failed (%s); falling back per-segment",
                market,
                e,
            )
            language = language_for_market(market)
            for seg_i in idx_with_text:
                s = segments[seg_i]
                limit = (
                    f" Keep it within {s.char_limit} characters."
                    if s.char_limit
                    else ""
                )
                p = (
                    f"Translate this marketing copy from English into "
                    f"{language}. Preserve HTML tags and [placeholders]."
                    f"{limit} Return only the translation.\n\n{s.text}"
                )
                try:
                    out[seg_i].text = self.gemini_service.generate_text(p).strip()
                except Exception as inner:
                    logger.error("Segment translation failed: %s", inner)
                    out[seg_i].text = s.text

        # Deterministic casing guardrail (only when the profile allows it).
        if profile is None or profile.preserve_casing:
            self._apply_casing(segments, out, idx_with_text)
        return out

    async def translate_briefing(
        self,
        briefing: BriefingInputDto,
        markets: list[str],
    ) -> list[MarketTranslationDto]:
        invalid = [m for m in markets if not is_valid_market(m)]
        if invalid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown market(s): {', '.join(invalid)}",
            )
        all_terms = await self.glossary_repo.get_by_languages(markets)
        by_market: dict[str, list] = {}
        for t in all_terms:
            by_market.setdefault(t.language, []).append(t)
        profiles = await self.language_config_repo.get_by_languages(markets)
        notes = briefing.meta.notes if briefing.meta else None

        results: list[MarketTranslationDto] = []
        for market in markets:
            if market == SOURCE_MARKET:
                continue
            translated = self._translate_market(
                briefing.segments,
                market,
                by_market.get(market, []),
                profiles.get(market),
                notes,
            )
            results.append(
                MarketTranslationDto(market=market, segments=translated)
            )
        return results

    # --- Persistence -----------------------------------------------------

    async def save_briefing(self, dto: SaveBriefingRequestDto):
        b = dto.briefing
        meta = b.meta.model_dump()
        segments = [s.model_dump() for s in b.segments]
        # Upsert: update when an id is supplied, otherwise create.
        saved = None
        if b.id is not None:
            saved = await self.repo.update_briefing(b.id, b.name, meta, segments)
        if saved is None:
            saved = await self.repo.create_briefing(
                name=b.name,
                source_market=b.source_market,
                meta=meta,
                segments=segments,
            )
        for tr in dto.translations:
            await self.repo.upsert_translation(
                saved.id,
                tr.market,
                [s.model_dump() for s in tr.segments],
                status=tr.approval or "draft",
                comment=tr.comment,
            )
        await self.repo.commit()
        return saved

    def export_xlsx(
        self, briefing: BriefingInputDto, translations: list[MarketTranslationDto]
    ) -> bytes:
        briefing_dict = {
            "name": briefing.name,
            "meta": briefing.meta.model_dump(),
            "segments": [s.model_dump() for s in briefing.segments],
        }
        tr_dicts = [
            {"market": t.market, "segments": [s.model_dump() for s in t.segments]}
            for t in translations
        ]
        return build_briefing_xlsx(briefing_dict, tr_dicts)

    async def glossary_summary(self):
        from src.translations.dto.briefing_dto import (
            GlossaryMarketSummary,
            GlossarySample,
            GlossarySummaryDto,
        )

        terms = await self.glossary_repo.find_all(limit=100000)
        by_market: dict[str, list] = {}
        for t in terms:
            by_market.setdefault(t.language, []).append(t)

        per_market = []
        for market in sorted(by_market):
            items = by_market[market]
            per_market.append(
                GlossaryMarketSummary(
                    market=market,
                    count=len(items),
                    samples=[
                        GlossarySample(source=i.source, target=i.target)
                        for i in items[:3]
                    ],
                )
            )
        return GlossarySummaryDto(total=len(terms), per_market=per_market)

    # --- Glossary management (configurable by end users) -----------------

    async def list_glossary(self, market: str | None, q: str | None):
        if market:
            terms = await self.glossary_repo.get_by_languages([market])
        else:
            terms = await self.glossary_repo.find_all(limit=100000)
        if q:
            ql = q.lower()
            terms = [
                t
                for t in terms
                if ql in t.source.lower() or ql in t.target.lower()
            ]
        return sorted(terms, key=lambda t: t.source.lower())[:500]

    async def create_glossary_term(
        self,
        market: str,
        source: str,
        target: str | None = None,
        do_not_translate: bool = False,
    ):
        existing = await self.glossary_repo.get_by_language_and_source(
            market, source
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"'{source}' already exists in the {market} dictionary.",
            )
        # A do-not-translate term is reproduced verbatim, so the target
        # defaults to the source when the caller omits it.
        resolved_target = target or source
        return await self.glossary_repo.create(
            {
                "language": market,
                "source": source,
                "target": resolved_target,
                "do_not_translate": do_not_translate,
            }
        )

    async def update_glossary_term(self, term_id: int, data: dict):
        # Map external 'market' onto the stored 'language' column.
        if "market" in data:
            data["language"] = data.pop("market")
        updated = await self.glossary_repo.update(term_id, data)
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Glossary term {term_id} not found.",
            )
        return updated

    async def delete_glossary_term(self, term_id: int) -> None:
        deleted = await self.glossary_repo.delete(term_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Glossary term {term_id} not found.",
            )

    async def list_briefings(self):
        return await self.repo.list_briefings()

    async def rename_briefing(self, briefing_id: int, name: str) -> None:
        ok = await self.repo.rename_briefing(briefing_id, name)
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Briefing {briefing_id} not found.",
            )

    async def delete_briefing(self, briefing_id: int) -> None:
        ok = await self.repo.delete_briefing(briefing_id)
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Briefing {briefing_id} not found.",
            )

    async def get_briefing_with_translations(self, briefing_id: int):
        briefing = await self.repo.get_briefing(briefing_id)
        if not briefing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Briefing {briefing_id} not found.",
            )
        translations = await self.repo.get_translations(briefing_id)
        return {"briefing": briefing, "translations": translations}
