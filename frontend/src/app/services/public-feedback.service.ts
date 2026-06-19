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

import {HttpClient, HttpContext} from '@angular/common/http';
import {Injectable} from '@angular/core';
import {Observable} from 'rxjs';
import {environment} from '../../environments/environment';
import {SKIP_AUTH} from '../auth.interceptor';

export interface PublicFeedbackItem {
  index: number;
  block: string | null;
  field: string;
  label: string;
  charLimit: number | null;
  source: string;
  translation: string;
}

export type TicketStatus = 'open' | 'in_progress' | 'resolved';

export interface PublicTicket {
  id: number;
  segmentIndex: number;
  authorName: string;
  authorRole: 'content_manager' | 'translator';
  body: string;
  status: TicketStatus;
  createdAt?: string;
  itemChanged: boolean;
}

export interface PublicFeedbackView {
  briefingName: string;
  market: string;
  marketLabel: string;
  items: PublicFeedbackItem[];
  tickets: PublicTicket[];
}

/**
 * Client for the unauthenticated translator feedback endpoints. Every request
 * opts out of the auth interceptor via the SKIP_AUTH context token, so it
 * carries no Firebase token and never triggers a logout — the share token is
 * the only credential.
 */
@Injectable({providedIn: 'root'})
export class PublicFeedbackService {
  private readonly baseUrl = `${environment.backendURL}/public/feedback`;

  constructor(private http: HttpClient) {}

  private noAuth(): {context: HttpContext} {
    return {context: new HttpContext().set(SKIP_AUTH, true)};
  }

  getByToken(token: string): Observable<PublicFeedbackView> {
    return this.http.get<PublicFeedbackView>(
      `${this.baseUrl}/${encodeURIComponent(token)}`,
      this.noAuth(),
    );
  }

  addTicket(
    token: string,
    payload: {segmentIndex: number; authorName: string; body: string},
  ): Observable<PublicTicket> {
    return this.http.post<PublicTicket>(
      `${this.baseUrl}/${encodeURIComponent(token)}/tickets`,
      payload,
      this.noAuth(),
    );
  }
}
