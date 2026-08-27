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

import {HttpClient} from '@angular/common/http';
import {Injectable} from '@angular/core';
import {Observable} from 'rxjs';
import {environment} from '../../environments/environment';

export interface LoadedTable {
  table: string;
  sheet: string;
  n_rows: number;
  columns: string[];
  source_file: string;
}

export interface SourceTable {
  table: string;
  n_rows: number | null;
}

/** A durably-cataloged uploaded sheet (manage page). */
export interface SheetInfo {
  id: number;
  tableName: string;
  sourceFile: string;
  sheet: string | null;
  nRows: number | null;
  nCols: number | null;
  columns: string[];
  createdAt?: string;
}

export interface SqlResult {
  columns?: string[];
  rows?: Record<string, unknown>[];
  row_count?: number;
  truncated?: boolean;
  error?: string;
}

/** A citation behind a research-library fact in the answer. */
export interface ClaimSource {
  claim_id: number;
  document_id: number;
  document: string;
  page: number;
  statement?: string;
  period?: string | null;
  source_citation?: string | null;
}

/**
 * One assembled step of the agent's trace: narrated text, a tool call, or —
 * only while the run is in flight — a ``model`` marker saying the agent is
 * mid-turn. The marker never survives into a finished run.
 */
export interface AgentStep {
  kind: 'text' | 'tool' | 'model';
  text?: string;
  name?: string;
  input?: Record<string, unknown>;
  summary?: string;
  result?: SqlResult | null;
  /** How long the tool call took, in ms (tool steps, once finished). */
  ms?: number;
  /** Which loop step the agent is on (``model`` markers). */
  n?: number;
}

/** A background ask run: kicked off by POST /ask, polled via GET /ask/{id}. */
export interface DataQueryRun {
  id: string;
  status: 'processing' | 'completed' | 'failed';
  question: string;
  steps: AgentStep[];
  answerSources: ClaimSource[];
  errorMessage?: string | null;
}

@Injectable({providedIn: 'root'})
export class DataQueryService {
  private readonly baseUrl = `${environment.backendURL}/data-query`;

  constructor(private http: HttpClient) {}

  /** Upload a .csv/.xlsx; it's loaded into DuckDB as one or more tables. */
  upload(file: File): Observable<{loaded: LoadedTable[]}> {
    const form = new FormData();
    form.append('file', file);
    return this.http.post<{loaded: LoadedTable[]}>(`${this.baseUrl}/upload`, form);
  }

  /** List the uploaded tables (lightweight, for the query sidebar). */
  sources(): Observable<{tables: SourceTable[]}> {
    return this.http.get<{tables: SourceTable[]}>(`${this.baseUrl}/sources`);
  }

  /** List uploaded sheets with metadata (manage page). */
  sheets(): Observable<SheetInfo[]> {
    return this.http.get<SheetInfo[]>(`${this.baseUrl}/sheets`);
  }

  /** Delete an uploaded sheet (catalog row + warehouse table + raw file). */
  deleteSheet(id: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/sheets/${id}`);
  }

  /**
   * Kick off a background ask; returns the run immediately (status
   * ``processing``). Deep retrieval can outlast the hosting rewrite's ~60s
   * timeout on a buffered stream, so the answer is built server-side and the
   * caller polls {@link getRun} for accumulating steps + the final answer.
   */
  startAsk(
    question: string,
    allowedTables: string[] | null,
    allowedDocuments: number[] | null = null,
    history: {question: string; answer: string}[] = [],
    minPeriod: string | null = null,
  ): Observable<DataQueryRun> {
    return this.http.post<DataQueryRun>(`${this.baseUrl}/ask`, {
      question,
      history,
      allowed_tables: allowedTables,
      allowed_documents: allowedDocuments,
      min_period: minPeriod,
    });
  }

  /** Fetch a run's current state (poll this until status !== 'processing'). */
  getRun(id: string): Observable<DataQueryRun> {
    return this.http.get<DataQueryRun>(`${this.baseUrl}/ask/${id}`);
  }
}
