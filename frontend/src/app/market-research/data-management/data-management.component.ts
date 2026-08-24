/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import {Component, OnDestroy, OnInit} from '@angular/core';
import {MatSnackBar} from '@angular/material/snack-bar';
import {Subject, Subscription, concatMap, debounceTime, from, timer} from 'rxjs';
import {
  DataQueryService,
  SheetInfo,
} from '../../services/data-query.service';
import {
  ClaimRow,
  PriorityTier,
  ResearchDocument,
  ResearchLibraryService,
  isStalled,
} from '../../services/research-library.service';
import {handleErrorSnackbar} from '../../utils/handleMessageSnackbar';

type ManageView = 'documents' | 'spreadsheets' | 'facts';

const DOC_ACCEPT = '.pdf,.docx,.ppt,.pptx,.odp,.png,.jpg,.jpeg';
const SHEET_ACCEPT = '.csv,.xlsx,.xlsm,.xls';
const PAGE_SIZE = 25;

@Component({
  selector: 'app-data-management',
  templateUrl: './data-management.component.html',
  styleUrls: ['./data-management.component.scss'],
})
export class DataManagementComponent implements OnInit, OnDestroy {
  view: ManageView = 'documents';
  readonly docAccept = DOC_ACCEPT;
  readonly sheetAccept = SHEET_ACCEPT;
  readonly tiers: PriorityTier[] = ['primary', 'supporting', 'background'];

  // Documents (research library)
  documents: ResearchDocument[] = [];
  docsLoading = true;
  docUploadsPending = 0;
  /**
   * Local tier writes that must survive a poll. A GET that left before the
   * PATCH committed would otherwise snap the dropdown back to the old value.
   */
  private readonly stickyTiers = new Map<number, PriorityTier>();

  // Spreadsheets (DuckDB warehouse catalog)
  sheets: SheetInfo[] = [];
  sheetsLoading = true;
  sheetUploadsPending = 0;

  // Facts (extracted claims)
  facts: ClaimRow[] = [];
  factsTotal = 0;
  factsOffset = 0;
  readonly pageSize = PAGE_SIZE;
  factsQuery = '';
  factsLoading = false;
  private factSearch$ = new Subject<void>();

  private poller: Subscription | null = null;
  private subs: Subscription[] = [];

  constructor(
    private library: ResearchLibraryService,
    private dataQuery: DataQueryService,
    private snackBar: MatSnackBar,
  ) {}

  ngOnInit(): void {
    this.loadDocuments();
    this.loadSheets();
    this.subs.push(
      this.factSearch$.pipe(debounceTime(350)).subscribe(() => {
        this.factsOffset = 0;
        this.loadFacts();
      }),
    );
    this.loadFacts();
  }

  ngOnDestroy(): void {
    this.poller?.unsubscribe();
    this.subs.forEach(s => s.unsubscribe());
  }

  setView(v: ManageView): void {
    this.view = v;
  }

  // ── documents ──────────────────────────────────────────────────
  loadDocuments(): void {
    this.docsLoading = true;
    this.library.list(200).subscribe({
      next: r => {
        const incoming = r.data ?? [];
        for (const doc of incoming) {
          const sticky = this.stickyTiers.get(doc.id);
          if (!sticky) continue;
          if (doc.priorityTier === sticky) this.stickyTiers.delete(doc.id);
          else doc.priorityTier = sticky;
        }
        this.documents = incoming;
        this.docsLoading = false;
        this.syncPolling();
      },
      error: err => {
        this.docsLoading = false;
        handleErrorSnackbar(this.snackBar, err, 'Documents');
      },
    });
  }

  onDocsSelected(ev: Event): void {
    const input = ev.target as HTMLInputElement;
    const files = Array.from(input.files ?? []);
    input.value = '';
    if (!files.length) return;
    this.docUploadsPending = files.length;
    from(files)
      .pipe(concatMap(f => this.library.upload(f)))
      .subscribe({
        next: () => {
          this.docUploadsPending--;
          this.loadDocuments();
        },
        error: err => {
          this.docUploadsPending = 0;
          handleErrorSnackbar(this.snackBar, err, 'Upload');
          this.loadDocuments();
        },
        complete: () => (this.docUploadsPending = 0),
      });
  }

  setTier(doc: ResearchDocument, tier: string): void {
    const next = tier as PriorityTier;
    if (doc.priorityTier === next && !this.stickyTiers.has(doc.id)) return;
    const previous = doc.priorityTier;
    doc.priorityTier = next;
    this.stickyTiers.set(doc.id, next);
    this.library.updateTier(doc.id, next).subscribe({
      next: u => {
        Object.assign(doc, u);
        doc.priorityTier = this.stickyTiers.get(doc.id) ?? doc.priorityTier;
      },
      error: err => {
        this.stickyTiers.delete(doc.id);
        doc.priorityTier = previous;
        handleErrorSnackbar(this.snackBar, err, 'Tier');
      },
    });
  }

