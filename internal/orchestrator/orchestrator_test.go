package orchestrator

import (
	"bytes"
	"context"
	"io"
	"strings"
	"testing"

	"github.com/MdSadiqMd/Kairo/internal/command"
	"github.com/MdSadiqMd/Kairo/internal/config"
	"github.com/MdSadiqMd/Kairo/internal/logx"
	"github.com/MdSadiqMd/Kairo/internal/modelconfig"
)

// okHandler makes every shelled-out command succeed, returning realistic JSON
// for the few calls whose output the orchestrator parses.
func okHandler(name string, args []string) (string, error) {
	joined := name + " " + strings.Join(args, " ")
	switch {
	case strings.Contains(joined, "sts get-caller-identity"):
		return `{"Account":"111122223333","Arn":"arn:aws:iam::111122223333:user/ci"}`, nil
	case strings.Contains(joined, "configure get region"):
		return "us-west-2\n", nil
	case strings.Contains(joined, "service-quotas get-service-quota"):
		return `{"Quota":{"Value":128}}`, nil
	case strings.Contains(joined, "docker info --format"):
		return `{"NCPU":16,"MemTotal":42949672960,"Architecture":"aarch64"}`, nil
	case strings.Contains(joined, "s3api head-bucket"):
		return "", nil
	case strings.Contains(joined, "output -json irsa_role_arns"):
		return `{"router":"arn:aws:iam::111122223333:role/kairo-cloud-dev-router",` +
			`"inference_pod":"arn:aws:iam::111122223333:role/kairo-cloud-dev-inference-pod",` +
			`"log_ingestor":"arn:aws:iam::111122223333:role/kairo-cloud-dev-log-ingestor",` +
			`"eval_runner":"arn:aws:iam::111122223333:role/kairo-cloud-dev-eval-runner",` +
			`"training_job":"arn:aws:iam::111122223333:role/kairo-cloud-dev-training-job",` +
			`"agent_worker":"arn:aws:iam::111122223333:role/kairo-cloud-dev-agent-worker",` +
			`"proof_worker":"arn:aws:iam::111122223333:role/kairo-cloud-dev-proof-worker"}`, nil
	case strings.Contains(joined, "output -json bucket_names"):
		return `{"raw_events":"kairo-cloud-dev-raw-events","redacted_events":"kairo-cloud-dev-redacted-events",` +
			`"checkpoints":"kairo-cloud-dev-checkpoints","eval_results":"kairo-cloud-dev-eval-results",` +
			`"datasets":"kairo-cloud-dev-datasets","model_artifacts":"kairo-cloud-dev-model-artifacts"}`, nil
	case strings.Contains(joined, "output -json"):
		return `{"inference_url":{"value":"https://alb.example/v1/chat/completions"},` +
			`"api_key_secret_arn":{"value":"arn:aws:secretsmanager:us-west-2:111122223333:secret:kairo-dev-api-key"},` +
			`"grafana_url":{"value":"https://grafana.example"}}`, nil
	case strings.Contains(joined, "output -raw ecr_registry"):
		return "111122223333.dkr.ecr.us-west-2.amazonaws.com", nil
	case strings.Contains(joined, "resourcegroupstaggingapi get-resources"):
		return `{"ResourceTagMappingList":[]}`, nil
	case strings.Contains(joined, "describe-instances"),
		strings.Contains(joined, "describe-nat-gateways"),
		strings.Contains(joined, "describe-load-balancers"):
		return "0", nil
	default:
		return "", nil
	}
}

func newTestOrch(t *testing.T, env string, in io.Reader) (*Orchestrator, *command.FakeRunner, *bytes.Buffer) {
	t.Helper()
	cfg, err := config.Load(env, t.TempDir())
	if err != nil {
		t.Fatalf("config.Load: %v", err)
	}
	fr := &command.FakeRunner{Handler: okHandler}
	out := &bytes.Buffer{}
	models, err := modelconfig.Load("../..", modelconfig.ProfileName(env, cfg.IsLocal()))
	if err != nil {
		t.Fatalf("modelconfig.Load: %v", err)
	}
	o := New(cfg, models, fr, logx.New(io.Discard), out, in)
	return o, fr, out
}

func TestUpPhaseSequencing(t *testing.T) {
	o, fr, out := newTestOrch(t, "dev", nil)
	if err := o.Up(context.Background(), UpOptions{Model: "model-32b", Replicas: 2}); err != nil {
		t.Fatalf("Up: %v", err)
	}

	// Preflight (aws sts) must precede terraform apply, which must precede the
	// kubectl rollout, which must precede the smoke-eval verify step.
	stsIdx := fr.IndexOf("sts get-caller-identity")
	applyIdx := fr.IndexOf("apply -input=false -auto-approve")
	rolloutIdx := fr.IndexOf("rollout status deployment/vllm")
	verifyIdx := fr.IndexOf("router smoke request failed")
	if verifyIdx < 0 {
		verifyIdx = fr.IndexOf("Reply with ok.")
	}
	for _, c := range []struct {
		name string
		idx  int
	}{{"sts", stsIdx}, {"apply", applyIdx}, {"rollout", rolloutIdx}, {"verify", verifyIdx}} {
		if c.idx < 0 {
			t.Fatalf("expected command %q to have run; commands=%v", c.name, fr.Commands())
		}
	}
	if !(stsIdx < applyIdx && applyIdx < rolloutIdx && rolloutIdx < verifyIdx) {
		t.Fatalf("phase order violated: sts=%d apply=%d rollout=%d verify=%d",
			stsIdx, applyIdx, rolloutIdx, verifyIdx)
	}
	if !strings.Contains(out.String(), "is up.") {
		t.Errorf("contract block not printed: %q", out.String())
	}
	if !strings.Contains(out.String(), "arn:aws:secretsmanager") {
		t.Errorf("api key ARN not in contract: %q", out.String())
	}
}

