/**
 * Copyright 2026 Google LLC — Licensed under the Apache License, Version 2.0.
 * Hunkemöller "Vertalingen" page.
 */

import {Component, OnInit} from '@angular/core';
import {MatSnackBar} from '@angular/material/snack-bar';
import {
  Briefing,
  BriefingFeedback,
  BriefingSegment,
  FeedbackStatus,
  FeedbackTicket,
  MarketOverview,
  MarketTranslation,
  TranslationService,
} from '../services/translation.service';
import {handleErrorSnackbar} from '../utils/handleMessageSnackbar';

interface MarketMeta {
  code: string;
  label: string;
  group: string;
  variant?: boolean;
  source?: boolean;
}

interface FieldVM {
  id: string;
  block: string;
  name: string;
  limit: number | null;
  text: string;
}

interface BriefingVM {
  id: number | null;
  name: string;
  requestor: string;
  due: string;
  notes: string;
  fields: FieldVM[];
}

interface MarketState {
  status: 'loading' | 'done' | 'error';
  texts: Record<string, string>; // fieldId -> translated text
  approval: 'pending' | 'approved' | 'changes' | 'rejected';
  comment?: string;
}

interface LibItem {
  id: number;
  name: string;
  fields: number;
  date: string;
  status: 'draft' | 'review' | 'approved' | 'changes';
}

const MARKETS: MarketMeta[] = [
  {code: 'EN', label: 'English (source)', group: 'Source', source: true},
  {code: 'UK', label: 'English (UK)', group: 'English'},
  {code: 'NL', label: 'Dutch (Netherlands)', group: 'Dutch'},
  {code: 'BENL', label: 'Dutch (Belgium)', group: 'Dutch', variant: true},
  {code: 'BEFR', label: 'French (Belgium)', group: 'French', variant: true},
  {code: 'FR', label: 'French (France)', group: 'French'},
  {code: 'LU', label: 'French (Luxembourg)', group: 'French'},
  {code: 'CHFR', label: 'French (Switzerland)', group: 'French', variant: true},
  {code: 'CHDE', label: 'German (Switzerland)', group: 'German', variant: true},
  {code: 'DE', label: 'German (Germany)', group: 'German'},
  {code: 'AT', label: 'German (Austria)', group: 'German', variant: true},
  {code: 'DK', label: 'Danish (Denmark)', group: 'Scandinavian'},
  {code: 'ES', label: 'Spanish (Spain)', group: 'Southern Europe'},
  {code: 'SE', label: 'Swedish (Sweden)', group: 'Scandinavian'},
  {code: 'NO', label: 'Norwegian (Norway)', group: 'Scandinavian'},
];
const MARKET_GROUPS = ['English', 'Dutch', 'French', 'German', 'Scandinavian', 'Southern Europe'];

@Component({
  selector: 'app-translations',
  templateUrl: './translations.component.html',
  styleUrls: ['./translations.component.scss'],
})
export class TranslationsComponent implements OnInit {
  readonly markets = MARKETS;
  readonly groups = MARKET_GROUPS;
  readonly bars = [0, 1, 2, 3, 4, 5, 6, 7];
  readonly targets = MARKETS.filter(m => !m.source);

  view: 'empty' | 'intake' | 'work' | 'dict' = 'empty';
  workTab: 'briefing' | 'results' = 'briefing';
  toast = '';

  // library
  library: LibItem[] = [];
  librarySearch = '';
  renamingId: number | null = null;
  renameValue = '';

  // intake
  selectedFile: File | null = null;
  sheets: string[] = [];
  selectedSheet = '';
  requests: {index: number; label: string; filled: number}[] = [];
  selectedRequestIndex: number | null = null;
  isUploading = false;
  fileName = '';

  // working briefing
  briefing: BriefingVM | null = null;
  marketFilter = '';
  selected: string[] = [];
  tone: 'informeel' | 'formeel' = 'informeel';
  metaOpen = false;

  // results
  mstate: Record<string, MarketState> = {};
  active = '';
  retranslating = new Set<string>();
  commentingMarket = false;
  commentDraft = '';

