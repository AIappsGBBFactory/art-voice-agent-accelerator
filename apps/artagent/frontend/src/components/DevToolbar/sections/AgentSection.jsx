/**
 * AgentSection - Shows current agent details
 * Mirrors the "Active Agent" card from AgentDetailsPanel
 */
import React, { useState } from 'react';
import SmartToyRoundedIcon from '@mui/icons-material/SmartToyRounded';
import BuildRoundedIcon from '@mui/icons-material/BuildRounded';
import AccountTreeRoundedIcon from '@mui/icons-material/AccountTreeRounded';
import ContentCopyRoundedIcon from '@mui/icons-material/ContentCopyRounded';
import CheckRoundedIcon from '@mui/icons-material/CheckRounded';

const styles = {
  // Main agent card
  agentCard: {
    background: 'linear-gradient(135deg, rgba(248,250,252,0.96), rgba(255,255,255,0.92))',
    borderRadius: 16,
    border: '1px solid rgba(226,232,240,0.9)',
    boxShadow: '0 4px 16px rgba(15,23,42,0.06)',
    padding: 16,
    marginBottom: 16,
  },
  agentHeader: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: 12,
    marginBottom: 12,
  },
  agentIcon: {
    width: 44,
    height: 44,
    borderRadius: 12,
    background: 'linear-gradient(135deg, #0ea5e9, #6366f1)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    boxShadow: '0 4px 12px rgba(14,165,233,0.3)',
    flexShrink: 0,
  },
  agentInfo: {
    flex: 1,
    minWidth: 0,
  },
  agentName: {
    fontSize: 18,
    fontWeight: 800,
    color: '#0f172a',
    marginBottom: 2,
    letterSpacing: '-0.01em',
  },
  activeBadge: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 4,
    fontSize: 10,
    fontWeight: 700,
    padding: '3px 8px',
    borderRadius: 6,
    background: 'rgba(34,197,94,0.1)',
    color: '#16a34a',
    border: '1px solid rgba(34,197,94,0.2)',
    marginLeft: 8,
  },
  activeDot: {
    width: 6,
    height: 6,
    borderRadius: '50%',
    background: '#22c55e',
    animation: 'pulse 2s infinite',
  },
  description: {
    fontSize: 12,
    color: '#64748b',
    lineHeight: 1.5,
    marginTop: 4,
  },
  
  // Session info row
  sessionRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    marginTop: 12,
    padding: '10px 12px',
    background: 'rgba(99,102,241,0.06)',
    borderRadius: 10,
    border: '1px solid rgba(99,102,241,0.12)',
  },
  sessionLabel: {
    fontSize: 10,
    fontWeight: 700,
    color: '#6366f1',
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
  },
  sessionId: {
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
    borderRadius: 4,
    transition: 'background 0.15s',
  },

  // Stats summary
  statsGrid: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: 8,
    marginTop: 12,
  },
  statCard: {
    background: '#f8fafc',
    borderRadius: 10,
    padding: '10px 12px',
    border: '1px solid #e2e8f0',
  },
  statValue: {
    fontSize: 20,
    fontWeight: 800,
    color: '#0f172a',
  },
  statLabel: {
    fontSize: 10,
    fontWeight: 600,
    color: '#94a3b8',
    textTransform: 'uppercase',
    marginTop: 2,
  },

  // Tools section
  sectionHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 20,
    marginBottom: 10,
  },
  sectionTitle: {
    fontSize: 11,
    fontWeight: 700,
    color: '#64748b',
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
    display: 'flex',
    alignItems: 'center',
    gap: 6,
  },
  sectionCount: {
    fontSize: 10,
    fontWeight: 700,
    color: '#fff',
    background: '#0ea5e9',
    padding: '2px 6px',
    borderRadius: 10,
    minWidth: 18,
    textAlign: 'center',
  },
  toolsGrid: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 6,
  },
  toolChip: (isHandoff) => ({
    display: 'inline-flex',
    alignItems: 'center',
    gap: 4,
    fontSize: 11,
    fontWeight: 600,
    padding: '5px 10px',
    borderRadius: 8,
    background: isHandoff ? 'rgba(234,88,12,0.08)' : 'rgba(14,165,233,0.08)',
    color: isHandoff ? '#ea580c' : '#0ea5e9',
    border: `1px solid ${isHandoff ? 'rgba(234,88,12,0.25)' : 'rgba(14,165,233,0.25)'}`,
    transition: 'all 0.15s ease',
    cursor: 'default',
  }),
  emptyTools: {
    fontSize: 12,
    color: '#94a3b8',
    fontStyle: 'italic',
    padding: '12px 0',
  },
};

