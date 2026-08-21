# Router image — multi-stage, uv-based, non-root.
# Built and pushed to ECR by build-images.yml / qctl.
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS build

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Copy only what the router package needs from the workspace so the build cache
# is not invalidated by unrelated services.
COPY pyproject.toml uv.lock ./
COPY libs/kairo_common ./libs/kairo_common
COPY services/router ./services/router

# Install the router package plus its AWS extra into a self-contained venv.
RUN uv sync --package kairo-router --extra aws --no-dev --frozen

FROM python:3.11-slim-bookworm AS runtime

# Non-root runtime user.
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home app

WORKDIR /app
COPY --from=build --chown=app:app /app/.venv /app/.venv
COPY --from=build --chown=app:app /app/services/router/src /app/src
COPY --from=build --chown=app:app /app/libs/kairo_common/src/kairo_common /app/src/kairo_common
COPY --chown=app:app ml/models/registry.local.yaml /app/ml/models/registry.local.yaml

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src" \
    PYTHONUNBUFFERED=1 \
    ROUTER_LOG_LEVEL=INFO

USER app
EXPOSE 8080

# /readyz gates traffic on the registry being loaded; /healthz is liveness.
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8080/healthz').status==200 else 1)"

CMD ["uvicorn", "router.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
