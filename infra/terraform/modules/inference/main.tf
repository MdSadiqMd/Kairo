terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

locals {
  discovery_tag = var.discovery_tag != "" ? var.discovery_tag : var.name_prefix

  # The whole control model is these two lines: one knob (replicas)
  # deterministically decides GPUs and therefore nodes.
  # In CPU mode (gpus_per_node=0), nodes equals replicas directly.
  total_gpus = var.replicas * var.tensor_parallel_size
  nodes      = var.gpus_per_node > 0 ? ceil(local.total_gpus / var.gpus_per_node) : var.replicas

  nodeclass_name = "${var.name_prefix}-model"
  nodepool_name  = "${var.name_prefix}-model"
  app_name       = "${var.name_prefix}-kairo-vllm"

  common_tags = merge(var.tags, {
    "karpenter.sh/discovery" = local.discovery_tag
    component                = "inference"
  })

  ec2nodeclass = {
    apiVersion = "karpenter.k8s.aws/v1"
    kind       = "EC2NodeClass"
    metadata = {
      name = local.nodeclass_name
    }
    spec = {
      role = var.karpenter_node_role_name
      amiSelectorTerms = [
        { alias = "${lower(var.ami_family)}@latest" }
      ]
      subnetSelectorTerms = [
        { tags = { "karpenter.sh/discovery" = local.discovery_tag } }
      ]
      securityGroupSelectorTerms = [
        { tags = { "karpenter.sh/discovery" = local.discovery_tag } }
      ]
      # ~300 GiB gp3 with provisioned throughput holds the ~64 GB weight download
      # with headroom; gp3 decouples throughput from size for fast loads.
      blockDeviceMappings = [
        {
          deviceName = "/dev/xvda"
          ebs = {
            volumeSize          = "${var.root_volume_size_gib}Gi"
            volumeType          = "gp3"
            throughput          = var.root_volume_throughput
            iops                = var.root_volume_iops
            encrypted           = true
            deleteOnTermination = true
          }
        }
      ]
      metadataOptions = {
        httpEndpoint            = "enabled"
        httpTokens              = "required"
        httpPutResponseHopLimit = 2
      }
      tags = local.common_tags
    }
  }

  nodepool = {
    apiVersion = "karpenter.sh/v1"
    kind       = "NodePool"
    metadata = {
      name = local.nodepool_name
    }
    spec = {
      template = {
        metadata = {
          labels = {
            "nvidia.com/gpu.present" = "true"
            workload                 = "inference"
          }
        }
        spec = {
          nodeClassRef = {
            group = "karpenter.k8s.aws"
            kind  = "EC2NodeClass"
            name  = local.nodeclass_name
          }
          expireAfter = "720h"
          # A 4-GPU pod cannot share a 4-GPU node, so one-pod-per-node falls out
          # naturally with no anti-affinity.
          taints = [
            {
              key    = var.gpu_taint_key
              value  = "true"
              effect = "NoSchedule"
            }
          ]
          requirements = [
            {
              key      = "node.kubernetes.io/instance-type"
              operator = "In"
              values   = [var.gpu_instance_type]
            },
            {
              key      = "karpenter.sh/capacity-type"
              operator = "In"
              values   = ["on-demand"]
            }
          ]
        }
      }
      # Cost guardrail: the fleet can never exceed max_total_gpus GPUs regardless
      # of how large replicas is set.
      limits = {
        "nvidia.com/gpu" = var.max_total_gpus
      }
      disruption = {
        consolidationPolicy = "WhenEmpty"
        consolidateAfter    = "60s"
      }
    }
  }

  vllm_args = concat(
    [
      "--model", var.model_id,
      "--served-model-name", "model-32b",
      "--tensor-parallel-size", tostring(var.tensor_parallel_size),
      "--max-model-len", tostring(var.max_model_len),
      "--host", "0.0.0.0",
      "--port", "8000",
    ],
  )

  deployment = {
    apiVersion = "apps/v1"
    kind       = "Deployment"
    metadata = {
      name      = local.app_name
      namespace = var.namespace
      labels    = { app = local.app_name }
    }
    spec = {
      replicas = var.replicas
      selector = { matchLabels = { app = local.app_name } }
      template = {
        metadata = {
          labels = { app = local.app_name }
          annotations = {
            "prometheus.io/scrape" = "true"
            "prometheus.io/port"   = "8000"
            "prometheus.io/path"   = "/metrics"
          }
        }
        spec = {
          nodeSelector = {
            "node.kubernetes.io/instance-type" = var.gpu_instance_type
          }
          tolerations = [
            {
              key      = var.gpu_taint_key
              operator = "Equal"
              value    = "true"
              effect   = "NoSchedule"
            }
          ]
          containers = [
            {
              name  = "vllm"
              image = var.vllm_image
              args  = local.vllm_args
              ports = [
                { name = "http", containerPort = 8000 }
              ]
              env = [
                # Rust downloader saturates instance bandwidth for the ~64 GB pull.
                { name = "HF_HUB_ENABLE_HF_TRANSFER", value = "1" }
              ]
              # request == limit: extended GPU resources cannot be over/under-committed.
              resources = {
                requests = { "nvidia.com/gpu" = var.tensor_parallel_size }
                limits   = { "nvidia.com/gpu" = var.tensor_parallel_size }
              }
              readinessProbe = {
                httpGet             = { path = "/health", port = 8000 }
                initialDelaySeconds = 120
                periodSeconds       = 10
              }
              livenessProbe = {
                httpGet             = { path = "/health", port = 8000 }
                initialDelaySeconds = 300
                periodSeconds       = 30
              }
              volumeMounts = [
                # NCCL for TP uses shared memory; the default 64 MB /dev/shm makes
                # multi-GPU startup hang or crash — mount an in-memory emptyDir.
                { name = "dshm", mountPath = "/dev/shm" }
              ]
            }
          ]
          volumes = [
            {
              name = "dshm"
              emptyDir = {
                medium    = "Memory"
                sizeLimit = var.dev_shm_size
              }
            }
          ]
        }
      }
    }
  }

  nodepool_yaml   = "${yamlencode(local.ec2nodeclass)}---\n${yamlencode(local.nodepool)}"
  deployment_yaml = yamlencode(local.deployment)
}

# Guardrails that fail at PLAN time, not at 3 a.m. terraform_data is a
# built-in resource requiring no provider, so the preconditions are always evaluated.
# When require_gpu=false (local/CPU mode), these checks are skipped.
resource "terraform_data" "guardrails" {
  input = {
    total_gpus = local.total_gpus
    nodes      = local.nodes
  }

  lifecycle {
    precondition {
      condition     = !var.require_gpu || var.tensor_parallel_size <= var.gpus_per_node
      error_message = "tensor_parallel_size (${var.tensor_parallel_size}) must be <= gpus_per_node (${var.gpus_per_node}); a single instance cannot shard across more GPUs than it has."
    }

    precondition {
      condition     = !var.require_gpu || var.replicas * var.tensor_parallel_size <= var.max_total_gpus
      error_message = "replicas * tensor_parallel_size (${var.replicas * var.tensor_parallel_size}) exceeds max_total_gpus (${var.max_total_gpus}); raise max_total_gpus or lower replicas."
    }
  }
}
