from unittest.mock import patch

import httpx
import pytest

from agent_runtime.config import settings
from agent_runtime.model_adapter import build_model
from agent_runtime.registry import Registration


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    monkeypatch.delenv("OPENAI_FORCE_IPV4", raising=False)
    monkeypatch.setenv("ADAPTER_TEST_KEY", "offline-test-key")
    settings.cache_clear()
    yield
    settings.cache_clear()


def registration(adapter, endpoint):
    return Registration(
        provider="test",
        model="test",
        adapter=adapter,
        upstream_model="test-model",
        endpoint=endpoint,
        auth="env",
        credential_env="ADAPTER_TEST_KEY",
        tool_calling=True,
        max_output_tokens=256,
        total_tokens_limit=3000,
    )


@pytest.mark.parametrize("adapter", ["openai_responses", "openai_chat"])
@pytest.mark.parametrize("suffix", ["", "/"])
async def test_official_openai_ipv4_transport_and_lifecycle(adapter, suffix, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:8080")
    with patch(
        "agent_runtime.model_adapter.httpx.AsyncHTTPTransport", wraps=httpx.AsyncHTTPTransport
    ) as make:
        model = build_model(registration(adapter, "https://api.openai.com/v1" + suffix))
    make.assert_called_once_with(local_address="0.0.0.0", trust_env=False, retries=0)
    client = model.client._client
    assert not client.trust_env
    assert model.client.max_retries == 0
    async with model:
        async with model:
            assert not client.is_closed
        assert not client.is_closed
    assert client.is_closed


@pytest.mark.parametrize(
    "adapter,endpoint,opt_out",
    [
        ("openai_responses", "https://api.openai.com/v1", True),
        ("openai_chat", "https://backend.invalid/v1", False),
        ("openai_responses", "https://backend.invalid/v1", False),
        ("openai_chat", "http://api.openai.com/v1", False),
        ("openai_chat", "https://api.openai.com/v2", False),
        ("anthropic", "https://api.anthropic.com", False),
    ],
)
async def test_default_routing_for_opt_out_and_other_endpoints(monkeypatch, adapter, endpoint, opt_out):
    if opt_out:
        monkeypatch.setenv("OPENAI_FORCE_IPV4", "false")
    with patch(
        "agent_runtime.model_adapter.httpx.AsyncHTTPTransport", wraps=httpx.AsyncHTTPTransport
    ) as make:
        model = build_model(registration(adapter, endpoint))
    make.assert_not_called()
    async with model:
        assert model.client._client.trust_env
    assert model.client.is_closed()


async def test_official_openai_preserves_injected_mock_client():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200))
    ) as client:
        with patch("agent_runtime.model_adapter.httpx.AsyncHTTPTransport") as make:
            model = build_model(
                registration("openai_responses", "https://api.openai.com/v1"), http_client=client
            )
        make.assert_not_called()
        assert model.client._client is client
        async with model:
            assert not client.is_closed
        assert client.is_closed


async def test_ipv4_client_sends_compatible_stream_without_network(monkeypatch):
    import httpcore
    from openai import APIConnectionError

    model = build_model(registration("openai_responses", "https://api.openai.com/v1"))
    calls = []

    async def offline_send(request):
        calls.append(request)
        assert b'"model"' in b"".join([chunk async for chunk in request.stream])
        raise httpcore.ConnectError("offline transport reached")

    monkeypatch.setattr(model.client._client._transport._pool, "handle_async_request", offline_send)
    async with model:
        with pytest.raises(APIConnectionError) as caught:
            await model.client.responses.create(model="test-model", input="offline", max_output_tokens=256)
    assert len(calls) == 1
    assert isinstance(caught.value.__cause__, httpx.ConnectError)
    assert str(caught.value.__cause__) == "offline transport reached"
