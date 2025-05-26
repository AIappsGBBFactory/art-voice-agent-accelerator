# """orchestration.orchestrator

# Minimal state‑machine that delegates each user turn to the **first** agent whose
# ``gate()`` returns *True*.  The orchestrator itself is stateless beyond that
# agent list; all conversation context lives in :class:`ConversationMemory`.

# Usage (inside a WebSocket handler)
# ---------------------------------
# """
# from fastapi import WebSocket
# from usecases.RTMedAgent.backend.orchestration.gpt_flow import process_gpt_response

# from utils.ml_logging import get_logger
# logger = get_logger("gpt_flow")

# async def route_turn(cm, transcript: str, ws: WebSocket, *, is_acs: bool) -> None:
#     """
#     Routes a single user utterance through authentication or main dialog,
#     then persists the conversation state.

#     Adds latency tracking for each step.
#     """
#     redis_mgr = ws.app.state.redis
#     latency_tool = ws.state.lt

#     if not cm.get_context("authenticated", False):
#         # Processing step for authentication
#         latency_tool.start("processing")
#         result = await process_gpt_response(cm, transcript, ws, is_acs=is_acs)
#         latency_tool.stop("processing", redis_mgr)

#         if result and result.get("authenticated"):
#             cm.update_context("authenticated", True)
#             cm.upsert_system_prompt()
#             logger.info(
#                 f"Session {cm.session_id} authenticated successfully."
#             )
#     else:
#         # Processing step for main dialog
#         latency_tool.start("processing")
#         await process_gpt_response(cm, transcript, ws, is_acs=is_acs)
#         latency_tool.stop("processing", redis_mgr)
#     cm.persist_to_redis(redis_mgr)
