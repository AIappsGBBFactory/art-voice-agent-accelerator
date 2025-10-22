import React from "react";
import { formatDuration } from "../../utils/format";

const clampProgress = (value) => {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return null;
  }
  if (value < 0) return 0;
  if (value > 100) return 100;
  return Math.round(value);
};

const deriveDetailFromText = (toolName, text) => {
  if (!text) {
    return null;
  }
  let result = text.trim();
  if (!result) {
    return null;
  }
  result = result.replace(/^🛠️\s*/, "");
  if (toolName) {
    const escaped = toolName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const regex = new RegExp(`^${escaped}[\\s·:-]*`, "i");
    result = result.replace(regex, "").trim();
  }
  return result || null;
};

const baseStyles = {
  card: {
    width: "100%",
    maxWidth: "420px",
    background: "linear-gradient(135deg, rgba(14,165,233,0.12) 0%, rgba(30,64,175,0.18) 100%)",
    border: "1px solid rgba(59,130,246,0.35)",
    borderRadius: "16px",
    padding: "14px 18px",
    display: "flex",
    flexDirection: "column",
    gap: "10px",
    boxShadow: "0 12px 22px rgba(15,23,42,0.15)",
    color: "#0f172a",
    backgroundColor: "rgba(236,253,245,0.6)",
  },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    gap: "12px",
  },
  title: {
    display: "flex",
    alignItems: "center",
    gap: "10px",
  },
  icon: {
    width: "36px",
    height: "36px",
    borderRadius: "12px",
    background: "linear-gradient(135deg, #0ea5e9 0%, #2563eb 100%)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    color: "#f8fafc",
    fontSize: "18px",
    boxShadow: "0 6px 14px rgba(37,99,235,0.35)",
  },
  toolName: {
    fontSize: "15px",
    fontWeight: 600,
    color: "#0f172a",
    textTransform: "capitalize",
  },
  agentName: {
    fontSize: "12px",
    color: "#475569",
    marginTop: "2px",
  },
  statusBadge: (status) => {
    const palettes = {
      success: { bg: "rgba(34,197,94,0.15)", fg: "#15803d", border: "rgba(34,197,94,0.35)" },
      failed: { bg: "rgba(248,113,113,0.18)", fg: "#b91c1c", border: "rgba(248,113,113,0.35)" },
      running: { bg: "rgba(59,130,246,0.18)", fg: "#1d4ed8", border: "rgba(59,130,246,0.35)" },
    };
    const palette = palettes[status] || palettes.running;
    return {
      backgroundColor: palette.bg,
      color: palette.fg,
      border: `1px solid ${palette.border}`,
      borderRadius: "999px",
      fontSize: "11px",
      fontWeight: 600,
      padding: "6px 12px",
      textTransform: "uppercase",
      letterSpacing: "0.6px",
    };
  },
  progressWrapper: {
    display: "flex",
    flexDirection: "column",
    gap: "6px",
  },
  progressBarTrack: {
    width: "100%",
    height: "6px",
    borderRadius: "999px",
    backgroundColor: "rgba(148,163,184,0.25)",
    overflow: "hidden",
  },
  progressBarFill: (pct) => ({
    width: `${pct}%`,
    height: "100%",
    borderRadius: "999px",
    background: "linear-gradient(135deg, #38bdf8 0%, #2563eb 100%)",
    boxShadow: "0 0 12px rgba(59,130,246,0.5)",
    transition: "width 180ms ease-out",
  }),
  progressLabel: {
    fontSize: "12px",
    color: "#475569",
    fontWeight: 500,
  },
  metaRow: {
    display: "flex",
    flexWrap: "wrap",
    gap: "12px",
    fontSize: "12px",
    color: "#475569",
    alignItems: "center",
  },
  detailText: {
    fontSize: "13px",
    lineHeight: 1.6,
    color: "#0f172a",
  },
  errorBox: {
    borderRadius: "12px",
    padding: "10px 12px",
    backgroundColor: "rgba(248,113,113,0.15)",
    border: "1px solid rgba(248,113,113,0.3)",
    color: "#b91c1c",
    fontSize: "12px",
    display: "flex",
    gap: "8px",
    alignItems: "flex-start",
  },
};

const ToolActivityCard = ({ toolName = "tool", state = {}, agentName, fallbackText }) => {
  const {
    status: statusRaw,
    statusLabel,
    progress,
    startedAt,
    updatedAt,
    completedAt,
    elapsedMs,
    resultPreview,
    detailText,
    error,
  } = state;

  const normalizedStatus = (() => {
    if (statusRaw === "success") return "success";
    if (statusRaw === "failed" || statusRaw === "failure") return "failed";
    return "running";
  })();

  const badgeLabel = statusLabel || (
    normalizedStatus === "success" ? "Completed" : normalizedStatus === "failed" ? "Failed" : "In Progress"
  );

  const clampedProgress = clampProgress(progress);
  const showProgress = normalizedStatus === "running" && clampedProgress != null;

  const durationValue = (() => {
    if (typeof elapsedMs === "number") {
      return elapsedMs;
    }
    if (typeof startedAt === "number" && typeof (completedAt ?? updatedAt) === "number") {
      const endTs = completedAt ?? updatedAt;
      return Math.max(endTs - startedAt, 0);
    }
    return null;
  })();
  const durationLabel = durationValue != null ? formatDuration(durationValue) : null;

  const detailFromText = deriveDetailFromText(toolName, fallbackText);
  const effectiveDetail = detailText || detailFromText || (resultPreview ? `Result: ${resultPreview}` : null);

  return (
    <div style={baseStyles.card}>
      <div style={baseStyles.header}>
        <div style={baseStyles.title}>
          <div style={baseStyles.icon}>🛠️</div>
          <div>
            <div style={baseStyles.toolName}>{toolName}</div>
            {agentName ? <div style={baseStyles.agentName}>by {agentName}</div> : null}
          </div>
        </div>
        <span style={baseStyles.statusBadge(normalizedStatus)}>{badgeLabel}</span>
      </div>

      {showProgress ? (
        <div style={baseStyles.progressWrapper}>
          <div style={baseStyles.progressBarTrack}>
            <div style={baseStyles.progressBarFill(clampedProgress)} />
          </div>
          <div style={baseStyles.progressLabel}>{clampedProgress}% complete</div>
        </div>
      ) : null}

      {(durationLabel || resultPreview) ? (
        <div style={baseStyles.metaRow}>
          {durationLabel ? <div>Duration: {durationLabel}</div> : null}
          {resultPreview ? <div>Result: {resultPreview}</div> : null}
        </div>
      ) : null}

      {effectiveDetail ? <div style={baseStyles.detailText}>{effectiveDetail}</div> : null}

      {error ? (
        <div style={baseStyles.errorBox}>
          <span>⚠️</span>
          <span>{error}</span>
        </div>
      ) : null}
    </div>
  );
};

export default ToolActivityCard;
