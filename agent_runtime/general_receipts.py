"""Authoritative current check receipts; never resolve acceptance from prompt projections."""

from sqlalchemy import select

from .general_db import GeneralRecordRow
from .project_store import digest


async def current_checks(store, db, gr):
    if not gr.data.get("workspace"):
        return {}
    branch, _ = await store.granted_branch(db, gr.run_id)
    revision = await store.project_revision(db, branch.workspace_id, branch.head)
    specifications = {(c["id"], s["id"]): (c, s) for c in gr.data["goal"]["criteria"] for s in c["checks"]}
    records = await db.scalars(
        select(GeneralRecordRow)
        .where(
            GeneralRecordRow.run_id == gr.run_id,
            GeneralRecordRow.kind == "verification",
        )
        .order_by(GeneralRecordRow.sequence)
    )
    result = {}
    for record in records:
        v = record.data
        key = (v["criterion_id"], v["check_id"])
        if key not in specifications:
            continue
        criterion, spec = specifications[key]
        if (
            v["goal_version"] == gr.data["goal"]["version"]
            and v["branch_id"] == branch.id
            and v["revision_id"] == branch.head
            and v["dependency_hash"] == digest(revision.data["files"])
            and v["spec_hash"] == digest(spec)
            and v["method"] == spec["kind"]
            and v["provenance"] == criterion["origin"]
            and v["provenance"] in {"user", "runtime"}
        ):
            result[key] = {"id": record.id, **v}
    return result
