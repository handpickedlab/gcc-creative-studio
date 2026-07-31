/**
 * Copyright 2026 Google LLC — Licensed under the Apache License, Version 2.0.
 * Hunkemöller "Documents" page — annual-report (docx) translation experience.
 *
 * Flow: library → intake (upload) → preflight → translation run → review
 * workspace (tree + segments + QA findings) → QA report → export.
 * The backend job/API layer lands in a later slice; runs and re-translations
 * are simulated on the demo corpus so the whole flow is clickable.
 */

import {
  Component,
  HostListener,
  OnDestroy,
  ViewChild,
  ElementRef,
} from '@angular/core';
import {
  ALL_SECTIONS,
  buildInitialSegs,
  DNT_LIST,
  DOC_LIBRARY,
  DOC_TARGETS,
  DOC_TOTALS,
  DocItem,
  DocStatus,
  GLOSSARY_FIN,
  GLOSSARY_MKT,
  GlossaryRow,
  PROV_META,
  ProvMeta,
  QA_META,
  QaFinding,
  QaMeta,
  QaType,
  ReviewFilter,
  RunState,
  SectionMeta,
  sectionById,
  Segment,
  STATUS_META,
  StatusMeta,
  TREE,
} from './documents.data';

type View =
  | 'library'
  | 'intake'
  | 'preflight'
  | 'run'
  | 'review'
  | 'qa'
  | 'export'
  | 'glossary';
type SegAction = 'approve' | 'edit' | 'dismiss' | 'retrans' | 'approveSection';

interface SegGroup {
  type: 'seg' | 'table';
  key: string;
  seg?: Segment;
  rows?: Segment[];
}

interface DocBlock {
  meta: SectionMeta;
  groups: SegGroup[];
  count: number;
  remaining: number;
}

interface DocRollup {
  open: number;
  att: number;
  aiOpen: number;
  edited: number;
  findings: number;
  critical: number;
  approved: number;
  pct: number;
}

interface Finding {
  sec: string;
  seg: Segment;
}

interface QaGroup {
  type: QaType;
  meta: QaMeta;
  list: Finding[];
}

interface RunInfo {
  states: Record<string, RunState>;
  pct: number;
  done: number;
  failed: string[];
  complete: boolean;
}

interface TermInfo {
  sec: string;
  segId: string;
  expected: string;
  found: string;
  count: number;
  sections: number;
  approvedHit: number;
}

const FILTERS: Array<{v: ReviewFilter; label: string}> = [
  {v: 'attention', label: 'Needs attention'},
  {v: 'ai', label: 'AI — new'},
  {v: 'edited', label: 'Edited'},
  {v: 'all', label: 'All'},
];

@Component({
  selector: 'app-documents',
  templateUrl: './documents.component.html',
  styleUrls: ['./documents.component.scss'],
})
export class DocumentsComponent implements OnDestroy {
  readonly tree = TREE;
  readonly totals = DOC_TOTALS;
  readonly sectionCount = ALL_SECTIONS.length;
  readonly filters = FILTERS;
  readonly library: DocItem[] = DOC_LIBRARY;
  readonly targets = DOC_TARGETS;
  readonly dntList = DNT_LIST;
  readonly statusMeta = STATUS_META;
  readonly qaMeta = QA_META;

  view: View = 'library';
  doc: DocItem | null = null;

  segs: Record<string, Segment[]> = {};
  more: Record<string, number> = {};

  activeSec = '1.1';
  filter: ReviewFilter = 'attention';
  q = '';
  scope: 'section' | 'doc' = 'section';
  focusSeg: string | null = null;
  busyIds = new Set<string>();
  editingId: string | null = null;
  editDraft = '';
  retransId: string | null = null;
  retransDraft = '';
  termInfo: TermInfo | null = null;

  toast = '';
  exported = false;
  run: RunInfo | null = null;

  /* intake */
  intake: 'idle' | 'parsing' | 'pdf' | 'corrupt' = 'idle';
  drag = false;

  /* preflight config */
  pfTargets: string[] = ['NL', 'DE'];
  pfDomain: 'financial' | 'marketing' = 'financial';
  pfLocalise = false;
  pfDisclaimer = true;

  /* glossary */
  glossDomain: 'financial' | 'marketing' = 'financial';

