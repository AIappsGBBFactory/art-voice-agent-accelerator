/**
 * ContextSection - Shows conversation context / recent messages
 * Mirrors "Conversation Context" from AgentDetailsPanel
 */
import React from 'react';
import ChatRoundedIcon from '@mui/icons-material/ChatRounded';
import PersonRoundedIcon from '@mui/icons-material/PersonRounded';
import SmartToyRoundedIcon from '@mui/icons-material/SmartToyRounded';
import SettingsRoundedIcon from '@mui/icons-material/SettingsRounded';

const styles = {
  emptyState: {
    textAlign: 'center',
    padding: '40px 20px',
  },
  emptyIcon: {
    width: 56,
    height: 56,
    borderRadius: 16,
    background: 'linear-gradient(135deg, rgba(236,72,153,0.1), rgba(236,72,153,0.05))',
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

  // Counter badge
  counterBadge: {
    fontSize: 11,
    color: '#64748b',
    textAlign: 'center',
    padding: '8px 12px',
    background: '#f8fafc',
    borderRadius: 8,
    marginBottom: 12,
    border: '1px solid #e2e8f0',
  },

  // Message card
  messageCard: {
    borderRadius: 12,
    border: '1px solid rgba(226,232,240,0.9)',
    background: '#fff',
    marginBottom: 10,
    overflow: 'hidden',
    transition: 'all 0.15s ease',
  },
  messageHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    padding: '10px 12px',
    background: '#f8fafc',
    borderBottom: '1px solid #f1f5f9',
  },
  avatar: (speaker) => {
    const colors = {
      User: '#2563eb',
      System: '#64748b',
      default: '#0ea5e9',
    };
    const bg = colors[speaker] || colors.default;
    return {
      width: 26,
      height: 26,
      borderRadius: 7,
      background: speaker === 'User' ? bg : `linear-gradient(135deg, ${bg}, #6366f1)`,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      flexShrink: 0,
    };
  },
  speakerInfo: {
    flex: 1,
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  speakerName: {
    fontSize: 11,
    fontWeight: 700,
    color: '#0f172a',
    textTransform: 'uppercase',
  },
  turnId: {
    fontSize: 10,
    color: '#94a3b8',
    fontFamily: 'ui-monospace, monospace',
  },
  messageContent: {
    padding: '10px 12px',
    fontSize: 12,
    color: '#334155',
    lineHeight: 1.5,
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
  },
  noText: {
    color: '#94a3b8',
    fontStyle: 'italic',
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
  badge: {
    fontSize: 10,
    fontWeight: 700,
    color: '#fff',
    background: '#ec4899',
    padding: '2px 8px',
    borderRadius: 10,
  },
};

const getSpeakerIcon = (speaker) => {
  if (speaker === 'User') {
    return <PersonRoundedIcon sx={{ fontSize: 14, color: '#fff' }} />;
  }
  if (speaker === 'System') {
    return <SettingsRoundedIcon sx={{ fontSize: 14, color: '#fff' }} />;
  }
  return <SmartToyRoundedIcon sx={{ fontSize: 14, color: '#fff' }} />;
};

const getSpeakerColor = (speaker) => {
  if (speaker === 'User') return '#2563eb';
  if (speaker === 'System') return '#64748b';
  return '#0ea5e9';
};

const MessageCard = ({ message }) => {
  const speaker = message.speaker || 'Assistant';
  const content = message.text || message.content || '';
  
  return (
    <div style={styles.messageCard}>
      <div style={styles.messageHeader}>
        <div style={styles.avatar(speaker)}>
          {getSpeakerIcon(speaker)}
        </div>
        <div style={styles.speakerInfo}>
          <span style={{ ...styles.speakerName, color: getSpeakerColor(speaker) }}>
            {speaker}
          </span>
          {message.turnId && (
            <span style={styles.turnId}>{message.turnId}</span>
          )}
        </div>
      </div>
      <div style={styles.messageContent}>
        {content ? (
          content.length > 200 ? `${content.slice(0, 200)}...` : content
        ) : (
          <span style={styles.noText}>(no text)</span>
        )}
      </div>
    </div>
  );
};

const ContextSection = ({ messages = [] }) => {
  if (!messages || messages.length === 0) {
    return (
      <div style={styles.emptyState}>
        <div style={styles.emptyIcon}>
          <ChatRoundedIcon sx={{ fontSize: 28, color: '#ec4899' }} />
        </div>
        <div style={styles.emptyTitle}>No messages yet</div>
        <div style={styles.emptySubtitle}>
          Conversation context will appear here as the session progresses
        </div>
      </div>
    );
  }

  // Show last 12 messages, reversed for most recent first
  const recentMessages = messages.slice(-12).reverse();
  const hiddenCount = messages.length - recentMessages.length;

  return (
    <div>
      <div style={styles.sectionHeader}>
        <span style={styles.sectionTitle}>Recent Messages</span>
        <span style={styles.badge}>{messages.length}</span>
      </div>

      {hiddenCount > 0 && (
        <div style={styles.counterBadge}>
          Showing {recentMessages.length} of {messages.length} messages
        </div>
      )}

      {recentMessages.map((msg, idx) => (
        <MessageCard 
          key={msg.turnId || msg.id || `msg-${idx}`} 
          message={msg} 
        />
      ))}
    </div>
  );
};

export default ContextSection;
