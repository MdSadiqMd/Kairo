# waf

Regional AWS WAFv2 web ACL for the platform ALB. Provides abuse shielding, rate
limiting, and managed-rule coverage in front of the router (§9.2, §19.2).

## What it creates

- `aws_wafv2_web_acl` (scope `REGIONAL`, `default_action` allow) with:
  - AWS managed rule groups (`override_action` = none):
    `AWSManagedRulesCommonRuleSet`, `AWSManagedRulesKnownBadInputsRuleSet`,
    `AWSManagedRulesAmazonIpReputationList`, `AWSManagedRulesSQLiRuleSet`.
  - A rate-based rule (`aggregate_key_type = IP`, `action` block) limiting each
    source IP to `rate_limit` requests per 5-minute window.
  - CloudWatch metrics + sampled requests on every rule and the ACL itself.
- `aws_wafv2_web_acl_association` — created only when `alb_arn` is non-empty
  (count-gated), so the ACL can be provisioned before the ALB exists.
- Optional logging: a CloudWatch log group (name prefixed `aws-waf-logs-`, as
  required by WAFv2) plus `aws_wafv2_web_acl_logging_configuration`, gated by
  `enable_logging`.

## Key variables

| Variable | Default | Purpose |
|---|---|---|
| `rate_limit` | `2000` | Per-IP request limit per 5-minute window. |
| `alb_arn` | `""` | ALB ARN to associate; empty skips association. |
| `enable_logging` | `true` | Toggle CloudWatch logging. |
| `managed_rules` | `[]` | Override the default managed rule set. |

## Outputs

`web_acl_arn`, `web_acl_id`, `web_acl_name`, `web_acl_capacity`.
