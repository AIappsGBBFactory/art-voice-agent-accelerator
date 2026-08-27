// Requested-vs-applied VoiceLive session config, normalized for display.
//
// The backend (`LiveOrchestrator._verify_session_contract`) already decided
// whether the live session matches what was tuned, including the SKU tolerance
// that makes `gpt-realtime` and `gpt-realtime-datazone-standard` the same model.
// This module deliberately does NOT re-derive any of that: it reads the
// booleans the backend sent. Comparing the strings here would re-introduce the
// false alarm the backend allowlist exists to prevent.
//
// Kept pure and dependency-free so the panel's state derivation is testable
// without a browser.

const asText = (value) => {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
};

const readContract = (payload) => {
  if (!payload || typeof payload !== 'object') return null;
  const candidates = [payload.contract, payload.data?.contract, payload.event_data?.contract];
  for (const candidate of candidates) {
    if (candidate && typeof candidate === 'object') return candidate;
  }
  return null;
};

/**
 * Human-readable reasons the live session does not match what was requested.
 * Only verifiable divergences are listed; an unknown (null) flag is silence,
 * not an accusation.
 */
const collectIssues = (contract) => {
  const issues = [];

  if (contract.voice_ok === false) {
    issues.push(
      `Voice: requested ${asText(contract.voice_requested) || 'unknown'}, ` +
        `running ${asText(contract.voice_applied) || 'unknown'}`,
    );
  }
  if (contract.model_ok === false) {
    issues.push(
      `Model: requested ${asText(contract.model_requested) || 'unknown'}, ` +
        `running ${asText(contract.model_applied) || 'unknown'}`,
    );
  }
  if (contract.agent_ok === false) {
    issues.push(
      `Agent: session was set up for ${asText(contract.bound_agent) || 'unknown'}, ` +
        `but ${asText(contract.active_agent) || 'unknown'} is live — its voice and ` +
        'instructions are not the tuned ones',
    );
  }
  if (contract.model_override_ignored === true) {
    issues.push(
      `${asText(contract.active_agent) || 'This agent'} asks for ` +
        `${asText(contract.agent_requested_model) || 'another model'}, but the connection is ` +
        `bound to ${asText(contract.connection_model) || 'its model'} and cannot change mid-call`,
    );
  }

  return issues;
};

/**
 * Normalize a `session_updated` payload into the session-config view model.
 *
 * Returns `null` when the payload carries no contract, so callers can keep the
 * previous (still accurate) contract rather than blanking the panel on an
 * envelope that simply predates this feature.
 */
export const deriveSessionContract = (payload) => {
  const contract = readContract(payload);
  if (!contract) return null;

  const issues = collectIssues(contract);
  // `overall_ok` is the backend aggregate. Fall back to the issue list only
  // when talking to a backend that predates it, never to string comparison.
  const ok =
    typeof contract.overall_ok === 'boolean' ? contract.overall_ok : issues.length === 0;

  return {
    status: ok ? 'ok' : 'mismatch',
    ok,
    activeAgent: asText(contract.active_agent) || asText(payload?.agent_name) || null,
    boundAgent: asText(contract.bound_agent),
    agentOk: typeof contract.agent_ok === 'boolean' ? contract.agent_ok : null,
    voice: {
      requested: asText(contract.voice_requested),
      applied: asText(contract.voice_applied),
      ok: typeof contract.voice_ok === 'boolean' ? contract.voice_ok : null,
    },
    model: {
      requested: asText(contract.model_requested),
      applied: asText(contract.model_applied),
      ok: typeof contract.model_ok === 'boolean' ? contract.model_ok : null,
      // Present when the service echoed a deployment tier (e.g. the applied
      // name is `gpt-realtime-datazone-standard` for a requested
      // `gpt-realtime`). This is a match, so it is a note and never a warning.
      appliedSku: asText(contract.model_applied_sku),
    },
    connectionModel: asText(contract.connection_model),
    agentRequestedModel: asText(contract.agent_requested_model),
    modelOverrideIgnored: contract.model_override_ignored === true,
    issues,
    updatedAt: payload?.ts || payload?.timestamp || null,
  };
};

export default deriveSessionContract;