  // feedback loop (persisted, per item + per market)
  feedback: BriefingFeedback | null = null;
  ticketFilter: 'all' | FeedbackStatus = 'all';
  ticketDrafts: Record<string, string> = {}; // `${market}:${index}` -> draft
  // Minted links, kept client-side: the raw token is only returned once.
  shareInfo: Record<string, {url: string; expiresAt: string}> = {};

  // dictionary
  glossaryTotal = 0;
  glossaryPerMarket: {market: string; count: number}[] = [];
  dictMarket = 'NL';
  dictTerms: {id: number; source: string; target: string}[] = [];
  dictQuery = '';
  newSource = '';
  newTarget = '';

  constructor(
    private service: TranslationService,
    private snackBar: MatSnackBar,
  ) {}

  ngOnInit(): void {
    this.loadLibrary();
    this.service.getGlossarySummary().subscribe({
      next: s => {
        this.glossaryTotal = s.total;
        this.glossaryPerMarket = s.perMarket.map(p => ({market: p.market, count: p.count}));
      },
      error: () => {},
    });
  }

  flash(m: string): void {
    this.toast = m;
    setTimeout(() => (this.toast = ''), 2200);
  }

  marketLabel(code: string): string {
    return this.markets.find(m => m.code === code)?.label ?? code;
  }

  // ── library ────────────────────────────────────────────────────
  loadLibrary(): void {
    this.service.listBriefings().subscribe({
      next: list =>
        (this.library = list.map(b => ({
          id: (b as any).id,
          name: b.name,
          fields: b.segments?.length ?? 0,
          date: this.fmtDate((b as any).createdAt),
          status: 'draft' as const,
        }))),
      error: () => {},
    });
  }

  fmtDate(iso?: string): string {
    if (!iso) return '';
    try {
      return new Date(iso).toLocaleDateString('nl-NL', {day: 'numeric', month: 'short'});
    } catch {
      return '';
    }
  }

  get filteredLibrary(): LibItem[] {
    const q = this.librarySearch.toLowerCase();
    return q ? this.library.filter(b => b.name.toLowerCase().includes(q)) : this.library;
  }

  openBriefing(id: number): void {
    this.service.getBriefing(id).subscribe({
      next: res => {
        this.briefing = this.fromBackend(res.briefing, id);
        this.mstate = {};
        const codes: string[] = [];
        (res.translations || []).forEach(tr => {
          codes.push(tr.market);
          const stored = (tr as any).status as string | undefined;
          const approval = (['approved', 'changes', 'rejected'].includes(stored ?? '')
            ? stored
            : 'pending') as MarketState['approval'];
          this.mstate[tr.market] = {
            status: 'done',
            approval,
            comment: (tr as any).comment ?? undefined,
            texts: this.textsFromSegments(tr.segments),
          };
        });
        this.selected = codes;
        this.active = codes[0] ?? '';
        this.workTab = codes.length ? 'results' : 'briefing';
        this.view = 'work';
        this.feedback = null;
        this.shareInfo = {};
        this.loadFeedback();
      },
      error: err => handleErr(this.snackBar, err, 'Could not open briefing'),
    });
  }

  duplicateBriefing(b: LibItem, ev: Event): void {
    ev.stopPropagation();
    this.service.getBriefing(b.id).subscribe({
      next: res => {
        const copy = {...res.briefing, name: res.briefing.name + ' (copy)'};
        this.service.save(copy, []).subscribe({
          next: () => {
            this.flash('Briefing duplicated');
            this.loadLibrary();
          },
          error: err => handleErr(this.snackBar, err, 'Duplication failed'),
        });
      },
      error: err => handleErr(this.snackBar, err, 'Duplication failed'),
    });
  }

  startRename(b: LibItem, ev: Event): void {
    ev.stopPropagation();
    this.renamingId = b.id;
    this.renameValue = b.name;
  }

