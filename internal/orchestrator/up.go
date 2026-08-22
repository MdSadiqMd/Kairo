package orchestrator

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/MdSadiqMd/Kairo/internal/preflight"
)

// UpOptions are the flags accepted by `qctl up`.
type UpOptions struct {
	Model      string
	Replicas   int
	WithRL     bool
	PlanOnly   bool
	SkipImages bool
}

// Outputs is the machine-readable contract written to outputs.json.
type Outputs struct {
	Env          string `json:"env"`
	InferenceURL string `json:"inference_url"`
	APIKeySecret string `json:"api_key_secret_arn"`
	GrafanaURL   string `json:"grafana_url"`
	KubeContext  string `json:"kube_context"`
}

// Up runs Phases 0→5. It is idempotent: Terraform
// reconciles drift and Kubernetes applies are declarative, so re-running
// converges rather than duplicating resources.
func (o *Orchestrator) Up(ctx context.Context, opts UpOptions) error {
	if opts.Replicas <= 0 {
		opts.Replicas = o.Models.Reasoner().Replicas
	}

	if err := o.phasePreflight(ctx); err != nil {
		return err
	}

	if opts.PlanOnly {
		return o.terraformPlan(ctx, opts)
	}

	if err := o.phaseInfrastructure(ctx, opts); err != nil {
		return fmt.Errorf("phase 1 (infrastructure): %w", err)
	}
	if err := o.phaseImages(ctx, opts); err != nil {
		return fmt.Errorf("phase 2 (images): %w", err)
	}
	if err := o.phaseKubernetes(ctx, opts); err != nil {
		return fmt.Errorf("phase 3 (kubernetes): %w", err)
	}
	if opts.WithRL {
		if err := o.phaseRL(ctx); err != nil {
			return fmt.Errorf("phase 4 (rl): %w", err)
		}
	}
	if opts.WithRL {
		if err := o.phaseProofs(ctx); err != nil {
			return fmt.Errorf("phase 4b (proofs): %w", err)
		}
	}
	if err := o.Verify(ctx); err != nil {
		return fmt.Errorf("phase 5 (verify): %w", err)
	}

	out, err := o.collectOutputs(ctx)
	if err != nil {
		return err
	}
	if err := o.writeOutputs(out); err != nil {
		return err
	}
	o.printContract(out)
	return nil
}

func (o *Orchestrator) phasePreflight(ctx context.Context) error {
	o.info("phase.preflight.start", "env", o.Cfg.Env)
	rep, err := preflight.Run(ctx, o.Runner, o.Cfg)
	if err != nil {
		return err
	}
	if !rep.OK() {
		for _, f := range rep.Failures() {
			o.printf("preflight FAILED %s: %s\n  remediation: %s\n", f.Name, f.Detail, f.Remediation)
		}
		return fmt.Errorf("preflight failed: %d check(s) did not pass", len(rep.Failures()))
	}
	o.info("phase.preflight.ok")
	return nil
}

func (o *Orchestrator) tfVars(opts UpOptions) []string {
	reasoner := o.Models.Reasoner()
	fast := o.Models.Fast()
	if opts.Model != "" {
		reasoner.HFModelID = opts.Model
	}
	args := []string{
		"-var", "model=" + modelTag(reasoner.HFModelID),
		"-var", "model_id=" + reasoner.HFModelID,
		"-var", "replicas=" + strconv.Itoa(opts.Replicas),
		"-var", "enable_rl=" + strconv.FormatBool(opts.WithRL),
		"-var", "zk_inference_enabled=" + strconv.FormatBool(o.ZKInference),
	}
	if o.Cfg.IsLocal() {
		args = append([]string{"-var-file=local.tfvars"}, args...)
		args = append(args,
			"-var", "fast_model_id="+fast.HFModelID,
			"-var", "reasoner_served_model_name="+reasoner.ServedModelName,
			"-var", "fast_served_model_name="+fast.ServedModelName,
			"-var", "reasoner_max_model_len="+strconv.Itoa(reasoner.MaxModelLen),
			"-var", "fast_max_model_len="+strconv.Itoa(fast.MaxModelLen),
		)
	}
	return args
}

func (o *Orchestrator) terraformPlan(ctx context.Context, opts UpOptions) error {
	o.info("phase.plan-only.start")
	if _, err := o.tf(ctx, o.tfInitArgs()...); err != nil {
		return err
	}
	args := append([]string{"plan", "-input=false", "-out=tfplan"}, o.tfVars(opts)...)
	out, err := o.tf(ctx, args...)
	if err != nil {
		return err
	}
	o.printf("%s\n", out)
	return nil
}

func (o *Orchestrator) phaseInfrastructure(ctx context.Context, opts UpOptions) error {
	o.info("phase.infra.start")
	if err := o.ensureStateBucket(ctx); err != nil {
		return err
	}
	if _, err := o.tf(ctx, o.tfInitArgs()...); err != nil {
		return err
	}
	if err := o.ensureLocalBuckets(ctx); err != nil {
		return err
	}
	args := append([]string{"apply", "-input=false", "-auto-approve"}, o.tfVars(opts)...)
	if _, err := o.tf(ctx, args...); err != nil {
		return err
	}
	if o.Cfg.IsLocal() {
		if err := o.writeLocalModelConfig(); err != nil {
			return err
		}
	}
	if err := o.writeZKConfig(ctx); err != nil {
		return err
	}
	if err := o.writeRLEnvConfig(ctx); err != nil {
		return err
	}
	if err := o.writeRouterConfig(ctx); err != nil {
		return err
	}
	if err := o.writeFSxPV(ctx); err != nil {
		return err
	}
	if err := o.writeEFSStorageClass(ctx); err != nil {
		return err
	}
	if err := o.seedModelRegistry(ctx, opts); err != nil {
		return err
	}
	o.info("phase.infra.ok")
	return nil
}

