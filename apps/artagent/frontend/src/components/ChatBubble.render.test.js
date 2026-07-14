import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';

let vite;
let ChatBubble;

test.before(async () => {
  vite = await createServer({
    root: process.cwd(),
    server: { middlewareMode: true },
    appType: 'custom',
    logLevel: 'silent',
  });
  ({ default: ChatBubble } = await vite.ssrLoadModule('/src/components/ChatBubble.jsx'));
});

test.after(async () => {
  await vite?.close();
});

const renderBubble = (message) =>
  renderToStaticMarkup(React.createElement(ChatBubble, { message }));

test('streaming user bubble is italic, inline, and normalized without a phantom newline', () => {
  const html = renderBubble({
    speaker: 'User',
    text: 'hello\n\nworld\n',
    streaming: true,
    turnId: 'turn-1',
  });

  assert.match(html, /font-style:italic/);
  assert.match(html, /hello world/);
  assert.match(html, /▌/);
  assert.doesNotMatch(html, /hello<br\/?>/);
});

test('final assistant bubble becomes normal text and removes the streaming cursor', () => {
  const html = renderBubble({
    speaker: 'Concierge',
    text: 'Final response.',
    streaming: false,
    turnId: 'turn-1',
  });

  assert.match(html, /font-style:normal/);
  assert.match(html, /Final response\./);
  assert.doesNotMatch(html, /▌/);
});

test('tool group stays hidden until a tool response exists', () => {
  const started = renderBubble({
    speaker: 'Assistant',
    isTool: true,
    isToolGroup: true,
    turnId: 'turn-1',
    toolCalls: [
      {
        callKey: 'call-1',
        callId: 'call-1',
        toolName: 'lookup_balance',
        status: 'started',
      },
    ],
  });
  assert.equal(started, '');

  const completed = renderBubble({
    speaker: 'Assistant',
    isTool: true,
    isToolGroup: true,
    turnId: 'turn-1',
    toolCalls: [
      {
        callKey: 'call-1',
        callId: 'call-1',
        toolName: 'lookup_balance',
        status: 'success',
        result: { balance: 42 },
      },
    ],
  });
  assert.match(completed, /Tool Activity/);
  assert.match(completed, /lookup balance/);
  assert.match(completed, /42/);
});

test('barge-in cancelled response bubble drops the cursor and shows the reason', () => {
  const html = renderBubble({
    speaker: 'Concierge',
    text: 'Your balance is fifty',
    streaming: false,
    cancelled: true,
    cancelReason: 'barge_in',
    turnId: 'turn-1',
  });

  // No live cursor once cancelled, and the underscore reason is humanized.
  assert.doesNotMatch(html, /▌/);
  assert.match(html, /Your balance is fifty/);
  assert.match(html, /barge in/);
});
