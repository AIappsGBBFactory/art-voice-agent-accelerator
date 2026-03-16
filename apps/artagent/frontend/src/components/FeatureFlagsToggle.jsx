import React, { useEffect, useState, useRef } from 'react';
import { API_BASE_URL } from '../config/constants.js';

const FeatureFlagsToggle = () => {
  const [flags, setFlags] = useState(null);
  const [showPanel, setShowPanel] = useState(false);
  const [updating, setUpdating] = useState({});
  const panelRef = useRef(null);
  const buttonRef = useRef(null);

  const fetchFlags = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/feature-flags`);
      if (res.ok) {
        const data = await res.json();
        setFlags(data.flags);
      }
    } catch {
      // silent
    }
  };

  useEffect(() => {
    fetchFlags();
  }, []);

  // Close panel on outside click
  useEffect(() => {
    if (!showPanel) return;
    const handler = (e) => {
      if (
        panelRef.current && !panelRef.current.contains(e.target) &&
        buttonRef.current && !buttonRef.current.contains(e.target)
      ) {
        setShowPanel(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [showPanel]);

  const toggleFlag = async (name, currentEnabled) => {
    setUpdating((prev) => ({ ...prev, [name]: true }));
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/feature-flags/${name}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !currentEnabled }),
      });
      if (res.ok) {
        setFlags((prev) => ({
          ...prev,
          [name]: { ...prev[name], enabled: !currentEnabled },
        }));
      }
    } catch {
      // silent
    } finally {
      setUpdating((prev) => ({ ...prev, [name]: false }));
    }
  };

  // Labels for display
  const flagLabels = {
    'voiceprint': 'Voice Biometrics',
    'warm-pool': 'Warm Pool',
    'dtmf-validation': 'DTMF Validation',
    'auth-validation': 'Auth Validation',
    'call-recording': 'Call Recording',
    'session-persistence': 'Session Persistence',
    'performance-logging': 'Performance Logging',
    'tracing': 'Tracing',
    'connection-limits': 'Connection Limits',
  };

  if (!flags) return null;

  return (
    <>
      <button
        ref={buttonRef}
        onClick={() => setShowPanel(!showPanel)}
        title="Feature Flags"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: 36,
          height: 36,
          borderRadius: 8,
          border: '1px solid rgba(226,232,240,0.8)',
          background: showPanel ? 'rgba(99,102,241,0.1)' : 'rgba(255,255,255,0.9)',
          cursor: 'pointer',
          transition: 'all 0.2s',
          fontSize: 16,
        }}
      >
        ⚙️
      </button>

      {showPanel && (
        <div
          ref={panelRef}
          style={{
            position: 'fixed',
            top: 60,
            left: 60,
            width: 320,
            background: '#fff',
            borderRadius: 12,
            boxShadow: '0 8px 32px rgba(0,0,0,0.12), 0 2px 8px rgba(0,0,0,0.08)',
            border: '1px solid rgba(226,232,240,0.8)',
            zIndex: 10000,
            overflow: 'hidden',
          }}
        >
          <div style={{
            padding: '14px 16px',
            borderBottom: '1px solid rgba(226,232,240,0.6)',
            background: 'linear-gradient(135deg, #f8fafc, #f1f5f9)',
          }}>
            <div style={{ fontWeight: 600, fontSize: 14, color: '#1e293b' }}>
              Feature Flags
            </div>
            <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 2 }}>
              Runtime toggles — changes take effect on next call
            </div>
          </div>

          <div style={{ padding: '8px 0', maxHeight: 400, overflowY: 'auto' }}>
            {Object.entries(flags).map(([name, flag]) => (
              <div
                key={name}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '10px 16px',
                  borderBottom: '1px solid rgba(241,245,249,0.8)',
                }}
              >
                <div>
                  <div style={{ fontSize: 13, fontWeight: 500, color: '#334155' }}>
                    {flagLabels[name] || name}
                  </div>
                  <div style={{ fontSize: 10, color: '#94a3b8', fontFamily: 'monospace' }}>
                    {name}
                  </div>
                </div>

                <button
                  onClick={() => toggleFlag(name, flag.enabled)}
                  disabled={!!updating[name]}
                  style={{
                    position: 'relative',
                    width: 44,
                    height: 24,
                    borderRadius: 12,
                    border: 'none',
                    background: flag.enabled
                      ? 'linear-gradient(135deg, #6366f1, #818cf8)'
                      : '#cbd5e1',
                    cursor: updating[name] ? 'wait' : 'pointer',
                    transition: 'background 0.2s',
                    flexShrink: 0,
                    padding: 0,
                  }}
                >
                  <div style={{
                    position: 'absolute',
                    top: 2,
                    left: flag.enabled ? 22 : 2,
                    width: 20,
                    height: 20,
                    borderRadius: '50%',
                    background: '#fff',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
                    transition: 'left 0.2s',
                  }} />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
};

export default FeatureFlagsToggle;
