variable "name_prefix" {
  type        = string
  description = "Prefix applied to repository names and resource Name tags."
}

variable "tags" {
  type        = map(string)
  description = "Additional tags merged onto every taggable resource."
  default     = {}
}

variable "image_tag_mutability" {
  type        = string
  description = "Tag mutability for every repository."
  default     = "IMMUTABLE"

  validation {
    condition     = contains(["IMMUTABLE", "MUTABLE"], var.image_tag_mutability)
    error_message = "image_tag_mutability must be IMMUTABLE or MUTABLE."
  }
}

variable "encryption_type" {
  type        = string
  description = "Repository encryption type: AES256 or KMS."
  default     = "AES256"

  validation {
    condition     = contains(["AES256", "KMS"], var.encryption_type)
    error_message = "encryption_type must be AES256 or KMS."
  }
}

variable "kms_key_arn" {
  type        = string
  description = "CMK ARN used when encryption_type is KMS. Ignored otherwise."
  default     = null
}

variable "keep_last_images" {
  type        = number
  description = "Number of most-recent tagged images to retain per repository."
  default     = 20
}

variable "untagged_expire_days" {
  type        = number
  description = "Days after which untagged images are expired."
  default     = 14
}

variable "enable_pull_through_cache" {
  type        = bool
  description = "Create a pull-through cache rule for an upstream public registry."
  default     = true
}

variable "upstream_registry_url" {
  type        = string
  description = "Upstream registry URL for the pull-through cache rule."
  default     = "public.ecr.aws"
}

variable "ecr_repository_prefix" {
  type        = string
  description = "Namespace prefix under which cached upstream images are mirrored."
  default     = "ecr-public"
}
