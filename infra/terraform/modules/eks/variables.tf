variable "name_prefix" {
  type = string
}

variable "tags" {
  type    = map(string)
  default = {}
}

variable "cluster_name" {
  type = string
}

variable "cluster_version" {
  type    = string
  default = "1.31"
}

variable "subnet_ids" {
  type        = list(string)
  description = "Private-app subnet ids for the control plane ENIs and the system node group."
}

variable "endpoint_public_access" {
  type    = bool
  default = true
}

variable "endpoint_public_access_cidrs" {
  type        = list(string)
  description = "CIDRs allowed to reach the public control-plane endpoint. Ignored when endpoint_public_access is false."
  default     = []
}

variable "enable_secrets_encryption" {
  type    = bool
  default = true
}

variable "secrets_kms_key_arn" {
  type        = string
  description = "KMS key ARN used to envelope-encrypt Kubernetes secrets. Required when enable_secrets_encryption is true."
  default     = ""
}

variable "system_node_instance_types" {
  type    = list(string)
  default = ["m6i.large"]
}

variable "system_node_desired_size" {
  type    = number
  default = 2
}

variable "system_node_min_size" {
  type    = number
  default = 2
}

variable "system_node_max_size" {
  type    = number
  default = 4
}

variable "system_node_taint" {
  type        = bool
  default     = true
  description = "When true, taints the system node group with CriticalAddonsOnly=true:NoSchedule."
}

variable "addon_versions" {
  type = object({
    vpc_cni        = optional(string)
    coredns        = optional(string)
    kube_proxy     = optional(string)
    ebs_csi_driver = optional(string)
  })
  description = "Optional pinned add-on versions. Null entries resolve to the latest default version for the cluster."
  default     = {}
}
