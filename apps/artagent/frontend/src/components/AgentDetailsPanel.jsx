import React, { useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  Box,
  Chip,
  Button,
  Divider,
  IconButton,
  Typography,
} from '@mui/material';
import SmartToyRoundedIcon from '@mui/icons-material/SmartToyRounded';
import CloseRoundedIcon from '@mui/icons-material/CloseRounded';
import PersonRoundedIcon from '@mui/icons-material/PersonRounded';
import BuildRoundedIcon from '@mui/icons-material/BuildRounded';
import TimelineRoundedIcon from '@mui/icons-material/TimelineRounded';

const PanelCard = ({ title, icon, children, collapsible, defaultOpen = true }) => {
  const [expanded, setExpanded] = useState(defaultOpen);

  return (
    <Box
      sx={{
        borderRadius: '18px',
        border: '1px solid rgba(226,232,240,0.9)',
        background: 'linear-gradient(135deg, rgba(248,250,252,0.96), rgba(255,255,255,0.92))',
        boxShadow: '0 8px 22px rgba(15,23,42,0.08)',
        p: 2,
        mb: 2,
      }}
    >
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          mb: (collapsible && !expanded) ? 0 : 1,
          cursor: collapsible ? 'pointer' : 'default',
        }}
        onClick={() => collapsible && setExpanded(!expanded)}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          {icon}
          <Typography sx={{ fontWeight: 700, color: '#0f172a', fontSize: '12px', letterSpacing: '0.5px' }}>
            {title}
          </Typography>
        </Box>
        {collapsible && (
          <Typography sx={{ fontSize: '10px', color: '#94a3b8', fontWeight: 600 }}>
            {expanded ? 'Hide' : 'Show'}
          </Typography>
        )}
      </Box>
      {(!collapsible || expanded) && children}
    </Box>
  );
};

const SummaryRow = ({ label, value }) => (
  <Box sx={{ display: 'flex', justifyContent: 'space-between', py: 0.5, gap: 1 }}>
    <Typography sx={{ color: '#475569', fontWeight: 600, fontSize: '11px' }}>{label}</Typography>
    <Typography sx={{ color: '#0f172a', fontWeight: 600, fontSize: '12px', textAlign: 'right', flex: 1 }}>
      {value || '—'}
    </Typography>
  </Box>
);

