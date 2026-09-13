from temporalio import activity

from .runtime import get_store, models
from .telemetry import operation


@activity.defn
async def load_run(run_id: str) -> dict:
    with operation("run.load", run_id):
        data = await get_store().load(run_id)
    config = data["config"]
    data["model_available"] = f"{config['provider']}:{config['model']}" in models
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
