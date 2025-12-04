/**
 * StatusButton - Backend/Session status indicator button
 * 
 * Light/pale style matching the rest of the UI.
 * Same content as the old BackendIndicator.
 */
import React, { useState, useEffect, useRef } from 'react';
import { useBackendHealth } from '../hooks/useBackendHealth.js';
import { API_BASE_URL } from '../config/constants.js';

// Inject keyframes for animations
const addStatusKeyframes = () => {
  if (typeof document === 'undefined') return;
  const id = 'status-button-keyframes';
  if (document.getElementById(id)) return;
  
  const style = document.createElement('style');
  style.id = id;
  style.textContent = `
    @keyframes statusPulse {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.7; transform: scale(1.1); }
    }
    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(-4px); }
      to { opacity: 1; transform: translateY(0); }
    }
  `;
  document.head.appendChild(style);
};

const componentIcons = {
  redis: '💾',
  azure_openai: '🧠',
  speech_services: '🎙️',
  acs_caller: '📞',
  rt_agents: '🤖',
  cosmosdb: '🗄️',
};

const StatusButton = ({ sessionId, url, onAgentSelect }) => {
  const [isHovered, setIsHovered] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const [revealUrl, setRevealUrl] = useState(false);
  const [showLatency, setShowLatency] = useState(false);
  const [showComponents, setShowComponents] = useState(false);
  const panelRef = useRef(null);
  
  // Use provided url or fall back to API_BASE_URL
  const backendUrl = url || API_BASE_URL;
  
  const { 
    readinessData, 
    healthData, 
    error, 
    overallStatus,
    isConnected,
    refresh 
  } = useBackendHealth(backendUrl);
  
  useEffect(() => {
    addStatusKeyframes();
  }, []);

  // Close panel when clicking outside
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (panelRef.current && !panelRef.current.contains(e.target)) {
        setIsOpen(false);
      }
    };
    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isOpen]);

  // Data extraction - matching old BackendIndicator
  const checks = readinessData?.checks || [];
  const responseTime = readinessData?.response_time_ms;
  const activeSessions = healthData?.active_sessions || 0;
  const totalConnected = healthData?.session_metrics?.connected || 0;
  const disconnected = healthData?.session_metrics?.disconnected || 0;
  const lastCheck = new Date().toLocaleTimeString();

  const getStatusColor = () => {
    switch (overallStatus) {
      case 'healthy': return '#22c55e';
      case 'degraded': return '#f59e0b';
      case 'unhealthy': return '#ef4444';
      default: return '#94a3b8';
    }
  };

  const getStatusLabel = () => {
    switch (overallStatus) {
      case 'healthy': return 'Healthy';
      case 'degraded': return 'Degraded';
      case 'unhealthy': return 'Unhealthy';
      default: return 'Checking...';
    }
  };

  const getStatusBg = () => {
    switch (overallStatus) {
      case 'healthy': return { bg: '#f0fdf4', border: '#bbf7d0', text: '#166534' };
      case 'degraded': return { bg: '#fffbeb', border: '#fed7aa', text: '#92400e' };
      case 'unhealthy': return { bg: '#fef2f2', border: '#fecaca', text: '#dc2626' };
      default: return { bg: '#f8fafc', border: '#e2e8f0', text: '#64748b' };
    }
  };

  const maskUrl = (value) => {
    if (!value) return '';
    try {
      const parsed = new URL(value);
      const host = parsed.hostname;
      if (host === 'localhost') {
        return `${parsed.protocol}//${host}:${parsed.port || '8000'}/`;
      }
      if (host.length <= 10) return value;
      return `${parsed.protocol}//${host.slice(0, 2)}${'•'.repeat(5)}${host.slice(-3)}/`;
    } catch {
      return value;
    }
  };

  const statusBg = getStatusBg();
  const statusColor = getStatusColor();

  return (
    <div style={{ position: 'relative' }} ref={panelRef}>
      {/* Button - matches DevToolbar gradient style */}
      <div
        style={{
          width: 40,
          height: 40,
          borderRadius: '50%',
          background: isHovered 
            ? `linear-gradient(135deg, ${statusColor}20, ${statusColor}10)` 
            : 'linear-gradient(135deg, #f1f5f9, #e2e8f0)',
          border: 'none',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          cursor: 'pointer',
          transition: 'all 0.3s ease',
          boxShadow: isHovered 
            ? `0 4px 12px ${statusColor}30` 
            : '0 2px 8px rgba(0,0,0,0.08)',
          transform: isHovered ? 'scale(1.08)' : 'scale(1)',
        }}
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
        onClick={() => setIsOpen(!isOpen)}
        title={`Backend Status: ${getStatusLabel()}`}
      >
        <span
          style={{
            width: 10,
            height: 10,
            borderRadius: '50%',
            background: statusColor,
            boxShadow: `0 0 8px ${statusColor}60`,
            animation: overallStatus === 'healthy' ? 'statusPulse 2s infinite' : 'none',
          }}
        />
      </div>

      {/* Panel */}
      {isOpen && (
        <div
          style={{
            position: 'absolute',
            top: 'calc(100% + 10px)',
            left: 0,
            right: 'auto',
            width: 320,
            background: '#ffffff',
            borderRadius: 12,
            border: '1px solid #e2e8f0',
            boxShadow: '0 10px 40px rgba(15,23,42,0.12), 0 4px 12px rgba(0,0,0,0.06)',
            overflow: 'hidden',
            zIndex: 9999,
            animation: 'fadeIn 0.15s ease-out',
          }}
        >
          {/* API Entry Point Header */}
          <div style={{
            padding: '12px 14px',
            background: '#f8fafc',
            borderBottom: '1px solid #e2e8f0',
          }}>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              marginBottom: 8,
            }}>
              <span style={{ fontSize: 16 }}>🌐</span>
              <span style={{
                fontSize: 12,
                fontWeight: 600,
                color: '#475569',
              }}>Backend API Entry Point</span>
            </div>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              marginBottom: 8,
            }}>
              <div style={{
                flex: 1,
                padding: '4px 8px',
                background: '#fff',
                border: '1px solid #f1f5f9',
                borderRadius: 4,
                fontFamily: 'ui-monospace, monospace',
                fontSize: 10,
                color: '#64748b',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}>
                {revealUrl ? backendUrl : maskUrl(backendUrl)}
              </div>
              <button
                onClick={(e) => { e.stopPropagation(); setRevealUrl(!revealUrl); }}
                style={{
                  padding: '3px 8px',
                  fontSize: 9,
                  fontWeight: 600,
                  color: '#3b82f6',
                  background: revealUrl ? '#eff6ff' : 'transparent',
                  border: '1px solid #bfdbfe',
                  borderRadius: 4,
                  cursor: 'pointer',
                }}
              >
                {revealUrl ? 'Hide' : 'Reveal'}
              </button>
            </div>
            <div style={{
              fontSize: 9,
              color: '#64748b',
              lineHeight: 1.4,
            }}>
              Main FastAPI server handling WebSocket connections, voice processing, and AI agent orchestration
            </div>
          </div>

          {/* System Status */}
          <div
            style={{
              margin: '10px 12px',
              padding: '8px 10px',
              background: statusBg.bg,
              border: `1px solid ${statusBg.border}`,
              borderRadius: 8,
              cursor: 'pointer',
            }}
            onClick={() => setShowComponents(!showComponents)}
          >
            <div style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}>
              <div>
                <div style={{
                  fontSize: 11,
                  fontWeight: 600,
                  color: statusBg.text,
                  marginBottom: 2,
                }}>
                  System Status: {getStatusLabel()}
                </div>
                <div style={{ fontSize: 9, color: '#64748b' }}>
                  {checks.length} components monitored • Last check: {lastCheck}
                </div>
              </div>
              <span style={{
                fontSize: 10,
                color: '#64748b',
                transform: showComponents ? 'rotate(180deg)' : 'rotate(0deg)',
                transition: 'transform 0.2s ease',
              }}>▼</span>
            </div>
          </div>

          {/* Component Details (expandable) */}
          {showComponents && checks.length > 0 && (
            <div style={{
              margin: '0 12px 10px',
              background: '#f8fafc',
              borderRadius: 8,
              border: '1px solid #e2e8f0',
              overflow: 'hidden',
            }}>
              {checks.map((check, idx) => (
                <div
                  key={idx}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    padding: '8px 10px',
                    borderBottom: idx < checks.length - 1 ? '1px solid #f1f5f9' : 'none',
                    fontSize: 10,
                  }}
                >
                  <span>{componentIcons[check.component] || '•'}</span>
                  <span style={{
                    width: 6,
                    height: 6,
                    borderRadius: '50%',
                    background: check.status === 'healthy' ? '#22c55e' : 
                               check.status === 'degraded' ? '#f59e0b' : '#ef4444',
                  }} />
                  <span style={{ flex: 1, color: '#374151', fontWeight: 500 }}>
                    {check.component.replace(/_/g, ' ')}
                  </span>
                  {check.check_time_ms !== undefined && (
                    <span style={{ color: '#94a3b8', fontSize: 9, fontFamily: 'monospace' }}>
                      {check.check_time_ms.toFixed(0)}ms
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Latency Row */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '8px 14px',
              borderTop: '1px solid #f1f5f9',
              fontSize: 10,
              color: '#94a3b8',
              cursor: 'pointer',
            }}
            onClick={() => setShowLatency(!showLatency)}
          >
            <span>
              {showLatency ? '▼' : '▶'} Health check latency: {responseTime ? `${responseTime.toFixed(0)}ms` : '—'}
            </span>
            <span title="Auto-refreshes every 30 seconds">🔄</span>
          </div>

          {/* Session Statistics */}
          <div style={{
            padding: '10px 14px',
            borderTop: '1px solid #f1f5f9',
          }}>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              marginBottom: 10,
              fontSize: 11,
              fontWeight: 600,
              color: '#374151',
            }}>
              <span>📊</span>
              <span>Session Statistics</span>
            </div>
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(3, 1fr)',
              gap: 8,
            }}>
              <div style={{
                textAlign: 'center',
                padding: '8px 6px',
                background: '#f8fafc',
                border: '1px solid #e2e8f0',
                borderRadius: 6,
              }}>
                <div style={{ fontSize: 16, fontWeight: 700, color: '#10b981' }}>
                  {activeSessions}
                </div>
                <div style={{ fontSize: 8, color: '#64748b', marginTop: 2 }}>
                  Active Sessions
                </div>
              </div>
              <div style={{
                textAlign: 'center',
                padding: '8px 6px',
                background: '#f8fafc',
                border: '1px solid #e2e8f0',
                borderRadius: 6,
              }}>
                <div style={{ fontSize: 16, fontWeight: 700, color: '#3b82f6' }}>
                  {totalConnected}
                </div>
                <div style={{ fontSize: 8, color: '#64748b', marginTop: 2 }}>
                  Total Connected
                </div>
              </div>
              <div style={{
                textAlign: 'center',
                padding: '8px 6px',
                background: '#f8fafc',
                border: '1px solid #e2e8f0',
                borderRadius: 6,
              }}>
                <div style={{ fontSize: 16, fontWeight: 700, color: '#6b7280' }}>
                  {disconnected}
                </div>
                <div style={{ fontSize: 8, color: '#64748b', marginTop: 2 }}>
                  Disconnected
                </div>
              </div>
            </div>
          </div>

          {/* Footer */}
          <div style={{
            padding: '8px 14px',
            borderTop: '1px solid #f1f5f9',
            background: '#fafbfc',
            fontSize: 9,
            color: '#94a3b8',
            textAlign: 'right',
          }}>
            Updated: {lastCheck}
          </div>

          {/* Error display */}
          {error && (
            <div style={{
              padding: '8px 14px',
              background: '#fef2f2',
              borderTop: '1px solid #fecaca',
              color: '#dc2626',
              fontSize: 10,
            }}>
              ⚠️ {error}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default StatusButton;
