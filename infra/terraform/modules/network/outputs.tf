output "vpc_id" {
  description = "ID of the VPC."
  value       = aws_vpc.this.id
}

output "vpc_cidr" {
  description = "CIDR block of the VPC."
  value       = aws_vpc.this.cidr_block
}

output "availability_zones" {
  description = "Availability Zones the subnets span."
  value       = var.availability_zones
}

output "public_subnet_ids" {
  description = "IDs of the public subnets."
  value       = aws_subnet.public[*].id
}

output "private_app_subnet_ids" {
  description = "IDs of the private-app subnets."
  value       = aws_subnet.private_app[*].id
}

output "private_gpu_subnet_ids" {
  description = "IDs of the private-gpu subnets (no internet gateway route)."
  value       = aws_subnet.private_gpu[*].id
}

output "private_data_subnet_ids" {
  description = "IDs of the private-data subnets (no internet egress)."
  value       = aws_subnet.private_data[*].id
}

output "nat_gateway_ids" {
  description = "IDs of the NAT gateways."
  value       = aws_nat_gateway.this[*].id
}

output "vpc_endpoints_security_group_id" {
  description = "Security group ID guarding the interface VPC endpoints."
  value       = aws_security_group.endpoints.id
}

output "s3_gateway_endpoint_id" {
  description = "ID of the S3 gateway VPC endpoint."
  value       = aws_vpc_endpoint.s3.id
}

output "dynamodb_gateway_endpoint_id" {
  description = "ID of the DynamoDB gateway VPC endpoint."
  value       = aws_vpc_endpoint.dynamodb.id
}
