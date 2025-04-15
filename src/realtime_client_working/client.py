# ⚡ streamlined to match your working style
import asyncio
import json
import logging
import traceback
import yaml
from datetime import datetime
from typing import Dict, List, Optional, Callable, Awaitable, Any

import backoff

from src.realtime_client.api import RealtimeAPI
from src.realtime_client.conversation import RealtimeConversation
from src.realtime_client.event_handler import RealtimeEventHandler
from src.realtime_client.utils import array_buffer_to_base64

logger = logging.getLogger(__name__)
MAX_BUFFER_SIZE = 5 * 1024 * 1024  # 5MB


class RealtimeClient(RealtimeEventHandler):
    def dispatch(self, event_name: str, event_data: dict) -> None:
        logger.info(f"Dispatching event: {event_name} with data: {event_data}")

    def __init__(self, system_prompt: str, session_config_path: Optional[str] = None) -> None:
        super().__init__()
        self.system_prompt = system_prompt
        self.realtime = RealtimeAPI()
        self.conversation = RealtimeConversation()
        self.session_created = False

        self.default_session_config = {
            "modalities": ["text", "audio"],
            "instructions": system_prompt,
            "voice": "ballad",
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
            "input_audio_transcription": {"model": "whisper-1"},
            "turn_detection": {
                "type": "server_vad",
                "threshold": 0.5,
                "prefix_padding_ms": 300,
                "silence_duration_ms": 200,
                "create_response": True,
            },
            "tools": [],
            "tool_choice": "auto",
            "temperature": 1.0,
            "max_response_output_tokens": 4096,
        }

        self.session_config: dict = {}
        self.tools: Dict[str, dict] = {}
        self.input_audio_buffer: bytearray = bytearray()

        self._reset_config()
        if session_config_path:
            self._load_session_config_from_yaml(session_config_path)
        self._add_api_event_handlers()

    def _reset_config(self) -> None:
        self.session_config = self.default_session_config.copy()
        self.tools = {}
        self.input_audio_buffer = bytearray()

    def _load_session_config_from_yaml(self, path: str) -> None:
        try:
            with open(path, 'r') as f:
                config = yaml.safe_load(f)
                if isinstance(config, dict):
                    logger.info(f"Loaded session config from {path}")
                    merged = self.default_session_config.copy()
                    merged.update(config)
                    if "turn_detection" in config:
                        merged_turn = self.default_session_config["turn_detection"].copy()
                        merged_turn.update(config["turn_detection"])
                        merged["turn_detection"] = merged_turn
                    self.session_config = merged
        except Exception as e:
            logger.error(f"Error loading session config: {e}")

    def _add_api_event_handlers(self) -> None:
        self.realtime.on("client.*", self._log_event)
        self.realtime.on("server.*", self._log_event)
        self.realtime.on("server.response.created", self._process_event)
        self.realtime.on("server.response.output_item.added", self._process_event)
        self.realtime.on("server.response.content_part.added", self._process_event)
        self.realtime.on("server.input_audio_buffer.speech_started", self._on_speech_started)
        self.realtime.on("server.input_audio_buffer.speech_stopped", self._on_speech_stopped)
        self.realtime.on("server.conversation.item.created", self._on_item_created)
        self.realtime.on("server.response.audio_transcript.delta", self._process_event)
        self.realtime.on("server.response.audio.delta", self._process_event)
        self.realtime.on("server.response.text.delta", self._process_event)
        self.realtime.on("server.response.function_call_arguments.delta", self._process_event)
        self.realtime.on("server.response.output_item.done", self._on_output_item_done)

    def _log_event(self, event: dict) -> None:
        self.dispatch("realtime.event", {
            "time": datetime.utcnow().isoformat(),
            "source": "client" if event["type"].startswith("client.") else "server",
            "event": event,
        })

    def _process_event(self, event: dict, *args) -> Optional[tuple]:
        item, delta = self.conversation.process_event(event, *args)
        if event["type"] == "conversation.item.input_audio_transcription.completed":
            self.dispatch("conversation.item.input_audio_transcription.completed", {"item": item, "delta": delta})
        if item:
            self.dispatch("conversation.updated", {"item": item, "delta": delta})
        return item, delta

    def _on_speech_started(self, event: dict) -> None:
        self._process_event(event)
        self.dispatch("conversation.interrupted", event)

    def _on_speech_stopped(self, event: dict) -> None:
        self._process_event(event, self.input_audio_buffer)

    def _on_item_created(self, event: dict) -> None:
        item, delta = self._process_event(event)
        self.dispatch("conversation.item.appended", {"item": item})
        if item and item.get("status") == "completed":
            self.dispatch("conversation.item.completed", {"item": item})

    async def _on_output_item_done(self, event: dict) -> None:
        item, delta = self._process_event(event)
        if item and item.get("status") == "completed":
            self.dispatch("conversation.item.completed", {"item": item})
        if item and item.get("formatted", {}).get("tool"):
            await self._call_tool(item["formatted"]["tool"])

    async def _call_tool(self, tool: dict) -> None:
        try:
            json_arguments = json.loads(tool["arguments"])
            tool_config = self.tools.get(tool["name"])
            if not tool_config:
                raise Exception(f"Tool {tool['name']} not found")
            result = await tool_config["handler"](**json_arguments)
            output = {"output": json.dumps(result)}
        except Exception as e:
            logger.error(traceback.format_exc())
            output = {"error": str(e)}
        await self.safe_send("conversation.item.create", {
            "item": {"type": "function_call_output", "call_id": tool["call_id"], **output}
        })
        await self.create_response()

    def is_connected(self) -> bool:
        return self.realtime.is_connected()

    async def reset(self) -> bool:
        await self.disconnect()
        self.realtime.clear_event_handlers()
        self._reset_config()
        self._add_api_event_handlers()
        return True

    async def connect(self) -> bool:
        await self.realtime.connect()
        await self.update_session()
        return True
    
    async def add_tool(self, definition: dict, handler: Callable[..., Awaitable[dict]]) -> dict:
        """
        Register a new tool that the model can call.
        """
        if not definition.get("name"):
            raise Exception("Tool definition must have a 'name'.")
        name = definition["name"]
        if name in self.tools:
            raise Exception(f"Tool '{name}' already exists.")
        if not callable(handler):
            raise Exception("Tool handler must be callable.")
        self.tools[name] = {"definition": definition, "handler": handler}
        await self.update_session()
        return self.tools[name]

    def remove_tool(self, name: str) -> bool:
        """
        Remove a previously registered tool.
        """
        if name not in self.tools:
            raise Exception(f"Tool '{name}' does not exist.")
        del self.tools[name]
        return True

    async def disconnect(self) -> None:
        if self.realtime.is_connected():
            await self.realtime.disconnect()
        self.conversation.clear()

    async def update_session(self, **kwargs) -> bool:
        self.session_config.update(kwargs)
        tool_defs = [{**tool["definition"], "type": "function"} for tool in self.tools.values()]
        session = {**self.session_config, "tools": tool_defs}
        if self.realtime.is_connected():
            await self.safe_send("session.update", {"session": session})
        return True

    @backoff.on_exception(backoff.expo, Exception, max_tries=3)
    async def safe_send(self, event_name: str, data: Optional[dict] = None) -> None:
        await self.realtime.send(event_name, data)

    async def create_response(self) -> bool:
        if not self.get_turn_detection_type() and len(self.input_audio_buffer) > 0:
            await self.safe_send("input_audio_buffer.commit")
            self.conversation.queue_input_audio(self.input_audio_buffer)
            self.input_audio_buffer.clear()
        await self.safe_send("response.create")
        return True

    def get_turn_detection_type(self) -> Optional[str]:
        return self.session_config.get("turn_detection", {}).get("type")

    async def append_input_audio(self, array_buffer: bytes) -> bool:
        if len(array_buffer) > 0:
            await self.safe_send("input_audio_buffer.append", {
                "audio": array_buffer_to_base64(array_buffer),
            })
            self.input_audio_buffer.extend(array_buffer)
        return True