  /* cached view state — rebuilt by refreshView() after every mutation */
  dr: DocRollup = {
    open: 0,
    att: 0,
    aiOpen: 0,
    edited: 0,
    findings: 0,
    critical: 0,
    approved: 0,
    pct: 0,
  };
  groups: SegGroup[] = [];
  docBlocks: DocBlock[] = [];
  flatVisible: Array<{sec: string; seg: Segment}> = [];
  qaGroups: QaGroup[] = [];
  criticals: Finding[] = [];
  visibleCount = 0;
  sectionRemaining = 0;

  @ViewChild('scroller') scroller?: ElementRef<HTMLElement>;

  private timers: ReturnType<typeof setTimeout>[] = [];

  constructor() {
    const built = buildInitialSegs();
    this.segs = built.segs;
    this.more = built.more;
    this.refreshView();
  }

  ngOnDestroy() {
    this.timers.forEach(clearTimeout);
  }

  private later(fn: () => void, ms: number) {
    this.timers.push(setTimeout(fn, ms));
  }

  flash(msg: string) {
    this.toast = msg;
    this.later(() => (this.toast = ''), 2400);
  }

  /* ── header helpers ─────────────────────────────────────────── */

  get inDoc(): boolean {
    return !!this.doc && ['review', 'qa', 'export'].includes(this.view);
  }

  get trail(): string | null {
    if (this.inDoc || this.view === 'run' || this.view === 'preflight') {
      return this.doc?.name || 'Annual Report FY2025-26.docx';
    }
    return this.view === 'glossary' ? 'Glossary' : null;
  }

  get docStatus(): DocStatus | null {
    if (!this.trail || this.view === 'glossary') return null;
    if (this.view === 'run') return 'translating';
    return this.doc?.status || null;
  }

  get allClear(): boolean {
    return this.doc ? !!this.doc.clear || this.doc.id === 'd2' : false;
  }

  /** QA / export nav badges honour the all-clear demo documents. */
  get navFindings(): number {
    return this.allClear ? 0 : this.dr.findings;
  }

  get navCritical(): number {
    return this.allClear ? 0 : this.dr.critical;
  }

  statusOf(status: DocStatus): StatusMeta {
    return STATUS_META[status];
  }

  provOf(seg: Segment): ProvMeta {
    const key = seg.approved
      ? 'approved'
      : seg.finding
        ? 'attention'
        : seg.prov;
    return PROV_META[key];
  }

  isApproved(seg: Segment): boolean {
    return seg.approved;
  }

  sectionMeta(id: string): SectionMeta | undefined {
    return sectionById(id);
  }

  qaOf(f: QaFinding): QaMeta {
    return QA_META[f.type];
  }

  /* ── view navigation ────────────────────────────────────────── */

  openDoc(d: DocItem) {
    this.doc = d;
    this.exported = d.status === 'exported';
    if (d.status === 'review') {
      this.activeSec = '1.1';
      this.filter = 'attention';
      this.scope = 'section';
      this.q = '';
      this.setView('review');
    } else {
      this.setView('export');
    }
  }

  backToLibrary() {
    this.doc = null;
    this.setView('library');
  }

  setView(v: View) {
    this.view = v;
    this.editingId = null;
    this.retransId = null;
    if (v === 'intake') this.intake = 'idle';
    this.refreshView();
  }

  openSeg(sec: string, segId: string) {
    this.activeSec = sec;
    this.filter = 'all';
    this.scope = 'section';
    this.q = '';
    this.focusSeg = segId;
    this.setView('review');
    this.scrollToFocus();
  }

  pickSection(id: string) {
    this.activeSec = id;
    this.focusSeg = null;
    this.refreshView();
    if (this.scope === 'doc') {
      this.later(() => {
        document
          .getElementById('secblock-' + id)
          ?.scrollIntoView({block: 'start'});
      }, 30);
    }
  }

  setFilter(f: ReviewFilter) {
    this.filter = f;
    this.refreshView();
  }

  setScope(s: 'section' | 'doc') {
    this.scope = s;
    this.focusSeg = null;
    this.refreshView();
  }

  onSearch() {
    this.refreshView();
  }

  /* ── review view model ──────────────────────────────────────── */

  private matches(seg: Segment): boolean {
    if (this.q) {
      const s = this.q.toLowerCase();
      if (
        !seg.src.toLowerCase().includes(s) &&
        !seg.tgt.toLowerCase().includes(s)
      )
        return false;
    }
    if (this.filter === 'all') return true;
    if (this.filter === 'attention') return !!seg.finding && !seg.approved;
    if (this.filter === 'ai') return seg.prov === 'ai' && !seg.approved;
    if (this.filter === 'edited') return seg.prov === 'edited';
    return true;
  }

