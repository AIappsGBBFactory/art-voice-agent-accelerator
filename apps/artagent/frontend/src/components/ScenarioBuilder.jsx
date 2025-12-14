/**
 * ScenarioBuilder Component
 * =========================
 * 
 * A visual flow-based scenario builder with connected agent nodes:
 * 
 *   [Start Agent] ──→ [Target A] ──→ [Target C]
 *                          │
 *                          └──→ [Target B]
 * 
 * Features:
 * - Visual graph layout showing agent flow
 * - Click "+" on any node to add handoff targets
 * - Arrows show handoff connections with type indicators
 * - Select start agent to begin the flow
 */

import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  Alert,
  Avatar,
  Box,
  Button,
  Card,
  Chip,
  CircularProgress,
  Collapse,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Divider,
  FormControl,
  FormControlLabel,
  IconButton,
  InputLabel,
  LinearProgress,
  List,
  ListItem,
  ListItemAvatar,
  ListItemButton,
  ListItemText,
  MenuItem,
  Paper,
  Popover,
  Select,
  Stack,
  Switch,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import CheckIcon from '@mui/icons-material/Check';
import CloseIcon from '@mui/icons-material/Close';
import DeleteIcon from '@mui/icons-material/Delete';
import EditIcon from '@mui/icons-material/Edit';
import HubIcon from '@mui/icons-material/Hub';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import RefreshIcon from '@mui/icons-material/Refresh';
import SaveIcon from '@mui/icons-material/Save';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import SettingsIcon from '@mui/icons-material/Settings';
import VolumeUpIcon from '@mui/icons-material/VolumeUp';
import VolumeOffIcon from '@mui/icons-material/VolumeOff';
import TuneIcon from '@mui/icons-material/Tune';
import CallSplitIcon from '@mui/icons-material/CallSplit';
import ArrowRightAltIcon from '@mui/icons-material/ArrowRightAlt';
import AutoFixHighIcon from '@mui/icons-material/AutoFixHigh';
import PersonAddIcon from '@mui/icons-material/PersonAdd';

import { API_BASE_URL } from '../config/constants.js';
import logger from '../utils/logger.js';

// ═══════════════════════════════════════════════════════════════════════════════
// CONSTANTS & STYLES
// ═══════════════════════════════════════════════════════════════════════════════

const NODE_WIDTH = 180;
const NODE_HEIGHT = 80;
const HORIZONTAL_GAP = 120;
const VERTICAL_GAP = 100;
const ARROW_SIZE = 24;

const colors = {
  start: { bg: '#ecfdf5', border: '#10b981', avatar: '#059669' },
  active: { bg: '#f5f3ff', border: '#8b5cf6', avatar: '#7c3aed' },
  inactive: { bg: '#f9fafb', border: '#d1d5db', avatar: '#9ca3af' },
  selected: { bg: '#ede9fe', border: '#6366f1', avatar: '#4f46e5' },
  session: { bg: '#fef3c7', border: '#f59e0b', avatar: '#d97706' }, // Amber for session agents
  announced: '#8b5cf6',
  discrete: '#f59e0b',
};

// Distinct color palette for connection arrows (to differentiate overlapping paths)
const connectionColors = [
  '#8b5cf6', // violet
  '#3b82f6', // blue
  '#06b6d4', // cyan
  '#10b981', // emerald
  '#f59e0b', // amber
  '#ef4444', // red
  '#ec4899', // pink
  '#6366f1', // indigo
  '#14b8a6', // teal
  '#f97316', // orange
  '#84cc16', // lime
  '#a855f7', // purple
];

// ═══════════════════════════════════════════════════════════════════════════════
// FLOW NODE COMPONENT
// ═══════════════════════════════════════════════════════════════════════════════

