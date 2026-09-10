import React from 'react';
import { Box, Card, CardContent, CardHeader, Chip, Divider, LinearProgress, Typography } from '@mui/material';
import BuildCircleRoundedIcon from '@mui/icons-material/BuildCircleRounded';
import CheckCircleRoundedIcon from '@mui/icons-material/CheckCircleRounded';
import ErrorOutlineRoundedIcon from '@mui/icons-material/ErrorOutlineRounded';
import HourglassTopRoundedIcon from '@mui/icons-material/HourglassTopRounded';
import { formatEventTypeLabel, formatStatusTimestamp, describeEventData, inferStatusTone, STATUS_TONE_META } from '../utils/formatters.js';
import { styles } from '../styles/voiceAppStyles.js';
import logger from '../utils/logger.js';
import { normalizeTranscriptText } from '../utils/turnMessages.js';

// Renders a single tool call inside the per-turn grouped tool card.
const ToolCallRow = ({ call }) => {
  const status = call?.status || "started";
  const toolLabel = (call?.toolName || "tool").replace(/_/g, " ");
  const isSuccess = status === "success";
  const isFailure = status === "error";
  const isProgress = status === "in_progress";
  const pct = Number(call?.pct);
  const statusLabel = isSuccess
    ? "Completed"
    : isFailure
    ? "Failed"
    : isProgress
    ? "In Progress"
    : "Started";
  const chipColor = isSuccess ? "success" : isFailure ? "error" : "info";
  const chipIcon = isSuccess
    ? <CheckCircleRoundedIcon fontSize="small" />
    : isFailure
    ? <ErrorOutlineRoundedIcon fontSize="small" />
    : <HourglassTopRoundedIcon fontSize="small" />;

  let detailText = null;
  if (isFailure && call?.error != null) {
    detailText =
      typeof call.error === "string" ? call.error : JSON.stringify(call.error, null, 2);
  } else if (call?.result !== undefined && call?.result !== null) {
    detailText =
      typeof call.result === "string" ? call.result : JSON.stringify(call.result, null, 2);
  }

  let parsedJson = null;
  if (detailText) {
    try {
      parsedJson = JSON.parse(detailText);
    } catch (err) {
      logger.debug?.("Failed to parse tool payload", { err, detailText });
    }
  }

  return (
    <Box sx={{ borderRadius: 2, backgroundColor: "rgba(15,23,42,0.18)", p: 1.25 }}>
      <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 1 }}>
        <Box sx={{ display: "flex", alignItems: "center", gap: 0.75, minWidth: 0 }}>
          <BuildCircleRoundedIcon sx={{ color: "#e0e7ff", fontSize: 18 }} />
          <Typography
            variant="body2"
            sx={{ fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}
          >
            {toolLabel}
          </Typography>
        </Box>
        <Chip
          label={statusLabel}
          color={chipColor}
          variant="outlined"
          size="small"
          icon={chipIcon}
          sx={{
            color: chipColor === "success" ? "#064e3b" : chipColor === "error" ? "#7f1d1d" : "#0f172a",
            borderColor: "rgba(248,250,252,0.4)",
            backgroundColor: "rgba(248,250,252,0.15)",
            '& .MuiChip-icon': {
              color: chipColor === "success" ? "#047857" : chipColor === "error" ? "#dc2626" : "#1e293b",
            },
          }}
        />
      </Box>
      {isProgress && Number.isFinite(pct) && (
        <Box sx={{ mt: 1 }}>
          <LinearProgress
            variant="determinate"
            value={Math.max(0, Math.min(100, pct))}
            sx={{
              height: 6,
              borderRadius: 999,
              backgroundColor: "rgba(15,23,42,0.25)",
              '& .MuiLinearProgress-bar': { backgroundColor: "#f8fafc" },
            }}
          />
        </Box>
      )}
      {detailText && (
        <Box
          component="pre"
          sx={{
            m: 0,
            mt: 1,
            backgroundColor: "rgba(15,23,42,0.35)",
            borderRadius: 2,
            p: 1.5,
            fontFamily:
              'Roboto Mono, ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
            fontSize: "0.72rem",
            maxHeight: 220,
            overflow: "auto",
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}
        >
          {parsedJson ? JSON.stringify(parsedJson, null, 2) : detailText}
        </Box>
      )}
    </Box>
  );
};

