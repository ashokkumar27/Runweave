from unittest.mock import MagicMock

import httpx
import pytest

from scripts import auth_diagnostic


@pytest.mark.parametrize(
    "file_setting,ambient,address",
    [
        (None, None, "0.0.0.0"),
        ("false", None, None),
        (None, "false", None),
        ("true", "false", "0.0.0.0"),
    ],
)
def test_diagnostic_routing_and_safe_ip_denial(monkeypatch, capsys, file_setting, ambient, address):
    values = {"OPENAI_API_KEY": "test-secret"}
    if file_setting is not None:
        values["OPENAI_FORCE_IPV4"] = file_setting
    monkeypatch.setattr("dotenv.dotenv_values", lambda _: values)
    monkeypatch.delenv("OPENAI_FORCE_IPV4", raising=False)
    if ambient is not None:
        monkeypatch.setenv("OPENAI_FORCE_IPV4", ambient)
    transport = MagicMock()
    monkeypatch.setattr(httpx, "HTTPTransport", transport)
    client = MagicMock()
    client.return_value.__enter__.return_value.get.return_value = httpx.Response(
        403,
        json={
            "error": {"code": "ip_not_authorized", "type": "permission_error", "message": "test-secret"},
        },
    )
    monkeypatch.setattr(httpx, "Client", client)
    assert auth_diagnostic.main() == 1
    transport.assert_called_once_with(local_address=address, trust_env=False, retries=0)
    client.assert_called_once_with(
        timeout=10, trust_env=False, follow_redirects=False, transport=transport.return_value
    )
    client.return_value.__enter__.return_value.get.assert_called_once()
    assert capsys.readouterr().out == "status=403 code=ip_not_authorized type=permission_error\n"


@pytest.mark.parametrize(
    "body", [None, {"code": "test-secret", "type": "test-secret"}, {"error": {"code": [], "type": {}}}]
)
def test_diagnostic_sanitizes_unknown_error_values(body):
    assert auth_diagnostic.safe_error(body) == ("unclassified", "unclassified")