  commitRename(b: LibItem): void {
    const name = this.renameValue.trim();
    this.renamingId = null;
    if (!name || name === b.name) return;
    this.service.renameBriefing(b.id, name).subscribe({
      next: () => {
        b.name = name;
        if (this.briefing?.id === b.id) this.briefing.name = name;
      },
      error: err => handleErr(this.snackBar, err, 'Rename failed'),
    });
  }

  deleteBriefing(b: LibItem, ev: Event): void {
    ev.stopPropagation();
    this.service.deleteBriefing(b.id).subscribe({
      next: () => {
        this.library = this.library.filter(x => x.id !== b.id);
        if (this.briefing?.id === b.id) {
          this.briefing = null;
          this.view = 'empty';
        }
        this.flash('Briefing deleted');
      },
      error: err => handleErr(this.snackBar, err, 'Delete failed'),
    });
  }

  // ── intake / new ───────────────────────────────────────────────
  startBlank(): void {
    this.briefing = {
      id: null,
      name: 'New briefing',
      requestor: '',
      due: '',
      notes: '',
      fields: [
        {id: fid(), block: 'B1', name: 'Subject line', limit: 50, text: ''},
        {id: fid(), block: 'B1', name: 'Pre-header', limit: 90, text: ''},
        {id: fid(), block: 'B2', name: 'Header', limit: 34, text: ''},
        {id: fid(), block: 'B2', name: 'Body', limit: 320, text: ''},
        {id: fid(), block: 'B2', name: 'CTA', limit: 22, text: ''},
      ],
    };
    this.mstate = {};
    this.selected = [];
    this.workTab = 'briefing';
    this.view = 'work';
  }

  onFileSelected(ev: Event): void {
    const input = ev.target as HTMLInputElement;
    const file = input.files?.[0] ?? null;
    if (!file) return;
    this.selectedFile = file;
    this.fileName = file.name;
    this.selectedRequestIndex = null;
    this.isUploading = true;
    this.service.upload(file).subscribe({
      next: res => {
        this.sheets = res.sheets;
        this.selectedSheet = res.selectedSheet ?? res.sheets[0] ?? '';
        this.requests = res.requests;
        this.isUploading = false;
        this.view = 'intake';
        if (res.sheets.includes('Translation Memories')) this.autoImportTm(file);
      },
      error: err => {
        this.isUploading = false;
        handleErr(this.snackBar, err, 'Upload failed');
      },
    });
  }

  onSheetChange(): void {
    if (!this.selectedFile) return;
    this.selectedRequestIndex = null;
    this.isUploading = true;
    this.service.upload(this.selectedFile, this.selectedSheet).subscribe({
      next: res => {
        this.requests = res.requests;
        this.isUploading = false;
      },
      error: err => {
        this.isUploading = false;
        handleErr(this.snackBar, err, 'Kon blad niet lezen');
      },
    });
  }

  private autoImportTm(file: File): void {
    this.service.importTranslationMemory(file).subscribe({
      next: () =>
        this.service.getGlossarySummary().subscribe(s => {
          this.glossaryTotal = s.total;
          this.glossaryPerMarket = s.perMarket.map(p => ({market: p.market, count: p.count}));
        }),
      error: () => {},
    });
  }

  get selectedRequest() {
    return this.requests.find(r => r.index === this.selectedRequestIndex);
  }

  confirmIntake(): void {
    if (!this.selectedFile || this.selectedRequestIndex == null) return;
    this.isUploading = true;
    this.service
      .upload(this.selectedFile, this.selectedSheet, this.selectedRequestIndex)
      .subscribe({
        next: res => {
          this.isUploading = false;
          this.briefing = {
            id: null,
            name: res.briefingName ?? 'Briefing',
            requestor: res.meta?.requestor ?? '',
            due: res.meta?.due ?? '',
            notes: res.meta?.notes ?? '',
            fields: res.segments.map((s, i) => ({
              id: 'f' + i,
              block: s.block ?? 'B1',
              name: s.field,
              limit: s.charLimit,
              text: s.text,
            })),
          };
          this.mstate = {};
          this.selected = [];
          this.workTab = 'briefing';
          this.view = 'work';
        },
        error: err => {
          this.isUploading = false;
          handleErr(this.snackBar, err, 'Could not load request');
        },
      });
  }

