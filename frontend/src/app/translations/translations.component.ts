/**
 * Copyright 2026 Google LLC — Licensed under the Apache License, Version 2.0.
 * Hunkemöller "Translations" page.
 */

import {Component, OnInit} from '@angular/core';
import {MatSnackBar} from '@angular/material/snack-bar';
import {
  Briefing,
  BriefingFeedback,
  BriefingMeta,
  BriefingSegment,
  FeedbackStatus,
  FeedbackTicket,
  Formality,
  LanguageConfig,
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
  type?: string; // block | push | sms | banner | social
  translate?: boolean; // include this field in the translation (default true)
  loose?: boolean; // intake-only: copy that sits outside the e-mail blocks (push/SMS/banner/social)
}

interface TokenPart {
  kind: 'text' | 'tag' | 'ph';
  v: string;
}

interface FieldType {
  key: string;
  tag: string;
  label: string;
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

const FIELD_TYPES: FieldType[] = [
  {key: 'block', tag: 'B', label: 'E-mail block'},
  {key: 'push', tag: 'PUSH', label: 'Push notification'},
  {key: 'sms', tag: 'SMS', label: 'SMS'},
  {key: 'banner', tag: 'BAN', label: 'Banner'},
  {key: 'social', tag: 'SOC', label: 'Social'},
];
// Free-text guidance lines a user can one-click append to a language profile.
const GUIDANCE_SNIPPETS = [
  'Keep brand, product and collection names untranslated.',
  'Respect the character limit per field.',
  'Preserve HTML tags and [placeholders] exactly.',
  'Use the dictionary for recurring terms.',
  'No emoji.',
  'Prefer short, punchy sentences.',
];

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
  readonly fieldTypes = FIELD_TYPES;
  readonly looseTypes = FIELD_TYPES.filter(t => t.key !== 'block');
  readonly guidanceSnippets = GUIDANCE_SNIPPETS;

  view: 'empty' | 'intake' | 'work' | 'dict' | 'lang' = 'empty';
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
  isUploading = false; // busy on file upload / sheet switch
  loadingRequest = false; // busy fetching the selected request's segments
  fileName = '';
  intakeName = '';
  intakeMeta: BriefingMeta | null = null;
  intakeFields: FieldVM[] = []; // selectable rows for the currently opened request
  showAddCustom = false;
  customRow: {name: string; text: string; type: string} = {name: '', text: '', type: 'block'};

  // working briefing
  briefing: BriefingVM | null = null;
  marketFilter = '';
  selected: string[] = [];
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
  dictTerms: {id: number; source: string; target: string; doNotTranslate: boolean}[] = [];
  dictQuery = '';
  newSource = '';
  newTarget = '';
  newDnt = false;

