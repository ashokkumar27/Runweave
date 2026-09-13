import hashlib
from uuid import uuid4

from sqlalchemy import func, select

from .db import AgentRow, EventRow, GateRow, NoteRow, OutboxRow, RunRow, SessionRow
from .schemas import Agent, AgentConfig, Event, Run, RunCreate, Session

TERMINAL = {"completed", "failed", "cancelled"}


class Problem(Exception):
    def __init__(self, status: int, detail: str):
        self.status, self.detail = status, detail


class Store:
    def __init__(self, database, max_active=20):
        self.database, self.max_active = database, max_active

    async def agent(self, config: AgentConfig, agent_id=None):
        # Explicit tested model registry, not a promise about arbitrary model capabilities.
        supported = {"fake": {"deterministic"}, "openai": {"gpt-4.1-mini"}, "anthropic": {"claude-haiku-4-5"}}
        if config.model not in supported[config.provider]:
            raise Problem(422, "Unsupported provider/model combination")
        async with self.database.sessions.begin() as db:
            row = await db.get(AgentRow, agent_id) if agent_id else None
            if agent_id and row is None:
                raise Problem(404, "Agent not found")
            if row is None:
                row = AgentRow(id=str(uuid4()), config=config.model_dump())
                db.add(row)
            else:
                row.config = config.model_dump()
            return Agent(id=row.id, config=config)

    async def get_agent(self, agent_id):
        async with self.database.sessions() as db:
            row = await db.get(AgentRow, agent_id)
            if row is None:
                raise Problem(404, "Agent not found")
            return Agent(id=row.id, config=row.config)

    async def session(self):
        async with self.database.sessions.begin() as db:
            row = SessionRow(id=str(uuid4()))
            db.add(row)
            await db.flush()
            return Session(id=row.id, created_at=row.created_at)

    @staticmethod
    def public(row):
        return Run(**{k: getattr(row, k) for k in Run.model_fields})

    async def locked(self, db, run_id):
        row = await db.scalar(select(RunRow).where(RunRow.id == run_id).with_for_update())
        if row is None:
            raise Problem(404, "Run not found")
        return row

    async def emit(self, db, row, key, kind, data=None):
        exists = await db.scalar(select(EventRow.id).where(EventRow.run_id == row.id, EventRow.dedupe == key))
        if exists is not None:
            return
        db.add(EventRow(run_id=row.id, id=row.next_event, dedupe=key, type=kind, data=data or {}))
        row.next_event += 1
        await db.flush()

    async def submit(self, body: RunCreate, key: str):
        fingerprint = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
        async with self.database.sessions.begin() as db:
            # One workspace: this short lock enforces global admission + idempotency atomically.
            await db.scalar(select(GateRow).where(GateRow.id == 1).with_for_update())
            existing = await db.scalar(select(RunRow).where(RunRow.key == key))
            if existing:
                if existing.fingerprint != fingerprint:
                    raise Problem(409, "Idempotency key reused with different input")
                return self.public(existing)
            agent = await db.get(AgentRow, body.agent_id)
            if agent is None:
                raise Problem(404, "Agent not found")
            count = await db.scalar(
                select(func.count()).select_from(RunRow).where(RunRow.status.not_in(TERMINAL))
            )
            if count >= self.max_active:
                raise Problem(429, "Active run limit reached")
            if body.session_id:
                session = await db.scalar(
                    select(SessionRow).where(SessionRow.id == body.session_id).with_for_update()
                )
                if session is None:
                    raise Problem(404, "Session not found")
                active = await db.scalar(
                    select(RunRow.id).where(RunRow.session_id == session.id, RunRow.status.not_in(TERMINAL))
                )
                if active:
                    raise Problem(409, "Session already has an active run")
            else:
                session = SessionRow(id=str(uuid4()))
                db.add(session)
                await db.flush()
            row = RunRow(
                id=str(uuid4()),
                session_id=session.id,
                agent_id=agent.id,
                key=key,
                fingerprint=fingerprint,
                config=agent.config,
                input=body.input,
            )
            db.add(row)
            await db.flush()
            await self.emit(db, row, "created", "run.queued")
            db.add(OutboxRow(id=f"start:{row.id}", run_id=row.id, kind="start"))
            return self.public(row)

    async def get(self, run_id):
        async with self.database.sessions() as db:
            row = await db.get(RunRow, run_id)
            if row is None:
                raise Problem(404, "Run not found")
            return self.public(row)

    async def events(self, run_id, cursor=0):
        async with self.database.sessions() as db:
            rows = (
                await db.scalars(
                    select(EventRow)
                    .where(EventRow.run_id == run_id, EventRow.id > cursor)
                    .order_by(EventRow.id)
                    .limit(100)
                )
            ).all()
            return [Event(**{k: getattr(r, k) for k in Event.model_fields}) for r in rows]

    async def load(self, run_id):
        async with self.database.sessions.begin() as db:
            row = await self.locked(db, run_id)
            session = await db.get(SessionRow, row.session_id)
            if row.status == "queued":
                row.status = "running"
                await self.emit(db, row, "running", "run.running")
            return {
                "id": row.id,
                "status": row.status,
                "config": row.config,
                "input": row.input,
                "history": session.history,
                "session_id": row.session_id,
            }

    async def finish(self, run_id, status, output=None, history=None, usage=None, error=None):
        async with self.database.sessions.begin() as db:
            row = await self.locked(db, run_id)
            if row.status in TERMINAL:
                return row.status
            row.status, row.output, row.error, row.usage = status, output, error, usage or {}
            row.approvals = []
            if status == "completed":
                session = await db.scalar(
                    select(SessionRow).where(SessionRow.id == row.session_id).with_for_update()
                )
                session.history = history or []
            await self.emit(db, row, "terminal", f"run.{status}", {"error": error} if error else {})
            return status

    async def cancel(self, run_id):
        async with self.database.sessions.begin() as db:
            row = await self.locked(db, run_id)
            if row.status not in TERMINAL:
                row.status, row.approvals = "cancelled", []
                await self.emit(db, row, "terminal", "run.cancelled")
                db.add(OutboxRow(id=f"cancel:{run_id}", run_id=run_id, kind="cancel"))
            return self.public(row)

    async def awaiting(self, run_id, approvals):
        async with self.database.sessions.begin() as db:
            row = await self.locked(db, run_id)
            if row.status in TERMINAL:
                return
            row.status, row.approvals = "awaiting_approval", approvals
            for approval in approvals:
                await self.emit(db, row, f"approval:{approval['id']}", "approval.required", approval)

    async def decide(self, run_id, approval_id, approved):
        async with self.database.sessions.begin() as db:
            row = await self.locked(db, run_id)
            old = row.decisions.get(approval_id)
            if old is not None:
                if old != approved:
                    raise Problem(409, "Approval decision is immutable")
                return self.public(row)
            if row.status != "awaiting_approval" or approval_id not in {a["id"] for a in row.approvals}:
                raise Problem(409, "Approval is not pending")
            row.decisions = {**row.decisions, approval_id: approved}
            await self.emit(
                db,
                row,
                f"decision:{approval_id}",
                "approval.decided",
                {"id": approval_id, "approved": approved},
            )
            db.add(
                OutboxRow(
                    id=f"decision:{run_id}:{approval_id}",
                    run_id=run_id,
                    kind="decision",
                    payload={"id": approval_id, "approved": approved},
                )
            )
            return self.public(row)

    async def resumed(self, run_id):
        async with self.database.sessions.begin() as db:
            row = await self.locked(db, run_id)
            if row.status not in TERMINAL:
                row.status, row.approvals = "running", []

    async def tool_event(self, run_id, call_id, tool, phase):
        async with self.database.sessions.begin() as db:
            row = await self.locked(db, run_id)
            if row.status not in TERMINAL:
                await self.emit(
                    db, row, f"tool:{call_id}:{phase}", f"tool.{phase}", {"tool": tool, "call_id": call_id}
                )

    async def record_note(self, run_id, call_id, text):
        operation = f"{run_id}:{call_id}"
        async with self.database.sessions.begin() as db:
            row = await self.locked(db, run_id)
            existing = await db.get(NoteRow, operation)
            if existing:
                if existing.text != text:
                    raise Problem(409, "Operation arguments changed")
                return "Note recorded"
            if row.status in TERMINAL:
                raise Problem(409, "Run is terminal")
            if row.decisions.get(call_id) is not True:
                raise Problem(409, "Tool approval required")
            db.add(NoteRow(operation_id=operation, run_id=run_id, text=text))
            # Effect and event commit together; retries return the same effect.
            await self.emit(
                db,
                row,
                f"note:{call_id}",
                "tool.effect_committed",
                {"call_id": call_id, "tool": "record_note"},
            )
            return "Note recorded"


def require_retry_safe_effect(*, idempotency_supported: bool, reconciler_available: bool):
    """External mutating connectors must implement one of these before registration."""
    if not (idempotency_supported or reconciler_available):
        raise ValueError("Non-idempotent external effects require reconciliation; execution refused")
