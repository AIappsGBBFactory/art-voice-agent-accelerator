// src/RealTimeVoiceApp.jsx
import React, { useEffect, useRef, useState } from 'react';
import VoiceSphere from './components/VoiceSphere';
import "reactflow/dist/style.css";
// import { useHealthMonitor } from "./hooks/useHealthMonitor";
// import HealthStatusIndicator from "./components/HealthStatusIndicator";

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
    fontFamily: "Segoe UI, Roboto, sans-serif",
    background: "linear-gradient(135deg, rgba(20,25,35,0.85), rgba(30,35,45,0.85))",
    backdropFilter: "blur(12px)",
    WebkitBackdropFilter: "blur(12px)",
    boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.05), 0 8px 32px rgba(0,0,0,0.6)",
    borderRadius: "20px",
    color: "#E5E7EB",
    minHeight: "100vh",
    padding: 32,
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: 40,
  },
  header:       { width:"100%", maxWidth:1080, textAlign:"center" },
  headerTitle:  { fontSize:"3rem", fontWeight:700, marginBottom:8, textShadow:"0 2px 8px rgba(88,166,255,0.3)" },
  headerSubtitle:{ fontSize:"1.1rem", color:"#9CA3AF", textShadow:"0 2px 8px rgba(88,166,255,0.3)" },

  chatWrapper: { background:"#263238", borderRadius:12, padding:20,
                 width:"95%", maxWidth:1080, height:480, overflow:"hidden",
                 display:"flex", flexDirection:"column" },
  chatScroll:  { flex:1, overflowY:"auto", padding:"12px 18px" },

  controlBar: { textAlign:"center", width:"100%" },
  primaryBtn: rec => ({
    padding:"14px 40px", border:"none", borderRadius:10,
    fontWeight:600, fontSize:"1rem", cursor:"pointer",
    background: rec ? "#D13438" : "#107C10", color:"#fff"
  }),

  secondRow: { display:"flex", gap:32, width:"100%", maxWidth:1080,
               alignItems:"center", justifyContent:"center" },
  card:      { flex:1, background:"#263238", borderRadius:12, padding:20,
               height:300, display:"flex", alignItems:"center", justifyContent:"center",
               position:"relative" },

  logsWrapper:{ width:"100%", maxWidth:1080 },
  logsPre:    { background:"#17202A", padding:14, borderRadius:10,
                fontSize:"0.9rem", maxHeight:260, overflow:"auto", whiteSpace:"pre-wrap" },

  phoneWidget:{ position:"fixed", right:28, bottom:28, width:220, height:275,
                  display:"flex", alignItems:"center", justifyContent:"center" },
};

/* ------------------------------------------------------------------ *
 *  CHAT BUBBLE
 * ------------------------------------------------------------------ */
const ChatBubble = ({ message }) => {
  const { speaker, text, isTool, streaming } = message;
  const isUser = speaker === "User";
  return (
    <div style={{ display:"flex", justifyContent: isUser ? "flex-end" : "flex-start", marginBottom:16 }}>
      <div style={{
        background: isTool ? "rgba(26,101,112,0.2)"
                    : isUser ? "#0078D4"
                    : "#394B59",
        color:"#fff", padding:"12px 16px", borderRadius:20,
        maxWidth:"75%", lineHeight:1.5, boxShadow:"0 2px 6px rgba(0,0,0,.2)"
      }}>
        <span style={{ opacity: streaming ? 0.7 : 1 }}>
          {text.split("\n").map((line,i)=><p key={i} style={{margin:"4px 0"}}>{line}</p>)}
          {streaming && <em>▌</em>}
        </span>
        <span style={{
          display:"block", fontSize:"0.8rem", color:"#B0BEC5",
          marginTop:8, textAlign: isUser ? "right" : "left"
        }}>
          { isTool
              ? "🛠️ Agent Called Tool"
              : isUser
                ? "👤 User"
                : "🤖 Agent" }
        </span>
      </div>
    </div>
  );
};

/* ------------------------------------------------------------------ *
 *  MAIN COMPONENT
 * ------------------------------------------------------------------ */
