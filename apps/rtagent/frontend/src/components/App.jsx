import React, { useCallback, useEffect, useRef, useState } from 'react';
import "reactflow/dist/style.css";
import BackendIndicator from './common/BackendIndicator';
import HelpButton from './common/HelpButton';
import ChatBubble from './chat/ChatBubble';
import WaveformVisualization from './visualizations/WaveformVisualization';
import { insertGlobalStyles, styles } from './AppStyles';
import { createNewSessionId, getOrCreateSessionId } from '../utils/session';

// Environment configuration
const backendPlaceholder = '__BACKEND_URL__';
const API_BASE_URL = backendPlaceholder.startsWith('__') 
  ? import.meta.env.VITE_BACKEND_BASE_URL || 'http://localhost:8000'
  : backendPlaceholder;

const WS_URL = API_BASE_URL.replace(/^https?/, "wss");
const DEFAULT_TTS_SAMPLE_RATE = 16000;

const resampleToSampleRate = (input, sourceRate, targetRate) => {
  if (!input || input.length === 0 || !Number.isFinite(sourceRate) || !Number.isFinite(targetRate) || sourceRate <= 0 || targetRate <= 0 || sourceRate === targetRate) {
    return input;
  }
  const ratio = targetRate / sourceRate;
  const outputLength = Math.max(1, Math.round(input.length * ratio));
  const output = new Float32Array(outputLength);
  for (let i = 0; i < outputLength; i++) {
    const index = i / ratio;
    const i0 = Math.floor(index);
    const i1 = Math.min(i0 + 1, input.length - 1);
    const weight = index - i0;
    output[i] = input[i0] * (1 - weight) + input[i1] * weight;
  }
  return output;
};

const applyFadeEnvelope = (buffer, fadeInSamples = 0, fadeOutSamples = 0) => {
  if (!buffer || typeof buffer.length !== "number" || buffer.length === 0) {
    return buffer;
  }
  const length = buffer.length;
  if (fadeInSamples > 0) {
    const limit = Math.min(fadeInSamples, length);
    for (let i = 0; i < limit; i++) {
      const ratio = limit > 1 ? i / (limit - 1) : 1;
      buffer[i] = buffer[i] * ratio;
    }
  }
  if (fadeOutSamples > 0) {
    const limit = Math.min(fadeOutSamples, length);
    const start = length - limit;
    for (let i = 0; i < limit; i++) {
      const ratio = limit > 1 ? (limit - 1 - i) / (limit - 1) : 0;
      const idx = start + i;
      buffer[idx] = buffer[idx] * ratio;
    }
  }
  return buffer;
};

