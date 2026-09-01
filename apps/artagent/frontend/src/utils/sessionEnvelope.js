// Normalize the backend WebSocket envelope into the flat payload consumed by
// the frontend event handlers. Keeping this pure makes the backend→UI contract
// testable without a browser or WebSocket.
export const isSessionEnvelope = (value) =>
  Boolean(
    value &&
      value.type &&
      value.sender &&
      value.payload &&
      value.ts,
  );

export const flattenSessionEnvelope = (envelope) => {
  if (!isSessionEnvelope(envelope)) return envelope;

  const envelopeType = envelope.type;
  const envelopeSender = envelope.sender;
  const actualPayload = envelope.payload ?? {};
  let flattenedPayload;

  if (envelopeType === 'event' && (actualPayload.event_type || actualPayload.eventType)) {
    const eventType = actualPayload.event_type || actualPayload.eventType;
    const eventData = {
      ...(typeof actualPayload.data === 'object' && actualPayload.data
        ? actualPayload.data
        : {}),
      ...actualPayload,
    };
    delete eventData.event_type;
    delete eventData.eventType;
    flattenedPayload = {
      ...eventData,
      type: 'event',
      event_type: eventType,
      event_data: eventData,
      data: eventData,
      message: actualPayload.message || eventData.message,
      content: actualPayload.content || eventData.content || actualPayload.message,
      sender: envelopeSender,
      speaker: envelopeSender,
    };
  } else if (
    envelopeType === 'event' &&
    actualPayload.message !== undefined &&
    !actualPayload.event_type &&
    !actualPayload.eventType
  ) {
    const merged = { ...actualPayload };
    merged.message = merged.message ?? actualPayload.message;
    merged.content = merged.content ?? actualPayload.message;
    merged.streaming = merged.streaming ?? false;
    flattenedPayload = {
      ...merged,
      type: merged.type || 'assistant',
      sender: envelopeSender,
      speaker: envelopeSender,
    };
  } else if (envelopeType === 'assistant_streaming') {
    const merged = { ...actualPayload };
    merged.content = merged.content ?? merged.message ?? '';
    merged.streaming = true;
    flattenedPayload = {
      ...merged,
      type: 'assistant_streaming',
      sender: envelopeSender,
      speaker: envelopeSender,
    };
  } else if (envelopeType === 'status' && actualPayload.message) {
    const merged = { ...actualPayload };
    merged.message = merged.message ?? actualPayload.message;
    merged.content = merged.content ?? actualPayload.message;
    merged.statusLabel = merged.statusLabel ?? merged.label ?? merged.status_label;
    flattenedPayload = {
      ...merged,
      type: 'status',
      sender: envelopeSender,
      speaker: envelopeSender,
    };
  } else {
    flattenedPayload = {
      ...actualPayload,
      type: actualPayload.type || envelopeType,
      sender: envelopeSender,
      speaker: envelopeSender,
    };
  }

  if (envelope.ts && !flattenedPayload.ts) flattenedPayload.ts = envelope.ts;
  if (envelope.session_id && !flattenedPayload.session_id) {
    flattenedPayload.session_id = envelope.session_id;
  }
  if (envelope.topic && !flattenedPayload.topic) {
    flattenedPayload.topic = envelope.topic;
  }

  return flattenedPayload;
};
