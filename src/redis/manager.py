import os
import time
import threading
import redis
import asyncio
from typing import Optional, Dict, Any, List
from redis.exceptions import AuthenticationError
from utils.ml_logging import get_logger
from azure.identity import DefaultAzureCredential

try:
    import redis.asyncio as aioredis
    ASYNC_REDIS_AVAILABLE = True
except ImportError:
    ASYNC_REDIS_AVAILABLE = False

class AzureRedisManager:
    """
    AzureRedisManager provides a simplified interface to connect, store,
    retrieve, and manage session data using Azure Cache for Redis.
    """
    @property
    def is_connected(self) -> bool:
        """Check if Redis connection is healthy."""
        try:
            return self.ping()
        except Exception as e:
            self.logger.error("Redis connection check failed: %s", e)
            return False
    def __init__(
        self,
        host: Optional[str] = None,
        access_key: Optional[str] = None,
        port: Optional[int] = None,
        db: int = 0,
        ssl: bool = True,
        credential: Optional[object] = None,  # For DefaultAzureCredential
        user_name: Optional[str] = None,
        scope: Optional[str] = None,
    ):
        """
        Initialize the Redis connection.

        Args:
            host (str, optional): The Redis host name. If not provided, uses REDIS_HOST env variable.
            access_key (str, optional): The Redis access key. If not provided, uses DefaultAzureCredential.
            port (int, optional): Redis port, default is 6380.
            db (int): Redis database index.
            ssl (bool): Use SSL for the connection.
        """
        self.logger = get_logger()
        self.host = host or os.getenv("REDIS_HOST")
        self.access_key = access_key or os.getenv("REDIS_ACCESS_KEY")
        self.port = port if isinstance(port, int) else int(os.getenv("REDIS_PORT", port))
        self.db = db
        self.ssl = ssl

        if not self.host:
            raise ValueError("Redis host must be provided either as argument or environment variable.")
        if ":" in self.host:
            host_parts = self.host.rsplit(":", 1)
            if host_parts[1].isdigit():
                self.host = host_parts[0]
                self.port = int(host_parts[1])

        # AAD credential details
        self.credential = credential or DefaultAzureCredential()
        self.scope      = scope or os.getenv("REDIS_SCOPE") or "https://redis.azure.com/.default"
        self.user_name  = user_name or os.getenv("REDIS_USER_NAME") or "user"

        # Build initial client and, if using AAD, start a refresh thread
        self._create_client()
        if not self.access_key:
            t = threading.Thread(target=self._refresh_loop, daemon=True)
            t.start()

    def _create_client(self):
        """(Re)create self.redis_client and record expiry for AAD."""
        if self.access_key:
            # static key-based auth
            self.redis_client = redis.Redis(
                host=self.host,
                port=self.port,
                db=self.db,
                password=self.access_key,
                ssl=self.ssl,
                decode_responses=True,
            )
            self.logger.info("Azure Redis connection initialized with access key.")
        else:
            # get fresh AAD token
            token = self.credential.get_token(self.scope)
            self.token_expiry = token.expires_on
            self.redis_client = redis.Redis(
                host=self.host,
                port=self.port,
                db=self.db,
                username=self.user_name,
                password=token.token,
                ssl=self.ssl,
                decode_responses=True,
            )
            self.logger.info("Azure Redis connection initialized with AAD token (expires at %s).", self.token_expiry)

    def _refresh_loop(self):
        """Background thread: sleep until just before expiry, then refresh token."""
        while True:
            now = int(time.time())
            # sleep until 60s before expiry
            wait = max(self.token_expiry - now - 60, 1)
            time.sleep(wait)
            try:
                self.logger.debug("Refreshing Azure Redis AAD token in background...")
                self._create_client()
            except Exception as e:
                self.logger.error("Failed to refresh Redis token: %s", e)
                # retry sooner if something goes wrong
                time.sleep(5)

    async def ping(self) -> bool:
        """Check Redis connectivity."""
        try:
            return self.redis_client.ping()
        except AuthenticationError:
            # token might have expired early: rebuild & retry once
            self.logger.info("Redis auth error on ping, refreshing token")
            self._create_client()
            return self.redis_client.ping()

    def set_value(self, key: str, value: str) -> bool:
        """Set a string value in Redis."""
        return self.redis_client.set(key, value)

    def get_value(self, key: str) -> Optional[str]:
        """Get a string value from Redis."""
        value = self.redis_client.get(key)
        return value.decode() if isinstance(value, bytes) else value

    def store_session_data(self, session_id: str, data: Dict[str, Any]) -> bool:
        """Store session data using a Redis hash."""
        return bool(self.redis_client.hset(session_id, mapping=data))

    def get_session_data(self, session_id: str) -> Dict[str, str]:
        """Retrieve all session data for a given session ID."""
        raw = self.redis_client.hgetall(session_id)
        return dict(raw)

    def update_session_field(self, session_id: str, field: str, value: str) -> bool:
        """Update a single field in the session hash."""
        return bool(self.redis_client.hset(session_id, field, value))

    def delete_session(self, session_id: str) -> int:
        """Delete a session from Redis."""
        return self.redis_client.delete(session_id)

    def list_connected_clients(self) -> List[Dict[str, str]]:
        """List currently connected clients."""
        return self.redis_client.client_list()

    # ============================================================================
    # ASYNC METHODS - Use these in async contexts to avoid blocking the event loop
    # ============================================================================

    async def store_session_data_async(self, session_id: str, data: Dict[str, Any]) -> bool:
        """Async version of store_session_data using thread pool executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.store_session_data, session_id, data)

    async def get_session_data_async(self, session_id: str) -> Dict[str, str]:
        """Async version of get_session_data using thread pool executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.get_session_data, session_id)

    async def update_session_field_async(self, session_id: str, field: str, value: str) -> bool:
        """Async version of update_session_field using thread pool executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.update_session_field, session_id, field, value)

    async def delete_session_async(self, session_id: str) -> int:
        """Async version of delete_session using thread pool executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.delete_session, session_id)

    async def get_value_async(self, key: str) -> Optional[str]:
        """Async version of get_value using thread pool executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.get_value, key)

    async def set_value_async(self, key: str, value: str, ttl_seconds: Optional[int] = None) -> bool:
        """Async version of set_value using thread pool executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.set_value, key, value, ttl_seconds)