func (o *Orchestrator) ensureLocalBuckets(ctx context.Context) error {
	if !o.Cfg.IsLocal() {
		return nil
	}
	state, err := o.tf(ctx, "state", "list")
	if err != nil || !strings.Contains(state, "module.s3_data_lake.aws_s3_bucket.this") {
		for _, bucketSpec := range localBucketSpecs {
			bucket := o.Cfg.ClusterName + "-" + bucketSpec.suffix
			cmd := fmt.Sprintf(
				"aws --region %s --endpoint-url %s s3api head-bucket --bucket %s >/dev/null 2>&1 && "+
					"aws --region %s --endpoint-url %s s3 rb s3://%s --force >/dev/null || true",
				shellQuote(o.Cfg.Region), shellQuote(o.Cfg.AWSEndpoint), shellQuote(bucket),
				shellQuote(o.Cfg.Region), shellQuote(o.Cfg.AWSEndpoint), shellQuote(bucket),
			)
			if _, err := o.Runner.Run(ctx, "sh", "-c", cmd); err != nil {
				return fmt.Errorf("remove stale local S3 bucket %s: %w", bucket, err)
			}
		}
		return nil
	}
	for _, bucketSpec := range localBucketSpecs {
		address := fmt.Sprintf("module.s3_data_lake.aws_s3_bucket.this[\"%s\"]", bucketSpec.key)
		if !strings.Contains(state, address) {
			continue
		}
		bucket := o.Cfg.ClusterName + "-" + bucketSpec.suffix
		if _, err := o.aws(ctx, "s3api", "head-bucket", "--bucket", bucket); err != nil {
			if _, err := o.tf(ctx, "state", "rm", address); err != nil {
				return fmt.Errorf("remove stale local S3 bucket state %s: %w", bucket, err)
			}
		}
	}
	return nil
}

var localBucketSpecs = []struct {
	key    string
	suffix string
}{
	{key: "raw_events", suffix: "raw-events"},
	{key: "redacted_events", suffix: "redacted-events"},
	{key: "datasets", suffix: "datasets"},
	{key: "model_artifacts", suffix: "model-artifacts"},
	{key: "checkpoints", suffix: "checkpoints"},
	{key: "eval_results", suffix: "eval-results"},
	{key: "audit_logs", suffix: "audit-logs"},
}

func (o *Orchestrator) tfInitArgs() []string {
	args := []string{"init", "-input=false"}
	if o.Cfg.IsLocal() {
		args = append(args, "-force-copy")
	}
	return args
}

func (o *Orchestrator) phaseImages(ctx context.Context, opts UpOptions) error {
	if opts.SkipImages {
		o.info("phase.images.skipped")
		return nil
	}
	o.info("phase.images.start")
	registry, err := o.output(ctx, "ecr_registry")
	if err != nil {
		return err
	}
	// Authenticate docker to ECR. get-login-password must be piped into
	// docker login, so this is one shell pipeline (Runner.Run has no stdin).
	if !o.Cfg.IsLocal() {
		login := fmt.Sprintf(
			"aws ecr get-login-password --region %s | docker login --username AWS --password-stdin %s",
			o.Cfg.Region, registry)
		if _, err := o.Runner.Run(ctx, "sh", "-c", login); err != nil {
			return err
		}
	}
	// Build+push the router and vLLM images via scripts/build_image.sh, which
	// owns the per-service Dockerfile+context mapping (router builds from the
	// repo root; vLLM from infra/docker/vllm.Dockerfile). Phase 2 builds
	// exactly these two; CI's build-images.yml builds the full image set.
	services := []string{"router", "safety", "eval-runner", "log-ingestor", "vllm", "training"}
	if o.Cfg.IsLocal() {
		services = []string{"router", "safety", "eval-runner", "log-ingestor", "vllm-cpu", "training"}
	}
	if o.ZKInference {
		services = append(services, "proof-worker")
	}
	for _, svc := range services {
		args := []string{"--service", svc, "--registry", registry, "--tag", o.Cfg.Env}
		if !o.Cfg.IsLocal() {
			args = append(args, "--push")
		}
		if o.Cfg.IsLocal() {
			args = append(args, "--platform", "linux/arm64")
		}
		image, err := o.Runner.Run(ctx, "scripts/build_image.sh", args...)
		if err != nil {
			return err
		}
		if o.Cfg.IsLocal() {
			if err := o.importLocalImage(ctx, strings.TrimSpace(image)); err != nil {
				return err
			}
		}
	}
	o.info("phase.images.ok")
	return nil
}

func (o *Orchestrator) importLocalImage(ctx context.Context, image string) error {
	if image == "" {
		return fmt.Errorf("local image import: build did not return an image tag")
	}
	node := "ministack-eks-" + o.Cfg.ClusterName
	cmd := fmt.Sprintf(
		"node=%s; image=%s; "+
			"docker inspect \"$node\" >/dev/null 2>&1 || { echo \"MiniStack EKS node $node not found\" >&2; exit 1; }; "+
			"if [ \"$(docker inspect -f '{{.State.Running}}' \"$node\")\" != true ]; then docker start \"$node\" >/dev/null; fi; "+
			"docker save \"$image\" | docker exec -i \"$node\" ctr --address /run/k3s/containerd/containerd.sock --namespace k8s.io images import -",
		shellQuote(node), shellQuote(image),
	)
	if _, err := o.Runner.Run(ctx, "sh", "-c", cmd); err != nil {
		return fmt.Errorf("import local image %s into %s: %w", image, node, err)
	}
	return nil
}

