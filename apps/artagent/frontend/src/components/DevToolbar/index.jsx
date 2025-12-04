/**
 * DevToolbar - Minimal floating developer tools button
 * 
 * A subtle floating button in the bottom-right that expands into a dev panel.
 * Designed to be unobtrusive and match the app's clean, light aesthetic.
 * 
 * Keyboard shortcuts:
 * - ⌘D: Toggle dev panel
 * - ⌘1-5: Switch sections when open
 * - Esc: Close panel
 */

import React, { useState, useCallback, useEffect } from 'react';
import { createPortal } from 'react-dom';
import CodeRoundedIcon from '@mui/icons-material/CodeRounded';
import CloseRoundedIcon from '@mui/icons-material/CloseRounded';
import SmartToyRoundedIcon from '@mui/icons-material/SmartToyRounded';
import BuildRoundedIcon from '@mui/icons-material/BuildRounded';
import TimelineRoundedIcon from '@mui/icons-material/TimelineRounded';
import AccountTreeRoundedIcon from '@mui/icons-material/AccountTreeRounded';
import ChatRoundedIcon from '@mui/icons-material/ChatRounded';
import SettingsRoundedIcon from '@mui/icons-material/SettingsRounded';

import AgentSection from './sections/AgentSection';
import ToolsSection from './sections/ToolsSection';
import SessionSection from './sections/SessionSection';
import TopologySection from './sections/TopologySection';
import ContextSection from './sections/ContextSection';
import SettingsSection from './sections/SettingsSection';

const PANEL_WIDTH = 360;

const SECTIONS = [
  { id: 'agent', icon: SmartToyRoundedIcon, label: 'Agent', shortcut: '1', color: '#6366f1' },
  { id: 'tools', icon: BuildRoundedIcon, label: 'Tools', shortcut: '2', color: '#10b981' },
  { id: 'session', icon: TimelineRoundedIcon, label: 'Session', shortcut: '3', color: '#8b5cf6' },
  { id: 'topology', icon: AccountTreeRoundedIcon, label: 'Topology', shortcut: '4', color: '#f59e0b' },
  { id: 'context', icon: ChatRoundedIcon, label: 'Context', shortcut: '5', color: '#ec4899' },
];

// Inject keyframes for animations
const injectKeyframes = () => {
  if (typeof document === 'undefined') return;
  if (document.getElementById('devtoolbar-keyframes')) return;
  const style = document.createElement('style');
  style.id = 'devtoolbar-keyframes';
  style.textContent = `
    @keyframes devPanelSlideIn {
      from { opacity: 0; transform: translateY(-8px) scale(0.98); }
      to { opacity: 1; transform: translateY(0) scale(1); }
    }
  `;
  document.head.appendChild(style);
};

