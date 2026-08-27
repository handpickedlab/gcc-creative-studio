/**
 * Copyright 2026 Google LLC — Licensed under the Apache License, Version 2.0.
 *
 * The live view of a run is assembled from the polled trace, so these cover
 * the helpers that turn it into something a waiting user can read.
 */
import {AgentStep} from '../services/data-query.service';

import {DataQueryComponent} from './data-query.component';

function component(): DataQueryComponent {
  return new DataQueryComponent({} as never, {} as never);
}

const modelTurn = (n: number): AgentStep => ({kind: 'model', n});
const toolCall = (ms?: number): AgentStep => ({
  kind: 'tool',
  name: 'search_claims',
  input: {query: 'nps'},
  summary: ms == null ? '…' : '3 claims',
  ms,
});

describe('DataQueryComponent live progress', () => {
  it('names the step the model is on, so the wait is not a blank spinner', () => {
    const c = component();

    expect(c.thinkingLabel([toolCall(120), modelTurn(4)])).toBe(
      'thinking… (step 4)',
    );
  });

  it('falls back to a plain label before the first step lands', () => {
    expect(component().thinkingLabel([])).toBe('thinking…');
  });

  it('only calls the agent "thinking" when no tool is in flight', () => {
    const c = component();

    expect(c.toolRunning([toolCall()])).toBe(true);
    expect(c.toolRunning([toolCall(90)])).toBe(false);
  });

  it('marks a tool call as running until its duration lands', () => {
    const c = component();

    expect(c.running(toolCall())).toBe(true);
    expect(c.took(toolCall())).toBe('');
    expect(c.running(toolCall(1400))).toBe(false);
    expect(c.took(toolCall(1400))).toBe('1.4s');
  });

  it('keeps the model markers out of the finished trace', () => {
    const c = component();

    const trace = c.traceSteps([toolCall(10), modelTurn(2), {kind: 'text', text: '42'}]);

    expect(trace.length).toBe(1);
    expect(trace[0].kind).toBe('tool');
  });
});
