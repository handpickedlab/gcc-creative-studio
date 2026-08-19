/**
 * Copyright 2026 Google LLC — Licensed under the Apache License, Version 2.0.
 *
 * Reading a finished section while the rest of the document is still being
 * translated: only that section's segments are fetched, a slower earlier
 * response can never overwrite a newer pick, and the run progress keeps
 * flowing underneath.
 */

import {ComponentFixture, TestBed} from '@angular/core/testing';
import {Subject, of} from 'rxjs';
import {NO_ERRORS_SCHEMA} from '@angular/core';
import {DocumentsComponent} from './documents.component';
import {
  ApiJob,
  ApiSegment,
  DocumentTranslationsService,
} from './document-translations.service';

function seg(over: Partial<ApiSegment> = {}): ApiSegment {
  return {
    id: 1,
    jobId: 'j1',
    segIndex: 1,
    kind: 'prose',
    sectionId: '1.1',
    bold: false,
    sourceText: 'Hunkemöller is a lingerie brand.',
    translation: 'Hunkemöller is een lingeriemerk.',
    status: 'translated',
    provenance: 'ai',
    ...over,
  };
}

const JOB: ApiJob = {
  id: 'j1',
  filename: 'annual-report.docx',
  status: 'translating',
  progress: {
    translated: 12,
    failed: 0,
    total: 100,
    sections: {'1.1': 'done', '1.2': 'run'},
  },
};

describe('DocumentsComponent — mid-run section preview', () => {
  let fixture: ComponentFixture<DocumentsComponent>;
  let cmp: DocumentsComponent;
  let listSegments: jasmine.Spy;

  beforeEach(async () => {
    listSegments = jasmine.createSpy('listSegments').and.returnValue(of([]));
    const api = {
      listJobs: () => of([]),
      listSegments,
    };
    await TestBed.configureTestingModule({
      declarations: [DocumentsComponent],
      providers: [{provide: DocumentTranslationsService, useValue: api}],
      schemas: [NO_ERRORS_SCHEMA],
    }).compileComponents();
    fixture = TestBed.createComponent(DocumentsComponent);
    cmp = fixture.componentInstance;
    cmp.job = JOB;
    cmp.sections = [
      {id: '1.1', title: 'About Hunkemöller', n: 3},
      {id: '1.2', title: 'CEO Statement', n: 4},
    ];
  });

  it('fetches only the picked section, not the whole document', () => {
    cmp.peekSection('1.1');
    expect(listSegments).toHaveBeenCalledOnceWith('j1', {sectionId: '1.1'});
  });

  it('shows the section it loaded', () => {
    listSegments.and.returnValue(of([seg()]));
    cmp.peekSection('1.1');
    expect(cmp.runPeek).toBe('1.1');
    expect(cmp.runPeekLoading).toBeFalse();
    expect(cmp.runPeekGroups.length).toBe(1);
    expect(cmp.runPeekGroups[0].seg?.tgt).toBe(
      'Hunkemöller is een lingeriemerk.',
    );
    expect(cmp.sectionTitle('1.1')).toBe('About Hunkemöller');
  });

  it('ignores a slow response for a section the reviewer already left', () => {
    const slow = new Subject<ApiSegment[]>();
    const fast = new Subject<ApiSegment[]>();
    listSegments.and.returnValues(slow, fast);

    cmp.peekSection('1.1'); // still in flight
    cmp.peekSection('1.2'); // reviewer moves on

    fast.next([seg({sectionId: '1.2', translation: 'Tweede sectie.'})]);
    slow.next([seg({sectionId: '1.1', translation: 'STALE — must not show'})]);

    expect(cmp.runPeek).toBe('1.2');
    expect(cmp.runPeekGroups.length).toBe(1);
    expect(cmp.runPeekGroups[0].seg?.tgt).toBe('Tweede sectie.');
  });

  it('does not get stuck loading when a stale response lands', () => {
    const slow = new Subject<ApiSegment[]>();
    const fast = new Subject<ApiSegment[]>();
    listSegments.and.returnValues(slow, fast);

    cmp.peekSection('1.1');
    cmp.peekSection('1.2');
    fast.next([seg({sectionId: '1.2'})]);
    expect(cmp.runPeekLoading).toBeFalse();

    slow.next([seg({sectionId: '1.1'})]);
    expect(cmp.runPeekLoading).toBeFalse();
  });

  it('surfaces a load failure without wedging the panel', () => {
    const err = new Subject<ApiSegment[]>();
    listSegments.and.returnValue(err);
    cmp.peekSection('1.1');
    err.error(new Error('boom'));
    expect(cmp.runPeekLoading).toBeFalse();
    expect(cmp.runPeekError).toContain('Could not load');
  });

  it('closing the preview returns to the progress card', () => {
    listSegments.and.returnValue(of([seg()]));
    cmp.peekSection('1.1');
    cmp.closePeek();
    expect(cmp.runPeek).toBeNull();
    expect(cmp.runPeekGroups).toEqual([]);
    expect(cmp.runPeekError).toBe('');
  });

  it('leaving the run view drops the preview', () => {
    listSegments.and.returnValue(of([seg()]));
    cmp.peekSection('1.1');
    cmp.setView('review');
    expect(cmp.runPeek).toBeNull();
  });

  it('keeps the run progress visible while previewing', () => {
    listSegments.and.returnValue(of([seg()]));
    cmp.peekSection('1.1');
    expect(cmp.runPct).toBe(12);
    expect(cmp.runComplete).toBeFalse();
  });

  it('reports the in-flight section as running, finished as done', () => {
    const states = cmp.runStates;
    expect(states['1.1']).toBe('done');
    expect(states['1.2']).toBe('run');
  });
});
