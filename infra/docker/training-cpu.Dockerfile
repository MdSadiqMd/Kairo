FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends git curl ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && curl -LsSf https://astral.sh/uv/install.sh | sh

ENV PATH="/root/.local/bin:${PATH}"
WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY libs/kairo_common ./libs/kairo_common
COPY ml ./ml

RUN uv sync --package kairo-ml --extra aws --no-dev \
 && uv pip install --python /app/.venv/bin/python --index-url https://download.pytorch.org/whl/cpu \
    "torch>=2.4.0" \
 && uv pip install --python /app/.venv/bin/python \
    "transformers>=4.44.0" \
    "peft>=0.12.0" \
    "trl>=0.11.0" \
    "accelerate>=0.34.0" \
    "datasets>=2.20.0"

ENV PATH="/app/.venv/bin:${PATH}"

ENTRYPOINT ["kairo-train"]
