import test from 'node:test';
import assert from 'node:assert/strict';

import {
  BubbleEventType,
  conversationBubbleEventFromPayload,
  reduceConversationPayload,
} from './conversationBubbles.js';
import { flattenSessionEnvelope } from './sessionEnvelope.js';

const envelope = (type, sender, payload, ts = '2026-07-11T00:00:00Z') => ({
  type,
  topic: 'session',
  session_id: 'session-1',
  sender,
  ts,
  payload,
});

const apply = (messages, frame) =>
  reduceConversationPayload(messages, flattenSessionEnvelope(frame));

const turnMessages = (messages, turnId) =>
  messages.filter((message) => message.turnId === turnId);

const role = (messages, turnId, turnRole) =>
  messages.find(
    (message) => message.turnId === turnId && message.turnRole === turnRole,
  );

test('cascade backend envelopes produce one ordered user, assistant, and tool bubble', () => {
  let messages = [];

  messages = apply(
    messages,
    envelope('event', 'STT', {
      event_type: 'stt_partial',
      data: {
        type: 'streaming',
        content: 'check my',
        streaming_type: 'stt_partial',
        content_mode: 'snapshot',
        turn_id: 'cascade-1',
        response_id: 'cascade-1',
        sequence: 1,
        is_final: false,
      },
    }),
  );
  messages = apply(
    messages,
    envelope('event', 'STT', {
      event_type: 'stt_partial',
      data: {
        type: 'streaming',
        content: 'check my balance',
        content_mode: 'snapshot',
        turn_id: 'cascade-1',
        sequence: 2,
      },
    }),
  );
  messages = apply(
    messages,
    envelope('event', 'User', {
      type: 'user',
      message: 'Check my balance.',
      content: 'Check my balance.',
      streaming: false,
      content_mode: 'final_turn',
      turn_id: 'cascade-1',
      response_id: 'cascade-1',
      sequence: 3,
      is_final: true,
    }),
  );

  messages = apply(
    messages,
    envelope('assistant_streaming', 'Banking Concierge', {
      content: 'I can ',
      content_mode: 'delta',
      turn_id: 'cascade-1',
      segment_id: 'cascade-1',
      response_id: 'cascade-1',
      sequence: 1,
    }),
  );
  messages = apply(messages, {
    type: 'tool_start',
    tool: 'lookup_balance',
    call_id: 'call-1',
    turn_id: 'cascade-1',
    segment_id: 'cascade-1',
  });
  messages = apply(
    messages,
    envelope('assistant_streaming', 'Banking Concierge', {
      content: 'check that. ',
      content_mode: 'delta',
      turn_id: 'cascade-1',
      segment_id: 'cascade-1_s1',
      response_id: 'cascade-1_s1',
      sequence: 2,
    }),
  );
  messages = apply(messages, {
    type: 'tool_end',
    tool: 'lookup_balance',
    call_id: 'call-1',
    turn_id: 'cascade-1',
    segment_id: 'cascade-1_s1',
    status: 'success',
    result: { balance: 42 },
  });
  messages = apply(
    messages,
    envelope('event', 'Banking Concierge', {
      type: 'assistant',
      content: 'Your balance is $42.',
      message: 'Your balance is $42.',
      streaming: false,
      content_mode: 'final_turn',
      turn_id: 'cascade-1',
      segment_id: 'cascade-1_s1',
      response_id: 'cascade-1_s1',
      sequence: 3,
    }),
  );

  const turn = turnMessages(messages, 'cascade-1');
  assert.deepEqual(turn.map((message) => message.turnRole), [
    'user',
    'assistant',
    'tool',
  ]);
  assert.equal(turn.length, 3);
  assert.equal(turn[0].text, 'Check my balance.');
  assert.equal(turn[0].streaming, false);
  assert.equal(turn[1].text, 'Your balance is $42.');
  assert.equal(turn[1].streaming, false);
  assert.equal(turn[2].toolCalls.length, 1);
  assert.equal(turn[2].toolCalls[0].status, 'success');
});

test('cascade delta chunks accumulate into one streaming response bubble then finalize', () => {
  let messages = [];
  messages = apply(
    messages,
    envelope('event', 'User', {
      type: 'user',
      content: 'Tell me a joke.',
      message: 'Tell me a joke.',
      streaming: false,
      content_mode: 'final_turn',
      turn_id: 'casc-delta-1',
      is_final: true,
    }),
  );

  // Cascade streams per-sentence TTS chunks as deltas that keep the same
  // segment_id (it never advances mid-turn) and must concatenate in order.
  for (const [index, chunk] of [
    'Why did the ',
    'chicken cross ',
    'the road?',
  ].entries()) {
    messages = apply(
      messages,
      envelope('assistant_streaming', 'Concierge', {
        content: chunk,
        content_mode: 'delta',
        turn_id: 'casc-delta-1',
        segment_id: 'casc-delta-1',
        response_id: 'casc-delta-1',
        sequence: index + 1,
      }),
    );
  }

  assert.equal(role(messages, 'casc-delta-1', 'assistant').streaming, true);
  assert.equal(
    role(messages, 'casc-delta-1', 'assistant').text,
    'Why did the chicken cross the road?',
  );

  messages = apply(
    messages,
    envelope('event', 'Concierge', {
      type: 'assistant',
      content: 'Why did the chicken cross the road?',
      message: 'Why did the chicken cross the road?',
      streaming: false,
      content_mode: 'final_turn',
      turn_id: 'casc-delta-1',
      segment_id: 'casc-delta-1',
      response_id: 'casc-delta-1',
      sequence: 4,
    }),
  );

  const assistants = turnMessages(messages, 'casc-delta-1').filter(
    (message) => message.turnRole === 'assistant',
  );
  assert.equal(assistants.length, 1);
  assert.equal(assistants[0].streaming, false);
  assert.equal(assistants[0].text, 'Why did the chicken cross the road?');
});

