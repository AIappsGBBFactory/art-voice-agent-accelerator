import test from 'node:test';
import assert from 'node:assert/strict';

import {
  mergeStreamText,
  normalizeTranscriptText,
  upsertToolGroupMessage,
  upsertTurnMessage,
} from './turnMessages.js';

test('VoiceLive user snapshots update one bubble and ignore stale sequences', () => {
  let messages = [];
  const update = (text, sequence, streaming = true) => {
    messages = upsertTurnMessage(messages, {
      turnId: 'turn-1',
      role: 'user',
      speaker: 'User',
      updater: (current) => ({ ...current, text, sequence, streaming }),
      initial: { speaker: 'User', text, sequence, streaming },
    });
  };

  update('hello', 1);
  update('hello world', 2);
  update('stale', 1);
  update('hello world', 3, false);

  assert.equal(messages.length, 1);
  assert.equal(messages[0].text, 'hello world');
  assert.equal(messages[0].streaming, false);
});

test('tool group bubbles do not become transcript update targets', () => {
  let messages = upsertTurnMessage([], {
    turnId: 'turn-2',
    role: 'assistant',
    speaker: 'BankingConcierge',
    updater: null,
    initial: { speaker: 'BankingConcierge', text: 'Checking', streaming: true },
  });
  messages = upsertToolGroupMessage(messages, {
    turnId: 'turn-2',
    callId: 'call-7',
    toolName: 'lookup_balance',
    patch: { status: 'started' },
  });
  messages = upsertTurnMessage(messages, {
    turnId: 'turn-2',
    role: 'assistant',
    speaker: 'BankingConcierge',
    updater: (current) => ({ ...current, text: 'Checking complete' }),
    initial: null,
  });

  assert.equal(messages.length, 2);
  assert.equal(messages[0].text, 'Checking complete');
  assert.equal(messages[1].isToolGroup, true);
  assert.equal(messages[1].turnId, 'turn-2');
});

test('a handoff keeps all assistant streaming text in one turn response bubble', () => {
  let messages = upsertTurnMessage([], {
    turnId: 'turn-2',
    role: 'assistant',
    speaker: 'BankingConcierge',
    updater: null,
    initial: { speaker: 'BankingConcierge', text: 'I will transfer you.', streaming: true },
  });

  messages = upsertTurnMessage(messages, {
    turnId: 'turn-2',
    role: 'assistant',
    speaker: 'DeclineSpecialist',
    updater: (current) => ({
      ...current,
      speaker: 'DeclineSpecialist',
      text: 'I will transfer you. I can now help with the decline.',
      streaming: false,
    }),
    initial: null,
  });

  assert.equal(messages.length, 1);
  assert.equal(messages[0].speaker, 'DeclineSpecialist');
  assert.equal(messages[0].text, 'I will transfer you. I can now help with the decline.');
});

test('tool calls in a turn share one grouped blob isolated by call ID', () => {
  let messages = [];
  for (const callId of ['call-a', 'call-b']) {
    messages = upsertToolGroupMessage(messages, {
      turnId: 'turn-3',
      callId,
      toolName: 'search',
      patch: { status: 'started' },
    });
  }

  // Both calls collapse into a single per-turn tool blob.
  assert.equal(messages.length, 1);
  assert.equal(messages[0].isToolGroup, true);
  assert.equal(messages[0].toolCalls.length, 2);

  messages = upsertToolGroupMessage(messages, {
    turnId: 'turn-3',
    callId: 'call-a',
    toolName: 'search',
    patch: { status: 'success', result: { ok: true } },
  });

  assert.equal(messages.length, 1);
  const callA = messages[0].toolCalls.find((c) => c.callId === 'call-a');
  const callB = messages[0].toolCalls.find((c) => c.callId === 'call-b');
  assert.equal(callA.status, 'success');
  assert.equal(callB.status, 'started');
});

test('stream merge supports delta and cumulative snapshot protocols', () => {
  assert.equal(mergeStreamText('hello ', 'world', 'delta'), 'hello world');
  assert.equal(mergeStreamText('old', 'complete snapshot', 'snapshot'), 'complete snapshot');
});

test('normalizeTranscriptText keeps partial and final visually consistent', () => {
  // Trailing newline (the phantom blank line) is stripped.
  assert.equal(normalizeTranscriptText('hello world\n'), 'hello world');
  // Leading/trailing whitespace trimmed.
  assert.equal(normalizeTranscriptText('  hello  '), 'hello');
  // CRLF and blank runs collapse to one visual space in chat bubbles.
  assert.equal(normalizeTranscriptText('line 1\r\n\r\nline 2'), 'line 1 line 2');
  // A streaming partial and its final render to the same string.
  assert.equal(
    normalizeTranscriptText('I need help \n'),
    normalizeTranscriptText('I need help'),
  );
  // Null/undefined are safe.
  assert.equal(normalizeTranscriptText(undefined), '');
});

test('cascade partial snapshots stream into one bubble then finalize', () => {
  let messages = [];
  const partial = (text, sequence) => {
    messages = upsertTurnMessage(messages, {
      turnId: 'utt-1',
      role: 'user',
      speaker: 'User',
      updater: (current = {}) => ({
        ...current,
        speaker: 'User',
        text: mergeStreamText(current.text, text, 'snapshot'),
        streaming: true,
        streamingType: 'stt_partial',
        sequence,
      }),
      initial: () => ({ speaker: 'User', text, streaming: true, sequence }),
    });
  };

  partial('I need', 1);
  partial('I need to check', 2);

  // Final transcript for the same utterance turn id.
  messages = upsertTurnMessage(messages, {
    turnId: 'utt-1',
    role: 'user',
    speaker: 'User',
    updater: (current = {}) => ({
      ...current,
      speaker: 'User',
      text: mergeStreamText(current.text, 'I need to check my balance.', 'final_turn'),
      streaming: false,
      streamingType: 'stt_final',
      sequence: 3,
    }),
    initial: null,
  });

  assert.equal(messages.length, 1);
  assert.equal(messages[0].text, 'I need to check my balance.');
  assert.equal(messages[0].streaming, false);
});