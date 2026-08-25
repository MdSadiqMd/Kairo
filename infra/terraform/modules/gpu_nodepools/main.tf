terraform {
  required_version = ">= 1.9"
  required_providers {
    aws = { source = "hashicorp/aws" }
  }
}

locals {
  discovery_tag  = var.discovery_tag != "" ? var.discovery_tag : var.name_prefix
  discovery_tags = { "karpenter.sh/discovery" = local.discovery_tag }

  # Karpenter v1 EC2NodeClass AMI alias (e.g. al2023@latest). AL2023 -> al2023.
  ami_alias = "${lower(var.ami_family)}@latest"

  gpu_taint = {
    key    = "nvidia.com/gpu"
    value  = "true"
    effect = "NoSchedule"
  }

  training_taint = {
    key    = "dedicated"
    value  = "training"
    effect = "NoSchedule"
  }

  # gp3 root volume with provisioned throughput/IOPS decoupled from size so
  # multi-GB weight loads get 1 GB/s without oversizing the disk.
  block_device_mappings = [{
    deviceName = "/dev/xvda"
    ebs = {
      volumeType          = "gp3"
      volumeSize          = var.root_volume_size
      throughput          = 1000
      iops                = 4000
      encrypted           = true
      deleteOnTermination = true
    }
  }]

  metadata_options = {
    httpEndpoint            = "enabled"
    httpTokens              = "required"
    httpPutResponseHopLimit = 1
  }

  pools = {
    # warm-min replica count is enforced by KEDA, not by the NodePool.
    "gpu-inference-small" = {
      instance_key         = "karpenter.k8s.aws/instance-family"
      instance_values      = ["g5", "g6", "g6e"]
      extra_requirements   = [{ key = "kubernetes.io/arch", operator = "In", values = ["amd64"] }]
      capacity_types       = ["on-demand"]
      taints               = [local.gpu_taint]
      consolidation_policy = "WhenEmpty"
      consolidate_after    = "1m"
      disruption_budget    = "10%"
      expire_after         = var.expire_after
      limits               = { "nvidia.com/gpu" = var.gpu_inference_small_limit }
      capacity_reservation = false
    }

    # P-family interactive serving launches into ODCR only; never spot/JIT.
    "gpu-inference-large" = {
      instance_key         = "karpenter.k8s.aws/instance-family"
      instance_values      = ["p5", "p5e", "p6"]
      extra_requirements   = [{ key = "kubernetes.io/arch", operator = "In", values = ["amd64"] }]
      capacity_types       = ["reserved", "on-demand"]
      taints               = [local.gpu_taint]
      consolidation_policy = "WhenEmpty"
      consolidate_after    = "1m"
      disruption_budget    = "10%"
      expire_after         = var.expire_after
      limits               = { "nvidia.com/gpu" = var.gpu_inference_large_limit }
      capacity_reservation = true
    }

    "gpu-batch-eval" = {
      instance_key         = "karpenter.k8s.aws/instance-family"
      instance_values      = ["g5", "g6e"]
      extra_requirements   = [{ key = "kubernetes.io/arch", operator = "In", values = ["amd64"] }]
      capacity_types       = ["spot", "on-demand"]
      taints               = [local.gpu_taint]
      consolidation_policy = "WhenEmptyOrUnderutilized"
      consolidate_after    = "30s"
      disruption_budget    = "50%"
      expire_after         = var.expire_after
      limits               = { "nvidia.com/gpu" = var.gpu_batch_eval_limit }
      capacity_reservation = false
    }

    # ML Capacity Blocks are reserved per training run and released when done.
    "gpu-training" = {
      instance_key         = "karpenter.k8s.aws/instance-family"
      instance_values      = ["p5", "p5e"]
      extra_requirements   = [{ key = "kubernetes.io/arch", operator = "In", values = ["amd64"] }]
      capacity_types       = ["on-demand"]
      taints               = [local.gpu_taint, local.training_taint]
      consolidation_policy = "WhenEmpty"
      consolidate_after    = "1m"
      disruption_budget    = "10%"
      expire_after         = var.expire_after_training
      limits               = { "nvidia.com/gpu" = var.gpu_training_limit }
      capacity_reservation = false
    }

    "cpu-system" = {
      instance_key         = "karpenter.k8s.aws/instance-category"
      instance_values      = ["m", "c", "r"]
      extra_requirements   = [{ key = "kubernetes.io/arch", operator = "In", values = var.cpu_arch }]
      capacity_types       = ["on-demand"]
      taints               = []
      consolidation_policy = "WhenEmptyOrUnderutilized"
      consolidate_after    = "1m"
      disruption_budget    = "20%"
      expire_after         = var.expire_after
      limits               = { "cpu" = var.cpu_system_cpu_limit }
      capacity_reservation = false
    }
  }

  ec2nodeclass_objects = {
    for name, cfg in local.pools : name => {
      apiVersion = "karpenter.k8s.aws/v1"
      kind       = "EC2NodeClass"
      metadata   = { name = name }
      spec = merge({
        role                       = var.karpenter_node_role_name
        amiSelectorTerms           = [{ alias = local.ami_alias }]
        subnetSelectorTerms        = [{ tags = local.discovery_tags }]
        securityGroupSelectorTerms = [{ tags = local.discovery_tags }]
        blockDeviceMappings        = local.block_device_mappings
        metadataOptions            = local.metadata_options
        tags = merge(var.tags, {
          "Name"     = "${var.name_prefix}-${name}"
          "nodepool" = name
        })
        }, cfg.capacity_reservation ? {
        capacityReservationSelectorTerms = [{ tags = var.capacity_reservation_tags }]
      } : {})
    }
  }

  nodepool_objects = {
    for name, cfg in local.pools : name => {
      apiVersion = "karpenter.sh/v1"
      kind       = "NodePool"
      metadata   = { name = name }
      spec = {
        template = {
          metadata = { labels = { "nodepool" = name } }
          spec = merge({
            expireAfter = cfg.expire_after
            nodeClassRef = {
              group = "karpenter.k8s.aws"
              kind  = "EC2NodeClass"
              name  = name
            }
            requirements = concat([
              { key = cfg.instance_key, operator = "In", values = cfg.instance_values },
              { key = "karpenter.sh/capacity-type", operator = "In", values = cfg.capacity_types },
            ], cfg.extra_requirements)
            }, length(cfg.taints) > 0 ? {
            taints = cfg.taints
          } : {})
        }
        disruption = {
          consolidationPolicy = cfg.consolidation_policy
          consolidateAfter    = cfg.consolidate_after
          budgets             = [{ nodes = cfg.disruption_budget }]
        }
        limits = cfg.limits
      }
    }
  }

  ec2nodeclass_manifests = { for name, obj in local.ec2nodeclass_objects : name => yamlencode(obj) }
  nodepool_manifests     = { for name, obj in local.nodepool_objects : name => yamlencode(obj) }

  ordered_pools = ["gpu-inference-small", "gpu-inference-large", "gpu-batch-eval", "gpu-training", "cpu-system"]

  all_manifests = flatten([
    for name in local.ordered_pools : [
      local.ec2nodeclass_manifests[name],
      local.nodepool_manifests[name],
    ]
  ])
}