test('cascade barge-in mid-response closes the old bubble when the new user partial arrives', () => {
  let messages = [];
  // Turn one: user final then a still-streaming assistant response.
  messages = apply(
    messages,
    envelope('event', 'User', {
      type: 'user',
      content: 'What is my balance?',
      message: 'What is my balance?',
      streaming: false,
      content_mode: 'final_turn',
      turn_id: 'casc-bi-1',
      is_final: true,
    }),
  );
  messages = apply(
    messages,
    envelope('assistant_streaming', 'Concierge', {
      content: 'Your balance is fifty ',
      content_mode: 'delta',
      turn_id: 'casc-bi-1',
      segment_id: 'casc-bi-1',
      response_id: 'casc-bi-1',
      sequence: 1,
    }),
  );
  assert.equal(role(messages, 'casc-bi-1', 'assistant').streaming, true);

  // Cascade emits no assistant_cancelled envelope. The interrupting utterance's
  // first STT partial (which triggers the backend barge-in) is a NEW canonical
  // turn, and that boundary closes the prior streaming response bubble.
  messages = apply(
    messages,
    envelope('event', 'STT', {
      event_type: 'stt_partial',
      data: {
        type: 'streaming',
        content: 'actually transfer',
        content_mode: 'snapshot',
        turn_id: 'casc-bi-2',
        sequence: 1,
      },
    }),
  );

  const oldAssistant = role(messages, 'casc-bi-1', 'assistant');
  assert.equal(oldAssistant.streaming, false);
  assert.equal(oldAssistant.cancelled, true);
  assert.equal(role(messages, 'casc-bi-2', 'user').text, 'actually transfer');

  // A late delta from the interrupted response cannot reopen the closed bubble.
  messages = apply(
    messages,
    envelope('assistant_streaming', 'Concierge', {
      content: 'dollars.',
      content_mode: 'delta',
      turn_id: 'casc-bi-1',
      segment_id: 'casc-bi-1',
      response_id: 'casc-bi-1',
      sequence: 2,
    }),
  );
  assert.equal(role(messages, 'casc-bi-1', 'assistant').text, 'Your balance is fifty ');
  assert.equal(role(messages, 'casc-bi-1', 'assistant').cancelled, true);
});

test('a response whose turn_id differs from the user turn still renders after a greeting', () => {
  let messages = [];
  // Greeting (no turn_id) renders as its own bubble.
  messages = apply(
    messages,
    envelope('assistant', 'Concierge', {
      content: 'Hi, how can I help?',
      message: 'Hi, how can I help?',
      streaming: false,
    }),
  );
  // User turn with one id.
  messages = apply(
    messages,
    envelope('event', 'User', {
      type: 'user',
      sender: 'User',
      message: 'What is my balance?',
      content: 'What is my balance?',
      streaming: false,
      is_final: true,
      turn_id: 'user-A',
    }),
  );
  // The backend response carries a DIFFERENT turn id than the user turn. It is a
  // fresh response (not a superseded prior turn), so it must still render.
  messages = apply(
    messages,
    envelope('assistant_streaming', 'Concierge', {
      content: 'Your balance is $42.',
      content_mode: 'delta',
      turn_id: 'resp-R',
      segment_id: 'resp-R',
    }),
  );
  messages = apply(
    messages,
    envelope('event', 'Concierge', {
      type: 'assistant',
      content: 'Your balance is $42.',
      message: 'Your balance is $42.',
      streaming: false,
      content_mode: 'final_turn',
      turn_id: 'resp-R',
      segment_id: 'resp-R',
    }),
  );

  const assistants = messages.filter((m) => m.turnRole === 'assistant');
  assert.equal(assistants.length, 2); // greeting + response
  assert.equal(assistants[1].text, 'Your balance is $42.');
  assert.equal(assistants[1].streaming, false);
});

