// src/utils/auth.js
//
// Reads the signed-in principal from the platform EasyAuth endpoint (/.auth/me)
// exposed by Azure Container Apps / App Service authentication. Used only to
// attribute telemetry to the operator and to forward identity to the backend
// WebSocket; it does NOT gate any app behavior. When EasyAuth is not enabled
// the endpoint is absent and this resolves to null (anonymous).

import logger from './logger.js';

const OID_CLAIM = 'http://schemas.microsoft.com/identity/claims/objectidentifier';
const EMAIL_CLAIMS = [
  'preferred_username',
  'http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress',
  'emails',
  'email',
  'upn',
  'http://schemas.microsoft.com/identity/claims/upn',
];
const NAME_CLAIM = 'name';

let cachedUser = null;
let fetched = false;

const buildClaimMap = (claims) => {
  const map = {};
  for (const claim of claims || []) {
    const typ = claim.typ || claim.type;
    const val = claim.val || claim.value;
    if (typ && val && !(typ in map)) map[typ] = val;
  }
  return map;
};

const normalizePrincipal = (data) => {
  // /.auth/me shapes vary by host:
  //   - App Service / Container Apps: array of { user_id, user_claims, ... }
  //   - Static Web Apps: { clientPrincipal: { userId, userDetails, claims } }
  const principal = Array.isArray(data)
    ? data[0]
    : data?.clientPrincipal || data;
  if (!principal) return null;

  // Static Web Apps shape
  if (principal.userId || principal.userDetails) {
    return {
      userId: principal.userId || principal.userDetails || null,
      email: principal.userDetails || null,
      name: principal.userDetails || null,
    };
  }

  const claimMap = buildClaimMap(principal.user_claims || principal.claims);
  const email = EMAIL_CLAIMS.map((c) => claimMap[c]).find(Boolean) || principal.user_id || null;
  const userId = claimMap[OID_CLAIM] || claimMap.oid || principal.user_id || email;
  const name = claimMap[NAME_CLAIM] || null;

  if (!userId && !email) return null;
  return { userId: userId || email, email, name };
};

/**
 * Resolve the authenticated user once and cache it.
 * @returns {Promise<{userId: string, email: string|null, name: string|null}|null>}
 */
export const fetchAuthenticatedUser = async () => {
  if (fetched) return cachedUser;
  fetched = true;
  try {
    const res = await fetch('/.auth/me', { credentials: 'include' });
    if (!res.ok) return null;
    const data = await res.json();
    cachedUser = normalizePrincipal(data);
    if (cachedUser) {
      logger.info('[auth] Signed-in operator resolved from /.auth/me');
    }
    return cachedUser;
  } catch (err) {
    logger.debug('[auth] /.auth/me not available (EasyAuth likely disabled):', err?.message || err);
    return null;
  }
};

/** Synchronous accessor for the cached authenticated user (may be null). */
export const getAuthenticatedUser = () => cachedUser;

/** Build the auth identity query string for the backend WebSocket URL. */
export const buildAuthQueryParams = () => {
  const user = cachedUser;
  if (!user) return '';
  // Forward only the operator id (an opaque Entra oid). The backend
  // pseudonymizes it for telemetry. The raw email is intentionally NOT sent —
  // it is PII and is never emitted to telemetry.
  return `&auth_user_id=${encodeURIComponent(user.userId)}`;
};
