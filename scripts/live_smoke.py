"""Explicit, bounded provider verification. Never prints credentials or exception bodies."""

import argparse
import asyncio
import os
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["openai", "anthropic"], required=True)
    parser.add_argument(
        "--load-local-env", action="store_true", help="Load the authorized .env.local in this process only"
    )
    args = parser.parse_args()
    if args.load_local_env:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parents[1] / ".env.local", override=False)
    key = "OPENAI_API_KEY" if args.provider == "openai" else "ANTHROPIC_API_KEY"
    if not os.environ.get(key):
        print(f"{args.provider}: NOT RUN (credential unavailable)")
        return 2
    os.environ["PYDANTIC_AI_NO_BANNER"] = "1"
    try:
        asyncio.run(check(args.provider))
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        body = getattr(exc, "body", None)
        code = (
            body.get("error", {}).get("code")
            if isinstance(body, dict) and isinstance(body.get("error"), dict)
            else None
        )
        allowed_codes = {
            "insufficient_quota",
            "rate_limit_exceeded",
            "invalid_api_key",
            "model_not_found",
            "unsupported_parameter",
            "invalid_request_error",
        }
        safe_code = code if code in allowed_codes else "unclassified"
        safe_status = status if isinstance(status, int) else "none"
        print(
            f"{args.provider}: FAILED ({type(exc).__name__}; HTTP {safe_status}; code={safe_code}; body suppressed)"
        )
        return 1
    return 0


async def check(provider):
    from pydantic_ai.usage import UsageLimits

    from agent_runtime.db import Database
    from agent_runtime.runtime import Deps, agent, configure_store, models
    from agent_runtime.schemas import AgentConfig, RunCreate
    from agent_runtime.store import Store

    model = "gpt-4.1-mini" if provider == "openai" else "claude-haiku-4-5"
    with tempfile.TemporaryDirectory(prefix="agents-smoke-") as directory:
        db = Database(f"sqlite+aiosqlite:///{directory}/smoke.db")
        try:
            await db.create_test_schema()
            store = Store(db)
            configure_store(store)
            saved = await store.agent(AgentConfig(name="live smoke", provider=provider, model=model))
            prompt = 'Call the add tool exactly once with a=2 and b=3. Return answer="5" and value=5.'
            run = await store.submit(RunCreate(agent_id=saved.id, input=prompt), "smoke")
            async with asyncio.timeout(45):
                result = await agent.run(
                    prompt,
                    model=models[f"{provider}:{model}"],
                    deps=Deps(run.id, ["add"]),
                    retries=0,
                    usage_limits=UsageLimits(request_limit=2, tool_calls_limit=1, total_tokens_limit=3000),
                    model_settings={"max_tokens": 256, "timeout": 20},
                )
            assert result.output.value == 5 and result.usage.tool_calls == 1
            print(f"{provider}: PASS (typed add + structured output; {result.usage.requests} requests)")
        finally:
            await db.close()


if __name__ == "__main__":
    raise SystemExit(main())
