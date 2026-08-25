# eks

EKS control plane for the Kairo platform (plan §9.4).

Provisions:

- `aws_eks_cluster` in private-app subnets. Private endpoint always on; public
  endpoint gated by `endpoint_public_access` and restricted to
  `endpoint_public_access_cidrs`.
- Control-plane logs: api, audit, authenticator, controllerManager, scheduler.
- Envelope encryption of Kubernetes secrets with `secrets_kms_key_arn`
  (`enable_secrets_encryption`, default true).
- IAM OIDC provider for IRSA (via `tls_certificate` thumbprint).
- Cluster IAM role (`AmazonEKSClusterPolicy`) and a system managed node group
  with its own node role (`AmazonEKSWorkerNodePolicy`, `AmazonEKS_CNI_Policy`,
  `AmazonEC2ContainerRegistryReadOnly`, `AmazonSSMManagedInstanceCore`), labeled
  `role=system` and optionally tainted `CriticalAddonsOnly=true:NoSchedule`.
- Core add-ons: vpc-cni, coredns, kube-proxy, aws-ebs-csi-driver. Versions in
  `addon_versions` are optional; null resolves to the cluster's latest default.
  The EBS CSI driver runs under a dedicated IRSA role
  (`kube-system/ebs-csi-controller-sa`, `AmazonEBSCSIDriverPolicy`).

## Conventions

- OIDC subject convention for IRSA:
  `system:serviceaccount:<namespace>:<sa-name>`, audience `sts.amazonaws.com`.
- Karpenter discovery: tag the EKS-managed cluster security group
  (`cluster_security_group_id`) with `karpenter.sh/discovery = var.name_prefix`
  so Karpenter can discover it. The SG is created by EKS, so apply the tag on
  the consumer side (subnets/SG data sources) rather than in this module.
- The managed node group shares the cluster security group; `node_security_group_id`
  therefore returns the cluster SG.
- GPU nodes are provisioned by Karpenter (§9.5), not by this module.

## Outputs

`cluster_name`, `cluster_id`, `cluster_endpoint`, `cluster_arn`,
`cluster_version`, `cluster_certificate_authority_data`,
`cluster_security_group_id`, `node_security_group_id`, `oidc_provider_arn`,
`oidc_provider_url` (issuer without scheme), `cluster_oidc_issuer_url`.
