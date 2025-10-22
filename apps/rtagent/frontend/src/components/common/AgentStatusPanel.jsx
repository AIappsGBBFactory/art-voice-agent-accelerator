import React from "react";
import { formatDuration } from "../../utils/format";

const styles = {
  panel: {
    display: "flex",
    flexDirection: "column",
    gap: "10px",
    padding: "12px 16px",
    borderRadius: "16px",
    background: "rgba(255, 255, 255, 0.92)",
    border: "1px solid rgba(148, 163, 184, 0.28)",
    boxShadow: "0 12px 24px rgba(148,163,184,0.18)",
    fontSize: "12px",
    color: "#1f2937",
    minWidth: "220px",
    backdropFilter: "blur(14px)",
  },
  item: {
    display: "flex",
    flexDirection: "column",
    gap: "4px",
  },
  label: {
    fontSize: "10px",
    textTransform: "uppercase",
    letterSpacing: "0.14em",
    color: "rgba(100, 116, 139, 0.8)",
  },
  value: {
    fontSize: "14px",
    fontWeight: 600,
    color: "#0f172a",
  },
  toolStatusText: {
    fontSize: "10px",
    color: "rgba(71, 85, 105, 0.82)",
  },
  toolProgressContainer: {
    position: "relative",
    width: "160px",
    height: "5px",
    borderRadius: "999px",
    backgroundColor: "rgba(203,213,225,0.35)",
    overflow: "hidden",
  },
  toolProgressBar: {
    position: "absolute",
    top: 0,
    left: 0,
    bottom: 0,
    borderRadius: "999px",
    background: "linear-gradient(135deg, #38bdf8, #0ea5e9)",
    transition: "width 150ms ease-out",
  },
  toolStatusChip: {
    alignSelf: "flex-start",
    padding: "3px 9px",
    borderRadius: "999px",
    backgroundColor: "rgba(59, 130, 246, 0.18)",
    color: "#2563eb",
    fontSize: "10px",
    letterSpacing: "0.08em",
    textTransform: "uppercase",
  },
};

const AgentStatusPanel = ({ agentName, toolActivity }) => {
  if (!agentName && !toolActivity) {
    return null;
  }

  const toolProgress = toolActivity?.progress ?? null;
  const boundedProgress =
    typeof toolProgress === "number"
      ? Math.min(Math.max(toolProgress, 0), 100)
      : null;

  const toolStatusText = toolActivity
    ? `${
        toolActivity.status === "success"
          ? "Completed"
          : toolActivity.status === "failed"
            ? "Failed"
            : "Running"
      }${
        toolActivity.elapsedMs != null
          ? ` · ${formatDuration(toolActivity.elapsedMs)}`
          : ""
      }`
    : null;

  const statusChipLabel = toolActivity
    ? toolActivity.status === "running"
      ? "In progress"
      : toolActivity.status === "failed"
        ? "Failed"
        : "Completed"
    : null;

  return (
    <div style={styles.panel}>
      {agentName ? (
        <div style={styles.item}>
          <span style={styles.label}>Active Agent</span>
          <span style={styles.value}>{agentName}</span>
        </div>
      ) : null}

      {toolActivity ? (
        <div style={{ ...styles.item, gap: "6px" }}>
          <span style={styles.label}>Tool Call</span>
          <span style={styles.value}>{toolActivity.tool}</span>
          <div style={styles.toolStatusText}>{toolStatusText}</div>
          {toolActivity.status === "running" && boundedProgress != null ? (
            <div style={styles.toolProgressContainer}>
              <div
                style={{
                  ...styles.toolProgressBar,
                  width: `${boundedProgress}%`,
                  background:
                    toolActivity.status === "failed"
                      ? "linear-gradient(135deg, #f97316, #ef4444)"
                      : styles.toolProgressBar.background,
                }}
              />
            </div>
          ) : null}
          {statusChipLabel ? (
            <span style={styles.toolStatusChip}>{statusChipLabel}</span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
};

export default AgentStatusPanel;
