/**
 * Copyright 2026 Google LLC — Licensed under the Apache License, Version 2.0.
 * Hunkemöller "Documents" page — translating a Word document with its layout
 * left intact.
 *
 * Flow: library → intake (upload) → preflight → translation run → review
 * workspace (outline + segments + QA findings) → QA report → export. Every
 * step talks to `/api/document-translations`; the run happens server-side and
 * this polls the job for its progress.
 */

import {
  Component,
  ElementRef,
  HostListener,
  OnDestroy,
  OnInit,
  ViewChild,
  inject,
} from '@angular/core';
import {
  Chapter,
  DNT_LIST,
  DOC_TARGETS,
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
  Segment,
  STATUS_META,
  StatusMeta,
  marketLabel,
} from './documents.data';
import {
  ApiJob,
  ApiSegment,
  DocumentTranslationsService,
} from './document-translations.service';
import {
  allSectionsOf,
  chaptersFrom,
  segIndexOf,
  segmentsBySection,
} from './documents.adapter';

type View =
  | 'library'
  | 'intake'
  | 'preflight'
  | 'run'
  | 'review'
  | 'qa'
  | 'export'
  | 'glossary';

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
  total: number;
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

interface TermInfo {
  sec: string;
  segId: string;
  expected: string;
  found: string;
  /** segments whose translation still carries the wrong term */
  hits: Array<{sec: string; seg: Segment}>;
  count: number;
  sections: number;
  approvedHit: number;
}

/** One row in the library table. */
interface JobRow {
  job: ApiJob;
  name: string;
  status: DocStatus;
  targets: string[];
  progress: number;
  pages: number;
  words: number;
  activity: string;
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
export class DocumentsComponent implements OnInit, OnDestroy {
  private readonly api = inject(DocumentTranslationsService);

  readonly filters = FILTERS;
  readonly targets = DOC_TARGETS;
  readonly dntList = DNT_LIST;
  readonly statusMeta = STATUS_META;
  readonly qaMeta = QA_META;

  view: View = 'library';

  /* library */
  jobs: JobRow[] = [];
  loadingJobs = false;
  /** Set when the list could not be fetched — an empty library is not the same
   *  thing as an unreachable one. */
  loadError = '';

  /* active document */
  job: ApiJob | null = null;
  tree: Chapter[] = [];
  sections: SectionMeta[] = [];
  segs: Record<string, Segment[]> = {};
  loadingDoc = false;

  activeSec = '';
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

  /* intake */
  intake: 'idle' | 'parsing' | 'error' = 'idle';
  intakeError = '';
  drag = false;

  /* preflight — the API translates into one market per job */
  pfTarget = 'NL';
  reusePct: number | null = null;
  reuseTotal = 0;
  reuseCount = 0;
  loadingReuse = false;

  /* glossary */
  glossDomain: 'financial' | 'marketing' = 'financial';

