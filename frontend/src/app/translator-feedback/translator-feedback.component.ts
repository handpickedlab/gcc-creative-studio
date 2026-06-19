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

import {Component, OnInit} from '@angular/core';
import {ActivatedRoute} from '@angular/router';

import {
  PublicFeedbackService,
  PublicFeedbackView,
  PublicTicket,
} from '../services/public-feedback.service';

const NAME_KEY = 'hkm_translator_name';

/**
 * Public, account-less view-only page reached via a per-market share link
 * (/feedback/:token). The translator sees source + translation side by side
 * and may only leave feedback tickets — no editing. Served without the app
 * nav (see AppComponent) and without auth (the token is the only credential).
 */
@Component({
  selector: 'app-translator-feedback',
  templateUrl: './translator-feedback.component.html',
  styleUrls: ['./translator-feedback.component.scss'],
})
export class TranslatorFeedbackComponent implements OnInit {
  token = '';
  loading = true;
  errorState: 'expired' | 'unknown' | 'generic' | null = null;
  view: PublicFeedbackView | null = null;

  translatorName = '';
  drafts: Record<number, string> = {};
  submitting: Record<number, boolean> = {};

  constructor(
    private route: ActivatedRoute,
    private service: PublicFeedbackService,
  ) {}

  ngOnInit(): void {
    this.token = this.route.snapshot.paramMap.get('token') ?? '';
    try {
      this.translatorName = localStorage.getItem(NAME_KEY) ?? '';
    } catch {
      // localStorage may be unavailable; not fatal.
    }
    this.load();
  }

  private load(): void {
    this.loading = true;
    this.errorState = null;
    this.service.getByToken(this.token).subscribe({
      next: v => {
        this.view = v;
        this.loading = false;
      },
      error: err => {
        this.loading = false;
        const code = err?.status;
        this.errorState =
          code === 410 ? 'expired' : code === 404 ? 'unknown' : 'generic';
      },
    });
  }

  ticketsFor(index: number): PublicTicket[] {
    return (this.view?.tickets ?? []).filter(t => t.segmentIndex === index);
  }

  roleLabel(role: string): string {
    return role === 'translator' ? 'Vertaler' : 'Content manager';
  }

  statusLabel(status: string): string {
    return status === 'open'
      ? 'Open'
      : status === 'in_progress'
        ? 'Opgepakt'
        : 'Opgelost';
  }

  statusColor(status: string): string {
    return status === 'resolved'
      ? '#7AAE88'
      : status === 'in_progress'
        ? '#D99A40'
        : '#C77';
  }

  canSubmit(index: number): boolean {
    return (
      !!this.translatorName.trim() &&
      !!(this.drafts[index] ?? '').trim() &&
      !this.submitting[index]
    );
  }

  submit(index: number): void {
    const name = this.translatorName.trim();
    const body = (this.drafts[index] ?? '').trim();
    if (!name || !body) return;
    try {
      localStorage.setItem(NAME_KEY, name);
    } catch {
      // ignore
    }
    this.submitting[index] = true;
    this.service
      .addTicket(this.token, {segmentIndex: index, authorName: name, body})
      .subscribe({
        next: ticket => {
          if (this.view) this.view.tickets = [...this.view.tickets, ticket];
          this.drafts[index] = '';
          this.submitting[index] = false;
        },
        error: () => {
          this.submitting[index] = false;
        },
      });
  }
}
