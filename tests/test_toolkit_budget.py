import asyncio
import json
import sqlite3

import httpx
import pytest

from agent_runtime.model_adapter import request_context
from scripts.toolkit_budget import Transport, initialize, reserve, validate


async def test_atomic_fifty_and_no_transport_after_cap(tmp_path):
    path = tmp_path / "campaign.sqlite"
    initialize(path)
    results = await asyncio.gather(
        *(asyncio.to_thread(reserve, path, "test", "root", 512) for _ in range(60)), return_exceptions=True
    )
    assert sum(r is None for r in results) == 50 and validate(path) == 50
    sent = []
    transport = Transport(path, httpx.MockTransport(lambda request: sent.append(request)))
    context = request_context.set({"run_id": "root"})
    try:
        with pytest.raises(RuntimeError):
            await transport.handle_async_request(
                httpx.Request(
                    "POST",
                    "https://api.openai.com/v1/responses",
                    content=json.dumps(
                        {"model": "gpt-5.6-luna", "max_output_tokens": 512, "reasoning": {"effort": "none"}}
                    ),
                )
            )
    finally:
        request_context.reset(context)
    assert not sent
    with sqlite3.connect(path) as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM attempts")
    path.unlink()
    with pytest.raises(RuntimeError):
        initialize(path)


def test_symlinks_and_manifest_changes_refused(tmp_path):
    target = tmp_path / "real"
    target.write_text("not a ledger")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(RuntimeError):
        initialize(link)
    path = tmp_path / "valid"
    initialize(path)
    with sqlite3.connect(path) as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE manifest SET value='{}'")