  // ── briefing editor ────────────────────────────────────────────
  get blocks(): string[] {
    return [...new Set((this.briefing?.fields ?? []).map(f => f.block))];
  }
  fieldsInBlock(block: string): FieldVM[] {
    return (this.briefing?.fields ?? []).filter(f => f.block === block);
  }
  addField(block: string): void {
    this.briefing?.fields.push({id: fid(), block, name: 'Nieuw veld', limit: 80, text: ''});
  }
  addBlock(): void {
    const n = 'B' + (this.blocks.length + 1);
    this.briefing?.fields.push({id: fid(), block: n, name: 'Header', limit: 40, text: ''});
  }
  removeField(f: FieldVM): void {
    if (this.briefing) this.briefing.fields = this.briefing.fields.filter(x => x.id !== f.id);
  }

  // ── market selection ───────────────────────────────────────────
  groupTargets(g: string): MarketMeta[] {
    const q = this.marketFilter.toLowerCase();
    return this.targets.filter(
      m => m.group === g && (!q || m.code.toLowerCase().includes(q) || m.label.toLowerCase().includes(q)),
    );
  }
  isSelected(code: string): boolean {
    return this.selected.includes(code);
  }
  toggleMarket(code: string): void {
    this.selected = this.isSelected(code)
      ? this.selected.filter(c => c !== code)
      : [...this.selected, code];
  }
  selectAllMarkets(): void {
    this.selected =
      this.selected.length === this.targets.length ? [] : this.targets.map(m => m.code);
  }
  get allSelected(): boolean {
    return this.selected.length === this.targets.length;
  }

  // ── translate ──────────────────────────────────────────────────
  get hasResults(): boolean {
    return Object.keys(this.mstate).length > 0;
  }
  goResults(): void {
    if (this.hasResults) this.workTab = 'results';
  }
  get isTranslating(): boolean {
    return Object.values(this.mstate).some(s => s.status === 'loading');
  }
  get doneCount(): number {
    return this.selected.filter(c => this.mstate[c]?.status === 'done').length;
  }
  get apprCount(): number {
    return this.selected.filter(c => this.mstate[c]?.approval === 'approved').length;
  }

  translate(): void {
    if (!this.briefing || this.selected.length === 0) return;
    this.mstate = {};
    this.selected.forEach(c => (this.mstate[c] = {status: 'loading', approval: 'pending', texts: {}}));
    this.active = this.selected[0];
    this.workTab = 'results';
    const backend = this.toBackend(this.briefing);
    this.selected.forEach(code => {
      this.service.translate(backend, [code], this.tone).subscribe({
        next: res => {
          const tr = res.translations[0];
          this.mstate[code] = {
            status: 'done',
            approval: 'pending',
            texts: tr ? this.textsFromSegments(tr.segments) : {},
          };
          if (!this.isTranslating) this.persist(true); // save once all done
        },
        error: () => {
          this.mstate[code] = {status: 'error', approval: 'pending', texts: {}};
          if (!this.isTranslating) this.persist(true);
        },
      });
    });
  }

  retryMarket(code: string): void {
    if (!this.briefing) return;
    this.mstate[code] = {status: 'loading', approval: 'pending', texts: {}};
    const backend = this.toBackend(this.briefing);
    this.service.translate(backend, [code], this.tone).subscribe({
      next: res => {
        const tr = res.translations[0];
        this.mstate[code] = {status: 'done', approval: 'pending', texts: tr ? this.textsFromSegments(tr.segments) : {}};
      },
      error: () => (this.mstate[code] = {status: 'error', approval: 'pending', texts: {}}),
    });
  }