const styles = {
  // Floating trigger button - LEFT side, in its own pill container
  trigger: (isOpen, isHovered) => ({
    position: 'fixed',
    top: 'calc(50% + 75px)', // Below the Status/Help pill
    left: 20,
    width: 40,
    height: 40,
    borderRadius: '50%',
    background: isOpen 
      ? 'linear-gradient(135deg, #6366f1, #4f46e5)'
      : isHovered 
        ? 'linear-gradient(135deg, #e0e7ff, #c7d2fe)' 
        : 'linear-gradient(135deg, #f1f5f9, #e2e8f0)',
    border: 'none',
    boxShadow: isOpen
      ? '0 6px 20px rgba(99, 102, 241, 0.4), 0 0 0 3px rgba(99, 102, 241, 0.15)'
      : isHovered 
        ? '0 4px 12px rgba(99, 102, 241, 0.25), 0 0 0 3px rgba(99, 102, 241, 0.1)'
        : '0 4px 14px rgba(15,23,42,0.12)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    cursor: 'pointer',
    transition: 'all 0.3s ease',
    transform: isHovered ? 'scale(1.08)' : 'scale(1)',
    flexShrink: 0,
    zIndex: 1200,
    // Add pill background like the other container
    padding: 0,
  }),
  
  // Wrapper to create the pill effect around just this button
  triggerWrapper: {
    position: 'fixed',
    top: 'calc(50% + 70px)',
    left: 20,
    background: 'rgba(255,255,255,0.9)',
    padding: '10px',
    borderRadius: '24px',
    boxShadow: '0 4px 14px rgba(15,23,42,0.12)',
    border: '1px solid rgba(226,232,240,0.9)',
    zIndex: 1200,
  },
  
  // Panel container - appears to the right of buttons
  panel: {
    position: 'fixed',
    top: '50%',
    left: 84,
    transform: 'translateY(-50%)',
    width: PANEL_WIDTH,
    maxHeight: 'calc(100vh - 180px)',
    background: '#ffffff',
    borderRadius: 16,
    border: '1px solid rgba(0,0,0,0.06)',
    boxShadow: '0 8px 32px rgba(0,0,0,0.1), 0 2px 8px rgba(0,0,0,0.04)',
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
    zIndex: 1199,
    animation: 'devPanelSlideIn 0.15s ease-out',
  },
  
  // Header
  header: {
    display: 'flex',
    flexDirection: 'column',
    borderBottom: '1px solid rgba(0,0,0,0.05)',
  },
  headerTop: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '12px 14px 10px 14px',
  },
  headerTitle: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  headerIcon: {
    width: 22,
    height: 22,
    borderRadius: 6,
    background: '#6366f1',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  },
  headerText: {
    fontSize: 13,
    fontWeight: 600,
    color: '#0f172a',
  },
  closeBtn: {
    width: 24,
    height: 24,
    borderRadius: 6,
    border: 'none',
    background: 'transparent',
    color: '#94a3b8',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    transition: 'all 0.12s ease',
  },
  
  // Tabs
  tabs: {
    display: 'flex',
    padding: '0 10px 10px 10px',
    gap: 4,
    overflowX: 'auto',
  },
  tab: (isActive, color) => ({
    display: 'flex',
    alignItems: 'center',
    gap: 5,
    padding: '6px 10px',
    borderRadius: 8,
    border: 'none',
    background: isActive ? `${color}12` : 'transparent',
    color: isActive ? color : '#64748b',
    cursor: 'pointer',
    transition: 'all 0.1s ease',
    fontSize: 11,
    fontWeight: 500,
    whiteSpace: 'nowrap',
  }),
  
  // Content
  content: {
    flex: 1,
    overflowY: 'auto',
    overflowX: 'hidden',
    padding: 14,
    scrollbarWidth: 'thin',
    scrollbarColor: 'rgba(0,0,0,0.08) transparent',
  },
  
  // Footer with keyboard hint
  footer: {
    padding: '8px 14px',
    borderTop: '1px solid rgba(0,0,0,0.04)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    fontSize: 10,
    color: '#94a3b8',
  },
  kbd: {
    padding: '2px 5px',
    borderRadius: 4,
    background: '#f1f5f9',
    border: '1px solid rgba(0,0,0,0.06)',
    fontFamily: 'SF Mono, Monaco, monospace',
    fontSize: 9,
  },
};

