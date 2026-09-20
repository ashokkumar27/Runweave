"""One new 72-call campaign; reuse immutable admission/terminal transport enforcement."""

import sys
from functools import partial

import httpx

from scripts import general_budget as legacy
from scripts import lightweight_budget as base

MANIFEST = {
    **base.MANIFEST,
    "campaign": "completion-loop-v1",
    "limit": 72,
    "scenario_limits": {"bug": 12, "csv": 12, "recovery": 12, "direct": 12, "parallel": 24},
    "scenario_caps": {"bug": 1024, "csv": 1024, "recovery": 1024, "direct": 768, "parallel": 768},
    "parallel_root_limit": 24,
    "parallel_child_limit": 4,
}
SCHEMA = base.SCHEMA
TRIGGERS = {**base.TRIGGERS, "hard_limit": base.TRIGGERS["hard_limit"].replace(">=32", ">=72")}
manifest = partial(base.manifest, policy=sys.modules[__name__])
initialize = partial(base.initialize, policy=sys.modules[__name__])
validate = partial(base.validate, policy=sys.modules[__name__])
admit = partial(base.admit, policy=sys.modules[__name__])
finish = partial(base.finish, policy=sys.modules[__name__])
reserve = partial(base.reserve, policy=sys.modules[__name__])
reconcile_unknown = partial(base.reconcile_unknown, policy=sys.modules[__name__])


class Transport(legacy.Transport):
    def __init__(self, path, inner=None):
        super().__init__(
            path,
            base.BufferedResponse(
                inner or httpx.AsyncHTTPTransport(local_address="0.0.0.0", trust_env=False, retries=0)
            ),
            guard=sys.modules[__name__],
        )