test('cascade post-tool final settles the streaming bubble even when its id differs', () => {
  let messages = [];
  messages = apply(
    messages,
    envelope('event', 'User', {
      type: 'user',
      sender: 'User',
      message: 'verify me',
      content: 'verify me',
      streaming: false,
      is_final: true,
      turn_id: 'A',
    }),
  );
  messages = apply(messages, {
    type: 'tool_end',
    tool: 'verify_client_identity',
    call_id: 'c1',
    turn_id: 'A',
    status: 'error',
    error: 'Could not verify identity.',
  });
  // Post-tool response streams under one id ...
  messages = apply(
    messages,
    envelope('assistant_streaming', 'BankingConcierge', {
      content: "It looks like I couldn't verify your identity.",
      content_mode: 'delta',
      turn_id: 'X',
      segment_id: 'X',
    }),
  );
  // ... but the final envelope carries a DIFFERENT id. It must finalize the same
  // streamed bubble instead of cloning it.
  messages = apply(
    messages,
    envelope('event', 'BankingConcierge', {
      type: 'assistant',
      content: "It looks like I couldn't verify your identity.",
      message: "It looks like I couldn't verify your identity.",
      streaming: false,
      content_mode: 'final_turn',
      turn_id: 'Y',
      segment_id: 'Y',
    }),
  );

  const assistants = messages.filter((m) => m.turnRole === 'assistant');
  assert.equal(assistants.length, 1);
  assert.equal(assistants[0].streaming, false);
  assert.equal(assistants[0].text, "It looks like I couldn't verify your identity.");
});

test('cascade barge-in cancel marks the in-flight streaming bubble even with a mismatched id', () => {
  let messages = [];
  messages = apply(
    messages,
    envelope('event', 'User', {
      type: 'user',
      sender: 'User',
      message: 'tell me about my account',
      content: 'tell me about my account',
      streaming: false,
      is_final: true,
      turn_id: 'A',
    }),
  );
  // Response is streaming under its own id ...
  messages = apply(
    messages,
    envelope('assistant_streaming', 'BankingConcierge', {
      content: 'Your account has ',
      content_mode: 'delta',
      turn_id: 'X',
      segment_id: 'X',
    }),
  );
  assert.equal(role(messages, 'X', 'assistant').streaming, true);

  // ... user barges in; cascade emits assistant_cancelled whose id (the user
  // turn id) differs from the streamed response id. It must still cancel the
  // in-flight bubble.
  messages = apply(
    messages,
    envelope('event', 'BankingConcierge', {
      type: 'assistant_cancelled',
      message: '',
      content: '',
      streaming: false,
      cancel_reason: 'barge_in',
      turn_id: 'A',
    }),
  );

  const bubble = role(messages, 'X', 'assistant');
  assert.equal(bubble.cancelled, true);
  assert.equal(bubble.streaming, false);
  // No duplicate assistant bubble was created for the cancel id.
  assert.equal(messages.filter((m) => m.turnRole === 'assistant').length, 1);
});

test('tool arriving before assistant is re-indexed into user, assistant, tools order', () => {
  let messages = [];
  messages = apply(
    messages,
    envelope('event', 'User', {
      type: 'user',
      content: 'Find it',
      message: 'Find it',
      turn_id: 'order-1',
      streaming: false,
    }),
  );
  messages = apply(messages, {
    type: 'tool_start',
    tool: 'search',
    call_id: 'search-1',
    turn_id: 'order-1',
  });
  messages = apply(
    messages,
    envelope('assistant_streaming', 'Assistant', {
      content: 'Searching',
      content_mode: 'snapshot',
      turn_id: 'order-1',
      sequence: 1,
    }),
  );

  assert.deepEqual(
    turnMessages(messages, 'order-1').map((message) => message.turnRole),
    ['user', 'assistant', 'tool'],
  );
});

test('VoiceLive tool response continues a finalized pre-tool assistant bubble', () => {
  let messages = [];
  messages = apply(
    messages,
    envelope('event', 'User', {
      type: 'user',
      content: 'What is my balance?',
      message: 'What is my balance?',
      turn_id: 'vl-tool-1',
      streaming: false,
    }),
  );

  // VoiceLive can complete the first response segment after announcing that it
  // will invoke a tool.
  messages = apply(
    messages,
    envelope('assistant_streaming', 'Concierge', {
      content: 'Let me check that.',
      content_mode: 'snapshot',
      turn_id: 'vl-tool-1',
      segment_id: 'vl-tool-1',
      response_id: 'response-before-tool',
      sequence: 1,
    }),
  );
  messages = apply(
    messages,
    envelope('event', 'Concierge', {
      type: 'assistant',
      content: 'Let me check that.',
      message: 'Let me check that.',
      turn_id: 'vl-tool-1',
      segment_id: 'vl-tool-1',
      response_id: 'response-before-tool',
      streaming: false,
      sequence: 2,
    }),
  );

  messages = apply(messages, {
    type: 'tool_start',
    tool: 'lookup_balance',
    call_id: 'balance-1',
    turn_id: 'vl-tool-1',
    segment_id: 'vl-tool-1',
  });
  messages = apply(messages, {
    type: 'tool_end',
    tool: 'lookup_balance',
    call_id: 'balance-1',
    turn_id: 'vl-tool-1',
    segment_id: 'vl-tool-1',
    status: 'success',
    result: { balance: 42 },
  });

  // After tool output is submitted, VoiceLive advances only segment_id. The
  // canonical turn and bubble remain the same, and the snapshot includes both
  // response phases.
  messages = apply(
    messages,
    envelope('assistant_streaming', 'Concierge', {
      content: 'Let me check that.\n\nYour balance is $42.',
      content_mode: 'snapshot',
      turn_id: 'vl-tool-1',
      segment_id: 'vl-tool-1_s1',
      response_id: 'response-after-tool',
      sequence: 3,
    }),
  );
  assert.equal(role(messages, 'vl-tool-1', 'assistant').streaming, true);
  assert.equal(
    role(messages, 'vl-tool-1', 'assistant').text,
    'Let me check that.\n\nYour balance is $42.',
  );

  messages = apply(
    messages,
    envelope('event', 'Concierge', {
      type: 'assistant',
      content: 'Let me check that.\n\nYour balance is $42.',
      message: 'Let me check that.\n\nYour balance is $42.',
      turn_id: 'vl-tool-1',
      segment_id: 'vl-tool-1_s1',
      response_id: 'response-after-tool',
      streaming: false,
      sequence: 4,
    }),
  );

  const turn = turnMessages(messages, 'vl-tool-1');
  assert.deepEqual(turn.map((message) => message.turnRole), [
    'user',
    'assistant',
    'tool',
  ]);
  assert.equal(turn.filter((message) => message.turnRole === 'assistant').length, 1);
  assert.equal(turn[1].streaming, false);
  assert.equal(turn[1].segmentId, 'vl-tool-1_s1');
  assert.equal(turn[2].toolCalls[0].status, 'success');
  assert.deepEqual(turn[2].toolCalls[0].result, { balance: 42 });

  // A late pre-tool segment cannot reopen or replace the completed post-tool
  // response, even if it is delivered after the newer final.
  const completed = structuredClone(messages);
  messages = apply(
    messages,
    envelope('assistant_streaming', 'Concierge', {
      content: 'late old segment',
      content_mode: 'snapshot',
      turn_id: 'vl-tool-1',
      segment_id: 'vl-tool-1',
      response_id: 'response-before-tool',
      sequence: 5,
    }),
  );
  assert.deepEqual(messages, completed);
});

