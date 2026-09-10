const asId = (value) => {
  if (value === null || value === undefined || value === '') return null;
  return String(value);
};

export const resolveTurnId = (payload = {}) =>
  asId(
    payload.turn_id ??
      payload.turnId ??
      payload.parent_turn_id ??
      payload.parentTurnId,
  );

export const resolveSegmentId = (payload = {}, turnId = resolveTurnId(payload)) =>
  asId(
    payload.segment_id ??
      payload.segmentId ??
      payload.response_id ??
      payload.responseId ??
      turnId,
  );

export const buildTurnMessageKey = ({ turnId, role, speaker }) => {
  const canonicalTurn = asId(turnId) || 'unscoped';
  if (role === 'user') return `turn:${canonicalTurn}:user`;
  // A turn has one response bubble even if a handoff changes the agent that
  // completes it. Tool cards have their own call-scoped keys below, so they
  // cannot be mistaken for or overwrite the response.
  return `turn:${canonicalTurn}:assistant`;
};

// Every tool call in a turn shares ONE grouped card so the UI shows a single
// consolidated "tool activity" blob per turn instead of one card per call.
export const buildToolGroupKey = ({ turnId }) =>
  `turn:${asId(turnId) || 'unscoped'}:tools`;

export const mergeStreamText = (currentText, incomingText, contentMode) => {
  const incoming = incomingText ?? '';
  if (contentMode === 'delta') {
    return `${currentText ?? ''}${incoming}`;
  }
  return incoming;
};

// Normalize transcript/response text so a streaming partial renders identically
// to the final: unify CRLF, strip trailing spaces before newlines, collapse
// blank runs, and trim the edges. This keeps the bubble visually stable as
// partials stream into the final (no phantom blank lines or jitter).
export const normalizeTranscriptText = (value) =>
  String(value ?? '')
    .replace(/\r\n/g, '\n')
    .replace(/\s*\n+\s*/g, ' ')
    .replace(/[ \t]{2,}/g, ' ')
    .trim();

const TURN_ROLE_ORDER = Object.freeze({ user: 0, assistant: 1, tool: 2 });

const insertTurnScopedMessage = (messages, message) => {
  if (!message?.turnId) return [...messages, message];

  const roleOrder = TURN_ROLE_ORDER[message.turnRole] ?? 99;
  let lastTurnIndex = -1;
  for (let index = 0; index < messages.length; index += 1) {
    const candidate = messages[index];
    if (String(candidate?.turnId) !== String(message.turnId)) continue;
    lastTurnIndex = index;
    const candidateOrder = TURN_ROLE_ORDER[candidate.turnRole] ?? 99;
    if (candidateOrder > roleOrder) {
      return [
        ...messages.slice(0, index),
        message,
        ...messages.slice(index),
      ];
    }
  }

  if (lastTurnIndex >= 0) {
    return [
      ...messages.slice(0, lastTurnIndex + 1),
      message,
      ...messages.slice(lastTurnIndex + 1),
    ];
  }
  return [...messages, message];
};

const isStaleSequence = (current, patch) => {
  const currentSequence = Number(current?.sequence);
  const nextSequence = Number(patch?.sequence);
  return (
    Number.isFinite(currentSequence) &&
    Number.isFinite(nextSequence) &&
    nextSequence < currentSequence
  );
};

export const upsertTurnMessage = (
  messages,
  {
    turnId,
    role,
    speaker,
    updater,
    initial,
    createIfMissing = true,
  },
) => {
  const messageKey = buildTurnMessageKey({ turnId, role, speaker });
  let index = messages.findIndex((message) => message.messageKey === messageKey);

  // Backward-compatible lookup for a bubble created before messageKey was added.
  if (index === -1 && turnId) {
    index = messages.findIndex(
      (message) =>
        !message?.isTool &&
        message?.turnId === turnId &&
        (role === 'user'
          ? message?.speaker === 'User'
          : message?.turnRole === 'assistant'),
    );
  }

  if (index === -1) {
    if (!createIfMissing) return messages;
    const base = typeof initial === 'function' ? initial() : initial;
    if (!base) return messages;
    return insertTurnScopedMessage(messages, {
      ...base,
      messageKey,
      turnId: turnId || base.turnId,
      turnRole: role,
    });
  }

  const current = messages[index];
  const patch = typeof updater === 'function' ? updater(current) : updater;
  if (!patch || patch === current || isStaleSequence(current, patch)) return messages;

  const next = [...messages];
  next[index] = {
    ...current,
    ...patch,
    messageKey,
    turnId: turnId || current.turnId,
    turnRole: role,
  };
  return next;
};

export const upsertToolGroupMessage = (
  messages,
  { turnId, callId, toolName, patch = {} },
) => {
  const messageKey = buildToolGroupKey({ turnId });
  const callKey = asId(callId) || toolName || 'unknown';

  // Merge a single call's patch into the group's toolCalls list, tracking each
  // call by its id (falling back to tool name) so same-name calls stay distinct.
  const applyCall = (calls = []) => {
    const next = [...calls];
    let callIndex = next.findIndex((c) => c.callKey === callKey);
    if (callIndex === -1 && callId) {
      callIndex = next.findIndex((c) => asId(c.callId) === asId(callId));
    }
    const identity = {
      callKey,
      callId: asId(callId) || null,
      toolName: toolName || patch.toolName || 'tool',
    };
    if (callIndex === -1) {
      next.push({ ...identity, ...patch });
    } else {
      next[callIndex] = { ...next[callIndex], ...identity, ...patch };
    }
    return next;
  };

  let index = messages.findIndex((message) => message.messageKey === messageKey);
  if (index === -1 && turnId) {
    index = messages.findIndex(
      (message) => message?.isToolGroup && asId(message?.turnId) === asId(turnId),
    );
  }

  if (index === -1) {
    return insertTurnScopedMessage(messages, {
      isTool: true,
      isToolGroup: true,
      speaker: 'Assistant',
      messageKey,
      turnId: asId(turnId),
      turnRole: 'tool',
      toolCalls: applyCall([]),
    });
  }

  const current = messages[index];
  const next = [...messages];
  next[index] = {
    ...current,
    toolCalls: applyCall(current.toolCalls),
  };
  return next;
};