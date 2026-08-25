# opensearch

Private OpenSearch domain backing hybrid RAG (BM25 lexical + k-NN vector) and
eval/search indexes (final_plan §11.7). VPC-only — no public access.

## Security posture

- `vpc_options` places the domain's ENIs in private-data subnets; there is no
  public endpoint.
- Dedicated security group allows 443 only from `vpc_cidr`.
- `encrypt_at_rest` (customer KMS key), `node_to_node_encryption`, and
  `enforce_https` with a modern TLS policy are all enabled.
- Fine-grained access control (`advanced_security_options`) is on. Default is the
  internal user database (username/password); set `use_internal_user_database=false`
  and provide `master_user_arn` to use an IAM master instead.
- `access_policies` grants `es:ESHttp*` only to explicit IAM principals
  (`access_principal_arns`, default account root) scoped to the domain ARN — never
  a public `*` principal.

## Key variables

| Variable | Default | Purpose |
|---|---|---|
| `vpc_id`, `subnet_ids`, `vpc_cidr` | — | Private VPC placement + ingress CIDR. |
| `kms_key_arn` | — | Encryption-at-rest key. |
| `engine_version` | `OpenSearch_2.13` | Engine version. |
| `instance_type` | `r6g.large.search` | Data node type. |
| `instance_count` | `2` | Data node count. |
| `volume_size` | `100` | gp3 GiB per node. |
| `zone_awareness_enabled` | `true` | Multi-AZ data nodes. |
| `master_user_name` | `admin` | Internal master username. |
| `master_user_password` | — (sensitive) | Internal master password. |

## Key outputs

- `domain_name`, `domain_arn`, `domain_id`
- `domain_endpoint` — VPC search/index endpoint.
- `kibana_endpoint` (also `dashboard_endpoint`) — OpenSearch Dashboards.
- `security_group_id`

## Notes

- Domain names must be 3-28 lowercase chars; if `name_prefix` violates that, set
  `domain_name` explicitly.
- `subnet_ids` count should match `availability_zone_count`, and `instance_count`
  should be a multiple of the AZ count for balanced shard placement.
