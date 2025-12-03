import React, { useCallback, useState } from 'react';
import { IconButton } from '@mui/material';
import MicNoneRoundedIcon from '@mui/icons-material/MicNoneRounded';
import MicOffRoundedIcon from '@mui/icons-material/MicOffRounded';
import RecordVoiceOverRoundedIcon from '@mui/icons-material/RecordVoiceOverRounded';
import StopCircleRoundedIcon from '@mui/icons-material/StopCircleRounded';
import PhoneDisabledRoundedIcon from '@mui/icons-material/PhoneDisabledRounded';
import PhoneRoundedIcon from '@mui/icons-material/PhoneRounded';
import RestartAltRoundedIcon from '@mui/icons-material/RestartAltRounded';
import MicRoundedIcon from '@mui/icons-material/MicRounded';
import PhoneInTalkRoundedIcon from '@mui/icons-material/PhoneInTalkRounded';
import KeyboardRoundedIcon from '@mui/icons-material/KeyboardRounded';
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
        <div style={styles.viewInlineSwitch}>
          {["chat", "graph", "timeline"].map((mode) => (
            <button
              key={mode}
              type="button"
              style={styles.viewInlineButton(mainView === mode)}
              onClick={() => onMainViewChange(mode)}
            >
              {mode === "chat" ? "Chat" : mode === "graph" ? "Graph" : "Timeline"}
            </button>
          ))}
        </div>
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
