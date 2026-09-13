"""Deadline-based readiness for CI/local services."""

import asyncio

from fastmcp import Client as MCPClient
from sqlalchemy import text

from agent_runtime.config import settings
from agent_runtime.db import Database
from agent_runtime.worker import connect


async def main():
    async with asyncio.timeout(90):
        await connect()
        db = Database(settings().database_url)
        try:
            while True:
                try:
                    async with db.engine.connect() as conn:
                        await conn.execute(text("SELECT 1"))
                    async with MCPClient(settings().mcp_url, timeout=3) as client:
                        result = await client.call_tool("convert_temperature", {"celsius": 0})
                        assert result.data == 32
                    return
                except Exception:
                    await asyncio.sleep(0.5)
        finally:
            await db.close()


if __name__ == "__main__":
    asyncio.run(main())
