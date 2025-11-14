import React from 'react';

const containerStyle = {
  display: 'flex',
  flexDirection: 'column',
  gap: '8px',
  width: '100%',
  maxWidth: '320px',
  padding: '10px 12px',
  borderRadius: '14px',
  background: 'rgba(255,255,255,0.9)',
  border: '1px solid rgba(226,232,240,0.8)',
  boxShadow: '0 8px 20px rgba(15,23,42,0.12)',
  boxSizing: 'border-box',
};

const headerStyle = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  fontSize: '11px',
  color: '#475569',
  fontWeight: 600,
  letterSpacing: '0.03em',
};

const badgeStyle = {
  fontSize: '9px',
  padding: '2px 8px',
  borderRadius: '999px',
  backgroundColor: 'rgba(59, 130, 246, 0.12)',
  color: '#2563eb',
  textTransform: 'uppercase',
  letterSpacing: '0.08em',
};

const optionsRowStyle = {
  display: 'flex',
  flexDirection: 'column',
  gap: '8px',
  width: '100%',
};

const baseCardStyle = {
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'flex-start',
  gap: '6px',
  padding: '10px 12px',
  width: '100%',
  borderRadius: '12px',
  border: '1px solid rgba(226,232,240,0.9)',
  background: '#f8fafc',
  cursor: 'pointer',
  transition: 'all 0.2s ease',
  boxShadow: '0 4px 8px rgba(15, 23, 42, 0.08)',
  textAlign: 'left',
};

const selectedCardStyle = {
  borderColor: 'rgba(99,102,241,0.85)',
  boxShadow: '0 8px 16px rgba(99,102,241,0.22)',
  background: 'linear-gradient(135deg, rgba(255,255,255,0.98) 0%, rgba(224,231,255,0.9) 100%)',
};

const optionHeaderStyle = {
  display: 'flex',
  alignItems: 'center',
  gap: '10px',
  width: '100%',
};

const textBlockStyle = {
  display: 'flex',
  flexDirection: 'column',
  gap: '1px',
};

const disabledCardStyle = {
  cursor: 'not-allowed',
  opacity: 0.6,
  boxShadow: 'none',
};

const iconStyle = {
  fontSize: '18px',
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  width: '26px',
};

const titleStyle = {
  fontSize: '12px',
  fontWeight: 700,
  color: '#0f172a',
  margin: 0,
};

const descriptionStyle = {
  fontSize: '10px',
  color: '#475569',
  margin: 0,
  lineHeight: 1.5,
};

const hintStyle = {
  fontSize: '9px',
  color: '#1d4ed8',
  fontWeight: 600,
  textTransform: 'uppercase',
  letterSpacing: '0.06em',
};

const footerNoteStyle = {
  fontSize: '9px',
  color: '#94a3b8',
  lineHeight: 1.4,
};

const STREAMING_MODE_OPTIONS = [
  {
    value: 'voice_live',
    label: 'Voice Live',
    icon: '⚡️',
    description:
      'Ultra-low latency playback via Azure AI Voice Live. Ideal for PSTN calls with barge-in.',
    hint: 'Recommended',
  },
  {
    value: 'media',
    label: 'Media Handler',
    icon: '🎧',
    description:
      'Three-thread ACS media pipeline with custom orchestration. Best for advanced agent control.',
  },
  // {
  //   value: 'transcription',
  //   label: 'Transcription',
  //   icon: '📝',
  //   description:
  //     'Capture audio for speech-to-text only. Choose when you do not need TTS playback.',
  // },
];

function StreamingModeSelector({ value, onChange, disabled = false }) {
  return (
    <div style={containerStyle}>
      <div style={headerStyle}>
        <span>ACS Streaming Mode</span>
        <span style={badgeStyle}>Per call</span>
      </div>
      <div style={optionsRowStyle}>
        {STREAMING_MODE_OPTIONS.map((option) => {
          const isSelected = option.value === value;
          return (
            <button
              key={option.value}
              type="button"
              onClick={() => {
                if (!disabled && option.value !== value) {
                  onChange?.(option.value);
                }
              }}
              style={{
                ...baseCardStyle,
                ...(isSelected ? selectedCardStyle : {}),
                ...(disabled ? disabledCardStyle : {}),
              }}
              disabled={disabled}
            >
              <div style={optionHeaderStyle}>
                <span style={iconStyle}>{option.icon}</span>
                <div style={textBlockStyle}>
                  <p style={titleStyle}>{option.label}</p>
                  <p style={descriptionStyle}>{option.description}</p>
                </div>
              </div>
              {option.hint && isSelected && <span style={hintStyle}>{option.hint}</span>}
            </button>
          );
        })}
      </div>
      <div style={footerNoteStyle}>
        Active mode applies to ACS PSTN calls only. Browser/WebRTC streaming remains unchanged.
      </div>
    </div>
  );
}

StreamingModeSelector.options = STREAMING_MODE_OPTIONS;
StreamingModeSelector.getLabel = (streamMode) => {
  const match = STREAMING_MODE_OPTIONS.find((option) => option.value === streamMode);
  return match ? match.label : streamMode;
};

export default StreamingModeSelector;