func (o *Orchestrator) phaseKubernetes(ctx context.Context, opts UpOptions) error {
	o.info("phase.kubernetes.start")
	if _, err := o.aws(ctx, "eks", "update-kubeconfig",
		"--name", o.Cfg.ClusterName, "--alias", o.Cfg.KubeContext); err != nil {
		return err
	}
	if o.Cfg.IsLocal() {
		if err := o.mergeLocalK3sKubeconfig(ctx); err != nil {
			return err
		}
	} else {
		// Prod/staging: install cluster add-ons (CRDs + controllers) before applying manifests
		if err := o.installClusterAddons(ctx); err != nil {
			return fmt.Errorf("install cluster addons: %w", err)
		}
	}
	kustomizeDir := filepath.Join(o.Cfg.KubernetesDir, "overlays", "deploy")
	if o.Cfg.IsLocal() {
		kustomizeDir = filepath.Join(o.Cfg.KubernetesDir, "overlays", "local")
	} else if err := o.writeDeployOverlays(ctx); err != nil {
		return err
	}
	if _, err := o.applyKustomize(ctx, kustomizeDir); err != nil {
		return err
	}
	if _, err := o.kubectl(ctx, "-n", o.Cfg.Namespace,
		"rollout", "status", "deployment/vllm-reasoner", "--timeout=15m"); err != nil {
		return err
	}
	if _, err := o.kubectl(ctx, "-n", o.Cfg.Namespace,
		"rollout", "status", "deployment/router", "--timeout=5m"); err != nil {
		return err
	}
	o.info("phase.kubernetes.ok")
	return nil
}

func (o *Orchestrator) mergeLocalK3sKubeconfig(ctx context.Context) error {
	node := "ministack-eks-" + o.Cfg.ClusterName
	cmd := fmt.Sprintf(
		"node=%s; ctx=%s; tmp=$(mktemp); merged=$(mktemp); "+
			"docker inspect \"$node\" >/dev/null 2>&1 || { echo \"MiniStack EKS node $node not found\" >&2; exit 1; }; "+
			"if [ \"$(docker inspect -f '{{.State.Running}}' \"$node\")\" != true ]; then docker start \"$node\" >/dev/null; fi; "+
			"docker exec \"$node\" cat /etc/rancher/k3s/k3s.yaml | sed 's#https://127.0.0.1:6443#https://localhost:16443#g' > \"$tmp\"; "+
			"KUBECONFIG=\"$tmp\" kubectl config rename-context default \"$ctx\" >/dev/null; "+
			"mkdir -p \"$HOME/.kube\"; touch \"$HOME/.kube/config\"; "+
			"kubectl config delete-context \"$ctx\" >/dev/null 2>&1 || true; "+
			"KUBECONFIG=\"$tmp:$HOME/.kube/config\" kubectl config view --flatten > \"$merged\"; "+
			"mv \"$merged\" \"$HOME/.kube/config\"; "+
			"kubectl config use-context \"$ctx\" >/dev/null; "+
			"rm -f \"$tmp\"",
		shellQuote(node), shellQuote(o.Cfg.KubeContext),
	)
	if _, err := o.Runner.Run(ctx, "sh", "-c", cmd); err != nil {
		return fmt.Errorf("merge local k3s kubeconfig: %w", err)
	}
	return nil
}

func (o *Orchestrator) seedModelRegistry(ctx context.Context, opts UpOptions) error {
	table, err := o.output(ctx, "model_registry_table")
	if err != nil {
		return err
	}
	for _, entry := range o.Models.OrderedModels() {
		replicas := entry.Replicas
		if entry.Role == "reasoner" && opts.Replicas > 0 {
			replicas = opts.Replicas
		}
		hfModelID := entry.HFModelID
		if entry.Role == "reasoner" && opts.Model != "" {
			hfModelID = opts.Model
		}
		endpoint := fmt.Sprintf("http://%s.%s.svc.cluster.local:8000", entry.EndpointService, o.Cfg.Namespace)
		// deployable is GSI key type S, not BOOL — must be "true"/"false" strings
		item := fmt.Sprintf(`{"model_id":{"S":%q},"version":{"N":"1"},"name":{"S":%q},"role":{"S":%q},"endpoint":{"S":%q},"served_model_id":{"S":%q},"backing_model_id":{"S":%q},"max_model_len":{"N":%q},"replicas":{"N":%q},"precision":{"S":%q},"deployable":{"S":"true"}}`,
			entry.LogicalName, entry.LogicalName, entry.Role, endpoint, entry.ServedModelName, hfModelID, strconv.Itoa(entry.MaxModelLen), strconv.Itoa(replicas), entry.Precision)
		if _, err := o.aws(ctx, "dynamodb", "put-item", "--table-name", table, "--item", item); err != nil {
			return err
		}
	}
	return nil
}

// bucketNames reads the bucket_names map output. `terraform output -raw`
// rejects non-string values, so map outputs must go through -json.
func (o *Orchestrator) bucketNames(ctx context.Context) map[string]string {
	raw, err := o.tf(ctx, "output", "-json", "bucket_names")
	if err != nil {
		return nil
	}
	var bucketMap map[string]string
	if err := json.Unmarshal([]byte(strings.TrimSpace(raw)), &bucketMap); err != nil {
		return nil
	}
	return bucketMap
}

