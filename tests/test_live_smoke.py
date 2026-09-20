import json
import sys

import httpx
import pytest

from agent_runtime import runtime
from scripts import live_smoke


@pytest.mark.parametrize("override", [None, "gpt-4.1-mini"])
def test_openai_smoke_settings_and_sanitized_failure(monkeypatch, capsys, override):
    requests = []
    expected_model = override or "gpt-5.6-luna"

    def respond(request):
        requests.append(request)
        assert request.url.path == "/v1/responses"
        body = json.loads(request.content)
        assert body["model"] == expected_model
        assert body["max_output_tokens"] == 256
        if override is None:
            assert body["reasoning"]["effort"] == "none"
        else:
            assert not body.get("reasoning")
        assert request.extensions["timeout"]["read"] == 20
        return httpx.Response(
            401,
            json={"error": {"message": "private-error-body", "type": "invalid_request_error"}},
        )

    original_build = runtime.build_model

    def build(registration):
        model = original_build(
            registration, http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))
        )
        assert model.client.max_retries == 0
        return model

    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-credential")
    monkeypatch.setattr("pydantic_ai.models.ALLOW_MODEL_REQUESTS", True)
    monkeypatch.setattr(runtime, "build_model", build)
    argv = ["live_smoke", "--provider", "openai"]
    if override:
        argv.extend(["--model", override])
    monkeypatch.setattr(sys, "argv", argv)
    assert live_smoke.main() == 1
    output = capsys.readouterr()
    assert "HTTP 401" in output.out
    assert "private-error-body" not in output.out + output.err
    assert "offline-test-credential" not in output.out + output.err
    assert len(requests) == 1
