"""Two fixed model-qualified completion phases using the existing immutable ledger."""

from functools import partial
from types import SimpleNamespace

import httpx

from scripts import general_budget as legacy
from scripts import lightweight_budget as base
from scripts.completion_loop_budget import MANIFEST as COMPLETION
from scripts.model_comparison_budget import MODELS, Capture

PHASES = ("completion-models-baseline-v1", "completion-models-verified-v1")


def profile(campaign):
    if campaign not in PHASES:
        raise ValueError("Unknown completion phase")
    policy = SimpleNamespace(
        MODELS=MODELS,
        MANIFEST={
            **COMPLETION,
            "campaign": campaign,
            "model": None,
            "models": MODELS,
            "limit": 216,
            **{
                key: {f"{m}/{s}": n for m in MODELS for s, n in COMPLETION[key].items()}
                for key in ("scenario_limits", "scenario_caps")
            },
        },
        SCHEMA=base.SCHEMA,
        TRIGGERS={**base.TRIGGERS, "hard_limit": base.TRIGGERS["hard_limit"].replace(">=32", ">=216")},
    )
    for name in ("manifest", "initialize", "validate", "admit", "finish", "reserve", "reconcile_unknown"):
        setattr(policy, name, partial(getattr(base, name), policy=policy))

    def transport(path, model, inner=None):
        if model not in MODELS:
            raise RuntimeError("Unregistered completion model")

        def reserve(value, context, cap):
            return policy.reserve(value, {**context, "scenario": model + "/" + context["scenario"]}, cap)

        return legacy.Transport(
            path,
            Capture(
                inner or httpx.AsyncHTTPTransport(local_address="0.0.0.0", trust_env=False, retries=0),
                path,
                model,
                policy,
            ),
            guard=SimpleNamespace(
                MANIFEST={**policy.MANIFEST, "model": model}, validate=policy.validate, reserve=reserve
            ),
        )

    policy.Transport = transport
    return policy
