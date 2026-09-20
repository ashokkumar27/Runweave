from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from scripts import start_local


@pytest.mark.parametrize("sudo", [False, True])
def test_startup_pins_validated_env_and_port(monkeypatch, tmp_path, sudo):
    monkeypatch.setattr(start_local, "ROOT", tmp_path)
    prepare = MagicMock(return_value="test-key")
    monkeypatch.setattr(start_local, "prepare_auth", prepare)
    ready = AsyncMock()
    monkeypatch.setattr(start_local, "ready", ready)
    monkeypatch.setenv("AGENTS_ENV_FILE", "/wrong/env")
    monkeypatch.setenv("API_PORT", "9999")
    sock = MagicMock()
    sock.__enter__.return_value.connect_ex.return_value = 0
    monkeypatch.setattr(start_local, "socket", SimpleNamespace(socket=MagicMock(return_value=sock)))
    calls = []

    def run(command, **kwargs):
        if command == ["docker", "info"]:
            return SimpleNamespace(returncode=int(sudo))
        calls.append(command)
        effective = kwargs["env"]
        if sudo:
            # sudo strips ambient variables; only explicit env assignments survive.
            assert command[:3] == ["sudo", "-n", "env"]
            effective = dict(part.split("=", 1) for part in command[3:5])
        assert effective["AGENTS_ENV_FILE"] == str(tmp_path / ".env.local")
        assert effective["API_PORT"] == "18000"
        assert kwargs["cwd"] == tmp_path
        return SimpleNamespace(returncode=0, stdout="127.0.0.1:18000\n")

    monkeypatch.setattr(start_local.subprocess, "run", run)
    assert start_local.main() == 0
    prepare.assert_called_once_with()
    ready.assert_awaited_once_with("test-key")
    assert len(calls) == 3
    assert calls[1][-3:] == ["compose", "build", "sandbox-image"]
    assert calls[-1][-5:] == ["--profile", "app", "up", "-d", "--build"]
    assert {p.name for p in tmp_path.iterdir()} == {".env.api.local", ".env.sandbox.local"}
    assert (tmp_path / ".env.api.local").read_text() == "API_KEY=test-key\n"
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in tmp_path.iterdir())
