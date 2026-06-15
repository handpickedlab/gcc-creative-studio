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

import {Component, OnInit} from '@angular/core';
import {MatSnackBar} from '@angular/material/snack-bar';
import {
  Briefing,
  GlossarySummary,
  GlossaryTerm,
  Market,
  MarketTranslation,
  ParseResult,
  TranslationService,
} from '../services/translation.service';
import {
  handleErrorSnackbar,
  handleSuccessSnackbar,
} from '../utils/handleMessageSnackbar';

@Component({
  selector: 'app-translations',
  templateUrl: './translations.component.html',
  styleUrls: ['./translations.component.scss'],
})
export class TranslationsComponent implements OnInit {
  markets: Market[] = [];
  selectedFile: File | null = null;

  parse: ParseResult | null = null;
  selectedSheet = '';
  selectedRequestIndex: number | null = null;

  briefing: Briefing | null = null;
  selectedMarkets: string[] = [];
  translations: MarketTranslation[] = [];
  activeTab = 0;

  glossary: GlossarySummary | null = null;

  // Glossary manager (configurable dictionary)
  showGlossaryManager = false;
  glossaryMarket = '';
  glossaryTerms: GlossaryTerm[] = [];
  glossaryQuery = '';
  isLoadingTerms = false;
  newTermSource = '';
  newTermTarget = '';

  isUploading = false;
  isLoadingRequest = false;
  isTranslating = false;
  isImportingTm = false;
  isSaving = false;
  isExporting = false;

  constructor(
    private service: TranslationService,
    private snackBar: MatSnackBar,
  ) {}

  ngOnInit(): void {
    this.service.getMarkets().subscribe({
      next: m => (this.markets = m),
      error: err =>
        handleErrorSnackbar(this.snackBar, err, 'Could not load markets'),
    });
    this.loadGlossarySummary();
  }

  get targetMarkets(): Market[] {
    return this.markets.filter(m => m.code !== 'EN');
  }

  /** True once a request is loaded but it has no source copy at all. */
  get briefingIsEmpty(): boolean {
    return (
      !!this.briefing && !this.briefing.segments.some(s => !!s.text?.trim())
    );
  }

  loadGlossarySummary(): void {
    this.service.getGlossarySummary().subscribe({
      next: s => (this.glossary = s),
      error: () => {},
    });
  }

  // --- Glossary manager ------------------------------------------------

  toggleGlossaryManager(): void {
    this.showGlossaryManager = !this.showGlossaryManager;
    if (this.showGlossaryManager && !this.glossaryMarket) {
      this.glossaryMarket =
        this.glossary?.perMarket?.[0]?.market ?? this.targetMarkets[0]?.code ?? 'NL';
      this.loadGlossaryTerms();
    }
  }

  loadGlossaryTerms(): void {
    if (!this.glossaryMarket) return;
    this.isLoadingTerms = true;
    this.service
      .getGlossaryTerms(this.glossaryMarket, this.glossaryQuery || undefined)
      .subscribe({
        next: t => {
          this.glossaryTerms = t;
          this.isLoadingTerms = false;
        },
        error: err => {
          this.isLoadingTerms = false;
          handleErrorSnackbar(this.snackBar, err, 'Could not load dictionary');
        },
      });
  }

  addGlossaryTerm(): void {
    const source = this.newTermSource.trim();
    const target = this.newTermTarget.trim();
    if (!source || !target || !this.glossaryMarket) return;
    this.service
      .createGlossaryTerm(this.glossaryMarket, source, target)
      .subscribe({
        next: term => {
          this.glossaryTerms = [term, ...this.glossaryTerms];
          this.newTermSource = '';
          this.newTermTarget = '';
          this.loadGlossarySummary();
        },
        error: err => handleErrorSnackbar(this.snackBar, err, 'Could not add term'),
      });
  }

  saveGlossaryTerm(term: GlossaryTerm): void {
    this.service
      .updateGlossaryTerm(term.id, {source: term.source, target: term.target})
      .subscribe({
        next: () => handleSuccessSnackbar(this.snackBar, 'Term updated'),
        error: err =>
          handleErrorSnackbar(this.snackBar, err, 'Could not update term'),
      });
  }

  deleteGlossaryTerm(term: GlossaryTerm): void {
    this.service.deleteGlossaryTerm(term.id).subscribe({
      next: () => {
        this.glossaryTerms = this.glossaryTerms.filter(t => t.id !== term.id);
        this.loadGlossarySummary();
      },
      error: err =>
        handleErrorSnackbar(this.snackBar, err, 'Could not delete term'),
    });
  }

