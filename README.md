# Kairo

Kairo runs open-weight LLMs on AWS GPUs and then makes them better over time —
serve a model, learn from how it's actually used, gate every candidate behind
private statistical evals, cryptographically witness the training loop, and
redeploy. It is not a wrapper around a single endpoint and not a Terraform demo;
it is the full serve → learn → gate → prove loop on infrastructure you own.

Production target: **[Qwen3-32B](https://huggingface.co/Qwen/Qwen3-32B)** as the
reasoner (BF16, tensor-parallel across 4×A10G on one `g5.12xlarge`) and
**[Qwen3-8B](https://huggingface.co/Qwen/Qwen3-8B)** as the fast path, both served
by vLLM, with per-request thinking budgets and chain-of-thought stripped from the
stream. The loop is modeled on how
[Cursor does real-time RL](https://cursor.com/blog/real-time-rl-for-composer):
collect implicit reward from what users do, run a QLoRA policy update, gate it
through private evals (Wilson CI, paired bootstrap, minimum detectable effect),
and redeploy.

The full design is [`docs/final_plan.md`](docs/final_plan.md); the pitch and
diagrams are in [`docs/PITCH.md`](docs/PITCH.md). This README covers what the
repository is, where each capability lives, and — honestly — what is verified
versus what is designed but not yet proven on real AWS.

## The loop

1. **Serve** — A FastAPI router is the only public service. It authenticates the
   tenant, enforces quota and a token budget, classifies the request for safety,
   picks a route/model/thinking-budget, calls the internal vLLM deployment, and
   streams **final answer tokens only** — never raw chain-of-thought. `deep`/`max`
   modes sample N candidates and rerank with a verifier. Qwen3-32B is served
   tensor-parallel across 4 GPUs because ~64 GB of weights will not fit on a 24 GB
   A10G.

2. **Learn** — Every request emits a structured event (hashes and metadata by
   default; raw text only under consent). Events flow Kinesis → Go ingestor → S3,
   are redacted for PII/secrets/high-entropy credentials, consent-filtered, and
   scored into an implicit reward. GRPO computes group-relative advantages, drops
   stale off-policy samples, and drives a QLoRA update.

3. **Gate** — No checkpoint, adapter, prompt, or tool policy reaches production
   without passing private, statistically-sound evals: Wilson score intervals
   (not raw pass rates), paired bootstrap against the current prod model on the
   same items/seeds, and a sample size derived from a target minimum detectable
   effect. Safety and over-refusal gates are one-sided and strict.

4. **Prove** — Every reward computation, filter decision, GRPO advantage, and gate
   verdict is witnessed: inputs canonicalized to JSON, hashed with SHA-256, and
   committed. A proof worker re-executes the same logic on the committed inputs
   and attests that outputs match, storing a receipt in DynamoDB. This is the
   integrity story for the RL loop — whoever controls the reward or the gate
   controls what the model learns, so each step is made tamper-evident.

## Layout

```
libs/kairo_common/            Shared Python primitives (config, logging, events, errors)
services/router/              FastAPI router — the only public entry point (Python)
services/safety_classifier/   Input/output/tool-action policy classifier (Python)
services/eval_api/            Eval registry + promotion-gate API (Python)
services/log_ingestor/        High-throughput event ingestor (Go)
ml/src/kairo_ml/              evals+gate, redaction/manifests, training, rl (+online loop),
                              rl_envs, sandbox, agent_runtime, rag, cost, proofs (Python)
ml/proofs/risc0/              RISC Zero zkVM host + guests (Rust)
cmd/qctl/ + internal/         Lifecycle orchestrator: up/down/verify/sweep (Go, §20)
infra/terraform/              19 modules + per-env roots (local, dev, staging, prod)
infra/kubernetes/             Base, inference, RL overlay, observability, evals manifests
infra/docker/                 vLLM serving images + entrypoints
scripts/                      start.sh / stop.sh / build_image.sh + eval/promotion CLIs
docs/                         architecture, security, data-governance, evals, operations, decisions
```

Language split follows the job: **Go** for the devops-heavy control plane
(lifecycle orchestration, high-throughput ingestion), **Python** (managed with
[uv](https://docs.astral.sh/uv/)) for services and ML, **Rust** for the RISC Zero
proof guests, **Terraform/HCL** for infrastructure.

## Quickstart (local — the verified path)

The local stack is real: native `linux/arm64` vLLM CPU serving
`Qwen/Qwen2.5-0.5B-Instruct` on a k3s node under [MiniStack](https://ministack.org),
with the same router/safety/eval/RL/proof code paths as prod — only the model,
device, and a handful of tfvars differ (see the parity table in
[`docs/local.md`](docs/local.md)).

```bash
uv sync --all-packages --dev     # install the Python workspace
make test                        # Python tests
make go-test                     # Go tests
make check                       # ruff + mypy + pytest + go vet + go test
```

Run the router alone against a mock upstream:

```bash
uv run --package kairo-router uvicorn router.main:app --reload --port 8080
```

Bring up the full local platform (router, safety, ARM64 vLLM CPU, RL, proofs):

```bash
just capability-check   # fail-fast Docker/MiniStack capacity check
just local-up           # full local stack
just local-verify       # router -> safety -> vLLM smoke request
just rl-local           # one fail-fast CPU LoRA update + proof verification
just rl-artifacts       # inspect latest adapter artifact manifest
just proofs             # inspect proof receipts
```

Pause without deleting data/images/model cache, then resume from cache:

```bash
just local-down         # scale deployments to zero, suspend cronjobs
just local-up-no-images # resume using cached images/model weights
just local-destroy      # destructive MiniStack/Terraform teardown
```

Custom local RL runs need no code edits:

```bash
just rl --local --max-steps 1 --lora-r 4 --lora-alpha 8 --timeout 1200
just rl-dry-run --max-steps 1   # render the Kubernetes Job manifest
```

## Deploy (AWS)

The intended contract is two commands — **scripts orchestrate, Terraform owns**
(§20). Every AWS resource is declared in Terraform; the Go orchestrator `qctl`
only sequences `terraform apply/destroy`, image builds, the Kubernetes rollout,
and verification.

```bash
./scripts/start.sh --env dev [--model model-32b] [--replicas 2] [--with-rl]
./scripts/stop.sh  --env dev [--delete-data]

# preferred just wrappers
just prod-preflight     # AWS credentials, region, GPU quota, Docker capacity
just prod-plan          # Terraform plan for prod with RL enabled
just prod-up            # full prod stack with RL
just prod-up-no-rl      # prod stack without RL
just prod-down          # guarded destructive prod teardown
```

> **Prod is not yet deploy-verified.** The infra, manifests, and code all exist
> and `terraform validate` passes in every environment, but the last full-codebase
> audit ([`docs/decisions.md`](docs/decisions.md), 2026-07-17) found `qctl up` does
> not stand up a working prod cluster as written — there is no helm/add-on phase
> (Karpenter, NVIDIA device plugin, KEDA, Prometheus Operator, External Secrets,
> LB controller, EFS/FSx CSI are installed by nothing), the model-registry GSI key
> type and the `adapter-storage` PVC StorageClass are wrong for real AWS, and the
> RL flywheel has no live reward source. Treat `prod-up` as work-in-progress and
> read the audit before spending GPU credits. The dev stack as declared burns
> **~$386/day**, ~83% of it warm idle GPUs — turn it off when idle.

## Implementation map — what, and where

| Capability | Where it lives | Plan § |
|---|---|---|
| **Shared primitives** — JSON logging, event schema, error taxonomy, request-id propagation | `libs/kairo_common/` | §12.2, §18.2, §24 |
| **Router** — OpenAI-compatible API, auth, quota + context guard | `services/router/src/router/{main,auth,quota,schemas}.py` | §11.1–11.2 |
| **Thinking budgets** (fast/normal/deep/max → tokens, candidates, verifier) | `router/budgets.py` | §11.3 |
| **Model routing** (deterministic, auditable rule engine) | `router/routing.py` | §11.4 |
| **SSE streaming with chain-of-thought stripping** | `router/streaming.py` | §11.6, §15.2 |
| **Verifier / candidate reranking** (test-time compute) | `router/verifier.py`, `router/pipeline.py` | §10, §11.3 |
| **Model registry** (file for dev, DynamoDB for prod; promoted-only) | `router/model_registry.py`, `router/registry_dynamodb.py` | §9.2, §13.4 |
| **Event emission** (stdout / Kinesis / SQS) | `router/telemetry.py`, `router/event_sinks_aws.py` | §12.2 |
| **Safety classifier** — input / output / tool-action policy | `services/safety_classifier/src/safety_classifier/` | §15.2–15.3 |
| **Eval registry + runner + scorers** | `ml/src/kairo_ml/evals/{registry,runners,scorers}.py`, `ml/evals/registry/*.yaml` | §13.1–13.3 |
| **Statistical promotion gate** — Wilson CI, paired bootstrap, MDE power | `ml/src/kairo_ml/evals/{statistics,gate,report}.py` | §13.4–13.5 |
| **Promotion / rollback** (registry state, gate-enforced) | `ml/src/kairo_ml/evals/promote.py`, `scripts/{promote,rollback}_model.py` | §13.4, §17.3 |
| **Redaction pipeline** (PII/secret/entropy, consent + license gates) | `ml/src/kairo_ml/data/redaction.py` | §12.3, §19.4 |
| **Dataset manifests + dedup + contamination** | `ml/src/kairo_ml/data/manifests.py` | §13.6, §14.5 |
| **Real-time RL control path** — implicit reward + hacking guards, GRPO advantages, cycle runner, per-cycle gate + staleness guard | `ml/src/kairo_ml/rl/{rewards,aggregate_rewards,grpo,online_loop,online_trainer}.py` | §4 |
| **Training plane** — LoRA/QLoRA SFT, DPO/IPO/KTO, reward/verifier/critic, distillation, quantization, MLflow, `kairo-train` CLI | `ml/src/kairo_ml/training/` | §14 |
| **Execution sandbox** — ephemeral fs, killpg timeouts, traversal guard, net-deny, git reinit | `ml/src/kairo_ml/sandbox/` | §13.3, §15.1 |
| **RL environments** — code_repair, math (sympy), sql (sqlite), tool_use, browser + validators | `ml/src/kairo_ml/rl_envs/` | §15.1 |
| **Agent runtime** — durable event-sourced workflow, typed tools, autonomy gate, checkpoints, planner/worker loop | `ml/src/kairo_ml/agent_runtime/` | §15.2 |
| **Cryptographic proofs** — witness capture, canonical JSON, fixed-point, spec hashes, HashCommit backend, RISC Zero backend | `ml/src/kairo_ml/proofs/`, `ml/proofs/risc0/` | §19 |
| **Hybrid RAG** — chunker, contextualizer, BM25, vector index, RRF, reranker, untrusted-content assembly, retrieval evals | `ml/src/kairo_ml/rag/` | §11.7 |
| **Cache-aware routing** (consistent-hash prefix affinity + failover) | `router/cache_routing.py` | §11.5 |
| **Cost / unit economics** — two-regime model, roofline $/token floor, per-route pricing + live tracker | `ml/src/kairo_ml/cost/` | §16 |
| **Log ingestor** (Kinesis→S3, batch/gzip/partition, malformed-drop) | `services/log_ingestor/`, `internal/ingestor/` | §12, §22.6 |
| **Lifecycle orchestrator** `qctl` (preflight/up/down/verify/sweep) | `cmd/qctl/`, `internal/{orchestrator,preflight,config,command}/` | §20 |
| **vLLM serving images** (GPU TP flags + CPU/arm64 local; dev endpoints blocked) | `infra/docker/vllm.Dockerfile`, `vllm-cpu.Dockerfile`, entrypoints | §10.1–10.2, §24 |
| **§10.6 distributed serving** — the "one knob" TP=4 module + preconditions | `infra/terraform/modules/model_inference/` | §10.6 |
| **K8s inference** — vLLM (TP=4, /dev/shm, request==limit), router, safety, KEDA, HPA, PDB | `infra/kubernetes/inference/` | §10.3, §9.7 |
| **Terraform infra** — 19 modules across 4 env roots (local/dev/staging/prod) | `infra/terraform/modules/`, `environments/*/` | §9 |
| **CI/CD** — lint, test, build-images, tf-plan (tflint+OPA), deploy-dev, eval-candidate, promote | `.github/workflows/` | §17.1 |

## Status — verified vs. designed

The honest split, from the code-as-source-of-truth audit in
[`docs/decisions.md`](docs/decisions.md):

**Verified real (local, tested):**

- Router core — auth, quota, token budgets, deterministic routing, CoT-strip SSE
  streaming, async event emission.
- Deterministic rule-based safety classifier (input/output/tool-action, fail-closed).
- Eval gate — Wilson CI, paired bootstrap, MDE power; the statistical gate is the
  centerpiece and is tested.
- Redaction (regex + entropy) and dataset manifest dedup/contamination library.
- Go log-ingestor internals; LoRA/QLoRA + DPO training via TRL/PEFT (weights really
  update); the execution sandbox and RL environment validators.
- HashCommit witness/commitment chain including full gate re-execution, and a local
  end-to-end RL cycle producing **attested** proof receipts.
- `just local-up` → `just local-verify` → `just rl-local` complete end-to-end: real
  CPU LoRA update, adapter artifact uploaded to MiniStack S3, RL cycle attested in
  DynamoDB.

**Designed / implemented but not yet in the live path:**

- **Prod bring-up** — infra + manifests + code exist and `terraform validate`
  passes everywhere, but `qctl up` has open P0 blockers on real AWS (no cluster
  add-on/helm phase, DynamoDB GSI key type, EFS StorageClass, add-on CRDs). Not yet
  deploy-verified. See the 2026-07-17 audit.
- **RL flywheel end-to-end in prod** — there is no live reward source yet (no
  feedback endpoint; raw-capture/consent flags set only in the local overlay), so
  the prod aggregator emits no candidates until that is wired.
- **"ZK" proofs today = attestation.** The HashCommit backend (trusted Python
  re-execution) is what runs and produces `attested` receipts. The RISC Zero host +
  guests exist in Rust but no running path builds/ships the host binary, so no
  environment yet produces `verified` receipts.
- **Hybrid RAG** and **cache-aware routing** are complete and tested libraries but
  are not yet called from the router request path.

**Explicitly out of scope:** §10.7 235B multi-node serving (EFA/LWS), blue-green
warm-standby rollout, dynamic production LoRA loading (security), broad agent
internet access.

## Verification

```bash
make check                                                   # ruff + mypy + pytest + go vet + go test
terraform -chdir=infra/terraform/environments/dev validate   # Success (all 4 envs validate)
kubectl kustomize infra/kubernetes                            # base overlay builds
just local-up && just local-verify && just rl-local          # full local stack + RL + proof receipt
```

- Terraform: `fmt` clean, `validate` green in local/dev/staging/prod.
- Go: `build`/`vet` clean; stdlib-only default build, AWS adapters behind `-tags aws`.
- Python: `mypy` clean. **`ruff` is currently red** (32 lint errors, mostly
  line-length in tests) — `make check`/CI lint fails until they are cleared. Last
  recorded suite sizes were 258 Python + 42 Go tests (2026-07-17); run `make check`
  after `uv sync` for current numbers.

See [`docs/architecture.md`](docs/architecture.md) for the plane map,
[`docs/operations.md`](docs/operations.md) for run/rollback/FSx procedures,
[`docs/security.md`](docs/security.md) for the data-perimeter posture,
[`docs/evals.md`](docs/evals.md) for the gate, and
[`docs/cryptography_rl.md`](docs/cryptography_rl.md) for the proof design.

## License

MIT — see [`LICENSE`](LICENSE).
</content>
</invoke>
