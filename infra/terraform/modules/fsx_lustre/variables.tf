variable "name_prefix" {
  type        = string
  description = "Prefix for named resources."
}

variable "enable_fsx" {
  type        = bool
  description = "Provision the FSx for Lustre weight-staging filesystem. Off by default in dev — it is a priced, always-on cost."
  default     = false
}

variable "subnet_id" {
  type        = string
  description = "Private GPU subnet the filesystem is placed in (single-AZ scratch/persistent)."
  default     = ""
}

variable "security_group_ids" {
  type        = list(string)
  description = "Security groups allowing Lustre (988/1018-1023) from the GPU nodes."
  default     = []
}

variable "storage_capacity_gib" {
  type        = number
  description = "Filesystem size (GiB). PERSISTENT_2 increments of 1200."
  default     = 2400
}

variable "per_unit_throughput" {
  type        = number
  description = "PERSISTENT_2 throughput per TiB (125/250/500/1000 MB/s/TiB)."
  default     = 250
}

variable "model_artifacts_bucket" {
  type        = string
  description = "S3 bucket the filesystem hydrates weights from (data repository association)."
  default     = ""
}

variable "import_path_prefix" {
  type        = string
  description = "Prefix within the bucket to link (e.g. models/)."
  default     = "models"
}

variable "kms_key_arn" {
  type        = string
  description = "KMS key for at-rest encryption."
  default     = ""
}

variable "tags" {
  type    = map(string)
  default = {}
}
