/**
 * CustomerResearchPanel Component
 * ================================
 *
 * Dialog for researching a company and auto-building voice-agent scenarios.
 *
 * Flow:
 *   1. User enters a company name (+ optional industry / use case) and clicks "Research"
 *   2. Backend calls Azure OpenAI to generate use-case proposals with value props
 *   3. User reviews use-case cards and clicks "Build This Scenario"
 *   4. Backend creates agents, tools, and scenario for the session
 *   5. User can "View Scenario Details" for agent graph, demo script, pitch
 *   6. User can export/import scenarios as YAML
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
  Collapse,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  IconButton,
  LinearProgress,
  Paper,
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
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import VisibilityIcon from '@mui/icons-material/Visibility';
import FileDownloadIcon from '@mui/icons-material/FileDownload';
import FileUploadIcon from '@mui/icons-material/FileUpload';
import TrendingUpIcon from '@mui/icons-material/TrendingUp';
import CampaignIcon from '@mui/icons-material/Campaign';
import DescriptionIcon from '@mui/icons-material/Description';
import ChatIcon from '@mui/icons-material/Chat';
import ReportProblemIcon from '@mui/icons-material/ReportProblem';

import { API_BASE_URL } from '../config/constants.js';

// ═══════════════════════════════════════════════════════════════════════════════
// STYLES
// ═══════════════════════════════════════════════════════════════════════════════

const styles = {
  dialog: {
    '& .MuiDialog-paper': {
      maxWidth: '1100px',
      width: '92vw',
      maxHeight: '88vh',
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
    mb: 1,
    alignItems: 'flex-start',
  },
  optionalInputs: {
    display: 'flex',
    gap: 2,
    mb: 3,
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
  agentChip: { fontSize: '0.75rem' },
  toolChip: { fontSize: '0.7rem', height: '22px' },
  detailSection: {
    p: 2,
    mb: 2,
    bgcolor: 'grey.50',
    borderRadius: 2,
    border: '1px solid',
    borderColor: 'divider',
  },
  graphNode: {
    px: 2,
    py: 1.5,
    borderRadius: 2,
    border: '2px solid',
    textAlign: 'center',
    minWidth: 120,
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
// YAML EXPORT / IMPORT HELPERS
// ═══════════════════════════════════════════════════════════════════════════════

function useCaseToYaml(useCase) {
  const lines = [];
  const indent = (n) => '  '.repeat(n);

  lines.push(`name: "${useCase.name}"`);
  lines.push(`description: "${(useCase.description || '').replace(/"/g, '\\"')}"`);
  lines.push(`icon: "${useCase.icon || '🎯'}"`);
  lines.push(`industry: "${useCase.industry || ''}"`);
  lines.push(`start_agent: "${useCase.start_agent}"`);

  // Value proposition fields
  if (useCase.value_proposition) {
    lines.push(`value_proposition: "${useCase.value_proposition.replace(/"/g, '\\"')}"`);
  }
  if (useCase.pain_points?.length) {
    lines.push('pain_points:');
    useCase.pain_points.forEach((p) => lines.push(`${indent(1)}- "${p.replace(/"/g, '\\"')}"`));
  }
  if (useCase.seller_pitch) {
    lines.push(`seller_pitch: "${useCase.seller_pitch.replace(/"/g, '\\"')}"`);
  }
  if (useCase.estimated_monthly_callers) {
    lines.push(`estimated_monthly_callers: ${useCase.estimated_monthly_callers}`);
  }
  if (useCase.avg_cost_per_contact) {
    lines.push(`avg_cost_per_contact: ${useCase.avg_cost_per_contact}`);
  }
  if (useCase.estimated_annual_savings) {
    lines.push(`estimated_annual_savings: "${useCase.estimated_annual_savings.replace(/"/g, '\\"')}"`);
  }
  if (useCase.roi_summary) {
    lines.push(`roi_summary: "${useCase.roi_summary.replace(/"/g, '\\"')}"`);
  }
  if (useCase.conversation_examples?.length) {
    lines.push('conversation_examples:');
    useCase.conversation_examples.forEach((ex) => {
      lines.push(`${indent(1)}- title: "${(ex.title || '').replace(/"/g, '\\"')}"`);
      lines.push(`${indent(2)}flow: |`);
      (ex.flow || '').split('\n').forEach((l) => lines.push(`${indent(3)}${l}`));
      lines.push(`${indent(2)}demo_script: |`);
      (ex.demo_script || '').split('\n').forEach((l) => lines.push(`${indent(3)}${l}`));
    });
  }

  lines.push('template_vars:');
  Object.entries(useCase.template_vars || {}).forEach(([k, v]) => {
    lines.push(`${indent(1)}${k}: "${v}"`);
  });

  lines.push('agents:');
  (useCase.agents || []).forEach((a) => {
    lines.push(`${indent(1)}- name: "${a.name}"`);
    lines.push(`${indent(2)}description: "${(a.description || '').replace(/"/g, '\\"')}"`);
    lines.push(`${indent(2)}greeting: "${(a.greeting || '').replace(/"/g, '\\"')}"`);
    lines.push(`${indent(2)}return_greeting: "${(a.return_greeting || '').replace(/"/g, '\\"')}"`);
    lines.push(`${indent(2)}handoff_trigger: "${a.handoff_trigger || ''}"`);
    lines.push(`${indent(2)}tools:`);
    (a.tools || []).forEach((t) => lines.push(`${indent(3)}- "${t}"`));
    lines.push(`${indent(2)}prompt: |`);
    (a.prompt || '').split('\n').forEach((l) => lines.push(`${indent(3)}${l}`));
  });

  lines.push('tools:');
  (useCase.tools || []).forEach((t) => {
    lines.push(`${indent(1)}- name: "${t.name}"`);
    lines.push(`${indent(2)}description: "${(t.description || '').replace(/"/g, '\\"')}"`);
    lines.push(`${indent(2)}mock_response: '${t.mock_response || '{}'}'`);
    lines.push(`${indent(2)}required_params:`);
    (t.required_params || []).forEach((p) => lines.push(`${indent(3)}- "${p}"`));
    lines.push(`${indent(2)}parameters:`);
    (t.parameters || []).forEach((p) => {
      lines.push(`${indent(3)}- name: "${p.name}"`);
      lines.push(`${indent(4)}type: "${p.type}"`);
      lines.push(`${indent(4)}description: "${(p.description || '').replace(/"/g, '\\"')}"`);
    });
  });

  lines.push('handoffs:');
  (useCase.handoffs || []).forEach((h) => {
    lines.push(`${indent(1)}- from_agent: "${h.from_agent}"`);
    lines.push(`${indent(2)}to_agent: "${h.to_agent}"`);
    lines.push(`${indent(2)}tool: "${h.tool}"`);
    lines.push(`${indent(2)}type: "${h.type || 'discrete'}"`);
    lines.push(`${indent(2)}handoff_condition: "${(h.handoff_condition || '').replace(/"/g, '\\"')}"`);
  });

  return lines.join('\n');
}

function downloadYaml(useCase) {
  const yaml = useCaseToYaml(useCase);
  const blob = new Blob([yaml], { type: 'text/yaml' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${(useCase.name || 'scenario').replace(/\s+/g, '_').toLowerCase()}.yaml`;
  a.click();
  URL.revokeObjectURL(url);
}

// Minimal YAML parser — handles the subset our export produces
function parseSimpleYaml(text) {
  try {
    // Use JSON round-trip via a simple line-by-line parser
    // For robustness, we'll try to parse the YAML as JSON-like structure
    const lines = text.split('\n');
    const result = {};
    let currentKey = null;
    let currentArray = null;
    let currentObj = null;
    let blockScalar = null;
    let blockIndent = 0;
    let blockLines = [];

    const setValue = (obj, key, val) => {
      if (typeof val === 'string') {
        // Strip surrounding quotes
        val = val.replace(/^["']|["']$/g, '');
      }
      obj[key] = val;
    };

    // For complex nested YAML, fall back to JSON parse of a simplified conversion
    // Actually, let's just store raw text and re-parse at build time
    return { _raw_yaml: text };
  } catch {
    return null;
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
// MAIN COMPONENT
// ═══════════════════════════════════════════════════════════════════════════════

export default function CustomerResearchPanel({ open, onClose, sessionId, onBuilt }) {
  const [companyName, setCompanyName] = useState('');
  const [industry, setIndustry] = useState('');
  const [useCaseHint, setUseCaseHint] = useState('');
  const [researching, setResearching] = useState(false);
  const [building, setBuilding] = useState(null);
  const [builtIndex, setBuiltIndex] = useState(null);
  const [researchResult, setResearchResult] = useState(null);
  const [error, setError] = useState(null);
  const [buildResult, setBuildResult] = useState(null);
  const [progressStep, setProgressStep] = useState(0);
  const [detailsIndex, setDetailsIndex] = useState(null); // which use case details view is open
  const progressTimer = useRef(null);
  const fileInputRef = useRef(null);

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
    setDetailsIndex(null);

    try {
      const body = { company_name: companyName.trim() };
      if (industry.trim()) body.industry = industry.trim();
      if (useCaseHint.trim()) body.use_case_hint = useCaseHint.trim();

      const resp = await fetch(`${API_BASE_URL}/api/v1/customer-research/research`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
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
  }, [companyName, industry, useCaseHint]);

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
          body: JSON.stringify({ session_id: sessionId, use_case: useCase }),
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
    [sessionId, onBuilt],
  );

  // ─── Import ────────────────────────────────────────────────────────────────
  const handleImport = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const handleFileSelected = useCallback(
    (e) => {
      const file = e.target.files?.[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = async (ev) => {
        try {
          const text = ev.target.result;
          // Send raw YAML to backend to parse and build
          if (!sessionId) {
            setError('No active session. Please start a session first.');
            return;
          }
          const resp = await fetch(`${API_BASE_URL}/api/v1/customer-research/import`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: sessionId, yaml_content: text }),
          });
          if (!resp.ok) {
            const detail = await resp.json().catch(() => ({}));
            throw new Error(detail.detail || `Import failed (${resp.status})`);
          }
          const data = await resp.json();
          setBuildResult(data);
          if (onBuilt) onBuilt(data);
        } catch (err) {
          setError(err.message);
        }
      };
      reader.readAsText(file);
      // Reset so same file can be re-imported
      e.target.value = '';
    },
    [sessionId, onBuilt],
  );

  // ─── Key handler ───────────────────────────────────────────────────────────
  const handleKeyDown = useCallback(
    (e) => {
      if (e.key === 'Enter' && !researching) handleResearch();
    },
    [handleResearch, researching],
  );

  const handleClose = useCallback(() => onClose(), [onClose]);

  // ─── Details view active? ─────────────────────────────────────────────────
  const showingDetails = detailsIndex !== null && researchResult?.use_cases?.[detailsIndex];
  const detailUseCase = showingDetails ? researchResult.use_cases[detailsIndex] : null;

  return (
    <Dialog open={open} onClose={handleClose} sx={styles.dialog} maxWidth={false}>
      {/* ── Header ──────────────────────────────────────────────────── */}
      <DialogTitle sx={styles.header}>
        <Stack direction="row" alignItems="center" justifyContent="space-between">
          <Stack direction="row" alignItems="center" spacing={1.5}>
            {showingDetails && (
              <IconButton onClick={() => setDetailsIndex(null)} sx={{ color: 'white' }}>
                <ArrowBackIcon />
              </IconButton>
            )}
            <Avatar sx={{ bgcolor: 'rgba(255,255,255,0.15)' }}>
              <BusinessIcon />
            </Avatar>
            <Box>
              <Typography variant="h6" fontWeight={700}>
                {showingDetails ? `${detailUseCase.icon} ${detailUseCase.name}` : 'Customer Research'}
              </Typography>
              <Typography variant="caption" sx={{ opacity: 0.8 }}>
                {showingDetails
                  ? 'Scenario details, agent graph, and demo guidance'
                  : 'Research a company and auto-build a voice-agent scenario'}
              </Typography>
            </Box>
          </Stack>
          <IconButton onClick={handleClose} sx={{ color: 'white' }}>
            <CloseIcon />
          </IconButton>
        </Stack>
      </DialogTitle>

      <DialogContent sx={{ pt: 3, pb: 2 }}>
        {/* ═══════════════════════════════════════════════════════════════
            DETAILS VIEW
            ═══════════════════════════════════════════════════════════════ */}
        {showingDetails ? (
          <ScenarioDetailsView useCase={detailUseCase} isBuilt={builtIndex === detailsIndex} />
        ) : (
          <>
            {/* ── Search Bar ──────────────────────────────────────────── */}
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

            {/* ── Optional Inputs ─────────────────────────────────────── */}
            <Box sx={styles.optionalInputs}>
              <TextField
                label="Industry (optional)"
                placeholder="e.g. Aviation, Healthcare, Retail…"
                value={industry}
                onChange={(e) => setIndustry(e.target.value)}
                disabled={researching}
                size="small"
                sx={{ flex: 1 }}
              />
              <TextField
                label="Specific Use Case (optional)"
                placeholder="e.g. Flight rebooking and delay notifications…"
                value={useCaseHint}
                onChange={(e) => setUseCaseHint(e.target.value)}
                disabled={researching}
                size="small"
                sx={{ flex: 2 }}
              />
            </Box>

            {/* ── Error ───────────────────────────────────────────────── */}
            {error && (
              <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
                {error}
              </Alert>
            )}

            {/* ── Research Progress ───────────────────────────────────── */}
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

            {/* ── Build Success ────────────────────────────────────────── */}
            {buildResult && (
              <Alert severity="success" sx={{ mb: 2 }} icon={<CheckCircleIcon />}>
                <strong>Scenario &quot;{buildResult.scenario_name}&quot; built!</strong> Created{' '}
                {buildResult.agents_created.length} agents and {buildResult.tools_created.length} tools.
                The scenario is now active — you can start a voice session.
              </Alert>
            )}

            {/* ── Company Summary ──────────────────────────────────────── */}
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

                <Stack spacing={2}>
                  {researchResult.use_cases.map((uc, idx) => (
                    <UseCaseCard
                      key={idx}
                      useCase={uc}
                      index={idx}
                      isBuilding={building === idx}
                      isBuilt={builtIndex === idx}
                      onBuild={() => handleBuild(uc, idx)}
                      onViewDetails={() => setDetailsIndex(idx)}
                      onExport={() => downloadYaml(uc)}
                    />
                  ))}
                </Stack>
              </>
            )}

            {/* ── Empty State ──────────────────────────────────────────── */}
            {!researchResult && !researching && !error && (
              <Box sx={{ textAlign: 'center', py: 6, color: 'text.secondary' }}>
                <BusinessIcon sx={{ fontSize: 48, mb: 1, opacity: 0.3 }} />
                <Typography variant="body1">Enter a company name to get started</Typography>
                <Typography variant="body2" sx={{ mt: 0.5, opacity: 0.7 }}>
                  We'll research the company and propose voice-agent use cases you can build instantly
                </Typography>
              </Box>
            )}
          </>
        )}
      </DialogContent>

      <DialogActions sx={{ px: 3, pb: 2 }}>
        <input
          type="file"
          ref={fileInputRef}
          accept=".yaml,.yml"
          style={{ display: 'none' }}
          onChange={handleFileSelected}
        />
        <Button onClick={handleImport} startIcon={<FileUploadIcon />} color="inherit" sx={{ mr: 'auto' }}>
          Import Scenario
        </Button>
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

