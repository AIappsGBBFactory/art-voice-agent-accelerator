import { useCallback, useEffect, useRef, useState } from 'react';
import { agentKey, quickTuneRequest, sameConfig } from '../utils/quickTune.js';
import logger from '../utils/logger.js';

const isDirty = (entry) => Boolean(entry && (
  !sameConfig(entry.base, entry.config) || Object.values(entry.jsonErrors).some(Boolean)
));

export default function useScenarioEditor({ open, enabled, sessionId, activeScenario, scenarios }) {
  const [selectedName, setSelectedName] = useState(activeScenario?.name || '');
  const [entries, setEntries] = useState({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  const userSelected = useRef(false);
  const key = agentKey(selectedName);
  const entry = entries[key];
  const metadata = scenarios.find((item) => agentKey(item.name) === key);

  useEffect(() => {
    if (!userSelected.current) {
      setSelectedName(activeScenario?.name || scenarios.find((item) => item.is_active)?.name || scenarios[0]?.name || '');
    }
  }, [activeScenario?.name, scenarios]);

  useEffect(() => {
    if (open) setEntries((previous) => Object.fromEntries(
      Object.entries(previous).filter(([, item]) => isDirty(item)),
    ));
  }, [open]);

  useEffect(() => {
    if (!open || !enabled || !selectedName || entry) {
      setLoading(false);
      return undefined;
    }
    const controller = new AbortController();
    setLoading(true);
    setError('');
    const load = async () => {
      try {
        let data = await quickTuneRequest(
          `scenario-builder/session/${encodeURIComponent(sessionId)}?scenario_name=${encodeURIComponent(selectedName)}`,
          { signal: controller.signal, allowNotFound: true },
        );
        if (!data?.config || agentKey(data.config.name) !== key) {
          if (metadata?.is_custom || metadata?.is_session_override) {
            throw new Error('The saved scenario is not available yet. Refresh before editing it.');
          }
          const templateId = metadata?.id || selectedName.toLowerCase().replace(/\s+/g, '_');
          data = await quickTuneRequest(`scenario-builder/templates/${encodeURIComponent(templateId)}`, {
            signal: controller.signal,
          });
        }
        if (!data.config || agentKey(data.config.name) !== key) {
          throw new Error('Could not load the complete scenario configuration. Refresh before editing.');
        }
        if (controller.signal.aborted) return;
        setEntries((previous) => ({
          ...previous,
          [key]: { config: data.config, base: data.config, layout: {}, jsonDrafts: {}, jsonErrors: {} },
        }));
      } catch (cause) {
        if (!controller.signal.aborted) {
          logger.error('Quick Tune scenario loading failed:', cause);
          setError(cause.message);
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };
    load();
    return () => controller.abort();
  }, [open, enabled, sessionId, selectedName, key, entry, metadata?.id, metadata?.is_custom, metadata?.is_session_override, reload]);

  const updateEntry = useCallback((updater) => {
    userSelected.current = true;
    setEntries((previous) => ({ ...previous, [key]: updater(previous[key]) }));
    setError('');
  }, [key]);
  const updateConfig = useCallback((updater) => updateEntry((current) => ({
    ...current,
    config: typeof updater === 'function' ? updater(current.config) : updater,
  })), [updateEntry]);
  const updateLayout = useCallback((updater) => updateEntry((current) => ({
    ...current,
    layout: typeof updater === 'function' ? updater(current.layout) : updater,
  })), [updateEntry]);
  const updateJson = useCallback((field, text) => {
    let value;
    let message = '';
    try {
      value = JSON.parse(text, (_, item) => {
        if (typeof item === 'number' && !Number.isFinite(item)) throw new RangeError('Use finite numbers.');
        return item;
      });
      if (!value || typeof value !== 'object' || Array.isArray(value)) {
        message = 'Use a JSON object with named values.';
      } else if (field === 'agent_defaults') {
        const allowed = new Set(['greeting', 'return_greeting', 'description', 'template_vars', 'voice_name', 'voice_rate']);
        const unknown = Object.keys(value).filter((name) => !allowed.has(name));
        if (unknown.length) message = `Unsupported agent defaults: ${unknown.join(', ')}.`;
      }
    } catch (cause) {
      if (!(cause instanceof SyntaxError) && !(cause instanceof RangeError)) throw cause;
      message = cause instanceof RangeError ? 'Use finite numbers in context.' : 'Complete the JSON object before saving.';
    }
    updateEntry((current) => ({
      ...current,
      config: message ? current.config : { ...current.config, [field]: value },
      jsonDrafts: { ...current.jsonDrafts, [field]: text },
      jsonErrors: { ...current.jsonErrors, [field]: message },
    }));
  }, [updateEntry]);
  const discard = useCallback(() => updateEntry((current) => ({
    ...current, config: structuredClone(current.base), jsonDrafts: {}, jsonErrors: {},
  })), [updateEntry]);
  const markSaved = useCallback((config) => updateEntry((current) => ({
    ...current, config, base: config, jsonDrafts: {}, jsonErrors: {},
  })), [updateEntry]);

  return {
    entries,
    selectedName, select: (name) => { userSelected.current = true; setSelectedName(name); setError(''); },
    entry, loading, error, setError, updateConfig, updateLayout, updateJson, discard, markSaved,
    dirty: isDirty(entry), hasDrafts: Object.values(entries).some(isDirty),
    jsonError: Object.values(entry?.jsonErrors || {}).find(Boolean) || '',
    retry: () => setReload((value) => value + 1),
  };
}
