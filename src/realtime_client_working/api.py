import os
import json
import asyncio
import logging
import websockets
from datetime import datetime
from typing import Optional, Dict, Any

from src.realtime_client.event_handler import RealtimeEventHandler

logger = logging.getLogger(__name__)


class RealtimeAPI(RealtimeEventHandler):
    """
    Handles WebSocket connection to the Azure OpenAI Realtime API.
    """

    def __init__(self) -> None:
        super().__init__()
        self.default_url = "wss://api.openai.com/v1/realtime"
        self.url = os.getenv("AZURE_OPENAI_ENDPOINT", self.default_url)
        self.api_key = os.getenv("AZURE_OPENAI_API_KEY")
        self.api_version = "2024-10-01-preview"
        self.azure_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
        self.ws: Optional[websockets.WebSocketClientProtocol] = None

    def is_connected(self) -> bool:
        return self.ws is not None

    def log(self, *args: Any) -> None:
        logger.debug(f"[WebSocket {datetime.utcnow().isoformat()}]", *args)

    async def connect(self) -> None:
        if self.is_connected():
            raise Exception("Already connected, call disconnect first.")

        connection_url = (
            f"{self.url}/openai/realtime"
            f"?api-version={self.api_version}"
            f"&deployment={self.azure_deployment}"
            f"&api-key={self.api_key}"
        )

        logger.info(f"Connecting to Realtime API at {connection_url}")
        self.ws = await websockets.connect(connection_url)
        self.log(f"Connected to {self.url}")

        asyncio.create_task(self._receive_messages())

    async def _receive_messages(self) -> None:
        try:
            async for message in self.ws:
                try:
                    event = json.loads(message)
                    self.log("Received:", event)

                    if event.get("type") == "error":
                        logger.error(f"Server Error: {event}")

                    self.dispatch(f"server.{event['type']}", event)
                    self.dispatch("server.*", event)

                except json.JSONDecodeError:
                    logger.warning("Received non-JSON message, ignoring.")
                except Exception as e:
                    logger.error(f"Error processing message: {e}")

        except websockets.ConnectionClosed as e:
            logger.warning(f"WebSocket closed: {e.code} - {e.reason}")
        except Exception as e:
            logger.error(f"Error in receive loop: {e}")

    async def send(self, event_name: str, data: Optional[Dict[str, Any]] = None) -> None:
        if not self.is_connected():
            raise Exception("RealtimeAPI is not connected.")

        event = {
            "event_id": self._generate_id("evt_"),
            "type": event_name,
            **(data or {}),
        }

        self.dispatch(f"client.{event_name}", event)
        self.dispatch("client.*", event)

        self.log("Sent:", event)

        try:
            await self.ws.send(json.dumps(event))
        except Exception as e:
            logger.error(f"Error sending event: {e}")
            raise

    def _generate_id(self, prefix: str) -> str:
        return f"{prefix}{int(datetime.utcnow().timestamp() * 1000)}"

    async def disconnect(self) -> None:
        if self.ws:
            try:
                await self.ws.close()
                self.ws = None
                self.log(f"Disconnected from {self.url}")
            except Exception as e:
                logger.error(f"Error during disconnect: {e}")