func TestUpPlanOnlyStopsBeforeApply(t *testing.T) {
	o, fr, _ := newTestOrch(t, "dev", nil)
	if err := o.Up(context.Background(), UpOptions{PlanOnly: true}); err != nil {
		t.Fatalf("Up plan-only: %v", err)
	}
	if fr.IndexOf("plan -input=false") < 0 {
		t.Fatalf("expected terraform plan to run; commands=%v", fr.Commands())
	}
	if fr.IndexOf("apply -input=false") >= 0 {
		t.Fatalf("plan-only must not apply; commands=%v", fr.Commands())
	}
	if fr.IndexOf("rollout status") >= 0 {
		t.Fatalf("plan-only must not roll out kubernetes; commands=%v", fr.Commands())
	}
}

func TestUpSkipImages(t *testing.T) {
	o, fr, _ := newTestOrch(t, "dev", nil)
	if err := o.Up(context.Background(), UpOptions{SkipImages: true}); err != nil {
		t.Fatalf("Up: %v", err)
	}
	if fr.IndexOf("docker build") >= 0 {
		t.Fatalf("--skip-images must not build images; commands=%v", fr.Commands())
	}
}

func TestDownTeardownOrder(t *testing.T) {
	o, fr, _ := newTestOrch(t, "dev", strings.NewReader("dev\n"))
	if err := o.Down(context.Background(), DownOptions{}); err != nil {
		t.Fatalf("Down: %v", err)
	}

	drainIdx := fr.IndexOf("scale deployment --all --replicas=0")
	karpenterIdx := fr.IndexOf("delete nodepools")
	destroyIdx := fr.IndexOf("destroy -input=false")
	sweepIdx := fr.IndexOf("resourcegroupstaggingapi get-resources")

	for _, c := range []struct {
		name string
		idx  int
	}{{"drain", drainIdx}, {"karpenter", karpenterIdx}, {"destroy", destroyIdx}, {"sweep", sweepIdx}} {
		if c.idx < 0 {
			t.Fatalf("expected %q to have run; commands=%v", c.name, fr.Commands())
		}
	}
	// The whole point of teardown ordering: kubernetes drain and Karpenter reaping must run
	// BEFORE terraform destroy, and the tag sweep runs after.
	if !(drainIdx < destroyIdx) {
		t.Fatalf("kubernetes drain (%d) must precede terraform destroy (%d)", drainIdx, destroyIdx)
	}
	if !(karpenterIdx < destroyIdx) {
		t.Fatalf("karpenter reaping (%d) must precede terraform destroy (%d)", karpenterIdx, destroyIdx)
	}
	if !(destroyIdx < sweepIdx) {
		t.Fatalf("orphan sweep (%d) must run after terraform destroy (%d)", sweepIdx, destroyIdx)
	}
}

func TestDownConfirmationGating(t *testing.T) {
	tests := []struct {
		name    string
		env     string
		input   string
		opts    DownOptions
		wantErr bool
	}{
		{"dev correct name", "dev", "dev\n", DownOptions{}, false},
		{"dev wrong name", "dev", "nope\n", DownOptions{}, true},
		{"dev empty", "dev", "\n", DownOptions{}, true},
		{"prod without force", "prod", "prod\nDESTROY prod\n", DownOptions{}, true},
		{"prod with force ok", "prod", "prod\nDESTROY prod\n", DownOptions{Force: true}, false},
		{"prod force wrong second", "prod", "prod\nnope\n", DownOptions{Force: true}, true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			o, _, _ := newTestOrch(t, tt.env, strings.NewReader(tt.input))
			err := o.Down(context.Background(), tt.opts)
			if tt.wantErr && err == nil {
				t.Fatalf("expected error, got nil")
			}
			if !tt.wantErr && err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if tt.wantErr {
				if _, ok := err.(ErrConfirmationFailed); !ok {
					// prod-without-force also returns ErrConfirmationFailed.
					t.Fatalf("expected ErrConfirmationFailed, got %T: %v", err, err)
				}
			}
		})
	}
}

func TestDownConfirmationBlocksDestroy(t *testing.T) {
	o, fr, _ := newTestOrch(t, "dev", strings.NewReader("wrong\n"))
	if err := o.Down(context.Background(), DownOptions{}); err == nil {
		t.Fatal("expected confirmation failure")
	}
	if fr.IndexOf("destroy") >= 0 {
		t.Fatalf("failed confirmation must not reach terraform destroy; commands=%v", fr.Commands())
	}
}

func TestSweepDryRunDoesNotMutate(t *testing.T) {
	o, fr, _ := newTestOrch(t, "dev", nil)
	if _, err := o.Sweep(context.Background(), true); err != nil {
		t.Fatalf("Sweep: %v", err)
	}
	if fr.IndexOf("untag-resources") >= 0 {
		t.Fatalf("dry-run must not untag; commands=%v", fr.Commands())
	}
}
