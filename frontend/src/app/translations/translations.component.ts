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
import {Clipboard} from '@angular/cdk/clipboard';
import {
  GlossaryTerm,
  TranslationResult,
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
  // Source text + language selection
  sourceText = '';
  selectedLanguages: string[] = ['Dutch', 'French'];
  availableLanguages: string[] = [
    'Dutch',
    'English',
    'French',
    'German',
    'Spanish',
    'Italian',
    'Portuguese',
    'Polish',
    'Swedish',
    'Japanese',
    'Chinese',
  ];

  // Results
  results: TranslationResult[] = [];
  isTranslating = false;

  // Glossary
  glossary: GlossaryTerm[] = [];
  isLoadingGlossary = false;
  newSource = '';
  newTarget = '';

  constructor(
    private translationService: TranslationService,
    private snackBar: MatSnackBar,
    private clipboard: Clipboard,
  ) {}

  ngOnInit(): void {
    this.loadGlossary();
  }

  // --- Translation -----------------------------------------------------

  translate(): void {
    const text = this.sourceText.trim();
    if (!text || this.selectedLanguages.length === 0) {
      return;
    }
    this.isTranslating = true;
    this.results = [];
    this.translationService
      .translate({text, target_languages: this.selectedLanguages})
      .subscribe({
        next: response => {
          this.results = response.results;
          this.isTranslating = false;
        },
        error: err => {
          this.isTranslating = false;
          handleErrorSnackbar(this.snackBar, err, 'Translation failed');
        },
      });
  }

  copyResult(result: TranslationResult): void {
    this.clipboard.copy(result.translation);
    handleSuccessSnackbar(this.snackBar, `Copied ${result.language}`);
  }

  // --- Glossary --------------------------------------------------------

  loadGlossary(): void {
    this.isLoadingGlossary = true;
    this.translationService.getGlossary().subscribe({
      next: terms => {
        this.glossary = terms;
        this.isLoadingGlossary = false;
      },
      error: err => {
        this.isLoadingGlossary = false;
        handleErrorSnackbar(this.snackBar, err, 'Could not load glossary');
      },
    });
  }

  addTerm(): void {
    const source = this.newSource.trim();
    const target = this.newTarget.trim();
    if (!source || !target) {
      return;
    }
    this.translationService.createTerm({source, target}).subscribe({
      next: term => {
        this.glossary = [...this.glossary, term];
        this.newSource = '';
        this.newTarget = '';
      },
      error: err => {
        handleErrorSnackbar(this.snackBar, err, 'Could not add term');
      },
    });
  }

  deleteTerm(term: GlossaryTerm): void {
    this.translationService.deleteTerm(term.id).subscribe({
      next: () => {
        this.glossary = this.glossary.filter(t => t.id !== term.id);
      },
      error: err => {
        handleErrorSnackbar(this.snackBar, err, 'Could not delete term');
      },
    });
  }
}
