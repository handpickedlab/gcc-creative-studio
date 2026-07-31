/**
 * Copyright 2026 Google LLC — Licensed under the Apache License, Version 2.0.
 * Hunkemöller "Documents" — data layer for the document-translation experience.
 *
 * Demo corpus: Hunkemöller Group Annual Report FY ended Jan 31, 2026. The
 * backend job/API layer lands in a later slice; this drives the full UI.
 */

export type DocStatus =
  | 'parsing'
  | 'translating'
  | 'review'
  | 'approved'
  | 'exported'
  | 'failed'
  | 'draft';
export type Provenance = 'tm' | 'ai' | 'edited';
export type QaType = 'number' | 'glossary' | 'dnt' | 'length';
export type SegKind = 'h1' | 'h2' | 'p' | 'trow';
export type RunState = 'queued' | 'run' | 'done' | 'fail';
export type ReviewFilter = 'attention' | 'ai' | 'edited' | 'all';

export interface QaFinding {
  type: QaType;
  msg: string;
  /** glossary findings: the offending term and its expected/actual translation */
  term?: string;
  expected?: string;
  found?: string;
}

export interface TableHead {
  cols: string[];
  src: string;
  tgt: string;
}

export interface Segment {
  id: string;
  kind: SegKind;
  prov: Provenance;
  approved: boolean;
  src: string;
  tgt: string;
  finding?: QaFinding;
  /** trow only: table id groups consecutive rows into one rendered table */
  table?: string;
  /** trow only: set on the first row of a table */
  head?: TableHead;
  /** trow only: note reference shown after the label */
  note?: string;
  /** trow only: locked numeric cells */
  nums?: string[];
  bold?: boolean;
}

export interface SectionMeta {
  id: string;
  title: string;
  /** total segments in the section (drives rollups; more than we render) */
  n: number;
  /** tables in the section */
  t?: number;
  /** seeded needs-attention / fresh-AI counts for generated sections */
  att?: number;
  ai?: number;
}

export interface Chapter {
  id: string;
  title: string;
  sections: SectionMeta[];
}

export interface DocItem {
  id: string;
  name: string;
  status: DocStatus;
  targets: string[];
  progress: number;
  pages: number;
  words: number;
  activity: string;
  owner: string;
  tm?: number;
  active?: boolean;
  /** document finished QA with zero findings */
  clear?: boolean;
}

export interface StatusMeta {
  label: string;
  dot: string;
}

export interface ProvMeta {
  label: string;
  color: string;
  bg: string;
  hint: string;
}

export interface QaMeta {
  label: string;
  level: 'critical' | 'warn' | 'info';
  color: string;
  icon: string;
}

/* Document-level statuses — consumed by the status badge */
export const STATUS_META: Record<DocStatus, StatusMeta> = {
  parsing: {label: 'Parsing', dot: 'var(--text-s)'},
  translating: {label: 'Translating', dot: '#7C8BB0'},
  review: {label: 'In review', dot: '#D99A40'},
  approved: {label: 'Approved', dot: '#7AAE88'},
  exported: {label: 'Exported', dot: '#7AAE88'},
  failed: {label: 'Failed', dot: '#C77'},
  draft: {label: 'Draft', dot: 'var(--text-s)'},
};

/* Provenance badges */
export const PROV_META: Record<string, ProvMeta> = {
  tm: {
    label: 'TM',
    color: '#7AAE88',
    bg: 'rgba(122,174,136,.14)',
    hint: 'Reused from approved translation memory',
  },
  ai: {
    label: 'AI',
    color: '#7C8BB0',
    bg: 'rgba(124,139,176,.14)',
    hint: 'Machine translated — not yet reviewed',
  },
  edited: {
    label: 'Edited',
    color: '#C29445',
    bg: 'rgba(194,148,69,.14)',
    hint: 'Human edited',
  },
  attention: {
    label: 'Needs attention',
    color: '#C77',
    bg: 'rgba(204,119,119,.12)',
    hint: 'QA finding or low confidence',
  },
  approved: {
    label: 'Approved',
    color: '#7AAE88',
    bg: 'transparent',
    hint: 'Approved',
  },
  locked: {
    label: 'Locked',
    color: 'var(--text-s)',
    bg: 'var(--surface)',
    hint: 'Numeric — never edited, never AI-touched',
  },
};

