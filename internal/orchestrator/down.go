package orchestrator

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"strings"
)

// DownOptions are the flags accepted by `qctl down`.
type DownOptions struct {
	DeleteData bool
	NukeState  bool
	Force      bool
}

// ErrConfirmationFailed is returned when the operator does not confirm teardown.
type ErrConfirmationFailed struct{ Reason string }

func (e ErrConfirmationFailed) Error() string { return "teardown not confirmed: " + e.Reason }

// Down tears the environment down in the exact order of the teardown plan.
// The order is load-bearing: Kubernetes is drained and Karpenter nodes are
// removed BEFORE terraform destroy, otherwise controller-created ALBs/ENIs are
// invisible to Terraform state and the VPC destroy hangs for hours on dangling
// ENIs — the classic teardown failure.
func (o *Orchestrator) Down(ctx context.Context, opts DownOptions) error {
	if err := o.confirm(opts); err != nil {
		return err
	}
	if err := o.drainKubernetes(ctx); err != nil {
		return fmt.Errorf("drain kubernetes: %w", err)
	}
	if err := o.deleteKarpenterNodes(ctx); err != nil {
		return fmt.Errorf("delete karpenter nodes: %w", err)
	}
	if err := o.terraformDestroy(ctx, opts); err != nil {
		return fmt.Errorf("terraform destroy: %w", err)
	}
	if err := o.handleData(ctx, opts); err != nil {
		return fmt.Errorf("data handling: %w", err)
	}

	if !o.Cfg.IsLocal() {
		if _, err := o.Sweep(ctx, false); err != nil {
			return fmt.Errorf("orphan sweep: %w", err)
		}
		if err := o.costStopReport(ctx); err != nil {
			return fmt.Errorf("cost-stop report: %w", err)
		}
	} else {
		o.printf("cost-stop [local]: skipped (no real AWS resources)\n")
	}

	if opts.NukeState {
		if err := o.nukeState(ctx); err != nil {
			return fmt.Errorf("nuke state: %w", err)
		}
	}
	return nil
}

// confirm gates teardown (step 1). The operator must type the environment name;
// prod additionally requires --force plus a second typed confirmation, so
// deleting a prod fleet is never one keystroke. Local mode skips confirmation
// for faster iteration.
func (o *Orchestrator) confirm(opts DownOptions) error {
	o.printf("This will destroy the %q environment.\n", o.Cfg.Env)

	if o.Cfg.IsLocal() {
		o.info("teardown.confirmed", "env", o.Cfg.Env, "mode", "local-auto")
		return nil
	}

	if o.Cfg.IsProd() && !opts.Force {
		return ErrConfirmationFailed{Reason: "prod teardown requires --force"}
	}
	reader := bufio.NewReader(o.In)

	o.printf("Type the environment name (%s) to continue: ", o.Cfg.Env)
	line, _ := reader.ReadString('\n')
	if strings.TrimSpace(line) != o.Cfg.Env {
		return ErrConfirmationFailed{Reason: "environment name did not match"}
	}

	if o.Cfg.IsProd() {
		o.printf("PROD teardown. Type DESTROY %s to confirm: ", o.Cfg.Env)
		line2, _ := reader.ReadString('\n')
		if strings.TrimSpace(line2) != "DESTROY "+o.Cfg.Env {
			return ErrConfirmationFailed{Reason: "second prod confirmation did not match"}
		}
	}
	o.info("teardown.confirmed", "env", o.Cfg.Env)
	return nil
}

// drainKubernetes (step 2) scales workloads to zero then deletes the
// controller-owned Ingress/Service/ExternalSecret objects BEFORE Terraform, so
// the ALBs/ENIs/SGs they created are released first.
func (o *Orchestrator) drainKubernetes(ctx context.Context) error {
	o.info("teardown.drain.start")
	// Best-effort: the cluster may already be gone on a re-run (idempotent).
	_, _ = o.kubectl(ctx, "-n", o.Cfg.Namespace, "scale", "deployment", "--all", "--replicas=0")
	_, _ = o.kubectl(ctx, "-n", o.Cfg.Namespace, "delete", "ingress", "--all", "--ignore-not-found")
	_, _ = o.kubectl(ctx, "-n", o.Cfg.Namespace, "delete", "service", "--all", "--ignore-not-found")
	_, _ = o.kubectl(ctx, "-n", o.Cfg.Namespace, "delete", "externalsecret", "--all", "--ignore-not-found")
	o.info("teardown.drain.ok")
	return nil
}

