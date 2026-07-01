/**
 * Copyright 2025 Google LLC
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
import {FormBuilder, FormControl, FormGroup, Validators} from '@angular/forms';
import {Subscription, interval} from 'rxjs';
import {switchMap} from 'rxjs/operators';
import {
  DeepResearchReport,
  IntakeField,
  IntakeFieldType,
  IntakeSchema,
  JobStatus,
  StartDeepResearchRequest,
} from '../common/models/deep-research.model';
import {
  DeepResearchEvent,
  DeepResearchService,
} from '../services/deep-research/deep-research.service';

/** Sentinel option that reveals a free-text input on a single-select field. */
const CUSTOM_OPTION = 'Anders… (vul zelf in)';
/** Competitor option that reveals the "which competitors?" input. */
const SPECIFIC_COMPETITORS = 'Specific competitors';
const POLL_INTERVAL_MS = 4000;
const DEFAULT_ITERATIONS = 3;

type ViewState = 'wizard' | 'running' | 'report';

@Component({
  selector: 'app-deep-research',
  templateUrl: './deep-research.component.html',
  styleUrls: ['./deep-research.component.scss'],
})
export class DeepResearchComponent implements OnInit, OnDestroy {
  // Template-facing constants.
  readonly FieldType = IntakeFieldType;
  readonly JobStatus = JobStatus;
  readonly CUSTOM_OPTION = CUSTOM_OPTION;
  readonly SPECIFIC_COMPETITORS = SPECIFIC_COMPETITORS;

  loadingSchema = true;
  schemaError: string | null = null;
  schema?: IntakeSchema;
  fieldsByKey: Record<string, IntakeField> = {};

  /** One FormGroup per intake step, aligned with schema.steps by index. */
  stepForms: FormGroup[] = [];
  maxIterations = new FormControl(DEFAULT_ITERATIONS);

  /** Current wizard step (0..reviewStep). The review step is the last one. */
  step = 0;
  readonly iterationOptions = [1, 2, 3, 4, 5, 6];

  view: ViewState = 'wizard';
  activeReport?: DeepResearchReport;
  starting = false;
  runError: string | null = null;

  history: DeepResearchReport[] = [];

  /** Live activity log while a scan runs, grouped by pipeline phase. */
  liveGroups: {key: string; label: string; icon: string; lines: string[]}[] = [];

  private readonly agentLabels: Record<string, {label: string; icon: string}> = {
    plan_generator: {label: 'Onderzoeksplan opstellen', icon: 'checklist'},
    web_researcher: {label: 'Web doorzoeken', icon: 'travel_explore'},
    reflector: {label: 'Dekking beoordelen', icon: 'psychology'},
    report_composer: {label: 'Concept schrijven', icon: 'edit_note'},
    claim_verifier: {label: 'Bronnen verifiëren', icon: 'fact_check'},
  };

  private pollSub?: Subscription;
  private streamSub?: Subscription;

  constructor(
    private fb: FormBuilder,
    private service: DeepResearchService,
  ) {}

  ngOnInit(): void {
    this.loadSchema();
    this.loadHistory();
  }

  ngOnDestroy(): void {
    this.pollSub?.unsubscribe();
    this.streamSub?.unsubscribe();
  }

  // --- Loading ---------------------------------------------------------------

  private loadSchema(): void {
    this.loadingSchema = true;
    this.schemaError = null;
    this.service.getIntakeSchema().subscribe({
      next: schema => {
        this.schema = schema;
        this.fieldsByKey = {};
        schema.fields.forEach(f => (this.fieldsByKey[f.key] = f));
        this.buildForms(schema);
        this.loadingSchema = false;
      },
      error: () => {
        this.schemaError = 'Kon het intake-formulier niet laden.';
        this.loadingSchema = false;
      },
    });
  }

