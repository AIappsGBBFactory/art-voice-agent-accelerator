import { useCallback, useEffect, useRef, useState } from 'react';
import { quickTuneRequest } from '../utils/quickTune.js';
import logger from '../utils/logger.js';

export default function usePromptPreview({ open, sessionId, payload }) {
  const [snapshot, setSnapshot] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const latest = useRef(payload);
  latest.current = payload;
  const controller = useRef(null);
  const refresh = useCallback(async () => {
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    setLoading(true);
    setError('');
    const submitted = structuredClone(latest.current);
    try {
      const data = await quickTuneRequest(
        `agent-builder/prompt-preview?session_id=${encodeURIComponent(sessionId)}`,
        { method: 'POST', signal: request.signal, body: JSON.stringify(submitted) },
      );
      if (!Array.isArray(data.variables) || !Array.isArray(data.errors)
        || !Array.isArray(data.missing_variables) || !Array.isArray(data.warnings)
        || (data.rendered_prompt !== null && typeof data.rendered_prompt !== 'string')) {
        throw new Error('The server returned an invalid prompt preview.');
      }
      if (!request.signal.aborted) setSnapshot({ data, signature: JSON.stringify(submitted) });
    } catch (cause) {
      if (!request.signal.aborted) {
        logger.error('Prompt preview could not be loaded:', cause);
        setError(cause.status === 404
          ? 'The prompt preview endpoint is not available on the connected backend. Start or restart the updated API, then retry. Your draft is kept.'
          : cause.message);
      }
    } finally {
      if (!request.signal.aborted) setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    if (open) {
      setSnapshot(null);
      refresh();
    }
    return () => controller.current?.abort();
  }, [open, sessionId, payload.agent_name, refresh]);

  return {
    data: snapshot?.data, loading, error, refresh,
    stale: Boolean(snapshot && snapshot.signature !== JSON.stringify(payload)),
  };
}