const AgentDetailsPanel = ({
  open,
  onClose,
  agentName,
  agentDescription,
  sessionId,
  lastUserMessage,
  lastAssistantMessage,
  recentTools = [],
  messages = [],
  agentTools = [],
  handoffTools = [],
}) => {
  const toolRows = useMemo(
    () => recentTools.slice(0, 5),
    [recentTools],
  );
  const recentMessages = useMemo(
    () => (messages || []).slice(-12).reverse(),
    [messages],
  );

  if (!open) return null;

  return createPortal(
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        bottom: 0,
        width: '340px',
        background: 'linear-gradient(180deg, #f8fafc, #ffffff)',
        borderRight: '1px solid rgba(226,232,240,0.8)',
        boxShadow: '8px 0 24px rgba(15,23,42,0.12)',
        zIndex: 1200,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        resize: 'horizontal',
        minWidth: '280px',
        maxWidth: '520px',
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', p: 2, pb: 1.5, cursor: 'grab' }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <SmartToyRoundedIcon sx={{ color: '#0ea5e9' }} fontSize="small" />
          <Box>
            <Typography sx={{ fontWeight: 800, fontSize: '15px', color: '#0f172a' }}>Agent Details</Typography>
            <Typography sx={{ fontSize: '11px', color: '#64748b' }}>Debug context for current session</Typography>
          </Box>
        </Box>
        <IconButton size="small" onClick={onClose}>
          <CloseRoundedIcon fontSize="small" />
        </IconButton>
      </Box>
      <Divider />
      <Box
        sx={{
          p: 2,
          overflowY: 'auto',
          scrollbarWidth: 'none',
          '&::-webkit-scrollbar': { display: 'none' },
          maxHeight: '100%',
        }}
      >
        <PanelCard
          title="Active Agent"
          icon={<SmartToyRoundedIcon sx={{ fontSize: 16, color: '#0ea5e9' }} />}
        >
          <Typography sx={{ fontSize: '18px', fontWeight: 800, color: '#0f172a', mb: 0.5 }}>
            {agentName || 'Unknown'}
          </Typography>
          {agentDescription && (
            <Typography sx={{ fontSize: '12px', color: '#475569', mb: 1 }}>
              {agentDescription}
            </Typography>
          )}
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mb: 1 }}>
            {agentName && (
              <Chip
                size="small"
                label={agentName}
                icon={<SmartToyRoundedIcon fontSize="small" />}
                sx={{ background: 'rgba(14,165,233,0.12)', color: '#0ea5e9', fontWeight: 700 }}
              />
            )}
            {sessionId && (
              <Chip
                size="small"
                label={`Session: ${sessionId}`}
                sx={{ background: 'rgba(99,102,241,0.12)', color: '#4338ca', fontWeight: 700 }}
              />
            )}
          </Box>
        </PanelCard>

        <PanelCard
          title={`Agent Tools (${agentTools.length || 0})`}
          icon={<BuildRoundedIcon sx={{ fontSize: 16, color: '#0ea5e9' }} />}
          collapsible
          defaultOpen={true}
        >
          {agentTools.length === 0 ? (
            <Typography sx={{ fontSize: '12px', color: '#94a3b8' }}>
              No tools registered for this agent.
            </Typography>
          ) : (
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.75 }}>
              {agentTools.map((tool) => {
                const isHandoff = handoffTools.includes(tool);
                return (
                  <Chip
                    key={tool}
                    label={tool}
                    size="small"
                    icon={isHandoff ? <TimelineRoundedIcon fontSize="small" /> : <BuildRoundedIcon fontSize="small" />}
                    sx={{
                      borderRadius: '10px',
                      fontWeight: 700,
                      borderColor: isHandoff ? 'rgba(234,88,12,0.5)' : 'rgba(14,165,233,0.5)',
                      background: isHandoff ? 'rgba(234,88,12,0.08)' : 'rgba(14,165,233,0.08)',
                      color: isHandoff ? '#ea580c' : '#0ea5e9',
                    }}
                    variant="outlined"
                  />
                );
              })}
            </Box>
          )}
        </PanelCard>

        <PanelCard
          title="Latest Turns"
          icon={<TimelineRoundedIcon sx={{ fontSize: 16, color: '#6366f1' }} />}
          collapsible
          defaultOpen={false}
        >
          <SummaryRow label="Last User" value={lastUserMessage || '—'} />
          <SummaryRow label="Last Assistant" value={lastAssistantMessage || '—'} />
        </PanelCard>

        <PanelCard
          title="Conversation Context"
          icon={<TimelineRoundedIcon sx={{ fontSize: 16, color: '#0ea5e9' }} />}
          collapsible
          defaultOpen={false}
        >
          {recentMessages.length === 0 && (
            <Typography sx={{ fontSize: '12px', color: '#94a3b8' }}>
              No messages yet.
            </Typography>
          )}
          {recentMessages.map((msg, idx) => {
            const speaker = msg.speaker || "Assistant";
            const tone = speaker === "User" ? "#2563eb" : speaker === "System" ? "#6b7280" : "#0ea5e9";
            return (
              <Box
                key={`${msg.turnId || msg.id || idx}-${idx}`}
                sx={{
                  borderRadius: '10px',
                  border: '1px solid rgba(226,232,240,0.9)',
                  background: 'rgba(248,250,252,0.8)',
                  p: 1,
                  mb: 1,
                }}
              >
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                  <Chip
                    label={speaker}
                    size="small"
                    sx={{
                      height: 22,
                      fontSize: '11px',
                      fontWeight: 700,
                      color: tone,
                      borderColor: `${tone}66`,
                      backgroundColor: `${tone}10`,
                    }}
                    variant="outlined"
                  />
                  {msg.turnId && (
                    <Typography sx={{ fontSize: '10px', color: '#94a3b8' }}>
                      {msg.turnId}
                    </Typography>
                  )}
                </Box>
                <Typography sx={{ fontSize: '12px', color: '#0f172a', whiteSpace: 'pre-wrap' }}>
                  {msg.text || msg.content || '(no text)'}
                </Typography>
              </Box>
            );
          })}
        </PanelCard>

        <PanelCard
          title="Recent Tools"
          icon={<BuildRoundedIcon sx={{ fontSize: 16, color: '#22c55e' }} />}
        >
          {toolRows.length === 0 && (
            <Typography sx={{ fontSize: '12px', color: '#94a3b8' }}>No tools invoked yet.</Typography>
          )}
          {toolRows.map((tool) => (
            <Box
              key={tool.id || tool.ts || tool.tool}
              sx={{
                borderRadius: '12px',
                border: '1px solid rgba(226,232,240,0.9)',
                background: 'rgba(34,197,94,0.04)',
                p: 1,
                mb: 1,
              }}
            >
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <BuildRoundedIcon sx={{ fontSize: 16, color: '#22c55e' }} />
                <Typography sx={{ fontWeight: 700, fontSize: '12px', color: '#0f172a' }}>
                  {tool.tool || tool.name || 'Tool'}
                </Typography>
              </Box>
              <Typography sx={{ fontSize: '11px', color: '#64748b', mt: 0.5 }}>
                {tool.text || tool.detail || tool.status || 'invoked'}
              </Typography>
            </Box>
          ))}
        </PanelCard>

        <PanelCard
          title="Session Snapshot"
          icon={<PersonRoundedIcon sx={{ fontSize: 16, color: '#f97316' }} />}
        >
          <SummaryRow label="Speaker" value={lastAssistantMessage ? agentName || 'Assistant' : '—'} />
          <SummaryRow label="Last User Turn" value={lastUserMessage ? 'Captured' : '—'} />
          <SummaryRow label="Tool Count" value={agentTools.length ? agentTools.length.toString() : '0'} />
        </PanelCard>

      </Box>
    </div>,
    document.body,
  );
};

export default AgentDetailsPanel;
