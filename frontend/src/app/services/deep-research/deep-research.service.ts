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

import {
  HttpClient,
  HttpEvent,
  HttpEventType,
  HttpParams,
} from '@angular/common/http';
import {Injectable} from '@angular/core';
import {Observable} from 'rxjs';
import {environment} from '../../../environments/environment';
import {
  DeepResearchReport,
  IntakeSchema,
  PaginatedReports,
  StartDeepResearchRequest,
} from '../../common/models/deep-research.model';

/** One Server-Sent event from the streaming research run. */
export interface DeepResearchEvent {
  t: 'start' | 'step' | 'done' | 'error';
  id?: number;
  topic?: string;
  author?: string;
  kind?: string; // 'tool' | 'text'
  text?: string;
  status?: string;
  message?: string;
}

@Injectable({
  providedIn: 'root',
})
export class DeepResearchService {
  // Note the trailing slash on the collection routes: the backend mounts them
  // at '/api/deep-research/', and hitting the un-slashed path would 307-redirect
  // (dropping the auth header / POST body on some clients).
  private apiUrl = `${environment.backendURL}/deep-research`;

  constructor(private http: HttpClient) {}

  /** Fetch the intake fields + stepper grouping used to render the wizard. */
  getIntakeSchema(): Observable<IntakeSchema> {
    return this.http.get<IntakeSchema>(`${this.apiUrl}/intake-schema`);
  }

  /**
   * Start a scan and stream the agent's progress live (SSE). Uses HttpClient
   * download-progress so the auth interceptor still applies — no manual token
   * handling — and parses the server-sent-events frames as they accumulate.
   */
  startResearchStream(
    request: StartDeepResearchRequest,
  ): Observable<DeepResearchEvent> {
    const req = this.http.post(`${this.apiUrl}/stream`, request, {
      observe: 'events',
      responseType: 'text',
      reportProgress: true,
    });
    return new Observable<DeepResearchEvent>(sub => {
      let seen = 0;
      const emitFrames = (text: string) => {
        let idx: number;
        while ((idx = text.indexOf('\n\n', seen)) >= 0) {
          const frame = text.slice(seen, idx);
          seen = idx + 2;
          const line = frame.split('\n').find(l => l.startsWith('data:'));
          if (!line) continue;
          try {
            sub.next(JSON.parse(line.slice(5).trim()) as DeepResearchEvent);
          } catch {
            // ignore partial / malformed frame
          }
        }
      };
      const inner = req.subscribe({
        next: (ev: HttpEvent<string>) => {
          if (ev.type === HttpEventType.DownloadProgress) {
            emitFrames((ev as {partialText?: string}).partialText ?? '');
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

  /** Kick off a scan; returns the placeholder report (status "processing"). */
  startResearch(
    request: StartDeepResearchRequest,
  ): Observable<DeepResearchReport> {
    return this.http.post<DeepResearchReport>(`${this.apiUrl}/`, request);
  }

  /** List the current user's reports, newest first. */
  listReports(limit = 20, offset = 0): Observable<PaginatedReports> {
    const params = new HttpParams()
      .set('limit', limit)
      .set('offset', offset);
    return this.http.get<PaginatedReports>(`${this.apiUrl}/`, {params});
  }

  /** Fetch a single report (used for polling while it runs). */
  getReport(id: number): Observable<DeepResearchReport> {
    return this.http.get<DeepResearchReport>(`${this.apiUrl}/${id}`);
  }

  /** Delete a report. */
  deleteReport(id: number): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/${id}`);
  }
}
