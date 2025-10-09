from opentelemetry import trace
from opentelemetry.trace import SpanKind
import asyncio
import os
import threading
import time
from typing import Any, Dict, List, Optional

from utils.azure_auth import get_credential

import redis
from redis.exceptions import AuthenticationError
from utils.ml_logging import get_logger

# Import Azure managed identity dependencies for AMR
try:
    from redis_entraid.cred_provider import (
        create_from_default_azure_credential,
        create_from_managed_identity,
        create_from_service_principal,
        ManagedIdentityType,
        TokenManagerConfig,
        RetryPolicy
    )
    AMR_AVAILABLE = True
except ImportError:
    AMR_AVAILABLE = False


class AzureRedisManager:
    """
    AzureRedisManager provides a simplified interface to connect, store,
    retrieve, and manage session data using Azure Cache for Redis.
    """

    @property
    async def is_connected(self) -> bool:
        """Check if Redis connection is healthy."""
        try:
            return await self.ping()
        except Exception as e:
            self.logger.error("Redis connection check failed: %s", e)
            return False

    @property
    def database(self) -> int:
        """Get the Redis database number."""
        return self.db

    def __init__(
        self,
        host: Optional[str] = None,
        access_key: Optional[str] = None,
        port: Optional[int] = None,
        db: int = 0,
        ssl: bool = True,

        use_amr: Optional[bool] = None,  # Auto-detect if not specified
    ):
        """
        Initialize the Redis connection.
        
        Args:
            host: Redis host address
            access_key: Redis access key (if using key-based auth)
            port: Redis port number
            db: Redis database number
            ssl: Whether to use SSL/TLS
            credential: Azure credential object (if using legacy AAD auth)
            user_name: Username for Redis authentication (legacy AAD only)
            scope: OAuth scope for token requests (legacy AAD only)
            use_amr: Whether to use Azure Managed Redis credentials (auto-detected if None)
            
        Environment Variables (for AMR authentication):
            AZURE_CLIENT_ID: Client ID for user-assigned managed identity or service principal
            AZURE_CLIENT_SECRET: Client secret for service principal (optional)
            AZURE_TENANT_ID: Tenant ID for service principal (required if using client secret)
            REDIS_HOST: Redis host address
            REDIS_ACCESS_KEY: Redis access key
            REDIS_PORT: Redis port number
            
        Authentication Priority:
            1. Access key (if provided)
            2. Service principal (if AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, and AZURE_TENANT_ID are set)
            3. User-assigned managed identity (if AZURE_CLIENT_ID is set)
            4. Default Azure credential (supports managed identity, Azure CLI, Visual Studio, etc.)
            5. Legacy AAD token-based authentication (fallback)
        """
        self.logger = get_logger(__name__)
        self.host = host or os.getenv("REDIS_HOST")
        self.access_key = access_key or os.getenv("REDIS_ACCESS_KEY")
        self.port = (
            port if isinstance(port, int) else int(os.getenv("REDIS_PORT", port or 6380))
        )
        self.db = db
        self.ssl = ssl
        self.tracer = trace.get_tracer(__name__)
        
        if not self.host:
            raise ValueError(
                "Redis host must be provided either as argument or environment variable."
            )
        if ":" in self.host:
            host_parts = self.host.rsplit(":", 1)
            if host_parts[1].isdigit():
                self.host = host_parts[0]
                self.port = int(host_parts[1])

        # Determine if we should use AMR credentials
        self.use_amr = use_amr
        if self.use_amr is None:
            # Auto-detect: use AMR if available and no access key provided
            self.use_amr = AMR_AVAILABLE and not self.access_key
            
        self.logger.info(f"AMR package available: {AMR_AVAILABLE}")
        self.logger.info(f"Using AMR authentication: {self.use_amr}")
        self.logger.info(f"Access key provided: {bool(self.access_key)}")
        
        # Validate AMR dependencies
        if self.use_amr and not AMR_AVAILABLE:
            raise ImportError(
                "redis-entraid package is required for Azure Managed Redis authentication. "
                "Install it with: pip install redis-entraid"
            )
            
        # Initialize Azure credentials for AMR or legacy AAD auth
        self._setup_azure_credentials()
        
        # For legacy AAD token tracking
        self._auth_expires_at = 0
        
        # Build initial client
        self._create_client()
        
        # Start refresh thread only for legacy AAD auth (not needed for AMR)
        if not self.access_key and not self.use_amr:
            t = threading.Thread(target=self._refresh_loop, daemon=True)
            t.start()

    def _setup_azure_credentials(self):
        """Setup Azure credentials based on environment and configuration."""
        if self.access_key:
            # Using access key, no credentials needed
            self.credential_provider = None
            self.scope = None
            self.user_name = None
            return
            
        if self.use_amr and AMR_AVAILABLE:
            # Use redis-entraid credential provider
            azure_client_id = os.getenv("AZURE_CLIENT_ID")
            azure_client_secret = os.getenv("AZURE_CLIENT_SECRET")
            azure_tenant_id = os.getenv("AZURE_TENANT_ID")
            
            if azure_client_id and azure_client_secret and azure_tenant_id:
                # Service principal authentication
                self.logger.info(f"Using service principal authentication with client ID: {azure_client_id}")
                self.credential_provider = create_from_service_principal(
                    azure_client_id,
                    azure_client_secret,
                    azure_tenant_id
                )
            elif azure_client_id:
                # User-assigned managed identity
                self.logger.info(f"Using user-assigned managed identity with client ID: {azure_client_id}")
                self.credential_provider = create_from_managed_identity(
                    identity_type=ManagedIdentityType.USER_ASSIGNED,
                    resource=f"https://{self.host}",
                    id_type=None,
                    id_value=azure_client_id
                )
            else:
                # Default Azure credential (supports managed identity, Azure CLI, Visual Studio, etc.)
                self.logger.info("Using default Azure credential")
                self.credential_provider = create_from_default_azure_credential(
                    scopes=("https://redis.azure.com/.default",)
                )
                
            # No need for manual token management with redis-entraid
            self.credential = None
            self.user_name = None
            
        else:
            # Legacy AAD token-based authentication
            self.logger.info("Using legacy AAD token-based authentication")
            self.credential = get_credential()
            self.user_name = os.getenv("REDIS_USER_NAME") or "user"
            self.credential_provider = None
            self.scope = os.getenv("REDIS_SCOPE") or "https://redis.azure.com/.default"

    async def initialize(self) -> None:
        """
        Async initialization method for FastAPI lifespan compatibility.

        Validates Redis connectivity and ensures proper initialization.
        This method is idempotent and can be called multiple times safely.
        """
        try:
            self.logger.info(f"Validating Redis connection to {self.host}:{self.port}")

            # Validate connection with health check
            loop = asyncio.get_event_loop()
            ping_result = await loop.run_in_executor(None, self._health_check)

            if ping_result:
                self.logger.info("✅ Redis connection validated successfully")
            else:
                raise ConnectionError("Redis health check failed")

        except Exception as e:
            self.logger.error(f"Redis initialization failed: {e}")
            raise ConnectionError(f"Failed to initialize Redis: {e}")

    def _health_check(self) -> bool:
        """
        Perform comprehensive health check on Redis connection.
        """
        try:
            # Basic connectivity test
            if not self.redis_client.ping():
                return False

            # Test basic operations
            test_key = "health_check_test"
            self.redis_client.set(test_key, "test_value", ex=5)
            result = self.redis_client.get(test_key)
            self.redis_client.delete(test_key)

            return result == "test_value"

        except Exception as e:
            self.logger.error(f"Redis health check failed: {e}")
            return False

    def _redis_span(self, name: str, op: str | None = None):
        host = (self.host or "").split(":")[0]
        return self.tracer.start_as_current_span(
            name,
            kind=SpanKind.CLIENT,
            attributes={
                "peer.service": "azure-managed-redis",
                "server.address": host,
                "server.port": self.port or 6380,
                "db.system": "redis",
                **({"db.operation": op} if op else {}),
            },
        )

    def _create_client(self):
        """(Re)create self.redis_client using appropriate authentication method."""
        common_config = {
            "host": self.host,
            "port": self.port,
            "db": self.db,
            "ssl": self.ssl,
            "decode_responses": True,
            "socket_keepalive": True,
            "health_check_interval": 30,
            "socket_connect_timeout": 5.0,
            "socket_timeout": 5.0,
            "max_connections": 200,
            "client_name": "rtagent-api",
        }
        
        if self.access_key:
            # Static key-based auth
            self.redis_client = redis.Redis(
                password=self.access_key,
                **common_config
            )
            self.logger.info("Azure Redis connection initialized with access key.")
            
        elif self.use_amr and self.credential_provider:
            # Use redis-entraid credential provider (recommended for AMR)
            self.redis_client = redis.Redis(
                credential_provider=self.credential_provider,
                **common_config
            )
            self.logger.info("Azure Redis connection initialized with AMR credential provider.")
            
        else:
            # Legacy AAD token-based auth
            token = self.credential.get_token(self.scope)
            self.token_expiry = token.expires_on
            self.redis_client = redis.Redis(
                username=self.user_name,
                password=token.token,
                **common_config
            )
            self.logger.info(
                "Azure Redis connection initialized with AAD token (expires at %s).",
                self.token_expiry,
            )

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

    def publish_event(self, stream_key: str, event_data: Dict[str, Any]) -> str:
        """Append an event to a Redis stream."""
        with self._redis_span("Redis.XADD"):
            return self.redis_client.xadd(stream_key, event_data)

    def read_events_blocking(
        self,
        stream_key: str,
        last_id: str = "$",
        block_ms: int = 30000,
        count: int = 1,
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Block and read new events from a Redis stream starting after `last_id`.
        Returns list of new events (or None on timeout).
        """
        with self._redis_span("Redis.XREAD"):
            streams = self.redis_client.xread(
                {stream_key: last_id}, block=block_ms, count=count
            )
            return streams if streams else None

    async def publish_event_async(
        self, stream_key: str, event_data: Dict[str, Any]
    ) -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self.publish_event, stream_key, event_data
        )

    async def read_events_blocking_async(
        self,
        stream_key: str,
        last_id: str = "$",
        block_ms: int = 30000,
        count: int = 1,
    ) -> Optional[List[Dict[str, Any]]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self.read_events_blocking, stream_key, last_id, block_ms, count
        )

    async def ping(self) -> bool:
        """Check Redis connectivity."""
        try:
            with self._redis_span("Redis.PING"):
                return self.redis_client.ping()
        except AuthenticationError:
            # Handle auth errors differently based on auth method
            if self.use_amr and self.credential_provider:
                # For AMR with credential provider, the provider should handle token refresh automatically
                self.logger.info("Redis auth error on ping with AMR credential provider")
                # The credential provider should handle this automatically, but we can try recreating the client
                self._create_client()
            elif not self.access_key:
                # Legacy token might have expired early: rebuild & retry once
                self.logger.info("Redis auth error on ping, refreshing token")
                self._create_client()
            else:
                # Access key auth shouldn't have auth errors, re-raise
                raise
                
            # Retry ping after potential client recreation
            with self._redis_span("Redis.PING"):
                return self.redis_client.ping()

    def set_value(
        self, key: str, value: str, ttl_seconds: Optional[int] = None
    ) -> bool:
        """Set a string value in Redis (optionally with TTL)."""
        with self._redis_span("Redis.SET"):
            if ttl_seconds is not None:
                return self.redis_client.setex(key, ttl_seconds, str(value))
            return self.redis_client.set(key, str(value))

    def get_value(self, key: str) -> Optional[str]:
        """Get a string value from Redis."""
        with self._redis_span("Redis.GET"):
            value = self.redis_client.get(key)
            return value.decode() if isinstance(value, bytes) else value

    def store_session_data(self, session_id: str, data: Dict[str, Any]) -> bool:
        """Store session data using a Redis hash."""
        with self._redis_span("Redis.HSET"):
            return bool(self.redis_client.hset(session_id, mapping=data))

    def get_session_data(self, session_id: str) -> Dict[str, str]:
        """Retrieve all session data for a given session ID."""
        with self._redis_span("Redis.HGETALL"):
            raw = self.redis_client.hgetall(session_id)
            return dict(raw)

    def update_session_field(self, session_id: str, field: str, value: str) -> bool:
        """Update a single field in the session hash."""
        with self._redis_span("Redis.HSET"):
            return bool(self.redis_client.hset(session_id, field, value))

    def delete_session(self, session_id: str) -> int:
        """Delete a session from Redis."""
        with self._redis_span("Redis.DEL"):
            return self.redis_client.delete(session_id)

    def list_connected_clients(self) -> List[Dict[str, str]]:
        """List currently connected clients."""
        with self._redis_span("Redis.CLIENTLIST"):
            return self.redis_client.client_list()

    async def store_session_data_async(
        self, session_id: str, data: Dict[str, Any]
    ) -> bool:
        """Async version using thread pool executor."""
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None, self.store_session_data, session_id, data
            )
        except asyncio.CancelledError:
            self.logger.debug(
                f"store_session_data_async cancelled for session {session_id}"
            )
            # Don't log as warning - cancellation is normal during shutdown
            raise
        except Exception as e:
            self.logger.error(
                f"Error in store_session_data_async for session {session_id}: {e}"
            )
            return False

    async def get_session_data_async(self, session_id: str) -> Dict[str, str]:
        """Async version of get_session_data using thread pool executor."""
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self.get_session_data, session_id)
        except asyncio.CancelledError:
            self.logger.debug(
                f"get_session_data_async cancelled for session {session_id}"
            )
            raise
        except Exception as e:
            self.logger.error(
                f"Error in get_session_data_async for session {session_id}: {e}"
            )
            return {}

    async def update_session_field_async(
        self, session_id: str, field: str, value: str
    ) -> bool:
        """Async version of update_session_field using thread pool executor."""
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None, self.update_session_field, session_id, field, value
            )
        except asyncio.CancelledError:
            self.logger.debug(
                f"update_session_field_async cancelled for session {session_id}"
            )
            raise
        except Exception as e:
            self.logger.error(
                f"Error in update_session_field_async for session {session_id}: {e}"
            )
            return False

    async def delete_session_async(self, session_id: str) -> int:
        """Async version of delete_session using thread pool executor."""
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self.delete_session, session_id)
        except asyncio.CancelledError:
            self.logger.debug(
                f"delete_session_async cancelled for session {session_id}"
            )
            raise
        except Exception as e:
            self.logger.error(
                f"Error in delete_session_async for session {session_id}: {e}"
            )
            return 0

    async def get_value_async(self, key: str) -> Optional[str]:
        """Async version of get_value using thread pool executor."""
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self.get_value, key)
        except asyncio.CancelledError:
            self.logger.debug(f"get_value_async cancelled for key {key}")
            raise
        except Exception as e:
            self.logger.error(f"Error in get_value_async for key {key}: {e}")
            return None

    async def set_value_async(
        self, key: str, value: str, ttl_seconds: Optional[int] = None
    ) -> bool:
        """Async version of set_value using thread pool executor."""
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None, self.set_value, key, value, ttl_seconds
            )
        except asyncio.CancelledError:
            self.logger.debug(f"set_value_async cancelled for key {key}")
            raise
        except Exception as e:
            self.logger.error(f"Error in set_value_async for key {key}: {e}")
            return False
