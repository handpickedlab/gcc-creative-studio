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

/** Status of a long-running research job (mirrors the backend JobStatusEnum). */
export enum JobStatus {
  PROCESSING = 'processing',
  COMPLETED = 'completed',
  FAILED = 'failed',
  STOPPED = 'stopped',
}

/** How an intake field is captured (mirrors the backend FieldType). */
export enum IntakeFieldType {
  FREE_TEXT = 'free_text',
  SINGLE_SELECT = 'single_select',
  SINGLE_SELECT_CUSTOM = 'single_select_custom',
  MULTI_SELECT = 'multi_select',
  COMPETITOR = 'competitor',
}

/** One intake question, as described by the backend intake schema. */
export interface IntakeField {
  key: string;
  label: string;
  type: IntakeFieldType;
  briefLabel: string;
  options: string[];
  example: string;
  help: string;
}

/** One step of the wizard: a title and the field keys it groups. */
export interface IntakeStep {
  title: string;
  fieldKeys: string[];
}

/** The full intake schema returned by GET /deep-research/intake-schema. */
export interface IntakeSchema {
  fields: IntakeField[];
  steps: IntakeStep[];
}

/** A persisted deep research report. */
export interface DeepResearchReport {
  id: number;
  userId: number;
  topic: string;
  status: JobStatus;
  errorMessage?: string | null;
  maxIterations?: number | null;
  intake: Record<string, string | string[]>;
  progress?: ProgressEvent[];
  brief?: string | null;
  report?: string | null;
  createdAt: string;
  updatedAt: string;
}

/** One live progress step recorded while the pipeline runs. */
export interface ProgressEvent {
  author: string;
  kind: string; // 'tool' | 'text'
  text: string;
}

/**
 * Request body to start a scan. Keys are the snake_case intake field keys; the
 * backend accepts them by name (populate_by_name) alongside its camelCase
 * aliases, so we build the payload directly from the intake field keys.
 */
export interface StartDeepResearchRequest {
  research_topic: string;
  market?: string | null;
  customer_lens?: string | null;
  gender?: string[];
  research_goal?: string | null;
  category_focus?: string[];
  consumer_angle?: string[];
  time_horizon?: string | null;
  source_preference?: string[];
  competitor_context?: string | null;
  output_usage?: string | null;
  max_iterations?: number | null;
}

/** A page of reports from GET /deep-research/. */
export interface PaginatedReports {
  data: DeepResearchReport[];
  count: number;
  page: number;
  pageSize: number;
  totalPages: number;
}
