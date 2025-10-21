const styles = {
  root: {
    width: "768px",
    maxWidth: "768px",
    fontFamily: "Segoe UI, Roboto, sans-serif",
    background: "transparent",
    minHeight: "100vh",
    display: "flex",
    flexDirection: "column",
    color: "#1e293b",
    position: "relative",
    alignItems: "center",
    justifyContent: "center",
    padding: "8px",
    border: "0px solid #0e4bf3ff",
  },

  mainContainer: {
    width: "100%",
    maxWidth: "100%",
    height: "90vh",
    maxHeight: "900px",
    background: "white",
    borderRadius: "20px",
    boxShadow: "0 20px 60px rgba(0,0,0,0.15)",
    border: "0px solid #ce1010ff",
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
    position: "relative",
  },

  appHeader: {
    backgroundColor: "#f8fafc",
    background: "linear-gradient(180deg, #ffffff 0%, #f8fafc 100%)",
    padding: "16px 24px 12px 24px",
    borderBottom: "1px solid #e2e8f0",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "16px",
    flexWrap: "wrap",
    position: "relative",
  },

  appTitleContainer: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: "4px",
    margin: "0 auto",
    textAlign: "center",
  },

  appTitleWrapper: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
  },

  appTitleIcon: {
    fontSize: "20px",
    opacity: 0.7,
  },

  appTitle: {
    fontSize: "18px",
    fontWeight: "600",
    color: "#334155",
    textAlign: "left",
    margin: 0,
    letterSpacing: "0.1px",
  },

  appSubtitle: {
    fontSize: "12px",
    fontWeight: "400",
    color: "#64748b",
    textAlign: "center",
    margin: 0,
    letterSpacing: "0.1px",
    maxWidth: "350px",
    lineHeight: "1.3",
    opacity: 0.8,
  },
  appHeaderRight: {
    display: "flex",
    alignItems: "center",
    gap: "12px",
    position: "absolute",
    top: "16px",
    right: "24px",
  },
  statusOverlay: {
    position: "absolute",
    top: "64px",
    right: "24px",
    pointerEvents: "none",
    zIndex: 5,
  },
  statusOverlayInner: {
    pointerEvents: "auto",
  },
  waveformSection: {
    backgroundColor: "#f1f5f9",
    background: "linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%)",
    padding: "18px 12px 22px",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    borderBottom: "1px solid #e2e8f0",
    height: "28%",
    minHeight: "140px",
    position: "relative",
  },

  waveformSectionTitle: {
    fontSize: "12px",
    fontWeight: "500",
    color: "#64748b",
    textTransform: "uppercase",
    letterSpacing: "0.5px",
    marginBottom: "8px",
    opacity: 0.8,
  },

  sectionDivider: {
    position: "absolute",
    bottom: "-1px",
    left: "20%",
    right: "20%",
    height: "1px",
    backgroundColor: "#cbd5e1",
    borderRadius: "0.5px",
    opacity: 0.6,
  },

  waveformContainer: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    width: "100%",
    height: "72%",
    padding: "0 18px",
    background: "radial-gradient(ellipse at center, rgba(100, 116, 139, 0.08) 0%, transparent 75%)",
    borderRadius: "12px",
  },

  waveformSvg: {
    width: "100%",
    height: "60px",
    filter: "drop-shadow(0 1px 2px rgba(100, 116, 139, 0.1))",
    transition: "filter 0.3s ease",
  },

  chatSection: {
    flex: 1,
    padding: "15px 20px 15px 5px",
    width: "100%",
    overflowY: "auto",
    backgroundColor: "#ffffff",
    borderBottom: "1px solid #e2e8f0",
    display: "flex",
    flexDirection: "column",
    position: "relative",
  },

  chatSectionHeader: {
    textAlign: "center",
    marginBottom: "30px",
    paddingBottom: "20px",
    borderBottom: "1px solid #f1f5f9",
  },

  chatSectionTitle: {
    fontSize: "14px",
    fontWeight: "600",
    color: "#64748b",
    textTransform: "uppercase",
    letterSpacing: "0.5px",
    marginBottom: "5px",
  },

  chatSectionSubtitle: {
    fontSize: "12px",
    color: "#94a3b8",
    fontStyle: "italic",
  },

  chatSectionIndicator: {
    position: "absolute",
    left: "0",
    top: "0",
    bottom: "0",
    width: "0px",
    backgroundColor: "#3b82f6",
  },

  messageContainer: {
    display: "flex",
    flexDirection: "column",
    gap: "16px",
    flex: 1,
    overflowY: "auto",
    padding: "0 8px 0 0",
    scrollbarWidth: "thin",
    scrollbarColor: "#cbd5e1 transparent",
  },

  userMessage: {
    alignSelf: "flex-end",
    maxWidth: "75%",
    marginRight: "15px",
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

  assistantMessage: {
    alignSelf: "flex-start",
    maxWidth: "80%",
    marginLeft: "0px",
    marginBottom: "4px",
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
  agentStatusPanel: {
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
  agentStatusItem: {
    display: "flex",
    flexDirection: "column",
    gap: "4px",
  },
  agentStatusLabel: {
    fontSize: "10px",
    textTransform: "uppercase",
    letterSpacing: "0.14em",
    color: "rgba(100, 116, 139, 0.8)",
  },
  agentStatusValue: {
    fontSize: "14px",
    fontWeight: 600,
    color: "#0f172a",
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
  toolStatusText: {
    fontSize: "10px",
    color: "rgba(71, 85, 105, 0.82)",
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

  controlSection: {
    padding: "12px",
    backgroundColor: "#f1f5f9",
    background: "linear-gradient(180deg, #f1f5f9 0%, #e2e8f0 100%)",
    display: "flex",
    justifyContent: "center",
    alignItems: "center",
    height: "15%",
    minHeight: "100px",
    borderTop: "1px solid #e2e8f0",
    position: "relative",
  },

  controlContainer: {
    display: "flex",
    gap: "8px",
    background: "white",
    padding: "12px 16px",
    borderRadius: "24px",
    boxShadow: "0 4px 16px rgba(100, 116, 139, 0.08), 0 1px 4px rgba(100, 116, 139, 0.04)",
    border: "1px solid #e2e8f0",
    width: "fit-content",
  },

  controlButton: (isActive) => ({
    width: "56px",
    height: "56px",
    borderRadius: "50%",
    border: "none",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    cursor: "pointer",
    fontSize: "20px",
    transition: "all 0.3s ease",
    position: "relative",
    background: "linear-gradient(135deg, #f1f5f9, #e2e8f0)",
    color: isActive ? "#10b981" : "#64748b",
    transform: isActive ? "scale(1.05)" : "scale(1)",
    boxShadow: isActive
      ? "0 6px 20px rgba(16,185,129,0.3), 0 0 0 3px rgba(16,185,129,0.1)"
      : "0 2px 8px rgba(0,0,0,0.08)",
  }),

  resetButton: (isActive, isHovered) => ({
    width: "56px",
    height: "56px",
    borderRadius: "50%",
    border: "none",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    cursor: "pointer",
    fontSize: "20px",
    transition: "all 0.3s ease",
    position: "relative",
    background: "linear-gradient(135deg, #f1f5f9, #e2e8f0)",
    color: isActive ? "#10b981" : "#64748b",
    transform: isHovered ? "scale(1.08)" : isActive ? "scale(1.05)" : "scale(1)",
    boxShadow: isHovered
      ? "0 8px 24px rgba(100,116,139,0.3), 0 0 0 3px rgba(100,116,139,0.15)"
      : isActive
      ? "0 6px 20px rgba(16,185,129,0.3), 0 0 0 3px rgba(16,185,129,0.1)"
      : "0 2px 8px rgba(0,0,0,0.08)",
  }),

  micButton: (isActive, isHovered) => ({
    width: "56px",
    height: "56px",
    borderRadius: "50%",
    border: "none",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    cursor: "pointer",
    fontSize: "20px",
    transition: "all 0.3s ease",
    position: "relative",
    background: isHovered
      ? isActive
        ? "linear-gradient(135deg, #10b981, #059669)"
        : "linear-gradient(135deg, #dcfce7, #bbf7d0)"
      : "linear-gradient(135deg, #f1f5f9, #e2e8f0)",
    color: isHovered ? (isActive ? "white" : "#16a34a") : isActive ? "#10b981" : "#64748b",
    transform: isHovered ? "scale(1.08)" : isActive ? "scale(1.05)" : "scale(1)",
    boxShadow: isHovered
      ? "0 8px 25px rgba(16,185,129,0.4), 0 0 0 4px rgba(16,185,129,0.15), inset 0 1px 2px rgba(255,255,255,0.2)"
      : isActive
      ? "0 6px 20px rgba(16,185,129,0.3), 0 0 0 3px rgba(16,185,129,0.1)"
      : "0 2px 8px rgba(0,0,0,0.08)",
  }),

  phoneButton: (isActive, isHovered, isDisabled = false) => {
    const base = {
      width: "56px",
      height: "56px",
      borderRadius: "50%",
      border: "none",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      fontSize: "20px",
      transition: "all 0.3s ease",
      position: "relative",
    };

    if (isDisabled) {
      return {
        ...base,
        cursor: "not-allowed",
        background: "linear-gradient(135deg, #e2e8f0, #cbd5e1)",
        color: "#94a3b8",
        transform: "scale(1)",
        boxShadow: "inset 0 0 0 1px rgba(148, 163, 184, 0.3)",
        opacity: 0.7,
      };
    }

    return {
      ...base,
      cursor: "pointer",
      background: isHovered
        ? isActive
          ? "linear-gradient(135deg, #3f75a8ff, #2b5d8f)"
          : "linear-gradient(135deg, #dcfce7, #bbf7d0)"
        : "linear-gradient(135deg, #f1f5f9, #e2e8f0)",
      color: isHovered ? (isActive ? "white" : "#3f75a8ff") : isActive ? "#3f75a8ff" : "#64748b",
      transform: isHovered ? "scale(1.08)" : isActive ? "scale(1.05)" : "scale(1)",
      boxShadow: isHovered
        ? "0 8px 25px rgba(16,185,129,0.4), 0 0 0 4px rgba(16,185,129,0.15), inset 0 1px 2px rgba(255,255,255,0.2)"
        : isActive
        ? "0 6px 20px rgba(16,185,129,0.3), 0 0 0 3px rgba(16,185,129,0.1)"
        : "0 2px 8px rgba(0,0,0,0.08)",
    };
  },

  buttonTooltip: {
    position: "absolute",
    bottom: "-45px",
    left: "50%",
    transform: "translateX(-50%)",
    background: "rgba(51, 65, 85, 0.95)",
    color: "#f1f5f9",
    padding: "8px 12px",
    borderRadius: "8px",
    fontSize: "11px",
    fontWeight: "500",
    whiteSpace: "nowrap",
    backdropFilter: "blur(10px)",
    boxShadow: "0 4px 12px rgba(0,0,0,0.15)",
    border: "1px solid rgba(255,255,255,0.1)",
    pointerEvents: "none",
    opacity: 0,
    transition: "opacity 0.2s ease, transform 0.2s ease",
    zIndex: 1000,
  },

  buttonTooltipVisible: {
    opacity: 1,
    transform: "translateX(-50%) translateY(-2px)",
  },

  phoneInputSection: {
    position: "absolute",
    bottom: "60px",
    left: "500px",
    background: "white",
    padding: "20px",
    borderRadius: "20px",
    boxShadow: "0 8px 32px rgba(0,0,0,0.12)",
    border: "1px solid #e2e8f0",
    display: "flex",
    flexDirection: "column",
    gap: "12px",
    minWidth: "240px",
    zIndex: 90,
  },

  phoneInput: {
    padding: "12px 16px",
    border: "1px solid #d1d5db",
    borderRadius: "12px",
    fontSize: "14px",
    outline: "none",
    transition: "border-color 0.2s ease, box-shadow 0.2s ease",
  },

  backendIndicator: {
    position: "fixed",
    bottom: "20px",
    left: "20px",
    display: "flex",
    flexDirection: "column",
    gap: "8px",
    padding: "12px 16px",
    backgroundColor: "rgba(255, 255, 255, 0.98)",
    border: "1px solid #e2e8f0",
    borderRadius: "12px",
    fontSize: "11px",
    color: "#64748b",
    boxShadow: "0 8px 32px rgba(0,0,0,0.12)",
    zIndex: 1000,
    minWidth: "280px",
    maxWidth: "320px",
    backdropFilter: "blur(8px)",
  },

  backendHeader: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
    marginBottom: "4px",
    cursor: "pointer",
  },

  backendStatus: {
    width: "8px",
    height: "8px",
    borderRadius: "50%",
    backgroundColor: "#10b981",
    animation: "pulse 2s ease-in-out infinite",
    flexShrink: 0,
  },

  backendUrl: {
    fontFamily: "monospace",
    fontSize: "10px",
    color: "#475569",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },

  backendLabel: {
    fontWeight: "600",
    color: "#334155",
    fontSize: "12px",
    letterSpacing: "0.3px",
  },

  expandIcon: {
    marginLeft: "auto",
    fontSize: "12px",
    color: "#94a3b8",
    transition: "transform 0.2s ease",
  },

  componentGrid: {
    display: "grid",
    gridTemplateColumns: "1fr",
    gap: "6px",
    marginTop: "6px",
    paddingTop: "6px",
    borderTop: "1px solid #f1f5f9",
  },

  componentItem: {
    display: "flex",
    alignItems: "center",
    gap: "4px",
    padding: "5px 7px",
    backgroundColor: "#f8fafc",
    borderRadius: "5px",
    fontSize: "9px",
    border: "1px solid #e2e8f0",
    transition: "all 0.2s ease",
    minHeight: "22px",
  },

  componentDot: (status) => ({
    width: "4px",
    height: "4px",
    borderRadius: "50%",
    backgroundColor:
      status === "healthy"
        ? "#10b981"
        : status === "degraded"
        ? "#f59e0b"
        : status === "unhealthy"
        ? "#ef4444"
        : "#6b7280",
    flexShrink: 0,
  }),

  componentName: {
    fontWeight: "500",
    color: "#475569",
    textTransform: "capitalize",
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
    fontSize: "9px",
    letterSpacing: "0.01em",
  },

  responseTime: {
    fontSize: "8px",
    color: "#94a3b8",
    marginLeft: "auto",
  },

  errorMessage: {
    fontSize: "10px",
    color: "#ef4444",
    marginTop: "4px",
    fontStyle: "italic",
  },

  callMeButton: (isActive, isDisabled = false) => ({
    padding: "12px 24px",
    background: isDisabled
      ? "linear-gradient(135deg, #e2e8f0, #cbd5e1)"
      : isActive
      ? "#ef4444"
      : "#67d8ef",
    color: isDisabled ? "#94a3b8" : "white",
    border: "none",
    borderRadius: "8px",
    cursor: isDisabled ? "not-allowed" : "pointer",
    fontSize: "14px",
    fontWeight: "600",
    transition: "all 0.2s ease",
    boxShadow: isDisabled ? "inset 0 0 0 1px rgba(148, 163, 184, 0.3)" : "0 2px 8px rgba(0,0,0,0.1)",
    minWidth: "120px",
    opacity: isDisabled ? 0.7 : 1,
  }),

  acsHoverDialog: {
    position: "fixed",
    transform: "translateX(-50%)",
    marginTop: "0",
    backgroundColor: "rgba(255, 255, 255, 0.98)",
    border: "1px solid #fed7aa",
    borderRadius: "6px",
    padding: "8px 10px",
    fontSize: "9px",
    color: "#b45309",
    boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
    width: "260px",
    zIndex: 2000,
    lineHeight: "1.4",
    pointerEvents: "none",
  },

  phoneDisabledDialog: {
    position: "fixed",
    transform: "translateX(-50%)",
    backgroundColor: "rgba(255, 255, 255, 0.98)",
    border: "1px solid #fecaca",
    borderRadius: "8px",
    padding: "10px 14px",
    fontSize: "11px",
    color: "#b45309",
    boxShadow: "0 6px 16px rgba(0,0,0,0.15)",
    width: "280px",
    zIndex: 2000,
    lineHeight: "1.5",
    pointerEvents: "none",
  },

  helpButton: {
    position: "absolute",
    top: "16px",
    right: "16px",
    width: "32px",
    height: "32px",
    borderRadius: "50%",
    border: "1px solid #e2e8f0",
    background: "#f8fafc",
    color: "#64748b",
    cursor: "pointer",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: "14px",
    transition: "all 0.2s ease",
    zIndex: 1000,
    boxShadow: "0 2px 8px rgba(0,0,0,0.05)",
  },

  helpButtonHover: {
    background: "#f1f5f9",
    color: "#334155",
    boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
    transform: "scale(1.05)",
  },

  helpTooltip: {
    position: "absolute",
    top: "40px",
    right: "0px",
    background: "white",
    border: "1px solid #e2e8f0",
    borderRadius: "12px",
    padding: "16px",
    width: "280px",
    boxShadow: "0 8px 32px rgba(0,0,0,0.12), 0 2px 8px rgba(0,0,0,0.08)",
    fontSize: "12px",
    lineHeight: "1.5",
    color: "#334155",
    zIndex: 1001,
    opacity: 0,
    transform: "translateY(-8px)",
    pointerEvents: "none",
    transition: "all 0.2s ease",
  },

  helpTooltipVisible: {
    opacity: 1,
    transform: "translateY(0px)",
    pointerEvents: "auto",
  },

  helpTooltipTitle: {
    fontSize: "13px",
    fontWeight: "600",
    color: "#1e293b",
    marginBottom: "8px",
    display: "flex",
    alignItems: "center",
    gap: "6px",
  },

  helpTooltipText: {
    marginBottom: "12px",
    color: "#64748b",
  },

  helpTooltipContact: {
    fontSize: "11px",
    color: "#67d8ef",
    fontFamily: "monospace",
    background: "#f8fafc",
    padding: "4px 8px",
    borderRadius: "6px",
    border: "1px solid #e2e8f0",
  },
};

const insertGlobalStyles = () => {
  if (typeof document === "undefined") {
    return;
  }

  const existing = document.getElementById("app-shared-keyframes");
  if (existing) {
    return;
  }

  const styleSheet = document.createElement("style");
  styleSheet.id = "app-shared-keyframes";
  styleSheet.textContent = `
    @keyframes pulse {
      0% {
        box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.4);
      }
      70% {
        box-shadow: 0 0 0 6px rgba(16, 185, 129, 0);
      }
      100% {
        box-shadow: 0 0 0 0 rgba(16, 185, 129, 0);
      }
    }

    @keyframes typingBounce {
      0%, 80%, 100% {
        transform: translateY(0px);
        opacity: 0.35;
      }
      40% {
        transform: translateY(-4px);
        opacity: 1;
      }
    }

    /* Custom scrollbar styles */
    *::-webkit-scrollbar {
      width: 8px;
    }
    
    *::-webkit-scrollbar-track {
      background: transparent;
    }
    
    *::-webkit-scrollbar-thumb {
      background: #cbd5e1;
      border-radius: 4px;
    }
    
    *::-webkit-scrollbar-thumb:hover {
      background: #94a3b8;
    }
  `;
  document.head.appendChild(styleSheet);
};

export { styles, insertGlobalStyles };
