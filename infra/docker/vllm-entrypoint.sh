#!/usr/bin/env bash
# vLLM serving entrypoint.
# Builds the OpenAI-compatible server command from environment variables and
# starts it. Critically, it does NOT enable any of the vLLM dev/admin endpoints:
# no runtime LoRA load/unload, no /pause /sleep, no /update_weights, no
# /collective_rpc, no /reset_prefix_cache. Those are disabled by default in the
# server; we simply never turn them on.
set -euo pipefail

MODEL_ID="${MODEL_ID:?MODEL_ID is required (e.g. MODEL_PROVIDER/Model-32B)}"
SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-${MODEL_ID}}"
TENSOR_PARALLEL_SIZE="${TENSOR_PARALLEL_SIZE:-1}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-16384}"
HOST="${VLLM_HOST:-0.0.0.0}"
PORT="${VLLM_PORT:-8000}"
DEVICE="${VLLM_DEVICE:-}"
DTYPE="${VLLM_DTYPE:-}"
# Leave headroom below 1.0 so CUDA/NCCL and activation buffers fit alongside the
# KV cache.
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.90}"

args=(
  --model "${MODEL_ID}"
  --served-model-name "${SERVED_MODEL_NAME}"
  --tensor-parallel-size "${TENSOR_PARALLEL_SIZE}"
  --max-model-len "${MAX_MODEL_LEN}"
  --host "${HOST}"
  --port "${PORT}"
)

if [[ -n "${DEVICE}" && "${DEVICE}" != "cpu" ]]; then
  args+=(--device "${DEVICE}")
fi

if [[ -n "${DTYPE}" ]]; then
  args+=(--dtype "${DTYPE}")
fi

if [[ "${DEVICE}" != "cpu" ]]; then
  args+=(--gpu-memory-utilization "${GPU_MEMORY_UTILIZATION}")
fi

# Pin the exact HF commit for immutable, reproducible deploys.
if [[ -n "${MODEL_REVISION:-}" ]]; then
  args+=(--revision "${MODEL_REVISION}")
fi

# Optional internal API key — a second auth layer behind the
# NetworkPolicy (defense in depth against a misconfigured policy).
if [[ -n "${VLLM_API_KEY:-}" ]]; then
  args+=(--api-key "${VLLM_API_KEY}")
fi

# FP8/INT8 KV cache roughly doubles concurrency per replica.
if [[ -n "${KV_CACHE_DTYPE:-}" ]]; then
  args+=(--kv-cache-dtype "${KV_CACHE_DTYPE}")
fi

if [[ -n "${MAX_NUM_SEQS:-}" ]]; then
  args+=(--max-num-seqs "${MAX_NUM_SEQS}")
fi

if [[ -n "${MAX_NUM_BATCHED_TOKENS:-}" ]]; then
  args+=(--max-num-batched-tokens "${MAX_NUM_BATCHED_TOKENS}")
fi

# Explicit quantization (e.g. fp8, awq) on capable GPUs.
if [[ -n "${QUANTIZATION:-}" ]]; then
  args+=(--quantization "${QUANTIZATION}")
fi

if [[ "${ENFORCE_EAGER:-}" == "true" ]]; then
  args+=(--enforce-eager)
fi

# Task type for non-generation models (e.g. "score" for cross-encoder rerankers).
# When set, vLLM exposes /v1/score instead of /v1/chat/completions.
if [[ -n "${VLLM_TASK:-}" ]]; then
  args+=(--task "${VLLM_TASK}")
fi

# LoRA serving for candidate evaluation deployment. ENABLE_LORA=true enables
# --enable-lora and optionally loads static adapters from LORA_MODULES.
# Only used by the candidate deployment; production uses annotation-based rollouts.
if [[ "${ENABLE_LORA:-}" == "true" ]]; then
  args+=(--enable-lora)
  # Only add --lora-modules if the adapter path exists and has an adapter_config.json
  # (first boot the dir is empty; vLLM crashes if --lora-modules points to empty path)
  if [[ -n "${LORA_MODULES:-}" ]]; then
    # LORA_MODULES format: "name=path" — extract path
    adapter_path="${LORA_MODULES#*=}"
    if [[ -f "${adapter_path}/adapter_config.json" ]]; then
      args+=(--lora-modules "${LORA_MODULES}")
      echo "loading adapter from ${adapter_path}" >&2
    else
      echo "no adapter at ${adapter_path} (first boot?); starting without LoRA modules" >&2
    fi
  fi
  if [[ -n "${MAX_LORAS:-}" ]]; then
    args+=(--max-loras "${MAX_LORAS}")
  fi
  if [[ -n "${MAX_LORA_RANK:-}" ]]; then
    args+=(--max-lora-rank "${MAX_LORA_RANK}")
  fi
fi

echo "starting vLLM: model=${MODEL_ID} served_as=${SERVED_MODEL_NAME} tp=${TENSOR_PARALLEL_SIZE} max_model_len=${MAX_MODEL_LEN} task=${VLLM_TASK:-generate} lora=${ENABLE_LORA:-false}" >&2

# Extra args (if any) are appended verbatim; the deployment does not pass dev
# flags. exec so vLLM is PID 1 and receives signals for clean shutdown.
exec python3 -m vllm.entrypoints.openai.api_server "${args[@]}" "$@"
