// Package preflight implements Phase 0 of the lifecycle:
// verify required tools, AWS credentials, region, and the KMS-encrypted
// versioned Terraform state bucket — the one documented resource qctl creates
// directly rather than through Terraform.
package preflight

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/MdSadiqMd/Kairo/internal/command"
	"github.com/MdSadiqMd/Kairo/internal/config"
)

// requiredTools must be on PATH; each is probed with `--version`.
var requiredTools = []string{"terraform", "aws", "kubectl", "helm", "jq", "docker"}

// gpuQuota is the Service Quotas code for on-demand G/VT instances. Preflight
// surfaces it in the remediation message so an operator knows exactly what to
// request when GPU capacity is missing.
const gpuQuotaCode = "L-DB2E81BA"
const gpuQuotaService = "ec2"

// Result is the outcome of a single preflight check.
type Result struct {
	Name        string
	OK          bool
	Detail      string
	Remediation string
}

// Report is the full preflight outcome.
type Report struct {
	Results []Result
}

// OK reports whether every check passed.
func (r Report) OK() bool {
	for _, res := range r.Results {
		if !res.OK {
			return false
		}
	}
	return true
}

// Failures returns only the checks that failed.
func (r Report) Failures() []Result {
	var out []Result
	for _, res := range r.Results {
		if !res.OK {
			out = append(out, res)
		}
	}
	return out
}

// Run executes all Phase 0 checks. It never returns an error for a failed
// check — the failure is captured in the Report so the caller can print every
// problem at once. An error is returned only for a programming/context fault.
func Run(ctx context.Context, r command.Runner, cfg config.Config) (Report, error) {
	var rep Report
	rep.Results = append(rep.Results, checkTools(ctx, r)...)
	rep.Results = append(rep.Results, checkSystemCapacity(ctx, r, cfg))

	if cfg.IsLocal() {
		rep.Results = append(rep.Results, checkLocalTools(ctx, r)...)
		rep.Results = append(rep.Results, checkMiniStack(ctx, r, cfg))
		rep.Results = append(rep.Results, checkCredentials(ctx, r))
		rep.Results = append(rep.Results, checkRegion(ctx, r, cfg))
		rep.Results = append(rep.Results, ensureLocalStateBackend(ctx, r, cfg))
	} else {
		rep.Results = append(rep.Results, checkCredentials(ctx, r))
		rep.Results = append(rep.Results, checkRegion(ctx, r, cfg))
		rep.Results = append(rep.Results, checkGPUQuota(ctx, r))
		rep.Results = append(rep.Results, ensureStateBucket(ctx, r, cfg))
	}
	return rep, nil
}

func checkSystemCapacity(ctx context.Context, r command.Runner, cfg config.Config) Result {
	name := "system:capacity"
	out, err := r.Run(ctx, "docker", "info", "--format", "{{json .}}")
	if err != nil {
		return Result{Name: name, OK: false, Detail: err.Error(), Remediation: "start Docker Desktop and ensure the Docker daemon is reachable"}
	}
	var info struct {
		NCPU         int    `json:"NCPU"`
		MemTotal     int64  `json:"MemTotal"`
		Architecture string `json:"Architecture"`
	}
	if err := json.Unmarshal([]byte(out), &info); err != nil || info.NCPU == 0 || info.MemTotal == 0 {
		return Result{Name: name, OK: false, Detail: "could not parse docker info", Remediation: "verify `docker info --format '{{json .}}'` returns NCPU and MemTotal"}
	}

	minCPU := 4
	minMemGiB := 8.0
	if cfg.IsLocal() {
		minCPU = 8
		minMemGiB = 36.0
	}
	memGiB := float64(info.MemTotal) / (1024 * 1024 * 1024)
	if info.NCPU < minCPU || memGiB < minMemGiB {
		return Result{
			Name:        name,
			OK:          false,
			Detail:      fmt.Sprintf("docker has %d CPU, %.1f GiB RAM; need >=%d CPU, >=%.0f GiB RAM for %s", info.NCPU, memGiB, minCPU, minMemGiB, cfg.Env),
			Remediation: "increase Docker Desktop CPU/memory resources before running Kairo",
		}
	}
	return Result{Name: name, OK: true, Detail: fmt.Sprintf("docker=%d CPU %.1f GiB arch=%s", info.NCPU, memGiB, info.Architecture)}
}

