/**
 * Copyright 2026 Google LLC — Licensed under the Apache License, Version 2.0.
 * Hunkemöller "Documents" — view model and presentation metadata.
 *
 * The document data itself comes from the API (see
 * document-translations.service.ts); what lives here is the shape the review
 * workspace renders, and the labels and colours it renders it with.
 */

/** Job statuses, as the API reports them. */
export type DocStatus =
  | 'uploaded'
  | 'translating'
  | 'review'
  | 'completed'
  | 'failed';
export type Provenance = 'tm' | 'ai' | 'edited';
export type QaType = 'number' | 'glossary' | 'dnt' | 'length';
export type SegKind = 'h1' | 'h2' | 'p' | 'trow';
export type RunState = 'queued' | 'run' | 'done' | 'fail';
export type ReviewFilter = 'attention' | 'ai' | 'edited' | 'all';

export interface QaFinding {
  type: QaType;
  msg: string;
  /** The API decides what blocks an export: `error` does, `warning` does not. */
  severity?: 'error' | 'warning';
  /** glossary/dnt findings: the offending term and its expected translation */
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
  /** The parser's segment index as a string — the id the segment routes take. */
  id: string;
  kind: SegKind;
  prov: Provenance;
  approved: boolean;
  src: string;
  tgt: string;
  finding?: QaFinding;
  /** trow only: groups consecutive rows into one rendered table */
  table?: string;
  /** trow only: column headings, when the document gives us any */
  head?: TableHead;
  /** trow only: note reference shown after the label */
  note?: string;
  /** trow only: locked figure cells, verified against the source */
  nums?: string[];
  bold?: boolean;
}

export interface SectionMeta {
  id: string;
  title: string;
  /** translatable segments in the section — what review progress counts */
  n: number;
  /** tables in the section */
  t?: number;
}

export interface Chapter {
  id: string;
  title: string;
  sections: SectionMeta[];
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

export const STATUS_META: Record<DocStatus, StatusMeta> = {
  uploaded: {label: 'Parsed', dot: 'var(--text-s)'},
  translating: {label: 'Translating', dot: '#7C8BB0'},
  review: {label: 'In review', dot: '#D99A40'},
  completed: {label: 'Exported', dot: '#7AAE88'},
  failed: {label: 'Failed', dot: '#C77'},
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

/**
 * `level` drives the icon and colour. Whether a finding blocks the export comes
 * from the API's severity, not from here — the checks own that call.
 */
export const QA_META: Record<QaType, QaMeta> = {
  number: {
    label: 'Number mismatch',
    level: 'critical',
    color: '#C77',
    icon: '≠',
  },
  dnt: {label: 'Do-not-translate', level: 'critical', color: '#C77', icon: '✕'},
  glossary: {
    label: 'Glossary inconsistency',
    level: 'warn',
    color: '#C29445',
    icon: '§',
  },
  length: {
    label: 'Length expansion',
    level: 'info',
    color: '#7C8BB0',
    icon: '↔',
  },
};

/** Target markets, matching the backend's market codes. */
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

/**
 * What the notation toggle produces, per market — "319,915.00 · January 31,
 * 2026" as that market writes it. Generated from the backend's
 * `locale_format._FORMATS`, which decides the real thing at export; a market
 * missing here (UK) reads the source notation and needs no renotation.
 */
export const NOTATION_SAMPLES: Record<string, string> = {
  NL: '319.915,00 · 31 januari 2026',
  BENL: '319.915,00 · 31 januari 2026',
  DE: '319.915,00 · 31. Januar 2026',
  AT: '319.915,00 · 31. Januar 2026',
  CHDE: "319'915.00 · 31. Januar 2026",
  CHFR: "319'915.00 · 31 janvier 2026",
  FR: '319\u00A0915,00 · 31 janvier 2026',
  BEFR: '319\u00A0915,00 · 31 janvier 2026',
  LU: '319\u00A0915,00 · 31 janvier 2026',
  DK: '319.915,00 · 31. januar 2026',
  ES: '319.915,00 · 31 de enero de 2026',
  SE: '319\u00A0915,00 · 31 januari 2026',
  NO: '319\u00A0915,00 · 31. januar 2026',
};

export function marketLabel(code: string | null | undefined): string {
  if (!code) return '';
  return DOC_TARGETS.find(t => t.code === code)?.label || code;
}

/* ── Terminology used for highlighting in the review workspace ──
   The QA checks run server-side against the stored glossary; these lists only
   decide what gets underlined on screen. */
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
