import {
  mergeStreamText,
  resolveSegmentId,
  resolveTurnId,
  upsertToolGroupMessage,
  upsertTurnMessage,
} from './turnMessages.js';

export const BubbleEventType = Object.freeze({
  USER_PARTIAL: 'user_partial',
  USER_FINAL: 'user_final',
  ASSISTANT_STREAM: 'assistant_stream',
  ASSISTANT_FINAL: 'assistant_final',
  ASSISTANT_CANCELLED: 'assistant_cancelled',
  TOOL_START: 'tool_start',
  TOOL_PROGRESS: 'tool_progress',
  TOOL_END: 'tool_end',
  ERROR: 'error',
});

const textFrom = (payload = {}) => payload.content ?? payload.message ?? '';

const canonicalTurnId = (payload = {}) =>
  resolveTurnId(payload) ||
  (payload.response_id && !payload.segment_id ? String(payload.response_id) : null) ||
  (payload.responseId && !payload.segmentId ? String(payload.responseId) : null);

/** Convert a flattened backend payload into a side-effect-free bubble event. */
export const conversationBubbleEventFromPayload = (payload = {}) => {
  const type = String(payload.type || '').toLowerCase();

  if (payload.event_type === 'stt_partial') {
    const data = payload.data || payload.event_data || payload;
    return {
      type: BubbleEventType.USER_PARTIAL,
      turnId: canonicalTurnId(data),
      segmentId: resolveSegmentId(data),
      text: textFrom(data),
      contentMode: data.content_mode || data.contentMode || 'snapshot',
      sequence: data.sequence,
      language: data.language,
      timestamp: data.ts || data.timestamp || payload.ts,
    };
  }

  if (type === 'user' || payload.speaker === 'User') {
    const streaming = payload.streaming === true && payload.is_final !== true;
    return {
      type: streaming ? BubbleEventType.USER_PARTIAL : BubbleEventType.USER_FINAL,
      turnId: canonicalTurnId(payload),
      segmentId: resolveSegmentId(payload),
      text: textFrom(payload),
      contentMode: payload.content_mode || payload.contentMode || 'snapshot',
      sequence: payload.sequence,
      language: payload.language,
      timestamp: payload.ts || payload.timestamp,
    };
  }

  if (type === 'error') {
    return {
      type: BubbleEventType.ERROR,
      turnId: canonicalTurnId(payload),
      code: payload.code || payload.error_type || 'UnknownError',
      text: payload.message || payload.error_message || payload.content || 'An error occurred.',
      details: payload.details,
      remediation: payload.remediation,
      source: payload.source,
      fatal: payload.fatal === true,
      timestamp: payload.ts || payload.timestamp,
    };
  }

  if (type === 'assistant_cancelled') {
    return {
      type: BubbleEventType.ASSISTANT_CANCELLED,
      turnId: canonicalTurnId(payload),
      segmentId: resolveSegmentId(payload),
      reason: payload.cancel_reason || payload.cancelReason || payload.reason,
      timestamp: payload.ts || payload.timestamp,
    };
  }

  if (type === 'assistant_streaming') {
    return {
      type: BubbleEventType.ASSISTANT_STREAM,
      turnId: canonicalTurnId(payload),
      segmentId: resolveSegmentId(payload),
      speaker: payload.speaker || payload.sender || 'Assistant',
      text: textFrom(payload),
      contentMode: payload.content_mode || payload.contentMode || 'delta',
      sequence: payload.sequence,
      timestamp: payload.ts || payload.timestamp,
    };
  }

  if (type === 'assistant') {
    return {
      type: BubbleEventType.ASSISTANT_FINAL,
      turnId: canonicalTurnId(payload),
      segmentId: resolveSegmentId(payload),
      speaker: payload.speaker || payload.sender || 'Assistant',
      text: textFrom(payload),
      sequence: payload.sequence,
      status: payload.status,
      error: payload.error,
      timestamp: payload.ts || payload.timestamp,
    };
  }

  if (type === 'tool_start' || type === 'tool_progress' || type === 'tool_end') {
    const eventType = {
      tool_start: BubbleEventType.TOOL_START,
      tool_progress: BubbleEventType.TOOL_PROGRESS,
      tool_end: BubbleEventType.TOOL_END,
    }[type];
    return {
      type: eventType,
      turnId: canonicalTurnId(payload),
      segmentId: resolveSegmentId(payload),
      callId: payload.call_id || payload.callId || payload.tool_call_id || null,
      toolName: payload.tool || payload.tool_name || 'unknown',
      status: payload.status,
      pct: payload.pct,
      result: payload.result ?? payload.output ?? payload.data ?? payload.response,
      error: payload.error,
      elapsedMs: payload.elapsedMs ?? payload.elapsed_ms,
      sender: payload.speaker || payload.sender || 'Assistant',
      timestamp: payload.ts || payload.timestamp,
    };
  }

  return null;
};

