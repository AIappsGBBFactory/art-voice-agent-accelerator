// Bounded, id-based deduplication for backend WebSocket envelopes.
//
// A single backend emission is fanned out to every connection registered under
// a session (see ConnectionManager.broadcast_session), and the browser holds
// more than one such connection during a call: the conversation socket and the
// dashboard relay socket. Both funnel into the same message handler, so without
// an identity check every event renders twice.
//
// Dedupe is deliberately identity-based, never content-based: two genuinely
// distinct events that look alike (consecutive agent handoffs, repeated
// identical status pings) carry different ids and both survive.
//
// Kept pure so the backend -> UI contract is testable without a browser.

export const DEFAULT_DEDUPE_CAPACITY = 512;

export const createEnvelopeDeduper = ({ capacity = DEFAULT_DEDUPE_CAPACITY } = {}) => {
  const maxEntries = Number.isFinite(capacity) && capacity > 0 ? Math.floor(capacity) : DEFAULT_DEDUPE_CAPACITY;
  const seen = new Set();
  const order = [];

  // Fail open: frames without a usable id keep the pre-existing behavior rather
  // than risking the loss of a legitimate event.
  const shouldProcess = (id) => {
    if (typeof id !== 'string' || id === '') return true;
    if (seen.has(id)) return false;

    seen.add(id);
    order.push(id);
    while (order.length > maxEntries) {
      seen.delete(order.shift());
    }
    return true;
  };

  return {
    shouldProcess,
    clear: () => {
      seen.clear();
      order.length = 0;
    },
    size: () => seen.size,
    capacity: maxEntries,
  };
};
