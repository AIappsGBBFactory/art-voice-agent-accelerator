# """orchestration.orchestrator

# Minimal state‑machine that delegates each user turn to the **first** agent whose
# ``gate()`` returns *True*.  The orchestrator itself is stateless beyond that
# agent list; all conversation context lives in :class:`ConversationMemory`.

# Usage (inside a WebSocket handler)
# ---------------------------------
# ::

#     conv_mem = ConversationMemory(cid)
#     agents = [AuthAgent(llm=aoai, conv_mem=conv_mem, mem0=mem0_auth, prompt=AUTH_PROMPT),
#               TaskAgent(llm=aoai, conv_mem=conv_mem, mem0=mem0_task, prompt=TASK_PROMPT, tools=available_tools)]
#     orc = Orchestrator(agents)

#     async for user_text in stt_stream():
#         await orc.handle_turn(user_text, chunk_cb=tts.enqueue)

#     await orc.finish()  # flush to Cosmos once at end
# """
# from __future__ import annotations

# import asyncio
# from typing import List, Sequence

# from agents.base import BaseAgent
# from memory import ConversationMemory

# __all__ = ["Orchestrator"]


# class Orchestrator:
#     """Lightweight turn router.

#     Parameters
#     ----------
#     agents
#         Ordered list; the first agent that reports ``gate() == True`` will run
#         the turn.  Typical order: `[AuthAgent, TaskAgent, ...]`.
#     """

#     def __init__(self, agents: Sequence[BaseAgent]):
#         if not agents:
#             raise ValueError("Orchestrator requires ≥1 agent")
#         self._agents: List[BaseAgent] = list(agents)
#         self._conv_mem: ConversationMemory = agents[0]._conv_mem  # they all share

#     async def handle_turn(
#         self,
#         user_text: str,
#         *,
#         chunk_cb: callable[[str], asyncio.Future] | None = None,
#     ) -> str:
#         """Route `user_text` to the eligible agent and return its full reply."""
#         for agent in self._agents:
#             if agent.gate():
#                 return await agent.run_turn(user_text, chunk_cb=chunk_cb)
#         # In practice this should never happen if the last agent’s gate() is
#         # always True, but fail fast if mis‑configured.
#         raise RuntimeError("No eligible agent found for current turn")

#     async def finish(self) -> None:
#         """Flush shared conversation memory to Cosmos (one call)."""
#         await self._conv_mem.flush()
#         await self._conv_mem.clear()  # free Redis
