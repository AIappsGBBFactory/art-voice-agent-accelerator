// src/RealTimeVoiceApp.jsx
import React, { useEffect, useRef, useState } from 'react';
import {
  AudioConfig,
  SpeechConfig,
  SpeechRecognizer,
  PropertyId,
} from 'microsoft-cognitiveservices-speech-sdk';
import VoiceSphere from './components/VoiceSphere';
import "reactflow/dist/style.css";
import { useHealthMonitor } from "./hooks/useHealthMonitor";
import HealthStatusIndicator from "./components/HealthStatusIndicator";

/* ------------------------------------------------------------------ *
 *  ENV VARS
 * ------------------------------------------------------------------ */
const {
  VITE_AZURE_SPEECH_KEY: AZURE_SPEECH_KEY,
  VITE_AZURE_REGION:     AZURE_REGION,
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


  /* ---------- mind‑map state ---------- */
  // const rootUser      = { id:"user-root",      data:{label:"👤 User"},      position:{x:-220,y:0},
  //                         style:{background:"#0F766E",color:"#fff"} };
  // const rootAssistant = { id:"assistant-root", data:{label:"🤖 Assistant"}, position:{x: 220,y:0},
  //                         style:{background:"#4338CA",color:"#fff"} };

  // const [nodes, setNodes] = useState([rootUser, rootAssistant]);
  // const [edges, setEdges] = useState([]);

  // all of our former “mind-map” state now lives here:
  const [functionCalls, setFunctionCalls] = useState([]);
  const [callResetKey, setCallResetKey]   = useState(0);

  /* ---------- refs ---------- */
  // const idRef        = useRef(0);
  const chatRef      = useRef(null);
  const socketRef    = useRef(null);
  const recognizerRef= useRef(null);

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

  /* ---------- STOP & RESET on end ---------- */
  const stopRecognition = () => {
    recognizerRef.current?.stopContinuousRecognitionAsync();
    if (socketRef.current?.readyState === WebSocket.OPEN)
      socketRef.current.close();

    setRecording(false);
    setActiveSpeaker(null);

    // reset all sphere state
    setFunctionCalls([]);
    setCallResetKey(k=>k+1);

    appendLog("🛑 Recognition stopped");
  };

  /* ------------------------------------------------------------------ *
   *  SEND USER SPEECH → BACKEND
   * ------------------------------------------------------------------ */
  const sendToBackend = text => {
    if (socketRef.current?.readyState === WebSocket.OPEN)
      socketRef.current.send(JSON.stringify({ text }));
  };

  const handleUserSpeech = userText => {
    setMessages(ms => [...ms, { speaker:"User", text:userText }]);
    setActiveSpeaker("User");
    appendLog(`User: ${userText}`);
    sendToBackend(userText);
  };

  /* ------------------------------------------------------------------ *
   *  START RECOGNITION + WS
   * ------------------------------------------------------------------ */
  const startRecognition = () => {
    setMessages([]);
    setFunctionCalls([]);
    setCallResetKey(k=>k+1);

    /* Azure Speech config */
    const cfg = SpeechConfig.fromSubscription(AZURE_SPEECH_KEY, AZURE_REGION);
    cfg.speechRecognitionLanguage = "en-US";
    const rec = new SpeechRecognizer(cfg, AudioConfig.fromDefaultMicrophoneInput());
    rec.properties.setProperty(PropertyId.Speech_SegmentationSilenceTimeoutMs, "800");
    rec.properties.setProperty(PropertyId.Speech_SegmentationStrategy, "Semantic");
    recognizerRef.current = rec;

    let lastInterrupt = Date.now();
    rec.recognizing = (_, e) => {
      if (e.result.text.trim() &&
          socketRef.current?.readyState === WebSocket.OPEN &&
          Date.now()-lastInterrupt > 1000)
      {
        socketRef.current.send(JSON.stringify({ type:"interrupt" }));
        appendLog("→ Sent interrupt");
        lastInterrupt = Date.now();
      }
    };
    rec.recognized = (_, e) => {
      const txt = e.result.text.trim();
      if (txt) handleUserSpeech(txt);
    };

    rec.startContinuousRecognitionAsync();
    setRecording(true);
    appendLog("🎤 Recognition started");

    /* WebSocket for assistant streaming */
    const socket = new WebSocket(`${WS_URL}/realtime`);
    socket.binaryType = "arraybuffer";
    socketRef.current = socket;
    socket.onopen  = () => appendLog("🔌 WS open");
    socket.onclose = () => appendLog("🔌 WS closed");
    socket.onmessage = handleSocketMessage;
  };

  /* ------------------------------------------------------------------ *
   *  HANDLE INCOMING SOCKET MESSAGES
   * ------------------------------------------------------------------ */
  const handleSocketMessage = async event => {
    // audio
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

    // JSON frames
    let payload;
    try { payload = JSON.parse(event.data); }
    catch { appendLog("Ignored non-JSON frame"); return; }

    const { type, content="", message="", tool, pct, status, elapsedMs, result, error } = payload;
    const txt = content || message;

    // streaming assistant
    if (type==="assistant_streaming") {
      setActiveSpeaker("Assistant");
      setMessages(prev => {
        if (prev.at(-1)?.streaming) {
          return prev.map((m,i) =>
            i===prev.length-1 ? { ...m, text: txt } : m
          );
        }
        return [...prev, { speaker:"Assistant", text: txt, streaming:true }];
      });
      return;
    }

    // final assistant
    if (type==="assistant"||type==="status") {
      setActiveSpeaker("Assistant");
      setMessages(prev => {
        if (prev.at(-1)?.streaming) {
          return prev.map((m,i) =>
            i===prev.length-1 ? { speaker:"Assistant", text: txt } : m
          );
        }
        return [...prev, { speaker:"Assistant", text: txt }];
      });
      appendLog("🤖 Assistant responded");
      return;
    }

    // tool start
    if (type==="tool_start") {
      const callId = `${tool}-${Date.now()}`;
      setFunctionCalls(fc => [...fc, { id:callId, name:tool, status:"running" }]);
      setMessages(prev => [
        ...prev,
        { speaker:"Assistant", isTool:true, text:`🛠️ tool ${tool} started 🔄` }
      ]);
      appendLog(`⚙️ ${tool} started`);
      return;
    }

    // tool progress
    if (type==="tool_progress") {
      setMessages(prev =>
        prev.map((m,i,arr) =>
          i===arr.length-1 && m.text.startsWith(`🛠️ tool ${tool}`)
            ? { ...m, text:`🛠️ tool ${tool} ${pct}% 🔄` }
            : m
        )
      );
      appendLog(`⚙️ ${tool} ${pct}%`);
      return;
    }

    // tool end
    if (type==="tool_end") {
      setFunctionCalls(fc =>
        fc.map(f =>
          f.name===tool
            ? { ...f, status: status==="success" ? "completed" : "error" }
            : f
        )
      );
      // float out then remove
      setTimeout(() => {
        setFunctionCalls(fc => fc.filter(f => f.name!==tool));
      }, 2000);

      const finalText = status==="success"
        ? `🛠️ tool ${tool} completed ✔️\n${JSON.stringify(result, null,2)}`
        : `🛠️ tool ${tool} failed ❌\n${error}`;
      setMessages(prev =>
        prev.map((m,i,arr) =>
          i===arr.length-1 && m.text.startsWith(`🛠️ tool ${tool}`)
            ? { ...m, text: finalText }
            : m
        )
      );
      appendLog(`⚙️ ${tool} ${status} (${elapsedMs}ms)`);
      return;
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
          <div style={{ flex: 1, display: 'flex', justifyContent: 'flex-end' }}>
            <HealthStatusIndicator
              healthStatus={healthStatus}
              readinessStatus={readinessStatus}
              overallStatus={overallStatus}
              onRefresh={refresh}
              compact={true}
            />
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
