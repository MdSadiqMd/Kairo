// Package config derives the per-environment settings qctl needs from a single
// environment name. Everything else (bucket names, kube context, terraform
// dir) is a deterministic function of env and the fixed project name, so there
// is exactly one source of truth and no snowflake wiring.
package config

import (
	"fmt"
	"os"
	"path/filepath"
)

// Project is the universal tag/name prefix.
const Project = "kairo"

// DefaultModel is the model served when --model is not supplied.
const DefaultModel = "model-32b"

// LocalModel is the CPU-friendly model for local MiniStack mode.
const LocalModel = "MODEL_PROVIDER/Model-0.6B"

// MiniStackEndpoint is the default MiniStack/LocalStack endpoint.
const MiniStackEndpoint = "http://localhost:4566"

var validEnvs = map[string]bool{"dev": true, "staging": true, "prod": true, "local": true}

// Config is the resolved control-plane configuration for one environment.
type Config struct {
	Env           string
	Region        string
	ClusterName   string
	KubeContext   string
	StateBucket   string
	APIKeySecret  string
	TerraformDir  string
	KubernetesDir string
	Namespace     string
	Local         bool
	AWSEndpoint   string
	NamePrefix    string // terraform name_prefix variable (kairo-{env})
}

// Load validates env and derives every dependent value. root is the repository
// root that terraform/kubernetes directories are resolved against.
func Load(env, root string) (Config, error) {
	if !validEnvs[env] {
		return Config{}, fmt.Errorf("invalid --env %q: must be one of dev, staging, prod, local", env)
	}
	if root == "" {
		root = "."
	}

	cfg := Config{
		Env:           env,
		Region:        "us-west-2",
		ClusterName:   fmt.Sprintf("kairo-cloud-%s", env),
		KubeContext:   fmt.Sprintf("kairo-cloud-%s", env),
		StateBucket:   fmt.Sprintf("%s-tfstate-%s", Project, env),
		APIKeySecret:  fmt.Sprintf("kairo-%s-api-key", env),
		TerraformDir:  filepath.Join(root, "infra", "terraform", "environments", env),
		KubernetesDir: filepath.Join(root, "infra", "kubernetes"),
		Namespace:     "kairo",
		Local:         env == "local",
		AWSEndpoint:   "",
		NamePrefix:    fmt.Sprintf("%s-%s", Project, env),
	}

	if cfg.Local {
		cfg.Region = "us-east-1"
		cfg.AWSEndpoint = MiniStackEndpoint
		cfg.StateBucket = fmt.Sprintf("%s-tfstate-%s", Project, env)
	}

	return cfg, nil
}

// IsProd reports whether the environment requires the extra teardown guards.
func (c Config) IsProd() bool { return c.Env == "prod" }

// IsLocal reports whether this is a local MiniStack environment.
func (c Config) IsLocal() bool { return c.Local }

// ExportLocalAWSEnv makes stock AWS clients, the AWS CLI, Terraform, and boto3
// target MiniStack without per-call endpoint branches.
func ExportLocalAWSEnv(c Config) {
	if !c.IsLocal() {
		return
	}
	setDefaultEnv("AWS_ENDPOINT_URL", c.AWSEndpoint)
	setDefaultEnv("AWS_ACCESS_KEY_ID", "test")
	setDefaultEnv("AWS_SECRET_ACCESS_KEY", "test")
	setDefaultEnv("AWS_DEFAULT_REGION", c.Region)
	setDefaultEnv("AWS_REGION", c.Region)
}

func setDefaultEnv(key, value string) {
	if os.Getenv(key) == "" {
		_ = os.Setenv(key, value)
	}
}