  /* cached view state, rebuilt by refreshView() after every mutation */
  dr: DocRollup = {
    open: 0,
    att: 0,
    aiOpen: 0,
    edited: 0,
    findings: 0,
    critical: 0,
    approved: 0,
    total: 0,
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
  private poller: ReturnType<typeof setInterval> | null = null;

  ngOnInit() {
    this.loadJobs();
  }

  ngOnDestroy() {
    this.timers.forEach(clearTimeout);
    this.stopPolling();
  }

  private later(fn: () => void, ms: number) {
    this.timers.push(setTimeout(fn, ms));
  }

  flash(msg: string) {
    this.toast = msg;
    this.later(() => (this.toast = ''), 2800);
  }

  private failed(action: string) {
    return (err: unknown) => {
      const detail =
        (err as {error?: {detail?: string}})?.error?.detail ||
        (err as {message?: string})?.message ||
        '';
      this.flash(`${action} failed${detail ? ` — ${detail}` : ''}`);
    };
  }

  /* ── library ────────────────────────────────────────────────── */

  loadJobs() {
    this.loadingJobs = true;
    this.loadError = '';
    this.api.listJobs().subscribe({
      next: jobs => {
        this.jobs = jobs.map(j => this.toRow(j));
        this.loadingJobs = false;
      },
      error: (err: {status?: number; error?: {detail?: string}}) => {
        this.loadingJobs = false;
        this.loadError =
          err?.status === 0
            ? 'Could not reach the translation service.'
            : err?.error?.detail ||
              `The translation service returned an error (${err?.status ?? '?'}).`;
      },
    });
  }

  private toRow(job: ApiJob): JobRow {
    const stats = job.stats || {};
    const prog = job.progress;
    const pct = prog?.total
      ? Math.round((100 * prog.translated) / prog.total)
      : job.status === 'completed'
        ? 100
        : 0;
    return {
      job,
      name: job.filename,
      status: job.status,
      targets: job.targetMarket ? [job.targetMarket] : [],
      progress: pct,
      pages: stats.pages || 0,
      words: stats.words || 0,
      activity: this.when(job.updatedAt || job.createdAt),
    };
  }

  private when(iso?: string): string {
    if (!iso) return '';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '';
    const sameDay = new Date().toDateString() === d.toDateString();
    return sameDay
      ? `today, ${d.toLocaleTimeString(undefined, {hour: '2-digit', minute: '2-digit'})}`
      : d.toLocaleDateString(undefined, {
          day: 'numeric',
          month: 'short',
          year: 'numeric',
        });
  }

  /* ── opening a document ─────────────────────────────────────── */

  openJob(row: JobRow) {
    this.job = row.job;
    this.exported = row.job.status === 'completed';
    this.tree = chaptersFrom(row.job);
    this.sections = allSectionsOf(this.tree);
    this.activeSec = this.sections[0]?.id || '';
    this.filter = 'attention';
    this.scope = 'section';
    this.q = '';
    this.segs = {};

    if (row.job.status === 'uploaded') {
      this.setView('preflight');
      this.loadReuse();
      return;
    }
    if (row.job.status === 'translating') {
      this.setView('run');
      this.startPolling();
      return;
    }
    this.loadSegments(() => this.setView('review'));
  }

  private loadSegments(done?: () => void) {
    const job = this.job;
    if (!job) return;
    this.loadingDoc = true;
    this.api.listSegments(job.id).subscribe({
      next: (api: ApiSegment[]) => {
        this.segs = segmentsBySection(api, this.sections);
        this.loadingDoc = false;
        this.refreshView();
        if (done) done();
      },
      error: err => {
        this.loadingDoc = false;
        this.failed('Loading segments')(err);
      },
    });
  }

  backToLibrary() {
    this.stopPolling();
    this.job = null;
    this.segs = {};
    this.tree = [];
    this.sections = [];
    this.setView('library');
    this.loadJobs();
  }

  setView(v: View) {
    this.view = v;
    this.editingId = null;
    this.retransId = null;
    if (v === 'intake') {
      this.intake = 'idle';
      this.intakeError = '';
    }
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

  /* ── header helpers ─────────────────────────────────────────── */

  get inDoc(): boolean {
    return !!this.job && ['review', 'qa', 'export'].includes(this.view);
  }

  get docStatus(): DocStatus | null {
    return this.job?.status ?? null;
  }

  statusOf(status: DocStatus): StatusMeta {
    return STATUS_META[status] || STATUS_META.uploaded;
  }

  provOf(seg: Segment): ProvMeta {
    const key = seg.approved
      ? 'approved'
      : seg.finding
        ? 'attention'
        : seg.prov;
    return PROV_META[key];
  }

  qaOf(f: QaFinding): QaMeta {
    return QA_META[f.type];
  }

  /** The checks decide what blocks an export, not the finding's kind. */
  blocksExport(f: QaFinding): boolean {
    return f.severity
      ? f.severity === 'error'
      : QA_META[f.type].level === 'critical';
  }

  sectionMeta(id: string): SectionMeta | undefined {
    return this.sections.find(s => s.id === id);
  }

  get navFindings(): number {
    return this.dr.findings;
  }

  get navCritical(): number {
    return this.dr.critical;
  }

  get docName(): string {
    return this.job?.filename || '';
  }

  get targetLabel(): string {
    return marketLabel(this.job?.targetMarket);
  }

  marketOf(code: string): string {
    return marketLabel(code);
  }

  /* ── review view model ──────────────────────────────────────── */

  private matches(seg: Segment): boolean {
    if (this.q) {
      const s = this.q.toLowerCase();
      if (
        !seg.src.toLowerCase().includes(s) &&
        !seg.tgt.toLowerCase().includes(s)
      ) {
        return false;
      }
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
    let open = 0;
    let att = 0;
    let aiOpen = 0;
    let edited = 0;
    let critical = 0;
    let total = 0;
    Object.values(this.segs).forEach(segs =>
      segs.forEach(s => {
        total++;
        if (!s.approved) {
          open++;
          if (s.finding) {
            att++;
            if (this.blocksExport(s.finding)) critical++;
          }
          if (s.prov === 'ai') aiOpen++;
        }
        if (s.prov === 'edited') edited++;
      }),
    );
    const approved = total - open;
    this.dr = {
      open,
      att,
      aiOpen,
      edited,
      findings: att,
      critical,
      approved,
      total,
      pct: total ? Math.round((100 * approved) / total) : 0,
    };

    const segs = this.segs[this.activeSec] || [];
    const visible = segs.filter(s => this.matches(s));
    this.visibleCount = visible.length;
    this.sectionRemaining = segs.filter(s => !s.approved).length;
    this.groups = this.mkGroups(visible, this.activeSec);

    if (this.scope === 'doc') {
      this.docBlocks = this.sections
        .map(meta => {
          const list = (this.segs[meta.id] || []).filter(s => this.matches(s));
          return {
            meta,
            groups: this.mkGroups(list, meta.id),
            count: list.length,
            remaining: (this.segs[meta.id] || []).filter(s => !s.approved)
              .length,
          };
        })
        .filter(b => b.count > 0);
      this.flatVisible = this.docBlocks.flatMap(b =>
        b.groups
          .flatMap(g => (g.type === 'table' ? g.rows! : [g.seg!]))
          .map(seg => ({sec: b.meta.id, seg})),
      );
    } else {
      this.docBlocks = [];
      this.flatVisible = visible.map(seg => ({sec: this.activeSec, seg}));
    }

    const found: Finding[] = [];
    Object.entries(this.segs).forEach(([sec, list]) =>
      list.forEach(seg => {
        if (seg.finding && !seg.approved) found.push({sec, seg});
      }),
    );
    const order: Record<QaType, number> = {
      number: 0,
      dnt: 1,
      glossary: 2,
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
    this.criticals = found.filter(f => this.blocksExport(f.seg.finding!));
  }

  filterCount(f: ReviewFilter): number {
    if (f === 'attention') return this.dr.att;
    if (f === 'ai') return this.dr.aiOpen;
    if (f === 'edited') return this.dr.edited;
    return this.dr.total;
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

  trackJob(_i: number, r: JobRow) {
    return r.job.id;
  }

  /* ── segment mutations ──────────────────────────────────────── */

  /** Replaces one segment in place from the API's answer. */
  private absorb(sec: string, api: ApiSegment) {
    const list = this.segs[sec];
    if (!list) return;
    const idx = list.findIndex(s => s.id === String(api.segIndex));
    if (idx < 0) return;
    const before = list[idx];
    list[idx] = {
      ...before,
      prov: api.provenance ?? before.prov,
      approved: api.status === 'approved',
      tgt: api.translation ?? '',
      finding: api.finding
        ? {
            type: before.finding?.type ?? 'glossary',
            msg: api.finding.msg,
            severity: api.finding.severity,
            term: api.finding.term ?? undefined,
            expected: api.finding.expected ?? undefined,
            found: api.finding.found ?? undefined,
          }
        : undefined,
    };
    this.refreshView();
  }

  approve(sec: string, seg: Segment) {
    if (seg.finding && this.blocksExport(seg.finding)) {
      this.flash('Resolve the blocking finding before approving');
      return;
    }
    const job = this.job;
    if (!job) return;
    this.busyIds.add(seg.id);
    this.api
      .updateSegment(job.id, segIndexOf(seg.id), {status: 'approved'})
      .subscribe({
        next: api => {
          this.busyIds.delete(seg.id);
          this.absorb(sec, api);
        },
        error: err => {
          this.busyIds.delete(seg.id);
          this.failed('Approving')(err);
        },
      });
  }

  approveTitle(seg: Segment): string {
    return seg.finding && this.blocksExport(seg.finding)
      ? 'Resolve the blocking finding first'
      : 'Approve (A)';
  }

  approveSection(sec: string) {
    const job = this.job;
    if (!job) return;
    this.api.approveSection(job.id, sec).subscribe({
      next: res => {
        this.flash(`Section approved — ${res.approved} segments`);
        this.loadSegments();
      },
      error: this.failed('Approving the section'),
    });
  }

  startEdit(seg: Segment) {
    this.editingId = seg.id;
    this.editDraft = seg.tgt;
    this.retransId = null;
  }

  cancelEdit() {
    this.editingId = null;
  }

  saveEdit(sec: string) {
    const job = this.job;
    const id = this.editingId;
    if (!job || !id) return;
    this.editingId = null;
    this.busyIds.add(id);
    this.api
      .updateSegment(job.id, segIndexOf(id), {translation: this.editDraft})
      .subscribe({
        next: api => {
          this.busyIds.delete(id);
          this.absorb(sec, api);
        },
        error: err => {
          this.busyIds.delete(id);
          this.failed('Saving')(err);
        },
      });
  }

  toggleRetrans(seg: Segment) {
    this.retransId = this.retransId === seg.id ? null : seg.id;
    this.retransDraft = '';
  }

  goRetrans(sec: string) {
    const job = this.job;
    const id = this.retransId;
    if (!job || !id) return;
    this.retransId = null;
    const instruction = this.retransDraft.trim();
    this.busyIds.add(id);
    this.api
      .retranslateSegment(job.id, segIndexOf(id), instruction || undefined)
      .subscribe({
        next: api => {
          this.busyIds.delete(id);
          this.absorb(sec, api);
          this.flash(
            instruction
              ? `Re-translated with instruction “${instruction}”`
              : 'Segment re-translated',
          );
        },
        error: err => {
          this.busyIds.delete(id);
          this.failed('Re-translating')(err);
        },
      });
  }

  /**
   * Dismissing is local: the finding stays on the server, but the reviewer has
   * seen it and does not want it in the way. A reload brings it back.
   */
  dismiss(sec: string, seg: Segment) {
    const list = this.segs[sec];
    const idx = list?.findIndex(s => s.id === seg.id) ?? -1;
    if (idx < 0) return;
    list[idx] = {...list[idx], finding: undefined};
    this.refreshView();
  }

  /* ── applying a glossary term across the document ───────────── */

  openTermModal(sec: string, seg: Segment) {
    const f = seg.finding;
    if (!f?.found || !f?.expected) return;
    const found = f.found;
    const hits: Array<{sec: string; seg: Segment}> = [];
    Object.entries(this.segs).forEach(([s, list]) =>
      list.forEach(candidate => {
        if (candidate.tgt.includes(found)) hits.push({sec: s, seg: candidate});
      }),
    );
    this.termInfo = {
      sec,
      segId: seg.id,
      expected: f.expected,
      found,
      hits,
      count: hits.length,
      sections: new Set(hits.map(h => h.sec)).size,
      approvedHit: hits.filter(h => h.seg.approved).length,
    };
  }

  applyTerm() {
    const info = this.termInfo;
    const job = this.job;
    if (!info || !job) return;
    this.termInfo = null;
    let done = 0;
    let failedCount = 0;
    const total = info.hits.length;
    if (!total) return;
    info.hits.forEach(hit => {
      const next = hit.seg.tgt.split(info.found).join(info.expected);
      this.api
        .updateSegment(job.id, segIndexOf(hit.seg.id), {translation: next})
        .subscribe({
          next: api => {
            this.absorb(hit.sec, api);
            if (++done + failedCount === total)
              this.termApplied(info, done, failedCount);
          },
          error: () => {
            failedCount++;
            if (done + failedCount === total)
              this.termApplied(info, done, failedCount);
          },
        });
    });
  }

  private termApplied(info: TermInfo, done: number, failedCount: number) {
    this.flash(
      failedCount
        ? `“${info.expected}” applied to ${done} segments — ${failedCount} failed`
        : `“${info.expected}” applied to ${done} segments across ${info.sections} sections`,
    );
  }

  /* ── keyboard: j/k move · a approve · e edit · esc clear ─────── */

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
      this.approve(cur.sec, cur.seg);
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

  onFileChosen(event: Event) {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (file) this.upload(file);
  }

  onDrop(e: DragEvent) {
    e.preventDefault();
    this.drag = false;
    const file = e.dataTransfer?.files?.[0];
    if (file) this.upload(file);
  }

  onDragOver(e: DragEvent) {
    e.preventDefault();
    this.drag = true;
  }

  private upload(file: File) {
    if (!file.name.toLowerCase().endsWith('.docx')) {
      this.intake = 'error';
      this.intakeError = `${file.name} is not a .docx — Word is the only format whose layout we can keep intact. If you only have a PDF, ask Finance for the Word source.`;
      return;
    }
    this.intake = 'parsing';
    this.intakeError = '';
    this.api.createJob(file).subscribe({
      next: job => {
        this.job = job;
        this.tree = chaptersFrom(job);
        this.sections = allSectionsOf(this.tree);
        this.activeSec = this.sections[0]?.id || '';
        this.intake = 'idle';
        this.setView('preflight');
        this.loadReuse();
      },
      error: err => {
        this.intake = 'error';
        const detail = (err as {error?: {detail?: string}})?.error?.detail;
        this.intakeError =
          detail ||
          `${file.name} could not be parsed. Open it in Word, save a fresh copy (File → Save As) and upload that.`;
      },
    });
  }

  /* ── preflight ──────────────────────────────────────────────── */

  get stats() {
    return this.job?.stats || {};
  }

  get sectionCount(): number {
    return this.sections.length;
  }

  get tableCount(): number {
    return this.sections.reduce((a, s) => a + (s.t || 0), 0);
  }

  get translatableCount(): number {
    return this.stats.translatable || 0;
  }

  pickTarget(code: string) {
    if (this.pfTarget === code) return;
    this.pfTarget = code;
    this.loadReuse();
  }

  loadReuse() {
    const job = this.job;
    if (!job) return;
    this.loadingReuse = true;
    this.reusePct = null;
    this.api.reuseEstimate(job.id, this.pfTarget).subscribe({
      next: est => {
        this.reusePct = est.pct;
        this.reuseTotal = est.total;
        this.reuseCount = est.reusable;
        this.loadingReuse = false;
      },
      error: err => {
        this.loadingReuse = false;
        this.failed('Estimating reuse')(err);
      },
    });
  }

  /* ── the run ────────────────────────────────────────────────── */

  startRun() {
    const job = this.job;
    if (!job) return;
    this.api.startTranslation(job.id, this.pfTarget).subscribe({
      next: updated => {
        this.job = updated;
        this.setView('run');
        this.startPolling();
      },
      error: this.failed('Starting the translation'),
    });
  }

  private startPolling() {
    this.stopPolling();
    this.poller = setInterval(() => this.pollJob(), 2500);
    this.pollJob();
  }

  private stopPolling() {
    if (this.poller) clearInterval(this.poller);
    this.poller = null;
  }

  private pollJob() {
    const job = this.job;
    if (!job) return;
    this.api.getJob(job.id).subscribe({
      next: updated => {
        this.job = updated;
        if (updated.status !== 'translating') {
          this.stopPolling();
          if (updated.status === 'review' || updated.status === 'completed') {
            this.tree = chaptersFrom(updated);
            this.sections = allSectionsOf(this.tree);
            if (!this.activeSec) this.activeSec = this.sections[0]?.id || '';
            this.loadSegments();
          }
        }
      },
      error: () => this.stopPolling(),
    });
  }

  get runProgress() {
    return this.job?.progress || null;
  }

  get runPct(): number {
    const p = this.runProgress;
    if (!p?.total) return this.job?.status === 'review' ? 100 : 0;
    return Math.round((100 * p.translated) / p.total);
  }

  get runComplete(): boolean {
    return this.job?.status === 'review' || this.job?.status === 'completed';
  }

  get runFailed(): boolean {
    return this.job?.status === 'failed';
  }

  /** Section run states for the outline while a job is translating. */
  get runStates(): Record<string, RunState> {
    const sections = this.runProgress?.sections || {};
    const out: Record<string, RunState> = {};
    for (const meta of this.sections) {
      const raw = sections[meta.id];
      out[meta.id] =
        raw === 'done' ? 'done' : raw === 'fail' ? 'fail' : 'queued';
    }
    return out;
  }

  openReview() {
    if (this.runComplete) {
      this.filter = 'attention';
      this.scope = 'section';
      this.setView('review');
    } else {
      this.backToLibrary();
    }
  }

  retryRun() {
    const job = this.job;
    if (!job) return;
    this.api
      .startTranslation(job.id, job.targetMarket || this.pfTarget)
      .subscribe({
        next: updated => {
          this.job = updated;
          this.startPolling();
        },
        error: this.failed('Retrying'),
      });
  }

  /* ── export ─────────────────────────────────────────────────── */

  get exportBlocked(): boolean {
    return this.criticals.length > 0;
  }

  doExport() {
    const job = this.job;
    if (!job) return;
    this.api.exportDocx(job.id).subscribe({
      next: res => {
        const blob = res.body;
        if (!blob) {
          this.flash('Export returned no file');
          return;
        }
        const disposition = res.headers.get('content-disposition') || '';
        const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition);
        const name = match
          ? decodeURIComponent(match[1])
          : job.filename.replace('.docx', ' — translated.docx');
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = name;
        a.click();
        window.URL.revokeObjectURL(url);
        this.exported = true;
        this.flash(`${name} downloaded`);
      },
      error: this.failed('Exporting'),
    });
  }

  /* ── glossary ───────────────────────────────────────────────── */

  get glossRows(): GlossaryRow[] {
    return this.glossDomain === 'financial' ? GLOSSARY_FIN : GLOSSARY_MKT;
  }
}
