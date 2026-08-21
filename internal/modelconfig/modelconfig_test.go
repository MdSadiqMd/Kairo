package modelconfig

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoadProfiles(t *testing.T) {
	prod, err := Load("../..", "prod")
	if err != nil {
		t.Fatalf("load prod: %v", err)
	}
	if prod.Reasoner().HFModelID == "" {
		t.Fatal("prod reasoner model id is empty")
	}
	if prod.Reasoner().TotalGPUs() != 4 {
		t.Fatalf("prod reasoner GPUs = %d", prod.Reasoner().TotalGPUs())
	}

	local, err := Load("../..", "local")
	if err != nil {
		t.Fatalf("load local: %v", err)
	}
	if local.Reasoner().HFModelID == prod.Reasoner().HFModelID {
		t.Fatal("local reasoner should use a smaller backing model than prod")
	}
	if local.Fast().HFModelID == "" {
		t.Fatal("local fast model id is empty")
	}
	for _, m := range local.OrderedModels() {
		if m.RequireGPU || m.TotalGPUs() != 0 {
			t.Fatalf("local model %s rendered GPU requirements", m.LogicalName)
		}
	}
}

func TestProfileName(t *testing.T) {
	if ProfileName("local", false) != "local" {
		t.Fatal("local env should use local profile")
	}
	if ProfileName("prod", false) != "prod" {
		t.Fatal("prod env should use prod profile")
	}
}

func TestZKInferenceToggle(t *testing.T) {
	cfg, err := LoadConfig("../..")
	if err != nil {
		t.Fatalf("LoadConfig: %v", err)
	}
	if !cfg.ZKInferenceEnabled() {
		t.Fatal("real config with zk_inference=true should be enabled")
	}

	for _, tc := range []struct {
		name    string
		json    string
		enabled bool
	}{
		{"missing_defaults_true", `{"profiles":{"test":{"runtime":"r","models":{"reasoner":{"logical_name":"reasoner","role":"reasoner","hf_model_id":"m","served_model_name":"s","endpoint_service":"e","params_b":1,"max_model_len":1,"replicas":1,"tensor_parallel_size":1},"fast":{"logical_name":"fast","role":"fast","hf_model_id":"m","served_model_name":"s","endpoint_service":"e","params_b":1,"max_model_len":1,"replicas":1,"tensor_parallel_size":1}}}}}`, true},
		{"explicit_true", `{"zk_inference":true,"profiles":{"test":{"runtime":"r","models":{"reasoner":{"logical_name":"reasoner","role":"reasoner","hf_model_id":"m","served_model_name":"s","endpoint_service":"e","params_b":1,"max_model_len":1,"replicas":1,"tensor_parallel_size":1},"fast":{"logical_name":"fast","role":"fast","hf_model_id":"m","served_model_name":"s","endpoint_service":"e","params_b":1,"max_model_len":1,"replicas":1,"tensor_parallel_size":1}}}}}`, true},
		{"explicit_false", `{"zk_inference":false,"profiles":{"test":{"runtime":"r","models":{"reasoner":{"logical_name":"reasoner","role":"reasoner","hf_model_id":"m","served_model_name":"s","endpoint_service":"e","params_b":1,"max_model_len":1,"replicas":1,"tensor_parallel_size":1},"fast":{"logical_name":"fast","role":"fast","hf_model_id":"m","served_model_name":"s","endpoint_service":"e","params_b":1,"max_model_len":1,"replicas":1,"tensor_parallel_size":1}}}}}`, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			dir := t.TempDir()
			cfgDir := filepath.Join(dir, "config")
			os.MkdirAll(cfgDir, 0o755)
			os.WriteFile(filepath.Join(cfgDir, "models.json"), []byte(tc.json), 0o644)
			cfg, err := LoadConfig(dir)
			if err != nil {
				t.Fatalf("LoadConfig: %v", err)
			}
			if cfg.ZKInferenceEnabled() != tc.enabled {
				t.Fatalf("got %v, want %v", cfg.ZKInferenceEnabled(), tc.enabled)
			}
		})
	}
}