  private mkGroups(list: Segment[], secId: string): SegGroup[] {
    const groups: SegGroup[] = [];
    list.forEach(seg => {
      const last = groups[groups.length - 1];
      if (
        seg.kind === 'trow' &&
        last &&
        last.type === 'table' &&
        last.rows![0].table === seg.table
      ) {
        last.rows!.push(seg);
      } else if (seg.kind === 'trow') {
        groups.push({type: 'table', key: `${secId}-t-${seg.id}`, rows: [seg]});
      } else {
        groups.push({type: 'seg', key: seg.id, seg});
      }
    });
    return groups;
  }

  refreshView() {
    /* document rollup */
    let open = 0,
      att = 0,
      aiOpen = 0,
      edited = 0,
      critical = 0;
    Object.values(this.segs).forEach(segs =>
      segs.forEach(s => {
        if (!s.approved) {
          open++;
          if (s.finding) {
            att++;
            if (QA_META[s.finding.type].level === 'critical') critical++;
          }
          if (s.prov === 'ai') aiOpen++;
        }
        if (s.prov === 'edited') edited++;
      }),
    );
    const approved = DOC_TOTALS.segments - open;
    this.dr = {
      open,
      att,
      aiOpen,
      edited,
      findings: att,
      critical,
      approved,
      pct: Math.round((100 * approved) / DOC_TOTALS.segments),
    };

    /* section scope */
    const segs = this.segs[this.activeSec] || [];
    const visible = segs.filter(s => this.matches(s));
    this.visibleCount = visible.length;
    this.sectionRemaining = segs.filter(s => !s.approved).length;
    this.groups = this.mkGroups(visible, this.activeSec);

    /* doc scope */
    if (this.scope === 'doc') {
      this.docBlocks = ALL_SECTIONS.map(meta => {
        const list = (this.segs[meta.id] || []).filter(s => this.matches(s));
        return {
          meta,
          groups: this.mkGroups(list, meta.id),
          count: list.length,
          remaining: (this.segs[meta.id] || []).filter(s => !s.approved).length,
        };
      }).filter(b => b.count > 0);
      this.flatVisible = this.docBlocks.flatMap(b =>
        b.groups
          .flatMap(g => (g.type === 'table' ? g.rows! : [g.seg!]))
          .map(seg => ({sec: b.meta.id, seg})),
      );
    } else {
      this.docBlocks = [];
      this.flatVisible = visible.map(seg => ({sec: this.activeSec, seg}));
    }

    /* QA + export */
    const found: Finding[] = [];
    Object.entries(this.segs).forEach(([sec, list]) =>
      list.forEach(seg => {
        if (seg.finding && !seg.approved) found.push({sec, seg});
      }),
    );
    const order: Record<QaType, number> = {
      number: 0,
      glossary: 1,
      dnt: 2,
      length: 3,
    };
    found.sort(
      (a, b) => order[a.seg.finding!.type] - order[b.seg.finding!.type],
    );
    const byType = new Map<QaType, Finding[]>();
    found.forEach(f => {
      const t = f.seg.finding!.type;
      if (!byType.has(t)) byType.set(t, []);
      byType.get(t)!.push(f);
    });
    this.qaGroups = Array.from(byType.entries()).map(([type, list]) => ({
      type,
      meta: QA_META[type],
      list,
    }));
    this.criticals = found.filter(
      f => QA_META[f.seg.finding!.type].level === 'critical',
    );
  }

  get qaFindingsTotal(): number {
    return this.qaGroups.reduce((a, g) => a + g.list.length, 0);
  }

  filterCount(f: ReviewFilter): number {
    if (f === 'attention') return this.dr.att;
    if (f === 'ai') return this.dr.aiOpen;
    if (f === 'edited') return this.dr.edited;
    return DOC_TOTALS.segments;
  }

  trackGroup(_i: number, g: SegGroup) {
    return g.key;
  }

  trackSeg(_i: number, s: Segment) {
    return s.id;
  }

  trackBlock(_i: number, b: DocBlock) {
    return b.meta.id;
  }

  /* ── segment mutations ──────────────────────────────────────── */

