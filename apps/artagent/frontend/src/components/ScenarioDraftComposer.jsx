import { memo, useEffect, useId, useMemo, useRef, useState } from 'react';
import {
  Accordion, AccordionDetails, AccordionSummary, Alert, AlertTitle,
  Box, Button, Chip, CircularProgress, Divider, MenuItem, Paper, Stack, TextField, Typography,
} from '@mui/material';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import QuickTuneAgentEditor from './QuickTuneAgentEditor.jsx';
import ScenarioFlowEditor from './ScenarioFlowEditor.jsx';
import ScenarioGraphDialog from './ScenarioGraphDialog.jsx';
import ToolCatalogPicker from './ToolCatalogPicker.jsx';
import {
  agentKey, copyAgentConfig, loadEditableAgent, mergeAgentAssignments, quickTuneRequest, replaceScenarioAgent, scenarioFlowError,
} from '../utils/quickTune.js';
import logger from '../utils/logger.js';
import {
  authoringSelectProps, authoringSurfaceSx,
} from '../styles/authoringStyles.js';
import { maiConfigurationError } from '../utils/maiSpeech.js';

const isMissing = (value) => value === undefined || value === null
  || (typeof value === 'string' && !value.trim());

// Shared "review one agent" panel: a new draft agent gets the full editor,
// a reused agent gets a read-only summary with a "Customize a copy" escape
// hatch. Used by both the simple list review and the graphical review dialog
// so there is exactly one place this logic lives.
function AgentReviewPanel({
  agentName, draft, catalog, mode, onModeChange, busy, applied, onUpdateDraft, onCustomizeCopy, onRenameAgent, catalogUnavailable,
  assignmentAgents, sessionId, voicesLoading, onRefreshVoices,
}) {
  const newAgent = draft.agents.find((agent) => agentKey(agent.name) === agentKey(agentName));
  const reusedAgent = catalog.agents.find((agent) => agentKey(agent.name) === agentKey(agentName));
  if (newAgent) {
    return (
      <QuickTuneAgentEditor config={newAgent} isNew initialSection="behavior"
        sessionId={sessionId} scenario={draft.scenario}
        contextNotice="Previewing this scenario draft. Its new agents and context are not registered until Apply scenario."
        tools={catalog.tools} voices={catalog.voices} models={catalog.models}
        voiceMetadata={catalog.voiceMetadata} voicesLoading={voicesLoading} onRefreshVoices={onRefreshVoices}
        assignmentAgents={assignmentAgents} toolsAvailable={!catalogUnavailable} assignmentsAvailable={!catalogUnavailable}
        mode={mode} onModeChange={onModeChange} disabled={Boolean(busy) || applied}
        onChange={(config) => {
          if (config.name !== newAgent.name) onRenameAgent?.(newAgent.name, config.name);
          onUpdateDraft({
            ...draft,
            agents: draft.agents.map((agent) => agent.name === newAgent.name ? config : agent),
            scenario: config.name === newAgent.name ? draft.scenario
              : replaceScenarioAgent(draft.scenario, newAgent.name, config.name),
          });
        }} />
    );
  }
  return (
    <Paper variant="outlined" sx={{ ...authoringSurfaceSx, p: 2, borderRadius: 2 }}>
      <Stack spacing={1.5}>
        <Typography fontWeight={600}>{agentName}</Typography>
        <Typography variant="body2">{reusedAgent?.description || 'Existing agent'}</Typography>
        <Stack direction="row" gap={0.75} flexWrap="wrap">
          {(reusedAgent?.tools || []).map((tool) => <Chip key={tool} label={tool} size="small" variant="outlined" />)}
        </Stack>
        <Typography variant="caption" color="text.secondary">
          Reused unchanged. Make a copy to customize its instructions, tools, or voice.
        </Typography>
        <Button size="small" startIcon={<ContentCopyIcon />} onClick={() => onCustomizeCopy(agentName)}
          disabled={Boolean(busy) || applied || catalogUnavailable} sx={{ alignSelf: 'flex-start' }}>Customize a copy</Button>
      </Stack>
    </Paper>
  );
}

