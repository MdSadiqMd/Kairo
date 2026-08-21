# Safety classifier image — multi-stage, uv-based, non-root.
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY libs/kairo_common ./libs/kairo_common
COPY services/safety_classifier ./services/safety_classifier
RUN uv sync --package kairo-safety-classifier --no-dev --frozen

FROM python:3.11-slim-bookworm AS runtime
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home app
WORKDIR /app
COPY --from=build --chown=app:app /app/.venv /app/.venv
COPY --from=build --chown=app:app /app/services/safety_classifier/src /app/src
COPY --from=build --chown=app:app /app/libs/kairo_common/src/kairo_common /app/src/kairo_common
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH="/app/src" PYTHONUNBUFFERED=1
USER app
EXPOSE 8080
CMD ["uvicorn", "safety_classifier.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