  act(sec: string, segId: string | null, type: SegAction, payload?: string) {
    const segs = this.segs[sec];
    if (!segs) return;

    if (type === 'retrans') {
      if (!segId) return;
      this.busyIds.add(segId);
      this.later(() => {
        this.busyIds.delete(segId);
        const s = segs.find(x => x.id === segId);
        if (!s) return;
        if (s.finding?.type === 'number')
          s.tgt = s.tgt.replace('€ 85 miljoen', '€ 8,5 miljoen');
        if (s.finding?.found && s.finding?.expected)
          s.tgt = s.tgt.split(s.finding.found).join(s.finding.expected);
        s.prov = 'ai';
        s.approved = false;
        s.finding = undefined;
        this.flash(
          payload
            ? `Re-translated with instruction “${payload}”`
            : 'Segment re-translated',
        );
        this.refreshView();
      }, 950);
      return;
    }

    if (type === 'approveSection') {
      let skipped = 0;
      segs.forEach(s => {
        if (s.approved) return;
        if (s.finding && QA_META[s.finding.type].level === 'critical') {
          skipped++;
          return;
        }
        s.approved = true;
        s.finding = undefined;
      });
      this.flash(
        skipped
          ? `Section approved — ${skipped} critical finding left open`
          : 'Section approved',
      );
      this.refreshView();
      return;
    }

    const s = segs.find(x => x.id === segId);
    if (!s) return;
    if (type === 'edit') {
      s.tgt = payload ?? s.tgt;
      s.prov = 'edited';
      s.approved = false;
      s.finding = undefined;
    } else if (type === 'dismiss') {
      s.finding = undefined;
    } else if (type === 'approve') {
      if (s.finding && QA_META[s.finding.type].level === 'critical') {
        this.flash('Resolve the number mismatch before approving');
        return;
      }
      s.approved = true;
      s.finding = undefined;
    }
    this.refreshView();
  }

  startEdit(seg: Segment) {
    this.editingId = seg.id;
    this.editDraft = seg.tgt;
    this.retransId = null;
  }

  saveEdit(sec: string) {
    if (!this.editingId) return;
    this.act(sec, this.editingId, 'edit', this.editDraft);
    this.editingId = null;
  }

  cancelEdit() {
    this.editingId = null;
  }

  toggleRetrans(seg: Segment) {
    this.retransId = this.retransId === seg.id ? null : seg.id;
    this.retransDraft = '';
  }

  goRetrans(sec: string) {
    if (!this.retransId) return;
    const id = this.retransId;
    this.retransId = null;
    this.act(sec, id, 'retrans', this.retransDraft.trim() || undefined);
  }

  approveTitle(seg: Segment): string {
    return seg.finding && QA_META[seg.finding.type].level === 'critical'
      ? 'Resolve the critical finding first'
      : 'Approve (A)';
  }

  /* term fix at scale */
  openTermModal(sec: string, seg: Segment) {
    const f = seg.finding;
    if (!f?.found || !f?.expected) return;
    this.termInfo = {
      sec,
      segId: seg.id,
      expected: f.expected,
      found: f.found,
      count: 7,
      sections: 3,
      approvedHit: 4,
    };
  }

  applyTerm() {
    const info = this.termInfo;
    if (!info) return;
    const seg = (this.segs[info.sec] || []).find(s => s.id === info.segId);
    if (seg)
      this.act(
        info.sec,
        info.segId,
        'edit',
        seg.tgt.split(info.found).join(info.expected),
      );
    this.termInfo = null;
    this.flash(
      `“${info.expected}” applied to ${info.count} segments across ${info.sections} sections`,
    );
  }

  /* ── keyboard: j/k move · a approve · esc clear ─────────────── */

  @HostListener('window:keydown', ['$event'])
  onKey(e: KeyboardEvent) {
    if (
      this.view !== 'review' ||
      this.editingId ||
      this.retransId ||
      this.termInfo
    )
      return;
    const tag = (e.target as HTMLElement)?.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA') return;
    const idx = this.flatVisible.findIndex(x => x.seg.id === this.focusSeg);
    if (e.key === 'j' || e.key === 'ArrowDown') {
      e.preventDefault();
      const n =
        this.flatVisible[Math.min(idx + 1, this.flatVisible.length - 1)];
      if (n) {
        this.focusSeg = n.seg.id;
        this.scrollToFocus();
      }
    } else if (e.key === 'k' || e.key === 'ArrowUp') {
      e.preventDefault();
      const n = this.flatVisible[Math.max(idx - 1, 0)];
      if (n) {
        this.focusSeg = n.seg.id;
        this.scrollToFocus();
      }
    } else if (e.key === 'a' && idx >= 0) {
      const cur = this.flatVisible[idx];
      this.act(cur.sec, cur.seg.id, 'approve');
    } else if (e.key === 'e' && idx >= 0) {
      e.preventDefault();
      this.startEdit(this.flatVisible[idx].seg);
    } else if (e.key === 'Escape') {
      this.focusSeg = null;
    }
  }