test('out-of-order tool start cannot downgrade an already completed result', () => {
  let messages = [];
  messages = apply(
    messages,
    envelope('event', 'User', {
      type: 'user',
      content: 'Run it',
      message: 'Run it',
      turn_id: 'tool-order-1',
      streaming: false,
    }),
  );
  messages = apply(messages, {
    type: 'tool_end',
    tool: 'lookup',
    call_id: 'lookup-1',
    turn_id: 'tool-order-1',
    status: 'success',
    result: { value: 1 },
  });
  messages = apply(messages, {
    type: 'tool_start',
    tool: 'lookup',
    call_id: 'lookup-1',
    turn_id: 'tool-order-1',
  });

  const call = role(messages, 'tool-order-1', 'tool').toolCalls[0];
  assert.equal(call.status, 'success');
  assert.deepEqual(call.result, { value: 1 });
});

test('VoiceLive barge-in closes the old response and rejects all late old-turn events', () => {
  let messages = [];

  // Turn one is active and has a partial response plus an in-flight tool.
  messages = apply(
    messages,
    envelope('event', 'User', {
      type: 'user',
      content: 'First request',
      message: 'First request',
      turn_id: 'vl-1',
      streaming: false,
    }),
  );
  messages = apply(
    messages,
    envelope('assistant_streaming', 'Concierge', {
      content: 'The first partial',
      content_mode: 'snapshot',
      turn_id: 'vl-1',
      segment_id: 'response-1',
      sequence: 1,
    }),
  );
  messages = apply(messages, {
    type: 'tool_start',
    tool: 'slow_lookup',
    call_id: 'slow-1',
    turn_id: 'vl-1',
    segment_id: 'response-1',
  });

  // VoiceLive speech_started immediately establishes the next canonical turn.
  // The cursor-only user bubble closes the race before the first STT delta.
  messages = apply(
    messages,
    envelope('event', 'User', {
      type: 'user',
      content: '',
      message: '',
      streaming: true,
      turn_id: 'vl-2',
      response_id: 'vl-2',
      sequence: 0,
    }),
  );
  assert.equal(role(messages, 'vl-1', 'assistant').cancelled, true);
  assert.equal(role(messages, 'vl-1', 'assistant').streaming, false);
  assert.equal(role(messages, 'vl-1', 'tool').toolCalls[0].status, 'cancelled');
  assert.equal(role(messages, 'vl-2', 'user').text, '');
  assert.equal(role(messages, 'vl-2', 'user').streaming, true);

  messages = apply(
    messages,
    envelope('event', 'User', {
      type: 'user',
      content: 'Second',
      message: 'Second',
      content_mode: 'snapshot',
      streaming: true,
      turn_id: 'vl-2',
      sequence: 1,
    }),
  );
  messages = apply(
    messages,
    envelope('event', 'User', {
      type: 'user',
      content: 'Second request',
      message: 'Second request',
      content_mode: 'final_turn',
      streaming: false,
      is_final: true,
      turn_id: 'vl-2',
      sequence: 2,
    }),
  );

  // These queued events belong to the interrupted response and must not reopen,
  // replace, duplicate, or append bubbles.
  const beforeLateEvents = structuredClone(messages);
  messages = apply(
    messages,
    envelope('assistant_streaming', 'Concierge', {
      content: 'The first partial plus stale text',
      content_mode: 'snapshot',
      turn_id: 'vl-1',
      segment_id: 'response-1',
      sequence: 2,
    }),
  );
  messages = apply(
    messages,
    envelope('event', 'Concierge', {
      type: 'assistant',
      content: 'Stale final',
      message: 'Stale final',
      turn_id: 'vl-1',
      segment_id: 'response-1',
      streaming: false,
    }),
  );
  messages = apply(messages, {
    type: 'tool_end',
    tool: 'slow_lookup',
    call_id: 'slow-1',
    turn_id: 'vl-1',
    segment_id: 'response-1',
    status: 'success',
    result: { stale: true },
  });
  assert.deepEqual(messages, beforeLateEvents);

  // The new response gets its own bubble and cannot reuse the old one.
  messages = apply(
    messages,
    envelope('assistant_streaming', 'Concierge', {
      content: 'New answer',
      content_mode: 'snapshot',
      turn_id: 'vl-2',
      segment_id: 'response-2',
      sequence: 1,
    }),
  );
  messages = apply(
    messages,
    envelope('event', 'Concierge', {
      type: 'assistant',
      content: 'New answer complete.',
      message: 'New answer complete.',
      turn_id: 'vl-2',
      segment_id: 'response-2',
      streaming: false,
      sequence: 2,
    }),
  );

  assert.equal(role(messages, 'vl-1', 'assistant').text, 'The first partial');
  assert.equal(role(messages, 'vl-2', 'assistant').text, 'New answer complete.');
  assert.equal(
    messages.filter((message) => message.turnRole === 'assistant').length,
    2,
  );
});

