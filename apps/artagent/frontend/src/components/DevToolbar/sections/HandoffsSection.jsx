/**
 * HandoffsSection - Shows handoff history (agent transitions)
 */
import React from 'react';
import SwapHorizRoundedIcon from '@mui/icons-material/SwapHorizRounded';
import ArrowForwardRoundedIcon from '@mui/icons-material/ArrowForwardRounded';
import SmartToyRoundedIcon from '@mui/icons-material/SmartToyRounded';

const styles = {
  emptyState: {
    textAlign: 'center',
    padding: 32,
    color: '#94a3b8',
  },
  emptyIcon: {
    fontSize: 40,
    marginBottom: 8,
    color: '#cbd5e1',
  },
  handoffCard: {
    background: '#fff',
    borderRadius: 10,
    border: '1px solid #e2e8f0',
    padding: 12,
    marginBottom: 8,
  },
  handoffRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  agentBubble: (isFrom) => ({
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    padding: '6px 10px',
    borderRadius: 8,
    fontSize: 12,
    fontWeight: 600,
    background: isFrom ? '#f1f5f9' : 'linear-gradient(135deg, #0ea5e9, #6366f1)',
    color: isFrom ? '#64748b' : '#fff',
  }),
  arrow: {
    color: '#cbd5e1',
    fontSize: 18,
  },
  timestamp: {
    fontSize: 10,
    color: '#94a3b8',
    marginTop: 8,
  },
  reason: {
    fontSize: 11,
    color: '#64748b',
    marginTop: 8,
    padding: 8,
    background: '#f8fafc',
    borderRadius: 6,
    fontStyle: 'italic',
  },
  timelineConnector: {
    width: 2,
    height: 12,
    background: '#e2e8f0',
    marginLeft: 19,
  },
};

const HandoffsSection = ({ handoffs = [] }) => {
  if (!handoffs || handoffs.length === 0) {
    return (
      <div style={styles.emptyState}>
        <SwapHorizRoundedIcon style={styles.emptyIcon} />
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>No handoffs yet</div>
        <div style={{ fontSize: 12 }}>Agent transitions will appear here</div>
      </div>
    );
  }

  return (
    <div>
      {handoffs.map((handoff, idx) => (
        <React.Fragment key={idx}>
          <div style={styles.handoffCard}>
            <div style={styles.handoffRow}>
              <span style={styles.agentBubble(true)}>
                <SmartToyRoundedIcon sx={{ fontSize: 14 }} />
                {handoff.from || 'Unknown'}
              </span>
              <ArrowForwardRoundedIcon style={styles.arrow} />
              <span style={styles.agentBubble(false)}>
                <SmartToyRoundedIcon sx={{ fontSize: 14 }} />
                {handoff.to || 'Unknown'}
              </span>
            </div>
            {handoff.reason && (
              <div style={styles.reason}>"{handoff.reason}"</div>
            )}
            {handoff.timestamp && (
              <div style={styles.timestamp}>{handoff.timestamp}</div>
            )}
          </div>
          {idx < handoffs.length - 1 && <div style={styles.timelineConnector} />}
        </React.Fragment>
      ))}
    </div>
  );
};

export default HandoffsSection;