func (o *Orchestrator) writeZKConfig(ctx context.Context) error {
	zkEnabled := strconv.FormatBool(o.ZKInference)
	proofQueueURL, _ := o.output(ctx, "rl_proofs_queue_url")
	proofReceiptsTable, _ := o.output(ctx, "proof_receipts_table")
	modelArtifactsBucket := o.bucketNames(ctx)["model_artifacts"]
	artifactsURI := ""
	if modelArtifactsBucket != "" {
		artifactsURI = "s3://" + modelArtifactsBucket + "/proofs/"
	}
	content := strings.Join([]string{
		"ZK_INFERENCE=" + zkEnabled,
		"PROOF_QUEUE_URL=" + proofQueueURL,
		"PROOF_RECEIPTS_TABLE=" + proofReceiptsTable,
		"PROOF_ARTIFACTS_URI=" + artifactsURI,
		"",
	}, "\n")
	dir := filepath.Join(o.Cfg.KubernetesDir, "rl")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(dir, "zk-config.env"), []byte(content), 0o644)
}

func (o *Orchestrator) writeRLEnvConfig(ctx context.Context) error {
	kinesisStream, _ := o.output(ctx, "kinesis_stream_name")

	bucketMap := o.bucketNames(ctx)
	rawEvents := bucketMap["raw_events"]
	redactedEvents := bucketMap["redacted_events"]
	checkpoints := bucketMap["checkpoints"]
	evalResults := bucketMap["eval_results"]
	modelArtifacts := bucketMap["model_artifacts"]

	content := strings.Join([]string{
		"INGEST_STREAM=" + kinesisStream,
		"INGEST_BUCKET=" + rawEvents,
		"RAW_EVENTS_BUCKET=" + rawEvents,
		"REDACTED_EVENTS_BUCKET=" + redactedEvents,
		"CHECKPOINTS_BUCKET=" + checkpoints,
		"EVAL_RESULTS_BUCKET=" + evalResults,
		"MODEL_ARTIFACTS_BUCKET=" + modelArtifacts,
		"AGGREGATOR_INPUT_URI=s3://" + redactedEvents + "/redacted-events/",
		"AGGREGATOR_OUTPUT_URI=s3://" + redactedEvents + "/candidates/scored.ndjson",
		"ONLINE_RL_CANDIDATES_URI=s3://" + redactedEvents + "/candidates/scored.ndjson",
		"ONLINE_RL_OUTPUT_URI=s3://" + checkpoints + "/online-rl/candidate.json",
		"ONLINE_RL_RESULT_URI=s3://" + evalResults + "/online-rl/result.json",
		"ONLINE_RL_ADAPTER_S3_URI=s3://" + checkpoints + "/online-rl/adapters/candidate",
		"REDACTION_INPUT_URI=s3://" + rawEvents + "/raw-events/",
		"REDACTION_OUTPUT_URI=s3://" + redactedEvents + "/redacted-events/",
		// Enable synthetic feedback for initial RL loop (no real feedback endpoint yet)
		"AGGREGATOR_SYNTHETIC_FEEDBACK=true",
		"",
	}, "\n")
	dir := filepath.Join(o.Cfg.KubernetesDir, "rl")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(dir, "rl-env-config.env"), []byte(content), 0o644)
}

func (o *Orchestrator) writeRouterConfig(ctx context.Context) error {
	registryTable, _ := o.output(ctx, "model_registry_table")
	kinesisStream, _ := o.output(ctx, "kinesis_stream_name")
	if registryTable == "" && kinesisStream == "" {
		return nil
	}
	content := strings.Join([]string{
		"ROUTER_ENVIRONMENT=" + o.Cfg.Env,
		"ROUTER_LOG_LEVEL=INFO",
		"ROUTER_REGISTRY_BACKEND=dynamodb",
		"ROUTER_REGISTRY_TABLE=" + registryTable,
		"ROUTER_SAFETY_ENABLED=true",
		"ROUTER_SAFETY_URL=http://safety-classifier.kairo.svc.cluster.local:8080",
		"ROUTER_SAFETY_FAIL_OPEN=false",
		"ROUTER_AUTH_ENABLED=true",
		"ROUTER_API_KEYS_FILE=/etc/kairo/secrets/api_keys.json",
		"ROUTER_EVENTS_ENABLED=true",
		"ROUTER_EVENTS_BACKEND=kinesis",
		"ROUTER_EVENTS_STREAM=" + kinesisStream,
		"ROUTER_CACHE_AFFINITY_ENABLED=true",
		// RL feedback capture — required for online RL loop to receive training signal
		"ROUTER_CAPTURE_RAW_ENABLED=true",
		"ROUTER_DEFAULT_TRAINING_CONSENT=true",
		"",
	}, "\n")
	dir := filepath.Join(o.Cfg.KubernetesDir, "inference")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(dir, "router-config.env"), []byte(content), 0o644)
}

func (o *Orchestrator) writeEFSStorageClass(ctx context.Context) error {
	efsEnabled, _ := o.output(ctx, "efs_enabled")
	if efsEnabled != "true" {
		return nil
	}
	fsID, _ := o.output(ctx, "efs_file_system_id")
	if fsID == "" {
		return nil
	}
	content := fmt.Sprintf(`# EFS StorageClass for ReadWriteMany volumes (adapter storage).
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: efs-sc
  labels:
    app.kubernetes.io/part-of: Kairo
provisioner: efs.csi.aws.com
parameters:
  provisioningMode: efs-ap
  fileSystemId: %s
  directoryPerms: "700"
  gidRangeStart: "1000"
  gidRangeEnd: "2000"
  basePath: "/kairo"
reclaimPolicy: Retain
volumeBindingMode: Immediate
`, fsID)
	dir := filepath.Join(o.Cfg.KubernetesDir, "inference")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(dir, "efs-storageclass.yaml"), []byte(content), 0o644)
}