function FlowNode({
  agent,
  isStart,
  isSelected,
  isSessionAgent,
  position,
  onSelect,
  onAddHandoff,
  onEditAgent,
  outgoingCount,
}) {
  // Color scheme: start > session > active
  const colorScheme = isStart 
    ? colors.start 
    : isSessionAgent 
      ? colors.session 
      : colors.active;
  
  return (
    <Paper
      elevation={isSelected ? 4 : 1}
      onClick={() => onSelect(agent)}
      sx={{
        position: 'absolute',
        left: position.x,
        top: position.y,
        width: NODE_WIDTH,
        height: NODE_HEIGHT,
        borderRadius: '12px',
        border: `2px solid ${isSelected ? colors.selected.border : colorScheme.border}`,
        backgroundColor: isSelected ? colors.selected.bg : colorScheme.bg,
        cursor: 'pointer',
        transition: 'all 0.2s ease',
        overflow: 'visible',
        zIndex: isSelected ? 10 : 1,
        '&:hover': {
          boxShadow: '0 4px 20px rgba(0,0,0,0.12)',
          transform: 'translateY(-2px)',
        },
      }}
    >
      {/* Start badge */}
      {isStart && (
        <Chip
          icon={<PlayArrowIcon sx={{ fontSize: 12 }} />}
          label="START"
          size="small"
          color="success"
          sx={{
            position: 'absolute',
            top: -12,
            left: '50%',
            transform: 'translateX(-50%)',
            height: 22,
            fontSize: 10,
            fontWeight: 700,
          }}
        />
      )}

      {/* Session agent badge */}
      {isSessionAgent && !isStart && (
        <Chip
          icon={<AutoFixHighIcon sx={{ fontSize: 12 }} />}
          label="CUSTOM"
          size="small"
          sx={{
            position: 'absolute',
            top: -12,
            left: '50%',
            transform: 'translateX(-50%)',
            height: 22,
            fontSize: 10,
            fontWeight: 700,
            backgroundColor: colors.session.border,
            color: '#fff',
          }}
        />
      )}
      
      {/* Node content */}
      <Stack
        direction="row"
        alignItems="center"
        spacing={1.5}
        sx={{ p: 1.5, height: '100%' }}
      >
        <Avatar
          sx={{
            width: 40,
            height: 40,
            bgcolor: isSelected ? colors.selected.avatar : colorScheme.avatar,
            fontSize: 16,
            fontWeight: 600,
          }}
        >
          {agent.name?.[0] || 'A'}
        </Avatar>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography
            variant="subtitle2"
            sx={{
              fontWeight: 600,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              lineHeight: 1.2,
            }}
          >
            {agent.name}
          </Typography>
          {agent.description && (
            <Typography
              variant="caption"
              color="text.secondary"
              sx={{
                display: 'block',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                fontSize: 10,
              }}
            >
              {agent.description}
            </Typography>
          )}
        </Box>
      </Stack>

      {/* Add handoff button (right side) */}
      <Tooltip title="Add handoff target">
        <IconButton
          size="small"
          onClick={(e) => {
            e.stopPropagation();
            onAddHandoff(agent);
          }}
          sx={{
            position: 'absolute',
            right: -16,
            top: '50%',
            transform: 'translateY(-50%)',
            width: 32,
            height: 32,
            backgroundColor: '#fff',
            border: '2px solid #e5e7eb',
            boxShadow: '0 2px 8px rgba(0,0,0,0.1)',
            '&:hover': {
              backgroundColor: '#f5f3ff',
              borderColor: '#8b5cf6',
            },
          }}
        >
          <AddIcon fontSize="small" />
        </IconButton>
      </Tooltip>

      {/* Edit button for session agents (left side) */}
      {isSessionAgent && onEditAgent && (
        <Tooltip title="Edit agent in Agent Builder">
          <IconButton
            size="small"
            onClick={(e) => {
              e.stopPropagation();
              onEditAgent(agent);
            }}
            sx={{
              position: 'absolute',
              left: -16,
              top: '50%',
              transform: 'translateY(-50%)',
              width: 28,
              height: 28,
              backgroundColor: '#fff',
              border: `2px solid ${colors.session.border}`,
              boxShadow: '0 2px 8px rgba(0,0,0,0.1)',
              '&:hover': {
                backgroundColor: colors.session.bg,
                borderColor: colors.session.avatar,
              },
            }}
          >
            <EditIcon sx={{ fontSize: 14 }} />
          </IconButton>
        </Tooltip>
      )}

      {/* Outgoing count badge */}
      {outgoingCount > 0 && (
        <Chip
          label={outgoingCount}
          size="small"
          sx={{
            position: 'absolute',
            bottom: -10,
            right: 10,
            height: 20,
            minWidth: 20,
            fontSize: 11,
            fontWeight: 600,
            backgroundColor: '#8b5cf6',
            color: '#fff',
          }}
        />
      )}
    </Paper>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// CONNECTION ARROW COMPONENT (SVG)
// ═══════════════════════════════════════════════════════════════════════════════

function ConnectionArrow({ from, to, type, isSelected, onClick, onDelete, colorIndex = 0 }) {
  // Get connection color from palette
  const connectionColor = connectionColors[colorIndex % connectionColors.length];
  
  // Determine if this is a forward or backward connection
  const isBackward = to.x < from.x;
  
  let startX, startY, endX, endY;
  
  if (isBackward) {
    // Backward: connect LEFT side of source → RIGHT side of target
    // This creates a short, direct path instead of looping around
    startX = from.x;
    startY = from.y + NODE_HEIGHT / 2;
    endX = to.x + NODE_WIDTH;
    endY = to.y + NODE_HEIGHT / 2;
  } else {
    // Forward: connect RIGHT side of source → LEFT side of target
    startX = from.x + NODE_WIDTH;
    startY = from.y + NODE_HEIGHT / 2;
    endX = to.x;
    endY = to.y + NODE_HEIGHT / 2;
  }
  
  const dx = endX - startX;
  const dy = endY - startY;
  const distance = Math.sqrt(dx * dx + dy * dy);
  const arrowOffset = 10; // Space for arrowhead
  
  // Simple S-curve for all connections
  const curvature = Math.min(60, Math.max(30, distance * 0.35));
  
  let path;
  if (isBackward) {
    // Backward: curve to the left
    path = `M ${startX} ${startY} 
            C ${startX - curvature} ${startY}, 
              ${endX + curvature + arrowOffset} ${endY}, 
              ${endX + arrowOffset} ${endY}`;
  } else {
    // Forward: curve to the right
    path = `M ${startX} ${startY} 
            C ${startX + curvature} ${startY}, 
              ${endX - curvature - arrowOffset} ${endY}, 
              ${endX - arrowOffset} ${endY}`;
  }
  
  // Calculate label position (midpoint)
  const labelX = (startX + endX) / 2;
  const labelY = (startY + endY) / 2;
  const labelOffsetY = isSelected ? 25 : 18;
  
  // Use connection color from palette (unique per arrow)
  const arrowColor = connectionColor;
  
  // Determine marker based on direction
  const markerPrefix = isBackward ? 'arrowhead-back' : 'arrowhead';
  const markerId = `${markerPrefix}-${colorIndex}${isSelected ? '-selected' : ''}`;
  
  return (
    <g style={{ cursor: 'pointer' }} onClick={onClick}>
      {/* Invisible wider path for easier clicking */}
      <path
        d={path}
        fill="none"
        stroke="transparent"
        strokeWidth={20}
      />
      {/* Visible arrow path */}
      <path
        d={path}
        fill="none"
        stroke={isSelected ? colors.selected.border : arrowColor}
        strokeWidth={isSelected ? 3 : 2}
        strokeDasharray={type === 'discrete' ? '8,4' : 'none'}
        markerEnd={`url(#${markerId})`}
        style={{ transition: 'stroke 0.2s, stroke-width 0.2s' }}
      />
      {/* Delete button (shown when selected) */}
      {isSelected && (
        <g
          transform={`translate(${labelX - 10}, ${labelY + labelOffsetY - 30})`}
          onClick={(e) => { e.stopPropagation(); onDelete(); }}
          style={{ cursor: 'pointer' }}
        >
          <circle cx="10" cy="10" r="12" fill="#fff" stroke="#ef4444" strokeWidth="2" />
          <text x="10" y="14" textAnchor="middle" fill="#ef4444" fontSize="14" fontWeight="bold">×</text>
        </g>
      )}
      {/* Type label with background for visibility */}
      <g>
        <rect
          x={labelX - 12}
          y={labelY + labelOffsetY - 10}
          width={24}
          height={16}
          rx={4}
          fill="white"
          fillOpacity={0.9}
          stroke={arrowColor}
          strokeWidth={1}
        />
        <text
          x={labelX}
          y={labelY + labelOffsetY + 3}
          textAnchor="middle"
          fill={arrowColor}
          fontSize="10"
          fontWeight="600"
        >
          {type === 'announced' ? '🔊' : '🔇'}
        </text>
      </g>
    </g>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// HANDOFF EDITOR DIALOG
// ═══════════════════════════════════════════════════════════════════════════════

function HandoffEditorDialog({ open, onClose, handoff, agents, onSave, onDelete }) {
  const [type, setType] = useState(handoff?.type || 'announced');
  const [tool, setTool] = useState(handoff?.tool || '');
  const [shareContext, setShareContext] = useState(handoff?.share_context !== false);

  useEffect(() => {
    if (handoff) {
      setType(handoff.type || 'announced');
      setTool(handoff.tool || `handoff_${(handoff.to_agent || '').toLowerCase().replace(/\s+/g, '_')}`);
      setShareContext(handoff.share_context !== false);
    }
  }, [handoff]);

  const handleSave = () => {
    onSave({
      ...handoff,
      type,
      tool,
      share_context: shareContext,
    });
    onClose();
  };

  if (!handoff) return null;

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <CallSplitIcon color="primary" />
        Edit Handoff: {handoff.from_agent} → {handoff.to_agent}
      </DialogTitle>
      <DialogContent>
        <Stack spacing={3} sx={{ mt: 1 }}>
          {/* Type selector */}
          <Box>
            <Typography variant="subtitle2" gutterBottom>
              Handoff Type
            </Typography>
            <ToggleButtonGroup
              value={type}
              exclusive
              onChange={(e, v) => v && setType(v)}
              size="small"
              fullWidth
            >
              <ToggleButton value="announced" sx={{ textTransform: 'none' }}>
                <VolumeUpIcon sx={{ mr: 1, color: colors.announced }} />
                Announced
              </ToggleButton>
              <ToggleButton value="discrete" sx={{ textTransform: 'none' }}>
                <VolumeOffIcon sx={{ mr: 1, color: colors.discrete }} />
                Discrete (Silent)
              </ToggleButton>
            </ToggleButtonGroup>
            <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
              {type === 'announced'
                ? 'Target agent will greet/announce the transfer'
                : 'Silent handoff - agent continues conversation naturally'}
            </Typography>
          </Box>

          {/* Tool name */}
          <TextField
            label="Handoff Tool Name"
            value={tool}
            onChange={(e) => setTool(e.target.value)}
            size="small"
            fullWidth
            helperText="The function name the LLM calls to trigger this handoff"
          />

          {/* Share context */}
          <FormControlLabel
            control={
              <Switch
                checked={shareContext}
                onChange={(e) => setShareContext(e.target.checked)}
              />
            }
            label={
              <Box>
                <Typography variant="body2">Share conversation context</Typography>
                <Typography variant="caption" color="text.secondary">
                  Pass chat history and memory to target agent
                </Typography>
              </Box>
            }
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={() => { onDelete(); onClose(); }} color="error">
          Delete
        </Button>
        <Box sx={{ flex: 1 }} />
        <Button onClick={onClose}>Cancel</Button>
        <Button onClick={handleSave} variant="contained">
          Save
        </Button>
      </DialogActions>
    </Dialog>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// ADD HANDOFF POPOVER
// ═══════════════════════════════════════════════════════════════════════════════

function AddHandoffPopover({ anchorEl, open, onClose, fromAgent, agents, existingTargets, onAdd }) {
  const availableAgents = useMemo(() => {
    if (!fromAgent) return [];
    return agents.filter(
      (a) => a.name !== fromAgent.name && !existingTargets.includes(a.name)
    );
  }, [agents, fromAgent, existingTargets]);

  return (
    <Popover
      open={open}
      anchorEl={anchorEl}
      onClose={onClose}
      anchorOrigin={{ vertical: 'center', horizontal: 'right' }}
      transformOrigin={{ vertical: 'center', horizontal: 'left' }}
      PaperProps={{
        sx: { width: 280, maxHeight: 400, borderRadius: '12px' },
      }}
    >
      <Box sx={{ p: 2 }}>
        <Typography variant="subtitle2" gutterBottom>
          Add handoff from {fromAgent?.name}
        </Typography>
        <Typography variant="caption" color="text.secondary" sx={{ mb: 2, display: 'block' }}>
          Select target agent
        </Typography>
        
        {availableAgents.length === 0 ? (
          <Alert severity="info" sx={{ borderRadius: '8px' }}>
            No more agents available to add
          </Alert>
        ) : (
          <List dense sx={{ mx: -2 }}>
            {availableAgents.map((agent) => (
              <ListItemButton
                key={agent.name}
                onClick={() => { onAdd(agent); onClose(); }}
                sx={{ borderRadius: '8px', mx: 1 }}
              >
                <ListItemAvatar>
                  <Avatar sx={{ width: 32, height: 32, bgcolor: colors.active.avatar }}>
                    {agent.name?.[0]}
                  </Avatar>
                </ListItemAvatar>
                <ListItemText
                  primary={agent.name}
                  secondary={agent.description}
                  primaryTypographyProps={{ variant: 'body2', fontWeight: 500 }}
                  secondaryTypographyProps={{ variant: 'caption', noWrap: true }}
                />
              </ListItemButton>
            ))}
          </List>
        )}
      </Box>
    </Popover>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// START AGENT SELECTOR
// ═══════════════════════════════════════════════════════════════════════════════

function StartAgentSelector({ agents, selectedStart, onSelect }) {
  return (
    <Paper
      variant="outlined"
      sx={{
        p: 2,
        borderRadius: '12px',
        borderStyle: 'dashed',
        borderColor: '#10b981',
        backgroundColor: '#f0fdf4',
      }}
    >
      <Typography variant="subtitle2" sx={{ mb: 1, color: '#059669' }}>
        <PlayArrowIcon sx={{ fontSize: 16, mr: 0.5, verticalAlign: 'middle' }} />
        Select Starting Agent
      </Typography>
      <FormControl size="small" fullWidth>
        <Select
          value={selectedStart || ''}
          onChange={(e) => onSelect(e.target.value)}
          displayEmpty
        >
          <MenuItem value="" disabled>
            <em>Choose the entry point agent...</em>
          </MenuItem>
          {agents.map((agent) => (
            <MenuItem key={agent.name} value={agent.name}>
              <Stack direction="row" alignItems="center" spacing={1}>
                <Avatar 
                  sx={{ 
                    width: 24, 
                    height: 24, 
                    bgcolor: agent.is_session_agent ? colors.session.avatar : colors.start.avatar, 
                    fontSize: 12 
                  }}
                >
                  {agent.name?.[0]}
                </Avatar>
                <span>{agent.name}</span>
                {agent.is_session_agent && (
                  <Chip
                    icon={<AutoFixHighIcon sx={{ fontSize: 10 }} />}
                    label="Custom"
                    size="small"
                    sx={{
                      height: 18,
                      fontSize: 9,
                      ml: 1,
                      backgroundColor: colors.session.bg,
                      color: colors.session.avatar,
                    }}
                  />
                )}
              </Stack>
            </MenuItem>
          ))}
        </Select>
      </FormControl>
    </Paper>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// AGENT LIST SIDEBAR
// ═══════════════════════════════════════════════════════════════════════════════

function AgentListSidebar({ agents, graphAgents, onAddToGraph, onEditAgent, onCreateAgent }) {
  const ungraphedAgents = agents.filter((a) => !graphAgents.includes(a.name));
  
  // Separate static and session agents
  const staticAgents = ungraphedAgents.filter((a) => !a.is_session_agent);
  const sessionAgents = ungraphedAgents.filter((a) => a.is_session_agent);

  return (
    <Box sx={{ p: 1, height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Create new agent button */}
      {onCreateAgent && (
        <Button
          variant="outlined"
          size="small"
          startIcon={<PersonAddIcon />}
          onClick={onCreateAgent}
          sx={{
            mx: 1,
            mb: 1,
            borderStyle: 'dashed',
            borderColor: colors.session.border,
            color: colors.session.avatar,
            '&:hover': {
              borderStyle: 'solid',
              backgroundColor: colors.session.bg,
            },
          }}
        >
          Create New Agent
        </Button>
      )}

      {ungraphedAgents.length === 0 ? (
        <Box sx={{ p: 2, textAlign: 'center', color: '#9ca3af', flex: 1 }}>
          <SmartToyIcon sx={{ fontSize: 32, opacity: 0.5 }} />
          <Typography variant="caption" display="block">
            All agents in graph
          </Typography>
        </Box>
      ) : (
        <Box sx={{ flex: 1, overflowY: 'auto' }}>
          {/* Static agents */}
          {staticAgents.length > 0 && (
            <>
              <Typography variant="caption" color="text.secondary" sx={{ px: 1, fontWeight: 600 }}>
                Built-in Agents
              </Typography>
              <List dense>
                {staticAgents.map((agent) => (
                  <ListItem
                    key={agent.name}
                    secondaryAction={
                      <Stack direction="row" spacing={0.5}>
                        {onEditAgent && (
                          <Tooltip title="Override agent">
                            <IconButton edge="end" size="small" onClick={() => onEditAgent(agent, null)}>
                              <EditIcon fontSize="small" sx={{ color: colors.active.avatar }} />
                            </IconButton>
                          </Tooltip>
                        )}
                        <IconButton edge="end" size="small" onClick={() => onAddToGraph(agent)}>
                          <AddIcon fontSize="small" />
                        </IconButton>
                      </Stack>
                    }
                    sx={{ py: 0.5 }}
                  >
                    <ListItemAvatar sx={{ minWidth: 36 }}>
                      <Avatar sx={{ width: 28, height: 28, bgcolor: colors.active.avatar, fontSize: 12 }}>
                        {agent.name?.[0]}
                      </Avatar>
                    </ListItemAvatar>
                    <ListItemText
                      primary={agent.name}
                      primaryTypographyProps={{ variant: 'body2', fontSize: 12 }}
                    />
                  </ListItem>
                ))}
              </List>
            </>
          )}

          {/* Session/Custom agents */}
          {sessionAgents.length > 0 && (
            <>
              <Typography variant="caption" sx={{ px: 1, fontWeight: 600, color: colors.session.avatar, mt: 1, display: 'block' }}>
                Custom Agents
              </Typography>
              <List dense>
                {sessionAgents.map((agent) => (
                  <ListItem
                    key={agent.name}
                    secondaryAction={
                      <Stack direction="row" spacing={0.5}>
                        {onEditAgent && (
                          <Tooltip title="Edit agent">
                            <IconButton edge="end" size="small" onClick={() => onEditAgent(agent, agent.session_id)}>
                              <EditIcon fontSize="small" sx={{ color: colors.session.avatar }} />
                            </IconButton>
                          </Tooltip>
                        )}
                        <IconButton edge="end" size="small" onClick={() => onAddToGraph(agent)}>
                          <AddIcon fontSize="small" />
                        </IconButton>
                      </Stack>
                    }
                    sx={{ py: 0.5 }}
                  >
                    <ListItemAvatar sx={{ minWidth: 36 }}>
                      <Avatar sx={{ width: 28, height: 28, bgcolor: colors.session.avatar, fontSize: 12 }}>
                        {agent.name?.[0]}
                      </Avatar>
                    </ListItemAvatar>
                    <ListItemText
                      primary={agent.name}
                      secondary={agent.session_id ? `Session: ${agent.session_id.slice(0, 8)}...` : null}
                      primaryTypographyProps={{ variant: 'body2', fontSize: 12 }}
                      secondaryTypographyProps={{ variant: 'caption', fontSize: 9 }}
                    />
                  </ListItem>
                ))}
              </List>
            </>
          )}
        </Box>
      )}
    </Box>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// MAIN COMPONENT
// ═══════════════════════════════════════════════════════════════════════════════

export default function ScenarioBuilder({
  sessionId,
  onScenarioCreated,
  onScenarioUpdated,
  onEditAgent,  // Callback to switch to agent builder for editing: (agent, sessionId) => void
  onCreateAgent, // Callback to switch to agent builder for creating new agent: () => void
  existingConfig = null,
  editMode = false,
}) {
  // State
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  // Data
  const [availableAgents, setAvailableAgents] = useState([]);
  const [availableTemplates, setAvailableTemplates] = useState([]);
  const [selectedTemplate, setSelectedTemplate] = useState(null);

  // Scenario config
  const [config, setConfig] = useState({
    name: 'Custom Scenario',
    description: '',
    start_agent: null,
    handoff_type: 'announced',
    handoffs: [],
    global_template_vars: {
      company_name: 'ART Voice Agent',
      industry: 'general',
    },
  });

  // UI state
  const [selectedNode, setSelectedNode] = useState(null);
  const [selectedEdge, setSelectedEdge] = useState(null);
  const [addHandoffAnchor, setAddHandoffAnchor] = useState(null);
  const [addHandoffFrom, setAddHandoffFrom] = useState(null);
  const [showSettings, setShowSettings] = useState(false);
  const [editingHandoff, setEditingHandoff] = useState(null);

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
      logger.error('Failed to fetch templates:', err);
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
            start_agent: data.config.start_agent,
            handoff_type: data.config.handoff_type || 'announced',
            handoffs: data.config.handoffs || [],
            global_template_vars: data.config.global_template_vars || {},
          });
        }
      }
    } catch (err) {
      logger.debug('No existing scenario');
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

  useEffect(() => {
    if (existingConfig) {
      setConfig({
        name: existingConfig.name || 'Custom Scenario',
        description: existingConfig.description || '',
        start_agent: existingConfig.start_agent,
        handoff_type: existingConfig.handoff_type || 'announced',
        handoffs: existingConfig.handoffs || [],
        global_template_vars: existingConfig.global_template_vars || {},
      });
    }
  }, [existingConfig]);

  // ─────────────────────────────────────────────────────────────────────────
  // GRAPH LAYOUT CALCULATION
  // ─────────────────────────────────────────────────────────────────────────

  const graphLayout = useMemo(() => {
    const positions = {};
    const agentsInGraph = new Set();

    if (!config.start_agent) {
      return { positions, agentsInGraph: [] };
    }

    // BFS to calculate positions
    const queue = [{ agent: config.start_agent, level: 0, index: 0 }];
    const levelCounts = {};
    const visited = new Set();

    // First pass: count agents per level for vertical centering
    const tempQueue = [{ agent: config.start_agent, level: 0 }];
    const tempVisited = new Set();
    while (tempQueue.length > 0) {
      const { agent, level } = tempQueue.shift();
      if (tempVisited.has(agent)) continue;
      tempVisited.add(agent);
      levelCounts[level] = (levelCounts[level] || 0) + 1;
      
      const outgoing = config.handoffs.filter((h) => h.from_agent === agent);
      outgoing.forEach((h) => {
        if (!tempVisited.has(h.to_agent)) {
          tempQueue.push({ agent: h.to_agent, level: level + 1 });
        }
      });
    }

    // Second pass: assign positions
    const levelIndices = {};
    while (queue.length > 0) {
      const { agent, level } = queue.shift();
      if (visited.has(agent)) continue;
      visited.add(agent);
      agentsInGraph.add(agent);

      // Calculate position
      const currentIndex = levelIndices[level] || 0;
      levelIndices[level] = currentIndex + 1;
      const totalInLevel = levelCounts[level] || 1;
      
      // Center vertically based on number of agents in this level
      const totalHeight = totalInLevel * (NODE_HEIGHT + VERTICAL_GAP) - VERTICAL_GAP;
      const startY = Math.max(60, 200 - totalHeight / 2);
      
      positions[agent] = {
        x: 40 + level * (NODE_WIDTH + HORIZONTAL_GAP),
        y: startY + currentIndex * (NODE_HEIGHT + VERTICAL_GAP),
      };

      // Queue outgoing connections
      const outgoing = config.handoffs.filter((h) => h.from_agent === agent);
      outgoing.forEach((h) => {
        if (!visited.has(h.to_agent)) {
          queue.push({ agent: h.to_agent, level: level + 1 });
        }
      });
    }

    return { positions, agentsInGraph: Array.from(agentsInGraph) };
  }, [config.start_agent, config.handoffs]);

  // ─────────────────────────────────────────────────────────────────────────
  // HANDLERS
  // ─────────────────────────────────────────────────────────────────────────

  const handleSetStartAgent = useCallback((agentName) => {
    setConfig((prev) => ({ ...prev, start_agent: agentName }));
  }, []);

  const handleOpenAddHandoff = useCallback((agent, event) => {
    setAddHandoffFrom(agent);
    setAddHandoffAnchor(event?.currentTarget || canvasRef.current);
  }, []);

  const handleAddHandoff = useCallback((targetAgent) => {
    if (!addHandoffFrom) return;
    
    const newHandoff = {
      from_agent: addHandoffFrom.name,
      to_agent: targetAgent.name,
      tool: `handoff_${targetAgent.name.toLowerCase().replace(/\s+/g, '_')}`,
      type: config.handoff_type,
      share_context: true,
    };

    setConfig((prev) => ({
      ...prev,
      handoffs: [...prev.handoffs, newHandoff],
    }));

    setAddHandoffFrom(null);
    setAddHandoffAnchor(null);
  }, [addHandoffFrom, config.handoff_type]);

  const handleSelectEdge = useCallback((handoff) => {
    setSelectedEdge(handoff);
    setSelectedNode(null);
  }, []);

  const handleUpdateHandoff = useCallback((updatedHandoff) => {
    setConfig((prev) => ({
      ...prev,
      handoffs: prev.handoffs.map((h) =>
        h.from_agent === updatedHandoff.from_agent && h.to_agent === updatedHandoff.to_agent
          ? updatedHandoff
          : h
      ),
    }));
    setSelectedEdge(null);
  }, []);

  const handleDeleteHandoff = useCallback((handoff) => {
    setConfig((prev) => ({
      ...prev,
      handoffs: prev.handoffs.filter(
        (h) => !(h.from_agent === handoff.from_agent && h.to_agent === handoff.to_agent)
      ),
    }));
    setSelectedEdge(null);
    setEditingHandoff(null);
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
          start_agent: template.start_agent,
          handoff_type: template.handoff_type || 'announced',
          handoffs: template.handoffs || [],
          global_template_vars: template.global_template_vars || {},
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
        agents: graphLayout.agentsInGraph,
        start_agent: config.start_agent,
        handoff_type: config.handoff_type,
        handoffs: config.handoffs,
        global_template_vars: config.global_template_vars,
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
      start_agent: null,
      handoff_type: 'announced',
      handoffs: [],
      global_template_vars: {
        company_name: 'ART Voice Agent',
        industry: 'general',
      },
    });
    setSelectedTemplate(null);
    setSelectedNode(null);
    setSelectedEdge(null);
  };

  // Get outgoing handoff counts per agent
  const outgoingCounts = useMemo(() => {
    const counts = {};
    config.handoffs.forEach((h) => {
      counts[h.from_agent] = (counts[h.from_agent] || 0) + 1;
    });
    return counts;
  }, [config.handoffs]);

  // Get existing targets for an agent
  const getExistingTargets = useCallback((agentName) => {
    return config.handoffs
      .filter((h) => h.from_agent === agentName)
      .map((h) => h.to_agent);
  }, [config.handoffs]);

  // ─────────────────────────────────────────────────────────────────────────
  // RENDER
  // ─────────────────────────────────────────────────────────────────────────

  const canvasWidth = Math.max(
    800,
    Math.max(...Object.values(graphLayout.positions).map((p) => p.x + NODE_WIDTH + 100), 0)
  );
  const canvasHeight = Math.max(
    400,
    Math.max(...Object.values(graphLayout.positions).map((p) => p.y + NODE_HEIGHT + 60), 0)
  );

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Loading bar */}
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

      {/* Header */}
      <Box sx={{ p: 2, borderBottom: '1px solid #e5e7eb' }}>
        <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} sx={{ mb: 2 }}>
          <TextField
            label="Scenario Name"
            value={config.name}
            onChange={(e) => setConfig((prev) => ({ ...prev, name: e.target.value }))}
            size="small"
            sx={{ flex: 1, maxWidth: 300 }}
          />
          <TextField
            label="Description"
            value={config.description}
            onChange={(e) => setConfig((prev) => ({ ...prev, description: e.target.value }))}
            size="small"
            sx={{ flex: 2 }}
          />
          <Button
            variant="outlined"
            startIcon={<SettingsIcon />}
            onClick={() => setShowSettings(!showSettings)}
            size="small"
          >
            Settings
          </Button>
        </Stack>

        {/* Templates */}
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
          <Typography variant="caption" color="text.secondary">
            Templates:
          </Typography>
          {availableTemplates.map((template) => (
            <Chip
              key={template.id}
              label={template.name}
              size="small"
              icon={selectedTemplate === template.id ? <CheckIcon /> : <HubIcon fontSize="small" />}
              color={selectedTemplate === template.id ? 'primary' : 'default'}
              variant={selectedTemplate === template.id ? 'filled' : 'outlined'}
              onClick={() => handleApplyTemplate(template.id)}
              sx={{ cursor: 'pointer' }}
            />
          ))}
        </Stack>

        {/* Settings panel */}
        <Collapse in={showSettings}>
          <Paper variant="outlined" sx={{ mt: 2, p: 2, borderRadius: '12px' }}>
            <Stack direction={{ xs: 'column', md: 'row' }} spacing={2}>
              <FormControl size="small" sx={{ minWidth: 180 }}>
                <InputLabel>Default Handoff Type</InputLabel>
                <Select
                  value={config.handoff_type}
                  label="Default Handoff Type"
                  onChange={(e) => setConfig((prev) => ({ ...prev, handoff_type: e.target.value }))}
                >
                  <MenuItem value="announced">🔊 Announced</MenuItem>
                  <MenuItem value="discrete">🔇 Discrete</MenuItem>
                </Select>
              </FormControl>
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
                sx={{ flex: 1 }}
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
                sx={{ flex: 1 }}
              />
            </Stack>
          </Paper>
        </Collapse>
      </Box>

      {/* Main content */}
      <Box sx={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* Left sidebar - Agent list */}
        <Box
          sx={{
            width: 200,
            borderRight: '1px solid #e5e7eb',
            backgroundColor: '#fafbfc',
            overflowY: 'auto',
            // Custom scrollbar styling
            '&::-webkit-scrollbar': {
              width: 6,
            },
            '&::-webkit-scrollbar-track': {
              background: 'transparent',
            },
            '&::-webkit-scrollbar-thumb': {
              background: '#d1d1d1',
              borderRadius: 3,
              '&:hover': {
                background: '#b1b1b1',
              },
            },
          }}
        >
          <Box sx={{ p: 2, borderBottom: '1px solid #e5e7eb' }}>
            <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
              <SmartToyIcon fontSize="small" sx={{ mr: 0.5, verticalAlign: 'middle' }} />
              Agents
            </Typography>
          </Box>
          <AgentListSidebar
            agents={availableAgents}
            graphAgents={graphLayout.agentsInGraph}
            onAddToGraph={(agent) => {
              // If no start agent, make this the start
              if (!config.start_agent) {
                handleSetStartAgent(agent.name);
              }
            }}
            onEditAgent={onEditAgent}
            onCreateAgent={onCreateAgent}
          />
        </Box>

        {/* Canvas area */}
        <Box
          ref={canvasRef}
          sx={{
            flex: 1,
            backgroundColor: '#f8fafc',
            overflow: 'auto',
            position: 'relative',
            // Custom scrollbar styling
            '&::-webkit-scrollbar': {
              width: 10,
              height: 10,
            },
            '&::-webkit-scrollbar-track': {
              background: '#f1f1f1',
              borderRadius: 5,
            },
            '&::-webkit-scrollbar-thumb': {
              background: '#c1c1c1',
              borderRadius: 5,
              '&:hover': {
                background: '#a1a1a1',
              },
            },
            '&::-webkit-scrollbar-corner': {
              background: '#f1f1f1',
            },
          }}
        >
          {/* Empty state - no start agent */}
          {!config.start_agent ? (
            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                height: '100%',
                p: 4,
              }}
            >
              <StartAgentSelector
                agents={availableAgents}
                selectedStart={config.start_agent}
                onSelect={handleSetStartAgent}
              />
            </Box>
          ) : (
            /* Visual flow graph */
            <Box
              sx={{
                position: 'relative',
                minWidth: canvasWidth,
                minHeight: canvasHeight,
                p: 2,
              }}
            >
              {/* SVG layer for arrows */}
              <svg
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  height: '100%',
                  pointerEvents: 'none',
                  overflow: 'visible',
                }}
              >
                <defs>
                  {/* Forward arrow markers (pointing right) - one for each color */}
                  {connectionColors.map((color, idx) => (
                    <marker
                      key={`arrowhead-${idx}`}
                      id={`arrowhead-${idx}`}
                      markerWidth="10"
                      markerHeight="7"
                      refX="9"
                      refY="3.5"
                      orient="auto"
                    >
                      <polygon points="0 0, 10 3.5, 0 7" fill={color} />
                    </marker>
                  ))}
                  {/* Backward arrow markers (pointing left) - one for each color */}
                  {connectionColors.map((color, idx) => (
                    <marker
                      key={`arrowhead-back-${idx}`}
                      id={`arrowhead-back-${idx}`}
                      markerWidth="10"
                      markerHeight="7"
                      refX="1"
                      refY="3.5"
                      orient="auto"
                    >
                      <polygon points="10 0, 0 3.5, 10 7" fill={color} />
                    </marker>
                  ))}
                  {/* Selected state markers (forward) */}
                  {connectionColors.map((color, idx) => (
                    <marker
                      key={`arrowhead-${idx}-selected`}
                      id={`arrowhead-${idx}-selected`}
                      markerWidth="10"
                      markerHeight="7"
                      refX="9"
                      refY="3.5"
                      orient="auto"
                    >
                      <polygon points="0 0, 10 3.5, 0 7" fill={colors.selected.border} />
                    </marker>
                  ))}
                  {/* Selected state markers (backward) */}
                  {connectionColors.map((color, idx) => (
                    <marker
                      key={`arrowhead-back-${idx}-selected`}
                      id={`arrowhead-back-${idx}-selected`}
                      markerWidth="10"
                      markerHeight="7"
                      refX="1"
                      refY="3.5"
                      orient="auto"
                    >
                      <polygon points="10 0, 0 3.5, 10 7" fill={colors.selected.border} />
                    </marker>
                  ))}
                </defs>

                {/* Render connection arrows */}
                <g style={{ pointerEvents: 'auto' }}>
                  {config.handoffs.map((handoff, idx) => {
                    const fromPos = graphLayout.positions[handoff.from_agent];
                    const toPos = graphLayout.positions[handoff.to_agent];
                    if (!fromPos || !toPos) return null;

                    return (
                      <ConnectionArrow
                        key={`${handoff.from_agent}-${handoff.to_agent}-${idx}`}
                        from={fromPos}
                        to={toPos}
                        type={handoff.type}
                        colorIndex={idx}
                        isSelected={selectedEdge === handoff}
                        onClick={() => {
                          setSelectedEdge(handoff);
                          setEditingHandoff(handoff);
                        }}
                        onDelete={() => handleDeleteHandoff(handoff)}
                      />
                    );
                  })}
                </g>
              </svg>

              {/* Render nodes */}
              {Object.entries(graphLayout.positions).map(([agentName, position]) => {
                const agent = availableAgents.find((a) => a.name === agentName);
                if (!agent) return null;

                return (
                  <FlowNode
                    key={agentName}
                    agent={agent}
                    isStart={config.start_agent === agentName}
                    isSelected={selectedNode?.name === agentName}
                    isSessionAgent={agent.is_session_agent}
                    position={position}
                    onSelect={setSelectedNode}
                    onAddHandoff={(a) => handleOpenAddHandoff(a, null)}
                    onEditAgent={onEditAgent ? (a) => onEditAgent(a, a.session_id) : null}
                    outgoingCount={outgoingCounts[agentName] || 0}
                  />
                );
              })}
            </Box>
          )}
        </Box>

        {/* Right sidebar - Stats */}
        <Box
          sx={{
            width: 220,
            borderLeft: '1px solid #e5e7eb',
            backgroundColor: '#fff',
            p: 2,
          }}
        >
          <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 2 }}>
            Scenario Stats
          </Typography>
          
          <Stack spacing={2}>
            <Paper variant="outlined" sx={{ p: 1.5, borderRadius: '10px' }}>
              <Typography variant="caption" color="text.secondary">
                Start Agent
              </Typography>
              <Typography variant="body2" sx={{ fontWeight: 600 }}>
                {config.start_agent || '—'}
              </Typography>
            </Paper>

            <Paper variant="outlined" sx={{ p: 1.5, borderRadius: '10px' }}>
              <Typography variant="caption" color="text.secondary">
                Agents in Graph
              </Typography>
              <Typography variant="body2" sx={{ fontWeight: 600 }}>
                {graphLayout.agentsInGraph.length}
              </Typography>
            </Paper>

            <Paper variant="outlined" sx={{ p: 1.5, borderRadius: '10px' }}>
              <Typography variant="caption" color="text.secondary">
                Handoff Routes
              </Typography>
              <Typography variant="body2" sx={{ fontWeight: 600 }}>
                {config.handoffs.length}
              </Typography>
            </Paper>

            <Divider />

            <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>
              Handoffs
            </Typography>
            {config.handoffs.length === 0 ? (
              <Typography variant="caption" color="text.secondary">
                No handoffs yet. Click + on a node to add.
              </Typography>
            ) : (
              <Stack spacing={0.5}>
                {config.handoffs.map((h, i) => {
                  const handoffColor = connectionColors[i % connectionColors.length];
                  return (
                    <Chip
                      key={i}
                      label={`${h.from_agent} → ${h.to_agent}`}
                      size="small"
                      variant="outlined"
                      icon={h.type === 'announced' ? <VolumeUpIcon sx={{ color: `${handoffColor} !important` }} /> : <VolumeOffIcon sx={{ color: `${handoffColor} !important` }} />}
                      onClick={() => setEditingHandoff(h)}
                      onDelete={() => handleDeleteHandoff(h)}
                      sx={{
                        justifyContent: 'flex-start',
                        height: 28,
                        fontSize: 11,
                        borderColor: handoffColor,
                        borderWidth: 2,
                        '&:hover': {
                          borderColor: handoffColor,
                          backgroundColor: `${handoffColor}15`,
                        },
                      }}
                    />
                  );
                })}
              </Stack>
            )}
          </Stack>
        </Box>
      </Box>

      {/* Footer */}
      <Box
        sx={{
          p: 2,
          borderTop: '1px solid #e5e7eb',
          backgroundColor: '#fafbfc',
          display: 'flex',
          gap: 2,
          justifyContent: 'flex-end',
        }}
      >
        <Button onClick={handleReset} startIcon={<RefreshIcon />} disabled={saving}>
          Reset
        </Button>
        <Button
          variant="contained"
          onClick={handleSave}
          startIcon={saving ? <CircularProgress size={18} color="inherit" /> : <SaveIcon />}
          disabled={saving || !config.name.trim() || !config.start_agent}
          sx={{
            background: editMode
              ? 'linear-gradient(135deg, #f59e0b 0%, #fbbf24 100%)'
              : 'linear-gradient(135deg, #4f46e5 0%, #6366f1 100%)',
          }}
        >
          {saving ? 'Saving...' : editMode ? 'Update Scenario' : 'Create Scenario'}
        </Button>
      </Box>

      {/* Add Handoff Popover */}
      <AddHandoffPopover
        anchorEl={addHandoffAnchor}
        open={Boolean(addHandoffAnchor)}
        onClose={() => { setAddHandoffAnchor(null); setAddHandoffFrom(null); }}
        fromAgent={addHandoffFrom}
        agents={availableAgents}
        existingTargets={addHandoffFrom ? getExistingTargets(addHandoffFrom.name) : []}
        onAdd={handleAddHandoff}
      />

      {/* Handoff Editor Dialog */}
      <HandoffEditorDialog
        open={Boolean(editingHandoff)}
        onClose={() => setEditingHandoff(null)}
        handoff={editingHandoff}
        agents={availableAgents}
        onSave={handleUpdateHandoff}
        onDelete={() => editingHandoff && handleDeleteHandoff(editingHandoff)}
      />
    </Box>
  );
}
