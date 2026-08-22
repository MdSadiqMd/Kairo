package config

import (
	"strings"
	"testing"
)

func TestLoadValidEnvs(t *testing.T) {
	for _, env := range []string{"dev", "staging", "prod"} {
		cfg, err := Load(env, "/repo")
		if err != nil {
			t.Fatalf("Load(%q): %v", env, err)
		}
		if cfg.Env != env {
			t.Errorf("Env = %q, want %q", cfg.Env, env)
		}
		if !strings.HasSuffix(cfg.TerraformDir, "environments/"+env) {
			t.Errorf("TerraformDir = %q, want suffix environments/%s", cfg.TerraformDir, env)
		}
		if cfg.ClusterName != "kairo-cloud-"+env {
			t.Errorf("ClusterName = %q", cfg.ClusterName)
		}
		if cfg.APIKeySecret != "kairo-"+env+"-api-key" {
			t.Errorf("APIKeySecret = %q", cfg.APIKeySecret)
		}
	}
}

func TestLoadRejectsUnknownEnv(t *testing.T) {
	if _, err := Load("qa", "/repo"); err == nil {
		t.Fatal("expected error for unknown env")
	}
}

func TestIsProd(t *testing.T) {
	prod, _ := Load("prod", ".")
	dev, _ := Load("dev", ".")
	if !prod.IsProd() {
		t.Error("prod.IsProd() = false")
	}
	if dev.IsProd() {
		t.Error("dev.IsProd() = true")
	}
}
