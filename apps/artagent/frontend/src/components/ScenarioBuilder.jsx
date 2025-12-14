/**
 * ScenarioBuilder Component
 * =========================
 * 
 * A visual scenario orchestration builder that allows users to:
 * - Drag and drop agents to build orchestration flows
 * - Configure handoff routing between agents (announced vs discrete)
 * - Set starting agents and agent overrides
 * - Create and update scenarios at runtime
 * 
 * The scenario defines the agent graph - which agents are available
 * and how they can hand off to each other.
 */

import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  Alert,
  AlertTitle,
  Avatar,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Collapse,
  Dialog,
  DialogActions,
  DialogContent,
  Divider,
  FormControl,
  FormControlLabel,
  IconButton,
  InputLabel,
  LinearProgress,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  MenuItem,
  Paper,
  Radio,
  RadioGroup,
  Select,
  Stack,
  Switch,
  Tab,
  Tabs,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import ArrowForwardIcon from '@mui/icons-material/ArrowForward';
import CheckIcon from '@mui/icons-material/Check';
import CloseIcon from '@mui/icons-material/Close';
import DeleteIcon from '@mui/icons-material/Delete';
import DragIndicatorIcon from '@mui/icons-material/DragIndicator';
import EditIcon from '@mui/icons-material/Edit';
import FolderOpenIcon from '@mui/icons-material/FolderOpen';
import HubIcon from '@mui/icons-material/Hub';
import LinkIcon from '@mui/icons-material/Link';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import RefreshIcon from '@mui/icons-material/Refresh';
import SaveIcon from '@mui/icons-material/Save';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import StarIcon from '@mui/icons-material/Star';
import SwapHorizIcon from '@mui/icons-material/SwapHoriz';
import VolumeUpIcon from '@mui/icons-material/VolumeUp';
import VolumeOffIcon from '@mui/icons-material/VolumeOff';

import { API_BASE_URL } from '../config/constants.js';
import logger from '../utils/logger.js';

// ═══════════════════════════════════════════════════════════════════════════════
// STYLES
// ═══════════════════════════════════════════════════════════════════════════════

const styles = {
  canvas: {
    minHeight: 500,
    backgroundColor: '#f8fafc',
    borderRadius: '12px',
    border: '2px dashed #e2e8f0',
    position: 'relative',
    overflow: 'hidden',
  },
  agentCard: {
    width: 180,
    cursor: 'grab',
    userSelect: 'none',
    transition: 'all 0.2s ease',
    border: '2px solid #e5e7eb',
    borderRadius: '12px',
    backgroundColor: '#fff',
    '&:hover': {
      borderColor: '#6366f1',
      boxShadow: '0 4px 12px rgba(99, 102, 241, 0.15)',
      transform: 'translateY(-2px)',
    },
  },
  agentCardDragging: {
    opacity: 0.5,
    transform: 'rotate(2deg)',
  },
  agentCardSelected: {
    borderColor: '#6366f1',
    backgroundColor: '#f5f3ff',
    boxShadow: '0 0 0 3px rgba(99, 102, 241, 0.2)',
  },
  agentCardStarting: {
    borderColor: '#10b981',
    backgroundColor: '#ecfdf5',
  },
  dropZone: {
    minHeight: 400,
    padding: '24px',
    display: 'flex',
    flexWrap: 'wrap',
    gap: '16px',
    alignContent: 'flex-start',
  },
  handoffCard: {
    padding: '12px 16px',
    borderRadius: '10px',
    border: '1px solid #e5e7eb',
    backgroundColor: '#fff',
    marginBottom: '8px',
    transition: 'all 0.2s',
    '&:hover': {
      borderColor: '#c7d2fe',
      backgroundColor: '#fafafa',
    },
  },
  handoffArrow: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    color: '#6b7280',
    fontSize: '14px',
  },
  templateCard: {
    cursor: 'pointer',
    transition: 'all 0.2s',
    border: '2px solid transparent',
    '&:hover': {
      borderColor: '#6366f1',
      transform: 'translateY(-2px)',
    },
  },
  templateCardSelected: {
    borderColor: '#6366f1',
    backgroundColor: '#f5f3ff',
  },
  sidePanel: {
    width: 320,
    borderLeft: '1px solid #e5e7eb',
    backgroundColor: '#fafbfc',
    overflowY: 'auto',
  },
};

