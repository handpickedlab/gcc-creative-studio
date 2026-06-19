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

import {HttpContext, HttpHandler, HttpRequest} from '@angular/common/http';
import {of} from 'rxjs';

import {AuthInterceptor, SKIP_AUTH} from './auth.interceptor';

describe('AuthInterceptor', () => {
  let authService: jasmine.SpyObj<{
    getValidIdentityPlatformToken$: () => unknown;
    logout: () => void;
  }>;
  let interceptor: AuthInterceptor;

  beforeEach(() => {
    authService = jasmine.createSpyObj('AuthService', [
      'getValidIdentityPlatformToken$',
      'logout',
    ]);
    authService.getValidIdentityPlatformToken$.and.returnValue(of('tok'));
    interceptor = new AuthInterceptor(authService as never);
  });

  function nextSpy(): HttpHandler & {handle: jasmine.Spy} {
    const handle = jasmine
      .createSpy('handle')
      .and.callFake((r: HttpRequest<unknown>) => of(r));
    return {handle} as HttpHandler & {handle: jasmine.Spy};
  }

  it('adds a bearer token to normal requests', done => {
    const next = nextSpy();
    interceptor
      .intercept(new HttpRequest('GET', '/api/briefings'), next)
      .subscribe(() => {
        const sent = next.handle.calls.mostRecent().args[0];
        expect(sent.headers.get('Authorization')).toBe('Bearer tok');
        done();
      });
  });

  it('skips auth entirely when SKIP_AUTH is set', done => {
    const next = nextSpy();
    const req = new HttpRequest('GET', '/api/public/feedback/abc', {
      context: new HttpContext().set(SKIP_AUTH, true),
    });
    interceptor.intercept(req, next).subscribe(() => {
      const sent = next.handle.calls.mostRecent().args[0];
      expect(sent.headers.get('Authorization')).toBeNull();
      // No token fetch => no logout path can be triggered.
      expect(authService.getValidIdentityPlatformToken$).not.toHaveBeenCalled();
      done();
    });
  });

  it('still authenticates a URL that merely contains the word "public"', done => {
    const next = nextSpy();
    interceptor
      .intercept(new HttpRequest('GET', '/api/briefings?name=public'), next)
      .subscribe(() => {
        const sent = next.handle.calls.mostRecent().args[0];
        expect(sent.headers.get('Authorization')).toBe('Bearer tok');
        done();
      });
  });
});
