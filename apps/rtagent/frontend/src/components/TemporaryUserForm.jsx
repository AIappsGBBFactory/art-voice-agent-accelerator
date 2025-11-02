import React, { useMemo, useState } from 'react';

const formStyles = {
  container: {
    margin: '0',
    padding: '16px 20px',
    maxWidth: '360px',
    width: '360px',
    borderRadius: '16px',
    border: '1px solid #e2e8f0',
    background: '#ffffff',
    boxShadow: '0 12px 32px rgba(15, 23, 42, 0.12)',
    display: 'flex',
    flexDirection: 'column',
    gap: '12px',
  },
  headerRow: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: '16px',
  },
  title: {
    fontSize: '16px',
    fontWeight: 600,
    color: '#0f172a',
    margin: 0,
  },
  subtitle: {
    fontSize: '12px',
    color: '#64748b',
    margin: 0,
    lineHeight: 1.5,
  },
  closeButton: {
    background: 'transparent',
    border: 'none',
    color: '#0f172a',
    fontSize: '20px',
    lineHeight: 1,
    cursor: 'pointer',
    padding: '0 4px',
  },
  warning: {
    fontSize: '11px',
    color: '#dc2626',
    background: '#fef2f2',
    border: '1px solid #fecaca',
    borderRadius: '8px',
    padding: '8px 10px',
  },
  form: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: '12px',
  },
  formRow: {
    display: 'flex',
    flexDirection: 'column',
    gap: '6px',
  },
  label: {
    fontSize: '11px',
    fontWeight: 600,
    color: '#475569',
    textTransform: 'uppercase',
    letterSpacing: '0.4px',
  },
  input: {
    padding: '10px 12px',
    borderRadius: '10px',
    border: '1px solid #cbd5f5',
    fontSize: '13px',
    color: '#1f2937',
    outline: 'none',
    background: '#fff', // Always white background
    boxShadow: '0 1px 2px rgba(0,0,0,0.04)',
    transition: 'border-color 0.2s ease, box-shadow 0.2s ease',
    // Prevent system dark mode from affecting input
    WebkitTextFillColor: '#1f2937',
    // For Firefox
    MozAppearance: 'none',
    appearance: 'none',
  },
  buttonRow: {
    gridColumn: '1 / -1',
    display: 'flex',
    justifyContent: 'flex-end',
  },
  button: {
    padding: '10px 18px',
    borderRadius: '10px',
    border: 'none',
    fontSize: '13px',
    fontWeight: 600,
    cursor: 'pointer',
    background: 'linear-gradient(135deg, #3b82f6, #1d4ed8)',
    color: '#ffffff',
    boxShadow: '0 8px 16px rgba(37, 99, 235, 0.2)',
    transition: 'transform 0.2s ease, box-shadow 0.2s ease',
  },
  buttonDisabled: {
    opacity: 0.65,
    cursor: 'not-allowed',
    boxShadow: 'none',
    transform: 'scale(1)',
  },
  status: {
    padding: '10px 14px',
    borderRadius: '10px',
    fontSize: '12px',
  },
  statusSuccess: {
    background: '#f0fdf4',
    border: '1px solid #bbf7d0',
    color: '#166534',
  },
  statusError: {
    background: '#fef2f2',
    border: '1px solid #fecaca',
    color: '#b91c1c',
  },
  resultCard: {
    borderRadius: '10px',
    border: '1px solid #e2e8f0',
    padding: '12px 14px',
    background: '#f8fafc',
    display: 'grid',
    gap: '6px',
    fontSize: '12px',
    color: '#0f172a',
  },
  resultList: {
    margin: '4px 0 0',
    paddingLeft: '18px',
    color: '#475569',
  },
  ssnBanner: {
    padding: '10px 12px',
    borderRadius: '10px',
    background: 'linear-gradient(135deg, #f97316, #ef4444)',
    color: '#ffffff',
    fontWeight: 700,
    fontSize: '13px',
    textAlign: 'center',
    letterSpacing: '0.6px',
  },
  cautionBox: {
    marginTop: '8px',
    padding: '10px 12px',
    borderRadius: '10px',
    background: '#fef2f2',
    border: '1px solid #fecaca',
    color: '#b91c1c',
    fontSize: '11px',
    fontWeight: 600,
    textAlign: 'center',
    textTransform: 'uppercase',
  },
};

const TemporaryUserForm = ({ apiBaseUrl, onClose, sessionId, onSuccess }) => {
  const [formState, setFormState] = useState({
    full_name: '',
    email: '',
    phone_number: '',
  });
  const [status, setStatus] = useState({ type: 'idle', message: '', data: null });

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
      setFormState({ full_name: '', email: '', phone_number: '' });
    } catch (error) {
      setStatus({
        type: 'error',
        message: error.message || 'Unable to create demo profile.',
        data: null,
      });
    }
  };

  return (
    <section style={formStyles.container}>
      <div style={formStyles.headerRow}>
        <h2 style={formStyles.title}>Create 1-Hour Demo Access</h2>
        {onClose && (
          <button
            type="button"
            style={formStyles.closeButton}
            onClick={onClose}
            aria-label="Close demo form"
            title="Close demo form"
          >
            ×
          </button>
        )}
      </div>
      <p style={formStyles.subtitle}>
        Supply your details to generate a temporary profile that is automatically purged after
        1 hour. Phone number is optional and used only for SMS simulations.
      </p>
      <div style={formStyles.warning}>
        ⚠️ This environment is for demonstration purposes only. All records are erased after 1 hour.
      </div>

      <form style={formStyles.form} onSubmit={handleSubmit}>
        <div style={formStyles.formRow}>
          <label style={formStyles.label} htmlFor="full_name">
            Full Name
          </label>
          <input
            id="full_name"
            name="full_name"
            value={formState.full_name}
            onChange={handleChange}
            style={formStyles.input}
            placeholder="Ada Lovelace"
            required
          />
        </div>
        <div style={formStyles.formRow}>
          <label style={formStyles.label} htmlFor="email">
            Email
          </label>
          <input
            id="email"
            name="email"
            type="email"
            value={formState.email}
            onChange={handleChange}
            style={formStyles.input}
            placeholder="ada@example.com"
            required
          />
        </div>
        <div style={formStyles.formRow}>
          <label style={formStyles.label} htmlFor="phone_number">
            Phone (Optional)
          </label>
          <input
            id="phone_number"
            name="phone_number"
            value={formState.phone_number}
            onChange={handleChange}
            style={formStyles.input}
            placeholder="+15551234567"
          />
        </div>
        <div style={formStyles.buttonRow}>
          <button
            type="submit"
            style={{
              ...formStyles.button,
              ...(submitDisabled ? formStyles.buttonDisabled : {}),
            }}
            disabled={submitDisabled}
          >
            {status.type === 'pending' ? 'Creating…' : 'Create Demo Profile'}
          </button>
        </div>
      </form>

      {status.type !== 'idle' && status.message && (
        <div
          style={{
            ...formStyles.status,
            ...(status.type === 'success' ? formStyles.statusSuccess : formStyles.statusError),
          }}
        >
          {status.message}
          {status.type === 'success' && status.data?.safety_notice && (
            <div style={{ marginTop: '6px', fontWeight: 600 }}>{status.data.safety_notice}</div>
          )}
        </div>
      )}

      {/* Demo details now live in the main UI profile panel */}
    </section>
  );
};

export default TemporaryUserForm;
