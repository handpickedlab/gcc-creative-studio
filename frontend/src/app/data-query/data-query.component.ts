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

/** A completed question/answer turn in the conversation thread. */
interface Turn {
  question: string;
  steps: Step[];
  answerSources: ClaimSource[];
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

  /** Completed turns (the conversation thread) + the in-progress turn. */
  conversation: Turn[] = [];
  pendingQuestion: string | null = null;
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
    'What share of online purchases is made via smartphone, now and toward 2030?',
    'Which payment methods dominate online spending in the Netherlands?',
    'How does Gen Z discover new brands and fashion?',
    'What are the most important global consumer trends for 2026?',
    'How important is sustainability to consumers when buying fashion?',
    'What share of online spending goes to foreign webshops?',
    'What does the ARD/ZDF study say about media use in Germany?',
    'What role does AI play in the future of retail and fashion?',
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
    this.pendingQuestion = q;
    this.question = '';
    this.steps = [];
    this.curText = null;
    this.curTool = null;
    this.answerSources = [];
    this.viewerSource = null;

    const allowed = this.off.size
      ? this.sources.map(s => s.table).filter(t => !this.off.has(t))
      : null;
    // Replay prior turns so the agent can resolve follow-ups ("en in Duitsland?").
    const history = this.conversation.map(t => ({
      question: t.question,
      answer: this.answerText(t.steps),
    }));

    this.service.ask(q, allowed, this.allowedDocuments, history).subscribe({
      next: ev => this.handle(ev),
      error: err => {
        this.discardTurn();
        handleErrorSnackbar(this.snackBar, err, 'Query');
      },
      complete: () => this.finishTurn(),
    });
  }

  /** The concatenated answer text of a turn (for the history we send back). */
  private answerText(steps: Step[]): string {
    return steps
      .filter(s => s.kind === 'text')
      .map(s => s.text || '')
      .join('\n')
      .trim();
  }

  /** Move the in-progress turn into the thread. Idempotent per turn. */
  private finishTurn(): void {
    this.busy = false;
    if (!this.pendingQuestion) return;
    this.conversation.push({
      question: this.pendingQuestion,
      steps: this.steps,
      answerSources: this.answerSources,
    });
    this.pendingQuestion = null;
    this.steps = [];
    this.curText = null;
    this.curTool = null;
    this.answerSources = [];
  }

  /** Drop a failed in-progress turn without adding it to the thread. */
  private discardTurn(): void {
    this.busy = false;
    this.pendingQuestion = null;
    this.steps = [];
    this.curText = null;
    this.curTool = null;
    this.answerSources = [];
  }

  /** Start a fresh conversation (clears the thread). */
  newConversation(): void {
    this.discardTurn();
    this.conversation = [];
    this.viewerSource = null;
    this.question = '';
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
        this.finishTurn();
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
