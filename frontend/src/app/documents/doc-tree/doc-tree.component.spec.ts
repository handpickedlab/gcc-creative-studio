/**
 * Copyright 2026 Google LLC — Licensed under the Apache License, Version 2.0.
 *
 * The outline rail is shown in two modes. During a translation run only the
 * sections that already finished may be opened, so a reviewer can read them
 * while the rest of the document is still being translated. Outside a run the
 * whole outline follows `focusable`.
 */

import {ComponentFixture, TestBed} from '@angular/core/testing';
import {DocTreeComponent} from './doc-tree.component';
import {Chapter, RunState} from '../documents.data';

const TREE: Chapter[] = [
  {
    id: '1',
    title: 'Management board report',
    sections: [
      {id: '1.1', title: 'About Hunkemöller', n: 3, t: 0},
      {id: '1.2', title: 'CEO Statement', n: 4, t: 0},
      {id: '1.3', title: 'Brand', n: 2, t: 0},
      {id: '1.4', title: 'Routes to market', n: 5, t: 0},
    ],
  },
];

describe('DocTreeComponent', () => {
  let fixture: ComponentFixture<DocTreeComponent>;
  let cmp: DocTreeComponent;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [DocTreeComponent],
    }).compileComponents();
    fixture = TestBed.createComponent(DocTreeComponent);
    cmp = fixture.componentInstance;
    cmp.tree = TREE;
  });

  function runMode(states: Record<string, RunState>) {
    cmp.run = states;
    fixture.detectChanges();
  }

  const sec = (id: string) => TREE[0].sections.find(s => s.id === id)!;

  describe('during a translation run', () => {
    beforeEach(() => {
      runMode({'1.1': 'done', '1.2': 'run', '1.3': 'queued', '1.4': 'fail'});
    });

    it('lets a finished section be opened', () => {
      expect(cmp.canPick(sec('1.1'))).toBeTrue();
    });

    it('does not open the section still being translated', () => {
      expect(cmp.canPick(sec('1.2'))).toBeFalse();
    });

    it('does not open a queued section', () => {
      expect(cmp.canPick(sec('1.3'))).toBeFalse();
    });

    it('does not open a failed section', () => {
      expect(cmp.canPick(sec('1.4'))).toBeFalse();
    });

    it('emits only for the finished section', () => {
      const picked: string[] = [];
      cmp.picked.subscribe(id => picked.push(id));
      cmp.select(sec('1.1'));
      cmp.select(sec('1.2'));
      cmp.select(sec('1.3'));
      cmp.select(sec('1.4'));
      expect(picked).toEqual(['1.1']);
    });

    it('treats a section missing from progress as queued, not clickable', () => {
      runMode({'1.1': 'done'});
      expect(cmp.runState('1.4')).toBe('queued');
      expect(cmp.canPick(sec('1.4'))).toBeFalse();
    });

    it('renders the finished section as enabled and the rest disabled', () => {
      const btns: HTMLButtonElement[] = Array.from(
        fixture.nativeElement.querySelectorAll('button.sec'),
      );
      expect(btns.length).toBe(4);
      expect(btns.map(b => b.disabled)).toEqual([false, true, true, true]);
      // the clickable one must not carry the inert styling
      expect(btns[0].classList.contains('static')).toBeFalse();
      expect(btns[1].classList.contains('static')).toBeTrue();
    });

    it('shows a spinner for the section in flight, not "queued"', () => {
      const row = fixture.nativeElement.querySelectorAll('button.sec')[1];
      expect(row.querySelector('.spinner')).toBeTruthy();
      expect(row.textContent).not.toContain('queued');
    });
  });

  describe('outside a run', () => {
    it('follows focusable when it is true', () => {
      cmp.run = null;
      cmp.focusable = true;
      fixture.detectChanges();
      expect(cmp.canPick(sec('1.3'))).toBeTrue();
    });

    it('follows focusable when it is false', () => {
      cmp.run = null;
      cmp.focusable = false;
      fixture.detectChanges();
      expect(cmp.canPick(sec('1.1'))).toBeFalse();
      cmp.select(sec('1.1'));
      // no emission expected; select is a no-op when not focusable
    });
  });
});
