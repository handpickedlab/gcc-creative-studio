/**
 * Copyright 2026 Google LLC — Licensed under the Apache License, Version 2.0.
 * Translates the document-translation API into the review workspace's view
 * model.
 *
 * Two shapes have to meet here. The parser emits one segment per paragraph or
 * table cell, tagged `heading | prose | table_label | numeric | skip` and
 * carrying its table/row position. The workspace renders prose rows and whole
 * tables, where a table row is one translatable label plus its locked figure
 * cells. Folding the figures into their row is what this module is for.
 */

import {
  ApiJob,
  ApiOutlineChapter,
  ApiSegment,
  ApiFinding,
} from './document-translations.service';
import {
  Chapter,
  QaFinding,
  QaType,
  Segment,
  SectionMeta,
} from './documents.data';

const QA_TYPES: QaType[] = ['number', 'glossary', 'dnt', 'length'];

/** Falls back to `glossary` for a check this UI does not know about yet. */
function qaType(raw: string): QaType {
  return (QA_TYPES as string[]).includes(raw) ? (raw as QaType) : 'glossary';
}

export function findingFrom(api?: ApiFinding | null): QaFinding | undefined {
  if (!api) return undefined;
  return {
    type: qaType(api.type),
    msg: api.msg,
    severity: api.severity,
    term: api.term ?? undefined,
    expected: api.expected ?? undefined,
    found: api.found ?? undefined,
  };
}

/**
 * The review outline, two levels deep. `n` counts translatable segments only —
 * locked figure cells are never open for review, so counting them would leave
 * every section permanently short of done.
 */
export function chaptersFrom(job: ApiJob | null): Chapter[] {
  const raw: ApiOutlineChapter[] = job?.stats?.chapters ?? [];
  return raw.map(ch => ({
    id: ch.id || ch.title,
    title: ch.title,
    sections: ch.sections.map(
      (s): SectionMeta => ({
        id: s.id,
        title: s.title,
        n: s.translatable,
        t: s.tables || undefined,
      }),
    ),
  }));
}

export function allSectionsOf(chapters: Chapter[]): SectionMeta[] {
  return chapters.flatMap(c => c.sections);
}

function kindOf(api: ApiSegment): Segment['kind'] {
  if (api.kind === 'heading') return (api.headingLevel ?? 1) <= 1 ? 'h1' : 'h2';
  if (api.kind === 'table_label') return 'trow';
  return 'p';
}

function provOf(api: ApiSegment): Segment['prov'] {
  return api.provenance ?? 'ai';
}

function baseSegment(api: ApiSegment): Segment {
  return {
    id: String(api.segIndex),
    kind: kindOf(api),
    prov: provOf(api),
    approved: api.status === 'approved',
    src: api.sourceText,
    tgt: api.translation ?? '',
    finding: findingFrom(api.finding),
    bold: api.bold || undefined,
  };
}

/**
 * Builds the reviewable segments for one section, in document order.
 *
 * Every translatable segment survives — a table row with two text columns
 * yields two reviewable rows rather than quietly dropping the second. `skip`
 * segments (blank cells, figures without digits) carry nothing to review and
 * are left out; `numeric` cells attach to their row as locked values.
 */
export function viewSegments(api: ApiSegment[]): Segment[] {
  const ordered = [...api].sort((a, b) => a.segIndex - b.segIndex);
  const out: Segment[] = [];

  /** "tableIndex:rowIndex", or null for anything outside a table row. */
  const rowKey = (seg: ApiSegment): string | null => {
    const table = seg.tableIndex ?? null;
    const row = seg.rowIndex ?? null;
    return table === null || row === null ? null : `${table}:${row}`;
  };

  /** Figure cells keyed by their row, in column order. */
  const figures = new Map<string, ApiSegment[]>();
  for (const seg of ordered) {
    const key = seg.kind === 'numeric' ? rowKey(seg) : null;
    if (key === null) continue;
    const list = figures.get(key);
    if (list) list.push(seg);
    else figures.set(key, [seg]);
  }

  const rowsSeen = new Set<string>();
  for (const seg of ordered) {
    if (seg.kind === 'skip' || seg.kind === 'numeric') continue;

    const view = baseSegment(seg);
    if (seg.kind === 'table_label') {
      // Belongs to a table even if the row is unknown, so it still renders as
      // part of that table rather than drifting into the prose above it.
      const table = seg.tableIndex ?? null;
      if (table !== null) view.table = `t${table}`;
      const key = rowKey(seg);
      // The figures belong to the row's first label; a second text column in
      // the same row is its own row here, without repeating the numbers.
      if (key !== null && !rowsSeen.has(key)) {
        rowsSeen.add(key);
        const nums = figures.get(key);
        if (nums?.length) view.nums = nums.map(n => n.sourceText.trim());
      }
    }
    out.push(view);
  }
  return out;
}

/** Groups a job's segments per section id, ready for the workspace. */
export function segmentsBySection(
  api: ApiSegment[],
  sections: SectionMeta[],
): Record<string, Segment[]> {
  const bySection = new Map<string, ApiSegment[]>();
  for (const seg of api) {
    const key = seg.sectionId || '';
    const list = bySection.get(key);
    if (list) list.push(seg);
    else bySection.set(key, [seg]);
  }
  const out: Record<string, Segment[]> = {};
  for (const meta of sections) {
    out[meta.id] = viewSegments(bySection.get(meta.id) ?? []);
  }
  return out;
}

/** The segment route takes the parser's index; the view keeps it as its id. */
export function segIndexOf(viewId: string): number {
  return Number(viewId);
}
