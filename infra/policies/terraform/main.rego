# Terraform OPA policies for Kairo infrastructure
# Run with: conftest test tfplan.json -p infra/policies/terraform/
package terraform

import rego.v1

# Helper to get resources from plan
resources := input.planned_values.root_module.resources

# Deny public IPs on EC2 instances (especially GPU nodes)
deny contains msg if {
    some resource in resources
    resource.type == "aws_instance"
    resource.values.associate_public_ip_address == true
    msg := sprintf("EC2 instance '%s' has public IP enabled. GPU and inference nodes must not have public IPs.", [resource.address])
}

# Deny public IPs on EKS node groups
deny contains msg if {
    some resource in resources
    resource.type == "aws_eks_node_group"
    resource.values.remote_access
    resource.values.remote_access[_].ec2_ssh_key != ""
    msg := sprintf("EKS node group '%s' has SSH access configured. Use SSM for node access.", [resource.address])
}

# Require encryption on S3 buckets
deny contains msg if {
    some resource in resources
    resource.type == "aws_s3_bucket"
    not has_encryption(resource.address)
    msg := sprintf("S3 bucket '%s' must have server-side encryption enabled.", [resource.address])
}

has_encryption(bucket_address) if {
    some resource in resources
    resource.type == "aws_s3_bucket_server_side_encryption_configuration"
    contains(resource.address, bucket_address)
}

# Require encryption on EBS volumes
deny contains msg if {
    some resource in resources
    resource.type == "aws_ebs_volume"
    resource.values.encrypted != true
    msg := sprintf("EBS volume '%s' must be encrypted.", [resource.address])
}

# Require encryption on RDS instances
deny contains msg if {
    some resource in resources
    resource.type == "aws_rds_cluster"
    resource.values.storage_encrypted != true
    msg := sprintf("RDS cluster '%s' must have storage encryption enabled.", [resource.address])
}

# Require required tags on resources
required_tags := {"Project", "Environment", "ManagedBy"}

warn contains msg if {
    some resource in resources
    resource.type in {"aws_s3_bucket", "aws_eks_cluster", "aws_rds_cluster", "aws_opensearch_domain"}
    tags := object.get(resource.values, "tags", {})
    some tag in required_tags
    not tags[tag]
    msg := sprintf("Resource '%s' is missing required tag '%s'.", [resource.address, tag])
}

# Deny deletion protection disabled on production resources
deny contains msg if {
    some resource in resources
    resource.type == "aws_rds_cluster"
    resource.values.deletion_protection != true
    contains(resource.address, "prod")
    msg := sprintf("RDS cluster '%s' must have deletion protection enabled in production.", [resource.address])
}

deny contains msg if {
    some resource in resources
    resource.type == "aws_dynamodb_table"
    resource.values.deletion_protection_enabled != true
    contains(resource.address, "prod")
    msg := sprintf("DynamoDB table '%s' must have deletion protection enabled in production.", [resource.address])
}