export const QA_META: Record<QaType, QaMeta> = {
  number: {
    label: 'Number mismatch',
    level: 'critical',
    color: '#C77',
    icon: '≠',
  },
  glossary: {
    label: 'Glossary inconsistency',
    level: 'warn',
    color: '#C29445',
    icon: '§',
  },
  dnt: {label: 'Do-not-translate', level: 'warn', color: '#C29445', icon: '✕'},
  length: {
    label: 'Length expansion',
    level: 'info',
    color: '#7C8BB0',
    icon: '↔',
  },
};

/* Target languages (same 15-market list as briefings, English labels) */
export const DOC_TARGETS: Array<{code: string; label: string}> = [
  {code: 'NL', label: 'Dutch'},
  {code: 'DE', label: 'German'},
  {code: 'FR', label: 'French'},
  {code: 'UK', label: 'English (UK)'},
  {code: 'BENL', label: 'Dutch (BE)'},
  {code: 'BEFR', label: 'French (BE)'},
  {code: 'LU', label: 'French (LU)'},
  {code: 'CHFR', label: 'French (CH)'},
  {code: 'CHDE', label: 'German (CH)'},
  {code: 'AT', label: 'German (AT)'},
  {code: 'DK', label: 'Danish'},
  {code: 'ES', label: 'Spanish'},
  {code: 'SE', label: 'Swedish'},
  {code: 'NO', label: 'Norwegian'},
];

/* ── Document tree — real outline of the FY2025-26 report ──
   t = tables in section · n = segment count (drives rollups)
   att/ai seeded into generated sections via meta               */
