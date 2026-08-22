# Training image. Runs LoRA/DPO/reward/distillation jobs and
# the online-RL train step as EKS/HyperPod GPU Jobs. Heavy (torch+transformers+
# peft+trl) — built on demand by the training pipeline, not on every push.
# Pushes to the ECR "training" repo. Built from the repo root.
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04 AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3.11 python3.11-venv git curl ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && curl -LsSf https://astral.sh/uv/install.sh | sh

ENV PATH="/root/.local/bin:${PATH}"
WORKDIR /app

# Install the ml package with the training extra (torch/transformers/peft/trl/
# accelerate/datasets/mlflow) into a self-contained venv.
COPY pyproject.toml uv.lock ./
COPY libs/kairo_common ./libs/kairo_common
COPY ml ./ml
RUN uv sync --package kairo-ml --extra train --extra aws --no-dev

ENV PATH="/app/.venv/bin:${PATH}"

# Entry: `kairo-train <job> --config ...`. GPU scheduling, dataset URIs, and the
# MLflow tracking URI are supplied by the Job spec.
ENTRYPOINT ["kairo-train"]