  retranslateField(code: string, f: FieldVM): void {
    if (!this.briefing) return;
    const key = `${code}:${f.id}`;
    this.retranslating.add(key);
    const single: Briefing = {
      name: this.briefing.name,
      sourceMarket: 'EN',
      meta: {},
      segments: [{block: f.block, field: f.name, label: f.name, charLimit: f.limit, text: f.text}],
    };
    this.service.translate(single, [code], this.tone).subscribe({
      next: res => {
        const seg = res.translations[0]?.segments[0];
        if (seg && this.mstate[code]) this.mstate[code].texts[f.id] = seg.text;
        this.retranslating.delete(key);
      },
      error: () => {
        this.retranslating.delete(key);
        handleErr(this.snackBar, null, 'Re-translation failed');
      },
    });
  }

  isRetranslating(code: string, f: FieldVM): boolean {
    return this.retranslating.has(`${code}:${f.id}`);
  }

  textFor(code: string, f: FieldVM): string {
    return this.mstate[code]?.texts[f.id] ?? '';
  }
  setTextFor(code: string, f: FieldVM, val: string): void {
    if (this.mstate[code]) this.mstate[code].texts[f.id] = val;
  }
  over(code: string, f: FieldVM): boolean {
    return !!f.limit && this.textFor(code, f).length > f.limit;
  }

  // ── approval (client-side, market scope) ───────────────────────
  approveMarket(code: string): void {
    if (this.mstate[code]) this.mstate[code].approval = 'approved';
    this.flash(`${code} goedgekeurd · opgeslagen`);
    this.persist(true);
  }
  rejectMarket(code: string): void {
    if (this.mstate[code]) this.mstate[code].approval = 'rejected';
    this.persist(true);
  }
  startComment(): void {
    this.commentingMarket = true;
    this.commentDraft = this.mstate[this.active]?.comment ?? '';
  }
  saveComment(): void {
    if (this.mstate[this.active]) {
      this.mstate[this.active].approval = 'changes';
      this.mstate[this.active].comment = this.commentDraft;
    }
    this.commentingMarket = false;
    this.persist(true);
  }

  // ── feedback loop (persisted tickets + share links) ─────────────
  /** Feedback requires a saved briefing (needs an id for the API). */
  get feedbackReady(): boolean {
    return !!this.briefing?.id;
  }

  loadFeedback(): void {
    if (!this.briefing?.id) {
      this.feedback = null;
      return;
    }
    this.service.getFeedback(this.briefing.id).subscribe({
      next: fb => (this.feedback = fb),
      error: () => (this.feedback = null),
    });
  }

  marketOverview(code: string): MarketOverview | undefined {
    return this.feedback?.markets.find(m => m.market === code);
  }

  reviewStateLabel(code: string): string {
    const s = this.marketOverview(code)?.reviewState;
    return s === 'in_review' ? 'In review' : s === 'done' ? 'Done' : 'Draft';
  }

  linkStatusLabel(code: string): string {
    const s = this.marketOverview(code)?.linkStatus;
    return s === 'active'
      ? 'Link active'
      : s === 'expired'
        ? 'Link expired'
        : s === 'revoked'
          ? 'Link revoked'
          : 'No active link';
  }

  draftKey(code: string, index: number): string {
    return `${code}:${index}`;
  }

  allTicketsFor(code: string, index: number): FeedbackTicket[] {
    return (this.feedback?.tickets ?? []).filter(
      t => t.market === code && t.segmentIndex === index,
    );
  }

  ticketsFor(code: string, index: number): FeedbackTicket[] {
    const all = this.allTicketsFor(code, index);
    return this.ticketFilter === 'all'
      ? all
      : all.filter(t => t.status === this.ticketFilter);
  }

  openCountFor(code: string, index: number): number {
    return this.allTicketsFor(code, index).filter(
      t => t.status !== 'resolved',
    ).length;
  }

  resolvedCountFor(code: string, index: number): number {
    return this.allTicketsFor(code, index).filter(t => t.status === 'resolved')
      .length;
  }