export const TREE: Chapter[] = [
  {
    id: 'ch1',
    title: '1 · Management Board Report',
    sections: [
      {id: '1.1', title: 'General information', n: 24, att: 2, ai: 3},
      {id: '1.2', title: 'Financial performance', n: 38, att: 0, ai: 4},
      {id: '1.3', title: 'Environmental and social', n: 46, att: 1, ai: 6},
      {id: '1.4', title: 'Key figures', n: 18, t: 3, att: 0, ai: 0},
      {id: '1.5', title: 'Segment review', n: 22, t: 2, att: 1, ai: 2},
    ],
  },
  {
    id: 'ch2',
    title: '2 · Consolidated Financial Statements',
    sections: [
      {
        id: '2.1',
        title: 'Statement of profit or loss',
        n: 16,
        t: 1,
        att: 0,
        ai: 1,
      },
      {
        id: '2.2',
        title: 'Other comprehensive income',
        n: 14,
        t: 1,
        att: 0,
        ai: 0,
      },
      {
        id: '2.3',
        title: 'Statement of financial position',
        n: 28,
        t: 1,
        att: 0,
        ai: 0,
      },
      {id: '2.4', title: 'Changes in equity', n: 12, t: 1, att: 0, ai: 0},
      {id: '2.5', title: 'Statement of cash flows', n: 24, t: 1, att: 0, ai: 0},
    ],
  },
  {
    id: 'ch2n',
    title: 'Notes to the consolidated statements',
    sections: [
      {
        id: '2.7',
        title: 'Adoption of new and revised IFRS',
        n: 21,
        att: 0,
        ai: 0,
      },
      {id: '2.8', title: 'Material accounting policies', n: 118, att: 0, ai: 8},
      {
        id: '2.9',
        title: 'Critical accounting judgements',
        n: 34,
        att: 1,
        ai: 3,
      },
      {id: '2.10', title: 'Operating segments', n: 42, t: 4, att: 0, ai: 0},
      {id: '2.11', title: 'Revenue', n: 19, t: 2, att: 0, ai: 0},
      {id: '2.12', title: 'Expenses by nature', n: 14, t: 1, att: 0, ai: 0},
      {
        id: '2.13',
        title: 'Salaries and pension expenses',
        n: 16,
        t: 1,
        att: 0,
        ai: 0,
      },
      {
        id: '2.14',
        title: 'Amortisation, depreciation and impairment',
        n: 12,
        t: 1,
        att: 1,
        ai: 1,
      },
      {id: '2.15', title: 'Number of employees', n: 8, t: 1, att: 0, ai: 0},
      {
        id: '2.16',
        title: 'Financial income and expenses',
        n: 13,
        t: 1,
        att: 0,
        ai: 0,
      },
      {id: '2.17', title: 'Income taxes', n: 36, t: 3, att: 0, ai: 2},
      {id: '2.18', title: 'Intangible assets', n: 26, t: 2, att: 0, ai: 0},
      {id: '2.19', title: 'Right-of-use assets', n: 44, t: 3, att: 3, ai: 2},
      {
        id: '2.20',
        title: 'Property, plant and equipment',
        n: 31,
        t: 2,
        att: 0,
        ai: 0,
      },
      {id: '2.21', title: 'Other financial assets', n: 12, t: 1, att: 0, ai: 0},
      {id: '2.22', title: 'Inventories', n: 9, t: 1, att: 0, ai: 1},
      {
        id: '2.23',
        title: 'Trade and other receivables',
        n: 14,
        t: 1,
        att: 0,
        ai: 0,
      },
      {
        id: '2.24',
        title: 'Cash and cash equivalents',
        n: 7,
        t: 1,
        att: 0,
        ai: 0,
      },
      {id: '2.25', title: 'Financial liabilities', n: 29, t: 2, att: 0, ai: 3},
      {id: '2.26', title: 'Lease liabilities', n: 18, t: 1, att: 0, ai: 0},
      {
        id: '2.27',
        title: 'Pensions and employee benefits',
        n: 33,
        t: 2,
        att: 1,
        ai: 2,
      },
      {id: '2.28', title: 'Other provisions', n: 17, t: 1, att: 0, ai: 0},
      {
        id: '2.29',
        title: 'Trade and other payables',
        n: 9,
        t: 1,
        att: 0,
        ai: 0,
      },
      {
        id: '2.30',
        title: 'Other current financial liabilities',
        n: 8,
        t: 1,
        att: 0,
        ai: 0,
      },
      {
        id: '2.31',
        title: 'Financial instruments and risks',
        n: 52,
        t: 4,
        att: 2,
        ai: 4,
      },
      {
        id: '2.32',
        title: 'Remuneration of the Management Board',
        n: 11,
        t: 1,
        att: 0,
        ai: 0,
      },
      {
        id: '2.33',
        title: 'Off-balance sheet commitments',
        n: 10,
        att: 0,
        ai: 0,
      },
      {
        id: '2.34',
        title: 'Related party transactions',
        n: 13,
        t: 1,
        att: 0,
        ai: 0,
      },
      {
        id: '2.35',
        title: 'Events after the balance sheet date',
        n: 6,
        att: 0,
        ai: 1,
      },
    ],
  },
  {
    id: 'ch3',
    title: '3 · Company Only Financial Statements',
    sections: [
      {
        id: '3.1',
        title: 'Company statement of profit or loss',
        n: 9,
        t: 1,
        att: 0,
        ai: 0,
      },
      {
        id: '3.2',
        title: 'Company statement of financial position',
        n: 16,
        t: 1,
        att: 0,
        ai: 0,
      },
      {
        id: '3.3',
        title: 'Notes to the company statements',
        n: 64,
        t: 6,
        att: 0,
        ai: 5,
      },
      {id: '3.7', title: 'Other information', n: 12, att: 0, ai: 0},
    ],
  },
];

export const ALL_SECTIONS: SectionMeta[] = TREE.flatMap(c => c.sections);
export const sectionById = (id: string): SectionMeta | undefined =>
  ALL_SECTIONS.find(s => s.id === id);

export const DOC_TOTALS = {
  pages: 103,
  words: 23412,
  tables: 74,
  numbers: 2913,
  segments: ALL_SECTIONS.reduce((a, s) => a + s.n, 0),
};