const userMessages = (messages) =>
  messages.filter((message) => message?.turnRole === 'user' || message?.speaker === 'User');

const latestUserTurnId = (messages) => {
  const latest = userMessages(messages).at(-1);
  return latest?.turnId ? String(latest.turnId) : null;
};

const hasUserTurn = (messages, turnId) =>
  Boolean(
    turnId &&
      userMessages(messages).some((message) => String(message?.turnId) === String(turnId)),
  );

// A different known turn arriving after a newer user turn is a late event from
// the interrupted turn. A previously unseen turn ID is the start of a new turn.
const isLateKnownUserTurn = (messages, turnId) => {
  const latestTurn = latestUserTurnId(messages);
  return Boolean(
    turnId &&
      latestTurn &&
      String(turnId) !== latestTurn &&
      hasUserTurn(messages, turnId),
  );
};

const isLateAssistantOrToolTurn = (messages, turnId) => {
  const latestTurn = latestUserTurnId(messages);
  if (!turnId || !latestTurn || String(turnId) === latestTurn) return false;
  // Late only if this id belongs to an earlier *user* turn that a newer user
  // turn has superseded (barge-in). Response/tool ids that never matched a user
  // turn are the current response and MUST render, even when the backend stamps
  // them with an id that differs from the user turn's.
  return userMessages(messages).some(
    (message) => String(message?.turnId) === String(turnId),
  );
};

const interruptPriorTurnActivity = (messages, nextTurnId) =>
  messages.map((message) => {
    if (!message?.turnId || String(message.turnId) === String(nextTurnId)) return message;

    if (message.turnRole === 'assistant' && message.streaming) {
      return {
        ...message,
        streaming: false,
        cancelled: true,
        cancelReason: message.cancelReason || 'barge_in',
      };
    }

    if (message.isToolGroup && Array.isArray(message.toolCalls)) {
      let changed = false;
      const toolCalls = message.toolCalls.map((call) => {
        if (call.status === 'started' || call.status === 'in_progress') {
          changed = true;
          return { ...call, status: 'cancelled' };
        }
        return call;
      });
      return changed ? { ...message, toolCalls } : message;
    }

    return message;
  });

const findTurnBubble = (messages, turnId, role) =>
  messages.find(
    (message) =>
      message?.turnRole === role && String(message?.turnId) === String(turnId),
  );

// Turn ID of the currently-open (streaming) bubble for a role, so a run of
// turn-id-less partials/deltas collapses into one bubble instead of vanishing.
const openBubbleTurnId = (messages, role) => {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message?.turnRole === role && message?.streaming === true && message?.turnId) {
      return String(message.turnId);
    }
  }
  return null;
};

// Deterministic fallback turn key for envelopes that omit turn_id. It is unique
// per utterance because the message list only grows between finalized turns.
const newSyntheticTurnId = (messages) => `synthetic-${messages.length}`;

const segmentRank = (segmentId, turnId) => {
  if (!segmentId || !turnId) return null;
  const segment = String(segmentId);
  const turn = String(turnId);
  if (segment === turn) return 0;
  const match = segment.match(new RegExp(`^${turn.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}_s(\\d+)$`));
  return match ? Number(match[1]) : null;
};

const isNewAssistantSegment = (current, event) => {
  if (!current?.segmentId || !event?.segmentId) return false;
  if (String(current.segmentId) === String(event.segmentId)) return false;

  const currentRank = segmentRank(current.segmentId, event.turnId);
  const nextRank = segmentRank(event.segmentId, event.turnId);
  if (currentRank !== null && nextRank !== null) return nextRank > currentRank;

  const currentSequence = Number(current.sequence);
  const nextSequence = Number(event.sequence);
  return (
    Number.isFinite(currentSequence) &&
    Number.isFinite(nextSequence) &&
    nextSequence > currentSequence
  );
};

