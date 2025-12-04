/**
 * SettingsSection - Shows keyboard shortcuts and settings
 */
import React from 'react';
import KeyboardRoundedIcon from '@mui/icons-material/KeyboardRounded';

const styles = {
  card: {
    background: '#fff',
    borderRadius: 12,
    border: '1px solid #e2e8f0',
    padding: 16,
    marginBottom: 12,
  },
  title: {
    fontSize: 13,
    fontWeight: 700,
    color: '#0f172a',
    marginBottom: 12,
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  shortcutRow: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '8px 0',
    borderBottom: '1px solid #f1f5f9',
  },
  shortcutLabel: {
    fontSize: 12,
    color: '#64748b',
  },
  shortcutKeys: {
    display: 'flex',
    alignItems: 'center',
    gap: 4,
  },
  key: {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    minWidth: 24,
    height: 24,
    padding: '0 6px',
    fontSize: 11,
    fontWeight: 600,
    fontFamily: 'ui-monospace, monospace',
    color: '#475569',
    background: '#f1f5f9',
    border: '1px solid #e2e8f0',
    borderRadius: 4,
    boxShadow: '0 1px 0 #e2e8f0',
  },
  sectionLabel: {
    fontSize: 11,
    fontWeight: 700,
    color: '#94a3b8',
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
    marginBottom: 8,
    marginTop: 16,
  },
  version: {
    fontSize: 11,
    color: '#94a3b8',
    textAlign: 'center',
    marginTop: 24,
    padding: 12,
    background: '#f8fafc',
    borderRadius: 8,
  },
};

const shortcuts = [
  { label: 'Toggle Toolbar', keys: ['⌘', '\\'] },
  { label: 'Agent Section', keys: ['⌘', '1'] },
  { label: 'Tools Section', keys: ['⌘', '2'] },
  { label: 'Session Section', keys: ['⌘', '3'] },
  { label: 'Handoffs Section', keys: ['⌘', '4'] },
  { label: 'Context Section', keys: ['⌘', '5'] },
  { label: 'Collapse All', keys: ['Esc'] },
];

const SettingsSection = () => {
  return (
    <div>
      <div style={styles.card}>
        <div style={styles.title}>
          <KeyboardRoundedIcon sx={{ fontSize: 18, color: '#0ea5e9' }} />
          Keyboard Shortcuts
        </div>
        {shortcuts.map((shortcut, idx) => (
          <div
            key={idx}
            style={{
              ...styles.shortcutRow,
              borderBottom: idx === shortcuts.length - 1 ? 'none' : '1px solid #f1f5f9',
            }}
          >
            <span style={styles.shortcutLabel}>{shortcut.label}</span>
            <span style={styles.shortcutKeys}>
              {shortcut.keys.map((key, kidx) => (
                <React.Fragment key={kidx}>
                  <span style={styles.key}>{key}</span>
                  {kidx < shortcut.keys.length - 1 && (
                    <span style={{ fontSize: 10, color: '#94a3b8' }}>+</span>
                  )}
                </React.Fragment>
              ))}
            </span>
          </div>
        ))}
      </div>

      <div style={styles.sectionLabel}>About</div>
      <div style={styles.version}>
        <strong>ART Voice Agent Accelerator</strong>
        <br />
        Developer Toolbar v1.0
      </div>
    </div>
  );
};

export default SettingsSection;
