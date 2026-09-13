FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.12 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY agent_runtime ./agent_runtime
COPY alembic.ini ./
COPY migrations ./migrations
ENV PYTHONUNBUFFERED=1 PYDANTIC_AI_NO_BANNER=1
