import asyncio
import json
import uuid
from collections import deque
from statistics import mean
from typing import Any, Dict, List, Optional

from rtagents.RTInsuranceAgent.backend.agents.prompt_store.prompt_manager import (
    PromptManager,
)

from src.redis.manager import AzureRedisManager
from utils.ml_logging import get_logger

logger = get_logger("src.stateful.state_managment")


class MemoManager:
    def __init__(
        self,
        auth: bool = False,
        session_id: Optional[str] = None,
        active_agent: str = None,
        auto_refresh_interval: Optional[float] = None,  # seconds
    ) -> None:
        self.session_id: str = session_id or str(uuid.uuid4())[:8]
        self.histories: Dict[str, List[Dict[str, Any]]] = {}
        self.context: Dict[str, Any] = {
            "authenticated": auth,
            "active_agent": active_agent,
        }  # Message queue for sequential TTS playback
        self.message_queue: deque = deque()
        self.queue_lock = asyncio.Lock()
        self.is_processing_queue = False
        self.media_cancelled = (
            False  # Flag to indicate if media was cancelled due to interrupt
        )

        # Auto-refresh configuration
        self.auto_refresh_interval = auto_refresh_interval
        self.last_refresh_time = 0
        self._refresh_task: Optional[asyncio.Task] = None
        self._redis_manager: Optional[AzureRedisManager] = None

    @staticmethod
    def build_redis_key(session_id: str) -> str:
        return f"session:{session_id}"

    def to_redis_dict(self) -> Dict[str, str]:
        return {
            "histories": json.dumps(self.histories, ensure_ascii=False),
            "context": json.dumps(self.context, ensure_ascii=False),
        }

    @classmethod
    def from_redis(cls, session_id: str, redis_mgr: AzureRedisManager) -> "MemoManager":
        key = cls.build_redis_key(session_id)
        data = redis_mgr.get_session_data(key)
        cm = cls(session_id=session_id)
        if "histories" in data:
            cm.histories = json.loads(data["histories"])
        if "context" in data:
            cm.context = json.loads(data["context"])
        logger.info(
            f"Restored session {session_id}: "
            f"{sum(len(h) for h in cm.histories.values())} msgs total, ctx keys={list(cm.context.keys())}"
        )
        return cm

    def persist_to_redis(
        self, redis_mgr: AzureRedisManager, ttl_seconds: Optional[int] = None
    ) -> None:
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
            # Run expire in executor to avoid blocking
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, redis_mgr.redis_client.expire, key, ttl_seconds
            )
        logger.info(
            f"Persisted session {self.session_id} async – "
            f"histories per agent: {[f'{a}: {len(h)}' for a, h in self.histories.items()]}, ctx_keys={list(self.context.keys())}"
        )

    # --- SLOTS & TOOL OUTPUTS -----------------------------------------
    def update_slots(self, slots: dict) -> None:
        """Merge new slot values into persistent context['slots']."""
        if not slots:
            return
        self.context.setdefault("slots", {}).update(slots)
        logger.debug(f"Updated slots: {slots}")

    def get_slot(self, slot_name: str, default: Any = None) -> Any:
        """Get a slot value (from context)."""
        return self.context.get("slots", {}).get(slot_name, default)

    def persist_tool_output(self, tool_name: str, result: dict) -> None:
        """Store last result for each backend tool in context['tool_outputs']."""
        if not tool_name or not result:
            return
        self.context.setdefault("tool_outputs", {})[tool_name] = result
        logger.debug(f"Persisted tool output for '{tool_name}': {result}")

    def get_tool_output(self, tool_name: str, default: Any = None) -> Any:
        return self.context.get("tool_outputs", {}).get(tool_name, default)

    # --- LATENCY ------------------------------------------------------

    _LAT_KEY = "latency_roundtrip"

    def _latency_bucket(self) -> Dict[str, List[Dict[str, float]]]:
        return self.context.setdefault(self._LAT_KEY, {})

    def note_latency(self, stage: str, start_t: float, end_t: float) -> None:
        self._latency_bucket().setdefault(stage, []).append(
            {"start": start_t, "end": end_t, "dur": end_t - start_t}
        )

    def latency_summary(self) -> Dict[str, Dict[str, float]]:
        out: Dict[str, Dict[str, float]] = {}
        for stage, samples in self._latency_bucket().items():
            durations = [s["dur"] for s in samples]
            out[stage] = {
                "count": len(durations),
                "avg": mean(durations) if durations else 0.0,
                "min": min(durations) if durations else 0.0,
                "max": max(durations) if durations else 0.0,
            }
        return out

    # --- HISTORY ------------------------------------------------------

    def full_history(self) -> List[Dict[str, Any]]:
        """Returns a flat list of all messages across all agents, sorted in session order."""
        all_msgs = []
        for agent_name, turns in self.histories.items():
            for msg in turns:
                msg_copy = dict(msg)
                msg_copy["agent"] = agent_name
                all_msgs.append(msg_copy)
        # Optionally sort by insertion order if you store timestamps.
        return all_msgs

    def append_to_history(self, agent_name: str, role: str, content: str) -> None:
        history = self.histories.setdefault(agent_name, [])
        history.append({"role": role, "content": content})

    def get_history(self, agent_name: str) -> List[Dict[str, Any]]:
        return self.histories.setdefault(agent_name, [])

    def clear_history(self, agent_name: str) -> None:
        self.histories[agent_name] = []

    # --- PROMPT INJECTION ---------------------------------------------

    def get_context(self, key: str, default: Any = None) -> Any:
        return self.context.get(key, default)

    def update_context(self, key: str, value: Any) -> None:
        self.context[key] = value

    def _build_full_name(self) -> str:
        return f"{self.get_context('first_name', 'Alice')} {self.get_context('last_name', 'Brown')}"

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
            patient_phone_number=self.get_context("phone_number", None),
            patient_name=self._build_full_name(),
            patient_dob=self.get_context("patient_dob", None),
            patient_id=self.get_context("patient_id", None),
            slots=self.context.get("slots", {}),
            tool_outputs=self.context.get("tool_outputs", {}),
        )
        if not history or history[0].get("role") != "system":
            history.insert(0, {"role": "system", "content": prompt})
        elif history[0].get("content") != prompt:
            history[0]["content"] = prompt

    # --- MESSAGE QUEUE MANAGEMENT -------------------------------------

    async def enqueue_message(
        self,
        response_text: str,
        use_ssml: bool = False,
        voice_name: str = None,
        locale: str = "en-US",
        participants: list = None,
        max_retries: int = 5,
        initial_backoff: float = 0.5,
        transcription_resume_delay: float = 1.0,
    ) -> None:
        """Add a message to the queue for sequential playback."""
        async with self.queue_lock:
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
            self.message_queue.append(message_data)
            logger.info(
                f"📝 Enqueued message for session {self.session_id}. Queue size: {len(self.message_queue)}"
            )

    async def get_next_message(self) -> Optional[Dict[str, Any]]:
        """Get the next message from the queue."""
        async with self.queue_lock:
            if self.message_queue:
                return self.message_queue.popleft()
            return None

    async def clear_queue(self) -> None:
        """Clear all queued messages."""
        async with self.queue_lock:
            self.message_queue.clear()
            logger.info(f"🗑️ Cleared message queue for session {self.session_id}")

    def get_queue_size(self) -> int:
        """Get the current queue size."""
        return len(self.message_queue)

    async def set_queue_processing_status(self, is_processing: bool) -> None:
        """Set the queue processing status."""
        async with self.queue_lock:
            self.is_processing_queue = is_processing
            logger.debug(
                f"🔄 Queue processing status for session {self.session_id}: {is_processing}"
            )

    def is_queue_processing(self) -> bool:
        """Check if the queue is currently being processed."""
        return self.is_processing_queue

    async def set_media_cancelled(self, cancelled: bool) -> None:
        """Set the media cancellation flag."""
        async with self.queue_lock:
            self.media_cancelled = cancelled
            logger.debug(
                f"📵 Media cancellation flag for session {self.session_id}: {cancelled}"
            )

    def is_media_cancelled(self) -> bool:
        """Check if media was cancelled due to interrupt."""
        return self.media_cancelled

    async def reset_queue_on_interrupt(self) -> None:
        """
        Reset the queue state when an interrupt is detected.
        This clears the queue, stops processing, and resets cancellation flag.
        """
        async with self.queue_lock:
            queue_size_before = len(self.message_queue)
            self.message_queue.clear()
            self.is_processing_queue = False
            self.media_cancelled = False
            logger.info(
                f"🔄 Reset queue on interrupt for session {self.session_id}. Cleared {queue_size_before} messages."
            )

    # --- LIVE DATA REFRESH -------------------------------------------

    async def refresh_from_redis_async(self, redis_mgr: AzureRedisManager) -> bool:
        """
        Refresh the current session with live data from Redis.
        Returns True if data was found and loaded, False otherwise.

        This allows getting live updates during an active session.
        """
        key = self.build_redis_key(self.session_id)
        try:
            data = await redis_mgr.get_session_data_async(key)
            if not data:
                logger.warning(f"No live data found for session {self.session_id}")
                return False

            # Update histories if present
            if "histories" in data:
                new_histories = json.loads(data["histories"])
                if new_histories != self.histories:
                    logger.info(f"Refreshed histories for session {self.session_id}")
                    self.histories = new_histories

            # Update context if present
            if "context" in data:
                new_context = json.loads(data["context"])
                # Preserve queue state and locks - only update other context
                queue_state = {
                    "message_queue": getattr(self, "message_queue", deque()),
                    "queue_lock": getattr(self, "queue_lock", asyncio.Lock()),
                    "is_processing_queue": getattr(self, "is_processing_queue", False),
                }

                self.context = new_context
                # Restore queue state
                if hasattr(self, "message_queue"):
                    # Update queue from context if it exists
                    if "message_queue" in new_context:
                        self.message_queue = deque(new_context["message_queue"])
                        del self.context[
                            "message_queue"
                        ]  # Remove from context to avoid duplication

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
        """
        Synchronous version of refresh_from_redis_async.
        Use the async version when possible.
        """
        key = self.build_redis_key(self.session_id)
        try:
            data = redis_mgr.get_session_data(key)
            if not data:
                logger.warning(f"No live data found for session {self.session_id}")
                return False

            # Update histories if present
            if "histories" in data:
                new_histories = json.loads(data["histories"])
                if new_histories != self.histories:
                    logger.info(f"Refreshed histories for session {self.session_id}")
                    self.histories = new_histories

            # Update context if present (preserving queue state)
            if "context" in data:
                new_context = json.loads(data["context"])
                # Preserve current queue state
                current_queue_size = self.get_queue_size()
                current_processing = self.is_queue_processing()

                self.context = new_context

                # Restore queue state if it was active
                if hasattr(self, "message_queue") and current_queue_size > 0:
                    logger.info(
                        f"Preserving active queue state: {current_queue_size} messages"
                    )

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
        """
        Get a specific context value from live Redis data without fully refreshing the session.
        Useful for checking specific flags or values that might have been updated by other processes.
        """
        try:
            redis_key = self.build_redis_key(self.session_id)
            data = await redis_mgr.get_session_data_async(redis_key)
            if data and "context" in data:
                context = json.loads(data["context"])
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
        """
        Set a specific context value in both local state and Redis.
        This ensures the change is immediately persisted and available to other processes.
        """
        try:
            # Update local state
            self.context[key] = value

            # Persist to Redis immediately
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
    ):
        """
        Enable automatic refresh of data from Redis at specified intervals.
        Useful for long-running sessions that need to stay in sync.
        """
        self._redis_manager = redis_mgr
        self.auto_refresh_interval = interval_seconds

        if self._refresh_task and not self._refresh_task.done():
            self._refresh_task.cancel()

        self._refresh_task = asyncio.create_task(self._auto_refresh_loop())
        logger.info(
            f"Enabled auto-refresh every {interval_seconds}s for session {self.session_id}"
        )

    def disable_auto_refresh(self):
        """Disable automatic refresh."""
        if self._refresh_task and not self._refresh_task.done():
            self._refresh_task.cancel()
        self._refresh_task = None
        self._redis_manager = None
        logger.info(f"Disabled auto-refresh for session {self.session_id}")

    async def _auto_refresh_loop(self):
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
                # Continue the loop despite errors

    async def check_for_changes(self, redis_mgr: AzureRedisManager) -> Dict[str, bool]:
        """
        Check what has changed in Redis compared to local state.
        Returns a dict indicating what changed: {'context': bool, 'histories': bool, 'queue': bool}
        """
        changes = {"context": False, "histories": False, "queue": False}

        try:
            key = self.build_redis_key(self.session_id)
            data = await redis_mgr.get_session_data_async(key)

            if not data:
                return changes

            # Check context changes
            if "context" in data:
                remote_context = json.loads(data["context"])
                # Compare excluding queue-related items
                local_context_clean = {
                    k: v for k, v in self.context.items() if k not in ["message_queue"]
                }
                remote_context_clean = {
                    k: v
                    for k, v in remote_context.items()
                    if k not in ["message_queue"]
                }
                changes["context"] = local_context_clean != remote_context_clean

                # Check queue changes specifically
                if "message_queue" in remote_context:
                    remote_queue = remote_context["message_queue"]
                    local_queue = list(self.message_queue)
                    changes["queue"] = local_queue != remote_queue

            # Check history changes
            if "histories" in data:
                remote_histories = json.loads(data["histories"])
                changes["histories"] = self.histories != remote_histories

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
        """
        Selectively refresh only specified parts of the session data.
        Returns what was actually updated.
        """
        updated = {"context": False, "histories": False, "queue": False}

        try:
            key = self.build_redis_key(self.session_id)
            data = await redis_mgr.get_session_data_async(key)

            if not data:
                return updated

            if refresh_context and "context" in data:
                new_context = json.loads(data["context"])
                # Preserve queue state unless explicitly refreshing it
                if not refresh_queue and hasattr(self, "message_queue"):
                    # Remove queue from new context to preserve local queue
                    new_context.pop("message_queue", None)

                self.context.update(new_context)
                updated["context"] = True
                logger.debug(f"Updated context for session {self.session_id}")

            if refresh_histories and "histories" in data:
                self.histories = json.loads(data["histories"])
                updated["histories"] = True
                logger.debug(f"Updated histories for session {self.session_id}")

            if refresh_queue and "context" in data:
                context = json.loads(data["context"])
                if "message_queue" in context:
                    # Safely update queue
                    async with self.queue_lock:
                        self.message_queue = deque(context["message_queue"])
                        updated["queue"] = True
                        logger.debug(
                            f"Updated message queue for session {self.session_id}"
                        )

        except Exception as e:
            logger.error(
                f"Error in selective refresh for session {self.session_id}: {e}"
            )

        return updated

    # Utility to get all agent names in this session (useful for admin/debug)
    def all_agents(self) -> List[str]:
        return list(self.histories.keys())