func ensureLocalStateBackend(ctx context.Context, r command.Runner, cfg config.Config) Result {
	name := "ministack:state-backend"
	alias := "alias/" + cfg.StateBucket
	if _, err := r.Run(ctx, "aws", "kms", "describe-key", "--key-id", alias); err != nil {
		out, createErr := r.Run(ctx, "aws", "kms", "create-key", "--description", cfg.StateBucket+" terraform state key", "--output", "json")
		if createErr != nil {
			return Result{Name: name, OK: false, Detail: createErr.Error(), Remediation: "check MiniStack KMS support and logs"}
		}
		var resp struct {
			KeyMetadata struct {
				KeyID string `json:"KeyId"`
			} `json:"KeyMetadata"`
		}
		_ = json.Unmarshal([]byte(out), &resp)
		if resp.KeyMetadata.KeyID != "" {
			if _, err := r.Run(ctx, "aws", "kms", "create-alias", "--alias-name", alias, "--target-key-id", resp.KeyMetadata.KeyID); err != nil {
				return Result{Name: name, OK: false, Detail: err.Error(), Remediation: "create MiniStack KMS alias manually or clear local state"}
			}
		}
	}
	if _, err := r.Run(ctx, "aws", "s3api", "head-bucket", "--bucket", cfg.StateBucket); err != nil {
		if _, err := r.Run(ctx, "aws", "s3api", "create-bucket", "--bucket", cfg.StateBucket, "--region", cfg.Region); err != nil {
			return Result{Name: name, OK: false, Detail: err.Error(), Remediation: "check MiniStack S3 support and logs"}
		}
		_, _ = r.Run(ctx, "aws", "s3api", "put-bucket-versioning", "--bucket", cfg.StateBucket, "--versioning-configuration", "Status=Enabled")
		_, _ = r.Run(ctx, "aws", "s3api", "put-bucket-encryption", "--bucket", cfg.StateBucket, "--server-side-encryption-configuration", fmt.Sprintf(`{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"aws:kms","KMSMasterKeyID":"%s"},"BucketKeyEnabled":true}]}`, alias))
	}
	return Result{Name: name, OK: true, Detail: cfg.StateBucket + " with " + alias}
}

func checkTools(ctx context.Context, r command.Runner) []Result {
	out := make([]Result, 0, len(requiredTools))
	for _, tool := range requiredTools {
		var err error
		switch tool {
		case "kubectl":
			_, err = r.Run(ctx, tool, "version", "--client")
		case "helm":
			_, err = r.Run(ctx, tool, "version")
		default:
			_, err = r.Run(ctx, tool, "--version")
		}
		res := Result{Name: "tool:" + tool, OK: err == nil}
		if err != nil {
			res.Detail = err.Error()
			res.Remediation = fmt.Sprintf("install %q and ensure it is on PATH", tool)
		}
		out = append(out, res)
	}
	return out
}

func checkCredentials(ctx context.Context, r command.Runner) Result {
	out, err := r.Run(ctx, "aws", "sts", "get-caller-identity", "--output", "json")
	if err != nil {
		return Result{
			Name:        "aws:credentials",
			OK:          false,
			Detail:      err.Error(),
			Remediation: "configure AWS credentials (aws configure / SSO / assume-role) for the target account",
		}
	}
	var ident struct {
		Account string `json:"Account"`
		Arn     string `json:"Arn"`
	}
	_ = json.Unmarshal([]byte(out), &ident)
	return Result{Name: "aws:credentials", OK: true, Detail: fmt.Sprintf("account=%s arn=%s", ident.Account, ident.Arn)}
}

func checkRegion(ctx context.Context, r command.Runner, cfg config.Config) Result {
	if got := firstNonEmpty(os.Getenv("AWS_REGION"), os.Getenv("AWS_DEFAULT_REGION")); got != "" {
		if got == cfg.Region {
			return Result{Name: "aws:region", OK: true, Detail: got}
		}
		return Result{
			Name:        "aws:region",
			OK:          false,
			Detail:      fmt.Sprintf("environment region %q != expected %q", got, cfg.Region),
			Remediation: fmt.Sprintf("export AWS_REGION=%s for env %s", cfg.Region, cfg.Env),
		}
	}
	out, err := r.Run(ctx, "aws", "configure", "get", "region")
	got := strings.TrimSpace(out)
	if err != nil || got == "" {
		return Result{
			Name:        "aws:region",
			OK:          false,
			Detail:      "no default region configured",
			Remediation: fmt.Sprintf("export AWS_REGION=%s or set it via `aws configure`", cfg.Region),
		}
	}
	if got != cfg.Region {
		return Result{
			Name:        "aws:region",
			OK:          false,
			Detail:      fmt.Sprintf("configured region %q != expected %q", got, cfg.Region),
			Remediation: fmt.Sprintf("set the region to %s for env %s", cfg.Region, cfg.Env),
		}
	}
	return Result{Name: "aws:region", OK: true, Detail: got}
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if value != "" {
			return value
		}
	}
	return ""
}

