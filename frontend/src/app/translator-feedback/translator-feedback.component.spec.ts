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

import {of, throwError} from 'rxjs';

import {TranslatorFeedbackComponent} from './translator-feedback.component';
import {PublicFeedbackView} from '../services/public-feedback.service';

function routeWithToken(token: string): never {
  return {snapshot: {paramMap: {get: () => token}}} as never;
}

const VIEW: PublicFeedbackView = {
  briefingName: 'Q3 Campaign',
  market: 'NL',
  marketLabel: 'Dutch (Netherlands)',
  items: [
    {
      index: 0,
      block: 'B1',
      field: 'Header',
      label: 'Header',
      charLimit: 34,
      source: 'Shop now',
      translation: 'Koop nu',
    },
  ],
  tickets: [],
};

describe('TranslatorFeedbackComponent', () => {
  let service: jasmine.SpyObj<{
    getByToken: () => unknown;
    addTicket: () => unknown;
  }>;

  beforeEach(() => {
    service = jasmine.createSpyObj('PublicFeedbackService', [
      'getByToken',
      'addTicket',
    ]);
  });

  it('loads the view for a valid token', () => {
    service.getByToken.and.returnValue(of(VIEW));
    const c = new TranslatorFeedbackComponent(
      routeWithToken('tok'),
      service as never,
    );
    c.ngOnInit();
    expect(c.loading).toBeFalse();
    expect(c.errorState).toBeNull();
    expect(c.view?.market).toBe('NL');
  });

  it('shows the expired state on a 410', () => {
    service.getByToken.and.returnValue(throwError(() => ({status: 410})));
    const c = new TranslatorFeedbackComponent(
      routeWithToken('expired'),
      service as never,
    );
    c.ngOnInit();
    expect(c.errorState).toBe('expired');
    expect(c.view).toBeNull();
  });

  it('shows the unknown state on a 404', () => {
    service.getByToken.and.returnValue(throwError(() => ({status: 404})));
    const c = new TranslatorFeedbackComponent(
      routeWithToken('bogus'),
      service as never,
    );
    c.ngOnInit();
    expect(c.errorState).toBe('unknown');
  });

  it('requires a name before a comment can be submitted', () => {
    service.getByToken.and.returnValue(of(VIEW));
    const c = new TranslatorFeedbackComponent(
      routeWithToken('tok'),
      service as never,
    );
    c.ngOnInit();
    c.translatorName = '';
    c.drafts[0] = 'te lang';
    expect(c.canSubmit(0)).toBeFalse();
    c.translatorName = 'Sanne';
    expect(c.canSubmit(0)).toBeTrue();
  });

  it('appends the created ticket and clears the draft on submit', () => {
    service.getByToken.and.returnValue(of(VIEW));
    service.addTicket.and.returnValue(
      of({
        id: 1,
        segmentIndex: 0,
        authorName: 'Sanne',
        authorRole: 'translator',
        body: 'te lang',
        status: 'open',
        itemChanged: false,
      }),
    );
    const c = new TranslatorFeedbackComponent(
      routeWithToken('tok'),
      service as never,
    );
    c.ngOnInit();
    c.translatorName = 'Sanne';
    c.drafts[0] = 'te lang';
    c.submit(0);
    expect(c.view?.tickets.length).toBe(1);
    expect(c.drafts[0]).toBe('');
  });
});
