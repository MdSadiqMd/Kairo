# karpenter

AWS-side infrastructure for the Karpenter controller. Kubernetes-side objects
(Helm release, NodePools, EC2NodeClasses) are applied separately — NodePool and
EC2NodeClass manifests come from the `gpu_nodepools` module.

## What this module creates

- **Controller IRSA role** federating the EKS OIDC provider for the
  `kube-system:karpenter` service account, with an inline policy scoped to the
  standard Karpenter controller permissions (EC2 fleet/launch-template lifecycle,
  `iam:PassRole` on the node role only, pricing, SSM, `eks:DescribeCluster`, and
  interruption-queue consumption).
- **Node IAM role + instance profile** with the four managed policies Karpenter
  nodes require (EKS worker, CNI, ECR read-only, SSM core).
- **SQS interruption queue** (SSE enabled, 300s retention) and its access policy.
- **EventBridge rules** routing Spot interruption, rebalance recommendation,
  instance state-change, and AWS Health events to the queue.

## Interruption handling

Karpenter watches the SQS queue for termination signals. On a Spot interruption
warning, rebalance recommendation, unhealthy-instance state change, or an AWS
Health event, it proactively cordons and drains the affected node and launches a
replacement before the instance is reclaimed, minimizing disruption to serving
pods. The queue uses SSE and a short (300s) retention because messages are only
actionable within the interruption window.

## Wiring

- Pass `oidc_provider_arn` / `oidc_provider_url` from the `eks` module outputs.
- Feed `node_role_name` into the `gpu_nodepools` module's
  `karpenter_node_role_name`.
- Configure the Karpenter Helm chart with `controller_role_arn` (service-account
  annotation) and `interruption_queue_name`.
