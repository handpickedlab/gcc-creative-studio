/**
 * Copyright 2026 Google LLC — Licensed under the Apache License, Version 2.0.
 *
 * Notes are sent to the model with every translation, but they live behind the
 * collapsed "Details" panel — so a note carried in from the uploaded sheet has
 * to announce itself rather than sit there unread.
 */
import {TranslationsComponent} from './translations.component';

function component(): TranslationsComponent {
  return new TranslationsComponent({} as never, {} as never);
}

function withNotes(cmp: TranslationsComponent, notes: string) {
  cmp.briefing = {
    id: 1,
    name: 'Spring drop',
    requestor: 'Roxanne',
    due: '',
    notes,
    fields: [],
  } as never;
}

describe('TranslationsComponent notes', () => {
  it('starts with the details panel closed', () => {
    expect(component().metaOpen).toBeFalse();
  });

  it('opens the panel for a briefing that arrives with notes', () => {
    const cmp = component();
    withNotes(cmp, 'Playful tone, keep cashmere untranslated.');

    cmp['revealNotes']();

    expect(cmp.metaOpen).toBeTrue();
    expect(cmp.hasNotes).toBeTrue();
  });

  it('leaves the panel closed when there is nothing to read', () => {
    const cmp = component();
    withNotes(cmp, '   ');

    cmp['revealNotes']();

    expect(cmp.metaOpen).toBeFalse();
    expect(cmp.hasNotes).toBeFalse();
  });
});
