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
"""Financial-domain glossary seed for annual-report translation.

IFRS and Dutch statutory terms have established equivalents that auditors
and filings expect — this is terminology, not phrasing, so the model must
not improvise. Seeded once as a starting point; users edit and extend it
through the glossary manager afterwards.

Sourced from the terminology used across the Hunkemöller/Shero Holdco
annual reports (FY22-23 through FY25-26): the statements themselves, the
notes, and the Dutch statutory references.
"""

DOMAIN = "financial"

# (source_en, target_nl)
FINANCIAL_TERMS_NL: list[tuple[str, str]] = [
    # --- Statements -----------------------------------------------------
    ("annual report", "jaarverslag"),
    ("financial statements", "jaarrekening"),
    ("consolidated financial statements", "geconsolideerde jaarrekening"),
    ("company financial statements", "enkelvoudige jaarrekening"),
    ("statement of profit or loss", "winst-en-verliesrekening"),
    ("statement of other comprehensive income", "overzicht van het totaalresultaat"),
    ("statement of financial position", "balans"),
    ("statement of changes in equity", "overzicht van mutaties in het eigen vermogen"),
    ("statement of cash flows", "kasstroomoverzicht"),
    ("notes to the financial statements", "toelichting op de jaarrekening"),
    ("accounting policies", "grondslagen voor waardering en resultaatbepaling"),
    # --- Assets ---------------------------------------------------------
    ("intangible assets", "immateriële vaste activa"),
    ("property, plant and equipment", "materiële vaste activa"),
    ("right-of-use assets", "gebruiksrechten"),
    ("goodwill", "goodwill"),
    ("non-current assets", "vaste activa"),
    ("current assets", "vlottende activa"),
    ("inventories", "voorraden"),
    ("trade and other receivables", "handels- en overige vorderingen"),
    ("cash and cash equivalents", "liquide middelen"),
    ("deferred tax assets", "latente belastingvorderingen"),
    ("total assets", "totaal activa"),
    # --- Equity and liabilities -----------------------------------------
    ("equity", "eigen vermogen"),
    ("share capital", "aandelenkapitaal"),
    ("share premium", "agio"),
    ("retained earnings", "ingehouden winsten"),
    ("legal reserve", "wettelijke reserve"),
    ("foreign currency translation reserve", "reserve omrekeningsverschillen"),
    ("non-current liabilities", "langlopende verplichtingen"),
    ("current liabilities", "kortlopende verplichtingen"),
    ("financial liabilities", "financiële verplichtingen"),
    ("lease liabilities", "leaseverplichtingen"),
    ("trade and other payables", "handels- en overige schulden"),
    ("provisions", "voorzieningen"),
    ("deferred tax liabilities", "latente belastingverplichtingen"),
    ("pensions and other employee benefits", "pensioenen en overige personeelsbeloningen"),
    # --- Result ---------------------------------------------------------
    ("revenue", "omzet"),
    ("net sales", "netto-omzet"),
    ("cost of sales", "kostprijs van de omzet"),
    ("gross profit", "brutowinst"),
    ("operating result", "bedrijfsresultaat"),
    ("expenses by nature", "kosten naar aard"),
    ("salaries, social security charges and pension expenses",
     "lonen, sociale lasten en pensioenlasten"),
    ("amortisation", "amortisatie"),
    ("depreciation", "afschrijvingen"),
    ("impairment", "bijzondere waardevermindering"),
    ("impairment loss", "verlies uit bijzondere waardevermindering"),
    ("reversal of impairment", "terugneming van bijzondere waardevermindering"),
    ("financial income and expenses", "financiële baten en lasten"),
    ("income tax expense", "belastinglast"),
    ("profit before tax", "resultaat voor belastingen"),
    ("loss for the period", "verlies over de periode"),
    ("earnings per share", "winst per aandeel"),
    # --- Measurement ----------------------------------------------------
    ("fair value", "reële waarde"),
    ("carrying amount", "boekwaarde"),
    ("recoverable amount", "realiseerbare waarde"),
    ("value in use", "bedrijfswaarde"),
    ("net realisable value", "opbrengstwaarde"),
    ("cash-generating unit", "kasstroomgenererende eenheid"),
    ("incremental borrowing rate", "marginale rentevoet"),
    ("expected credit loss", "verwacht kredietverlies"),
    ("useful life", "gebruiksduur"),
    ("residual value", "restwaarde"),
    ("discount rate", "discontovoet"),
    ("estimation uncertainty", "schattingsonzekerheid"),
    ("critical accounting judgements", "belangrijke oordelen"),
    # --- Going concern / financing ---------------------------------------
    ("going concern", "continuïteit"),
    ("material uncertainty", "materiële onzekerheid"),
    ("covenant", "convenant"),
    ("revolving credit facility", "doorlopende kredietfaciliteit"),
    ("debt restructuring", "herstructurering van schulden"),
    ("recapitalisation", "herkapitalisatie"),
    ("solvency", "solvabiliteit"),
    ("liquidity risk", "liquiditeitsrisico"),
    ("credit risk", "kredietrisico"),
    ("currency risk", "valutarisico"),
    ("interest rate risk", "renterisico"),
    ("hedge accounting", "hedge-accounting"),
    ("off-balance sheet commitments", "niet in de balans opgenomen verplichtingen"),
    ("related party transactions", "transacties met verbonden partijen"),
    ("events after the balance sheet date", "gebeurtenissen na balansdatum"),
    ("operating segments", "operationele segmenten"),
    # --- Governance / statutory ------------------------------------------
    ("Management Board", "Raad van Bestuur"),
    ("Supervisory Board", "Raad van Commissarissen"),
    ("Statutory Board", "statutaire directie"),
    ("works council", "ondernemingsraad"),
    ("General Meeting", "Algemene Vergadering"),
    ("appropriation of result", "resultaatbestemming"),
    ("proposal of result appropriation", "voorstel tot resultaatbestemming"),
    ("large company regime", "structuurregime"),
    ("Dutch Civil Code", "Burgerlijk Wetboek"),
    ("Chamber of Commerce", "Kamer van Koophandel"),
    ("auditor's report", "controleverklaring"),
    ("auditor's remuneration", "accountantshonoraria"),
    ("remuneration of the Management Board", "bezoldiging van de Raad van Bestuur"),
    ("subsidiaries", "dochterondernemingen"),
    ("group companies", "groepsmaatschappijen"),
    ("shareholder", "aandeelhouder"),
    ("fiscal unity", "fiscale eenheid"),
    # --- Retail / operations ---------------------------------------------
    ("like-for-like sales", "vergelijkbare omzet"),
    ("store footprint", "winkelbestand"),
    ("franchise partners", "franchisepartners"),
    ("wholesale", "wholesale"),
    ("concessions", "concessies"),
    ("loyalty programme", "loyaliteitsprogramma"),
    ("supply chain", "toeleveringsketen"),
    ("double materiality assessment", "dubbele materialiteitsanalyse"),
]

