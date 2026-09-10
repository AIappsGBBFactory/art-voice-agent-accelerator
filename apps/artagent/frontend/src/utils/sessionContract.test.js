import test from 'node:test';
import assert from 'node:assert/strict';

import { deriveSessionContract } from './sessionContract.js';

const envelope = (contract, extra = {}) => ({
  type: 'event',
  event_type: 'session_updated',
  agent_name: contract?.active_agent ?? 'Concierge',
  contract,
  ts: '2026-01-01T00:00:00Z',
  ...extra,
});

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

test('a fully matching contract reports ok with no issues', () => {
  const derived = deriveSessionContract(envelope(matching));

  assert.equal(derived.status, 'ok');
  assert.equal(derived.ok, true);
  assert.deepEqual(derived.issues, []);
  assert.equal(derived.activeAgent, 'Concierge');
  assert.equal(derived.voice.applied, 'en-us-emmamultilingualneural');
});

test('a deployment SKU echo is a match, not an alarm', () => {
  // gpt-realtime vs gpt-realtime-datazone-standard is the same model on a
  // differently-provisioned deployment. The UI must trust model_ok rather than
  // comparing the strings, or every call reports a false substitution.
  const derived = deriveSessionContract(
    envelope({
      ...matching,
      model_applied: 'gpt-realtime-datazone-standard',
      model_applied_sku: 'datazone-standard',
    }),
  );

  assert.equal(derived.status, 'ok');
  assert.deepEqual(derived.issues, []);
  assert.notEqual(derived.model.requested, derived.model.applied);
  assert.equal(derived.model.ok, true);
  assert.equal(derived.model.appliedSku, 'datazone-standard');
});

test('a substituted voice reports a mismatch naming both sides', () => {
  const derived = deriveSessionContract(
    envelope({
      ...matching,
      voice_applied: 'en-us-alloyturbomultilingualneural',
      voice_ok: false,
      ok: false,
      overall_ok: false,
    }),
  );

  assert.equal(derived.status, 'mismatch');
  assert.equal(derived.ok, false);
  assert.equal(derived.issues.length, 1);
  assert.match(derived.issues[0], /en-us-emmamultilingualneural/);
  assert.match(derived.issues[0], /en-us-alloyturbomultilingualneural/);
});

test('an agent restored from a previous connection reports a mismatch', () => {
  // The production split-brain: the session was tuned as Concierge, but
  // BankingConcierge was restored onto it and is what actually speaks.
  const derived = deriveSessionContract(
    envelope({
      ...matching,
      active_agent: 'BankingConcierge',
      bound_agent: 'Concierge',
      agent_ok: false,
      tuned_voice: 'en-us-emmamultilingualneural',
      voice_requested: 'en-us-alloyturbomultilingualneural',
      voice_applied: 'en-us-alloyturbomultilingualneural',
      overall_ok: false,
    }),
  );

  assert.equal(derived.status, 'mismatch');
  assert.equal(derived.agentOk, false);
  assert.equal(derived.boundAgent, 'Concierge');
  assert.equal(derived.activeAgent, 'BankingConcierge');
  assert.match(derived.issues[0], /Concierge/);
  assert.match(derived.issues[0], /BankingConcierge/);
  // The voice contract itself is satisfied, so the displaced voice is the only
  // thing that can tell the operator what they actually lost.
  assert.equal(derived.voice.ok, true);
  assert.equal(derived.tunedVoice, 'en-us-emmamultilingualneural');
  assert.match(derived.issues[0], /en-us-emmamultilingualneural is not what the caller hears/);
});

test('an ignored per-agent model override is explained', () => {
  const derived = deriveSessionContract(
    envelope({
      ...matching,
      connection_model: 'gpt-4o-mini',
      agent_requested_model: 'gpt-realtime',
      model_override_ignored: true,
      overall_ok: false,
    }),
  );

  assert.equal(derived.status, 'mismatch');
  assert.equal(derived.modelOverrideIgnored, true);
  assert.match(derived.issues[0], /gpt-realtime/);
  assert.match(derived.issues[0], /gpt-4o-mini/);
});

test('several divergences are all listed', () => {
  const derived = deriveSessionContract(
    envelope({
      ...matching,
      voice_applied: 'en-us-alloyturbomultilingualneural',
      voice_ok: false,
      active_agent: 'BankingConcierge',
      bound_agent: 'Concierge',
      agent_ok: false,
      connection_model: 'gpt-4o-mini',
      agent_requested_model: 'gpt-realtime',
      model_override_ignored: true,
      ok: false,
      overall_ok: false,
    }),
  );

  assert.equal(derived.issues.length, 3);
});

test('unverifiable fields are silence, not accusations', () => {
  const derived = deriveSessionContract(
    envelope({
      voice_requested: 'en-us-emmamultilingualneural',
      voice_applied: null,
      voice_ok: null,
      model_requested: 'gpt-realtime',
      model_applied: null,
      model_ok: null,
      ok: true,
      active_agent: 'Concierge',
      bound_agent: 'Concierge',
      agent_ok: true,
      connection_model: 'gpt-realtime',
      agent_requested_model: null,
      model_override_ignored: false,
      overall_ok: true,
    }),
  );

  assert.equal(derived.status, 'ok');
  assert.equal(derived.voice.ok, null);
  assert.equal(derived.model.ok, null);
  assert.deepEqual(derived.issues, []);
});

test('a payload without a contract yields null so the panel keeps the last one', () => {
  assert.equal(deriveSessionContract(envelope(undefined)), null);
  assert.equal(deriveSessionContract({ event_type: 'session_updated' }), null);
  assert.equal(deriveSessionContract(null), null);
});

test('the contract is found when nested under the flattened event data', () => {
  const payload = {
    event_type: 'session_updated',
    data: { contract: matching },
  };

  assert.equal(deriveSessionContract(payload).status, 'ok');
});

test('overall_ok is trusted over the locally collected issues', () => {
  // A backend that flags something this module does not yet render must still
  // turn the badge red rather than silently reporting OK.
  const derived = deriveSessionContract(envelope({ ...matching, overall_ok: false }));

  assert.equal(derived.status, 'mismatch');
  assert.deepEqual(derived.issues, []);
});