test('assistant cancellation and duplicate late partials never create duplicate bubbles', () => {
  let messages = [];
  const userFinal = envelope('event', 'User', {
    type: 'user',
    content: 'Hello',
    message: 'Hello',
    turn_id: 'dup-1',
    streaming: false,
  });
  messages = apply(messages, userFinal);
  messages = apply(
    messages,
    envelope('assistant_streaming', 'Assistant', {
      content: 'Partial',
      content_mode: 'snapshot',
      turn_id: 'dup-1',
      sequence: 2,
    }),
  );
  messages = apply(
    messages,
    envelope('event', 'Assistant', {
      type: 'assistant_cancelled',
      content: '',
      message: '',
      turn_id: 'dup-1',
      cancel_reason: 'barge_in',
    }),
  );
  messages = apply(
    messages,
    envelope('assistant_streaming', 'Assistant', {
      content: 'Partial duplicated',
      content_mode: 'snapshot',
      turn_id: 'dup-1',
      sequence: 3,
    }),
  );

  const assistants = turnMessages(messages, 'dup-1').filter(
    (message) => message.turnRole === 'assistant',
  );
  assert.equal(assistants.length, 1);
  assert.equal(assistants[0].text, 'Partial');
  assert.equal(assistants[0].cancelled, true);
});

test('unrelated incoming messages do not break keyed updates or turn grouping', () => {
  let messages = [];
  messages = apply(
    messages,
    envelope('event', 'User', {
      type: 'user',
      content: 'Do work',
      message: 'Do work',
      turn_id: 'stable-1',
      streaming: false,
    }),
  );
  messages.push({ speaker: 'System', text: 'A status update', type: 'event' });
  messages = apply(messages, {
    type: 'tool_start',
    tool: 'work',
    call_id: 'work-1',
    turn_id: 'stable-1',
  });
  messages.push({ speaker: 'System', text: 'Another status', type: 'event' });
  messages = apply(
    messages,
    envelope('assistant_streaming', 'Worker', {
      content: 'Working',
      content_mode: 'snapshot',
      turn_id: 'stable-1',
      sequence: 1,
    }),
  );
  messages = apply(messages, {
    type: 'tool_end',
    tool: 'work',
    call_id: 'work-1',
    turn_id: 'stable-1',
    status: 'success',
    result: { done: true },
  });

  const turn = turnMessages(messages, 'stable-1');
  assert.deepEqual(turn.map((message) => message.turnRole), [
    'user',
    'assistant',
    'tool',
  ]);
  assert.equal(turn[2].toolCalls[0].result.done, true);
  assert.equal(messages.filter((message) => message.speaker === 'System').length, 2);
});

