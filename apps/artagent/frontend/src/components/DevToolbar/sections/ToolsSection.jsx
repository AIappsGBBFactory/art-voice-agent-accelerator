/**
 * ToolsSection - Shows tool invocation history
 * Mirrors "Recent Tools" from AgentDetailsPanel
 */
import React, { useState } from 'react';
import BuildRoundedIcon from '@mui/icons-material/BuildRounded';
import CheckCircleRoundedIcon from '@mui/icons-material/CheckCircleRounded';
import ErrorRoundedIcon from '@mui/icons-material/ErrorRounded';
import ScheduleRoundedIcon from '@mui/icons-material/ScheduleRounded';
import ExpandMoreRoundedIcon from '@mui/icons-material/ExpandMoreRounded';
import ExpandLessRoundedIcon from '@mui/icons-material/ExpandLessRounded';

const styles = {
  emptyState: {
    textAlign: 'center',
    padding: '40px 20px',
  },
  emptyIcon: {
    width: 56,
    height: 56,
    borderRadius: 16,
    background: 'linear-gradient(135deg, rgba(34,197,94,0.1), rgba(34,197,94,0.05))',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    margin: '0 auto 12px',
  },
  emptyTitle: {
    fontSize: 14,
    fontWeight: 700,
    color: '#0f172a',
    marginBottom: 4,
  },
  emptySubtitle: {
    fontSize: 12,
    color: '#94a3b8',
  },
  
  // Tool card styles
  toolCard: {
    background: 'linear-gradient(135deg, rgba(34,197,94,0.04), rgba(255,255,255,0.9))',
    borderRadius: 12,
    border: '1px solid rgba(226,232,240,0.9)',
    marginBottom: 10,
    overflow: 'hidden',
    transition: 'all 0.2s ease',
  },
  toolHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '12px 14px',
    cursor: 'pointer',
    transition: 'background 0.15s ease',
  },
  toolHeaderLeft: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    flex: 1,
    minWidth: 0,
  },
  toolIcon: {
    width: 32,
    height: 32,
    borderRadius: 8,
    background: 'rgba(34,197,94,0.1)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },
  toolInfo: {
    flex: 1,
    minWidth: 0,
  },
  toolName: {
    fontSize: 13,
    fontWeight: 700,
    color: '#0f172a',
    marginBottom: 2,
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  },
  toolMeta: {
    fontSize: 11,
    color: '#64748b',
    display: 'flex',
    alignItems: 'center',
    gap: 6,
  },
  statusDot: (status) => ({
    width: 6,
    height: 6,
    borderRadius: '50%',
    background: status === 'success' ? '#22c55e' : status === 'pending' ? '#f59e0b' : '#ef4444',
  }),
  toolHeaderRight: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  timestamp: {
    fontSize: 10,
    color: '#94a3b8',
    fontFamily: 'ui-monospace, monospace',
  },
  expandBtn: {
    width: 24,
    height: 24,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 6,
    background: 'rgba(0,0,0,0.03)',
    color: '#64748b',
    border: 'none',
    cursor: 'pointer',
    transition: 'all 0.15s ease',
  },
  
  // Expanded details
  toolBody: {
    padding: '0 14px 14px',
    borderTop: '1px solid rgba(226,232,240,0.6)',
    marginTop: 0,
  },
  detailSection: {
    marginTop: 12,
  },
  detailLabel: {
    fontSize: 10,
    fontWeight: 700,
    color: '#94a3b8',
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
    marginBottom: 6,
  },
  detailContent: {
    fontSize: 11,
    fontFamily: 'ui-monospace, monospace',
    color: '#334155',
    background: '#f8fafc',
    borderRadius: 8,
    padding: 10,
    overflow: 'auto',
    maxHeight: 120,
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
    border: '1px solid #e2e8f0',
  },

  // Section header
  sectionHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 12,
  },
  sectionTitle: {
    fontSize: 11,
    fontWeight: 700,
    color: '#64748b',
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
  },
  badge: (color) => ({
    fontSize: 10,
    fontWeight: 700,
    color: '#fff',
    background: color,
    padding: '2px 8px',
    borderRadius: 10,
  }),
};

const ToolCard = ({ tool }) => {
  const [expanded, setExpanded] = useState(false);
  
  const status = tool.status || 'success';
  const name = tool.tool || tool.name || 'Unknown Tool';
  const detail = tool.text || tool.detail || tool.status || 'invoked';
  const timestamp = tool.ts || tool.timestamp;

  return (
    <div style={styles.toolCard}>
      <div 
        style={styles.toolHeader}
        onClick={() => setExpanded(!expanded)}
      >
        <div style={styles.toolHeaderLeft}>
          <div style={styles.toolIcon}>
            <BuildRoundedIcon sx={{ fontSize: 16, color: '#22c55e' }} />
          </div>
          <div style={styles.toolInfo}>
            <div style={styles.toolName}>{name}</div>
            <div style={styles.toolMeta}>
              <span style={styles.statusDot(status)} />
              <span>{detail}</span>
            </div>
          </div>
        </div>
        <div style={styles.toolHeaderRight}>
          {timestamp && (
            <span style={styles.timestamp}>
              {new Date(timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </span>
          )}
          <button style={styles.expandBtn}>
            {expanded ? (
              <ExpandLessRoundedIcon sx={{ fontSize: 16 }} />
            ) : (
              <ExpandMoreRoundedIcon sx={{ fontSize: 16 }} />
            )}
          </button>
        </div>
      </div>
      
      {expanded && (
        <div style={styles.toolBody}>
          {tool.arguments && (
            <div style={styles.detailSection}>
              <div style={styles.detailLabel}>Arguments</div>
              <pre style={styles.detailContent}>
                {typeof tool.arguments === 'string' 
                  ? tool.arguments 
                  : JSON.stringify(tool.arguments, null, 2)}
              </pre>
            </div>
          )}
          {tool.result && (
            <div style={styles.detailSection}>
              <div style={styles.detailLabel}>Result</div>
              <pre style={styles.detailContent}>
                {typeof tool.result === 'string' 
                  ? tool.result 
                  : JSON.stringify(tool.result, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

const ToolsSection = ({ recentInvocations = [] }) => {
  if (!recentInvocations || recentInvocations.length === 0) {
    return (
      <div style={styles.emptyState}>
        <div style={styles.emptyIcon}>
          <BuildRoundedIcon sx={{ fontSize: 28, color: '#22c55e' }} />
        </div>
        <div style={styles.emptyTitle}>No tools invoked yet</div>
        <div style={styles.emptySubtitle}>
          Tool invocations will appear here as the agent uses them
        </div>
      </div>
    );
  }

  // Sort by timestamp if available, most recent first
  const sortedTools = [...recentInvocations].reverse();
  const pendingCount = sortedTools.filter(t => t.status === 'pending').length;

  return (
    <div>
      <div style={styles.sectionHeader}>
        <span style={styles.sectionTitle}>Recent Invocations</span>
        {pendingCount > 0 && (
          <span style={styles.badge('#f59e0b')}>{pendingCount} pending</span>
        )}
      </div>
      
      {sortedTools.slice(0, 10).map((tool, idx) => (
        <ToolCard key={tool.id || tool.ts || idx} tool={tool} />
      ))}
      
      {sortedTools.length > 10 && (
        <div style={{ textAlign: 'center', padding: '8px 0', color: '#94a3b8', fontSize: 11 }}>
          + {sortedTools.length - 10} more invocations
        </div>
      )}
    </div>
  );
};

export default ToolsSection;
