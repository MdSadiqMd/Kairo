// Package command defines the Runner seam that the orchestrator and preflight
// use to shell out to terraform/kubectl/aws/docker/helm. The production runner
// (ExecRunner) invokes binaries via os/exec; the test double (FakeRunner, in
// fakerunner.go) records calls and returns canned output so orchestration logic
// is unit-testable offline.
package command

import (
	"bytes"
	"context"
	"fmt"
	"os/exec"
	"strings"
)

// Runner executes an external command and returns its combined stdout.
type Runner interface {
	// Run executes name with args and returns stdout. Implementations must
	// honour ctx cancellation.
	Run(ctx context.Context, name string, args ...string) (string, error)
}

// ExecRunner is the production Runner backed by os/exec. Stdout is captured and
// returned; stderr is folded into the error so callers see the real failure.
type ExecRunner struct {
	// Dir, when set, is the working directory for every command.
	Dir string
}

func (r *ExecRunner) Run(ctx context.Context, name string, args ...string) (string, error) {
	cmd := exec.CommandContext(ctx, name, args...)
	cmd.Dir = r.Dir
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		return stdout.String(), fmt.Errorf("%s %s: %w: %s",
			name, strings.Join(args, " "), err, strings.TrimSpace(stderr.String()))
	}
	return stdout.String(), nil
}