test('envelopes without turn_id still render and coalesce per utterance', () => {
  let messages = [];

  // Turn 1: two partials (no turn_id) must collapse into one streaming user
  // bubble, then finalize in place, then the id-less assistant attaches to it.
  messages = apply(
    messages,
    envelope('event', 'STT', {
      event_type: 'stt_partial',
      data: { streaming_type: 'stt_partial', content: 'hello', is_final: false },
    }),
  );
  messages = apply(
    messages,
    envelope('event', 'STT', {
      event_type: 'stt_partial',
      data: { streaming_type: 'stt_partial', content: 'hello there', is_final: false },
    }),
  );
  assert.equal(messages.filter((m) => m.turnRole === 'user').length, 1);
  assert.equal(messages[0].streaming, true);

  messages = apply(
    messages,
    envelope('event', 'User', {
      type: 'user',
      sender: 'User',
      message: 'Hello there.',
      content: 'Hello there.',
      streaming: false,
      is_final: true,
    }),
  );
  messages = apply(
    messages,
    envelope('assistant_streaming', 'Concierge', {
      content: 'Hi ',
      content_mode: 'delta',
    }),
  );
  messages = apply(
    messages,
    envelope('assistant_streaming', 'Concierge', {
      content: 'there!',
      content_mode: 'delta',
    }),
  );
  messages = apply(
    messages,
    envelope('event', 'Concierge', {
      type: 'assistant',
      message: 'Hi there!',
      content: 'Hi there!',
      streaming: false,
    }),
  );

  const turn1User = messages.filter((m) => m.turnRole === 'user');
  const turn1Assistant = messages.filter((m) => m.turnRole === 'assistant');
  assert.equal(turn1User.length, 1);
  assert.equal(turn1User[0].text, 'Hello there.');
  assert.equal(turn1User[0].streaming, false);
  assert.equal(turn1Assistant.length, 1);
  assert.equal(turn1Assistant[0].text, 'Hi there!');
  assert.equal(turn1Assistant[0].streaming, false);
  // User and assistant of the same id-less utterance share one synthetic turn.
  assert.equal(turn1User[0].turnId, turn1Assistant[0].turnId);

  // Turn 2 (still no turn_id) is a distinct utterance and must not overwrite
  // turn 1's finalized user bubble.
  messages = apply(
    messages,
    envelope('event', 'User', {
      type: 'user',
      sender: 'User',
      message: 'Goodbye.',
      content: 'Goodbye.',
      streaming: false,
      is_final: true,
    }),
  );
  const users = messages.filter((m) => m.turnRole === 'user');
  assert.equal(users.length, 2);
  assert.deepEqual(users.map((m) => m.text), ['Hello there.', 'Goodbye.']);
  assert.notEqual(users[0].turnId, users[1].turnId);
});

// ---------------------------------------------------------------------------
// Envelope-classifier contract
// ---------------------------------------------------------------------------
// These lock the mapping from the backend's wire envelope types to bubble
// events. If the backend renames/adds an event type (a change that historically
// slipped through because the reducer silently returns null for unknown types
// and the bubble just never appears), one of these assertions fails loudly.

test('every backend conversation envelope classifies to the expected bubble event', () => {
  const classify = (frame) =>
    conversationBubbleEventFromPayload(flattenSessionEnvelope(frame));

  // Cascade user partial transcript (send_user_partial_transcript).
  assert.equal(
    classify(
      envelope('event', 'STT', {
        event_type: 'stt_partial',
        data: {
          type: 'streaming',
          content: 'check my bal',
          content_mode: 'snapshot',
          turn_id: 'c-1',
          sequence: 1,
        },
      }),
    ).type,
    BubbleEventType.USER_PARTIAL,
  );

  // Cascade final user transcript (send_user_transcript).
  assert.equal(
    classify(
      envelope('event', 'User', {
        type: 'user',
        content: 'Check my balance.',
        message: 'Check my balance.',
        streaming: false,
        content_mode: 'final_turn',
        is_final: true,
        turn_id: 'c-1',
      }),
    ).type,
    BubbleEventType.USER_FINAL,
  );

  // VoiceLive streaming user snapshot (streaming true, not final).
  assert.equal(
    classify(
      envelope('event', 'User', {
        type: 'user',
        content: 'transfer',
        message: 'transfer',
        streaming: true,
        streaming_type: 'stt_partial',
        content_mode: 'snapshot',
        is_final: false,
        turn_id: 'c-2',
        sequence: 1,
      }),
    ).type,
    BubbleEventType.USER_PARTIAL,
  );

  // Assistant streaming chunk (make_assistant_streaming_envelope).
  assert.equal(
    classify(
      envelope('assistant_streaming', 'Concierge', {
        content: 'I can help ',
        content_mode: 'delta',
        turn_id: 'c-1',
        segment_id: 'c-1',
      }),
    ).type,
    BubbleEventType.ASSISTANT_STREAM,
  );

  // Assistant final turn.
  assert.equal(
    classify(
      envelope('event', 'Concierge', {
        type: 'assistant',
        content: 'Your balance is $42.',
        message: 'Your balance is $42.',
        streaming: false,
        content_mode: 'final_turn',
        turn_id: 'c-1',
      }),
    ).type,
    BubbleEventType.ASSISTANT_FINAL,
  );

  // Assistant greeting (make_assistant_envelope, no turn_id) is still a final.
  assert.equal(
    classify(
      envelope('assistant', 'Concierge', {
        content: 'Hi, how can I help?',
        message: 'Hi, how can I help?',
        streaming: false,
      }),
    ).type,
    BubbleEventType.ASSISTANT_FINAL,
  );

  // Barge-in cancel (VoiceHandler._emit_assistant_cancelled).
  assert.equal(
    classify(
      envelope('event', 'Concierge', {
        type: 'assistant_cancelled',
        content: '',
        message: '',
        streaming: false,
        cancel_reason: 'barge_in',
        turn_id: 'c-1',
      }),
    ).type,
    BubbleEventType.ASSISTANT_CANCELLED,
  );

  // Tool frames are sent directly (not wrapped in a session envelope).
  assert.equal(
    conversationBubbleEventFromPayload({
      type: 'tool_start',
      tool: 'lookup_balance',
      call_id: 'call-1',
      turn_id: 'c-1',
    }).type,
    BubbleEventType.TOOL_START,
  );
  assert.equal(
    conversationBubbleEventFromPayload({
      type: 'tool_progress',
      tool: 'lookup_balance',
      call_id: 'call-1',
      turn_id: 'c-1',
      pct: 50,
    }).type,
    BubbleEventType.TOOL_PROGRESS,
  );
  assert.equal(
    conversationBubbleEventFromPayload({
      type: 'tool_end',
      tool: 'lookup_balance',
      call_id: 'call-1',
      turn_id: 'c-1',
      status: 'success',
      result: { balance: 42 },
    }).type,
    BubbleEventType.TOOL_END,
  );
});

