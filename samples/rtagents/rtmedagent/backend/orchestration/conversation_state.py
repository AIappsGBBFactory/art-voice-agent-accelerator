import json
import uuid
from statistics import mean
from typing import Any, Dict, List, Optional

from rtagents.RTMedAgent.backend.agents.prompt_store.prompt_manager import PromptManager

from src.redis.manager import AzureRedisManager
from utils.ml_logging import get_logger

logger = get_logger()


class MemoManager:
    def __init__(
        self,
        auth: bool = False,
        session_id: Optional[str] = None,
        active_agent: str = None,
    ) -> None:
        self.session_id: str = session_id or str(uuid.uuid4())[:8]
        self.histories: Dict[str, List[Dict[str, Any]]] = {}
        self.context: Dict[str, Any] = {
            "authenticated": auth,
            "active_agent": active_agent,
        }

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

    # Utility to get all agent names in this session (useful for admin/debug)
    def all_agents(self) -> List[str]:
        return list(self.histories.keys())
