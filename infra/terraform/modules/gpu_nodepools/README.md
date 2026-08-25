# gpu_nodepools

Renders Karpenter `NodePool` (`karpenter.sh/v1`) and `EC2NodeClass`
(`karpenter.k8s.aws/v1`) manifests as YAML string outputs. This module creates
**no AWS resources** — the Kubernetes provider is deliberately not used. The
rendered manifests are emitted as outputs and applied by `scripts/start.sh` with
`kubectl apply` once the cluster and Karpenter controller exist.

## Pools

| Pool | Families | Capacity | Consolidation | Notes |
|---|---|---|---|---|
| `gpu-inference-small` | g5, g6, g6e | on-demand | WhenEmpty (conservative) | Warm-min is set by KEDA, not here |
| `gpu-inference-large` | p5, p5e, p6 | reserved + on-demand | WhenEmpty | ODCR via `capacityReservationSelectorTerms`; never spot |
| `gpu-batch-eval` | g5, g6e | spot + on-demand | WhenEmptyOrUnderutilized (aggressive) | Tolerates interruption |
| `gpu-training` | p5, p5e | on-demand | WhenEmpty | ML Capacity Blocks; extra `dedicated=training` taint; 30d expiry |
| `cpu-system` | m, c, r | on-demand | WhenEmptyOrUnderutilized | amd64+arm64; no GPU taint |

## Capacity strategy (§9.6)

High-end P-family GPUs are supply-constrained, so interactive serving must never
depend on JIT-provisioning them. The `gpu-inference-large` EC2NodeClass targets
On-Demand Capacity Reservations through `capacityReservationSelectorTerms`
(matched by `capacity_reservation_tags`) and its NodePool allows only the
`reserved` and `on-demand` capacity types — never spot. Training runs use ML
Capacity Blocks. Only `gpu-batch-eval` uses spot, because batch tolerates
interruption.

## Node volumes (§24 win 12)

Every EC2NodeClass provisions a gp3 root volume with provisioned throughput
(1 GB/s) and IOPS decoupled from size, encrypted, IMDSv2-only
(`httpTokens: required`), so multi-GB weight loads are fast without oversizing.

## Usage

- `discovery_tag` defaults to `name_prefix`; tag subnets and security groups with
  `karpenter.sh/discovery = <discovery_tag>` for selection.
- Feed `karpenter_node_role_name` from the `karpenter` module output.
- GPU limits per pool bound fleet cost. Apply `all_manifests_yaml` after the
  Karpenter Helm release is healthy.