// deleteKarpenterNodes (step 3) removes NodePools/NodeClaims and waits for the
// EC2 instances to terminate. Karpenter-launched instances are not in
// Terraform state, so they must be reaped explicitly.
func (o *Orchestrator) deleteKarpenterNodes(ctx context.Context) error {
	o.info("teardown.karpenter.start")
	_, _ = o.kubectl(ctx, "delete", "nodepools", "--all", "--ignore-not-found")
	_, _ = o.kubectl(ctx, "delete", "nodeclaims", "--all", "--ignore-not-found")
	if _, err := o.kubectl(ctx, "wait", "--for=delete", "nodeclaims", "--all", "--timeout=10m"); err != nil {
		// A timeout here should not block destroy; the tag sweep is the backstop.
		o.info("teardown.karpenter.wait.warn", "err", err.Error())
	}
	o.info("teardown.karpenter.ok")
	return nil
}

func (o *Orchestrator) terraformDestroy(ctx context.Context, opts DownOptions) error {
	o.info("teardown.terraform.start")
	if _, err := o.tf(ctx, o.tfInitArgs()...); err != nil {
		return err
	}
	args := []string{"destroy", "-input=false", "-auto-approve",
		"-var", "force_destroy=" + boolStr(o.Cfg.Env == "dev" || opts.DeleteData)}
	if _, err := o.tf(ctx, args...); err != nil {
		return err
	}
	o.info("teardown.terraform.ok")
	return nil
}

// handleData (step 5): dev buckets use force_destroy; prod/staging data buckets
// survive unless --delete-data. Object-Lock audit buckets cannot be deleted
// before retention expiry — a documented exception, reported not deleted.
func (o *Orchestrator) handleData(ctx context.Context, opts DownOptions) error {
	if o.Cfg.Env == "dev" {
		o.printf("data [dev]: buckets force-destroyed with the infrastructure\n")
		return nil
	}
	if o.Cfg.IsLocal() {
		o.printf("data [local]: MiniStack buckets force-destroyed with the local terraform state\n")
		return nil
	}
	if !opts.DeleteData {
		o.printf("data [%s]: retained (training data, datasets, model artifacts). Pass --delete-data to remove.\n", o.Cfg.Env)
		return nil
	}
	o.printf("data [%s]: --delete-data set; non-Object-Lock data buckets removed. Object-Locked audit logs remain until retention expiry.\n", o.Cfg.Env)
	return nil
}

// costStopReport (step 7) proves the bill is going to ~zero by asserting no GPU
// instances, NAT gateways, or ALBs remain for this env.
func (o *Orchestrator) costStopReport(ctx context.Context) error {
	o.info("teardown.cost-report.start")
	tag := "Name=tag:env,Values=" + o.Cfg.Env

	gpu, err := o.countJSON(ctx, []string{"ec2", "describe-instances",
		"--filters", tag, "Name=instance-state-name,Values=running,pending",
		"--query", "length(Reservations[].Instances[])", "--output", "json"})
	if err != nil {
		return err
	}
	nat, err := o.countJSON(ctx, []string{"ec2", "describe-nat-gateways",
		"--filter", tag, "--query", "length(NatGateways[?State=='available'])", "--output", "json"})
	if err != nil {
		return err
	}
	alb, err := o.countJSON(ctx, []string{"elbv2", "describe-load-balancers",
		"--query", "length(LoadBalancers[])", "--output", "json"})
	if err != nil {
		return err
	}

	o.printf("cost-stop report [%s]: gpu_instances=%d nat_gateways=%d load_balancers=%d\n",
		o.Cfg.Env, gpu, nat, alb)
	if gpu != 0 || nat != 0 || alb != 0 {
		return fmt.Errorf("residual billable resources remain: gpu=%d nat=%d alb=%d", gpu, nat, alb)
	}
	o.printf("✅ cost-stop [%s]: zero GPU instances, zero NAT gateways, zero ALBs — bill is ~zero\n", o.Cfg.Env)
	return nil
}

func (o *Orchestrator) countJSON(ctx context.Context, args []string) (int, error) {
	out, err := o.aws(ctx, args...)
	if err != nil {
		return 0, err
	}
	out = strings.TrimSpace(out)
	if out == "" {
		return 0, nil
	}
	var n int
	if err := json.Unmarshal([]byte(out), &n); err != nil {
		return 0, fmt.Errorf("parse count %q: %w", out, err)
	}
	return n, nil
}

// nukeState removes the Terraform state bucket itself (dev only, --nuke-state).
func (o *Orchestrator) nukeState(ctx context.Context) error {
	if o.Cfg.IsLocal() {
		return fmt.Errorf("--nuke-state is not needed for local backend state")
	}
	if o.Cfg.Env != "dev" {
		return fmt.Errorf("--nuke-state is only permitted for dev (got %s)", o.Cfg.Env)
	}
	o.info("teardown.nuke-state.start", "bucket", o.Cfg.StateBucket)
	if _, err := o.Runner.Run(ctx, "aws", "s3", "rb", "s3://"+o.Cfg.StateBucket, "--force"); err != nil {
		return err
	}
	o.printf("state bucket %s removed\n", o.Cfg.StateBucket)
	return nil
}

func boolStr(b bool) string {
	if b {
		return "true"
	}
	return "false"
}
