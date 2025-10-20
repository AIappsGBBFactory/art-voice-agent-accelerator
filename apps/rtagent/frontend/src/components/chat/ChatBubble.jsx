import React from "react";
import { formatDuration } from "../../utils/format";

const styles = {
  userMessage: {
    alignSelf: "flex-end",
    maxWidth: "75%",
    marginRight: "15px",
    marginBottom: "4px",
  },
  assistantMessage: {
    alignSelf: "flex-start",
    maxWidth: "80%",
    marginLeft: "0px",
    marginBottom: "4px",
  },
  userBubble: {
    background: "#e0f2fe",
    color: "#0f172a",
    padding: "12px 16px",
    borderRadius: "20px",
    fontSize: "14px",
    lineHeight: "1.5",
    border: "1px solid #bae6fd",
    boxShadow: "0 2px 8px rgba(14,165,233,0.15)",
    wordWrap: "break-word",
    overflowWrap: "break-word",
    hyphens: "auto",
    whiteSpace: "pre-wrap",
  },
  assistantBubble: {
    background: "linear-gradient(135deg, #2563eb 0%, #0ea5e9 100%)",
    color: "#f8fafc",
    padding: "12px 16px",
    borderRadius: "20px",
    fontSize: "14px",
    lineHeight: "1.5",
    boxShadow: "0 8px 18px rgba(30,58,138,0.25)",
    wordWrap: "break-word",
    overflowWrap: "break-word",
    hyphens: "auto",
    whiteSpace: "pre-wrap",
  },
  messageMeta: {
    fontSize: "11px",
    color: "#64748b",
    marginTop: "6px",
    display: "flex",
    flexDirection: "column",
    gap: "4px",
  },
  messageTimestamp: {
    fontSize: "10px",
    color: "#94a3b8",
    marginTop: "4px",
    letterSpacing: "0.03em",
  },
  messageMetaDetails: {
    display: "flex",
    flexWrap: "wrap",
    gap: "6px",
  },
  busyRow: {
    display: "flex",
    alignItems: "center",
    gap: "6px",
    color: "#f59e0b",
    fontWeight: "500",
  },
  metricChip: {
    display: "inline-flex",
    alignItems: "center",
    gap: "4px",
    padding: "2px 8px",
    borderRadius: "12px",
    backgroundColor: "#e2e8f0",
    color: "#475569",
    fontSize: "10px",
    fontWeight: "500",
    letterSpacing: "0.01em",
  },
  metricLabel: {
    fontWeight: "600",
    color: "#1e293b",
  },
  metricValue: {
    color: "#0f172a",
  },
  spokenText: {
    opacity: 1,
    fontWeight: 600,
  },
  typingContainer: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "6px",
    minWidth: "32px",
  },
  typingDot: {
    width: "6px",
    height: "6px",
    borderRadius: "50%",
    backgroundColor: "rgba(15, 23, 42, 0.6)",
    animation: "typingBounce 1.2s infinite",
  },
  listeningIndicator: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "flex-start",
    gap: "6px",
    marginTop: "6px",
  },
  listeningDot: {
    width: "6px",
    height: "6px",
    borderRadius: "50%",
    backgroundColor: "#38bdf8",
    animation: "typingBounce 1.2s infinite",
  },
  listeningStandalone: {
    display: "inline-flex",
    alignItems: "center",
    gap: "6px",
    padding: "4px 0",
    color: "#38bdf8",
  },
  speechLengthRow: {
    marginTop: "6px",
    display: "inline-flex",
    alignItems: "center",
    gap: "6px",
    fontSize: "11px",
    color: "#475569",
    fontWeight: 500,
  },
  speechLengthLabel: {
    fontWeight: 600,
    color: "#1e293b",
  },
  agentNameLabel: {
    fontSize: "10px",
    fontWeight: "400",
    color: "#64748b",
    opacity: 0.7,
    marginBottom: "2px",
    marginLeft: "8px",
    letterSpacing: "0.5px",
    textTransform: "none",
    fontStyle: "italic",
  },
  sessionDividerWrapper: {
    display: "flex",
    alignItems: "center",
    gap: "12px",
    color: "#64748b",
    fontSize: "10px",
    letterSpacing: "0.08em",
    textTransform: "uppercase",
  },
  sessionDividerLine: {
    flex: 1,
    height: "1px",
    backgroundColor: "#e2e8f0",
  },
  sessionDividerContent: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: "4px",
    minWidth: "0",
  },
  sessionDividerSummary: {
    color: "#94a3b8",
    fontSize: "10px",
    letterSpacing: "0.04em",
    textTransform: "none",
  },
};

