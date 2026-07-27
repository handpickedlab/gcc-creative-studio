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

import {Component, EventEmitter, OnDestroy, OnInit, Output} from '@angular/core';
import {MatSnackBar} from '@angular/material/snack-bar';
import {Subscription, concatMap, from, timer} from 'rxjs';
import {
  PriorityTier,
  ResearchDocument,
  ResearchLibraryService,
  isStalled,
} from '../../services/research-library.service';
import {handleErrorSnackbar} from '../../utils/handleMessageSnackbar';

/**
 * Sidebar panel for the research document library: batch upload, per-document
 * status/tier management, and toggling documents in/out of the next question
 * (mirroring how sheet sources are toggled).
 */
@Component({
  selector: 'app-library-panel',
  templateUrl: './library-panel.component.html',
  styleUrls: ['./library-panel.component.scss'],
})
export class LibraryPanelComponent implements OnInit, OnDestroy {
  /**
   * Emits the whitelist of document ids for the next question: null when
   * every document participates, otherwise the non-excluded ids.
   */
  @Output() allowedDocumentsChange = new EventEmitter<number[] | null>();

  documents: ResearchDocument[] = [];
  uploadsPending = 0;

  readonly tiers: PriorityTier[] = ['primary', 'supporting', 'background'];

  private readonly off = new Set<number>();
  private poller: Subscription | null = null;

  constructor(
    private service: ResearchLibraryService,
    private snackBar: MatSnackBar,
  ) {}

  ngOnInit(): void {
    this.refresh();
  }

  ngOnDestroy(): void {
    this.stopPolling();
  }

  refresh(): void {
    this.service.list().subscribe({
      next: r => {
        this.documents = r.data ?? [];
        this.syncPolling();
      },
      error: () => {},
    });
  }

  // ── upload ─────────────────────────────────────────────────────
  onFilesSelected(ev: Event): void {
    const input = ev.target as HTMLInputElement;
    const files = Array.from(input.files ?? []);
    input.value = '';
    if (!files.length) return;

    this.uploadsPending = files.length;
    from(files)
      .pipe(concatMap(file => this.service.upload(file)))
      .subscribe({
        next: () => {
          this.uploadsPending--;
          this.refresh();
        },
        error: err => {
          this.uploadsPending = 0;
          handleErrorSnackbar(this.snackBar, err, 'Upload');
          this.refresh();
        },
        complete: () => (this.uploadsPending = 0),
      });
  }

  // ── management ─────────────────────────────────────────────────
  setTier(doc: ResearchDocument, tier: string): void {
    this.service.updateTier(doc.id, tier as PriorityTier).subscribe({
      next: updated => Object.assign(doc, updated),
      error: err => handleErrorSnackbar(this.snackBar, err, 'Tier'),
    });
  }

  delete(doc: ResearchDocument, ev: MouseEvent): void {
    ev.stopPropagation();
    this.service.delete(doc.id).subscribe({
      next: () => {
        this.off.delete(doc.id);
        this.emitAllowed();
        this.refresh();
      },
      error: err => handleErrorSnackbar(this.snackBar, err, 'Delete'),
    });
  }

  reprocess(doc: ResearchDocument, ev: MouseEvent): void {
    ev.stopPropagation();
    this.service.reprocess(doc.id).subscribe({
      next: () => this.refresh(),
      error: err => handleErrorSnackbar(this.snackBar, err, 'Reprocess'),
    });
  }

  // ── question scoping (mirrors the sheet-source toggle) ─────────
  toggle(doc: ResearchDocument): void {
    if (!this.isSearchable(doc)) return;
    if (this.off.has(doc.id)) this.off.delete(doc.id);
    else this.off.add(doc.id);
    this.emitAllowed();
  }

  isOff(doc: ResearchDocument): boolean {
    return this.off.has(doc.id);
  }

  private emitAllowed(): void {
    if (!this.off.size) {
      this.allowedDocumentsChange.emit(null);
      return;
    }
    const allowed = this.documents
      .filter(d => this.isSearchable(d) && !this.off.has(d.id))
      .map(d => d.id);
    this.allowedDocumentsChange.emit(allowed);
  }

  /** Whether the retry action applies: finished, or stuck with no worker. */
  canReprocess(doc: ResearchDocument): boolean {
    if (doc.status === 'rejected') return false;
    return doc.status !== 'processing' || isStalled(doc);
  }

  // ── presentation helpers ───────────────────────────────────────
  isSearchable(doc: ResearchDocument): boolean {
    return (
      doc.status === 'completed' || doc.status === 'completed_with_errors'
    );
  }

  statusIcon(doc: ResearchDocument): string {
    switch (doc.status) {
      case 'processing':
        return 'hourglass_top';
      case 'completed':
        return 'check_circle';
      case 'completed_with_errors':
        return 'warning';
      case 'rejected':
        return 'block';
      default:
        return 'error';
    }
  }

  statusDetail(doc: ResearchDocument): string {
    switch (doc.status) {
      case 'processing':
        return 'processing…';
      case 'completed':
        return doc.pageCount ? `${doc.pageCount} p.` : 'ready';
      case 'completed_with_errors':
        return `${doc.failedPages?.length ?? 0} page(s) failed`;
      case 'rejected':
        return doc.errorMessage || 'rejected';
      default:
        return doc.errorMessage || 'failed';
    }
  }

  // ── polling while anything is processing ───────────────────────
  private syncPolling(): void {
    const busy = this.documents.some(d => d.status === 'processing');
    if (busy && !this.poller) {
      this.poller = timer(5000, 5000).subscribe(() => this.refresh());
    } else if (!busy) {
      this.stopPolling();
    }
  }

  private stopPolling(): void {
    this.poller?.unsubscribe();
    this.poller = null;
  }
}
