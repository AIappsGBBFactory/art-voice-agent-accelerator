const SESSION_STORAGE_KEY = 'voice_agent_session_id';

/**
 * Provides helpers for generating conversation session identifiers.
 * Session identifiers are scoped to the current browser tab.
 */
export const getOrCreateSessionId = () => {
  let sessionId = sessionStorage.getItem(SESSION_STORAGE_KEY);

  if (!sessionId) {
    sessionId = buildSessionId();
    sessionStorage.setItem(SESSION_STORAGE_KEY, sessionId);
  }

  return sessionId;
};

/**
 * Forces creation of a brand-new session identifier and updates storage.
 */
export const createNewSessionId = () => {
  const sessionId = buildSessionId();
  sessionStorage.setItem(SESSION_STORAGE_KEY, sessionId);
  console.info('Created NEW session ID for reset:', sessionId);
  return sessionId;
};

const buildSessionId = () => {
  const tabId = Math.random().toString(36).slice(2, 8);
  return `session_${Date.now()}_${tabId}`;
};
