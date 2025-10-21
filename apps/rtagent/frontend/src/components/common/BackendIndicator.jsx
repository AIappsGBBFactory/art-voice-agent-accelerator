import React, { useCallback, useEffect, useRef, useState } from "react";
import { styles } from "../AppStyles";

const BackendHelpButton = () => {
  const [isHovered, setIsHovered] = useState(false);
  const [isClicked, setIsClicked] = useState(false);

  const handleClick = (event) => {
    event.preventDefault();
    event.stopPropagation();
    setIsClicked((prev) => !prev);
  };

  const handleMouseLeave = () => {
    setIsHovered(false);
  };

  return (
    <div
      style={{
        width: "14px",
        height: "14px",
        borderRadius: "50%",
        backgroundColor: isHovered ? "#3b82f6" : "#64748b",
        color: "white",
        fontSize: "9px",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        cursor: "pointer",
        transition: "all 0.2s ease",
        fontWeight: "600",
        position: "relative",
        flexShrink: 0,
      }}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={handleMouseLeave}
      onClick={handleClick}
    >
      ?
      <div
        style={{
          visibility: isHovered || isClicked ? "visible" : "hidden",
          opacity: isHovered || isClicked ? 1 : 0,
          position: "absolute",
          bottom: "20px",
          left: "0",
          backgroundColor: "rgba(0, 0, 0, 0.95)",
          color: "white",
          padding: "12px",
          borderRadius: "8px",
          fontSize: "11px",
          lineHeight: "1.4",
          minWidth: "280px",
          maxWidth: "320px",
          boxShadow: "0 4px 12px rgba(0,0,0,0.3)",
          zIndex: 10000,
          transition: "all 0.2s ease",
          backdropFilter: "blur(8px)",
        }}
      >
        <div
          style={{
            fontSize: "12px",
            fontWeight: "600",
            color: "#67d8ef",
            marginBottom: "8px",
            display: "flex",
            alignItems: "center",
            gap: "6px",
          }}
        >
          🔧 Backend Status Monitor
        </div>
        <div style={{ marginBottom: "8px" }}>
          Real-time health monitoring for all ARTAgent backend services including
          Redis cache, Azure OpenAI, Speech Services, and Communication Services.
        </div>
        <div style={{ marginBottom: "8px" }}>
          <strong>Status Colors:</strong>
          <br />
          🟢 Healthy - All systems operational
          <br />
          🟡 Degraded - Some performance issues
          <br />
          🔴 Unhealthy - Service disruption
        </div>
        <div
          style={{ fontSize: "10px", color: "#94a3b8", fontStyle: "italic" }}
        >
          Auto-refreshes every 30 seconds • Click to expand for details
        </div>
        {isClicked && (
          <div
            style={{
              textAlign: "center",
              marginTop: "8px",
              fontSize: "9px",
              color: "#94a3b8",
              fontStyle: "italic",
            }}
          >
            Click ? again to close
          </div>
        )}
      </div>
    </div>
  );
};

