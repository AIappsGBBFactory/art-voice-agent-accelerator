import test from 'node:test';
import assert from 'node:assert/strict';

import { createEnvelopeDeduper, DEFAULT_DEDUPE_CAPACITY } from './envelopeDedupe.js';
import { flattenSessionEnvelope, isSessionEnvelope } from './sessionEnvelope.js';

test('first sighting of an envelope id is processed', () => {
  const deduper = createEnvelopeDeduper();
  assert.equal(deduper.shouldProcess('abc123'), true);
});

test('a repeat of the same envelope id is suppressed', () => {
  const deduper = createEnvelopeDeduper();

  // One backend emission fanned out to the conversation socket and the relay.
  assert.equal(deduper.shouldProcess('abc123'), true);
  assert.equal(deduper.shouldProcess('abc123'), false);
  assert.equal(deduper.shouldProcess('abc123'), false);
});

test('distinct ids both pass even when the events look identical', () => {
  const deduper = createEnvelopeDeduper();

  // Two real consecutive handoffs / repeated identical status pings must not
  // be collapsed: identity is the envelope id, never the content.
  assert.equal(deduper.shouldProcess('handoff-1'), true);
  assert.equal(deduper.shouldProcess('handoff-2'), true);
  assert.equal(deduper.size(), 2);
});

test('frames without a usable id fail open and are always processed', () => {
  const deduper = createEnvelopeDeduper();

  for (const id of [undefined, null, '', 0, 42, {}, []]) {
    assert.equal(deduper.shouldProcess(id), true);
    assert.equal(deduper.shouldProcess(id), true);
  }
  assert.equal(deduper.size(), 0);
});

test('cache stays bounded and evicts oldest ids first', () => {
  const deduper = createEnvelopeDeduper({ capacity: 3 });

  ['a', 'b', 'c'].forEach((id) => assert.equal(deduper.shouldProcess(id), true));
  assert.equal(deduper.size(), 3);

  // 'd' evicts 'a'.
  assert.equal(deduper.shouldProcess('d'), true);
  assert.equal(deduper.size(), 3);
  assert.equal(deduper.shouldProcess('b'), false, 'newer ids stay cached');
  assert.equal(deduper.shouldProcess('d'), false);
  assert.equal(deduper.shouldProcess('a'), true, 'evicted id is no longer known');
});

test('a long call never grows the cache past capacity', () => {
  const deduper = createEnvelopeDeduper({ capacity: 8 });

  for (let i = 0; i < 5000; i += 1) {
    assert.equal(deduper.shouldProcess(`envelope-${i}`), true);
  }
  assert.equal(deduper.size(), 8);
});

test('invalid capacity falls back to the default', () => {
  for (const capacity of [0, -1, Number.NaN, Number.POSITIVE_INFINITY, 'lots']) {
    assert.equal(createEnvelopeDeduper({ capacity }).capacity, DEFAULT_DEDUPE_CAPACITY);
  }
});

test('clear() resets the cache so a new session starts fresh', () => {
  const deduper = createEnvelopeDeduper();

  assert.equal(deduper.shouldProcess('abc123'), true);
  assert.equal(deduper.shouldProcess('abc123'), false);

  deduper.clear();
  assert.equal(deduper.size(), 0);
  assert.equal(deduper.shouldProcess('abc123'), true);
});

test('deduper instances are independent', () => {
  const a = createEnvelopeDeduper();
  const b = createEnvelopeDeduper();

  assert.equal(a.shouldProcess('shared'), true);
  assert.equal(b.shouldProcess('shared'), true);
});

// --- handler seam ---------------------------------------------------------
// Mirrors handleSocketMessage in App.jsx: dedupe on the envelope id *before*
// flattening, because flattenSessionEnvelope only spreads envelope.payload and
// would drop a top-level id.

const makeSessionUpdatedEnvelope = (id, agentLabel = 'BankingConcierge') => ({
  id,
  type: 'event',
  topic: 'session',
  session_id: 'sess_EHW3k83FWo0XdjrPxPtjU',
  call_id: null,
  user_id: null,
  sender: 'System',
  ts: '2026-02-11T15:12:07.611000+00:00',
  speaker_id: 'System',
  payload: {
    event_type: 'session_updated',
    agent_label: agentLabel,
    agent_name: agentLabel,
    active_agent_label: agentLabel,
    message: `Active agent: ${agentLabel}`,
  },
});

const drainSocketFrames = (deduper, frames) => {
  const rendered = [];
  for (const frame of frames) {
    let payload = JSON.parse(frame);
    if (isSessionEnvelope(payload)) {
      if (!deduper.shouldProcess(payload.id)) continue;
      payload = flattenSessionEnvelope(payload);
    }
    rendered.push(payload);
  }
  return rendered;
};

test('one backend envelope delivered on both sockets renders once', () => {
  const deduper = createEnvelopeDeduper();
  const envelope = makeSessionUpdatedEnvelope('e1');

  // Same emission fanned out to the conversation socket and the relay socket.
  const rendered = drainSocketFrames(deduper, [
    JSON.stringify(envelope),
    JSON.stringify(envelope),
  ]);

  assert.equal(rendered.length, 1);
  assert.equal(rendered[0].event_type, 'session_updated');
  assert.equal(rendered[0].message, 'Active agent: BankingConcierge');
  // Flattening still restores envelope context the relay reshape used to drop.
  assert.equal(rendered[0].ts, envelope.ts);
  assert.equal(rendered[0].topic, 'session');
  assert.equal(rendered[0].session_id, envelope.session_id);
});

test('two genuinely distinct handoffs both render', () => {
  const deduper = createEnvelopeDeduper();

  const rendered = drainSocketFrames(deduper, [
    JSON.stringify(makeSessionUpdatedEnvelope('e1', 'BankingConcierge')),
    JSON.stringify(makeSessionUpdatedEnvelope('e2', 'FraudAgent')),
    JSON.stringify(makeSessionUpdatedEnvelope('e2', 'FraudAgent')),
  ]);

  assert.equal(rendered.length, 2);
  assert.deepEqual(
    rendered.map((payload) => payload.agent_label),
    ['BankingConcierge', 'FraudAgent'],
  );
});

test('dedupe is uniform across envelope types, not session_updated specific', () => {
  const deduper = createEnvelopeDeduper();
  const base = { topic: 'session', session_id: 'sess-1', ts: '2026-02-11T15:12:07Z' };
  const envelopes = [
    { ...base, id: 'a1', type: 'assistant', sender: 'Assistant', payload: { content: 'hi', message: 'hi' } },
    { ...base, id: 's1', type: 'status', sender: 'System', payload: { message: 'Thinking…' } },
    { ...base, id: 't1', type: 'event', sender: 'System', payload: { event_type: 'tool_call', data: { name: 'lookup' } } },
  ];

  // Each envelope arrives twice, once per socket.
  const frames = envelopes.flatMap((envelope) => [
    JSON.stringify(envelope),
    JSON.stringify(envelope),
  ]);

  assert.equal(drainSocketFrames(deduper, frames).length, envelopes.length);
});

test('non-envelope frames are never suppressed', () => {
  const deduper = createEnvelopeDeduper();
  const frame = JSON.stringify({ type: 'audio_data', frame_index: 0 });

  assert.equal(drainSocketFrames(deduper, [frame, frame]).length, 2);
});
