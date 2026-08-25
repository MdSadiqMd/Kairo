# sagemaker_hyperpod

**Optional** SageMaker HyperPod cluster for large-scale training (§9.2). This
module is **count-gated off by default** (`enable_hyperpod = false`) — with the
switch off it creates nothing and still plans cleanly, so it can sit in the
environment root as a no-op until large training is needed.

## What it creates (only when `enable_hyperpod = true`)

- `aws_sagemaker_cluster` (`<name_prefix>-hyperpod`) with a single training
  `instance_group` (`instance_type`, default `ml.p5.48xlarge`; `instance_count`,
  default 2) referencing a lifecycle config at `lifecycle_config_s3_uri`.
- A `vpc_config` over `subnet_ids` + `security_group_ids` (omitted when no subnets
  are supplied) — training stays on private subnets per §19.5.
- A SageMaker execution IAM role (with `AmazonSageMakerClusterInstanceRolePolicy`
  and an optional permissions boundary) created only when `execution_role_arn` is
  not supplied.

## Key variables

| Variable | Default | Purpose |
|---|---|---|
| `enable_hyperpod` | `false` | Master on/off switch. |
| `instance_type` | `"ml.p5.48xlarge"` | Training instance type. |
| `instance_count` | `2` | Instances in the group. |
| `subnet_ids` / `security_group_ids` | `[]` | VPC placement. |
| `lifecycle_config_s3_uri` | `""` | Lifecycle scripts. |
| `execution_role_arn` | `""` | Reuse a role instead of creating one. |

## Outputs

`cluster_arn` (null when disabled), `cluster_name` (null when disabled),
`enabled` (bool echo).