/* ── Authored segments (verbatim from the report) ── */
const SECTION_SEGS: Record<string, Segment[]> = {
  '1.1': [
    {
      id: 's11-1',
      kind: 'h1',
      prov: 'tm',
      approved: true,
      src: '1.1 General information',
      tgt: '1.1 Algemene informatie',
    },
    {
      id: 's11-2',
      kind: 'h2',
      prov: 'tm',
      approved: true,
      src: 'BRAND & MISSION',
      tgt: 'MERK & MISSIE',
    },
    {
      id: 's11-3',
      kind: 'p',
      prov: 'ai',
      approved: false,
      src: 'Hunkemöller is a leading European brand with more than 700 stores across 20 countries, supported by a strong and ever-growing digital presence.',
      tgt: 'Hunkemöller is een toonaangevend Europees merk met meer dan 700 winkels in 20 landen, ondersteund door een sterke en steeds groeiende digitale aanwezigheid.',
    },
    {
      id: 's11-4',
      kind: 'p',
      prov: 'ai',
      approved: false,
      src: 'Founded in Amsterdam in 1886, we have evolved from a traditional retailer into a brand dedicated to understanding every mood, moment, and occasion in a woman’s life.',
      tgt: 'Opgericht in Amsterdam in 1886 zijn wij geëvolueerd van een traditionele retailer naar een merk dat elke stemming, elk moment en elke gelegenheid in het leven van een vrouw wil begrijpen.',
    },
    {
      id: 's11-5',
      kind: 'p',
      prov: 'edited',
      approved: false,
      src: 'Because one woman is many women.',
      tgt: 'Want één vrouw is vele vrouwen.',
    },
    {
      id: 's11-6',
      kind: 'p',
      prov: 'tm',
      approved: true,
      src: 'Across our stores, our trained experts provide personalised fittings, tailored advice, and deep product knowledge.',
      tgt: 'In onze winkels bieden onze getrainde experts persoonlijke pasadviezen, advies op maat en diepgaande productkennis.',
    },
    {
      id: 's11-7',
      kind: 'p',
      prov: 'ai',
      approved: false,
      src: 'In 2024, we strengthened this direction with our refreshed brand message, For Every Woman In You, that came to full fruition in campaigns throughout 2025.',
      tgt: 'In 2024 versterkten wij deze richting met onze vernieuwde merkboodschap, Voor Elke Vrouw In Jou, die in campagnes gedurende 2025 volledig tot wasdom kwam.',
      finding: {
        type: 'dnt',
        msg: '“For Every Woman In You” is on the do-not-translate list but was translated as “Voor Elke Vrouw In Jou”.',
      },
    },
    {
      id: 's11-8',
      kind: 'h2',
      prov: 'tm',
      approved: true,
      src: 'CEO STATEMENT',
      tgt: 'VERKLARING VAN DE CEO',
    },
    {
      id: 's11-9',
      kind: 'p',
      prov: 'ai',
      approved: false,
      src: 'Throughout the past year, the retail landscape remained fast-moving and demanding, shaped by persistent macroeconomic pressures, shifting customer behavior, and ongoing supply chain complexities.',
      tgt: 'Het afgelopen jaar bleef het retaillandschap snel veranderen en veeleisend, gevormd door aanhoudende macro-economische druk, verschuivend klantgedrag en voortdurende complexiteit in de toeleveringsketen, waarbij wij onze koers desondanks met overtuiging en discipline hebben vastgehouden.',
      finding: {
        type: 'length',
        msg: 'Target is 41% longer than source — may affect layout of the two-column CEO page.',
      },
    },
    {
      id: 's11-10',
      kind: 'p',
      prov: 'tm',
      approved: true,
      src: 'We completed a restructuring of existing debt alongside new capital investment in early March 2025.',
      tgt: 'Begin maart 2025 hebben wij een herstructurering van bestaande schulden afgerond, samen met nieuwe kapitaalinvesteringen.',
    },
    {
      id: 's11-11',
      kind: 'p',
      prov: 'tm',
      approved: true,
      src: 'I am grateful to our teams for their resilience and commitment, and to our partners and shareholder for their continued support.',
      tgt: 'Ik ben onze teams dankbaar voor hun veerkracht en toewijding, en onze partners en aandeelhouder voor hun voortdurende steun.',
    },
  ],
  '2.1': [
    {
      id: 's21-1',
      kind: 'h1',
      prov: 'tm',
      approved: true,
      src: '2.1 Consolidated statement of profit or loss for the fiscal period ended January 31, 2026',
      tgt: '2.1 Geconsolideerde winst-en-verliesrekening over de verslagperiode eindigend op 31 januari 2026',
    },
    {
      id: 's21-2',
      kind: 'trow',
      table: 'pl',
      head: {
        cols: [
          'Notes',
          'FY Feb 1, 2025 – Jan 31, 2026',
          'FY Feb 1, 2024 – Jan 31, 2025',
        ],
        src: '€ in thousands',
        tgt: '€ × 1.000',
      },
      prov: 'tm',
      approved: true,
      src: 'Revenue',
      tgt: 'Omzet',
      note: '2.11',
      nums: ['452,720', '474,348'],
    },
    {
      id: 's21-3',
      kind: 'trow',
      table: 'pl',
      prov: 'tm',
      approved: true,
      src: 'Cost of sales',
      tgt: 'Kostprijs van de omzet',
      nums: ['(123,470)', '(129,552)'],
    },
    {
      id: 's21-4',
      kind: 'trow',
      table: 'pl',
      prov: 'tm',
      approved: true,
      bold: true,
      src: 'Gross profit',
      tgt: 'Brutowinst',
      nums: ['329,250', '344,796'],
    },
    {
      id: 's21-5',
      kind: 'trow',
      table: 'pl',
      prov: 'tm',
      approved: true,
      src: 'Selling expenses',
      tgt: 'Verkoopkosten',
      note: '2.12/13',
      nums: ['(210,823)', '(205,162)'],
    },
    {
      id: 's21-6',
      kind: 'trow',
      table: 'pl',
      prov: 'tm',
      approved: true,
      src: 'General and administrative expenses',
      tgt: 'Algemene en beheerskosten',
      note: '2.12/13',
      nums: ['(89,870)', '(63,600)'],
    },
    {
      id: 's21-7',
      kind: 'trow',
      table: 'pl',
      prov: 'tm',
      approved: true,
      src: 'Depreciation, Amortisation, Impairment',
      tgt: 'Afschrijvingen, amortisatie en bijzondere waardeverminderingen',
      note: '2.14',
      nums: ['(75,072)', '(137,473)'],
    },
    {
      id: 's21-8',
      kind: 'trow',
      table: 'pl',
      prov: 'tm',
      approved: true,
      src: 'Financial income',
      tgt: 'Financiële baten',
      note: '2.16',
      nums: ['1,419', '1,846'],
    },
    {
      id: 's21-9',
      kind: 'trow',
      table: 'pl',
      prov: 'ai',
      approved: false,
      src: 'Interest accretion to lease liability',
      tgt: 'Rente-aangroei op leaseverplichtingen',
      note: '2.16',
      nums: ['(11,988)', '(14,375)'],
    },
    {
      id: 's21-10',
      kind: 'trow',
      table: 'pl',
      prov: 'tm',
      approved: true,
      src: 'Financial expenses',
      tgt: 'Financiële lasten',
      note: '2.16',
      nums: ['(26,263)', '(39,004)'],
    },
    {
      id: 's21-11',
      kind: 'trow',
      table: 'pl',
      prov: 'tm',
      approved: true,
      bold: true,
      src: 'Loss before tax',
      tgt: 'Verlies vóór belastingen',
      nums: ['(83,347)', '(112,972)'],
    },
    {
      id: 's21-12',
      kind: 'trow',
      table: 'pl',
      prov: 'tm',
      approved: true,
      src: 'Income tax income/(expense)',
      tgt: 'Belastingbate/(-last)',
      note: '2.17',
      nums: ['127', '(4,805)'],
    },
    {
      id: 's21-13',
      kind: 'trow',
      table: 'pl',
      prov: 'tm',
      approved: true,
      bold: true,
      src: 'Loss for the fiscal period',
      tgt: 'Verlies over de verslagperiode',
      nums: ['(83,220)', '(117,778)'],
    },
    {
      id: 's21-14',
      kind: 'p',
      prov: 'tm',
      approved: true,
      src: 'Loss for the fiscal period attributable to: Owners of the Company.',
      tgt: 'Verlies over de verslagperiode toe te rekenen aan: eigenaren van de vennootschap.',
    },
  ],
  '2.19': [
    {
      id: 's219-1',
      kind: 'h1',
      prov: 'tm',
      approved: true,
      src: '2.19 Right-of-use assets',
      tgt: '2.19 Gebruiksrechten op activa',
    },
    {
      id: 's219-2',
      kind: 'trow',
      table: 'rou',
      head: {
        cols: ['Properties', 'Cars', 'Total'],
        src: '€ in thousands',
        tgt: '€ × 1.000',
      },
      prov: 'tm',
      approved: true,
      src: 'Book value as of February 1, 2025',
      tgt: 'Boekwaarde per 1 februari 2025',
      nums: ['186,762', '2,330', '189,092'],
    },
    {
      id: 's219-3',
      kind: 'trow',
      table: 'rou',
      prov: 'tm',
      approved: true,
      src: 'Additions',
      tgt: 'Investeringen',
      nums: ['9,223', '973', '10,196'],
    },
    {
      id: 's219-4',
      kind: 'trow',
      table: 'rou',
      prov: 'ai',
      approved: false,
      src: 'Reassessments and modifications',
      tgt: 'Herbeoordelingen en wijzigingen',
      nums: ['16,651', '(120)', '16,531'],
    },
    {
      id: 's219-5',
      kind: 'trow',
      table: 'rou',
      prov: 'tm',
      approved: true,
      src: 'Depreciation',
      tgt: 'Afschrijvingen',
      nums: ['(52,017)', '(964)', '(52,981)'],
    },
    {
      id: 's219-6',
      kind: 'trow',
      table: 'rou',
      prov: 'ai',
      approved: false,
      src: 'Disposed impairments due to closed stores',
      tgt: 'Vrijgevallen waardeverminderingen door gesloten winkels',
      nums: ['10,808', '–', '10,808'],
      finding: {
        type: 'glossary',
        msg: 'Glossary: “impairment” → “bijzondere waardevermindering”. Translation uses “waardevermindering”.',
        term: 'impairment',
        expected: 'bijzondere waardevermindering',
        found: 'waardevermindering',
      },
    },
    {
      id: 's219-7',
      kind: 'trow',
      table: 'rou',
      prov: 'tm',
      approved: true,
      src: 'Impairment',
      tgt: 'Bijzondere waardevermindering',
      nums: ['(8,481)', '–', '(8,481)'],
    },
    {
      id: 's219-8',
      kind: 'trow',
      table: 'rou',
      prov: 'tm',
      approved: true,
      src: 'Effect of foreign currency exchange differences',
      tgt: 'Effect van valutakoersverschillen',
      nums: ['540', '10', '549'],
    },
    {
      id: 's219-9',
      kind: 'trow',
      table: 'rou',
      prov: 'tm',
      approved: true,
      src: 'Lease incentive',
      tgt: 'Lease-incentive',
      nums: ['(605)', '–', '(605)'],
    },
    {
      id: 's219-10',
      kind: 'trow',
      table: 'rou',
      prov: 'tm',
      approved: true,
      bold: true,
      src: 'Book value as of January 31, 2026',
      tgt: 'Boekwaarde per 31 januari 2026',
      nums: ['162,881', '2,229', '165,110'],
    },
    {
      id: 's219-11',
      kind: 'p',
      prov: 'ai',
      approved: false,
      src: 'The Group has assessed its Logistics Services Agreement with GXO and concluded that it does not contain a lease within the scope of IFRS 16. The significant judgements applied are disclosed in Note 2.9.',
      tgt: 'De Groep heeft haar Logistics Services Agreement met GXO beoordeeld en geconcludeerd dat deze geen lease bevat binnen de reikwijdte van IFRS 16. De belangrijkste oordeelsvormingen zijn toegelicht in noot 2.9.',
    },
    {
      id: 's219-12',
      kind: 'p',
      prov: 'tm',
      approved: true,
      src: 'To determine the incremental borrowing rate, the Company uses a build-up approach that starts with a risk-free interest rate adjusted for credit risk for leases held by the Company.',
      tgt: 'Voor het bepalen van de marginale rentevoet hanteert de vennootschap een opbouwbenadering die start met een risicovrije rentevoet, gecorrigeerd voor kredietrisico voor door de vennootschap gehouden leases.',
    },
    {
      id: 's219-13',
      kind: 'h2',
      prov: 'tm',
      approved: true,
      src: 'Impairment testing',
      tgt: 'Toetsing op bijzondere waardevermindering',
    },
    {
      id: 's219-14',
      kind: 'p',
      prov: 'tm',
      approved: true,
      src: 'The determination of the recoverable amount of these tangible fixed assets is based on a Value in Use (“VIU”) valuation, based on a discounted cash flow forecast of the remaining contractual rental period of the stores.',
      tgt: 'De bepaling van de realiseerbare waarde van deze materiële vaste activa is gebaseerd op een bedrijfswaardeberekening (“VIU”), op basis van een verdisconteerde kasstroomprognose over de resterende contractuele huurperiode van de winkels.',
    },
    {
      id: 's219-15',
      kind: 'p',
      prov: 'ai',
      approved: false,
      src: 'Discount rate: 11.5% – 13.5% and pre-tax rate 12.5% – 13.5%.',
      tgt: 'Disconteringsvoet: 11,5% – 13,5% en vóór belastingen 12,5% – 13,5%.',
    },
    {
      id: 's219-16',
      kind: 'p',
      prov: 'ai',
      approved: false,
      src: 'A total impairment loss of € 8.5 million.',
      tgt: 'Een totaal bijzonder waardeverminderingsverlies van € 85 miljoen.',
      finding: {
        type: 'number',
        msg: 'Source says € 8.5 million; translation says € 85 miljoen. Numbers must match the source exactly.',
      },
    },
  ],
  '2.22': [
    {
      id: 's222-1',
      kind: 'h1',
      prov: 'tm',
      approved: true,
      src: '2.22 Inventories',
      tgt: '2.22 Voorraden',
    },
    {
      id: 's222-2',
      kind: 'trow',
      table: 'inv',
      head: {
        cols: ['January 31, 2026', 'January 31, 2025'],
        src: '€ in thousands',
        tgt: '€ × 1.000',
      },
      prov: 'tm',
      approved: true,
      src: 'Finished products and merchandise inventories',
      tgt: 'Gereed product en handelsvoorraden',
      nums: ['67,882', '64,577'],
    },
    {
      id: 's222-3',
      kind: 'p',
      prov: 'ai',
      approved: false,
      src: 'The quality of the inventory improved, as reflected in a better aging profile.',
      tgt: 'De kwaliteit van de voorraad is verbeterd, wat tot uiting komt in een beter verouderingsprofiel.',
    },
  ],
};

