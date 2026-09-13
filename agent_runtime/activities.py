from temporalio import activity

from .runtime import get_store
from .telemetry import operation


@activity.defn
async def load_run(run_id: str) -> dict:
    with operation("run.load", run_id):
        data = await get_store().load(run_id)
    registration = await get_store().registration(data["registration_id"])
    data["model_available"] = registration.available()
    data["total_tokens_limit"] = registration.total_tokens_limit
    return data


@activity.defn
async def finish_run(data: dict) -> str:
    with operation("run.finish", data["run_id"]):
        return await get_store().finish(**data)


@activity.defn
async def await_approval(data: dict):
    await get_store().awaiting(data["run_id"], data["approvals"])


@activity.defn
async def resume_run(run_id: str):
    await get_store().resumed(run_id)


ACTIVITIES = [load_run, finish_run, await_approval, resume_run]
