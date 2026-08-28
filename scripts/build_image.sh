#!/usr/bin/env bash
# build_image.sh — build (and optionally push) one service image to ECR.
#
# Knows the Dockerfile and build context for each service so start.sh/qctl and
# build-images.yml can build consistently. Router builds from the repo root (uv
# workspace); vLLM builds from infra/docker with the vllm.Dockerfile.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

SERVICE=""
TAG="latest"
REGISTRY=""
PUSH=false
PLATFORM="linux/amd64"
FALLBACK_DOCKERFILE=""

usage() {
  cat <<'EOF'
build_image.sh — build/push a Kairo service image.

Usage:
  scripts/build_image.sh --service <name> [options]

Services:
  router | vllm | vllm-cpu | safety | log-ingestor | eval-runner | training | proof-worker

Options:
  --service <name>     Which image to build (required).
  --tag <tag>          Image tag. Default: latest.
  --registry <uri>     ECR registry (e.g. 123456789012.dkr.ecr.us-west-2.amazonaws.com).
                       Default: local build only, image tagged kairo/<service>:<tag>.
  --push               Push to the registry after building (requires --registry).
  --platform <p>       Build platform. Default: linux/amd64.
  -h, --help           Show this help.

Examples:
  scripts/build_image.sh --service router
  scripts/build_image.sh --service vllm --registry 123.dkr.ecr.us-west-2.amazonaws.com --tag v1 --push
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --service) SERVICE="$2"; shift 2 ;;
    --service=*) SERVICE="${1#*=}"; shift ;;
    --tag) TAG="$2"; shift 2 ;;
    --tag=*) TAG="${1#*=}"; shift ;;
    --registry) REGISTRY="$2"; shift 2 ;;
    --registry=*) REGISTRY="${1#*=}"; shift ;;
    --platform) PLATFORM="$2"; shift 2 ;;
    --platform=*) PLATFORM="${1#*=}"; shift ;;
    --push) PUSH=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "error: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "${SERVICE}" ]]; then
  echo "error: --service is required" >&2
  usage >&2
  exit 2
fi

case "${SERVICE}" in
  router)       DOCKERFILE="${ROOT}/services/router/Dockerfile";            CONTEXT="${ROOT}" ;;
  vllm)         DOCKERFILE="${ROOT}/infra/docker/vllm.Dockerfile";          CONTEXT="${ROOT}/infra/docker" ;;
  vllm-cpu)     DOCKERFILE="${ROOT}/infra/docker/vllm-cpu.Dockerfile";      FALLBACK_DOCKERFILE="${ROOT}/infra/docker/local-openai-server.Dockerfile"; CONTEXT="${ROOT}/infra/docker" ;;
  safety)       DOCKERFILE="${ROOT}/services/safety_classifier/Dockerfile"; CONTEXT="${ROOT}" ;;
  log-ingestor) DOCKERFILE="${ROOT}/services/log_ingestor/Dockerfile";      CONTEXT="${ROOT}" ;;
  eval-runner)  DOCKERFILE="${ROOT}/services/eval_api/Dockerfile";          CONTEXT="${ROOT}" ;;
  training)
    DOCKERFILE="${ROOT}/infra/docker/training.Dockerfile"
    if [[ "${PLATFORM}" == "linux/arm64" && "${REGISTRY}" == *":4566" ]]; then
      DOCKERFILE="${ROOT}/infra/docker/training-cpu.Dockerfile"
    fi
    CONTEXT="${ROOT}"
    ;;
  agent-worker) DOCKERFILE="${ROOT}/infra/docker/agent-worker.Dockerfile";  CONTEXT="${ROOT}" ;;
  proof-worker) DOCKERFILE="${ROOT}/infra/docker/proof-worker.Dockerfile";  CONTEXT="${ROOT}" ;;
  *) echo "error: unknown service '${SERVICE}' (router|vllm|vllm-cpu|safety|log-ingestor|eval-runner|training|agent-worker|proof-worker)" >&2; exit 2 ;;
esac

if [[ ! -f "${DOCKERFILE}" ]]; then
  echo "error: Dockerfile not found for ${SERVICE}: ${DOCKERFILE}" >&2
  exit 1
fi

if [[ -n "${REGISTRY}" ]]; then
  IMAGE="${REGISTRY}/kairo/${SERVICE}:${TAG}"
else
  IMAGE="kairo/${SERVICE}:${TAG}"
fi

if [[ "${PUSH}" == true && -z "${REGISTRY}" ]]; then
  echo "error: --push requires --registry" >&2
  exit 2
fi

build_once() {
  local dockerfile="$1"
  echo "==> building ${IMAGE} (dockerfile=${dockerfile} context=${CONTEXT} platform=${PLATFORM})" >&2
  if [[ "${PUSH}" == true && "${REGISTRY}" == *":4566" ]]; then
    docker buildx build \
      --platform "${PLATFORM}" \
      -f "${dockerfile}" \
      -t "${IMAGE}" \
      --output "type=image,name=${IMAGE},push=true,registry.insecure=true" \
      "${CONTEXT}"
  else
    docker build \
      --platform "${PLATFORM}" \
      -f "${dockerfile}" \
      -t "${IMAGE}" \
      "${CONTEXT}"

    if [[ "${PUSH}" == true ]]; then
      echo "==> pushing ${IMAGE}" >&2
      docker push "${IMAGE}"
    fi
  fi
}

if ! build_once "${DOCKERFILE}"; then
  if [[ -z "${FALLBACK_DOCKERFILE}" ]]; then
    exit 1
  fi
  echo "==> primary image failed; falling back to ${FALLBACK_DOCKERFILE}" >&2
  build_once "${FALLBACK_DOCKERFILE}"
fi

echo "${IMAGE}"
