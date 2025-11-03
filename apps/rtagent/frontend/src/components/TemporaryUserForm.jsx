import React, { useMemo, useState } from 'react';

const formStyles = {
  container: {
    margin: '0',
    padding: '24px 28px 28px 28px',
    maxWidth: '420px',
    width: '420px',
    borderRadius: '24px',
    border: '1px solid rgba(226, 232, 240, 0.8)',
    background: 'linear-gradient(135deg, rgba(255, 255, 255, 0.95) 0%, rgba(248, 250, 252, 0.98) 100%)',
    backdropFilter: 'blur(20px)',
    display: 'flex',
    flexDirection: 'column',
    gap: '16px',
    position: 'relative',
    overflow: 'hidden',
    transform: 'translateY(0)',
    transition: 'all 0.4s cubic-bezier(0.4, 0, 0.2, 1)',
  },
  headerRow: {
    display: 'flex',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    gap: '20px',
    marginBottom: '4px',
  },
  titleSection: {
    display: 'flex',
    flexDirection: 'column',
    gap: '6px',
    flex: 1,
  },
  title: {
    fontSize: '20px',
    fontWeight: 700,
    background: 'linear-gradient(135deg, #1e293b 0%, #3b82f6 100%)',
    backgroundClip: 'text',
    WebkitBackgroundClip: 'text',
    WebkitTextFillColor: 'transparent',
    margin: 0,
    letterSpacing: '-0.025em',
  },
  subtitle: {
    fontSize: '13px',
    color: '#64748b',
    margin: 0,
    lineHeight: 1.5,
    fontWeight: 400,
  },
  closeButton: {
    background: 'rgba(148, 163, 184, 0.1)',
    border: 'none',
    color: '#64748b',
    fontSize: '16px',
    lineHeight: 1,
    cursor: 'pointer',
    padding: '8px',
    borderRadius: '8px',
    transition: 'all 0.2s ease',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: '32px',
    height: '32px',
    flexShrink: 0,
  },
  closeButtonHover: {
    background: 'rgba(239, 68, 68, 0.1)',
    color: '#ef4444',
    transform: 'scale(1.05)',
  },
  warning: {
    fontSize: '12px',
    color: '#dc2626',
    background: 'linear-gradient(135deg, rgba(254, 242, 242, 0.9) 0%, rgba(252, 165, 165, 0.1) 100%)',
    border: '1px solid rgba(252, 165, 165, 0.3)',
    borderRadius: '12px',
    padding: '12px 16px',
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    backdropFilter: 'blur(10px)',
    fontWeight: 500,
  },
  form: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: '16px',
    marginTop: '8px',
  },
  formRow: {
    display: 'flex',
    flexDirection: 'column',
    gap: '8px',
    position: 'relative',
  },
  formRowFull: {
    gridColumn: '1 / -1',
  },
  label: {
    fontSize: '12px',
    fontWeight: 600,
    color: '#374151',
    letterSpacing: '0.025em',
    marginBottom: '2px',
    transition: 'color 0.2s ease',
  },
  labelFocused: {
    color: '#3b82f6',
  },
  inputContainer: {
    position: 'relative',
  },
  input: {
    width: '100%',
    padding: '14px 16px',
    borderRadius: '12px',
    border: '2px solid #e5e7eb',
    fontSize: '14px',
    color: '#1f2937',
    outline: 'none',
    background: 'rgba(255, 255, 255, 0.8)',
    backdropFilter: 'blur(10px)',
    boxShadow: '0 1px 3px rgba(0, 0, 0, 0.05), inset 0 1px 2px rgba(0, 0, 0, 0.02)',
    transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
    fontWeight: 500,
    WebkitTextFillColor: '#1f2937',
    MozAppearance: 'none',
    appearance: 'none',
    boxSizing: 'border-box',
  },
  inputFocused: {
    borderColor: '#3b82f6',
    background: 'rgba(255, 255, 255, 0.95)',
    boxShadow: '0 0 0 4px rgba(59, 130, 246, 0.1), 0 1px 3px rgba(0, 0, 0, 0.05)',
    transform: 'translateY(-1px)',
  },
  inputError: {
    borderColor: '#ef4444',
    background: 'rgba(254, 242, 242, 0.5)',
  },
  buttonRow: {
    gridColumn: '1 / -1',
    display: 'flex',
    justifyContent: 'flex-end',
    marginTop: '8px',
  },
  button: {
    padding: '16px 32px',
    borderRadius: '12px',
    border: 'none',
    fontSize: '14px',
    fontWeight: 600,
    cursor: 'pointer',
    background: 'linear-gradient(135deg, #3b82f6 0%, #1d4ed8 50%, #1e40af 100%)',
    color: '#ffffff',
    boxShadow: '0 10px 25px -5px rgba(59, 130, 246, 0.4), 0 4px 6px -2px rgba(59, 130, 246, 0.2)',
    transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
    position: 'relative',
    overflow: 'hidden',
    letterSpacing: '0.025em',
    minWidth: '140px',
  },
  buttonHover: {
    transform: 'translateY(-2px) scale(1.02)',
    boxShadow: '0 15px 35px -5px rgba(59, 130, 246, 0.5), 0 8px 15px -5px rgba(59, 130, 246, 0.3)',
  },
  buttonDisabled: {
    opacity: 0.6,
    cursor: 'not-allowed',
    transform: 'none',
    boxShadow: '0 2px 4px rgba(0, 0, 0, 0.1)',
  },
  buttonLoader: {
    display: 'inline-block',
    width: '16px',
    height: '16px',
    border: '2px solid rgba(255, 255, 255, 0.3)',
    borderRadius: '50%',
    borderTopColor: '#ffffff',
    animation: 'spin 1s ease-in-out infinite',
    marginRight: '8px',
  },
  status: {
    padding: '14px 18px',
    borderRadius: '12px',
    fontSize: '13px',
    fontWeight: 500,
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
    backdropFilter: 'blur(10px)',
    border: '1px solid transparent',
    transition: 'all 0.3s ease',
  },
  statusSuccess: {
    background: 'linear-gradient(135deg, rgba(240, 253, 244, 0.9) 0%, rgba(187, 247, 208, 0.2) 100%)',
    border: '1px solid rgba(34, 197, 94, 0.2)',
    color: '#059669',
  },
  statusError: {
    background: 'linear-gradient(135deg, rgba(254, 242, 242, 0.9) 0%, rgba(252, 165, 165, 0.2) 100%)',
    border: '1px solid rgba(239, 68, 68, 0.2)',
    color: '#dc2626',
  },
  statusIcon: {
    fontSize: '16px',
    flexShrink: 0,
  },
  resultCard: {
    borderRadius: '12px',
    border: '1px solid rgba(226, 232, 240, 0.8)',
    padding: '16px 20px',
    background: 'linear-gradient(135deg, rgba(248, 250, 252, 0.8) 0%, rgba(241, 245, 249, 0.6) 100%)',
    backdropFilter: 'blur(10px)',
    display: 'grid',
    gap: '8px',
    fontSize: '13px',
    color: '#0f172a',
    boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.05)',
  },
  resultList: {
    margin: '6px 0 0',
    paddingLeft: '20px',
    color: '#475569',
    lineHeight: '1.5',
  },
  ssnBanner: {
    padding: '14px 16px',
    borderRadius: '12px',
    background: 'linear-gradient(135deg, #f97316 0%, #ef4444 100%)',
    color: '#ffffff',
    fontWeight: 700,
    fontSize: '14px',
    textAlign: 'center',
    letterSpacing: '0.5px',
    boxShadow: '0 8px 25px -8px rgba(239, 68, 68, 0.4)',
  },
  cautionBox: {
    marginTop: '12px',
    padding: '12px 16px',
    borderRadius: '12px',
    background: 'linear-gradient(135deg, rgba(254, 242, 242, 0.9) 0%, rgba(252, 165, 165, 0.1) 100%)',
    border: '1px solid rgba(239, 68, 68, 0.2)',
    color: '#b91c1c',
    fontSize: '12px',
    fontWeight: 600,
    textAlign: 'center',
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
    backdropFilter: 'blur(10px)',
  },
};

