// src/utils/telemetry.js
//
// Browser-side Application Insights instrumentation.
//
// Correlation model:
//   - ai.session.id  = the voice session id (shared with the backend, which
//     stamps the same key on its spans). This is what ties browser telemetry
//     to the server-side call in App Insights (union by session_Id).
//   - authenticatedId = an obfuscated, non-reversible pseudonym of the signed-in
//     operator (EasyAuth /.auth/me). The raw Entra oid/email never leaves the
//     client; the pseudonym matches the backend so the same operator correlates
//     end-to-end, enabling "user activities across sessions" in the Users /
//     User Flows / Retention blades without exposing PII.
//
// The connection string is injected at container start by entrypoint.sh
// (replacing the __APPINSIGHTS_CONNECTION_STRING__ placeholder), with a Vite
// env fallback for local development. When neither is present, telemetry is a
// no-op so the app still runs unmodified.

import { ApplicationInsights, DistributedTracingModes } from '@microsoft/applicationinsights-web';
import logger from './logger.js';

const CONNECTION_STRING_PLACEHOLDER = '__APPINSIGHTS_CONNECTION_STRING__';

// Dependency (fetch) targets that represent passive polling and add no
// diagnostic value; dropped from browser telemetry to reduce noise. Covers
// health/probe endpoints and the periodic status/metrics polls the UI issues.
const NOISY_DEPENDENCY_RE =
  /\/(health|healthz|readiness|liveness|ping)\b|\/api\/v1\/mcp\/servers|\/api\/v1\/metrics\/session\//i;

const resolveConnectionString = () => {
  if (!CONNECTION_STRING_PLACEHOLDER.startsWith('__')) {
    return CONNECTION_STRING_PLACEHOLDER;
  }
  return import.meta.env?.VITE_APPLICATIONINSIGHTS_CONNECTION_STRING || '';
};

// App Insights disallows commas, semicolons, equals, pipes and spaces in the
// user/account id fields; normalize so identity is preserved but valid.
const sanitizeId = (value) =>
  value == null ? undefined : String(value).replace(/[,;=| ]+/g, '_');

// Stable, non-reversible pseudonym salt. Mirrors the backend
// TELEMETRY_PII_HASH_SALT default so the SAME signed-in user hashes to the SAME
// token in browser and server telemetry (deployments that override the backend
// salt should set VITE_TELEMETRY_PII_HASH_SALT to match).
const HASH_SALT =
  import.meta.env?.VITE_TELEMETRY_PII_HASH_SALT || 'artvoice-log-pseudonym-v1';

// Obfuscate a sensitive identifier into a stable, non-reversible pseudonym of
// the form `<prefix>:<10 hex>`. Byte-for-byte compatible with the backend
// utils.pii_filter.mask_pii (SHA-256 of `"<salt>:<value>"`, first 10 hex).
const maskId = async (value, prefix = 'user') => {
  if (value == null || value === '') return `${prefix}:none`;
  try {
    const bytes = new TextEncoder().encode(`${HASH_SALT}:${value}`);
    const digest = await crypto.subtle.digest('SHA-256', bytes);
    const hex = Array.from(new Uint8Array(digest), (b) =>
      b.toString(16).padStart(2, '0'),
    ).join('');
    return `${prefix}:${hex.slice(0, 10)}`;
  } catch {
    return `${prefix}:unknown`;
  }
};

let appInsights = null;
let initialized = false;
let currentSessionId = null;
let currentTraceparent = null;

// 16 random bytes -> 32 hex (trace id); 8 bytes -> 16 hex (span id).
const randomHex = (bytes) => {
  const arr = new Uint8Array(bytes);
  crypto.getRandomValues(arr);
  return Array.from(arr, (b) => b.toString(16).padStart(2, '0')).join('');
};

// Start (or reuse) the distributed-trace operation for a voice session. Sets
// the App Insights operation trace so all browser telemetry for the session
// shares operation_Id = traceId, and returns the matching W3C traceparent to
// hand to the backend over the WebSocket (which the SDK cannot auto-propagate).
// Generates a traceparent even when telemetry is disabled, so the backend can
// still stitch its own spans into one end-to-end trace.
const beginOperation = (sessionId) => {
  const sid = sessionId || currentSessionId;
  if (sid && sid === currentSessionId && currentTraceparent) {
    return currentTraceparent;
  }
  currentSessionId = sid || currentSessionId;
  const traceId = randomHex(16);
  const spanId = randomHex(8);
  currentTraceparent = `00-${traceId}-${spanId}-01`;
  if (appInsights) {
    try {
      appInsights.context.telemetryTrace.traceID = traceId;
      appInsights.context.telemetryTrace.parentID = spanId;
      if (sid) appInsights.context.telemetryTrace.name = sid;
    } catch (err) {
      logger.warn('[telemetry] failed to set operation trace:', err?.message || err);
    }
  }
  return currentTraceparent;
};

