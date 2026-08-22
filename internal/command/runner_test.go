package command

import (
	"context"
	"errors"
	"testing"
)

func TestFakeRunnerRecordsCalls(t *testing.T) {
	fr := &FakeRunner{}
	ctx := context.Background()
	_, _ = fr.Run(ctx, "terraform", "init")
	_, _ = fr.Run(ctx, "kubectl", "apply", "-k", "dir")

	if len(fr.Calls) != 2 {
		t.Fatalf("expected 2 calls, got %d", len(fr.Calls))
	}
	if got := fr.Commands()[1]; got != "kubectl apply -k dir" {
		t.Errorf("Commands()[1] = %q", got)
	}
	if fr.IndexOf("apply -k") != 1 {
		t.Errorf("IndexOf = %d, want 1", fr.IndexOf("apply -k"))
	}
	if fr.IndexOf("nonexistent") != -1 {
		t.Errorf("IndexOf(missing) = %d, want -1", fr.IndexOf("nonexistent"))
	}
}

func TestFakeRunnerHandler(t *testing.T) {
	fr := &FakeRunner{Handler: func(name string, args []string) (string, error) {
		if name == "boom" {
			return "", errors.New("kaboom")
		}
		return "ok", nil
	}}
	out, err := fr.Run(context.Background(), "echo")
	if err != nil || out != "ok" {
		t.Fatalf("out=%q err=%v", out, err)
	}
	if _, err := fr.Run(context.Background(), "boom"); err == nil {
		t.Fatal("expected error from handler")
	}
}

func TestExecRunnerRealCommand(t *testing.T) {
	r := &ExecRunner{}
	out, err := r.Run(context.Background(), "echo", "hello")
	if err != nil {
		t.Fatalf("echo: %v", err)
	}
	if out != "hello\n" {
		t.Errorf("out = %q, want %q", out, "hello\n")
	}
}

func TestExecRunnerError(t *testing.T) {
	r := &ExecRunner{}
	if _, err := r.Run(context.Background(), "false"); err == nil {
		t.Fatal("expected non-zero exit to error")
	}
}