/* ── Generic segment pool for non-authored sections ── */
const POOL: Array<[string, string]> = [
  [
    'The accounting policies set out below have been applied consistently to all periods presented in these consolidated financial statements.',
    'De hieronder uiteengezette grondslagen zijn consistent toegepast op alle in deze geconsolideerde jaarrekening gepresenteerde perioden.',
  ],
  [
    'Amounts are presented in thousands of euros, unless stated otherwise.',
    'Bedragen luiden in duizenden euro’s, tenzij anders vermeld.',
  ],
  [
    'The Group has applied all IFRS standards and interpretations as adopted by the European Union effective for the reporting period.',
    'De Groep heeft alle door de Europese Unie goedgekeurde IFRS-standaarden en interpretaties toegepast die van kracht zijn voor de verslagperiode.',
  ],
  [
    'Management has assessed the carrying amount of the related assets and liabilities as at the reporting date.',
    'Het management heeft de boekwaarde van de betreffende activa en verplichtingen per verslagdatum beoordeeld.',
  ],
  [
    'Reference is made to Note 2.9 for the significant judgements and estimates applied.',
    'Verwezen wordt naar noot 2.9 voor de belangrijkste oordeelsvormingen en schattingen.',
  ],
  [
    'The comparative figures have been reclassified where necessary to conform with the current period presentation.',
    'De vergelijkende cijfers zijn waar nodig geherrubriceerd om aan te sluiten bij de presentatie van de huidige periode.',
  ],
  [
    'No material events occurred that would require adjustment of these amounts.',
    'Er hebben zich geen materiële gebeurtenissen voorgedaan die aanpassing van deze bedragen vereisen.',
  ],
  [
    'The Group monitors these positions on a monthly basis as part of its internal reporting cycle.',
    'De Groep monitort deze posities maandelijks als onderdeel van haar interne rapportagecyclus.',
  ],
];

