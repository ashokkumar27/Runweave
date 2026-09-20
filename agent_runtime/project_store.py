"""Immutable projects and file-level three-way integration, with explicit grants."""

import base64
import hashlib
import io
import json
import unicodedata
import zipfile
from uuid import uuid4

from sqlalchemy import func, select

from .db import GateRow
from .general_db import (
    ProjectBlobRow,
    ProjectBranchRow,
    ProjectGrantRow,
    ProjectRevisionRow,
    ProjectWorkspaceRow,
)


def digest(data):
    if not isinstance(data, bytes):
        data = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(data).hexdigest()


def fail(code, status=422):
    from .store import Problem

    raise Problem(status, code)


def path(value, *, prefix=False):
    if prefix and value == "":
        return value
    if not isinstance(value, str) or not value or len(value.encode()) > 200:
        fail("invalid_project_path")
    if unicodedata.normalize("NFC", value) != value or "\\" in value:
        fail("invalid_project_path")
    parts = value.split("/")
    if len(parts) > 16 or any(
        p in {"", ".", ".."}
        or p.casefold() in {".git", ".runtime", "__runtime__"}
        or len(p.encode()) > 100
        or any(ord(c) < 32 or ord(c) == 127 for c in p)
        for p in parts
    ):
        fail("invalid_project_path")
    return value


def covered(name, prefixes):
    return any(not p or name == p or name.startswith(p + "/") for p in prefixes)


def decode(value):
    try:
        result = base64.b64decode(value, validate=True)
    except Exception:
        fail("invalid_project_bytes")
    if len(result) > 262144:
        fail("project_file_limit", 413)
    return result


def validate_files(files, limits=None):
    limits = limits or {}
    if len(files) > limits.get("files", 256):
        fail("project_file_limit", 413)
    folded = set()
    canonical = {}
    for name, content in sorted(files.items()):
        path(name)
        for i in range(1, len(name.split("/")) + 1):
            component_path = "/".join(name.split("/")[:i])
            key = component_path.casefold()
            if key in canonical and canonical[key] != component_path:
                fail("project_path_collision")
            canonical[key] = component_path
        if name.casefold() in folded:
            fail("project_path_collision")
        folded.add(name.casefold())
        if len(content) > limits.get("file_bytes", 262144):
            fail("project_file_limit", 413)
    # A file cannot also be a directory, including casefold aliases.
    for name in folded:
        if any("/".join(name.split("/")[:i]) in folded for i in range(1, len(name.split("/")))):
            fail("project_path_collision")
    if sum(map(len, files.values())) > limits.get("revision_bytes", 4194304):
        fail("project_revision_limit", 413)


def three_way(base, parent, child, write_prefixes):
    merged, conflicts = dict(parent), []
    for name in sorted(set(base) | set(child)):
        before, after, current = base.get(name), child.get(name), parent.get(name)
        if before == after:
            continue
        if not covered(name, write_prefixes):
            conflicts.append(name)
        elif current == before or current == after:
            if after is None:
                merged.pop(name, None)
            else:
                merged[name] = after
        else:
            conflicts.append(name)
    return merged, conflicts


