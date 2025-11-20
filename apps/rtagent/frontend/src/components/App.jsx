import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Box, Button, Card, CardContent, CardHeader, Chip, Divider, IconButton, LinearProgress, Paper, Typography } from '@mui/material';
import BuildCircleRoundedIcon from '@mui/icons-material/BuildCircleRounded';
import CheckCircleRoundedIcon from '@mui/icons-material/CheckCircleRounded';
import ErrorOutlineRoundedIcon from '@mui/icons-material/ErrorOutlineRounded';
import HourglassTopRoundedIcon from '@mui/icons-material/HourglassTopRounded';
import InfoRoundedIcon from '@mui/icons-material/InfoRounded';
import MicNoneRoundedIcon from '@mui/icons-material/MicNoneRounded';
import MicOffRoundedIcon from '@mui/icons-material/MicOffRounded';
import MicRoundedIcon from '@mui/icons-material/MicRounded';
import PhoneDisabledRoundedIcon from '@mui/icons-material/PhoneDisabledRounded';
import PhoneRoundedIcon from '@mui/icons-material/PhoneRounded';
import PhoneInTalkRoundedIcon from '@mui/icons-material/PhoneInTalkRounded';
import RestartAltRoundedIcon from '@mui/icons-material/RestartAltRounded';
import KeyboardRoundedIcon from '@mui/icons-material/KeyboardRounded';
import SendRoundedIcon from '@mui/icons-material/SendRounded';
import KeyboardArrowDownRoundedIcon from '@mui/icons-material/KeyboardArrowDownRounded';
import KeyboardArrowUpRoundedIcon from '@mui/icons-material/KeyboardArrowUpRounded';
import WarningAmberRoundedIcon from '@mui/icons-material/WarningAmberRounded';
import BoltRoundedIcon from '@mui/icons-material/BoltRounded';
import "reactflow/dist/style.css";
import TemporaryUserForm from './TemporaryUserForm';
import { AcsStreamingModeSelector, RealtimeStreamingModeSelector } from './StreamingModeSelector.jsx';
import ProfileButton from './ProfileButton.jsx';
import ProfileDetailsPanel from './ProfileDetailsPanel.jsx';
import DemoScenariosWidget from './DemoScenariosWidget.jsx';
import useBargeIn from '../hooks/useBargeIn.js';
import logger from '../utils/logger.js';

// Environment configuration
const backendPlaceholder = '__BACKEND_URL__';
const API_BASE_URL = backendPlaceholder.startsWith('__')
  ? import.meta.env.VITE_BACKEND_BASE_URL
  : backendPlaceholder;

const wsPlaceholder = '__WS_URL__';
const wsBaseCandidate = wsPlaceholder.startsWith('__')
  ? import.meta.env.VITE_WS_BASE_URL || API_BASE_URL
  : wsPlaceholder;

