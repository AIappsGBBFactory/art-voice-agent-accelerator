/**
 * CustomerResearchPanel Component
 * ================================
 *
 * Dialog for researching a company and auto-building voice-agent scenarios.
 *
 * Flow:
 *   1. User enters a company name and clicks "Research"
 *   2. Backend calls Azure OpenAI to generate use-case proposals
 *   3. User reviews use-case cards and clicks "Build This Scenario"
 *   4. Backend creates agents, tools, and scenario for the session
 *   5. The scenario is set as active — user can start a voice session
 */

import React, { useState, useCallback, useEffect, useRef } from 'react';
import {
  Avatar,
  Box,
  Button,
  Card,
  CardContent,
  CardActions,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  IconButton,
  LinearProgress,
  Stack,
  TextField,
  Tooltip,
  Typography,
  Alert,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import SearchIcon from '@mui/icons-material/Search';
import BuildIcon from '@mui/icons-material/Build';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import HandymanIcon from '@mui/icons-material/Handyman';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import BusinessIcon from '@mui/icons-material/Business';

import { API_BASE_URL } from '../config/constants.js';

// ═══════════════════════════════════════════════════════════════════════════════
// STYLES
// ═══════════════════════════════════════════════════════════════════════════════

const styles = {
  dialog: {
    '& .MuiDialog-paper': {
      maxWidth: '1000px',
      width: '90vw',
      maxHeight: '85vh',
      borderRadius: '16px',
    },
  },
  header: {
    background: 'linear-gradient(135deg, #1a237e 0%, #283593 50%, #3949ab 100%)',
    color: 'white',
    padding: '16px 24px',
    borderRadius: '16px 16px 0 0',
  },
  searchBox: {
    display: 'flex',
    gap: 2,
    mt: 3,
    mb: 3,
    alignItems: 'flex-start',
  },
  useCaseCard: {
    borderRadius: '12px',
    border: '1px solid',
    borderColor: 'divider',
    transition: 'box-shadow 0.2s, border-color 0.2s',
    '&:hover': {
      boxShadow: 3,
      borderColor: 'primary.main',
    },
  },
  builtCard: {
    borderColor: 'success.main',
    backgroundColor: 'success.50',
  },
  agentChip: {
    fontSize: '0.75rem',
  },
  toolChip: {
    fontSize: '0.7rem',
    height: '22px',
  },
};

// ═══════════════════════════════════════════════════════════════════════════════
// RESEARCH PROGRESS STEPS
// ═══════════════════════════════════════════════════════════════════════════════

const RESEARCH_STEPS = [
  { label: 'Analyzing company profile…', duration: 3000 },
  { label: 'Identifying industry pain points…', duration: 5000 },
  { label: 'Designing multi-agent architectures…', duration: 7000 },
  { label: 'Generating tool specifications…', duration: 5000 },
  { label: 'Building handoff graphs…', duration: 4000 },
  { label: 'Finalizing use case proposals…', duration: 3000 },
];

// ═══════════════════════════════════════════════════════════════════════════════
// COMPONENT
// ═══════════════════════════════════════════════════════════════════════════════

export default function CustomerResearchPanel({ open, onClose, sessionId, onBuilt }) {
  const [companyName, setCompanyName] = useState('');
  const [researching, setResearching] = useState(false);
  const [building, setBuilding] = useState(null); // index of use case being built
  const [builtIndex, setBuiltIndex] = useState(null); // index of successfully built use case
  const [researchResult, setResearchResult] = useState(null);
  const [error, setError] = useState(null);
  const [buildResult, setBuildResult] = useState(null);
  const [progressStep, setProgressStep] = useState(0);
  const progressTimer = useRef(null);

  // Progress animation while researching
  useEffect(() => {
    if (researching) {
      setProgressStep(0);
      let step = 0;
      const advance = () => {
        step += 1;
        if (step < RESEARCH_STEPS.length) {
          setProgressStep(step);
          progressTimer.current = setTimeout(advance, RESEARCH_STEPS[step].duration);
        }
      };
      progressTimer.current = setTimeout(advance, RESEARCH_STEPS[0].duration);
    } else {
      if (progressTimer.current) clearTimeout(progressTimer.current);
      progressTimer.current = null;
    }
    return () => {
      if (progressTimer.current) clearTimeout(progressTimer.current);
    };
  }, [researching]);

  // ─── Research ──────────────────────────────────────────────────────────────
  const handleResearch = useCallback(async () => {
    if (!companyName.trim()) return;

    setResearching(true);
    setError(null);
    setResearchResult(null);
    setBuiltIndex(null);
    setBuildResult(null);

    try {
      const resp = await fetch(`${API_BASE_URL}/api/v1/customer-research/research`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ company_name: companyName.trim() }),
      });

      if (!resp.ok) {
        const detail = await resp.json().catch(() => ({}));
        throw new Error(detail.detail || `Research failed (${resp.status})`);
      }

      const data = await resp.json();
      setResearchResult(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setResearching(false);
    }
  }, [companyName]);

  // ─── Build ─────────────────────────────────────────────────────────────────
  const handleBuild = useCallback(
    async (useCase, index) => {
      if (!sessionId) {
        setError('No active session. Please start a session first.');
        return;
      }

      setBuilding(index);
      setError(null);
      setBuildResult(null);

      try {
        const resp = await fetch(`${API_BASE_URL}/api/v1/customer-research/build`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            session_id: sessionId,
            use_case: useCase,
          }),
        });

        if (!resp.ok) {
          const detail = await resp.json().catch(() => ({}));
          throw new Error(detail.detail || `Build failed (${resp.status})`);
        }

        const data = await resp.json();
        setBuildResult(data);
        setBuiltIndex(index);
        if (onBuilt) onBuilt(data);
      } catch (err) {
        setError(err.message);
      } finally {
        setBuilding(null);
      }
    },
    [sessionId],
  );

  // ─── Key handler ───────────────────────────────────────────────────────────
  const handleKeyDown = useCallback(
    (e) => {
      if (e.key === 'Enter' && !researching) {
        handleResearch();
      }
    },
    [handleResearch, researching],
  );

  // ─── Reset on close ───────────────────────────────────────────────────────
  const handleClose = useCallback(() => {
    onClose();
  }, [onClose]);

  return (
    <Dialog open={open} onClose={handleClose} sx={styles.dialog} maxWidth={false}>
      {/* ── Header ──────────────────────────────────────────────────────── */}
      <DialogTitle sx={styles.header}>
        <Stack direction="row" alignItems="center" justifyContent="space-between">
          <Stack direction="row" alignItems="center" spacing={1.5}>
            <Avatar sx={{ bgcolor: 'rgba(255,255,255,0.15)' }}>
              <BusinessIcon />
            </Avatar>
            <Box>
              <Typography variant="h6" fontWeight={700}>
                Customer Research
              </Typography>
              <Typography variant="caption" sx={{ opacity: 0.8 }}>
                Research a company and auto-build a voice-agent scenario
              </Typography>
            </Box>
          </Stack>
          <IconButton onClick={handleClose} sx={{ color: 'white' }}>
            <CloseIcon />
          </IconButton>
        </Stack>
      </DialogTitle>

      <DialogContent sx={{ pt: 3, pb: 2 }}>
        {/* ── Search Bar ──────────────────────────────────────────────── */}
        <Box sx={styles.searchBox}>
          <TextField
            fullWidth
            label="Company Name"
            placeholder="e.g. Contoso, Northwind Traders, Fabrikam…"
            value={companyName}
            onChange={(e) => setCompanyName(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={researching}
            size="small"
          />
          <Button
            variant="contained"
            startIcon={researching ? <CircularProgress size={18} color="inherit" /> : <SearchIcon />}
            onClick={handleResearch}
            disabled={researching || !companyName.trim()}
            sx={{ minWidth: 140, height: 40 }}
          >
            {researching ? 'Researching…' : 'Research'}
          </Button>
        </Box>

        {/* ── Error ───────────────────────────────────────────────────── */}
        {error && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        {/* ── Research Progress ─────────────────────────────────────── */}
        {researching && (
          <Box sx={{ mb: 3, p: 3, bgcolor: 'grey.50', borderRadius: 2 }}>
            <Stack direction="row" alignItems="center" spacing={2} mb={2}>
              <CircularProgress size={24} />
              <Typography variant="subtitle2" fontWeight={600}>
                Researching {companyName}…
              </Typography>
            </Stack>
            <LinearProgress
              variant="determinate"
              value={Math.min(((progressStep + 1) / RESEARCH_STEPS.length) * 100, 95)}
              sx={{ mb: 2, borderRadius: 1, height: 6 }}
            />
            <Stack spacing={0.5}>
              {RESEARCH_STEPS.map((step, i) => (
                <Typography
                  key={i}
                  variant="body2"
                  sx={{
                    color: i <= progressStep ? 'text.primary' : 'text.disabled',
                    fontWeight: i === progressStep ? 600 : 400,
                    transition: 'all 0.3s ease',
                  }}
                >
                  {i < progressStep ? '✓' : i === progressStep ? '⟳' : '○'} {step.label}
                </Typography>
              ))}
            </Stack>
          </Box>
        )}

        {/* ── Build Success ───────────────────────────────────────────── */}
        {buildResult && (
          <Alert severity="success" sx={{ mb: 2 }} icon={<CheckCircleIcon />}>
            <strong>Scenario "{buildResult.scenario_name}" built!</strong> Created{' '}
            {buildResult.agents_created.length} agents and {buildResult.tools_created.length} tools.
            The scenario is now active — you can start a voice session.
          </Alert>
        )}

        {/* ── Company Summary ─────────────────────────────────────────── */}
        {researchResult && (
          <>
            <Box sx={{ mb: 3, p: 2, bgcolor: 'grey.50', borderRadius: 2 }}>
              <Stack direction="row" alignItems="center" spacing={1} mb={1}>
                <Typography variant="subtitle1" fontWeight={700}>
                  {researchResult.company_name}
                </Typography>
                <Chip label={researchResult.industry} size="small" color="primary" variant="outlined" />
              </Stack>
              <Typography variant="body2" color="text.secondary">
                {researchResult.company_summary}
              </Typography>
            </Box>

            <Typography variant="subtitle2" fontWeight={700} mb={2}>
              Proposed Use Cases ({researchResult.use_cases.length})
            </Typography>

            {/* ── Use Case Cards ─────────────────────────────────────── */}
            <Stack spacing={2}>
              {researchResult.use_cases.map((uc, idx) => (
                <UseCaseCard
                  key={idx}
                  useCase={uc}
                  index={idx}
                  isBuilding={building === idx}
                  isBuilt={builtIndex === idx}
                  onBuild={() => handleBuild(uc, idx)}
                />
              ))}
            </Stack>
          </>
        )}

        {/* ── Empty State ─────────────────────────────────────────────── */}
        {!researchResult && !researching && !error && (
          <Box sx={{ textAlign: 'center', py: 6, color: 'text.secondary' }}>
            <BusinessIcon sx={{ fontSize: 48, mb: 1, opacity: 0.3 }} />
            <Typography variant="body1">
              Enter a company name to get started
            </Typography>
            <Typography variant="body2" sx={{ mt: 0.5, opacity: 0.7 }}>
              We'll research the company and propose voice-agent use cases you can build instantly
            </Typography>
          </Box>
        )}
      </DialogContent>

      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={handleClose} color="inherit">
          Close
        </Button>
      </DialogActions>
    </Dialog>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// USE CASE CARD SUB-COMPONENT
// ═══════════════════════════════════════════════════════════════════════════════

function UseCaseCard({ useCase, index, isBuilding, isBuilt, onBuild }) {
  return (
    <Card sx={{ ...styles.useCaseCard, ...(isBuilt ? styles.builtCard : {}) }} variant="outlined">
      <CardContent>
        <Stack direction="row" alignItems="flex-start" justifyContent="space-between">
          <Box sx={{ flex: 1 }}>
            <Stack direction="row" alignItems="center" spacing={1} mb={0.5}>
              <Typography variant="h6" fontSize="1.05rem">
                {useCase.icon} {useCase.name}
              </Typography>
              {isBuilt && (
                <Chip
                  label="Built"
                  size="small"
                  color="success"
                  icon={<CheckCircleIcon />}
                />
              )}
            </Stack>
            <Typography variant="body2" color="text.secondary" mb={1.5}>
              {useCase.description}
            </Typography>
          </Box>
        </Stack>

        <Divider sx={{ mb: 1.5 }} />

        {/* Agents */}
        <Stack direction="row" alignItems="center" spacing={0.5} mb={1}>
          <SmartToyIcon fontSize="small" color="action" />
          <Typography variant="caption" fontWeight={600} color="text.secondary">
            Agents ({useCase.agents?.length || 0}):
          </Typography>
        </Stack>
        <Stack direction="row" flexWrap="wrap" gap={0.5} mb={1.5}>
          {useCase.agents?.map((agent) => (
            <Tooltip key={agent.name} title={agent.description} arrow>
              <Chip
                label={agent.name}
                size="small"
                sx={styles.agentChip}
                color={agent.name === useCase.start_agent ? 'primary' : 'default'}
                variant={agent.name === useCase.start_agent ? 'filled' : 'outlined'}
              />
            </Tooltip>
          ))}
        </Stack>

        {/* Tools */}
        <Stack direction="row" alignItems="center" spacing={0.5} mb={1}>
          <HandymanIcon fontSize="small" color="action" />
          <Typography variant="caption" fontWeight={600} color="text.secondary">
            Tools ({useCase.tools?.length || 0}):
          </Typography>
        </Stack>
        <Stack direction="row" flexWrap="wrap" gap={0.5} mb={1.5}>
          {useCase.tools?.map((tool) => (
            <Tooltip key={tool.name} title={tool.description} arrow>
              <Chip label={tool.name} size="small" sx={styles.toolChip} variant="outlined" />
            </Tooltip>
          ))}
        </Stack>

        {/* Handoffs */}
        <Stack direction="row" alignItems="center" spacing={0.5} mb={1}>
          <AccountTreeIcon fontSize="small" color="action" />
          <Typography variant="caption" fontWeight={600} color="text.secondary">
            Handoffs ({useCase.handoffs?.length || 0}):
          </Typography>
        </Stack>
        <Stack direction="row" flexWrap="wrap" gap={0.5}>
          {useCase.handoffs?.map((h, i) => (
            <Chip
              key={i}
              label={`${h.from_agent} → ${h.to_agent}`}
              size="small"
              sx={styles.toolChip}
              variant="outlined"
              color="secondary"
            />
          ))}
        </Stack>
      </CardContent>

      <CardActions sx={{ px: 2, pb: 2 }}>
        <Button
          variant={isBuilt ? 'outlined' : 'contained'}
          color={isBuilt ? 'success' : 'primary'}
          startIcon={
            isBuilding ? (
              <CircularProgress size={18} color="inherit" />
            ) : isBuilt ? (
              <CheckCircleIcon />
            ) : (
              <BuildIcon />
            )
          }
          onClick={onBuild}
          disabled={isBuilding || isBuilt}
          size="small"
        >
          {isBuilding ? 'Building…' : isBuilt ? 'Scenario Active' : 'Build This Scenario'}
        </Button>
      </CardActions>
    </Card>
  );
}
