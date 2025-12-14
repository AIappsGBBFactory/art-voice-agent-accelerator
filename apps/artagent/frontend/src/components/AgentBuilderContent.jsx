/**
 * AgentBuilderContent Component
 * ==============================
 * 
 * The content portion of the AgentBuilder that can be embedded in 
 * the unified AgentScenarioBuilder dialog. This is a re-export that
 * wraps the original AgentBuilder to work in embedded mode.
 * 
 * For now, this imports and re-exports the original AgentBuilder
 * with a special prop to indicate embedded mode. The AgentBuilder
 * handles this by conditionally rendering without its Dialog wrapper.
 */

import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  AlertTitle,
  Autocomplete,
  Avatar,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  Chip,
  CircularProgress,
  Collapse,
  Divider,
  FormControlLabel,
  IconButton,
  InputAdornment,
  LinearProgress,
  List,
  ListItem,
  ListItemAvatar,
  ListItemIcon,
  ListItemText,
  Radio,
  Slider,
  Stack,
  Tab,
  Tabs,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
} from '@mui/material';
import SaveIcon from '@mui/icons-material/Save';
import RefreshIcon from '@mui/icons-material/Refresh';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import BuildIcon from '@mui/icons-material/Build';
import RecordVoiceOverIcon from '@mui/icons-material/RecordVoiceOver';
import TuneIcon from '@mui/icons-material/Tune';
import CodeIcon from '@mui/icons-material/Code';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import CheckIcon from '@mui/icons-material/Check';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import MemoryIcon from '@mui/icons-material/Memory';
import SwapHorizIcon from '@mui/icons-material/SwapHoriz';
import FolderOpenIcon from '@mui/icons-material/FolderOpen';
import StarIcon from '@mui/icons-material/Star';
import EditIcon from '@mui/icons-material/Edit';
import HearingIcon from '@mui/icons-material/Hearing';

import { API_BASE_URL } from '../config/constants.js';
import logger from '../utils/logger.js';

// ═══════════════════════════════════════════════════════════════════════════════
// STYLES
// ═══════════════════════════════════════════════════════════════════════════════

const styles = {
  tabs: {
    borderBottom: 1,
    borderColor: 'divider',
    backgroundColor: '#fafbfc',
    '& .MuiTab-root': {
      textTransform: 'none',
      fontWeight: 600,
      minHeight: 48,
    },
    '& .Mui-selected': {
      color: '#1e3a5f',
    },
  },
  tabPanel: {
    padding: '24px',
    minHeight: '400px',
    height: 'calc(100% - 48px)',
    overflowY: 'auto',
    backgroundColor: '#fff',
  },
  sectionCard: {
    borderRadius: '12px',
    border: '1px solid #e5e7eb',
    boxShadow: 'none',
    '&:hover': {
      borderColor: '#c7d2fe',
      boxShadow: '0 2px 8px rgba(99, 102, 241, 0.08)',
    },
  },
  promptEditor: {
    fontFamily: '"Fira Code", "Consolas", monospace',
    fontSize: '13px',
    lineHeight: 1.6,
    '& .MuiInputBase-root': {
      backgroundColor: '#1e1e2e',
      color: '#cdd6f4',
      borderRadius: '8px',
    },
  },
};

// ═══════════════════════════════════════════════════════════════════════════════
// TAB PANEL
// ═══════════════════════════════════════════════════════════════════════════════