# Reproduced verbatim in every language: standards, metrics, entities and
# programme names that would lose their meaning translated.
DO_NOT_TRANSLATE: list[str] = [
    "IFRS",
    "IAS",
    "EBITDA",
    "EBIT",
    "SBTi",
    "CSRD",
    "LkSG",
    "ESG",
    "Hunkemöller",
    "Shero Holdco B.V.",
    "Hunkemöller International B.V.",
    "Together Tomorrow",
    "For Every Woman In You",
    "Click & Collect",
    "KPMG",
    "Deloitte",
]


# Only markets we have vetted terminology for get term pairs. Flemish uses
# the same IFRS vocabulary as Dutch; a Belgian reviewer can adjust after
# seeding. Other markets start with the protected names only, and their
# terms get added through the glossary manager.
FINANCIAL_TERMS_BY_LANGUAGE: dict[str, list[tuple[str, str]]] = {
    "NL": FINANCIAL_TERMS_NL,
    "BENL": FINANCIAL_TERMS_NL,
}


def seed_entries(language: str) -> list[dict]:
    """Rows for `GlossaryRepository.bulk_upsert` for one target market."""
    terms = [
        {
            "language": language,
            "source": source,
            "target": target,
            "domain": DOMAIN,
            "do_not_translate": False,
        }
        for source, target in FINANCIAL_TERMS_BY_LANGUAGE.get(language, [])
    ]
    protected = [
        {
            "language": language,
            "source": name,
            "target": name,
            "domain": DOMAIN,
            "do_not_translate": True,
        }
        for name in DO_NOT_TRANSLATE
    ]
    return terms + protected
