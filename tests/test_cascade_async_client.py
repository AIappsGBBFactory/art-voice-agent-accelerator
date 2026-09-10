"""Application-owned AOAI clients; no credential or network operations."""

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import AsyncAzureOpenAI
from src.aoai.client_manager import AoaiClientManager


@pytest.mark.asyncio
async def test_manager_caches_and_closes_real_async_http_transport():
    async def respond(request):
        return httpx.Response(
            200,
            json={
                "id": "test",
                "object": "chat.completion",
                "created": 1,
                "model": "test",
                "choices": [],
            },
        )

    transport = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    client = AsyncAzureOpenAI(
        api_key="test",
        azure_endpoint="https://test.openai.azure.com",
        api_version="2025-01-01-preview",
        http_client=transport,
    )
    created = []

    def factory():
        created.append(client)
        return client

    sync_client = object()
    manager = AoaiClientManager(initial_client=sync_client, async_factory=factory)
    clients = await asyncio.gather(*(manager.get_async_client() for _ in range(5)))
    assert all(instance is client for instance in clients)
    assert created == [client]
    await client.chat.completions.create(model="test", messages=[])
    assert await manager.get_client() is sync_client
    await manager.aclose()
    await manager.aclose()
    assert transport.is_closed
    with pytest.raises(RuntimeError, match="closed"):
        await manager.get_async_client()


@pytest.mark.asyncio
async def test_async_factory_keeps_existing_key_auth_policy():
    # conftest replaces src.aoai.client for unrelated legacy tests. Load the
    # production factory separately rather than accidentally testing that stub.
    path = Path(__file__).parents[1] / "src/aoai/client.py"
    spec = importlib.util.spec_from_file_location("cascade_client_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    client = module.create_async_azure_openai_client(
        azure_endpoint="https://test.openai.azure.com", azure_api_key="test"
    )
    try:
        assert isinstance(client, AsyncAzureOpenAI)
        assert client.api_key == "test"
    finally:
        await client.close()
    assert client.is_closed()


@pytest.mark.asyncio
async def test_lifecycle_step_closes_borrowed_async_client():
    from apps.artagent.backend.lifecycle.steps import register_aoai_step

    steps = []

    class Lifecycle:
        def add_step(self, name, start, stop):
            steps.append((start, stop))

    app = SimpleNamespace(state=SimpleNamespace())
    register_aoai_step(Lifecycle(), app)
    start, stop = steps[0]
    await start()
    client = SimpleNamespace(close=AsyncMock())
    app.state.aoai_client_manager._async_factory = lambda: client
    assert await app.state.aoai_client_manager.get_async_client() is client
    await stop()
    client.close.assert_awaited_once()