  private buildForms(schema: IntakeSchema): void {
    this.stepForms = schema.steps.map(step => {
      const controls: Record<string, FormControl> = {};
      step.fieldKeys.forEach(key => {
        const field = this.fieldsByKey[key];
        if (!field) {
          return;
        }
        switch (field.type) {
          case IntakeFieldType.MULTI_SELECT:
            controls[key] = new FormControl<string[]>([]);
            break;
          case IntakeFieldType.COMPETITOR:
            controls[key] = new FormControl(field.options[0] ?? '');
            controls[`${key}__names`] = new FormControl('');
            break;
          case IntakeFieldType.SINGLE_SELECT_CUSTOM:
            controls[key] = new FormControl(field.options[0] ?? '');
            controls[`${key}__custom`] = new FormControl('');
            break;
          case IntakeFieldType.SINGLE_SELECT:
            controls[key] = new FormControl(field.options[0] ?? '');
            break;
          default: // FREE_TEXT
            controls[key] = new FormControl(
              '',
              key === 'research_topic' ? Validators.required : [],
            );
        }
      });
      return this.fb.group(controls);
    });
  }

  private loadHistory(): void {
    this.service.listReports().subscribe({
      next: page => (this.history = page.data ?? []),
      error: () => {},
    });
  }

  // --- Value resolution ------------------------------------------------------

  private controlValue(key: string): string | string[] | null {
    for (const form of this.stepForms) {
      if (form.contains(key)) {
        return form.get(key)!.value;
      }
    }
    return null;
  }

  /** Resolve a field to the value the brief expects (custom/competitor aware). */
  private resolveField(field: IntakeField): string | string[] {
    const raw = this.controlValue(field.key);

    if (
      field.type === IntakeFieldType.SINGLE_SELECT_CUSTOM &&
      raw === CUSTOM_OPTION
    ) {
      return (
        (this.controlValue(`${field.key}__custom`) as string) || ''
      ).trim();
    }
    if (
      field.type === IntakeFieldType.COMPETITOR &&
      raw === SPECIFIC_COMPETITORS
    ) {
      const names = (
        (this.controlValue(`${field.key}__names`) as string) || ''
      ).trim();
      return names || 'Include competitor context (specific competitors)';
    }
    return raw ?? '';
  }

  /** Human-readable value for the review summary. */
  displayValue(field: IntakeField): string {
    const value = this.resolveField(field);
    return Array.isArray(value) ? value.join(', ') : (value ?? '').toString();
  }

  get topic(): string {
    return ((this.controlValue('research_topic') as string) || '').trim();
  }

  get reportBody(): string {
    return this.activeReport?.report || '';
  }

  // --- Report splitting (collapse the long Sources list) ---------------------

  private _parsedFor: string | null = null;
  private _parsed = {main: '', sources: '', rest: '', count: 0};

  /**
   * Split the report into the body, the (long) Sources list and anything after
   * it (e.g. the verification section), so the UI can tuck the sources away.
   * Memoized on the raw report string so change detection stays cheap.
   */
  private parseReport(): {main: string; sources: string; rest: string; count: number} {
    const md = this.reportBody;
    if (md === this._parsedFor) {
      return this._parsed;
    }
    this._parsedFor = md;

    const lines = md.split('\n');
    const start = lines.findIndex(l => /^#{1,6}\s+sources\b/i.test(l.trim()));
    if (start < 0) {
      this._parsed = {main: md, sources: '', rest: '', count: 0};
      return this._parsed;
    }

    // The sources list runs until the next heading or a horizontal rule.
    let end = lines.length;
    for (let i = start + 1; i < lines.length; i++) {
      const t = lines[i].trim();
      if (t === '---' || t === '***' || /^#{1,6}\s+/.test(t)) {
        end = i;
        break;
      }
    }

    const sources = lines.slice(start + 1, end).join('\n').trim();
    let count = (sources.match(/^\s*\[\d+\]/gm) || []).length;
    if (!count) {
      count = (sources.match(/^\s*(\d+[.)]|[-*])\s/gm) || []).length;
    }

    this._parsed = {
      main: lines.slice(0, start).join('\n').trim(),
      sources,
      rest: lines.slice(end).join('\n').trim(),
      count,
    };
    return this._parsed;
  }

