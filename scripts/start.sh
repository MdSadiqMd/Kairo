#!/usr/bin/env bash
# start.sh — zero to inference URL.
#
# THIN wrapper: it builds the Go lifecycle orchestrator (qctl) and forwards its
# arguments to `qctl up`. All orchestration — preflight, terraform apply, image
# build/push, Kubernetes rollout, RL setup, verify — lives in qctl so that this
# script and the deploy-dev.yml CI job run the exact same path (CI parity).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
QCTL_BIN="${ROOT}/bin/qctl"

usage() {
  cat <<'EOF'
start.sh — bring Kairo up (thin wrapper over `qctl up`).

Usage:
  scripts/start.sh --env <dev|staging|prod> [options]
  scripts/start.sh --prod [options]
  scripts/start.sh --local [options]

Options:
  --env <name>       Target environment (dev|staging|prod). Required unless --prod/--local.
  --prod             Run the production AWS flow (implies --env prod).
  --local            Run against MiniStack local emulator (implies --env local).
  --model <name>     Model to serve (e.g. model-32b). Default: qctl default.
                     For --local, defaults to MODEL_PROVIDER/Model-0.6B (CPU-friendly).
  --replicas <n>     model_replicas — the one knob. Default: qctl default.
  --with-rl          Also stand up the RL / reward pipeline.
  --plan-only        Print the terraform plan and exit; change nothing.
  --skip-images      Skip building/pushing images (infra-only iteration).
  -h, --help         Show this help.

Examples:
  scripts/start.sh --env dev
  scripts/start.sh --env dev --model model-32b --replicas 2 --with-rl
  scripts/start.sh --env dev --plan-only
  scripts/start.sh --local
  scripts/start.sh --local --model MODEL_PROVIDER/Model-0.6B

On success qctl prints the inference URL, API-key secret ARN, Grafana URL, and
kube context, and writes them to outputs.json.
EOF
}

have_env=false
is_local=false
is_prod=false
args=()

for arg in "$@"; do
  case "${arg}" in
    -h|--help)
      usage
      exit 0
      ;;
    --local)
      is_local=true
      args+=("${arg}")
      ;;
    --prod)
      is_prod=true
      args+=("${arg}")
      ;;
    --env)
      have_env=true
      args+=("${arg}")
      ;;
    --env=*)
      have_env=true
      args+=("${arg}")
      ;;
    *)
      args+=("${arg}")
      ;;
  esac
done

if [[ "${is_local}" == true && "${is_prod}" == true ]]; then
  echo "error: --local and --prod are mutually exclusive" >&2
  exit 2
fi

if [[ "${is_local}" == true ]]; then
  have_env=true

  export AWS_ENDPOINT_URL="http://localhost:4566"
  export AWS_ACCESS_KEY_ID="test"
  export AWS_SECRET_ACCESS_KEY="test"
  export AWS_DEFAULT_REGION="us-east-1"
  export AWS_REGION="us-east-1"
fi

if [[ "${is_prod}" == true ]]; then
  have_env=true
fi

if [[ "${have_env}" != true ]]; then
  echo "error: --env is required (dev|staging|prod) or use --prod/--local" >&2
  echo >&2
  usage >&2
  exit 2
fi

echo "==> building qctl" >&2
( cd "${ROOT}" && go build -o "${QCTL_BIN}" ./cmd/qctl )

echo "==> qctl up ${args[*]}" >&2
exec "${QCTL_BIN}" up "${args[@]}"
