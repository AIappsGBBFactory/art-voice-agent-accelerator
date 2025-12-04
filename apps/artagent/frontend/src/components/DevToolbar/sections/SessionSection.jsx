/**
 * SessionSection - Shows session info, latest turns, and snapshot
 * Mirrors "Latest Turns" + "Session Snapshot" from AgentDetailsPanel
 */
import React, { useState, useEffect } from 'react';
import TimelineRoundedIcon from '@mui/icons-material/TimelineRounded';
import PersonRoundedIcon from '@mui/icons-material/PersonRounded';
import SmartToyRoundedIcon from '@mui/icons-material/SmartToyRounded';
import ContentCopyRoundedIcon from '@mui/icons-material/ContentCopyRounded';
import CheckRoundedIcon from '@mui/icons-material/CheckRounded';
import FiberManualRecordRoundedIcon from '@mui/icons-material/FiberManualRecordRounded';

const styles = {
  // Status card
  statusCard: {
    background: 'linear-gradient(135deg, rgba(99,102,241,0.06), rgba(255,255,255,0.9))',
    borderRadius: 14,
    border: '1px solid rgba(99,102,241,0.15)',
    padding: 16,
    marginBottom: 16,
  },
  statusHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 12,
  },
  statusBadge: (connected) => ({
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    padding: '6px 12px',
    borderRadius: 20,
    fontSize: 11,
    fontWeight: 700,
    background: connected ? 'rgba(34,197,94,0.1)' : 'rgba(239,68,68,0.1)',
    color: connected ? '#16a34a' : '#dc2626',
    border: `1px solid ${connected ? 'rgba(34,197,94,0.2)' : 'rgba(239,68,68,0.2)'}`,
  }),
  liveDot: {
    width: 8,
    height: 8,
    borderRadius: '50%',
    background: '#22c55e',
    animation: 'pulse 2s infinite',
  },
  sessionIdRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    background: '#f8fafc',
    borderRadius: 8,
    padding: '8px 10px',
    border: '1px solid #e2e8f0',
  },
  sessionLabel: {
    fontSize: 10,
    fontWeight: 700,
    color: '#6366f1',
    textTransform: 'uppercase',
  },
  sessionIdValue: {
    fontSize: 11,
    fontWeight: 600,
    color: '#4338ca',
    fontFamily: 'ui-monospace, monospace',
    flex: 1,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  copyBtn: {
    background: 'none',
    border: 'none',
    padding: 4,
    cursor: 'pointer',
    color: '#6366f1',
    display: 'flex',
    alignItems: 'center',
  },

  // Stats grid
  statsGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(3, 1fr)',
    gap: 8,
    marginBottom: 16,
  },
  statCard: {
    background: '#fff',
    borderRadius: 10,
    padding: 12,
    textAlign: 'center',
    border: '1px solid #e2e8f0',
    boxShadow: '0 2px 8px rgba(0,0,0,0.03)',
  },
  statValue: {
    fontSize: 22,
    fontWeight: 800,
    color: '#0f172a',
  },
  statLabel: {
    fontSize: 9,
    fontWeight: 700,
    color: '#94a3b8',
    textTransform: 'uppercase',
    letterSpacing: '0.3px',
    marginTop: 2,
  },

  // Section header
  sectionHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    marginBottom: 10,
    marginTop: 20,
  },
  sectionTitle: {
    fontSize: 11,
    fontWeight: 700,
    color: '#64748b',
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
  },

  // Latest turns card
  turnCard: {
    background: '#fff',
    borderRadius: 12,
    border: '1px solid #e2e8f0',
    marginBottom: 8,
    overflow: 'hidden',
  },
  turnHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    padding: '10px 12px',
    background: '#f8fafc',
    borderBottom: '1px solid #e2e8f0',
  },
  turnAvatar: (isUser) => ({
    width: 28,
    height: 28,
    borderRadius: 8,
    background: isUser ? '#2563eb' : 'linear-gradient(135deg, #0ea5e9, #6366f1)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  }),
  turnLabel: {
    fontSize: 11,
    fontWeight: 700,
    color: '#0f172a',
    textTransform: 'uppercase',
  },
  turnContent: {
    padding: '10px 12px',
    fontSize: 12,
    color: '#334155',
    lineHeight: 1.5,
    maxHeight: 80,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  },
  emptyTurn: {
    padding: '10px 12px',
    fontSize: 12,
    color: '#94a3b8',
    fontStyle: 'italic',
  },

  // Summary row
  summaryRow: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '8px 0',
    borderBottom: '1px solid #f1f5f9',
  },
  summaryLabel: {
    fontSize: 12,
    fontWeight: 600,
    color: '#64748b',
  },
  summaryValue: {
    fontSize: 12,
    fontWeight: 700,
    color: '#0f172a',
  },
};