func (o *Orchestrator) writeFSxPV(ctx context.Context) error {
	fsxEnabled, _ := o.output(ctx, "fsx_enabled")
	if fsxEnabled != "true" {
		return nil
	}

	fsID, _ := o.output(ctx, "fsx_file_system_id")
	dnsName, _ := o.output(ctx, "fsx_dns_name")
	mountName, _ := o.output(ctx, "fsx_mount_name")

	if fsID == "" || dnsName == "" || mountName == "" {
		return nil
	}

	pvTemplate := `apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: fsx-weights
provisioner: fsx.csi.aws.com
mountOptions:
  - flock
parameters:
  deploymentType: PERSISTENT_2
---
apiVersion: v1
kind: PersistentVolume
metadata:
  name: kairo-weights
  labels:
    app.kubernetes.io/part-of: Kairo
spec:
  capacity:
    storage: 2400Gi
  accessModes:
    - ReadOnlyMany
  storageClassName: fsx-weights
  persistentVolumeReclaimPolicy: Retain
  csi:
    driver: fsx.csi.aws.com
    volumeHandle: %s
    volumeAttributes:
      dnsname: %s
      mountname: %s
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: kairo-weights
  namespace: kairo
spec:
  accessModes:
    - ReadOnlyMany
  storageClassName: fsx-weights
  resources:
    requests:
      storage: 2400Gi
  volumeName: kairo-weights
`
	content := fmt.Sprintf(pvTemplate, fsID, dnsName, mountName)
	dir := filepath.Join(o.Cfg.KubernetesDir, "fsx")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(dir, "pv-pvc.yaml"), []byte(content), 0o644)
}

func (o *Orchestrator) writeLocalModelConfig() error {
	if !o.Cfg.IsLocal() {
		return nil
	}
	reasoner := o.Models.Reasoner()
	fast := o.Models.Fast()
	content := strings.Join([]string{
		"REASONER_MODEL_ID=" + reasoner.HFModelID,
		"REASONER_SERVED_MODEL_NAME=" + reasoner.ServedModelName,
		"REASONER_MAX_MODEL_LEN=" + strconv.Itoa(reasoner.MaxModelLen),
		"FAST_MODEL_ID=" + fast.HFModelID,
		"FAST_SERVED_MODEL_NAME=" + fast.ServedModelName,
		"FAST_MAX_MODEL_LEN=" + strconv.Itoa(fast.MaxModelLen),
		"",
	}, "\n")
	path := filepath.Join(o.Cfg.KubernetesDir, "overlays", "local", "model-config.env")
	return os.WriteFile(path, []byte(content), 0o644)
}

func modelTag(model string) string {
	return strings.ToLower(strings.NewReplacer("/", "-", ":", "-", "_", "-").Replace(model))
}

// deployImageServices maps every kairo image placeholder that appears in the
// checked-in manifests. The generated deploy overlays rewrite each to the real
// ECR registry with the env tag pushed by phaseImages.
var deployImageServices = []string{
	"router", "safety", "eval-runner", "log-ingestor", "vllm", "training", "proof-worker", "agent-worker",
}

// serviceAccountRoles maps ServiceAccount names in base/serviceaccounts.yaml to
// the iam module's role_arns output keys (the IRSA naming contract).
var serviceAccountRoles = map[string]string{
	"router":            "router",
	"inference":         "inference_pod",
	"safety-classifier": "inference_pod",
	"log-ingestor":      "log_ingestor",
	"eval-runner":       "eval_runner",
	"agent-worker":      "agent_worker",
	"proof-worker":      "proof_worker",
	"training-job":      "training_job",
}

func (o *Orchestrator) irsaRoleArns(ctx context.Context) (map[string]string, error) {
	raw, err := o.tf(ctx, "output", "-json", "irsa_role_arns")
	if err != nil {
		return nil, err
	}
	var roleMap map[string]string
	if err := json.Unmarshal([]byte(strings.TrimSpace(raw)), &roleMap); err != nil {
		return nil, err
	}
	return roleMap, nil
}

func (o *Orchestrator) deployImagesYAML(registry string) string {
	var b strings.Builder
	b.WriteString("images:\n")
	for _, svc := range deployImageServices {
		fmt.Fprintf(&b, "- name: 000000000000.dkr.ecr.us-west-2.amazonaws.com/kairo/%s\n", svc)
		fmt.Fprintf(&b, "  newName: %s/kairo/%s\n", registry, svc)
		fmt.Fprintf(&b, "  newTag: %s\n", o.Cfg.Env)
	}
	return b.String()
}

