import os
import subprocess
import sys

import pytest


@pytest.mark.live
@pytest.mark.parametrize("provider,key", [("openai", "OPENAI_API_KEY"), ("anthropic", "ANTHROPIC_API_KEY")])
def test_provider_smoke(provider, key):
    if not os.environ.get(key):
        pytest.skip(f"{provider} credential not provided")
    result = subprocess.run(
        [sys.executable, "-m", "scripts.live_smoke", "--provider", provider],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout  # Script output is deliberately sanitized.
