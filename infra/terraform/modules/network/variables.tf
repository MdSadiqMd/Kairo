variable "name_prefix" {
  type        = string
  description = "Prefix applied to resource Name tags."
}

variable "tags" {
  type        = map(string)
  description = "Additional tags merged onto every taggable resource."
  default     = {}
}

variable "vpc_cidr" {
  type        = string
  description = "CIDR block for the VPC. Subnet CIDRs are derived from this."
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  type        = list(string)
  description = "Availability Zones to spread subnet tiers across."
  default     = ["us-east-1a", "us-east-1b", "us-east-1c"]
}

variable "subnet_newbits" {
  type        = number
  description = "Additional bits added to the VPC prefix when carving subnets via cidrsubnet (e.g. 4 turns a /16 into /20s)."
  default     = 4
}

variable "single_nat_gateway" {
  type        = bool
  description = "When true, provision a single shared NAT gateway instead of one per AZ."
  default     = false
}

variable "gpu_subnets_use_nat" {
  type        = bool
  description = "When true, add a default (0.0.0.0/0) route via NAT to the private-gpu route tables for bootstrapping. Default false keeps GPU subnets egress-isolated per data-perimeter policy."
  default     = false
}

variable "interface_endpoint_services" {
  type        = list(string)
  description = "Short service names for interface VPC endpoints (com.amazonaws.<region>.<name>)."
  default = [
    "ecr.api",
    "ecr.dkr",
    "logs",
    "monitoring",
    "sts",
    "secretsmanager",
    "kms",
  ]
}
