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

import {HttpClient, HttpParams} from '@angular/common/http';
import {Injectable} from '@angular/core';
import {Observable} from 'rxjs';
import {environment} from '../../../environments/environment';
import {
  DeepResearchReport,
  IntakeSchema,
  PaginatedReports,
  StartDeepResearchRequest,
} from '../../common/models/deep-research.model';

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
