# sagemaker_mlflow

Managed MLflow tracking server for experiment tracking and model lineage (§9.2).
MLflow lineage backs the §19.4 right-to-delete workflow (identify which
models/adapters trained on a given record).

## What it creates

- `aws_sagemaker_mlflow_tracking_server` named `<name_prefix>-mlflow`, sized by
  `tracking_server_size` (default `Small`), with `automatic_model_registration`
  (default on) and `artifact_store_uri` pointing at the artifact bucket.
- An artifact-store S3 bucket (`mlflow_artifact_bucket` or the derived
  `<name_prefix>-mlflow-artifacts-<account>`) with versioning, full Block Public
  Access, KMS/SSE encryption, and a TLS-only bucket policy.
- A SageMaker execution IAM role scoped to the artifact bucket (list + object
  read/write/delete) and, when `kms_key_arn` is set, the KMS key. An optional
  `permissions_boundary_arn` can be applied per §19.5.

## Key variables

| Variable | Default | Purpose |
|---|---|---|
| `kms_key_arn` | `""` | KMS key for bucket + role; empty uses SSE-S3. |
| `mlflow_artifact_bucket` | `""` | Override the derived bucket name. |
| `tracking_server_size` | `"Small"` | Server size. |
| `automatic_model_registration` | `true` | Auto-register logged models. |
| `mlflow_version` | `""` | Pin an MLflow version. |

## Outputs

`tracking_server_arn`, `tracking_server_name`, `tracking_server_url`,
`artifact_bucket`, `execution_role_arn`.