//     if (typeof summary.assistantTurns === "number") {
// Main voice application component
function RealTimeVoiceApp() {
  useEffect(() => {
    insertGlobalStyles();
  }, []);

  const USER_SPEECH_LEVEL_THRESHOLD = 0.08;
  const USER_SILENCE_WINDOW_MS = 180;

  // Component state
  const [messages, setMessages] = useState([]);
  const messagesRef = useRef(messages);
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);
  const [log, setLog] = useState("");
  const [recording, setRecording] = useState(false);
  const [targetPhoneNumber, setTargetPhoneNumber] = useState("");
  const [callActive, setCallActive] = useState(false);
  const [activeSpeaker, setActiveSpeaker] = useState(null);
  const [activeAgentName, setActiveAgentName] = useState(null);
  const [toolActivity, setToolActivity] = useState(null);
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

  const [showResetTooltip, setShowResetTooltip] = useState(false);
  const [showMicTooltip, setShowMicTooltip] = useState(false);
  const [showPhoneTooltip, setShowPhoneTooltip] = useState(false);
  const [resetHovered, setResetHovered] = useState(false);
  const [micHovered, setMicHovered] = useState(false);
  const [phoneHovered, setPhoneHovered] = useState(false);
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

  const chatRef = useRef(null);
  const messageContainerRef = useRef(null);
  const socketRef = useRef(null);
  const phoneButtonRef = useRef(null);

  const audioContextRef = useRef(null);
  const processorRef = useRef(null);
  const analyserRef = useRef(null);
  const micStreamRef = useRef(null);
  const micStreamingActiveRef = useRef(false);
  const micStartPromiseRef = useRef(null);
  const playbackAudioContextRef = useRef(null);
  const pcmSinkRef = useRef(null);

  const [audioLevel, setAudioLevel] = useState(0);
  const audioLevelRef = useRef(0);

  const messageCounterRef = useRef(0);
  const pendingUserRef = useRef(null);
  const activeAssistantRef = useRef({
    messageId: null,
    streaming: false,
    speaking: false,
    speechStartedAt: null,
    respondedAt: null,
    originUserMessageId: null,
    originUserStartedAt: null,
    bufferedText: "",
    finalText: "",
    incomplete: false,
    agentName: null,
  });
  const bargeInRef = useRef(null);
  const assistantAudioProgressRef = useRef(new Map());
  const currentSpeechMessageRef = useRef(null);
  const toolMessageRef = useRef(new Map());
  const lastToolMessageIdRef = useRef(null);
  const workletMessageHandlerRef = useRef(null);
  const userSpeechDraftRef = useRef(null);
  const assistantBacklogRef = useRef([]);

  const createMessage = useCallback((message = {}) => {
    const id = `msg-${Date.now()}-${messageCounterRef.current++}`;
    const {
      metrics: providedMetrics,
      streaming: streamingFlag = false,
      timestamp,
      incomplete = false,
      ...remaining
    } = message;
    return {
      id,
      streaming: streamingFlag,
      timestamp: timestamp ?? Date.now(),
      incomplete,
      ...remaining,
      metrics: { ...(providedMetrics || {}) },
    };
  }, []);

  const appendMessage = useCallback((message) => {
    const msg = createMessage(message);
    setMessages((prev) => [...prev, msg]);
    return msg;
  }, [createMessage]);

  const updateMessage = useCallback((id, updater) => {
    if (!id) {
      return;
    }
    setMessages((prev) =>
      prev.map((msg) => {
        if (msg.id !== id) {
          return msg;
        }
        const updates = updater(msg);
        if (!updates) {
          return msg;
        }
        const merged = { ...msg, ...updates };
        if (updates.metrics) {
          merged.metrics = { ...(msg.metrics || {}), ...updates.metrics };
        }
        if (updates.toolState) {
          merged.toolState = { ...(msg.toolState || {}), ...updates.toolState };
        }
        return merged;
      })
    );
  }, []);

  const repositionMessageAfter = useCallback((messageId, afterMessageId) => {
    if (!messageId || !afterMessageId || messageId === afterMessageId) {
      return;
    }
    setMessages((prev) => {
      const currentIdx = prev.findIndex((msg) => msg.id === messageId);
      const afterIdx = prev.findIndex((msg) => msg.id === afterMessageId);
      if (currentIdx === -1 || afterIdx === -1 || currentIdx === afterIdx + 1) {
        return prev;
      }
      const reordered = [...prev];
      const [message] = reordered.splice(currentIdx, 1);
      const targetIdx = reordered.findIndex((msg) => msg.id === afterMessageId);
      if (targetIdx === -1) {
        return prev;
      }
      reordered.splice(targetIdx + 1, 0, message);
      return reordered;
    });
  }, []);

  const anchorAssistantAfterTool = useCallback((assistantMessageId, originUserMessageId) => {
    const snapshot = lastToolMessageIdRef.current;
    if (!assistantMessageId || !snapshot?.messageId) {
      return;
    }
    if (
      snapshot.userMessageId &&
      originUserMessageId &&
      snapshot.userMessageId !== originUserMessageId
    ) {
      return;
    }
    repositionMessageAfter(assistantMessageId, snapshot.lastAssistantId || snapshot.messageId);
    lastToolMessageIdRef.current = {
      ...snapshot,
      lastAssistantId: assistantMessageId,
    };
  }, [repositionMessageAfter]);

  // Disabled to preserve natural message order
  // const repositionMessageAfter = useCallback((messageId, afterMessageId) => {
  //   if (!messageId || !afterMessageId) {
  //     return;
  //   }
  //   setMessages((prev) => {
  //     const currentIdx = prev.findIndex((msg) => msg.id === messageId);
  //     if (currentIdx === -1) {
  //       return prev;
  //     }
  //     const afterIdx = prev.findIndex((msg) => msg.id === afterMessageId);
  //     if (afterIdx === -1 || currentIdx === afterIdx + 1) {
  //       return prev;
  //     }
  //     const reordered = [...prev];
  //     const [message] = reordered.splice(currentIdx, 1);
  //     const nextAfterIdx = reordered.findIndex((msg) => msg.id === afterMessageId);
  //     const targetIdx = nextAfterIdx === -1 ? reordered.length : nextAfterIdx + 1;
  //     reordered.splice(targetIdx, 0, message);
  //     return reordered;
  //   });
  // }, [setMessages]);

  // Disabled to preserve natural message order
  // const anchorAssistantAfterTool = useCallback((assistantMessageId, originUserMessageId) => {
  //   const toolSnapshot = lastToolMessageIdRef.current;
  //   if (!assistantMessageId || !toolSnapshot?.messageId) {
  //     return;
  //   }
  //   if (
  //     toolSnapshot.userMessageId &&
  //     originUserMessageId &&
  //     toolSnapshot.userMessageId !== originUserMessageId
  //   ) {
  //     return;
  //   }
  //   const anchorAfterId = toolSnapshot.lastAssistantId || toolSnapshot.messageId;
  //   repositionMessageAfter(assistantMessageId, anchorAfterId);
  //   lastToolMessageIdRef.current = {
  //     ...toolSnapshot,
  //     lastAssistantId: assistantMessageId,
  //   };
  // }, [repositionMessageAfter]);

  const finalizeActiveAssistantMessage = useCallback((reason = "unknown") => {
    const current = activeAssistantRef.current;
    if (!current?.messageId) {
      return null;
    }
    console.info(`Finalizing assistant message (reason: ${reason}), messageId: ${current.messageId}`);
    const timestamp = Date.now();
    const summaryText = current.finalText || current.bufferedText || null;
    const messageId = current.messageId;

    updateMessage(messageId, (msg) => {
      const nextText = summaryText || msg.text || "";
      const nextMetrics = {
        ...(msg.metrics || {}),
        finalizedAt: timestamp,
      };
      const nextAgent = msg.agentName || current.agentName || null;
      const updates = {
        streaming: false,
        incomplete: false,
        agentName: nextAgent,
        metrics: nextMetrics,
        timestamp: timestamp,
      };
      if (nextText && nextText !== msg.text) {
        updates.text = nextText;
      }
      return updates;
    });

    currentSpeechMessageRef.current = null;
    assistantAudioProgressRef.current.delete(messageId);
    
    // Process any pending backlog tasks to preserve incomplete messages before clearing
    if (assistantBacklogRef.current.length > 0) {
      console.info(`Processing ${assistantBacklogRef.current.length} pending backlog tasks before finalization`);
      const pendingTasks = assistantBacklogRef.current.slice();
      assistantBacklogRef.current = [];
      
      // Execute pending tasks to ensure they create separate messages
      pendingTasks.forEach((task, index) => {
        try {
          console.info(`Executing pending task ${index + 1}/${pendingTasks.length}`);
          task();
        } catch (error) {
          console.error(`Pending task ${index + 1} failed during finalization:`, error);
        }
      });
    } else {
      assistantBacklogRef.current = [];
    }

    activeAssistantRef.current = {
      messageId: null,
      streaming: false,
      speaking: false,
      speechStartedAt: null,
      respondedAt: current.respondedAt ?? timestamp,
      originUserMessageId: current.originUserMessageId ?? null,
      originUserStartedAt: current.originUserStartedAt ?? null,
      bufferedText: "",
      finalText: "",
      incomplete: false,
      agentName: null,
    };

    return messageId;
  }, [updateMessage]);

  const isUserTranscriptReady = useCallback(() => {
    const pending = pendingUserRef.current;
    if (!pending || !pending.userMessageId) {
      return true;
    }
    if (pending.textReady && !(pending.requireFinal && !pending.finalReceived)) {
      return true;
    }
    const currentMessages = messagesRef.current || [];
    const target = currentMessages.find((msg) => msg.id === pending.userMessageId);
    if (!target) {
      return false;
    }
    const text = typeof target.text === "string" ? target.text.trim() : "";
    const hasContent = text.length > 0;
    if (hasContent && !pending.textReady) {
      pendingUserRef.current = { ...pending, textReady: true };
    }
    const nextPending = pendingUserRef.current || pending;
    if (nextPending.requireFinal && !nextPending.finalReceived) {
      return false;
    }
    return hasContent;
  }, []);

  const enqueueAssistantTask = useCallback((task) => {
    if (typeof task !== "function") {
      return;
    }
    assistantBacklogRef.current.push(task);
  }, []);

  const flushAssistantBacklog = useCallback(() => {
    if (!assistantBacklogRef.current.length) {
      return;
    }
    if (!isUserTranscriptReady()) {
      return;
    }
    const backlog = assistantBacklogRef.current.slice();
    assistantBacklogRef.current = [];
    backlog.forEach((task) => {
      try {
        task();
      } catch (error) {
        console.error("Assistant backlog task failed", error);
      }
    });
  }, [isUserTranscriptReady]);

  const parseIsoTimestamp = (value) => {
    if (!value || typeof value !== "string") {
      return null;
    }
    const parsed = Date.parse(value);
    return Number.isNaN(parsed) ? null : parsed;
  };

  const computePendingLatency = (pending, fallbackStopTs = null) => {
    if (!pending) {
      return null;
    }

    const stopCandidates = [pending.latencyStopAt, fallbackStopTs].filter(
      (value) => typeof value === "number" && !Number.isNaN(value),
    );
    const startCandidates = [
      pending.latencyStartAt,
      pending.audioEndAt,
      pending.audioLastChunkAt,
      pending.audioStartedAt,
    ].filter((value) => typeof value === "number" && !Number.isNaN(value));

    if (!stopCandidates.length) {
      return null;
    }

    const stopTs = stopCandidates[0];
    const startTs = startCandidates[0];
    const startedAt = typeof pending.startedAt === "number" && !Number.isNaN(pending.startedAt)
      ? pending.startedAt
      : null;

    let latency = null;

    if (typeof startTs === "number" && stopTs > startTs) {
      latency = stopTs - startTs;
    } else if (typeof startTs === "number") {
      latency = Math.max(stopTs - startTs, 0);
    }

    if ((latency === null || latency <= 0) && typeof startedAt === "number" && stopTs > startedAt) {
      latency = stopTs - startedAt;
    }

    if (latency !== null && latency < 0) {
      latency = 0;
    }

    return latency;
  };

  const mergeAssistantText = useCallback((existingText = "", incomingText = "") => {
    if (!incomingText) {
      return existingText;
    }
    if (!existingText) {
      return incomingText;
    }
    if (incomingText === existingText) {
      return existingText;
    }
    if (incomingText.startsWith(existingText)) {
      return incomingText;
    }
    if (existingText.startsWith(incomingText)) {
      return existingText;
    }
    const maxOverlap = Math.min(existingText.length, incomingText.length);
    let overlap = 0;
    for (let i = maxOverlap; i > 0; i--) {
      if (existingText.endsWith(incomingText.slice(0, i))) {
        overlap = i;
        break;
      }
    }
    if (overlap > 0) {
      return `${existingText}${incomingText.slice(overlap)}`;
    }
    return `${existingText}${incomingText}`;
  }, []);

  const processAssistantStreaming = ({ payload, text, speaker }) => {
    const streamingSpeaker = speaker || "Assistant";
    const prevCtx = activeAssistantRef.current;
    const streamingAgentName = payload.agent || streamingSpeaker || prevCtx?.agentName || null;
    setActiveSpeaker(streamingSpeaker);
    setActiveAgentName(streamingAgentName);
    console.info("Current active agent: " + streamingAgentName)
    const streamingTimestamp = Date.now();

    let messageId = prevCtx?.messageId;
    let updatedText = prevCtx?.bufferedText ?? "";
    const incomingText = text ?? "";
    const hasIncomingText = incomingText.length > 0;

    // Force new message if agent changed, previous message was finalized, or speaker changed
    // But don't create new message if same agent continues after tool call
    const agentChanged = prevCtx?.agentName && prevCtx.agentName !== streamingAgentName;
    const speakerChanged = prevCtx?.messageId && prevCtx.speaker && prevCtx.speaker !== streamingSpeaker;
    const prevFinalized = prevCtx?.messageId && prevCtx.finalizedAt;
    const isToolActive = toolActivity?.status === "running";
    const shouldCreateNewMessage = !messageId || !(prevCtx?.incomplete) || 
      (agentChanged && !isToolActive) || prevFinalized || speakerChanged;
    
    if ((agentChanged && !isToolActive) || speakerChanged) {
      console.info(`Message boundary detected - Agent: ${prevCtx?.agentName} → ${streamingAgentName}, Speaker: ${prevCtx?.speaker} → ${streamingSpeaker}`);
    }

    if (shouldCreateNewMessage) {
      const initialText = hasIncomingText ? incomingText : "";
      const streamingMsg = appendMessage({
        speaker: streamingSpeaker,
        text: initialText,
        streaming: true,
        incomplete: true,
        agentName: streamingAgentName,
        timestamp: streamingTimestamp,
      });
      messageId = streamingMsg.id;
      updatedText = initialText;
      anchorAssistantAfterTool(messageId, originUserMessageId);
    } else if (hasIncomingText) {
      updatedText = mergeAssistantText(prevCtx?.bufferedText ?? "", incomingText);
      const textForUpdate = updatedText;
      updateMessage(messageId, () => ({
        text: textForUpdate,
        streaming: true,
        incomplete: true,
        agentName: streamingAgentName,
      }));
    } else {
      updatedText = prevCtx?.bufferedText ?? "";
      updateMessage(messageId, () => ({
        streaming: true,
        incomplete: true,
        agentName: streamingAgentName,
      }));
    }

    const originUserMessageId =
      pendingUserRef.current?.userMessageId ?? prevCtx?.originUserMessageId ?? null;
    const originUserStartedAt =
      pendingUserRef.current?.startedAt ?? prevCtx?.originUserStartedAt ?? null;
    const isSameMessage = prevCtx?.messageId === messageId;

    activeAssistantRef.current = {
      messageId,
      streaming: true,
      speaking: prevCtx?.speaking ?? false,
      speechStartedAt: prevCtx?.speechStartedAt ?? null,
      respondedAt: prevCtx?.respondedAt ?? streamingTimestamp,
      originUserMessageId,
      originUserStartedAt,
      bufferedText: updatedText,
      finalText: isSameMessage ? prevCtx?.finalText ?? "" : "",
      incomplete: true,
      agentName: streamingAgentName,
      speaker: streamingSpeaker,
    };

    // Keep natural message order - disable repositioning
    // if (originUserMessageId) {
    //   repositionMessageAfter(messageId, originUserMessageId);
    // }
    // anchorAssistantAfterTool(messageId, originUserMessageId);

    if (pendingUserRef.current?.userMessageId) {
      const pending = pendingUserRef.current;
      const latencyMs = computePendingLatency(pending);
      if (latencyMs !== null && pending.latencyMs !== latencyMs) {
        pendingUserRef.current = { ...pending, latencyMs };
      }
      updateMessage(pending.userMessageId, (msg) => ({
        metrics: {
          ...(msg.metrics || {}),
          awaitingResponse: true,
          ...(latencyMs !== null ? { responseLatencyMs: latencyMs } : {}),
        },
      }));
    }
  };

  const processAssistantResponse = ({ payload, text, speaker }) => {
    const assistantSpeaker = speaker || "Assistant";
    const prevCtx = activeAssistantRef.current;
    const assistantAgentName = payload.agent || assistantSpeaker || prevCtx?.agentName || null;
    setActiveSpeaker(assistantSpeaker);
    setActiveAgentName(assistantAgentName);
    const assistantTimestamp = Date.now();

    let assistantMessageId = prevCtx?.messageId;
    if (!assistantMessageId) {
      const currentMessages = messagesRef.current || [];
      for (let idx = currentMessages.length - 1; idx >= 0; idx--) {
        const candidate = currentMessages[idx];
        if (
          candidate?.speaker === assistantSpeaker &&
          (candidate?.streaming || candidate?.incomplete) &&
          (candidate?.agentName ? candidate.agentName === assistantAgentName : true)
        ) {
          assistantMessageId = candidate.id;
          break;
        }
      }
    }
    const incomingText = text ?? "";
    const hasTextUpdate = incomingText.length > 0;
    const previousFinalText = prevCtx?.finalText ?? "";
    const previousBufferedText = prevCtx?.bufferedText ?? "";
    let finalText = hasTextUpdate
      ? incomingText
      : previousFinalText || previousBufferedText || "";

    if (!assistantMessageId) {
      const finalMsg = appendMessage({
        speaker: assistantSpeaker,
        text: finalText,
        streaming: false,
        incomplete: false,
        agentName: assistantAgentName,
        timestamp: assistantTimestamp,
      });
      assistantMessageId = finalMsg.id;
    } else {
      const textForUpdate = finalText;
      updateMessage(assistantMessageId, () => ({
        ...(textForUpdate ? { text: textForUpdate } : {}),
        streaming: false,
        incomplete: false,
        agentName: assistantAgentName,
        timestamp: assistantTimestamp,
      }));
    }

    anchorAssistantAfterTool(
      assistantMessageId,
      activeAssistantRef.current?.originUserMessageId ?? null
    );

    const pending = pendingUserRef.current;
    let latencyMs = null;
    if (pending?.userMessageId) {
      latencyMs = computePendingLatency(pending, assistantTimestamp);
      pendingUserRef.current = null;
      updateMessage(pending.userMessageId, (msg) => ({
        metrics: {
          ...(msg.metrics || {}),
          awaitingResponse: false,
          ...(latencyMs !== null ? { responseLatencyMs: latencyMs } : {}),
        },
      }));
    }

    if (latencyMs !== null) {
      updateMessage(assistantMessageId, (msg) => ({
        streaming: false,
        metrics: {
          ...(msg.metrics || {}),
          responseLatencyMs: latencyMs,
        },
      }));
    } else {
      updateMessage(assistantMessageId, () => ({ streaming: false }));
    }

    activeAssistantRef.current = {
      messageId: assistantMessageId,
      streaming: false,
      speaking: false,
      speechStartedAt: null,
      respondedAt: assistantTimestamp,
      originUserMessageId: prevCtx?.originUserMessageId ?? null,
      originUserStartedAt: prevCtx?.originUserStartedAt ?? null,
      bufferedText: "",
      finalText,
      incomplete: false,
      agentName: assistantAgentName,
    };

    currentSpeechMessageRef.current = assistantMessageId;

    // Keep natural message order - disable repositioning
    // if (prevCtx?.originUserMessageId) {
    //   repositionMessageAfter(assistantMessageId, prevCtx.originUserMessageId);
    // }
    // anchorAssistantAfterTool(assistantMessageId, prevCtx?.originUserMessageId ?? null);

    lastToolMessageIdRef.current = null;

    appendLog("🤖 Assistant responded");
  };

  const previewValue = useCallback((value) => {
    if (value === null || value === undefined) {
      return "-";
    }
    if (typeof value === "string") {
      return value.length > 120 ? `${value.slice(0, 117)}...` : value;
    }
    if (typeof value === "number" || typeof value === "boolean") {
      return String(value);
    }
    try {
      const json = JSON.stringify(value);
      return json.length > 120 ? `${json.slice(0, 117)}...` : json;
    } catch {
      return String(value);
    }
  }, []);

  const formatToolMessage = useCallback((toolName, { status, progress, error, result } = {}) => {
    const trimmedStatus = status ? status.trim() : "";
    const parts = [`🛠️ ${toolName}${trimmedStatus ? ` ${trimmedStatus}` : ""}`];

    if (typeof progress === "number") {
      parts[0] = `${parts[0]} · ${Math.round(progress)}%`;
    }

    if (error) {
      parts.push(`Error: ${error}`);
    } else if (result !== undefined) {
      if (result && typeof result === "object" && !Array.isArray(result)) {
        const entries = Object.entries(result).slice(0, 3);
        if (entries.length === 0) {
          parts.push("Result: (empty)");
        } else {
          const condensed = entries
            .map(([key, value]) => `${key}=${previewValue(value)}`)
            .join(" | ");
          parts.push(`Result: ${condensed}`);
        }
      } else {
        parts.push(`Result: ${previewValue(result)}`);
      }
    }

    return parts.join("\n");
  }, [previewValue]);

  const handleWorkletMessage = useCallback((data) => {
    if (!data || typeof data !== 'object') {
      return;
    }

    if (data.type === 'played') {
      const { messageId, samples } = data;
      if (!messageId || typeof samples !== 'number') {
        return;
      }

      const progressMap = assistantAudioProgressRef.current;
      const entry = progressMap.get(messageId);
      if (!entry) {
        return;
      }

      entry.playedSamples = (entry.playedSamples || 0) + samples;
      if (!entry.startedAt) {
        entry.startedAt = Date.now();
        const ctx = activeAssistantRef.current;
        if (ctx?.messageId === messageId && !ctx.speechStartedAt) {
          activeAssistantRef.current = {
            ...ctx,
            speechStartedAt: entry.startedAt,
          };
        }
      }

      const expectedSamples =
        typeof entry.expectedSamples === "number" && entry.expectedSamples > 0
          ? entry.expectedSamples
          : null;
      let ratio = 0;
      if (expectedSamples) {
        ratio = Math.min(entry.playedSamples / expectedSamples, 1);
      } else if (entry.queuedSamples > 0) {
        ratio = Math.min(entry.playedSamples / entry.queuedSamples, 0.95);
      }
      const playedMs = entry.sampleRate ? (entry.playedSamples / entry.sampleRate) * 1000 : null;
      const totalMs =
        entry.sampleRate && typeof entry.expectedSamples === "number"
          ? (entry.expectedSamples / entry.sampleRate) * 1000
          : null;

      const lastRatio = entry.lastRatio ?? 0;
      const hasExpectedUpdate = Boolean(expectedSamples) && !entry.expectedNotified;
      const shouldUpdate = Math.abs(ratio - lastRatio) >= 0.02 || ratio >= 0.999 || hasExpectedUpdate;
      if (!shouldUpdate) {
        return;
      }

      entry.lastRatio = ratio;
      if (hasExpectedUpdate) {
        entry.expectedNotified = true;
      }
      if (expectedSamples && ratio >= 0.999) {
        entry.completed = true;
      }

      updateMessage(messageId, (msg) => {
        const existingMetrics = msg.metrics || {};
        const nextMetrics = {
          ...existingMetrics,
          playbackProgress: {
            messageId,
            ratio,
            playedMs,
            totalMs: totalMs ?? existingMetrics.playbackProgress?.totalMs ?? null,
          },
        };
        if (totalMs !== null) {
          nextMetrics.speechDurationMs = totalMs;
        }
        return { metrics: nextMetrics };
      });

      if (entry.completed) {
        setTimeout(() => {
          const current = assistantAudioProgressRef.current.get(messageId);
          if (current && current.completed) {
            assistantAudioProgressRef.current.delete(messageId);
          }
        }, 1200);
      }
    } else if (data.type === 'cleared') {
      assistantAudioProgressRef.current.clear();
    }
  }, [updateMessage]);

  useEffect(() => {
    workletMessageHandlerRef.current = handleWorkletMessage;
  }, [handleWorkletMessage]);

  useEffect(() => {
    if (
      recording &&
      audioLevel > USER_SPEECH_LEVEL_THRESHOLD &&
      !userSpeechDraftRef.current &&
      (!pendingUserRef.current || !pendingUserRef.current.userMessageId)
    ) {
      const startedAt = Date.now();
      const draft = appendMessage({
        speaker: "User",
        text: "",
        streaming: true,
        incomplete: true,
        metrics: { awaitingResponse: true, audioDetected: true },
      });
      userSpeechDraftRef.current = {
        messageId: draft.id,
        startedAt,
      };
      setActiveSpeaker("User");
      pendingUserRef.current = {
        userMessageId: draft.id,
        startedAt,
        latencyMs: null,
        textReady: false,
        audioStartedAt: startedAt,
        audioLastChunkAt: null,
        audioEndAt: null,
        latencyStopAt: null,
        latencyStartAt: null,
        requireFinal: true,
        finalReceived: false,
      };
    }
  }, [USER_SPEECH_LEVEL_THRESHOLD, appendMessage, audioLevel, recording]);

  const workletSource = `
    class PcmSink extends AudioWorkletProcessor {
      constructor() {
        super();
        this.queue = [];
        this.samplesProcessed = 0;
        this.port.onmessage = (e) => {
          const data = e.data || {};
          if (data.type === 'push' && data.payload) {
            this.queue.push({
              buffer: new Float32Array(data.payload, 0, data.length || data.payload.byteLength / 4),
              messageId: data.messageId || null,
              offset: 0,
              length: data.length || data.payload.byteLength / 4,
              sourceSamples: data.sourceSamples != null ? data.sourceSamples : (data.length || data.payload.byteLength / 4),
              sourceConsumed: 0,
            });
          } else if (data.type === 'clear') {
            this.queue = [];
            this.samplesProcessed = 0;
            this.port.postMessage({ type: 'cleared' });
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
          const buffer = chunk.buffer;
          const start = chunk.offset || 0;
          const length = chunk.length != null ? chunk.length : buffer.length;
          const remain = length - start;
          if (remain <= 0) {
            this.queue.shift();
            continue;
          }
          const toCopy = Math.min(remain, out.length - i);
          out.set(buffer.subarray(start, start + toCopy), i);
          i += toCopy;
          chunk.offset = start + toCopy;
          this.samplesProcessed += toCopy;
          if (chunk.messageId) {
            const resampledLength = length || buffer.length || 1;
            const sourceSamples = chunk.sourceSamples != null ? chunk.sourceSamples : resampledLength;
            const ratio = sourceSamples / resampledLength;
            let sourceAdvance = Math.round(toCopy * ratio);
            const consumed = chunk.sourceConsumed || 0;
            const remainingSource = Math.max(sourceSamples - consumed, 0);
            if (sourceAdvance > remainingSource) {
              sourceAdvance = remainingSource;
            } else if (sourceAdvance <= 0 && remainingSource > 0 && toCopy > 0) {
              sourceAdvance = Math.min(1, remainingSource);
            }
            chunk.sourceConsumed = consumed + sourceAdvance;
            if (sourceAdvance > 0) {
              this.port.postMessage({
                type: 'played',
                messageId: chunk.messageId,
                samples: sourceAdvance,
              });
            }
          }
          if (chunk.offset >= buffer.length) {
            this.queue.shift();
          }
        }
        return true;
      }
    }
    registerProcessor('pcm-sink', PcmSink);
  `;

  // Initialize playback audio context and worklet (call on user gesture)
  const initializeAudioPlayback = async () => {
    if (playbackAudioContextRef.current) return; // Already initialized
    
    try {
      const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      
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
        const handler = workletMessageHandlerRef.current;
        if (handler) {
          handler(event.data);
        }
      };
      
      // Resume on user gesture
      await audioCtx.resume();
      
      playbackAudioContextRef.current = audioCtx;
      pcmSinkRef.current = sink;
      
      appendLog("🔊 Audio playback initialized");
      console.info("AudioWorklet playback system initialized, context sample rate:", audioCtx.sampleRate);
    } catch (error) {
      console.error("Failed to initialize audio playback:", error);
      appendLog("❌ Audio playback init failed");
    }
  };


  const appendLog = m => setLog(p => `${p}\n${new Date().toLocaleTimeString()} - ${m}`);

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
      setMessages([]);
      messageCounterRef.current = 0;
      pendingUserRef.current = null;
      activeAssistantRef.current = {
        messageId: null,
        streaming: false,
        speaking: false,
        speechStartedAt: null,
        respondedAt: null,
        originUserMessageId: null,
        originUserStartedAt: null,
        bufferedText: "",
        finalText: "",
        incomplete: false,
        agentName: null,
      };
      bargeInRef.current = null;
      toolMessageRef.current.clear();
      assistantBacklogRef.current = [];
      userSpeechDraftRef.current = null;
      lastToolMessageIdRef.current = null;
      micStreamingActiveRef.current = false;
      if (micStartPromiseRef.current) {
        micStartPromiseRef.current = null;
      }
      if (micStreamRef.current) {
        micStreamRef.current.getTracks()?.forEach((track) => track.stop());
        micStreamRef.current = null;
      }
      setRecording(false);
      audioLevelRef.current = 0;
      setAudioLevel(0);
      appendLog("🔈 Waiting for assistant audio before enabling microphone");

      await initializeAudioPlayback();

      const sessionId = getOrCreateSessionId();
      console.info('🔗 [FRONTEND] Starting conversation WebSocket with session_id:', sessionId);

      // 1) open WS with session ID
      const socket = new WebSocket(`${WS_URL}/api/v1/realtime/conversation?session_id=${sessionId}`);
      socket.binaryType = "arraybuffer";

      socket.onopen = () => {
        appendLog("🔌 WS open - Connected to backend!");
        console.info("WebSocket connection OPENED to backend at:", `${WS_URL}/api/v1/realtime/conversation`);
        
        // Always send insurance use case (hardcoded)
        const initMessage = {
          type: 'init',
          use_case: 'insurance',
          session_id: sessionId
        };
        socket.send(JSON.stringify(initMessage));
        console.info('📤 [FRONTEND] Sent use case preselection: insurance');
        appendLog('✅ Selected service: Insurance Services');
      };
      socket.onclose = (event) => {
        appendLog(`🔌 WS closed - Code: ${event.code}, Reason: ${event.reason}`);
        console.info("WebSocket connection CLOSED. Code:", event.code, "Reason:", event.reason);
      };
      socket.onerror = (err) => {
        appendLog("❌ WS error - Check if backend is running");
        console.error("WebSocket error - backend might not be running:", err);
      };
      socket.onmessage = handleSocketMessage;
      socketRef.current = socket;
    };

  const beginMicStreaming = async () => {
    if (micStreamingActiveRef.current) {
      return;
    }
    if (micStartPromiseRef.current) {
      return micStartPromiseRef.current;
    }

    const startPromise = (async () => {
      try {
        const socket = socketRef.current;
        if (!socket || socket.readyState !== WebSocket.OPEN) {
          appendLog("⚠️ Skipping mic start until WebSocket is ready");
          return;
        }

        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        micStreamRef.current = stream;

        const audioCtx = new (window.AudioContext || window.webkitAudioContext)({
          sampleRate: 16000,
        });
        audioContextRef.current = audioCtx;

        const source = audioCtx.createMediaStreamSource(stream);

        const analyser = audioCtx.createAnalyser();
        analyser.fftSize = 256;
        analyser.smoothingTimeConstant = 0.3;
        analyserRef.current = analyser;
        source.connect(analyser);

        const bufferSize = 512;
        const processor = audioCtx.createScriptProcessor(bufferSize, 1, 1);
        processorRef.current = processor;
        analyser.connect(processor);

        processor.onaudioprocess = (evt) => {
          const float32 = evt.inputBuffer.getChannelData(0);

          let sum = 0;
          for (let i = 0; i < float32.length; i++) {
            sum += float32[i] * float32[i];
          }
          const rms = Math.sqrt(sum / float32.length);
          const level = Math.min(1, rms * 10);

          audioLevelRef.current = level;
          setAudioLevel(level);

          const chunkTimestamp = Date.now();
          const pending = pendingUserRef.current;
          if (pending?.userMessageId) {
            const hasSpeech = level >= USER_SPEECH_LEVEL_THRESHOLD;
            let nextPending = null;

            if (hasSpeech) {
              const audioStartedAt = pending.audioStartedAt ?? chunkTimestamp;
              const resumedAfterSilence = pending.audioEndAt !== null || pending.latencyStartAt !== null;
              if (
                pending.audioStartedAt !== audioStartedAt ||
                pending.audioLastChunkAt !== chunkTimestamp ||
                pending.audioEndAt !== null
              ) {
                nextPending = {
                  ...pending,
                  audioStartedAt,
                  audioLastChunkAt: chunkTimestamp,
                  audioEndAt: null,
                  latencyStartAt: resumedAfterSilence ? null : pending.latencyStartAt,
                  latencyStopAt: resumedAfterSilence ? null : pending.latencyStopAt,
                  latencyMs: resumedAfterSilence ? null : pending.latencyMs,
                };
              }
            } else if (pending.audioLastChunkAt) {
              const silenceElapsed = chunkTimestamp - pending.audioLastChunkAt;
              if (silenceElapsed >= USER_SILENCE_WINDOW_MS && pending.audioEndAt == null) {
                nextPending = {
                  ...pending,
                  audioEndAt: pending.audioLastChunkAt,
                  latencyStartAt: pending.latencyStartAt ?? pending.audioLastChunkAt,
                };
              }
            }

            if (nextPending) {
              const resolvedLatency = computePendingLatency(nextPending);
              if (resolvedLatency !== null && nextPending.latencyMs !== resolvedLatency) {
                nextPending = { ...nextPending, latencyMs: resolvedLatency };
              }
              pendingUserRef.current = nextPending;
            } else if (pending.latencyMs == null) {
              const resolvedLatency = computePendingLatency(pending);
              if (resolvedLatency !== null) {
                pendingUserRef.current = { ...pending, latencyMs: resolvedLatency };
              }
            }
          }

          const int16 = new Int16Array(float32.length);
          for (let i = 0; i < float32.length; i++) {
            int16[i] = Math.max(-1, Math.min(1, float32[i])) * 0x7fff;
          }

          const activeSocket = socketRef.current;
          if (activeSocket && activeSocket.readyState === WebSocket.OPEN) {
            activeSocket.send(int16.buffer);
          } else {
            console.error("WebSocket not open, did not send audio.");
          }
        };

        source.connect(processor);
        processor.connect(audioCtx.destination);

        setRecording(true);
        micStreamingActiveRef.current = true;
        appendLog("🎤 PCM streaming started");
      } catch (error) {
        micStreamingActiveRef.current = false;
        if (processorRef.current) {
          try {
            processorRef.current.disconnect();
          } catch (processorError) {
            console.warn("Cleanup error after mic start failure:", processorError);
          }
          processorRef.current = null;
        }
        if (audioContextRef.current) {
          try {
            audioContextRef.current.close();
          } catch (ctxError) {
            console.warn("Failed to close audio context after mic start failure:", ctxError);
          }
          audioContextRef.current = null;
        }
        if (micStreamRef.current) {
          try {
            micStreamRef.current.getTracks()?.forEach((track) => track.stop());
          } catch (streamError) {
            console.warn("Failed to stop mic stream after start failure:", streamError);
          }
          micStreamRef.current = null;
        }
        appendLog(`❌ Mic start failed: ${error?.message || error}`);
        console.error("Failed to start microphone streaming:", error);
        throw error;
      } finally {
        micStartPromiseRef.current = null;
      }
    })();

    micStartPromiseRef.current = startPromise;
    return startPromise;
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

      if (micStreamRef.current) {
        try {
          micStreamRef.current.getTracks()?.forEach((track) => track.stop());
        } catch (e) {
          console.warn("Error stopping mic stream:", e);
        }
        micStreamRef.current = null;
      }

      micStreamingActiveRef.current = false;
      if (micStartPromiseRef.current) {
        micStartPromiseRef.current = null;
      }
      audioLevelRef.current = 0;
      setAudioLevel(0);
      
      if (socketRef.current) {
        try { 
          socketRef.current.close(); 
        } catch (e) {
          console.warn("Error closing socket:", e);
        }
        socketRef.current = null;
      }
      
      const summaryTimestamp = Date.now();
      setMessages((prev) => {
        if (prev.length > 0 && prev[prev.length - 1]?.kind === "divider") {
          return prev;
        }
        const userTurns = prev.filter((msg) => msg.speaker === "User").length;
        const assistantTurns = prev.filter((msg) => msg.speaker && msg.speaker !== "User").length;
        const firstTimestamp = prev.find((msg) => typeof msg.timestamp === "number")?.timestamp;
        const durationMs = firstTimestamp ? Math.max(summaryTimestamp - firstTimestamp, 0) : null;
        const dividerMessage = createMessage({
          kind: "divider",
          timestamp: summaryTimestamp,
          summary: {
            userTurns,
            assistantTurns,
            durationMs,
          },
        });
        return [...prev, dividerMessage];
      });
      setActiveSpeaker(null);
      setActiveAgentName(null);
      setToolActivity(null);
      setRecording(false);
      const pendingUser = pendingUserRef.current;
      if (pendingUser?.userMessageId) {
        updateMessage(pendingUser.userMessageId, () => ({ metrics: { awaitingResponse: false } }));
      }
      pendingUserRef.current = null;
      activeAssistantRef.current = {
        messageId: null,
        streaming: false,
        speaking: false,
        speechStartedAt: null,
        respondedAt: null,
        originUserMessageId: null,
        originUserStartedAt: null,
        bufferedText: "",
        finalText: "",
        incomplete: false,
        agentName: null,
      };
      bargeInRef.current = null;
      assistantAudioProgressRef.current.clear();
      currentSpeechMessageRef.current = null;
      toolMessageRef.current.clear();
      assistantBacklogRef.current = [];
      appendLog("🛑 PCM streaming stopped");
    };

    const handleSocketMessage = async (event) => {
      // Log all incoming messages for debugging
      // if (typeof event.data === "string") {
      //   try {
      //     const msg = JSON.parse(event.data);
      //     console.info("📨 WebSocket message received:", msg.type || "unknown", msg);
      //   } catch {
      //     console.warn("📨 Non-JSON WebSocket message:", event.data);
      //   }
      // } else {
      //   console.info("📨 Binary WebSocket message received, length:", event.data.byteLength);
      // }

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

      // --- NEW: Handle envelope format from backend ---
      // If message is in envelope format, extract the actual payload
      if (payload.type && payload.sender && payload.payload && payload.ts) {
        console.info("📨 Received envelope message:", {
          type: payload.type,
          sender: payload.sender,
          topic: payload.topic,
          session_id: payload.session_id
        });
        
        // Check for agent/sender change and finalize current message
        const currentAssistant = activeAssistantRef.current;
        const envelopeSender = payload.sender;
        if (currentAssistant?.messageId && currentAssistant.agentName && 
            currentAssistant.agentName !== envelopeSender && 
            (currentAssistant.streaming || currentAssistant.incomplete)) {
          console.info(`Agent handoff detected: ${currentAssistant.agentName} → ${envelopeSender}`);
          finalizeActiveAssistantMessage("envelope-agent-handoff");
        }
        
        // Extract the actual message from the envelope
        const envelopeType = payload.type;
        const envelopeTopic = payload.topic;
        const envelopeTimestamp = payload.ts || null;
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
          const normalizedSender = envelopeSender || "System";
          if (normalizedSender === "User") {
            payload = {
              type: "user",
              sender: normalizedSender,
              speaker: "User",
              message: actualPayload.message,
              content: actualPayload.message,
            };
          } else {
            const agentName = actualPayload.agent || normalizedSender || "Assistant";
            setActiveAgentName(agentName);
            const statusSpeaker = normalizedSender === "System" ? "System" : "Assistant";
            payload = {
              type: "status",
              sender: normalizedSender,
              speaker: statusSpeaker,
              agent: agentName,
              message: actualPayload.message,
              content: actualPayload.message,
            };
          }
        } else if (envelopeType === "event") {
          const eventType = actualPayload?.event_type || actualPayload?.eventType || null;
          const eventData = actualPayload?.data || actualPayload?.payload || actualPayload;
          if (eventType === "transcription_final" || eventType === "transcription_partial") {
            const text = eventData?.text ?? eventData?.message ?? "";
            const language = eventData?.language ?? eventData?.lang ?? null;
            const timestampIso = eventData?.timestamp ?? null;
            payload = {
              type:
                eventType === "transcription_final"
                  ? "user_transcription_final"
                  : "user_transcription_partial",
              sender: "User",
              speaker: "User",
              message: text,
              content: text,
              language,
              transcriptionTimestamp: timestampIso,
              transcriptionMeta: {
                raw: actualPayload,
                topic: envelopeTopic,
                sender: envelopeSender,
                envelopeTimestamp,
              },
            };
          } else {
            payload = {
              ...actualPayload,
              sender: envelopeSender,
              speaker: envelopeSender,
            };
          }
        } else {
          // For other envelope types, use the payload directly
          payload = {
            ...actualPayload,
            sender: envelopeSender,
            speaker: envelopeSender,
          };
        }
        
        // console.info("📨 Transformed envelope to legacy format:", payload);
      }
      
      flushAssistantBacklog();

      // Handle audio_data messages from backend TTS
      if (payload.type === "audio_data" && payload.data) {
        if (!micStreamingActiveRef.current && !micStartPromiseRef.current) {
          beginMicStreaming().catch((error) => {
            console.error("Mic streaming initialization failed:", error);
          });
        }
        try {
          // console.info("🔊 Received audio_data message:", {
          //   frame_index: payload.frame_index,
          //   total_frames: payload.total_frames,
          //   sample_rate: payload.sample_rate,
          //   data_length: payload.data.length,
          //   is_final: payload.is_final
          // });
          const audioTimestamp = Date.now();

          const pendingUser = pendingUserRef.current;
          if (pendingUser?.userMessageId && pendingUser.latencyStopAt == null) {
            let nextPending = {
              ...pendingUser,
              latencyStopAt: audioTimestamp,
              latencyStartAt:
                pendingUser.latencyStartAt ??
                pendingUser.audioEndAt ??
                pendingUser.audioLastChunkAt ??
                pendingUser.audioStartedAt ??
                pendingUser.startedAt ??
                null,
            };
            const resolvedLatency = computePendingLatency(nextPending, audioTimestamp);
            if (resolvedLatency !== null && nextPending.latencyMs !== resolvedLatency) {
              nextPending = { ...nextPending, latencyMs: resolvedLatency };
            }
            pendingUserRef.current = nextPending;
            if (resolvedLatency !== null) {
              updateMessage(nextPending.userMessageId, (msg) => ({
                metrics: {
                  ...(msg.metrics || {}),
                  awaitingResponse: true,
                  responseLatencyMs: resolvedLatency,
                },
              }));
            }
          }

          // Decode base64 -> Int16 -> Float32 [-1, 1]
          const bstr = atob(payload.data);
          const buf = new ArrayBuffer(bstr.length);
          const view = new Uint8Array(buf);
          for (let i = 0; i < bstr.length; i++) view[i] = bstr.charCodeAt(i);
          const int16 = new Int16Array(buf);
          const float32 = new Float32Array(int16.length);
          for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 0x8000;

          // console.info(`🔊 Processing TTS audio chunk: ${float32.length} samples, sample_rate: ${payload.sample_rate || DEFAULT_TTS_SAMPLE_RATE}`);
          // console.info("🔊 Audio data preview:", float32.slice(0, 10));

          let assistantCtx = activeAssistantRef.current;
          const isFirstFrame = payload.frame_index === 0;
          const currentMessages = messagesRef.current || [];

          const getMessageById = (id) =>
            id ? currentMessages.find((msg) => msg && msg.id === id) : null;

          const findLatestAssistantMessage = () => {
            for (let idx = currentMessages.length - 1; idx >= 0; idx--) {
              const candidate = currentMessages[idx];
              if (!candidate) continue;
              if (candidate.isTool) continue;
              if (candidate.speaker === "User") continue;
              return candidate;
            }
            return null;
          };

          let playbackMessage = getMessageById(assistantCtx?.messageId);
          if (!playbackMessage && currentSpeechMessageRef.current) {
            playbackMessage = getMessageById(currentSpeechMessageRef.current);
          }
          if (!playbackMessage || playbackMessage.isTool || playbackMessage.speaker === "User") {
            playbackMessage = findLatestAssistantMessage();
          }

          if (!playbackMessage) {
            const placeholderSpeaker = payload.speaker || "Assistant";
            const placeholderAgent = payload.agent || placeholderSpeaker || null;
            const placeholder = appendMessage({
              speaker: placeholderSpeaker,
              text: "",
              streaming: true,
              incomplete: true,
              agentName: placeholderAgent,
            });

            setActiveAgentName(placeholderAgent);

            const originUserMessageId =
              pendingUserRef.current?.userMessageId ?? assistantCtx?.originUserMessageId ?? null;
            const originUserStartedAt =
              pendingUserRef.current?.startedAt ?? assistantCtx?.originUserStartedAt ?? null;

            playbackMessage = placeholder;
            assistantCtx = {
              messageId: placeholder.id,
              streaming: true,
              speaking: false,
              speechStartedAt: null,
              respondedAt: Date.now(),
              originUserMessageId,
              originUserStartedAt,
              bufferedText: "",
              finalText: "",
              incomplete: true,
              agentName: placeholderAgent,
            };
            activeAssistantRef.current = assistantCtx;
            currentSpeechMessageRef.current = placeholder.id;
            // anchorAssistantAfterTool(placeholder.id, originUserMessageId);
          } else {
            const originUserMessageId =
              assistantCtx?.originUserMessageId ??
              pendingUserRef.current?.userMessageId ??
              null;
            const originUserStartedAt =
              assistantCtx?.originUserStartedAt ??
              pendingUserRef.current?.startedAt ??
              null;
            assistantCtx = {
              messageId: playbackMessage.id,
              streaming: assistantCtx?.streaming ?? playbackMessage.streaming ?? false,
              speaking: true,
              speechStartedAt: assistantCtx?.speechStartedAt ?? null,
              respondedAt: assistantCtx?.respondedAt ?? Date.now(),
              originUserMessageId,
              originUserStartedAt,
              bufferedText: assistantCtx?.bufferedText ?? playbackMessage.text ?? "",
              finalText: assistantCtx?.finalText ?? playbackMessage.text ?? "",
              incomplete: assistantCtx?.incomplete ?? playbackMessage.incomplete ?? false,
              agentName:
                assistantCtx?.agentName ??
                playbackMessage.agentName ??
                payload.agent ??
                playbackMessage.speaker ??
                null,
            };
            activeAssistantRef.current = assistantCtx;
            if (isFirstFrame) {
              currentSpeechMessageRef.current = playbackMessage.id;
              // anchorAssistantAfterTool(playbackMessage.id, originUserMessageId ?? null);
            }
          }

          const activeMessageId = assistantCtx?.messageId || playbackMessage?.id || null;
          if (!activeMessageId) {
            console.warn("Audio chunk without resolved assistant message");
          }
          const sampleRate = payload.sample_rate || DEFAULT_TTS_SAMPLE_RATE;

          if (activeMessageId) {
            const progressMap = assistantAudioProgressRef.current;
            const entry = progressMap.get(activeMessageId) || {
              queuedSamples: 0,
              playedSamples: 0,
              sampleRate,
              lastRatio: 0,
            };
            entry.sampleRate = sampleRate;
            const chunkSamples = float32.length;
            entry.queuedSamples = (entry.queuedSamples || 0) + chunkSamples;
            entry.completed = false;
            if (payload.is_final) {
              entry.expectedSamples = entry.queuedSamples;
              entry.expectedNotified = false;
            }
            if (!entry.userMessageId && assistantCtx?.originUserMessageId) {
              entry.userMessageId = assistantCtx.originUserMessageId;
            }
            progressMap.set(activeMessageId, entry);
            if (payload.is_final) {
              currentSpeechMessageRef.current = null;
            }
          }

          const ensurePlaybackReady = async () => {
            if (pcmSinkRef.current) {
              return true;
            }
            console.warn("Audio playback not initialized, attempting init...");
            appendLog("⚠️ Audio playback not ready, initializing...");
            await initializeAudioPlayback();
            return Boolean(pcmSinkRef.current);
          };

          if (await ensurePlaybackReady()) {
            const playbackRate = playbackAudioContextRef.current?.sampleRate || sampleRate;
            let playbackChunk =
              playbackRate === sampleRate
                ? float32
                : resampleToSampleRate(float32, sampleRate, playbackRate);

            const fadeDurationMs = 20;
            const fadeSamples = Math.max(8, Math.floor((playbackRate * fadeDurationMs) / 1000));
            const entryForFade = assistantAudioProgressRef.current.get(activeMessageId);
            const shouldFadeIn = Boolean(entryForFade && !entryForFade.hasAppliedFadeIn && payload.frame_index === 0);
            const shouldFadeOut = payload.is_final === true;
            
            // Add buffer padding for smoother start
            if (shouldFadeIn && playbackChunk.length > 0) {
              const bufferPadding = new Float32Array(Math.min(64, fadeSamples));
              const paddedChunk = new Float32Array(bufferPadding.length + playbackChunk.length);
              paddedChunk.set(bufferPadding, 0);
              paddedChunk.set(playbackChunk, bufferPadding.length);
              playbackChunk = paddedChunk;
            }
            
            if (shouldFadeIn || shouldFadeOut) {
              playbackChunk = applyFadeEnvelope(
                playbackChunk,
                shouldFadeIn ? fadeSamples : 0,
                shouldFadeOut ? fadeSamples : 0,
              );
              if (entryForFade) {
                if (shouldFadeIn) {
                  entryForFade.hasAppliedFadeIn = true;
                }
                if (shouldFadeOut) {
                  entryForFade.hasAppliedFadeOut = true;
                }
                assistantAudioProgressRef.current.set(activeMessageId, entryForFade);
              }
            }

            const payloadBuffer = playbackChunk.buffer;
            const payloadLength = playbackChunk.length;
            pcmSinkRef.current.port.postMessage(
              {
                type: 'push',
                payload: payloadBuffer,
                length: payloadLength,
                messageId: activeMessageId,
                sourceSamples: float32.length,
              },
              [payloadBuffer]
            );
            appendLog(`🔊 TTS audio frame ${payload.frame_index + 1}/${payload.total_frames}`);
          } else {
            console.error("Failed to initialize audio playback");
            appendLog("❌ Audio init failed");
          }

          if (assistantCtx?.messageId) {
            const nextCtx = {
              ...assistantCtx,
              speaking: true,
              speechStartedAt: assistantCtx.speechStartedAt ?? audioTimestamp,
              streaming: false,
              respondedAt: assistantCtx.respondedAt ?? audioTimestamp,
              awaitingAudio: !payload.is_final,
              bufferedText: assistantCtx?.bufferedText ?? "",
              finalText: assistantCtx?.finalText ?? "",
              incomplete: assistantCtx?.incomplete ?? false,
              agentName: assistantCtx?.agentName ?? payload.agent ?? null,
            };
            activeAssistantRef.current = nextCtx;

            if (payload.is_final) {
              const duration = nextCtx.speechStartedAt ? audioTimestamp - nextCtx.speechStartedAt : null;
              const metricsUpdate = {};
              const progressEntry = assistantAudioProgressRef.current.get(nextCtx.messageId || "");
              if (progressEntry?.sampleRate && progressEntry?.expectedSamples) {
                metricsUpdate.speechDurationMs = (progressEntry.expectedSamples / progressEntry.sampleRate) * 1000;
              } else if (duration !== null && duration >= 0) {
                metricsUpdate.speechDurationMs = duration;
              }
              updateMessage(nextCtx.messageId, (msg) => ({
                streaming: false,
                incomplete: false,
                agentName: msg.agentName || nextCtx.agentName || payload.agent || null,
              }));
              if (bargeInRef.current && bargeInRef.current.assistantMessageId === nextCtx.messageId) {
                const bargeDuration = audioTimestamp - bargeInRef.current.startedAt;
                metricsUpdate.bargeInMs = bargeDuration;
                if (bargeInRef.current.userMessageId) {
                  updateMessage(bargeInRef.current.userMessageId, () => ({ metrics: { bargeInMs: bargeDuration } }));
                }
                bargeInRef.current = null;
              }
              if (Object.keys(metricsUpdate).length > 0) {
                updateMessage(nextCtx.messageId, () => ({ metrics: metricsUpdate }));
              }
              activeAssistantRef.current = {
                messageId: nextCtx.messageId,
                streaming: false,
                speaking: false,
                speechStartedAt: null,
                respondedAt: nextCtx.respondedAt ?? audioTimestamp,
                originUserMessageId: nextCtx.originUserMessageId ?? null,
                originUserStartedAt: nextCtx.originUserStartedAt ?? null,
                bufferedText: nextCtx.bufferedText ?? "",
                finalText: nextCtx.finalText ?? "",
                incomplete: nextCtx.incomplete ?? false,
                agentName: nextCtx.agentName ?? payload.agent ?? null,
              };
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
      const userTextReady = typeof txt === "string" && txt.trim().length > 0;
      const msgType = (type || "").toLowerCase();
      const isTranscriptionFinal = msgType === "user_transcription_final";
      const isTranscriptionPartial = msgType === "user_transcription_partial";
      const hasTranscription = isTranscriptionFinal || isTranscriptionPartial;
      const transcriptionMeta = hasTranscription ? payload.transcriptionMeta || {} : null;
      const transcriptionTimestampIso = hasTranscription
        ? payload.transcriptionTimestamp ||
          transcriptionMeta?.timestamp ||
          transcriptionMeta?.envelopeTimestamp ||
          transcriptionMeta?.raw?.timestamp ||
          transcriptionMeta?.raw?.data?.timestamp ||
          transcriptionMeta?.raw?.payload?.timestamp ||
          null
        : null;
      const transcriptionTs = hasTranscription ? parseIsoTimestamp(transcriptionTimestampIso) : null;
      const finalTranscriptionTs = isTranscriptionFinal ? transcriptionTs : null;
      const partialTranscriptionTs = isTranscriptionPartial ? transcriptionTs : null;
      const currentAssistant = activeAssistantRef.current;
      const isSystemSpeaker = speaker === "System";
      const isSystemStatus = msgType === "status" && isSystemSpeaker;

      if (isSystemStatus) {
        if (currentAssistant?.messageId && (currentAssistant.streaming || currentAssistant.speaking || currentAssistant.incomplete)) {
          finalizeActiveAssistantMessage("system-status-change");
        }

        setActiveSpeaker("System");
        const agentSource = payload.agent || null;
        if (agentSource) {
          setActiveAgentName(agentSource);
        }
        lastToolMessageIdRef.current = null;

        if (userTextReady) {
          appendMessage({
            speaker: "System",
            text: txt,
            agentName: agentSource,
          });
          appendLog(`System: ${txt}`);
        }
        return;
      }

      if (msgType === "user" || speaker === "User" || isTranscriptionFinal || isTranscriptionPartial) {
        // Speaker change detected - finalize any active assistant message
        const currentAssistant = activeAssistantRef.current;
        if (currentAssistant?.messageId && (currentAssistant.streaming || currentAssistant.speaking)) {
          finalizeActiveAssistantMessage("user-speaker-change");
        }
        
        setActiveSpeaker("User");
        lastToolMessageIdRef.current = null;
        const pending = pendingUserRef.current;
        const draft = userSpeechDraftRef.current;
        const existingDraftId = draft?.messageId ?? null;
        if (pending?.userMessageId && pending.userMessageId !== existingDraftId) {
          updateMessage(pending.userMessageId, () => ({ metrics: { awaitingResponse: false } }));
        }

        const userTimestamp =
          finalTranscriptionTs ??
          partialTranscriptionTs ??
          Date.now();
        let userMessageId = existingDraftId;

        if (isTranscriptionPartial) {
          const partialText = typeof txt === "string" ? txt : "";
          if (!partialText) {
            return;
          }

          const currentMessages = messagesRef.current || [];
          let targetMessageId = userMessageId || null;
          if (!targetMessageId && pending?.userMessageId && !pending.finalReceived) {
            targetMessageId = pending.userMessageId;
          }
          let startedAt = pending?.finalReceived ? userTimestamp : pending?.startedAt ?? draft?.startedAt ?? userTimestamp;

          if (targetMessageId) {
            const exists = currentMessages.some((msg) => msg.id === targetMessageId);
            if (!exists) {
              targetMessageId = null;
            }
          }

          const carryPending = pending && !pending.finalReceived ? pending : null;

          if (!targetMessageId) {
            const userMsg = appendMessage({
              speaker: "User",
              text: partialText,
              streaming: true,
              incomplete: true,
              metrics: { awaitingResponse: true },
              timestamp: userTimestamp,
            });
            targetMessageId = userMsg.id;
            startedAt = userTimestamp;
          } else {
            updateMessage(targetMessageId, (msg) => ({
              text: partialText,
              streaming: true,
              incomplete: true,
              timestamp: userTimestamp,
              metrics: { ...(msg.metrics || {}), awaitingResponse: true },
            }));
          }

          userSpeechDraftRef.current = {
            messageId: targetMessageId,
            startedAt,
          };

          pendingUserRef.current = {
            userMessageId: targetMessageId,
            startedAt,
            latencyMs: carryPending?.latencyMs ?? null,
            textReady: true,
            audioStartedAt: carryPending?.audioStartedAt ?? startedAt,
            audioLastChunkAt: userTimestamp,
            audioEndAt: carryPending?.audioEndAt ?? null,
            latencyStopAt: carryPending?.latencyStopAt ?? null,
            latencyStartAt: carryPending?.latencyStartAt ?? null,
            requireFinal: true,
            finalReceived: false,
          };

          const activeUserMessageId = pendingUserRef.current.userMessageId;
          const assistantCtx = activeAssistantRef.current;
          if ((assistantCtx?.streaming || assistantCtx?.speaking) && assistantCtx?.messageId) {
            bargeInRef.current = {
              assistantMessageId: assistantCtx.messageId,
              startedAt: userTimestamp,
              userMessageId: activeUserMessageId,
            };
            updateMessage(assistantCtx.messageId, () => ({ incomplete: true }));
            activeAssistantRef.current = {
              ...assistantCtx,
              incomplete: true,
            };
          }

          appendLog(`User (partial): ${partialText}`);
          return;
        }

        if (existingDraftId) {
          updateMessage(existingDraftId, () => ({
            text: txt,
            streaming: false,
            incomplete: false,
            timestamp: userTimestamp,
          }));
          pendingUserRef.current = {
            userMessageId: existingDraftId,
            startedAt: pending?.startedAt ?? draft.startedAt ?? userTimestamp,
            latencyMs: pending?.latencyMs ?? null,
            textReady: userTextReady || pending?.textReady || false,
            audioStartedAt: pending?.audioStartedAt ?? null,
            audioLastChunkAt: pending?.audioLastChunkAt ?? null,
            audioEndAt: pending?.audioEndAt ?? null,
            latencyStopAt: pending?.latencyStopAt ?? null,
            latencyStartAt: pending?.latencyStartAt ?? null,
            requireFinal: false,
            finalReceived: true,
          };
          userSpeechDraftRef.current = null;
        } else {
          const userMsg = appendMessage({
            speaker: "User",
            text: txt,
            metrics: { awaitingResponse: true },
          });
          userMessageId = userMsg.id;
          pendingUserRef.current = {
            userMessageId,
            startedAt: userTimestamp,
            latencyMs: null,
            textReady: userTextReady,
            audioStartedAt: null,
            audioLastChunkAt: null,
            audioEndAt: null,
            latencyStopAt: null,
            latencyStartAt: null,
            requireFinal: false,
            finalReceived: true,
          };
        }

        if (pendingUserRef.current) {
          let nextPending = {
            ...pendingUserRef.current,
            textReady: userTextReady || pendingUserRef.current.textReady || false,
          };

          if (isTranscriptionFinal) {
            nextPending = {
              ...nextPending,
              textReady: true,
            };
            if (!nextPending.audioStartedAt) {
              nextPending.audioStartedAt = nextPending.startedAt ?? finalTranscriptionTs ?? userTimestamp;
            }
            if (finalTranscriptionTs !== null) {
              if (!nextPending.audioLastChunkAt) {
                nextPending.audioLastChunkAt = finalTranscriptionTs;
              }
              if (!nextPending.audioEndAt) {
                nextPending.audioEndAt = finalTranscriptionTs;
              }
            }
            if (!nextPending.latencyStartAt) {
              nextPending.latencyStartAt =
                nextPending.audioEndAt ??
                nextPending.audioLastChunkAt ??
                finalTranscriptionTs ??
                nextPending.audioStartedAt ??
                nextPending.startedAt ??
                userTimestamp;
            }
            nextPending.requireFinal = false;
            nextPending.finalReceived = true;
          }

          const resolvedLatency = computePendingLatency(nextPending);
          if (resolvedLatency !== null && nextPending.latencyMs !== resolvedLatency) {
            nextPending = { ...nextPending, latencyMs: resolvedLatency };
          }

          pendingUserRef.current = nextPending;

          if (nextPending.userMessageId && (userTextReady || isTranscriptionFinal)) {
            updateMessage(nextPending.userMessageId, (msg) => {
              const baseMetrics = msg.metrics || {};
              const awaitingResponse = true;
              const metrics =
                resolvedLatency !== null
                  ? { ...baseMetrics, awaitingResponse, responseLatencyMs: resolvedLatency }
                  : { ...baseMetrics, awaitingResponse };
              return { metrics };
            });
          }
        }

        const activeUserMessageId = pendingUserRef.current?.userMessageId;
        const assistantCtx = activeAssistantRef.current;
        if ((assistantCtx?.streaming || assistantCtx?.speaking) && assistantCtx?.messageId) {
          bargeInRef.current = {
            assistantMessageId: assistantCtx.messageId,
            startedAt: userTimestamp,
            userMessageId: activeUserMessageId,
          };
          updateMessage(assistantCtx.messageId, () => ({ incomplete: true }));
          activeAssistantRef.current = {
            ...assistantCtx,
            incomplete: true,
          };
        }
        flushAssistantBacklog();
        appendLog(`User: ${txt}`);
        return;
      }

      if (msgType === "assistant_streaming") {
        // Check for agent handoff during streaming (but not during tool calls)
        const currentAssistant = activeAssistantRef.current;
        const incomingAgent = payload.agent || speaker || "Assistant";
        const isToolActive = toolActivity?.status === "running";
        if (currentAssistant?.messageId && currentAssistant.agentName && 
            currentAssistant.agentName !== incomingAgent && 
            (currentAssistant.streaming || currentAssistant.incomplete) &&
            !isToolActive) {
          console.info(`Agent handoff during streaming: ${currentAssistant.agentName} → ${incomingAgent}`);
          finalizeActiveAssistantMessage("streaming-agent-handoff");
        }
        
        const executeStreaming = () => processAssistantStreaming({
          payload,
          text: txt,
          speaker,
        });
        if (!isUserTranscriptReady()) {
          enqueueAssistantTask(executeStreaming);
          return;
        }
        executeStreaming();
        return;
      }

      if (
        msgType === "assistant_streaming" ||
        (msgType === "status" && speaker !== "System") ||
        speaker === "Assistant"
      ) {
        // If we're getting a new assistant response but have an active different assistant, finalize it
        // But not during tool calls, as the same agent continues after the tool
        const currentAssistant = activeAssistantRef.current;
        const incomingAgent = payload.agent || speaker || "Assistant";
        const isToolActive = toolActivity?.status === "running";
        if (currentAssistant?.messageId && currentAssistant.agentName && 
            currentAssistant.agentName !== incomingAgent && 
            (currentAssistant.streaming || currentAssistant.speaking) &&
            !isToolActive) {
          console.info(`Agent handoff in assistant response: ${currentAssistant.agentName} → ${incomingAgent}`);
          finalizeActiveAssistantMessage("assistant-response-handoff");
        }
        
        const executeAssistant = () => processAssistantResponse({
          payload,
          text: txt,
          speaker,
        });
        if (!isUserTranscriptReady()) {
          enqueueAssistantTask(executeAssistant);
          return;
        }
        executeAssistant();
        flushAssistantBacklog();
        return;
      }
    
      if (type === "tool_start") {
        const startedAt = Date.now();
        const agentSource = payload.agent || payload.speaker || null;
        if (agentSource) {
          setActiveAgentName(agentSource);
        }
        const toolName = payload.tool || "tool";
        const progressValue = typeof payload.pct === "number" ? payload.pct : null;
        setToolActivity({
          tool: toolName,
          status: "running",
          progress: progressValue,
          startedAt,
          agent: agentSource,
          elapsedMs: null,
        });

        const initialToolState = {
          toolName,
          status: "running",
          statusLabel: progressValue != null ? `Running · ${Math.round(progressValue)}%` : "Running",
          progress: progressValue,
          startedAt,
          updatedAt: startedAt,
          elapsedMs: null,
          agent: agentSource || null,
          error: null,
          result: null,
          resultPreview: null,
          detailText: payload.message || null,
        };

        const toolMessage = appendMessage({
          speaker: speaker || "Assistant",
          isTool: true,
          text: formatToolMessage(toolName, { status: "started", progress: progressValue }),
          agentName: agentSource,
          tool: toolName,
          toolState: initialToolState,
        });

        toolMessageRef.current.set(toolName, toolMessage.id);
        lastToolMessageIdRef.current = {
          messageId: toolMessage.id,
          userMessageId:
            pendingUserRef.current?.userMessageId ??
            activeAssistantRef.current?.originUserMessageId ??
            null,
          lastAssistantId: null,
        };
      
        appendLog(`⚙️ ${payload.tool} started`);
        return;
      }
      
    
      if (type === "tool_progress") {
        const toolName = payload.tool || "tool";
        const now = Date.now();
        const progressValue = typeof payload.pct === "number" ? Math.max(0, Math.min(100, payload.pct)) : null;
        const agentSource = payload.agent || payload.speaker || null;

        setToolActivity((prev) => {
          if (!prev || prev.tool !== toolName) {
            return prev;
          }
          return {
            ...prev,
            status: "running",
            progress: progressValue ?? prev.progress ?? null,
          };
        });

        const messageId = toolMessageRef.current.get(toolName);
        const toolUpdatePayload = {
          status: progressValue != null ? "in_progress" : "running",
          progress: progressValue,
        };

        if (messageId) {
          updateMessage(messageId, (msg) => {
            const prevState = msg.toolState || {};
            const nextState = {
              ...prevState,
              status: "running",
              statusLabel: progressValue != null ? `Running · ${Math.round(progressValue)}%` : "Running",
              progress: progressValue ?? prevState.progress ?? null,
              updatedAt: now,
              agent: agentSource || prevState.agent || null,
              detailText: payload.message || prevState.detailText || null,
            };
            if (nextState.startedAt == null) {
              nextState.startedAt = prevState.startedAt ?? now;
            }
            return {
              text: formatToolMessage(toolName, toolUpdatePayload),
              agentName: msg.agentName || agentSource || null,
              tool: msg.tool || toolName,
              isTool: true,
              toolState: nextState,
            };
          });
          lastToolMessageIdRef.current = {
            messageId,
            userMessageId:
              pendingUserRef.current?.userMessageId ??
              activeAssistantRef.current?.originUserMessageId ??
              null,
          };
        } else {
          const initialState = {
            toolName,
            status: "running",
            statusLabel: progressValue != null ? `Running · ${Math.round(progressValue)}%` : "Running",
            progress: progressValue,
            startedAt: now,
            updatedAt: now,
            agent: agentSource || null,
            elapsedMs: null,
            error: null,
            result: null,
            resultPreview: null,
            detailText: payload.message || null,
          };
          const replacement = appendMessage({
            speaker: "Assistant",
            isTool: true,
            text: formatToolMessage(toolName, toolUpdatePayload),
            agentName: agentSource,
            tool: toolName,
            toolState: initialState,
          });
          toolMessageRef.current.set(toolName, replacement.id);
          lastToolMessageIdRef.current = {
            messageId: replacement.id,
            userMessageId:
              pendingUserRef.current?.userMessageId ??
              activeAssistantRef.current?.originUserMessageId ??
              null,
          };
        }
        appendLog(`⚙️ ${payload.tool} ${payload.pct}%`);
        return;
      }
    
      if (type === "tool_end") {
        const finishedAt = Date.now();
        const toolName = payload.tool || "tool";
        const success = payload.status === "success";
        const agentSource = payload.agent || payload.speaker || null;

        setToolActivity((prev) => {
          if (!prev || prev.tool !== toolName) {
            const startedAt = finishedAt - (payload.elapsedMs ?? 0);
            return {
              tool: toolName,
              status: success ? "success" : "failed",
              progress: success ? 100 : prev?.progress ?? null,
              startedAt,
              elapsedMs: null,
              agent: agentSource ?? prev?.agent ?? null,
            };
          }
          return {
            ...prev,
            status: success ? "success" : "failed",
            progress: success ? 100 : prev.progress ?? null,
            elapsedMs: payload.elapsedMs ??
              (prev.startedAt != null ? Math.max(finishedAt - prev.startedAt, 0) : null),
          };
        });

        const messageId = toolMessageRef.current.get(toolName);
        const finalText = formatToolMessage(toolName, {
          status: success ? "completed ✔️" : "failed ❌",
          progress: success ? 100 : undefined,
          error: success ? undefined : payload.error,
          result: success ? payload.result : undefined,
        });

        const resultPreview = success && payload.result !== undefined ? previewValue(payload.result) : null;
        const errorMessage = success ? null : (payload.error || "Tool reported an error");

        if (messageId) {
          updateMessage(messageId, (msg) => {
            const prevState = msg.toolState || {};
            const startedAt = prevState.startedAt ?? (payload.elapsedMs != null ? finishedAt - payload.elapsedMs : finishedAt);
            const elapsedMs = payload.elapsedMs ?? (startedAt != null ? Math.max(finishedAt - startedAt, 0) : null);
            const nextState = {
              ...prevState,
              status: success ? "success" : "failed",
              statusLabel: success ? "Completed" : "Failed",
              progress: success ? 100 : prevState.progress ?? null,
              updatedAt: finishedAt,
              completedAt: finishedAt,
              elapsedMs,
              agent: agentSource || prevState.agent || null,
              error: errorMessage,
              result: success ? (payload.result ?? prevState.result ?? null) : null,
              resultPreview: success ? (resultPreview ?? prevState.resultPreview ?? null) : null,
              detailText: success
                ? (resultPreview || prevState.detailText || null)
                : (errorMessage || prevState.detailText || null),
            };
            if (nextState.startedAt == null) {
              nextState.startedAt = startedAt;
            }
            return {
              text: finalText,
              agentName: msg.agentName || agentSource || null,
              tool: msg.tool || toolName,
              isTool: true,
              toolState: nextState,
            };
          });
          lastToolMessageIdRef.current = {
            messageId,
            userMessageId:
              pendingUserRef.current?.userMessageId ??
              activeAssistantRef.current?.originUserMessageId ??
              null,
          };
        } else {
          const startedAt = finishedAt - (payload.elapsedMs ?? 0);
          const fallbackState = {
            toolName,
            status: success ? "success" : "failed",
            statusLabel: success ? "Completed" : "Failed",
            progress: success ? 100 : null,
            startedAt,
            updatedAt: finishedAt,
            completedAt: finishedAt,
            elapsedMs: payload.elapsedMs ?? null,
            agent: agentSource || null,
            error: errorMessage,
            result: success ? payload.result ?? null : null,
            resultPreview: success ? resultPreview : null,
            detailText: success ? resultPreview : errorMessage,
          };
          const fallback = appendMessage({
            speaker: "Assistant",
            isTool: true,
            text: finalText,
            agentName: agentSource,
            tool: toolName,
            toolState: fallbackState,
          });
          toolMessageRef.current.set(toolName, fallback.id);
          lastToolMessageIdRef.current = {
            messageId: fallback.id,
            userMessageId:
              pendingUserRef.current?.userMessageId ??
              activeAssistantRef.current?.originUserMessageId ??
              null,
          };
        }

        toolMessageRef.current.delete(toolName);

        appendLog(`⚙️ ${payload.tool} ${payload.status} (${payload.elapsedMs} ms)`);
        return;
      }

      if (type === "control") {
        const { action } = payload;
        const controlTimestamp = Date.now();
        console.info("🎮 Control message received:", action);
        
        if (action === "tts_cancelled") {
          console.info("🔇 TTS cancelled - clearing audio queue");
          appendLog("🔇 Audio interrupted by user speech");
          
          if (pcmSinkRef.current) {
            pcmSinkRef.current.port.postMessage({ type: 'clear' });
          }
          assistantAudioProgressRef.current.clear();
          currentSpeechMessageRef.current = null;

          const assistantCtx = activeAssistantRef.current;
          if (assistantCtx?.messageId) {
            const updates = {};
            if (assistantCtx.speechStartedAt) {
              updates.speechDurationMs = controlTimestamp - assistantCtx.speechStartedAt;
            }
            updates.speechInterrupted = true;
            if (bargeInRef.current && bargeInRef.current.assistantMessageId === assistantCtx.messageId) {
              const bargeDuration = controlTimestamp - bargeInRef.current.startedAt;
              updates.bargeInMs = bargeDuration;
              if (bargeInRef.current.userMessageId) {
                updateMessage(bargeInRef.current.userMessageId, () => ({ metrics: { bargeInMs: bargeDuration } }));
              }
              bargeInRef.current = null;
            }
            updateMessage(assistantCtx.messageId, () => ({ metrics: updates, incomplete: true }));
          }

          activeAssistantRef.current = {
            messageId: assistantCtx?.messageId ?? null,
            streaming: false,
            speaking: false,
            speechStartedAt: null,
            respondedAt: assistantCtx?.respondedAt ?? controlTimestamp,
            originUserMessageId: assistantCtx?.originUserMessageId ?? null,
            originUserStartedAt: assistantCtx?.originUserStartedAt ?? null,
            bufferedText: assistantCtx?.bufferedText ?? "",
            finalText: assistantCtx?.finalText ?? "",
            incomplete: true,
            agentName: assistantCtx?.agentName ?? null,
          };

          setActiveSpeaker(null);
          return;
        }
        
        console.error("🎮 Unknown control action:", action);
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
      console.info('📞 [FRONTEND] Initiating phone call with session_id:', currentSessionId);
      console.info('📞 [FRONTEND] This session_id will be sent to backend for call mapping');
      
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
        createMessage({ speaker:"Assistant", text:`📞 Call started → ${targetPhoneNumber}` }),
      ]);
      appendLog("📞 Call initiated");

      // relay WS WITH session_id to monitor THIS session (including phone calls)
      console.info('🔗 [FRONTEND] Starting dashboard relay WebSocket to monitor session:', currentSessionId);
      const relay = new WebSocket(`${WS_URL}/api/v1/realtime/dashboard/relay?session_id=${currentSessionId}`);
      relay.onopen = () => appendLog("Relay WS connected");
      relay.onmessage = ({data}) => {
        try {
          const obj = JSON.parse(data);
          
          // Handle envelope format for relay messages
          let processedObj = obj;
          if (obj.type && obj.sender && obj.payload && obj.ts) {
            console.info("📨 Relay received envelope message:", {
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
            console.info("📨 Transformed relay envelope:", processedObj);
          }
          
          if (processedObj.type?.startsWith("tool_")) {
            handleSocketMessage({ data: JSON.stringify(processedObj) });
            return;
          }
          const { sender, message } = processedObj;
          if (sender && message) {
            setMessages(m => [...m, createMessage({ speaker: sender, text: message })]);
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
      <div style={styles.mainContainer}>
        {/* Backend Status Indicator */}
        <BackendIndicator url={API_BASE_URL} onStatusChange={handleSystemStatus} />

        {/* App Header */}
        <div style={styles.appHeader}>
          <div style={styles.appTitleContainer}>
            <div style={styles.appTitleWrapper}>
              <span style={styles.appTitleIcon}>🎙️</span>
              <h1 style={styles.appTitle}>ARTAgent</h1>
            </div>
            <p style={styles.appSubtitle}>Transforming customer interactions with real-time, intelligent voice interactions</p>
            <div style={{
              fontSize: '10px',
              color: '#94a3b8',
              marginTop: '4px',
              fontFamily: 'monospace',
              display: 'flex',
              alignItems: 'center',
              gap: '4px'
            }}>
              <span>💬</span>
              <span>Session: {getOrCreateSessionId()}</span>
            </div>
          </div>
          <div style={styles.appHeaderRight}>
            <HelpButton />
          </div>
          {(activeAgentName || toolActivity) && (
            <div style={styles.statusOverlay}>
              <div style={styles.statusOverlayInner}>
                {/* <AgentStatusPanel agentName={activeAgentName} toolActivity={toolActivity} /> */}
              </div>
            </div>
          )}
        </div>

        {/* Waveform Section */}
        <div style={styles.waveformSection}>
          <div style={styles.waveformSectionTitle}>Voice Activity</div>
          <WaveformVisualization 
            isActive={recording} 
            speaker={activeSpeaker} 
            audioLevel={audioLevel}
            outputAudioLevel={0}
          />
          <div style={styles.sectionDivider}></div>
        </div>

        {/* Chat Messages */}
        <div style={styles.chatSection} ref={chatRef}>
          <div style={styles.chatSectionIndicator}></div>
          <div style={styles.messageContainer} ref={messageContainerRef}>
            {messages.map((message, index) => (
              <ChatBubble key={message.id || index} message={message} />
            ))}
          </div>
        </div>

        {/* Control Buttons - Clean 3-button layout */}
        <div style={styles.controlSection}>
          <div style={styles.controlContainer}>
            
            {/* LEFT: Reset/Restart Session Button */}
            <div style={{ position: 'relative' }}>
              <button
                style={styles.resetButton(false, resetHovered)}
                onMouseEnter={() => {
                  setShowResetTooltip(true);
                  setResetHovered(true);
                }}
                onMouseLeave={() => {
                  setShowResetTooltip(false);
                  setResetHovered(false);
                }}
                onClick={() => {
                  // Reset entire session - clear chat and restart with new session ID
                  const newSessionId = createNewSessionId();
                  
                  // Close existing WebSocket if connected
                  if (socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
                    console.info('🔌 Closing WebSocket for session reset...');
                    socketRef.current.close();
                  }
                  
                  // Reset UI state
                  setMessages([]);
                  pendingUserRef.current = null;
                  activeAssistantRef.current = {
                    messageId: null,
                    streaming: false,
                    speaking: false,
                    speechStartedAt: null,
                    respondedAt: null,
                    originUserMessageId: null,
                    originUserStartedAt: null,
                    bufferedText: "",
                    finalText: "",
                    incomplete: false,
                    agentName: null,
                  };
                  bargeInRef.current = null;
                  toolMessageRef.current.clear();
                  setActiveSpeaker(null);
                  setActiveAgentName(null);
                  setToolActivity(null);
                  stopRecognition();
                  setCallActive(false);
                  setShowPhoneInput(false);
                  appendLog(`🔄️ Session reset - new session ID: ${newSessionId.split('_')[1]}`);
                  
                  // Add welcome message
                  setTimeout(() => {
                    setMessages([createMessage({ 
                      speaker: "System", 
                      text: "✅ Session restarted with new ID. Ready for a fresh conversation!" 
                    })]);
                  }, 500);
                }}
              >
                ⟲
              </button>
              
              {/* Tooltip */}
              <div 
                style={{
                  ...styles.buttonTooltip,
                  ...(showResetTooltip ? styles.buttonTooltipVisible : {})
                }}
              >
                Reset conversation & start fresh
              </div>

            </div>

            {/* MIDDLE: Microphone Button */}
            <div style={{ position: 'relative' }}>
              <button
                style={styles.micButton(recording, micHovered)}
                onMouseEnter={() => {
                  setShowMicTooltip(true);
                  setMicHovered(true);
                }}
                onMouseLeave={() => {
                  setShowMicTooltip(false);
                  setMicHovered(false);
                }}
                onClick={recording ? stopRecognition : startRecognition}
              >
                {recording ? "🛑" : "🎤"}
              </button>
              
              {/* Tooltip */}
              <div 
                style={{
                  ...styles.buttonTooltip,
                  ...(showMicTooltip ? styles.buttonTooltipVisible : {})
                }}
              >
                {recording ? "Stop recording your voice" : "Start voice conversation"}
              </div>

            </div>

            {/* RIGHT: Phone Call Button */}
            <div 
              style={{ position: 'relative' }}
              onMouseEnter={() => {
                setShowPhoneTooltip(true);
                if (isCallDisabled && phoneButtonRef.current) {
                  const rect = phoneButtonRef.current.getBoundingClientRect();
                  setPhoneDisabledPos({
                    top: rect.bottom + 12,
                    left: rect.left + rect.width / 2,
                  });
                }
                if (!isCallDisabled) {
                  setPhoneHovered(true);
                }
              }}
              onMouseLeave={() => {
                setShowPhoneTooltip(false);
                setPhoneHovered(false);
                setPhoneDisabledPos(null);
              }}
            >
              <button
                ref={phoneButtonRef}
                style={styles.phoneButton(callActive, phoneHovered, isCallDisabled)}
                disabled={isCallDisabled}
                title={
                  isCallDisabled
                    ? undefined
                    : callActive
                      ? "Hang up the phone call"
                      : "Make a phone call"
                }
                onClick={() => {
                  if (isCallDisabled) {
                    return;
                  }
                  if (callActive) {
                    // Hang up call
                    stopRecognition();
                    setCallActive(false);
                    setMessages(prev => [...prev, createMessage({ 
                      speaker: "System",
                      text: "📞 Call ended" 
                    })]);
                  } else {
                    // Show phone input
                    setShowPhoneInput(!showPhoneInput);
                  }
                }}
              >
                {callActive ? "📵" : "📞"}
              </button>
              
              {/* Tooltip */}
              {!isCallDisabled && (
                <div 
                  style={{
                    ...styles.buttonTooltip,
                    ...(showPhoneTooltip ? styles.buttonTooltipVisible : {})
                  }}
                >
                  {callActive ? "Hang up the phone call" : "Make a phone call"}
                </div>
              )}
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

          </div>
        </div>

        {/* Phone Input Panel */}
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