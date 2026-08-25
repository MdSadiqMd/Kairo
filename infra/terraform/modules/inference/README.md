# model_inference

Distributed multi-GPU inference for Model-32B on GPUs individually too small to
hold the model (§10.6). Tensor-parallel (TP) sharding forces genuine distributed
inference, driven by a **single control knob: `model_replicas`**.

## The control model

```text
total_gpus = model_replicas × tensor_parallel_size
nodes      = ceil(total_gpus / gpus_per_node)   # gpus_per_node = 4 on g5.12xlarge
```

Set `model_replicas`; Kubernetes schedules that many `tensor_parallel_size`-GPU
pods; Karpenter provisions exactly enough single-type nodes and scales back down
when replicas are removed. `limits.nvidia.com/gpu = max_total_gpus` caps the fleet
so a large replica count cannot run away on cost.

| `model_replicas` | GPUs requested | `g5.12xlarge` nodes |
|---:|---:|---:|
| 1 | 4 | 1 |
| 2 | 8 | 2 |
| 4 | 16 | 4 |

## What it provisions (as rendered YAML outputs)

1. A Karpenter EC2NodeClass + NodePool restricted to the **one** instance type
   (`node.kubernetes.io/instance-type In [g5.12xlarge]`, on-demand,
   `nvidia.com/gpu` taint, `limits.nvidia.com/gpu = max_total_gpus`, `WhenEmpty`
   consolidation, ~300 GiB gp3 root with provisioned throughput per §24 win 12).
2. A vLLM Deployment with `replicas = model_replicas` and
   `nvidia.com/gpu = tensor_parallel_size` for **both** requests and limits.

Manifests are emitted as `nodepool_yaml` and `deployment_yaml`; `start.sh` applies
them with `kubectl` (the module stays provider-light and offline-plannable).

## Correctness gotchas enforced here

- **`/dev/shm` ≥ 16 Gi**: an in-memory `emptyDir` (`medium: Memory`) is mounted at
  `/dev/shm`. vLLM TP uses NCCL over shared memory; the default 64 MB makes
  multi-GPU startup hang or crash — the single most common multi-GPU failure.
- **Request == limit for GPUs**: extended resources cannot be over/under-committed,
  so the container sets identical `requests` and `limits` of `nvidia.com/gpu`.
- **One pod per node falls out naturally**: a 4-GPU pod can't share a 4-GPU node;
  no anti-affinity needed.
- **PCIe, not NVLink**: g5 A10Gs interconnect over PCIe, so TP-4 all-reduce is
  slower than an NVLink box. Acceptable; note it when benchmarking (§10.8 Rule 4).
- **Cold start**: ~64 GB weight download per pod on first start; `HF_HUB_ENABLE_HF_TRANSFER=1`
  is set to saturate bandwidth. Node-local cache is fine for now; FSx later (§10.5).

## Plan-time validation

`tensor_parallel_size` is validated to be one of `[1, 2, 4, 8]` (must divide
Model-32B's 64 attention heads and 8 KV heads). The two capacity invariants fail
at **plan** time, not at 3 a.m., via `terraform_data` preconditions:

```hcl
resource "terraform_data" "guardrails" {
  input = {
    total_gpus = local.total_gpus
    nodes      = local.nodes
  }

  lifecycle {
    precondition {
      condition     = var.tensor_parallel_size <= var.gpus_per_node
      error_message = "tensor_parallel_size (${var.tensor_parallel_size}) must be <= gpus_per_node (${var.gpus_per_node}); a single instance cannot shard across more GPUs than it has (§10.6)."
    }

    precondition {
      condition     = var.model_replicas * var.tensor_parallel_size <= var.max_total_gpus
      error_message = "model_replicas * tensor_parallel_size (${var.model_replicas * var.tensor_parallel_size}) exceeds max_total_gpus (${var.max_total_gpus}); raise max_total_gpus or lower model_replicas (§10.6)."
    }
  }
}
```

## Key variables

| Variable | Purpose | Default |
|---|---|---|
| `gpu_instance_type` | The single allowed GPU instance type | `g5.12xlarge` |
| `gpus_per_node` | GPUs on that instance | `4` |
| `tensor_parallel_size` | GPUs each instance shards across | `4` |
| `model_replicas` | **How many configured model instances to run (the knob)** | `1` |
| `max_total_gpus` | NodePool GPU cap for cost safety | `16` |
| `model_id` | HF model id | `MODEL_PROVIDER/Model-32B` |
| `max_model_len` | Context bound (caps KV-cache VRAM) | `16384` |

## Outputs

`total_gpus`, `nodes`, `nodepool_yaml`, `deployment_yaml`, `instance_type`,
`model_id`, `nodepool_name`, `deployment_name`.

## Growth path (out of scope now)

TP=2 on an FP8-capable single type (e.g. `g6.12xlarge`) to fit two instances per
node; a second instance type for capacity resilience; cross-node TP/PP for 235B
via LWS or Ray + EFA (§10.7).
