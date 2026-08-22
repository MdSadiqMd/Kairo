# Agent worker image. Runs the durable agent runtime:
# planner/worker loop, isolated sandbox, typed tools, autonomy gate, state
# checkpointing. Ships git + a toolchain because the sandbox executes real code
# tasks. No torch — inference is called out to the router
# Built from the repo root; pushes to the ECR "agent-worker" repo
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY libs/kairo_common ./libs/kairo_common
COPY ml ./ml
RUN uv sync --package kairo-ml --no-dev --frozen

FROM python:3.11-slim-bookworm AS runtime
# git + build-essential: the agent sandbox reinitializes git history and
# compiles/tests code tasks.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git build-essential ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --gid 10001 app && useradd --uid 10001 --gid app --create-home app
WORKDIR /app
COPY --from=build --chown=app:app /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER app
# `kairo-agent run --task <spec>` per invocation; the Temporal worker/queue poll
# is the production backend (agents/temporal.yaml) wrapping this same runtime
ENTRYPOINT ["kairo-agent"]