  // language settings (per-language localization profiles)
  readonly formalities: {value: Formality; label: string}[] = [
    {value: 'default', label: 'Default (natural register)'},
    {value: 'formal', label: 'Formal (vous / Sie / u)'},
    {value: 'informal', label: 'Informal (tu / du / je)'},
  ];
  langConfigs: Record<string, LanguageConfig> = {};
  langSaving = new Set<string>();
  langLoaded = false;
  langActive = 'NL'; // selected language in the Instructies rail

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
        this.revealNotes();
        this.mstate = {};
        const fields = this.briefing.fields;
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
            texts: this.textsFromSegments(fields, tr.segments),
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
        {id: fid(), block: 'B1', type: 'block', name: 'Subject line', limit: 50, text: '', translate: true},
        {id: fid(), block: 'B1', type: 'block', name: 'Pre-header', limit: 90, text: '', translate: true},
        {id: fid(), block: 'B2', type: 'block', name: 'Header', limit: 34, text: '', translate: true},
        {id: fid(), block: 'B2', type: 'block', name: 'Body', limit: 320, text: '', translate: true},
        {id: fid(), block: 'B2', type: 'block', name: 'CTA', limit: 22, text: '', translate: true},
      ],
    };
    this.revealNotes();
    this.mstate = {};
    this.selected = [];
    this.workTab = 'briefing';
    this.view = 'work';
  }

  /**
   * Notes steer the translation (they are sent to the model), but they live
   * behind the collapsed "Details" panel, so a note carried in from the
   * uploaded sheet was invisible unless you happened to open it. Opening the
   * panel when there is something to read makes it findable; the flag in the
   * meta row keeps it findable after you close it again.
   */
  private revealNotes(): void {
    if (this.briefing?.notes?.trim()) this.metaOpen = true;
  }
  get hasNotes(): boolean {
    return !!this.briefing?.notes?.trim();
  }

  onFileSelected(ev: Event): void {
    const input = ev.target as HTMLInputElement;
    const file = input.files?.[0] ?? null;
    if (!file) return;
    this.selectedFile = file;
    this.fileName = file.name;
    this.selectedRequestIndex = null;
    this.intakeFields = [];
    this.showAddCustom = false;
    this.isUploading = true;
    this.service.upload(file).subscribe({
      next: res => {
        this.sheets = res.sheets;
        this.selectedSheet = res.selectedSheet ?? res.sheets[0] ?? '';
        // The Translation-Memories tab is a dictionary, not a briefing source —
        // never surface it as a request list.
        this.requests = this.isTm(this.selectedSheet) ? [] : res.requests;
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

  /** Sheet tabs across the top of the intake screen (design requirement). */
  selectSheet(sheet: string): void {
    this.selectedSheet = sheet;
    this.selectedRequestIndex = null;
    this.intakeFields = [];
    this.showAddCustom = false;
    if (!this.selectedFile || this.isTm(sheet)) {
      this.requests = [];
      return;
    }
    this.isUploading = true;
    this.service.upload(this.selectedFile, sheet).subscribe({
      next: res => {
        this.requests = res.requests;
        this.isUploading = false;
      },
      error: err => {
        this.isUploading = false;
        handleErr(this.snackBar, err, 'Could not read sheet');
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

  /** Translation-Memories sheets are a merged dictionary, not a briefing —
   * heuristic on the sheet name since the backend has no dedicated flag. */
  isTm(sheet: string): boolean {
    return /translation\s*memor/i.test(sheet);
  }
  get isTmSheet(): boolean {
    return this.isTm(this.selectedSheet);
  }

  get selectedRequest() {
    return this.requests.find(r => r.index === this.selectedRequestIndex);
  }

  /** Loose copy (push / SMS / banner / social) sits outside the e-mail
   * blocks — no backend flag for this, so we heuristically detect it from
   * the segment having no block, or its field/label naming the channel. */
  private isLooseSegment(s: BriefingSegment): boolean {
    const hay = `${s.field ?? ''} ${s.label ?? ''}`.toLowerCase();
    return !s.block || /push|sms|banner|social/i.test(hay);
  }
  private guessType(s: BriefingSegment): string {
    const hay = `${s.field ?? ''} ${s.label ?? ''}`.toLowerCase();
    if (/sms/.test(hay)) return 'sms';
    if (/push/.test(hay)) return 'push';
    if (/banner/.test(hay)) return 'banner';
    if (/social/.test(hay)) return 'social';
    return 'block';
  }
  private segmentToRow(s: BriefingSegment, i: number): FieldVM {
    const loose = this.isLooseSegment(s);
    return {
      id: 'f' + i,
      block: s.block ?? '',
      type: this.guessType(s),
      name: s.field,
      limit: s.charLimit,
      text: s.text,
      // Loose copy is unchecked by default — the user must opt in.
      translate: !loose,
      loose,
    };
  }

  /** Selecting a request fetches its segments and renders them as
   * selectable rows (include checkbox, tokenized source text, type select). */
  selectRequest(index: number): void {
    if (!this.selectedFile) return;
    this.selectedRequestIndex = index;
    this.intakeFields = [];
    this.showAddCustom = false;
    this.loadingRequest = true;
    this.service.upload(this.selectedFile, this.selectedSheet, index).subscribe({
      next: res => {
        this.loadingRequest = false;
        this.intakeName = res.briefingName ?? 'Briefing';
        this.intakeMeta = res.meta ?? null;
        this.intakeFields = (res.segments ?? []).map((s, i) => this.segmentToRow(s, i));
      },
      error: err => {
        this.loadingRequest = false;
        handleErr(this.snackBar, err, 'Could not load request');
      },
    });
  }

  get includedCount(): number {
    return this.intakeFields.filter(f => f.translate !== false).length;
  }
  get allIntakeIncluded(): boolean {
    return this.intakeFields.length > 0 && this.intakeFields.every(f => f.translate !== false);
  }
  get hasUncheckedLoose(): boolean {
    return this.intakeFields.some(f => f.loose && f.translate === false);
  }
  selectAllIntake(): void {
    const all = this.allIntakeIncluded;
    this.intakeFields.forEach(f => (f.translate = !all));
  }
  removeIntakeRow(f: FieldVM): void {
    this.intakeFields = this.intakeFields.filter(x => x.id !== f.id);
  }
  addCustomRow(): void {
    const name = this.customRow.name.trim();
    if (!name) return;
    this.intakeFields.push({
      id: fid(),
      block: '',
      type: this.customRow.type,
      name,
      limit: null,
      text: this.customRow.text,
      translate: true,
      loose: this.customRow.type !== 'block',
    });
    this.customRow = {name: '', text: '', type: 'block'};
    this.showAddCustom = false;
  }

  cancelIntake(): void {
    this.view = this.briefing ? 'work' : 'empty';
  }

  /** Builds the BriefingVM from the included rows only — loose copy left
   * unchecked never enters the briefing. */
  confirmIntake(): void {
    const included = this.intakeFields.filter(f => f.translate !== false);
    if (!included.length) return;
    this.briefing = {
      id: null,
      name: this.intakeName || 'Briefing',
      requestor: this.intakeMeta?.requestor ?? '',
      due: this.intakeMeta?.due ?? '',
      notes: this.intakeMeta?.notes ?? '',
      fields: included.map((f, i) => ({
        id: 'f' + i,
        block: f.block || 'B1',
        type: f.type ?? 'block',
        name: f.name,
        limit: f.limit,
        text: f.text,
        translate: true,
      })),
    };
    this.mstate = {};
    this.selected = [];
    this.workTab = 'briefing';
    this.view = 'work';
  }

  // ── briefing editor ────────────────────────────────────────────
  get blocks(): string[] {
    return [...new Set((this.briefing?.fields ?? []).map(f => f.block))];
  }
  fieldsInBlock(block: string): FieldVM[] {
    return (this.briefing?.fields ?? []).filter(f => f.block === block);
  }
  addField(block: string): void {
    const type = this.briefing?.fields.find(f => f.block === block)?.type ?? 'block';
    this.briefing?.fields.push({
      id: fid(), block, type, name: 'New field', limit: 80, text: '', translate: true,
    });
  }
  addBlock(): void {
    const n = 'B' + (this.blocks.length + 1);
    this.briefing?.fields.push({
      id: fid(), block: n, type: 'block', name: 'Header', limit: 40, text: '', translate: true,
    });
  }
  /** Adds a loose-copy line (push / SMS / banner / social) — a normal segment
   * that translates and exports like any other field, so the "blank" push/SMS
   * copy that sits outside the e-mail blocks is no longer un-selectable. */
  addLoose(typeKey: string): void {
    const t = FIELD_TYPES.find(x => x.key === typeKey) ?? FIELD_TYPES[1];
    const limit = typeKey === 'sms' ? 160 : typeKey === 'push' ? 90 : 120;
    this.briefing?.fields.push({
      id: fid(), block: t.tag, type: t.key, name: t.label, limit, text: '', translate: true,
    });
  }
  removeField(f: FieldVM): void {
    if (this.briefing) this.briefing.fields = this.briefing.fields.filter(x => x.id !== f.id);
  }
  isTranslated(f: FieldVM): boolean {
    return f.translate !== false;
  }
  toggleTranslate(f: FieldVM): void {
    f.translate = f.translate === false;
  }
  typeTag(f: FieldVM): string {
    return (FIELD_TYPES.find(t => t.key === f.type)?.tag) ?? f.block;
  }
  /** Splits copy into plain text, <html tags> and [placeholders] for chip
   * rendering — the design's signature token highlighting. */
  tokenize(text: string): TokenPart[] {
    const parts = String(text ?? '').split(/(<[^>]+>|\[[^\]]+\]|\{[^}]+\})/g).filter(Boolean);
    return parts.map(p => {
      if (/^<[^>]+>$/.test(p)) return {kind: 'tag' as const, v: p};
      if (/^[[{]/.test(p)) return {kind: 'ph' as const, v: p};
      return {kind: 'text' as const, v: p};
    });
  }
  /** Fields that actually take part in the translation (the "meevertalen" flag). */
  get translatedFields(): FieldVM[] {
    return (this.briefing?.fields ?? []).filter(f => f.translate !== false);
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
    const fields = this.briefing.fields;
    this.selected.forEach(code => {
      this.service.translate(backend, [code]).subscribe({
        next: res => {
          const tr = res.translations[0];
          this.mstate[code] = {
            status: 'done',
            approval: 'pending',
            texts: tr ? this.textsFromSegments(fields, tr.segments) : {},
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
    const fields = this.briefing.fields;
    this.service.translate(backend, [code]).subscribe({
      next: res => {
        const tr = res.translations[0];
        this.mstate[code] = {status: 'done', approval: 'pending', texts: tr ? this.textsFromSegments(fields, tr.segments) : {}};
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
    this.service.translate(single, [code]).subscribe({
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
      next: t =>
        (this.dictTerms = t.map(x => ({
          id: x.id,
          source: x.source,
          target: x.target,
          doNotTranslate: !!x.doNotTranslate,
        }))),
      error: () => {},
    });
  }
  addDictTerm(): void {
    const s = this.newSource.trim();
    const t = this.newTarget.trim();
    // A "keep as-is" term needs no translation (target defaults to source).
    if (!s || (!this.newDnt && !t)) return;
    this.service.createGlossaryTerm(this.dictMarket, s, t, this.newDnt).subscribe({
      next: term => {
        this.dictTerms = [
          {
            id: term.id,
            source: term.source,
            target: term.target,
            doNotTranslate: !!term.doNotTranslate,
          },
          ...this.dictTerms,
        ];
        this.newSource = '';
        this.newTarget = '';
        this.newDnt = false;
      },
      error: err => handleErr(this.snackBar, err, 'Failed to add term'),
    });
  }
  saveDictTerm(t: {id: number; source: string; target: string; doNotTranslate: boolean}): void {
    this.service
      .updateGlossaryTerm(t.id, {
        source: t.source,
        target: t.target,
        doNotTranslate: t.doNotTranslate,
      })
      .subscribe({error: () => {}});
  }
  toggleDnt(t: {id: number; source: string; target: string; doNotTranslate: boolean}): void {
    t.doNotTranslate = !t.doNotTranslate;
    this.saveDictTerm(t);
  }
  deleteDictTerm(t: {id: number}): void {
    this.service.deleteGlossaryTerm(t.id).subscribe({
      next: () => (this.dictTerms = this.dictTerms.filter(x => x.id !== t.id)),
      error: () => {},
    });
  }

  // ── language settings (per-language localization profiles) ─────
  openLangSettings(): void {
    this.view = 'lang';
    this.loadLangConfigs();
  }
  loadLangConfigs(): void {
    this.service.getLanguageConfigs().subscribe({
      next: configs => {
        const map: Record<string, LanguageConfig> = {};
        // Seed a neutral default for every target so the editor binds cleanly.
        this.targets.forEach(m => {
          map[m.code] = {
            language: m.code,
            formality: 'default',
            preserveCasing: true,
            guidance: '',
          };
        });
        configs.forEach(c => (map[c.language] = c));
        this.langConfigs = map;
        this.langLoaded = true;
      },
      error: () => (this.langLoaded = true),
    });
  }
  /** Existing profile for a market, or an in-memory neutral default. */
  configFor(code: string): LanguageConfig {
    if (!this.langConfigs[code]) {
      this.langConfigs[code] = {
        language: code,
        formality: 'default',
        preserveCasing: true,
        guidance: '',
      };
    }
    return this.langConfigs[code];
  }
  saveLangConfig(code: string): void {
    const c = this.configFor(code);
    this.langSaving.add(code);
    this.service
      .upsertLanguageConfig(code, {
        formality: c.formality,
        preserveCasing: c.preserveCasing,
        guidance: c.guidance ?? '',
      })
      .subscribe({
        next: saved => {
          this.langConfigs[code] = saved;
          this.langSaving.delete(code);
          this.flash(`${code} tone of voice saved`);
        },
        error: err => {
          this.langSaving.delete(code);
          handleErr(this.snackBar, err, 'Could not save profile');
        },
      });
  }
  isLangSaving(code: string): boolean {
    return this.langSaving.has(code);
  }
  /** One-click append a reusable guidance line to a language's profile. */
  appendSnippet(code: string, snippet: string): void {
    const c = this.configFor(code);
    const cur = (c.guidance ?? '').replace(/\s*$/, '');
    c.guidance = cur ? `${cur}\n• ${snippet}` : `• ${snippet}`;
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
        type: 'block',
        name: s.field,
        limit: s.charLimit,
        text: s.text,
        translate: true,
      })),
    };
  }
  /** Keys translated text by the actual field id sent for the request
   * (falling back to positional 'f'+i) so lookups survive fid()-based ids,
   * reordering after removeField(), and any future field-exclusion filter. */
  private textsFromSegments(fields: FieldVM[], segs: BriefingSegment[]): Record<string, string> {
    const out: Record<string, string> = {};
    (segs ?? []).forEach((s, i) => (out[fields[i]?.id ?? 'f' + i] = s.text));
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