const ChatBubble = ({ message }) => {
  if (message?.type === "divider") {
    return (
      <Box sx={{ width: "100%", display: "flex", justifyContent: "center", px: 1, py: 1 }}>
        <Divider textAlign="center" sx={{ width: "100%", maxWidth: 560 }}>
          <Typography
            variant="caption"
            sx={{
              color: "#94a3b8",
              fontFamily: 'Roboto Mono, ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
              letterSpacing: "0.12em",
              textTransform: "uppercase",
            }}
          >
            {message.label || formatStatusTimestamp(message.timestamp) || "—"}
          </Typography>
        </Divider>
      </Box>
    );
  }

  if (message?.type === "event") {
    const eventType = message.eventType || message.event_type;
    const eventLabel = formatEventTypeLabel(eventType);
    const timestampLabel = formatStatusTimestamp(message.timestamp);
    const baseDetail = message.summary ?? describeEventData(message.data);
    const isSessionUpdate = eventType === "session_updated";
    const inferredAgentLabel =
      message.data?.active_agent_label ??
      message.data?.agent_label ??
      message.data?.agentLabel ??
      message.data?.agent_name ??
      null;
    const detailText = isSessionUpdate
      ? message.summary ?? message.data?.message ?? (inferredAgentLabel ? `Active agent: ${inferredAgentLabel}` : baseDetail)
      : baseDetail;
    const severity = inferStatusTone(detailText || eventLabel);
    const palette = {
      success: "#16a34a",
      warning: "#f59e0b",
      error: "#ef4444",
      info: "#2563eb",
    }[severity || "info"];

    return (
      <div style={{ width: "100%", display: "flex", justifyContent: "center", padding: "2px 12px" }}>
        <span style={{ fontSize: "11px", color: "#94a3b8", marginRight: "6px" }}>•</span>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", alignItems: "center", justifyContent: "center", textAlign: "center", color: "#0f172a", fontSize: "12px" }}>
          <span style={{ fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", color: palette }}>
            {eventLabel}
          </span>
          {timestampLabel && (
            <span style={{ color: "#94a3b8", fontFamily: 'Roboto Mono, ui-monospace, Menlo, Consolas, "Courier New", monospace', letterSpacing: "0.02em" }}>
              {timestampLabel}
            </span>
          )}
          {detailText && (
            <span style={{ color: "#334155", whiteSpace: "pre-wrap" }}>
              {detailText}
            </span>
          )}
        </div>
      </div>
    );
  }

  const {
    speaker,
    text = "",
    isTool,
    streaming,
    cancelled,
    cancelReason,
    status,
    error,
  } = message;
  const isUser = speaker === "User";
  const isSystem = speaker === "System" && !isTool;
  const effectiveText = typeof text === "string" ? text : "";
  const cancellationLabel = cancelReason
    ? cancelReason.replace(/[_-]+/g, " ")
    : "Assistant interrupted";

  // The full error card belongs to the dedicated error bubble that the backend
  // emits for a failure. A failed *turn* also carries `status`/`error` metadata,
  // but it still has the line the agent spoke, so rendering the card here too
  // would show the same failure twice and hide what the caller actually heard.
  // A failed turn with nothing to show still falls back to the card so the
  // failure is never silent.
  const isErrorBubble = message.kind === "error";
  if (isErrorBubble || ((status === "error" || error) && !effectiveText.trim())) {
    let errorData = {};
    try {
      // Try to parse error as JSON if it's a string
      errorData = typeof error === "string" ? JSON.parse(error) : error || {};
    } catch {
      // Fallback to simple error message
      errorData = {
        code: "Error",
        message: typeof error === "string" ? error : "An error occurred",
        details: ""
      };
    }

    const {
      code = "Error",
      message: errorMessage = "An error occurred",
      details = "",
      remediation = "",
    } = errorData;

    return (
      <Box sx={{ width: "100%", display: "flex", justifyContent: "center", px: 1, py: 1 }}>
        <Card
          elevation={6}
          sx={{
            width: "100%",
            maxWidth: 600,
            borderRadius: 3,
            background: "linear-gradient(135deg, #fca5a5, #ef4444)",
            color: "#fff",
            border: "1px solid rgba(255,255,255,0.16)",
            boxShadow: "0 18px 40px rgba(239,68,68,0.28)",
          }}
        >
          <CardHeader
            avatar={<ErrorOutlineRoundedIcon sx={{ color: "#fee2e2", fontSize: 28 }} />}
            title={
              <Typography variant="subtitle1" sx={{ fontWeight: 600, letterSpacing: 0.4 }}>
                {code}
              </Typography>
            }
            subheader="Error occurred during processing"
            subheaderTypographyProps={{
              sx: {
                color: "rgba(254,226,226,0.85)",
                textTransform: "uppercase",
                fontSize: "0.7rem",
                letterSpacing: "0.08em",
                fontWeight: 600,
              },
            }}
            action={
              <Chip
                label="Failed"
                color="error"
                variant="outlined"
                size="small"
                icon={<ErrorOutlineRoundedIcon fontSize="small" />}
                sx={{
                  color: "#7f1d1d",
                  borderColor: "rgba(248,250,252,0.4)",
                  backgroundColor: "rgba(248,250,252,0.15)",
                  '& .MuiChip-icon': {
                    color: "#dc2626",
                  },
                }}
              />
            }
            sx={{
              '& .MuiCardHeader-action': { alignSelf: "center" },
              pb: 0,
            }}
          />
          <Divider sx={{ borderColor: "rgba(248,250,252,0.2)" }} />
          <CardContent sx={{ pt: 2, pb: 2, color: "rgba(248,250,252,0.95)" }}>
            <Typography
              variant="body1"
              sx={{ fontWeight: 500, mb: details || remediation ? 1.5 : 0 }}
            >
              {errorMessage}
            </Typography>
            {remediation && (
              <Box
                sx={{
                  mt: 1,
                  mb: details ? 1.5 : 0,
                  p: 1.25,
                  borderRadius: 2,
                  backgroundColor: "rgba(248,250,252,0.16)",
                }}
              >
                <Typography
                  variant="caption"
                  sx={{
                    display: "block",
                    textTransform: "uppercase",
                    letterSpacing: "0.08em",
                    fontWeight: 700,
                    color: "rgba(254,226,226,0.9)",
                    mb: 0.5,
                  }}
                >
                  How to fix
                </Typography>
                <Typography variant="body2" sx={{ color: "rgba(248,250,252,0.95)" }}>
                  {remediation}
                </Typography>
              </Box>
            )}
            {details && (
              <Typography
                variant="body2"
                sx={{
                  color: "rgba(248,250,252,0.75)",
                  fontSize: "0.85rem",
                  fontStyle: "italic",
                  mt: 1,
                  pl: 1.5,
                  borderLeft: "2px solid rgba(248,250,252,0.3)"
                }}
              >
                {details}
              </Typography>
            )}
          </CardContent>
        </Card>
      </Box>
    );
  }

  if (message?.isToolGroup || Array.isArray(message?.toolCalls)) {
    const toolCalls = Array.isArray(message.toolCalls) ? message.toolCalls : [];
    const responded = toolCalls.filter(
      (call) => call?.status === "success" || call?.status === "error",
    );

    // Only surface the tool blob once at least one call has returned a response.
    // Until then the group stays invisible so "started"/progress cards don't flash.
    if (responded.length === 0) {
      return null;
    }

    const anyFailure = toolCalls.some((call) => call?.status === "error");
    const allSuccess = toolCalls.every((call) => call?.status === "success");
    const cardGradient = anyFailure
      ? "linear-gradient(135deg, #f87171, #ef4444)"
      : allSuccess
      ? "linear-gradient(135deg, #34d399, #10b981)"
      : "linear-gradient(135deg, #8b5cf6, #6366f1)";
    const subheaderText =
      toolCalls.length > 1 ? `${toolCalls.length} tool calls` : "Tool call";

    return (
      <Box sx={{ width: "100%", display: "flex", justifyContent: "center", px: 1, py: 1 }}>
        <Card
          elevation={6}
          sx={{
            width: "100%",
            maxWidth: 600,
            borderRadius: 3,
            background: cardGradient,
            color: "#f8fafc",
            border: "1px solid rgba(255,255,255,0.16)",
            boxShadow: "0 18px 40px rgba(99,102,241,0.28)",
          }}
        >
          <CardHeader
            avatar={<BuildCircleRoundedIcon sx={{ color: "#e0e7ff" }} />}
            title={
              <Typography variant="subtitle1" sx={{ fontWeight: 600, letterSpacing: 0.4 }}>
                Tool Activity
              </Typography>
            }
            subheader={subheaderText}
            subheaderTypographyProps={{
              sx: {
                color: "rgba(248,250,252,0.78)",
                textTransform: "uppercase",
                fontSize: "0.7rem",
                letterSpacing: "0.08em",
                fontWeight: 600,
              },
            }}
            sx={{ pb: 0 }}
          />
          <Divider sx={{ borderColor: "rgba(248,250,252,0.2)" }} />
          <CardContent
            sx={{
              pt: 1.5,
              pb: 1.5,
              color: "rgba(248,250,252,0.92)",
              display: "flex",
              flexDirection: "column",
              gap: 1.5,
            }}
          >
            {toolCalls.map((call) => (
              <ToolCallRow key={call.callKey || call.callId || call.toolName} call={call} />
            ))}
          </CardContent>
        </Card>
      </Box>
    );
  }

  if (isTool) {
    const safeText = text ?? "";
    const [headline = "", ...detailLines] = safeText.split("\n");
    const detailText = detailLines.join("\n").trim();
    const toolMatch = headline.match(/tool\s+([\w-]+)/i);
    const toolName = toolMatch?.[1]?.replace(/_/g, " ") ?? "Tool";
    const progressMatch = headline.match(/(\d+)%/);
    const progressValue = progressMatch ? Number(progressMatch[1]) : null;
    const isSuccess = /completed/i.test(headline);
    const isFailure = /failed/i.test(headline);
    const isStart = /started/i.test(headline);
    const statusLabel = isSuccess
      ? "Completed"
      : isFailure
      ? "Failed"
      : progressValue !== null
      ? "In Progress"
      : isStart
      ? "Started"
      : "Update";
    const chipColor = isSuccess ? "success" : isFailure ? "error" : "info";
    const chipIcon = isSuccess
      ? <CheckCircleRoundedIcon fontSize="small" />
      : isFailure
      ? <ErrorOutlineRoundedIcon fontSize="small" />
      : <HourglassTopRoundedIcon fontSize="small" />;
    const subheaderText = headline
      .replace(/^🛠️\s*/u, "")
      .replace(/tool\s+[\w-]+\s*/i, "")
      .trim();

    let parsedJson = null;
    if (detailText) {
      try {
        parsedJson = JSON.parse(detailText);
      } catch (err) {
        logger.debug?.("Failed to parse tool payload", { err, detailText });
      }
    }

    const cardGradient = isFailure
      ? "linear-gradient(135deg, #f87171, #ef4444)"
      : isSuccess
      ? "linear-gradient(135deg, #34d399, #10b981)"
      : "linear-gradient(135deg, #8b5cf6, #6366f1)";
    const hasContent = Boolean(detailText) || (progressValue !== null && !Number.isNaN(progressValue));

    return (
      <Box sx={{ width: "100%", display: "flex", justifyContent: "center", px: 1, py: 1 }}>
        <Card
          elevation={6}
          sx={{
            width: "100%",
            maxWidth: 600,
            borderRadius: 3,
            background: cardGradient,
            color: "#f8fafc",
            border: "1px solid rgba(255,255,255,0.16)",
            boxShadow: "0 18px 40px rgba(99,102,241,0.28)",
          }}
        >
          <CardHeader
            avatar={<BuildCircleRoundedIcon sx={{ color: "#e0e7ff" }} />}
            title={
              <Typography variant="subtitle1" sx={{ fontWeight: 600, letterSpacing: 0.4 }}>
                {toolName}
              </Typography>
            }
            subheader={subheaderText || null}
            subheaderTypographyProps={{
              sx: {
                color: "rgba(248,250,252,0.78)",
                textTransform: "uppercase",
                fontSize: "0.7rem",
                letterSpacing: "0.08em",
                fontWeight: 600,
              },
            }}
            action={
              <Chip
                label={statusLabel}
                color={chipColor}
                variant="outlined"
                size="small"
                icon={chipIcon}
                sx={{
                  color: chipColor === "success" ? "#064e3b" : chipColor === "error" ? "#7f1d1d" : "#0f172a",
                  borderColor: "rgba(248,250,252,0.4)",
                  backgroundColor: "rgba(248,250,252,0.15)",
                  '& .MuiChip-icon': {
                    color: chipColor === "success" ? "#047857" : chipColor === "error" ? "#dc2626" : "#1e293b",
                  },
                }}
              />
            }
            sx={{
              '& .MuiCardHeader-action': { alignSelf: "center" },
              pb: hasContent ? 0 : 1,
            }}
          />
          {hasContent && <Divider sx={{ borderColor: "rgba(248,250,252,0.2)" }} />}
          {hasContent && (
            <CardContent sx={{ pt: 2, pb: 2, color: "rgba(248,250,252,0.92)" }}>
              {progressValue !== null && !isSuccess && !isFailure && (
                <Box sx={{ mb: detailText ? 2 : 0 }}>
                  <LinearProgress
                    variant="determinate"
                    value={Math.max(0, Math.min(100, progressValue))}
                    sx={{
                      height: 8,
                      borderRadius: 999,
                      backgroundColor: "rgba(15,23,42,0.25)",
                      '& .MuiLinearProgress-bar': { backgroundColor: "#f8fafc" },
                    }}
                  />
                </Box>
              )}
              {parsedJson ? (
                <Box
                  component="pre"
                  sx={{
                    m: 0,
                    backgroundColor: "rgba(15,23,42,0.35)",
                    borderRadius: 2,
                    p: 2,
                    fontFamily:
                      'Roboto Mono, ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
                    fontSize: "0.75rem",
                    maxHeight: 260,
                    overflowX: "auto",
                    overflowY: "auto",
                    whiteSpace: "pre-wrap",
                  }}
                >
                  {JSON.stringify(parsedJson, null, 2)}
                </Box>
              ) : (
                detailText && (
                  <Typography variant="body2" sx={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                    {detailText}
                  </Typography>
                )
              )}
            </CardContent>
          )}
        </Card>
      </Box>
    );
  }
  
  if (isSystem) {
    const toneKey = message.statusTone && STATUS_TONE_META[message.statusTone] ? message.statusTone : inferStatusTone(text);
    const tone = STATUS_TONE_META[toneKey] ?? STATUS_TONE_META.info;
    const toneLabel = message.statusLabel || tone.label;
    const timestampLabel = formatStatusTimestamp(message.timestamp);
    const lines = (text || "").split("\n").filter(Boolean);
    const Icon = tone.icon;

    return (
      <div style={{ width: "100%", display: "flex", justifyContent: "center", padding: "2px 12px" }}>
        <span style={{ fontSize: "11px", color: "#94a3b8", marginRight: "6px" }}>•</span>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", alignItems: "center", justifyContent: "center", textAlign: "center", fontSize: "12px", color: "#0f172a" }}>
          {Icon ? <Icon sx={{ fontSize: 16, color: tone.accent, mr: 0.5 }} /> : null}
          <span style={{ fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", color: tone.accent }}>
            {toneLabel}
          </span>
          {timestampLabel && (
            <span style={{ color: tone.captionColor, fontFamily: 'Roboto Mono, ui-monospace, Menlo, Consolas, "Courier New", monospace', letterSpacing: "0.02em" }}>
              {timestampLabel}
            </span>
          )}
          {lines.length > 0 && (
            <span style={{ color: tone.textColor, whiteSpace: "pre-wrap" }}>
              {lines.join(" ")}
            </span>
          )}
          {message.statusCaption && (
            <span style={{ color: tone.captionColor }}>
              {message.statusCaption}
            </span>
          )}
        </div>
      </div>
    );
  }
  
  const bubbleStyle = isUser ? styles.userBubble : styles.assistantBubble;
  // While a turn is still streaming (partial transcript / partial response),
  // render the text in italics with a subtle dim; on finalization it flips to
  // normal weight so the bubble visibly "settles" on the recognized final.
  const streamingTextStyle = streaming
    ? { fontStyle: "italic", opacity: 0.85 }
    : cancelled
    ? { fontStyle: "normal", opacity: 0.7 }
    : { fontStyle: "normal" };
  // Normalize whitespace so a partial transcript renders identically to the
  // final: collapse CRLF, drop blank runs, and trim edges. This keeps the
  // bubble stable (no phantom blank line) as partials stream into the final.
  const displayText = normalizeTranscriptText(effectiveText);

  return (
    <div style={isUser ? styles.userMessage : styles.assistantMessage}>
      {/* Show agent name for any non-default assistant */}
      {!isUser && speaker && speaker !== "Assistant" && (
        <div style={styles.agentNameLabel}>
          {speaker}
        </div>
      )}
      <div style={{ ...bubbleStyle, ...streamingTextStyle }}>
        {/* Inline text + cursor: keeping the cursor inline (not after block
            <div> lines) prevents a phantom newline while streaming. */}
        <span style={{ whiteSpace: "pre-wrap" }}>{displayText}</span>
        {streaming && (
          <span style={{ opacity: 0.7, fontStyle: "normal", marginLeft: "1px" }}>▌</span>
        )}
        {cancelled && (
          <span
            style={{
              display: "block",
              marginTop: "4px",
              fontSize: "0.72rem",
              fontStyle: "normal",
              opacity: 0.72,
            }}
          >
            {cancellationLabel}
          </span>
        )}
      </div>
    </div>
  );
};

export default ChatBubble;