export default function RealTimeVoiceApp() {
  /* ---------- state ---------- */
  const [messages, setMessages]       = useState([]);
  const [log, setLog]                 = useState("");
  const [recording, setRecording]     = useState(false);
  const [targetPhoneNumber, setTargetPhoneNumber] = useState("");
  const [callActive, setCallActive]   = useState(false);
  const [activeSpeaker, setActiveSpeaker] = useState(null);

  // /* ---------- health monitoring ---------- */
  // const { 
  //   healthStatus = { isHealthy: null, lastChecked: null, responseTime: null, error: null },
  //   readinessStatus = { status: null, timestamp: null, responseTime: null, checks: [], lastChecked: null, error: null },
  //   overallStatus = { isHealthy: false, hasWarnings: false, criticalErrors: [] },
  //   refresh = () => {} 
  // } = useHealthMonitor({
  //   baseUrl: API_BASE_URL,
  //   healthInterval: 30000,
  //   readinessInterval: 15000,
  //   enableAutoRefresh: true,
  // });


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
      {/* HEADER */}
      <header style={styles.header}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
          <div style={{ flex: 1 }} />
          <div style={{ textAlign: 'center' }}>
            <h1 style={styles.headerTitle}>🎙️ RTInsuranceAgent</h1>
            <p style={styles.headerSubtitle}>
              Transforming patient care with real-time, intelligent voice interactions
            </p>
          </div>
        </div>
      </header>

      {/* CHAT */}
      <section style={styles.chatWrapper}>
        <div ref={chatRef} style={styles.chatScroll}>
          {messages.map((m,i)=> <ChatBubble key={i} message={m} />)}
        </div>
      </section>

      {/* START/STOP */}
      <div style={styles.controlBar}>
        <button
          style={styles.primaryBtn(recording)}
          onClick={recording ? stopRecognition : startRecognition}
        >
          {recording ? "⏹ End Conversation" : "▶ Start Conversation"}
        </button>
      </div>

      {/* AVATAR + SPHERE */}
      <div style={styles.secondRow}>
        <div style={styles.card}>
          <VoiceSphere
            speaker={activeSpeaker}
            active={!!activeSpeaker}
            functionCalls={functionCalls}
            resetKey={callResetKey}
          />
        </div>
      </div>

      {/* LOGS */}
      <div style={styles.logsWrapper}>
        <h3 style={{ marginBottom:8 }}>System Logs</h3>
        <pre style={styles.logsPre}>{log}</pre>
      </div>

      {/* PHONE WIDGET */}
      <div style={{
        position:"fixed",right:-300,bottom:20,width:260,height:350,
        display:"flex",alignItems:"center",justifyContent:"center"
      }}>
        {callActive && (
          <div style={{
            position:"absolute", left:"7%", width:"80%", height:"120%",
            borderRadius:20, background:"rgba(0,183,255,0.88)",
            animation:"ring 1.6s ease-out infinite"
          }}/>
        )}
        <img
          src={`${import.meta.env.BASE_URL}phoneimage.png`}
          alt="Phone"
          style={{ width:"100%", height:"auto" }}
        />
        {callActive && (
          <div style={{
            position:"absolute", top:88, left:"63%",
            transform:"translate(-50%,-50%)",
            width:12, height:12, background:"#A3FF12",
            boxShadow:"0 0 6px 3px rgba(73,255,18,0.8)",
            animation:"led 1.2s infinite"
          }}/>
        )}
        <div style={{
          position:"absolute", top:112, left:48, width:134,
          display:"flex", flexDirection:"column", gap:8
        }}>
          <input
            type="tel"
            disabled={callActive}
            value={targetPhoneNumber}
            placeholder="+15551234567"
            onChange={e=>setTargetPhoneNumber(e.target.value)}
            style={{
              background:"#1E293B", color:"#E5E7EB",
              border:"1px solid #374151", borderRadius:4,
              padding:"6px 6px", textAlign:"center",
              fontSize:"0.8rem", opacity: callActive ? 0.6 : 1
            }}
          />
          <button
            onClick={startACSCall}
            style={{
              background: callActive?"#DC2626":"#2563EB",
              color:"#fff", border:"none", borderRadius:4,
              fontSize:"0.8rem", fontWeight:600, padding:"8px 0",
              cursor:"pointer",
              animation: callActive ? "btnGlow 1.4s infinite" : undefined
            }}
          >
            {callActive ? "End" : "Call"}
          </button>
        </div>
      </div>
    </div>
  );
}