function buildSegs(meta: SectionMeta): Segment[] {
  const authored = SECTION_SEGS[meta.id];
  if (authored) {
    return authored.map(s => ({
      ...s,
      finding: s.finding ? {...s.finding} : undefined,
    }));
  }
  const shown = Math.min(meta.n, 28);
  const segs: Segment[] = [
    {
      id: `g${meta.id}-0`,
      kind: 'h1',
      prov: 'tm',
      approved: true,
      src: `${meta.id} ${meta.title}`,
      tgt: `${meta.id} ${meta.title}`,
    },
  ];
  let ai = meta.ai || 0;
  let att = meta.att || 0;
  for (let i = 1; i < shown; i++) {
    const [src, tgt] = POOL[(i + meta.id.length * 3) % POOL.length];
    const seg: Segment = {
      id: `g${meta.id}-${i}`,
      kind: 'p',
      prov: 'tm',
      approved: true,
      src,
      tgt,
    };
    if (att > 0) {
      att--;
      seg.prov = 'ai';
      seg.approved = false;
      seg.finding = {
        type: 'glossary',
        msg: 'Low-confidence match — review the applied terminology.',
      };
    } else if (ai > 0) {
      ai--;
      seg.prov = 'ai';
      seg.approved = false;
    }
    segs.push(seg);
  }
  return segs;
}