test('non-conversation envelopes are ignored by the classifier', () => {
  // Control/lifecycle frames must not be mistaken for conversation bubbles.
  for (const payload of [
    { type: 'control', action: 'audio_stop', reason: 'barge_in' },
    { type: 'status', content: 'Call connected' },
    { event_type: 'call_connected' },
    { event_type: 'speech_cascade_connected' },
    { type: 'session_profile' },
    { type: 'function_call', name: 'lookup' },
  ]) {
    assert.equal(conversationBubbleEventFromPayload(payload), null);
  }
});

// ---------------------------------------------------------------------------
// Full realistic session (the "does everything populate" golden path)
// ---------------------------------------------------------------------------
// One continuous cascade session that exercises, in order: greeting, streamed
// user transcript, streamed agent response, a grouped tool call that only
// surfaces after the response exists, the agent final, then a user barge-in
// that opens a fresh turn. Asserts the WHOLE bubble array so cross-turn leakage
// (tool blobs bleeding across turns, orphaned/duplicate bubbles, a barge-in
// leaving the prior response open) is caught holistically.

test('a full cascade session renders one user, one response, and one tool blob per turn', () => {
  let messages = [];

  // 1. Greeting (no turn_id) — its own assistant bubble.
  messages = apply(
    messages,
    envelope('assistant', 'Banking Concierge', {
      content: 'Welcome to the bank. How can I help?',
      message: 'Welcome to the bank. How can I help?',
      streaming: false,
    }),
  );

  // 2. Turn 1 user transcript streams (partials) then finalizes.
  messages = apply(
    messages,
    envelope('event', 'STT', {
      event_type: 'stt_partial',
      data: { content: 'what is my', content_mode: 'snapshot', turn_id: 't1', sequence: 1 },
    }),
  );
  messages = apply(
    messages,
    envelope('event', 'STT', {
      event_type: 'stt_partial',
      data: { content: 'what is my balance', content_mode: 'snapshot', turn_id: 't1', sequence: 2 },
    }),
  );
  messages = apply(
    messages,
    envelope('event', 'User', {
      type: 'user',
      content: 'What is my balance?',
      message: 'What is my balance?',
      streaming: false,
      content_mode: 'final_turn',
      is_final: true,
      turn_id: 't1',
    }),
  );
  assert.equal(role(messages, 't1', 'user').text, 'What is my balance?');
  assert.equal(role(messages, 't1', 'user').streaming, false);

  // 3. Agent starts responding, announces the tool, and the tool runs.
  messages = apply(
    messages,
    envelope('assistant_streaming', 'Banking Concierge', {
      content: 'Let me check that. ',
      content_mode: 'delta',
      turn_id: 't1',
      segment_id: 't1',
    }),
  );
  messages = apply(messages, {
    type: 'tool_start',
    tool: 'lookup_balance',
    call_id: 'lb-1',
    turn_id: 't1',
    segment_id: 't1',
  });
  messages = apply(messages, {
    type: 'tool_end',
    tool: 'lookup_balance',
    call_id: 'lb-1',
    turn_id: 't1',
    segment_id: 't1',
    status: 'success',
    result: { balance: 42 },
  });

  // 4. Agent final.
  messages = apply(
    messages,
    envelope('event', 'Banking Concierge', {
      type: 'assistant',
      content: 'Let me check that. Your balance is $42.',
      message: 'Let me check that. Your balance is $42.',
      streaming: false,
      content_mode: 'final_turn',
      turn_id: 't1',
      segment_id: 't1',
    }),
  );

  // Turn 1 is exactly [user, assistant, tool].
  const turn1 = turnMessages(messages, 't1');
  assert.deepEqual(turn1.map((m) => m.turnRole), ['user', 'assistant', 'tool']);
  assert.equal(turn1[1].text, 'Let me check that. Your balance is $42.');
  assert.equal(turn1[1].streaming, false);
  assert.equal(turn1[2].toolCalls.length, 1);
  assert.equal(turn1[2].toolCalls[0].status, 'success');

  // 5. User barges in: first STT partial of turn 2 opens a new canonical turn,
  //    which closes turn 1's response and does NOT clone a tool blob into turn 2.
  messages = apply(
    messages,
    envelope('event', 'STT', {
      event_type: 'stt_partial',
      data: { content: 'actually transfer money', content_mode: 'snapshot', turn_id: 't2', sequence: 1 },
    }),
  );
  messages = apply(
    messages,
    envelope('event', 'User', {
      type: 'user',
      content: 'Actually, transfer money.',
      message: 'Actually, transfer money.',
      streaming: false,
      content_mode: 'final_turn',
      is_final: true,
      turn_id: 't2',
    }),
  );
  messages = apply(
    messages,
    envelope('assistant_streaming', 'Banking Concierge', {
      content: 'Sure, transferring now.',
      content_mode: 'delta',
      turn_id: 't2',
      segment_id: 't2',
    }),
  );
  messages = apply(
    messages,
    envelope('event', 'Banking Concierge', {
      type: 'assistant',
      content: 'Sure, transferring now.',
      message: 'Sure, transferring now.',
      streaming: false,
      content_mode: 'final_turn',
      turn_id: 't2',
      segment_id: 't2',
    }),
  );

  // Whole-conversation invariants: greeting + 2 fully-formed turns, no leakage.
  const greetings = messages.filter(
    (m) => m.turnRole === 'assistant' && m.turnId !== 't1' && m.turnId !== 't2',
  );
  assert.equal(greetings.length, 1);
  assert.equal(greetings[0].text, 'Welcome to the bank. How can I help?');

  const turn2 = turnMessages(messages, 't2');
  assert.deepEqual(turn2.map((m) => m.turnRole), ['user', 'assistant']); // no tool blob leaked
  assert.equal(turn2[0].text, 'Actually, transfer money.');
  assert.equal(turn2[1].text, 'Sure, transferring now.');

  // Exactly one user, one response, and one tool blob for turn 1; one user and
  // one response for turn 2. Never a duplicate bubble.
  const countRole = (turnId, r) =>
    turnMessages(messages, turnId).filter((m) => m.turnRole === r).length;
  assert.equal(countRole('t1', 'user'), 1);
  assert.equal(countRole('t1', 'assistant'), 1);
  assert.equal(countRole('t1', 'tool'), 1);
  assert.equal(countRole('t2', 'user'), 1);
  assert.equal(countRole('t2', 'assistant'), 1);
  assert.equal(countRole('t2', 'tool'), 0);
});



