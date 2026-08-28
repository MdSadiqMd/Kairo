#!/usr/bin/env bash
# stop.sh — teardown of every last resource.
#
# THIN wrapper: it builds the Go lifecycle orchestrator (qctl) and forwards its
# arguments to `qctl down`. Teardown ordering (drain Kubernetes -> delete
# Karpenter nodes -> terraform destroy -> data handling -> orphan sweep ->
# cost-stop report) lives in qctl, so nothing is created or destroyed by hand.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
QCTL_BIN="${ROOT}/bin/qctl"

usage() {
  cat <<'EOF'
stop.sh — tear Kairo down (thin wrapper over `qctl down`).

Usage:
  scripts/stop.sh --env <dev|staging|prod> [options]
  scripts/stop.sh --prod [options]
  scripts/stop.sh --local [options]

Options:
  --env <name>       Target environment (dev|staging|prod). Required unless --prod/--local.
  --prod             Tear down the production AWS environment (implies --env prod).
  --local            Tear down MiniStack local environment (implies --env local).
  --delete-data      Also destroy data buckets (datasets, model artifacts).
                     Ignored for audit-log buckets under Object Lock retention.
  --nuke-state       After a successful destroy, remove the terraform state
                     bucket itself (dev only).
  --stop-ministack   Also stop the MiniStack container after teardown (--local only).
  --force            Required for prod; also skips would-block interactive gates.
  -h, --help         Show this help.

Safety: qctl requires typing the environment name to confirm; prod additionally
requires --force plus a second confirmation. The final cost-stop report proves
zero GPU instances, NAT gateways, and ALBs remain.

Examples:
  scripts/stop.sh --env dev
  scripts/stop.sh --env dev --delete-data --nuke-state
  scripts/stop.sh --env prod --force
  scripts/stop.sh --local
  scripts/stop.sh --local --stop-ministack
EOF
}

have_env=false
is_local=false
is_prod=false
stop_ministack=false
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
    --stop-ministack)
      stop_ministack=true
      ;;
    --env|--env=*)
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

echo "==> qctl down ${args[*]}" >&2
"${QCTL_BIN}" down "${args[@]}"

if [[ "${is_local}" == true && "${stop_ministack}" == true ]]; then
  echo "==> stopping ministack" >&2
  ministack stop || ministack --stop || true
fi