class ProjectStore:
    async def project_revision(self, db, workspace_id, revision_id):
        workspace = await db.get(ProjectWorkspaceRow, workspace_id)
        revision = await db.get(ProjectRevisionRow, revision_id)
        if workspace is None or revision is None or revision.workspace_id != workspace_id:
            fail("Workspace revision not found", 404)
        if digest(revision.data) != revision.id:
            fail("project_integrity", 409)
        return revision

    async def project_files(self, db, workspace_id, revision_id):
        revision = await self.project_revision(db, workspace_id, revision_id)
        files = {}
        for entry in revision.data["files"]:
            blob = await db.get(ProjectBlobRow, entry["sha256"])
            if (
                blob is None
                or blob.length != entry["size_bytes"]
                or len(blob.content) != blob.length
                or digest(blob.content) != blob.id
            ):
                fail("project_integrity", 409)
            files[entry["path"]] = blob.content
        validate_files(files)
        return files

    async def project_commit(self, db, workspace_id, files, parents, limits=None):
        validate_files(files, limits)
        entries = [{"path": p, "sha256": digest(b), "size_bytes": len(b)} for p, b in sorted(files.items())]
        payload = {"schema_version": 3, "workspace_id": workspace_id, "parents": parents, "files": entries}
        rid = digest(payload)
        if await db.get(ProjectRevisionRow, rid):
            return rid
        total = await db.scalar(select(func.coalesce(func.sum(ProjectBlobRow.length), 0)))
        for b in files.values():
            bid = digest(b)
            if await db.get(ProjectBlobRow, bid) is None:
                total += len(b)
                if total > 268435456:
                    fail("project_storage_limit", 413)
                db.add(ProjectBlobRow(id=bid, content=b, length=len(b)))
                await db.flush()
        db.add(ProjectRevisionRow(id=rid, workspace_id=workspace_id, data=payload))
        await db.flush()
        return rid

    async def workspace_create(self, request, key):
        files = {f.path: decode(f.content_base64) for f in request.files}
        if len(files) != len(request.files):
            fail("project_path_collision")
        validate_files(files)
        fingerprint = digest({p: digest(b) for p, b in files.items()})
        async with self.database.sessions.begin() as db:
            await db.scalar(select(GateRow).where(GateRow.id == 1).with_for_update())
            old = await db.scalar(select(ProjectWorkspaceRow).where(ProjectWorkspaceRow.key == key))
            if old:
                if old.fingerprint != fingerprint:
                    fail("Idempotency key reused with different input", 409)
                return {"workspace_id": old.id, "revision_id": old.initial_revision}
            wid = str(uuid4())
            row = ProjectWorkspaceRow(
                id=wid, key=key, fingerprint=fingerprint, principal="app", initial_revision=""
            )
            db.add(row)
            await db.flush()
            row.initial_revision = await self.project_commit(db, wid, files, [])
            return {"workspace_id": wid, "revision_id": row.initial_revision}

    async def workspace_get(self, wid, revision=None, file=None, archive=False):
        async with self.database.sessions() as db:
            workspace = await db.get(ProjectWorkspaceRow, wid)
            if workspace is None or workspace.principal != "app":
                fail("Workspace not found", 404)
            revision = revision or workspace.initial_revision
            record = await self.project_revision(db, wid, revision)
            if file is None and not archive:
                return {"workspace_id": wid, "revision_id": revision, **record.data}
            files = await self.project_files(db, wid, revision)
            if file is not None:
                path(file)
                if file not in files:
                    fail("File not found", 404)
                return files[file]
            out = io.BytesIO()
            with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_STORED) as z:
                for name, data in sorted(files.items()):
                    info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                    info.external_attr = 0o100644 << 16
                    z.writestr(info, data)
            return out.getvalue()

    async def granted_branch(self, db, run_id, expected=None):
        grant = await db.get(ProjectGrantRow, run_id)
        if grant is None:
            fail("workspace_not_authorized", 404)
        branch = await db.scalar(
            select(ProjectBranchRow).where(ProjectBranchRow.id == grant.branch_id).with_for_update()
        )
        if expected is not None and branch.head != expected:
            fail("revision_conflict", 409)
        return branch, grant

    async def branch_files(self, db, run_id, revision=None):
        branch, grant = await self.granted_branch(db, run_id)
        # Historical reads are restricted to revisions recorded in this branch's grant.
        revision = revision or branch.head
        if revision not in grant.data["revisions"]:
            fail("revision_not_authorized", 404)
        files = await self.project_files(db, branch.workspace_id, revision)
        return branch, grant, {p: b for p, b in files.items() if covered(p, grant.data["read_prefixes"])}

    async def branch_commit(self, db, run_id, files, expected, parents=None):
        branch, grant, old = await self.branch_files(db, run_id)
        if branch.head != expected:
            fail("revision_conflict", 409)
        for name in set(old) | set(files):
            if old.get(name) != files.get(name) and not covered(name, grant.data["write_prefixes"]):
                fail("workspace_write_denied", 403)
        if files == old:
            return branch.head
        from .general_db import GeneralRunRow

        gr = await db.get(GeneralRunRow, run_id)
        root = await db.get(GeneralRunRow, gr.root_id)
        state = dict(root.data)
        budget = dict(state["budget"])
        limits = state["policy"]["limits"]
        validate_files(files, limits)
        hashes = dict(state.get("project_hashes", {}))
        hashes.update({digest(b): len(b) for b in files.values()})
        if (
            sum(hashes.values()) > limits["storage_bytes"]
            or budget.get("revisions", 0) >= limits["revisions"]
        ):
            fail("project_storage_limit", 409)
        rid = await self.project_commit(db, branch.workspace_id, files, parents or [expected], limits)
        branch.head, branch.version = rid, branch.version + 1
        grant.data = {**grant.data, "revisions": [*grant.data["revisions"], rid]}
        budget["revisions"] = budget.get("revisions", 0) + 1
        budget["storage_bytes"] = sum(hashes.values())
        root.data = {**state, "budget": budget, "project_hashes": hashes}
        return rid
