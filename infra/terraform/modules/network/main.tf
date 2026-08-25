terraform {
  required_version = ">= 1.9"
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

data "aws_region" "current" {}

locals {
  region    = data.aws_region.current.name
  az_count  = length(var.availability_zones)
  nat_count = var.single_nat_gateway ? 1 : local.az_count

  # Each tier occupies a contiguous block of netnums so the four tiers never
  # overlap: public [0..n), app [n..2n), gpu [2n..3n), data [3n..4n).
  public_cidrs       = [for i in range(local.az_count) : cidrsubnet(var.vpc_cidr, var.subnet_newbits, i)]
  private_app_cidrs  = [for i in range(local.az_count) : cidrsubnet(var.vpc_cidr, var.subnet_newbits, local.az_count + i)]
  private_gpu_cidrs  = [for i in range(local.az_count) : cidrsubnet(var.vpc_cidr, var.subnet_newbits, (2 * local.az_count) + i)]
  private_data_cidrs = [for i in range(local.az_count) : cidrsubnet(var.vpc_cidr, var.subnet_newbits, (3 * local.az_count) + i)]
}

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true
  tags                 = merge(var.tags, { Name = var.name_prefix })
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id
  tags   = merge(var.tags, { Name = "${var.name_prefix}-igw" })
}

resource "aws_subnet" "public" {
  count                   = local.az_count
  vpc_id                  = aws_vpc.this.id
  cidr_block              = local.public_cidrs[count.index]
  availability_zone       = var.availability_zones[count.index]
  map_public_ip_on_launch = true
  tags = merge(var.tags, {
    Name                     = "${var.name_prefix}-public-${var.availability_zones[count.index]}"
    Tier                     = "public"
    "kubernetes.io/role/elb" = "1"
  })
}

resource "aws_subnet" "private_app" {
  count             = local.az_count
  vpc_id            = aws_vpc.this.id
  cidr_block        = local.private_app_cidrs[count.index]
  availability_zone = var.availability_zones[count.index]
  tags = merge(var.tags, {
    Name                              = "${var.name_prefix}-private-app-${var.availability_zones[count.index]}"
    Tier                              = "private-app"
    "kubernetes.io/role/internal-elb" = "1"
    "karpenter.sh/discovery"          = var.name_prefix
  })
}

resource "aws_subnet" "private_gpu" {
  count             = local.az_count
  vpc_id            = aws_vpc.this.id
  cidr_block        = local.private_gpu_cidrs[count.index]
  availability_zone = var.availability_zones[count.index]
  tags = merge(var.tags, {
    Name                     = "${var.name_prefix}-private-gpu-${var.availability_zones[count.index]}"
    Tier                     = "private-gpu"
    "karpenter.sh/discovery" = var.name_prefix
  })
}

resource "aws_subnet" "private_data" {
  count             = local.az_count
  vpc_id            = aws_vpc.this.id
  cidr_block        = local.private_data_cidrs[count.index]
  availability_zone = var.availability_zones[count.index]
  tags = merge(var.tags, {
    Name = "${var.name_prefix}-private-data-${var.availability_zones[count.index]}"
    Tier = "private-data"
  })
}

resource "aws_eip" "nat" {
  count      = local.nat_count
  domain     = "vpc"
  tags       = merge(var.tags, { Name = "${var.name_prefix}-nat-${count.index}" })
  depends_on = [aws_internet_gateway.this]
}

resource "aws_nat_gateway" "this" {
  count         = local.nat_count
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id
  tags          = merge(var.tags, { Name = "${var.name_prefix}-nat-${count.index}" })
  depends_on    = [aws_internet_gateway.this]
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id
  tags   = merge(var.tags, { Name = "${var.name_prefix}-public" })
}

resource "aws_route" "public_internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.this.id
}

resource "aws_route_table_association" "public" {
  count          = local.az_count
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "private_app" {
  count  = local.az_count
  vpc_id = aws_vpc.this.id
  tags   = merge(var.tags, { Name = "${var.name_prefix}-private-app-${var.availability_zones[count.index]}" })
}

resource "aws_route" "private_app_nat" {
  count                  = local.az_count
  route_table_id         = aws_route_table.private_app[count.index].id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.this[var.single_nat_gateway ? 0 : count.index].id
}

resource "aws_route_table_association" "private_app" {
  count          = local.az_count
  subnet_id      = aws_subnet.private_app[count.index].id
  route_table_id = aws_route_table.private_app[count.index].id
}

# GPU subnets are egress-isolated by default: their route
# tables carry only the implicit local route plus gateway-endpoint routes. A
# default route via NAT is added ONLY when gpu_subnets_use_nat is true.
resource "aws_route_table" "private_gpu" {
  count  = local.az_count
  vpc_id = aws_vpc.this.id
  tags   = merge(var.tags, { Name = "${var.name_prefix}-private-gpu-${var.availability_zones[count.index]}" })
}

resource "aws_route" "private_gpu_nat" {
  count                  = var.gpu_subnets_use_nat ? local.az_count : 0
  route_table_id         = aws_route_table.private_gpu[count.index].id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.this[var.single_nat_gateway ? 0 : count.index].id
}

resource "aws_route_table_association" "private_gpu" {
  count          = local.az_count
  subnet_id      = aws_subnet.private_gpu[count.index].id
  route_table_id = aws_route_table.private_gpu[count.index].id
}

# Data subnets have NO internet egress path at all: no NAT
# route, no IGW route — only local + gateway-endpoint routes.
resource "aws_route_table" "private_data" {
  count  = local.az_count
  vpc_id = aws_vpc.this.id
  tags   = merge(var.tags, { Name = "${var.name_prefix}-private-data-${var.availability_zones[count.index]}" })
}

resource "aws_route_table_association" "private_data" {
  count          = local.az_count
  subnet_id      = aws_subnet.private_data[count.index].id
  route_table_id = aws_route_table.private_data[count.index].id
}

locals {
  private_route_table_ids = concat(
    aws_route_table.private_app[*].id,
    aws_route_table.private_gpu[*].id,
    aws_route_table.private_data[*].id,
  )
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${local.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = local.private_route_table_ids
  tags              = merge(var.tags, { Name = "${var.name_prefix}-s3-gw" })
}

resource "aws_vpc_endpoint" "dynamodb" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${local.region}.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = local.private_route_table_ids
  tags              = merge(var.tags, { Name = "${var.name_prefix}-dynamodb-gw" })
}

resource "aws_security_group" "endpoints" {
  name_prefix = "${var.name_prefix}-vpce-"
  description = "Allow HTTPS from the VPC to interface VPC endpoints."
  vpc_id      = aws_vpc.this.id
  tags        = merge(var.tags, { Name = "${var.name_prefix}-vpce" })

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_ingress_rule" "endpoints_https" {
  security_group_id = aws_security_group.endpoints.id
  description       = "HTTPS from within the VPC"
  cidr_ipv4         = var.vpc_cidr
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "endpoints_all" {
  security_group_id = aws_security_group.endpoints.id
  description       = "Allow all egress"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

resource "aws_vpc_endpoint" "interface" {
  for_each = toset(var.interface_endpoint_services)

  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${local.region}.${each.value}"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = aws_subnet.private_app[*].id
  security_group_ids  = [aws_security_group.endpoints.id]
  tags                = merge(var.tags, { Name = "${var.name_prefix}-${replace(each.value, ".", "-")}" })
}
