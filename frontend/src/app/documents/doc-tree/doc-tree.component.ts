/**
 * Copyright 2026 Google LLC — Licensed under the Apache License, Version 2.0.
 * Hunkemöller "Documents" — document outline (left rail).
 *
 * Renders the chapter/section tree with per-section rollups. During a
 * translation run the rollup column is replaced by the section run state.
 */

import {Component, EventEmitter, Input, Output} from '@angular/core';
import {Chapter, RunState, SectionMeta, Segment} from '../documents.data';

export interface SectionRollup {
  total: number;
  open: number;
  att: number;
}

@Component({
  selector: 'app-doc-tree',
  templateUrl: './doc-tree.component.html',
  styleUrls: ['./doc-tree.component.scss'],
})
export class DocTreeComponent {
  /** The active document's outline; empty until a job is loaded. */
  @Input() tree: Chapter[] = [];

  @Input() segs: Record<string, Segment[]> = {};
  @Input() active: string | null = null;
  /** run mode: per-section run states replace the rollups */
  @Input() run: Record<string, RunState> | null = null;
  @Input() focusable = true;
  @Output() picked = new EventEmitter<string>();

  collapsed: Record<string, boolean> = {};

  toggle(ch: Chapter) {
    this.collapsed[ch.id] = !this.collapsed[ch.id];
  }

  /**
   * During a run only the sections that already finished can be opened —
   * a queued one has no translation to show yet, and the one in flight is
   * still being written. Outside a run the whole outline follows `focusable`.
   */
  canPick(s: SectionMeta): boolean {
    if (this.run) return this.runState(s.id) === 'done';
    return this.focusable;
  }

  select(s: SectionMeta) {
    if (this.canPick(s)) this.picked.emit(s.id);
  }

  rollup(id: string): SectionRollup {
    const segs = this.segs[id] || [];
    const open = segs.filter(s => !s.approved).length;
    const att = segs.filter(s => s.finding && !s.approved).length;
    const meta = this.tree.flatMap(c => c.sections).find(s => s.id === id);
    return {
      total: meta ? Math.max(meta.n, segs.length) : segs.length,
      open,
      att,
    };
  }

  pct(id: string): number {
    const r = this.rollup(id);
    return Math.round((100 * (r.total - r.open)) / r.total);
  }

  runState(id: string): RunState {
    return (this.run && this.run[id]) || 'queued';
  }

  chapterAtt(ch: Chapter): number {
    return ch.sections.reduce((a, s) => a + this.rollup(s.id).att, 0);
  }

  chapterOpen(ch: Chapter): number {
    return ch.sections.reduce((a, s) => a + this.rollup(s.id).open, 0);
  }
}