// ═══════════════════════════════════════════════════════════════════════════════
// DRAGGABLE AGENT CARD
// ═══════════════════════════════════════════════════════════════════════════════

function DraggableAgentCard({
  agent,
  isSelected,
  isStarting,
  isInScenario,
  onSelect,
  onDragStart,
  onDragEnd,
  onRemove,
  onSetStarting,
}) {
  const [isDragging, setIsDragging] = useState(false);

  const handleDragStart = (e) => {
    setIsDragging(true);
    e.dataTransfer.setData('agent', JSON.stringify(agent));
    e.dataTransfer.effectAllowed = 'move';
    if (onDragStart) onDragStart(agent);
  };

  const handleDragEnd = () => {
    setIsDragging(false);
    if (onDragEnd) onDragEnd();
  };

  return (
    <Card
      variant="outlined"
      draggable
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
      onClick={() => onSelect(agent)}
      sx={{
        ...styles.agentCard,
        ...(isDragging ? styles.agentCardDragging : {}),
        ...(isSelected ? styles.agentCardSelected : {}),
        ...(isStarting ? styles.agentCardStarting : {}),
        opacity: isInScenario ? 1 : 0.6,
      }}
    >
      <CardContent sx={{ p: '12px !important' }}>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
          <DragIndicatorIcon fontSize="small" sx={{ color: '#9ca3af', cursor: 'grab' }} />
          <Avatar
            sx={{
              width: 28,
              height: 28,
              bgcolor: isStarting ? '#10b981' : '#6366f1',
              fontSize: '14px',
            }}
          >
            {agent.name?.[0] || 'A'}
          </Avatar>
          <Typography
            variant="subtitle2"
            sx={{
              flex: 1,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {agent.name}
          </Typography>
        </Stack>

        {/* Status chips */}
        <Stack direction="row" flexWrap="wrap" gap={0.5} sx={{ mb: 1 }}>
          {isStarting && (
            <Chip
              icon={<PlayArrowIcon sx={{ fontSize: 14 }} />}
              label="Start"
              size="small"
              color="success"
              sx={{ height: 20, fontSize: 10 }}
            />
          )}
          {agent.tools?.length > 0 && (
            <Chip
              label={`${agent.tools.length} tools`}
              size="small"
              variant="outlined"
              sx={{ height: 20, fontSize: 10 }}
            />
          )}
        </Stack>

        {/* Actions */}
        {isInScenario && (
          <Stack direction="row" spacing={0.5} justifyContent="flex-end">
            {!isStarting && (
              <Tooltip title="Set as starting agent">
                <IconButton size="small" onClick={(e) => { e.stopPropagation(); onSetStarting(agent); }}>
                  <StarIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            )}
            <Tooltip title="Remove from scenario">
              <IconButton size="small" onClick={(e) => { e.stopPropagation(); onRemove(agent); }}>
                <DeleteIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </Stack>
        )}
      </CardContent>
    </Card>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// HANDOFF EDITOR
// ═══════════════════════════════════════════════════════════════════════════════

function HandoffEditor({ handoff, agents, onUpdate, onDelete }) {
  const [fromAgent, setFromAgent] = useState(handoff.from_agent);
  const [toAgent, setToAgent] = useState(handoff.to_agent);
  const [tool, setTool] = useState(handoff.tool);
  const [type, setType] = useState(handoff.type || 'announced');
  const [shareContext, setShareContext] = useState(handoff.share_context !== false);

  useEffect(() => {
    onUpdate({
      from_agent: fromAgent,
      to_agent: toAgent,
      tool: tool,
      type: type,
      share_context: shareContext,
    });
  }, [fromAgent, toAgent, tool, type, shareContext]);

  // Generate tool name from agents if not set
  useEffect(() => {
    if (!tool && toAgent) {
      const defaultTool = `handoff_${toAgent.toLowerCase().replace(/\s+/g, '_')}`;
      setTool(defaultTool);
    }
  }, [toAgent, tool]);

  return (
    <Paper elevation={0} sx={styles.handoffCard}>
      <Stack spacing={2}>
        {/* From → To header */}
        <Stack direction="row" alignItems="center" justifyContent="space-between">
          <Box sx={styles.handoffArrow}>
            <FormControl size="small" sx={{ minWidth: 140 }}>
              <InputLabel>From</InputLabel>
              <Select
                value={fromAgent}
                label="From"
                onChange={(e) => setFromAgent(e.target.value)}
              >
                {agents.map((a) => (
                  <MenuItem key={a.name} value={a.name}>
                    {a.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <ArrowForwardIcon fontSize="small" />
            <FormControl size="small" sx={{ minWidth: 140 }}>
              <InputLabel>To</InputLabel>
              <Select
                value={toAgent}
                label="To"
                onChange={(e) => setToAgent(e.target.value)}
              >
                {agents.filter((a) => a.name !== fromAgent).map((a) => (
                  <MenuItem key={a.name} value={a.name}>
                    {a.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </Box>
          <IconButton size="small" onClick={onDelete} sx={{ color: '#ef4444' }}>
            <DeleteIcon fontSize="small" />
          </IconButton>
        </Stack>

        {/* Tool name */}
        <TextField
          label="Handoff Tool Name"
          value={tool}
          onChange={(e) => setTool(e.target.value)}
          size="small"
          fullWidth
          helperText="Function name that triggers this handoff"
        />

        {/* Type toggle */}
        <Stack direction="row" alignItems="center" spacing={2}>
          <Typography variant="body2" color="text.secondary">
            Handoff Type:
          </Typography>
          <ToggleButtonGroup
            value={type}
            exclusive
            onChange={(e, v) => v && setType(v)}
            size="small"
          >
            <ToggleButton value="announced">
              <Tooltip title="Target agent greets/announces the transfer">
                <Stack direction="row" alignItems="center" spacing={0.5}>
                  <VolumeUpIcon fontSize="small" />
                  <span>Announced</span>
                </Stack>
              </Tooltip>
            </ToggleButton>
            <ToggleButton value="discrete">
              <Tooltip title="Silent handoff, agent continues naturally">
                <Stack direction="row" alignItems="center" spacing={0.5}>
                  <VolumeOffIcon fontSize="small" />
                  <span>Discrete</span>
                </Stack>
              </Tooltip>
            </ToggleButton>
          </ToggleButtonGroup>
        </Stack>

        {/* Share context */}
        <FormControlLabel
          control={
            <Switch
              checked={shareContext}
              onChange={(e) => setShareContext(e.target.checked)}
              size="small"
            />
          }
          label={
            <Typography variant="body2" color="text.secondary">
              Share conversation context
            </Typography>
          }
        />
      </Stack>
    </Paper>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// MAIN COMPONENT
// ═══════════════════════════════════════════════════════════════════════════════

export default function ScenarioBuilder({
  sessionId,
  onScenarioCreated,
  onScenarioUpdated,
  existingConfig = null,
  editMode = false,
}) {
  // State
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  // Available data from backend
  const [availableAgents, setAvailableAgents] = useState([]);
  const [availableTemplates, setAvailableTemplates] = useState([]);
  const [selectedTemplate, setSelectedTemplate] = useState(null);

  // Scenario configuration
  const [config, setConfig] = useState({
    name: 'Custom Scenario',
    description: '',
    agents: [],
    start_agent: null,
    handoff_type: 'announced',
    handoffs: [],
    global_template_vars: {
      company_name: 'ART Voice Agent',
      industry: 'general',
    },
    agent_defaults: null,
  });

  // UI state
  const [selectedAgent, setSelectedAgent] = useState(null);
  const [showHandoffEditor, setShowHandoffEditor] = useState(false);
  const [activeTab, setActiveTab] = useState(0); // 0=Canvas, 1=Handoffs, 2=Settings
  const canvasRef = useRef(null);

  // ─────────────────────────────────────────────────────────────────────────
  // DATA FETCHING
  // ─────────────────────────────────────────────────────────────────────────

  const fetchAvailableAgents = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/scenario-builder/agents`);
      if (response.ok) {
        const data = await response.json();
        setAvailableAgents(data.agents || []);
      }
    } catch (err) {
      logger.error('Failed to fetch agents:', err);
    }
  }, []);

  const fetchAvailableTemplates = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/scenario-builder/templates`);
      if (response.ok) {
        const data = await response.json();
        setAvailableTemplates(data.templates || []);
      }
    } catch (err) {
      logger.error('Failed to fetch scenario templates:', err);
    }
  }, []);

  const fetchExistingScenario = useCallback(async () => {
    if (!sessionId) return;
    try {
      const response = await fetch(
        `${API_BASE_URL}/api/v1/scenario-builder/session/${sessionId}`
      );
      if (response.ok) {
        const data = await response.json();
        if (data.config) {
          setConfig({
            name: data.config.name || 'Custom Scenario',
            description: data.config.description || '',
            agents: data.config.agents || [],
            start_agent: data.config.start_agent,
            handoff_type: data.config.handoff_type || 'announced',
            handoffs: data.config.handoffs || [],
            global_template_vars: data.config.global_template_vars || {},
            agent_defaults: data.config.agent_defaults,
          });
        }
      }
    } catch (err) {
      // No existing scenario - that's fine
      logger.debug('No existing scenario for session');
    }
  }, [sessionId]);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      fetchAvailableAgents(),
      fetchAvailableTemplates(),
      editMode ? fetchExistingScenario() : Promise.resolve(),
    ]).finally(() => setLoading(false));
  }, [fetchAvailableAgents, fetchAvailableTemplates, fetchExistingScenario, editMode]);

  // Apply existing config if provided
  useEffect(() => {
    if (existingConfig) {
      setConfig({
        name: existingConfig.name || 'Custom Scenario',
        description: existingConfig.description || '',
        agents: existingConfig.agents || [],
        start_agent: existingConfig.start_agent,
        handoff_type: existingConfig.handoff_type || 'announced',
        handoffs: existingConfig.handoffs || [],
        global_template_vars: existingConfig.global_template_vars || {},
        agent_defaults: existingConfig.agent_defaults,
      });
    }
  }, [existingConfig]);

  // ─────────────────────────────────────────────────────────────────────────
  // COMPUTED VALUES
  // ─────────────────────────────────────────────────────────────────────────

  // Agents currently in the scenario
  const scenarioAgents = useMemo(() => {
    if (config.agents.length === 0) {
      // Empty agents means "all agents"
      return availableAgents;
    }
    return availableAgents.filter((a) => config.agents.includes(a.name));
  }, [availableAgents, config.agents]);

  // Agents available to add (not in scenario yet)
  const availableToAdd = useMemo(() => {
    if (config.agents.length === 0) return []; // All agents already included
    return availableAgents.filter((a) => !config.agents.includes(a.name));
  }, [availableAgents, config.agents]);

  // ─────────────────────────────────────────────────────────────────────────
  // HANDLERS
  // ─────────────────────────────────────────────────────────────────────────

  const handleAgentDrop = useCallback((e) => {
    e.preventDefault();
    try {
      const agentData = JSON.parse(e.dataTransfer.getData('agent'));
      if (agentData && agentData.name) {
        setConfig((prev) => {
          // If we're using "all agents" mode (empty array), switch to explicit mode
          if (prev.agents.length === 0) {
            const allNames = availableAgents.map((a) => a.name);
            return { ...prev, agents: allNames };
          }
          // Otherwise add if not already present
          if (!prev.agents.includes(agentData.name)) {
            return { ...prev, agents: [...prev.agents, agentData.name] };
          }
          return prev;
        });
      }
    } catch (err) {
      logger.error('Failed to handle agent drop:', err);
    }
  }, [availableAgents]);

  const handleRemoveAgent = useCallback((agent) => {
    setConfig((prev) => {
      const newAgents = prev.agents.filter((a) => a !== agent.name);
      // Also remove any handoffs involving this agent
      const newHandoffs = prev.handoffs.filter(
        (h) => h.from_agent !== agent.name && h.to_agent !== agent.name
      );
      // Clear start_agent if it was this agent
      const newStartAgent = prev.start_agent === agent.name ? null : prev.start_agent;
      return {
        ...prev,
        agents: newAgents,
        handoffs: newHandoffs,
        start_agent: newStartAgent,
      };
    });
    if (selectedAgent?.name === agent.name) {
      setSelectedAgent(null);
    }
  }, [selectedAgent]);

  const handleSetStartingAgent = useCallback((agent) => {
    setConfig((prev) => ({ ...prev, start_agent: agent.name }));
  }, []);

  const handleAddHandoff = useCallback(() => {
    const defaultFrom = scenarioAgents[0]?.name || '';
    const defaultTo = scenarioAgents[1]?.name || scenarioAgents[0]?.name || '';
    setConfig((prev) => ({
      ...prev,
      handoffs: [
        ...prev.handoffs,
        {
          from_agent: defaultFrom,
          to_agent: defaultTo,
          tool: `handoff_${defaultTo.toLowerCase().replace(/\s+/g, '_')}`,
          type: prev.handoff_type || 'announced',
          share_context: true,
        },
      ],
    }));
  }, [scenarioAgents]);

  const handleUpdateHandoff = useCallback((index, updatedHandoff) => {
    setConfig((prev) => ({
      ...prev,
      handoffs: prev.handoffs.map((h, i) => (i === index ? updatedHandoff : h)),
    }));
  }, []);

  const handleDeleteHandoff = useCallback((index) => {
    setConfig((prev) => ({
      ...prev,
      handoffs: prev.handoffs.filter((_, i) => i !== index),
    }));
  }, []);

  const handleApplyTemplate = useCallback(async (templateId) => {
    setLoading(true);
    try {
      const response = await fetch(
        `${API_BASE_URL}/api/v1/scenario-builder/templates/${templateId}`
      );
      if (response.ok) {
        const data = await response.json();
        const template = data.template;
        setConfig({
          name: template.name || 'Custom Scenario',
          description: template.description || '',
          agents: template.agents || [],
          start_agent: template.start_agent,
          handoff_type: template.handoff_type || 'announced',
          handoffs: template.handoffs || [],
          global_template_vars: template.global_template_vars || {},
          agent_defaults: template.agent_defaults,
        });
        setSelectedTemplate(templateId);
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
      const endpoint = editMode
        ? `${API_BASE_URL}/api/v1/scenario-builder/session/${sessionId}`
        : `${API_BASE_URL}/api/v1/scenario-builder/create?session_id=${sessionId}`;

      const method = editMode ? 'PUT' : 'POST';

      const payload = {
        name: config.name,
        description: config.description,
        agents: config.agents,
        start_agent: config.start_agent,
        handoff_type: config.handoff_type,
        handoffs: config.handoffs,
        global_template_vars: config.global_template_vars,
        agent_defaults: config.agent_defaults,
        tools: [],
      };

      const response = await fetch(endpoint, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to save scenario');
      }

      const data = await response.json();

      if (editMode && onScenarioUpdated) {
        onScenarioUpdated(data.config || config);
      } else if (onScenarioCreated) {
        onScenarioCreated(data.config || config);
      }

      setSuccess(editMode ? 'Scenario updated!' : 'Scenario created!');
      setTimeout(() => setSuccess(null), 3000);
    } catch (err) {
      logger.error('Failed to save scenario:', err);
      setError(err.message || 'Failed to save scenario');
    } finally {
      setSaving(false);
    }
  };

  const handleReset = () => {
    setConfig({
      name: 'Custom Scenario',
      description: '',
      agents: [],
      start_agent: null,
      handoff_type: 'announced',
      handoffs: [],
      global_template_vars: {
        company_name: 'ART Voice Agent',
        industry: 'general',
      },
      agent_defaults: null,
    });
    setSelectedTemplate(null);
    setSelectedAgent(null);
  };

  // ─────────────────────────────────────────────────────────────────────────
  // RENDER
  // ─────────────────────────────────────────────────────────────────────────

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Loading bar */}
      {loading && <LinearProgress />}

      {/* Alerts */}
      <Collapse in={!!error || !!success}>
        <Box sx={{ px: 2, pt: 2 }}>
          {error && (
            <Alert severity="error" onClose={() => setError(null)} sx={{ borderRadius: '12px' }}>
              <AlertTitle>Error</AlertTitle>
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

      {/* Tabs */}
      <Tabs
        value={activeTab}
        onChange={(e, v) => setActiveTab(v)}
        sx={{
          borderBottom: 1,
          borderColor: 'divider',
          backgroundColor: '#fafbfc',
          '& .MuiTab-root': { textTransform: 'none', fontWeight: 600 },
        }}
      >
        <Tab icon={<HubIcon />} label="Orchestration" iconPosition="start" />
        <Tab icon={<SwapHorizIcon />} label="Handoffs" iconPosition="start" />
        <Tab icon={<EditIcon />} label="Settings" iconPosition="start" />
      </Tabs>

      {/* Content */}
      <Box sx={{ flex: 1, overflow: 'auto', p: 3 }}>
        {loading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: 300 }}>
            <CircularProgress />
          </Box>
        ) : (
          <>
            {/* ════════════════════════════════════════════════════════════════ */}
            {/* TAB 0: ORCHESTRATION CANVAS */}
            {/* ════════════════════════════════════════════════════════════════ */}
            {activeTab === 0 && (
              <Stack spacing={3}>
                {/* Scenario name & description */}
                <Stack direction={{ xs: 'column', md: 'row' }} spacing={2}>
                  <TextField
                    label="Scenario Name"
                    value={config.name}
                    onChange={(e) => setConfig((prev) => ({ ...prev, name: e.target.value }))}
                    size="small"
                    fullWidth
                  />
                  <TextField
                    label="Description"
                    value={config.description}
                    onChange={(e) => setConfig((prev) => ({ ...prev, description: e.target.value }))}
                    size="small"
                    fullWidth
                  />
                </Stack>

                {/* Templates */}
                <Card variant="outlined" sx={{ borderRadius: '12px' }}>
                  <CardContent>
                    <Typography variant="subtitle2" color="primary" sx={{ mb: 2 }}>
                      <FolderOpenIcon fontSize="small" sx={{ mr: 1, verticalAlign: 'middle' }} />
                      Start from Template
                    </Typography>
                    <Stack direction="row" flexWrap="wrap" gap={1}>
                      {availableTemplates.map((template) => (
                        <Chip
                          key={template.id}
                          label={template.name}
                          icon={selectedTemplate === template.id ? <CheckIcon /> : undefined}
                          color={selectedTemplate === template.id ? 'primary' : 'default'}
                          variant={selectedTemplate === template.id ? 'filled' : 'outlined'}
                          onClick={() => handleApplyTemplate(template.id)}
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

                {/* Main canvas area */}
                <Stack direction="row" spacing={2}>
                  {/* Available agents (sidebar) */}
                  <Card variant="outlined" sx={{ width: 220, borderRadius: '12px' }}>
                    <CardContent>
                      <Typography variant="subtitle2" sx={{ mb: 2 }}>
                        <SmartToyIcon fontSize="small" sx={{ mr: 1, verticalAlign: 'middle' }} />
                        Available Agents
                      </Typography>
                      <Stack spacing={1}>
                        {availableAgents.map((agent) => (
                          <DraggableAgentCard
                            key={agent.name}
                            agent={agent}
                            isSelected={selectedAgent?.name === agent.name}
                            isStarting={config.start_agent === agent.name}
                            isInScenario={
                              config.agents.length === 0 || config.agents.includes(agent.name)
                            }
                            onSelect={setSelectedAgent}
                            onRemove={handleRemoveAgent}
                            onSetStarting={handleSetStartingAgent}
                          />
                        ))}
                        {availableAgents.length === 0 && (
                          <Typography variant="body2" color="text.secondary" sx={{ p: 2 }}>
                            No agents available
                          </Typography>
                        )}
                      </Stack>
                    </CardContent>
                  </Card>

                  {/* Drop zone / canvas */}
                  <Box
                    ref={canvasRef}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={handleAgentDrop}
                    sx={{ ...styles.canvas, flex: 1 }}
                  >
                    <Box sx={{ p: 2, borderBottom: '1px solid #e5e7eb', backgroundColor: '#fff' }}>
                      <Stack direction="row" justifyContent="space-between" alignItems="center">
                        <Typography variant="subtitle2">
                          Scenario Agents ({scenarioAgents.length})
                        </Typography>
                        <Stack direction="row" spacing={1}>
                          <Chip
                            label={config.agents.length === 0 ? 'All Agents' : 'Selected Agents'}
                            size="small"
                            color={config.agents.length === 0 ? 'primary' : 'default'}
                            variant="outlined"
                          />
                          {config.start_agent && (
                            <Chip
                              icon={<PlayArrowIcon sx={{ fontSize: 14 }} />}
                              label={`Start: ${config.start_agent}`}
                              size="small"
                              color="success"
                            />
                          )}
                        </Stack>
                      </Stack>
                    </Box>
                    <Box sx={styles.dropZone}>
                      {scenarioAgents.map((agent) => (
                        <DraggableAgentCard
                          key={agent.name}
                          agent={agent}
                          isSelected={selectedAgent?.name === agent.name}
                          isStarting={config.start_agent === agent.name}
                          isInScenario={true}
                          onSelect={setSelectedAgent}
                          onRemove={handleRemoveAgent}
                          onSetStarting={handleSetStartingAgent}
                        />
                      ))}
                      {scenarioAgents.length === 0 && (
                        <Box
                          sx={{
                            width: '100%',
                            height: 200,
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            flexDirection: 'column',
                            color: '#9ca3af',
                          }}
                        >
                          <SmartToyIcon sx={{ fontSize: 48, mb: 2, opacity: 0.5 }} />
                          <Typography>Drag agents here to add to scenario</Typography>
                        </Box>
                      )}
                    </Box>
                  </Box>
                </Stack>

                {/* Quick stats */}
                <Stack direction="row" spacing={2}>
                  <Chip
                    icon={<SmartToyIcon />}
                    label={`${scenarioAgents.length} agents`}
                    variant="outlined"
                  />
                  <Chip
                    icon={<SwapHorizIcon />}
                    label={`${config.handoffs.length} handoffs`}
                    variant="outlined"
                  />
                  <Chip
                    icon={config.handoff_type === 'announced' ? <VolumeUpIcon /> : <VolumeOffIcon />}
                    label={`Default: ${config.handoff_type}`}
                    variant="outlined"
                  />
                </Stack>
              </Stack>
            )}

            {/* ════════════════════════════════════════════════════════════════ */}
            {/* TAB 1: HANDOFFS */}
            {/* ════════════════════════════════════════════════════════════════ */}
            {activeTab === 1 && (
              <Stack spacing={3}>
                <Alert severity="info" sx={{ borderRadius: '12px' }}>
                  <AlertTitle>Handoff Configuration</AlertTitle>
                  Define how agents can transfer calls to each other. Each handoff is a directed edge
                  in the agent graph, specifying the trigger tool and behavior.
                </Alert>

                {/* Default handoff type */}
                <Card variant="outlined" sx={{ borderRadius: '12px' }}>
                  <CardContent>
                    <Typography variant="subtitle2" sx={{ mb: 2 }}>
                      Default Handoff Behavior
                    </Typography>
                    <ToggleButtonGroup
                      value={config.handoff_type}
                      exclusive
                      onChange={(e, v) => v && setConfig((prev) => ({ ...prev, handoff_type: v }))}
                      size="small"
                    >
                      <ToggleButton value="announced">
                        <VolumeUpIcon sx={{ mr: 1 }} />
                        Announced (greet on transfer)
                      </ToggleButton>
                      <ToggleButton value="discrete">
                        <VolumeOffIcon sx={{ mr: 1 }} />
                        Discrete (silent handoff)
                      </ToggleButton>
                    </ToggleButtonGroup>
                  </CardContent>
                </Card>

                {/* Handoffs list */}
                <Card variant="outlined" sx={{ borderRadius: '12px' }}>
                  <CardContent>
                    <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2 }}>
                      <Typography variant="subtitle2">
                        <LinkIcon fontSize="small" sx={{ mr: 1, verticalAlign: 'middle' }} />
                        Handoff Routes ({config.handoffs.length})
                      </Typography>
                      <Button
                        startIcon={<AddIcon />}
                        size="small"
                        onClick={handleAddHandoff}
                        disabled={scenarioAgents.length < 2}
                      >
                        Add Handoff
                      </Button>
                    </Stack>

                    {config.handoffs.length === 0 ? (
                      <Box
                        sx={{
                          p: 4,
                          textAlign: 'center',
                          color: '#9ca3af',
                          border: '2px dashed #e5e7eb',
                          borderRadius: '12px',
                        }}
                      >
                        <SwapHorizIcon sx={{ fontSize: 48, mb: 2, opacity: 0.5 }} />
                        <Typography>No handoffs configured</Typography>
                        <Typography variant="caption">
                          Add handoffs to define how agents can transfer to each other
                        </Typography>
                      </Box>
                    ) : (
                      <Stack spacing={2}>
                        {config.handoffs.map((handoff, index) => (
                          <HandoffEditor
                            key={index}
                            handoff={handoff}
                            agents={scenarioAgents}
                            onUpdate={(updated) => handleUpdateHandoff(index, updated)}
                            onDelete={() => handleDeleteHandoff(index)}
                          />
                        ))}
                      </Stack>
                    )}
                  </CardContent>
                </Card>
              </Stack>
            )}

            {/* ════════════════════════════════════════════════════════════════ */}
            {/* TAB 2: SETTINGS */}
            {/* ════════════════════════════════════════════════════════════════ */}
            {activeTab === 2 && (
              <Stack spacing={3}>
                {/* Global template variables */}
                <Card variant="outlined" sx={{ borderRadius: '12px' }}>
                  <CardContent>
                    <Typography variant="subtitle2" sx={{ mb: 2 }}>
                      Global Template Variables
                    </Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                      These variables are available to all agents in the scenario via Jinja templates.
                    </Typography>
                    <Stack spacing={2}>
                      <TextField
                        label="Company Name"
                        value={config.global_template_vars.company_name || ''}
                        onChange={(e) =>
                          setConfig((prev) => ({
                            ...prev,
                            global_template_vars: {
                              ...prev.global_template_vars,
                              company_name: e.target.value,
                            },
                          }))
                        }
                        size="small"
                        fullWidth
                      />
                      <TextField
                        label="Industry"
                        value={config.global_template_vars.industry || ''}
                        onChange={(e) =>
                          setConfig((prev) => ({
                            ...prev,
                            global_template_vars: {
                              ...prev.global_template_vars,
                              industry: e.target.value,
                            },
                          }))
                        }
                        size="small"
                        fullWidth
                      />
                    </Stack>
                  </CardContent>
                </Card>

                {/* Agent defaults */}
                <Card variant="outlined" sx={{ borderRadius: '12px' }}>
                  <CardContent>
                    <Typography variant="subtitle2" sx={{ mb: 2 }}>
                      Agent Defaults (applies to all agents)
                    </Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                      Optional overrides applied to every agent in this scenario.
                    </Typography>
                    <Stack spacing={2}>
                      <TextField
                        label="Default Greeting"
                        value={config.agent_defaults?.greeting || ''}
                        onChange={(e) =>
                          setConfig((prev) => ({
                            ...prev,
                            agent_defaults: {
                              ...prev.agent_defaults,
                              greeting: e.target.value || null,
                            },
                          }))
                        }
                        size="small"
                        fullWidth
                        placeholder="Leave empty to use agent's own greeting"
                      />
                      <TextField
                        label="Default Return Greeting"
                        value={config.agent_defaults?.return_greeting || ''}
                        onChange={(e) =>
                          setConfig((prev) => ({
                            ...prev,
                            agent_defaults: {
                              ...prev.agent_defaults,
                              return_greeting: e.target.value || null,
                            },
                          }))
                        }
                        size="small"
                        fullWidth
                        placeholder="Leave empty to use agent's own return greeting"
                      />
                    </Stack>
                  </CardContent>
                </Card>
              </Stack>
            )}
          </>
        )}
      </Box>

      {/* Footer actions */}
      <Divider />
      <Box sx={{ p: 2, backgroundColor: '#fafbfc', display: 'flex', gap: 2, justifyContent: 'flex-end' }}>
        <Button onClick={handleReset} startIcon={<RefreshIcon />} disabled={saving}>
          Reset
        </Button>
        <Button
          variant="contained"
          onClick={handleSave}
          startIcon={saving ? <CircularProgress size={18} color="inherit" /> : <SaveIcon />}
          disabled={saving || !config.name.trim()}
          sx={{
            background: editMode
              ? 'linear-gradient(135deg, #f59e0b 0%, #fbbf24 100%)'
              : 'linear-gradient(135deg, #4f46e5 0%, #6366f1 100%)',
            boxShadow: editMode
              ? '0 4px 14px rgba(245, 158, 11, 0.35)'
              : '0 4px 14px rgba(99, 102, 241, 0.35)',
          }}
        >
          {saving
            ? editMode
              ? 'Updating...'
              : 'Creating...'
            : editMode
            ? 'Update Scenario'
            : 'Create Scenario'}
        </Button>
      </Box>
    </Box>
  );
}
