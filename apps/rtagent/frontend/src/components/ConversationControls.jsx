import React, { useCallback, useState } from 'react';
import { IconButton } from '@mui/material';
import MicNoneRoundedIcon from '@mui/icons-material/MicNoneRounded';
import MicOffRoundedIcon from '@mui/icons-material/MicOffRounded';
import RecordVoiceOverRoundedIcon from '@mui/icons-material/RecordVoiceOverRounded';
import StopCircleRoundedIcon from '@mui/icons-material/StopCircleRounded';
import PhoneDisabledRoundedIcon from '@mui/icons-material/PhoneDisabledRounded';
import PhoneRoundedIcon from '@mui/icons-material/PhoneRounded';
import RestartAltRoundedIcon from '@mui/icons-material/RestartAltRounded';
import { styles } from '../styles/voiceAppStyles.js';

const ConversationControls = React.memo(({
  recording,
  callActive,
  isCallDisabled,
  onResetSession,
  onMicToggle,
  onPhoneButtonClick,
  phoneButtonRef,
  micButtonRef,
  micMuted,
  onMuteToggle,
  mainView,
  onMainViewChange,
}) => {
  const [resetHovered, setResetHovered] = useState(false);
  const [micHovered, setMicHovered] = useState(false);
  const [phoneHovered, setPhoneHovered] = useState(false);
  const [muteHovered, setMuteHovered] = useState(false);
  const [showResetTooltip, setShowResetTooltip] = useState(false);
  const [showMicTooltip, setShowMicTooltip] = useState(false);
  const [showPhoneTooltip, setShowPhoneTooltip] = useState(false);
  const [showMuteTooltip, setShowMuteTooltip] = useState(false);
  const [phoneDisabledPos, setPhoneDisabledPos] = useState(null);
  const [resetTooltipPos, setResetTooltipPos] = useState(null);
  const [micTooltipPos, setMicTooltipPos] = useState(null);
  const [phoneTooltipPos, setPhoneTooltipPos] = useState(null);
  const [muteTooltipPos, setMuteTooltipPos] = useState(null);

  const handlePhoneMouseEnter = useCallback((event) => {
    setShowPhoneTooltip(true);
    const target = phoneButtonRef?.current || event?.currentTarget;
    if (target) {
      const rect = target.getBoundingClientRect();
      setPhoneTooltipPos({
        top: rect.bottom + 12,
        left: rect.left + rect.width / 2,
      });
      setPhoneDisabledPos({
        top: rect.bottom + 12,
        left: rect.left + rect.width / 2,
      });
    }
    if (!isCallDisabled) {
      setPhoneHovered(true);
    }
  }, [isCallDisabled, phoneButtonRef]);

  const handlePhoneMouseLeave = useCallback(() => {
    setShowPhoneTooltip(false);
    setPhoneHovered(false);
    setPhoneDisabledPos(null);
    setPhoneTooltipPos(null);
  }, []);

  return (
    <div style={styles.controlSection}>
      <div style={styles.controlContainer}>
        {/* Reset */}
        <div style={{ position: 'relative' }}>
          <IconButton
            disableRipple
            aria-label="Reset session"
            sx={styles.resetButton(resetHovered)}
            onMouseEnter={(event) => {
              setShowResetTooltip(true);
              setResetHovered(true);
              const rect = event.currentTarget.getBoundingClientRect();
              setResetTooltipPos({
                top: rect.bottom + 12,
                left: rect.left + rect.width / 2,
              });
            }}
            onMouseLeave={() => {
              setShowResetTooltip(false);
              setResetHovered(false);
              setResetTooltipPos(null);
            }}
            onClick={onResetSession}
          >
            <RestartAltRoundedIcon fontSize="medium" />
          </IconButton>
          {showResetTooltip && resetTooltipPos && (
            <div
              style={{
                ...styles.buttonTooltip,
                top: resetTooltipPos.top,
                left: resetTooltipPos.left,
                ...(showResetTooltip ? styles.buttonTooltipVisible : {}),
              }}
            >
              Reset conversation & start fresh
            </div>
          )}
        </div>

        {/* Mute */}
        <div
          style={{ position: 'relative' }}
          onMouseEnter={(event) => {
            const target = event.currentTarget.querySelector('button') ?? event.currentTarget;
            const rect = target.getBoundingClientRect();
            setMuteTooltipPos({
              top: rect.bottom + 12,
              left: rect.left + rect.width / 2,
            });
            setShowMuteTooltip(true);
            if (recording) {
              setMuteHovered(true);
            }
          }}
          onMouseLeave={() => {
            setShowMuteTooltip(false);
            setMuteHovered(false);
            setMuteTooltipPos(null);
          }}
        >
          <IconButton
            disableRipple
            aria-label={micMuted ? "Unmute microphone" : "Mute microphone"}
            sx={styles.muteButton(micMuted, muteHovered, !recording)}
            disabled={!recording}
            onClick={() => {
              if (!recording) {
                return;
              }
              onMuteToggle();
            }}
          >
            {micMuted ? (
              <MicOffRoundedIcon fontSize="medium" />
            ) : (
              <MicNoneRoundedIcon fontSize="medium" />
            )}
          </IconButton>
          {showMuteTooltip && muteTooltipPos && (
            <div
              style={{
                ...styles.buttonTooltip,
                top: muteTooltipPos.top,
                left: muteTooltipPos.left,
                ...(showMuteTooltip ? styles.buttonTooltipVisible : {}),
              }}
            >
              {recording
                ? micMuted
                  ? "Resume sending microphone audio"
                  : "Temporarily mute your microphone"
                : "Start the microphone to enable mute"}
            </div>
          )}
        </div>

        {/* Mic */}
        <div style={{ position: 'relative' }}>
          <IconButton
            disableRipple
            aria-label={recording ? "End conversation with agent" : "Start talking to agent"}
            sx={styles.micButton(recording, micHovered)}
            ref={micButtonRef}
            onMouseEnter={(event) => {
              setShowMicTooltip(true);
              setMicHovered(true);
              const rect = event.currentTarget.getBoundingClientRect();
              setMicTooltipPos({
                top: rect.bottom + 12,
                left: rect.left + rect.width / 2,
              });
            }}
            onMouseLeave={() => {
              setShowMicTooltip(false);
              setMicHovered(false);
              setMicTooltipPos(null);
            }}
            onClick={onMicToggle}
          >
            {recording ? (
              <StopCircleRoundedIcon fontSize="medium" />
            ) : (
              <RecordVoiceOverRoundedIcon fontSize="medium" />
            )}
          </IconButton>
          {showMicTooltip && micTooltipPos && (
            <div
              style={{
                ...styles.buttonTooltip,
                top: micTooltipPos.top,
                left: micTooltipPos.left,
                ...(showMicTooltip ? styles.buttonTooltipVisible : {}),
              }}
            >
              {recording ? "End the conversation" : "Start talking to the agent"}
            </div>
          )}
        </div>

        {/* Call */}
        <div
          style={{ position: 'relative' }}
          onMouseEnter={handlePhoneMouseEnter}
          onMouseLeave={handlePhoneMouseLeave}
        >
          <IconButton
            ref={phoneButtonRef}
            disableRipple
            aria-label={callActive ? "Hang up call" : "Place call"}
            sx={styles.phoneButton(callActive, phoneHovered, isCallDisabled)}
            disabled={isCallDisabled && !callActive}
            onClick={onPhoneButtonClick}
          >
            {callActive ? (
              <PhoneDisabledRoundedIcon fontSize="medium" sx={{ transform: 'rotate(135deg)', transition: 'transform 0.3s ease' }} />
            ) : (
              <PhoneRoundedIcon fontSize="medium" />
            )}
          </IconButton>
          {!isCallDisabled && showPhoneTooltip && phoneTooltipPos && (
            <div
              style={{
                ...styles.buttonTooltip,
                top: phoneTooltipPos.top,
                left: phoneTooltipPos.left,
                ...(showPhoneTooltip ? styles.buttonTooltipVisible : {}),
              }}
            >
              {callActive ? "End the conversation" : "Start a conversation"}
            </div>
          )}
        </div>
      </div>

      {typeof onMainViewChange === "function" && (
        <>
          {/* Mini floating view selector (non-intrusive, above main cluster) */}
          <div
            style={{
              position: "fixed",
              right: "28px",
              bottom: "72px",
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "6px 6px",
              borderRadius: 12,
              background: "rgba(255,255,255,0.42)",
              backdropFilter: "blur(10px)",
              border: "1px solid rgba(148,163,184,0.35)",
              boxShadow: "0 10px 26px rgba(15,23,42,0.12)",
              zIndex: 19,
            }}
          >
            {[
              { mode: "chat", label: "C" },
              { mode: "graph", label: "G" },
              { mode: "timeline", label: "T" },
            ].map(({ mode, label }) => {
              const active = mainView === mode;
              return (
                <button
                  key={mode}
                  type="button"
                  aria-label={`Switch to ${mode}`}
                  style={{
                    width: 34,
                    height: 34,
                    borderRadius: 10,
                    border: active ? "1px solid #2563eb" : "1px solid rgba(148,163,184,0.45)",
                    background: active
                      ? "linear-gradient(135deg, rgba(59,130,246,0.2), rgba(59,130,246,0.08))"
                      : "rgba(255,255,255,0.75)",
                    color: active ? "#0f172a" : "#475569",
                    fontWeight: 700,
                    fontSize: 12,
                    cursor: "pointer",
                    transition: "all 0.14s ease",
                    boxShadow: active ? "0 8px 14px rgba(59,130,246,0.15)" : "none",
                  }}
                  onClick={() => onMainViewChange(mode)}
                >
                  {label}
                </button>
              );
            })}
          </div>

          {/* Full view selector (existing control cluster) */}
          <div
            style={{
              position: "fixed",
              right: "20px",
              bottom: "24px",
              display: "flex",
              alignItems: "center",
              gap: 8,
              zIndex: 18,
            }}
          >
            <span style={{ fontSize: 11, color: "#94a3b8", paddingLeft: 4 }}>View</span>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                padding: "6px 8px",
                borderRadius: 12,
                background: "rgba(255,255,255,0.92)",
                border: "1px solid #e5e7eb",
                boxShadow: "0 8px 20px rgba(15,23,42,0.14)",
              }}
            >
              {["chat", "graph", "timeline"].map((mode) => {
                const active = mainView === mode;
                return (
                  <button
                    key={mode}
                    type="button"
                    style={{
                      border: "1px solid " + (active ? "#3b82f6" : "#e5e7eb"),
                      background: active ? "linear-gradient(135deg, #dbeafe 0%, #eff6ff 100%)" : "#ffffff",
                      color: active ? "#0f172a" : "#475569",
                      borderRadius: 10,
                      padding: "6px 10px",
                      fontSize: 12,
                      fontWeight: 600,
                      cursor: "pointer",
                      minWidth: 68,
                      transition: "all 0.12s ease",
                    }}
                    onClick={() => onMainViewChange(mode)}
                  >
                    {mode === "chat"
                      ? "Chat"
                      : mode === "graph"
                        ? "Graph"
                        : "Timeline"}
                  </button>
                );
              })}
            </div>
          </div>
        </>
      )}

      {isCallDisabled && showPhoneTooltip && phoneDisabledPos && (
        <div
          style={{
            ...styles.phoneDisabledDialog,
            top: phoneDisabledPos.top,
            left: phoneDisabledPos.left,
          }}
        >
          ⚠️ Outbound calling is disabled. Update backend .env with Azure Communication Services settings (ACS_CONNECTION_STRING, ACS_SOURCE_PHONE_NUMBER, ACS_ENDPOINT) to enable this feature.
        </div>
      )}
    </div>
  );
});

export default React.memo(ConversationControls);
