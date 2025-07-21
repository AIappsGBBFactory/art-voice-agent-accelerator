// src/RealTimeVoiceApp.jsx
import React, { useEffect, useRef, useState } from 'react';
import VoiceSphere from './components/VoiceSphere';
import "reactflow/dist/style.css";
import { useHealthMonitor } from "./hooks/useHealthMonitor";
import HealthStatusIndicator from "./components/HealthStatusIndicator";

/* ------------------------------------------------------------------ *
 *  ENV VARS
 * ------------------------------------------------------------------ */
const {
  VITE_BACKEND_BASE_URL: API_BASE_URL,
} = import.meta.env;

const WS_URL = API_BASE_URL.replace(/^https?/, "wss");

/* ------------------------------------------------------------------ *
 *  STYLES
 * ------------------------------------------------------------------ */
const styles = {
  root: {
    width: "768px",
    maxWidth: "768px", // Expanded from iPad width
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
  
  // Main iPad-sized container
  mainContainer: {
    width: "100%",
    maxWidth: "100%", // Expanded from iPad width
    height: "90vh",
    maxHeight: "900px", // Adjusted height
    background: "white",
    borderRadius: "20px",
    boxShadow: "0 20px 60px rgba(0,0,0,0.15)",
    border: "0px solid #ce1010ff",
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
  },
  
  // Waveform section (top third)
  waveformSection: {
    backgroundColor: "#dbeafe",
    padding: "2px 4px",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    borderBottom: "1px solid #e2e8f0",
    height: "25%",
    minHeight: "100px",
    position: "relative",
  },
  
  waveformSectionTitle: {
    fontSize: "14px",
    fontWeight: "600",
    color: "#64748b",
    textTransform: "uppercase",
    letterSpacing: "0.5px",
    marginBottom: "2px",
  },
  
  // Section divider line
  sectionDivider: {
    position: "absolute",
    bottom: "-1px",
    left: "15%",
    right: "15%",
    height: "3px",
    backgroundColor: "#3b82f6",
    borderRadius: "1px",
  },
  
  waveformContainer: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    width: "100%",
    height: "60%",
    padding: "0 10px", // Add horizontal padding to prevent edge cutoff
  },
  
  waveformSvg: {
    width: "100%",
    height: "60px",
  },
  
  // Chat section (middle section)
  chatSection: {
    flex: 1,
    padding: "15px 20px 15px 5px", // Remove most left padding, keep right padding
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
  
  // Chat section visual indicator
  chatSectionIndicator: {
    position: "absolute",
    left: "0",
    top: "0",
    bottom: "0",
    width: "0px", // Removed blue border
    backgroundColor: "#3b82f6",
  },
  
  messageContainer: {
    display: "flex",
    flexDirection: "column",
    gap: "16px",
    flex: 1,
    overflowY: "auto",
    padding: "0", // Remove all padding for maximum space usage
  },
  
  // User message (right aligned - blue bubble)
  userMessage: {
    alignSelf: "flex-end",
    maxWidth: "75%", // More conservative width
    marginRight: "15px", // Increased margin for more right padding
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
    maxWidth: "80%", // Increased width for maximum space usage
    marginLeft: "0px", // No left margin - flush to edge
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
  
  // Control section (bottom third)
  controlSection: {
    padding: "8px",
    backgroundColor: "#dbeafe",
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
    gap: "6px",
    background: "white",
    padding: "10px 10px",
    borderRadius: "50px",
    boxShadow: "0 8px 32px rgba(0,0,0,0.12)",
    border: "1px solid #e2e8f0",
    width: "fit-content",
  },
  
  controlButton: (isActive, variant = 'default') => ({
    width: "56px",
    height: "56px",
    borderRadius: "50%",
    border: "none",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    cursor: "pointer",
    fontSize: "20px",
    transition: "all 0.2s ease",
    background: variant === 'phone' ? "#67d8ef" : 
                variant === 'close' ? "#f1f5f9" :
                isActive ? "#67d8ef" : "#f1f5f9",
    color: variant === 'phone' || isActive ? "white" : "#64748b",
    transform: isActive ? "scale(1.05)" : "scale(1)",
    boxShadow: isActive ? "0 4px 16px rgba(103,216,239,0.4)" : "0 2px 8px rgba(0,0,0,0.05)",
  }),
  
  // Health indicator in top right
  healthIndicator: {
    position: "absolute",
    top: "20px",
    right: "20px",
    zIndex: 10,
  },
  
  // Input section for phone calls
  phoneInputSection: {
    position: "absolute",
    bottom: "140px",
    right: "20px",
    background: "white",
    padding: "20px",
    borderRadius: "16px",
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
    borderRadius: "8px",
    fontSize: "14px",
    outline: "none",
    transition: "border-color 0.2s ease",
  },
  
  phoneButton: (isActive) => ({
    padding: "12px 20px",
    background: isActive ? "#ef4444" : "#67d8ef",
    color: "white",
    border: "none",
    borderRadius: "8px",
    cursor: "pointer",
    fontSize: "14px",
    fontWeight: "600",
    transition: "all 0.2s ease",
  }),
};

/* ------------------------------------------------------------------ *
 *  WAVEFORM COMPONENT
 * ------------------------------------------------------------------ */
const WaveformVisualization = ({ isActive, speaker }) => {
  const [waveOffset, setWaveOffset] = useState(0);
  const [amplitude, setAmplitude] = useState(5);
  const animationRef = useRef();
  
  useEffect(() => {
    // Animation should run when there's an active speaker
    if (!speaker) {
      setAmplitude(3);
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
      return;
    }
    
    // Higher amplitude when someone is speaking
    setAmplitude(15 + Math.random() * 10);
    
    // Animate the wave
    const animate = () => {
      setWaveOffset(prev => (prev + 2) % 360);
      setAmplitude(prev => {
        const baseAmplitude = speaker ? 15 : 3;
        const variation = speaker ? Math.random() * 15 : Math.random() * 2;
        return baseAmplitude + variation;
      });
      animationRef.current = requestAnimationFrame(animate);
    };
    
    animationRef.current = requestAnimationFrame(animate);
    
    return () => {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
    };
  }, [speaker]); // Changed dependency from isActive to speaker
  
  // Generate wave path
  const generateWavePath = () => {
    const width = 750;
    const height = 100;
    const centerY = height / 2;
    const frequency = 0.02; // How many waves across the width
    const points = 200; // Number of points to draw
    
    let path = `M 0 ${centerY}`;
    
    for (let i = 0; i <= points; i++) {
      const x = (i / points) * width;
      const y = centerY + Math.sin((x * frequency + waveOffset * 0.1)) * amplitude;
      path += ` L ${x} ${y}`;
    }
    
    return path;
  };
  
  // Generate multiple wave layers for richer visualization
  const generateMultipleWaves = () => {
    const waves = [];
    // More distinct colors based on speaker
    const baseColor = speaker === "User" ? "#ef4444" :  // Red for user
                     speaker === "Assistant" ? "#67d8ef" :  // Teal for assistant
                     "#11d483ff"; // fallback color
    const opacity = !!speaker ? 0.8 : 0.4; // Simplified opacity logic
    
    // Main wave
    waves.push(
      <path
        key="wave1"
        d={generateWavePath()}
        stroke={baseColor}
        strokeWidth="3"
        fill="none"
        opacity={opacity}
        strokeLinecap="round"
      />
    );
    
    // Secondary wave (slightly offset and smaller)
    const secondaryPath = generateSecondaryWave();
    waves.push(
      <path
        key="wave2"
        d={secondaryPath}
        stroke={baseColor}
        strokeWidth="2"
        fill="none"
        opacity={opacity * 0.6}
        strokeLinecap="round"
      />
    );
    
    return waves;
  };
  
  const generateSecondaryWave = () => {
    const width = 750;
    const height = 100;
    const centerY = height / 2;
    const frequency = 0.025; // Slightly different frequency
    const points = 200;
    
    let path = `M 0 ${centerY}`;
    
    for (let i = 0; i <= points; i++) {
      const x = (i / points) * width;
      const y = centerY + Math.sin((x * frequency + waveOffset * 0.15)) * (amplitude * 0.6);
      path += ` L ${x} ${y}`;
    }
    
    return path;
  };
  
  return (
    <div style={styles.waveformContainer}>
      {!!speaker && (
        <svg style={styles.waveformSvg} viewBox="0 0 750 80" preserveAspectRatio="xMidYMid meet">
          {generateMultipleWaves()}
        </svg>
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
      <div style={isUser ? styles.userBubble : styles.assistantBubble}>
        {text.split("\n").map((line, i) => (
          <div key={i}>{line}</div>
        ))}
        {streaming && <span style={{ opacity: 0.7 }}>▌</span>}
      </div>
    </div>
  );
};

/* ------------------------------------------------------------------ *
 *  MAIN COMPONENT
 * ------------------------------------------------------------------ */
export default function RealTimeVoiceApp() {
  /* ---------- state ---------- */
  const [messages, setMessages] = useState([
    { speaker: "User", text: "Hello, I need help with my insurance claim." },
    { speaker: "Assistant", text: "I'd be happy to help you with your insurance claim. Can you please provide me with your policy number?" }
  ]);
  const [log, setLog]                 = useState("");
  const [recording, setRecording]     = useState(false);
  const [targetPhoneNumber, setTargetPhoneNumber] = useState("");
  const [callActive, setCallActive]   = useState(false);
  const [activeSpeaker, setActiveSpeaker] = useState(null);
  const [showPhoneInput, setShowPhoneInput] = useState(false);

  /* ---------- health monitoring ---------- */
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


  // Function call state (not mind-map)
  const [functionCalls, setFunctionCalls] = useState([]);
  const [callResetKey, setCallResetKey]   = useState(0);

  /* ---------- refs ---------- */
  const chatRef      = useRef(null);
  const socketRef    = useRef(null);
  const recognizerRef= useRef(null);

  // Fix: missing refs for audio and processor
  const audioContextRef = useRef(null);
  const processorRef = useRef(null);



  const appendLog = m => setLog(p => `${p}\n${new Date().toLocaleTimeString()} - ${m}`);

  /* ---------- scroll chat on new message ---------- */
  useEffect(()=>{
    if(chatRef.current) chatRef.current.scrollTop = chatRef.current.scrollHeight;
  },[messages]);

  /* ---------- teardown on unmount ---------- */
  useEffect(()=>()=> stopRecognition(),[]);

  /* ---------- derive callActive from logs ---------- */
  useEffect(()=>{
    if (log.includes("Call connected"))  setCallActive(true);
    if (log.includes("Call ended"))      setCallActive(false);
  },[log]);
  /* ------------------------------------------------------------------ *
   *  START RECOGNITION + WS
   * ------------------------------------------------------------------ */
  const startRecognition = async () => {
      // mind-map reset not needed
      setMessages([]);
      appendLog("🎤 PCM streaming started");

      // 1) open WS
      const socket = new WebSocket(`${WS_URL}/realtime`);
      socket.binaryType = "arraybuffer";

      socket.onopen = () => {
        appendLog("🔌 WS open");
        console.log("WebSocket connection OPENED to backend!");
      };
      socket.onclose = () => {
        console.log("WebSocket connection CLOSED.");
      };
      socket.onerror = (err) => {
        console.error("WebSocket error:", err);
      };
      socket.onmessage = handleSocketMessage;
      socketRef.current = socket;

      // 2) setup Web Audio for raw PCM @16 kHz
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const audioCtx = new (window.AudioContext || window.webkitAudioContext)({
        sampleRate: 16000
      });
      audioContextRef.current = audioCtx;

      const source = audioCtx.createMediaStreamSource(stream);

      // 3) ScriptProcessor with small buffer for low latency (256 or 512 samples)
      const bufferSize = 512; 
      const processor  = audioCtx.createScriptProcessor(bufferSize, 1, 1);
      processorRef.current = processor;

      processor.onaudioprocess = (evt) => {
        const float32 = evt.inputBuffer.getChannelData(0);
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
      };

      source.connect(processor);
      processor.connect(audioCtx.destination);
      setRecording(true);
    };

    const stopRecognition = () => {
      if (processorRef.current) {
        try { processorRef.current.disconnect(); } catch {}
        processorRef.current = null;
      }
      if (audioContextRef.current) {
        try { audioContextRef.current.close(); } catch {}
        audioContextRef.current = null;
      }
      if (socketRef.current) {
        try { socketRef.current.close(); } catch {}
        socketRef.current = null;
      }
      setRecording(false);
      appendLog("🛑 PCM streaming stopped");
    };

    // Helper to dedupe consecutive identical messages
    const pushIfChanged = (arr, msg) => {
      // Only dedupe if the last message is from the same speaker and has the same text
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
      // --- Handle relay/broadcast messages with {sender, message} ---
      if (payload.sender && payload.message) {
        // Route all relay messages through the same logic
        payload.speaker = payload.sender;
        payload.content = payload.message;
        // fall through to unified logic below
      }
      const { type, content = "", message = "", function_call, speaker } = payload;
      const txt = content || message;
      const msgType = (type || "").toLowerCase();

      /* ---------- USER BRANCH ---------- */
      if (msgType === "user" || speaker === "User") {
        setActiveSpeaker("User");
        // Always append user message immediately, do not dedupe
        setMessages(prev => [...prev, { speaker: "User", text: txt }]);

        appendLog(`User: ${txt}`);
        return;
      }

      /* ---------- ASSISTANT STREAM ---------- */
      if (type === "assistant_streaming") {
        setActiveSpeaker("Assistant");
        setMessages(prev => {
          if (prev.at(-1)?.streaming) {
            return prev.map((m,i)=> i===prev.length-1 ? {...m, text:txt} : m);
          }
          return [...prev, { speaker:"Assistant", text:txt, streaming:true }];
        });
        return;
      }

      /* ---------- ASSISTANT FINAL ---------- */
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
      }
    };
  
  /* ------------------------------------------------------------------ *
   *  OUTBOUND ACS CALL
   * ------------------------------------------------------------------ */
  const startACSCall = async () => {
    if (!/^\+\d+$/.test(targetPhoneNumber)) {
      alert("Enter phone in E.164 format e.g. +15551234567");
      return;
    }
    try {
      const res = await fetch(`${API_BASE_URL}/api/call`, {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body: JSON.stringify({ target_number: targetPhoneNumber }),
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

      // relay WS
      const relay = new WebSocket(`${WS_URL}/relay`);
      relay.onopen = () => appendLog("Relay WS connected");
      relay.onmessage = ({data}) => {
        try {
          const obj = JSON.parse(data);
          if (obj.type?.startsWith("tool_")) {
            handleSocketMessage({ data: JSON.stringify(obj) });
            return;
          }
          const { sender, message } = obj;
          setMessages(m => [...m, { speaker: sender, text: message }]);
          setActiveSpeaker(sender);
          appendLog(`[Relay] ${sender}: ${message}`);
        } catch {
          appendLog("Relay parse error");
        }
      };
      relay.onclose = () => {
        appendLog("Relay WS disconnected");
        setCallActive(false);
        setActiveSpeaker(null);
        setFunctionCalls([]);
        setCallResetKey(k=>k+1);
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
      {/* Health Status - Top Right */}
      <div style={{...styles.healthIndicator, display: "none"}}>
        <HealthStatusIndicator
          healthStatus={healthStatus}
          readinessStatus={readinessStatus}
          overallStatus={overallStatus}
          onRefresh={refresh}
          compact={true}
        />
      </div>

      {/* Main iPad-sized Container */}
      <div style={styles.mainContainer}>
        {/* Waveform Section */}
        <div style={styles.waveformSection}>
          <WaveformVisualization 
            isActive={recording || !!activeSpeaker} 
            speaker={activeSpeaker} 
          />
        </div>

        {/* Chat Messages */}
        <div style={styles.chatSection} ref={chatRef}>
          <div style={styles.chatSectionIndicator}></div>
          <div style={styles.messageContainer}>
            {messages.map((message, index) => (
              <ChatBubble key={index} message={message} />
            ))}
          </div>
        </div>

        {/* Control Buttons */}
        <div style={styles.controlSection}>
          <div style={styles.controlContainer}>
            {/* Microphone Button */}
            <button
              style={styles.controlButton(recording)}
              onClick={recording ? stopRecognition : startRecognition}
              title={recording ? "Stop Recording" : "Start Recording"}
            >
              🎤
            </button>
            
            {/* Phone Call Button */}
            <button
              style={styles.controlButton(false, 'phone')}
              onClick={() => setShowPhoneInput(!showPhoneInput)}
              title="Phone Call"
            >
              📞
            </button>
            
            {/* Close Button */}
            <button
              style={styles.controlButton(false, 'close')}
              onClick={stopRecognition}
              title="End Session"
            >
              ✕
            </button>
          </div>
        </div>
      </div>

      {/* Phone Input Panel */}
      {showPhoneInput && (
        <div style={styles.phoneInputSection}>
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
            style={styles.phoneButton(callActive)}
          >
            {callActive ? "End Call" : "Call"}
          </button>
        </div>
      )}
    </div>
  );
}
