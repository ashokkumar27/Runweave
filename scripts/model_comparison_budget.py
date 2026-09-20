"""Acceptance-only immutable twelve-cell guard; reuse confidence ledger enforcement."""

import json
import os
import sys
from functools import partial
from types import SimpleNamespace

import httpx

from scripts import general_budget as legacy
from scripts import lightweight_budget as base

MODELS = tuple("gpt-5.6-" + name for name in ("luna", "terra", "sol"))
LIMITS = {"bug": 5, "csv": 6, "recovery": 6, "direct": 3}
CAPS = {"bug": 1024, "csv": 1024, "recovery": 1024, "direct": 768}
MANIFEST = {
    **base.MANIFEST,
    "campaign": "lightweight-model-comparison-v1",
    "limit": 60,
    "models": MODELS,
    "model": None,
    "scenario_limits": {f"{m}/{s}": n for m in MODELS for s, n in LIMITS.items()},
    "scenario_caps": {f"{m}/{s}": n for m in MODELS for s, n in CAPS.items()},
}
SCHEMA = base.SCHEMA
TRIGGERS = {**base.TRIGGERS, "hard_limit": base.TRIGGERS["hard_limit"].replace(">=32", ">=60")}
manifest = partial(base.manifest, policy=sys.modules[__name__])
initialize = partial(base.initialize, policy=sys.modules[__name__])
validate = partial(base.validate, policy=sys.modules[__name__])
admit = partial(base.admit, policy=sys.modules[__name__])
finish = partial(base.finish, policy=sys.modules[__name__])
reserve = partial(base.reserve, policy=sys.modules[__name__])
reconcile_unknown = partial(base.reconcile_unknown, policy=sys.modules[__name__])


class Capture(base.BufferedResponse):
    def __init__(self, inner, path, model, policy=None):
        super().__init__(inner)
        self.path, self.model = path, model
        self.policy = policy or sys.modules[__name__]

    async def handle_async_request(self, request):
        from agent_runtime.model_adapter import request_context

        record = {"context": request_context.get(), "body": json.loads(await request.aread())}
        try:
            response = await super().handle_async_request(request)
            record["status_code"] = response.status_code
            try:
                data = response.json()
                # Retain decisions/usage/refusals, never headers or provider error bodies.
                record["response"] = {k: data[k] for k in ("output", "usage", "status", "model") if k in data}
                if any(
                    part.get("type") == "refusal"
                    for item in data.get("output", [])
                    for part in item.get("content", [])
                ):
                    self.policy.finish(
                        self.path, self.model + "/" + record["context"]["scenario"], "provider_refusal"
                    )
                    record["refusal"] = True
                if response.status_code >= 400:
                    record["error_code"] = data.get("error", {}).get("code")
                    record["error_type"] = data.get("error", {}).get("type")
            except ValueError:
                record["invalid_json"] = True
            return response
        finally:
            if target := os.environ.get("COMPARISON_WIRE_LOG"):
                fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                with os.fdopen(fd, "a") as stream:
                    stream.write(json.dumps(record) + "\n")


class Transport(legacy.Transport):
    def __init__(self, path, model, inner=None):
        if model not in MODELS:
            raise RuntimeError("Unregistered comparison model")

        def bound_reserve(value, context, cap):
            # Model comes from the validated wire body, scenario/root from durable runtime accounting.
            return reserve(value, {**context, "scenario": model + "/" + context["scenario"]}, cap)

        policy = SimpleNamespace(
            MANIFEST={**MANIFEST, "model": model}, validate=validate, reserve=bound_reserve
        )
        super().__init__(
            path,
            Capture(
                inner or httpx.AsyncHTTPTransport(local_address="0.0.0.0", trust_env=False, retries=0),
                path,
                model,
            ),
            guard=policy,
        )
