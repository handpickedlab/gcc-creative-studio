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

import {Injectable} from '@angular/core';
import {
  HttpRequest,
  HttpHandler,
  HttpEvent,
  HttpInterceptor,
  HttpErrorResponse,
  HttpContextToken,
} from '@angular/common/http';
import {Observable, throwError} from 'rxjs';
import {catchError, switchMap} from 'rxjs/operators';
import {AuthService} from './common/services/auth.service';

/**
 * Opt a request out of authentication. Requests that set this context token are
 * sent WITHOUT an Authorization header and never trigger a logout on failure.
 * This is the only sanctioned way to bypass auth — used by the public
 * translator-feedback endpoints. We deliberately do NOT match on URL substrings
 * (e.g. "/public/"), which would be a fragile, accidental coupling.
 */
export const SKIP_AUTH = new HttpContextToken<boolean>(() => false);

@Injectable()
export class AuthInterceptor implements HttpInterceptor {
  constructor(private authService: AuthService) {}

  intercept(
    request: HttpRequest<unknown>,
    next: HttpHandler,
  ): Observable<HttpEvent<unknown>> {
    // Explicitly unauthenticated requests pass straight through.
    if (request.context.get(SKIP_AUTH)) {
      return next.handle(request);
    }

    // Asynchronously get a valid token. This will use the cache or trigger a silent refresh.
    return this.authService.getValidIdentityPlatformToken$().pipe(
      switchMap(token => {
        // Token was retrieved successfully. Clone the request and add the auth header.
        const authorizedRequest = request.clone({
          setHeaders: {Authorization: `Bearer ${token}`},
        });
        return next.handle(authorizedRequest);
      }),
      catchError(error => {
        // If the error is NOT an HttpErrorResponse, it's a token refresh failure
        // from our AuthService. In this case, the session is invalid, and we should log out.
        if (!(error instanceof HttpErrorResponse)) {
          console.error(
            'AuthInterceptor: Session expired and could not be refreshed. Logging out.',
            error,
          );
          void this.authService.logout();
        }

        // Otherwise, it's a backend API error (e.g., 404, 500). We should NOT log out.
        // We just re-throw the original HttpErrorResponse so the calling service
        // (e.g., UserService) can handle it and display an appropriate error message.
        return throwError(() => error);
      }),
    );
  }
}
