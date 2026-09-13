import asyncio
import hmac
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .config import settings
from .db import Database
from .schemas import Agent, AgentConfig, Decision, Run, RunCreate, Session
from .store import TERMINAL, Problem, Store


def create_app(store: Store | None = None, api_key: str | None = None):
    owned = store is None
    store = store or Store(
        Database(settings().database_url, settings().database_schema), settings().max_active_runs
    )
    expected = api_key if api_key is not None else settings().api_key.get_secret_value()

    @asynccontextmanager
    async def lifespan(app):
        if not expected:
            raise RuntimeError("API_KEY must be configured")
        yield
        if owned:
            await store.database.close()

    async def authenticate(authorization: Annotated[str | None, Header()] = None):
        supplied = (authorization or "").removeprefix("Bearer ")
        if (
            not expected
            or not authorization
            or not authorization.startswith("Bearer ")
            or not hmac.compare_digest(supplied.encode(), expected.encode())
        ):
            raise Problem(401, "Invalid API key")

    app = FastAPI(
        title="Independent Agents API",
        version="1.0.0",
        lifespan=lifespan,
        dependencies=[Depends(authenticate)],
    )

    @app.exception_handler(Problem)
    async def problem_handler(request, exc):
        return JSONResponse(
            status_code=exc.status,
            content={"detail": exc.detail},
            headers={"WWW-Authenticate": "Bearer"} if exc.status == 401 else {},
        )

    @app.post("/v1/agents", response_model=Agent, status_code=201)
    async def create_agent(config: AgentConfig):
        return await store.agent(config)

    @app.get("/v1/agents/{agent_id}", response_model=Agent)
    async def get_agent(agent_id: str):
        return await store.get_agent(agent_id)

    @app.put("/v1/agents/{agent_id}", response_model=Agent)
    async def update_agent(agent_id: str, config: AgentConfig):
        return await store.agent(config, agent_id)

    @app.post("/v1/sessions", response_model=Session, status_code=201)
    async def create_session():
        return await store.session()

    @app.post("/v1/runs", response_model=Run, status_code=202)
    async def create_run(
        body: RunCreate, idempotency_key: Annotated[str, Header(min_length=1, max_length=128)]
    ):
        return await store.submit(body, idempotency_key)

    @app.get("/v1/runs/{run_id}", response_model=Run)
    async def get_run(run_id: str):
        return await store.get(run_id)

    @app.post("/v1/runs/{run_id}/cancel", response_model=Run)
    async def cancel_run(run_id: str):
        return await store.cancel(run_id)

    @app.post("/v1/runs/{run_id}/approvals/{approval_id}", response_model=Run)
    async def decide(run_id: str, approval_id: str, decision: Decision):
        return await store.decide(run_id, approval_id, decision.approved)

    @app.get("/v1/runs/{run_id}/events")
    async def stream(
        run_id: str,
        request: Request,
        cursor: Annotated[int, Query(ge=0)] = 0,
        last_event_id: Annotated[str | None, Header()] = None,
    ):
        if last_event_id is not None:
            try:
                cursor = int(last_event_id)
                if cursor < 0:
                    raise ValueError
            except ValueError:
                raise Problem(400, "Invalid Last-Event-ID") from None
        await store.get(run_id)

        async def generate():
            nonlocal cursor
            while not await request.is_disconnected():
                # Read status before events to avoid missing a terminal event committed between reads.
                run = await store.get(run_id)
                events = await store.events(run_id, cursor)
                for event in events:
                    yield f"id: {event.id}\nevent: {event.type}\ndata: {event.model_dump_json()}\n\n"
                    cursor = event.id
                if run.status in TERMINAL and len(events) < 100:
                    return
                if not events:
                    yield ": keepalive\n\n"
                    await asyncio.sleep(0.5)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


app = create_app()
