"""
Tests for Azure Redis Manager (AMR) with different authentication methods.
"""

import asyncio
import os
import pytest
import time
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from typing import Dict, Any

# Import our module normally - the mocking will be done in individual tests
from src.redis.amr_manager import AzureRedisManager


class TestAzureRedisManager:
    """Test suite for AzureRedisManager with various authentication methods."""

    def setup_method(self):
        """Setup method run before each test."""
        # Clear environment variables
        env_vars_to_clear = [
            'REDIS_HOST', 'REDIS_ACCESS_KEY', 'REDIS_PORT', 'REDIS_USER_NAME', 'REDIS_SCOPE',
            'AZURE_CLIENT_ID', 'AZURE_CLIENT_SECRET', 'AZURE_TENANT_ID'
        ]
        for var in env_vars_to_clear:
            if var in os.environ:
                del os.environ[var]

    @patch('src.redis.amr_manager.redis.Redis')
    @patch('src.redis.amr_manager.AMR_AVAILABLE', True)
    def test_access_key_authentication(self, mock_redis_class):
        """Test Redis connection with access key authentication."""
        mock_redis_instance = Mock()
        mock_redis_class.return_value = mock_redis_instance
        
        manager = AzureRedisManager(
            host="test-redis.redis.cache.windows.net",
            access_key="test-access-key",
            port=6380
        )
        
        # Verify Redis client was created with correct parameters
        mock_redis_class.assert_called_once()
        call_kwargs = mock_redis_class.call_args[1]
        assert call_kwargs['host'] == "test-redis.redis.cache.windows.net"
        assert call_kwargs['port'] == 6380
        assert call_kwargs['password'] == "test-access-key"
        assert call_kwargs['ssl'] is True
        assert call_kwargs['client_name'] == "rtagent-api"
        
        # Verify no credential provider is used
        assert manager.credential_provider is None

    @patch('src.redis.amr_manager.AMR_AVAILABLE', True)
    @patch('src.redis.amr_manager.create_from_service_principal')
    @patch('src.redis.amr_manager.redis.Redis')
    def test_service_principal_authentication(self, mock_redis_class, mock_create_sp):
        """Test Redis connection with service principal authentication."""
        mock_redis_instance = Mock()
        mock_redis_class.return_value = mock_redis_instance
        mock_credential_provider = Mock()
        mock_create_sp.return_value = mock_credential_provider
        
        # Set environment variables for service principal
        os.environ['AZURE_CLIENT_ID'] = 'test-client-id'
        os.environ['AZURE_CLIENT_SECRET'] = 'test-client-secret'
        os.environ['AZURE_TENANT_ID'] = 'test-tenant-id'
        
        manager = AzureRedisManager(
            host="test-redis.redis.cache.windows.net",
            port=6380,
            use_amr=True
        )
        
        # Verify service principal credential provider was created
        mock_create_sp.assert_called_once_with(
            'test-client-id',
            'test-client-secret',
            'test-tenant-id'
        )
        
        # Verify Redis client was created with credential provider
        mock_redis_class.assert_called_once()
        call_kwargs = mock_redis_class.call_args[1]
        assert call_kwargs['credential_provider'] == mock_credential_provider
        assert manager.credential_provider == mock_credential_provider

    @patch('src.redis.amr_manager.AMR_AVAILABLE', True)
    @patch('src.redis.amr_manager.create_from_managed_identity')
    @patch('src.redis.amr_manager.ManagedIdentityType')
    @patch('src.redis.amr_manager.redis.Redis')
    def test_user_assigned_managed_identity(self, mock_redis_class, mock_identity_type, mock_create_mi):
        """Test Redis connection with user-assigned managed identity."""
        mock_redis_instance = Mock()
        mock_redis_class.return_value = mock_redis_instance
        mock_credential_provider = Mock()
        mock_create_mi.return_value = mock_credential_provider
        mock_identity_type.USER_ASSIGNED = 'USER_ASSIGNED'
        
        # Set environment variable for user-assigned managed identity
        os.environ['AZURE_CLIENT_ID'] = 'test-client-id'
        
        manager = AzureRedisManager(
            host="test-redis.redis.cache.windows.net",
            port=6380,
            use_amr=True
        )
        
        # Verify user-assigned managed identity credential provider was created
        mock_create_mi.assert_called_once_with(
            identity_type='USER_ASSIGNED',
            resource='https://test-redis.redis.cache.windows.net',
            id_type=None,
            id_value='test-client-id'
        )
        
        # Verify Redis client was created with credential provider
        call_kwargs = mock_redis_class.call_args[1]
        assert call_kwargs['credential_provider'] == mock_credential_provider

    @patch('src.redis.amr_manager.AMR_AVAILABLE', True)
    @patch('src.redis.amr_manager.create_from_default_azure_credential')
    @patch('src.redis.amr_manager.redis.Redis')
    def test_default_azure_credential(self, mock_redis_class, mock_create_default):
        """Test Redis connection with default Azure credential."""
        mock_redis_instance = Mock()
        mock_redis_class.return_value = mock_redis_instance
        mock_credential_provider = Mock()
        mock_create_default.return_value = mock_credential_provider
        
        manager = AzureRedisManager(
            host="test-redis.redis.cache.windows.net",
            port=6380,
            use_amr=True
        )
        
        # Verify default Azure credential provider was created
        mock_create_default.assert_called_once_with(
            scopes=('https://test-redis.redis.cache.windows.net/.default',)
        )
        
        # Verify Redis client was created with credential provider
        call_kwargs = mock_redis_class.call_args[1]
        assert call_kwargs['credential_provider'] == mock_credential_provider

    @patch('src.redis.amr_manager.AMR_AVAILABLE', False)
    def test_amr_not_available_error(self):
        """Test error when AMR is requested but redis-entraid is not available."""
        with pytest.raises(ImportError, match="redis-entraid package is required"):
            AzureRedisManager(
                host="test-redis.redis.cache.windows.net",
                port=6380,
                use_amr=True
            )

    @patch('src.redis.amr_manager.AMR_AVAILABLE', False)
    @patch('src.redis.amr_manager.get_credential')
    @patch('src.redis.amr_manager.redis.Redis')
    @patch('threading.Thread')
    def test_legacy_aad_authentication(self, mock_thread, mock_redis_class, mock_get_credential):
        """Test legacy AAD token-based authentication."""
        mock_redis_instance = Mock()
        mock_redis_class.return_value = mock_redis_instance
        mock_credential = Mock()
        mock_token = Mock()
        mock_token.token = "test-token"
        mock_token.expires_on = int(time.time()) + 3600
        mock_credential.get_token.return_value = mock_token
        mock_get_credential.return_value = mock_credential
        mock_thread_instance = Mock()
        mock_thread.return_value = mock_thread_instance
        
        manager = AzureRedisManager(
            host="test-redis.redis.cache.windows.net",
            port=6380,
            use_amr=False
        )
        
        # Verify credential was obtained
        mock_get_credential.assert_called_once()
        mock_credential.get_token.assert_called_once()
        
        # Verify Redis client was created with token
        call_kwargs = mock_redis_class.call_args[1]
        assert call_kwargs['username'] == "user"
        assert call_kwargs['password'] == "test-token"
        
        # Verify refresh thread was started
        mock_thread.assert_called_once()
        mock_thread_instance.start.assert_called_once()

    @patch('src.redis.amr_manager.redis.Redis')
    def test_host_port_parsing(self, mock_redis_class):
        """Test parsing of host:port format."""
        mock_redis_instance = Mock()
        mock_redis_class.return_value = mock_redis_instance
        
        manager = AzureRedisManager(
            host="test-redis.redis.cache.windows.net:6380",
            access_key="test-key"
        )
        
        assert manager.host == "test-redis.redis.cache.windows.net"
        assert manager.port == 6380

    def test_missing_host_error(self):
        """Test error when no host is provided."""
        with pytest.raises(ValueError, match="Redis host must be provided"):
            AzureRedisManager(access_key="test-key")

    @pytest.mark.asyncio
    @patch('src.redis.amr_manager.redis.Redis')
    async def test_ping_success(self, mock_redis_class):
        """Test successful ping operation."""
        mock_redis_instance = Mock()
        mock_redis_instance.ping.return_value = True
        mock_redis_class.return_value = mock_redis_instance
        
        manager = AzureRedisManager(
            host="test-redis.redis.cache.windows.net",
            access_key="test-key"
        )
        
        result = await manager.ping()
        assert result is True
        mock_redis_instance.ping.assert_called_once()

    @pytest.mark.asyncio
    @patch('src.redis.amr_manager.redis.Redis')
    async def test_ping_auth_error_with_amr(self, mock_redis_class):
        """Test ping with authentication error using AMR credentials."""
        from redis.exceptions import AuthenticationError
        
        mock_redis_instance = Mock()
        mock_redis_instance.ping.side_effect = [AuthenticationError("Auth failed"), True]
        mock_redis_class.return_value = mock_redis_instance
        
        with patch('src.redis.amr_manager.AMR_AVAILABLE', True):
            manager = AzureRedisManager(
                host="test-redis.redis.cache.windows.net",
                use_amr=True
            )
            manager.credential_provider = Mock()  # Mock credential provider
            
            result = await manager.ping()
            assert result is True
            assert mock_redis_instance.ping.call_count == 2

    @patch('src.redis.amr_manager.redis.Redis')
    def test_set_get_value(self, mock_redis_class):
        """Test setting and getting string values."""
        mock_redis_instance = Mock()
        mock_redis_instance.set.return_value = True
        mock_redis_instance.setex.return_value = True
        mock_redis_instance.get.return_value = "test-value"
        mock_redis_class.return_value = mock_redis_instance
        
        manager = AzureRedisManager(
            host="test-redis.redis.cache.windows.net",
            access_key="test-key"
        )
        
        # Test set without TTL
        result = manager.set_value("key1", "value1")
        assert result is True
        mock_redis_instance.set.assert_called_with("key1", "value1")
        
        # Test set with TTL
        result = manager.set_value("key2", "value2", ttl_seconds=300)
        assert result is True
        mock_redis_instance.setex.assert_called_with("key2", 300, "value2")
        
        # Test get
        result = manager.get_value("key1")
        assert result == "test-value"
        mock_redis_instance.get.assert_called_with("key1")
        assert manager.database == 0

    @pytest.mark.asyncio
    @patch('src.redis.amr_manager.redis.Redis')
    async def test_async_operations(self, mock_redis_class):
        """Test async wrapper methods."""
        mock_redis_instance = Mock()
        mock_redis_instance.set.return_value = True
        mock_redis_instance.get.return_value = "async-value"
        mock_redis_class.return_value = mock_redis_instance
        
        manager = AzureRedisManager(
            host="test-redis.redis.cache.windows.net",
            access_key="test-key"
        )
        
        # Test async set
        result = await manager.set_value_async("async-key", "async-value")
        assert result is True
        
        # Test async get
        result = await manager.get_value_async("async-key")
        assert result == "async-value"

    @patch('src.redis.amr_manager.redis.Redis')
    def test_session_data_operations(self, mock_redis_class):
        """Test session data storage and retrieval."""
        mock_redis_instance = Mock()
        mock_redis_instance.hset.return_value = 1
        mock_redis_instance.hgetall.return_value = {"field1": "value1", "field2": "value2"}
        mock_redis_instance.delete.return_value = 1
        mock_redis_class.return_value = mock_redis_instance
        
        manager = AzureRedisManager(
            host="test-redis.redis.cache.windows.net",
            access_key="test-key"
        )
        
        # Test store session data
        data = {"field1": "value1", "field2": "value2"}
        result = manager.store_session_data("session123", data)
        assert result is True
        mock_redis_instance.hset.assert_called_with("session123", mapping=data)
        
        # Test get session data
        result = manager.get_session_data("session123")
        assert result == {"field1": "value1", "field2": "value2"}
        mock_redis_instance.hgetall.assert_called_with("session123")
        
        # Test update session field
        result = manager.update_session_field("session123", "field3", "value3")
        assert result is True
        
        # Test delete session
        result = manager.delete_session("session123")
        assert result == 1
        mock_redis_instance.delete.assert_called_with("session123")

    @pytest.mark.asyncio
    @patch('src.redis.amr_manager.redis.Redis')
    async def test_session_data_async_operations(self, mock_redis_class):
        """Test async session data operations."""
        mock_redis_instance = Mock()
        mock_redis_instance.hset.return_value = 1
        mock_redis_instance.hgetall.return_value = {"async_field": "async_value"}
        mock_redis_instance.delete.return_value = 1
        mock_redis_class.return_value = mock_redis_instance
        
        manager = AzureRedisManager(
            host="test-redis.redis.cache.windows.net",
            access_key="test-key"
        )
        
        # Test async store session data
        data = {"async_field": "async_value"}
        result = await manager.store_session_data_async("async_session", data)
        assert result is True
        
        # Test async get session data
        result = await manager.get_session_data_async("async_session")
        assert result == {"async_field": "async_value"}
        
        # Test async update session field
        result = await manager.update_session_field_async("async_session", "new_field", "new_value")
        assert result is True
        
        # Test async delete session
        result = await manager.delete_session_async("async_session")
        assert result == 1

    @patch('src.redis.amr_manager.redis.Redis')
    def test_stream_operations(self, mock_redis_class):
        """Test Redis stream operations."""
        mock_redis_instance = Mock()
        mock_redis_instance.xadd.return_value = "1234567890-0"
        mock_redis_instance.xread.return_value = [("stream1", [("1234567890-0", {"field": "value"})])]
        mock_redis_class.return_value = mock_redis_instance
        
        manager = AzureRedisManager(
            host="test-redis.redis.cache.windows.net",
            access_key="test-key"
        )
        
        # Test publish event
        event_data = {"event_type": "test", "data": "value"}
        result = manager.publish_event("test_stream", event_data)
        assert result == "1234567890-0"
        mock_redis_instance.xadd.assert_called_with("test_stream", event_data)
        
        # Test read events
        result = manager.read_events_blocking("test_stream", last_id="$")
        assert result == [("stream1", [("1234567890-0", {"field": "value"})])]

    @pytest.mark.asyncio
    @patch('src.redis.amr_manager.redis.Redis')
    async def test_async_stream_operations(self, mock_redis_class):
        """Test async Redis stream operations."""
        mock_redis_instance = Mock()
        mock_redis_instance.xadd.return_value = "async-event-id"
        mock_redis_instance.xread.return_value = [("async_stream", [("async-event-id", {"async_field": "async_value"})])]
        mock_redis_class.return_value = mock_redis_instance
        
        manager = AzureRedisManager(
            host="test-redis.redis.cache.windows.net",
            access_key="test-key"
        )
        
        # Test async publish event
        event_data = {"async_event": "async_data"}
        result = await manager.publish_event_async("async_stream", event_data)
        assert result == "async-event-id"
        
        # Test async read events
        result = await manager.read_events_blocking_async("async_stream")
        assert result == [("async_stream", [("async-event-id", {"async_field": "async_value"})])]

    @pytest.mark.asyncio
    @patch('src.redis.amr_manager.redis.Redis')
    async def test_initialize_method(self, mock_redis_class):
        """Test the initialize method for FastAPI lifespan compatibility."""
        mock_redis_instance = Mock()
        mock_redis_instance.ping.return_value = True
        mock_redis_instance.set.return_value = True
        mock_redis_instance.get.return_value = "test_value"
        mock_redis_instance.delete.return_value = 1
        mock_redis_class.return_value = mock_redis_instance
        
        manager = AzureRedisManager(
            host="test-redis.redis.cache.windows.net",
            access_key="test-key"
        )
        
        # Test initialize
        await manager.initialize()
        
        # Verify health check operations were called
        assert mock_redis_instance.ping.called
        assert mock_redis_instance.set.called
        assert mock_redis_instance.get.called
        assert mock_redis_instance.delete.called
        await manager.initialize()

    @pytest.mark.asyncio
    @patch('src.redis.amr_manager.redis.Redis')
    async def test_initialize_failure(self, mock_redis_class):
        """Test initialize method failure handling."""
        mock_redis_instance = Mock()
        mock_redis_instance.ping.side_effect = Exception("Connection failed")
        mock_redis_class.return_value = mock_redis_instance
        
        manager = AzureRedisManager(
            host="test-redis.redis.cache.windows.net",
            access_key="test-key"
        )
        
        # Test initialize failure
        with pytest.raises(ConnectionError, match="Failed to initialize Redis"):
            await manager.initialize()

    @pytest.mark.asyncio
    @patch('src.redis.amr_manager.redis.Redis')
    async def test_is_connected_property(self, mock_redis_class):
        """Test is_connected property."""
        mock_redis_instance = Mock()
        mock_redis_class.return_value = mock_redis_instance
        
        manager = AzureRedisManager(
            host="test-redis.redis.cache.windows.net",
            access_key="test-key"
        )
        
        # Test successful connection check
        mock_redis_instance.ping.return_value = True
        result = await manager.is_connected
        assert result is True
        
        # Test failed connection check
        mock_redis_instance.ping.side_effect = Exception("Connection failed")
        result = await manager.is_connected
        assert result is False

    def test_environment_variable_defaults(self):
        """Test that environment variables are used as defaults."""
        # Set environment variables
        os.environ['REDIS_HOST'] = 'env-redis.cache.windows.net'
        os.environ['REDIS_ACCESS_KEY'] = 'env-access-key'
        os.environ['REDIS_PORT'] = '6379'
        
        with patch('src.redis.amr_manager.redis.Redis') as mock_redis_class:
            mock_redis_instance = Mock()
            mock_redis_class.return_value = mock_redis_instance
            
            manager = AzureRedisManager()
            
            assert manager.host == 'env-redis.cache.windows.net'
            assert manager.access_key == 'env-access-key'
            assert manager.port == 6379

    @patch('src.redis.amr_manager.AMR_AVAILABLE', True)
    def test_auto_detection_amr_vs_legacy(self):
        """Test auto-detection of AMR vs legacy authentication."""
        with patch('src.redis.amr_manager.redis.Redis'):
            # Test auto-detection with access key (should not use AMR)
            manager1 = AzureRedisManager(
                host="test-redis.redis.cache.windows.net",
                access_key="test-key"
            )
            assert manager1.use_amr is False
            
            # Test auto-detection without access key (should use AMR)
            with patch('src.redis.amr_manager.create_from_managed_identity'):
                with patch('src.redis.amr_manager.ManagedIdentityType'):
                    manager2 = AzureRedisManager(
                        host="test-redis.redis.cache.windows.net"
                    )
                    assert manager2.use_amr is True


# Integration tests that would require actual Redis instance
class TestAzureRedisManagerIntegration:
    """Integration tests that would run against a real Redis instance."""
    
    @pytest.mark.skipif(
        not os.getenv('REDIS_INTEGRATION_TESTS'),
        reason="Set REDIS_INTEGRATION_TESTS=1 to run integration tests"
    )
    async def test_real_redis_connection(self):
        """Test connection to real Redis instance (requires environment setup)."""
        host = os.getenv('REDIS_HOST')
        access_key = os.getenv('REDIS_ACCESS_KEY')
        
        if not host or not access_key:
            pytest.skip("REDIS_HOST and REDIS_ACCESS_KEY required for integration tests")
        
        manager = AzureRedisManager(host=host, access_key=access_key)
        
        # Test basic operations
        await manager.initialize()
        assert manager.is_connected
        
        # Test set/get
        test_key = "integration_test_key"
        test_value = "integration_test_value"
        
        assert manager.set_value(test_key, test_value, ttl_seconds=60)
        assert manager.get_value(test_key) == test_value
        
        # Cleanup
        manager.redis_client.delete(test_key)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])