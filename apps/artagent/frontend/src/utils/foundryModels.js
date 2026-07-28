/**
 * Foundry model & voice discovery helpers.
 *
 * Centralizes the "what can the CONNECTED Azure AI Foundry / Azure OpenAI
 * resource actually serve in its region" queries so both the standalone
 * AgentBuilder dialog and the embedded AgentBuilderContent (scenario builder)
 * show the same live deployment list instead of a hardcoded preset list.
 *
 *   • GET /api/v1/agent-builder/models  → real model deployments (incl. regional
 *     realtime/voice models). Each entry is tagged by the backend with `category`,
 *     `arch` ('native' | 'cascaded') and `modes` (['cascade'], ['voicelive'], or
 *     both) so we can route it to the correct dropdown.
 *   • GET /api/v1/agent-builder/voices  → TTS neural voices, already validated
 *     against the region by the backend (`verified_against_region`).
 *
 * Design contract: these helpers NEVER throw. On any failure (no creds, network,
 * empty list) they return null so callers can fall back to their static presets.
 */
import { API_BASE_URL } from '../config/constants.js';

/**
 * Classify a model by its VoiceLive audio architecture. Mirrors the backend
 * tagging; used only as a fallback when a model entry lacks an explicit `arch`.
 *   • 'native'   → realtime speech-to-speech (audio in/out).
 *   • 'cascaded' → Azure STT → text LLM → Azure TTS.
 */
export const classifyModelArch = (deploymentId) => {
  const name = (deploymentId || '').toLowerCase();
  if (!name) return 'native';
  return name.includes('realtime') ? 'native' : 'cascaded';
};

/**
 * Managed Voice Live models — the VoiceLive-hosted models used when BYOM is OFF.
 * These are NOT your resource deployments; they're billed by Voice Live pricing
 * tier. (BYOM is what lets you use your own deployments instead.)
 *
 * IMPORTANT: this list MUST match the models managed Voice Live actually serves.
 * Offering an unsupported model here lets the connection succeed but the model
 * never produces a response — the agent "stops responding" and the session ends
 * in a 900s idle timeout. In particular the plain `gpt-5-chat`, `o1`, `o3` and
 * `o3-mini` deployments are NOT valid managed Voice Live models (only the
 * versioned `gpt-5.x-chat` chat models are) — keep them out of this list.
 * Source (keep in sync):
 * https://learn.microsoft.com/azure/ai-services/speech-service/voice-live#supported-models-and-regions
 */
export const MANAGED_VOICELIVE_MODELS = [
  // Native speech-to-speech (realtime) — lowest latency.
  { id: 'gpt-realtime-1.5', tier: 'pro' },
  { id: 'gpt-realtime', tier: 'pro' },
  { id: 'gpt-realtime-mini', tier: 'basic' },
  { id: 'phi4-mm-realtime', tier: 'lite' },
  { id: 'azure-realtime', tier: 'lite' },
  // Cascaded (Azure STT → text LLM → Azure TTS).
  { id: 'gpt-5.4', tier: 'pro' },
  { id: 'gpt-5.3-chat', tier: 'pro' },
  { id: 'gpt-5.2', tier: 'pro' },
  { id: 'gpt-5.2-chat', tier: 'pro' },
  { id: 'gpt-5.1', tier: 'pro' },
  { id: 'gpt-5.1-chat', tier: 'pro' },
  { id: 'gpt-5', tier: 'pro' },
  { id: 'gpt-5-mini', tier: 'basic' },
  { id: 'gpt-5-nano', tier: 'lite' },
  { id: 'gpt-4.1', tier: 'pro' },
  { id: 'gpt-4.1-mini', tier: 'basic' },
  { id: 'gpt-4.1-nano', tier: 'lite' },
  { id: 'gpt-4o', tier: 'pro' },
  { id: 'gpt-4o-mini', tier: 'basic' },
  { id: 'phi4-mini', tier: 'lite' },
];

// {id, label} options for the managed VoiceLive model dropdown (label shows tier).
export const MANAGED_VOICELIVE_OPTIONS = MANAGED_VOICELIVE_MODELS.map((m) => ({
  id: m.id,
  label: `${m.id} · ${m.tier}`,
  tier: m.tier,
}));

/**
 * True when `deploymentId` is a model that managed Voice Live can actually host
 * (i.e. valid to run with BYOM OFF). Non-managed models — e.g. `o3-mini`, `o1`,
 * `o3`, plain `gpt-5-chat`, or any custom/fine-tuned deployment — REQUIRE a BYOM
 * profile: connecting them as managed lets the socket open but the model never
 * responds, so the agent goes silent. Empty id → true (nothing to validate; the
 * backend applies the managed default).
 */