  trackByDocId(_index: number, doc: ResearchDocument): number {
    return doc.id;
  }

  reprocess(doc: ResearchDocument): void {
    this.library.reprocess(doc.id).subscribe({
      next: () => this.loadDocuments(),
      error: err => handleErrorSnackbar(this.snackBar, err, 'Reprocess'),
    });
  }

  deleteDoc(doc: ResearchDocument): void {
    this.library.delete(doc.id).subscribe({
      next: () => (this.documents = this.documents.filter(d => d.id !== doc.id)),
      error: err => handleErrorSnackbar(this.snackBar, err, 'Delete'),
    });
  }

  /** Whether the retry action applies: finished, or stuck with no worker. */
  canReprocess(d: ResearchDocument): boolean {
    if (d.status === 'rejected') return false;
    return d.status !== 'processing' || isStalled(d);
  }

  docStatusDetail(d: ResearchDocument): string {
    switch (d.status) {
      case 'processing':
        // The backend sweeper picks these up by itself; saying so beats a
        // spinner that has silently meant nothing for four days.
        return isStalled(d) ? 'stalled — waiting for retry' : 'processing…';
      case 'completed':
        return d.pageCount ? `${d.pageCount} p.` : 'ready';
      case 'completed_with_errors':
        return `${d.failedPages?.length ?? 0} page(s) failed`;
      case 'rejected':
        return d.errorMessage || 'rejected';
      default:
        return d.errorMessage || 'failed';
    }
  }

  private syncPolling(): void {
    const busy = this.documents.some(d => d.status === 'processing');
    if (busy && !this.poller) {
      this.poller = timer(5000, 5000).subscribe(() => this.loadDocuments());
    } else if (!busy) {
      this.poller?.unsubscribe();
      this.poller = null;
    }
  }

  // ── spreadsheets ───────────────────────────────────────────────
  loadSheets(): void {
    this.sheetsLoading = true;
    this.dataQuery.sheets().subscribe({
      next: s => {
        this.sheets = s;
        this.sheetsLoading = false;
      },
      error: err => {
        this.sheetsLoading = false;
        handleErrorSnackbar(this.snackBar, err, 'Sheets');
      },
    });
  }

  onSheetsSelected(ev: Event): void {
    const input = ev.target as HTMLInputElement;
    const files = Array.from(input.files ?? []);
    input.value = '';
    if (!files.length) return;
    this.sheetUploadsPending = files.length;
    from(files)
      .pipe(concatMap(f => this.dataQuery.upload(f)))
      .subscribe({
        next: () => this.sheetUploadsPending--,
        error: err => {
          this.sheetUploadsPending = 0;
          handleErrorSnackbar(this.snackBar, err, 'Upload');
          this.loadSheets();
        },
        complete: () => {
          this.sheetUploadsPending = 0;
          this.loadSheets();
        },
      });
  }

  deleteSheet(sheet: SheetInfo): void {
    this.dataQuery.deleteSheet(sheet.id).subscribe({
      next: () => (this.sheets = this.sheets.filter(s => s.id !== sheet.id)),
      error: err => handleErrorSnackbar(this.snackBar, err, 'Delete'),
    });
  }

  sheetColumns(s: SheetInfo): string {
    const cols = s.columns ?? [];
    const head = cols.slice(0, 6).join(', ');
    return cols.length > 6 ? `${head}, +${cols.length - 6} more` : head;
  }

  // ── facts ──────────────────────────────────────────────────────
  onFactsQueryChange(): void {
    this.factSearch$.next();
  }

  loadFacts(): void {
    this.factsLoading = true;
    this.library
      .browseClaims({
        q: this.factsQuery.trim() || undefined,
        limit: this.pageSize,
        offset: this.factsOffset,
      })
      .subscribe({
        next: page => {
          this.facts = page.items;
          this.factsTotal = page.total;
          this.factsLoading = false;
        },
        error: err => {
          this.factsLoading = false;
          handleErrorSnackbar(this.snackBar, err, 'Facts');
        },
      });
  }

  nextFactsPage(): void {
    if (this.factsOffset + this.pageSize < this.factsTotal) {
      this.factsOffset += this.pageSize;
      this.loadFacts();
    }
  }

  prevFactsPage(): void {
    if (this.factsOffset > 0) {
      this.factsOffset = Math.max(0, this.factsOffset - this.pageSize);
      this.loadFacts();
    }
  }

  get factsRangeLabel(): string {
    if (!this.factsTotal) return '0';
    const from = this.factsOffset + 1;
    const to = Math.min(this.factsOffset + this.pageSize, this.factsTotal);
    return `${from}–${to} of ${this.factsTotal.toLocaleString()}`;
  }
}
