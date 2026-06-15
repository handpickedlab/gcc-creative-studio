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

export interface GlossaryTerm {
  id: number;
  language: string;
  source: string;
  target: string;
}

export interface TranslationResult {
  language: string;
  translation: string;
}

export interface TranslateResponse {
  results: TranslationResult[];
}

export interface TranslateRequest {
  text: string;
  target_languages: string[];
  tone?: string | null;
}

@Injectable({
  providedIn: 'root',
})
export class TranslationService {
  private readonly baseUrl = `${environment.backendURL}/translations`;

  constructor(private http: HttpClient) {}

  translate(payload: TranslateRequest): Observable<TranslateResponse> {
    return this.http.post<TranslateResponse>(
      `${this.baseUrl}/translate`,
      payload,
    );
  }

  getGlossary(): Observable<GlossaryTerm[]> {
    return this.http.get<GlossaryTerm[]>(`${this.baseUrl}/glossary`);
  }

  createTerm(payload: {
    language: string;
    source: string;
    target: string;
  }): Observable<GlossaryTerm> {
    return this.http.post<GlossaryTerm>(`${this.baseUrl}/glossary`, payload);
  }

  updateTerm(
    id: number,
    payload: {language?: string; source?: string; target?: string},
  ): Observable<GlossaryTerm> {
    return this.http.put<GlossaryTerm>(
      `${this.baseUrl}/glossary/${id}`,
      payload,
    );
  }

  deleteTerm(id: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/glossary/${id}`);
  }
}
