import uuid
import json
from typing import Any, Dict, List, Optional

from usecases.browser_RTMedAgent.backend.prompt_manager import PromptManager
from src.redis.redis_client import AzureRedisManager
from utils.ml_logging import get_logger

logger = get_logger()


class ConversationManager:
    def __init__(self, auth: bool = True, session_id: Optional[str] = None) -> None:
        self.pm: PromptManager = PromptManager()
        self.session_id: str = session_id or str(uuid.uuid4())[:8]
        self.hist: List[Dict[str, Any]] = []
        self.context: Dict[str, Any] = {"authenticated": auth}
        self.auth = auth  # Save for system prompt hydration

    @staticmethod
    def build_redis_key(session_id: str) -> str:
        return f"session:{session_id}"

    def to_redis_dict(self) -> Dict[str, str]:
        try:
            logger.debug(f"Serializing session {self.session_id} to Redis.")
            return {
                "history": json.dumps(self.hist),
                "context": json.dumps(self.context),
            }
        except Exception as e:
            logger.error(
                f"Failed to serialize session {self.session_id}: {e}", exc_info=True
            )
            raise

    @classmethod
    def from_redis(
        cls, session_id: str, redis_mgr: AzureRedisManager
    ) -> "ConversationManager":
        key = cls.build_redis_key(session_id)
        try:
            logger.info(
                f"Hydrating ConversationManager from Redis for session {session_id}"
            )
            data = redis_mgr.get_session_data(key)
            cm = cls(session_id=session_id)
            if "history" in data:
                cm.hist = json.loads(data["history"])
            if "context" in data:
                cm.context = json.loads(data["context"])
            logger.info(
                f"Restored session {session_id}: "
                f"History {len(cm.hist)} messages, Context keys: {list(cm.context.keys())}"
            )
            return cm
        except Exception as e:
            logger.error(
                f"Failed to hydrate session {session_id} from Redis: {e}", exc_info=True
            )
            return cls(session_id=session_id)

    def persist_to_redis(
        self, redis_mgr: AzureRedisManager, ttl_seconds: Optional[int] = None
    ) -> None:
        key = self.build_redis_key(self.session_id)
        try:
            redis_mgr.store_session_data(key, self.to_redis_dict())
            if ttl_seconds:
                redis_mgr.redis_client.expire(key, ttl_seconds)
            logger.info(
                f"Persisted session {self.session_id} to Redis. "
                f"History: {len(self.hist)}, Context: {self.context}"
            )
        except Exception as e:
            logger.error(
                f"Failed to persist session {self.session_id} to Redis: {e}",
                exc_info=True,
            )

    def update_context(self, key: str, value: Any) -> None:
        logger.debug(
            f"Updating context [{key}] = {value!r} for session {self.session_id}"
        )
        self.context[key] = value

    def get_context(self, key: str, default: Any = None) -> Any:
        val = self.context.get(key, default)
        logger.debug(
            f"Context get [{key}] = {val!r} (default={default!r}) for session {self.session_id}"
        )
        return val

    def append_to_history(self, role: str, content: str) -> None:
        logger.debug(
            f"Appending to history: role={role}, content={content[:80]!r}... (session {self.session_id})"
        )
        self.hist.append({"role": role, "content": content})

    def _build_full_name(self) -> str:
        first = self.get_context("first_name", "Alice")
        last = self.get_context("last_name", "Brown")
        full = f"{first} {last}"
        logger.debug(f"Built full name: {full}")
        return full

    def _generate_system_prompt(self) -> str:
        try:
            if self.get_context("authenticated", False):
                prompt = self.pm.create_prompt_system_main(
                    patient_phone_number=self.get_context("phone_number", "5552971078"),
                    patient_name=self._build_full_name(),
                    patient_dob=self.get_context("patient_dob", "1987-04-12"),
                    patient_id=self.get_context("patient_id", "P54321"),
                )
                logger.debug("Generated system prompt (authenticated).")
                return prompt
            else:
                prompt = self.pm.get_prompt("voice_agent_authentication.jinja")
                logger.debug("Generated system prompt (authenticating).")
                return prompt
        except Exception as e:
            logger.error(f"Failed to generate system prompt: {e}", exc_info=True)
            raise

    def ensure_system_prompt(self) -> None:
        """Inject system prompt only if not already present."""
        if not any(m["role"] == "system" for m in self.hist):
            try:
                self.hist.insert(
                    0, {"role": "system", "content": self._generate_system_prompt()}
                )
                logger.info("System prompt inserted at start of history.")
            except Exception as e:
                logger.error(f"Failed to ensure system prompt: {e}", exc_info=True)

    def upsert_system_prompt(self) -> None:
        """Insert or replace the system prompt (always keep only one)."""
        try:
            new_prompt = self._generate_system_prompt()
            for i, msg in enumerate(self.hist):
                if msg["role"] == "system":
                    logger.info("Replacing system prompt in history.")
                    self.hist[i]["content"] = new_prompt
                    return
            # If no system prompt found, insert at top
            self.hist.insert(0, {"role": "system", "content": new_prompt})
            logger.info("Inserted system prompt at top of history (was missing).")
        except Exception as e:
            logger.error(f"Failed to upsert system prompt: {e}", exc_info=True)
