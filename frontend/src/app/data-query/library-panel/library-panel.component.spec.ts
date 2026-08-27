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

import {NO_ERRORS_SCHEMA} from '@angular/core';
import {ComponentFixture, TestBed} from '@angular/core/testing';
import {MatSnackBar} from '@angular/material/snack-bar';
import {NEVER, of} from 'rxjs';
import {
  ResearchDocument,
  ResearchLibraryService,
} from '../../services/research-library.service';
import {
  LibraryPanelComponent,
  minPeriodFor,
  RecencyPreset,
} from './library-panel.component';

function doc(overrides: Partial<ResearchDocument> = {}): ResearchDocument {
  return {
    id: 1,
    filename: 'deck.pdf',
    mimeType: 'application/pdf',
    docKind: 'slide-deck',
    language: 'nl',
    period: null,
    priorityTier: 'primary',
    status: 'completed',
    errorMessage: null,
    pageCount: 12,
    failedPages: [],
    ...overrides,
  };
}

describe('LibraryPanelComponent', () => {
  let fixture: ComponentFixture<LibraryPanelComponent>;
  let component: LibraryPanelComponent;
  let service: jasmine.SpyObj<ResearchLibraryService>;

  beforeEach(async () => {
    service = jasmine.createSpyObj('ResearchLibraryService', [
      'list',
      'upload',
      'updateTier',
      'delete',
      'reprocess',
    ]);
    service.list.and.returnValue(of({data: [], count: 0}));

    await TestBed.configureTestingModule({
      declarations: [LibraryPanelComponent],
      providers: [
        {provide: ResearchLibraryService, useValue: service},
        {provide: MatSnackBar, useValue: jasmine.createSpyObj('MatSnackBar', ['open'])},
      ],
      schemas: [NO_ERRORS_SCHEMA],
    }).compileComponents();

    fixture = TestBed.createComponent(LibraryPanelComponent);
    component = fixture.componentInstance;
  });

  it('creates and loads documents on init', () => {
    fixture.detectChanges();
    expect(component).toBeTruthy();
    expect(service.list).toHaveBeenCalled();
  });

  it('shows a rejected document with its reason', () => {
    const rejected = doc({
      id: 2,
      status: 'rejected',
      errorMessage: 'Duplicate of deck.pdf (id 1)',
    });
    expect(component.statusDetail(rejected)).toContain('Duplicate of');
    expect(component.isSearchable(rejected)).toBeFalse();
  });

  it('reports failed pages for completed_with_errors', () => {
    const partial = doc({status: 'completed_with_errors', failedPages: [3, 7]});
    expect(component.statusDetail(partial)).toContain('2 page(s) failed');
    expect(component.isSearchable(partial)).toBeTrue();
  });

  it('emits the allowed-document whitelist when toggling', () => {
    const docs = [doc({id: 1}), doc({id: 2, filename: 'report.pdf'})];
    service.list.and.returnValue(of({data: docs, count: 2}));
    fixture.detectChanges();

    const emitted: Array<number[] | null> = [];
    component.allowedDocumentsChange.subscribe(v => emitted.push(v));

    component.toggle(docs[0]);
    expect(emitted[0]).toEqual([2]);

    component.toggle(docs[0]);
    expect(emitted[1]).toBeNull();
  });

  it('never toggles unsearchable documents', () => {
    const processing = doc({id: 3, status: 'processing'});
    const emitted: Array<number[] | null> = [];
    component.allowedDocumentsChange.subscribe(v => emitted.push(v));

    component.toggle(processing);

    expect(emitted.length).toBe(0);
  });

  it('round-trips a tier change', () => {
    const target = doc();
    service.updateTier.and.returnValue(
      of(doc({priorityTier: 'background'})),
    );

    component.setTier(target, 'background');

    expect(service.updateTier).toHaveBeenCalledWith(1, 'background');
    expect(target.priorityTier).toBe('background');
  });

  it('keeps an in-flight tier across a poll refresh', () => {
    const target = doc({priorityTier: 'primary'});
    service.list.and.returnValue(of({data: [target], count: 1}));
    fixture.detectChanges();

    service.updateTier.and.returnValue(NEVER);
    component.setTier(component.documents[0], 'background');
    expect(component.documents[0].priorityTier).toBe('background');

    service.list.and.returnValue(
      of({data: [doc({priorityTier: 'primary'})], count: 1}),
    );
    component.refresh();

    expect(component.documents[0].priorityTier).toBe('background');
  });

  it('keeps a saved tier when a stale list arrives', () => {
    const target = doc({priorityTier: 'primary'});
    service.list.and.returnValue(of({data: [target], count: 1}));
    fixture.detectChanges();

    service.updateTier.and.returnValue(
      of(doc({priorityTier: 'background'})),
    );
    component.setTier(component.documents[0], 'background');

    service.list.and.returnValue(
      of({data: [doc({priorityTier: 'primary'})], count: 1}),
    );
    component.refresh();

    expect(component.documents[0].priorityTier).toBe('background');
  });

  it('emits a YYYY-MM cutoff when recency changes', () => {
    const emitted: Array<string | null> = [];
    component.minPeriodChange.subscribe(v => emitted.push(v));

    component.setRecency('2025');
    expect(emitted[0]).toBe('2025-00');

    component.setRecency('all');
    expect(emitted[1]).toBeNull();
  });
});

describe('minPeriodFor', () => {
  it('returns null for all years', () => {
    expect(minPeriodFor('all')).toBeNull();
  });

  it('maps a year preset onto a year key', () => {
    expect(minPeriodFor('2024')).toBe('2024-00');
    expect(minPeriodFor('2025')).toBe('2025-00');
    expect(minPeriodFor('2026')).toBe('2026-00');
  });

  it('offers whole years only, so a year-labelled claim is never cut', () => {
    // A rolling window put "2025" (-> 2025-00) below a mid-year cutoff and so
    // dropped most of a tracker deck. Every cutoff is now a January key.
    const presets: RecencyPreset[] = ['all', '2024', '2025', '2026'];
    const keys = presets
      .map(p => minPeriodFor(p))
      .filter((k): k is string => k !== null);

    expect(keys.length).toBe(3);
    expect(keys.every(k => k.endsWith('-00'))).toBe(true);
  });
});