test('error envelope becomes an error bubble carrying code, message and remediation', () => {
  const frame = envelope('error', 'System', {
    error_message: "The model deployment 'gpt-4o-mini' was not found.",
    error_type: 'DeploymentNotFound',
    code: 'DeploymentNotFound',
    message: "The model deployment 'gpt-4o-mini' was not found.",
    content: "The model deployment 'gpt-4o-mini' was not found.",
    details: 'DeploymentNotFound: The API deployment for this resource does not exist.',
    remediation: "Check that the agent's model name matches a real deployment.",
    source: 'llm',
    fatal: false,
  });

  const event = conversationBubbleEventFromPayload(flattenSessionEnvelope(frame));
  assert.equal(event.type, BubbleEventType.ERROR);
  assert.equal(event.code, 'DeploymentNotFound');
  assert.equal(event.source, 'llm');

  const messages = apply([], frame);
  assert.equal(messages.length, 1);
  const bubble = messages[0];
  assert.equal(bubble.kind, 'error');
  assert.equal(bubble.speaker, 'System');
  // ChatBubble's existing error card keys off `status`/`error`.
  assert.equal(bubble.status, 'error');
  assert.equal(bubble.error.code, 'DeploymentNotFound');
  assert.equal(bubble.error.message, "The model deployment 'gpt-4o-mini' was not found.");
  assert.equal(
    bubble.error.remediation,
    "Check that the agent's model name matches a real deployment.",
  );
});

test('an identical repeated error does not flood the transcript', () => {
  const frame = envelope('error', 'System', {
    error_message: 'Voice not available.',
    error_type: 'VoiceNotAvailable',
    code: 'VoiceNotAvailable',
    message: 'Voice not available.',
    source: 'tts',
    fatal: false,
  });

  let messages = apply([], frame);
  messages = apply(messages, frame);
  assert.equal(messages.length, 1);

  // A *different* error still appends.
  const other = envelope('error', 'System', {
    error_message: 'Rate limit exceeded.',
    error_type: 'RateLimitExceeded',
    code: 'RateLimitExceeded',
    message: 'Rate limit exceeded.',
    source: 'llm',
    fatal: false,
  });
  messages = apply(messages, other);
  assert.equal(messages.length, 2);
  assert.equal(messages[1].error.code, 'RateLimitExceeded');
});

test('error bubbles never overwrite conversation turns', () => {
  let messages = apply([], envelope('user', 'User', { content: 'Hello', turn_id: 't1' }));
  messages = apply(
    messages,
    envelope('error', 'System', {
      error_message: 'Speech synthesis failed.',
      code: 'VoiceNotAvailable',
      message: 'Speech synthesis failed.',
      source: 'tts',
      turn_id: 't1',
    }),
  );

  assert.equal(messages.length, 2);
  assert.equal(messages[0].turnRole, 'user');
  assert.equal(messages[0].text, 'Hello');
  assert.equal(messages[1].kind, 'error');
});
