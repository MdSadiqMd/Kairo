# iam

Per-service IRSA roles for the Kairo platform (plan §19.1, §19.5).

Creates one `aws_iam_role` per workload — router, inference-pod, log-ingestor,
redactor, eval-runner, training-job, promotion-service, agent-worker — each
federating the cluster OIDC provider. Least-privilege inline policies follow the
§19.1 permissions table; every ARN input is optional (defaults `""` / `[]`) so
the module still plans before the data-plane resources exist. A statement is only
emitted when its backing ARN is supplied, and a role gets an inline policy only
when at least one statement is active.

## Conventions

- IRSA subject convention: the assume-role policy requires
  `<oidc>:sub = system:serviceaccount:<service_account_namespace>:<sa-name>`
  (namespace default `kairo`) and `<oidc>:aud = sts.amazonaws.com`.
- No long-lived access keys — IRSA only (§19.5).
- Every workload role carries a **permission boundary** (§19.5). The in-module
  boundary (`aws_iam_policy.boundary`) caps workloads to the platform action set
  and explicitly denies IAM policy-escalation and any tampering with CloudTrail,
  GuardDuty, or Config. Override it with `permission_boundary_arn`.
- S3 statements carry an `aws:SecureTransport = true` condition (TLS-only).
- Kubernetes request == limit is the pod-spec convention for these workloads
  (deterministic scheduling / QoS Guaranteed); it is enforced in the workload
  manifests, not here.

## Per-service scope

| Role | Scope |
|---|---|
| router | Read model-registry DynamoDB; write events to Kinesis/SQS |
| inference-pod | `s3:GetObject` on model-artifacts only + KMS decrypt |
| log-ingestor | Write raw-events + KMS encrypt; read Kinesis/SQS |
| redactor | Read raw-events, write redacted-events, KMS |
| eval-runner | Read datasets/eval, write eval-results, read/write eval DynamoDB |
| training-job | Read datasets; write checkpoints + model-artifacts; KMS; read HF token secret |
| promotion-service | Update model-registry + deployment-state DynamoDB |
| agent-worker | Scoped SQS + a single S3 state prefix only |

## Outputs

`role_arns` and `role_names` (maps keyed by `router`, `inference_pod`,
`log_ingestor`, `redactor`, `eval_runner`, `training_job`, `promotion_service`,
`agent_worker`), and `permission_boundary_arn`.
