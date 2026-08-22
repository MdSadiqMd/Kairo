// Package orchestrator sequences the platform lifecycle.
// It "orchestrates, Terraform owns": every method here shells out to
// terraform/kubectl/aws/docker/helm through a command.Runner, so the ordering
// logic is unit-testable offline against a fake runner.
package orchestrator

import (
	"context"
	"fmt"
	"io"
	"log/slog"
	"strings"

	"github.com/MdSadiqMd/Kairo/internal/command"
	"github.com/MdSadiqMd/Kairo/internal/config"
	"github.com/MdSadiqMd/Kairo/internal/modelconfig"
)

// Orchestrator carries the shared dependencies for every lifecycle action.
type Orchestrator struct {
	Cfg         config.Config
	Models      modelconfig.Profile
	Runner      command.Runner
	Log         *slog.Logger
	ZKInference bool
	// Out receives human-facing contract output (the final block, reports).
	Out io.Writer
	// In is the confirmation source for destructive actions (typically stdin).
	In io.Reader
}

// New constructs an Orchestrator with sensible defaults for the writers.
func New(cfg config.Config, models modelconfig.Profile, r command.Runner, log *slog.Logger, out io.Writer, in io.Reader) *Orchestrator {
	return &Orchestrator{Cfg: cfg, Models: models, Runner: r, Log: log, Out: out, In: in}
}

func (o *Orchestrator) tf(ctx context.Context, args ...string) (string, error) {
	full := append([]string{"-chdir=" + o.Cfg.TerraformDir}, args...)
	return o.Runner.Run(ctx, "terraform", full...)
}

func (o *Orchestrator) kubectl(ctx context.Context, args ...string) (string, error) {
	full := append([]string{"--context", o.Cfg.KubeContext}, args...)
	return o.Runner.Run(ctx, "kubectl", full...)
}

func (o *Orchestrator) applyKustomize(ctx context.Context, dir string) (string, error) {
	if !o.Cfg.IsLocal() {
		return o.kubectl(ctx, "apply", "-k", dir)
	}
	cmd := fmt.Sprintf("kubectl kustomize --load-restrictor=LoadRestrictionsNone %s | kubectl --context %s apply -f -",
		shellQuote(dir), shellQuote(o.Cfg.KubeContext))
	return o.Runner.Run(ctx, "sh", "-c", cmd)
}

func (o *Orchestrator) aws(ctx context.Context, args ...string) (string, error) {
	full := append([]string{"--region", o.Cfg.Region}, args...)
	return o.Runner.Run(ctx, "aws", full...)
}

func (o *Orchestrator) helm(ctx context.Context, args ...string) (string, error) {
	full := append([]string{"--kube-context", o.Cfg.KubeContext}, args...)
	return o.Runner.Run(ctx, "helm", full...)
}

func (o *Orchestrator) printf(format string, a ...any) {
	if o.Out != nil {
		fmt.Fprintf(o.Out, format, a...)
	}
}

func (o *Orchestrator) info(msg string, args ...any) {
	if o.Log != nil {
		o.Log.Info(msg, args...)
	}
}

func shellQuote(s string) string {
	return "'" + strings.ReplaceAll(s, "'", "'\\''") + "'"
}