const reduceUserEvent = (messages, event, streaming) => {
  const hasRealTurn = Boolean(event.turnId);
  // Resilience: never drop a transcript because the backend omitted turn_id.
  // Coalesce id-less partials into the open streaming user bubble and start a
  // fresh synthetic turn once it finalizes, mirroring pre-reducer behavior.
  const turnId =
    event.turnId || openBubbleTurnId(messages, 'user') || newSyntheticTurnId(messages);
  if (hasRealTurn && isLateKnownUserTurn(messages, turnId)) return messages;

  let next = interruptPriorTurnActivity(messages, turnId);
  const current = findTurnBubble(next, turnId, 'user');
  // Once finalized, late partial hypotheses for that turn cannot reopen it.
  if (streaming && current && current.streaming === false) return next;

  next = upsertTurnMessage(next, {
    turnId,
    role: 'user',
    speaker: 'User',
    updater: (existing = {}) => ({
      ...existing,
      speaker: 'User',
      text: mergeStreamText(existing.text, event.text, event.contentMode),
      streaming,
      streamingType: streaming ? 'stt_partial' : 'stt_final',
      sequence: event.sequence ?? existing.sequence,
      language: event.language || existing.language,
      segmentId: event.segmentId || existing.segmentId,
      timestamp: event.timestamp || existing.timestamp,
      cancelled: false,
    }),
    initial: () => ({
      speaker: 'User',
      text: event.text,
      streaming,
      streamingType: streaming ? 'stt_partial' : 'stt_final',
      sequence: event.sequence,
      language: event.language,
      segmentId: event.segmentId,
      timestamp: event.timestamp,
      cancelled: false,
    }),
  });

  if (!streaming) {
    // Defensive cleanup for legacy/unscoped partial bubbles. A canonical final
    // must leave exactly one user bubble for this turn.
    next = next.filter(
      (message) =>
        !(
          message?.speaker === 'User' &&
          message?.streaming === true &&
          String(message?.turnId) !== String(turnId)
        ),
    );
  }
  return next;
};

const reduceAssistantStream = (messages, event) => {
  if (!event.text) return messages;
  const hasRealTurn = Boolean(event.turnId);
  const turnId =
    event.turnId ||
    openBubbleTurnId(messages, 'assistant') ||
    latestUserTurnId(messages) ||
    newSyntheticTurnId(messages);
  if (hasRealTurn && isLateAssistantOrToolTurn(messages, turnId)) return messages;

  const current = findTurnBubble(messages, turnId, 'assistant');
  // Cancellation/finalization closes the stream. Late deltas cannot reopen or
  // duplicate the same segment after barge-in or RESPONSE_DONE. VoiceLive may
  // finalize a pre-tool segment and then start a new post-tool segment for the
  // same user turn; that newer segment is allowed to continue this one bubble.
  if (current?.cancelled) return messages;
  if (current?.streaming === false && !isNewAssistantSegment(current, event)) {
    return messages;
  }

  return upsertTurnMessage(messages, {
    turnId,
    role: 'assistant',
    speaker: event.speaker,
    updater: (existing = {}) => ({
      ...existing,
      speaker: event.speaker || existing.speaker || 'Assistant',
      text: mergeStreamText(existing.text, event.text, event.contentMode),
      streaming: true,
      sequence: event.sequence ?? existing.sequence,
      segmentId: event.segmentId || existing.segmentId,
      timestamp: event.timestamp || existing.timestamp,
      cancelled: false,
      cancelReason: undefined,
    }),
    initial: () => ({
      speaker: event.speaker || 'Assistant',
      text: event.text,
      streaming: true,
      sequence: event.sequence,
      segmentId: event.segmentId,
      timestamp: event.timestamp,
      cancelled: false,
    }),
  });
};

const reduceAssistantFinal = (messages, event) => {
  const hasRealTurn = Boolean(event.turnId);
  // Finalize the in-flight streaming response bubble when one is open, so a
  // final whose id differs from the streaming id (e.g. cascade post-tool, where
  // the streamed chunks and the final envelope can carry different ids) settles
  // the SAME bubble instead of spawning a duplicate beside it.
  const openTurnId = openBubbleTurnId(messages, 'assistant');
  const turnId =
    openTurnId ||
    event.turnId ||
    latestUserTurnId(messages) ||
    newSyntheticTurnId(messages);
  if (!openTurnId && hasRealTurn && isLateAssistantOrToolTurn(messages, turnId)) {
    return messages;
  }

  const current = findTurnBubble(messages, turnId, 'assistant');
  if (current?.cancelled) return messages;
  if (current?.streaming === false && !isNewAssistantSegment(current, event)) {
    return messages;
  }

  return upsertTurnMessage(messages, {
    turnId,
    role: 'assistant',
    speaker: event.speaker,
    updater: (existing = {}) => ({
      ...existing,
      speaker: event.speaker || existing.speaker || 'Assistant',
      text: event.text || existing.text || '',
      streaming: false,
      sequence: event.sequence ?? existing.sequence,
      segmentId: event.segmentId || existing.segmentId,
      timestamp: event.timestamp || existing.timestamp,
      status: event.status,
      error: event.error,
      cancelled: false,
      cancelReason: undefined,
    }),
    initial: () => ({
      speaker: event.speaker || 'Assistant',
      text: event.text || '',
      streaming: false,
      sequence: event.sequence,
      segmentId: event.segmentId,
      timestamp: event.timestamp,
      status: event.status,
      error: event.error,
      cancelled: false,
    }),
  });
};

