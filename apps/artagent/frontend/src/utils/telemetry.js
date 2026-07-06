// src/utils/telemetry.js
//
// Browser-side Application Insights instrumentation.
//
// Correlation model:
//   - ai.session.id  = the voice session id (shared with the backend, which
//     stamps the same key on its spans). This is what ties browser telemetry
//     to the server-side call in App Insights (union by session_Id).
//   - authenticatedId = the signed-in operator (EasyAuth /.auth/me). This is
//     what enables "user activities across sessions" in the Users / User Flows
//     / Retention blades.
//
// The connection string is injected at container start by entrypoint.sh
// (replacing the __APPINSIGHTS_CONNECTION_STRING__ placeholder), with a Vite
// env fallback for local development. When neither is present, telemetry is a
// no-op so the app still runs unmodified.

import { ApplicationInsights, DistributedTracingModes } from '@microsoft/applicationinsights-web';
import logger from './logger.js';

const CONNECTION_STRING_PLACEHOLDER = '__APPINSIGHTS_CONNECTION_STRING__';

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

let appInsights = null;
let initialized = false;
let currentSessionId = null;

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
    // and backend share ai.session.id.
    appInsights.addTelemetryInitializer((item) => {
      if (currentSessionId) {
        item.tags = item.tags || {};
        item.tags['ai.session.id'] = currentSessionId;
      }
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
 * under one user across time.
 * @param {{userId?: string, email?: string}|null} user
 */
export const setAuthenticatedUser = (user) => {
  if (!appInsights || !user?.userId) return;
  try {
    appInsights.setAuthenticatedUserContext(
      sanitizeId(user.userId),
      sanitizeId(user.email),
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
  currentSessionId = sessionId || null;
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