export const initTelemetry = () => {
  if (initialized) return appInsights;
  initialized = true;

  const connectionString = resolveConnectionString();
  if (!connectionString) {
    logger.info('[telemetry] App Insights connection string not configured; browser telemetry disabled');
    return null;
  }

  try {
    appInsights = new ApplicationInsights({
      config: {
        connectionString,
        // Propagate W3C traceparent on cross-origin fetch/XHR to the backend
        // so REST calls correlate end-to-end.
        distributedTracingMode: DistributedTracingModes.AI_AND_W3C,
        enableCorsCorrelation: true,
        disableFetchTracking: false,
        enableAutoRouteTracking: true,
        autoTrackPageVisitTime: true,
        enableUnhandledPromiseRejectionTracking: true,
      },
    });
    appInsights.loadAppInsights();

    // Stamp the active voice session id onto every telemetry item so browser
    // and backend share ai.session.id, and drop dependency noise from passive
    // polling (health probes + periodic status/metrics fetches) so App Insights
    // isn't flooded with low-value entries.
    appInsights.addTelemetryInitializer((item) => {
      if (
        item?.baseType === 'RemoteDependencyData' &&
        NOISY_DEPENDENCY_RE.test(String(item?.baseData?.target || item?.baseData?.name || ''))
      ) {
        return false; // drop
      }
      if (currentSessionId) {
        item.tags = item.tags || {};
        item.tags['ai.session.id'] = currentSessionId;
      }
      return true;
    });

    appInsights.trackPageView();
    logger.info('[telemetry] App Insights initialized');
  } catch (err) {
    logger.error('[telemetry] App Insights init failed:', err?.message || err);
    appInsights = null;
  }

  return appInsights;
};

export const getAppInsights = () => appInsights;

/**
 * Bind the signed-in operator identity so App Insights groups every session
 * under one user across time. The raw identity is never sent: only a stable,
 * non-reversible pseudonym (matching the backend) populates the App Insights
 * authenticated-user field, and the email is omitted entirely.
 * @param {{userId?: string, email?: string}|null} user
 */
export const setAuthenticatedUser = async (user) => {
  if (!appInsights || !user?.userId) return;
  try {
    const authId = sanitizeId(await maskId(user.userId, 'user'));
    appInsights.setAuthenticatedUserContext(
      authId,
      // No accountId: the raw email is PII and must not reach telemetry.
      undefined,
      // storeInCookie=true so the association persists across sessions/tabs.
      true,
    );
  } catch (err) {
    logger.warn('[telemetry] setAuthenticatedUserContext failed:', err?.message || err);
  }
};

/** Clear the authenticated user (e.g. on sign-out). */
export const clearAuthenticatedUser = () => {
  if (!appInsights) return;
  try {
    appInsights.clearAuthenticatedUserContext();
  } catch {
    /* noop */
  }
};

/** Set the active voice session id used as ai.session.id on all telemetry. */
export const setVoiceSession = (sessionId) => {
  beginOperation(sessionId);
};

/**
 * Ensure a distributed-trace operation exists for the session and return the
 * W3C traceparent to forward to the backend over the WebSocket URL.
 */
export const getSessionTraceparent = (sessionId) => beginOperation(sessionId);

const DEVICE_ID_KEY = 'voice_agent_device_id';

/**
 * Stable, persistent anonymous browser/device id. Prefers the App Insights
 * ai_user id (already persisted in the ai_user cookie ~1yr) so the backend
 * groups anonymous sessions the SAME way the browser does; falls back to a
 * localStorage-persisted id when telemetry is disabled. Enables cross-session
 * tracking even when EasyAuth is off (device-level rather than identity-level).
 */
export const getDeviceId = () => {
  try {
    const aiId = appInsights?.context?.user?.id;
    if (aiId) return String(aiId);
  } catch {
    /* noop */
  }
  try {
    let id = localStorage.getItem(DEVICE_ID_KEY);
    if (!id) {
      id = `device_${randomHex(8)}`;
      localStorage.setItem(DEVICE_ID_KEY, id);
    }
    return id;
  } catch {
    return null;
  }
};

const withSession = (properties = {}) => ({
  ...properties,
  ...(currentSessionId ? { session_id: currentSessionId } : {}),
});

/**
 * Track a custom event. Numeric values in `measurements` become metrics that
 * are aggregatable in App Insights.
 */
export const trackEvent = (name, properties = {}, measurements = undefined) => {
  if (!appInsights || !name) return;
  try {
    appInsights.trackEvent({ name, measurements }, withSession(properties));
  } catch {
    /* noop */
  }
};

/** Track a single-value metric (e.g. TTFT). */
export const trackMetric = (name, average, properties = {}) => {
  if (!appInsights || !name || average == null || Number.isNaN(average)) return;
  try {
    appInsights.trackMetric({ name, average }, withSession(properties));
  } catch {
    /* noop */
  }
};

/** Track an exception with session/context tags. */
export const trackException = (error, properties = {}) => {
  if (!appInsights || !error) return;
  try {
    appInsights.trackException({ exception: error }, withSession(properties));
  } catch {
    /* noop */
  }
};
