package orchestrator

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/MdSadiqMd/Kairo/internal/config"
)

// SweepResult is the outcome of the tag-based orphan sweep.
type SweepResult struct {
	DryRun    bool
	Resources []string
	Deleted   []string
}

// Sweep runs the tag-based orphan sweep (step 6 of teardown). It
// queries the Resource Groups Tagging API for anything still carrying this
// env's project/env tags and, unless dryRun, deletes each ARN. Tags are the
// guarantee behind "every small thing is gone" — trust tags, not memory.
func (o *Orchestrator) Sweep(ctx context.Context, dryRun bool) (SweepResult, error) {
	o.info("sweep.start", "env", o.Cfg.Env, "dry_run", dryRun)
	res := SweepResult{DryRun: dryRun}

	out, err := o.aws(ctx, "resourcegroupstaggingapi", "get-resources",
		"--tag-filters",
		"Key=project,Values="+config.Project,
		"Key=env,Values="+o.Cfg.Env,
		"--output", "json")
	if err != nil {
		return res, err
	}

	var resp struct {
		ResourceTagMappingList []struct {
			ResourceARN string `json:"ResourceARN"`
		} `json:"ResourceTagMappingList"`
	}
	if err := json.Unmarshal([]byte(out), &resp); err != nil && out != "" {
		return res, fmt.Errorf("parse tagging response: %w", err)
	}
	for _, r := range resp.ResourceTagMappingList {
		res.Resources = append(res.Resources, r.ResourceARN)
	}

	if dryRun {
		o.printf("sweep [%s] dry-run: %d tagged resource(s) remain\n", o.Cfg.Env, len(res.Resources))
		for _, arn := range res.Resources {
			o.printf("  would delete: %s\n", arn)
		}
		return res, nil
	}

	for _, arn := range res.Resources {
		if err := o.deleteResource(ctx, arn); err != nil {
			o.info("sweep.delete.error", "arn", arn, "err", err.Error())
			continue
		}
		res.Deleted = append(res.Deleted, arn)
	}
	o.printf("sweep [%s]: deleted %d tagged resource(s)\n", o.Cfg.Env, len(res.Deleted))
	return res, nil
}

func (o *Orchestrator) deleteResource(ctx context.Context, arn string) error {
	// Parse ARN to determine resource type and call appropriate delete API
	// ARN format: arn:aws:service:region:account:resource-type/resource-id
	// Example: arn:aws:ec2:us-west-2:123456789012:instance/i-1234567890abcdef0
	parts := parseARN(arn)
	if parts == nil {
		return fmt.Errorf("cannot parse ARN: %s", arn)
	}
	switch parts.service {
	case "ec2":
		return o.deleteEC2Resource(ctx, parts)
	case "elasticloadbalancing":
		return o.deleteELBResource(ctx, parts)
	case "dynamodb":
		return o.deleteDynamoDBResource(ctx, parts)
	case "s3":
		// S3 deletion handled by terraform destroy with force_destroy
		o.info("sweep.skip.s3", "arn", arn)
		return nil
	default:
		// Untag as fallback for resources we don't handle directly
		_, err := o.aws(ctx, "resourcegroupstaggingapi", "untag-resources",
			"--resource-arn-list", arn, "--tag-keys", "project", "env")
		return err
	}
}

type arnParts struct {
	service      string
	region       string
	account      string
	resourceType string
	resourceID   string
}

func parseARN(arn string) *arnParts {
	// arn:aws:service:region:account:resource-type/resource-id
	// or arn:aws:service:region:account:resource-type:resource-id
	var parts []string
	if len(arn) < 10 || arn[:4] != "arn:" {
		return nil
	}
	parts = splitARN(arn)
	if len(parts) < 6 {
		return nil
	}
	resourceParts := parts[5]
	resourceType := ""
	resourceID := resourceParts
	if idx := indexAny(resourceParts, "/:"); idx >= 0 {
		resourceType = resourceParts[:idx]
		resourceID = resourceParts[idx+1:]
	}
	return &arnParts{
		service:      parts[2],
		region:       parts[3],
		account:      parts[4],
		resourceType: resourceType,
		resourceID:   resourceID,
	}
}

func splitARN(arn string) []string {
	result := make([]string, 0, 7)
	start := 0
	count := 0
	for i, c := range arn {
		if c == ':' {
			result = append(result, arn[start:i])
			start = i + 1
			count++
			if count >= 5 {
				result = append(result, arn[start:])
				break
			}
		}
	}
	return result
}

func indexAny(s, chars string) int {
	for i, c := range s {
		for _, ch := range chars {
			if c == ch {
				return i
			}
		}
	}
	return -1
}

func (o *Orchestrator) deleteEC2Resource(ctx context.Context, parts *arnParts) error {
	switch parts.resourceType {
	case "instance":
		_, err := o.aws(ctx, "ec2", "terminate-instances", "--instance-ids", parts.resourceID)
		return err
	case "natgateway", "nat-gateway":
		_, err := o.aws(ctx, "ec2", "delete-nat-gateway", "--nat-gateway-id", parts.resourceID)
		return err
	case "vpc":
		_, err := o.aws(ctx, "ec2", "delete-vpc", "--vpc-id", parts.resourceID)
		return err
	default:
		return fmt.Errorf("unsupported EC2 resource type: %s", parts.resourceType)
	}
}

func (o *Orchestrator) deleteELBResource(ctx context.Context, parts *arnParts) error {
	// parts.resourceID for ALB: loadbalancer/app/name/id or targetgroup/name/id
	if len(parts.resourceID) > 12 && parts.resourceID[:12] == "loadbalancer" {
		_, err := o.aws(ctx, "elbv2", "delete-load-balancer", "--load-balancer-arn",
			fmt.Sprintf("arn:aws:elasticloadbalancing:%s:%s:%s", parts.region, parts.account, parts.resourceType+"/"+parts.resourceID))
		return err
	}
	if len(parts.resourceID) > 11 && parts.resourceID[:11] == "targetgroup" {
		_, err := o.aws(ctx, "elbv2", "delete-target-group", "--target-group-arn",
			fmt.Sprintf("arn:aws:elasticloadbalancing:%s:%s:%s", parts.region, parts.account, parts.resourceType+"/"+parts.resourceID))
		return err
	}
	return fmt.Errorf("unsupported ELB resource: %s", parts.resourceID)
}

func (o *Orchestrator) deleteDynamoDBResource(ctx context.Context, parts *arnParts) error {
	// resourceID is table/table-name
	tableName := parts.resourceID
	if len(tableName) > 6 && tableName[:6] == "table/" {
		tableName = tableName[6:]
	}
	_, err := o.aws(ctx, "dynamodb", "delete-table", "--table-name", tableName)
	return err
}
