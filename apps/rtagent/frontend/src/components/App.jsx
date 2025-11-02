import React, { useCallback, useEffect, useRef, useState } from 'react';
import "reactflow/dist/style.css";
import UserSwitcher from './UserSwitcher';

// Environment configuration
const backendPlaceholder = '__BACKEND_URL__';
const API_BASE_URL = backendPlaceholder.startsWith('__') 
  ? import.meta.env.VITE_BACKEND_BASE_URL || 'http://localhost:8000'
  : backendPlaceholder;

const WS_URL = API_BASE_URL.replace(/^https?/, "wss");

// Session management utilities
const getOrCreateSessionId = () => {
  const sessionKey = 'voice_agent_session_id';
  let sessionId = sessionStorage.getItem(sessionKey);
  
  if (!sessionId) {
    const tabId = Math.random().toString(36).substr(2, 6);
    sessionId = `session_${Date.now()}_${tabId}`;
    sessionStorage.setItem(sessionKey, sessionId);
    console.log('Created NEW tab-specific session ID:', sessionId);
  } else {
    console.log('Retrieved existing tab session ID:', sessionId);
  }
  
  return sessionId;
};

const createNewSessionId = () => {
  const sessionKey = 'voice_agent_session_id';
  const tabId = Math.random().toString(36).substr(2, 6);
  const sessionId = `session_${Date.now()}_${tabId}`;
  sessionStorage.setItem(sessionKey, sessionId);
  console.log('Created NEW session ID for reset:', sessionId);
  return sessionId;
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
  },

  appHeader: {
    backgroundColor: "#e0f2fe",
    background: "linear-gradient(135deg, #dbeafe 0%, #e0f2fe 50%, #f0f9ff 100%)",
    padding: "16px 24px 12px 24px",
    borderBottom: "1px solid #bae6fd",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    position: "relative",
    boxShadow: "0 2px 8px rgba(56, 189, 248, 0.1)",
  },

  appTitleContainer: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: "4px",
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
    fontSize: "19px",
    fontWeight: "700",
    background: "linear-gradient(135deg, #0369a1, #0284c7)",
    WebkitBackgroundClip: "text",
    WebkitTextFillColor: "transparent",
    backgroundClip: "text",
    textAlign: "center",
    margin: 0,
    letterSpacing: "0.3px",
  },

  appSubtitle: {
    fontSize: "12px",
    fontWeight: "500",
    color: "#0369a1",
    textAlign: "center",
    margin: 0,
    letterSpacing: "0.2px",
    maxWidth: "350px",
    lineHeight: "1.3",
    opacity: 0.85,
  },
  waveformSection: {
    backgroundColor: "#f1f5f9",
    background: "linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%)",
    padding: "12px 4px",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    borderBottom: "1px solid #e2e8f0",
    height: "22%",
    minHeight: "90px",
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
  
  // Section divider line - more subtle
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
    height: "60%",
    padding: "0 10px",
    background: "radial-gradient(ellipse at center, rgba(100, 116, 139, 0.05) 0%, transparent 70%)",
    borderRadius: "6px",
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
    backgroundColor: "#f0f9ff",
    background: "linear-gradient(180deg, #f0f9ff 0%, #e0f2fe 100%)",
    borderBottom: "1px solid #bae6fd",
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
    gap: "16px",
    flex: 1,
    overflowY: "auto",
    padding: "0",
  },
  
  userMessage: {
    alignSelf: "flex-start",
    maxWidth: "70%",
    marginLeft: "8px",
    marginBottom: "8px",
  },
  
  userBubble: {
    background: "linear-gradient(135deg, #3b82f6, #2563eb)",
    color: "#ffffff",
    padding: "12px 18px",
    borderRadius: "18px 18px 18px 4px",
    fontSize: "15px",
    lineHeight: "1.5",
    border: "none",
    boxShadow: "0 2px 12px rgba(59, 130, 246, 0.25)",
    wordWrap: "break-word",
    overflowWrap: "break-word",
    hyphens: "auto",
    whiteSpace: "pre-wrap",
    fontWeight: "400",
  },
  
  // Assistant message (right aligned - grey bubble)
  assistantMessage: {
    alignSelf: "flex-end",
    maxWidth: "75%",
    marginRight: "8px",
    marginBottom: "8px",
  },
  
  assistantBubble: {
    background: "#f3f4f6",
    color: "#1f2937",
    padding: "12px 18px",
    borderRadius: "18px 18px 4px 18px",
    fontSize: "15px",
    lineHeight: "1.5",
    boxShadow: "0 2px 8px rgba(0, 0, 0, 0.06)",
    wordWrap: "break-word",
    overflowWrap: "break-word",
    hyphens: "auto",
    whiteSpace: "pre-wrap",
    border: "1px solid #e5e7eb",
    fontWeight: "400",
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
  
  // Compact control section - smaller buttons, more space for chat
  controlSection: {
    padding: "12px",
    backgroundColor: "#f8fafc",
    background: "linear-gradient(180deg, #f8fafc 0%, #e2e8f0 100%)",
    display: "flex",
    justifyContent: "center",
    alignItems: "center",
    minHeight: "70px",
    borderTop: "1px solid #e1e7ef",
    position: "relative",
    boxShadow: "inset 0 1px 0 rgba(255, 255, 255, 0.8)",
  },
  
  controlContainer: {
    display: "flex",
    gap: "16px",
    background: "white",
    padding: "8px 16px",
    borderRadius: "20px",
    boxShadow: "0 2px 8px rgba(100, 116, 139, 0.1)",
    border: "1px solid #e2e8f0",
    width: "fit-content",
  },
  
  controlButton: (isActive, variant = 'default') => {
    // Base styles for all buttons
    return {
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
      boxShadow: isActive ? 
        "0 6px 20px rgba(16,185,129,0.3), 0 0 0 3px rgba(16,185,129,0.1)" : 
        "0 2px 8px rgba(0,0,0,0.08)",
    };
  },

  // Compact button styles - smaller size for cleaner layout
  resetButton: (isActive, isHovered) => ({
    width: "44px", // Reduced from 56px
    height: "44px", // Reduced from 56px
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
    transform: isHovered ? "scale(1.08)" : (isActive ? "scale(1.05)" : "scale(1)"),
    boxShadow: isHovered ? 
      "0 8px 24px rgba(100,116,139,0.3), 0 0 0 3px rgba(100,116,139,0.15)" :
      (isActive ? 
        "0 6px 20px rgba(16,185,129,0.3), 0 0 0 3px rgba(16,185,129,0.1)" : 
        "0 2px 8px rgba(0,0,0,0.08)"),
  }),

  micButton: (isActive, isHovered) => ({
    width: "44px", // Reduced from 56px
    height: "44px", // Reduced from 56px
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
      (isActive ? "white" : "#16a34a") :
      (isActive ? "#10b981" : "#64748b"),
    transform: isHovered ? "scale(1.08)" : (isActive ? "scale(1.05)" : "scale(1)"),
    boxShadow: isHovered ? 
      "0 8px 25px rgba(16,185,129,0.4), 0 0 0 4px rgba(16,185,129,0.15), inset 0 1px 2px rgba(255,255,255,0.2)" :
      (isActive ? 
        "0 6px 20px rgba(16,185,129,0.3), 0 0 0 3px rgba(16,185,129,0.1)" : 
        "0 2px 8px rgba(0,0,0,0.08)"),
  }),

  phoneButton: (isActive, isHovered, isDisabled = false) => {
    const base = {
      width: "44px", // Reduced from 56px
      height: "44px", // Reduced from 56px
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
      background: isHovered ? 
        (isActive ? "linear-gradient(135deg, #3f75a8ff, #2b5d8f)" : "linear-gradient(135deg, #dcfce7, #bbf7d0)") :
        "linear-gradient(135deg, #f1f5f9, #e2e8f0)",
      color: isHovered ? 
        (isActive ? "white" : "#3f75a8ff") :
        (isActive ? "#3f75a8ff" : "#64748b"),
      transform: isHovered ? "scale(1.08)" : (isActive ? "scale(1.05)" : "scale(1)"),
      boxShadow: isHovered ? 
        "0 8px 25px rgba(16,185,129,0.4), 0 0 0 4px rgba(16,185,129,0.15), inset 0 1px 2px rgba(255,255,255,0.2)" :
        (isActive ? 
          "0 6px 20px rgba(16,185,129,0.3), 0 0 0 3px rgba(16,185,129,0.1)" : 
          "0 2px 8px rgba(0,0,0,0.08)"),
    };
  },

  // Tooltip styles
  buttonTooltip: {
    position: 'absolute',
    bottom: '-45px',
    left: '50%',
    transform: 'translateX(-50%)',
    background: 'rgba(51, 65, 85, 0.95)',
    color: '#f1f5f9',
    padding: '8px 12px',
    borderRadius: '8px',
    fontSize: '11px',
    fontWeight: '500',
    whiteSpace: 'nowrap',
    backdropFilter: 'blur(10px)',
    boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
    border: '1px solid rgba(255,255,255,0.1)',
    pointerEvents: 'none',
    opacity: 0,
    transition: 'opacity 0.2s ease, transform 0.2s ease',
    zIndex: 1000,
  },

  buttonTooltipVisible: {
    opacity: 1,
    transform: 'translateX(-50%) translateY(-2px)',
  },
  
  // Input section for phone calls
  phoneInputSection: {
    position: "absolute",
    bottom: "60px", // Moved lower from 140px to 60px to avoid blocking chat bubbles
    left: "500px", // Moved further to the right from 400px to 500px
    background: "white",
    padding: "20px",
    borderRadius: "20px", // More rounded - changed from 16px to 20px
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
    borderRadius: "12px", // More rounded - changed from 8px to 12px
    fontSize: "14px",
    outline: "none",
    transition: "border-color 0.2s ease, box-shadow 0.2s ease",
    "&:focus": {
      borderColor: "#10b981",
      boxShadow: "0 0 0 3px rgba(16,185,129,0.1)"
    }
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
    background: isDisabled ? "linear-gradient(135deg, #e2e8f0, #cbd5e1)" : (isActive ? "#ef4444" : "#67d8ef"),
    color: isDisabled ? "#94a3b8" : "white",
    border: "none",
    borderRadius: "8px", // More box-like - less rounded
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

  industryTag: {
    position: "absolute",
    top: "40px",
    left: "20px",
    padding: "8px 14px",
    borderRadius: "18px",
    border: "none",
    background: "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
    color: "white",
    fontSize: "10px",
    fontWeight: "600",
    textTransform: "uppercase",
    letterSpacing: "0.8px",
    boxShadow: "0 4px 15px rgba(102, 126, 234, 0.4), 0 2px 4px rgba(0,0,0,0.1)",
    zIndex: 1000,
    userSelect: "none",
    backdropFilter: "blur(10px)",
    transition: "all 0.3s ease",
    whiteSpace: "nowrap",
    maxWidth: "fit-content",
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

  // Always visible chat interface - proper proportions
  chatInterface: {
    display: "flex",
    flexDirection: "column",
    flex: 1,
    width: "100%",
    background: "linear-gradient(to bottom, #f8fafc 0%, #ffffff 100%)",
    overflow: "hidden",
  },

  chatMessagesArea: {
    flex: 1,
    padding: "28px 32px",
    overflowY: "auto",
    background: "transparent",
    scrollBehavior: "smooth",
    position: "relative",
  },

  chatInputSection: {
    padding: "16px 24px 20px 24px",
    borderTop: "1px solid #e2e8f0",
    background: "#ffffff",
    boxShadow: "0 -2px 10px rgba(0, 0, 0, 0.03)",
  },

  chatInputContainer: {
    display: "flex",
    alignItems: "flex-end",
    gap: "8px",
    maxWidth: "800px",
    margin: "0 auto",
    position: "relative",
  },

  chatTextInput: {
    width: "100%",
    padding: "12px 16px",
    border: "1px solid #d1d5db",
    borderRadius: "20px",
    fontSize: "15px",
    lineHeight: "1.5",
    background: "#f9fafb",
    resize: "none",
    minHeight: "44px",
    maxHeight: "120px",
    outline: "none",
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
    color: "#111827",
    transition: "all 0.2s ease",
  },

  chatInputWrapper: {
    flex: 1,
    position: "relative",
  },

  chatButtonStack: {
    display: "flex",
    flexDirection: "row",
    gap: "6px",
    alignItems: "center",
    flexShrink: 0,
  },

  chatAttachButton: {
    width: "36px",
    height: "36px",
    borderRadius: "50%",
    border: "1px solid #e2e8f0",
    background: "#ffffff",
    color: "#6b7280",
    fontSize: "16px",
    cursor: "pointer",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    transition: "all 0.2s ease",
    flexShrink: 0,
  },

  chatSendButton: {
    width: "36px",
    height: "36px",
    borderRadius: "50%",
    border: "none",
    background: "#3b82f6",
    color: "white",
    fontSize: "18px",
    fontWeight: "bold",
    cursor: "pointer",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    transition: "all 0.2s ease",
    flexShrink: 0,
    boxShadow: "0 1px 3px rgba(0, 0, 0, 0.1)",
  },

  chatButton: (isActive, isHovered) => ({
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
      (isActive ? "linear-gradient(135deg, #3b82f6, #2563eb)" : "linear-gradient(135deg, #dcfce7, #bbf7d0)") :
      "linear-gradient(135deg, #f1f5f9, #e2e8f0)",
    color: isHovered ? 
      (isActive ? "white" : "#3b82f6") :
      (isActive ? "#3b82f6" : "#64748b"),
    transform: isHovered ? "scale(1.08)" : (isActive ? "scale(1.05)" : "scale(1)"),
    boxShadow: isHovered ? 
      "0 8px 25px rgba(59,130,246,0.4), 0 0 0 4px rgba(59,130,246,0.15), inset 0 1px 2px rgba(255,255,255,0.2)" :
      (isActive ? 
        "0 6px 20px rgba(59,130,246,0.3), 0 0 0 3px rgba(59,130,246,0.1)" : 
        "0 2px 8px rgba(0,0,0,0.08)"),
  }),
};
// Add keyframe animation and input styles
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
  
  /* Chat input focus and hover styles */
  textarea:focus {
    border-color: #3b82f6 !important;
    box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.12), 0 4px 12px rgba(0, 0, 0, 0.08) !important;
    background: #ffffff !important;
  }
  
  textarea:hover {
    border-color: #6b7280 !important;
    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.06), inset 0 1px 0 rgba(255, 255, 255, 0.9) !important;
  }
  
  /* Send button hover effect */
  button[title="Send message"]:hover {
    background: linear-gradient(135deg, #2563eb, #1d4ed8) !important;
    transform: scale(1.06) !important;
    box-shadow: 0 6px 20px rgba(59, 130, 246, 0.4) !important;
  }
  
  button[title="Send message"]:disabled {
    background: linear-gradient(135deg, #d1d5db, #9ca3af) !important;
    cursor: not-allowed !important;
    transform: scale(1) !important;
    box-shadow: none !important;
  }
  
  /* Attachment button hover effect */
  button[title="Attach file (coming soon)"]:hover {
    background: linear-gradient(135deg, #4b5563, #374151) !important;
    transform: scale(1.05) !important;
    box-shadow: 0 4px 12px rgba(107, 114, 128, 0.3) !important;
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
 *  HELP BUTTON COMPONENT
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
        position: 'relative',
        display: 'inline-block'
      }}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={handleMouseLeave}
      onClick={handleClick}
    >
      <button
        style={{
          width: '44px',
          height: '44px',
          borderRadius: '50%',
          border: '2px solid #e2e8f0',
          background: isHovered ? '#eff6ff' : '#ffffff',
          color: isHovered ? '#3b82f6' : '#64748b',
          fontSize: '20px',
          fontWeight: 'bold',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
          boxShadow: isHovered 
            ? '0 6px 16px rgba(59, 130, 246, 0.2)' 
            : '0 2px 8px rgba(100, 116, 139, 0.12)',
          transform: isHovered ? 'translateY(-2px) scale(1.05)' : 'translateY(0) scale(1)',
        }}
        title="Help & Information"
      >
        ?
      </button>
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
  // Determine branch-based industry tag
  const getIndustryTag = () => {
    const currentBranch = import.meta.env.VITE_BRANCH_NAME || 'finance';
    
    // When promoted to production (main branch) → Insurance Edition
    if (currentBranch === 'main') {
      return 'Insurance Edition';
    } 
    // Retail branch → Retail Edition
    else if (currentBranch.includes('retail')) {
      return 'Retail Edition';
    }
    // Finance/capitalmarkets branches → Finance Edition
    else if (currentBranch.includes('finance') || currentBranch.includes('capitalmarkets')) {
      return 'Finance Edition';
    }
    
    return 'Finance Edition'; // Default fallback
  };

  return (
    <div style={styles.industryTag}>
      {getIndustryTag()}
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
  const [configChanges, setConfigChanges] = useState({});
  const [updateStatus, setUpdateStatus] = useState({});
  const [showStatistics, setShowStatistics] = useState(false);
  const [showAcsHover, setShowAcsHover] = useState(false);
  const [acsTooltipPos, setAcsTooltipPos] = useState(null);
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
      console.error("Readiness check failed:", err);
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
      console.error("Agents check failed:", err);
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
      console.error("Health check failed:", err);
      setHealthData(null);
    }
  };

  // Update agent configuration
  const updateAgentConfig = async (agentName, config) => {
    try {
      setUpdateStatus({...updateStatus, [agentName]: 'updating'});
      
      const response = await fetch(`${url}/api/v1/agents/${agentName}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(config),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const data = await response.json();
      
      setUpdateStatus({...updateStatus, [agentName]: 'success'});
      
      // Refresh agents data
      checkAgents();
      
      // Clear success status after 3 seconds
      setTimeout(() => {
        setUpdateStatus(prev => {
          const newStatus = {...prev};
          delete newStatus[agentName];
          return newStatus;
        });
      }, 3000);
      
      return data;
    } catch (err) {
      console.error("Agent config update failed:", err);
      setUpdateStatus({...updateStatus, [agentName]: 'error'});
      
      // Clear error status after 5 seconds
      setTimeout(() => {
        setUpdateStatus(prev => {
          const newStatus = {...prev};
          delete newStatus[agentName];
          return newStatus;
        });
      }, 5000);
      
      throw err;
    }
  };

  useEffect(() => {
    // Parse and format the URL for display
    try {
      const urlObj = new URL(url);
      const host = urlObj.hostname;
      const protocol = urlObj.protocol.replace(':', '');
      
      // Shorten Azure URLs
      if (host.includes('.azurewebsites.net')) {
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
          {displayUrl}
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
                  color: "#64748b",
                  fontSize: "9px",
                  fontFamily: "monospace",
                  marginBottom: "6px",
                  padding: "3px 6px",
                  backgroundColor: "white",
                  borderRadius: "4px",
                  border: "1px solid #f1f5f9",
                }}>
                  {url}
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
const WaveformVisualization = ({ speaker, audioLevel = 0, outputAudioLevel = 0 }) => {
  const [waveOffset, setWaveOffset] = useState(0);
  const [amplitude, setAmplitude] = useState(5);
  const animationRef = useRef();
  
  useEffect(() => {
    const animate = () => {
      setWaveOffset(prev => (prev + (speaker ? 2 : 1)) % 1000);
      
      setAmplitude(() => {
        // React to actual audio levels first, then fall back to speaker state
        if (audioLevel > 0.01) {
          // User is speaking - use real audio level
          const scaledLevel = audioLevel * 25;
          const smoothVariation = Math.sin(Date.now() * 0.002) * (scaledLevel * 0.2);
          return Math.max(8, scaledLevel + smoothVariation);
        } else if (outputAudioLevel > 0.01) {
          // Assistant is speaking - use output audio level
          const scaledLevel = outputAudioLevel * 20;
          const smoothVariation = Math.sin(Date.now() * 0.0018) * (scaledLevel * 0.25);
          return Math.max(6, scaledLevel + smoothVariation);
        } else if (speaker) {
          // Active speaking fallback - gentle rhythmic movement
          const time = Date.now() * 0.002;
          const baseAmplitude = 10;
          const rhythmicVariation = Math.sin(time) * 5;
          return baseAmplitude + rhythmicVariation;
        } else {
          // Idle state - gentle breathing pattern
          const time = Date.now() * 0.0008;
          const breathingAmplitude = 3 + Math.sin(time) * 1.5;
          return breathingAmplitude;
        }
      });
      
      animationRef.current = requestAnimationFrame(animate);
    };
    
    animationRef.current = requestAnimationFrame(animate);
    
    return () => {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
    };
  }, [speaker, audioLevel, outputAudioLevel]);
  
  const generateWavePath = () => {
    const width = 750;
    const height = 100;
    const centerY = height / 2;
    const frequency = 0.02;
    const points = 100;
    
    let path = `M 0 ${centerY}`;
    
    for (let i = 0; i <= points; i++) {
      const x = (i / points) * width;
      const y = centerY + Math.sin((x * frequency + waveOffset * 0.1)) * amplitude;
      path += ` L ${x} ${y}`;
    }
    
    return path;
  };

  // Secondary wave
  const generateSecondaryWave = () => {
    const width = 750;
    const height = 100;
    const centerY = height / 2;
    const frequency = 0.025;
    const points = 100;
    
    let path = `M 0 ${centerY}`;
    
    for (let i = 0; i <= points; i++) {
      const x = (i / points) * width;
      const y = centerY + Math.sin((x * frequency + waveOffset * 0.12)) * (amplitude * 0.6);
      path += ` L ${x} ${y}`;
    }
    
    return path;
  };

  // Wave rendering
  const generateMultipleWaves = () => {
    const waves = [];
    
    let baseColor, opacity;
    if (speaker === "User") {
      baseColor = "#ef4444";
      opacity = 0.8;
    } else if (speaker === "Assistant") {
      baseColor = "#67d8ef";
      opacity = 0.8;
    } else {
      baseColor = "#3b82f6";
      opacity = 0.4;
    }
    
    // Main wave
    waves.push(
      <path
        key="wave1"
        d={generateWavePath()}
        stroke={baseColor}
        strokeWidth={speaker ? "3" : "2"}
        fill="none"
        opacity={opacity}
        strokeLinecap="round"
      />
    );
    
    // Secondary wave
    waves.push(
      <path
        key="wave2"
        d={generateSecondaryWave()}
        stroke={baseColor}
        strokeWidth={speaker ? "2" : "1.5"}
        fill="none"
        opacity={opacity * 0.5}
        strokeLinecap="round"
      />
    );
    
    return waves;
  };
  
  return (
    <div style={styles.waveformContainer}>
      <svg style={styles.waveformSvg} viewBox="0 0 750 80" preserveAspectRatio="xMidYMid meet">
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
          Input: {(audioLevel * 100).toFixed(1)}% | Amp: {amplitude.toFixed(1)}
        </div>
      )}
    </div>
  );
};

/* ------------------------------------------------------------------ *
 *  CHAT BUBBLE
 * ------------------------------------------------------------------ */
const ChatBubble = ({ message }) => {
  const { speaker, text, isTool, streaming } = message;
  const isUser = speaker === "User";
  const isSpecialist = speaker?.includes("Specialist");
  const isAuthAgent = speaker === "Auth Agent";
  
  if (isTool) {
    return (
      <div style={{ ...styles.assistantMessage, alignSelf: "center" }}>
        <div style={{
          ...styles.assistantBubble,
          background: "#8b5cf6",
          textAlign: "center",
          fontSize: "14px",
        }}>
          {text}
        </div>
      </div>
    );
  }
  
  return (
    <div style={isUser ? styles.userMessage : styles.assistantMessage}>
      {/* Show agent name for specialist agents and auth agent */}
      {!isUser && (isSpecialist || isAuthAgent) && (
        <div style={styles.agentNameLabel}>
          {speaker}
        </div>
      )}
      <div style={isUser ? styles.userBubble : styles.assistantBubble}>
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
  const [isMuted, setIsMuted] = useState(true); // Start muted by default
  const [targetPhoneNumber, setTargetPhoneNumber] = useState("");
  const [callActive, setCallActive] = useState(false);
  const [activeSpeaker, setActiveSpeaker] = useState(null);
  const [showPhoneInput, setShowPhoneInput] = useState(false);
  const [systemStatus, setSystemStatus] = useState({
    status: "checking",
    acsOnlyIssue: false,
  });
  const handleSystemStatus = useCallback((nextStatus) => {
    setSystemStatus((prev) =>
      prev.status === nextStatus.status && prev.acsOnlyIssue === nextStatus.acsOnlyIssue
        ? prev
        : nextStatus
    );
  }, []);

  // Chat mode state
  const [chatMode, setChatMode] = useState(false);
  const [chatInput, setChatInput] = useState('');

  // User management state
  const [currentUser, setCurrentUser] = useState(null);
  const [availableUsers, setAvailableUsers] = useState([]);
  const [isLoadingUser, setIsLoadingUser] = useState(false);
  
  // Profile cache for production - avoid redundant API calls
  const profileCacheRef = useRef(new Map());

  // Tooltip states
  const [showResetTooltip, setShowResetTooltip] = useState(false);
  const [showMicTooltip, setShowMicTooltip] = useState(false);
  const [showPhoneTooltip, setShowPhoneTooltip] = useState(false);
  const [showChatTooltip, setShowChatTooltip] = useState(false);

  // Hover states
  const [resetHovered, setResetHovered] = useState(false);
  const [micHovered, setMicHovered] = useState(false);
  const [phoneHovered, setPhoneHovered] = useState(false);
  const [chatHovered, setChatHovered] = useState(false);
  const [phoneDisabledPos, setPhoneDisabledPos] = useState(null);
  const isCallDisabled =
    systemStatus.status === "degraded" && systemStatus.acsOnlyIssue;

  useEffect(() => {
    if (isCallDisabled) {
      setShowPhoneInput(false);
    } else if (phoneDisabledPos) {
      setPhoneDisabledPos(null);
    }
  }, [isCallDisabled, phoneDisabledPos]);

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
  const phoneButtonRef = useRef(null);

  // Audio processing refs
  const audioContextRef = useRef(null);
  const processorRef = useRef(null);
  const analyserRef = useRef(null);
  const micStreamRef = useRef(null);
  const isMutedRef = useRef(true); // Track mute state in ref for audio processing
  const recordingRef = useRef(false); // Track recording state for TTS control
  
  // Audio playback refs for AudioWorklet
  const playbackAudioContextRef = useRef(null);
  const pcmSinkRef = useRef(null);
  
  const [audioLevel, setAudioLevel] = useState(0);
  const audioLevelRef = useRef(0);

  const workletSource = `
    class PcmSink extends AudioWorkletProcessor {
      constructor() {
        super();
        this.queue = [];
        this.readIndex = 0;
        this.samplesProcessed = 0;
        this.port.onmessage = (e) => {
          if (e.data?.type === 'push') {
            // payload is Float32Array
            this.queue.push(e.data.payload);
            console.log('AudioWorklet: Received audio chunk, queue length:', this.queue.length);
          } else if (e.data?.type === 'clear') {
            // Clear all queued audio data for immediate interruption
            this.queue = [];
            this.readIndex = 0;
            console.log('AudioWorklet: Audio queue cleared for barge-in');
          }
        };
      }
      process(inputs, outputs) {
        const out = outputs[0][0]; // mono
        let i = 0;
        while (i < out.length) {
          if (this.queue.length === 0) {
            // no data: output silence
            for (; i < out.length; i++) out[i] = 0;
            break;
          }
          const chunk = this.queue[0];
          const remain = chunk.length - this.readIndex;
          const toCopy = Math.min(remain, out.length - i);
          out.set(chunk.subarray(this.readIndex, this.readIndex + toCopy), i);
          i += toCopy;
          this.readIndex += toCopy;
          if (this.readIndex >= chunk.length) {
            this.queue.shift();
            this.readIndex = 0;
          }
        }
        this.samplesProcessed += out.length;
        return true;
      }
    }
    registerProcessor('pcm-sink', PcmSink);
  `;

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
      
      // Resume on user gesture
      await audioCtx.resume();
      
      playbackAudioContextRef.current = audioCtx;
      pcmSinkRef.current = sink;
      
      appendLog("🔊 Audio playback initialized");
      console.log("AudioWorklet playback system initialized, context sample rate:", audioCtx.sampleRate);
    } catch (error) {
      console.error("Failed to initialize audio playback:", error);
      appendLog("❌ Audio playback init failed");
    }
  };


  const appendLog = m => setLog(p => `${p}\n${new Date().toLocaleTimeString()} - ${m}`);

  const handleUserSwitch = async (newUser) => {
    setIsLoadingUser(true);
    appendLog(`Switching to user: ${newUser.full_name}`);
    
    try {
      const newSessionId = createNewSessionId();
      
      if (socketRef.current) {
        socketRef.current.close();
        socketRef.current = null;
      }
      
      // Use cached profile from availableUsers or wait for WebSocket push
      const cachedProfile = profileCacheRef.current.get(newUser.user_id);
      if (cachedProfile) {
        setCurrentUser({
          ...newUser,
          ...cachedProfile
        });
      } else {
        setCurrentUser(newUser);
      }
      
      setMessages([]);
      setLog('');
      setRecording(false);
      setIsMuted(true);
      setCallActive(false);
      setChatMode(false);
      
      appendLog(`Switched to ${newUser.full_name} (${newUser.loyalty_tier})`);
    } catch (error) {
      console.error('Error during user switch:', error);
      appendLog(`User switch failed: ${error.message}`);
    } finally {
      setIsLoadingUser(false);
    }
  };

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

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (processorRef.current) {
        try { 
          processorRef.current.disconnect(); 
        } catch (e) {
          console.warn("Cleanup error:", e);
        }
      }
      if (audioContextRef.current) {
        try { 
          audioContextRef.current.close(); 
        } catch (e) {
          console.warn("Cleanup error:", e);
        }
      }
      if (playbackAudioContextRef.current) {
        try { 
          playbackAudioContextRef.current.close(); 
        } catch (e) {
          console.warn("Cleanup error:", e);
        }
      }
      if (socketRef.current) {
        try { 
          socketRef.current.close(); 
        } catch (e) {
          console.warn("Cleanup error:", e);
        }
      }
    };
  }, []);

  useEffect(()=>{
    if (log.includes("Call connected"))  setCallActive(true);
    if (log.includes("Call ended"))      setCallActive(false);
  },[log]);

  const startRecognition = async () => {
      appendLog("🎤 Voice mode starting");

      await initializeAudioPlayback();

      const sessionId = getOrCreateSessionId();
      console.log('🔗 [FRONTEND] Starting voice WebSocket with session_id:', sessionId);

      // Close existing WebSocket if switching from text mode
      if (socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
        console.log('🔄 Switching from text to voice mode - reconnecting with TTS enabled');
        socketRef.current.close();
      }

      // 1) open WS with session ID, user_id (if selected), and enable_tts=true for voice mode
      const userId = currentUser?.user_id || '';
      const userParam = userId ? `&user_id=${userId}` : '';
      const socket = new WebSocket(`${WS_URL}/api/v1/realtime/conversation?session_id=${sessionId}&enable_tts=true${userParam}`);
      socket.binaryType = "arraybuffer";

      socket.onopen = () => {
        appendLog("🔌 WS open - Connected to backend with TTS enabled!");
        console.log("WebSocket connection OPENED to backend at:", `${WS_URL}/api/v1/realtime/conversation`);
      };
      socket.onclose = (event) => {
        appendLog(`🔌 WS closed - Code: ${event.code}, Reason: ${event.reason}`);
        console.log("WebSocket connection CLOSED. Code:", event.code, "Reason:", event.reason);
      };
      socket.onerror = (err) => {
        appendLog("❌ WS error - Check if backend is running");
        console.error("WebSocket error - backend might not be running:", err);
      };
      socket.onmessage = handleSocketMessage;
      socketRef.current = socket;

      // 2) setup Web Audio for raw PCM @16 kHz
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
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
        
        // Calculate real-time audio level
        let sum = 0;
        for (let i = 0; i < float32.length; i++) {
          sum += float32[i] * float32[i];
        }
        const rms = Math.sqrt(sum / float32.length);
        const level = Math.min(1, rms * 10); // Scale and clamp to 0-1
        
        audioLevelRef.current = level;
        setAudioLevel(level);

        // Only send audio data if NOT muted
        if (!isMutedRef.current) {
          // Debug: Log a sample of mic data
          console.log("Mic data sample:", float32.slice(0, 10)); // Should show non-zero values if your mic is hot

          const int16 = new Int16Array(float32.length);
          for (let i = 0; i < float32.length; i++) {
            int16[i] = Math.max(-1, Math.min(1, float32[i])) * 0x7fff;
          }

          // Debug: Show size before send
          console.log("Sending int16 PCM buffer, length:", int16.length);

          if (socket.readyState === WebSocket.OPEN) {
            socket.send(int16.buffer);
            // Debug: Confirm data sent
            console.log("PCM audio chunk sent to backend!");
          } else {
            console.log("WebSocket not open, did not send audio.");
          }
        } else {
          console.log("🔇 Microphone muted - not sending audio");
        }
      };

      source.connect(processor);
      processor.connect(audioCtx.destination);
      setRecording(true);
      recordingRef.current = true; // Update ref for TTS control
    };

    const stopRecognition = () => {
      if (processorRef.current) {
        try { 
          processorRef.current.disconnect(); 
        } catch (e) {
          console.warn("Error disconnecting processor:", e);
        }
        processorRef.current = null;
      }
      if (audioContextRef.current) {
        try { 
          audioContextRef.current.close(); 
        } catch (e) {
          console.warn("Error closing audio context:", e);
        }
        audioContextRef.current = null;
      }
      
      if (socketRef.current) {
        try { 
          socketRef.current.close(); 
        } catch (e) {
          console.warn("Error closing socket:", e);
        }
        socketRef.current = null;
      }
      
      // Add session stopped message instead of clearing everything
      setMessages(m => [...m, { 
        speaker: "System", 
        text: "🛑 Session stopped" 
      }]);
      setActiveSpeaker("System");
      setRecording(false);
      recordingRef.current = false; // Update ref for TTS control
      appendLog("🛑 PCM streaming stopped");
    };

    // Function to send text messages in chat mode
    const sendTextMessage = (text) => {
      if (!text.trim()) return;
      
      // Add user message to chat
      const userMessage = {
        speaker: "User",
        text: text.trim()
      };
      setMessages(prev => [...prev, userMessage]);

      // Send message via WebSocket if connected
      if (socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
        const textMessage = {
          type: "text_message",
          text: text.trim(),
          session_id: getOrCreateSessionId()
        };
        socketRef.current.send(JSON.stringify(textMessage));
        console.log("📤 Sent text message:", textMessage);
      } else {
        console.log("🚀 Auto-starting text-only session...");
        // Start WebSocket connection WITHOUT TTS (text-only mode)
        const sessionId = getOrCreateSessionId();
        const userId = currentUser?.user_id || '';
        const userParam = userId ? `&user_id=${userId}` : '';
        const socket = new WebSocket(`${WS_URL}/api/v1/realtime/conversation?session_id=${sessionId}&enable_tts=false${userParam}`);
        socket.binaryType = "arraybuffer"; // Support both text and binary messages
        socketRef.current = socket;
        
        socket.onopen = () => {
          console.log("✅ Text-only WebSocket connected (TTS disabled, same session)");
          appendLog("✅ Text chat session started");
          
          // Send the queued message
          const textMessage = {
            type: "text_message",
            text: text.trim(),
            session_id: sessionId
          };
          socket.send(JSON.stringify(textMessage));
          console.log("📤 Sent queued text message:", textMessage);
        };
        
        socket.onmessage = handleSocketMessage;
        
        socket.onerror = (err) => {
          console.error("WebSocket error:", err);
          appendLog("❌ Connection error");
        };
        
        socket.onclose = () => {
          console.log("WebSocket closed");
          appendLog("🔌 Connection closed");
        };
      }
    };

    const pushIfChanged = (arr, msg) => {
      if (arr.length === 0) return [...arr, msg];
      const last = arr[arr.length - 1];
      if (last.speaker === msg.speaker && last.text === msg.text) return arr;
      return [...arr, msg];
    };

    const handleSocketMessage = async (event) => {

      if (typeof event.data !== "string") {
        const ctx = new AudioContext();
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

      // Handle envelope format from backend
      // If message is in envelope format, extract the actual payload
      if (payload.type && payload.sender && payload.payload && payload.ts) {
        // Extract the actual message from the envelope
        const envelopeType = payload.type;
        const envelopeSender = payload.sender;
        const actualPayload = payload.payload;
        
        // Transform envelope back to legacy format for compatibility
        if (envelopeType === "event" && actualPayload.message) {
          // Status/chat message in envelope
          payload = {
            type: "assistant",
            sender: envelopeSender,
            speaker: envelopeSender,
            message: actualPayload.message,
            content: actualPayload.message
          };
        } else if (envelopeType === "assistant_streaming" && actualPayload.content) {
          // Streaming response in envelope
          payload = {
            type: "assistant_streaming",
            sender: envelopeSender,
            speaker: envelopeSender,
            content: actualPayload.content
          };
        } else if (envelopeType === "status" && actualPayload.message) {
          // Status message in envelope
          payload = {
            type: "status",
            sender: envelopeSender,
            speaker: envelopeSender,
            message: actualPayload.message,
            content: actualPayload.message
          };
        } else {
          // For other envelope types, preserve type and payload structure
          payload = {
            type: envelopeType,
            payload: actualPayload,
            sender: envelopeSender,
            speaker: envelopeSender
          };
        }
      }
      
      // Handle users list pushed from backend
      if (payload.type === "users_list" && payload.payload?.users) {
        setAvailableUsers(payload.payload.users);
        
        // Auto-select first user if none selected
        if (!currentUser && payload.payload.users.length > 0) {
          const firstUser = payload.payload.users[0];
          setCurrentUser(firstUser);
          appendLog(`Welcome ${firstUser.full_name}!`);
        }
        return;
      }
      
      // Handle user profile pushed from backend
      if (payload.type === "user_profile" && payload.payload?.profile) {
        const profile = payload.payload.profile;
        profileCacheRef.current.set(profile.user_id, profile);
        
        // Update current user with full profile
        setCurrentUser(prev => ({
          ...prev,
          ...profile
        }));
        
        return;
      }
      
      // Handle audio_data messages from backend TTS
      if (payload.type === "audio_data" && payload.data) {
        // Don't play audio for User messages (echo prevention)
        if (payload.speaker === "User" || payload.sender === "User") {
          console.log("🔇 Skipping TTS audio for User message (echo prevention)");
          return;
        }
        
        // Don't play TTS audio if microphone is muted (text-only mode)
        if (isMutedRef.current) {
          console.log("🔇 Skipping TTS audio - microphone is muted (text-only mode)");
          return;
        }
        
        // Don't play TTS audio if recording is not active (no voice session)
        if (!recordingRef.current) {
          console.log("🔇 Skipping TTS audio - voice session not active");
          return;
        }
        
        try {
          console.log("🔊 Received audio_data message:", {
            frame_index: payload.frame_index,
            total_frames: payload.total_frames,
            sample_rate: payload.sample_rate,
            data_length: payload.data.length,
            is_final: payload.is_final,
            speaker: payload.speaker || payload.sender
          });

          // Decode base64 -> Int16 -> Float32 [-1, 1]
          const bstr = atob(payload.data);
          const buf = new ArrayBuffer(bstr.length);
          const view = new Uint8Array(buf);
          for (let i = 0; i < bstr.length; i++) view[i] = bstr.charCodeAt(i);
          const int16 = new Int16Array(buf);
          const float32 = new Float32Array(int16.length);
          for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 0x8000;

          console.log(`🔊 Processing TTS audio chunk: ${float32.length} samples, sample_rate: ${payload.sample_rate || 16000}`);
          console.log("🔊 Audio data preview:", float32.slice(0, 10));

          // Push to the worklet queue
          if (pcmSinkRef.current) {
            pcmSinkRef.current.port.postMessage({ type: 'push', payload: float32 });
            appendLog(`🔊 TTS audio frame ${payload.frame_index + 1}/${payload.total_frames}`);
          } else {
            console.warn("Audio playback not initialized, attempting init...");
            appendLog("⚠️ Audio playback not ready, initializing...");
            // Try to initialize if not done yet
            await initializeAudioPlayback();
            if (pcmSinkRef.current) {
              pcmSinkRef.current.port.postMessage({ type: 'push', payload: float32 });
              appendLog("🔊 TTS audio playing (after init)");
            } else {
              console.error("Failed to initialize audio playback");
              appendLog("❌ Audio init failed");
            }
          }
          return; // handled
        } catch (error) {
          console.error("Error processing audio_data:", error);
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

      if (msgType === "user" || speaker === "User") {
        // Add user voice input to chat
        setActiveSpeaker("User");
        setMessages(prev => pushIfChanged(prev, { speaker: "User", text: txt }));
        appendLog(`User: ${txt}`);
        return;
      }

      if (type === "assistant_streaming") {
        const streamingSpeaker = speaker || "Assistant";
        setActiveSpeaker(streamingSpeaker);
        setMessages(prev => {
          if (prev.at(-1)?.streaming && prev.at(-1)?.speaker === streamingSpeaker) {
            return prev.map((m,i)=> i===prev.length-1 ? {...m, text: m.text + txt} : m);
          }
          return [...prev, { speaker:streamingSpeaker, text:txt, streaming:true }];
        });
        return;
      }

      if (msgType === "assistant" || msgType === "status" || speaker === "Assistant") {
        setActiveSpeaker("Assistant");
        setMessages(prev => {
          if (prev.at(-1)?.streaming) {
            return prev.map((m,i)=> i===prev.length-1 ? {...m, text:txt, streaming:false} : m);
          }
          return pushIfChanged(prev, { speaker:"Assistant", text:txt });
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
        setMessages((prev) =>
          prev.map((m, i, arr) =>
            i === arr.length - 1 && m.text.startsWith(`🛠️ tool ${payload.tool}`)
              ? { ...m, text: `🛠️ tool ${payload.tool} ${payload.pct}% 🔄` }
              : m,
          ),
        );
        appendLog(`⚙️ ${payload.tool} ${payload.pct}%`);
        return;
      }
    
      if (type === "tool_end") {

      
        const finalText =
          payload.status === "success"
            ? `🛠️ tool ${payload.tool} completed ✔️\n${JSON.stringify(
                payload.result,
                null,
                2,
              )}`
            : `🛠️ tool ${payload.tool} failed ❌\n${payload.error}`;
      
        setMessages((prev) =>
          prev.map((m, i, arr) =>
            i === arr.length - 1 && m.text.startsWith(`🛠️ tool ${payload.tool}`)
              ? { ...m, text: finalText }
              : m,
          ),
        );
      
        appendLog(`⚙️ ${payload.tool} ${payload.status} (${payload.elapsedMs} ms)`);
        return;
      }

      if (type === "control") {
        const { action } = payload;
        console.log("🎮 Control message received:", action);
        
        if (action === "tts_cancelled") {
          console.log("🔇 TTS cancelled - clearing audio queue");
          appendLog("🔇 Audio interrupted by user speech");
          
          if (pcmSinkRef.current) {
            pcmSinkRef.current.port.postMessage({ type: 'clear' });
          }
          
          setActiveSpeaker(null);
          return;
        }
        
        console.log("🎮 Unknown control action:", action);
        return;
      }
    };
  
  /* ------------------------------------------------------------------ *
   *  OUTBOUND ACS CALL
   * ------------------------------------------------------------------ */
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
      console.log('📞 [FRONTEND] Initiating phone call with session_id:', currentSessionId);
      console.log('📞 [FRONTEND] This session_id will be sent to backend for call mapping');
      
      const res = await fetch(`${API_BASE_URL}/api/v1/calls/initiate`, {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body: JSON.stringify({ 
          target_number: targetPhoneNumber,
          context: {
            browser_session_id: currentSessionId  // 🎯 CRITICAL: Pass browser session ID for ACS coordination
          }
        }),
      });
      const json = await res.json();
      if (!res.ok) {
        appendLog(`Call error: ${json.detail||res.statusText}`);
        return;
      }
      // show in chat
      setMessages(m => [
        ...m,
        { speaker:"Assistant", text:`📞 Call started → ${targetPhoneNumber}` }
      ]);
      appendLog("📞 Call initiated");

      // relay WS WITH session_id to monitor THIS session (including phone calls)
      console.log('🔗 [FRONTEND] Starting dashboard relay WebSocket to monitor session:', currentSessionId);
      const relay = new WebSocket(`${WS_URL}/api/v1/realtime/dashboard/relay?session_id=${currentSessionId}`);
      relay.onopen = () => appendLog("Relay WS connected");
      relay.onmessage = ({data}) => {
        try {
          const obj = JSON.parse(data);
          
          // Handle envelope format for relay messages
          let processedObj = obj;
          if (obj.type && obj.sender && obj.payload && obj.ts) {
            console.log("📨 Relay received envelope message:", {
              type: obj.type,
              sender: obj.sender,
              topic: obj.topic
            });
            
            // Extract actual message from envelope
            if (obj.payload.message) {
              processedObj = {
                type: obj.type,
                sender: obj.sender,
                message: obj.payload.message
              };
            } else if (obj.payload.text) {
              processedObj = {
                type: obj.type,
                sender: obj.sender,
                message: obj.payload.text
              };
            } else {
              // Fallback to using the whole payload as message
              processedObj = {
                type: obj.type,
                sender: obj.sender,
                message: JSON.stringify(obj.payload)
              };
            }
            console.log("📨 Transformed relay envelope:", processedObj);
          }
          
          if (processedObj.type?.startsWith("tool_")) {
            handleSocketMessage({ data: JSON.stringify(processedObj) });
            return;
          }
          const { sender, message } = processedObj;
          if (sender && message) {
            setMessages(m => [...m, { speaker: sender, text: message }]);
            setActiveSpeaker(sender);
            appendLog(`[Relay] ${sender}: ${message}`);
          }
        } catch (error) {
          console.error("Relay parse error:", error);
          appendLog("Relay parse error");
        }
      };
      relay.onclose = () => {
        appendLog("Relay WS disconnected");
        setCallActive(false);
        setActiveSpeaker(null);
      };
    } catch(e) {
      appendLog(`Network error starting call: ${e.message}`);
    }
  };

  /* ------------------------------------------------------------------ *
   *  RENDER
   * ------------------------------------------------------------------ */
  return (
    <div style={styles.root}>
      {/* User Profile Switcher - Floating outside ARTAgent box (like BackendIndicator) */}
      <div style={{
        position: 'fixed',
        top: '68px',
        right: '16px',
        zIndex: 1000
      }}>
        <UserSwitcher 
          currentUser={currentUser}
          availableUsers={availableUsers}
          onUserSwitch={handleUserSwitch}
          isLoading={isLoadingUser}
        />
      </div>

      <div style={styles.mainContainer}>
        {/* Backend Status Indicator */}
        <BackendIndicator url={API_BASE_URL} onStatusChange={handleSystemStatus} />

        {/* App Header - Apple Style */}
        <div style={{
          ...styles.appHeader,
          background: 'linear-gradient(to bottom, #f8fafc 0%, #f1f5f9 100%)',
          borderBottom: '0.5px solid rgba(0, 0, 0, 0.1)',
          boxShadow: '0 1px 3px rgba(0, 0, 0, 0.05)',
          padding: '20px 24px',
        }}>
          {/* Top Left Industry Tag */}
          <IndustryTag />
          <div style={styles.appTitleContainer}>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: '10px',
              marginBottom: '4px'
            }}>
              <div style={{
                fontSize: '22px',
                lineHeight: '1',
              }}>🛍️</div>
              <h1 style={{
                color: '#1e293b',
                fontSize: '19px',
                fontWeight: '600',
                letterSpacing: '-0.3px',
                margin: 0,
                fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
              }}>ARTAgent</h1>
            </div>
            <p style={{
              color: '#94a3b8',
              fontSize: '12px',
              fontWeight: '400',
              margin: '0 0 6px 44px',
              lineHeight: '1.4',
              fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
            }}>Your shopping companion</p>
            <div style={{
              fontSize: '11px',
              color: '#94a3b8',
              fontFamily: '-apple-system, BlinkMacSystemFont, "SF Mono", monospace',
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
              fontWeight: '400',
              marginLeft: '44px'
            }}>
              <span>💬</span>
              <span>Session: {getOrCreateSessionId()}</span>
            </div>
          </div>
          
          {/* Control Actions - Elegant header buttons */}
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            position: 'absolute',
            right: '24px',
            top: '50%',
            transform: 'translateY(-50%)'
          }}>
            {/* Session Reset */}
            <button
              style={{
                width: '44px',
                height: '44px',
                borderRadius: '50%',
                border: '2px solid #e2e8f0',
                background: '#ffffff',
                color: '#64748b',
                fontSize: '18px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
                boxShadow: '0 2px 8px rgba(100, 116, 139, 0.12)',
              }}
              onClick={() => {
                const newSessionId = createNewSessionId();
                if (socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
                  socketRef.current.close();
                }
                setMessages([]);
                setActiveSpeaker(null);
                stopRecognition();
                setCallActive(false);
                setShowPhoneInput(false);
                appendLog(`🔄️ Session reset - new session ID: ${newSessionId.split('_')[1]}`);
                setTimeout(() => {
                  setMessages([{ speaker: "System", text: "✅ New session started. How can I help you today?" }]);
                }, 300);
              }}
              title="Start new session"
              onMouseEnter={(e) => {
                e.currentTarget.style.background = '#fef2f2';
                e.currentTarget.style.borderColor = '#fca5a5';
                e.currentTarget.style.color = '#ef4444';
                e.currentTarget.style.transform = 'translateY(-2px) scale(1.05)';
                e.currentTarget.style.boxShadow = '0 6px 16px rgba(239, 68, 68, 0.2)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = '#ffffff';
                e.currentTarget.style.borderColor = '#e2e8f0';
                e.currentTarget.style.color = '#64748b';
                e.currentTarget.style.transform = 'translateY(0) scale(1)';
                e.currentTarget.style.boxShadow = '0 2px 8px rgba(100, 116, 139, 0.12)';
              }}
            >
              ⟲
            </button>

            {/* Phone Call Button */}
            <button
              style={{
                width: '44px',
                height: '44px',
                borderRadius: '50%',
                border: callActive ? 'none' : '2px solid #e2e8f0',
                background: callActive 
                  ? 'linear-gradient(135deg, #ef4444, #dc2626)' 
                  : (isCallDisabled ? '#f1f5f9' : '#ffffff'),
                color: callActive ? '#ffffff' : (isCallDisabled ? '#94a3b8' : '#64748b'),
                fontSize: '18px',
                cursor: isCallDisabled ? 'not-allowed' : 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
                boxShadow: callActive 
                  ? '0 8px 20px rgba(239, 68, 68, 0.35)' 
                  : '0 2px 8px rgba(100, 116, 139, 0.12)',
                opacity: isCallDisabled ? 0.6 : 1,
              }}
              onClick={() => {
                if (isCallDisabled) return;
                if (callActive) {
                  stopRecognition();
                  setCallActive(false);
                  setMessages(prev => [...prev, { speaker: "System", text: "📞 Call ended" }]);
                } else {
                  setShowPhoneInput(!showPhoneInput);
                }
              }}
              disabled={isCallDisabled}
              title={isCallDisabled ? "Phone calling disabled" : (callActive ? "Hang up" : "Make a call")}
              onMouseEnter={(e) => {
                if (!isCallDisabled && !callActive) {
                  e.currentTarget.style.background = '#eff6ff';
                  e.currentTarget.style.borderColor = '#93c5fd';
                  e.currentTarget.style.color = '#3b82f6';
                  e.currentTarget.style.transform = 'translateY(-2px) scale(1.05)';
                  e.currentTarget.style.boxShadow = '0 6px 16px rgba(59, 130, 246, 0.2)';
                } else if (callActive) {
                  e.currentTarget.style.transform = 'translateY(-2px) scale(1.05)';
                  e.currentTarget.style.boxShadow = '0 12px 28px rgba(239, 68, 68, 0.45)';
                }
              }}
              onMouseLeave={(e) => {
                if (!isCallDisabled && !callActive) {
                  e.currentTarget.style.background = '#ffffff';
                  e.currentTarget.style.borderColor = '#e2e8f0';
                  e.currentTarget.style.color = '#64748b';
                  e.currentTarget.style.transform = 'translateY(0) scale(1)';
                  e.currentTarget.style.boxShadow = '0 2px 8px rgba(100, 116, 139, 0.12)';
                } else if (callActive) {
                  e.currentTarget.style.transform = 'translateY(0) scale(1)';
                  e.currentTarget.style.boxShadow = '0 8px 20px rgba(239, 68, 68, 0.35)';
                }
              }}
            >
              {callActive ? "📵" : "📞"}
            </button>

            {/* Help Button */}
            <HelpButton />
          </div>
        </div>

        {/* Phone Input Panel - Positioned at top after header */}
        {showPhoneInput && (
          <div style={styles.phoneInputSection}>
            <div style={{ marginBottom: '8px', fontSize: '12px', color: '#64748b' }}>
              {callActive ? '📞 Call in progress' : '📞 Enter your phone number to get a call'}
            </div>
            <input
              type="tel"
              value={targetPhoneNumber}
              onChange={(e) => setTargetPhoneNumber(e.target.value)}
              placeholder="+15551234567"
              style={styles.phoneInput}
              disabled={callActive}
            />
            <button
              onClick={callActive ? stopRecognition : startACSCall}
              style={styles.callMeButton(callActive, isCallDisabled)}
              title={
                callActive
                  ? "🔴 Hang up call"
                  : "📞 Start phone call"
              }
              disabled={callActive}
            >
              {callActive ? "🔴 Hang Up" : "📞 Call Me"}
            </button>
          </div>
        )}

        {/* Always Visible Chat Interface - Text + Voice */}
        <div style={styles.chatInterface}>
            {/* Chat Messages Area */}
            <div style={styles.chatMessagesArea} ref={chatRef}>
              {messages.map((message, index) => (
                <ChatBubble key={index} message={message} />
              ))}
            </div>
            
            {/* ChatGPT-Style Input */}
            <div style={{
              padding: '16px 20px 20px 20px',
              background: 'linear-gradient(to bottom, #fafbfc 0%, #f0f4f8 100%)',
              borderTop: '1px solid #e2e8f0',
              boxShadow: '0 -1px 3px rgba(0, 0, 0, 0.03)'
            }}>
              <div style={{
                display: 'flex',
                alignItems: 'flex-end',
                gap: '8px',
                maxWidth: '900px',
                margin: '0 auto',
              }}>
                {/* Input Wrapper */}
                <div style={{
                  flex: 1,
                  display: 'flex',
                  flexDirection: 'column'
                }}>
                  <textarea
                    style={{
                      width: '100%',
                      minHeight: '48px',
                      maxHeight: '140px',
                      padding: '14px 16px',
                      fontSize: '16px',
                      lineHeight: '1.5',
                      border: '1px solid #E5E5EA',
                      borderRadius: '24px',
                      outline: 'none',
                      resize: 'none',
                      fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, sans-serif',
                      background: '#FFFFFF',
                      color: '#000000',
                      transition: 'all 0.2s ease-out',
                      boxShadow: 'none',
                    }}
                    value={chatInput}
                    onChange={(e) => setChatInput(e.target.value)}
                    placeholder="What would you like to shop for today?"
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        if (chatInput.trim()) {
                          sendTextMessage(chatInput);
                          setChatInput('');
                        }
                      }
                    }}
                    onFocus={(e) => {
                      e.currentTarget.style.borderColor = '#007AFF';
                    }}
                    onBlur={(e) => {
                      e.currentTarget.style.borderColor = '#E5E5EA';
                    }}
                  />
                </div>
                
                {/* Action Buttons - Send, Microphone, Attach */}
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '10px',
                  paddingBottom: '2px'
                }}>
                  {/* Send Button - Professional Style */}
                  <button
                    style={{
                      width: '48px',
                      height: '48px',
                      borderRadius: '50%',
                      border: 'none',
                      background: chatInput.trim() 
                        ? '#007AFF' 
                        : '#E5E5EA',
                      color: '#ffffff',
                      fontSize: '20px',
                      fontWeight: '600',
                      cursor: chatInput.trim() ? 'pointer' : 'not-allowed',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      transition: 'all 0.2s ease-out',
                      boxShadow: 'none',
                      position: 'relative',
                      overflow: 'hidden',
                      opacity: chatInput.trim() ? 1 : 0.5,
                    }}
                    onClick={() => {
                      if (chatInput.trim()) {
                        sendTextMessage(chatInput);
                        setChatInput('');
                      }
                    }}
                    disabled={!chatInput.trim()}
                    title="Send message"
                    onMouseEnter={(e) => {
                      if (chatInput.trim()) {
                        e.currentTarget.style.background = '#0051D5';
                      }
                    }}
                    onMouseLeave={(e) => {
                      if (chatInput.trim()) {
                        e.currentTarget.style.background = '#007AFF';
                      }
                    }}
                    onMouseDown={(e) => {
                      if (chatInput.trim()) {
                        e.currentTarget.style.transform = 'scale(0.95)';
                      }
                    }}
                    onMouseUp={(e) => {
                      if (chatInput.trim()) {
                        e.currentTarget.style.transform = 'scale(1)';
                      }
                    }}
                  >
                    <span style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: '22px',
                    }}>
                      ➤
                    </span>
                  </button>
                  
                  {/* Microphone Button - Mute/Unmute Toggle */}
                  <button
                    style={{
                      width: '48px',
                      height: '48px',
                      borderRadius: '50%',
                      border: 'none',
                      background: isMuted ? '#E5E5EA' : '#34C759',
                      color: isMuted ? '#8E8E93' : '#ffffff',
                      fontSize: '20px',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      transition: 'all 0.2s ease-out',
                      boxShadow: 'none',
                    }}
                    onClick={() => {
                      if (isMuted) {
                        // Unmute - start the session if not already started
                        if (!recording) {
                          startRecognition();
                        }
                        setIsMuted(false);
                        isMutedRef.current = false;
                        console.log("🎤 Microphone unmuted");
                      } else {
                        // Mute - clear audio levels to hide visualizer
                        setIsMuted(true);
                        isMutedRef.current = true;
                        setAudioLevel(0);
                        audioLevelRef.current = 0;
                        console.log("🔇 Microphone muted");
                      }
                    }}
                    title={isMuted ? "Unmute microphone" : "Mute microphone"}
                    onMouseEnter={(e) => {
                      if (isMuted) {
                        e.currentTarget.style.background = '#D1D1D6';
                      } else {
                        e.currentTarget.style.background = '#2DB84C';
                      }
                    }}
                    onMouseLeave={(e) => {
                      if (isMuted) {
                        e.currentTarget.style.background = '#E5E5EA';
                      } else {
                        e.currentTarget.style.background = '#34C759';
                      }
                    }}
                    onMouseDown={(e) => {
                      e.currentTarget.style.transform = 'scale(0.95)';
                    }}
                    onMouseUp={(e) => {
                      e.currentTarget.style.transform = 'scale(1)';
                    }}
                  >
                    {isMuted ? '🎤' : '🔇'}
                  </button>
                  
                  {/* Attach Button - Apple Style */}
                  <button
                    style={{
                      width: '48px',
                      height: '48px',
                      borderRadius: '50%',
                      border: 'none',
                      background: '#E5E5EA',
                      color: '#8E8E93',
                      fontSize: '20px',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      transition: 'all 0.2s ease-out',
                      boxShadow: 'none',
                    }}
                    onClick={() => {
                      console.log('Attachment button clicked');
                    }}
                    title="Attach file (coming soon)"
                    onMouseEnter={(e) => {
                      e.currentTarget.style.background = '#D1D1D6';
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background = '#E5E5EA';
                    }}
                    onMouseDown={(e) => {
                      e.currentTarget.style.transform = 'scale(0.95)';
                    }}
                    onMouseUp={(e) => {
                      e.currentTarget.style.transform = 'scale(1)';
                    }}
                  >
                    📎
                  </button>
                </div>
              </div>
            </div>
          </div>
          
          {/* Voice Activity Indicator - Only visible when recording AND unmuted */}
          {recording && !isMuted && (
            <div style={{
              padding: "6px 16px",
              background: "linear-gradient(90deg, #dcfce7 0%, #bbf7d0 100%)",
              borderTop: "1px solid #86efac",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              minHeight: "32px",
              transition: "all 0.3s ease"
            }}>
              <WaveformVisualization 
                isActive={true} 
                speaker={activeSpeaker} 
                audioLevel={audioLevel}
                outputAudioLevel={0}
              />
            </div>
          )}
        </div>
    </div>
  );
}

// Main App component wrapper
function App() {
  return <RealTimeVoiceApp />;
}

export default App;