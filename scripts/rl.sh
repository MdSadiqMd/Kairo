#!/usr/bin/env bash
set -euo pipefail

TARGET="local"
CONTEXT="kairo-cloud-local"
NAMESPACE="kairo"
JOB_NAME="online-rl-manual"
MODE="job"
UPDATER="lora"
EVAL_MODE="synthetic"
EVAL_N="10"
EVAL_PASS_RATE="1.0"
MODEL="reasoner-candidate"
ROLE="reasoner"
BASE_MODEL="Qwen/Qwen2.5-0.5B-Instruct"
OUTPUT_DIR="/tmp/online-rl/adapter"
OUTPUT_URI="s3://kairo-cloud-local-checkpoints/online-rl/candidate.json"
RESULT_URI="s3://kairo-cloud-local-eval-results/online-rl/result.json"
ADAPTER_URI="s3://kairo-cloud-local-checkpoints/online-rl/adapters/candidate"
REGISTRY_TABLE="kairo-cloud-local-model-registry"
USE_QLORA="false"
LORA_R="4"
LORA_ALPHA="8"
LORA_DROPOUT="0.05"
LR="2e-5"
MAX_STEPS="1"
MAX_SEQ_LEN="128"
MIN_N="1"
POLICY_STEP="0"
REQUEST_CPU="2"
REQUEST_MEMORY="8Gi"
LIMIT_CPU="6"
LIMIT_MEMORY="16Gi"
TIMEOUT_SECONDS="1200"
HF_HOME_DIR="/tmp/hf-cache"
CANDIDATES_JSON='[{"group_id":"g1","reward":1.0,"policy_step":0,"request_id":"r1","prompt_raw":"[{\"role\":\"user\",\"content\":\"Say ok\"}]","output_raw":"ok"},{"group_id":"g1","reward":0.2,"policy_step":0,"request_id":"r2","prompt_raw":"[{\"role\":\"user\",\"content\":\"Say ok\"}]","output_raw":"not ok"}]'
WAIT="true"
DRY_RUN="false"
VERIFY="true"