const ChatBubble = ({ message }) => {
  const {
    id,
    speaker,
    text = "",
    isTool,
    streaming,
    metrics = {},
    kind,
    summary = {},
    timestamp,
    incomplete,
  } = message;

  if (kind === "divider") {
    const dividerTime = new Date(timestamp ?? Date.now());
    const summaryParts = [];
    if (typeof summary.userTurns === "number") {
      summaryParts.push(`${summary.userTurns} user turn${summary.userTurns === 1 ? "" : "s"}`);
    }
    if (typeof summary.assistantTurns === "number") {
      summaryParts.push(`${summary.assistantTurns} assistant turn${summary.assistantTurns === 1 ? "" : "s"}`);
    }
    if (typeof summary.durationMs === "number") {
      const durationLabel = formatDuration(summary.durationMs);
      if (durationLabel) {
        summaryParts.push(`Duration ${durationLabel}`);
      }
    }

    const dividerLabel = `Session stopped · ${dividerTime.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    })}`;

    return (
      <div style={styles.sessionDividerWrapper}>
        <div style={styles.sessionDividerLine} />
        <div style={styles.sessionDividerContent}>
          <div>{dividerLabel}</div>
          {summaryParts.length > 0 ? (
            <div style={styles.sessionDividerSummary}>{summaryParts.join(" • ")}</div>
          ) : null}
        </div>
        <div style={styles.sessionDividerLine} />
      </div>
    );
  }

  const isUser = speaker === "User";
  const isSpecialist = speaker?.includes("Specialist");
  const isAuthAgent = speaker === "Auth Agent";
  const isPartial = Boolean(incomplete);
  const awaitingResponse = metrics.awaitingResponse;
  const playbackProgressRaw = metrics.playbackProgress;
  const latencyText = formatDuration(metrics.responseLatencyMs);
  const speechDurationText = formatDuration(metrics.speechDurationMs);
  const bargeInText = formatDuration(metrics.bargeInMs);
  const speechInterrupted = Boolean(metrics.speechInterrupted);
  const playbackProgress =
    playbackProgressRaw &&
    (!playbackProgressRaw.messageId || playbackProgressRaw.messageId === id)
      ? playbackProgressRaw
      : null;
  const shouldMaskUserText = isUser && awaitingResponse && (streaming || incomplete || !text);
  const trimmedAssistantText = !isUser && typeof text === "string" ? text.trim() : "";
  const hasAssistantText = !isUser && trimmedAssistantText.length > 0;
  const showListeningWithoutBubble = !isUser && isPartial && !shouldMaskUserText && !hasAssistantText;
  const timestampLabel = (() => {
    if (!timestamp) return null;
    const parsed = new Date(timestamp);
    if (Number.isNaN(parsed.getTime())) {
      return null;
    }
    return parsed.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  })();

  const assistantMetrics = [];
  if (!isPartial && typeof playbackProgress?.ratio === "number") {
    assistantMetrics.push({
      label: "Playback",
      value: `${Math.round(Math.min(playbackProgress.ratio, 1) * 100)}%`,
    });
  }
  if (isPartial) {
    assistantMetrics.unshift({ label: "Partial response" });
  }
  if (latencyText) assistantMetrics.push({ label: "Response latency", value: latencyText });
  if (bargeInText) assistantMetrics.push({ label: "Barge stop", value: bargeInText });
  if (speechInterrupted) assistantMetrics.push({ label: "Speech interrupted" });

  const userMetrics = [];
  if (bargeInText) {
    userMetrics.push({ label: "Barge-in duration", value: bargeInText });
  }

  const metricItems = isUser ? userMetrics : assistantMetrics;
  const showMetrics = metricItems.length > 0 && !showListeningWithoutBubble;
  const showSpeechDuration = !isUser && !isPartial && Boolean(speechDurationText);
  const agentLabel = !isUser
    ? message.agentName && message.agentName !== speaker
      ? message.agentName
      : (isSpecialist || isAuthAgent)
        ? speaker
        : null
    : null;

  if (isTool) {
    return (
      <div style={{ ...styles.assistantMessage, alignSelf: "center" }}>
        {agentLabel ? <div style={styles.agentNameLabel}>{agentLabel}</div> : null}
        <div
          style={{
            ...styles.assistantBubble,
            background: "#8b5cf6",
            textAlign: "center",
            fontSize: "14px",
          }}
        >
          {text}
        </div>
      </div>
    );
  }

  return (
    <div style={isUser ? styles.userMessage : styles.assistantMessage}>
      {!isUser && agentLabel ? <div style={styles.agentNameLabel}>{agentLabel}</div> : null}
      {showListeningWithoutBubble ? (
        <div style={styles.listeningStandalone} aria-label="Assistant listening">
          {[0, 1, 2].map((_, idx) => (
            <span
              key={idx}
              style={{
                ...styles.listeningDot,
                animationDelay: `${idx * 0.2}s`,
              }}
            />
          ))}
        </div>
      ) : (
        <div
          style={isUser ? styles.userBubble : styles.assistantBubble}
        >
          {shouldMaskUserText ? (
            <div style={styles.typingContainer} aria-label="Processing">
              {[0, 1, 2].map((_, idx) => (
                <span
                  key={idx}
                  style={{
                    ...styles.typingDot,
                    animationDelay: `${idx * 0.2}s`,
                  }}
                />
              ))}
            </div>
          ) : (
            <>
              {(() => {
                if (!text) {
                  return !isUser ? (
                    <span style={{ opacity: 0.75, fontStyle: "italic" }}>Audio response</span>
                  ) : null;
                }
                const ratio =
                  typeof playbackProgress?.ratio === "number" && !isPartial
                    ? Math.min(Math.max(playbackProgress.ratio, 0), 1)
                    : null;
                if (ratio === null || streaming) {
                  return text.split("\n").map((line, i) => <div key={i}>{line}</div>);
                }

                const totalChars = text.length;
                const spokenChars = Math.min(totalChars, Math.floor(totalChars * ratio));
                const spokenText = text.slice(0, spokenChars);
                const remainingText = text.slice(spokenChars);

                return (
                  <span style={{ whiteSpace: "pre-wrap" }}>
                    <span style={styles.spokenText}>{spokenText}</span>
                    <span>{remainingText}</span>
                  </span>
                );
              })()}
              {streaming && <span style={{ opacity: 0.7 }}>▌</span>}
            </>
          )}
          {isPartial && hasAssistantText && (
            <div style={styles.listeningIndicator} aria-label="Assistant listening">
              {[0, 1, 2].map((_, idx) => (
                <span
                  key={idx}
                  style={{
                    ...styles.listeningDot,
                    animationDelay: `${idx * 0.2}s`,
                  }}
                />
              ))}
            </div>
          )}
        </div>
      )}
      {showSpeechDuration && (
        <div style={styles.speechLengthRow}>
          <span style={styles.speechLengthLabel}>Speech length:</span>
          <span>{speechDurationText}</span>
        </div>
      )}
      {timestampLabel && (
        <div
          style={{
            ...styles.messageTimestamp,
            textAlign: isUser ? "right" : "left",
            alignSelf: isUser ? "flex-end" : "flex-start",
          }}
        >
          {timestampLabel}
        </div>
      )}
      {(awaitingResponse || showMetrics) && (
        <div
          style={{
            ...styles.messageMeta,
            alignItems: isUser ? "flex-end" : "flex-start",
            textAlign: isUser ? "right" : "left",
          }}
        >
          {awaitingResponse && (
            <div style={styles.busyRow}>
              <span role="img" aria-label="busy">
                ⏳
              </span>
              Awaiting assistant response...
            </div>
          )}
          {showMetrics && (
            <div style={styles.messageMetaDetails}>
              {metricItems.map(({ label, value }, idx) => (
                <span key={idx} style={styles.metricChip}>
                  <span style={styles.metricLabel}>{label}</span>
                  {value ? <span style={styles.metricValue}>{value}</span> : null}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default ChatBubble;