// checkGPUQuota is best-effort: if the quota lookup fails or reports zero, it
// fails the check with the exact quota code to request.
func checkGPUQuota(ctx context.Context, r command.Runner) Result {
	out, err := r.Run(ctx, "aws", "service-quotas", "get-service-quota",
		"--service-code", gpuQuotaService, "--quota-code", gpuQuotaCode, "--output", "json")
	remediation := fmt.Sprintf(
		"request Service Quota %s (%s: Running On-Demand G and VT instances) with enough vCPUs for the GPU fleet",
		gpuQuotaCode, gpuQuotaService)
	if err != nil {
		return Result{Name: "aws:gpu-quota", OK: false, Detail: err.Error(), Remediation: remediation}
	}
	var resp struct {
		Quota struct {
			Value float64 `json:"Value"`
		} `json:"Quota"`
	}
	if uerr := json.Unmarshal([]byte(out), &resp); uerr != nil {
		return Result{Name: "aws:gpu-quota", OK: false, Detail: uerr.Error(), Remediation: remediation}
	}
	if resp.Quota.Value <= 0 {
		return Result{Name: "aws:gpu-quota", OK: false, Detail: "quota value is 0", Remediation: remediation}
	}
	return Result{Name: "aws:gpu-quota", OK: true, Detail: fmt.Sprintf("vCPU quota=%.0f", resp.Quota.Value)}
}

// ensureStateBucket verifies (or creates) the versioned, KMS-encrypted state
// bucket. This is the ONE resource qctl provisions outside Terraform, because
// Terraform's own remote state must exist before the first apply.
func ensureStateBucket(ctx context.Context, r command.Runner, cfg config.Config) Result {
	name := "aws:state-bucket"
	if _, err := r.Run(ctx, "aws", "s3api", "head-bucket", "--bucket", cfg.StateBucket); err == nil {
		return Result{Name: name, OK: true, Detail: fmt.Sprintf("%s exists", cfg.StateBucket)}
	}
	steps := [][]string{
		{"s3api", "create-bucket", "--bucket", cfg.StateBucket,
			"--region", cfg.Region, "--create-bucket-configuration", "LocationConstraint=" + cfg.Region},
		{"s3api", "put-bucket-versioning", "--bucket", cfg.StateBucket,
			"--versioning-configuration", "Status=Enabled"},
		{"s3api", "put-bucket-encryption", "--bucket", cfg.StateBucket,
			"--server-side-encryption-configuration",
			`{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"aws:kms"},"BucketKeyEnabled":true}]}`},
		{"s3api", "put-public-access-block", "--bucket", cfg.StateBucket,
			"--public-access-block-configuration",
			"BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"},
	}
	for _, args := range steps {
		if _, err := r.Run(ctx, "aws", args...); err != nil {
			return Result{
				Name:        name,
				OK:          false,
				Detail:      err.Error(),
				Remediation: fmt.Sprintf("create a versioned, KMS-encrypted state bucket named %s manually", cfg.StateBucket),
			}
		}
	}
	return Result{Name: name, OK: true, Detail: fmt.Sprintf("created %s (versioned, KMS-encrypted, private)", cfg.StateBucket)}
}

func checkLocalTools(ctx context.Context, r command.Runner) []Result {
	var out []Result
	_, err := r.Run(ctx, "ministack", "-h")
	res := Result{Name: "tool:ministack", OK: err == nil}
	if err != nil {
		res.Detail = err.Error()
		res.Remediation = "install ministack: pip install ministack or see https://ministack.org/docs/"
	}
	out = append(out, res)
	return out
}

func checkMiniStack(ctx context.Context, r command.Runner, cfg config.Config) Result {
	name := "ministack:health"
	client := &http.Client{Timeout: 5 * time.Second}
	healthURL := cfg.AWSEndpoint + "/_ministack/health"

	resp, err := client.Get(healthURL)
	if err != nil {
		if _, startErr := r.Run(ctx, "ministack", "start", "-d"); startErr != nil {
			if _, startErr = r.Run(ctx, "ministack", "-d"); startErr == nil {
				goto waitForHealth
			}
			return Result{
				Name:        name,
				OK:          false,
				Detail:      fmt.Sprintf("ministack not running and failed to start: %v", startErr),
				Remediation: "run `ministack start -d` manually or check Docker is running",
			}
		}
	waitForHealth:
		for i := 0; i < 30; i++ {
			time.Sleep(1 * time.Second)
			resp, err = client.Get(healthURL)
			if err == nil && resp.StatusCode == 200 {
				resp.Body.Close()
				return Result{Name: name, OK: true, Detail: "ministack started and healthy"}
			}
			if resp != nil {
				resp.Body.Close()
			}
		}
		return Result{
			Name:        name,
			OK:          false,
			Detail:      "ministack started but health check timed out",
			Remediation: "check `ministack logs` for errors",
		}
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		return Result{
			Name:        name,
			OK:          false,
			Detail:      fmt.Sprintf("ministack health returned %d", resp.StatusCode),
			Remediation: "check `ministack logs` for errors",
		}
	}
	return Result{Name: name, OK: true, Detail: "ministack is healthy"}
}