  private scrollToFocus() {
    const id = this.focusSeg;
    if (!id) return;
    this.later(() => {
      document.getElementById('seg-' + id)?.scrollIntoView({block: 'center'});
    }, 60);
  }

  /* ── intake ─────────────────────────────────────────────────── */

  simulate(kind: 'ok' | 'pdf' | 'corrupt') {
    if (kind === 'ok') {
      this.intake = 'parsing';
      this.later(() => this.setView('preflight'), 1600);
    } else {
      this.intake = kind;
    }
  }

  onDrop(e: DragEvent) {
    e.preventDefault();
    this.drag = false;
    this.simulate('ok');
  }

  onDragOver(e: DragEvent) {
    e.preventDefault();
    this.drag = true;
  }

  /* ── preflight ──────────────────────────────────────────────── */

  togglePfTarget(code: string) {
    this.pfTargets = this.pfTargets.includes(code)
      ? this.pfTargets.filter(c => c !== code)
      : [...this.pfTargets, code];
  }

  /* ── translation run (simulated) ────────────────────────────── */

  startRun() {
    const states: Record<string, RunState> = {};
    ALL_SECTIONS.forEach(s => (states[s.id] = 'queued'));
    this.run = {states, pct: 0, done: 0, failed: [], complete: false};
    this.setView('run');
    let i = 0;
    let doneSegs = 0;
    const step = () => {
      const run = this.run;
      if (!run || this.view !== 'run') return;
      if (i >= ALL_SECTIONS.length) {
        run.complete = true;
        return;
      }
      const s = ALL_SECTIONS[i];
      run.states[s.id] = 'run';
      this.later(
        () => {
          if (!this.run) return;
          const fail = s.id === '2.31';
          doneSegs += fail ? 0 : s.n;
          this.run.states[s.id] = fail ? 'fail' : 'done';
          if (fail) this.run.failed.push(s.id);
          this.run.pct = Math.min(
            99,
            Math.round((100 * doneSegs) / DOC_TOTALS.segments),
          );
          this.run.done = doneSegs;
          i++;
          step();
        },
        i < 3 ? 700 : 90 + Math.random() * 120,
      );
    };
    step();
  }

  retrySection(id: string) {
    const run = this.run;
    if (!run) return;
    run.states[id] = 'run';
    run.failed = run.failed.filter(f => f !== id);
    run.complete = false;
    this.later(() => {
      if (!this.run) return;
      this.run.states[id] = 'done';
      this.run.pct = 100;
      this.run.done = DOC_TOTALS.segments;
      this.run.complete = true;
    }, 1600);
  }

  cancelRun() {
    this.run = null;
    this.flash('Run cancelled — completed sections kept');
    this.setView('library');
  }

  finishRun() {
    if (this.run?.complete && !this.run.failed.length) {
      this.doc = this.library[0];
      this.filter = 'attention';
      this.scope = 'section';
      this.activeSec = '1.1';
      this.setView('review');
    } else {
      this.setView('library');
    }
  }

  runFailedTitle(id: string): string {
    return `${id} ${sectionById(id)?.title || ''} failed`;
  }

  /* ── export ─────────────────────────────────────────────────── */

  get exportBlocked(): boolean {
    return !this.allClear && this.criticals.length > 0;
  }

  doExport() {
    this.exported = true;
    this.flash('Annual Report FY2025-26 — NL.docx downloaded');
  }

  get exportDocName(): string {
    return this.doc?.name || 'Annual Report FY2025-26.docx';
  }

  /* ── glossary ───────────────────────────────────────────────── */

  get glossRows(): GlossaryRow[] {
    return this.glossDomain === 'financial' ? GLOSSARY_FIN : GLOSSARY_MKT;
  }
}