// writeDeployOverlays generates kustomize overlays that bind the checked-in
// manifests (placeholder account id 000000000000) to the real environment:
// ECR image refs, IRSA role ARNs on ServiceAccounts, and the ALB ingress
// certificate/WAF annotations. This is the "qctl patches at rollout time"
// contract referenced by base/serviceaccounts.yaml.
func (o *Orchestrator) writeDeployOverlays(ctx context.Context) error {
	if o.Cfg.IsLocal() {
		return nil
	}
	registry, err := o.output(ctx, "ecr_registry")
	if err != nil || registry == "" {
		return fmt.Errorf("ecr_registry output missing; cannot render deploy overlay: %w", err)
	}
	images := o.deployImagesYAML(registry)

	roleArns, err := o.irsaRoleArns(ctx)
	if err != nil {
		return fmt.Errorf("irsa_role_arns output missing; cannot render deploy overlay: %w", err)
	}
	var saPatches strings.Builder
	for saName, roleKey := range serviceAccountRoles {
		arn, ok := roleArns[roleKey]
		if !ok || arn == "" {
			continue
		}
		fmt.Fprintf(&saPatches, `- patch: |-
    apiVersion: v1
    kind: ServiceAccount
    metadata:
      name: %s
      namespace: kairo
      annotations:
        eks.amazonaws.com/role-arn: %s
  target:
    kind: ServiceAccount
    name: %s
    namespace: kairo
`, saName, arn, saName)
	}

	wafArn, _ := o.output(ctx, "waf_web_acl_arn")
	certArn, _ := o.output(ctx, "acm_certificate_arn")
	hostname, _ := o.output(ctx, "inference_hostname")
	if hostname == "" {
		hostname = fmt.Sprintf("kairo-%s.example.com", o.Cfg.Env)
	}
	var ingressPatch strings.Builder
	ingressPatch.WriteString("- patch: |-\n")
	if certArn != "" {
		fmt.Fprintf(&ingressPatch, `    - op: replace
      path: /metadata/annotations/alb.ingress.kubernetes.io~1certificate-arn
      value: %s
`, certArn)
	} else {
		ingressPatch.WriteString(`    - op: replace
      path: /metadata/annotations/alb.ingress.kubernetes.io~1listen-ports
      value: '[{"HTTP":80}]'
    - op: remove
      path: /metadata/annotations/alb.ingress.kubernetes.io~1ssl-redirect
    - op: remove
      path: /metadata/annotations/alb.ingress.kubernetes.io~1certificate-arn
`)
	}
	if wafArn != "" {
		fmt.Fprintf(&ingressPatch, `    - op: replace
      path: /metadata/annotations/alb.ingress.kubernetes.io~1wafv2-acl-arn
      value: %s
`, wafArn)
	} else {
		ingressPatch.WriteString(`    - op: remove
      path: /metadata/annotations/alb.ingress.kubernetes.io~1wafv2-acl-arn
`)
	}
	fmt.Fprintf(&ingressPatch, `    - op: replace
      path: /metadata/annotations/alb.ingress.kubernetes.io~1group.name
      value: kairo-%s
    - op: replace
      path: /metadata/annotations/alb.ingress.kubernetes.io~1tags
      value: project=Kairo,env=%s,service=router
    - op: replace
      path: /spec/rules/0/host
      value: %s
  target:
    kind: Ingress
    name: router
    namespace: kairo
`, o.Cfg.Env, o.Cfg.Env, hostname)

	// vLLM model config patches (MODEL_ID, SERVED_MODEL_NAME, MAX_MODEL_LEN, TENSOR_PARALLEL_SIZE)
	reasoner := o.Models.Reasoner()
	fast := o.Models.Fast()
	var vllmPatches strings.Builder

	// Reasoner deployment
	fmt.Fprintf(&vllmPatches, `- patch: |-
    - op: replace
      path: /spec/template/spec/containers/0/env/0/value
      value: %s
    - op: replace
      path: /spec/template/spec/containers/0/env/1/value
      value: %s
    - op: replace
      path: /spec/template/spec/containers/0/env/2/value
      value: "%d"
    - op: replace
      path: /spec/template/spec/containers/0/env/3/value
      value: "%d"
  target:
    kind: Deployment
    name: vllm-reasoner
    namespace: kairo
`, reasoner.HFModelID, reasoner.ServedModelName, reasoner.TensorParallelSize, reasoner.MaxModelLen)

	// Fast deployment
	fmt.Fprintf(&vllmPatches, `- patch: |-
    - op: replace
      path: /spec/template/spec/containers/0/env/0/value
      value: %s
    - op: replace
      path: /spec/template/spec/containers/0/env/1/value
      value: %s
    - op: replace
      path: /spec/template/spec/containers/0/env/2/value
      value: "%d"
    - op: replace
      path: /spec/template/spec/containers/0/env/3/value
      value: "%d"
  target:
    kind: Deployment
    name: vllm-fast
    namespace: kairo
`, fast.HFModelID, fast.ServedModelName, fast.TensorParallelSize, fast.MaxModelLen)

	// Candidate deployment (uses reasoner model)
	fmt.Fprintf(&vllmPatches, `- patch: |-
    - op: replace
      path: /spec/template/spec/containers/0/env/0/value
      value: %s
    - op: replace
      path: /spec/template/spec/containers/0/env/2/value
      value: "%d"
    - op: replace
      path: /spec/template/spec/containers/0/env/3/value
      value: "%d"
  target:
    kind: Deployment
    name: vllm-reasoner-candidate
    namespace: kairo
`, reasoner.HFModelID, reasoner.TensorParallelSize, reasoner.MaxModelLen)

	root := fmt.Sprintf(`# GENERATED by qctl up — do not edit. Binds checked-in manifests to the %s
# environment (image registry, IRSA role ARNs, ALB ingress annotations, model config).
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
- ../..

%s
patches:
%s%s%s`, o.Cfg.Env, images, saPatches.String(), ingressPatch.String(), vllmPatches.String())

	sub := fmt.Sprintf(`# GENERATED by qctl up — do not edit. Image bindings for the %%s phase in %s.
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
- ../../%%s

%s`, o.Cfg.Env, images)

	overlays := map[string]string{
		"deploy":        root,
		"deploy-rl":     fmt.Sprintf(sub, "rl", "rl"),
		"deploy-proofs": fmt.Sprintf(sub, "proofs", "proofs"),
	}
	for name, content := range overlays {
		dir := filepath.Join(o.Cfg.KubernetesDir, "overlays", name)
		if err := os.MkdirAll(dir, 0o755); err != nil {
			return err
		}
		if err := os.WriteFile(filepath.Join(dir, "kustomization.yaml"), []byte(content), 0o644); err != nil {
			return err
		}
	}
	return nil
}

