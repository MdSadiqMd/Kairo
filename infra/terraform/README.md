# Kairo — Terraform Infrastructure

Every AWS resource for the platform is declared here. **Scripts orchestrate,
Terraform owns** (§20): `scripts/start.sh` / `scripts/stop.sh` only sequence
`terraform apply` / `destroy`, image builds, Kubernetes rollout, and verification —
no resource is ever created by hand or raw `aws` CLI (the single exception is
bootstrapping the Terraform state bucket itself).

## Layout

```
infra/terraform/
  modules/            # versioned, reusable modules (§9.2)
  environments/
    dev/              # low-cost dev root: main.tf, variables.tf, outputs.tf,
                      # backend.tf, providers.tf, terraform.tfvars.example
    staging/          # full-integration + canary scaffold
    prod/             # multi-AZ, locked-down scaffold (no local applies)
```

## State model (§9.1)

- **Remote backend per environment**: an S3 bucket (versioned, KMS-encrypted) with
  **native S3 state locking** (`use_lockfile`, Terraform >= 1.10). State is isolated
  per environment so a dev apply can never touch prod state.
- Each `environments/<env>` root has its own `backend.tf` and `terraform.tfvars`.
- Prod state access is restricted to the CI deploy role and break-glass; **no local
  applies against prod**.
- The state bucket is the one resource bootstrapped outside Terraform, in
  `start.sh` Phase 0 (KMS-encrypted + versioned before first `apply`).

## Universal tagging (§20)

`providers.tf` sets `default_tags` applying `project`, `env`, `service`, and `model`
to **every** resource. This powers the `stop.sh` tag-based orphan sweep, the
cost-allocation views (§16), and the tflint/OPA "untagged = forbidden" policy check
in CI (§24 win 11). Modules take a `tags` variable that is merged on top; they never
hardcode project/env tags.

## Module dependency order

The dev root wires modules in this order (Terraform's graph enforces it via
references; `iam` sits after `eks` because its IRSA trust policies need the OIDC
provider):

```
kms → network → s3_data_lake → ecr → eks → iam → karpenter → gpu_nodepools →
model_inference → dynamodb → eventing → observability → opensearch → aurora →
waf → security_baseline → sagemaker_mlflow → sagemaker_hyperpod
```

| Module | What it owns |
|---|---|
| `kms` | CMKs (S3, EBS, CloudWatch, DynamoDB, OpenSearch) with rotation |
| `network` | VPC; public / private-app / private-gpu / private-data subnets across 3 AZ; NAT; gateway + interface VPC endpoints. GPU/data subnets have **no IGW route** (§19.5) |
| `s3_data_lake` | Data-lake buckets; KMS-required, TLS-only, Object Lock on audit-logs, lifecycle + Intelligent-Tiering, account Block Public Access |
| `ecr` | Image repos; scan-on-push; lifecycle; pull-through cache (§24 win 9) |
| `eks` | Cluster, OIDC provider, system managed node group, core add-ons |
| `iam` | IRSA roles per service (§19.1) with permission boundaries (§19.5) |
| `karpenter` | Controller IRSA, node role/instance profile, SQS interruption queue + EventBridge rules |
| `gpu_nodepools` | Karpenter NodePools/EC2NodeClasses per workload (rendered YAML) |
| `model_inference` | **The centerpiece** — one-knob Model-32B TP serving (§10.6) |
| `dynamodb` | model-registry, eval-run-metadata, request-metadata, deployment-state (KMS + PITR) |
| `eventing` | Kinesis `inference-events`, SQS redaction/scoring, EventBridge bus |
| `observability` | Managed Prometheus + Grafana, CloudWatch log groups |
| `opensearch` | Private hybrid-RAG domain (BM25 + vector) |
| `aurora` | Serverless v2 Postgres, private |
| `waf` | WebACL (managed rule groups + rate limit) for the ALB |
| `security_baseline` | GuardDuty, Security Hub, CloudTrail (training-bucket data events), Macie |
| `sagemaker_mlflow` | Managed MLflow tracking server + artifact bucket |
| `sagemaker_hyperpod` | Optional HyperPod cluster (count-gated off by default) |

## How `qctl` / `start.sh` apply it

`start.sh --env dev` runs one `terraform apply` of `environments/dev` (Phase 1),
then builds/pushes images to the ECR repos this creates (Phase 2), then applies the
Kubernetes manifests — including the `model_inference` NodePool + vLLM Deployment YAML
rendered as Terraform outputs — sized by `model_replicas` (Phase 3). `--plan-only`
prints the full plan and exits; the CI `deploy-dev.yml` workflow calls the same
script (CI-parity). Fetch rendered manifests with:

```bash
terraform -chdir=environments/dev output -raw model_nodepool_yaml   | kubectl apply -f -
terraform -chdir=environments/dev output -raw model_deployment_yaml | kubectl apply -f -
```

## Get-the-GPUs lead time (§9.6)

GPU capacity is the binding constraint, not a detail. High-end accelerators
(P5/P5e/P6) are supply-constrained; on-demand launches routinely return
`InsufficientInstanceCapacity` and JIT provisioning of these families fails
intermittently. **Interactive serving must never depend on JIT-provisioning scarce
GPUs.** Treat capacity as a lead-time item that *precedes* the sprint needing it:

- Large-inference (P-family): **On-Demand Capacity Reservations (ODCR)**; the
  `gpu-inference-large` EC2NodeClass points at `capacityReservationSelectorTerms`.
  Never spot / JIT for interactive P-family serving.
- Training (P5/P5e): **ML Capacity Blocks** reserved per run, released when done.
- Batch/eval: spot with on-demand fallback (tolerates interruption).
- The dev MVP runs Model-32B on `g5.12xlarge` (generally available on-demand) via
  4-way tensor parallelism (§10.6), keeping the MVP off the scarce P-family path.

## Formatting

All HCL is canonical: `terraform fmt -check -recursive infra/terraform` passes.
`terraform validate` requires provider download (`terraform init`) and is run in CI,
not offline.