const toWsUrl = (value) => {
  if (!value || typeof value !== 'string') {
    return 'ws://localhost';
  }
  if (/^wss?:\/\//i.test(value)) {
    return value;
  }
  if (/^https:\/\//i.test(value)) {
    return value.replace(/^https:\/\//i, 'wss://');
  }
  if (/^http:\/\//i.test(value)) {
    return value.replace(/^http:\/\//i, 'ws://');
  }
  return value;
};

const WS_URL = toWsUrl(wsBaseCandidate);

// Session management utilities
const getOrCreateSessionId = () => {
  const sessionKey = 'voice_agent_session_id';
  let sessionId = sessionStorage.getItem(sessionKey);
  
  if (!sessionId) {
    const tabId = Math.random().toString(36).substr(2, 6);
    sessionId = `session_${Date.now()}_${tabId}`;
    sessionStorage.setItem(sessionKey, sessionId);
  }
  
  
  return sessionId;
};

const createNewSessionId = () => {
  const sessionKey = 'voice_agent_session_id';
  const tabId = Math.random().toString(36).substr(2, 6);
  const sessionId = `session_${Date.now()}_${tabId}`;
  sessionStorage.setItem(sessionKey, sessionId);
  logger.info('Created NEW session ID for reset:', sessionId);
  return sessionId;
};

const createMetricsState = () => ({
  sessionStart: null,
  sessionStartIso: null,
  sessionId: null,
  firstTokenTs: null,
  ttftMs: null,
  turnCounter: 0,
  turns: [],
  bargeInEvents: [],
  pendingBargeIn: null,
  lastAudioFrameTs: null,
  currentTurnId: null,
  awaitingAudioTurnId: null,
});

const toMs = (value) => (typeof value === "number" ? Math.round(value) : undefined);

const STREAM_MODE_STORAGE_KEY = 'rtagent.streamingMode';
const STREAM_MODE_FALLBACK = 'voice_live';
const REALTIME_STREAM_MODE_STORAGE_KEY = 'rtagent.realtimeStreamingMode';
const REALTIME_STREAM_MODE_FALLBACK = 'realtime';
const PANEL_MARGIN = 16;

const smoothValue = (prev, target, deltaMs, attackMs, releaseMs) => {
  const timeConstant = target > prev ? attackMs : releaseMs;
  const mix = 1 - Math.exp(-Math.max(deltaMs, 0) / Math.max(timeConstant, 1));
  return prev + (target - prev) * mix;
};

const buildSessionProfile = (raw, fallbackSessionId, previous) => {
  if (!raw && !previous) {
    return null;
  }
  const container = raw ?? {};
  const data = container.data ?? {};
  const demoMeta = container.demo_metadata
    ?? container.demoMetadata
    ?? data.demo_metadata
    ?? data.demoMetadata
    ?? {};
  const sessionValue = container.session_id
    ?? container.sessionId
    ?? data.session_id
    ?? data.sessionId
    ?? demoMeta.session_id
    ?? previous?.sessionId
    ?? fallbackSessionId;
  const profileValue = container.profile
    ?? data.profile
    ?? demoMeta.profile
    ?? previous?.profile
    ?? null;
  const rawTransactions = container.transactions ?? data.transactions;
  const metaTransactions = demoMeta.transactions;
  const transactionsValue = Array.isArray(rawTransactions) && rawTransactions.length
    ? rawTransactions
    : Array.isArray(metaTransactions) && metaTransactions.length
    ? metaTransactions
    : previous?.transactions ?? [];
  const interactionPlanValue = container.interaction_plan
    ?? container.interactionPlan
    ?? data.interaction_plan
    ?? data.interactionPlan
    ?? demoMeta.interaction_plan
    ?? previous?.interactionPlan
    ?? null;
  const entryIdValue = container.entry_id
    ?? container.entryId
    ?? data.entry_id
    ?? data.entryId
    ?? demoMeta.entry_id
    ?? previous?.entryId
    ?? null;
  const expiresAtValue = container.expires_at
    ?? container.expiresAt
    ?? data.expires_at
    ?? data.expiresAt
    ?? demoMeta.expires_at
    ?? previous?.expiresAt
    ?? null;
  const safetyNoticeValue = container.safety_notice
    ?? container.safetyNotice
    ?? data.safety_notice
    ?? data.safetyNotice
    ?? demoMeta.safety_notice
    ?? previous?.safetyNotice
    ?? null;

  return {
    sessionId: sessionValue,
    profile: profileValue,
    transactions: transactionsValue,
    interactionPlan: interactionPlanValue,
    entryId: entryIdValue,
    expiresAt: expiresAtValue,
    safetyNotice: safetyNoticeValue,
  };
};

const formatStatusTimestamp = (isoValue) => {
  if (!isoValue) {
    return null;
  }
  const date = isoValue instanceof Date ? isoValue : new Date(isoValue);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  return date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
};

const inferStatusTone = (textValue = "") => {
  const normalized = textValue.toLowerCase();
  const matchesAny = (needles) => needles.some((needle) => normalized.includes(needle));
  if (textValue.includes("❌") || textValue.includes("🚫") || matchesAny(["error", "fail", "critical"])) {
    return "error";
  }
  if (textValue.includes("✅") || textValue.includes("🎉") || matchesAny(["success", "ready", "connected", "restarted", "completed"])) {
    return "success";
  }
  if (textValue.includes("⚠️") || textValue.includes("🛑") || textValue.includes("📵") || matchesAny(["stopp", "ended", "disconnect", "hang up", "warning"])) {
    return "warning";
  }
  return "info";
};

const formatEventTypeLabel = (value = "") => {
  if (!value) return "System Event";
  return value
    .split(/[_\s]+/u)
    .filter(Boolean)
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
    .join(" ");
};

const shortenIdentifier = (value) => {
  if (typeof value !== "string") return value;
  return value.length > 14 ? `${value.slice(0, 6)}…${value.slice(-4)}` : value;
};

const describeEventData = (data = {}) => {
  if (!data || typeof data !== "object") {
    return null;
  }

  const summaryParts = [];
  const seen = new Set();
  const prioritizedKeys = [
    "message",
    "reason_label",
    "disconnect_reason",
    "caller_id",
    "call_connection_id",
    "browser_session_id",
    "connected_at",
    "ended_at",
  ];

  const formatKey = (key) =>
    key
      .split(/[_\s]+/u)
      .filter(Boolean)
      .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
      .join(" ");

  const formatValue = (key, value) => {
    if (value == null) return value;
    if (typeof value === "number") return value;
    if (typeof value !== "string") return value;
    if (key.includes("id")) return shortenIdentifier(value);
    if (key.includes("reason")) {
      return value
        .split(/[_\s]+/u)
        .filter(Boolean)
        .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
        .join(" ");
    }
    if (key.endsWith("_at")) {
      return formatStatusTimestamp(value) ?? value;
    }
    return value;
  };

  const appendSummary = (key, rawValue) => {
    if (rawValue == null || seen.has(key)) {
      return;
    }
    const formattedValue = formatValue(key, rawValue);
    if (formattedValue === undefined || formattedValue === null || formattedValue === "") {
      return;
    }
    summaryParts.push(`${formatKey(key)}: ${formattedValue}`);
    seen.add(key);
  };

  prioritizedKeys.forEach((key) => appendSummary(key, data[key]));

  if (!summaryParts.length) {
    Object.entries(data).forEach(([key, value]) => {
      if (seen.has(key)) return;
      if (typeof value === "string" || typeof value === "number") {
        appendSummary(key, value);
      }
    });
  }

  return summaryParts.length ? summaryParts.slice(0, 2).join(" • ") : null;
};

const buildSystemMessage = (text, options = {}) => {
  const timestamp = options.timestamp ?? new Date().toISOString();
  const statusTone = options.statusTone ?? options.tone ?? inferStatusTone(text);
  return {
    speaker: "System",
    text,
    statusTone,
    timestamp,
    statusCaption: options.statusCaption ?? null,
    statusLabel: options.statusLabel ?? null,
  };
};

const STATUS_TONE_META = {
  info: {
    label: "System Message",
    accent: "#2563eb",
    background: "linear-gradient(135deg, rgba(37,99,235,0.08), rgba(14,116,144,0.06))",
    border: "1px solid rgba(37,99,235,0.18)",
    borderColor: "rgba(37,99,235,0.18)",
    surface: "rgba(37,99,235,0.12)",
    iconBackground: "rgba(37,99,235,0.14)",
    icon: InfoRoundedIcon,
    textColor: "#0f172a",
    captionColor: "rgba(15,23,42,0.65)",
  },
  success: {
    label: "Event",
    accent: "#059669",
    background: "linear-gradient(135deg, rgba(16,185,129,0.12), rgba(56,189,248,0.05))",
    border: "1px solid rgba(34,197,94,0.24)",
    borderColor: "rgba(34,197,94,0.24)",
    surface: "rgba(16,185,129,0.14)",
    iconBackground: "rgba(16,185,129,0.18)",
    icon: CheckCircleRoundedIcon,
    textColor: "#064e3b",
    captionColor: "rgba(6,78,59,0.7)",
  },
  warning: {
    label: "Warning",
    accent: "#f59e0b",
    background: "linear-gradient(135deg, rgba(245,158,11,0.14), rgba(249,115,22,0.08))",
    border: "1px solid rgba(245,158,11,0.28)",
    borderColor: "rgba(245,158,11,0.28)",
    surface: "rgba(245,158,11,0.16)",
    iconBackground: "rgba(245,158,11,0.22)",
    icon: WarningAmberRoundedIcon,
    textColor: "#7c2d12",
    captionColor: "rgba(124,45,18,0.7)",
  },
  call: {
    label: "Call Live",
    accent: "#0ea5e9",
    background: "linear-gradient(135deg, rgba(14,165,233,0.14), rgba(45,212,191,0.08))",
    border: "1px solid rgba(14,165,233,0.24)",
    borderColor: "rgba(14,165,233,0.24)",
    surface: "rgba(14,165,233,0.16)",
    iconBackground: "rgba(14,165,233,0.22)",
    icon: PhoneInTalkRoundedIcon,
    textColor: "#0f172a",
    captionColor: "rgba(15,23,42,0.55)",
  },
  error: {
    label: "Action Needed",
    accent: "#ef4444",
    background: "linear-gradient(135deg, rgba(239,68,68,0.12), rgba(249,115,22,0.05))",
    border: "1px solid rgba(239,68,68,0.26)",
    borderColor: "rgba(239,68,68,0.26)",
    surface: "rgba(239,68,68,0.14)",
    iconBackground: "rgba(239,68,68,0.2)",
    icon: ErrorOutlineRoundedIcon,
    textColor: "#7f1d1d",
    captionColor: "rgba(127,29,29,0.7)",
  },
};

// Component styles
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
    position: "relative",
    width: "100%",
    maxWidth: "100%",
    height: "calc(100vh - 32px)",
    minHeight: "calc(100vh - 32px)",
    maxHeight: "calc(100vh - 32px)",
    display: "flex",
    flexDirection: "column",
    alignItems: "stretch",
    justifyContent: "flex-start",
    paddingTop: "18px",
  },

  mainShell: {
    position: "relative",
    flex: 1,
    background: "white",
    borderRadius: "20px",
    boxShadow: "0 12px 32px rgba(15,23,42,0.12)",
    border: "0px solid transparent",
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
  },

  helpButtonDock: {
    position: "fixed",
    top: "20px",
    left: "24px",
    display: "flex",
    alignItems: "center",
    gap: "12px",
    zIndex: 120,
  },
  backendIndicatorDock: {
    position: "fixed",
    bottom: "20px",
    left: "28px",
    transform: "scale(0.94)",
    transformOrigin: "bottom left",
    boxShadow: "0 6px 18px rgba(15,23,42,0.18)",
    zIndex: 7,
  },

  appHeader: {
    position: "relative",
    backgroundColor: "#f8fafc",
    background: "linear-gradient(180deg, #ffffff 0%, #f8fafc 100%)",
    padding: "20px 24px 18px 24px",
    borderBottom: "1px solid #e2e8f0",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: "18px",
    minHeight: "96px",
  },

  appHeaderIdentity: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: "8px",
    padding: "16px 24px",
    borderRadius: "22px",
    background: "linear-gradient(140deg, rgba(255,255,255,0.97), rgba(248,250,252,0.92))",
    border: "1px solid rgba(148,163,184,0.18)",
    boxShadow: "0 8px 20px rgba(15,23,42,0.08)",
    width: "100%",
    maxWidth: "420px",
  },

  appTitleBlock: {
    display: "flex",
    flexDirection: "column",
    gap: "4px",
    minWidth: 0,
    alignItems: "center",
    textAlign: "center",
  },

  appTitle: {
    fontSize: "16px",
    fontWeight: "800",
    color: "#0f172a",
    margin: 0,
    letterSpacing: "-0.02em",
    // textTransform: "uppercase",
  },

  appSubtitle: {
    fontSize: "11px",
    color: "#475569",
    margin: 0,
    maxWidth: "320px",
    lineHeight: "1.35",
  },

  appHeaderFooter: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "16px",
    flexWrap: "wrap",
    width: "100%",
    maxWidth: "520px",
    margin: "0 auto",
  },

  sessionTag: {
    display: "flex",
    alignItems: "center",
    gap: "6px",
    padding: "7px 14px",
    borderRadius: "999px",
    background: "rgba(248,250,252,0.9)",
    border: "1px solid rgba(148,163,184,0.28)",
    fontSize: "10px",
    color: "#1f2937",
    whiteSpace: "nowrap",
    boxShadow: "none",
    flexShrink: 0,
  },
  waveformSection: {
    position: "relative",
    // padding: "18px 28px 20px 28px",
    background: "linear-gradient(180deg, rgba(248,250,252,0.95) 0%, rgba(241,245,249,1) 100%)",
    borderBottom: "1px solid rgba(148,163,184,0.18)",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: "10px",
    overflow: "visible",
    boxShadow: "inset 0 -10px 20px rgba(15,23,42,0.04)",
  },
  waveformSectionCollapsed: {
    padding: "10px 22px 12px 22px",
    minHeight: "0",
    alignItems: "flex-start",
    justifyContent: "flex-start",
    gap: "6px",
  },
  waveformHeader: {
    width: "100%",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
  },
  waveformHint: {
    fontSize: "11px",
    color: "#94a3b8",
    fontWeight: 500,
    letterSpacing: "0.1px",
  },
  waveformCollapsedLine: {
    width: "100%",
    height: "2px",
    borderRadius: "999px",
    background: "linear-gradient(90deg, rgba(148,163,184,0.05), rgba(148,163,184,0.35), rgba(148,163,184,0.05))",
  },
  
  // Section divider line - more subtle
  sectionDivider: {
    position: "absolute",
    bottom: 0,
    left: "24px",
    right: "24px",
    height: "1px",
    backgroundColor: "rgba(148,163,184,0.35)",
    borderRadius: "999px",
    opacity: 0.7,
    pointerEvents: "none",
    zIndex: 0,
  },
  
  waveformContainer: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    width: "100%",
    height: "72px",
    padding: "0 16px",
    background: "radial-gradient(ellipse at center, rgba(100, 116, 139, 0.08) 0%, transparent 70%)",
    borderRadius: "0px",
  },
  
  waveformSvg: {
    width: "100%",
    height: "72px",
    filter: "drop-shadow(0 2px 6px rgba(100, 116, 139, 0.15))",
    transition: "filter 0.3s ease",
  },
  
  chatSection: {
    flex: 1,
    width: "100%",
    overflowY: "auto",
    overflowX: "hidden",
    backgroundColor: "#ffffff",
    borderTop: "1px solid rgba(148,163,184,0.14)",
    borderBottom: "1px solid rgba(148,163,184,0.12)",
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
  
  // Chat section visual indicator
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
    gap: "18px",
    flex: 1,
    overflowY: "auto",
    overflowX: "hidden",
    padding: "6px 6px 18px",
  },
  
  userMessage: {
    alignSelf: "flex-end",
    maxWidth: "78%",
    marginRight: "20px",
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
  
  // Assistant message (left aligned - teal bubble)
  assistantMessage: {
    alignSelf: "flex-start",
    maxWidth: "82%", // Increased width for maximum space usage
    marginLeft: "4px", // No left margin - flush to edge
    marginBottom: "4px",
  },
  
  assistantBubble: {
    background: "#67d8ef",
    color: "white",
    padding: "12px 16px",
    borderRadius: "20px",
    fontSize: "14px",
    lineHeight: "1.5",
    boxShadow: "0 2px 8px rgba(103,216,239,0.3)",
    wordWrap: "break-word",
    overflowWrap: "break-word",
    hyphens: "auto",
    whiteSpace: "pre-wrap",
  },

  // Agent name label (appears above specialist bubbles)
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
  
  // Control section - blended footer design
  controlSection: {
    padding: "10px 16px 14px",
    background: "#f5f7fb",
    display: "flex",
    justifyContent: "center",
    alignItems: "center",
    borderTop: "1px solid #e2e8f0",
    position: "relative",
  },
  
  controlContainer: {
    display: "flex",
    gap: "10px",
    background: "rgba(255,255,255,0.9)",
    padding: "12px 18px",
    borderRadius: "22px",
    boxShadow: "0 4px 14px rgba(15,23,42,0.12)",
    border: "1px solid rgba(226,232,240,0.9)",
    width: "fit-content",
  },
  
  // Enhanced button styles with hover effects
  resetButton: (isHovered) => ({
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
    color: "#1f2937",
    transform: isHovered ? "scale(1.08)" : "scale(1)",
    boxShadow: isHovered ? 
      "0 8px 24px rgba(100,116,139,0.3), 0 0 0 3px rgba(100,116,139,0.15)" :
      "0 2px 8px rgba(0,0,0,0.08)",
    padding: 0,
    '& svg': {
      color: isHovered ? "#0F172A" : "#1f2937",
    },
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
    background: isHovered ? 
      (isActive ? "linear-gradient(135deg, #10b981, #059669)" : "linear-gradient(135deg, #dcfce7, #bbf7d0)") :
      "linear-gradient(135deg, #f1f5f9, #e2e8f0)",
    color: isHovered ? 
      (isActive ? "white" : "#0f172a") :
      (isActive ? "#0ea5e9" : "#1f2937"),
    transform: isHovered ? "scale(1.08)" : (isActive ? "scale(1.05)" : "scale(1)"),
    boxShadow: isHovered ? 
      "0 8px 25px rgba(16,185,129,0.4), 0 0 0 4px rgba(16,185,129,0.15), inset 0 1px 2px rgba(255,255,255,0.2)" :
      (isActive ? 
        "0 6px 20px rgba(14,165,233,0.3), 0 0 0 3px rgba(14,165,233,0.15)" : 
        "0 2px 8px rgba(0,0,0,0.08)"),
    padding: 0,
    '& svg': {
      color: isHovered ? (isActive ? "#f8fafc" : "#0f172a") : (isActive ? "#0284c7" : "#1f2937"),
    },
  }),

  muteButton: (isMuted, isHovered, isDisabled = false) => {
    const base = {
      width: "56px",
      height: "56px",
      borderRadius: "50%",
      border: "none",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      transition: "all 0.3s ease",
      position: "relative",
      padding: 0,
      '& svg': {
        color: "#1f2937",
      },
    };

    if (isDisabled) {
      return {
        ...base,
        cursor: "not-allowed",
        background: "linear-gradient(135deg, #e2e8f0, #cbd5e1)",
        opacity: 0.6,
        boxShadow: "inset 0 0 0 1px rgba(148,163,184,0.35)",
        '& svg': {
          color: "#94a3b8",
        },
      };
    }

    const palette = isMuted
      ? {
          base: "linear-gradient(135deg, #f8fafc, #fee2e2)",
          hover: "linear-gradient(135deg, #fee2e2, #fecaca)",
          fg: "#dc2626",
          hoverFg: "#b91c1c",
          shadow: "0 6px 18px rgba(248,113,113,0.35), 0 0 0 3px rgba(248,113,113,0.15)",
        }
      : {
          base: "linear-gradient(135deg, #f1f5f9, #e2e8f0)",
          hover: "linear-gradient(135deg, #dcfce7, #bbf7d0)",
          fg: "#0f172a",
          hoverFg: "#047857",
          shadow: "0 6px 18px rgba(16,185,129,0.28), 0 0 0 3px rgba(16,185,129,0.16)",
        };

    return {
      ...base,
      cursor: "pointer",
      background: isHovered ? palette.hover : palette.base,
      transform: isHovered ? "scale(1.08)" : "scale(1)",
      boxShadow: isHovered ? palette.shadow : "0 2px 8px rgba(15,23,42,0.12)",
      '& svg': {
        color: isHovered ? palette.hoverFg : palette.fg,
      },
    };
  },

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
      color: "#1f2937",
      padding: 0,
      '& svg': {
        color: "#1f2937",
      },
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
        padding: 0,
        '& svg': {
          color: "#94a3b8",
        },
      };
    }

    return {
      ...base,
      cursor: "pointer",
      background: isHovered ? 
        (isActive ? "linear-gradient(135deg, #3f75a8ff, #2b5d8f)" : "linear-gradient(135deg, #dcfce7, #bbf7d0)") :
        "linear-gradient(135deg, #f1f5f9, #e2e8f0)",
      color: isHovered ? 
        (isActive ? "white" : "#1f2937") :
        (isActive ? "#2563eb" : "#1f2937"),
      transform: isHovered ? "scale(1.08)" : (isActive ? "scale(1.05)" : "scale(1)"),
      boxShadow: isHovered ? 
        "0 8px 25px rgba(37,99,235,0.25), 0 0 0 4px rgba(37,99,235,0.15), inset 0 1px 2px rgba(255,255,255,0.2)" :
        (isActive ? 
          "0 6px 20px rgba(37,99,235,0.35), 0 0 0 3px rgba(37,99,235,0.15)" : 
          "0 2px 8px rgba(0,0,0,0.08)"),
      padding: 0,
      '& svg': {
        color: isHovered ? (isActive ? "#f8fafc" : "#0f172a") : (isActive ? "#2563eb" : "#1f2937"),
      },
    };
  },

  keyboardButton: (isActive, isHovered) => ({
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
    background: isHovered ? 
      (isActive ? "linear-gradient(135deg, #3b82f6, #2563eb)" : "linear-gradient(135deg, #dbeafe, #bfdbfe)") :
      "linear-gradient(135deg, #f1f5f9, #e2e8f0)",
    color: isHovered ? 
      (isActive ? "white" : "#0f172a") :
      (isActive ? "#2563eb" : "#1f2937"),
    transform: isHovered ? "scale(1.08)" : (isActive ? "scale(1.05)" : "scale(1)"),
    boxShadow: isHovered ? 
      "0 8px 25px rgba(59,130,246,0.4), 0 0 0 4px rgba(59,130,246,0.15), inset 0 1px 2px rgba(255,255,255,0.2)" :
      (isActive ? 
        "0 6px 20px rgba(37,99,235,0.3), 0 0 0 3px rgba(37,99,235,0.15)" : 
        "0 2px 8px rgba(0,0,0,0.08)"),
    padding: 0,
    '& svg': {
      color: isHovered ? (isActive ? "#f8fafc" : "#0f172a") : (isActive ? "#2563eb" : "#1f2937"),
    },
  }),

  // Tooltip styles
  buttonTooltip: {
    position: 'fixed',
    left: 0,
    top: 0,
    transform: 'translate(-50%, 0)',
    background: 'rgba(30, 41, 59, 0.92)',
    color: '#f1f5f9',
    padding: '8px 12px',
    borderRadius: '8px',
    fontSize: '11px',
    fontWeight: '500',
    whiteSpace: 'nowrap',
    boxShadow: '0 4px 10px rgba(15,23,42,0.18)',
    border: '1px solid rgba(255,255,255,0.08)',
    pointerEvents: 'none',
    opacity: 0,
    transition: 'opacity 0.18s ease, transform 0.18s ease',
    zIndex: 80,
  },

  buttonTooltipVisible: {
    opacity: 1,
    transform: 'translate(-50%, 0)',
  },

  realtimeModeDock: {
    width: '100%',
    padding: '0 24px',
    marginTop: '12px',
    position: 'relative',
    minHeight: '1px',
  },

  realtimeModePanel: {
    position: 'fixed',
    width: '100%',
    maxWidth: '360px',
    zIndex: 120,
  },

  textInputContainer: {
    display: "flex",
    alignItems: "center",
    gap: "10px",
    padding: "14px 24px 16px",
    backgroundColor: "rgba(255,255,255,0.98)",
    borderTop: "1px solid rgba(226,232,240,0.5)",
    width: "100%",
    boxSizing: "border-box",
    boxShadow: "0 -4px 12px rgba(15,23,42,0.04)",
    transition: "all 0.3s ease",
  },

  textInput: {
    flex: 1,
    padding: "12px 16px",
    borderRadius: "22px",
    border: "1px solid #e2e8f0",
    fontSize: "14px",
    outline: "none",
    transition: "all 0.2s ease",
    backgroundColor: "#f8fafc",
    color: "#1e293b",
    fontFamily: "inherit",
  },
  
  // Input section for phone calls
  phoneInputSection: {
    position: "absolute",
    bottom: "120px",
    right: "32px",
    padding: "16px",
    borderRadius: "18px",
    background: "rgba(255,255,255,0.96)",
    border: "1px solid rgba(226,232,240,0.9)",
    boxShadow: "0 20px 30px rgba(15,23,42,0.18)",
    fontSize: "12px",
    flexDirection: "column",
    gap: "12px",
    minWidth: "280px",
    maxWidth: "320px",
    zIndex: 90,
  },
  
  phoneInputRow: {
    display: "flex",
    alignItems: "center",
    gap: "10px",
    width: "100%",
  },
  
  phoneInput: {
    flex: 1,
    padding: "10px 12px",
    border: "1px solid #d1d5db",
    borderRadius: "12px",
    fontSize: "14px",
    outline: "none",
    transition: "border-color 0.2s ease, box-shadow 0.2s ease",
  },
  

  // Backend status indicator - enhanced for component health - relocated to bottom left
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
    boxShadow: "0 6px 18px rgba(15,23,42,0.16)",
    zIndex: 60,
    minWidth: "280px",
    maxWidth: "320px",
  },

  maskToggleButton: {
    fontSize: "9px",
    padding: "4px 8px",
    borderRadius: "6px",
    border: "1px solid rgba(59,130,246,0.4)",
    background: "rgba(59,130,246,0.08)",
    color: "#2563eb",
    fontWeight: 600,
    cursor: "pointer",
    transition: "all 0.2s ease",
  },

  maskToggleButtonActive: {
    background: "rgba(59,130,246,0.16)",
    color: "#1d4ed8",
    borderColor: "rgba(37,99,235,0.5)",
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
    gap: "6px", // Reduced from 12px to half
    marginTop: "6px", // Reduced from 12px to half
    paddingTop: "6px", // Reduced from 12px to half
    borderTop: "1px solid #f1f5f9",
  },

  componentItem: {
    display: "flex",
    alignItems: "center",
    gap: "4px", // Reduced from 8px to half
    padding: "5px 7px", // Reduced from 10px 14px to half
    backgroundColor: "#f8fafc",
    borderRadius: "5px", // Reduced from 10px to half
    fontSize: "9px", // Reduced from 11px
    border: "1px solid #e2e8f0",
    transition: "all 0.2s ease",
    minHeight: "22px", // Reduced from 45px to half
  },

  componentDot: (status) => ({
    width: "4px", // Reduced from 8px to half
    height: "4px", // Reduced from 8px to half
    borderRadius: "50%",
    backgroundColor: status === "healthy" ? "#10b981" : 
                     status === "degraded" ? "#f59e0b" : 
                     status === "unhealthy" ? "#ef4444" : "#6b7280",
    flexShrink: 0,
  }),

  componentName: {
    fontWeight: "500",
    color: "#475569",
    textTransform: "capitalize",
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
    fontSize: "9px", // Reduced from 11px
    letterSpacing: "0.01em", // Reduced letter spacing
  },

  responseTime: {
    fontSize: "8px", // Reduced from 10px
    color: "#94a3b8",
    marginLeft: "auto",
  },

  errorMessage: {
    fontSize: "10px",
    color: "#ef4444",
    marginTop: "4px",
    fontStyle: "italic",
  },

  // Call Me button style (rectangular box)
  callMeButton: (isActive, isDisabled = false) => ({
    padding: "12px 24px",
    marginTop: "4px",
    background: isDisabled ? "linear-gradient(135deg, #e2e8f0, #cbd5e1)" : (isActive ? "#ef4444" : "#67d8ef"),
    color: isDisabled ? "#94a3b8" : "white",
    border: "none",
    borderRadius: "16px", // More box-like - less rounded
    cursor: isDisabled ? "not-allowed" : "pointer",
    fontSize: "14px",
    fontWeight: "600",
    transition: "all 0.2s ease",
    boxShadow: isDisabled ? "inset 0 0 0 1px rgba(148, 163, 184, 0.3)" : "0 2px 8px rgba(0,0,0,0.1)",
    minWidth: "120px", // Ensure consistent width
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

  // Help button in top right corner
  helpButton: {
    position: "relative",
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
    boxShadow: "0 2px 8px rgba(0,0,0,0.05)",
    flexShrink: 0,
    zIndex: 20,
  },

  helpButtonHover: {
    background: "#f1f5f9",
    color: "#334155",
    boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
    transform: "scale(1.05)",
  },

  industryTag: {
    display: "flex",
    flexDirection: "column",
    gap: "8px",
  },
  topTabsContainer: {
    position: "absolute",
    top: "-8px",
    left: "36px",
    display: "flex",
    alignItems: "center",
    gap: "6px",
    zIndex: 0,
  },
  topTab: (active, palette = {}) => {
    const {
      background = "linear-gradient(135deg, #334155, #1f2937)",
      color = "#f8fafc",
      borderColor = "rgba(51,65,85,0.45)",
      shadow = "0 10px 22px rgba(30,64,175,0.22)",
      textShadow = "0 1px 2px rgba(15,23,42,0.45)",
    } = palette;
    return {
      padding: "7px 18px",
      borderRadius: "12px 12px 0 0",
      border: active ? `1px solid ${borderColor}` : "1px solid rgba(148,163,184,0.45)",
      borderBottom: active ? "1px solid transparent" : "1px solid rgba(148,163,184,0.5)",
      background: active ? background : "rgba(148,163,184,0.08)",
      color: active ? color : "#475569",
      gap: "12px",
      flexWrap: "wrap",
      fontSize: "9px",
      fontWeight: 700,
      textTransform: "uppercase",
      letterSpacing: "0.14em",
      boxShadow: active ? shadow : "inset 0 -1px 0 rgba(148,163,184,0.4)",
      cursor: active ? "default" : "pointer",
      transition: "all 0.24s ease",
      textShadow: active ? textShadow : "none",
    };
  },
  createProfileButton: {
    textTransform: "uppercase",
    letterSpacing: "0.12em",
    fontWeight: 600,
    fontSize: "11px",
    padding: "10px 20px",
    borderRadius: "18px",
    background: "linear-gradient(135deg, #6366f1, #8b5cf6)",
    boxShadow: "0 10px 22px rgba(99,102,241,0.28)",
    color: "#f8fafc",
    border: "1px solid rgba(255,255,255,0.25)",
  },
  createProfileButtonHover: {
    boxShadow: "0 14px 26px rgba(99,102,241,0.33)",
  },

  helpTooltip: {
    position: "absolute",
    top: "calc(100% + 10px)",
    left: 0,
    background: "white",
    border: "1px solid #e2e8f0",
    borderRadius: "12px",
    padding: "16px",
    width: "280px",
    boxShadow: "0 8px 32px rgba(0,0,0,0.12), 0 2px 8px rgba(0,0,0,0.08)",
    fontSize: "12px",
    lineHeight: "1.5",
    color: "#334155",
    zIndex: 25,
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
    flexShrink: 0,
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
  demoFormBackdrop: {
    position: "fixed",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: "rgba(15, 23, 42, 0.25)",
    zIndex: 12000,
  },
  demoFormOverlay: {
    position: "fixed",
    top: "50%",
    left: "50%",
    transform: "translate(-50%, -50%)",
    zIndex: 12010,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: "8px",
    maxWidth: "100vw",
    maxHeight: "calc(100vh - 80px)",
    overflowY: "auto",
    scrollbarWidth: "none",
    msOverflowStyle: "none",
  },
  profileButtonWrapper: {
    margin: "0 24px",
    paddingBottom: "12px",
  },
  profileMenuPaper: {
    maxWidth: '380px',
    minWidth: '320px',
    boxShadow: '0 8px 32px rgba(0,0,0,0.12), 0 2px 16px rgba(0,0,0,0.08)',
    borderRadius: '16px',
    border: '1px solid rgba(226, 232, 240, 0.8)',
    backdropFilter: 'blur(20px)',
  },
  profileDetailsGrid: {
    padding: '16px',
    display: 'grid',
    gap: '8px',
    fontSize: '12px',
    color: '#1f2937',
  },
  profileDetailItem: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '4px 0',
  },
  profileDetailLabel: {
    fontWeight: '600',
    color: '#64748b',
    fontSize: '11px',
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
  },
  profileDetailValue: {
    fontWeight: '500',
    color: '#1f2937',
    textAlign: 'right',
    maxWidth: '200px',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  },
  profileMenuHeader: {
    padding: '16px 16px 8px 16px',
    background: 'linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%)',
    borderTopLeftRadius: '16px',
    borderTopRightRadius: '16px',
  },
  ssnChipWrapper: {
    display: 'flex',
    justifyContent: 'center',
    padding: '8px 16px',
    background: 'linear-gradient(135deg, rgba(239, 68, 68, 0.05) 0%, rgba(249, 115, 22, 0.05) 100%)',
  },
  profileBadge: {
    padding: "10px 12px",
    borderRadius: "10px",
    background: "linear-gradient(135deg, #f97316, #ef4444)",
    color: "#ffffff",
    fontWeight: 700,
    letterSpacing: "0.6px",
    textAlign: "center",
  },
  profileNotice: {
    marginTop: "4px",
    padding: "8px 10px",
    borderRadius: "8px",
    background: "#fef2f2",
    border: "1px solid #fecaca",
    color: "#b91c1c",
    fontSize: "11px",
    fontWeight: 600,
    textAlign: "center",
  },
};
// Add keyframe animation for pulse effect
const styleSheet = document.createElement("style");
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
  .demo-form-overlay {
    scrollbar-width: none;
    -ms-overflow-style: none;
  }
  .demo-form-overlay::-webkit-scrollbar {
    display: none;
  }
`;
document.head.appendChild(styleSheet);

/* ------------------------------------------------------------------ *
 *  BACKEND HELP BUTTON COMPONENT
 * ------------------------------------------------------------------ */
const BackendHelpButton = () => {
  const [isHovered, setIsHovered] = useState(false);
  const [isClicked, setIsClicked] = useState(false);

  const handleClick = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsClicked(!isClicked);
  };

  const handleMouseLeave = () => {
    setIsHovered(false);
  };

  return (
    <div 
      style={{
        width: '14px',
        height: '14px',
        borderRadius: '50%',
        backgroundColor: isHovered ? '#3b82f6' : '#64748b',
        color: 'white',
        fontSize: '9px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        cursor: 'pointer',
        transition: 'all 0.2s ease',
        fontWeight: '600',
        position: 'relative',
        flexShrink: 0
      }}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={handleMouseLeave}
      onClick={handleClick}
    >
      ?
      <div style={{
        visibility: (isHovered || isClicked) ? 'visible' : 'hidden',
        opacity: (isHovered || isClicked) ? 1 : 0,
        position: 'absolute',
        bottom: '20px',
        left: '0',
        backgroundColor: 'rgba(0, 0, 0, 0.95)',
        color: 'white',
        padding: '12px',
        borderRadius: '8px',
        fontSize: '11px',
        lineHeight: '1.4',
        minWidth: '280px',
        maxWidth: '320px',
        boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
        zIndex: 10000,
        transition: 'all 0.2s ease',
        backdropFilter: 'blur(8px)'
      }}>
        <div style={{
          fontSize: '12px',
          fontWeight: '600',
          color: '#67d8ef',
          marginBottom: '8px',
          display: 'flex',
          alignItems: 'center',
          gap: '6px'
        }}>
          🔧 Backend Status Monitor
        </div>
        <div style={{ marginBottom: '8px' }}>
          Real-time health monitoring for all ARTAgent backend services including Redis cache, Azure OpenAI, Speech Services, and Communication Services.
        </div>
        <div style={{ marginBottom: '8px' }}>
          <strong>Status Colors:</strong><br/>
          🟢 Healthy - All systems operational<br/>
          🟡 Degraded - Some performance issues<br/>
          🔴 Unhealthy - Service disruption
        </div>
        <div style={{ fontSize: '10px', color: '#94a3b8', fontStyle: 'italic' }}>
          Auto-refreshes every 30 seconds • Click to expand for details
        </div>
        {isClicked && (
          <div style={{
            textAlign: 'center',
            marginTop: '8px',
            fontSize: '9px',
            color: '#94a3b8',
            fontStyle: 'italic'
          }}>
            Click ? again to close
          </div>
        )}
      </div>
    </div>
  );
};

/* ------------------------------------------------------------------ *
 *  BACKEND STATISTICS BUTTON COMPONENT
 * ------------------------------------------------------------------ */
const BackendStatisticsButton = ({ onToggle, isActive }) => {
  const [isHovered, setIsHovered] = useState(false);

  const handleClick = (e) => {
    e.preventDefault();
    e.stopPropagation();
    onToggle();
  };

  return (
    <div 
      style={{
        width: '14px',
        height: '14px',
        borderRadius: '50%',
        backgroundColor: isActive ? '#3b82f6' : (isHovered ? '#3b82f6' : '#64748b'),
        color: 'white',
        fontSize: '8px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        cursor: 'pointer',
        transition: 'all 0.2s ease',
        fontWeight: '600',
        position: 'relative',
        flexShrink: 0
      }}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      onClick={handleClick}
      title="Toggle session statistics"
    >
      📊
    </div>
  );
};

/* ------------------------------------------------------------------ *
 *  HELP BUTTON WITH TOOLTIP COMPONENT
 * ------------------------------------------------------------------ */
const HelpButton = () => {
  const [isHovered, setIsHovered] = useState(false);
  const [isClicked, setIsClicked] = useState(false);

  const handleClick = (e) => {
    // Don't prevent default for links
    if (e.target.tagName !== 'A') {
      e.preventDefault();
      e.stopPropagation();
      setIsClicked(!isClicked);
    }
  };

  const handleMouseLeave = () => {
    setIsHovered(false);
    // Only hide if not clicked
    if (!isClicked) {
      // Tooltip will hide via CSS
    }
  };

  return (
    <div 
      style={{
        ...styles.helpButton,
        ...(isHovered ? styles.helpButtonHover : {})
      }}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={handleMouseLeave}
      onClick={handleClick}
    >
      ?
      <div style={{
        ...styles.helpTooltip,
        ...((isHovered || isClicked) ? styles.helpTooltipVisible : {})
      }}>
        <div style={styles.helpTooltipTitle}>
        </div>
        <div style={{
          ...styles.helpTooltipText,
          color: '#dc2626',
          fontWeight: '600',
          fontSize: '12px',
          marginBottom: '12px',
          padding: '8px',
          backgroundColor: '#fef2f2',
          borderRadius: '4px',
          border: '1px solid #fecaca'
        }}>
          This is a demo available for Microsoft employees only.
        </div>
        <div style={styles.helpTooltipTitle}>
          🤖 ARTAgent Demo
        </div>
        <div style={styles.helpTooltipText}>
          ARTAgent is an accelerator that delivers a friction-free, AI-driven voice experience—whether callers dial a phone number, speak to an IVR, or click "Call Me" in a web app. Built entirely on Azure services, it provides a low-latency stack that scales on demand while keeping the AI layer fully under your control.
        </div>
        <div style={styles.helpTooltipText}>
          Design a single agent or orchestrate multiple specialist agents. The framework allows you to build your voice agent from scratch, incorporate memory, configure actions, and fine-tune your TTS and STT layers.
        </div>
        <div style={styles.helpTooltipText}>
          🤔 <strong>Try asking about:</strong> Transfer Agency DRIP liquidations, compliance reviews, fraud detection, or general inquiries.
        </div>
        <div style={styles.helpTooltipText}>
         📑 <a 
            href="https://microsoft.sharepoint.com/teams/rtaudioagent" 
            target="_blank" 
            rel="noopener noreferrer"
            style={{
              color: '#3b82f6',
              textDecoration: 'underline'
            }}
            onClick={(e) => e.stopPropagation()}
          >
            Visit the Project Hub
          </a> for instructions, deep dives and more.
        </div>
        <div style={styles.helpTooltipText}>
          📧 Questions or feedback? <a 
            href="mailto:rtvoiceagent@microsoft.com?subject=ARTAgent Feedback"
            style={{
              color: '#3b82f6',
              textDecoration: 'underline'
            }}
            onClick={(e) => e.stopPropagation()}
          >
            Contact the team
          </a>
        </div>
        {isClicked && (
          <div style={{
            textAlign: 'center',
            marginTop: '8px',
            fontSize: '10px',
            color: '#64748b',
            fontStyle: 'italic'
          }}>
            Click ? again to close
          </div>
        )}
      </div>
    </div>
  );
};

/* ------------------------------------------------------------------ *
 *  INDUSTRY TAG COMPONENT
 * ------------------------------------------------------------------ */
const IndustryTag = () => {
  // Determine branch-based industry tag and palette
  const getIndustryPresentation = () => {
    const currentBranch = import.meta.env.VITE_BRANCH_NAME || 'finance';

    if (currentBranch === 'main') {
      return {
        label: 'Insurance Edition',
        palette: {
          background: 'linear-gradient(135deg, #0ea5e9, #10b981)',
          color: '#0f172a',
          borderColor: 'rgba(14,165,233,0.35)',
          shadow: '0 12px 28px rgba(14,165,233,0.24)',
          textShadow: '0 1px 2px rgba(15,23,42,0.3)',
        },
      };
    }

    if (currentBranch.includes('finance') || currentBranch.includes('capitalmarkets')) {
      return {
        label: 'Banking Edition',
        palette: {
          background: 'linear-gradient(135deg, #4338ca, #6366f1)',
          color: '#f8fafc',
          borderColor: 'rgba(99,102,241,0.45)',
          shadow: '0 12px 28px rgba(99,102,241,0.25)',
          textShadow: '0 1px 2px rgba(30,64,175,0.4)',
        },
      };
    }

    return {
      label: 'Banking Edition',
      palette: {
        background: 'linear-gradient(135deg, #4338ca, #6366f1)',
        color: '#f8fafc',
        borderColor: 'rgba(99,102,241,0.45)',
        shadow: '0 12px 28px rgba(99,102,241,0.25)',
        textShadow: '0 1px 2px rgba(30,64,175,0.4)',
      },
    };
  };

  const { label, palette } = getIndustryPresentation();

  return (
    <div style={styles.topTabsContainer}>
      <div style={styles.topTab(true, palette)}>
        {label}
      </div>
    </div>
  );
};

/* ------------------------------------------------------------------ *
 *  ENHANCED BACKEND INDICATOR WITH HEALTH MONITORING & AGENT CONFIG
 * ------------------------------------------------------------------ */
const BackendIndicator = ({ url, onConfigureClick, onStatusChange }) => {
  const [isConnected, setIsConnected] = useState(null);
  const [displayUrl, setDisplayUrl] = useState(url);
  const [readinessData, setReadinessData] = useState(null);
  const [agentsData, setAgentsData] = useState(null);
  const [error, setError] = useState(null);
  const [isExpanded, setIsExpanded] = useState(false);
  const [isClickedOpen, setIsClickedOpen] = useState(false);
  const [showComponentDetails, setShowComponentDetails] = useState(false);
  const [screenWidth, setScreenWidth] = useState(window.innerWidth);
  const [showAgentConfig, setShowAgentConfig] = useState(false);
  const [selectedAgent, setSelectedAgent] = useState(null);
  // const [configChanges, setConfigChanges] = useState({});
  // const [updateStatus, setUpdateStatus] = useState({});
  // const [showStatistics, setShowStatistics] = useState(false);
  const [showAcsHover, setShowAcsHover] = useState(false);
  const [acsTooltipPos, setAcsTooltipPos] = useState(null);
  const [revealApiUrl, setRevealApiUrl] = useState(false);
  const summaryRef = useRef(null);

  // Track screen width for responsive positioning
  useEffect(() => {
    const handleResize = () => setScreenWidth(window.innerWidth);
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // Check readiness endpoint
  const checkReadiness = async () => {
    try {
      const response = await fetch(`${url}/api/v1/readiness`);

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const data = await response.json();
      
      // Validate expected structure
      if (data.status && data.checks && Array.isArray(data.checks)) {
        setReadinessData(data);
        setIsConnected(data.status !== "unhealthy");
        setError(null);
      } else {
        throw new Error("Invalid response structure");
      }
    } catch (err) {
      logger.error("Readiness check failed:", err);
      setIsConnected(false);
      setError(err.message);
      setReadinessData(null);
    }
  };

  // Check agents endpoint
  const checkAgents = async () => {
    try {
      const response = await fetch(`${url}/api/v1/agents`);

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const data = await response.json();
      
      if (data.status === "success" && data.agents && Array.isArray(data.agents)) {
        setAgentsData(data);
      } else {
        throw new Error("Invalid agents response structure");
      }
    } catch (err) {
      logger.error("Agents check failed:", err);
      setAgentsData(null);
    }
  };

  // Check health endpoint for session statistics
  const [healthData, setHealthData] = useState(null);
  const checkHealth = async () => {
    try {
      const response = await fetch(`${url}/api/v1/health`);

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const data = await response.json();
      
      if (data.status) {
        setHealthData(data);
      } else {
        throw new Error("Invalid health response structure");
      }
    } catch (err) {
      logger.error("Health check failed:", err);
      setHealthData(null);
    }
  };

  // // Update agent configuration
  // const updateAgentConfig = async (agentName, config) => {
  //   try {
  //     setUpdateStatus({...updateStatus, [agentName]: 'updating'});
      
  //     const response = await fetch(`${url}/api/v1/agents/${agentName}`, {
  //       method: 'PUT',
  //       headers: {
  //         'Content-Type': 'application/json',
  //       },
  //       body: JSON.stringify(config),
  //     });

  //     if (!response.ok) {
  //       throw new Error(`HTTP ${response.status}`);
  //     }

  //     const data = await response.json();
      
  //     setUpdateStatus({...updateStatus, [agentName]: 'success'});
      
  //     // Refresh agents data
  //     checkAgents();
      
  //     // Clear success status after 3 seconds
  //     setTimeout(() => {
  //       setUpdateStatus(prev => {
  //         const newStatus = {...prev};
  //         delete newStatus[agentName];
  //         return newStatus;
  //       });
  //     }, 3000);
      
  //     return data;
  //   } catch (err) {
  //     logger.error("Agent config update failed:", err);
  //     setUpdateStatus({...updateStatus, [agentName]: 'error'});
      
  //     // Clear error status after 5 seconds
  //     setTimeout(() => {
  //       setUpdateStatus(prev => {
  //         const newStatus = {...prev};
  //         delete newStatus[agentName];
  //         return newStatus;
  //       });
  //     }, 5000);
      
  //     throw err;
  //   }
  // };

  useEffect(() => {
    // Parse and format the URL for display
    try {
      const urlObj = new URL(url);
      const host = urlObj.hostname;
      const protocol = urlObj.protocol.replace(':', '');
      
      // Shorten Azure URLs
      if (host.includes('.azurecontainerapps.io')) {
        const appName = host.split('.')[0];
        setDisplayUrl(`${protocol}://${appName}.azure...`);
      } else if (host === 'localhost') {
        setDisplayUrl(`${protocol}://localhost:${urlObj.port || '8000'}`);
      } else {
        setDisplayUrl(`${protocol}://${host}`);
      }
    } catch (e) {
      setDisplayUrl(url);
    }

    // Initial check
    checkReadiness();
    checkAgents();
    checkHealth();

    // Set up periodic checks every 30 seconds
    const interval = setInterval(() => {
      checkReadiness();
      checkAgents();
      checkHealth();
    }, 30000);

    return () => clearInterval(interval);
  }, [url]);

  // Get overall health status
  const readinessChecks = readinessData?.checks ?? [];
  const unhealthyChecks = readinessChecks.filter((c) => c.status === "unhealthy");
  const degradedChecks = readinessChecks.filter((c) => c.status === "degraded");
  const acsOnlyIssue =
    unhealthyChecks.length > 0 &&
    degradedChecks.length === 0 &&
    unhealthyChecks.every((c) => c.component === "acs_caller") &&
    readinessChecks
      .filter((c) => c.component !== "acs_caller")
      .every((c) => c.status === "healthy");

  const getOverallStatus = () => {
    if (!readinessData?.checks) {
      if (isConnected === null) return "checking";
      if (!isConnected) return "unhealthy";
      return "checking";
    }

    if (acsOnlyIssue) return "degraded";
    if (unhealthyChecks.length > 0) return "unhealthy";
    if (degradedChecks.length > 0) return "degraded";
    return "healthy";
  };

  const overallStatus = getOverallStatus();
  const statusColor = overallStatus === "healthy" ? "#10b981" : 
                     overallStatus === "degraded" ? "#f59e0b" :
                     overallStatus === "unhealthy" ? "#ef4444" : "#6b7280";

  useEffect(() => {
    if (typeof onStatusChange === "function") {
      onStatusChange({ status: overallStatus, acsOnlyIssue });
    }
  }, [overallStatus, acsOnlyIssue, onStatusChange]);

  useEffect(() => {
    if (!acsOnlyIssue && showAcsHover) {
      setShowAcsHover(false);
      setAcsTooltipPos(null);
    }
  }, [acsOnlyIssue, showAcsHover]);

  // Dynamic sizing based on screen width - keep in bottom left but adjust size to maintain separation
  const getResponsiveStyle = () => {
    const baseStyle = {
      ...styles.backendIndicator,
      transition: "all 0.3s ease",
    };

    // Calculate available space for the status box to avoid ARTAgent overlap
    const containerWidth = 768;
    const containerLeftEdge = (screenWidth / 2) - (containerWidth / 2);
    const availableWidth = containerLeftEdge - 40 - 20; // 40px margin from container, 20px from screen edge
    
    // Adjust size based on available space
    if (availableWidth < 200) {
      // Very narrow - compact size
      return {
        ...baseStyle,
        minWidth: "150px",
        maxWidth: "180px",
        padding: !shouldBeExpanded && overallStatus === "healthy" ? "8px 12px" : "10px 14px",
        fontSize: "10px",
      };
    } else if (availableWidth < 280) {
      // Medium space - reduced size
      return {
        ...baseStyle,
        minWidth: "180px",
        maxWidth: "250px",
        padding: !shouldBeExpanded && overallStatus === "healthy" ? "10px 14px" : "12px 16px",
      };
    } else {
      // Plenty of space - full size
      return {
        ...baseStyle,
        minWidth: !shouldBeExpanded && overallStatus === "healthy" ? "200px" : "280px",
        maxWidth: "320px",
        padding: !shouldBeExpanded && overallStatus === "healthy" ? "10px 14px" : "12px 16px",
      };
    }
  };

  // Component icon mapping with descriptions
  const componentIcons = {
    redis: "💾",
    azure_openai: "🧠",
    speech_services: "🎙️",
    acs_caller: "📞",
    rt_agents: "🤖"
  };

  // Component descriptions
  const componentDescriptions = {
    redis: "Redis Cache - Session & state management",
    azure_openai: "Azure OpenAI - GPT models & embeddings",
    speech_services: "Speech Services - STT/TTS processing",
    acs_caller: "Communication Services - Voice calling",
    rt_agents: "RT Agents - Real-time Voice Agents"
  };

  const handleBackendClick = (e) => {
    // Don't trigger if clicking on buttons
    if (e.target.closest('div')?.style?.cursor === 'pointer' && e.target !== e.currentTarget) {
      return;
    }
    e.preventDefault();
    e.stopPropagation();
    setIsClickedOpen(!isClickedOpen);
    if (!isClickedOpen) {
      setIsExpanded(true);
    }
  };

  const handleMouseEnter = () => {
    if (!isClickedOpen) {
      setIsExpanded(true);
    }
  };

  const handleMouseLeave = () => {
    if (!isClickedOpen) {
      setIsExpanded(false);
    }
  };

  // Determine if should be expanded (either clicked open or hovered)
  const shouldBeExpanded = isClickedOpen || isExpanded;

  const maskApiUrl = (value) => {
    if (!value) {
      return "";
    }
    try {
      const parsed = new URL(value);
      const protocol = parsed.protocol.replace(":", "");
      const hostParts = parsed.hostname.split(".");
      const primary = hostParts.shift() || "";
      const maskSegment = (segment) => {
        if (segment.length <= 3) {
          return "•".repeat(segment.length || 3);
        }
        const prefix = segment.slice(0, 2);
        const suffix = segment.slice(-2);
        const middle = "•".repeat(Math.max(segment.length - 4, 2));
        return `${prefix}${middle}${suffix}`;
      };
      const maskedPrimary = maskSegment(primary);
      const maskedHost = hostParts.length > 0 ? `${maskedPrimary}.${hostParts.join(".")}` : maskedPrimary;
      const path = parsed.pathname && parsed.pathname !== "/" ? "/…" : "/";
      return `${protocol}://${maskedHost}${path}`;
    } catch {
      const safe = String(value);
      if (safe.length <= 4) {
        return "•".repeat(safe.length);
      }
      return `${safe.slice(0, 2)}${"•".repeat(Math.max(safe.length - 4, 2))}${safe.slice(-2)}`;
    }
  };

  const displayedApiUrl = revealApiUrl ? url : maskApiUrl(url);
  const maskToggleStyle = revealApiUrl
    ? { ...styles.maskToggleButton, ...styles.maskToggleButtonActive }
    : styles.maskToggleButton;

  return (
    <div 
      style={getResponsiveStyle()} 
      title={isClickedOpen ? `Click to close backend status` : `Click to pin open backend status`}
      onClick={handleBackendClick}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      <div style={styles.backendHeader}>
        <div style={{
          ...styles.backendStatus,
          backgroundColor: statusColor,
        }}></div>
        <span style={styles.backendLabel}>Backend Status</span>
        <BackendHelpButton />
        <span style={{
          ...styles.expandIcon,
          transform: shouldBeExpanded ? "rotate(180deg)" : "rotate(0deg)",
          color: isClickedOpen ? "#3b82f6" : styles.expandIcon.color,
          fontWeight: isClickedOpen ? "600" : "normal",
        }}>▼</span>
      </div>
      
      {/* Compact URL display when collapsed */}
      {!shouldBeExpanded && (
        <div style={{
          ...styles.backendUrl,
          fontSize: "9px",
          opacity: 0.7,
          marginTop: "2px",
        }}>
          {displayedApiUrl}
        </div>
      )}

      {/* Only show component health when expanded or when there's an issue */}
      {(shouldBeExpanded || overallStatus !== "healthy") && (
        <>
          {/* Expanded information display */}
          {shouldBeExpanded && (
            <>
              
              {/* API Entry Point Info */}
              <div style={{
                padding: "8px 10px",
                backgroundColor: "#f8fafc",
                borderRadius: "8px",
                marginBottom: "10px",
                fontSize: "10px",
                border: "1px solid #e2e8f0",
              }}>
                <div style={{
                  fontWeight: "600",
                  color: "#475569",
                  marginBottom: "4px",
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                }}>
                  🌐 Backend API Entry Point
                </div>
                <div style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: "8px",
                  marginBottom: "6px",
                }}>
                  <div style={{
                    color: "#64748b",
                    fontSize: "9px",
                    fontFamily: "monospace",
                    padding: "3px 6px",
                    backgroundColor: "white",
                    borderRadius: "4px",
                    border: "1px solid #f1f5f9",
                    flex: "1 1 auto",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}>
                    {displayedApiUrl}
                  </div>
                  <button
                    type="button"
                    style={maskToggleStyle}
                    onClick={(event) => {
                      event.preventDefault();
                      event.stopPropagation();
                      setRevealApiUrl((prev) => !prev);
                    }}
                  >
                    {revealApiUrl ? "Mask" : "Reveal"}
                  </button>
                </div>
                <div style={{
                  color: "#64748b",
                  fontSize: "9px",
                  lineHeight: "1.3",
                }}>
                  Main FastAPI server handling WebSocket connections, voice processing, and AI agent orchestration
                </div>
              </div>

              {/* System status summary */}
              {readinessData && (
                <div 
                  style={{
                    padding: "6px 8px",
                    backgroundColor: overallStatus === "healthy" ? "#f0fdf4" : 
                                   overallStatus === "degraded" ? "#fffbeb" : "#fef2f2",
                    borderRadius: "6px",
                    marginBottom: "8px",
                    fontSize: "10px",
                    border: `1px solid ${overallStatus === "healthy" ? "#bbf7d0" : 
                                        overallStatus === "degraded" ? "#fed7aa" : "#fecaca"}`,
                    cursor: "pointer",
                    transition: "all 0.2s ease",
                  }}
                  ref={summaryRef}
                  onClick={(e) => {
                    e.stopPropagation();
                    setShowComponentDetails(!showComponentDetails);
                  }}
                  onMouseEnter={() => {
                    if (summaryRef.current) {
                      const rect = summaryRef.current.getBoundingClientRect();
                      setAcsTooltipPos({
                        top: rect.bottom + 8,
                        left: rect.left + rect.width / 2,
                      });
                    }
                    setShowAcsHover(true);
                  }}
                  onMouseLeave={() => {
                    setShowAcsHover(false);
                    setAcsTooltipPos(null);
                  }}
                  title="Click to show/hide component details"
                >
                  <div style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                  }}>
                    <div>
                      <div style={{
                        fontWeight: "600",
                        color: overallStatus === "healthy" ? "#166534" : 
                              overallStatus === "degraded" ? "#92400e" : "#dc2626",
                        marginBottom: "2px",
                      }}>
                        System Status: {overallStatus.charAt(0).toUpperCase() + overallStatus.slice(1)}
                      </div>
                      <div style={{
                        color: "#64748b",
                        fontSize: "9px",
                      }}>
                        {readinessData.checks.length} components monitored • 
                        Last check: {new Date().toLocaleTimeString()}
                      </div>
                    </div>
                    <div style={{
                      fontSize: "12px",
                      color: "#64748b",
                      transform: showComponentDetails ? "rotate(180deg)" : "rotate(0deg)",
                      transition: "transform 0.2s ease",
                    }}>
                      ▼
                    </div>
                  </div>
                </div>
              )}

              {acsOnlyIssue && showAcsHover && acsTooltipPos && (
                <div
                  style={{
                    ...styles.acsHoverDialog,
                    top: acsTooltipPos.top,
                    left: acsTooltipPos.left,
                  }}
                >
                  ACS outbound calling is currently unavailable, but the Conversation API continues to stream microphone audio from this device to the backend.
                </div>
              )}
            </>
          )}

          {error ? (
            <div style={styles.errorMessage}>
              ⚠️ Connection failed: {error}
            </div>
          ) : readinessData?.checks && showComponentDetails ? (
            <>
              <div style={styles.componentGrid}>
                {readinessData.checks.map((check, idx) => (
                  <div 
                    key={idx} 
                    style={{
                      ...styles.componentItem,
                      flexDirection: "column",
                      alignItems: "flex-start",
                      padding: "6px 8px", // Reduced from 12px 16px to half
                    }}
                    title={check.details || `${check.component} status: ${check.status}`}
                  >
                    <div style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "5px", // Reduced from 10px to half
                      width: "100%",
                    }}>
                      <span>{componentIcons[check.component] || "•"}</span>
                      <div style={styles.componentDot(check.status)}></div>
                      <span style={styles.componentName}>
                        {check.component.replace(/_/g, ' ')}
                      </span>
                      {check.check_time_ms !== undefined && (
                        <span style={styles.responseTime}>
                          {check.check_time_ms.toFixed(0)}ms
                        </span>
                      )}
                    </div>
                    
                    {/* Component description when expanded */}
                    {shouldBeExpanded && (
                      <div style={{
                        fontSize: "8px", // Reduced from 10px
                        color: "#64748b",
                        marginTop: "3px", // Reduced from 6px to half
                        lineHeight: "1.3", // Reduced line height
                        fontStyle: "italic",
                        paddingLeft: "9px", // Reduced from 18px to half
                      }}>
                        {componentDescriptions[check.component] || "Backend service component"}
                      </div>
                    )}
                    
                    {/* Status details removed per user request */}
                  </div>
                ))}
              </div>
              
              {/* Component details section removed per user request */}
            </>
          ) : null}
          
          {readinessData?.response_time_ms && shouldBeExpanded && (
            <div style={{
              fontSize: "9px",
              color: "#94a3b8",
              marginTop: "8px",
              paddingTop: "8px",
              borderTop: "1px solid #f1f5f9",
              textAlign: "center",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}>
              <span>Health check latency: {readinessData.response_time_ms.toFixed(0)}ms</span>
              <span title="Auto-refreshes every 30 seconds">🔄</span>
            </div>
          )}

          {/* Session Statistics Section */}
          {shouldBeExpanded && healthData && (
            <div style={{
              marginTop: "8px",
              paddingTop: "8px",
              borderTop: "1px solid #f1f5f9",
            }}>
              <div style={{
                fontSize: "10px",
                fontWeight: "600",
                color: "#374151",
                marginBottom: "6px",
                display: "flex",
                alignItems: "center",
                gap: "4px",
              }}>
                📊 Session Statistics
              </div>
              
              <div style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: "8px",
                fontSize: "9px",
              }}>
                {/* Active Sessions */}
                <div style={{
                  background: "#f8fafc",
                  border: "1px solid #e2e8f0",
                  borderRadius: "6px",
                  padding: "6px 8px",
                  textAlign: "center",
                }}>
                  <div style={{
                    fontWeight: "600",
                    color: "#10b981",
                    fontSize: "12px",
                  }}>
                    {healthData.active_sessions || 0}
                  </div>
                  <div style={{
                    color: "#64748b",
                    fontSize: "8px",
                  }}>
                    Active Sessions
                  </div>
                </div>

                {/* Session Metrics */}
                {healthData.session_metrics && (
                  <div style={{
                    background: "#f8fafc",
                    border: "1px solid #e2e8f0",
                    borderRadius: "6px",
                    padding: "6px 8px",
                    textAlign: "center",
                  }}>
                    <div style={{
                      fontWeight: "600",
                      color: "#3b82f6",
                      fontSize: "12px",
                    }}>
                      {healthData.session_metrics.connected || 0}
                    </div>
                    <div style={{
                      color: "#64748b",
                      fontSize: "8px",
                    }}>
                      Total Connected
                    </div>
                  </div>
                )}
                
                {/* Disconnected Sessions */}
                {healthData.session_metrics?.disconnected !== undefined && (
                  <div style={{
                    background: "#f8fafc",
                    border: "1px solid #e2e8f0",
                    borderRadius: "6px",
                    padding: "6px 8px",
                    textAlign: "center",
                    gridColumn: healthData.session_metrics ? "1 / -1" : "auto",
                  }}>
                    <div style={{
                      fontWeight: "600",
                      color: "#6b7280",
                      fontSize: "12px",
                    }}>
                      {healthData.session_metrics.disconnected}
                    </div>
                    <div style={{
                      color: "#64748b",
                      fontSize: "8px",
                    }}>
                      Disconnected
                    </div>
                  </div>
                )}
              </div>
              
              {/* Last updated */}
              <div style={{
                fontSize: "8px",
                color: "#94a3b8",
                marginTop: "6px",
                textAlign: "center",
                fontStyle: "italic",
              }}>
                Updated: {new Date(healthData.timestamp * 1000).toLocaleTimeString()}
              </div>
            </div>
          )}

          {/* Agents Configuration Section */}
          {shouldBeExpanded && agentsData?.agents && (
            <div style={{
              marginTop: "10px",
              paddingTop: "10px",
              borderTop: "2px solid #e2e8f0",
            }}>
              {/* Agents Header */}
              <div style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: "8px",
                padding: "6px 8px",
                backgroundColor: "#f1f5f9",
                borderRadius: "6px",
              }}>
                <div style={{
                  fontWeight: "600",
                  color: "#475569",
                  fontSize: "11px",
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                }}>
                  🤖 RT Agents ({agentsData.agents.length})
                </div>
              </div>

              {/* Agents List */}
              <div style={{
                display: "grid",
                gridTemplateColumns: "1fr",
                gap: "6px",
                fontSize: "10px",
              }}>
                {agentsData.agents.map((agent, idx) => (
                  <div 
                    key={idx} 
                    style={{
                      padding: "8px 10px",
                      border: "1px solid #e2e8f0",
                      borderRadius: "6px",
                      backgroundColor: "white",
                      cursor: showAgentConfig ? "pointer" : "default",
                      transition: "all 0.2s ease",
                      ...(showAgentConfig && selectedAgent === agent.name ? {
                        borderColor: "#3b82f6",
                        backgroundColor: "#f0f9ff",
                      } : {}),
                    }}
                    onClick={() => showAgentConfig && setSelectedAgent(selectedAgent === agent.name ? null : agent.name)}
                    title={agent.description || `${agent.name} - Real-time voice agent`}
                  >
                    <div style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      marginBottom: "4px",
                    }}>
                      <div style={{
                        fontWeight: "600",
                        color: "#374151",
                        display: "flex",
                        alignItems: "center",
                        gap: "6px",
                      }}>
                        <span style={{
                          width: "8px",
                          height: "8px",
                          borderRadius: "50%",
                          backgroundColor: agent.status === "loaded" ? "#10b981" : "#ef4444",
                          display: "inline-block",
                        }}></span>
                        {agent.name}
                      </div>
                      <div style={{
                        fontSize: "9px",
                        color: "#64748b",
                        display: "flex",
                        alignItems: "center",
                        gap: "6px",
                      }}>
                        {agent.model?.deployment_id && (
                          <span title={`Model: ${agent.model.deployment_id}`}>
                            💭 {agent.model.deployment_id.replace('gpt-', '')}
                          </span>
                        )}
                        {agent.voice?.current_voice && (
                          <span title={`Voice: ${agent.voice.current_voice}`}>
                            🔊 {agent.voice.current_voice.split('-').pop()?.replace('Neural', '')}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>

              {/* Agents Info Footer */}
              <div style={{
                fontSize: "8px",
                color: "#94a3b8",
                marginTop: "8px",
                textAlign: "center",
                fontStyle: "italic",
              }}>
                Runtime configuration • Changes require restart for persistence • Contact rtvoiceagent@microsoft.com
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
};

/* ------------------------------------------------------------------ *
 *  WAVEFORM COMPONENT - SIMPLE & SMOOTH
 * ------------------------------------------------------------------ */
const WaveformVisualization = React.memo(({ activeSpeaker, audioLevelRef, outputAudioLevelRef, bargeInActive = false }) => {
  const [waveRenderState, setWaveRenderState] = useState({ amplitude: 0, offset: 0 });
  const [speakerState, setSpeakerState] = useState({ user: false, assistant: false });
  const animationRef = useRef();
  const combinedLevelRef = useRef(0);
  const latestLevelsRef = useRef({ input: 0, output: 0 });
  const levelTimestampRef = useRef(performance.now());
  const lastVisualUpdateRef = useRef(performance.now());
  const waveRenderRef = useRef({ amplitude: 0, offset: 0 });
  const USER_THRESHOLD = 0.015;
  const ASSISTANT_THRESHOLD = 0.006;
  const userDisplayActive = speakerState.user || activeSpeaker === "User";
  const assistantDisplayActive = speakerState.assistant || activeSpeaker === "Assistant";
  const bothDisplayActive = userDisplayActive && assistantDisplayActive;

  useEffect(() => {
    let rafId;
    const updateLevels = () => {
      const now = performance.now();
      const deltaMs = now - (levelTimestampRef.current || now);
      levelTimestampRef.current = now;
      const inputLevel = audioLevelRef?.current ?? 0;
      const outputLevel = outputAudioLevelRef?.current ?? 0;
      latestLevelsRef.current = { input: inputLevel, output: outputLevel };

      const target = Math.max(inputLevel, outputLevel);
      const previous = combinedLevelRef.current;
      const next = smoothValue(previous, target, deltaMs, 85, 260);
      combinedLevelRef.current = next < 0.004 ? 0 : next;

      setSpeakerState((prev) => {
        const nextUser = inputLevel > USER_THRESHOLD
          ? true
          : inputLevel < USER_THRESHOLD * 0.6
            ? false
            : prev.user;
        const nextAssistant = outputLevel > ASSISTANT_THRESHOLD
          ? true
          : outputLevel < ASSISTANT_THRESHOLD * 0.6
            ? false
            : prev.assistant;
        if (prev.user === nextUser && prev.assistant === nextAssistant) {
          return prev;
        }
        return { user: nextUser, assistant: nextAssistant };
      });

      rafId = requestAnimationFrame(updateLevels);
    };
    rafId = requestAnimationFrame(updateLevels);
    return () => {
      if (rafId) {
        cancelAnimationFrame(rafId);
      }
    };
  }, [audioLevelRef, outputAudioLevelRef]);

  useEffect(() => {
    let lastTs = performance.now();

    const animate = () => {
      const now = performance.now();
      const delta = now - lastTs;
      lastTs = now;

      const activity = combinedLevelRef.current;
      const normalized = Math.min(1, Math.pow(activity * 1.1, 0.88));
      const targetAmplitude = normalized < 0.015
        ? 0
        : (36 * normalized) + (18 * normalized * normalized) + (bargeInActive ? 6 : 0);
      const prevAmplitude = waveRenderRef.current.amplitude;
      const easedAmplitude = smoothValue(prevAmplitude, targetAmplitude, delta, 110, 260);
      const finalAmplitude = easedAmplitude < 0.35 ? 0 : easedAmplitude;

      const prevOffset = waveRenderRef.current.offset;
      const waveSpeed = 0.38 + normalized * 2.1;
      const nextOffset = (prevOffset + waveSpeed * (delta / 16)) % 1000;

      const nowTs = now;
      const needsUpdate =
        Math.abs(finalAmplitude - prevAmplitude) > 0.35 ||
        Math.abs(nextOffset - prevOffset) > 0.9 ||
        nowTs - lastVisualUpdateRef.current > 48;

      if (needsUpdate) {
        const nextState = { amplitude: finalAmplitude, offset: nextOffset };
        waveRenderRef.current = nextState;
        lastVisualUpdateRef.current = nowTs;
        setWaveRenderState(nextState);
      }

      animationRef.current = requestAnimationFrame(animate);
    };

    animationRef.current = requestAnimationFrame(animate);
    return () => {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
    };
  }, [bargeInActive]);
  
  const generateWavePath = () => {
    const width = 750;
    const height = 100;
    const centerY = height / 2;
    const frequency = 0.02;
    const points = 160;

    let path = `M 0 ${centerY}`;

    for (let i = 0; i <= points; i++) {
      const x = (i / points) * width;
      const y = centerY + Math.sin((x * frequency + waveRenderState.offset * 0.1)) * waveRenderState.amplitude;
      path += ` L ${x} ${y}`;
    }
    
    return path;
  };

  // Secondary wave
  const generateSecondaryWave = () => {
    const width = 750;
    const height = 100;
    const centerY = height / 2;
    const frequency = 0.0245;
    const points = 140;

    let path = `M 0 ${centerY}`;

    for (let i = 0; i <= points; i++) {
      const x = (i / points) * width;
      const y = centerY + Math.sin((x * frequency + waveRenderState.offset * 0.12)) * (waveRenderState.amplitude * 0.6);
      path += ` L ${x} ${y}`;
    }
    
    return path;
  };

  // Wave rendering
  const generateMultipleWaves = () => {
    const waves = [];
    
    let baseColor;
    let opacity = 0.85;
    if (bothDisplayActive) {
      baseColor = "url(#waveGradientBarge)";
    } else if (userDisplayActive) {
      baseColor = "#ef4444";
    } else if (assistantDisplayActive) {
      baseColor = "#67d8ef";
    } else {
      baseColor = "#3b82f6";
      opacity = 0.45;
    }

    if (waveRenderState.amplitude <= 0.8) {
      baseColor = "#cbd5e1";
      waves.push(
        <line
          key="wave-idle"
          x1="0"
          y1="40"
          x2="750"
          y2="40"
          stroke={baseColor}
          strokeWidth="2"
          strokeLinecap="round"
          opacity={0.75}
        />
      );
      return waves;
    }

    waves.push(
      <path
        key="wave1"
        d={generateWavePath()}
        stroke={baseColor}
        strokeWidth={userDisplayActive || assistantDisplayActive ? "3" : "2"}
        fill="none"
        opacity={opacity}
        strokeLinecap="round"
      />
    );

    waves.push(
      <path
        key="wave2"
        d={generateSecondaryWave()}
        stroke={baseColor}
        strokeWidth={userDisplayActive || assistantDisplayActive ? "2" : "1.5"}
        fill="none"
        opacity={opacity * 0.5}
        strokeLinecap="round"
      />
    );
    
    return waves;
  };
  
  const audioLevel = latestLevelsRef.current.input;
  const outputAudioLevel = latestLevelsRef.current.output;

  return (
    <div style={styles.waveformContainer}>
      <svg style={styles.waveformSvg} viewBox="0 0 750 80" preserveAspectRatio="xMidYMid meet">
        <defs>
          <linearGradient id="waveGradientBarge" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="#ef4444" />
            <stop offset="50%" stopColor="#8b5cf6" />
            <stop offset="100%" stopColor="#67d8ef" />
          </linearGradient>
        </defs>
        {generateMultipleWaves()}
      </svg>
      
      {/* Audio level indicators for debugging */}
      {window.location.hostname === 'localhost' && (
        <div style={{
          position: 'absolute',
          bottom: '-25px',
          left: '50%',
          transform: 'translateX(-50%)',
          fontSize: '10px',
          color: '#666',
          whiteSpace: 'nowrap'
        }}>
          Input: {(audioLevel * 100).toFixed(1)}% | Output: {(outputAudioLevel * 100).toFixed(1)}% | Amp: {waveRenderState.amplitude.toFixed(1)} | Speaker: {bothDisplayActive ? 'Barge-In' : (userDisplayActive ? 'User' : assistantDisplayActive ? 'Assistant' : (activeSpeaker || 'Idle'))}
        </div>
      )}
    </div>
  );
});

/* ------------------------------------------------------------------ *
 *  CONVERSATION CONTROLS (Reset, Mute, Mic, Call)
 * ------------------------------------------------------------------ */
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
            aria-label={recording ? "Stop microphone" : "Start microphone"}
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
              <MicOffRoundedIcon fontSize="medium" />
            ) : (
              <MicRoundedIcon fontSize="medium" />
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
              {recording ? "Stop recording your voice" : "Start voice conversation"}
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
              <PhoneDisabledRoundedIcon fontSize="medium" />
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
              {callActive ? "Hang up the phone call" : "Make a phone call"}
            </div>
          )}
        </div>
      </div>

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