// ensureStateBucket bootstraps the per-env Terraform state bucket — the one
// resource that cannot live in Terraform state itself (Phase 0).
func (o *Orchestrator) ensureStateBucket(ctx context.Context) error {
	bucket := "kairo-tfstate-" + o.Cfg.Env
	if _, err := o.aws(ctx, "s3api", "head-bucket", "--bucket", bucket); err == nil {
		return nil
	}
	createArgs := []string{"s3api", "create-bucket", "--bucket", bucket}
	if o.Cfg.Region != "us-east-1" {
		createArgs = append(createArgs, "--create-bucket-configuration", "LocationConstraint="+o.Cfg.Region)
	}
	if _, err := o.aws(ctx, createArgs...); err != nil {
		return fmt.Errorf("creating state bucket %s: %w", bucket, err)
	}
	if _, err := o.aws(ctx, "s3api", "put-bucket-versioning", "--bucket", bucket,
		"--versioning-configuration", "Status=Enabled"); err != nil {
		return err
	}
	if _, err := o.aws(ctx, "s3api", "put-bucket-encryption", "--bucket", bucket,
		"--server-side-encryption-configuration",
		`{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"aws:kms"}}]}`); err != nil {
		return err
	}
	_, err := o.aws(ctx, "s3api", "put-public-access-block", "--bucket", bucket,
		"--public-access-block-configuration",
		"BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true")
	return err
}

// installClusterAddons installs Karpenter, NVIDIA device plugin, KEDA, Prometheus,
// External Secrets Operator, AWS LB Controller, and EFS CSI via helm. Then applies
// NodePool/EC2NodeClass CRs from terraform outputs. Required before manifests that
// reference these CRDs (ScaledObject, ExternalSecret, ServiceMonitor, nodeSelectors).
func (o *Orchestrator) installClusterAddons(ctx context.Context) error {
	if o.Cfg.IsLocal() {
		return nil
	}
	o.info("phase.addons.start")

	clusterEndpoint, _ := o.output(ctx, "cluster_endpoint")
	interruptionQueueName := o.Cfg.NamePrefix + "-karpenter-interruption"

	// Karpenter CRDs + controller
	if _, err := o.helm(ctx, "upgrade", "--install", "karpenter", "oci://public.ecr.aws/karpenter/karpenter",
		"--namespace", "kube-system", "--create-namespace",
		"--version", "1.1.1",
		"--set", "settings.clusterName="+o.Cfg.ClusterName,
		"--set", "settings.clusterEndpoint="+clusterEndpoint,
		"--set", "settings.interruptionQueue="+interruptionQueueName,
		"--set", "controller.resources.requests.cpu=500m",
		"--set", "controller.resources.requests.memory=512Mi",
		"--wait", "--timeout=5m"); err != nil {
		return fmt.Errorf("install karpenter: %w", err)
	}

	// NVIDIA device plugin (required for GPU scheduling)
	if _, err := o.helm(ctx, "upgrade", "--install", "nvidia-device-plugin",
		"oci://ghcr.io/nvidia/k8s-device-plugin/nvidia-device-plugin",
		"--namespace", "kube-system",
		"--version", "0.17.0",
		"--set", "runtimeClassName=nvidia",
		"--wait", "--timeout=3m"); err != nil {
		return fmt.Errorf("install nvidia device plugin: %w", err)
	}

	// AWS Load Balancer Controller (for ALB Ingress)
	vpcID, _ := o.output(ctx, "vpc_id")
	if _, err := o.helm(ctx, "upgrade", "--install", "aws-load-balancer-controller",
		"oci://public.ecr.aws/eks/aws-load-balancer-controller",
		"--namespace", "kube-system",
		"--version", "1.10.0",
		"--set", "clusterName="+o.Cfg.ClusterName,
		"--set", "vpcId="+vpcID,
		"--set", "region="+o.Cfg.Region,
		"--wait", "--timeout=3m"); err != nil {
		return fmt.Errorf("install aws-load-balancer-controller: %w", err)
	}

	// External Secrets Operator (for ExternalSecret CRs)
	if _, err := o.helm(ctx, "upgrade", "--install", "external-secrets",
		"oci://ghcr.io/external-secrets/charts/external-secrets",
		"--namespace", "external-secrets", "--create-namespace",
		"--version", "0.12.1",
		"--set", "installCRDs=true",
		"--wait", "--timeout=3m"); err != nil {
		return fmt.Errorf("install external-secrets: %w", err)
	}

	// KEDA (for ScaledObject CRs)
	if _, err := o.helm(ctx, "upgrade", "--install", "keda", "oci://ghcr.io/kedacore/charts/keda",
		"--namespace", "keda", "--create-namespace",
		"--version", "2.16.1",
		"--wait", "--timeout=3m"); err != nil {
		return fmt.Errorf("install keda: %w", err)
	}

	// kube-prometheus-stack (for ServiceMonitor CRs)
	if _, err := o.helm(ctx, "upgrade", "--install", "kube-prometheus-stack",
		"oci://ghcr.io/prometheus-community/charts/kube-prometheus-stack",
		"--namespace", "monitoring", "--create-namespace",
		"--version", "68.4.0",
		"--set", "prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false",
		"--set", "prometheus.prometheusSpec.podMonitorSelectorNilUsesHelmValues=false",
		"--wait", "--timeout=5m"); err != nil {
		return fmt.Errorf("install kube-prometheus-stack: %w", err)
	}

	// EFS CSI driver (for adapter-storage RWX PVC)
	if _, err := o.helm(ctx, "upgrade", "--install", "aws-efs-csi-driver",
		"oci://public.ecr.aws/eks/aws-efs-csi-driver",
		"--namespace", "kube-system",
		"--version", "3.1.2",
		"--set", "controller.serviceAccount.create=true",
		"--set", "controller.serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn="+o.Cfg.NamePrefix+"-efs-csi-controller",
		"--wait", "--timeout=3m"); err != nil {
		return fmt.Errorf("install aws-efs-csi-driver: %w", err)
	}

	// Apply NodePools and EC2NodeClasses from terraform output
	if err := o.applyNodePools(ctx); err != nil {
		return fmt.Errorf("apply nodepools: %w", err)
	}

	o.info("phase.addons.ok")
	return nil
}

