import asyncio
import json
from typing import Any, Dict, List

from fastapi import WebSocket

from apps.rtagent.backend.src.orchestration.orchestrator import route_turn
from src.stateful.state_managment import MemoManager
from utils.ml_logging import get_logger

logger = get_logger("handlers.transcription_handler")


class TranscriptionHandler:
    """
    Simple transcription handler for ACS WebSocket messages.
    Handles intermediate (barge-in) and final transcription processing.
    """

    def __init__(self, websocket: WebSocket, cm: MemoManager):
        self.websocket = websocket
        self.cm = cm
        # Shared singletons (safe to reference globally)
        self.redis_mgr = websocket.app.state.redis
        self.clients = None  # Will be set during first usage
        # Per-connection value (placed on websocket.state by router)
        self.call_conn = getattr(websocket.state, "call_conn", None)
        logger.info(
            f"📝 Transcription handler initialized | Session: {self.cm.session_id}"
        )

    async def _ensure_clients(self):
        """Lazy initialization of clients to avoid async call in __init__"""
        if self.clients is None:
            self.clients = (
                await self.websocket.app.state.websocket_manager.get_clients_snapshot()
            )

    async def handle_transcription_message(self, message: Dict[str, Any]) -> None:
        """
        Handle WebSocket transcription messages from ACS.

        Args:
            message: Transcription message from ACS WebSocket
        """
        try:
            # Convert message to JSON for logging and debugging
            message_json = json.loads(message)
            logger.debug(
                f"🔍 Raw transcription message: {message_json} | Session: {self.cm.session_id}"
            )
            if message_json.get("kind") != "TranscriptionData":
                return

            bot_speaking = await self.cm.get_live_context_value(
                self.redis_mgr, "bot_speaking"
            )
            td = message_json["transcriptionData"]
            text = td["text"].strip()
            words = text.split()
            status = td["resultStatus"]  # "Intermediate" or "Final"

            logger.info(
                "🎤📝 Transcription received: '%s' | Status: %s | Bot speaking: %s | Session: %s",
                text,
                status,
                bot_speaking,
                self.cm.session_id,
            )

            if status == "Intermediate":
                await self._handle_intermediate_transcription(text, bot_speaking)
            elif status == "Final":
                await self._handle_final_transcription(text)

        except Exception as e:
            logger.error(
                f"❌ Error processing transcription message: {e}", exc_info=True
            )
            # Continue processing rather than breaking the connection

    async def _handle_intermediate_transcription(
        self, text: str, bot_speaking: bool
    ) -> None:
        """Handle intermediate transcription (barge-in detection)"""
        if not bot_speaking:
            return

        logger.info(
            "🔊 Barge-in detected while bot is speaking, cancelling media: '%s' | Session: %s",
            text,
            self.cm.session_id,
        )

        # Cancel ongoing media operations
        self.call_conn.cancel_all_media_operations()
        await self.cm.reset_queue_on_interrupt()

        # Track interruption count
        interrupt_cnt = self.cm.context.get("interrupt_count", 0)
        self.cm.update_context("interrupt_count", interrupt_cnt + 1)
        await self.cm.persist_to_redis_async(self.redis_mgr)

        logger.info(
            f"📊 Interrupt count updated: {interrupt_cnt + 1} | Session: {self.cm.session_id}"
        )

    async def _handle_final_transcription(self, text: str) -> None:
        """Handle final transcription (user finished speaking)"""
        logger.info(
            f"📋 Final transcription received: '{text}' | Session: {self.cm.session_id}"
        )

        # Reset interrupt count
        self.cm.update_context("interrupt_count", 0)
        await self.cm.persist_to_redis_async(self.redis_mgr)

        # Note: broadcast_message is now handled in the orchestrator to avoid duplication
        # Route to orchestrator for AI processing (orchestrator will handle broadcasting)
        await route_turn(self.cm, text, self.websocket, is_acs=True)

        logger.info(
            f"✅ Transcription processed and routed | Session: {self.cm.session_id}"
        )

    def get_transcription_stats(self) -> Dict[str, Any]:
        """Get transcription statistics for monitoring"""
        return {
            "session_id": self.cm.session_id,
            "interrupt_count": self.cm.context.get("interrupt_count", 0),
            "total_messages": self.cm.context.get("total_transcription_messages", 0),
        }
