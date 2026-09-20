"""Test-only worker: persistent atomic reservations immediately before HTTP transport I/O."""

import asyncio
import json
import os
import sqlite3

import httpx


class BudgetExceeded(RuntimeError):
    pass


def reserve(path):
    with sqlite3.connect(path, timeout=10) as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS attempts (id INTEGER PRIMARY KEY, reserved_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        )
        db.execute("BEGIN IMMEDIATE")
        count = db.execute("SELECT count(*) FROM attempts").fetchone()[0]
        if count >= 20:
            raise BudgetExceeded("Acceptance attempt budget exhausted")
        db.execute("INSERT INTO attempts DEFAULT VALUES")
        db.commit()


class BoundedTransport(httpx.AsyncBaseTransport):
    def __init__(self, path, transport=None):
        self.path = path
        self.inner = transport or httpx.AsyncHTTPTransport(
            local_address="0.0.0.0", trust_env=False, retries=0
        )

    async def handle_async_request(self, request):
        body = json.loads(await request.aread())
        if (
            str(request.url) != "https://api.openai.com/v1/responses"
            or body.get("model") != "gpt-5.6-luna"
            or not 1 <= body.get("max_output_tokens", 0) <= 512
            or body.get("reasoning", {}).get("effort") != "none"
        ):
            raise BudgetExceeded("Request outside acceptance bounds")
        reserve(self.path)  # Commits before sending; ambiguous and failed attempts remain counted.
        return await self.inner.handle_async_request(request)

    async def aclose(self):
        await self.inner.aclose()


def main():
    import agent_runtime.runtime as runtime
    from agent_runtime.worker import main as worker_main

    if os.environ.get("ACCEPTANCE_CAMPAIGN") in {
        "toolkits-subagents-v1",
        "general-runtime-v3",
        "lightweight-confidence-v1",
        "completion-loop-v1",
        "lightweight-model-comparison-v1",
        "completion-models-baseline-v1",
        "completion-models-verified-v1",
    }:
        import agent_runtime.model_adapter as adapter

        completion_models = os.environ["ACCEPTANCE_CAMPAIGN"].startswith("completion-models-")
        comparison = (
            completion_models or os.environ["ACCEPTANCE_CAMPAIGN"] == "lightweight-model-comparison-v1"
        )
        if completion_models:
            from scripts.completion_models_budget import profile

            policy = profile(os.environ["ACCEPTANCE_CAMPAIGN"])
            MODELS, Transport = policy.MODELS, policy.Transport
            policy.reconcile_unknown(os.environ["ACCEPTANCE_BUDGET_FILE"])
        elif comparison:
            from scripts.model_comparison_budget import MODELS, Transport, reconcile_unknown

            reconcile_unknown(os.environ["ACCEPTANCE_BUDGET_FILE"])
        elif os.environ["ACCEPTANCE_CAMPAIGN"] == "completion-loop-v1":
            from scripts.completion_loop_budget import Transport, reconcile_unknown

            reconcile_unknown(os.environ["ACCEPTANCE_BUDGET_FILE"])
        elif os.environ["ACCEPTANCE_CAMPAIGN"] == "lightweight-confidence-v1":
            from scripts.lightweight_budget import Transport, reconcile_unknown

            reconcile_unknown(os.environ["ACCEPTANCE_BUDGET_FILE"])
        elif os.environ["ACCEPTANCE_CAMPAIGN"] == "general-runtime-v3":
            from scripts.general_budget import Transport
        else:
            from scripts.toolkit_budget import Transport

        def factory(registration):
            if registration.adapter == "fake":
                return None
            if registration.provider != "openai" or registration.model not in (
                MODELS if comparison else ("gpt-5.6-luna",)
            ):
                raise BudgetExceeded("Only Luna is allowed")
            return httpx.AsyncClient(
                transport=(
                    Transport(os.environ["ACCEPTANCE_BUDGET_FILE"], registration.model)
                    if comparison
                    else Transport(os.environ["ACCEPTANCE_BUDGET_FILE"])
                ),
                timeout=30,
                trust_env=False,
                follow_redirects=False,
            )

        adapter.http_client_factory = factory
        asyncio.run(worker_main())
        return

    original = runtime.build_model

    def bounded(registration, **kwargs):
        if registration.adapter == "fake":
            return original(registration, **kwargs)
        if (registration.provider, registration.model) != ("openai", "gpt-5.6-luna"):
            raise BudgetExceeded("Only Luna is allowed")
        client = httpx.AsyncClient(
            transport=BoundedTransport(os.environ["ACCEPTANCE_BUDGET_FILE"]),
            timeout=30,
            trust_env=False,
            follow_redirects=False,
        )
        return original(registration, http_client=client)

    runtime.build_model = bounded
    asyncio.run(worker_main())


if __name__ == "__main__":
    main()
