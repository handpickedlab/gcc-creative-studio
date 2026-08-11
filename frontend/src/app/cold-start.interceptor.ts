/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import {
  HttpErrorResponse,
  HttpEvent,
  HttpHandler,
  HttpInterceptor,
  HttpRequest,
} from '@angular/common/http';
import {Injectable} from '@angular/core';
import {Observable, throwError, timer} from 'rxjs';
import {retry} from 'rxjs/operators';

import {NotificationService} from './common/services/notification.service';

/**
 * Smooths over Cloud Run cold starts (min-instances = 0).
 *
 * While the backend boots, the hosting rewrite answers 502/503/504. Idempotent
 * requests are retried with a backoff that comfortably covers the boot time;
 * the user sees a "waking up" notice instead of a broken page. Non-GET
 * requests are never replayed automatically — the user is told to retry.
 */
@Injectable()
export class ColdStartInterceptor implements HttpInterceptor {
  private static readonly RETRYABLE_STATUS = [502, 503, 504];
  private static readonly RETRY_DELAYS_MS = [4000, 8000, 15000];

  private noticeShown = false;

  constructor(private notifications: NotificationService) {}

  intercept(
    req: HttpRequest<unknown>,
    next: HttpHandler,
  ): Observable<HttpEvent<unknown>> {
    return next.handle(req).pipe(
      retry({
        delay: (error: unknown, retryCount: number) => {
          if (
            !(error instanceof HttpErrorResponse) ||
            !ColdStartInterceptor.RETRYABLE_STATUS.includes(error.status) ||
            retryCount > ColdStartInterceptor.RETRY_DELAYS_MS.length
          ) {
            return throwError(() => error);
          }
          if (req.method !== 'GET' && req.method !== 'HEAD') {
            this.notify(
              'The studio is waking up — please try that again in a moment.',
            );
            return throwError(() => error);
          }
          this.notify('The studio is waking up — retrying automatically…');
          return timer(ColdStartInterceptor.RETRY_DELAYS_MS[retryCount - 1]);
        },
      }),
    );
  }

  private notify(message: string) {
    if (this.noticeShown) {
      return;
    }
    this.noticeShown = true;
    this.notifications.show(message, 'info', undefined, 'hourglass_top', 20000);
    // Allow a fresh notice for the next cold start, not for every request
    // in this burst.
    setTimeout(() => (this.noticeShown = false), 30000);
  }
}
