#!/usr/bin/env bash
set -euo pipefail

CONTEXT="kairo-cloud-local"
NAMESPACE="kairo"
TIMEOUT="180s"

refresh_kubeconfig() {
  local node="ministack-eks-${CONTEXT}"
  if ! docker inspect "${node}" >/dev/null 2>&1; then
    return 1
  fi
  if [[ "$(docker inspect -f '{{.State.Running}}' "${node}")" != "true" ]]; then
    docker start "${node}" >/dev/null
  fi
  local tmp merged
  tmp="$(mktemp)"
  merged="$(mktemp)"
  docker exec "${node}" cat /etc/rancher/k3s/k3s.yaml | sed 's#https://127.0.0.1:6443#https://localhost:16443#g' > "${tmp}"
  KUBECONFIG="${tmp}" kubectl config rename-context default "${CONTEXT}" >/dev/null
  mkdir -p "${HOME}/.kube"
  touch "${HOME}/.kube/config"
  kubectl config delete-context "${CONTEXT}" >/dev/null 2>&1 || true
  KUBECONFIG="${tmp}:${HOME}/.kube/config" kubectl config view --flatten > "${merged}"
  mv "${merged}" "${HOME}/.kube/config"
  kubectl config use-context "${CONTEXT}" >/dev/null
  rm -f "${tmp}"
}

usage() {
  cat <<'EOF'
Usage: scripts/local_down.sh [options]

Non-destructively pauses the local Kairo stack. It keeps MiniStack, Terraform
state, Docker images, S3/DynamoDB data, and local model cache intact.

Options:
  --context <name>     Kubernetes context. Default: kairo-cloud-local.
  --namespace <name>   Namespace. Default: kairo.
  --timeout <duration> Rollout wait timeout. Default: 180s.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --context) CONTEXT="$2"; shift 2 ;;
    --namespace) NAMESPACE="$2"; shift 2 ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if ! kubectl --context "${CONTEXT}" get namespace "${NAMESPACE}" >/dev/null 2>&1; then
  refresh_kubeconfig
fi
if ! kubectl --context "${CONTEXT}" get namespace "${NAMESPACE}" >/dev/null 2>&1; then
  echo "local stack already paused: namespace ${NAMESPACE} not found; data/images/model cache preserved"
  exit 0
fi

while read -r cronjob; do
  [[ -z "${cronjob}" ]] && continue
  kubectl --context "${CONTEXT}" -n "${NAMESPACE}" patch "${cronjob}" \
    --type merge -p '{"spec":{"suspend":true}}' >/dev/null
done < <(kubectl --context "${CONTEXT}" -n "${NAMESPACE}" get cronjob -o name 2>/dev/null || true)

kubectl --context "${CONTEXT}" -n "${NAMESPACE}" delete job --all --ignore-not-found >/dev/null || true

kubectl --context "${CONTEXT}" -n "${NAMESPACE}" scale deployment --all --replicas=0

deadline=$((SECONDS + 180))
while [[ ${SECONDS} -lt ${deadline} ]]; do
  running=$(kubectl --context "${CONTEXT}" -n "${NAMESPACE}" get pods \
    --field-selector=status.phase=Running --no-headers 2>/dev/null | wc -l | tr -d ' ')
  pending=$(kubectl --context "${CONTEXT}" -n "${NAMESPACE}" get pods \
    --field-selector=status.phase=Pending --no-headers 2>/dev/null | wc -l | tr -d ' ')
  if [[ "${running}" == "0" && "${pending}" == "0" ]]; then
    echo "local stack paused: workloads scaled to zero; data/images/model cache preserved"
    exit 0
  fi
  sleep 5
done

kubectl --context "${CONTEXT}" -n "${NAMESPACE}" get pods
echo "timed out waiting for local pods to stop after ${TIMEOUT}" >&2
exit 124