/* ------------------------------------------------------------------ *
 *  CHAT BUBBLE
 * ------------------------------------------------------------------ */
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
    return (
      <Box sx={{ width: "100%", display: "flex", justifyContent: "center", px: 1, py: 0.5 }}>
        <Paper
          elevation={0}
          sx={{
            display: "flex",
            alignItems: "center",
            gap: 1,
            px: 1.5,
            py: 0.75,
            borderRadius: 2,
            border: "1px solid rgba(148, 163, 184, 0.25)",
            background: "rgba(15, 23, 42, 0.55)",
            width: "max-content",
            maxWidth: "90%",
            color: "#e2e8f0",
          }}
        >
          <Box
            sx={{
              width: 28,
              height: 28,
              borderRadius: "999px",
              background: "rgba(94, 234, 212, 0.18)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "#5eead4",
            }}
          >
            <InfoRoundedIcon fontSize="small" />
          </Box>
          <Box sx={{ display: "flex", flexDirection: "column", gap: 0.25 }}>
            <Typography
              variant="caption"
              sx={{
                fontWeight: 600,
                textTransform: "uppercase",
                letterSpacing: "0.08em",
                color: "#e2e8f0",
              }}
            >
              {eventLabel}
              {timestampLabel && (
                <Typography
                  component="span"
                  variant="caption"
                  sx={{ fontWeight: 400, opacity: 0.7, ml: 1 }}
                >
                  {timestampLabel}
                </Typography>
              )}
            </Typography>
            {detailText && (
              <Typography
                variant="body2"
                sx={{ color: "#cbd5f5", fontSize: "0.78rem", lineHeight: 1.4 }}
              >
                {detailText}
              </Typography>
            )}
          </Box>
        </Paper>
      </Box>
    );
  }

  const { speaker, text, isTool, streaming } = message;
  const isUser = speaker === "User";
  const isSpecialist = speaker?.includes("Specialist");
  const isAuthAgent = speaker === "Auth Agent";
  const isSystem = speaker === "System" && !isTool;
  
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
    const ToneIcon = tone.icon;
    const timestampLabel = formatStatusTimestamp(message.timestamp);
    const lines = (text || "").split("\n").filter(Boolean);
    const surfaceColor = tone.surface ?? tone.background ?? "rgba(15,23,42,0.04)";
    const borderColor = tone.borderColor ?? (tone.border ? tone.border.replace(/^1px\s+solid\s+/u, "") : "rgba(148,163,184,0.28)");
    const iconBackground = tone.iconBackground ?? "rgba(148,163,184,0.25)";

    return (
      <Box sx={{ width: "100%", display: "flex", justifyContent: "center", px: 1, py: 0.75 }}>
        <Paper
          elevation={0}
          sx={{
            display: "flex",
            alignItems: "flex-start",
            gap: 1.25,
            px: 1.75,
            py: 1,
            borderRadius: 2.5,
            border: `1px solid ${borderColor}`,
            background: surfaceColor,
            color: tone.textColor,
            backdropFilter: "blur(12px)",
            width: "max-content",
            maxWidth: "88%",
            boxShadow: "0 10px 24px rgba(15,23,42,0.08)",
          }}
        >
          <Box
            sx={{
              width: 28,
              height: 28,
              borderRadius: "50%",
              background: iconBackground,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: tone.accent,
              flexShrink: 0,
            }}
          >
            <ToneIcon sx={{ fontSize: 18 }} />
          </Box>
          <Box sx={{ display: "flex", flexDirection: "column", gap: 0.5, minWidth: 0 }}>
            <Box sx={{ display: "flex", alignItems: "center", gap: 1, flexWrap: "wrap" }}>
              <Typography
                variant="caption"
                sx={{
                  textTransform: "uppercase",
                  letterSpacing: "0.1em",
                  fontWeight: 600,
                  color: tone.accent,
                }}
              >
                {toneLabel}
              </Typography>
              {timestampLabel && (
                <Typography
                  variant="caption"
                  sx={{
                    color: tone.captionColor,
                    fontFamily: 'Roboto Mono, ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
                    letterSpacing: "0.04em",
                  }}
                >
                  {timestampLabel}
                </Typography>
              )}
            </Box>
            <Typography
              variant="body2"
              sx={{
                whiteSpace: "pre-wrap",
                fontSize: "0.82rem",
                lineHeight: 1.45,
                color: tone.textColor,
                wordBreak: "break-word",
              }}
            >
              {lines.map((line, idx) => (
                <React.Fragment key={idx}>
                  {idx > 0 && <br />}
                  {line}
                </React.Fragment>
              ))}
            </Typography>
            {message.statusCaption && (
              <Typography
                variant="caption"
                sx={{ display: "block", color: tone.captionColor }}
              >
                {message.statusCaption}
              </Typography>
            )}
          </Box>
        </Paper>
      </Box>
    );
  }
  
  const bubbleStyle = isUser ? styles.userBubble : styles.assistantBubble;

  return (
    <div style={isUser ? styles.userMessage : styles.assistantMessage}>
      {/* Show agent name for specialist agents and auth agent */}
      {!isUser && (isSpecialist || isAuthAgent) && (
        <div style={styles.agentNameLabel}>
          {speaker}
        </div>
      )}
      <div style={bubbleStyle}>
        {text.split("\n").map((line, i) => (
          <div key={i}>{line}</div>
        ))}
        {streaming && <span style={{ opacity: 0.7 }}>▌</span>}
      </div>
    </div>
  );
};