export const isManagedVoiceLiveModel = (deploymentId) => {
  const id = (deploymentId || '').trim().toLowerCase();
  if (!id) return true;
  return MANAGED_VOICELIVE_MODELS.some((m) => m.id.toLowerCase() === id);
};

/**
 * Fetch the live model deployments for an orchestration mode.
 *
 * `mode` picks WHICH Azure resource is listed — they are usually different
 * accounts (Voice Live is often provisioned in its own region):
 *   • undefined / 'cascade'  → primary AI Foundry / Azure OpenAI (AZURE_OPENAI_ENDPOINT)
 *   • 'voicelive'            → the Voice Live account (AZURE_VOICELIVE_ENDPOINT)
 *
 * Listing the primary resource for the VoiceLive dropdown lets a user pick a
 * deployment Voice Live can't reach: the session connects but the agent never
 * responds. Always pass 'voicelive' for the VoiceLive model list.
 *
 * Returns { models, source, byCategory, resourceName, resourceFallback } or
 * null on failure/empty.
 */
export async function fetchFoundryModels(mode) {
  try {
    const qs = mode ? `?mode=${encodeURIComponent(mode)}` : '';
    const res = await fetch(`${API_BASE_URL}/api/v1/agent-builder/models${qs}`);
    if (!res.ok) return null;
    const data = await res.json();
    const models = Array.isArray(data.models) ? data.models : [];
    if (models.length === 0) return null;
    return {
      models,
      source: data.source || 'azure_openai',
      byCategory: data.by_category || {},
      resourceName: data.resource_name || '',
      resourceFallback: Boolean(data.resource_fallback),
    };
  } catch {
    return null;
  }
}

/**
 * Fetch the deployments on the Voice Live (AVL) resource and return them as
 * ready-to-render VoiceLive dropdown options, or null when unavailable.
 * Returns { options, resourceName, resourceFallback }.
 */
export async function fetchVoiceLiveModels() {
  const live = await fetchFoundryModels('voicelive');
  if (!live) return null;
  const { voicelive } = deriveModelOptions(live.models);
  if (!voicelive.length) return null;
  return {
    options: voicelive,
    resourceName: live.resourceName,
    resourceFallback: live.resourceFallback,
  };
}

/**
 * From the raw /models list, derive ordered option lists for each builder mode.
 * Each option is normalized to { id, label, category, arch, deployed: true }.
 * Realtime (native-audio) models are surfaced first in the VoiceLive list.
 */
export function deriveModelOptions(models = []) {
  const cascade = [];
  const voicelive = [];
  const seenCascade = new Set();
  const seenVoicelive = new Set();

  // Realtime models first for the VoiceLive dropdown; otherwise preserve order.
  const ordered = [...models].sort((a, b) => {
    const ar = a.category === 'realtime' ? 0 : 1;
    const br = b.category === 'realtime' ? 0 : 1;
    return ar - br;
  });

  for (const m of ordered) {
    const id = (m.deployment_id || '').trim();
    if (!id) continue;
    const category = m.category || 'chat';
    if (category === 'embedding' || category === 'transcription') continue;
    const arch = m.arch || classifyModelArch(id);
    const modes =
      Array.isArray(m.modes) && m.modes.length
        ? m.modes
        : category === 'realtime'
          ? ['voicelive']
          : ['cascade', 'voicelive'];
    const key = id.toLowerCase();
    if (modes.includes('cascade') && !seenCascade.has(key)) {
      seenCascade.add(key);
      cascade.push({ id, label: id, category, arch, deployed: true });
    }
    if (modes.includes('voicelive') && !seenVoicelive.has(key)) {
      seenVoicelive.add(key);
      voicelive.push({ id, label: id, category, arch, deployed: true });
    }
  }

  return { cascade, voicelive };
}

/**
 * Fetch the region-validated TTS voice list plus verification metadata.
 * Returns { voices, verifiedAgainstRegion, source, defaultVoice } or null.
 */
export async function fetchRegionVoices() {
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/agent-builder/voices`);
    if (!res.ok) return null;
    const data = await res.json();
    return {
      voices: data.voices || [],
      verifiedAgainstRegion: Boolean(data.verified_against_region),
      source: data.source || 'static-catalog',
      defaultVoice: data.default_voice || null,
    };
  } catch {
    return null;
  }
}
