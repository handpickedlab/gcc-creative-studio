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

import {
  Component,
  ElementRef,
  OnDestroy,
  OnInit,
  ViewChild,
} from '@angular/core';
import {MatSnackBar} from '@angular/material/snack-bar';
import {Subscription, timer} from 'rxjs';
import {exhaustMap, takeWhile} from 'rxjs/operators';
import {
  AgentStep,
  ClaimSource,
  DataQueryService,
  SourceTable,
} from '../services/data-query.service';
import {handleErrorSnackbar} from '../utils/handleMessageSnackbar';

/** A question/answer turn in the conversation thread. */
interface Turn {
  question: string;
  steps: AgentStep[];
  answerSources: ClaimSource[];
  /** Per-turn collapse state for the trace (above) and sources (below). */
  traceOpen: boolean;
  sourcesOpen: boolean;
  failed: boolean;
}

@Component({
  selector: 'app-data-query',
  templateUrl: './data-query.component.html',
  styleUrls: ['./data-query.component.scss'],
})
export class DataQueryComponent implements OnInit, OnDestroy {
  question = '';
  busy = false;
  uploading = false;
  uploadMsg = '';

  sources: SourceTable[] = [];
  private off = new Set<string>();

  /** Completed turns (the conversation thread). */
  conversation: Turn[] = [];
  /** The in-progress turn, shown optimistically the moment you hit Ask. */
  pendingQuestion: string | null = null;
  steps: AgentStep[] = [];
  answerSources: ClaimSource[] = [];

  /** Citations behind the current answer + the slide open in the viewer. */
  viewerSource: ClaimSource | null = null;
  /** Document whitelist emitted by the library panel (null = all). */
  allowedDocuments: number[] | null = null;
  /** YYYY-MM recency cutoff from the library panel (null = all years). */
  minPeriod: string | null = null;

  private poll?: Subscription;
  @ViewChild('pendingAnchor') private pendingAnchor?: ElementRef<HTMLElement>;

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

  ngOnDestroy(): void {
    this.poll?.unsubscribe();
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

  // ── ask (poll model) ───────────────────────────────────────────
  useExample(q: string): void {
    this.question = q;
    this.ask();
  }

  /** Enter sends; Shift+Enter inserts a newline. */
  onSend(ev: Event): void {
    if ((ev as KeyboardEvent).shiftKey) return;
    ev.preventDefault();
    this.ask();
  }

  ask(): void {
    const q = this.question.trim();
    if (!q || this.busy) return;
    this.busy = true;
    this.pendingQuestion = q;
    this.question = '';
    this.steps = [];
    this.answerSources = [];
    this.viewerSource = null;
    this.scrollToPending();

    const allowed = this.off.size
      ? this.sources.map(s => s.table).filter(t => !this.off.has(t))
      : null;
    // Replay prior turns so the agent can resolve follow-ups ("en in Duitsland?").
    const history = this.conversation.map(t => ({
      question: t.question,
      answer: this.answerText(t.steps),
    }));

    this.service
      .startAsk(q, allowed, this.allowedDocuments, history, this.minPeriod)
      .subscribe({
        next: run => this.startPolling(run.id),
        error: err => {
          this.discardTurn();
          handleErrorSnackbar(this.snackBar, err, 'Query');
        },
      });
  }

  /** Poll the run until it leaves ``processing``; render progress as it lands. */
  private startPolling(runId: string): void {
    this.poll?.unsubscribe();
    // exhaustMap, not switchMap: a poll that outlives the next tick (a cold
    // instance, a busy worker) must still land instead of being cancelled and
    // leaving the trace frozen.
    this.poll = timer(0, 1000)
      .pipe(
        exhaustMap(() => this.service.getRun(runId)),
        takeWhile(run => run.status === 'processing', true),
      )
      .subscribe({
        next: run => {
          this.steps = run.steps || [];
          this.answerSources = run.answerSources || [];
          if (run.status === 'completed') {
            this.finishTurn(false);
          } else if (run.status === 'failed') {
            handleErrorSnackbar(
              this.snackBar,
              {error: {detail: run.errorMessage || 'The query failed.'}},
              'Query',
            );
            this.finishTurn(true);
          }
        },
        error: err => {
          this.discardTurn();
          handleErrorSnackbar(this.snackBar, err, 'Query');
        },
      });
  }

  /** Move the in-progress turn into the thread. */
  private finishTurn(failed: boolean): void {
    this.busy = false;
    if (!this.pendingQuestion) return;
    this.conversation.push({
      question: this.pendingQuestion,
      steps: this.steps,
      answerSources: this.answerSources,
      traceOpen: false,
      sourcesOpen: false,
      failed,
    });
    this.pendingQuestion = null;
    this.steps = [];
    this.answerSources = [];
  }

  /** Drop a failed/cancelled in-progress turn without adding it to the thread. */
  private discardTurn(): void {
    this.poll?.unsubscribe();
    this.busy = false;
    this.pendingQuestion = null;
    this.steps = [];
    this.answerSources = [];
  }

  /** Start a fresh conversation (clears the thread). */
  newConversation(): void {
    this.discardTurn();
    this.conversation = [];
    this.viewerSource = null;
    this.question = '';
  }

  openSource(source: ClaimSource): void {
    this.viewerSource = source;
  }

  // ── template helpers ───────────────────────────────────────────
  /** The concatenated answer text of a turn (text steps only). */
  answerText(steps: AgentStep[]): string {
    return steps
      .filter(s => s.kind === 'text')
      .map(s => s.text || '')
      .join('\n')
      .trim();
  }
  /** The tool calls of a turn (the collapsible reasoning trace). */
  traceSteps(steps: AgentStep[]): AgentStep[] {
    return steps.filter(s => s.kind === 'tool');
  }
  /** Which loop step the agent is mid-way through, if it is thinking now. */
  thinkingStep(steps: AgentStep[]): number | null {
    const last = steps[steps.length - 1];
    return last?.kind === 'model' ? last.n ?? null : null;
  }
  /** Live label under the trace: names the step so the wait is legible. */
  thinkingLabel(steps: AgentStep[]): string {
    const n = this.thinkingStep(steps);
    return n ? `thinking… (step ${n})` : 'thinking…';
  }
  /** A finished tool call's duration, e.g. "1.4s"; empty while it runs. */
  took(s: AgentStep): string {
    return s.ms == null ? '' : `${(s.ms / 1000).toFixed(1)}s`;
  }
  /**
   * True while this tool call has not come back yet. Keyed on the placeholder
   * summary the worker writes when a call starts, not on the duration, so this
   * still reads correctly against a backend that does not send ``ms`` yet.
   */
  running(s: AgentStep): boolean {
    return s.kind === 'tool' && s.summary === '…';
  }
  /** True while any tool call in the turn is still in flight. */
  toolRunning(steps: AgentStep[]): boolean {
    return this.traceSteps(steps).some(s => this.running(s));
  }
  traceLabel(steps: AgentStep[]): string {
    const n = this.traceSteps(steps).length;
    return n === 1 ? '1 step' : `${n} steps`;
  }
  toolArgs(s: AgentStep): string {
    return JSON.stringify(s.input || {});
  }
  sql(s: AgentStep): string {
    return (s.input?.['sql'] as string) || '';
  }
  cols(s: AgentStep): string[] {
    return s.result?.columns ?? [];
  }

  /** Scroll the just-added pending turn into view so the follow-up is visible. */
  private scrollToPending(): void {
    setTimeout(
      () =>
        this.pendingAnchor?.nativeElement?.scrollIntoView({
          behavior: 'smooth',
          block: 'start',
        }),
      60,
    );
  }
}