  // --- Upload / discovery ---------------------------------------------

  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0] ?? null;
    if (!file) return;
    this.selectedFile = file;
    this.briefing = null;
    this.translations = [];
    this.selectedRequestIndex = null;
    this.isUploading = true;
    this.service.upload(file).subscribe({
      next: res => {
        this.parse = res;
        this.selectedSheet = res.selectedSheet ?? res.sheets[0] ?? '';
        this.isUploading = false;
        // Auto-load the dictionary from the Translation Memories sheet.
        if (res.sheets.includes('Translation Memories')) {
          this.autoImportTm(file);
        }
      },
      error: err => {
        this.isUploading = false;
        handleErrorSnackbar(this.snackBar, err, 'Upload failed');
      },
    });
  }

  private autoImportTm(file: File): void {
    this.isImportingTm = true;
    this.service.importTranslationMemory(file).subscribe({
      next: res => {
        this.isImportingTm = false;
        if (res.imported > 0) {
          handleSuccessSnackbar(
            this.snackBar,
            `Dictionary loaded: ${res.imported} new terms`,
          );
        }
        this.loadGlossarySummary();
      },
      error: () => {
        this.isImportingTm = false;
        this.loadGlossarySummary();
      },
    });
  }

  onSheetChange(): void {
    if (!this.selectedFile) return;
    this.selectedRequestIndex = null;
    this.briefing = null;
    this.translations = [];
    this.isUploading = true;
    this.service.upload(this.selectedFile, this.selectedSheet).subscribe({
      next: res => {
        this.parse = res;
        this.isUploading = false;
      },
      error: err => {
        this.isUploading = false;
        handleErrorSnackbar(this.snackBar, err, 'Could not read sheet');
      },
    });
  }

  loadRequest(): void {
    if (!this.selectedFile || this.selectedRequestIndex == null) return;
    this.isLoadingRequest = true;
    this.translations = [];
    this.service
      .upload(this.selectedFile, this.selectedSheet, this.selectedRequestIndex)
      .subscribe({
        next: res => {
          this.briefing = {
            name: res.briefingName ?? 'Briefing',
            sourceMarket: 'EN',
            meta: res.meta ?? {},
            segments: res.segments,
          };
          this.isLoadingRequest = false;
        },
        error: err => {
          this.isLoadingRequest = false;
          handleErrorSnackbar(this.snackBar, err, 'Could not load request');
        },
      });
  }

  importTm(): void {
    if (!this.selectedFile) return;
    this.isImportingTm = true;
    this.service.importTranslationMemory(this.selectedFile).subscribe({
      next: res => {
        this.isImportingTm = false;
        handleSuccessSnackbar(
          this.snackBar,
          `Imported ${res.imported} glossary terms (${res.markets.length} markets)`,
        );
      },
      error: err => {
        this.isImportingTm = false;
        handleErrorSnackbar(
          this.snackBar,
          err,
          'Translation memory import failed',
        );
      },
    });
  }

  // --- Translate ------------------------------------------------------

  translate(): void {
    if (!this.briefing || this.selectedMarkets.length === 0) return;
    this.isTranslating = true;
    this.service.translate(this.briefing, this.selectedMarkets).subscribe({
      next: res => {
        this.translations = res.translations;
        this.activeTab = 0;
        this.isTranslating = false;
      },
      error: err => {
        this.isTranslating = false;
        handleErrorSnackbar(this.snackBar, err, 'Translation failed');
      },
    });
  }

  marketLabel(code: string): string {
    return this.markets.find(m => m.code === code)?.label ?? code;
  }

  sourceText(i: number): string {
    return this.briefing?.segments?.[i]?.text ?? '';
  }

  over(seg: {charLimit: number | null; text: string}): boolean {
    return !!seg.charLimit && (seg.text?.length ?? 0) > seg.charLimit;
  }

  // --- Save / export --------------------------------------------------

  save(): void {
    if (!this.briefing) return;
    this.isSaving = true;
    this.service.save(this.briefing, this.translations).subscribe({
      next: () => {
        this.isSaving = false;
        handleSuccessSnackbar(this.snackBar, 'Briefing saved');
      },
      error: err => {
        this.isSaving = false;
        handleErrorSnackbar(this.snackBar, err, 'Save failed');
      },
    });
  }

  exportXlsx(): void {
    if (!this.briefing) return;
    this.isExporting = true;
    this.service.exportXlsx(this.briefing, this.translations).subscribe({
      next: blob => {
        this.isExporting = false;
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${this.briefing?.name ?? 'briefing'}.xlsx`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
      },
      error: err => {
        this.isExporting = false;
        handleErrorSnackbar(this.snackBar, err, 'Export failed');
      },
    });
  }
}
