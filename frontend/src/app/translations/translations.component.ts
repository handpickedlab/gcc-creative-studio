/**
 * Copyright 2026 Google LLC — Licensed under the Apache License, Version 2.0.
 * Hunkemöller "Vertalingen" page.
 */

import {Component, OnInit} from '@angular/core';
import {MatSnackBar} from '@angular/material/snack-bar';
import {
  Briefing,
  BriefingSegment,
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
  {code: 'EN', label: 'English (bron)', group: 'Bron', source: true},
  {code: 'UK', label: 'English (UK)', group: 'Engels'},
  {code: 'NL', label: 'Nederlands (Nederland)', group: 'Nederlands'},
  {code: 'BENL', label: 'Nederlands (België)', group: 'Nederlands', variant: true},
  {code: 'BEFR', label: 'Français (België)', group: 'Frans', variant: true},
  {code: 'FR', label: 'Français (Frankrijk)', group: 'Frans'},
  {code: 'LU', label: 'Français (Luxemburg)', group: 'Frans'},
  {code: 'CHFR', label: 'Français (Zwitserland)', group: 'Frans', variant: true},
  {code: 'CHDE', label: 'Deutsch (Zwitserland)', group: 'Duits', variant: true},
  {code: 'DE', label: 'Deutsch (Duitsland)', group: 'Duits'},
  {code: 'AT', label: 'Deutsch (Oostenrijk)', group: 'Duits', variant: true},
  {code: 'DK', label: 'Dansk (Denemarken)', group: 'Scandinavië'},
  {code: 'ES', label: 'Español (Spanje)', group: 'Zuid-Europa'},
  {code: 'SE', label: 'Svenska (Zweden)', group: 'Scandinavië'},
  {code: 'NO', label: 'Norsk (Noorwegen)', group: 'Scandinavië'},
];
const MARKET_GROUPS = ['Engels', 'Nederlands', 'Frans', 'Duits', 'Scandinavië', 'Zuid-Europa'];

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
          this.mstate[tr.market] = {
            status: 'done',
            approval: 'pending',
            texts: this.textsFromSegments(tr.segments),
          };
        });
        this.selected = codes;
        this.active = codes[0] ?? '';
        this.workTab = codes.length ? 'results' : 'briefing';
        this.view = 'work';
      },
      error: err => handleErr(this.snackBar, err, 'Kon briefing niet openen'),
    });
  }

  duplicateBriefing(b: LibItem, ev: Event): void {
    ev.stopPropagation();
    this.service.getBriefing(b.id).subscribe({
      next: res => {
        const copy = {...res.briefing, name: res.briefing.name + ' (kopie)'};
        this.service.save(copy, []).subscribe({
          next: () => {
            this.flash('Briefing gedupliceerd');
            this.loadLibrary();
          },
          error: err => handleErr(this.snackBar, err, 'Dupliceren mislukt'),
        });
      },
      error: err => handleErr(this.snackBar, err, 'Dupliceren mislukt'),
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
      error: err => handleErr(this.snackBar, err, 'Hernoemen mislukt'),
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
        this.flash('Briefing verwijderd');
      },
      error: err => handleErr(this.snackBar, err, 'Verwijderen mislukt'),
    });
  }

  // ── intake / new ───────────────────────────────────────────────
  startBlank(): void {
    this.briefing = {
      id: null,
      name: 'Nieuwe briefing',
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
        handleErr(this.snackBar, err, 'Upload mislukt');
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
          handleErr(this.snackBar, err, 'Kon request niet laden');
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
        },
        error: () => {
          this.mstate[code] = {status: 'error', approval: 'pending', texts: {}};
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
        handleErr(this.snackBar, null, 'Opnieuw vertalen mislukt');
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
    this.flash(`${code} goedgekeurd`);
  }
  rejectMarket(code: string): void {
    if (this.mstate[code]) this.mstate[code].approval = 'rejected';
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
  }

  approvalLabel(code: string): string {
    const a = this.mstate[code]?.approval;
    return a === 'approved'
      ? 'Goedgekeurd'
      : a === 'changes'
        ? 'Wijzigingen'
        : a === 'rejected'
          ? 'Afgekeurd'
          : 'Wacht op review';
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
        segments: (this.briefing?.fields ?? []).map(f => ({
          block: f.block,
          field: f.name,
          label: f.name,
          charLimit: f.limit,
          text: this.mstate[c].texts[f.id] ?? '',
        })),
      }));
  }

  save(): void {
    if (!this.briefing) return;
    this.service.save(this.toBackend(this.briefing), this.translationsPayload()).subscribe({
      next: () => {
        this.flash('Briefing opgeslagen');
        this.loadLibrary();
      },
      error: err => handleErr(this.snackBar, err, 'Opslaan mislukt'),
    });
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
        this.flash('Geëxporteerd naar .xlsx');
      },
      error: err => handleErr(this.snackBar, err, 'Export mislukt'),
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
      error: err => handleErr(this.snackBar, err, 'Term toevoegen mislukt'),
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
