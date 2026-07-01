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
import {DeepResearchService} from '../services/deep-research/deep-research.service';

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

  view: ViewState = 'wizard';
  activeReport?: DeepResearchReport;
  starting = false;
  runError: string | null = null;

  history: DeepResearchReport[] = [];

  private pollSub?: Subscription;

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

  private buildRequest(): StartDeepResearchRequest {
    const request: Record<string, unknown> = {};
    this.schema?.fields.forEach(field => {
      request[field.key] = this.resolveField(field);
    });
    request['max_iterations'] = this.maxIterations.value ?? DEFAULT_ITERATIONS;
    return request as unknown as StartDeepResearchRequest;
  }

  // --- Wizard interactions ---------------------------------------------------

  setValue(stepIndex: number, key: string, value: string): void {
    this.stepForms[stepIndex]?.get(key)?.setValue(value);
  }

  start(): void {
    if (!this.topic || this.starting) {
      return;
    }
    this.starting = true;
    this.runError = null;
    this.service.startResearch(this.buildRequest()).subscribe({
      next: report => {
        this.starting = false;
        this.activeReport = report;
        if (report.status === JobStatus.PROCESSING) {
          this.view = 'running';
          this.startPolling(report.id);
        } else {
          this.view = 'report';
        }
        this.loadHistory();
      },
      error: () => {
        this.starting = false;
        this.runError = 'Kon het onderzoek niet starten. Probeer het opnieuw.';
      },
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