const DevToolbar = ({
  // Agent data
  agentName,
  agentDescription,
  agentTools = [],
  handoffTools = [],
  
  // Session data
  sessionId,
  activeProfile,
  
  // Inventory/topology
  inventory,
  
  // Conversation
  messages = [],
  recentTools = [],
  lastUserMessage,
  lastAssistantMessage,
  
  // Visibility control
  visible = true,
  
  // Embedded mode (inside a container, no wrapper)
  embedded = false,
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const [isHovered, setIsHovered] = useState(false);
  const [activeTab, setActiveTab] = useState('agent');

  // Inject keyframes on mount
  useEffect(() => {
    injectKeyframes();
  }, []);

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e) => {
      // ⌘D to toggle
      if ((e.metaKey || e.ctrlKey) && e.key === 'd') {
        e.preventDefault();
        setIsOpen((prev) => !prev);
        return;
      }

      // Esc to close
      if (e.key === 'Escape' && isOpen) {
        e.preventDefault();
        setIsOpen(false);
        return;
      }

      // ⌘1-5 to switch tabs when open
      if (isOpen && (e.metaKey || e.ctrlKey) && e.key >= '1' && e.key <= '5') {
        e.preventDefault();
        const index = parseInt(e.key, 10) - 1;
        if (SECTIONS[index]) {
          setActiveTab(SECTIONS[index].id);
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen]);

  const renderContent = useCallback(() => {
    switch (activeTab) {
      case 'agent':
        return (
          <AgentSection
            name={agentName}
            description={agentDescription}
            tools={agentTools}
            handoffTools={handoffTools}
            sessionId={sessionId}
          />
        );
      case 'tools':
        return <ToolsSection recentInvocations={recentTools} />;
      case 'session':
        return (
          <SessionSection
            sessionId={sessionId}
            connected={true}
            messageCount={messages.length}
            toolCount={agentTools.length}
            lastUserMessage={lastUserMessage}
            lastAssistantMessage={lastAssistantMessage}
            agentName={agentName}
          />
        );
      case 'topology':
        return <TopologySection inventory={inventory} activeAgent={agentName} />;
      case 'context':
        return <ContextSection messages={messages} />;
      case 'settings':
        return <SettingsSection />;
      default:
        return null;
    }
  }, [
    activeTab,
    agentName,
    agentDescription,
    agentTools,
    handoffTools,
    recentTools,
    sessionId,
    messages,
    inventory,
    lastUserMessage,
    lastAssistantMessage,
  ]);

  if (!visible) {
    return null;
  }

  // Button component - shared between embedded and standalone modes
  const TriggerButton = (
    <div
      style={{
        width: 40,
        height: 40,
        borderRadius: '50%',
        background: isOpen 
          ? 'linear-gradient(135deg, #6366f1, #4f46e5)'
          : isHovered 
            ? 'linear-gradient(135deg, #e0e7ff, #c7d2fe)' 
            : 'linear-gradient(135deg, #f1f5f9, #e2e8f0)',
        border: 'none',
        boxShadow: isOpen
          ? '0 6px 20px rgba(99, 102, 241, 0.4)'
          : isHovered 
            ? '0 4px 12px rgba(99, 102, 241, 0.25)'
            : '0 2px 8px rgba(0,0,0,0.08)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        cursor: 'pointer',
        transition: 'all 0.3s ease',
        transform: isHovered ? 'scale(1.08)' : 'scale(1)',
      }}
      onClick={() => setIsOpen(!isOpen)}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      title="Developer Tools (⌘D)"
    >
      {isOpen ? (
        <CloseRoundedIcon sx={{ fontSize: 16, color: '#fff' }} />
      ) : (
        <CodeRoundedIcon sx={{ fontSize: 16, color: '#6366f1' }} />
      )}
    </div>
  );

  // Panel component - always rendered via portal
  const Panel = isOpen && (
    <div style={styles.panel}>
      {/* Header */}
      <div style={styles.header}>
        <div style={styles.headerTop}>
          <div style={styles.headerTitle}>
            <div style={styles.headerIcon}>
              <CodeRoundedIcon sx={{ fontSize: 14, color: '#fff' }} />
            </div>
            <span style={styles.headerText}>Developer Tools</span>
          </div>
          <button
            style={styles.closeBtn}
            onClick={() => setIsOpen(false)}
            onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(0,0,0,0.04)')}
            onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
          >
            <CloseRoundedIcon sx={{ fontSize: 16 }} />
          </button>
        </div>

        {/* Tabs */}
        <div style={styles.tabs}>
          {SECTIONS.map((section) => (
            <button
              key={section.id}
              style={styles.tab(activeTab === section.id, section.color)}
              onClick={() => setActiveTab(section.id)}
              onMouseEnter={(e) => {
                if (activeTab !== section.id) {
                  e.currentTarget.style.background = 'rgba(0,0,0,0.03)';
                }
              }}
              onMouseLeave={(e) => {
                if (activeTab !== section.id) {
                  e.currentTarget.style.background = 'transparent';
                }
              }}
            >
              <section.icon sx={{ fontSize: 14 }} />
              {section.label}
            </button>
          ))}
          {/* Settings tab */}
          <button
            style={styles.tab(activeTab === 'settings', '#64748b')}
            onClick={() => setActiveTab('settings')}
            onMouseEnter={(e) => {
              if (activeTab !== 'settings') {
                e.currentTarget.style.background = 'rgba(0,0,0,0.03)';
              }
            }}
            onMouseLeave={(e) => {
              if (activeTab !== 'settings') {
                e.currentTarget.style.background = 'transparent';
              }
            }}
          >
            <SettingsRoundedIcon sx={{ fontSize: 14 }} />
            Settings
          </button>
        </div>
      </div>

      {/* Content */}
      <div style={styles.content}>
        {renderContent()}
      </div>

      {/* Footer */}
      <div style={styles.footer}>
        <span style={styles.kbd}>⌘D</span>
        <span>toggle</span>
        <span style={{ margin: '0 4px', color: '#cbd5e1' }}>•</span>
        <span style={styles.kbd}>⌘1-5</span>
        <span>switch</span>
        <span style={{ margin: '0 4px', color: '#cbd5e1' }}>•</span>
        <span style={styles.kbd}>esc</span>
        <span>close</span>
      </div>
    </div>
  );

  // If embedded, render just the button inline (no wrapper) + panel via portal
  if (embedded) {
    return (
      <>
        {TriggerButton}
        {Panel && createPortal(Panel, document.body)}
      </>
    );
  }

  // Standalone mode: render both button (in wrapper) and panel via portal
  return createPortal(
    <>
      <div style={styles.triggerWrapper}>
        {TriggerButton}
      </div>
      {Panel}
    </>,
    document.body
  );
};

export default DevToolbar;
