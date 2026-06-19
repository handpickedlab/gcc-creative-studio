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

// --- Feedback loop ---

export type ReviewState = 'draft' | 'in_review' | 'done';
export type FeedbackStatus = 'open' | 'in_progress' | 'resolved';
export type LinkStatus = 'none' | 'active' | 'expired' | 'revoked';

export interface FeedbackTicket {
  id: number;
  briefingId: number;
  market: string;
  segmentIndex: number;
  fieldSnapshot?: string | null;
  sourceSnapshot?: string | null;
  authorName: string;
  authorRole: 'content_manager' | 'translator';
  body: string;
  status: FeedbackStatus;
  resolutionNote?: string | null;
  statusChangedAt?: string | null;
  createdAt?: string;
  itemChanged: boolean;
}

export interface MarketCounts {
  open: number;
  inProgress: number;
  resolved: number;
}

export interface MarketOverview {
  market: string;
  reviewState: ReviewState;
  linkStatus: LinkStatus;
  expiresAt?: string | null;
  counts: MarketCounts;
}

export interface BriefingFeedback {
  markets: MarketOverview[];
  tickets: FeedbackTicket[];
}

export interface ShareLink {
  token: string;
  expiresAt: string;
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
    tone?: string,
  ): Observable<{translations: MarketTranslation[]}> {
    return this.http.post<{translations: MarketTranslation[]}>(
      `${this.baseUrl}/translate`,
      {briefing, markets, tone},
    );
  }

  listBriefings(): Observable<(Briefing & {id: number; createdAt?: string})[]> {
    return this.http.get<(Briefing & {id: number; createdAt?: string})[]>(
      `${this.baseUrl}`,
    );
  }

  getBriefing(
    id: number,
  ): Observable<{briefing: Briefing; translations: MarketTranslation[]}> {
    return this.http.get<{briefing: Briefing; translations: MarketTranslation[]}>(
      `${this.baseUrl}/${id}`,
    );
  }

  renameBriefing(id: number, name: string): Observable<void> {
    return this.http.patch<void>(`${this.baseUrl}/${id}`, {name});
  }

  deleteBriefing(id: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${id}`);
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

  // --- Feedback loop (content-manager side) ---

  getFeedback(briefingId: number): Observable<BriefingFeedback> {
    return this.http.get<BriefingFeedback>(
      `${this.baseUrl}/${briefingId}/feedback`,
    );
  }

  createTicket(
    briefingId: number,
    market: string,
    payload: {segmentIndex: number; body: string},
  ): Observable<FeedbackTicket> {
    return this.http.post<FeedbackTicket>(
      `${this.baseUrl}/${briefingId}/markets/${encodeURIComponent(market)}/tickets`,
      payload,
    );
  }

  updateTicket(
    ticketId: number,
    payload: {status: FeedbackStatus; resolutionNote?: string | null},
  ): Observable<FeedbackTicket> {
    return this.http.patch<FeedbackTicket>(
      `${this.baseUrl}/tickets/${ticketId}`,
      payload,
    );
  }

  setReviewState(
    briefingId: number,
    market: string,
    reviewState: ReviewState,
  ): Observable<MarketOverview> {
    return this.http.patch<MarketOverview>(
      `${this.baseUrl}/${briefingId}/markets/${encodeURIComponent(market)}/review-state`,
      {reviewState},
    );
  }

  createShareLink(briefingId: number, market: string): Observable<ShareLink> {
    return this.http.post<ShareLink>(
      `${this.baseUrl}/${briefingId}/markets/${encodeURIComponent(market)}/share-link`,
      {},
    );
  }

  revokeShareLink(briefingId: number, market: string): Observable<void> {
    return this.http.delete<void>(
      `${this.baseUrl}/${briefingId}/markets/${encodeURIComponent(market)}/share-link`,
    );
  }
}
