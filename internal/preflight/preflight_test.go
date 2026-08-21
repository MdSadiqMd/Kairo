package preflight

import (
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/MdSadiqMd/Kairo/internal/config"
)

type fakeRunner struct {
	handler func(name string, args []string) (string, error)
}

func (f fakeRunner) Run(_ context.Context, name string, args ...string) (string, error) {
	return f.handler(name, args)
}

func devCfg(t *testing.T) config.Config {
	t.Helper()
	cfg, err := config.Load("dev", "/repo")
	if err != nil {
		t.Fatal(err)
	}
	return cfg
}

func TestRunAllPass(t *testing.T) {
	r := fakeRunner{handler: func(name string, args []string) (string, error) {
		joined := name + " " + strings.Join(args, " ")
		switch {
		case strings.Contains(joined, "info --format"):
			return `{"NCPU":16,"MemTotal":42949672960,"Architecture":"aarch64"}`, nil
		case strings.Contains(joined, "sts get-caller-identity"):
			return `{"Account":"1","Arn":"arn"}`, nil
		case strings.Contains(joined, "configure get region"):
			return "us-west-2", nil
		case strings.Contains(joined, "get-service-quota"):
			return `{"Quota":{"Value":64}}`, nil
		case strings.Contains(joined, "head-bucket"):
			return "", nil
		default:
			return "", nil
		}
	}}
	rep, err := Run(context.Background(), r, devCfg(t))
	if err != nil {
		t.Fatal(err)
	}
	if !rep.OK() {
		t.Fatalf("expected all checks to pass, failures=%v", rep.Failures())
	}
}

func TestMissingToolFails(t *testing.T) {
	r := fakeRunner{handler: func(name string, args []string) (string, error) {
		if name == "helm" {
			return "", errors.New("executable file not found in $PATH")
		}
		if strings.Contains(name+" "+strings.Join(args, " "), "sts get-caller-identity") {
			return `{"Account":"1"}`, nil
		}
		if strings.Contains(name+" "+strings.Join(args, " "), "docker info --format") {
			return `{"NCPU":16,"MemTotal":42949672960,"Architecture":"aarch64"}`, nil
		}
		if strings.Contains(strings.Join(args, " "), "get region") {
			return "us-west-2", nil
		}
		if strings.Contains(strings.Join(args, " "), "get-service-quota") {
			return `{"Quota":{"Value":64}}`, nil
		}
		return "", nil
	}}
	rep, _ := Run(context.Background(), r, devCfg(t))
	if rep.OK() {
		t.Fatal("expected failure for missing helm")
	}
	var found bool
	for _, f := range rep.Failures() {
		if f.Name == "tool:helm" && strings.Contains(f.Remediation, "helm") {
			found = true
		}
	}
	if !found {
		t.Fatalf("expected helm remediation, failures=%v", rep.Failures())
	}
}

func TestGPUQuotaZeroSurfacesRemediation(t *testing.T) {
	r := fakeRunner{handler: func(name string, args []string) (string, error) {
		joined := strings.Join(args, " ")
		switch {
		case strings.Contains(joined, "info --format"):
			return `{"NCPU":16,"MemTotal":42949672960,"Architecture":"aarch64"}`, nil
		case strings.Contains(joined, "sts get-caller-identity"):
			return `{"Account":"1"}`, nil
		case strings.Contains(joined, "get region"):
			return "us-west-2", nil
		case strings.Contains(joined, "get-service-quota"):
			return `{"Quota":{"Value":0}}`, nil
		default:
			return "", nil
		}
	}}
	rep, _ := Run(context.Background(), r, devCfg(t))
	var q *Result
	for i := range rep.Results {
		if rep.Results[i].Name == "aws:gpu-quota" {
			q = &rep.Results[i]
		}
	}
	if q == nil || q.OK {
		t.Fatal("expected gpu-quota check to fail")
	}
	if !strings.Contains(q.Remediation, gpuQuotaCode) {
		t.Fatalf("remediation must name the quota code %s: %q", gpuQuotaCode, q.Remediation)
	}
}

func TestStateBucketCreatedWhenMissing(t *testing.T) {
	var created bool
	r := fakeRunner{handler: func(name string, args []string) (string, error) {
		joined := strings.Join(args, " ")
		switch {
		case strings.Contains(joined, "info --format"):
			return `{"NCPU":16,"MemTotal":42949672960,"Architecture":"aarch64"}`, nil
		case strings.Contains(joined, "head-bucket"):
			return "", errors.New("Not Found")
		case strings.Contains(joined, "create-bucket"):
			created = true
			return "", nil
		case strings.Contains(joined, "sts get-caller-identity"):
			return `{"Account":"1"}`, nil
		case strings.Contains(joined, "get region"):
			return "us-west-2", nil
		case strings.Contains(joined, "get-service-quota"):
			return `{"Quota":{"Value":64}}`, nil
		default:
			return "", nil
		}
	}}
	rep, _ := Run(context.Background(), r, devCfg(t))
	if !created {
		t.Fatal("expected state bucket create-bucket to be invoked")
	}
	if !rep.OK() {
		t.Fatalf("expected pass after bucket creation, failures=%v", rep.Failures())
	}
}

func TestWrongRegionFails(t *testing.T) {
	r := fakeRunner{handler: func(name string, args []string) (string, error) {
		joined := strings.Join(args, " ")
		switch {
		case strings.Contains(joined, "info --format"):
			return `{"NCPU":16,"MemTotal":42949672960,"Architecture":"aarch64"}`, nil
		case strings.Contains(joined, "sts get-caller-identity"):
			return `{"Account":"1"}`, nil
		case strings.Contains(joined, "get region"):
			return "us-east-1", nil
		case strings.Contains(joined, "get-service-quota"):
			return `{"Quota":{"Value":64}}`, nil
		default:
			return "", nil
		}
	}}
	rep, _ := Run(context.Background(), r, devCfg(t))
	if rep.OK() {
		t.Fatal("expected region mismatch to fail")
	}
}
