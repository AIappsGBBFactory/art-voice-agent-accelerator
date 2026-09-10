import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';

let vite;
let LiveSessionConfigCard;
let deriveSessionContract;

test.before(async () => {
  vite = await createServer({
    root: process.cwd(),
    server: { middlewareMode: true },
    appType: 'custom',
    logLevel: 'silent',
  });
  ({ LiveSessionConfigCard } = await vite.ssrLoadModule(
    '/src/components/SessionPerformancePanel.jsx',
  ));
  ({ deriveSessionContract } = await vite.ssrLoadModule('/src/utils/sessionContract.js'));
});

test.after(async () => {
  await vite?.close();
});

const render = (contract) =>
  renderToStaticMarkup(
    React.createElement(LiveSessionConfigCard, { contract: deriveSessionContract({ contract }) }),
  );

const matching = {
  voice_requested: 'en-us-emmamultilingualneural',
  voice_applied: 'en-us-emmamultilingualneural',
  voice_ok: true,
  model_requested: 'gpt-realtime',
  model_applied: 'gpt-realtime',
  model_ok: true,
  model_applied_sku: null,
  ok: true,
  active_agent: 'Concierge',
  bound_agent: 'Concierge',
  agent_ok: true,
  connection_model: 'gpt-realtime',
  agent_requested_model: 'gpt-realtime',
  model_override_ignored: false,
  overall_ok: true,
};

test('a matching session renders as confirmation, with no warning', () => {
  const html = render(matching);

  assert.match(html, /matches what you configured/);
  assert.match(html, /MATCH/);
  assert.doesNotMatch(html, /MISMATCH/);
  assert.doesNotMatch(html, /Not as requested/);
});

test('a deployment SKU echo is confirmation plus a neutral tier note', () => {
  const html = render({
    ...matching,
    model_applied: 'gpt-realtime-datazone-standard',
    model_applied_sku: 'datazone-standard',
  });

  assert.match(html, /matches what you configured/);
  assert.doesNotMatch(html, /MISMATCH/);
  assert.match(html, /Same model, served from the &quot;datazone-standard&quot; deployment tier\./);
});

test('the production split-brain renders as an unmissable mismatch', () => {
  // Tuned as Concierge with Emma; BankingConcierge was restored onto the session
  // and speaks with Alloy, and its gpt-realtime override is silently ignored.
  const html = render({
    ...matching,
    voice_requested: 'en-us-alloyturbomultilingualneural',
    voice_applied: 'en-us-alloyturbomultilingualneural',
    voice_ok: true,
    tuned_voice: 'en-us-emmamultilingualneural',
    active_agent: 'BankingConcierge',
    bound_agent: 'Concierge',
    agent_ok: false,
    connection_model: 'gpt-4o-mini',
    model_requested: 'gpt-4o-mini',
    model_applied: 'gpt-4o-mini',
    agent_requested_model: 'gpt-realtime',
    model_override_ignored: true,
    ok: true,
    overall_ok: false,
  });

  assert.match(html, /is not the one you configured/);
  assert.match(html, /Not as requested/);
  assert.match(html, /MISMATCH/);
  // Both sides of every divergence are on screen.
  assert.match(html, /Concierge/);
  assert.match(html, /BankingConcierge/);
  assert.match(html, /en-us-emmamultilingualneural/);
  assert.match(html, /en-us-alloyturbomultilingualneural/);
  assert.match(html, /gpt-realtime/);
  assert.match(html, /gpt-4o-mini/);
  assert.match(html, /cannot change it mid-call/);
  // The Voice row truthfully reads MATCH here, so it must not be left to read
  // as reassurance: the displaced voice is named right beneath it.
  assert.match(html, /You configured en-us-emmamultilingualneural, which belongs to Concierge/);
});

test('the displaced-voice note is omitted when the agent did not drift', () => {
  const html = render(matching);

  assert.doesNotMatch(html, /You configured/);
  assert.doesNotMatch(html, /is not speaking/);
});

test('an unverifiable field is shown as unreported rather than as a mismatch', () => {
  const html = render({
    ...matching,
    voice_applied: null,
    voice_ok: null,
    model_applied: null,
    model_ok: null,
  });

  assert.match(html, /not reported/);
  assert.doesNotMatch(html, /MISMATCH/);
});