const BackendStatisticsButton = ({ isActive, onToggle }) => {
  const [isHovered, setIsHovered] = useState(false);

  const handleClick = (event) => {
    event.preventDefault();
    event.stopPropagation();
    onToggle();
  };

  return (
    <div
      style={{
        width: "14px",
        height: "14px",
        borderRadius: "50%",
        backgroundColor: isActive
          ? "#3b82f6"
          : isHovered
          ? "#3b82f6"
          : "#64748b",
        color: "white",
        fontSize: "8px",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        cursor: "pointer",
        transition: "all 0.2s ease",
        fontWeight: "600",
        position: "relative",
        flexShrink: 0,
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
  const [healthData, setHealthData] = useState(null);
  const summaryRef = useRef(null);

  useEffect(() => {
    const handleResize = () => setScreenWidth(window.innerWidth);
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  const checkReadiness = useCallback(async () => {
    try {
      const response = await fetch(`${url}/api/v1/readiness`);

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const data = await response.json();

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
  }, [url]);

  const checkAgents = useCallback(async () => {
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
  }, [url]);

  const checkHealth = useCallback(async () => {
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
  }, [url]);

  const updateAgentConfig = async (agentName, config) => {
    try {
      setUpdateStatus((prev) => ({ ...prev, [agentName]: "updating" }));

      const response = await fetch(`${url}/api/v1/agents/${agentName}`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(config),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const data = await response.json();

      setUpdateStatus((prev) => ({ ...prev, [agentName]: "success" }));

      checkAgents();

      setTimeout(() => {
        setUpdateStatus((prev) => {
          const next = { ...prev };
          delete next[agentName];
          return next;
        });
      }, 3000);

      return data;
    } catch (err) {
      console.error("Agent config update failed:", err);
      setUpdateStatus((prev) => ({ ...prev, [agentName]: "error" }));

      setTimeout(() => {
        setUpdateStatus((prev) => {
          const next = { ...prev };
          delete next[agentName];
          return next;
        });
      }, 5000);

      throw err;
    }
  };

  useEffect(() => {
    try {
      const urlObj = new URL(url);
      const host = urlObj.hostname;
      const protocol = urlObj.protocol.replace(":", "");

      if (host.includes(".azurewebsites.net")) {
        const appName = host.split(".")[0];
        setDisplayUrl(`${protocol}://${appName}.azure...`);
      } else if (host === "localhost") {
        setDisplayUrl(`${protocol}://localhost:${urlObj.port || "8000"}`);
      } else {
        setDisplayUrl(`${protocol}://${host}`);
      }
    } catch (error) {
      console.warn("Failed to format backend URL", error);
      setDisplayUrl(url);
    }

    checkReadiness();
    checkAgents();
    checkHealth();

    const interval = setInterval(() => {
      checkReadiness();
      checkAgents();
      checkHealth();
    }, 10000);

    return () => clearInterval(interval);
  }, [checkAgents, checkHealth, checkReadiness, url]);

  const readinessChecks = readinessData?.checks ?? [];
  const unhealthyChecks = readinessChecks.filter((check) => check.status === "unhealthy");
  const degradedChecks = readinessChecks.filter((check) => check.status === "degraded");
  const acsOnlyIssue =
    unhealthyChecks.length > 0 &&
    degradedChecks.length === 0 &&
    unhealthyChecks.every((check) => check.component === "acs_caller") &&
    readinessChecks
      .filter((check) => check.component !== "acs_caller")
      .every((check) => check.status === "healthy");

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
  const statusColor =
    overallStatus === "healthy"
      ? "#10b981"
      : overallStatus === "degraded"
      ? "#f59e0b"
      : overallStatus === "unhealthy"
      ? "#ef4444"
      : "#6b7280";

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

  const getResponsiveStyle = () => {
    const baseStyle = {
      ...styles.backendIndicator,
      transition: "all 0.3s ease",
    };

    const containerWidth = 768;
    const containerLeftEdge = screenWidth / 2 - containerWidth / 2;
    const availableWidth = containerLeftEdge - 40 - 20;

    if (availableWidth < 200) {
      return {
        ...baseStyle,
        minWidth: "150px",
        maxWidth: "180px",
        padding:
          !shouldBeExpanded && overallStatus === "healthy"
            ? "8px 12px"
            : "10px 14px",
        fontSize: "10px",
      };
    }
    if (availableWidth < 280) {
      return {
        ...baseStyle,
        minWidth: "180px",
        maxWidth: "250px",
        padding:
          !shouldBeExpanded && overallStatus === "healthy"
            ? "10px 14px"
            : "12px 16px",
      };
    }
    return {
      ...baseStyle,
      minWidth:
        !shouldBeExpanded && overallStatus === "healthy" ? "200px" : "280px",
      maxWidth: "320px",
      padding:
        !shouldBeExpanded && overallStatus === "healthy"
          ? "10px 14px"
          : "12px 16px",
    };
  };

  const componentIcons = {
    redis: "💾",
    azure_openai: "🧠",
    speech_services: "🎙️",
    acs_caller: "📞",
    rt_agents: "🤖",
  };

  const componentDescriptions = {
    redis: "Redis Cache - Session & state management",
    azure_openai: "Azure OpenAI - GPT models & embeddings",
    speech_services: "Speech Services - STT/TTS processing",
    acs_caller: "Communication Services - Voice calling",
    rt_agents: "RT Agents - Real-time Voice Agents",
  };

  const handleBackendClick = (event) => {
    if (event.target.closest("div")?.style?.cursor === "pointer" && event.target !== event.currentTarget) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    setIsClickedOpen((prev) => !prev);
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

  const shouldBeExpanded = isClickedOpen || isExpanded;

  return (
    <div
      style={getResponsiveStyle()}
      title={
        isClickedOpen
          ? "Click to close backend status"
          : "Click to pin open backend status"
      }
      onClick={handleBackendClick}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      <div style={styles.backendHeader}>
        <div
          style={{
            ...styles.backendStatus,
            backgroundColor: statusColor,
          }}
        ></div>
        <span style={styles.backendLabel}>Backend Status</span>
        <BackendHelpButton />
        <span
          style={{
            ...styles.expandIcon,
            transform: shouldBeExpanded ? "rotate(180deg)" : "rotate(0deg)",
            color: isClickedOpen ? "#3b82f6" : styles.expandIcon.color,
            fontWeight: isClickedOpen ? "600" : "normal",
          }}
        >
          ▼
        </span>
      </div>

      {!shouldBeExpanded && (
        <div
          style={{
            ...styles.backendUrl,
            fontSize: "9px",
            opacity: 0.7,
            marginTop: "2px",
          }}
        >
          {displayUrl}
        </div>
      )}

      {(shouldBeExpanded || overallStatus !== "healthy") && (
        <>
          {shouldBeExpanded && (
            <>
              <div
                style={{
                  padding: "8px 10px",
                  backgroundColor: "#f8fafc",
                  borderRadius: "8px",
                  marginBottom: "10px",
                  fontSize: "10px",
                  border: "1px solid #e2e8f0",
                }}
              >
                <div
                  style={{
                    fontWeight: "600",
                    color: "#475569",
                    marginBottom: "4px",
                    display: "flex",
                    alignItems: "center",
                    gap: "6px",
                  }}
                >
                  🌐 Backend API Entry Point
                </div>
                <div
                  style={{
                    color: "#64748b",
                    fontSize: "9px",
                    fontFamily: "monospace",
                    marginBottom: "6px",
                    padding: "3px 6px",
                    backgroundColor: "white",
                    borderRadius: "4px",
                    border: "1px solid #f1f5f9",
                  }}
                >
                  {url}
                </div>
                <div
                  style={{
                    color: "#64748b",
                    fontSize: "9px",
                    lineHeight: "1.3",
                  }}
                >
                  Main FastAPI server handling WebSocket connections, voice processing, and AI agent orchestration
                </div>
              </div>

              {readinessData && (
                <div
                  style={{
                    padding: "6px 8px",
                    backgroundColor:
                      overallStatus === "healthy"
                        ? "#f0fdf4"
                        : overallStatus === "degraded"
                        ? "#fffbeb"
                        : "#fef2f2",
                    borderRadius: "6px",
                    marginBottom: "8px",
                    fontSize: "10px",
                    border:
                      "1px solid " +
                      (overallStatus === "healthy"
                        ? "#bbf7d0"
                        : overallStatus === "degraded"
                        ? "#fed7aa"
                        : "#fecaca"),
                    cursor: "pointer",
                    transition: "all 0.2s ease",
                  }}
                  ref={summaryRef}
                  onClick={(event) => {
                    event.stopPropagation();
                    setShowComponentDetails((prev) => !prev);
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
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "6px",
                    }}
                  >
                    <span>
                      {overallStatus === "healthy"
                        ? "✅ All services operational"
                        : overallStatus === "degraded"
                        ? "⚠️ Service degradation detected"
                        : "🚨 Service disruption detected"}
                    </span>
                    <span
                      style={{
                        marginLeft: "auto",
                        fontSize: "9px",
                        color: "#64748b",
                        display: "flex",
                        alignItems: "center",
                        gap: "4px",
                      }}
                    >
                      {showComponentDetails ? "Hide details" : "View details"}
                      <span>{showComponentDetails ? "▲" : "▼"}</span>
                    </span>
                  </div>
                  {acsOnlyIssue && (
                    <div
                      style={{
                        marginTop: "6px",
                        fontSize: "9px",
                        color: "#b45309",
                      }}
                    >
                      ACS caller currently unhealthy. Voice call features may be
                      unavailable.
                    </div>
                  )}
                </div>
              )}

              {showAcsHover && acsTooltipPos && acsOnlyIssue && (
                <div
                  style={{
                    ...styles.acsHoverDialog,
                    top: `${acsTooltipPos.top}px`,
                    left: `${acsTooltipPos.left}px`,
                  }}
                >
                  Azure Communication Services (ACS) is currently unavailable or
                  misconfigured. The "Call Me" and inbound calling experiences will
                  not function until ACS connectivity is restored.
                </div>
              )}

              {showComponentDetails && readinessData && (
                <div style={styles.componentGrid}>
                  {readinessData.checks.map((component) => (
                    <div
                      key={component.component}
                      style={styles.componentItem}
                      title={componentDescriptions[component.component] || ""}
                    >
                      <span style={styles.componentDot(component.status)}></span>
                      <span style={styles.componentName}>
                        {componentIcons[component.component] || ""}
                        {" "}
                        {component.component.replace(/_/g, " ")}
                      </span>
                      <span style={styles.responseTime}>
                        {component.latency ? `${component.latency} ms` : ""}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {error && <div style={styles.errorMessage}>{error}</div>}

              <div
                style={{
                  display: "flex",
                  gap: "8px",
                  marginTop: "8px",
                }}
              >
                <button
                  style={{
                    padding: "8px 12px",
                    borderRadius: "8px",
                    border: "1px solid #e2e8f0",
                    background: "white",
                    cursor: "pointer",
                    fontSize: "11px",
                    color: "#334155",
                    fontWeight: 600,
                  }}
                  onClick={(event) => {
                    event.stopPropagation();
                    checkReadiness();
                    checkAgents();
                    checkHealth();
                  }}
                >
                  Refresh Now
                </button>
                <button
                  style={{
                    padding: "8px 12px",
                    borderRadius: "8px",
                    border: "1px solid #e2e8f0",
                    background: "white",
                    cursor: "pointer",
                    fontSize: "11px",
                    color: "#334155",
                    fontWeight: 600,
                  }}
                  onClick={(event) => {
                    event.stopPropagation();
                    if (typeof onConfigureClick === "function") {
                      onConfigureClick();
                    }
                  }}
                >
                  Configure Agents
                </button>
                <BackendStatisticsButton
                  onToggle={() => setShowStatistics((prev) => !prev)}
                  isActive={showStatistics}
                />
              </div>

              {showStatistics && healthData && (
                <div
                  style={{
                    marginTop: "10px",
                    padding: "10px",
                    background: "#f8fafc",
                    borderRadius: "10px",
                    border: "1px solid #e2e8f0",
                    fontSize: "10px",
                    color: "#475569",
                    display: "grid",
                    gridTemplateColumns: "1fr 1fr",
                    gap: "8px",
                  }}
                >
                  <div>
                    <div style={{ fontWeight: 600, marginBottom: "4px" }}>
                      Active Sessions
                    </div>
                    <div>{healthData.active_sessions ?? "n/a"}</div>
                  </div>
                  <div>
                    <div style={{ fontWeight: 600, marginBottom: "4px" }}>
                      Average Latency
                    </div>
                    <div>{healthData.average_latency_ms ?? "n/a"} ms</div>
                  </div>
                  <div>
                    <div style={{ fontWeight: 600, marginBottom: "4px" }}>
                      Last Request
                    </div>
                    <div>{healthData.last_request_at ?? "n/a"}</div>
                  </div>
                  <div>
                    <div style={{ fontWeight: 600, marginBottom: "4px" }}>
                      WebSocket Clients
                    </div>
                    <div>{healthData.websocket_clients ?? "n/a"}</div>
                  </div>
                </div>
              )}

              {agentsData && (
                <div
                  style={{
                    marginTop: "12px",
                    padding: "10px",
                    background: "#f1f5f9",
                    borderRadius: "10px",
                    border: "1px solid #e2e8f0",
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "6px",
                      marginBottom: "8px",
                      fontSize: "11px",
                      color: "#334155",
                      fontWeight: 600,
                    }}
                  >
                    🤖 Registered Agents ({agentsData.agents.length})
                  </div>
                  <div
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      gap: "6px",
                    }}
                  >
                    {agentsData.agents.map((agent) => (
                      <div
                        key={agent.name}
                        style={{
                          background: "white",
                          borderRadius: "8px",
                          padding: "8px",
                          border: "1px solid #e2e8f0",
                          display: "flex",
                          flexDirection: "column",
                          gap: "6px",
                          fontSize: "10px",
                        }}
                      >
                        <div
                          style={{
                            display: "flex",
                            justifyContent: "space-between",
                            alignItems: "center",
                          }}
                        >
                          <span
                            style={{
                              fontWeight: 600,
                              color: "#1e293b",
                              fontSize: "11px",
                            }}
                          >
                            {agent.name}
                          </span>
                          <button
                            style={{
                              padding: "6px 10px",
                              borderRadius: "6px",
                              border: "1px solid #e2e8f0",
                              background: "#f8fafc",
                              cursor: "pointer",
                              fontSize: "10px",
                              color: "#334155",
                              fontWeight: 600,
                            }}
                            onClick={(event) => {
                              event.stopPropagation();
                              setSelectedAgent(agent);
                              setShowAgentConfig(true);
                              setConfigChanges({});
                            }}
                          >
                            Configure
                          </button>
                        </div>
                        <div
                          style={{
                            display: "grid",
                            gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
                            gap: "6px",
                          }}
                        >
                          <div>
                            <div style={{ color: "#64748b" }}>Assistant</div>
                            <div>{agent.assistant || "n/a"}</div>
                          </div>
                          <div>
                            <div style={{ color: "#64748b" }}>Voice</div>
                            <div>{agent.voice || "n/a"}</div>
                          </div>
                          <div>
                            <div style={{ color: "#64748b" }}>Language</div>
                            <div>{agent.locale || "n/a"}</div>
                          </div>
                          <div>
                            <div style={{ color: "#64748b" }}>Status</div>
                            <div>{agent.enabled ? "Enabled" : "Disabled"}</div>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {showAgentConfig && selectedAgent && (
                <div
                  style={{
                    marginTop: "12px",
                    padding: "10px",
                    background: "white",
                    borderRadius: "10px",
                    border: "1px solid #e2e8f0",
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      marginBottom: "10px",
                    }}
                  >
                    <span
                      style={{
                        fontWeight: 600,
                        color: "#1e293b",
                        fontSize: "11px",
                      }}
                    >
                      Configure {selectedAgent.name}
                    </span>
                    <button
                      style={{
                        padding: "4px 8px",
                        borderRadius: "6px",
                        border: "1px solid #e2e8f0",
                        background: "#f8fafc",
                        cursor: "pointer",
                        fontSize: "10px",
                      }}
                      onClick={(event) => {
                        event.stopPropagation();
                        setShowAgentConfig(false);
                        setSelectedAgent(null);
                        setConfigChanges({});
                      }}
                    >
                      Close
                    </button>
                  </div>

                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
                      gap: "8px",
                    }}
                  >
                    <label
                      style={{
                        display: "flex",
                        flexDirection: "column",
                        gap: "4px",
                        fontSize: "10px",
                      }}
                    >
                      Assistant ID
                      <input
                        type="text"
                        defaultValue={selectedAgent.assistant || ""}
                        style={{
                          padding: "6px",
                          borderRadius: "6px",
                          border: "1px solid #d1d5db",
                          fontSize: "11px",
                        }}
                        onChange={(event) =>
                          setConfigChanges((prev) => ({
                            ...prev,
                            assistant: event.target.value,
                          }))
                        }
                      />
                    </label>
                    <label
                      style={{
                        display: "flex",
                        flexDirection: "column",
                        gap: "4px",
                        fontSize: "10px",
                      }}
                    >
                      Voice
                      <input
                        type="text"
                        defaultValue={selectedAgent.voice || ""}
                        style={{
                          padding: "6px",
                          borderRadius: "6px",
                          border: "1px solid #d1d5db",
                          fontSize: "11px",
                        }}
                        onChange={(event) =>
                          setConfigChanges((prev) => ({
                            ...prev,
                            voice: event.target.value,
                          }))
                        }
                      />
                    </label>
                    <label
                      style={{
                        display: "flex",
                        flexDirection: "column",
                        gap: "4px",
                        fontSize: "10px",
                      }}
                    >
                      Locale
                      <input
                        type="text"
                        defaultValue={selectedAgent.locale || ""}
                        style={{
                          padding: "6px",
                          borderRadius: "6px",
                          border: "1px solid #d1d5db",
                          fontSize: "11px",
                        }}
                        onChange={(event) =>
                          setConfigChanges((prev) => ({
                            ...prev,
                            locale: event.target.value,
                          }))
                        }
                      />
                    </label>
                    <label
                      style={{
                        display: "flex",
                        flexDirection: "column",
                        gap: "4px",
                        fontSize: "10px",
                      }}
                    >
                      Enabled
                      <select
                        defaultValue={selectedAgent.enabled ? "true" : "false"}
                        style={{
                          padding: "6px",
                          borderRadius: "6px",
                          border: "1px solid #d1d5db",
                          fontSize: "11px",
                        }}
                        onChange={(event) =>
                          setConfigChanges((prev) => ({
                            ...prev,
                            enabled: event.target.value === "true",
                          }))
                        }
                      >
                        <option value="true">True</option>
                        <option value="false">False</option>
                      </select>
                    </label>
                  </div>

                  <textarea
                    placeholder="Optional: provide JSON overrides"
                    style={{
                      marginTop: "8px",
                      width: "100%",
                      minHeight: "80px",
                      borderRadius: "6px",
                      border: "1px solid #d1d5db",
                      padding: "6px",
                      fontSize: "11px",
                      fontFamily: "monospace",
                    }}
                    onChange={(event) =>
                      setConfigChanges((prev) => ({
                        ...prev,
                        overrides: event.target.value,
                      }))
                    }
                  ></textarea>

                  <div
                    style={{
                      marginTop: "10px",
                      display: "flex",
                      gap: "8px",
                    }}
                  >
                    <button
                      style={{
                        padding: "8px 12px",
                        borderRadius: "6px",
                        border: "1px solid #e2e8f0",
                        background: "#f8fafc",
                        cursor: "pointer",
                        fontSize: "11px",
                        fontWeight: 600,
                        color: "#334155",
                      }}
                      onClick={async (event) => {
                        event.stopPropagation();
                        const payload = { ...configChanges };
                        if (payload.overrides) {
                          try {
                            payload.overrides = JSON.parse(payload.overrides);
                          } catch (parseError) {
                            console.error("Invalid overrides JSON:", parseError);
                            setUpdateStatus((prev) => ({ ...prev, [selectedAgent.name]: "error" }));
                            return;
                          }
                        }
                        try {
                          await updateAgentConfig(selectedAgent.name, payload);
                        } catch (updateError) {
                          console.error("Failed to update agent:", updateError);
                        }
                      }}
                    >
                      Save Changes
                    </button>
                    <button
                      style={{
                        padding: "8px 12px",
                        borderRadius: "6px",
                        border: "1px solid #e2e8f0",
                        background: "white",
                        cursor: "pointer",
                        fontSize: "11px",
                      }}
                      onClick={(event) => {
                        event.stopPropagation();
                        setConfigChanges({});
                      }}
                    >
                      Reset
                    </button>
                    {updateStatus[selectedAgent.name] === "updating" && (
                      <span
                        style={{
                          fontSize: "10px",
                          color: "#0ea5e9",
                          display: "flex",
                          alignItems: "center",
                          gap: "6px",
                        }}
                      >
                        Saving...
                      </span>
                    )}
                    {updateStatus[selectedAgent.name] === "success" && (
                      <span
                        style={{
                          fontSize: "10px",
                          color: "#10b981",
                          display: "flex",
                          alignItems: "center",
                          gap: "6px",
                        }}
                      >
                        Saved
                      </span>
                    )}
                    {updateStatus[selectedAgent.name] === "error" && (
                      <span
                        style={{
                          fontSize: "10px",
                          color: "#ef4444",
                          display: "flex",
                          alignItems: "center",
                          gap: "6px",
                        }}
                      >
                        Failed to save
                      </span>
                    )}
                  </div>
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
};

export default BackendIndicator;