const AgentSection = ({ 
  name, 
  description, 
  tools = [], 
  handoffTools = [],
  sessionId,
}) => {
  const [copied, setCopied] = useState(false);
  
  const regularTools = tools.filter((t) => !handoffTools.includes(t));
  const totalTools = tools.length;

  const handleCopySession = () => {
    if (sessionId) {
      navigator.clipboard.writeText(sessionId);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div>
      {/* Agent Identity Card */}
      <div style={styles.agentCard}>
        <div style={styles.agentHeader}>
          <div style={styles.agentIcon}>
            <SmartToyRoundedIcon sx={{ fontSize: 24, color: '#fff' }} />
          </div>
          <div style={styles.agentInfo}>
            <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap' }}>
              <span style={styles.agentName}>{name || 'Unknown'}</span>
              <span style={styles.activeBadge}>
                <span style={styles.activeDot} />
                ACTIVE
              </span>
            </div>
            {description && (
              <p style={styles.description}>{description}</p>
            )}
          </div>
        </div>

        {/* Session ID */}
        {sessionId && (
          <div style={styles.sessionRow}>
            <span style={styles.sessionLabel}>Session</span>
            <span style={styles.sessionId}>{sessionId}</span>
            <button 
              style={styles.copyBtn} 
              onClick={handleCopySession}
              title="Copy session ID"
            >
              {copied ? (
                <CheckRoundedIcon sx={{ fontSize: 14, color: '#22c55e' }} />
              ) : (
                <ContentCopyRoundedIcon sx={{ fontSize: 14 }} />
              )}
            </button>
          </div>
        )}

        {/* Quick Stats */}
        <div style={styles.statsGrid}>
          <div style={styles.statCard}>
            <div style={styles.statValue}>{totalTools}</div>
            <div style={styles.statLabel}>Tools</div>
          </div>
          <div style={styles.statCard}>
            <div style={styles.statValue}>{handoffTools.length}</div>
            <div style={styles.statLabel}>Handoffs</div>
          </div>
        </div>
      </div>

      {/* Agent Tools */}
      <div style={styles.sectionHeader}>
        <span style={styles.sectionTitle}>
          <BuildRoundedIcon sx={{ fontSize: 14, color: '#0ea5e9' }} />
          Agent Tools
        </span>
        {regularTools.length > 0 && (
          <span style={styles.sectionCount}>{regularTools.length}</span>
        )}
      </div>
      
      {regularTools.length === 0 ? (
        <div style={styles.emptyTools}>No tools registered for this agent.</div>
      ) : (
        <div style={styles.toolsGrid}>
          {regularTools.map((tool) => (
            <span key={tool} style={styles.toolChip(false)}>
              <BuildRoundedIcon sx={{ fontSize: 12 }} />
              {tool}
            </span>
          ))}
        </div>
      )}

      {/* Handoff Tools */}
      {handoffTools.length > 0 && (
        <>
          <div style={styles.sectionHeader}>
            <span style={styles.sectionTitle}>
              <AccountTreeRoundedIcon sx={{ fontSize: 14, color: '#ea580c' }} />
              Handoff Tools
            </span>
            <span style={{ ...styles.sectionCount, background: '#ea580c' }}>
              {handoffTools.length}
            </span>
          </div>
          <div style={styles.toolsGrid}>
            {handoffTools.map((tool) => (
              <span key={tool} style={styles.toolChip(true)}>
                <AccountTreeRoundedIcon sx={{ fontSize: 12 }} />
                {tool}
              </span>
            ))}
          </div>
        </>
      )}
    </div>
  );
};

export default AgentSection;
