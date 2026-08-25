variable "name_prefix" {
  type        = string
  description = "Prefix applied to all resource names."
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Tags merged onto every taggable resource."
}

variable "cluster_name" {
  type        = string
  description = "EKS cluster name Karpenter provisions nodes for."
}

variable "oidc_provider_arn" {
  type        = string
  description = "ARN of the EKS cluster OIDC provider for IRSA federation."
}

variable "oidc_provider_url" {
  type        = string
  description = "OIDC issuer URL without the https:// scheme, used in IRSA condition keys."
}
