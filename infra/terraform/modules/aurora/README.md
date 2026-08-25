# aurora

Aurora PostgreSQL Serverless v2 cluster for relational control-plane metadata
(final_plan §9.2). Private — reachable only from within the VPC.

## Design

- `engine_mode = "provisioned"` with `serverlessv2_scaling_configuration`
  (`min_capacity`/`max_capacity` ACU) — the required shape for Serverless v2.
- At least one `db.serverless` cluster instance (`instance_count`, default 1).
- `db_subnet_group` over private-data subnets; dedicated security group allows
  5432 only from `vpc_cidr`. No public access.
- `storage_encrypted` with a customer KMS key.
- Master password is managed by Secrets Manager (`manage_master_user_password`);
  the secret is encrypted with the same KMS key and exposed via
  `master_user_secret_arn`. No random provider or plaintext password.
- `copy_tags_to_snapshot`, `enabled_cloudwatch_logs_exports = ["postgresql"]`,
  deletion protection and final snapshot on by default.

## Key variables

| Variable | Default | Purpose |
|---|---|---|
| `vpc_id`, `subnet_ids`, `vpc_cidr` | — | Private VPC placement + ingress CIDR. |
| `kms_key_arn` | — | Storage + secret encryption key. |
| `database_name` | `kairo` | Initial database. |
| `master_username` | `kairo_admin` | Master username (password managed). |
| `min_capacity` / `max_capacity` | `0.5` / `4` | Serverless v2 ACU range. |
| `engine_version` | `16.4` | Aurora PostgreSQL version. |
| `backup_retention_period` | `7` | Backup retention days. |
| `deletion_protection` | `true` | Cluster deletion protection. |
| `skip_final_snapshot` | `false` | Skip final snapshot on destroy. |

## Key outputs

- `cluster_endpoint`, `reader_endpoint`
- `cluster_arn`, `cluster_identifier`
- `database_name`, `port`
- `security_group_id`
- `master_user_secret_arn` — read the managed password from Secrets Manager.

## Notes

- Retrieve credentials at runtime from `master_user_secret_arn`; the password
  never appears in Terraform state as a plaintext variable.
- With `deletion_protection = true` a destroy requires disabling protection first.
