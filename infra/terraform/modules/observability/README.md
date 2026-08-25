# observability

Managed monitoring backbone (see final_plan §18): an Amazon Managed Prometheus
workspace, an Amazon Managed Grafana workspace wired to Prometheus + CloudWatch,
and CloudWatch log groups for the platform components.

## Resources

- `aws_prometheus_workspace` — aliased to `name_prefix`; scrapes vLLM/DCGM/router
  metrics (TTFT, TPOT, queue depth, KV-cache hit rate, MBU/MFU).
- `aws_grafana_workspace` — `CURRENT_ACCOUNT` access, `SERVICE_MANAGED`
  permissions, `AWS_SSO` auth by default, with a dedicated IAM role granting
  read-only Prometheus query and CloudWatch metrics/logs access.
- `aws_cloudwatch_log_group` per component, named `/kairo/<name_prefix>/<component>`.

## Key variables

| Variable | Default | Purpose |
|---|---|---|
| `name_prefix` | — | Workspace alias and log path prefix. |
| `log_retention_days` | `30` | Log group retention (raise to 365 in prod). |
| `cloudwatch_kms_key_arn` | `""` | Optional CMK for log encryption. |
| `log_group_components` | router, vllm, log-ingestor, redactor, eval-runner, training | Components to create log groups for. |
| `grafana_authentication_providers` | `["AWS_SSO"]` | Grafana auth providers. |

## Key outputs

- `prometheus_workspace_id`, `prometheus_workspace_arn`,
  `prometheus_workspace_endpoint` (also `prometheus_endpoint`).
- `grafana_workspace_id`, `grafana_workspace_endpoint`, `grafana_workspace_arn`.
- `log_group_names`, `log_group_arns` — maps keyed by component name.

## Notes

- The Grafana IAM role trust policy is scoped to `grafana.amazonaws.com` with an
  `aws:SourceAccount` condition to prevent cross-account confused-deputy use.
- `AWS_SSO` requires IAM Identity Center enabled in the account; override
  `grafana_authentication_providers` for `SAML`-based setups.
