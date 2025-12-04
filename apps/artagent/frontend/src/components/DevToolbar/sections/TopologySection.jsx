/**
 * TopologySection - Shows agent topology and handoff relationships
 * Mirrors AgentTopologyPanel functionality
 */
import React, { useMemo } from 'react';
import AccountTreeRoundedIcon from '@mui/icons-material/AccountTreeRounded';
import SmartToyRoundedIcon from '@mui/icons-material/SmartToyRounded';
import ArrowForwardRoundedIcon from '@mui/icons-material/ArrowForwardRounded';
import BuildRoundedIcon from '@mui/icons-material/BuildRounded';

const styles = {
  emptyState: {
    textAlign: 'center',
    padding: '40px 20px',
  },
  emptyIcon: {
    width: 56,
    height: 56,
    borderRadius: 16,
    background: 'linear-gradient(135deg, rgba(245,158,11,0.1), rgba(245,158,11,0.05))',
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

  // Agent card
  agentCard: (isActive) => ({
    background: isActive 
      ? 'linear-gradient(135deg, rgba(14,165,233,0.08), rgba(99,102,241,0.06))'
      : '#fff',
    borderRadius: 12,
    border: isActive 
      ? '2px solid rgba(14,165,233,0.4)' 
      : '1px solid #e2e8f0',
    padding: 12,
    marginBottom: 10,
    position: 'relative',
    transition: 'all 0.2s ease',
  }),
  activeBadge: {
    position: 'absolute',
    top: -8,
    right: 12,
    fontSize: 9,
    fontWeight: 700,
    padding: '3px 8px',
    borderRadius: 10,
    background: 'linear-gradient(135deg, #0ea5e9, #6366f1)',
    color: '#fff',
    boxShadow: '0 2px 8px rgba(14,165,233,0.3)',
  },
  agentHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    marginBottom: 8,
  },
  agentIcon: (isActive) => ({
    width: 32,
    height: 32,
    borderRadius: 8,
    background: isActive 
      ? 'linear-gradient(135deg, #0ea5e9, #6366f1)' 
      : '#f1f5f9',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  }),
  agentName: {
    fontSize: 13,
    fontWeight: 700,
    color: '#0f172a',
  },
  agentDesc: {
    fontSize: 11,
    color: '#64748b',
    lineHeight: 1.4,
    marginBottom: 8,
  },
  agentStats: {
    display: 'flex',
    gap: 8,
    flexWrap: 'wrap',
  },
  statChip: (color) => ({
    fontSize: 10,
    fontWeight: 600,
    padding: '3px 8px',
    borderRadius: 6,
    background: `${color}10`,
    color: color,
    display: 'flex',
    alignItems: 'center',
    gap: 4,
  }),

  // Handoff section
  sectionHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    marginTop: 20,
    marginBottom: 10,
  },
  sectionTitle: {
    fontSize: 11,
    fontWeight: 700,
    color: '#64748b',
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
  },
  handoffRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '8px 10px',
    background: '#f8fafc',
    borderRadius: 8,
    marginBottom: 6,
    border: '1px solid #e2e8f0',
  },
  handoffFrom: {
    fontSize: 11,
    fontWeight: 600,
    color: '#64748b',
    background: '#fff',
    padding: '4px 8px',
    borderRadius: 6,
    border: '1px solid #e2e8f0',
  },
  handoffArrow: {
    color: '#cbd5e1',
  },
  handoffTo: {
    fontSize: 11,
    fontWeight: 700,
    color: '#0ea5e9',
    background: 'rgba(14,165,233,0.1)',
    padding: '4px 8px',
    borderRadius: 6,
    border: '1px solid rgba(14,165,233,0.2)',
  },
};

const AgentCard = ({ agent, isActive }) => {
  const toolCount = agent.toolCount ?? agent.tools?.length ?? 0;
  const handoffCount = agent.handoffTools?.length ?? 0;

  return (
    <div style={styles.agentCard(isActive)}>
      {isActive && <span style={styles.activeBadge}>ACTIVE</span>}
      <div style={styles.agentHeader}>
        <div style={styles.agentIcon(isActive)}>
          <SmartToyRoundedIcon sx={{ fontSize: 18, color: isActive ? '#fff' : '#94a3b8' }} />
        </div>
        <span style={styles.agentName}>{agent.name}</span>
      </div>
      {agent.description && (
        <div style={styles.agentDesc}>
          {agent.description.length > 80 
            ? `${agent.description.slice(0, 80)}...` 
            : agent.description}
        </div>
      )}
      <div style={styles.agentStats}>
        <span style={styles.statChip('#0ea5e9')}>
          <BuildRoundedIcon sx={{ fontSize: 10 }} />
          {toolCount} tools
        </span>
        {handoffCount > 0 && (
          <span style={styles.statChip('#f59e0b')}>
            <AccountTreeRoundedIcon sx={{ fontSize: 10 }} />
            {handoffCount} handoffs
          </span>
        )}
      </div>
    </div>
  );
};

const TopologySection = ({ inventory, activeAgent }) => {
  const agents = useMemo(() => {
    if (!inventory?.agents) return [];
    return inventory.agents;
  }, [inventory]);

  const handoffMap = useMemo(() => {
    if (!inventory?.handoffMap) return {};
    return inventory.handoffMap;
  }, [inventory]);

  const handoffEdges = useMemo(() => {
    const edges = [];
    Object.entries(handoffMap).forEach(([from, targets]) => {
      if (Array.isArray(targets)) {
        targets.forEach((to) => {
          edges.push({ from, to });
        });
      }
    });
    return edges;
  }, [handoffMap]);

  if (!agents || agents.length === 0) {
    return (
      <div style={styles.emptyState}>
        <div style={styles.emptyIcon}>
          <AccountTreeRoundedIcon sx={{ fontSize: 28, color: '#f59e0b' }} />
        </div>
        <div style={styles.emptyTitle}>No agents configured</div>
        <div style={styles.emptySubtitle}>
          Agent topology will appear here when agents are loaded
        </div>
      </div>
    );
  }

  // Sort to show active agent first
  const sortedAgents = [...agents].sort((a, b) => {
    if (a.name === activeAgent) return -1;
    if (b.name === activeAgent) return 1;
    return 0;
  });

  return (
    <div>
      {/* Agent List */}
      {sortedAgents.map((agent) => (
        <AgentCard
          key={agent.name}
          agent={agent}
          isActive={agent.name === activeAgent}
        />
      ))}

      {/* Handoff Relationships */}
      {handoffEdges.length > 0 && (
        <>
          <div style={styles.sectionHeader}>
            <AccountTreeRoundedIcon sx={{ fontSize: 14, color: '#f59e0b' }} />
            <span style={styles.sectionTitle}>Handoff Routes</span>
          </div>
          {handoffEdges.slice(0, 10).map((edge, idx) => (
            <div key={`${edge.from}-${edge.to}-${idx}`} style={styles.handoffRow}>
              <span style={styles.handoffFrom}>{edge.from}</span>
              <ArrowForwardRoundedIcon sx={{ fontSize: 14 }} style={styles.handoffArrow} />
              <span style={styles.handoffTo}>{edge.to}</span>
            </div>
          ))}
          {handoffEdges.length > 10 && (
            <div style={{ textAlign: 'center', padding: '8px 0', color: '#94a3b8', fontSize: 11 }}>
              + {handoffEdges.length - 10} more routes
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default TopologySection;
