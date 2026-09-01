"""
Live (deployed-endpoint) evaluation drivers.

These drivers exercise a *deployed* voice backend over its real WebSocket voice
channel so evals measure representative end-to-end latencies (STT -> LLM -> TTS ->
first audio) instead of running the orchestrator in-process on the runner.

Grading of tool-calls / handoffs / response content is intentionally NOT done in
these drivers -- it comes from the ``eval_``-tagged ``invoke_agent`` /
``execute_tool`` traces the session emits into Application Insights (the same
span content the Foundry trace-eval path consumes). The driver only captures
what the voice channel exposes: latency and the assistant's spoken/transcribed
response text.
"""
