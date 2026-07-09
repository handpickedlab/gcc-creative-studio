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
  AgentEvent,
  ClaimSource,
  DataQueryService,
  SourceTable,
  SqlResult,
} from '../services/data-query.service';
import {handleErrorSnackbar} from '../utils/handleMessageSnackbar';

interface Step {
  kind: 'text' | 'tool';
  text?: string;
  name?: string;
  input?: Record<string, unknown>;
  summary?: string;
  result?: SqlResult | null;
}

@Component({
  selector: 'app-data-query',
  templateUrl: './data-query.component.html',
  styleUrls: ['./data-query.component.scss'],
})
export class DataQueryComponent implements OnInit {
  question = '';
  busy = false;
  uploading = false;
  uploadMsg = '';

  sources: SourceTable[] = [];
  private off = new Set<string>();

  steps: Step[] = [];
  private curText: Step | null = null;
  private curTool: Step | null = null;

  /** Citations behind the current answer + the slide open in the viewer. */
  answerSources: ClaimSource[] = [];
  viewerSource: ClaimSource | null = null;
  /** Document whitelist emitted by the library panel (null = all). */
  allowedDocuments: number[] | null = null;

  // Grounded starter questions that hint at the kinds of things the research
  // library can answer (verified against the corpus). Span single facts,
  // trends, cross-document synthesis and cross-language sources.
  readonly examples = [
    'Hoeveel van de online aankopen gaat via de smartphone, nu en richting 2030?',
    'Welke betaalmethodes domineren de online bestedingen in Nederland?',
    'Hoe ontdekt Gen Z nieuwe merken en mode?',
    'Wat zijn de belangrijkste wereldwijde consumententrends voor 2026?',
    'Hoe belangrijk vinden consumenten duurzaamheid bij mode-aankopen?',
    'Welk deel van de online bestedingen gaat naar buitenlandse webshops?',
    'Wat zegt de ARD/ZDF-studie over mediagebruik in Duitsland?',
    'Welke rol speelt AI in de toekomst van retail en mode?',
  ];

  constructor(
    private service: DataQueryService,
    private snackBar: MatSnackBar,
  ) {}

  ngOnInit(): void {
    this.loadSources();
  }

  loadSources(): void {
    this.service.sources().subscribe({
      next: r => (this.sources = r.tables),
      error: () => {},
    });
  }

  onFileSelected(ev: Event): void {
    const input = ev.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    this.uploading = true;
    this.uploadMsg = 'Loading…';
    this.service.upload(file).subscribe({
      next: r => {
        this.uploading = false;
        this.uploadMsg =
          '✓ ' + r.loaded.map(t => `${t.table} (${t.n_rows})`).join(', ');
        this.loadSources();
      },
      error: err => {
        this.uploading = false;
        this.uploadMsg = '';
        handleErrorSnackbar(this.snackBar, err, 'Upload');
      },
    });
    input.value = '';
  }

  // ── sources sidebar ────────────────────────────────────────────
  toggle(table: string): void {
    if (this.off.has(table)) this.off.delete(table);
    else this.off.add(table);
  }
  isOff(table: string): boolean {
    return this.off.has(table);
  }

  // ── ask ────────────────────────────────────────────────────────
  useExample(q: string): void {
    this.question = q;
    this.ask();
  }

  ask(): void {
    const q = this.question.trim();
    if (!q || this.busy) return;
    this.busy = true;
    this.steps = [];
    this.curText = null;
    this.curTool = null;
    this.answerSources = [];
    this.viewerSource = null;

    const allowed = this.off.size
      ? this.sources.map(s => s.table).filter(t => !this.off.has(t))
      : null;

    this.service.ask(q, allowed, this.allowedDocuments).subscribe({
      next: ev => this.handle(ev),
      error: err => {
        this.busy = false;
        handleErrorSnackbar(this.snackBar, err, 'Query');
      },
      complete: () => (this.busy = false),
    });
  }

  private handle(ev: AgentEvent): void {
    switch (ev.t) {
      case 'tool':
        this.curText = null;
        this.curTool = {
          kind: 'tool',
          name: ev.name,
          input: ev.input,
          summary: '…',
        };
        this.steps.push(this.curTool);
        break;
      case 'tool_result':
        if (this.curTool) {
          this.curTool.summary = ev.summary || '';
          this.curTool.result = ev.result ?? null;
        }
        break;
      case 'text':
        if (!this.curText) {
          this.curText = {kind: 'text', text: ''};
          this.steps.push(this.curText);
        }
        this.curText.text = (this.curText.text || '') + (ev.v || '');
        break;
      case 'sources':
        this.answerSources = (ev.v as ClaimSource[]) || [];
        break;
      case 'error':
        this.steps.push({kind: 'text', text: '⚠️ ' + (ev.message || 'error')});
        break;
      case 'done':
        this.busy = false;
        break;
    }
  }

  openSource(source: ClaimSource): void {
    this.viewerSource = source;
  }

  // ── template helpers ───────────────────────────────────────────
  toolArgs(s: Step): string {
    return JSON.stringify(s.input || {});
  }
  sql(s: Step): string {
    return (s.input?.['sql'] as string) || '';
  }
  cols(s: Step): string[] {
    return s.result?.columns ?? [];
  }
}
