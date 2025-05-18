# api.py RealtimeAPI class for WebSocket connection to Azure OpenAI Realtime API

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

import websockets

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
        self.keep_running = True

        # Important addition to wait properly
        self.session_created_future: Optional[asyncio.Future] = None

    def is_connected(self) -> bool:
        return self.ws is not None

    def log(self, *args: Any) -> None:
        logger.debug(f"[WebSocket {datetime.utcnow().isoformat()}]", *args)

    async def connect(self) -> None:
        """
        Connect to the Azure OpenAI Realtime WebSocket endpoint and wait for session.created.
        """
        if self.is_connected():
            raise Exception("Already connected, call disconnect first.")

        connection_url = (
            f"{self.url}/openai/realtime"
            f"?api-version={self.api_version}"
            f"&deployment={self.azure_deployment}"
            f"&api-key={self.api_key}"
        )

        logger.info(f"Connecting to Realtime API at {connection_url}")
        try:
            self.ws = await websockets.connect(connection_url)
            self.log(f"Connected to {self.url}")

            self.session_created_future = asyncio.get_running_loop().create_future()

            asyncio.create_task(self._receive_messages())

            logger.info("Waiting for server session confirmation...")
            await asyncio.wait_for(self.session_created_future, timeout=10.0)
            logger.info("RealtimeAPI: Session confirmed!")
        except Exception as e:
            logger.error(f"Failed to connect to RealtimeAPI: {e}")
            raise

    async def _receive_messages(self) -> None:
        """
        Listen for WebSocket messages and dispatch them.
        """
        try:
            async for message in self.ws:
                try:
                    event = json.loads(message)
                    self.log("Received:", event)

                    # Dispatch to client/server event handlers
                    self.dispatch(f"server.{event['type']}", event)
                    self.dispatch("server.*", event)

                    # Fulfill session_created_future if session.created arrives
                    if event.get("type") == "session.created":
                        if (
                            self.session_created_future
                            and not self.session_created_future.done()
                        ):
                            self.session_created_future.set_result(True)
                except json.JSONDecodeError:
                    logger.warning("Received non-JSON message, ignoring.")
                except Exception as e:
                    logger.error(f"Error processing WebSocket message: {e}")
        except websockets.ConnectionClosed as e:
            logger.warning(f"WebSocket closed: {e.code} - {e.reason}")
            await self._handle_reconnect()
        except Exception as e:
            logger.error(f"Error in WebSocket receive loop: {e}")
            await self._handle_reconnect()

    async def send(
        self, event_name: str, data: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Send an event over the WebSocket connection.
        """
        if not self.is_connected():
            raise Exception("RealtimeAPI is not connected")

        data = data or {}
        if not isinstance(data, dict):
            raise ValueError("Data must be a dictionary")

        event = {"event_id": self._generate_id("evt_"), "type": event_name, **data}

        self.dispatch(f"client.{event_name}", event)
        self.dispatch("client.*", event)

        self.log("Sent:", event)

        try:
            await self.ws.send(json.dumps(event))
        except Exception as e:
            logger.error(f"Error sending WebSocket event: {e}")
            raise

    def _generate_id(self, prefix: str) -> str:
        """
        Generate a unique event ID.
        """
        return f"{prefix}{int(datetime.utcnow().timestamp() * 1000)}"

    async def disconnect(self) -> None:
        """
        Disconnect from the WebSocket server.
        """
        self.keep_running = False
        if self.ws:
            try:
                await self.ws.close()
                self.ws = None
                self.log(f"Disconnected from {self.url}")
            except Exception as e:
                logger.error(f"Error during disconnect: {e}")
                raise

    async def _handle_reconnect(self) -> None:
        """
        Try to reconnect after disconnection.
        """
        self.ws = None
        if self.keep_running:
            logger.info("Attempting to reconnect to Azure Realtime after 3 seconds...")
            await asyncio.sleep(3)
            try:
                await self.connect()
            except Exception as e:
                logger.error(f"Reconnect attempt failed: {e}")
                await self._handle_reconnect()  # Retry again
