import React from 'react';

/**
 * Use Case Selector Component - Top Left Status Indicator Style
 * Simple dropdown selector with no complex state management
 */

const OPTIONS = [
  { value: 'insurance', label: 'Insurance Services', icon: '🏥' },
  { value: 'healthcare', label: 'Healthcare Services', icon: '💊' },
  { value: 'finance', label: 'Finance Services', icon: '💰' }
];

const UseCaseSelector = ({ value, onChange, disabled }) => {
  const selectedOption = OPTIONS.find(opt => opt.value === value) || OPTIONS[0];

  return (
    <div style={styles.container}>
      <div style={styles.wrapper}>
        <span style={styles.icon}>{selectedOption.icon}</span>
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
          style={{
            ...styles.select,
            ...(disabled ? styles.selectDisabled : {})
          }}
        >
          {OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
};

const styles = {
  container: {
    position: 'absolute',
    top: '40px',
    left: '24px',
    zIndex: 1000,
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
  },
  wrapper: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    padding: '6px 10px',
    backgroundColor: 'white',
    border: '1px solid #e2e8f0',
    borderRadius: '6px',
    boxShadow: '0 1px 3px rgba(0, 0, 0, 0.1)'
  },
  icon: {
    fontSize: '14px'
  },
  select: {
    border: 'none',
    outline: 'none',
    backgroundColor: 'transparent',
    fontSize: '12px',
    fontWeight: '500',
    color: '#475569',
    cursor: 'pointer',
    fontFamily: 'inherit'
  },
  selectDisabled: {
    opacity: 0.5,
    cursor: 'not-allowed'
  }
};

export default UseCaseSelector;