  addTicket(code: string, index: number): void {
    if (!this.briefing?.id) {
      this.flash('Save the briefing first');
      return;
    }
    const key = this.draftKey(code, index);
    const body = (this.ticketDrafts[key] ?? '').trim();
    if (!body) return;
    this.service
      .createTicket(this.briefing.id, code, {segmentIndex: index, body})
      .subscribe({
        next: () => {
          this.ticketDrafts[key] = '';
          this.loadFeedback();
        },
        error: err => handleErr(this.snackBar, err, 'Failed to add comment'),
      });
  }

  setTicketStatus(t: FeedbackTicket, status: FeedbackStatus): void {
    this.service.updateTicket(t.id, {status}).subscribe({
      next: () => this.loadFeedback(),
      error: err => handleErr(this.snackBar, err, 'Failed to update status'),
    });
  }

  ticketStatusLabel(s: FeedbackStatus): string {
    return s === 'open' ? 'Open' : s === 'in_progress' ? 'In progress' : 'Resolved';
  }

  ticketStatusColor(s: FeedbackStatus): string {
    return s === 'resolved' ? '#7AAE88' : s === 'in_progress' ? '#D99A40' : '#C77';
  }

  requestLink(code: string): void {
    if (!this.briefing?.id) {
      this.flash('Save the briefing first');
      return;
    }
    this.service.createShareLink(this.briefing.id, code).subscribe({
      next: link => {
        const url = `${window.location.origin}/feedback/${link.token}`;
        this.shareInfo[code] = {url, expiresAt: link.expiresAt};
        this.copyText(url);
        this.flash('Translator link copied · valid for 3 days');
        this.loadFeedback();
      },
      error: err => handleErr(this.snackBar, err, 'Failed to create link'),
    });
  }

  copyLink(code: string): void {
    const url = this.shareInfo[code]?.url;
    if (url) {
      this.copyText(url);
      this.flash('Link copied');
    }
  }

  revokeLink(code: string): void {
    if (!this.briefing?.id) return;
    this.service.revokeShareLink(this.briefing.id, code).subscribe({
      next: () => {
        delete this.shareInfo[code];
        this.flash('Link revoked');
        this.loadFeedback();
      },
      error: err => handleErr(this.snackBar, err, 'Failed to revoke'),
    });
  }

  markReviewDone(code: string): void {
    if (!this.briefing?.id) return;
    this.service.setReviewState(this.briefing.id, code, 'done').subscribe({
      next: () => this.loadFeedback(),
      error: err => handleErr(this.snackBar, err, 'Update failed'),
    });
  }

  /** Tab-separated copy of the active market, ready to paste into Excel. */
  copyTsv(): void {
    if (!this.briefing) return;
    const esc = (s: string | number | null) =>
      String(s ?? '')
        .replace(/\t/g, ' ')
        .replace(/\r?\n/g, ' ');
    const rows = [
      ['Block', 'Field', 'Label', 'Limit', 'Source (EN)', `Translation ${this.active}`]
        .join('\t'),
    ];
    for (const f of this.briefing.fields) {
      rows.push(
        [
          f.block,
          f.name,
          f.name,
          f.limit ?? '',
          esc(f.text),
          esc(this.textFor(this.active, f)),
        ].join('\t'),
      );
    }
    this.copyText(rows.join('\n'));
    this.flash('Copied — paste into Excel');
  }

  private copyText(text: string): void {
    void navigator.clipboard?.writeText(text).catch(() => {});
  }

  approvalLabel(code: string): string {
    const a = this.mstate[code]?.approval;
    return a === 'approved'
      ? 'Approved'
      : a === 'changes'
        ? 'Changes'
        : a === 'rejected'
          ? 'Rejected'
          : 'Awaiting review';
  }
  approvalDot(code: string): string {
    const a = this.mstate[code]?.approval;
    return a === 'approved' ? '#7AAE88' : a === 'changes' ? '#C77' : a === 'rejected' ? '#B55' : '#D99A40';
  }

  // ── save / export ──────────────────────────────────────────────
  private translationsPayload(): MarketTranslation[] {
    return this.selected
      .filter(c => this.mstate[c]?.status === 'done')
      .map(c => ({
        market: c,
        approval: this.mstate[c].approval,
        comment: this.mstate[c].comment,
        segments: (this.briefing?.fields ?? []).map(f => ({
          block: f.block,
          field: f.name,
          label: f.name,
          charLimit: f.limit,
          text: this.mstate[c].texts[f.id] ?? '',
        })),
      }));
  }