const ScenarioDraftComposer = memo(function ScenarioDraftComposer({
  sessionId, catalog, catalogLoading, catalogErrors, connected = false,
  onApplied, onDraftChange, assignmentAgents = [], voicesLoading = false, onRefreshVoices,
}) {
  const promptInputId = useId();
  const [prompt, setPrompt] = useState('');
  const [draft, setDraft] = useState(null);
  const [allowedTools, setAllowedTools] = useState(null);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [mode, setMode] = useState('voicelive');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [applied, setApplied] = useState(false);
  // Graph review dialog state. Layout (drag positions) and the inspected
  // node are kept here - outside `draft` - so they never reach the strict
  // backend ScenarioDraft schema and survive the dialog closing/reopening.
  const [showGraph, setShowGraph] = useState(false);
  const [graphLayout, setGraphLayout] = useState({});
  const [inspectedAgentName, setInspectedAgentName] = useState(null);
  const lifetime = useRef(null);
  const toolScopeRef = useRef(null);

  useEffect(() => {
    lifetime.current = new AbortController();
    return () => lifetime.current.abort();
  }, []);
  useEffect(() => {
    onDraftChange?.(Boolean((draft || prompt.trim()) && !applied));
  }, [draft, prompt, applied, onDraftChange]);

  const updateDraft = (next) => {
    setDraft(next);
    setError('');
    setApplied(false);
  };
  const renameGraphAgent = (previousName, nextName) => {
    setInspectedAgentName((current) => agentKey(current) === agentKey(previousName) ? nextName : current);
    setGraphLayout((previous) => {
      if (!previous[previousName]) return previous;
      const next = { ...previous, [nextName]: previous[previousName] };
      delete next[previousName];
      return next;
    });
  };
  const setScenario = (scenario) => updateDraft({
    ...draft, scenario,
    agents: draft.agents.filter((agent) => scenario.agents.includes(agent.name)),
  });
  // ScenarioGraphCanvas calls onConfigChange with a React-style updater
  // function; adapt that to the composer's own updateDraft/setScenario pair
  // without inventing any fields the backend draft schema does not expect.
  const handleGraphConfigChange = (updater) => {
    const nextScenario = typeof updater === 'function' ? updater(draft.scenario) : updater;
    setScenario(nextScenario);
  };

  const generate = async () => {
    setBusy('generating');
    setError('');
    const signal = lifetime.current.signal;
    try {
      const data = await quickTuneRequest(
        `scenario-builder/generate?session_id=${encodeURIComponent(sessionId)}`,
        {
          method: 'POST', signal, timeoutMs: 95000,
          body: JSON.stringify({ prompt: prompt.trim(), draft, allowed_tools: allowedTools }),
        },
      );
      if (!data.scenario?.name || !Array.isArray(data.scenario.agents)
        || !Array.isArray(data.scenario.handoffs) || !Array.isArray(data.agents)
        || !Array.isArray(data.warnings) || !Array.isArray(data.required_inputs)
        || !Array.isArray(data.missing_capabilities)) {
        throw new Error('The server returned an invalid draft. The active scenario is unchanged.');
      }
      if (signal.aborted) return;
      updateDraft(data);
      setSelectedIndex(0);
      setInspectedAgentName(null);
      setShowGraph(true);
    } catch (cause) {
      if (signal.aborted) return;
      logger.error('Scenario draft generation failed:', cause);
      setError(cause.message);
    } finally {
      if (!signal.aborted) setBusy('');
    }
  };

  const apply = async () => {
    setBusy('applying');
    setError('');
    const signal = lifetime.current.signal;
    try {
      const data = await quickTuneRequest(
        `scenario-builder/apply-draft?session_id=${encodeURIComponent(sessionId)}`,
        { method: 'POST', signal, body: JSON.stringify(draft) },
      );
      if (!data.config?.name) throw new Error('The server did not confirm a saved scenario. Refresh before retrying.');
      if (signal.aborted) return;
      setApplied(true);
      setShowGraph(false);
      await onApplied(data.config, draft.agents);
    } catch (cause) {
      if (signal.aborted) return;
      logger.error('Scenario draft application failed:', cause);
      setError(cause.message);
    } finally {
      if (!signal.aborted) setBusy('');
    }
  };

  const selectedName = draft?.scenario.agents[selectedIndex] || draft?.scenario.agents[0];
  const customizeCopy = async (name = selectedName) => {
    setBusy('copying');
    setError('');
    const signal = lifetime.current.signal;
    try {
      const config = await loadEditableAgent(name, sessionId, catalog.agents, signal);
      const copy = copyAgentConfig(config, [
        ...catalog.agents.map((agent) => agent.name), ...draft.scenario.agents,
      ], catalog.tools);
      if (signal.aborted) return;
      updateDraft({
        ...draft,
        agents: [...draft.agents, copy],
        scenario: replaceScenarioAgent(draft.scenario, name, copy.name),
      });
      renameGraphAgent(name, copy.name);
    } catch (cause) {
      if (!signal.aborted) {
        logger.error('Could not copy agent into draft:', cause);
        setError(cause.message);
      }
    } finally {
      if (!signal.aborted) setBusy('');
    }
  };

  const requiredInputs = draft?.required_inputs || [];
  const missingInputs = requiredInputs.filter((key) => isMissing(draft.scenario.global_template_vars?.[key]));
  const missingCapabilities = draft?.missing_capabilities || [];
  const flowValidation = scenarioFlowError(draft?.scenario, catalog.tools);
  const speechValidation = (draft?.agents || []).map((agent) => {
    const error = maiConfigurationError(agent, mode, catalog.voiceMetadata);
    return error ? `${agent.name}: ${error}` : '';
  }).find(Boolean);
  const catalogUnavailable = catalogLoading
    || catalogErrors.some((message) => message.startsWith('Tool catalog') || message.startsWith('Agent catalog'));
  const canApply = draft && !applied && !busy && !connected
    && !missingInputs.length && !missingCapabilities.length && !flowValidation && !speechValidation && !catalogUnavailable;
  const contextKeys = [...new Set([
    ...requiredInputs, ...Object.keys(draft?.scenario.global_template_vars || {}),
  ])];
  // The graph catalog combines existing templates/session overrides with the
  // draft's new agent definitions only, so new/isolated nodes render with a
  // description without ever registering them.
  const graphAgents = useMemo(() => [
    ...catalog.agents,
    ...(draft?.agents || []).map((agent) => ({ ...agent, prompt_full: agent.prompt })),
  ], [catalog.agents, draft?.agents]);
  const toolAssignmentAgents = useMemo(() => mergeAgentAssignments(
    catalog.agents, assignmentAgents,
    (draft?.agents || []).map((agent) => ({ ...agent, has_local_draft: !applied })),
  ), [catalog.agents, assignmentAgents, draft?.agents, applied]);

  return (
    <Stack spacing={2.5} sx={authoringSurfaceSx}>
      <Box>
        <Typography component="h3" variant="h6" fontWeight={650}>Start with an outcome</Typography>
        <Typography variant="body2" color="text.secondary">
          Describe the conversation you want. We will reuse suitable agents and draft specialists only when needed.
        </Typography>
      </Box>
      <Stack spacing={1}>
        <Typography component="label" htmlFor={promptInputId} variant="body2" fontWeight={600}
          color={busy || applied ? 'text.disabled' : 'text.primary'}>
          {draft ? 'Describe a refinement' : 'What should this scenario do?'}
        </Typography>
        <TextField id={promptInputId}
          placeholder="For example: help customers check their balance, then route suspected fraud to a specialist."
          multiline minRows={4} maxRows={10} value={prompt} disabled={Boolean(busy) || applied}
          onChange={(event) => setPrompt(event.target.value)}
          slotProps={{ htmlInput: { maxLength: 8000 } }}
          helperText="Uses your registered tools. Generation never calls them or changes the running scenario." />
      </Stack>
      <Accordion disableGutters elevation={0}
        slotProps={{ transition: {
          onEntered: () => toolScopeRef.current?.scrollIntoView({ block: 'start', inline: 'nearest' }),
        } }}
        sx={{
        border: '1px solid', borderColor: 'divider', borderRadius: '10px !important',
        '&:before': { display: 'none' },
      }}>
        <AccordionSummary ref={toolScopeRef} expandIcon={<ExpandMoreIcon />} sx={{ textAlign: 'left' }}>
          <Typography variant="body2">
            Tool scope: {allowedTools === null ? `all ${catalog.tools.length} registered tools` : `${allowedTools.length} selected tools`}
          </Typography>
        </AccordionSummary>
        <AccordionDetails>
          <Stack spacing={1}>
            <ToolCatalogPicker tools={catalog.tools} disabled={Boolean(busy) || applied}
              value={allowedTools ?? catalog.tools.map((tool) => tool.name)} onChange={setAllowedTools}
              agents={toolAssignmentAgents}
              toolsAvailable={!catalogLoading && !catalogErrors.some((message) => message.startsWith('Tool catalog'))}
              assignmentsAvailable={!catalogLoading && !catalogErrors.some((message) => message.startsWith('Agent catalog'))} />
            {allowedTools !== null && <Button size="small" disabled={Boolean(busy) || applied}
              sx={{ alignSelf: 'flex-start' }} onClick={() => setAllowedTools(null)}>Use all registered tools</Button>}
            <Typography variant="caption" color="text.secondary">
              The server rechecks tool availability and connections before applying.
            </Typography>
          </Stack>
        </AccordionDetails>
      </Accordion>
      <Button variant="contained" startIcon={busy === 'generating' ? <CircularProgress size={16} color="inherit" /> : <AutoAwesomeIcon />}
        disabled={!prompt.trim() || Boolean(busy) || catalogUnavailable || applied} onClick={generate}
        sx={{ alignSelf: 'flex-start', textTransform: 'none', boxShadow: 'none' }}>
        {busy === 'generating' ? 'Drafting scenario...' : draft ? 'Refine draft' : 'Generate draft'}
      </Button>
      {error && <Alert severity="error" role="alert">{error}</Alert>}
      {draft && (
        <>
          <Divider />
          <Stack spacing={1}>
            <Typography component="h3" variant="h6" fontWeight={650}>Review your scenario</Typography>
            <Stack direction="row" gap={1} alignItems="center" flexWrap="wrap" justifyContent="space-between">
              <Button size="small" startIcon={<AccountTreeIcon fontSize="small" />}
                onClick={() => setShowGraph(true)} sx={{ textTransform: 'none' }}>
                Graphical editor
              </Button>
              <Chip label={applied ? 'Applied' : 'Draft - not active'} size="small" color={applied ? 'success' : 'default'} />
            </Stack>
          </Stack>
          <Typography variant="body2" color="text.secondary">{draft.summary}</Typography>
          {draft.warnings.map((warning, index) => <Alert severity="info" key={index}>{warning}</Alert>)}
          {missingCapabilities.length > 0 && (
            <Alert severity="warning">
              <AlertTitle>Capabilities still needed</AlertTitle>
              {missingCapabilities.map((capability, index) => <Typography variant="body2" key={index}>{capability}</Typography>)}
              <Typography variant="body2" sx={{ mt: 1 }}>
                Connect the missing tools in Advanced Builder, or refine the request to remove unsupported work.
              </Typography>
            </Alert>
          )}
          <Stack component="fieldset" disabled={Boolean(busy) || applied} spacing={2}
            sx={{ m: 0, p: 0, minWidth: 0, border: 0 }}>
            <TextField label="Scenario name" value={draft.scenario.name} size="small"
              onChange={(event) => setScenario({ ...draft.scenario, name: event.target.value })} />
            <TextField label="Scenario purpose" value={draft.scenario.description || ''} size="small" multiline
              onChange={(event) => setScenario({ ...draft.scenario, description: event.target.value })} />
            <ScenarioFlowEditor scenario={draft.scenario} onChange={setScenario} tools={catalog.tools}
              availableAgents={catalog.agents.map((agent) => agent.name)} disabled={Boolean(busy) || applied} />
            {draft.scenario.agents.length > 0 && (
              <>
                <Divider />
                <TextField select size="small" label="Review agent" value={selectedName || ''}
                  slotProps={{ select: authoringSelectProps }}
                  onChange={(event) => setSelectedIndex(draft.scenario.agents.indexOf(event.target.value))}>
                  {draft.scenario.agents.map((name, index) => (
                    <MenuItem key={index} value={name}>
                      {name || '(name required)'} - {draft.agents.some((agent) => agent.name === name) ? 'New' : 'Reused'}
                    </MenuItem>
                  ))}
                </TextField>
                <AgentReviewPanel agentName={selectedName} draft={draft} catalog={catalog}
                  voicesLoading={voicesLoading} onRefreshVoices={onRefreshVoices}
                  sessionId={sessionId}
                  assignmentAgents={toolAssignmentAgents}
                  mode={mode} onModeChange={setMode} busy={busy} applied={applied}
                  onUpdateDraft={updateDraft} onCustomizeCopy={customizeCopy}
                  onRenameAgent={renameGraphAgent}
                  catalogUnavailable={catalogUnavailable} />
              </>
            )}
            {contextKeys.length > 0 && (
              <>
                <Typography variant="subtitle2">Scenario context</Typography>
                {contextKeys.map((key) => {
                  const value = draft.scenario.global_template_vars?.[key];
                  const structured = value !== null && typeof value === 'object';
                  return (
                    <TextField key={key} label={key} size="small" required={requiredInputs.includes(key)}
                      value={structured ? JSON.stringify(value) : value ?? ''}
                      slotProps={{ input: { readOnly: structured } }}
                      helperText={structured ? 'Structured context is preserved. Refine the draft to change it.' : undefined}
                      onChange={(event) => setScenario({
                        ...draft.scenario,
                        global_template_vars: { ...draft.scenario.global_template_vars, [key]: event.target.value },
                      })} />
                  );
                })}
              </>
            )}
          </Stack>
          {connected && !applied && (
            <Alert severity="info">End the current conversation before applying a different scenario. Your draft is kept here.</Alert>
          )}
          {missingInputs.length > 0 && <Alert severity="warning">Fill in required context: {missingInputs.join(', ')}.</Alert>}
          {flowValidation && <Alert severity="warning">{flowValidation}</Alert>}
          {speechValidation && <Alert severity="warning">{speechValidation}</Alert>}
          {applied ? (
            <Alert severity="success">
              Scenario saved and selected. Start a conversation to try it.
              <Button size="small" onClick={() => {
                setDraft(null); setPrompt(''); setApplied(false); setError('');
                setShowGraph(false); setGraphLayout({}); setInspectedAgentName(null);
              }} sx={{ display: 'block', mt: 1 }}>Create another scenario</Button>
            </Alert>
          ) : (
            <Stack direction="row" gap={1} flexWrap="wrap">
              <Button variant="contained" onClick={apply} disabled={!canApply} sx={{ textTransform: 'none', boxShadow: 'none' }}>
                {busy === 'applying' ? 'Applying scenario...' : 'Apply scenario'}
              </Button>
              <Button disabled={Boolean(busy)} onClick={() => {
                setDraft(null); setError(''); setSelectedIndex(0);
                setShowGraph(false); setGraphLayout({}); setInspectedAgentName(null);
              }}>Discard draft</Button>
            </Stack>
          )}
        </>
      )}
      {draft && (
        <ScenarioGraphDialog
          open={showGraph}
          onClose={() => setShowGraph(false)}
          title="Review the generated scenario"
          subtitle="Drag, connect, and edit nodes here. Nothing is saved until you apply."
          agents={graphAgents}
          config={draft.scenario}
          onConfigChange={handleGraphConfigChange}
          layout={graphLayout}
          onLayoutChange={setGraphLayout}
          onSelectAgent={setInspectedAgentName}
          disabled={Boolean(busy) || applied}
          banner={error || speechValidation || connected || missingInputs.length > 0 || missingCapabilities.length > 0 ? (
            <Stack spacing={1}>
              {error && <Alert severity="error">{error}</Alert>}
              {speechValidation && <Alert severity="warning">{speechValidation}</Alert>}
              {connected && <Alert severity="info">End the current conversation before applying this scenario.</Alert>}
              {missingInputs.length > 0 && <Alert severity="warning">Fill required context in Quick Tune before applying: {missingInputs.join(', ')}.</Alert>}
              {missingCapabilities.length > 0 && (
                <Alert severity="warning">
                  <AlertTitle>Capabilities still needed</AlertTitle>
                  {missingCapabilities.map((capability, index) => <Typography variant="body2" key={index}>{capability}</Typography>)}
                </Alert>
              )}
            </Stack>
          ) : null}
          inspector={inspectedAgentName && draft.scenario.agents.includes(inspectedAgentName) ? (
            <Stack spacing={1.5}>
              <Typography variant="subtitle2">Inspect agent</Typography>
              <AgentReviewPanel agentName={inspectedAgentName} draft={draft} catalog={catalog}
                voicesLoading={voicesLoading} onRefreshVoices={onRefreshVoices}
                sessionId={sessionId}
                assignmentAgents={toolAssignmentAgents}
                mode={mode} onModeChange={setMode} busy={busy} applied={applied}
                onUpdateDraft={updateDraft} onCustomizeCopy={customizeCopy}
                onRenameAgent={renameGraphAgent}
                catalogUnavailable={catalogUnavailable} />
            </Stack>
          ) : null}
          actions={(
            <>
              {flowValidation && <Alert severity="warning" sx={{ flex: 1, py: 0 }}>{flowValidation}</Alert>}
              <Button onClick={() => setShowGraph(false)}>Close</Button>
              <Button variant="contained" onClick={apply} disabled={!canApply}
                sx={{ textTransform: 'none', boxShadow: 'none' }}>
                {busy === 'applying' ? 'Applying scenario...' : 'Apply scenario'}
              </Button>
            </>
          )}
        />
      )}
    </Stack>
  );
});

export default ScenarioDraftComposer;
