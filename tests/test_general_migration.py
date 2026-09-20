import asyncio
import json
import os
import sys
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from agent_runtime.db import AgentRow, Database, RunRow, SessionRow, ToolkitRunRow
from agent_runtime.schemas import AgentConfig

pytestmark = pytest.mark.integration


async def test_populated_0003_upgrade_preserves_active_legacy_rows(pg_store):
    schema = "upgrade_" + uuid4().hex
    admin = create_async_engine(pg_store.test_url)
    env = {**os.environ, "DATABASE_URL": pg_store.test_url, "DATABASE_SCHEMA": schema}
    env.pop("OPENAI_API_KEY", None)
    env.pop("ANTHROPIC_API_KEY", None)

    async def migrate(*args):
        p = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "alembic",
            *args,
            env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        assert await p.wait() == 0

    async with admin.begin() as conn:
        await conn.execute(text(f"CREATE SCHEMA {schema}"))
    database = Database(pg_store.test_url, schema)
    try:
        await migrate("upgrade", "0003")
        config = AgentConfig(name="legacy", provider="fake", model="deterministic").model_dump(
            exclude={"general"}
        )
        async with database.sessions.begin() as db:
            agent = AgentRow(id=str(uuid4()), config=config)
            session = SessionRow(id=str(uuid4()), history=[])
            db.add_all([agent, session])
            await db.flush()
            for version in [1, 2]:
                rid = str(uuid4())
                row = RunRow(
                    id=rid,
                    agent_id=agent.id,
                    session_id=session.id,
                    key="legacy-" + str(version),
                    fingerprint=str(version) * 64,
                    config=config,
                    input="legacy",
                    status="running",
                    approval_wait_seconds=60,
                )
                db.add(row)
                await db.flush()
                db.add(
                    ToolkitRunRow(
                        run_id=rid, root_id=rid, parent_id=None, state={"execution_version": version}
                    )
                )
        async with database.sessions() as db:
            before = (
                await db.execute(text("SELECT id,fingerprint,config::text,status FROM runs ORDER BY id"))
            ).all()
        await migrate("upgrade", "head")
        await migrate("check")
        async with database.sessions() as db:
            after = (
                await db.execute(text("SELECT id,fingerprint,config::text,status FROM runs ORDER BY id"))
            ).all()
            assert before == after
            assert all(json.loads(row[2]) == config for row in after)
            assert (await db.execute(text("SELECT count(*) FROM general_runs"))).scalar() == 0
    finally:
        await database.close()
        async with admin.begin() as conn:
            await conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        await admin.dispose()
