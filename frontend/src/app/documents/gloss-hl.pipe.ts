/**
 * Copyright 2026 Google LLC — Licensed under the Apache License, Version 2.0.
 * Hunkemöller "Documents" — glossary & do-not-translate term highlighting.
 *
 * Splits a segment text into tokens so the template can underline glossary
 * terms (source and target side) and do-not-translate names.
 */

import {Pipe, PipeTransform} from '@angular/core';
import {DNT_LIST, GLOSSARY_FIN} from './documents.data';

export interface GlossToken {
  v: string;
  cls: '' | 'gl' | 'dnt';
}

const TERMS: Array<{term: string; cls: 'gl' | 'dnt'}> = (() => {
  const t: Array<{term: string; cls: 'gl' | 'dnt'}> = [];
  GLOSSARY_FIN.forEach(g => {
    t.push({term: g.en, cls: 'gl'});
    t.push({term: g.nl, cls: 'gl'});
  });
  DNT_LIST.forEach(d => t.push({term: d, cls: 'dnt'}));
  return t;
})();

const PATTERN = new RegExp(
  '(' +
    TERMS.map(t => t.term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|') +
    ')',
  'gi',
);

@Pipe({name: 'glossHl'})
export class GlossHlPipe implements PipeTransform {
  transform(text: string): GlossToken[] {
    return String(text)
      .split(PATTERN)
      .filter(p => p !== '')
      .map(p => {
        const hit = TERMS.find(t => t.term.toLowerCase() === p.toLowerCase());
        return {v: p, cls: hit ? hit.cls : ('' as const)};
      });
  }
}
