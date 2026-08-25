# ecr

Container image repositories for the platform: `router`, `vllm`, `sglang`,
`eval-runner`, `log-ingestor`, and `training`, plus an optional pull-through
cache for an upstream public registry.

## Key variables

| Variable | Default | Purpose |
|---|---|---|
| `image_tag_mutability` | `IMMUTABLE` | Tag mutability for all repos. |
| `encryption_type` | `AES256` | `AES256` or `KMS`. |
| `kms_key_arn` | `null` | CMK ARN used when `encryption_type = KMS`. |
| `keep_last_images` | `20` | Tagged images retained per repo. |
| `untagged_expire_days` | `14` | Age at which untagged images expire. |
| `enable_pull_through_cache` | `true` | Create the pull-through cache rule. |
| `upstream_registry_url` | `public.ecr.aws` | Upstream registry to mirror. |
| `ecr_repository_prefix` | `ecr-public` | Local namespace for cached images. |

## Key outputs

`repository_urls`, `repository_arns`, `repository_names` — each a `map(string)`
keyed by logical name (`router`, `vllm`, `sglang`, `eval_runner`,
`log_ingestor`, `training`).

## Design notes

- Every repository scans on push and keeps immutable tags by default, so a
  deployed digest cannot be silently overwritten.
- The lifecycle policy expires untagged images by age, then caps total images at
  `keep_last_images`.
- The pull-through cache rule (final_plan §24 win 9) removes the build/pull-time
  dependency on external registry availability and rate limits; mirrored images
  appear under `<ecr_repository_prefix>/...`.