// applyNodePools applies EC2NodeClass and NodePool CRs from terraform module outputs.
func (o *Orchestrator) applyNodePools(ctx context.Context) error {
	// Apply GPU nodepools from gpu_nodepools module
	if raw, err := o.tf(ctx, "output", "-json", "gpu_nodepool_manifests"); err == nil {
		var manifests string
		if json.Unmarshal([]byte(strings.TrimSpace(raw)), &manifests) == nil && manifests != "" {
			tmpfile := filepath.Join(os.TempDir(), "kairo-gpu-nodepools.yaml")
			if err := os.WriteFile(tmpfile, []byte(manifests), 0o644); err != nil {
				return err
			}
			if _, err := o.kubectl(ctx, "apply", "-f", tmpfile); err != nil {
				os.Remove(tmpfile)
				return fmt.Errorf("apply gpu nodepools: %w", err)
			}
			os.Remove(tmpfile)
		}
	}
	// Apply inference nodepool from inference module
	if raw, err := o.tf(ctx, "output", "-json", "model_nodepool_yaml"); err == nil {
		var manifests string
		if json.Unmarshal([]byte(strings.TrimSpace(raw)), &manifests) == nil && manifests != "" {
			tmpfile := filepath.Join(os.TempDir(), "kairo-inference-nodepool.yaml")
			if err := os.WriteFile(tmpfile, []byte(manifests), 0o644); err != nil {
				return err
			}
			if _, err := o.kubectl(ctx, "apply", "-f", tmpfile); err != nil {
				os.Remove(tmpfile)
				return fmt.Errorf("apply inference nodepool: %w", err)
			}
			os.Remove(tmpfile)
		}
	}
	return nil
}

func (o *Orchestrator) phaseRL(ctx context.Context) error {
	o.info("phase.rl.start")
	// RL plumbing (event pipeline, reward aggregator, eval CronJob) is declared
	// in Terraform behind enable_rl and rolled out with the RL kustomize overlay.
	rlDir := filepath.Join(o.Cfg.KubernetesDir, "overlays", "deploy-rl")
	if o.Cfg.IsLocal() {
		rlDir = filepath.Join(o.Cfg.KubernetesDir, "overlays", "local", "rl")
	}
	if _, err := o.applyKustomize(ctx, rlDir); err != nil {
		return err
	}
	o.info("phase.rl.ok")
	return nil
}

func (o *Orchestrator) phaseProofs(ctx context.Context) error {
	if !o.ZKInference {
		_, _ = o.kubectl(ctx, "-n", o.Cfg.Namespace, "delete", "deployment", "proof-worker", "--ignore-not-found")
		return nil
	}
	o.info("phase.proofs.start")
	proofsDir := filepath.Join(o.Cfg.KubernetesDir, "overlays", "deploy-proofs")
	if o.Cfg.IsLocal() {
		proofsDir = filepath.Join(o.Cfg.KubernetesDir, "overlays", "local", "proofs")
	}
	if _, err := o.applyKustomize(ctx, proofsDir); err != nil {
		return err
	}
	o.info("phase.proofs.ok")
	return nil
}

func (o *Orchestrator) output(ctx context.Context, name string) (string, error) {
	out, err := o.tf(ctx, "output", "-raw", name)
	if err != nil {
		return "", err
	}
	return out, nil
}

func (o *Orchestrator) collectOutputs(ctx context.Context) (Outputs, error) {
	raw, err := o.tf(ctx, "output", "-json")
	if err != nil {
		return Outputs{}, err
	}
	// Terraform emits {"name":{"value":...,"type":...}}; tolerate empty output
	// from a fake runner by falling back to derived values.
	var tfout map[string]struct {
		Value string `json:"value"`
	}
	_ = json.Unmarshal([]byte(raw), &tfout)
	get := func(k string) string { return tfout[k].Value }
	return Outputs{
		Env:          o.Cfg.Env,
		InferenceURL: get("inference_url"),
		APIKeySecret: get("api_key_secret_arn"),
		GrafanaURL:   get("grafana_url"),
		KubeContext:  o.Cfg.KubeContext,
	}, nil
}

func (o *Orchestrator) writeOutputs(out Outputs) error {
	b, err := json.MarshalIndent(out, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile("outputs.json", append(b, '\n'), 0o644)
}

func (o *Orchestrator) printContract(out Outputs) {
	o.printf("\n✅ Kairo [%s] is up.\n", o.Cfg.Env)
	o.printf("Inference URL : %s\n", out.InferenceURL)
	o.printf("API key       : %s   (fetch: make api-key)\n", out.APIKeySecret)
	o.printf("Grafana       : %s\n", out.GrafanaURL)
	o.printf("Kube context  : %s\n", out.KubeContext)
}
