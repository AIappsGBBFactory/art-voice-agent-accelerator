import { memo, useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import {
  Alert, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, Divider,
  IconButton, InputAdornment, LinearProgress, Stack, Tab, Tabs, TextField, Tooltip,
  Typography, useMediaQuery,
} from '@mui/material';
import { createTheme, ThemeProvider, useTheme } from '@mui/material/styles';
import CloseIcon from '@mui/icons-material/Close';
import CodeIcon from '@mui/icons-material/Code';
import FormatBoldIcon from '@mui/icons-material/FormatBold';
import FormatItalicIcon from '@mui/icons-material/FormatItalic';
import FormatListBulletedIcon from '@mui/icons-material/FormatListBulleted';
import RedoIcon from '@mui/icons-material/Redo';
import RefreshIcon from '@mui/icons-material/Refresh';
import SearchIcon from '@mui/icons-material/Search';
import TitleIcon from '@mui/icons-material/Title';
import UndoIcon from '@mui/icons-material/Undo';
import VisibilityOutlinedIcon from '@mui/icons-material/VisibilityOutlined';
import usePromptPreview from '../hooks/usePromptPreview.js';
import { promptCaret, promptScenarioConfig, replacePromptSelection } from '../utils/promptEditor.js';
import { authoringSurfaceSx } from '../styles/authoringStyles.js';

const SOURCE_LIMIT = 64000;
const HISTORY_LIMIT = 100;

const PromptEditorDialog = memo(function PromptEditorDialog({
  open, onClose, value, onChange, agentName, templateVars = {}, tools = [],
  sessionId, scenario, mode, disabled = false, contextNotice,
  saveAction, saveError, saveNotice,
}) {
  const titleId = useId();
  const sourceId = useId();
  const parentTheme = useTheme();
  const theme = useMemo(() => createTheme(parentTheme, {
    zIndex: { modal: 13030, tooltip: 13040 },
  }), [parentTheme]);
  const desktop = useMediaQuery('(min-width:1000px)');
  const [mobileView, setMobileView] = useState('source');
  const [sideView, setSideView] = useState('context');
  const [query, setQuery] = useState('');
  const [editorError, setEditorError] = useState('');
  const [caret, setCaret] = useState({ line: 1, column: 1 });
  const [, refreshHistory] = useState(0);
  const textareaRef = useRef(null);
  const selection = useRef({ start: 0, end: 0 });
  const latestValue = useRef(value);
  latestValue.current = value;
  const history = useRef({ undo: [], redo: [] });
  const focusFrame = useRef(null);
  const payload = {
    prompt: value, agent_name: agentName, template_vars: templateVars,
    tools, scenario: promptScenarioConfig(scenario), mode,
  };
  const preview = usePromptPreview({ open, sessionId, payload });

  useEffect(() => {
    if (open) {
      history.current = { undo: [], redo: [] };
      refreshHistory((version) => version + 1);
      setMobileView('source');
      setSideView('context');
      setQuery('');
      setEditorError('');
    }
    return () => {
      if (focusFrame.current !== null) cancelAnimationFrame(focusFrame.current);
    };
  }, [open, agentName]);

  const rememberSelection = (event) => {
    const { selectionStart, selectionEnd } = event.currentTarget;
    selection.current = { start: selectionStart, end: selectionEnd };
    setCaret(promptCaret(event.currentTarget.value, selectionStart));
  };
  const restoreSelection = useCallback((edit) => {
    selection.current = { start: edit.start, end: edit.end };
    setCaret(promptCaret(edit.value, edit.start));
    setMobileView('source');
    if (focusFrame.current !== null) cancelAnimationFrame(focusFrame.current);
    focusFrame.current = requestAnimationFrame(() => {
      textareaRef.current?.focus({ preventScroll: true });
      textareaRef.current?.setSelectionRange(edit.start, edit.end);
    });
  }, []);
  const changeSource = (edit, focus = true) => {
    if (edit.value.length > SOURCE_LIMIT) {
      setEditorError(`Keep the prompt within ${SOURCE_LIMIT.toLocaleString()} characters.`);
      return;
    }
    if (edit.value !== latestValue.current) {
      history.current.undo.push({ value: latestValue.current, ...selection.current });
      history.current.undo = history.current.undo.slice(-HISTORY_LIMIT);
      history.current.redo = [];
      refreshHistory((version) => version + 1);
      latestValue.current = edit.value;
      onChange(edit.value);
    }
    setEditorError('');
    selection.current = { start: edit.start, end: edit.end };
    setCaret(promptCaret(edit.value, edit.start));
    if (focus) restoreSelection(edit);
  };
  const travelHistory = (direction) => {
    const from = history.current[direction];
    const edit = from.pop();
    if (!edit) return;
    history.current[direction === 'undo' ? 'redo' : 'undo'].push({
      value: latestValue.current, ...selection.current,
    });
    latestValue.current = edit.value;
    onChange(edit.value);
    refreshHistory((version) => version + 1);
    restoreSelection(edit);
  };
  const sourceSelection = () => {
    if (textareaRef.current) {
      selection.current = {
        start: textareaRef.current.selectionStart, end: textareaRef.current.selectionEnd,
      };
    }
    return selection.current;
  };
  const insert = (text, selectFrom, selectTo) => {
    const { start, end } = sourceSelection();
    const source = textareaRef.current?.value ?? latestValue.current;
    changeSource(replacePromptSelection(source, start, end, text, selectFrom, selectTo));
  };
  const format = (kind) => {
    const { start, end } = sourceSelection();
    const source = textareaRef.current?.value ?? latestValue.current;
    const selected = source.slice(start, end);
    if (kind === 'bold' || kind === 'italic') {
      const marker = kind === 'bold' ? '**' : '*';
      const text = selected || 'text';
      insert(`${marker}${text}${marker}`, marker.length, marker.length + text.length);
    } else if (kind === 'heading') {
      const text = selected || 'Heading';
      const prefix = start && source[start - 1] !== '\n' ? '\n## ' : '## ';
      insert(`${prefix}${text}\n`, prefix.length, prefix.length + text.length);
    } else if (kind === 'list') {
      const text = (selected || 'Item').split('\n').map((line) => `- ${line}`).join('\n');
      const prefix = start && source[start - 1] !== '\n' ? '\n' : '';
      insert(`${prefix}${text}\n`);
    } else {
      insert(`\n\`\`\`\n${selected || 'code'}\n\`\`\`\n`);
    }
  };
  const showPreview = () => {
    setSideView('preview');
    setMobileView('preview');
    preview.refresh();
  };
  const filteredVariables = useMemo(() => {
    const terms = query.toLowerCase().trim().split(/\s+/).filter(Boolean);
    return (preview.data?.variables || []).filter((variable) => {
      const text = `${variable.path} ${variable.source} ${variable.type}`.toLowerCase();
      return terms.every((term) => text.includes(term));
    });
  }, [preview.data?.variables, query]);
  const visibleSide = desktop ? sideView : mobileView;

  return (
    <ThemeProvider theme={theme}>
      <Dialog open={open} onClose={onClose} aria-labelledby={titleId} maxWidth="xl" fullWidth
        slotProps={{ paper: { sx: {
          ...authoringSurfaceSx, m: { xs: 1, sm: 3 }, borderRadius: 3,
          width: { xs: 'calc(100% - 16px)', sm: 'calc(100% - 48px)' },
          height: 'min(940px, calc(100dvh - 32px))', maxHeight: 'calc(100dvh - 16px)',
        } } }}>
        <DialogTitle component="div" id={`${titleId}-header`} sx={{ px: { xs: 2, sm: 3 }, py: 2 }}>
          <Stack direction="row" alignItems="flex-start" gap={1.5}>
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Typography component="h2" variant="h6" id={titleId} fontWeight={650}>Prompt editor</Typography>
              <Typography variant="body2" color="text.secondary">
                {agentName} / {mode === 'voicelive' ? 'VoiceLive' : 'Custom Speech'}
                {scenario?.name ? ` / ${scenario.name}` : ' / Session context'}
              </Typography>
            </Box>
            <IconButton aria-label="Close prompt editor" onClick={onClose}><CloseIcon fontSize="small" /></IconButton>
          </Stack>
        </DialogTitle>
        <Stack direction="row" alignItems="center" gap={0.5} flexWrap="wrap"
          sx={{ px: 1.5, py: 0.75, borderTop: 1, borderColor: 'divider', bgcolor: 'action.hover' }}>
          <Tooltip title="Undo (Ctrl/Cmd+Z)">
            <span><IconButton size="small" aria-label="Undo prompt edit" disabled={disabled || !history.current.undo.length}
              onClick={() => travelHistory('undo')}><UndoIcon fontSize="small" /></IconButton></span>
          </Tooltip>
          <Tooltip title="Redo (Ctrl/Cmd+Shift+Z)">
            <span><IconButton size="small" aria-label="Redo prompt edit" disabled={disabled || !history.current.redo.length}
              onClick={() => travelHistory('redo')}><RedoIcon fontSize="small" /></IconButton></span>
          </Tooltip>
          <Divider orientation="vertical" flexItem sx={{ mx: 0.5 }} />
          {[
            ['heading', 'Heading', TitleIcon], ['bold', 'Bold', FormatBoldIcon],
            ['italic', 'Italic', FormatItalicIcon], ['list', 'Bulleted list', FormatListBulletedIcon],
            ['code', 'Code block', CodeIcon],
          ].map(([kind, label, Icon]) => (
            <Tooltip title={label} key={kind}>
              <span><IconButton size="small" aria-label={label} onClick={() => format(kind)} disabled={disabled}>
                <Icon fontSize="small" />
              </IconButton></span>
            </Tooltip>
          ))}
          <Button size="small" startIcon={<VisibilityOutlinedIcon />} disabled={preview.loading}
            onClick={showPreview} sx={{ ml: 'auto' }}>Preview prompt</Button>
        </Stack>
        {!desktop && (
          <Tabs value={mobileView} onChange={(_, next) => setMobileView(next)} variant="fullWidth" aria-label="Prompt editor views"
            sx={{ '& .MuiTab-root': { textTransform: 'none', minWidth: 0 } }}>
            <Tab label="Source" value="source" />
            <Tab label="Context" value="context" />
            <Tab label="Preview" value="preview" />
          </Tabs>
        )}
        {preview.loading && <LinearProgress />}
        <DialogContent dividers sx={{ p: 0, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          {(contextNotice || editorError || saveError || saveNotice) && (
            <Stack spacing={1} sx={{ px: 2, py: 1, maxHeight: '25%', overflowY: 'auto', flexShrink: 0 }}>
              {contextNotice && <Alert severity="info">{contextNotice}</Alert>}
              {editorError && <Alert severity="warning">{editorError}</Alert>}
              {saveError && <Alert severity="error">{saveError}</Alert>}
              {saveNotice && !saveError && <Alert severity="success">{saveNotice}</Alert>}
            </Stack>
          )}
          <Box sx={{ display: 'flex', flex: 1, minHeight: 0 }}>
            <Box component="section" aria-label="Prompt source editor" sx={{
              flex: 1, minWidth: 0, minHeight: 0, flexDirection: 'column',
              display: desktop || mobileView === 'source' ? 'flex' : 'none',
            }}>
              <Typography component="label" htmlFor={sourceId} variant="caption" color="text.secondary"
                sx={{ px: 2, py: 1, borderBottom: 1, borderColor: 'divider' }}>Markdown / Jinja source</Typography>
              <Box component="textarea" id={sourceId} ref={textareaRef} aria-label="Prompt source"
                value={value} readOnly={disabled} spellCheck={false} autoFocus maxLength={SOURCE_LIMIT}
                onSelect={rememberSelection} onBeforeInput={rememberSelection}
                onChange={(event) => changeSource({
                  value: event.target.value, start: event.target.selectionStart, end: event.target.selectionEnd,
                }, false)}
                onKeyDown={(event) => {
                  if (disabled || !(event.ctrlKey || event.metaKey)) return;
                  const key = event.key.toLowerCase();
                  if (key === 'z' || key === 'y') {
                    event.preventDefault();
                    travelHistory(key === 'y' || event.shiftKey ? 'redo' : 'undo');
                  } else if (key === 'b' || key === 'i') {
                    event.preventDefault();
                    format(key === 'b' ? 'bold' : 'italic');
                  } else if (key === 'enter') {
                    event.preventDefault();
                    if (!preview.loading) showPreview();
                  }
                }}
                sx={{
                  flex: 1, width: '100%', minHeight: 0, boxSizing: 'border-box', resize: 'none',
                  border: 0, p: 2, bgcolor: 'background.paper', color: 'text.primary',
                  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
                  fontSize: 14, lineHeight: 1.7, tabSize: 2,
                  '&:focus-visible': { outline: '2px solid', outlineColor: 'primary.main', outlineOffset: -2 },
                }} />
              <Stack direction="row" justifyContent="space-between" gap={1} flexWrap="wrap"
                sx={{ px: 2, py: 0.75, borderTop: 1, borderColor: 'divider' }}>
                <Typography variant="caption" color="text.secondary">Line {caret.line}, column {caret.column}</Typography>
                <Typography variant="caption" color="text.secondary">{value.length.toLocaleString()} characters</Typography>
              </Stack>
            </Box>
            <Box component="section" aria-label="Prompt context and preview" sx={{
              display: desktop || mobileView !== 'source' ? 'flex' : 'none', flexDirection: 'column',
              width: desktop ? 380 : '100%', minWidth: 0, minHeight: 0, flexShrink: 0,
              borderLeft: desktop ? '1px solid' : 0, borderColor: 'divider',
            }}>
              {desktop && <Tabs value={sideView} onChange={(_, next) => setSideView(next)}
                variant="fullWidth" aria-label="Prompt support views" sx={{ '& .MuiTab-root': { textTransform: 'none' } }}>
                <Tab label="Context" value="context" />
                <Tab label="Preview" value="preview" />
              </Tabs>}
              <Box sx={{ flex: 1, minHeight: 0, overflowY: 'auto', p: 2, overscrollBehavior: 'contain' }}>
                {preview.error && <Alert severity="error" sx={{ mb: 2 }}
                  action={<Button size="small" onClick={preview.refresh} disabled={preview.loading}>Retry</Button>}>
                  {preview.error}
                </Alert>}
                {visibleSide === 'context' && (
                  <Stack spacing={1.5}>
                    <Stack direction="row" alignItems="center" gap={1}>
                      <TextField label="Find context" placeholder="Variable or source" size="small" value={query}
                        onChange={(event) => setQuery(event.target.value)} sx={{ flex: 1 }}
                        slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> } }} />
                      <Tooltip title="Refresh session context">
                        <span><IconButton aria-label="Refresh session context" disabled={preview.loading} onClick={preview.refresh}>
                          <RefreshIcon fontSize="small" />
                        </IconButton></span>
                      </Tooltip>
                    </Stack>
                    <Typography variant="caption" color="text.secondary">
                      Insert a Jinja reference at the cursor, not a copied value. Session values can change between conversations.
                    </Typography>
                    {preview.data?.warnings.map((warning, index) => <Alert key={index} severity="info">{warning}</Alert>)}
                    {!filteredVariables.length && !preview.loading && !preview.error && (
                      <Typography variant="body2" color="text.secondary">
                        {query ? 'No matching context variables.' : 'No context variables are available for this session yet.'}
                      </Typography>
                    )}
                    <Stack component="ul" spacing={0} sx={{ listStyle: 'none', p: 0, m: 0 }}>
                      {filteredVariables.map((variable) => (
                        <Box component="li" key={variable.path} sx={{ py: 1.5, borderBottom: 1, borderColor: 'divider' }}>
                          <Typography variant="body2" fontWeight={600}>{variable.path}</Typography>
                          <Typography variant="caption" color="text.secondary">
                            {variable.source} / {variable.type}
                          </Typography>
                          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, whiteSpace: 'pre-wrap' }}>
                            {variable.sensitive ? 'Hidden value' : variable.available ? variable.value_preview : 'Not available in this snapshot'}
                          </Typography>
                          <Button size="small" aria-label={`Insert ${variable.path}`} disabled={disabled || variable.sensitive}
                            onClick={() => insert(variable.available ? variable.expression
                              : variable.expression.replace(/\s*}}\s*$/, ' | default("") }}'))}
                            sx={{ mt: 0.5, px: 0 }}>
                            {variable.available ? 'Insert variable' : 'Insert with default'}
                          </Button>
                        </Box>
                      ))}
                    </Stack>
                  </Stack>
                )}
                {visibleSide === 'preview' && (
                  <Stack spacing={1.5}>
                    <Stack direction="row" justifyContent="space-between" gap={1} alignItems="center">
                      <Typography variant="subtitle2">Rendered text</Typography>
                      <Button size="small" disabled={preview.loading} onClick={preview.refresh}>Refresh preview</Button>
                    </Stack>
                    <Typography variant="caption" color="text.secondary">
                      A read-only context snapshot. The runtime may add scenario handoff instructions when connecting.
                    </Typography>
                    {preview.stale && <Alert severity="info">The prompt or context changed. Refresh to render the latest draft.</Alert>}
                    {!preview.stale && preview.data?.missing_variables.length > 0 && (
                      <Alert severity="warning">Missing context: {preview.data.missing_variables.join(', ')}.</Alert>
                    )}
                    {!preview.stale && preview.data?.errors.map((error, index) => (
                      <Alert key={index} severity="error">
                        {error.line ? `Line ${error.line}: ` : ''}{error.message}
                      </Alert>
                    ))}
                    {preview.data && !preview.error && !preview.stale && !preview.data.errors.length && preview.data.rendered_prompt !== null && (
                      <Box component="pre" data-testid="rendered-prompt" sx={{
                        m: 0, p: 1.5, bgcolor: 'action.hover', borderRadius: 1,
                        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
                        fontSize: 13, lineHeight: 1.6, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere',
                      }}>{preview.data?.rendered_prompt}</Box>
                    )}
                    {!preview.data && !preview.loading && !preview.error && <Typography variant="body2">Choose Preview prompt to render this draft.</Typography>}
                  </Stack>
                )}
              </Box>
            </Box>
          </Box>
        </DialogContent>
        <DialogActions disableSpacing sx={{ px: 2, py: 1.5, gap: 1, flexWrap: 'wrap' }}>
          <Typography variant="caption" color="text.secondary" sx={{ flex: 1, minWidth: 140 }}>
            {saveAction ? 'Changes stay in Quick Tune until saved.' : 'Changes stay in the scenario draft until Apply scenario.'}
          </Typography>
          <Button onClick={onClose} variant={saveAction ? 'text' : 'contained'}>Done editing</Button>
          {saveAction && <Button variant="contained" onClick={saveAction.onClick} disabled={saveAction.disabled || disabled}>
            {saveAction.label}
          </Button>}
        </DialogActions>
      </Dialog>
    </ThemeProvider>
  );
});

export default PromptEditorDialog;