usage() {
  cat <<'EOF'
Usage:
  scripts/rl.sh --local [options]
  scripts/rl.sh --local --pod [options]

Target:
  --local                 Use local MiniStack context (default).
  --context <name>        Kubernetes context override.
  --namespace <name>      Namespace. Default: kairo.

Execution:
  --job-name <name>       Job/Pod name. Default: online-rl-manual.
  --pod                   Create a one-shot Pod instead of a Job.
  --timeout <seconds>     Fail-fast monitor cap. Default: 1200 (20m).
  --no-wait               Submit only.
  --dry-run               Print rendered manifest.
  --no-verify             Skip post-run S3/proof verification.

RL configuration:
  --updater <type>        lora|artifact-only. Default: lora.
  --eval-mode <mode>      synthetic|real. Default: synthetic.
  --eval-n <n>            Synthetic eval item count. Default: 10.
  --eval-pass-rate <f>    Synthetic pass rate. Default: 1.0.
  --model <name>          Served candidate model name. Default: reasoner-candidate.
  --role <role>           Registry role. Default: reasoner.
  --base-model <hf-id>    Base model. Default: Qwen/Qwen2.5-0.5B-Instruct.
  --policy-step <n>       Current policy step. Default: 0.
  --candidates-json <js>  Inline scored candidates JSON.

LoRA/training:
  --use-qlora <bool>      Default: false for local CPU.
  --lora-r <n>            Default: 4.
  --lora-alpha <n>        Default: 8.
  --lora-dropout <f>      Default: 0.05.
  --lr <f>                Default: 2e-5.
  --max-steps <n>         Default: 1.
  --max-seq-len <n>       Default: 128.
  --min-n <n>             Promotion gate min_n. Default: 1.

Resources:
  --request-cpu <v>       Default: 2.
  --request-memory <v>    Default: 8Gi.
  --limit-cpu <v>         Default: 6.
  --limit-memory <v>      Default: 16Gi.
  --hf-home <path>        Default: /tmp/hf-cache.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --local) TARGET="local"; CONTEXT="kairo-cloud-local"; shift ;;
    --) shift ;;
    --context) CONTEXT="$2"; shift 2 ;;
    --namespace) NAMESPACE="$2"; shift 2 ;;
    --job-name) JOB_NAME="$2"; shift 2 ;;
    --pod) MODE="pod"; shift ;;
    --timeout) TIMEOUT_SECONDS="$2"; shift 2 ;;
    --no-wait) WAIT="false"; shift ;;
    --dry-run) DRY_RUN="true"; shift ;;
    --no-verify) VERIFY="false"; shift ;;
    --updater) UPDATER="$2"; shift 2 ;;
    --eval-mode) EVAL_MODE="$2"; shift 2 ;;
    --eval-n) EVAL_N="$2"; shift 2 ;;
    --eval-pass-rate) EVAL_PASS_RATE="$2"; shift 2 ;;
    --model) MODEL="$2"; shift 2 ;;
    --role) ROLE="$2"; shift 2 ;;
    --base-model) BASE_MODEL="$2"; shift 2 ;;
    --policy-step) POLICY_STEP="$2"; shift 2 ;;
    --candidates-json) CANDIDATES_JSON="$2"; shift 2 ;;
    --use-qlora) USE_QLORA="$2"; shift 2 ;;
    --lora-r) LORA_R="$2"; shift 2 ;;
    --lora-alpha) LORA_ALPHA="$2"; shift 2 ;;
    --lora-dropout) LORA_DROPOUT="$2"; shift 2 ;;
    --lr) LR="$2"; shift 2 ;;
    --max-steps) MAX_STEPS="$2"; shift 2 ;;
    --max-seq-len) MAX_SEQ_LEN="$2"; shift 2 ;;
    --min-n) MIN_N="$2"; shift 2 ;;
    --request-cpu) REQUEST_CPU="$2"; shift 2 ;;
    --request-memory) REQUEST_MEMORY="$2"; shift 2 ;;
    --limit-cpu) LIMIT_CPU="$2"; shift 2 ;;
    --limit-memory) LIMIT_MEMORY="$2"; shift 2 ;;
    --hf-home) HF_HOME_DIR="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "${TARGET}" != "local" ]]; then
  echo "only --local is currently supported by this helper" >&2
  exit 2
fi

manifest="$(mktemp)"
cleanup() { rm -f "${manifest}"; }
trap cleanup EXIT

export JOB_NAME MODE NAMESPACE UPDATER EVAL_MODE EVAL_N EVAL_PASS_RATE MODEL ROLE BASE_MODEL
export OUTPUT_DIR OUTPUT_URI RESULT_URI ADAPTER_URI REGISTRY_TABLE USE_QLORA LORA_R LORA_ALPHA
export LORA_DROPOUT LR MAX_STEPS MAX_SEQ_LEN MIN_N POLICY_STEP CANDIDATES_JSON REQUEST_CPU
export REQUEST_MEMORY LIMIT_CPU LIMIT_MEMORY HF_HOME_DIR

python - <<'PY' > "${manifest}"
import json
import os