const SessionSection = ({ 
  sessionId, 
  connected = true,
  messageCount = 0,
  agentSwitches = 0,
  toolCount = 0,
  lastUserMessage,
  lastAssistantMessage,
  agentName,
}) => {
  const [copied, setCopied] = useState(false);
  const [duration, setDuration] = useState('00:00');

  const handleCopy = () => {
    if (sessionId) {
      navigator.clipboard.writeText(sessionId);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div>
      {/* Status Card */}
      <div style={styles.statusCard}>
        <div style={styles.statusHeader}>
          <span style={styles.statusBadge(connected)}>
            {connected && <span style={styles.liveDot} />}
            {connected ? 'Session Active' : 'Disconnected'}
          </span>
        </div>
        <div style={styles.sessionIdRow}>
          <span style={styles.sessionLabel}>ID</span>
          <span style={styles.sessionIdValue}>
            {sessionId || 'No session'}
          </span>
          {sessionId && (
            <button style={styles.copyBtn} onClick={handleCopy}>
              {copied ? (
                <CheckRoundedIcon sx={{ fontSize: 14, color: '#22c55e' }} />
              ) : (
                <ContentCopyRoundedIcon sx={{ fontSize: 14 }} />
              )}
            </button>
          )}
        </div>
      </div>

      {/* Quick Stats */}
      <div style={styles.statsGrid}>
        <div style={styles.statCard}>
          <div style={styles.statValue}>{messageCount}</div>
          <div style={styles.statLabel}>Messages</div>
        </div>
        <div style={styles.statCard}>
          <div style={styles.statValue}>{agentSwitches}</div>
          <div style={styles.statLabel}>Handoffs</div>
        </div>
        <div style={styles.statCard}>
          <div style={styles.statValue}>{toolCount}</div>
          <div style={styles.statLabel}>Tools</div>
        </div>
      </div>

      {/* Latest Turns */}
      <div style={styles.sectionHeader}>
        <TimelineRoundedIcon sx={{ fontSize: 14, color: '#6366f1' }} />
        <span style={styles.sectionTitle}>Latest Turns</span>
      </div>

      <div style={styles.turnCard}>
        <div style={styles.turnHeader}>
          <div style={styles.turnAvatar(true)}>
            <PersonRoundedIcon sx={{ fontSize: 16, color: '#fff' }} />
          </div>
          <span style={styles.turnLabel}>Last User</span>
        </div>
        {lastUserMessage ? (
          <div style={styles.turnContent}>{lastUserMessage}</div>
        ) : (
          <div style={styles.emptyTurn}>No user message captured</div>
        )}
      </div>

      <div style={styles.turnCard}>
        <div style={styles.turnHeader}>
          <div style={styles.turnAvatar(false)}>
            <SmartToyRoundedIcon sx={{ fontSize: 16, color: '#fff' }} />
          </div>
          <span style={styles.turnLabel}>Last Assistant</span>
        </div>
        {lastAssistantMessage ? (
          <div style={styles.turnContent}>{lastAssistantMessage}</div>
        ) : (
          <div style={styles.emptyTurn}>No assistant response yet</div>
        )}
      </div>

      {/* Session Snapshot */}
      <div style={styles.sectionHeader}>
        <PersonRoundedIcon sx={{ fontSize: 14, color: '#f97316' }} />
        <span style={styles.sectionTitle}>Session Snapshot</span>
      </div>

      <div style={{ background: '#fff', borderRadius: 12, border: '1px solid #e2e8f0', padding: '4px 14px' }}>
        <div style={styles.summaryRow}>
          <span style={styles.summaryLabel}>Active Speaker</span>
          <span style={styles.summaryValue}>{agentName || 'Assistant'}</span>
        </div>
        <div style={styles.summaryRow}>
          <span style={styles.summaryLabel}>User Turn</span>
          <span style={styles.summaryValue}>{lastUserMessage ? 'Captured' : '—'}</span>
        </div>
        <div style={{ ...styles.summaryRow, borderBottom: 'none' }}>
          <span style={styles.summaryLabel}>Tool Count</span>
          <span style={styles.summaryValue}>{toolCount}</span>
        </div>
      </div>
    </div>
  );
};

export default SessionSection;
