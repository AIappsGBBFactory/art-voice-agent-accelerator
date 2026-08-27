/**
 * Foundry / Voice Live resource + region attribution.
 *
 * Quick Tune switches its model dropdown between two different Azure accounts —
 * the primary AI Foundry account for Cascade and the Voice Live (AVL) account
 * for VoiceLive. Voice Live is only offered in a subset of regions, so those
 * accounts are routinely provisioned in different geographies from each other
 * AND from the app itself, and every turn pays the distance.
 *
 * These are pure functions with no network or Vite dependency, so the
 * comparison rules that decide what the panel claims can be unit tested
 * directly.
 */

/**
 * Canonicalize an Azure region for comparison.
 *
 * Azure reports regions in two shapes — the display form the resource itself
 * returns ("Sweden Central") and the slug form configuration uses
 * ("swedencentral"). Comparing them raw makes one region look like two, which
 * would raise a cross-region warning for a colocated deployment.
 */
export const regionKeyOf = (value) =>
  (value || '')
    .toLowerCase()
    .split('')
    .filter((ch) => /[a-z0-9]/.test(ch))
    .join('');

/**
 * Suffix for the "Model" section label naming where the list came from.
 * Degrades gracefully: resource without region, region without resource, or
 * nothing at all when the backend couldn't determine either.
 *
 * `managed` covers BYOM-off VoiceLive, where the models are Microsoft-hosted
 * rather than deployments on your account — naming the account as their source
 * would be wrong, but its region still describes where the socket lands.
 */
export function describeModelSource(info, { managed = false } = {}) {
  const parts = [];
  if (managed) {
    parts.push('managed Voice Live');
  } else if (info?.resourceName) {
    parts.push(info.resourceName);
  }
  if (info?.region) parts.push(info.region);
  return parts.length ? ` · ${parts.join(' · ')}` : '';
}

/**
 * Advisory describing the geographic hops the current model list implies, or
 * null when there's nothing worth saying.
 *
 * Two independent signals, because they cost latency in different places:
 *   • active vs app — every turn leaves the app's region to reach the model.
 *   • active vs other — the two orchestrators are served from different
 *     geographies, so switching modes changes the latency floor.
 *
 * Returns null whenever a region is unknown: the panel stays silent rather
 * than implying a hop it can't verify.
 */
export function crossRegionHint({ active, app, other } = {}) {
  const activeKey = regionKeyOf(active?.region);
  const appKey = regionKeyOf(app);
  const otherKey = regionKeyOf(other?.region);

  const awayFromApp = Boolean(activeKey && appKey && activeKey !== appKey);
  // resourceFallback means both modes are served by ONE account, which cannot
  // be in two regions — so differing strings there are stale, not a real split.
  const splitFromOther = Boolean(
    activeKey && otherKey && activeKey !== otherKey && !active?.resourceFallback,
  );
  if (!awayFromApp && !splitFromOther) return null;

  const lines = [];
  if (awayFromApp) {
    lines.push(
      `${active.label} — served from ${active.region}, while this app runs in ${app}. `
      + 'Every turn crosses that distance, which adds round-trip latency no '
      + 'setting in this panel can tune away.',
    );
  }
  if (splitFromOther) {
    lines.push(
      `${other.label} — served from ${other.region}, so switching modes also `
      + 'changes how far the audio has to travel.',
    );
  }
  return { title: 'Cross-region round trip', lines };
}

/**
 * Normalize the resource/region attribution the backend tags every model and
 * voice list with, so callers never have to know the snake_case wire names.
 */
export function resourceAttribution(data = {}) {
  return {
    resourceName: data.resource_name || '',
    resourceFallback: Boolean(data.resource_fallback),
    endpointHost: data.endpoint_host || '',
    // Which Azure region actually serves this list, and whether that came from
    // the resource itself ('resource') or from configuration ('config').
    region: data.region || '',
    regionKey: data.region_key || regionKeyOf(data.region),
    regionSource: data.region_source || '',
    // Where the backend itself runs, for the distance comparison.
    appRegion: data.app_region || '',
    appRegionKey: data.app_region_key || regionKeyOf(data.app_region),
  };
}

/** Field names produced by `resourceAttribution`. */
export const ATTRIBUTION_KEYS = Object.keys(resourceAttribution());

/** Carry the attribution fields across to a differently-shaped result. */
export const pickAttribution = (normalized = {}) =>
  Object.fromEntries(ATTRIBUTION_KEYS.map((key) => [key, normalized[key]]));
