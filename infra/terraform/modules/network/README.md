# network

VPC with a four-tier subnet layout spread across the configured Availability
Zones, NAT gateways, gateway + interface VPC endpoints, and the route tables
that enforce the data perimeter.

## Subnet tiers

| Tier | Egress | Notable tags |
|---|---|---|
| public | IGW | `kubernetes.io/role/elb=1` |
| private-app | NAT | `kubernetes.io/role/internal-elb=1`, `karpenter.sh/discovery` |
| private-gpu | **none** (opt-in NAT) | `karpenter.sh/discovery` |
| private-data | **none** | — |

## Key variables

| Variable | Default | Purpose |
|---|---|---|
| `vpc_cidr` | `10.0.0.0/16` | Base CIDR; subnet CIDRs derive from it via `cidrsubnet`. |
| `availability_zones` | 3 AZs | List of AZs; tier subnet counts follow its length. |
| `subnet_newbits` | `4` | Bits added when carving subnets. |
| `single_nat_gateway` | `false` | One shared NAT instead of one per AZ. |
| `gpu_subnets_use_nat` | `false` | Opt-in default route via NAT for GPU subnets. |
| `interface_endpoint_services` | ecr.api, ecr.dkr, logs, monitoring, sts, secretsmanager, kms | Interface endpoints to create. |

## Key outputs

`vpc_id`, `vpc_cidr`, `availability_zones`, `public_subnet_ids`,
`private_app_subnet_ids`, `private_gpu_subnet_ids`, `private_data_subnet_ids`,
`nat_gateway_ids`, `vpc_endpoints_security_group_id`, `s3_gateway_endpoint_id`,
`dynamodb_gateway_endpoint_id`.

## Design note (final_plan §19.5)

The **private-gpu** and **private-data** tiers have **no route to an internet
gateway** and, by default, no NAT route either — their route tables carry only
the local route plus the S3/DynamoDB gateway-endpoint routes. This is the
network layer of the data perimeter: even with valid credentials, workloads on
GPU/data subnets cannot reach a foreign bucket over the internet. All AWS API
traffic flows through the gateway and interface endpoints. Setting
`gpu_subnets_use_nat = true` adds a NAT default route to the GPU tier for
bootstrapping only; leave it `false` in production.