function UseCaseCard({ useCase, index, isBuilding, isBuilt, onBuild, onViewDetails, onExport }) {
  return (
    <Card sx={{ ...styles.useCaseCard, ...(isBuilt ? styles.builtCard : {}) }} variant="outlined">
      <CardContent>
        <Stack direction="row" alignItems="flex-start" justifyContent="space-between">
          <Box sx={{ flex: 1 }}>
            <Stack direction="row" alignItems="center" spacing={1} mb={0.5}>
              <Typography variant="h6" fontSize="1.05rem">
                {useCase.icon} {useCase.name}
              </Typography>
              {isBuilt && <Chip label="Active" size="small" color="success" icon={<CheckCircleIcon />} />}
            </Stack>
            <Typography variant="body2" color="text.secondary" mb={1}>
              {useCase.description}
            </Typography>

            {/* Value Proposition Summary */}
            {useCase.value_proposition && (
              <Box sx={{ p: 1.5, bgcolor: 'primary.50', borderRadius: 1, mb: 1.5, border: '1px solid', borderColor: 'primary.100' }}>
                <Stack direction="row" spacing={0.5} alignItems="center" mb={0.5}>
                  <TrendingUpIcon fontSize="small" color="primary" />
                  <Typography variant="caption" fontWeight={700} color="primary.main">
                    Value Proposition
                  </Typography>
                </Stack>
                <Typography variant="body2" fontSize="0.82rem" mb={1}>
                  {useCase.value_proposition}
                </Typography>
                {(useCase.estimated_monthly_callers > 0 || useCase.avg_cost_per_contact > 0) && (
                  <Stack direction="row" spacing={2} flexWrap="wrap">
                    {useCase.estimated_monthly_callers > 0 && (
                      <Chip
                        label={`~${useCase.estimated_monthly_callers.toLocaleString()} calls/mo`}
                        size="small"
                        color="info"
                        variant="outlined"
                        sx={{ fontSize: '0.7rem' }}
                      />
                    )}
                    {useCase.avg_cost_per_contact > 0 && (
                      <Chip
                        label={`$${useCase.avg_cost_per_contact.toFixed(2)} avg cost/contact`}
                        size="small"
                        color="info"
                        variant="outlined"
                        sx={{ fontSize: '0.7rem' }}
                      />
                    )}
                    {useCase.estimated_annual_savings && (
                      <Chip
                        label={useCase.estimated_annual_savings}
                        size="small"
                        color="success"
                        variant="outlined"
                        sx={{ fontSize: '0.7rem' }}
                      />
                    )}
                  </Stack>
                )}
              </Box>
            )}
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

      <CardActions sx={{ px: 2, pb: 2, gap: 1 }}>
        <Button
          variant={isBuilt ? 'outlined' : 'contained'}
          color={isBuilt ? 'success' : 'primary'}
          startIcon={
            isBuilding ? <CircularProgress size={18} color="inherit" /> : isBuilt ? <CheckCircleIcon /> : <BuildIcon />
          }
          onClick={onBuild}
          disabled={isBuilding || isBuilt}
          size="small"
        >
          {isBuilding ? 'Building…' : isBuilt ? 'Scenario Active' : 'Build This Scenario'}
        </Button>
        <Button
          variant="outlined"
          size="small"
          startIcon={<VisibilityIcon />}
          onClick={onViewDetails}
        >
          View Scenario Details
        </Button>
        <Button
          variant="text"
          size="small"
          startIcon={<FileDownloadIcon />}
          onClick={onExport}
          sx={{ ml: 'auto' }}
        >
          Export
        </Button>
      </CardActions>
    </Card>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// SCENARIO DETAILS VIEW
// ═══════════════════════════════════════════════════════════════════════════════

function ScenarioDetailsView({ useCase, isBuilt }) {
  const startAgent = useCase.agents?.find((a) => a.name === useCase.start_agent);
  const subAgents = useCase.agents?.filter((a) => a.name !== useCase.start_agent) || [];

  return (
    <Box>
      {/* ── Description ───────────────────────────────────────────── */}
      <Typography variant="body2" color="text.secondary" mb={3}>
        {useCase.description}
      </Typography>

      {/* ── Agent Graph ───────────────────────────────────────────── */}
      <Box sx={styles.detailSection}>
        <Typography variant="subtitle2" fontWeight={700} mb={2}>
          <AccountTreeIcon fontSize="small" sx={{ verticalAlign: 'middle', mr: 0.5 }} />
          Agent Architecture
        </Typography>

        <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
          {/* Start Agent (Orchestrator) */}
          <Paper sx={{ ...styles.graphNode, borderColor: 'primary.main', bgcolor: 'primary.50' }} elevation={0}>
            <Typography variant="caption" color="primary.main" fontWeight={700}>
              ORCHESTRATOR
            </Typography>
            <Typography variant="subtitle2" fontWeight={700}>
              {startAgent?.name || useCase.start_agent}
            </Typography>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
              {startAgent?.description}
            </Typography>
            {startAgent?.tools?.length > 0 && (
              <Stack direction="row" flexWrap="wrap" gap={0.5} mt={1} justifyContent="center">
                {startAgent.tools.map((t) => (
                  <Chip key={t} label={t} size="small" sx={{ fontSize: '0.65rem', height: 20 }} variant="outlined" />
                ))}
              </Stack>
            )}
          </Paper>

          {/* Connection lines */}
          {subAgents.length > 0 && (
            <Typography variant="body2" color="text.disabled" sx={{ fontSize: '1.2rem' }}>
              {'┃'}
            </Typography>
          )}

          {/* Sub-agents */}
          <Stack direction="row" flexWrap="wrap" gap={2} justifyContent="center">
            {subAgents.map((agent) => {
              const agentTools = agent.tools || [];
              const incomingHandoff = useCase.handoffs?.find((h) => h.to_agent === agent.name);
              return (
                <Paper
                  key={agent.name}
                  sx={{ ...styles.graphNode, borderColor: 'secondary.main', bgcolor: 'grey.50', maxWidth: 220 }}
                  elevation={0}
                >
                  <Typography variant="caption" color="secondary.main" fontWeight={700}>
                    SPECIALIST
                  </Typography>
                  <Typography variant="subtitle2" fontWeight={700}>
                    {agent.name}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
                    {agent.description}
                  </Typography>
                  {incomingHandoff && (
                    <Typography variant="caption" color="text.disabled" sx={{ display: 'block', fontStyle: 'italic', mb: 0.5 }}>
                      ← {incomingHandoff.handoff_condition}
                    </Typography>
                  )}
                  {agentTools.length > 0 && (
                    <Stack direction="row" flexWrap="wrap" gap={0.5} mt={0.5} justifyContent="center">
                      {agentTools.map((t) => (
                        <Chip key={t} label={t} size="small" sx={{ fontSize: '0.65rem', height: 20 }} variant="outlined" />
                      ))}
                    </Stack>
                  )}
                </Paper>
              );
            })}
          </Stack>
        </Box>
      </Box>

      {/* ── Value Proposition (full — shown when built) ────────────── */}
      {isBuilt && useCase.value_proposition && (
        <Box sx={styles.detailSection}>
          <Typography variant="subtitle2" fontWeight={700} mb={1}>
            <TrendingUpIcon fontSize="small" sx={{ verticalAlign: 'middle', mr: 0.5 }} />
            Value Proposition &amp; Business Case
          </Typography>
          <Typography variant="body2" mb={2}>
            {useCase.value_proposition}
          </Typography>

          {/* ROI Metrics */}
          {(useCase.estimated_monthly_callers > 0 || useCase.avg_cost_per_contact > 0) && (
            <Paper sx={{ p: 2, bgcolor: 'info.50', border: '1px solid', borderColor: 'info.200', borderRadius: 1, mb: 2 }} elevation={0}>
              <Typography variant="caption" fontWeight={700} color="info.main" sx={{ display: 'block', mb: 1 }}>
                📊 ROI ESTIMATE
              </Typography>
              <Stack direction="row" spacing={3} flexWrap="wrap" mb={1}>
                {useCase.estimated_monthly_callers > 0 && (
                  <Box>
                    <Typography variant="h6" fontWeight={700} color="info.main">
                      {useCase.estimated_monthly_callers.toLocaleString()}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">calls / month</Typography>
                  </Box>
                )}
                {useCase.avg_cost_per_contact > 0 && (
                  <Box>
                    <Typography variant="h6" fontWeight={700} color="info.main">
                      ${useCase.avg_cost_per_contact.toFixed(2)}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">avg cost / contact</Typography>
                  </Box>
                )}
                {useCase.estimated_annual_savings && (
                  <Box>
                    <Typography variant="h6" fontWeight={700} color="success.main">
                      {useCase.estimated_annual_savings}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">est. annual savings</Typography>
                  </Box>
                )}
              </Stack>
              {useCase.roi_summary && (
                <Typography variant="body2" sx={{ mt: 1, fontStyle: 'italic' }}>
                  {useCase.roi_summary}
                </Typography>
              )}
            </Paper>
          )}

          {useCase.pain_points?.length > 0 && (
            <>
              <Typography variant="subtitle2" fontWeight={700} mb={1}>
                <ReportProblemIcon fontSize="small" sx={{ verticalAlign: 'middle', mr: 0.5 }} />
                Pain Points Addressed
              </Typography>
              <Box component="ul" sx={{ pl: 3, mb: 2 }}>
                {useCase.pain_points.map((p, i) => (
                  <Typography component="li" variant="body2" key={i} sx={{ mb: 0.5 }}>
                    {p}
                  </Typography>
                ))}
              </Box>
            </>
          )}

          {useCase.seller_pitch && (
            <>
              <Typography variant="subtitle2" fontWeight={700} mb={1}>
                <CampaignIcon fontSize="small" sx={{ verticalAlign: 'middle', mr: 0.5 }} />
                Seller Pitch
              </Typography>
              <Paper sx={{ p: 2, bgcolor: 'warning.50', border: '1px solid', borderColor: 'warning.200', borderRadius: 1, mb: 2 }} elevation={0}>
                <Typography variant="body2" fontStyle="italic">
                  &ldquo;{useCase.seller_pitch}&rdquo;
                </Typography>
              </Paper>
            </>
          )}
        </Box>
      )}

      {/* ── Value prop summary (when not yet built) ───────────────── */}
      {!isBuilt && useCase.value_proposition && (
        <Box sx={styles.detailSection}>
          <Typography variant="subtitle2" fontWeight={700} mb={1}>
            <TrendingUpIcon fontSize="small" sx={{ verticalAlign: 'middle', mr: 0.5 }} />
            Value Proposition
          </Typography>
          <Typography variant="body2" mb={1}>
            {useCase.value_proposition}
          </Typography>
          {(useCase.estimated_monthly_callers > 0 || useCase.estimated_annual_savings) && (
            <Stack direction="row" spacing={2} flexWrap="wrap" mb={1}>
              {useCase.estimated_monthly_callers > 0 && (
                <Chip
                  label={`~${useCase.estimated_monthly_callers.toLocaleString()} calls/mo`}
                  size="small"
                  color="info"
                  variant="outlined"
                  sx={{ fontSize: '0.7rem' }}
                />
              )}
              {useCase.estimated_annual_savings && (
                <Chip
                  label={useCase.estimated_annual_savings}
                  size="small"
                  color="success"
                  variant="outlined"
                  sx={{ fontSize: '0.7rem' }}
                />
              )}
            </Stack>
          )}
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
            Build this scenario to see the full pitch, pain points analysis, and ROI breakdown.
          </Typography>
        </Box>
      )}

      {/* ── Conversation Examples with Demo Scripts ────────────────── */}
      {useCase.conversation_examples?.length > 0 && (
        <Box sx={styles.detailSection}>
          <Typography variant="subtitle2" fontWeight={700} mb={2}>
            <ChatIcon fontSize="small" sx={{ verticalAlign: 'middle', mr: 0.5 }} />
            Example Conversation Flows
          </Typography>
          <Stack spacing={2}>
            {useCase.conversation_examples.map((ex, i) => (
              <Paper key={i} sx={{ p: 0, bgcolor: 'background.paper', borderRadius: 1, border: '1px solid', borderColor: 'divider', overflow: 'hidden' }} elevation={0}>
                <Box sx={{ p: 2, bgcolor: 'grey.50', borderBottom: '1px solid', borderColor: 'divider' }}>
                  <Typography variant="subtitle2" fontWeight={700}>
                    {ex.title || `Example ${i + 1}`}
                  </Typography>
                </Box>
                <Box sx={{ p: 2 }}>
                  <Typography variant="caption" fontWeight={700} color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
                    🎤 Customer Opens With
                  </Typography>
                  <Paper sx={{ p: 1.5, bgcolor: 'primary.50', borderRadius: 1, border: '1px solid', borderColor: 'primary.100', mb: 2 }} elevation={0}>
                    <Typography variant="body2" fontStyle="italic">
                      &ldquo;{typeof ex === 'string' ? ex : ex.flow}&rdquo;
                    </Typography>
                  </Paper>
                  {(typeof ex !== 'string' && ex.demo_script) && (
                    <>
                      <Typography variant="caption" fontWeight={700} color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
                        <DescriptionIcon fontSize="small" sx={{ verticalAlign: 'middle', mr: 0.5, fontSize: '0.9rem' }} />
                        Step-by-Step Demo Flow
                      </Typography>
                      <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', color: 'text.secondary' }}>
                        {ex.demo_script}
                      </Typography>
                    </>
                  )}
                </Box>
              </Paper>
            ))}
          </Stack>
        </Box>
      )}

      {/* ── Tools Detail ──────────────────────────────────────────── */}
      <Box sx={styles.detailSection}>
        <Typography variant="subtitle2" fontWeight={700} mb={2}>
          <HandymanIcon fontSize="small" sx={{ verticalAlign: 'middle', mr: 0.5 }} />
          Tools ({useCase.tools?.length || 0})
        </Typography>
        <Stack spacing={1}>
          {useCase.tools?.map((tool) => (
            <Box key={tool.name} sx={{ pl: 1 }}>
              <Typography variant="body2" fontWeight={600}>
                {tool.name}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {tool.description}
              </Typography>
              {tool.parameters?.length > 0 && (
                <Stack direction="row" flexWrap="wrap" gap={0.5} mt={0.5}>
                  {tool.parameters.map((p) => (
                    <Chip key={p.name} label={`${p.name}: ${p.type}`} size="small" sx={{ fontSize: '0.65rem', height: 18 }} />
                  ))}
                </Stack>
              )}
            </Box>
          ))}
        </Stack>
      </Box>
    </Box>
  );
}
