package modelconfig

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

const DefaultPath = "config/models.json"

type Config struct {
	ZKInference *bool              `json:"zk_inference"`
	Profiles    map[string]Profile `json:"profiles"`
}

func (c Config) ZKInferenceEnabled() bool {
	return c.ZKInference == nil || *c.ZKInference
}

type Profile struct {
	Name            string           `json:"-"`
	Runtime         string           `json:"runtime"`
	FallbackRuntime string           `json:"fallback_runtime"`
	Models          map[string]Model `json:"models"`
}

type Model struct {
	LogicalName        string  `json:"logical_name"`
	Role               string  `json:"role"`
	HFModelID          string  `json:"hf_model_id"`
	ServedModelName    string  `json:"served_model_name"`
	EndpointService    string  `json:"endpoint_service"`
	ParamsB            float64 `json:"params_b"`
	DType              string  `json:"dtype"`
	Precision          string  `json:"precision"`
	MaxModelLen        int     `json:"max_model_len"`
	Replicas           int     `json:"replicas"`
	RequireGPU         bool    `json:"require_gpu"`
	TensorParallelSize int     `json:"tensor_parallel_size"`
	GPUsPerReplica     int     `json:"gpus_per_replica"`
	GPUInstanceType    string  `json:"gpu_instance_type"`
	NodePool           string  `json:"nodepool"`
	Image              string  `json:"image"`
	CPURequest         string  `json:"cpu_request"`
	MemoryRequest      string  `json:"memory_request"`
	CPULimit           string  `json:"cpu_limit"`
	MemoryLimit        string  `json:"memory_limit"`
}

func LoadConfig(root string) (Config, error) {
	if root == "" {
		root = "."
	}
	path := filepath.Join(root, DefaultPath)
	b, err := os.ReadFile(path)
	if err != nil {
		return Config{}, err
	}
	var cfg Config
	if err := json.Unmarshal(b, &cfg); err != nil {
		return Config{}, err
	}
	return cfg, nil
}

func (c Config) Profile(name string) (Profile, error) {
	profile, ok := c.Profiles[name]
	if !ok {
		return Profile{}, fmt.Errorf("unknown model profile %q", name)
	}
	profile.Name = name
	if err := profile.Validate(); err != nil {
		return Profile{}, err
	}
	return profile, nil
}

func Load(root, profileName string) (Profile, error) {
	cfg, err := LoadConfig(root)
	if err != nil {
		return Profile{}, err
	}
	return cfg.Profile(profileName)
}

func ProfileName(env string, local bool) string {
	if local || env == "local" {
		return "local"
	}
	return "prod"
}

func (p Profile) Validate() error {
	if p.Runtime == "" {
		return fmt.Errorf("model profile %q missing runtime", p.Name)
	}
	for _, role := range []string{"reasoner", "fast"} {
		m, ok := p.Models[role]
		if !ok {
			return fmt.Errorf("model profile %q missing %s model", p.Name, role)
		}
		if err := m.Validate(role); err != nil {
			return fmt.Errorf("%s model: %w", role, err)
		}
	}
	return nil
}

func (m Model) Validate(role string) error {
	if m.LogicalName == "" || m.HFModelID == "" || m.ServedModelName == "" || m.EndpointService == "" {
		return fmt.Errorf("logical_name, hf_model_id, served_model_name, and endpoint_service are required")
	}
	if m.Role != role {
		return fmt.Errorf("role %q does not match map key %q", m.Role, role)
	}
	if m.MaxModelLen <= 0 || m.Replicas <= 0 || m.TensorParallelSize <= 0 {
		return fmt.Errorf("max_model_len, replicas, and tensor_parallel_size must be positive")
	}
	if m.RequireGPU {
		if m.GPUsPerReplica <= 0 {
			return fmt.Errorf("gpu profile requires gpus_per_replica > 0")
		}
		if m.TensorParallelSize > m.GPUsPerReplica {
			return fmt.Errorf("tensor_parallel_size must be <= gpus_per_replica")
		}
	} else if m.GPUsPerReplica != 0 {
		return fmt.Errorf("cpu profile must set gpus_per_replica to 0")
	}
	return nil
}

func (p Profile) Reasoner() Model { return p.Models["reasoner"] }

func (p Profile) Fast() Model { return p.Models["fast"] }

func (p Profile) Verifier() (Model, bool) {
	m, ok := p.Models["verifier"]
	return m, ok
}

func (p Profile) OrderedModels() []Model {
	models := []Model{p.Reasoner(), p.Fast()}
	if v, ok := p.Verifier(); ok {
		models = append(models, v)
	}
	return models
}

func (m Model) TotalGPUs() int {
	return m.Replicas * m.GPUsPerReplica
}