  get reportMain(): string {
    return this.parseReport().main;
  }

  get reportSources(): string {
    return this.parseReport().sources;
  }

  get reportRest(): string {
    return this.parseReport().rest;
  }

  get sourceCount(): number {
    return this.parseReport().count;
  }

  private buildRequest(): StartDeepResearchRequest {
    const request: Record<string, unknown> = {};
    this.schema?.fields.forEach(field => {
      request[field.key] = this.resolveField(field);
    });
    request['max_iterations'] = this.maxIterations.value ?? DEFAULT_ITERATIONS;
    return request as unknown as StartDeepResearchRequest;
  }

  // --- Wizard navigation -----------------------------------------------------

  /** Index of the final "review & start" step (after the content steps). */
  get reviewStep(): number {
    return this.schema?.steps.length ?? 0;
  }

  get onReview(): boolean {
    return this.step >= this.reviewStep;
  }

  goStep(index: number): void {
    // Stepper chips navigate backwards freely; forward goes via "Volgende".
    if (index <= this.step) {
      this.step = index;
    }
  }

  nextStep(): void {
    const form = this.stepForms[this.step];
    if (form && form.invalid) {
      form.markAllAsTouched();
      return;
    }
    this.step = Math.min(this.step + 1, this.reviewStep);
  }

  prevStep(): void {
    this.step = Math.max(this.step - 1, 0);
  }

  // --- Wizard interactions ---------------------------------------------------

  setValue(stepIndex: number, key: string, value: string): void {
    this.stepForms[stepIndex]?.get(key)?.setValue(value);
  }

  isMultiSelected(key: string, option: string): boolean {
    const value = this.controlValue(key);
    return Array.isArray(value) && value.includes(option);
  }

  toggleMulti(stepIndex: number, key: string, option: string): void {
    const control = this.stepForms[stepIndex]?.get(key);
    if (!control) {
      return;
    }
    const current: string[] = Array.isArray(control.value)
      ? [...control.value]
      : [];
    const at = current.indexOf(option);
    if (at >= 0) {
      current.splice(at, 1);
    } else {
      current.push(option);
    }
    control.setValue(current);
  }

  stepValue(key: string): string {
    return (this.controlValue(key) as string) || '';
  }

  start(): void {
    if (!this.topic || this.starting) {
      return;
    }
    this.starting = true;
    this.runError = null;
    this.liveGroups = [];
    this.streamSub?.unsubscribe();
    this.streamSub = this.service
      .startResearchStream(this.buildRequest())
      .subscribe({
        next: ev => this.handleStreamEvent(ev),
        error: () => {
          // Stream dropped (e.g. a proxy/idle timeout). If the run already
          // started, keep it visible and poll for the final report.
          this.starting = false;
          if (this.activeReport?.id) {
            this.view = 'running';
            this.startPolling(this.activeReport.id);
          } else {
            this.runError =
              'De verbinding werd verbroken. Probeer het opnieuw.';
          }
        },
        complete: () => {
          // Stream ended without a terminal event → poll for completion.
          if (this.view !== 'report' && this.activeReport?.id) {
            this.startPolling(this.activeReport.id);
          }
        },
      });
  }

  private handleStreamEvent(ev: DeepResearchEvent): void {
    switch (ev.t) {
      case 'start':
        this.starting = false;
        this.view = 'running';
        this.activeReport = {
          id: ev.id,
          topic: ev.topic ?? this.topic,
          status: JobStatus.PROCESSING,
        } as unknown as DeepResearchReport;
        break;
      case 'step':
        this.pushLive(ev);
        break;
      case 'done':
        if (ev.id) {
          this.finishFromStream(ev.id);
        }
        break;
      case 'error':
        this.runError = ev.message ?? 'Onderzoek mislukt.';
        if (ev.id) {
          this.finishFromStream(ev.id);
        } else {
          this.starting = false;
        }
        break;
    }
  }