/** Fresh, mutable segment state for a whole document. */
export function buildInitialSegs(): {
  segs: Record<string, Segment[]>;
  more: Record<string, number>;
} {
  const segs: Record<string, Segment[]> = {};
  const more: Record<string, number> = {};
  ALL_SECTIONS.forEach(meta => {
    const list = buildSegs(meta);
    segs[meta.id] = list;
    more[meta.id] = Math.max(0, meta.n - list.length);
  });
  return {segs, more};
}

/* ── Financial glossary + shared do-not-translate list ── */
export interface GlossaryRow {
  en: string;
  nl: string;
  de: string;
}

export const GLOSSARY_FIN: GlossaryRow[] = [
  {en: 'impairment', nl: 'bijzondere waardevermindering', de: 'Wertminderung'},
  {en: 'fair value', nl: 'reële waarde', de: 'beizulegender Zeitwert'},
  {
    en: 'right-of-use assets',
    nl: 'gebruiksrechten op activa',
    de: 'Nutzungsrechte',
  },
  {
    en: 'lease liability',
    nl: 'leaseverplichting',
    de: 'Leasingverbindlichkeit',
  },
  {en: 'revenue', nl: 'omzet', de: 'Umsatzerlöse'},
  {en: 'inventories', nl: 'voorraden', de: 'Vorräte'},
  {en: 'equity', nl: 'eigen vermogen', de: 'Eigenkapital'},
  {en: 'deferred tax', nl: 'uitgestelde belastingen', de: 'latente Steuern'},
  {
    en: 'incremental borrowing rate',
    nl: 'marginale rentevoet',
    de: 'Grenzfremdkapitalzinssatz',
  },
  {
    en: 'recoverable amount',
    nl: 'realiseerbare waarde',
    de: 'erzielbarer Betrag',
  },
  {
    en: 'cash-generating unit',
    nl: 'kasstroomgenererende eenheid',
    de: 'zahlungsmittelgenerierende Einheit',
  },
  {en: 'goodwill', nl: 'goodwill', de: 'Goodwill'},
];

