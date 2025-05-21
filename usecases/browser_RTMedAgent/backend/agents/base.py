"""agents.py

This module defines the **BaseAgent** class and its concrete subclasses
Each agent owns a **private Mem0** instance for durable semantic memory and
shares a **ConversationMemory** timeline (Redis→Cosmos) with its peers.  The
public API is optimised for *single‑digit‑ms* hot‑path latency:

* `gate()`  – O(1) boolean used by the Orchestrator to choose the agent.
* `run_turn()` – async, streams GPT chunks; caller can push to TTS in real‑time.

All agents are **stateless between turns** except for their Mem0 store and any
private flags (e.g. AuthAgent._authenticated).  They are therefore safe to keep
alive for the lifetime of a WebSocket connection.
"""
from __future__ import annotations

import asyncio
import json
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Sequence

from mem0 import Memory
from openai import AsyncAzureOpenAI

from memory.conversation import ConversationMemory

# --------------------------------------------------------------------------- #
#  BaseAgent – low‑latency backbone                                           #
# --------------------------------------------------------------------------- #


class BaseAgent(ABC):
    """Common functionality for auth & task agents."""

    _TOP_K_MEMORIES: int = 4

    def __init__(
        self,
        *,
        name: str,
        system_prompt: str,
        llm: AsyncAzureOpenAI,
        conv_mem: ConversationMemory,
        mem0: Memory,
        tools: Sequence[Dict[str, Any]] | None = None,
    ) -> None:
        self.name = name
        self._prompt = system_prompt
        self._llm = llm
        self._conv_mem = conv_mem
        self._mem0 = mem0
        self._tools_static = list(tools) if tools else []
        # Seed history once.  Downstream prompt builders reuse this list.
        self._conv_mem.append("system", system_prompt)

    @abstractmethod
    def gate(self) -> bool:
        """Return *True* iff this agent should handle the next user turn."""

    async def after_run(
        self, user_msg: str, assistant_reply: str
    ) -> None:  # noqa: D401
        """Optional post‑processing (store new memories, etc.)."""

    async def run_turn(
        self,
        user_msg: str,
        *,
        chunk_cb: callable[[str], asyncio.Future] | None = None,
    ) -> str:
        """Handle a **single** user message.

        Parameters
        ----------
        user_msg
            The recognised text from STT.
        chunk_cb
            Optional coroutine called for *each* partial assistant chunk –
            e.g. to push to TTS in real‑time.  This is a fire‑and‑forget
        Returns
        -------
        str
            Full assistant reply (after streaming completes).
        """
        # 1) Append user turn.
        self._conv_mem.append("user", user_msg)

        # 2) Pull top‑K relevant memories – *at most once* per turn.
        mem_ctx = ""
        try:
            search = await asyncio.to_thread(
                self._mem0.search,
                user_msg,
                user_id=self._conv_mem.cid,
                limit=self._TOP_K_MEMORIES,
            )
            if res := search.get("results"):
                mem_ctx = "\n".join(r["memory"] for r in res)
        except Exception:  # noqa: BLE001 – fallback silently
            pass

        # 3) Build prompt.
        messages: List[Dict[str, Any]] = self._conv_mem.history.copy()
        if mem_ctx:
            messages.append(
                {
                    "role": "assistant",
                    "content": f"Relevant memories:\n{mem_ctx}",
                }
            )

        # 4) Fire streaming request.
        start = time.perf_counter()
        stream = self._llm.chat.completions.create(
            stream=True,
            model="gpt-4o",
            messages=messages,
            tools=self.tools(),
            tool_choice="auto" if self.tools() else None,
            temperature=0.5,
            max_tokens=512,
        )

        reply_parts: List[str] = []
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if getattr(delta, "content", None):
                text = delta.content
                reply_parts.append(text)
                if chunk_cb:
                    # Fire‑and‑forget; don’t await so we keep reading quickly.
                    asyncio.create_task(chunk_cb(text))

        elapsed = (time.perf_counter() - start) * 1000
        full_reply = "".join(reply_parts).strip()

        # 5) Persist assistant turn and run post‑hook.
        self._conv_mem.append("assistant", full_reply)
        await self.after_run(user_msg, full_reply)

        # 6) Debug: log latency once per turn (optional).
        print(f"⚡ {self.name}: stream {elapsed:.1f} ms, {len(full_reply)} chars")
        return full_reply

    # -------------------------- helper methods --------------------------- #

    def tools(self) -> Sequence[Dict[str, Any]]:  # noqa: D401
        """OpenAI tool schema list (may be empty)."""
        return self._tools_static