// Add keyframe animations
const styleSheet = document.createElement('style');
styleSheet.textContent = `
  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }
  @keyframes slideInUp {
    from {
      opacity: 0;
      transform: translateY(20px);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }
`;
if (!document.head.querySelector('style[data-form-animations]')) {
  styleSheet.setAttribute('data-form-animations', 'true');
  document.head.appendChild(styleSheet);
}

const TemporaryUserForm = ({ apiBaseUrl, onClose, sessionId, onSuccess }) => {
  const [formState, setFormState] = useState({
    full_name: '',
    email: '',
    phone_number: '',
    preferred_channel: 'email',
  });
  const [status, setStatus] = useState({ type: 'idle', message: '', data: null });
  const [focusedField, setFocusedField] = useState(null);
  const [isButtonHovered, setIsButtonHovered] = useState(false);
  const [isCloseHovered, setIsCloseHovered] = useState(false);

  const submitDisabled = useMemo(
    () =>
      status.type === 'pending' ||
      !formState.full_name.trim() ||
      !formState.email.trim(),
    [status.type, formState],
  );

  const handleChange = (event) => {
    const { name, value } = event.target;
    setFormState((prev) => ({ ...prev, [name]: value }));
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (submitDisabled) {
      return;
    }

    setStatus({ type: 'pending', message: 'Creating demo profile…', data: null });

    const payload = {
      full_name: formState.full_name.trim(),
      email: formState.email.trim(),
      preferred_channel: formState.preferred_channel,
    };
    if (formState.phone_number.trim()) {
      payload.phone_number = formState.phone_number.trim();
    }
    if (sessionId) {
      payload.session_id = sessionId;
    }

    try {
      const response = await fetch(`${apiBaseUrl}/api/v1/demo-env/temporary-user`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail?.detail || `Request failed (${response.status})`);
      }

      const data = await response.json();
      setStatus({
        type: 'success',
        message: 'Demo profile ready. Check the User Profile panel for details.',
        data: { safety_notice: data?.safety_notice },
      });
      onSuccess?.(data);
      setFormState({ full_name: '', email: '', phone_number: '', preferred_channel: 'email' });
    } catch (error) {
      setStatus({
        type: 'error',
        message: error.message || 'Unable to create demo profile.',
        data: null,
      });
    }
  };

  return (
    <section style={{
      ...formStyles.container,
      animation: 'slideInUp 0.4s cubic-bezier(0.4, 0, 0.2, 1)'
    }}>
      <div style={formStyles.headerRow}>
        <div style={formStyles.titleSection}>
          <h2 style={formStyles.title}>Create Demo Access</h2>
          <p style={formStyles.subtitle}>
            Generate a temporary 24-hour profile for testing. Phone number is optional for future SMS simulations.
          </p>
        </div>
        {onClose && (
          <button
            type="button"
            style={{
              ...formStyles.closeButton,
              ...(isCloseHovered ? formStyles.closeButtonHover : {})
            }}
            onMouseEnter={() => setIsCloseHovered(true)}
            onMouseLeave={() => setIsCloseHovered(false)}
            onClick={onClose}
            aria-label="Close demo form"
            title="Close demo form"
          >
            ✕
          </button>
        )}
      </div>
      <div style={formStyles.warning}>
        <span style={formStyles.statusIcon}>⚠️</span>
        <span>Demo environment - All data is automatically purged after 24 hours</span>
      </div>

      <form style={formStyles.form} onSubmit={handleSubmit}>
        <div style={formStyles.formRow}>
          <label 
            style={{
              ...formStyles.label,
              ...(focusedField === 'full_name' ? formStyles.labelFocused : {})
            }} 
            htmlFor="full_name"
          >
            Full Name
          </label>
          <div style={formStyles.inputContainer}>
            <input
              id="full_name"
              name="full_name"
              value={formState.full_name}
              onChange={handleChange}
              onFocus={() => setFocusedField('full_name')}
              onBlur={() => setFocusedField(null)}
              style={{
                ...formStyles.input,
                ...(focusedField === 'full_name' ? formStyles.inputFocused : {})
              }}
              placeholder="Ada Lovelace"
              required
            />
          </div>
        </div>
        <div style={formStyles.formRow}>
          <label 
            style={{
              ...formStyles.label,
              ...(focusedField === 'email' ? formStyles.labelFocused : {})
            }} 
            htmlFor="email"
          >
            Email Address
          </label>
          <div style={formStyles.inputContainer}>
            <input
              id="email"
              name="email"
              type="email"
              value={formState.email}
              onChange={handleChange}
              onFocus={() => setFocusedField('email')}
              onBlur={() => setFocusedField(null)}
              style={{
                ...formStyles.input,
                ...(focusedField === 'email' ? formStyles.inputFocused : {})
              }}
              placeholder="ada@example.com"
              required
            />
          </div>
        </div>
        <div style={formStyles.formRow}>
          <label 
            style={{
              ...formStyles.label,
              ...(focusedField === 'phone_number' ? formStyles.labelFocused : {})
            }} 
            htmlFor="phone_number"
          >
            Phone Number (Coming Soon)
          </label>
          <div style={formStyles.inputContainer}>
            <input
              id="phone_number"
              name="phone_number"
              value={formState.phone_number}
              onChange={handleChange}
              onFocus={() => setFocusedField('phone_number')}
              onBlur={() => setFocusedField(null)}
              disabled
              style={{
                ...formStyles.input,
                ...(focusedField === 'phone_number' ? formStyles.inputFocused : {}),
                opacity: 0.6,
                cursor: 'not-allowed'
              }}
              placeholder="+1 (555) 123-4567 (Coming Soon)"
            />
          </div>
        </div>
        <div style={{ ...formStyles.formRow, ...formStyles.formRowFull }}>
          <label 
            style={{
              ...formStyles.label,
              ...(focusedField === 'preferred_channel' ? formStyles.labelFocused : {})
            }} 
            htmlFor="preferred_channel"
          >
            Verification Method
          </label>
          <div style={formStyles.inputContainer}>
            <select
              id="preferred_channel"
              name="preferred_channel"
              value={formState.preferred_channel}
              onChange={handleChange}
              onFocus={() => setFocusedField('preferred_channel')}
              onBlur={() => setFocusedField(null)}
              style={{
                ...formStyles.input,
                ...(focusedField === 'preferred_channel' ? formStyles.inputFocused : {}),
                paddingRight: '32px',
                backgroundImage: 'url("data:image/svg+xml,%3csvg xmlns=\'http://www.w3.org/2000/svg\' fill=\'none\' viewBox=\'0 0 20 20\'%3e%3cpath stroke=\'%236b7280\' stroke-linecap=\'round\' stroke-linejoin=\'round\' stroke-width=\'1.5\' d=\'m6 8 4 4 4-4\'/%3e%3c/svg%3e")',
                backgroundPosition: 'right 12px center',
                backgroundRepeat: 'no-repeat',
                backgroundSize: '16px',
              }}
            >
              <option value="email">📧 Email Verification</option>
              <option value="sms" disabled>📱 SMS Verification (Coming Soon)</option>
            </select>
          </div>
        </div>
        <div style={formStyles.buttonRow}>
          <button
            type="submit"
            style={{
              ...formStyles.button,
              ...(submitDisabled ? formStyles.buttonDisabled : {}),
              ...(isButtonHovered && !submitDisabled ? formStyles.buttonHover : {}),
            }}
            onMouseEnter={() => setIsButtonHovered(true)}
            onMouseLeave={() => setIsButtonHovered(false)}
            disabled={submitDisabled}
          >
            {status.type === 'pending' && (
              <span style={formStyles.buttonLoader}></span>
            )}
            {status.type === 'pending' ? 'Creating Profile...' : 'Create Demo Profile'}
          </button>
        </div>
      </form>

      {status.type !== 'idle' && status.message && (
        <div
          style={{
            ...formStyles.status,
            ...(status.type === 'success' ? formStyles.statusSuccess : formStyles.statusError),
            animation: 'slideInUp 0.3s ease-out'
          }}
        >
          <span style={formStyles.statusIcon}>
            {status.type === 'success' ? '✅' : '❌'}
          </span>
          <div>
            {status.message}
            {status.type === 'success' && status.data?.safety_notice && (
              <div style={{ marginTop: '6px', fontWeight: 600, fontSize: '12px', opacity: 0.8 }}>
                {status.data.safety_notice}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Demo details now live in the main UI profile panel */}
    </section>
  );
};

export default TemporaryUserForm;