export const GLOSSARY_MKT: GlossaryRow[] = [
  {en: 'everyday favourite', nl: 'alledaagse favoriet', de: 'Alltagsliebling'},
  {en: 'Effortless support', nl: 'Moeiteloze support', de: 'Müheloser Halt'},
  {en: 'Shop the collection', nl: 'Shop de collectie', de: 'Zur Kollektion'},
  {en: 'breathable silk', nl: 'ademende zijde', de: 'atmungsaktive Seide'},
];

export const DNT_LIST: string[] = [
  'For Every Woman In You',
  'Together Tomorrow',
  'My Hunkemöller',
  'Hunkemöller International B.V.',
  'Shero Holdco B.V.',
  'IFRS 16',
  'EBITDA',
  'GXO',
  'JD Logistics',
  'Value in Use',
];

/* ── Documents library ── */
export const DOC_LIBRARY: DocItem[] = [
  {
    id: 'd1',
    name: 'Annual Report FY2025-26.docx',
    status: 'review',
    targets: ['NL', 'DE'],
    progress: 96,
    pages: 103,
    words: 23412,
    activity: 'today, 11:32',
    owner: 'Marieke (Finance)',
    tm: 1847,
    active: true,
  },
  {
    id: 'd0',
    name: 'Annual Report FY2024-25.docx',
    status: 'exported',
    targets: ['NL'],
    progress: 100,
    pages: 98,
    words: 22108,
    activity: 'Jun 2025',
    owner: 'Marieke (Finance)',
    clear: true,
  },
  {
    id: 'd2',
    name: 'Half-year Update H1 FY2025.docx',
    status: 'approved',
    targets: ['NL', 'DE', 'FR'],
    progress: 100,
    pages: 34,
    words: 8210,
    activity: 'Sep 2025',
    owner: 'Joost (Comms)',
  },
];
