# Genesys AudioHook ownership notes

This module owns the Genesys-specific transport contract for the VoiceLive path.
It does **not** introduce a third engine or a generic voice framework layer.

## Channel responsibilities

- Negotiate and validate AudioHook v2 protocol messages.
- Convert Genesys PCMU 8 kHz audio to VoiceLive PCM16 24 kHz, and back.
- Preserve monotonic AudioHook server sequence numbers by sending all outbound
  JSON control messages and binary audio through a single writer task.
- Keep outbound audio response-scoped so barge-in can invalidate:
  - accumulated audio not yet chunked,
  - queued audio not yet written to the socket,
  - late provider deltas from an interrupted response.
- Let response terminal events finalize encoder residuals promptly; paced audio
  draining stays with the owned pacer/writer so the VoiceLive reader can react
  to a following `speech_started` interruption immediately.

## Lifecycle guarantees

- The outbound pacer task is the only pacing mechanism; there is no separate
  drain manager.
- Shutdown owns the pacer, writer, event loop, orchestrator cleanup, and
  partial-connection rollback.
- Audio deltas without a provider response id are dropped deliberately instead
  of being attributed to whichever response happened to be current.
- BYOM query parameters follow the common VoiceLive compatibility guard: a
  profile/model API mismatch is logged and dropped for that connection rather
  than opening a transcribing-but-silent call.

## Codec rules

- Streaming converters retain residual PCM bytes and resampling state so the
  result does not depend on arbitrary WebSocket chunk boundaries.
- Base64 and PCM framing errors surface as conversion failures; the bridge does
  not claim an 8 kHz PCMU payload while forwarding unconverted 24 kHz bytes.