  /** Persist the briefing + translations. silent → no toast (auto-save). */
  private persist(silent = false): void {
    if (!this.briefing) return;
    this.service.save(this.toBackend(this.briefing), this.translationsPayload()).subscribe({
      next: res => {
        // Capture the new id so feedback can be requested without reopening.
        if (res?.id != null && this.briefing) this.briefing.id = res.id;
        if (!silent) this.flash('Briefing saved');
        this.loadLibrary();
        this.loadFeedback();
      },
      error: err => {
        if (!silent) handleErr(this.snackBar, err, 'Save failed');
      },
    });
  }

  save(): void {
    this.persist(false);
  }

  exportXlsx(): void {
    if (!this.briefing) return;
    this.service.exportXlsx(this.toBackend(this.briefing), this.translationsPayload()).subscribe({
      next: blob => {
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${this.briefing?.name ?? 'briefing'}.xlsx`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
        this.flash('Exported to .xlsx');
      },
      error: err => handleErr(this.snackBar, err, 'Export failed'),
    });
  }

  // ── dictionary ─────────────────────────────────────────────────
  openDict(): void {
    this.view = 'dict';
    this.loadDictTerms();
  }
  loadDictTerms(): void {
    this.service.getGlossaryTerms(this.dictMarket, this.dictQuery || undefined).subscribe({
      next: t => (this.dictTerms = t),
      error: () => {},
    });
  }
  addDictTerm(): void {
    const s = this.newSource.trim();
    const t = this.newTarget.trim();
    if (!s || !t) return;
    this.service.createGlossaryTerm(this.dictMarket, s, t).subscribe({
      next: term => {
        this.dictTerms = [{id: term.id, source: term.source, target: term.target}, ...this.dictTerms];
        this.newSource = '';
        this.newTarget = '';
      },
      error: err => handleErr(this.snackBar, err, 'Failed to add term'),
    });
  }
  saveDictTerm(t: {id: number; source: string; target: string}): void {
    this.service.updateGlossaryTerm(t.id, {source: t.source, target: t.target}).subscribe({error: () => {}});
  }
  deleteDictTerm(t: {id: number}): void {
    this.service.deleteGlossaryTerm(t.id).subscribe({
      next: () => (this.dictTerms = this.dictTerms.filter(x => x.id !== t.id)),
      error: () => {},
    });
  }

  // ── mapping helpers ────────────────────────────────────────────
  private toBackend(vm: BriefingVM): Briefing {
    return {
      id: vm.id ?? undefined,
      name: vm.name,
      sourceMarket: 'EN',
      meta: {requestor: vm.requestor, due: vm.due, notes: vm.notes},
      segments: vm.fields.map(f => ({
        block: f.block,
        field: f.name,
        label: f.name,
        charLimit: f.limit,
        text: f.text,
      })),
    };
  }
  private fromBackend(b: Briefing, id: number): BriefingVM {
    return {
      id,
      name: b.name,
      requestor: b.meta?.requestor ?? '',
      due: b.meta?.due ?? '',
      notes: b.meta?.notes ?? '',
      fields: (b.segments ?? []).map((s, i) => ({
        id: 'f' + i,
        block: s.block ?? 'B1',
        name: s.field,
        limit: s.charLimit,
        text: s.text,
      })),
    };
  }
  private textsFromSegments(segs: BriefingSegment[]): Record<string, string> {
    const out: Record<string, string> = {};
    (segs ?? []).forEach((s, i) => (out['f' + i] = s.text));
    return out;
  }
}

let _fid = 0;
function fid(): string {
  return 'nf' + Date.now() + '_' + _fid++;
}

function handleErr(sb: MatSnackBar, err: any, ctx: string): void {
  handleErrorSnackbar(sb, err ?? {}, ctx);
}
