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

export interface Market {
  code: string;
  label: string;
}

export interface BriefingSegment {
  block: string | null;
  field: string;
  label: string;
  charLimit: number | null;
  text: string;
}

export interface BriefingMeta {
  requestLabel?: string | null;
  email?: string | null;
  requestor?: string | null;
  dateEmail?: string | null;
  due?: string | null;
  notes?: string | null;
}

export interface Briefing {
  name: string;
  sourceMarket: string;
  meta: BriefingMeta;
  segments: BriefingSegment[];
}

export interface ParseResult {
  sheets: string[];
  selectedSheet: string | null;
  requests: {index: number; label: string; filled: number}[];
  briefingName: string | null;
  meta: BriefingMeta | null;
  segments: BriefingSegment[];
}

export interface MarketTranslation {
  market: string;
  segments: BriefingSegment[];
}

export interface GlossarySummary {
  total: number;
  perMarket: {
    market: string;
    count: number;
    samples: {source: string; target: string}[];
  }[];
}

export interface GlossaryTerm {
  id: number;
  language: string; // market code
  source: string;
  target: string;
}

@Injectable({
  providedIn: 'root',
})
export class TranslationService {
  private readonly baseUrl = `${environment.backendURL}/briefings`;

  constructor(private http: HttpClient) {}

  getMarkets(): Observable<Market[]> {
    return this.http.get<Market[]>(`${this.baseUrl}/markets`);
  }

  /** Upload an xlsx. Without requestIndex returns sheets+requests (discovery);
   * with sheet+requestIndex returns the parsed briefing. */
  upload(
    file: File,
    sheetName?: string,
    requestIndex?: number,
  ): Observable<ParseResult> {
    const form = new FormData();
    form.append('file', file);
    if (sheetName != null) form.append('sheet_name', sheetName);
    if (requestIndex != null) {
      form.append('request_index', String(requestIndex));
    }
    return this.http.post<ParseResult>(`${this.baseUrl}/upload`, form);
  }

  importTranslationMemory(
    file: File,
  ): Observable<{imported: number; markets: string[]}> {
    const form = new FormData();
    form.append('file', file);
    return this.http.post<{imported: number; markets: string[]}>(
      `${this.baseUrl}/import-tm`,
      form,
    );
  }

  getGlossarySummary(): Observable<GlossarySummary> {
    return this.http.get<GlossarySummary>(`${this.baseUrl}/glossary/summary`);
  }

  getGlossaryTerms(market: string, q?: string): Observable<GlossaryTerm[]> {
    let url = `${this.baseUrl}/glossary?market=${encodeURIComponent(market)}`;
    if (q) url += `&q=${encodeURIComponent(q)}`;
    return this.http.get<GlossaryTerm[]>(url);
  }

  createGlossaryTerm(
    market: string,
    source: string,
    target: string,
  ): Observable<GlossaryTerm> {
    return this.http.post<GlossaryTerm>(`${this.baseUrl}/glossary`, {
      market,
      source,
      target,
    });
  }

  updateGlossaryTerm(
    id: number,
    data: {source?: string; target?: string},
  ): Observable<GlossaryTerm> {
    return this.http.put<GlossaryTerm>(`${this.baseUrl}/glossary/${id}`, data);
  }

  deleteGlossaryTerm(id: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/glossary/${id}`);
  }

  translate(
    briefing: Briefing,
    markets: string[],
  ): Observable<{translations: MarketTranslation[]}> {
    return this.http.post<{translations: MarketTranslation[]}>(
      `${this.baseUrl}/translate`,
      {briefing, markets},
    );
  }

  save(
    briefing: Briefing,
    translations: MarketTranslation[],
  ): Observable<{id: number}> {
    return this.http.post<{id: number}>(`${this.baseUrl}`, {
      briefing,
      translations,
    });
  }

  exportXlsx(
    briefing: Briefing,
    translations: MarketTranslation[],
  ): Observable<Blob> {
    return this.http.post(
      `${this.baseUrl}/export`,
      {briefing, translations},
      {responseType: 'blob'},
    );
  }
}
