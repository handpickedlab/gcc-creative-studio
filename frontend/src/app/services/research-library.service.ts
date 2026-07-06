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

import {HttpClient, HttpContext, HttpHeaders} from '@angular/common/http';
import {Injectable} from '@angular/core';
import {Observable} from 'rxjs';
import {switchMap} from 'rxjs/operators';
import {environment} from '../../environments/environment';
import {SKIP_AUTH} from '../auth.interceptor';

export type PriorityTier = 'primary' | 'supporting' | 'background';

export type ResearchDocStatus =
  | 'processing'
  | 'completed'
  | 'completed_with_errors'
  | 'failed'
  | 'stopped'
  | 'rejected';

export interface ResearchDocument {
  id: number;
  filename: string;
  mimeType: string;
  docKind: string | null;
  language: string | null;
  period: string | null;
  priorityTier: PriorityTier;
  status: ResearchDocStatus;
  errorMessage: string | null;
  pageCount: number | null;
  failedPages: number[];
  createdAt?: string;
}

interface GenerateUploadUrlResponse {
  uploadUrl: string;
  gcsUri: string;
}

@Injectable({providedIn: 'root'})
export class ResearchLibraryService {
  private readonly baseUrl = `${environment.backendURL}/research-library`;

  constructor(private http: HttpClient) {}

  /**
   * Uploads one document: signed-URL handshake, direct PUT to GCS (outside
   * the auth interceptor — a signed URL must be the ONLY authentication on
   * that request), then finalize to queue ingest. Emits the created
   * document row (which may be a visible REJECTED duplicate marker).
   */
  upload(file: File): Observable<ResearchDocument> {
    return this.http
      .post<GenerateUploadUrlResponse>(`${this.baseUrl}/generate-upload-url`, {
        filename: file.name,
        mimeType: file.type || 'application/octet-stream',
        sizeBytes: file.size,
      })
      .pipe(
        switchMap(({uploadUrl, gcsUri}) =>
          this.http
            .put(uploadUrl, file, {
              headers: new HttpHeaders({
                'Content-Type': file.type || 'application/octet-stream',
              }),
              context: new HttpContext().set(SKIP_AUTH, true),
            })
            .pipe(
              switchMap(() =>
                this.http.post<ResearchDocument>(
                  `${this.baseUrl}/finalize-upload`,
                  {
                    gcsUri,
                    filename: file.name,
                    mimeType: file.type || 'application/octet-stream',
                  },
                ),
              ),
            ),
        ),
      );
  }

  list(limit = 100, offset = 0): Observable<{data: ResearchDocument[]; count: number}> {
    return this.http.get<{data: ResearchDocument[]; count: number}>(
      `${this.baseUrl}/documents`,
      {params: {limit, offset}},
    );
  }

  updateTier(id: number, tier: PriorityTier): Observable<ResearchDocument> {
    return this.http.patch<ResearchDocument>(
      `${this.baseUrl}/documents/${id}`,
      {priorityTier: tier},
    );
  }

  delete(id: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/documents/${id}`);
  }

  reprocess(id: number): Observable<ResearchDocument> {
    return this.http.post<ResearchDocument>(
      `${this.baseUrl}/documents/${id}/reprocess`,
      {},
    );
  }

  /** The rendered page image behind a citation, as a blob (auth applies). */
  pageImage(
    documentId: number,
    pageNo: number,
    thumb = false,
  ): Observable<Blob> {
    return this.http.get(
      `${this.baseUrl}/documents/${documentId}/pages/${pageNo}/image`,
      {params: {thumb}, responseType: 'blob'},
    );
  }
}
