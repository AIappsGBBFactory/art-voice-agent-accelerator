/**
 * AgentScenarioBuilder Component
 * ===============================
 * 
 * A unified builder dialog that combines:
 * - Agent Builder: Create and configure individual agents
 * - Scenario Builder: Create orchestration flows between agents
 * 
 * Users can toggle between modes using a toolbar switch.
 */

import React, { useState, useCallback } from 'react';
import {
  Avatar,
  Box,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  IconButton,
  LinearProgress,
  Stack,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import HubIcon from '@mui/icons-material/Hub';
import EditIcon from '@mui/icons-material/Edit';

import AgentBuilderContent from './AgentBuilderContent.jsx';
import ScenarioBuilder from './ScenarioBuilder.jsx';

// ═══════════════════════════════════════════════════════════════════════════════
// STYLES
// ═══════════════════════════════════════════════════════════════════════════════

const styles = {
  dialog: {
    '& .MuiDialog-paper': {
      maxWidth: '1200px',
      width: '95vw',
      height: '90vh',
      maxHeight: '90vh',
      borderRadius: '16px',
      resize: 'both',
      overflow: 'auto',
    },
  },
  header: {
    background: 'linear-gradient(135deg, #1e3a5f 0%, #2d5a87 50%, #3d7ab5 100%)',
    color: 'white',
    padding: '16px 24px',
    borderRadius: '16px 16px 0 0',
  },
  modeToggle: {
    backgroundColor: 'rgba(255,255,255,0.1)',
    borderRadius: '12px',
    '& .MuiToggleButton-root': {
      color: 'rgba(255,255,255,0.7)',
      border: 'none',
      padding: '8px 16px',
      textTransform: 'none',
      fontWeight: 600,
      '&.Mui-selected': {
        color: 'white',
        backgroundColor: 'rgba(255,255,255,0.2)',
      },
      '&:hover': {
        backgroundColor: 'rgba(255,255,255,0.15)',
      },
    },
  },
  content: {
    height: 'calc(100% - 72px)', // Subtract header height
    overflow: 'hidden',
  },
};

// ═══════════════════════════════════════════════════════════════════════════════
// MAIN COMPONENT
// ═══════════════════════════════════════════════════════════════════════════════

export default function AgentScenarioBuilder({
  open,
  onClose,
  sessionId,
  sessionProfile = null,
  // Agent callbacks
  onAgentCreated,
  onAgentUpdated,
  existingAgentConfig = null,
  agentEditMode = false,
  // Scenario callbacks
  onScenarioCreated,
  onScenarioUpdated,
  existingScenarioConfig = null,
  scenarioEditMode = false,
  // Initial mode
  initialMode = 'agents',
}) {
  // Mode state: 'agents' or 'scenarios'
  const [mode, setMode] = useState(initialMode);

  const handleModeChange = useCallback((event, newMode) => {
    if (newMode !== null) {
      setMode(newMode);
    }
  }, []);

  const handleClose = useCallback(() => {
    onClose();
  }, [onClose]);

  const getModeTitle = () => {
    if (mode === 'agents') {
      return agentEditMode ? 'Editing Session Agent' : 'Create Custom Agent';
    }
    return scenarioEditMode ? 'Editing Session Scenario' : 'Create Custom Scenario';
  };

  const getModeDescription = () => {
    if (mode === 'agents') {
      return 'Configure AI agents with custom prompts, tools, and voice settings';
    }
    return 'Design agent orchestration flows with handoffs and routing';
  };

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      maxWidth="lg"
      fullWidth
      sx={styles.dialog}
    >
      {/* Header with mode toggle */}
      <DialogTitle sx={styles.header}>
        <Stack direction="row" alignItems="center" justifyContent="space-between">
          <Stack direction="row" alignItems="center" spacing={2}>
            <Avatar
              sx={{
                bgcolor: 'rgba(255,255,255,0.15)',
                width: 40,
                height: 40,
              }}
            >
              {mode === 'agents' ? (
                agentEditMode ? <EditIcon /> : <SmartToyIcon />
              ) : (
                scenarioEditMode ? <EditIcon /> : <HubIcon />
              )}
            </Avatar>
            <Box>
              <Typography variant="h6" sx={{ fontWeight: 700 }}>
                {mode === 'agents' ? 'Agent Builder' : 'Scenario Builder'}
              </Typography>
              <Typography variant="caption" sx={{ opacity: 0.8 }}>
                {getModeDescription()}
              </Typography>
            </Box>
          </Stack>

          <Stack direction="row" alignItems="center" spacing={3}>
            {/* Mode toggle */}
            <ToggleButtonGroup
              value={mode}
              exclusive
              onChange={handleModeChange}
              size="small"
              sx={styles.modeToggle}
            >
              <ToggleButton value="agents">
                <Tooltip title="Configure individual agents">
                  <Stack direction="row" alignItems="center" spacing={1}>
                    <SmartToyIcon fontSize="small" />
                    <span>Agents</span>
                  </Stack>
                </Tooltip>
              </ToggleButton>
              <ToggleButton value="scenarios">
                <Tooltip title="Design agent orchestration flows">
                  <Stack direction="row" alignItems="center" spacing={1}>
                    <HubIcon fontSize="small" />
                    <span>Scenarios</span>
                  </Stack>
                </Tooltip>
              </ToggleButton>
            </ToggleButtonGroup>

            {/* Session info */}
            <Box
              sx={{
                px: 1.5,
                py: 0.75,
                borderRadius: '999px',
                backgroundColor: 'rgba(255,255,255,0.12)',
                border: '1px solid rgba(255,255,255,0.2)',
                display: 'flex',
                alignItems: 'center',
                gap: 1,
              }}
            >
              <Typography variant="caption" sx={{ color: 'white', opacity: 0.8 }}>
                Session
              </Typography>
              <Typography variant="body2" sx={{ color: 'white', fontFamily: 'monospace' }}>
                {sessionId || 'none'}
              </Typography>
            </Box>

            <IconButton onClick={handleClose} sx={{ color: 'white' }}>
              <CloseIcon />
            </IconButton>
          </Stack>
        </Stack>
      </DialogTitle>

      {/* Content - switches between Agent and Scenario builder */}
      <Box sx={styles.content}>
        {mode === 'agents' ? (
          <AgentBuilderContent
            sessionId={sessionId}
            sessionProfile={sessionProfile}
            onAgentCreated={(config) => {
              if (onAgentCreated) onAgentCreated(config);
            }}
            onAgentUpdated={(config) => {
              if (onAgentUpdated) onAgentUpdated(config);
            }}
            existingConfig={existingAgentConfig}
            editMode={agentEditMode}
          />
        ) : (
          <ScenarioBuilder
            sessionId={sessionId}
            onScenarioCreated={onScenarioCreated}
            onScenarioUpdated={onScenarioUpdated}
            existingConfig={existingScenarioConfig}
            editMode={scenarioEditMode}
          />
        )}
      </Box>
    </Dialog>
  );
}