// Main voice application component
function RealTimeVoiceApp() {
  
  // CSS animation for pulsing effect
  React.useEffect(() => {
    const style = document.createElement('style');
    style.textContent = `
      @keyframes pulse {
        0% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
        70% { box-shadow: 0 0 0 10px rgba(16, 185, 129, 0); }
        100% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
      }
    `;
    document.head.appendChild(style);
    
    return () => {
      document.head.removeChild(style);
    };
  }, []);

  // Component state
  const [messages, setMessages] = useState([]);
  const [log, setLog] = useState("");
  const [recording, setRecording] = useState(false);
  const [micMuted, setMicMuted] = useState(false);
  const [targetPhoneNumber, setTargetPhoneNumber] = useState("");
  const [callActive, setCallActive] = useState(false);
  const [activeSpeaker, setActiveSpeaker] = useState(null);
  const [showPhoneInput, setShowPhoneInput] = useState(false);
  const [showRealtimeModePanel, setShowRealtimeModePanel] = useState(false);
  const [pendingRealtimeStart, setPendingRealtimeStart] = useState(false);
  const [realtimePanelCoords, setRealtimePanelCoords] = useState({ top: 0, left: 0 });
  const [systemStatus, setSystemStatus] = useState({
    status: "checking",
    acsOnlyIssue: false,
  });
  const streamingModeOptions = AcsStreamingModeSelector.options ?? [];
  const realtimeStreamingModeOptions = RealtimeStreamingModeSelector.options ?? [];
  const allowedStreamModes = streamingModeOptions.map((option) => option.value);
  const fallbackStreamMode = allowedStreamModes.includes(STREAM_MODE_FALLBACK)
    ? STREAM_MODE_FALLBACK
    : allowedStreamModes[0] || STREAM_MODE_FALLBACK;
  const allowedRealtimeStreamModes = realtimeStreamingModeOptions.map((option) => option.value);
  const fallbackRealtimeStreamMode = allowedRealtimeStreamModes.includes(
    REALTIME_STREAM_MODE_FALLBACK,
  )
    ? REALTIME_STREAM_MODE_FALLBACK
    : allowedRealtimeStreamModes[0] || REALTIME_STREAM_MODE_FALLBACK;
  const [selectedStreamingMode, setSelectedStreamingMode] = useState(() => {
    const allowed = new Set(allowedStreamModes);
    if (typeof window !== 'undefined') {
      try {
        const stored = window.localStorage.getItem(STREAM_MODE_STORAGE_KEY);
        if (stored && allowed.has(stored)) {
          return stored;
        }
      } catch (err) {
        logger.warn('Failed to read stored streaming mode preference', err);
      }
    }
    const envMode = (import.meta.env.VITE_ACS_STREAMING_MODE || '').toLowerCase();
    if (envMode && allowed.has(envMode)) {
      return envMode;
    }
    return fallbackStreamMode;
  });
  const [selectedRealtimeStreamingMode, setSelectedRealtimeStreamingMode] = useState(() => {
    const allowed = new Set(allowedRealtimeStreamModes);
    if (typeof window !== 'undefined') {
      try {
        const stored = window.localStorage.getItem(REALTIME_STREAM_MODE_STORAGE_KEY);
        if (stored && allowed.has(stored)) {
          return stored;
        }
      } catch (err) {
        logger.warn('Failed to read stored realtime streaming mode preference', err);
      }
    }
    const envMode = (import.meta.env.VITE_REALTIME_STREAMING_MODE || '').toLowerCase();
    if (envMode && allowed.has(envMode)) {
      return envMode;
    }
    return fallbackRealtimeStreamMode;
  });
  const [sessionProfiles, setSessionProfiles] = useState({});
  // Profile menu state moved to ProfileButton component
  // Profile menu state moved to ProfileButton component
  const [sessionId, setSessionId] = useState(() => getOrCreateSessionId());
  const [currentCallId, setCurrentCallId] = useState(null);
  const [showTextInput, setShowTextInput] = useState(false);
  const [textInput, setTextInput] = useState("");

  const appendLog = useCallback(m => setLog(p => `${p}\n${new Date().toLocaleTimeString()} - ${m}`), []);

  const handleSendText = useCallback(() => {
    if (!textInput.trim()) return;
    
    if (socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
      // BARGE-IN: Stop audio playback before sending text
      
      // 1. Stop recording audio context (microphone)
      if (audioContextRef.current && !audioContextRef.current.state.match(/closed/)) {
        audioContextRef.current.suspend();
        appendLog("🛑 Recording interrupted by user text input");
      }
      
      // 2. Stop TTS playback audio context (speaker output)
      if (playbackAudioContextRef.current && playbackAudioContextRef.current.state === "running") {
        playbackAudioContextRef.current.suspend();
        appendLog("🛑 TTS playback interrupted by user text input");
      }
      
      // 3. Clear the audio playback queue
      if (pcmSinkRef.current) {
        pcmSinkRef.current.port.postMessage({ type: 'clear' });
      }
      
      // Send as raw text message
      socketRef.current.send(textInput.trim());
      
      // Optimistically add to chat
      setMessages(prev => [...prev, { speaker: "User", text: textInput.trim() }]);
      setTextInput("");
    } else {
      appendLog("⚠️ Cannot send text: WebSocket not connected");
    }
  }, [textInput, appendLog]);

  const appendSystemMessage = useCallback((text, options = {}) => {
    const timestamp = options.timestamp ?? new Date().toISOString();

    if (options.variant === "session_stop") {
      const dividerLabel =
        options.dividerLabel ?? `Session paused · ${formatStatusTimestamp(timestamp)}`;
      setMessages((prev) => [
        ...prev,
        {
          type: "divider",
          label: dividerLabel,
          timestamp,
        },
      ]);
      return;
    }

    const baseMessage = buildSystemMessage(text, { ...options, timestamp });
    const shouldInsertDivider = options.withDivider === true;
    const dividerLabel = shouldInsertDivider
      ? options.dividerLabel ?? `Call disconnected · ${formatStatusTimestamp(timestamp)}`
      : null;
    setMessages((prev) => [
      ...prev,
      baseMessage,
      ...(shouldInsertDivider
        ? [
            {
              type: "divider",
              label: dividerLabel,
              timestamp,
            },
          ]
        : []),
    ]);
  }, [setMessages]);
  const handleSystemStatus = useCallback((nextStatus) => {
    setSystemStatus((prev) =>
      prev.status === nextStatus.status && prev.acsOnlyIssue === nextStatus.acsOnlyIssue
        ? prev
        : nextStatus
    );
  }, []);

  const [showDemoForm, setShowDemoForm] = useState(false);
  const openDemoForm = useCallback(() => setShowDemoForm(true), [setShowDemoForm]);
  const closeDemoForm = useCallback(() => setShowDemoForm(false), [setShowDemoForm]);
  const [createProfileHovered, setCreateProfileHovered] = useState(false);
  const demoFormCloseTimeoutRef = useRef(null);
  const profileHighlightTimeoutRef = useRef(null);
  const [profileHighlight, setProfileHighlight] = useState(false);
  const [showProfilePanel, setShowProfilePanel] = useState(false);
  const lastProfileIdRef = useRef(null);
  const realtimePanelRef = useRef(null);
  const realtimePanelAnchorRef = useRef(null);
  const triggerProfileHighlight = useCallback(() => {
    setProfileHighlight(true);
    if (profileHighlightTimeoutRef.current) {
      clearTimeout(profileHighlightTimeoutRef.current);
    }
    profileHighlightTimeoutRef.current = window.setTimeout(() => {
      setProfileHighlight(false);
      profileHighlightTimeoutRef.current = null;
    }, 3500);
  }, []);
  const isCallDisabled =
    systemStatus.status === "degraded" && systemStatus.acsOnlyIssue;

  useEffect(() => {
    if (isCallDisabled) {
      setShowPhoneInput(false);
    }
  }, [isCallDisabled]);

  useEffect(() => {
    return () => {
      if (demoFormCloseTimeoutRef.current) {
        clearTimeout(demoFormCloseTimeoutRef.current);
        demoFormCloseTimeoutRef.current = null;
      }
      if (profileHighlightTimeoutRef.current) {
        clearTimeout(profileHighlightTimeoutRef.current);
        profileHighlightTimeoutRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }
    try {
      window.localStorage.setItem(
        STREAM_MODE_STORAGE_KEY,
        selectedStreamingMode,
      );
    } catch (err) {
      logger.warn('Failed to persist streaming mode preference', err);
    }
  }, [selectedStreamingMode]);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }
    try {
      window.localStorage.setItem(
        REALTIME_STREAM_MODE_STORAGE_KEY,
        selectedRealtimeStreamingMode,
      );
    } catch (err) {
      logger.warn('Failed to persist realtime streaming mode preference', err);
    }
  }, [selectedRealtimeStreamingMode]);

  useEffect(() => {
    if (!showPhoneInput) {
      return undefined;
    }

    const handleOutsideClick = (event) => {
      const panelNode = phonePanelRef.current;
      const buttonNode = phoneButtonRef.current;
      if (panelNode && panelNode.contains(event.target)) {
        return;
      }
      if (buttonNode && buttonNode.contains(event.target)) {
        return;
      }
      setShowPhoneInput(false);
    };

    document.addEventListener('mousedown', handleOutsideClick);
    return () => document.removeEventListener('mousedown', handleOutsideClick);
  }, [showPhoneInput]);

  useEffect(() => {
    if (!showRealtimeModePanel) {
      setPendingRealtimeStart(false);
      return undefined;
    }

    const handleRealtimeOutsideClick = (event) => {
      const panelNode = realtimePanelRef.current;
      if (panelNode && panelNode.contains(event.target)) {
        return;
      }
      setShowRealtimeModePanel(false);
    };

    document.addEventListener('mousedown', handleRealtimeOutsideClick);
    return () => document.removeEventListener('mousedown', handleRealtimeOutsideClick);
  }, [showRealtimeModePanel]);

  useEffect(() => {
    if (recording) {
      setShowRealtimeModePanel(false);
    }
  }, [recording]);

  useLayoutEffect(() => {
    if (!showRealtimeModePanel) {
      return undefined;
    }
    if (typeof window === 'undefined') {
      return undefined;
    }

    const updatePosition = () => {
      const anchorEl = micButtonRef.current || realtimePanelAnchorRef.current;
      const panelEl = realtimePanelRef.current;
      if (!anchorEl || !panelEl) {
        return;
      }
      const anchorRect = anchorEl.getBoundingClientRect();
      const panelRect = panelEl.getBoundingClientRect();
      let top = anchorRect.top - panelRect.height - PANEL_MARGIN;
      if (top < PANEL_MARGIN) {
        top = anchorRect.bottom + PANEL_MARGIN;
      }
      let left = anchorRect.left + anchorRect.width / 2 - panelRect.width / 2;
      const maxLeft = window.innerWidth - panelRect.width - PANEL_MARGIN;
      left = Math.min(
        Math.max(left, PANEL_MARGIN),
        Math.max(PANEL_MARGIN, maxLeft),
      );
      setRealtimePanelCoords({ top, left });
    };

    updatePosition();
    window.addEventListener('resize', updatePosition);
    window.addEventListener('scroll', updatePosition, true);
    return () => {
      window.removeEventListener('resize', updatePosition);
      window.removeEventListener('scroll', updatePosition, true);
    };
  }, [showRealtimeModePanel]);

  useEffect(() => {
    if (typeof document === 'undefined') {
      return;
    }
    if (!showDemoForm) {
      document.body.style.removeProperty('overflow');
      return;
    }
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previousOverflow || '';
    };
  }, [showDemoForm]);

  const handleStreamingModeChange = useCallback(
    (mode) => {
      if (!mode || mode === selectedStreamingMode) {
        return;
      }
      setSelectedStreamingMode(mode);
      logger.info(`🎚️ [FRONTEND] Streaming mode updated to ${mode}`);
    },
    [selectedStreamingMode],
  );

  const handleRealtimeStreamingModeChange = useCallback(
    (mode) => {
      if (!mode) {
        return;
      }
      if (mode !== selectedRealtimeStreamingMode) {
        setSelectedRealtimeStreamingMode(mode);
        logger.info(`🎚️ [FRONTEND] Realtime streaming mode updated to ${mode}`);
      }
      const shouldStart = pendingRealtimeStart && !recording;
      setPendingRealtimeStart(false);
      setShowRealtimeModePanel(false);
      if (shouldStart) {
        startRecognitionRef.current?.(mode);
      }
    },
    [pendingRealtimeStart, recording, selectedRealtimeStreamingMode],
  );

  const selectedStreamingModeLabel = AcsStreamingModeSelector.getLabel(
    selectedStreamingMode,
  );
  const selectedRealtimeStreamingModeLabel = RealtimeStreamingModeSelector.getLabel(
    selectedRealtimeStreamingMode,
  );
  const selectedRealtimeModeConfig = useMemo(() => {
    const match = realtimeStreamingModeOptions.find(
      (option) => option.value === selectedRealtimeStreamingMode,
    );
    return match?.config ?? null;
  }, [realtimeStreamingModeOptions, selectedRealtimeStreamingMode]);

  const updateToolMessage = useCallback(
    (toolName, transformer, fallbackMessage) => {
      setMessages((prev) => {
        const next = [...prev];
        let targetIndex = -1;

        for (let idx = next.length - 1; idx >= 0; idx -= 1) {
          const candidate = next[idx];
          if (candidate?.isTool && candidate.text?.includes(`tool ${toolName}`)) {
            targetIndex = idx;
            break;
          }
        }

        if (targetIndex === -1) {
          if (!fallbackMessage) {
            return prev;
          }
          const fallback =
            typeof fallbackMessage === "function"
              ? fallbackMessage()
              : fallbackMessage;
          return [...prev, fallback];
        }

        const current = next[targetIndex];
        const updated = transformer(current);
        if (!updated || updated === current) {
          return prev;
        }

        next[targetIndex] = updated;
        return next;
      });
    },
    [setMessages],
  );

  // Health monitoring (disabled)
  /*
  const { 
    healthStatus = { isHealthy: null, lastChecked: null, responseTime: null, error: null },
    readinessStatus = { status: null, timestamp: null, responseTime: null, checks: [], lastChecked: null, error: null },
    overallStatus = { isHealthy: false, hasWarnings: false, criticalErrors: [] },
    refresh = () => {} 
  } = useHealthMonitor({
    baseUrl: API_BASE_URL,
    healthInterval: 30000,
    readinessInterval: 15000,
    enableAutoRefresh: true,
  });
  */

  // Function call state (disabled)
  /*
  const [functionCalls, setFunctionCalls] = useState([]);
  const [callResetKey, setCallResetKey] = useState(0);
  */

  // Component refs
  const chatRef = useRef(null);
  const messageContainerRef = useRef(null);
  const socketRef = useRef(null);
  const relaySocketRef = useRef(null);
  const phoneButtonRef = useRef(null);
  const phonePanelRef = useRef(null);
  const micButtonRef = useRef(null);
  const micMutedRef = useRef(false);
  const relayHealthIntervalRef = useRef(null);
  const relayReconnectTimeoutRef = useRef(null);
  const handleSocketMessageRef = useRef(null);
  const openRelaySocketRef = useRef(null);
  const callLifecycleRef = useRef({
    pending: false,
    active: false,
    callId: null,
    lastEnvelopeAt: 0,
    reconnectAttempts: 0,
    reconnectScheduled: false,
    stalledLoggedAt: null,
    lastRelayOpenedAt: 0,
  });

  // Audio processing refs
  const audioContextRef = useRef(null);
  const processorRef = useRef(null);
  const analyserRef = useRef(null);
  const micStreamRef = useRef(null);
  
  // Audio playback refs for AudioWorklet
  const playbackAudioContextRef = useRef(null);
  const pcmSinkRef = useRef(null);
  const playbackActiveRef = useRef(false);
  const assistantStreamGenerationRef = useRef(0);
  const terminationReasonRef = useRef(null);
  const resampleWarningRef = useRef(false);
  const shouldReconnectRef = useRef(false);
  const reconnectTimeoutRef = useRef(null);
  const reconnectAttemptsRef = useRef(0);
  
  const audioLevelRef = useRef(0);
  const outputAudioLevelRef = useRef(0);
  const outputLevelDecayTimeoutRef = useRef(null);
  const startRecognitionRef = useRef(null);
  const stopRecognitionRef = useRef(null);

  const cancelOutputLevelDecay = useCallback(() => {
    if (outputLevelDecayTimeoutRef.current && typeof window !== 'undefined') {
      window.clearTimeout(outputLevelDecayTimeoutRef.current);
      outputLevelDecayTimeoutRef.current = null;
    }
  }, []);

  const scheduleOutputLevelDecay = useCallback(() => {
    if (typeof window === 'undefined') {
      outputAudioLevelRef.current = 0;
      return;
    }
    cancelOutputLevelDecay();
    const decayStep = () => {
      let next = outputAudioLevelRef.current * 0.78;
      if (next < 0.002) {
        next = 0;
      }
      outputAudioLevelRef.current = next;
      if (next > 0) {
        outputLevelDecayTimeoutRef.current = window.setTimeout(decayStep, 160);
      } else {
        outputLevelDecayTimeoutRef.current = null;
      }
    };
    outputLevelDecayTimeoutRef.current = window.setTimeout(decayStep, 200);
  }, [cancelOutputLevelDecay]);
  const metricsRef = useRef(createMetricsState());

  const workletSource = `
    class PcmSink extends AudioWorkletProcessor {
      constructor() {
        super();
        this.queue = [];
        this.readIndex = 0;
        this.samplesProcessed = 0;
        this.meter = 0;
        this.meterSamples = 0;
        this.meterInterval = sampleRate / 20; // ~50ms cadence
        this.port.onmessage = (e) => {
          if (e.data?.type === 'push') {
            this.queue.push(e.data.payload);
          } else if (e.data?.type === 'clear') {
            this.queue = [];
            this.readIndex = 0;
            this.meter = 0;
            this.meterSamples = 0;
            this.port.postMessage({ type: 'meter', value: 0 });
          }
        };
      }
      process(inputs, outputs) {
        const out = outputs[0][0];
        let writeIndex = 0;
        let sumSquares = 0;

        while (writeIndex < out.length) {
          if (this.queue.length === 0) {
            break;
          }

          const chunk = this.queue[0];
          const remain = chunk.length - this.readIndex;
          const toCopy = Math.min(remain, out.length - writeIndex);

          for (let n = 0; n < toCopy; n += 1) {
            const sample = chunk[this.readIndex + n] || 0;
            out[writeIndex + n] = sample;
            sumSquares += sample * sample;
          }

          writeIndex += toCopy;
          this.readIndex += toCopy;

          if (this.readIndex >= chunk.length) {
            this.queue.shift();
            this.readIndex = 0;
          }
        }

        if (writeIndex < out.length) {
          out.fill(0, writeIndex);
        }

        const frameSamples = out.length;
        const rmsInstant = frameSamples > 0 ? Math.sqrt(sumSquares / frameSamples) : 0;
        const smoothing = rmsInstant > this.meter ? 0.35 : 0.15;
        this.meter = this.meter + (rmsInstant - this.meter) * smoothing;
        this.meterSamples += frameSamples;

        if (this.meterSamples >= this.meterInterval) {
          this.meterSamples = 0;
          this.port.postMessage({ type: 'meter', value: this.meter });
        }

        this.samplesProcessed += frameSamples;
        return true;
      }
    }
    registerProcessor('pcm-sink', PcmSink);
  `;

  const resampleFloat32 = useCallback((input, fromRate, toRate) => {
    if (!input || fromRate === toRate || !Number.isFinite(fromRate) || !Number.isFinite(toRate) || fromRate <= 0 || toRate <= 0) {
      return input;
    }

    const resampleRatio = toRate / fromRate;
    if (!Number.isFinite(resampleRatio) || resampleRatio <= 0) {
      return input;
    }

    const newLength = Math.max(1, Math.round(input.length * resampleRatio));
    const output = new Float32Array(newLength);
    for (let i = 0; i < newLength; i += 1) {
      const sourceIndex = i / resampleRatio;
      const index0 = Math.floor(sourceIndex);
      const index1 = Math.min(input.length - 1, index0 + 1);
      const frac = sourceIndex - index0;
      const sample0 = input[index0] ?? 0;
      const sample1 = input[index1] ?? sample0;
      output[i] = sample0 + (sample1 - sample0) * frac;
    }
    return output;
  }, []);

  const updateOutputLevelMeter = useCallback((samples, meterValue) => {
    const previous = outputAudioLevelRef.current;
    let target = previous;

    if (typeof meterValue === "number" && Number.isFinite(meterValue)) {
      target = Math.min(1, Math.max(0, meterValue * 1.35));
    } else if (samples && samples.length) {
      let sumSquares = 0;
      for (let i = 0; i < samples.length; i += 1) {
        const sample = samples[i] || 0;
        sumSquares += sample * sample;
      }
      const rms = Math.sqrt(sumSquares / samples.length);
      target = Math.min(1, rms * 10);
    } else {
      target = previous * 0.75;
    }

    const blend = target > previous ? 0.35 : 0.2;
    let nextLevel = previous + (target - previous) * blend;

    if (nextLevel < 0.002) {
      nextLevel = 0;
    }

    outputAudioLevelRef.current = nextLevel;
    scheduleOutputLevelDecay();
  }, [scheduleOutputLevelDecay]);

  // Initialize playback audio context and worklet (call on user gesture)
  const initializeAudioPlayback = async () => {
    if (playbackAudioContextRef.current) return; // Already initialized
    
    try {
      const audioCtx = new (window.AudioContext || window.webkitAudioContext)({
        // Let browser use its native rate (usually 48kHz), worklet will handle resampling
      });
      
      // Add the worklet module
      await audioCtx.audioWorklet.addModule(URL.createObjectURL(new Blob(
        [workletSource], { type: 'text/javascript' }
      )));
      
      // Create the worklet node
      const sink = new AudioWorkletNode(audioCtx, 'pcm-sink', {
        numberOfInputs: 0, 
        numberOfOutputs: 1, 
        outputChannelCount: [1]
      });
      sink.connect(audioCtx.destination);
      sink.port.onmessage = (event) => {
        if (event?.data?.type === 'meter') {
          updateOutputLevelMeter(undefined, event.data.value ?? 0);
        }
      };
      
      // Resume on user gesture
      await audioCtx.resume();
      
      playbackAudioContextRef.current = audioCtx;
      pcmSinkRef.current = sink;
      
      appendLog("🔊 Audio playback initialized");
      logger.info("AudioWorklet playback system initialized, context sample rate:", audioCtx.sampleRate);
    } catch (error) {
      logger.error("Failed to initialize audio playback:", error);
      appendLog("❌ Audio playback init failed");
    }
  };


  const resetCallLifecycle = useCallback(() => {
    const state = callLifecycleRef.current;
    state.pending = false;
    state.active = false;
    state.callId = null;
    state.lastEnvelopeAt = 0;
    state.reconnectAttempts = 0;
    state.reconnectScheduled = false;
    state.stalledLoggedAt = null;
    state.lastRelayOpenedAt = 0;
    if (relayReconnectTimeoutRef.current && typeof window !== "undefined") {
      window.clearTimeout(relayReconnectTimeoutRef.current);
      relayReconnectTimeoutRef.current = null;
    }
  }, []);

  const closeRelaySocket = useCallback((reason = "client stop", options = {}) => {
    const { preserveLifecycle = false } = options;
    const relaySocket = relaySocketRef.current;
    if (relayReconnectTimeoutRef.current && typeof window !== "undefined") {
      window.clearTimeout(relayReconnectTimeoutRef.current);
      relayReconnectTimeoutRef.current = null;
    }
    if (!relaySocket) {
      if (!preserveLifecycle) {
        resetCallLifecycle();
      }
      return;
    }
    try {
      relaySocket.close(1000, reason);
    } catch (error) {
      logger.warn("Error closing relay socket:", error);
    } finally {
      if (relaySocketRef.current === relaySocket) {
        relaySocketRef.current = null;
      }
      if (!preserveLifecycle) {
        resetCallLifecycle();
      }
    }
  }, [resetCallLifecycle]);
  // Formatting functions moved to ProfileButton component
  const activeSessionProfile = sessionProfiles[sessionId];
  const hasActiveProfile = Boolean(activeSessionProfile?.profile);
  useEffect(() => {
    const profilePayload = activeSessionProfile?.profile;
    const nextId = profilePayload?.id || activeSessionProfile?.sessionId || null;
    if (!nextId) {
      lastProfileIdRef.current = null;
      setShowProfilePanel(false);
      return;
    }
    if (lastProfileIdRef.current !== nextId) {
      lastProfileIdRef.current = nextId;
      setShowProfilePanel(true);
    }
  }, [activeSessionProfile]);
  
  const handleDemoCreated = useCallback((demoPayload) => {
    if (!demoPayload) {
      return;
    }
    const ssn = demoPayload?.profile?.verification_codes?.ssn4;
    const notice = demoPayload?.safety_notice ?? 'Demo data only.';
    const sessionKey = demoPayload.session_id ?? sessionId;
    let previouslyHadProfile = false;
    const messageLines = [
      '🚨 DEMO PROFILE GENERATED 🚨',
      ssn ? `Temporary SSN Last 4: ${ssn}` : null,
      notice,
      'NEVER enter real customer or personal data in this environment.',
    ].filter(Boolean);
    setSessionProfiles((prev) => {
      previouslyHadProfile = Boolean(prev[sessionKey]?.profile);
      return {
        ...prev,
        [sessionKey]: buildSessionProfile(
          demoPayload,
          sessionKey,
          prev[sessionKey],
        ),
      };
    });
    appendSystemMessage(messageLines.join('\n'), { tone: "warning" });
    appendLog('Synthetic demo profile issued with sandbox identifiers');
    if (!previouslyHadProfile) {
      triggerProfileHighlight();
    }
    if (demoFormCloseTimeoutRef.current) {
      clearTimeout(demoFormCloseTimeoutRef.current);
    }
    demoFormCloseTimeoutRef.current = window.setTimeout(() => {
      closeDemoForm();
      demoFormCloseTimeoutRef.current = null;
    }, 1000);
  }, [appendLog, appendSystemMessage, sessionId, triggerProfileHighlight, closeDemoForm]);

  useEffect(() => {
    return () => {
      closeRelaySocket("component unmount");
    };
  }, [closeRelaySocket]);

  useEffect(() => {
    if (!recording) {
      micMutedRef.current = false;
      setMicMuted(false);
    }
  }, [recording]);

  const handleResetSession = useCallback(() => {
    const newSessionId = createNewSessionId();
    setSessionId(newSessionId);
    setSessionProfiles({});
    if (socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
      logger.info('🔌 Closing WebSocket for session reset...');
      try {
        socketRef.current.close();
      } catch (error) {
        logger.warn('Error closing socket during reset', error);
      }
    }
    setMessages([]);
    setActiveSpeaker(null);
    stopRecognitionRef.current?.();
    setCallActive(false);
    setCurrentCallId(null);
    setShowPhoneInput(false);
    micMutedRef.current = false;
    setMicMuted(false);
    closeRelaySocket("session reset");
    appendLog(`🔄️ Session reset - new session ID: ${newSessionId}`);
    setTimeout(() => {
      appendSystemMessage(
        "✅ Session restarted with new ID. Ready for a fresh conversation!",
        { tone: "success" },
      );
    }, 500);
  }, [appendLog, appendSystemMessage, closeRelaySocket, setSessionId, setSessionProfiles, setMessages, setActiveSpeaker, setCallActive, setShowPhoneInput]);

  const handleMuteToggle = useCallback(() => {
    if (!recording) {
      return;
    }
    const next = !micMutedRef.current;
    micMutedRef.current = next;
    setMicMuted(next);
    appendLog(next ? "🔇 Microphone muted" : "🔈 Microphone unmuted");
  }, [appendLog, recording]);

  const handleMicToggle = useCallback(() => {
    if (recording) {
      stopRecognitionRef.current?.();
    } else {
      micMutedRef.current = false;
      setMicMuted(false);
      setPendingRealtimeStart(true);
      setShowRealtimeModePanel(true);
    }
  }, [recording]);

  const terminateACSCall = useCallback(async () => {
    if (!callActive && !currentCallId) {
      stopRecognitionRef.current?.();
      return;
    }

    const payload =
      currentCallId != null
        ? {
            call_id: currentCallId,
            session_id: getOrCreateSessionId(),
            reason: "normal",
          }
        : null;
    try {
      if (payload) {
        const res = await fetch(`${API_BASE_URL}/api/v1/calls/terminate`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!res.ok) {
          const errorBody = await res.json().catch(() => ({}));
          appendLog(
            `Hangup failed: ${errorBody.detail || res.statusText || res.status}`
          );
        } else {
          appendLog("📴 Hangup requested");
        }
      }
    } catch (err) {
      appendLog(`Hangup error: ${err?.message || err}`);
    } finally {
      stopRecognitionRef.current?.();
      setCallActive(false);
      setActiveSpeaker(null);
      setShowPhoneInput(false);
      setCurrentCallId(null);
      resetCallLifecycle();
      closeRelaySocket("call terminated");
    }
  }, [
    appendLog,
    closeRelaySocket,
    resetCallLifecycle,
    callActive,
    currentCallId,
    setCallActive,
    setShowPhoneInput,
  ]);

  const handlePhoneButtonClick = useCallback(() => {
    if (isCallDisabled && !callActive) {
      return;
    }
    if (callActive) {
      terminateACSCall();
      return;
    }
    setShowPhoneInput((prev) => !prev);
  }, [isCallDisabled, callActive, setShowPhoneInput, terminateACSCall]);

  const publishMetricsSummary = useCallback(
    (label, detail) => {
      if (!label) {
        return;
      }

      let formatted = null;
      if (typeof detail === "string") {
        formatted = detail;
        logger.info(`[Metrics] ${label}: ${detail}`);
      } else if (detail && typeof detail === "object") {
        const entries = Object.entries(detail).filter(([, value]) => value !== undefined && value !== null && value !== "");
        formatted = entries
          .map(([key, value]) => `${key}=${value}`)
          .join(" • ");
        logger.info(`[Metrics] ${label}`, detail);
      } else {
        logger.info(`[Metrics] ${label}`, metricsRef.current);
      }

      appendLog(formatted ? `📈 ${label} — ${formatted}` : `📈 ${label}`);
    },
    [appendLog],
  );

  const {
    interruptAssistantOutput,
    recordBargeInEvent,
    finalizeBargeInClear,
  } = useBargeIn({
    appendLog,
    setActiveSpeaker,
    assistantStreamGenerationRef,
    pcmSinkRef,
    playbackActiveRef,
    metricsRef,
    publishMetricsSummary,
  });

  const resetMetrics = useCallback(
    (sessionId) => {
      metricsRef.current = createMetricsState();
      const metrics = metricsRef.current;
      metrics.sessionStart = performance.now();
      metrics.sessionStartIso = new Date().toISOString();
      metrics.sessionId = sessionId;
      publishMetricsSummary("Session metrics reset", {
        sessionId,
        at: metrics.sessionStartIso,
      });
    },
    [publishMetricsSummary],
  );

  const registerUserTurn = useCallback(
    (text) => {
      const metrics = metricsRef.current;
      const now = performance.now();
      const turnId = metrics.turnCounter + 1;
      metrics.turnCounter = turnId;
      const turn = {
        id: turnId,
        userTs: now,
        userTextPreview: text.slice(0, 80),
      };
      metrics.turns.push(turn);
      metrics.currentTurnId = turnId;
      metrics.awaitingAudioTurnId = turnId;
      const elapsed = metrics.sessionStart != null ? toMs(now - metrics.sessionStart) : undefined;
      publishMetricsSummary(`Turn ${turnId} user`, {
        elapsedSinceStartMs: elapsed,
      });
    },
    [publishMetricsSummary],
  );

  const registerAssistantStreaming = useCallback(
    (speaker) => {
      const metrics = metricsRef.current;
      const now = performance.now();
      let turn = metrics.turns.slice().reverse().find((t) => !t.firstTokenTs || !t.audioEndTs);
      if (!turn) {
        const turnId = metrics.turnCounter + 1;
        metrics.turnCounter = turnId;
        turn = {
          id: turnId,
          userTs: metrics.sessionStart ?? now,
          synthetic: true,
          userTextPreview: "[synthetic]",
        };
        metrics.turns.push(turn);
        metrics.currentTurnId = turnId;
      }

      if (!turn.firstTokenTs) {
        turn.firstTokenTs = now;
        turn.firstTokenLatencyMs = turn.userTs != null ? now - turn.userTs : undefined;
        if (metrics.firstTokenTs == null) {
          metrics.firstTokenTs = now;
        }
        if (metrics.sessionStart != null && metrics.ttftMs == null) {
          metrics.ttftMs = now - metrics.sessionStart;
          publishMetricsSummary("TTFT captured", {
            ttftMs: toMs(metrics.ttftMs),
          });
        }
        publishMetricsSummary(`Turn ${turn.id} first token`, {
          latencyMs: toMs(turn.firstTokenLatencyMs),
          speaker,
        });
      }
      metrics.currentTurnId = turn.id;
    },
    [publishMetricsSummary],
  );

  const registerAssistantFinal = useCallback(
    (speaker) => {
      const metrics = metricsRef.current;
      const now = performance.now();
      const turn = metrics.turns.slice().reverse().find((t) => !t.finalTextTs);
      if (!turn) {
        return;
      }

      if (!turn.finalTextTs) {
        turn.finalTextTs = now;
        turn.finalLatencyMs = turn.userTs != null ? now - turn.userTs : undefined;
        metrics.awaitingAudioTurnId = turn.id;
        publishMetricsSummary(`Turn ${turn.id} final text`, {
          latencyMs: toMs(turn.finalLatencyMs),
          speaker,
        });
        if (turn.audioStartTs != null) {
          turn.finalToAudioMs = turn.audioStartTs - turn.finalTextTs;
          publishMetricsSummary(`Turn ${turn.id} final→audio`, {
            deltaMs: toMs(turn.finalToAudioMs),
          });
        }
      }
    },
    [publishMetricsSummary],
  );

  const registerAudioFrame = useCallback(
    (frameIndex, isFinal) => {
      const metrics = metricsRef.current;
      const now = performance.now();
      metrics.lastAudioFrameTs = now;

      const preferredId = metrics.awaitingAudioTurnId ?? metrics.currentTurnId;
      let turn = preferredId != null ? metrics.turns.find((t) => t.id === preferredId) : undefined;
      if (!turn) {
        turn = metrics.turns.slice().reverse().find((t) => !t.audioEndTs);
      }
      if (!turn) {
        return;
      }

      if ((frameIndex ?? 0) === 0 && turn.audioStartTs == null) {
        turn.audioStartTs = now;
        const deltaFromFinal = turn.finalTextTs != null ? now - turn.finalTextTs : undefined;
        turn.finalToAudioMs = deltaFromFinal;
        publishMetricsSummary(`Turn ${turn.id} audio start`, {
          afterFinalMs: toMs(deltaFromFinal),
          elapsedMs: turn.userTs != null ? toMs(now - turn.userTs) : undefined,
        });
      }

      if (isFinal) {
        turn.audioEndTs = now;
        turn.audioPlaybackDurationMs = turn.audioStartTs != null ? now - turn.audioStartTs : undefined;
        turn.totalLatencyMs = turn.userTs != null ? now - turn.userTs : undefined;
        metrics.awaitingAudioTurnId = null;
        publishMetricsSummary(`Turn ${turn.id} audio complete`, {
          playbackDurationMs: toMs(turn.audioPlaybackDurationMs),
          totalMs: toMs(turn.totalLatencyMs),
        });
      }
    },
    [publishMetricsSummary],
  );

  useEffect(()=>{
    if(messageContainerRef.current) {
      messageContainerRef.current.scrollTo({
        top: messageContainerRef.current.scrollHeight,
        behavior: 'smooth'
      });
    } else if(chatRef.current) {
      chatRef.current.scrollTo({
        top: chatRef.current.scrollHeight,
        behavior: 'smooth'
      });
    }
  },[messages]);

  useEffect(() => {
    return () => {
      if (processorRef.current) {
        try { 
          processorRef.current.disconnect(); 
        } catch (e) {
          logger.warn("Cleanup error:", e);
        }
      }
      if (audioContextRef.current) {
        try { 
          audioContextRef.current.close(); 
        } catch (e) {
          logger.warn("Cleanup error:", e);
        }
      }
      if (pcmSinkRef.current) {
        try {
          pcmSinkRef.current.port.onmessage = null;
          pcmSinkRef.current = null;
        } catch (e) {
          logger.warn("Cleanup error:", e);
        }
      }
      if (playbackAudioContextRef.current) {
        try { 
          playbackAudioContextRef.current.close(); 
        } catch (e) {
          logger.warn("Cleanup error:", e);
        }
      }
      playbackActiveRef.current = false;
      shouldReconnectRef.current = false;
      reconnectAttemptsRef.current = 0;
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
      if (socketRef.current) {
        try { 
          socketRef.current.close(); 
        } catch (e) {
          logger.warn("Cleanup error:", e);
        }
        socketRef.current = null;
      }
      cancelOutputLevelDecay();
      outputAudioLevelRef.current = 0;
      audioLevelRef.current = 0;
    };
  }, [cancelOutputLevelDecay]);

  const startRecognition = async (modeOverride) => {
      appendLog("🎤 PCM streaming started");

      await initializeAudioPlayback();

      const sessionId = getOrCreateSessionId();
      const realtimeMode = modeOverride || selectedRealtimeStreamingMode;
      const realtimeReadableMode =
        selectedRealtimeStreamingModeLabel || realtimeMode;
      const activeRealtimeConfig = modeOverride
        ? (realtimeStreamingModeOptions.find((option) => option.value === realtimeMode)?.config ?? null)
        : selectedRealtimeModeConfig;
      const baseConversationUrl = `${WS_URL}/api/v1/realtime/conversation?session_id=${sessionId}&streaming_mode=${encodeURIComponent(
        realtimeMode,
      )}`;
      resetMetrics(sessionId);
      assistantStreamGenerationRef.current = 0;
      terminationReasonRef.current = null;
      resampleWarningRef.current = false;
      shouldReconnectRef.current = true;
      reconnectAttemptsRef.current = 0;
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
      logger.info(
        '🔗 [FRONTEND] Starting conversation WebSocket with session_id: %s (realtime_mode=%s)',
        sessionId,
        realtimeReadableMode,
      );
      if (activeRealtimeConfig) {
        logger.debug(
          '[FRONTEND] Realtime streaming mode config:',
          activeRealtimeConfig,
        );
      }

      const connectSocket = (isReconnect = false) => {
        const ws = new WebSocket(baseConversationUrl);
        ws.binaryType = "arraybuffer";

        ws.onopen = () => {
          appendLog(isReconnect ? "🔌 WS reconnected - Connected to backend!" : "🔌 WS open - Connected to backend!");
          logger.info(
            "WebSocket connection %s to backend at:",
            isReconnect ? "RECONNECTED" : "OPENED",
            baseConversationUrl,
          );
          reconnectAttemptsRef.current = 0;
        };

        ws.onclose = (event) => {
          appendLog(`🔌 WS closed - Code: ${event.code}, Reason: ${event.reason}`);
          logger.info("WebSocket connection CLOSED. Code:", event.code, "Reason:", event.reason);

          if (socketRef.current === ws) {
            socketRef.current = null;
          }

          if (!shouldReconnectRef.current) {
            if (terminationReasonRef.current === "HUMAN_HANDOFF") {
              appendLog("🔌 WS closed after live agent transfer");
            }
            return;
          }

          const attempt = reconnectAttemptsRef.current + 1;
          reconnectAttemptsRef.current = attempt;
          const delay = Math.min(5000, 250 * Math.pow(2, attempt - 1));
          appendLog(`🔄 WS reconnect scheduled in ${Math.round(delay)} ms (attempt ${attempt})`);

          if (reconnectTimeoutRef.current) {
            clearTimeout(reconnectTimeoutRef.current);
          }

          reconnectTimeoutRef.current = window.setTimeout(() => {
            reconnectTimeoutRef.current = null;
            if (!shouldReconnectRef.current) {
              return;
            }
            appendLog("🔄 Attempting WS reconnect…");
            connectSocket(true);
          }, delay);
        };

        ws.onerror = (err) => {
          appendLog("❌ WS error - Check if backend is running");
          logger.error("WebSocket error - backend might not be running:", err);
        };

        ws.onmessage = (event) => {
          const handler = handleSocketMessageRef.current;
          if (handler) {
            handler(event);
          }
        };
        socketRef.current = ws;
        return ws;
      };

      connectSocket(false);

      // 2) setup Web Audio for raw PCM @16 kHz
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      micMutedRef.current = false;
      setMicMuted(false);
      micStreamRef.current = stream;
      const audioCtx = new (window.AudioContext || window.webkitAudioContext)({
        sampleRate: 16000
      });
      audioContextRef.current = audioCtx;

      const source = audioCtx.createMediaStreamSource(stream);

      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.3;
      analyserRef.current = analyser;
      
      source.connect(analyser);

      const bufferSize = 512; 
      const processor  = audioCtx.createScriptProcessor(bufferSize, 1, 1);
      processorRef.current = processor;

      analyser.connect(processor);

      processor.onaudioprocess = (evt) => {
        const float32 = evt.inputBuffer.getChannelData(0);
        const isMuted = micMutedRef.current;
        let target = 0;

        const int16 = new Int16Array(float32.length);

        if (isMuted) {
          for (let i = 0; i < float32.length; i++) {
            int16[i] = 0;
          }
        } else {
          let sum = 0;
          for (let i = 0; i < float32.length; i++) {
            const sample = Math.max(-1, Math.min(1, float32[i]));
            sum += sample * sample;
            int16[i] = sample * 0x7fff;
          }
          const rms = Math.sqrt(sum / float32.length);
          target = Math.min(1, rms * 10);
        }

        const previous = audioLevelRef.current;
        const smoothing = target > previous ? 0.32 : 0.18;
        const level = previous + (target - previous) * smoothing;
        audioLevelRef.current = level;

        const activeSocket = socketRef.current;
        if (activeSocket && activeSocket.readyState === WebSocket.OPEN) {
          activeSocket.send(int16.buffer);
          // Debug: Confirm data sent
          // logger.debug("PCM audio chunk sent to backend!");
        } else {
          logger.debug("WebSocket not open, did not send audio.");
        }
      };

      source.connect(processor);
      processor.connect(audioCtx.destination);
      setRecording(true);
    };

    const stopRecognition = () => {
      if (processorRef.current) {
        try { 
          processorRef.current.disconnect(); 
        } catch (e) {
          logger.warn("Error disconnecting processor:", e);
        }
        processorRef.current = null;
      }
      if (audioContextRef.current) {
        try { 
          audioContextRef.current.close(); 
        } catch (e) {
          logger.warn("Error closing audio context:", e);
        }
        audioContextRef.current = null;
      }
      if (micStreamRef.current) {
        try {
          micStreamRef.current.getTracks().forEach((track) => {
            try {
              track.stop();
            } catch (trackError) {
              logger.warn("Error stopping mic track:", trackError);
            }
          });
        } catch (streamError) {
          logger.warn("Error releasing microphone stream:", streamError);
        }
        micStreamRef.current = null;
      }
      playbackActiveRef.current = false;
      
      shouldReconnectRef.current = false;
      reconnectAttemptsRef.current = 0;
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }

      if (socketRef.current) {
        try { 
          socketRef.current.close(1000, "client stop"); 
        } catch (e) {
          logger.warn("Error closing socket:", e);
        }
        socketRef.current = null;
      }
      
      // Add session stopped divider instead of card
      appendSystemMessage("🛑 Session stopped", { variant: "session_stop" });
      setActiveSpeaker("System");
      setRecording(false);
      micMutedRef.current = false;
      setMicMuted(false);
      audioLevelRef.current = 0;
      outputAudioLevelRef.current = 0;
      cancelOutputLevelDecay();
      appendLog("🛑 PCM streaming stopped");
    };

    startRecognitionRef.current = startRecognition;
    stopRecognitionRef.current = stopRecognition;

    const pushIfChanged = (arr, msg) => {
      const normalizedMsg =
        msg?.speaker === "System"
          ? buildSystemMessage(msg.text ?? "", msg)
          : msg;
      if (arr.length === 0) return [...arr, normalizedMsg];
      const last = arr[arr.length - 1];
      if (last.speaker === normalizedMsg.speaker && last.text === normalizedMsg.text) return arr;
      return [...arr, normalizedMsg];
    };

    const handleSocketMessage = async (event) => {
      // Log all incoming messages for debugging
      if (typeof event.data === "string") {
        try {
          const msg = JSON.parse(event.data);
          logger.debug("📨 WebSocket message received:", msg.type || "unknown", msg);
        } catch (e) {
          logger.debug("📨 Non-JSON WebSocket message:", event.data);
          logger.debug(e)
        }
      } else {
        logger.debug("📨 Binary WebSocket message received, length:", event.data.byteLength);
      }

      if (typeof event.data !== "string") {
        // Binary audio data (legacy path)
        
        // Resume audio context if suspended (after text barge-in)
        if (audioContextRef.current && audioContextRef.current.state === "suspended") {
          await audioContextRef.current.resume();
          appendLog("▶️ Audio context resumed");
        }
        
        const ctx = audioContextRef.current || new AudioContext();
        if (!audioContextRef.current) {
          audioContextRef.current = ctx;
        }
        
        const buf = await event.data.arrayBuffer();
        const audioBuf = await ctx.decodeAudioData(buf);
        const src = ctx.createBufferSource();
        src.buffer = audioBuf;
        src.connect(ctx.destination);
        src.start();
        appendLog("🔊 Audio played");
        return;
      }
    
      let payload;
      try {
        payload = JSON.parse(event.data);
      } catch {
        appendLog("Ignored non‑JSON frame");
        return;
      }

      // --- NEW: Handle envelope format from backend ---
      // If message is in envelope format, extract the actual payload
      if (payload.type && payload.sender && payload.payload && payload.ts) {
        const envelope = payload;
        logger.debug("📨 Received envelope message:", {
          type: envelope.type,
          sender: envelope.sender,
          topic: envelope.topic,
          session_id: envelope.session_id,
        });

        const envelopeType = envelope.type;
        const envelopeSender = envelope.sender;
        const envelopeTimestamp = envelope.ts;
        const envelopeSessionId = envelope.session_id;
        const envelopeTopic = envelope.topic;
        const actualPayload = envelope.payload ?? {};

        let flattenedPayload;

        // Transform envelope back to legacy format for compatibility
        if (
          envelopeType === "event" &&
          actualPayload.message &&
          !actualPayload.event_type &&
          !actualPayload.eventType
        ) {
          // Status/chat message in envelope
          flattenedPayload = {
            type: "assistant",
            sender: envelopeSender,
            speaker: envelopeSender,
            message: actualPayload.message,
            content: actualPayload.message,
          };
        } else if (envelopeType === "assistant_streaming" && actualPayload.content) {
          // Streaming response in envelope
          flattenedPayload = {
            type: "assistant_streaming",
            sender: envelopeSender,
            speaker: envelopeSender,
            content: actualPayload.content,
          };
        } else if (envelopeType === "status" && actualPayload.message) {
          // Status message in envelope
          flattenedPayload = {
            type: "status",
            sender: envelopeSender,
            speaker: envelopeSender,
            message: actualPayload.message,
            content: actualPayload.message,
            statusLabel: actualPayload.label || actualPayload.status_label,
          };
        } else {
          // For other envelope types, use the payload directly and retain the type
          flattenedPayload = {
            ...actualPayload,
            type: envelopeType,
            sender: envelopeSender,
            speaker: envelopeSender,
          };
        }

        if (envelopeTimestamp && !flattenedPayload.ts) {
          flattenedPayload.ts = envelopeTimestamp;
        }
        if (envelopeSessionId && !flattenedPayload.session_id) {
          flattenedPayload.session_id = envelopeSessionId;
        }
        if (envelopeTopic && !flattenedPayload.topic) {
          flattenedPayload.topic = envelopeTopic;
        }

        payload = flattenedPayload;
        logger.debug("📨 Transformed envelope to legacy format:", payload);
      }

      if (callLifecycleRef.current.pending) {
        callLifecycleRef.current.lastEnvelopeAt = Date.now();
      }

      const normalizedEventType =
        payload.event_type ||
        payload.eventType ||
        (typeof payload.type === "string" && payload.type.startsWith("event_")
          ? payload.type
          : undefined);

      if (normalizedEventType) {
        payload.event_type = normalizedEventType;
      }

      if (normalizedEventType === "session_updated") {
        const combinedData = {
          ...(typeof payload.event_data === "object" && payload.event_data ? payload.event_data : {}),
          ...(typeof payload.data === "object" && payload.data ? payload.data : {}),
        };

        if (typeof payload.session === "object" && payload.session) {
          combinedData.session = combinedData.session ?? payload.session;
        }

        let candidateAgent =
          payload.active_agent_label ||
          payload.agent_label ||
          payload.agentLabel ||
          payload.agent_name ||
          combinedData.active_agent_label ||
          combinedData.agent_label ||
          combinedData.agentLabel ||
          combinedData.agent_name;

        if (!candidateAgent) {
          const sessionInfo = combinedData.session;
          if (sessionInfo && typeof sessionInfo === "object") {
            candidateAgent =
              sessionInfo.active_agent_label ||
              sessionInfo.activeAgentLabel ||
              sessionInfo.active_agent ||
              sessionInfo.agent_label ||
              sessionInfo.agentLabel ||
              sessionInfo.agent_name ||
              sessionInfo.agentName ||
              sessionInfo.current_agent ||
              sessionInfo.currentAgent ||
              sessionInfo.handoff_target ||
              sessionInfo.handoffTarget;
          }
        }

        const agentLabel =
          typeof candidateAgent === "string" ? candidateAgent.trim() : null;

        if (agentLabel) {
          const label = agentLabel;
          combinedData.active_agent_label = combinedData.active_agent_label ?? label;
          combinedData.agent_label = combinedData.agent_label ?? label;
          combinedData.agent_name = combinedData.agent_name ?? label;
          payload.active_agent_label = payload.active_agent_label ?? label;
          payload.agent_label = payload.agent_label ?? label;
          payload.agent_name = payload.agent_name ?? label;
        }

        const displayLabel = combinedData.active_agent_label || combinedData.agent_label;
        const resolvedMessage =
          payload.message ||
          payload.summary ||
          combinedData.message ||
          (displayLabel ? `Active agent: ${displayLabel}` : null);

        if (resolvedMessage) {
          combinedData.message = resolvedMessage;
          payload.summary = payload.summary ?? resolvedMessage;
          payload.message = payload.message ?? resolvedMessage;
        }

        if (!combinedData.timestamp && payload.ts) {
          combinedData.timestamp = payload.ts;
        }

        payload.data = combinedData;
        payload.event_data = combinedData;
        if (payload.type !== "event") {
          payload.type = "event";
        }
      }

      if (payload.event_type === "call_connected") {
        setCallActive(true);
        appendLog("📞 Call connected");
        const lifecycle = callLifecycleRef.current;
        lifecycle.pending = true;
        lifecycle.active = true;
        lifecycle.callId = payload.call_connection_id || lifecycle.callId;
        lifecycle.lastEnvelopeAt = Date.now();
        lifecycle.reconnectAttempts = 0;
        lifecycle.reconnectScheduled = false;
        lifecycle.stalledLoggedAt = null;
        payload.summary = payload.summary ?? "Call connected";
        payload.type = payload.type ?? "event";
      }

      if (payload.event_type === "call_disconnected") {
        setCallActive(false);
        setActiveSpeaker(null);
        resetCallLifecycle();
        closeRelaySocket("call disconnected");
        appendLog("📞 Call ended");
        payload.summary = payload.summary ?? "Call disconnected";
        payload.type = payload.type ?? "event";
      }

      if (payload.type === "session_end") {
        const reason = payload.reason || "UNKNOWN";
        terminationReasonRef.current = reason;
        if (reason === "HUMAN_HANDOFF") {
          shouldReconnectRef.current = false;
        }
        resetCallLifecycle();
        setCallActive(false);
        setShowPhoneInput(false);
        const normalizedReason =
          typeof reason === "string" ? reason.split("_").join(" ") : String(reason);
        const reasonText =
          reason === "HUMAN_HANDOFF"
            ? "Transferring you to a live agent. Please stay on the line."
            : `Session ended (${normalizedReason})`;
        setMessages((prev) =>
          pushIfChanged(prev, { speaker: "System", text: reasonText })
        );
        setActiveSpeaker("System");
        appendLog(`⚠️ Session ended (${reason})`);
        playbackActiveRef.current = false;
        if (pcmSinkRef.current) {
          pcmSinkRef.current.port.postMessage({ type: "clear" });
        }
        return;
      }

      if (payload.event_type === "stt_partial" && payload.data) {
        const partialData = payload.data;
        const partialText = (partialData.content || "").trim();
        const partialMeta = {
          reason: partialData.reason || "stt_partial",
          trigger: partialData.streaming_type || "stt_partial",
          at: partialData.stage || "partial",
          action: "stt_partial",
          sequence: partialData.sequence,
        };

        logger.debug("📝 STT partial detected:", {
          text: partialText,
          sequence: partialData.sequence,
          trigger: partialMeta.trigger,
        });

        const bargeInEvent = recordBargeInEvent("stt_partial", partialMeta);
        const shouldClearPlayback =
          playbackActiveRef.current === true || !bargeInEvent?.clearIssuedTs;

        if (shouldClearPlayback) {
          interruptAssistantOutput(partialMeta, {
            logMessage: "🔇 Audio cleared due to live speech (partial transcription)",
          });

          if (bargeInEvent) {
            finalizeBargeInClear(bargeInEvent, { keepPending: true });
          }
        }

        if (partialText) {
          let registeredTurn = false;
          setMessages((prev) => {
            const last = prev.at(-1);
            if (last?.speaker === "User" && last?.streaming) {
              if (last.text === partialText) {
                return prev;
              }
              const updated = prev.slice();
              updated[updated.length - 1] = {
                ...last,
                text: partialText,
                streamingType: "stt_partial",
                sequence: partialData.sequence,
                language: partialData.language || last.language,
              };
              return updated;
            }
            registeredTurn = true;
            return [
              ...prev,
              {
                speaker: "User",
                text: partialText,
                streaming: true,
                streamingType: "stt_partial",
                sequence: partialData.sequence,
                language: partialData.language,
              },
            ];
          });

          if (registeredTurn) {
            registerUserTurn(partialText);
          }
        }

        setActiveSpeaker("User");
        return;
      }

      if (payload.event_type === "live_agent_transfer") {
        terminationReasonRef.current = "HUMAN_HANDOFF";
        shouldReconnectRef.current = false;
        playbackActiveRef.current = false;
        if (pcmSinkRef.current) {
          pcmSinkRef.current.port.postMessage({ type: "clear" });
        }
        const reasonDetail =
          payload.data?.reason ||
          payload.data?.escalation_reason ||
          payload.data?.message;
        const transferText = reasonDetail
          ? `Escalating to a live agent: ${reasonDetail}`
          : "Escalating you to a live agent. Please hold while we connect.";
        setMessages((prev) =>
          pushIfChanged(prev, { speaker: "System", text: transferText })
        );
        setActiveSpeaker("System");
        appendLog("🤝 Escalated to live agent");
        return;
      }

      if (payload.type === "event") {
        const eventType =
          payload.event_type ||
          payload.eventType ||
          payload.name ||
          payload.data?.event_type ||
          "event";
        const rawEventData =
          payload.data ??
          payload.event_data ??
          (typeof payload.payload === "object" ? payload.payload : null);
        const eventData =
          rawEventData && typeof rawEventData === "object" ? rawEventData : {};
        const eventTimestamp = payload.ts || new Date().toISOString();
        const eventSpeaker = payload.speaker || payload.sender || "System";
        const eventTopic = payload.topic || "session";

        setMessages((prev) => [
          ...prev,
          {
            type: "event",
            speaker: eventSpeaker,
            eventType,
            data: eventData,
            timestamp: eventTimestamp,
            topic: eventTopic,
            sessionId: payload.session_id || sessionId,
          },
        ]);
        appendLog(`📡 Event received: ${eventType}`);
        return;
      }
      
      // Handle audio_data messages from backend TTS
      if (payload.type === "audio_data") {
        try {
          logger.info("🔊 Received audio_data message:", {
            frame_index: payload.frame_index,
            total_frames: payload.total_frames,
            sample_rate: payload.sample_rate,
            data_length: payload.data ? payload.data.length : 0,
            is_final: payload.is_final
          });

          const hasData = typeof payload.data === "string" && payload.data.length > 0;

          const isFinalChunk =
            payload.is_final === true ||
            (Number.isFinite(payload.total_frames) &&
              Number.isFinite(payload.frame_index) &&
              payload.frame_index + 1 >= payload.total_frames);

          const frameIndex = Number.isFinite(payload.frame_index) ? payload.frame_index : 0;
          registerAudioFrame(frameIndex, isFinalChunk);

          // Resume playback context if suspended (after text barge-in)
          if (playbackAudioContextRef.current) {
            const ctx = playbackAudioContextRef.current;
            logger.info(`[Audio] Playback context state: ${ctx.state}`);
            if (ctx.state === "suspended") {
              logger.info("[Audio] Resuming suspended playback context...");
              await ctx.resume();
              appendLog("▶️ TTS playback resumed");
              logger.info(`[Audio] Playback context state after resume: ${ctx.state}`);
            }
          } else {
            logger.warn("[Audio] No playback context found, initializing...");
            await initializeAudioPlayback();
          }

          if (!hasData) {
            playbackActiveRef.current = !isFinalChunk;
            updateOutputLevelMeter();
            return;
          }

          // Decode base64 -> Int16 -> Float32 [-1, 1]
          const bstr = atob(payload.data);
          const buf = new ArrayBuffer(bstr.length);
          const view = new Uint8Array(buf);
          for (let i = 0; i < bstr.length; i++) view[i] = bstr.charCodeAt(i);
          const int16 = new Int16Array(buf);
          const float32 = new Float32Array(int16.length);
          for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 0x8000;

          logger.debug(`🔊 Processing TTS audio chunk: ${float32.length} samples, sample_rate: ${payload.sample_rate || 16000}`);
          logger.debug("🔊 Audio data preview:", float32.slice(0, 10));

          // Push to the worklet queue
          if (pcmSinkRef.current) {
            let samples = float32;
            const playbackCtx = playbackAudioContextRef.current;
            const sourceRate = payload.sample_rate;
            if (playbackCtx && Number.isFinite(sourceRate) && sourceRate && playbackCtx.sampleRate !== sourceRate) {
              samples = resampleFloat32(float32, sourceRate, playbackCtx.sampleRate);
              if (!resampleWarningRef.current) {
                appendLog(`🎚️ Resampling audio ${sourceRate}Hz → ${playbackCtx.sampleRate}Hz`);
                resampleWarningRef.current = true;
              }
            }
            pcmSinkRef.current.port.postMessage({ type: 'push', payload: samples });
            updateOutputLevelMeter(samples);
            appendLog(`🔊 TTS audio frame ${payload.frame_index + 1}/${payload.total_frames}`);
          } else {
            logger.warn("Audio playback not initialized, attempting init...");
            appendLog("⚠️ Audio playback not ready, initializing...");
            // Try to initialize if not done yet
            await initializeAudioPlayback();
            if (pcmSinkRef.current) {
              let samples = float32;
              const playbackCtx = playbackAudioContextRef.current;
              const sourceRate = payload.sample_rate;
              if (playbackCtx && Number.isFinite(sourceRate) && sourceRate && playbackCtx.sampleRate !== sourceRate) {
                samples = resampleFloat32(float32, sourceRate, playbackCtx.sampleRate);
                if (!resampleWarningRef.current) {
                  appendLog(`🎚️ Resampling audio ${sourceRate}Hz → ${playbackCtx.sampleRate}Hz`);
                  resampleWarningRef.current = true;
                }
              }
              pcmSinkRef.current.port.postMessage({ type: 'push', payload: samples });
              updateOutputLevelMeter(samples);
              appendLog("🔊 TTS audio playing (after init)");
            } else {
              logger.error("Failed to initialize audio playback");
              appendLog("❌ Audio init failed");
            }
          }
          playbackActiveRef.current = !isFinalChunk;
          return; // handled
        } catch (error) {
          logger.error("Error processing audio_data:", error);
          appendLog("❌ Audio processing failed: " + error.message);
        }
      }
      
      // --- Handle relay/broadcast messages with {sender, message} ---
      if (payload.sender && payload.message) {
        // Route all relay messages through the same logic
        payload.speaker = payload.sender;
        payload.content = payload.message;
        // fall through to unified logic below
      }
      const { type, content = "", message = "", speaker } = payload;
      const txt = content || message;
      const msgType = (type || "").toLowerCase();

      if (msgType === "session_profile" || msgType === "demo_profile") {
        const sessionKey = payload.session_id ?? sessionId;
        if (sessionKey) {
          setSessionProfiles((prev) => {
            const normalized = buildSessionProfile(payload, sessionKey, prev[sessionKey]);
            if (!normalized) {
              return prev;
            }
            return {
              ...prev,
              [sessionKey]: normalized,
            };
          });
          appendLog(`Session profile acknowledged for ${sessionKey}`);
        }
        return;
      }

      if (msgType === "user" || speaker === "User") {
        setActiveSpeaker("User");
        setMessages((prev) => {
          const last = prev.at(-1);
          if (last?.speaker === "User" && last?.streaming) {
            return prev.map((m, i) =>
              i === prev.length - 1 ? { ...m, text: txt, streaming: false } : m,
            );
          }
          return [...prev, { speaker: "User", text: txt }];
        });
        appendLog(`User: ${txt}`);
        return;
      }

      if (type === "assistant_streaming") {
        const streamingSpeaker = speaker || "Assistant";
        const streamGeneration = assistantStreamGenerationRef.current;
        registerAssistantStreaming(streamingSpeaker);
        setActiveSpeaker(streamingSpeaker);
        setMessages(prev => {
          const latest = prev.at(-1);
          if (
            latest?.streaming &&
            latest?.speaker === streamingSpeaker &&
            latest?.streamGeneration === streamGeneration
          ) {
            return prev.map((m, i) =>
              i === prev.length - 1
                ? {
                    ...m,
                    text: m.text + txt,
                  }
                : m,
            );
          }
          return [
            ...prev,
            {
              speaker: streamingSpeaker,
              text: txt,
              streaming: true,
              streamGeneration,
            },
          ];
        });
        const pending = metricsRef.current?.pendingBargeIn;
        if (pending) {
          finalizeBargeInClear(pending);
        }
        return;
      }

      if (msgType === "assistant" || msgType === "status" || speaker === "Assistant") {
        if (msgType === "status") {
          const normalizedStatus = (txt || "").toLowerCase();
          if (
            normalizedStatus.includes("call connected") ||
            normalizedStatus.includes("call disconnected")
          ) {
            return;
          }
        }
        const assistantSpeaker = speaker || "Assistant";
        registerAssistantFinal(assistantSpeaker);
        setActiveSpeaker("Assistant");
        const messageOptions = {
          speaker: assistantSpeaker,
          text: txt,
        };
        if (payload.statusLabel) {
          messageOptions.statusLabel = payload.statusLabel;
        }
        if (payload.statusTone) {
          messageOptions.statusTone = payload.statusTone;
        }
        if (payload.statusCaption) {
          messageOptions.statusCaption = payload.statusCaption;
        }
        if (payload.ts || payload.timestamp) {
          messageOptions.timestamp = payload.ts || payload.timestamp;
        }
        setMessages(prev => {
          for (let idx = prev.length - 1; idx >= 0; idx -= 1) {
            const candidate = prev[idx];
            if (candidate?.streaming) {
              return prev.map((m, i) =>
                i === idx
                  ? {
                      ...m,
                      ...messageOptions,
                      streaming: false,
                    }
                  : m,
              );
            }
          }
          return pushIfChanged(prev, {
            ...messageOptions,
          });
        });

        appendLog("🤖 Assistant responded");
        return;
      }
    
      if (type === "tool_start") {

      
        setMessages((prev) => [
          ...prev,
          {
            speaker: "Assistant",
            isTool: true,
            text: `🛠️ tool ${payload.tool} started 🔄`,
          },
        ]);
      
        appendLog(`⚙️ ${payload.tool} started`);
        return;
      }
      
    
      if (type === "tool_progress") {
        const pctNumeric = Number(payload.pct);
        const pctText = Number.isFinite(pctNumeric)
          ? `${pctNumeric}%`
          : payload.pct
          ? `${payload.pct}`
          : "progress";
        updateToolMessage(
          payload.tool,
          (message) => ({
            ...message,
            text: `🛠️ tool ${payload.tool} ${pctText} 🔄`,
          }),
          () => ({
            speaker: "Assistant",
            isTool: true,
            text: `🛠️ tool ${payload.tool} ${pctText} 🔄`,
          }),
        );
        appendLog(`⚙️ ${payload.tool} ${pctText}`);
        return;
      }
    
      if (type === "tool_end") {

        const resultPayload =
          payload.result ?? payload.output ?? payload.data ?? payload.response;
        const serializedResult =
          resultPayload !== undefined
            ? JSON.stringify(resultPayload, null, 2)
            : null;
        const finalText =
          payload.status === "success"
            ? `🛠️ tool ${payload.tool} completed ✔️${
                serializedResult ? `\n${serializedResult}` : ""
              }`
            : `🛠️ tool ${payload.tool} failed ❌\n${payload.error}`;
        updateToolMessage(
          payload.tool,
          (message) => ({
            ...message,
            text: finalText,
          }),
          {
            speaker: "Assistant",
            isTool: true,
            text: finalText,
          },
        );
      
        appendLog(`⚙️ ${payload.tool} ${payload.status} (${payload.elapsedMs} ms)`);
        return;
      }

      if (type === "control") {
        const { action } = payload;
        logger.debug("🎮 Control message received:", action);
        
        if (action === "tts_cancelled" || action === "audio_stop") {
          logger.debug(`🔇 Control audio stop received (${action}) - clearing audio queue`);
          const meta = {
            reason: payload.reason,
            trigger: payload.trigger,
            at: payload.at,
            action,
          };
          const event = recordBargeInEvent(action, meta);
          interruptAssistantOutput(meta);
          if (action === "audio_stop" && event) {
            finalizeBargeInClear(event);
          }
          return;
        }

        logger.debug("🎮 Unknown control action:", action);
        return;
      }
    };

    handleSocketMessageRef.current = handleSocketMessage;
  
  /* ------------------------------------------------------------------ *
   *  OUTBOUND ACS CALL
   * ------------------------------------------------------------------ */
  const openRelaySocket = useCallback((targetSessionId, options = {}) => {
    const { reason = "manual", suppressLog = false } = options;
    if (!targetSessionId) {
      return null;
    }

    const lifecycle = callLifecycleRef.current;
    if (relayReconnectTimeoutRef.current && typeof window !== "undefined") {
      window.clearTimeout(relayReconnectTimeoutRef.current);
      relayReconnectTimeoutRef.current = null;
    }
    lifecycle.reconnectScheduled = false;

    try {
      const encodedSession = encodeURIComponent(targetSessionId);
      const relayUrl = `${WS_URL}/api/v1/realtime/dashboard/relay?session_id=${encodedSession}`;
      closeRelaySocket(`${reason || "manual"} reopen`, { preserveLifecycle: true });
      if (!suppressLog) {
        appendLog(`Connecting relay WS (${reason})`);
      }

      const relay = new WebSocket(relayUrl);
      relaySocketRef.current = relay;
      lifecycle.lastRelayOpenedAt = Date.now();

      relay.onopen = () => {
        appendLog("Relay WS connected");
        lifecycle.reconnectAttempts = 0;
        lifecycle.reconnectScheduled = false;
        lifecycle.stalledLoggedAt = null;
        lifecycle.lastEnvelopeAt = Date.now();
      };

      relay.onerror = (error) => {
        logger.error("Relay WS error:", error);
        appendLog("Relay WS error");
      };

      relay.onmessage = ({ data }) => {
        lifecycle.lastEnvelopeAt = Date.now();
        try {
          const obj = JSON.parse(data);
          let processedObj = obj;

          if (obj && obj.type && obj.sender && obj.payload && obj.ts) {
            logger.debug("📨 Relay received envelope message:", {
              type: obj.type,
              sender: obj.sender,
              topic: obj.topic,
            });

            processedObj = {
              type: obj.type,
              sender: obj.sender,
              ...obj.payload,
            };
            logger.debug("📨 Transformed relay envelope:", processedObj);
          }

          const handler = handleSocketMessageRef.current;
          if (handler) {
            handler({ data: JSON.stringify(processedObj) });
          }
        } catch (error) {
          logger.error("Relay parse error:", error);
          appendLog("Relay parse error");
        }
      };

      relay.onclose = (event) => {
        if (relaySocketRef.current === relay) {
          relaySocketRef.current = null;
        }

        const state = callLifecycleRef.current;
        const pending = state.pending;
        const code = event?.code;
        const reasonText = event?.reason;

        if (!pending) {
          appendLog("Relay WS disconnected");
          setCallActive(false);
          setActiveSpeaker(null);
          return;
        }

        const details = [code ?? "no code"];
        if (reasonText) {
          details.push(reasonText);
        }
        appendLog(`Relay WS closed (${details.join(": ")}) – scheduling retry`);

        state.reconnectAttempts = Math.min(state.reconnectAttempts + 1, 6);
        state.reconnectScheduled = true;

        if (typeof window !== "undefined") {
          const baseDelay = 800;
          const delay = Math.min(10000, baseDelay * Math.pow(2, state.reconnectAttempts - 1));
          if (relayReconnectTimeoutRef.current) {
            window.clearTimeout(relayReconnectTimeoutRef.current);
          }
          relayReconnectTimeoutRef.current = window.setTimeout(() => {
            relayReconnectTimeoutRef.current = null;
            state.reconnectScheduled = false;
            if (!callLifecycleRef.current.pending) {
              return;
            }
            const opener = openRelaySocketRef.current;
            if (opener) {
              opener(targetSessionId, { reason: "auto-reconnect", suppressLog: true });
            }
          }, delay);
        }
      };

      return relay;
    } catch (error) {
      logger.error("Failed to open relay websocket:", error);
      appendLog("Relay WS open failed");
      return null;
    }
  }, [appendLog, closeRelaySocket, setActiveSpeaker, setCallActive]);

  openRelaySocketRef.current = openRelaySocket;

  useEffect(() => {
    if (typeof window === "undefined") {
      return undefined;
    }

    const interval = window.setInterval(() => {
      const lifecycle = callLifecycleRef.current;
      if (!lifecycle.pending) {
        return;
      }

      const relay = relaySocketRef.current;
      const sessionKey = sessionId || getOrCreateSessionId();
      const now = Date.now();

      if (!relay || relay.readyState !== WebSocket.OPEN) {
        if (!lifecycle.reconnectScheduled) {
          lifecycle.reconnectScheduled = true;
          lifecycle.reconnectAttempts = Math.min(lifecycle.reconnectAttempts + 1, 6);
          const baseDelay = 800;
          const delay = Math.min(10000, baseDelay * Math.pow(2, lifecycle.reconnectAttempts - 1));
          if (relayReconnectTimeoutRef.current) {
            window.clearTimeout(relayReconnectTimeoutRef.current);
          }
          relayReconnectTimeoutRef.current = window.setTimeout(() => {
            relayReconnectTimeoutRef.current = null;
            lifecycle.reconnectScheduled = false;
            if (!callLifecycleRef.current.pending) {
              return;
            }
            const opener = openRelaySocketRef.current;
            if (opener) {
              opener(sessionKey, { reason: "monitor-reconnect", suppressLog: true });
            }
          }, delay);
        }
        return;
      }

      lifecycle.reconnectAttempts = 0;

      if (lifecycle.lastEnvelopeAt && now - lifecycle.lastEnvelopeAt > 15000) {
        if (!lifecycle.stalledLoggedAt || now - lifecycle.stalledLoggedAt > 15000) {
          appendLog("⚠️ No ACS updates in 15s — refreshing relay subscription.");
          lifecycle.stalledLoggedAt = now;
        }
        const opener = openRelaySocketRef.current;
        if (opener) {
          opener(sessionKey, { reason: "envelope-timeout", suppressLog: true });
        }
        lifecycle.lastEnvelopeAt = Date.now();
      }
    }, 6000);

    relayHealthIntervalRef.current = interval;

    return () => {
      if (relayHealthIntervalRef.current && typeof window !== "undefined") {
        window.clearInterval(relayHealthIntervalRef.current);
        relayHealthIntervalRef.current = null;
      }
    };
  }, [appendLog, sessionId]);

  const startACSCall = async () => {
    if (systemStatus.status === "degraded" && systemStatus.acsOnlyIssue) {
      appendLog("🚫 Outbound calling disabled until ACS configuration is provided.");
      return;
    }
    if (!/^\+\d+$/.test(targetPhoneNumber)) {
      alert("Enter phone in E.164 format e.g. +15551234567");
      return;
    }
    try {
      // Get the current session ID for this browser session
      const currentSessionId = getOrCreateSessionId();
      logger.info(
        `📞 [FRONTEND] Initiating phone call with session_id: ${currentSessionId} (streaming_mode=${selectedStreamingMode})`,
      );
      logger.debug(
        '📞 [FRONTEND] This session_id will be sent to backend for call mapping',
      );
      
      const res = await fetch(`${API_BASE_URL}/api/v1/calls/initiate`, {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body: JSON.stringify({ 
          target_number: targetPhoneNumber,
          streaming_mode: selectedStreamingMode,
          context: {
            browser_session_id: currentSessionId,  // 🎯 Pass browser session ID for ACS coordination
            streaming_mode: selectedStreamingMode,
          }
        }),
      });
      const json = await res.json();
      if (!res.ok) {
        appendLog(`Call error: ${json.detail||res.statusText}`);
        resetCallLifecycle();
        return;
      }
      const newCallId = json.call_id ?? json.callId ?? null;
      setCurrentCallId(newCallId);
      if (!newCallId) {
        appendLog("⚠️ Call initiated but call_id missing from response");
      }
      // show in chat with dedicated system card
      const readableMode = selectedStreamingModeLabel || selectedStreamingMode;
      appendSystemMessage("📞 Call started", {
        tone: "call",
        statusCaption: `→ ${targetPhoneNumber} · Mode: ${readableMode}`,
        statusLabel: "Call Initiated",
      });
      appendLog(`📞 Call initiated (mode: ${readableMode})`);
      setShowPhoneInput(false);
      const lifecycle = callLifecycleRef.current;
      lifecycle.pending = true;
      lifecycle.active = false;
      lifecycle.callId = newCallId ?? null;
      lifecycle.lastEnvelopeAt = Date.now();
      lifecycle.reconnectAttempts = 0;
      lifecycle.reconnectScheduled = false;
      lifecycle.stalledLoggedAt = null;
      lifecycle.lastRelayOpenedAt = 0;

      logger.info('🔗 [FRONTEND] Starting dashboard relay WebSocket to monitor session:', currentSessionId);
      openRelaySocket(currentSessionId, { reason: "call-start" });
    } catch(e) {
      appendLog(`Network error starting call: ${e.message}`);
      resetCallLifecycle();
    }
  };

  /* ------------------------------------------------------------------ *
   *  RENDER
   * ------------------------------------------------------------------ */
  return (
    <div style={styles.root}>
      <div style={styles.mainContainer}>
        <IndustryTag />
        <div style={styles.helpButtonDock}>
          <DemoScenariosWidget inline />
          <HelpButton />
        </div>
        <div style={styles.backendIndicatorDock}>
          <BackendIndicator url={API_BASE_URL} onStatusChange={handleSystemStatus} />
        </div>
        <div style={styles.mainShell}>

          {/* App Header */}
          <div style={styles.appHeader}>
            <div style={styles.appHeaderIdentity}>
              <div style={styles.appTitleBlock}>
                <h1 style={styles.appTitle}>🎙️ ARTAgent</h1>
                <p style={styles.appSubtitle}>Transforming customer interactions with real-time, intelligent voice experiences.</p>
              </div>
            </div>

            <div style={styles.appHeaderFooter}>
              <div style={styles.sessionTag}>
                <span style={styles.sessionTagIcon}>💬</span>
                <div>
                  <div style={styles.sessionTagLabel}>Active Session</div>
                  <code style={styles.sessionTagValue}>{sessionId}</code>
                </div>
              </div>

              <div style={styles.appHeaderActions}>
                {hasActiveProfile ? (
                  <ProfileButton
                    profile={activeSessionProfile}
                    highlight={profileHighlight}
                    onCreateProfile={openDemoForm}
                    onTogglePanel={() => setShowProfilePanel((prev) => !prev)}
                  />
                ) : (
                  <Button
                    variant="contained"
                    disableElevation
                    startIcon={<BoltRoundedIcon fontSize="small" />}
                    onMouseEnter={() => setCreateProfileHovered(true)}
                    onMouseLeave={() => setCreateProfileHovered(false)}
                    onClick={openDemoForm}
                    sx={{
                      ...styles.createProfileButton,
                      ...(createProfileHovered ? styles.createProfileButtonHover : {}),
                    }}
                  >
                    Create Demo Profile
                  </Button>
                )}
              </div>
            </div>
          </div>

            {/* Waveform Section */}
            <div style={styles.waveformSection}>
              <WaveformVisualization 
                activeSpeaker={activeSpeaker} 
                audioLevelRef={audioLevelRef}
                outputAudioLevelRef={outputAudioLevelRef}
              />
              <div style={styles.sectionDivider}></div>
            </div>

            {/* Chat Messages */}
            <div style={styles.chatSection} ref={chatRef}>
              <div style={styles.chatSectionIndicator}></div>
              <div style={styles.messageContainer} ref={messageContainerRef}>
                {messages.map((message, index) => (
                  <ChatBubble key={index} message={message} />
                ))}
              </div>
            </div>

            {/* Text Input - Shows above controls when recording */}
            {recording && (
              <div style={styles.textInputContainer}>
                <input
                  type="text"
                  value={textInput}
                  onChange={(e) => setTextInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && textInput.trim()) handleSendText();
                  }}
                  placeholder="Type your message here..."
                  style={styles.textInput}
                />
                <IconButton 
                  onClick={handleSendText} 
                  disabled={!textInput.trim()}
                  disableRipple
                  sx={{
                    width: "48px",
                    height: "48px",
                    minWidth: "48px",
                    borderRadius: "50%",
                    padding: 0,
                    background: textInput.trim() 
                      ? "linear-gradient(135deg, #10b981, #059669)" 
                      : "linear-gradient(135deg, #f1f5f9, #e2e8f0)",
                    color: textInput.trim() ? "white" : "#cbd5e1",
                    border: textInput.trim() ? "none" : "1px solid #e2e8f0",
                    boxShadow: textInput.trim() 
                      ? "0 4px 14px rgba(16,185,129,0.3), inset 0 1px 2px rgba(255,255,255,0.2)" 
                      : "0 2px 6px rgba(0,0,0,0.06)",
                    transition: "all 0.25s cubic-bezier(0.4, 0, 0.2, 1)",
                    cursor: textInput.trim() ? "pointer" : "not-allowed",
                    '&:hover': textInput.trim() ? {
                      background: "linear-gradient(135deg, #059669, #047857)",
                      transform: "scale(1.08) translateY(-1px)",
                      boxShadow: "0 8px 20px rgba(16,185,129,0.4), 0 0 0 3px rgba(16,185,129,0.15), inset 0 1px 2px rgba(255,255,255,0.2)",
                    } : {},
                    '&:active': textInput.trim() ? {
                      transform: "scale(1.02) translateY(0px)",
                      boxShadow: "0 2px 8px rgba(16,185,129,0.3)",
                    } : {},
                    '& svg': {
                      fontSize: '20px',
                      transform: 'translateX(1px)',
                    },
                  }}
                >
                  <SendRoundedIcon />
                </IconButton>
              </div>
            )}

            {/* Control Buttons - Clean 3-button layout */}
            <ConversationControls
              recording={recording}
              callActive={callActive}
              isCallDisabled={isCallDisabled}
              onResetSession={handleResetSession}
              onMicToggle={handleMicToggle}
              micMuted={micMuted}
              onMuteToggle={handleMuteToggle}
              onPhoneButtonClick={handlePhoneButtonClick}
              phoneButtonRef={phoneButtonRef}
              micButtonRef={micButtonRef}
            />

            <div style={styles.realtimeModeDock} ref={realtimePanelAnchorRef} />

        {/* Phone Input Panel */}
      {showPhoneInput && (
        <div ref={phonePanelRef} style={styles.phoneInputSection}>
          <div style={{ marginBottom: '8px', fontSize: '12px', color: '#64748b' }}>
            {callActive ? '📞 Call in progress' : '📞 Enter your phone number to get a call'}
          </div>
          <AcsStreamingModeSelector
            value={selectedStreamingMode}
            onChange={handleStreamingModeChange}
            disabled={callActive || isCallDisabled}
          />
          <div style={styles.phoneInputRow}>
            <input
              type="tel"
              value={targetPhoneNumber}
              onChange={(e) => setTargetPhoneNumber(e.target.value)}
              placeholder="+15551234567"
              style={styles.phoneInput}
              disabled={callActive || isCallDisabled}
            />
            <button
              onClick={callActive ? stopRecognition : startACSCall}
              style={styles.callMeButton(callActive, isCallDisabled)}
              title={
                callActive
                  ? "🔴 Hang up call"
                  : isCallDisabled
                    ? "Configure Azure Communication Services to enable calling"
                    : "📞 Start phone call"
              }
              disabled={callActive || isCallDisabled}
            >
              {callActive ? "🔴 Hang Up" : "📞 Call Me"}
            </button>
          </div>
        </div>
      )}
        {showRealtimeModePanel && typeof document !== 'undefined' &&
          createPortal(
            <div
              ref={realtimePanelRef}
              style={{
                ...styles.realtimeModePanel,
                top: realtimePanelCoords.top,
                left: realtimePanelCoords.left,
              }}
            >
              <RealtimeStreamingModeSelector
                value={selectedRealtimeStreamingMode}
                onChange={handleRealtimeStreamingModeChange}
                disabled={recording}
              />
            </div>,
            document.body,
          )}
        {showDemoForm && typeof document !== 'undefined' &&
          createPortal(
            <>
              <div style={styles.demoFormBackdrop} onClick={closeDemoForm} />
              <div className="demo-form-overlay" style={styles.demoFormOverlay}>
                <TemporaryUserForm
                  apiBaseUrl={API_BASE_URL}
                  onClose={closeDemoForm}
                  sessionId={sessionId}
                  onSuccess={handleDemoCreated}
                />
              </div>
            </>,
            document.body
          )
        }
      </div>
    </div>
    <ProfileDetailsPanel
      profile={activeSessionProfile}
      sessionId={sessionId}
      open={showProfilePanel}
      onClose={() => setShowProfilePanel(false)}
    />
  </div>
);
}

// Main App component wrapper
function App() {
  return <RealTimeVoiceApp />;
}

export default App;