name = os.environ["JOB_NAME"]
mode = os.environ["MODE"]
pod_spec = {
    "metadata": {"labels": {"app.kubernetes.io/name": "online-rl-trainer", "app.kubernetes.io/part-of": "Kairo"}},
    "spec": {
        "restartPolicy": "Never",
        "serviceAccountName": "eval-runner",
        "securityContext": {
            "runAsNonRoot": True,
            "runAsUser": 10001,
            "runAsGroup": 10001,
            "fsGroup": 10001,
            "seccompProfile": {"type": "RuntimeDefault"},
        },
        "containers": [{
            "name": "online-rl-trainer",
            "image": "host.docker.internal:4566/kairo/training:local",
            "imagePullPolicy": "IfNotPresent",
            "command": ["python", "-m", "kairo_ml.rl.online_trainer"],
            "securityContext": {"allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]}},
            "envFrom": [
                {"configMapRef": {"name": "kairo-rl-config"}},
                {"configMapRef": {"name": "kairo-zk-config"}},
            ],
            "env": [
                {"name": "HF_HOME", "value": os.environ["HF_HOME_DIR"]},
                {"name": "TRANSFORMERS_CACHE", "value": os.environ["HF_HOME_DIR"]},
                {"name": "ONLINE_RL_MODEL", "value": os.environ["MODEL"]},
                {"name": "ONLINE_RL_ROLE", "value": os.environ["ROLE"]},
                {"name": "ONLINE_RL_UPDATER", "value": os.environ["UPDATER"]},
                {"name": "ONLINE_RL_EVAL_MODE", "value": os.environ["EVAL_MODE"]},
                {"name": "ONLINE_RL_EVAL_N", "value": os.environ["EVAL_N"]},
                {"name": "ONLINE_RL_EVAL_PASS_RATE", "value": os.environ["EVAL_PASS_RATE"]},
                {"name": "ONLINE_RL_BASE_MODEL", "value": os.environ["BASE_MODEL"]},
                {"name": "ONLINE_RL_OUTPUT_DIR", "value": os.environ["OUTPUT_DIR"]},
                {"name": "ONLINE_RL_OUTPUT_URI", "value": os.environ["OUTPUT_URI"]},
                {"name": "ONLINE_RL_RESULT_URI", "value": os.environ["RESULT_URI"]},
                {"name": "ONLINE_RL_ADAPTER_S3_URI", "value": os.environ["ADAPTER_URI"]},
                {"name": "MODEL_REGISTRY_TABLE", "value": os.environ["REGISTRY_TABLE"]},
                {"name": "ONLINE_RL_USE_QLORA", "value": os.environ["USE_QLORA"]},
                {"name": "ONLINE_RL_LORA_R", "value": os.environ["LORA_R"]},
                {"name": "ONLINE_RL_LORA_ALPHA", "value": os.environ["LORA_ALPHA"]},
                {"name": "ONLINE_RL_LORA_DROPOUT", "value": os.environ["LORA_DROPOUT"]},
                {"name": "ONLINE_RL_LR", "value": os.environ["LR"]},
                {"name": "ONLINE_RL_MAX_STEPS", "value": os.environ["MAX_STEPS"]},
                {"name": "ONLINE_RL_MAX_SEQ_LEN", "value": os.environ["MAX_SEQ_LEN"]},
                {"name": "ONLINE_RL_MIN_N", "value": os.environ["MIN_N"]},
                {"name": "ONLINE_RL_POLICY_STEP", "value": os.environ["POLICY_STEP"]},
                {"name": "ONLINE_RL_CANDIDATES_JSON", "value": os.environ["CANDIDATES_JSON"]},
            ],
            "resources": {
                "requests": {"cpu": os.environ["REQUEST_CPU"], "memory": os.environ["REQUEST_MEMORY"]},
                "limits": {"cpu": os.environ["LIMIT_CPU"], "memory": os.environ["LIMIT_MEMORY"]},
            },
        }],
    },
}
if mode == "pod":
    doc = {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": name, "namespace": os.environ["NAMESPACE"], "labels": pod_spec["metadata"]["labels"]}, "spec": pod_spec["spec"]}
else:
    doc = {"apiVersion": "batch/v1", "kind": "Job", "metadata": {"name": name, "namespace": os.environ["NAMESPACE"], "labels": pod_spec["metadata"]["labels"]}, "spec": {"backoffLimit": 0, "template": pod_spec}}
print(json.dumps(doc, indent=2))
PY

if [[ "${DRY_RUN}" == "true" ]]; then
  cat "${manifest}"
  exit 0
fi

kind="job"
selector="job-name=${JOB_NAME}"
if [[ "${MODE}" == "pod" ]]; then
  kind="pod"
  selector="app.kubernetes.io/name=online-rl-trainer,app.kubernetes.io/part-of=Kairo"
fi

kubectl --context "${CONTEXT}" -n "${NAMESPACE}" delete "${kind}" "${JOB_NAME}" --ignore-not-found
kubectl --context "${CONTEXT}" -n "${NAMESPACE}" apply -f "${manifest}"

if [[ "${WAIT}" != "true" ]]; then
  exit 0
fi

end=$((SECONDS + TIMEOUT_SECONDS))
pod=""
while [[ ${SECONDS} -lt ${end} ]]; do
  if [[ "${MODE}" == "pod" ]]; then
    pod="${JOB_NAME}"
  else
    pod=$(kubectl --context "${CONTEXT}" -n "${NAMESPACE}" get pod -l "${selector}" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
  fi
  if [[ -n "${pod}" ]]; then
    phase=$(kubectl --context "${CONTEXT}" -n "${NAMESPACE}" get pod "${pod}" -o jsonpath='{.status.phase}' 2>/dev/null || true)
    reason=$(kubectl --context "${CONTEXT}" -n "${NAMESPACE}" get pod "${pod}" -o jsonpath='{.status.containerStatuses[0].state.waiting.reason}{.status.containerStatuses[0].state.terminated.reason}' 2>/dev/null || true)
    echo "${JOB_NAME}: phase=${phase:-unknown} reason=${reason:-}"
    if [[ "${phase}" == "Succeeded" ]]; then
      kubectl --context "${CONTEXT}" -n "${NAMESPACE}" logs "${pod}" --tail=120 || true
      break
    fi
    if [[ "${phase}" == "Failed" || "${reason}" == "Error" || "${reason}" == "OOMKilled" || "${reason}" == "CrashLoopBackOff" || "${reason}" == "ImagePullBackOff" ]]; then
      kubectl --context "${CONTEXT}" -n "${NAMESPACE}" logs "${pod}" --tail=200 || true
      exit 1
    fi
  fi
  sleep 20
done

if [[ -z "${pod}" || "$(kubectl --context "${CONTEXT}" -n "${NAMESPACE}" get pod "${pod}" -o jsonpath='{.status.phase}' 2>/dev/null || true)" != "Succeeded" ]]; then
  echo "${JOB_NAME} timed out after ${TIMEOUT_SECONDS}s" >&2
  [[ -n "${pod}" ]] && kubectl --context "${CONTEXT}" -n "${NAMESPACE}" logs "${pod}" --tail=200 || true
  exit 124
fi

if [[ "${VERIFY}" == "true" ]]; then
  AWS_ENDPOINT_URL=http://localhost:4566 AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_REGION=us-east-1 \
    aws --endpoint-url=http://localhost:4566 s3 ls s3://kairo-cloud-local-checkpoints/online-rl/adapters/candidate/ >/dev/null
  AWS_ENDPOINT_URL=http://localhost:4566 AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_REGION=us-east-1 \
    aws --endpoint-url=http://localhost:4566 s3 cp s3://kairo-cloud-local-eval-results/online-rl/result.json - >/tmp/kairo-rl-result.json
  grep -q '"accepted": true' /tmp/kairo-rl-result.json
  proof_id=$(python - <<'PY'
import json
print(json.load(open('/tmp/kairo-rl-result.json')).get('proof_job_id', ''))
PY
)
  if [[ -n "${proof_id}" ]]; then
    AWS_ENDPOINT_URL=http://localhost:4566 AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_REGION=us-east-1 \
      aws --endpoint-url=http://localhost:4566 dynamodb get-item \
        --table-name kairo-cloud-local-proof-receipts \
        --key "{\"proof_id\":{\"S\":\"${proof_id}\"}}" | grep -q '"attested"'
  fi
fi