const reduceAssistantCancelled = (messages, event) => {
  // Prefer the in-flight streaming response bubble (the one actually being
  // interrupted), then the event's own id, then the most recent assistant
  // bubble — so cascade barge-in marks the right bubble even when the cancel
  // envelope's id differs from the streamed response's id.
  const openTurnId = openBubbleTurnId(messages, 'assistant');
  const latestAssistant = [...messages]
    .reverse()
    .find((message) => message?.turnRole === 'assistant');
  const turnId = openTurnId || event.turnId || latestAssistant?.turnId;
  if (!turnId) return messages;

  return upsertTurnMessage(messages, {
    turnId,
    role: 'assistant',
    speaker: event.speaker,
    updater: (current) =>
      current
        ? {
            streaming: false,
            cancelled: true,
            cancelReason: event.reason || current.cancelReason || 'barge_in',
          }
        : null,
    initial: null,
    createIfMissing: false,
  });
};

const reduceToolEvent = (messages, event) => {
  const hasRealTurn = Boolean(event.turnId);
  const turnId =
    event.turnId || latestUserTurnId(messages) || newSyntheticTurnId(messages);
  if (hasRealTurn && isLateAssistantOrToolTurn(messages, turnId)) return messages;

  const existingGroup = messages.find(
    (message) =>
      message?.isToolGroup && String(message?.turnId) === String(turnId),
  );
  const existingCall = existingGroup?.toolCalls?.find(
    (call) =>
      (event.callId && String(call.callId) === String(event.callId)) ||
      (!event.callId && call.toolName === event.toolName),
  );
  if (existingCall?.status === 'cancelled') return messages;
  if (
    (existingCall?.status === 'success' || existingCall?.status === 'error') &&
    (event.type === BubbleEventType.TOOL_START ||
      event.type === BubbleEventType.TOOL_PROGRESS)
  ) {
    return messages;
  }

  const patch = {
    toolName: event.toolName,
    segmentId: event.segmentId,
    timestamp: event.timestamp,
  };
  if (event.type === BubbleEventType.TOOL_START) {
    patch.status = 'started';
    patch.sender = event.sender;
  } else if (event.type === BubbleEventType.TOOL_PROGRESS) {
    patch.status = 'in_progress';
    patch.pct = Number.isFinite(Number(event.pct)) ? Number(event.pct) : undefined;
  } else {
    patch.status = event.status === 'success' ? 'success' : 'error';
    patch.result = event.result;
    patch.error = event.error;
    patch.elapsedMs = event.elapsedMs;
  }

  return upsertToolGroupMessage(messages, {
    turnId,
    callId: event.callId,
    toolName: event.toolName,
    patch,
  });
};

/**
 * Append an error bubble. Errors are never merged into an existing turn slot:
 * a config failure can fire before any turn exists, and collapsing repeats
 * would hide a recurring failure from the operator.
 */
const reduceErrorEvent = (messages, event) => {
  const list = Array.isArray(messages) ? messages : [];
  const last = list[list.length - 1];

  // Collapse only an immediately repeated identical error so a retry loop does
  // not flood the transcript.
  if (last && last.kind === 'error' && last.code === event.code && last.text === event.text) {
    return list;
  }

  return [
    ...list,
    {
      kind: 'error',
      speaker: 'System',
      // `status`/`error` are the shape ChatBubble's error card already renders.
      status: 'error',
      error: {
        code: event.code,
        message: event.text,
        details: event.details,
        remediation: event.remediation,
        source: event.source,
      },
      code: event.code,
      text: event.text,
      details: event.details,
      remediation: event.remediation,
      source: event.source,
      fatal: event.fatal,
      timestamp: event.timestamp,
    },
  ];
};

/**
 * Pure reducer for the three canonical bubble slots in a turn:
 * user transcript, assistant response, and grouped tool activity.
 */
export const reduceConversationBubbles = (messages, event) => {
  if (!event) return messages;

  switch (event.type) {
    case BubbleEventType.USER_PARTIAL:
      return reduceUserEvent(messages, event, true);
    case BubbleEventType.USER_FINAL:
      return reduceUserEvent(messages, event, false);
    case BubbleEventType.ASSISTANT_STREAM:
      return reduceAssistantStream(messages, event);
    case BubbleEventType.ASSISTANT_FINAL:
      return reduceAssistantFinal(messages, event);
    case BubbleEventType.ASSISTANT_CANCELLED:
      return reduceAssistantCancelled(messages, event);
    case BubbleEventType.TOOL_START:
    case BubbleEventType.TOOL_PROGRESS:
    case BubbleEventType.TOOL_END:
      return reduceToolEvent(messages, event);
    case BubbleEventType.ERROR:
      return reduceErrorEvent(messages, event);
    default:
      return messages;
  }
};

export const reduceConversationPayload = (messages, payload) =>
  reduceConversationBubbles(messages, conversationBubbleEventFromPayload(payload));