  private pushLive(ev: DeepResearchEvent): void {
    const base = (ev.author ?? '').startsWith('web_researcher')
      ? 'web_researcher'
      : ev.author ?? '';
    const info = this.agentLabels[base] ?? {label: base || 'Agent', icon: 'bolt'};

    let group = this.liveGroups[this.liveGroups.length - 1];
    if (!group || group.key !== base) {
      group = {key: base, label: info.label, icon: info.icon, lines: []};
      this.liveGroups.push(group);
    }

    let line: string;
    if (ev.kind === 'tool') {
      line =
        ev.text === 'google_search'
          ? 'Web doorzoeken…'
          : ev.text === 'url_context'
            ? 'Bronpagina lezen…'
            : ev.text === 'exit_research_loop'
              ? 'Dekking voldoende — afronden'
              : ev.text || 'tool';
    } else {
      const t = (ev.text ?? '').trim();
      if (!t) {
        return;
      }
      line = t.length > 180 ? t.slice(0, 177) + '…' : t;
    }
    group.lines.push(line);
  }

  private finishFromStream(id: number): void {
    this.streamSub?.unsubscribe();
    this.starting = false;
    this.service.getReport(id).subscribe({
      next: full => {
        this.activeReport = full;
        this.view = 'report';
        this.loadHistory();
      },
      error: () => this.startPolling(id),
    });
  }

  private startPolling(id: number): void {
    this.pollSub?.unsubscribe();
    this.pollSub = interval(POLL_INTERVAL_MS)
      .pipe(switchMap(() => this.service.getReport(id)))
      .subscribe({
        next: report => {
          this.activeReport = report;
          if (report.status !== JobStatus.PROCESSING) {
            this.pollSub?.unsubscribe();
            this.view = 'report';
            this.loadHistory();
          }
        },
        error: () => {},
      });
  }

  openReport(report: DeepResearchReport): void {
    this.pollSub?.unsubscribe();
    this.service.getReport(report.id).subscribe({
      next: full => {
        this.activeReport = full;
        if (full.status === JobStatus.PROCESSING) {
          this.view = 'running';
          this.startPolling(full.id);
        } else {
          this.view = 'report';
        }
      },
      error: () => {},
    });
  }

  newResearch(): void {
    this.pollSub?.unsubscribe();
    this.activeReport = undefined;
    this.runError = null;
    this.view = 'wizard';
    this.step = 0;
    if (this.schema) {
      this.buildForms(this.schema);
    }
    this.maxIterations.setValue(DEFAULT_ITERATIONS);
  }

  deleteReport(report: DeepResearchReport, event: Event): void {
    event.stopPropagation();
    this.service.deleteReport(report.id).subscribe({
      next: () => {
        this.history = this.history.filter(r => r.id !== report.id);
        if (this.activeReport?.id === report.id) {
          this.newResearch();
        }
      },
      error: () => {},
    });
  }

  download(): void {
    const report = this.activeReport;
    if (!report?.report) {
      return;
    }
    const blob = new Blob([report.report], {type: 'text/markdown'});
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${this.slugify(report.topic)}.md`;
    link.click();
    URL.revokeObjectURL(url);
  }

  private slugify(text: string): string {
    return (
      (text || 'report')
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '')
        .slice(0, 60) || 'report'
    );
  }

  statusLabel(status?: JobStatus): string {
    switch (status) {
      case JobStatus.PROCESSING:
        return 'Bezig';
      case JobStatus.COMPLETED:
        return 'Voltooid';
      case JobStatus.FAILED:
        return 'Mislukt';
      case JobStatus.STOPPED:
        return 'Gestopt';
      default:
        return '';
    }
  }
}
