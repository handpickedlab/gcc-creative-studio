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

import {HttpClient, HttpEvent, HttpEventType} from '@angular/common/http';
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

export interface SqlResult {
  columns?: string[];
  rows?: Record<string, unknown>[];
  row_count?: number;
  truncated?: boolean;
  error?: string;
}

/** One event from the streaming agent. */
export interface AgentEvent {
  t: 'tool' | 'tool_result' | 'text' | 'error' | 'done';
  v?: string;
  name?: string;
  input?: Record<string, unknown>;
  summary?: string;
  result?: SqlResult | null;
  message?: string;
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

  /** List the uploaded tables. */
  sources(): Observable<{tables: SourceTable[]}> {
    return this.http.get<{tables: SourceTable[]}>(`${this.baseUrl}/sources`);
  }

  /**
   * Ask a question; emits the agent's events live (tool calls, results, answer).
   * Uses HttpClient download-progress so the auth interceptor still applies — no
   * manual token handling needed. Parses the server-sent-events frames as they
   * accumulate in `partialText`.
   */
  ask(question: string, allowedTables: string[] | null): Observable<AgentEvent> {
    const req = this.http.post(
      `${this.baseUrl}/ask`,
      {question, allowed_tables: allowedTables},
      {observe: 'events', responseType: 'text', reportProgress: true},
    );
    return new Observable<AgentEvent>(sub => {
      let seen = 0;
      const emitFrames = (text: string) => {
        let idx: number;
        while ((idx = text.indexOf('\n\n', seen)) >= 0) {
          const frame = text.slice(seen, idx);
          seen = idx + 2;
          const line = frame.split('\n').find(l => l.startsWith('data:'));
          if (!line) continue;
          try {
            sub.next(JSON.parse(line.slice(5).trim()) as AgentEvent);
          } catch {
            // ignore partial / malformed frame
          }
        }
      };
      const inner = req.subscribe({
        next: (ev: HttpEvent<string>) => {
          if (ev.type === HttpEventType.DownloadProgress) {
            emitFrames(((ev as {partialText?: string}).partialText) ?? '');
          } else if (ev.type === HttpEventType.Response) {
            if (typeof ev.body === 'string') emitFrames(ev.body);
            sub.complete();
          }
        },
        error: err => sub.error(err),
        complete: () => sub.complete(),
      });
      return () => inner.unsubscribe();
    });
  }
}
