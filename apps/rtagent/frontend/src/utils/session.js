import logger from './logger.js';

export const SESSION_STORAGE_KEY = 'voice_agent_session_id';

export const getOrCreateSessionId = () => {
  let sessionId = sessionStorage.getItem(SESSION_STORAGE_KEY);

  if (!sessionId) {
    const tabId = Math.random().toString(36).substr(2, 6);
    sessionId = `session_${Date.now()}_${tabId}`;
    sessionStorage.setItem(SESSION_STORAGE_KEY, sessionId);
  }

  return sessionId;
};

export const createNewSessionId = () => {
  const tabId = Math.random().toString(36).substr(2, 6);
  const sessionId = `session_${Date.now()}_${tabId}`;
  sessionStorage.setItem(SESSION_STORAGE_KEY, sessionId);
  logger.info('Created NEW session ID for reset:', sessionId);
  return sessionId;
};

export const createMetricsState = () => ({
  sessionStart: null,
  sessionStartIso: null,
  sessionId: null,
  firstTokenTs: null,
  ttftMs: null,
  turnCounter: 0,
  turns: [],
  bargeInEvents: [],
  pendingBargeIn: null,
  lastAudioFrameTs: null,
  currentTurnId: null,
  awaitingAudioTurnId: null,
});

export const toMs = (value) => (typeof value === 'number' ? Math.round(value) : undefined);