function TabPanel({ children, value, index, ...other }) {
  return (
    <div
      role="tabpanel"
      hidden={value !== index}
      id={`agent-builder-content-tabpanel-${index}`}
      {...other}
    >
      {value === index && <Box sx={styles.tabPanel}>{children}</Box>}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// DEFAULT PROMPT
// ═══════════════════════════════════════════════════════════════════════════════

const DEFAULT_PROMPT = `You are {{ agent_name | default('Assistant') }}, a helpful AI assistant for {{ institution_name | default('our organization') }}.

## Your Role
Assist users with their inquiries in a friendly, professional manner.
{% if caller_name %}
The caller's name is {{ caller_name }}.
{% endif %}

## Guidelines
- Be concise and helpful in your responses
- Ask clarifying questions when the request is ambiguous
- Use the available tools when appropriate to help the user
- If you cannot help with something, acknowledge it honestly

## Available Tools
You have access to the following tools:
{% for tool in tools %}
- {{ tool }}
{% endfor %}
`;

// ═══════════════════════════════════════════════════════════════════════════════
// MAIN COMPONENT
// ═══════════════════════════════════════════════════════════════════════════════

export default function AgentBuilderContent({
  sessionId,
  sessionProfile = null,
  onAgentCreated,
  onAgentUpdated,
  existingConfig = null,
  editMode = false,
}) {
  // Tab state
  const [activeTab, setActiveTab] = useState(0);
  const [isEditMode, setIsEditMode] = useState(editMode);
  
  // Loading states
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  
  // Available options from backend
  const [availableTools, setAvailableTools] = useState([]);
  const [availableVoices, setAvailableVoices] = useState([]);
  const [availableTemplates, setAvailableTemplates] = useState([]);
  
  // Agent configuration state
  const [config, setConfig] = useState({
    name: 'Custom Agent',
    description: '',
    greeting: '',
    return_greeting: '',
    prompt: DEFAULT_PROMPT,
    tools: [],
    cascade_model: {
      deployment_id: 'gpt-4o',
      temperature: 0.7,
      top_p: 0.9,
      max_tokens: 4096,
    },
    voicelive_model: {
      deployment_id: 'gpt-4o-realtime-preview',
      temperature: 0.7,
      top_p: 0.9,
      max_tokens: 4096,
    },
    voice: {
      name: 'en-US-AvaMultilingualNeural',
      type: 'azure-standard',
      style: 'chat',
      rate: '+0%',
    },
    speech: {
      vad_silence_timeout_ms: 800,
      use_semantic_segmentation: false,
      candidate_languages: ['en-US'],
    },
    template_vars: {
      institution_name: 'Contoso Financial',
      agent_name: 'Assistant',
    },
  });

  // Tool categories
  const [expandedCategories, setExpandedCategories] = useState({});
  const [toolFilter, setToolFilter] = useState('all');

  // ─────────────────────────────────────────────────────────────────────────
  // DATA FETCHING
  // ─────────────────────────────────────────────────────────────────────────

  const fetchAvailableTools = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/agent-builder/tools`);
      if (response.ok) {
        const data = await response.json();
        setAvailableTools(data.tools || []);
      }
    } catch (err) {
      logger.error('Failed to fetch tools:', err);
    }
  }, []);

  const fetchAvailableVoices = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/agent-builder/voices`);
      if (response.ok) {
        const data = await response.json();
        setAvailableVoices(data.voices || []);
      }
    } catch (err) {
      logger.error('Failed to fetch voices:', err);
    }
  }, []);

  const fetchAvailableTemplates = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/agent-builder/templates`);
      if (response.ok) {
        const data = await response.json();
        setAvailableTemplates(data.templates || []);
      }
    } catch (err) {
      logger.error('Failed to fetch templates:', err);
    }
  }, []);

  const fetchExistingConfig = useCallback(async () => {
    if (!sessionId || !editMode) return;
    try {
      const response = await fetch(
        `${API_BASE_URL}/api/v1/agent-builder/session/${sessionId}`
      );
      if (response.ok) {
        const data = await response.json();
        if (data.config) {
          setConfig((prev) => ({
            ...prev,
            name: data.config.name || prev.name,
            description: data.config.description || '',
            greeting: data.config.greeting || '',
            return_greeting: data.config.return_greeting || '',
            prompt: data.config.prompt_full || data.config.prompt || prev.prompt,
            tools: data.config.tools || [],
            voice: data.config.voice || prev.voice,
          }));
          setIsEditMode(true);
        }
      }
    } catch (err) {
      logger.debug('No existing config for session');
    }
  }, [sessionId, editMode]);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      fetchAvailableTools(),
      fetchAvailableVoices(),
      fetchAvailableTemplates(),
      fetchExistingConfig(),
    ]).finally(() => setLoading(false));
  }, [fetchAvailableTools, fetchAvailableVoices, fetchAvailableTemplates, fetchExistingConfig]);

  // Apply existing config
  useEffect(() => {
    if (existingConfig) {
      setConfig((prev) => ({
        ...prev,
        ...existingConfig,
      }));
    }
  }, [existingConfig]);

  // ─────────────────────────────────────────────────────────────────────────
  // COMPUTED
  // ─────────────────────────────────────────────────────────────────────────

  const toolsByCategory = useMemo(() => {
    const grouped = {};
    availableTools.forEach((tool) => {
      const category = tool.is_handoff ? 'Handoffs' : (tool.tags?.[0] || 'General');
      if (!grouped[category]) grouped[category] = [];
      grouped[category].push(tool);
    });
    return grouped;
  }, [availableTools]);

  const filteredTools = useMemo(() => {
    if (toolFilter === 'all') return availableTools;
    if (toolFilter === 'handoff') return availableTools.filter((t) => t.is_handoff);
    return availableTools.filter((t) => !t.is_handoff);
  }, [availableTools, toolFilter]);

  // ─────────────────────────────────────────────────────────────────────────
  // HANDLERS
  // ─────────────────────────────────────────────────────────────────────────

  const handleConfigChange = useCallback((field, value) => {
    setConfig((prev) => ({ ...prev, [field]: value }));
  }, []);

  const handleNestedConfigChange = useCallback((parent, field, value) => {
    setConfig((prev) => ({
      ...prev,
      [parent]: { ...prev[parent], [field]: value },
    }));
  }, []);

  const handleToolToggle = useCallback((toolName) => {
    setConfig((prev) => ({
      ...prev,
      tools: prev.tools.includes(toolName)
        ? prev.tools.filter((t) => t !== toolName)
        : [...prev.tools, toolName],
    }));
  }, []);

  const handleApplyTemplate = useCallback(async (templateId) => {
    setLoading(true);
    try {
      const response = await fetch(
        `${API_BASE_URL}/api/v1/agent-builder/templates/${templateId}`
      );
      if (response.ok) {
        const data = await response.json();
        const template = data.template;
        setConfig((prev) => ({
          ...prev,
          name: template.name || prev.name,
          description: template.description || '',
          greeting: template.greeting || '',
          return_greeting: template.return_greeting || '',
          prompt: template.prompt_full || template.prompt || DEFAULT_PROMPT,
          tools: template.tools || [],
          voice: template.voice || prev.voice,
        }));
        setSuccess(`Applied template: ${template.name}`);
        setTimeout(() => setSuccess(null), 3000);
      }
    } catch (err) {
      setError('Failed to apply template');
    } finally {
      setLoading(false);
    }
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setError(null);

    try {
      const payload = {
        name: config.name,
        description: config.description,
        greeting: config.greeting,
        return_greeting: config.return_greeting,
        prompt: config.prompt,
        tools: config.tools,
        cascade_model: config.cascade_model,
        voicelive_model: config.voicelive_model,
        voice: config.voice,
        speech: config.speech,
        template_vars: config.template_vars,
      };

      const url = isEditMode
        ? `${API_BASE_URL}/api/v1/agent-builder/session/${encodeURIComponent(sessionId)}`
        : `${API_BASE_URL}/api/v1/agent-builder/create?session_id=${encodeURIComponent(sessionId)}`;
      const method = isEditMode ? 'PUT' : 'POST';

      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || 'Failed to save agent');
      }

      const data = await res.json();
      setSuccess(`Agent "${config.name}" ${isEditMode ? 'updated' : 'created'} successfully!`);

      if (!isEditMode) {
        setIsEditMode(true);
      }

      const agentConfig = { ...config, session_id: sessionId, agent_id: data.agent_id };

      if (isEditMode && onAgentUpdated) {
        onAgentUpdated(agentConfig);
      } else if (onAgentCreated) {
        onAgentCreated(agentConfig);
      }
    } catch (err) {
      setError(err.message);
      logger.error('Error saving agent:', err);
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/agent-builder/defaults`);
      const { defaults } = await res.json();
      setConfig({
        name: 'Custom Agent',
        description: '',
        greeting: '',
        return_greeting: '',
        prompt: DEFAULT_PROMPT,
        tools: [],
        cascade_model: defaults?.model || config.cascade_model,
        voicelive_model: config.voicelive_model,
        voice: defaults?.voice || config.voice,
        speech: config.speech,
        template_vars: defaults?.template_vars || config.template_vars,
      });
      setSuccess('Reset to defaults');
    } catch {
      setError('Failed to reset');
    }
  };

  // ─────────────────────────────────────────────────────────────────────────
  // RENDER
  // ─────────────────────────────────────────────────────────────────────────

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Loading */}
      {loading && <LinearProgress />}

      {/* Alerts */}
      <Collapse in={!!error || !!success}>
        <Box sx={{ px: 2, pt: 2 }}>
          {error && (
            <Alert severity="error" onClose={() => setError(null)} sx={{ borderRadius: '12px' }}>
              {error}
            </Alert>
          )}
          {success && (
            <Alert severity="success" onClose={() => setSuccess(null)} sx={{ borderRadius: '12px' }}>
              {success}
            </Alert>
          )}
        </Box>
      </Collapse>

      {/* Edit mode banner */}
      {isEditMode && (
        <Alert
          severity="info"
          icon={<EditIcon />}
          sx={{
            mx: 3,
            mt: 2,
            borderRadius: '12px',
            backgroundColor: '#fef3c7',
            color: '#92400e',
          }}
        >
          <Typography variant="body2">
            <strong>Edit Mode:</strong> Updating existing agent for this session.
          </Typography>
        </Alert>
      )}

      {/* Tabs */}
      <Tabs
        value={activeTab}
        onChange={(e, v) => setActiveTab(v)}
        sx={styles.tabs}
        variant="fullWidth"
      >
        <Tab icon={<SmartToyIcon />} label="Identity" iconPosition="start" />
        <Tab icon={<CodeIcon />} label="Prompt" iconPosition="start" />
        <Tab icon={<BuildIcon />} label="Tools" iconPosition="start" />
        <Tab icon={<RecordVoiceOverIcon />} label="Voice" iconPosition="start" />
        <Tab icon={<TuneIcon />} label="Model" iconPosition="start" />
      </Tabs>

      {/* Content */}
      <Box sx={{ flex: 1, overflow: 'auto' }}>
        {loading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: 300 }}>
            <CircularProgress />
          </Box>
        ) : (
          <>
            {/* TAB 0: IDENTITY */}
            <TabPanel value={activeTab} index={0}>
              <Stack spacing={3}>
                <Card variant="outlined" sx={styles.sectionCard}>
                  <CardContent>
                    <Typography variant="subtitle2" color="primary" sx={{ mb: 2, fontWeight: 600 }}>
                      🤖 Agent Identity
                    </Typography>
                    <Stack spacing={2}>
                      <TextField
                        label="Agent Name"
                        value={config.name}
                        onChange={(e) => handleConfigChange('name', e.target.value)}
                        fullWidth
                        required
                      />
                      <TextField
                        label="Description"
                        value={config.description}
                        onChange={(e) => handleConfigChange('description', e.target.value)}
                        fullWidth
                        multiline
                        rows={2}
                      />
                      <TextField
                        label="Greeting"
                        value={config.greeting}
                        onChange={(e) => handleConfigChange('greeting', e.target.value)}
                        fullWidth
                        multiline
                        rows={2}
                        helperText="Initial greeting when agent starts"
                      />
                      <TextField
                        label="Return Greeting"
                        value={config.return_greeting}
                        onChange={(e) => handleConfigChange('return_greeting', e.target.value)}
                        fullWidth
                        multiline
                        rows={2}
                        helperText="Greeting when caller returns to this agent"
                      />
                    </Stack>
                  </CardContent>
                </Card>

                {/* Templates */}
                <Card variant="outlined" sx={styles.sectionCard}>
                  <CardContent>
                    <Typography variant="subtitle2" color="primary" sx={{ mb: 2, fontWeight: 600 }}>
                      <FolderOpenIcon fontSize="small" sx={{ mr: 1, verticalAlign: 'middle' }} />
                      Start from Template
                    </Typography>
                    <Stack direction="row" flexWrap="wrap" gap={1}>
                      {availableTemplates.map((t) => (
                        <Chip
                          key={t.id}
                          label={t.name}
                          onClick={() => handleApplyTemplate(t.id)}
                          sx={{ cursor: 'pointer' }}
                        />
                      ))}
                      {availableTemplates.length === 0 && (
                        <Typography variant="body2" color="text.secondary">
                          No templates available
                        </Typography>
                      )}
                    </Stack>
                  </CardContent>
                </Card>
              </Stack>
            </TabPanel>

            {/* TAB 1: PROMPT */}
            <TabPanel value={activeTab} index={1}>
              <Card variant="outlined" sx={styles.sectionCard}>
                <CardContent>
                  <Typography variant="subtitle2" color="primary" sx={{ mb: 2, fontWeight: 600 }}>
                    📝 System Prompt
                  </Typography>
                  <TextField
                    value={config.prompt}
                    onChange={(e) => handleConfigChange('prompt', e.target.value)}
                    fullWidth
                    multiline
                    rows={20}
                    sx={styles.promptEditor}
                  />
                </CardContent>
              </Card>
            </TabPanel>

            {/* TAB 2: TOOLS */}
            <TabPanel value={activeTab} index={2}>
              <Stack spacing={2}>
                <Stack direction="row" justifyContent="space-between" alignItems="center">
                  <Typography variant="subtitle2" color="primary" sx={{ fontWeight: 600 }}>
                    🛠️ Available Tools ({config.tools.length} selected)
                  </Typography>
                  <ToggleButtonGroup
                    value={toolFilter}
                    exclusive
                    onChange={(e, v) => v && setToolFilter(v)}
                    size="small"
                  >
                    <ToggleButton value="all">All</ToggleButton>
                    <ToggleButton value="normal">Tools</ToggleButton>
                    <ToggleButton value="handoff">Handoffs</ToggleButton>
                  </ToggleButtonGroup>
                </Stack>

                {Object.entries(toolsByCategory).map(([category, tools]) => (
                  <Accordion key={category} defaultExpanded>
                    <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                      <Typography variant="subtitle2">{category}</Typography>
                      <Chip
                        size="small"
                        label={`${tools.filter((t) => config.tools.includes(t.name)).length}/${tools.length}`}
                        sx={{ ml: 2 }}
                      />
                    </AccordionSummary>
                    <AccordionDetails>
                      <Stack spacing={1}>
                        {tools.map((tool) => (
                          <FormControlLabel
                            key={tool.name}
                            control={
                              <Checkbox
                                checked={config.tools.includes(tool.name)}
                                onChange={() => handleToolToggle(tool.name)}
                              />
                            }
                            label={
                              <Stack direction="row" alignItems="center" spacing={1}>
                                <Typography variant="body2">{tool.name}</Typography>
                                {tool.is_handoff && (
                                  <Chip label="handoff" size="small" color="secondary" sx={{ height: 18, fontSize: 10 }} />
                                )}
                              </Stack>
                            }
                          />
                        ))}
                      </Stack>
                    </AccordionDetails>
                  </Accordion>
                ))}
              </Stack>
            </TabPanel>

            {/* TAB 3: VOICE */}
            <TabPanel value={activeTab} index={3}>
              <Card variant="outlined" sx={styles.sectionCard}>
                <CardContent>
                  <Typography variant="subtitle2" color="primary" sx={{ mb: 2, fontWeight: 600 }}>
                    🎙️ Voice Settings
                  </Typography>
                  <Stack spacing={2}>
                    <Autocomplete
                      options={availableVoices}
                      getOptionLabel={(opt) => opt.display_name || opt.name}
                      value={availableVoices.find((v) => v.name === config.voice?.name) || null}
                      onChange={(e, v) => v && handleNestedConfigChange('voice', 'name', v.name)}
                      renderInput={(params) => <TextField {...params} label="Voice" />}
                    />
                    <TextField
                      label="Speaking Rate"
                      value={config.voice?.rate || '+0%'}
                      onChange={(e) => handleNestedConfigChange('voice', 'rate', e.target.value)}
                      helperText="e.g., +10%, -5%, +0%"
                    />
                  </Stack>
                </CardContent>
              </Card>
            </TabPanel>

            {/* TAB 4: MODEL */}
            <TabPanel value={activeTab} index={4}>
              <Stack spacing={3}>
                <Card variant="outlined" sx={styles.sectionCard}>
                  <CardContent>
                    <Typography variant="subtitle2" color="primary" sx={{ mb: 2, fontWeight: 600 }}>
                      ⚡ Cascade Mode Model (STT → LLM → TTS)
                    </Typography>
                    <TextField
                      label="Deployment ID"
                      value={config.cascade_model?.deployment_id || 'gpt-4o'}
                      onChange={(e) => handleNestedConfigChange('cascade_model', 'deployment_id', e.target.value)}
                      fullWidth
                      helperText="Azure OpenAI deployment name"
                    />
                    <Stack direction="row" spacing={2} sx={{ mt: 2 }}>
                      <TextField
                        label="Temperature"
                        type="number"
                        value={config.cascade_model?.temperature ?? 0.7}
                        onChange={(e) => handleNestedConfigChange('cascade_model', 'temperature', parseFloat(e.target.value))}
                        inputProps={{ min: 0, max: 2, step: 0.1 }}
                        size="small"
                      />
                      <TextField
                        label="Max Tokens"
                        type="number"
                        value={config.cascade_model?.max_tokens ?? 4096}
                        onChange={(e) => handleNestedConfigChange('cascade_model', 'max_tokens', parseInt(e.target.value))}
                        size="small"
                      />
                    </Stack>
                  </CardContent>
                </Card>

                <Card variant="outlined" sx={styles.sectionCard}>
                  <CardContent>
                    <Typography variant="subtitle2" color="primary" sx={{ mb: 2, fontWeight: 600 }}>
                      🎤 VoiceLive Mode Model (Realtime API)
                    </Typography>
                    <TextField
                      label="Deployment ID"
                      value={config.voicelive_model?.deployment_id || 'gpt-4o-realtime-preview'}
                      onChange={(e) => handleNestedConfigChange('voicelive_model', 'deployment_id', e.target.value)}
                      fullWidth
                      helperText="Azure OpenAI realtime deployment name"
                    />
                    <Stack direction="row" spacing={2} sx={{ mt: 2 }}>
                      <TextField
                        label="Temperature"
                        type="number"
                        value={config.voicelive_model?.temperature ?? 0.7}
                        onChange={(e) => handleNestedConfigChange('voicelive_model', 'temperature', parseFloat(e.target.value))}
                        inputProps={{ min: 0, max: 2, step: 0.1 }}
                        size="small"
                      />
                      <TextField
                        label="Max Tokens"
                        type="number"
                        value={config.voicelive_model?.max_tokens ?? 4096}
                        onChange={(e) => handleNestedConfigChange('voicelive_model', 'max_tokens', parseInt(e.target.value))}
                        size="small"
                      />
                    </Stack>
                  </CardContent>
                </Card>
              </Stack>
            </TabPanel>
          </>
        )}
      </Box>

      {/* Footer */}
      <Divider />
      <Box sx={{ p: 2, backgroundColor: '#fafbfc', display: 'flex', gap: 2, justifyContent: 'flex-end' }}>
        <Button onClick={handleReset} startIcon={<RefreshIcon />} disabled={saving}>
          Reset
        </Button>
        <Button
          variant="contained"
          onClick={handleSave}
          startIcon={saving ? <CircularProgress size={18} color="inherit" /> : <SaveIcon />}
          disabled={saving || !config.name.trim() || config.prompt.length < 10}
          sx={{
            background: isEditMode
              ? 'linear-gradient(135deg, #f59e0b 0%, #fbbf24 100%)'
              : 'linear-gradient(135deg, #4f46e5 0%, #6366f1 100%)',
          }}
        >
          {saving
            ? isEditMode ? 'Updating...' : 'Creating...'
            : isEditMode ? 'Update Agent' : 'Create Agent'}
        </Button>
      </Box>
    </Box>
  );
}
