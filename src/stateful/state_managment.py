"""
This module powers real‑time voice‑agent sessions. It extends the original
`MemoManager` with **live‑refresh** helpers that keep local state in sync with a
shared Redis cache and expose fine‑grained utilities for selective updates.
"""
import asyncio
import json
import uuid
from collections import deque
from typing import Any, Dict, List, Optional

from src.agenticmemory.playback_queue import MessageQueue
from src.agenticmemory.types import ChatHistory, CoreMemory
from src.agenticmemory.utils import LatencyTracker
from src.redis.manager import AzureRedisManager
from src.agents.prompts_loader.base import PromptManager
from utils.ml_logging import get_logger

logger = get_logger("src.stateful.state_managment")


class MemoManager:
    """
    Owns a conversation session – core memory, chat history & runtime state.
    """

    _CORE_KEY = "corememory"
    _HISTORY_KEY = "chat_history"

    def __init__(
        self,
        session_id: Optional[str] = None,
        auto_refresh_interval: Optional[float] = None,
        redis_mgr: Optional[AzureRedisManager] = None,
    ) -> None:
        """
        Constructor for MemoManager.

        Parameters:
        session_id (str): the session ID (default: a new UUID4)
        auto_refresh_interval (float): optional interval in seconds for auto-refresh (default: None)
        redis_mgr (AzureRedisManager): optional Redis manager (default: None)
        """
        self.session_id: str = session_id or str(uuid.uuid4())[:8]
        self.chatHistory: ChatHistory = ChatHistory()
        self.corememory: CoreMemory = CoreMemory()
        self.message_queue = MessageQueue()
        self._is_tts_interrupted: bool = False
        self.latency = LatencyTracker()
        self.auto_refresh_interval = auto_refresh_interval
        self.last_refresh_time = 0
        self._refresh_task: Optional[asyncio.Task] = None
        self._redis_manager: Optional[AzureRedisManager] = redis_mgr

    # ------------------------------------------------------------------
    # Compatibility aliases
    # TODO Fix
    # ------------------------------------------------------------------
    @property
    def histories(self) -> Dict[str, List[Dict[str, str]]]:  # noqa: D401
        return self.chatHistory.get_all()

    @histories.setter
    def histories(self, value: Dict[str, List[Dict[str, str]]]) -> None:  # noqa: D401
        self.chatHistory._threads = value  # direct assignment

    @property
    def context(self) -> Dict[str, Any]:  # noqa: D401
        return self.corememory._store

    @context.setter
    def context(self, value: Dict[str, Any]) -> None:  # noqa: D401
        self.corememory._store = value

    # single‑history alias for minimal diff elsewhere
    @property
    def history(self) -> ChatHistory:  # noqa: D401
        return self.chatHistory

    @staticmethod
    def build_redis_key(session_id: str) -> str:
        """Builds the Redis key for a session."""
        return f"session:{session_id}"

    def to_redis_dict(self) -> Dict[str, str]:
        return {
            self._CORE_KEY: self.corememory.to_json(),
            self._HISTORY_KEY: self.chatHistory.to_json(),
        }

    @classmethod
    def from_redis(cls, session_id: str, redis_mgr: AzureRedisManager) -> "MemoManager":
        key = cls.build_redis_key(session_id)
        data = redis_mgr.get_session_data(key)
        mm = cls(session_id=session_id)
        if mm._CORE_KEY in data:
            mm.corememory.from_json(data[mm._CORE_KEY])
        if mm._HISTORY_KEY in data:
            mm.chatHistory.from_json(data[mm._HISTORY_KEY])
        return mm

    @classmethod
    def from_redis_with_manager(
        cls, session_id: str, redis_mgr: AzureRedisManager
    ) -> "MemoManager":
        """Alternative constructor that stores the manager."""
        cm = cls(session_id=session_id, redis_mgr=redis_mgr)
        # ...existing logic...
        return cm

    async def persist(self, redis_mgr: Optional[AzureRedisManager] = None) -> None:
        """Persist using provided or stored redis manager."""
        mgr = redis_mgr or self._redis_manager
        if not mgr:
            raise ValueError("No Redis manager available")
        await self.persist_to_redis_async(mgr)

    def persist_to_redis(
        self, redis_mgr: AzureRedisManager, ttl_seconds: Optional[int] = None
    ) -> None:
        """Persist session state to Redis synchronously."""
        key = self.build_redis_key(self.session_id)
        redis_mgr.store_session_data(key, self.to_redis_dict())
        if ttl_seconds:
            redis_mgr.redis_client.expire(key, ttl_seconds)
        logger.info(
            f"Persisted session {self.session_id} – "
            f"histories per agent: {[f'{a}: {len(h)}' for a, h in self.histories.items()]}, ctx_keys={list(self.context.keys())}"
        )

    async def persist_to_redis_async(
        self, redis_mgr: AzureRedisManager, ttl_seconds: Optional[int] = None
    ) -> None:
        """Async version of persist_to_redis to avoid blocking the event loop."""
        key = self.build_redis_key(self.session_id)
        await redis_mgr.store_session_data_async(key, self.to_redis_dict())
        if ttl_seconds:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, redis_mgr.redis_client.expire, key, ttl_seconds
            )
        logger.info(
            f"Persisted session {self.session_id} async – "
            f"histories per agent: {[f'{a}: {len(h)}' for a, h in self.histories.items()]}, ctx_keys={list(self.context.keys())}"
        )

    # --- TTS Interrupt ------------------------------------------------
    def is_tts_interrupted(self) -> bool:
        """Return the in-memory TTS interrupted flag."""
        return self._is_tts_interrupted

    def set_tts_interrupted(self, value: bool) -> None:
        """Set the TTS interrupted flag in local context and optionally in Redis."""
        self.set_context("tts_interrupted", value)
        self._is_tts_interrupted = value

    async def set_tts_interrupted_live(
        self, redis_mgr: Optional[AzureRedisManager], session_id: str, value: bool
    ) -> None:
        """Set the TTS interrupted flag in Redis."""
        await self.set_live_context_value(
            redis_mgr or self._redis_manager, f"tts_interrupted:{session_id}", value
        )

    async def is_tts_interrupted_live(
        self,
        redis_mgr: Optional[AzureRedisManager] = None,
        session_id: Optional[str] = None,
    ) -> bool:
        """Check if TTS is interrupted, optionally checking live Redis data."""
        if redis_mgr and session_id:
            self._is_tts_interrupted = await self.get_live_context_value(
                redis_mgr, f"tts_interrupted:{session_id}", False
            )
            return self._is_tts_interrupted
        return self.get_context(f"tts_interrupted:{session_id}", False)

    # --- SLOTS & TOOL OUTPUTS -----------------------------------------
    def update_slots(self, slots: Dict[str, Any]) -> None:
        """
        Merge new slot values into core memory under 'slots'.
        """
        if not slots:
            return
        current_slots = self.corememory.get("slots", {})
        current_slots.update(slots)
        self.corememory.set("slots", current_slots)
        logger.debug(f"Updated slots: {slots}")

    def get_slot(self, slot_name: str, default: Any = None) -> Any:
        """
        Get a slot value from core memory.
        """
        return self.corememory.get("slots", {}).get(slot_name, default)

    def persist_tool_output(self, tool_name: str, result: Dict[str, Any]) -> None:
        """
        Store last result for each backend tool in core memory under 'tool_outputs'.
        """
        if not tool_name or not result:
            return
        tool_outputs = self.corememory.get("tool_outputs", {})
        tool_outputs[tool_name] = result
        self.corememory.set("tool_outputs", tool_outputs)
        logger.debug(f"Persisted tool output for '{tool_name}': {result}")

    def get_tool_output(self, tool_name: str, default: Any = None) -> Any:
        """
        Get last tool output from core memory.
        """
        return self.corememory.get("tool_outputs", {}).get(tool_name, default)

    # --- LATENCY ------------------------------------------------------
    def note_latency(self, stage: str, start_t: float, end_t: float) -> None:
        """Record latency for a stage."""
        self.latency.note(stage, start_t, end_t)

    def latency_summary(self) -> Dict[str, Dict[str, float]]:
        """Get latency summary."""
        return self.latency.summary()

    # --- HISTORY ------------------------------------------------------
    def append_to_history(self, agent: str, role: str, content: str) -> None:
        """Append *content* with *role* to the specified *agent* thread."""
        self.history.append(role, content, agent)

    def get_history(self, agent_name: str) -> List[Dict[str, str]]:
        """Return (and create if missing) the history for *agent_name*."""
        return self.history.get_agent(agent_name)

    def clear_history(self, agent_name: Optional[str] = None) -> None:
        """Clear chat history for *agent_name* or **all** if *None*."""
        self.history.clear(agent_name)

    # --- PROMPT INJECTION ---------------------------------------------
    # TODO this is wrong and needs to be fixed after close refactor [P.S]
    
    def get_context(self, key: str, default: Any = None) -> Any:
        """
        Shorthand for self.corememory.get().
        Returns *default* when the key is absent.
        """
        return self.corememory.get(key, default)

    def set_context(self, key: str, value: Any) -> None:
        """
        Overwrite *key* with *value* in core memory.
        Use `await self.persist()` afterwards if you need the change
        flushed to Redis immediately.
        """
        self.corememory.set(key, value)


    def update_context(self, key: str, value: Any) -> None:
        """
        Merge *value* into an existing dict stored under *key*.
        If the current value is not a mapping, it is replaced.
        """
        current = self.corememory.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            current.update(value)
            self.corememory.set(key, current)
        else:
            # Either no entry yet or not a dict → replace
            self.corememory.set(key, value)

    def ensure_system_prompt(
        self, agent_name: str, prompt_manager: PromptManager, prompt_path: str
    ) -> None:
        """
        Ensures the system prompt is at the start of the agent's history.
        Should be called after authentication or context update.
        """
        history = self.histories.setdefault(agent_name, [])
        prompt = prompt_manager.get_prompt(
            prompt_path,
        )
        if not history or history[0].get("role") != "system":
            history.insert(0, {"role": "system", "content": prompt})
        elif history[0].get("content") != prompt:
            history[0]["content"] = prompt

    def get_value_from_corememory(self, key: str, default: Any = None) -> Any:
        """
        Get a value from core memory.
        """
        return self.corememory.get(key, default)

    def set_corememory(self, key: str, value: Any) -> None:
        """
        Set a value in core memory.
        """
        self.corememory.set(key, value)

    def update_corememory(self, key: str, value: Any) -> None:
        """
        Update a value in core memory.
        """
        self.corememory.set(key, value)

    # TODO: REVIEW--- MESSAGE QUEUE MANAGEMENT -------------------------------------
    async def enqueue_message(
        self,
        response_text: str,
        use_ssml: bool = False,
        voice_name: Optional[str] = None,
        locale: str = "en-US",
        participants: Optional[List[Any]] = None,
        max_retries: int = 5,
        initial_backoff: float = 0.5,
        transcription_resume_delay: float = 1.0,
    ) -> None:
        """Add a message to the queue for sequential playback."""
        message_data = {
            "response_text": response_text,
            "use_ssml": use_ssml,
            "voice_name": voice_name,
            "locale": locale,
            "participants": participants,
            "max_retries": max_retries,
            "initial_backoff": initial_backoff,
            "transcription_resume_delay": transcription_resume_delay,
            "timestamp": asyncio.get_event_loop().time(),
        }
        await self.message_queue.enqueue(message_data)

    async def get_next_message(self) -> Optional[Dict[str, Any]]:
        """Get the next message from the queue."""
        return await self.message_queue.dequeue()

    async def clear_queue(self) -> None:
        """Clear all queued messages."""
        await self.message_queue.clear()

    def get_queue_size(self) -> int:
        """Get the current queue size."""
        return self.message_queue.size()

    async def set_queue_processing_status(self, is_processing: bool) -> None:
        """Set the queue processing status."""
        await self.message_queue.set_processing(is_processing)

    def is_queue_processing(self) -> bool:
        """Check if the queue is currently being processed."""
        return self.message_queue.is_processing_queue()

    async def set_media_cancelled(self, cancelled: bool) -> None:
        """Set the media cancellation flag."""
        await self.message_queue.set_media_cancelled(cancelled)

    def is_media_cancelled(self) -> bool:
        """Check if media was cancelled due to interrupt."""
        return self.message_queue.is_media_cancelled()

    async def reset_queue_on_interrupt(self) -> None:
        """Reset the queue state when an interrupt is detected."""
        await self.message_queue.reset_on_interrupt()

    # --- LIVE DATA REFRESH -------------------------------------------
    async def refresh_from_redis_async(self, redis_mgr: AzureRedisManager) -> bool:
        """Refresh the current session with live data from Redis."""
        key = self.build_redis_key(self.session_id)
        try:
            data = await redis_mgr.get_session_data_async(key)
            if not data:
                logger.warning(f"No live data found for session {self.session_id}")
                return False
            if "chat_history" in data:
                new_histories = json.loads(data["chat_history"])
                if new_histories != self.histories:
                    logger.info(f"Refreshed histories for session {self.session_id}")
                    self.histories = new_histories
            if "corememory" in data:
                new_context = json.loads(data["corememory"])
                self.context = new_context
            logger.info(
                f"Successfully refreshed live data for session {self.session_id}"
            )
            return True
        except Exception as e:
            logger.error(
                f"Failed to refresh live data for session {self.session_id}: {e}"
            )
            return False

    def refresh_from_redis(self, redis_mgr: AzureRedisManager) -> bool:
        """Synchronous version of refresh_from_redis_async."""
        key = self.build_redis_key(self.session_id)
        try:
            data = redis_mgr.get_session_data(key)
            if not data:
                logger.warning(f"No live data found for session {self.session_id}")
                return False
            if "chat_history" in data:
                new_histories = json.loads(data["chat_history"])
                if new_histories != self.histories:
                    logger.info(f"Refreshed histories for session {self.session_id}")
                    self.histories = new_histories
            if "corememory" in data:
                new_context = json.loads(data["corememory"])
                self.context = new_context
            logger.info(
                f"Successfully refreshed live data for session {self.session_id}"
            )
            return True
        except Exception as e:
            logger.error(
                f"Failed to refresh live data for session {self.session_id}: {e}"
            )
            return False

    async def get_live_context_value(
        self, redis_mgr: AzureRedisManager, key: str, default: Any = None
    ) -> Any:
        """Get a specific context value from live Redis data without fully refreshing the session."""
        try:
            redis_key = self.build_redis_key(self.session_id)
            data = await redis_mgr.get_session_data_async(redis_key)
            if data and "corememory" in data:
                context = json.loads(data["corememory"])
                return context.get(key, default)
            return default
        except Exception as e:
            logger.error(
                f"Failed to get live context value '{key}' for session {self.session_id}: {e}"
            )
            return default

    async def set_live_context_value(
        self, redis_mgr: AzureRedisManager, key: str, value: Any
    ) -> bool:
        """Set a specific context value in both local state and Redis."""
        try:
            self.context[key] = value
            await self.persist_to_redis_async(redis_mgr)
            logger.debug(
                f"Set live context value '{key}' = {value} for session {self.session_id}"
            )
            return True
        except Exception as e:
            logger.error(
                f"Failed to set live context value '{key}' for session {self.session_id}: {e}"
            )
            return False

    def enable_auto_refresh(
        self, redis_mgr: AzureRedisManager, interval_seconds: float = 30.0
    ) -> None:
        """Enable automatic refresh of data from Redis at specified intervals."""
        self._redis_manager = redis_mgr
        self.auto_refresh_interval = interval_seconds
        if self._refresh_task and not self._refresh_task.done():
            self._refresh_task.cancel()
        self._refresh_task = asyncio.create_task(self._auto_refresh_loop())
        logger.info(
            f"Enabled auto-refresh every {interval_seconds}s for session {self.session_id}"
        )

    def disable_auto_refresh(self) -> None:
        """Disable automatic refresh."""
        if self._refresh_task and not self._refresh_task.done():
            self._refresh_task.cancel()
        self._refresh_task = None
        self._redis_manager = None
        logger.info(f"Disabled auto-refresh for session {self.session_id}")

    async def _auto_refresh_loop(self) -> None:
        """Internal method to handle automatic refresh loop."""
        while self.auto_refresh_interval and self._redis_manager:
            try:
                await asyncio.sleep(self.auto_refresh_interval)
                await self.refresh_from_redis_async(self._redis_manager)
                self.last_refresh_time = asyncio.get_event_loop().time()
            except asyncio.CancelledError:
                logger.info(f"Auto-refresh cancelled for session {self.session_id}")
                break
            except Exception as e:
                logger.error(f"Auto-refresh error for session {self.session_id}: {e}")

    async def check_for_changes(self, redis_mgr: AzureRedisManager) -> Dict[str, bool]:
        """Check what has changed in Redis compared to local state."""
        changes = {"corememory": False, "chat_history": False, "queue": False}
        try:
            key = self.build_redis_key(self.session_id)
            data = await redis_mgr.get_session_data_async(key)
            if not data:
                return changes
            if "corememory" in data:
                remote_context = json.loads(data["corememory"])
                local_context_clean = {
                    k: v for k, v in self.context.items() if k != "message_queue"
                }
                remote_context_clean = {
                    k: v for k, v in remote_context.items() if k != "message_queue"
                }
                changes["corememory"] = local_context_clean != remote_context_clean
                if "message_queue" in remote_context:
                    remote_queue = remote_context["message_queue"]
                    local_queue = list(self.message_queue.queue)
                    changes["queue"] = local_queue != remote_queue
            if "chat_history" in data:
                remote_histories = json.loads(data["chat_history"])
                changes["chat_history"] = self.histories != remote_histories
        except Exception as e:
            logger.error(
                f"Error checking for changes in session {self.session_id}: {e}"
            )
        return changes

    async def selective_refresh(
        self,
        redis_mgr: AzureRedisManager,
        refresh_context: bool = True,
        refresh_histories: bool = True,
        refresh_queue: bool = False,
    ) -> Dict[str, bool]:
        """Selectively refresh only specified parts of the session data."""
        updated = {"corememory": False, "chat_history": False, "queue": False}
        try:
            key = self.build_redis_key(self.session_id)
            data = await redis_mgr.get_session_data_async(key)
            if not data:
                return updated
            if refresh_context and "corememory" in data:
                new_context = json.loads(data["corememory"])
                if not refresh_queue:
                    new_context.pop("message_queue", None)
                self.context.update(new_context)
                updated["corememory"] = True
                logger.debug(f"Updated context for session {self.session_id}")
            if refresh_histories and "chat_history" in data:
                self.histories = json.loads(data["chat_history"])
                updated["chat_history"] = True
                logger.debug(f"Updated histories for session {self.session_id}")
            if refresh_queue and "corememory" in data:
                context = json.loads(data["corememory"])
                if "message_queue" in context:
                    async with self.message_queue.lock:
                        self.message_queue.queue = deque(context["message_queue"])
                        updated["queue"] = True
                        logger.debug(
                            f"Updated message queue for session {self.session_id}"
                        )
        except Exception as e:
            logger.error(
                f"Error in selective refresh for session {self.session_id}: {e}"
            )
        return updated
