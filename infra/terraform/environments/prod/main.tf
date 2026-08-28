# Prod environment root. Modules resolve in dependency order via references:
# kms -> network -> s3_data_lake -> ecr -> eks -> iam -> karpenter -> gpu_nodepools
# -> inference -> dynamodb -> eventing -> observability -> opensearch -> aurora
# -> waf -> security_baseline -> sagemaker_mlflow -> sagemaker_hyperpod -> fsx_lustre.
#
# Prod hardening applied:
# - 3 AZs (us-west-2a/b/c) with one NAT gateway per AZ
# - EKS endpoint private-only (eks_endpoint_public_access = false)
# - DynamoDB deletion_protection = true
# - S3 force_destroy = false
# - log_retention_days = 365
# - ODCR-backed capacity for GPU inference

module "kms" {
  source      = "../../modules/kms"
  name_prefix = var.name_prefix
}

module "network" {
  source             = "../../modules/network"
  name_prefix        = var.name_prefix
  vpc_cidr           = var.vpc_cidr
  availability_zones = var.availability_zones
  single_nat_gateway = var.single_nat_gateway
}

module "s3_data_lake" {
  source             = "../../modules/s3_data_lake"
  name_prefix        = var.name_prefix
  s3_kms_key_arn     = module.kms.s3_key_arn
  force_destroy      = var.force_destroy_buckets
  log_retention_days = var.log_retention_days
}

module "ecr" {
  source      = "../../modules/ecr"
  name_prefix = var.name_prefix
}

module "eks" {
  source                       = "../../modules/eks"
  name_prefix                  = var.name_prefix
  cluster_name                 = var.cluster_name
  subnet_ids                   = module.network.private_app_subnet_ids
  endpoint_public_access       = var.eks_endpoint_public_access
  endpoint_public_access_cidrs = var.eks_public_access_cidrs
  enable_secrets_encryption    = var.enable_secrets_encryption
  secrets_kms_key_arn          = module.kms.ebs_key_arn
}

module "iam" {
  source            = "../../modules/iam"
  name_prefix       = var.name_prefix
  oidc_provider_arn = module.eks.oidc_provider_arn
  oidc_provider_url = module.eks.oidc_provider_url

  dynamodb_registry_table_arn         = module.dynamodb.model_registry_table_arn
  dynamodb_eval_table_arn             = module.dynamodb.eval_run_metadata_table_arn
  dynamodb_deployment_state_table_arn = module.dynamodb.deployment_state_table_arn

  kinesis_stream_arn = module.eventing.kinesis_stream_arn
  event_queue_arns   = module.eventing.all_queue_arns

  s3_kms_key_arn             = module.kms.s3_key_arn
  model_artifacts_bucket_arn = module.s3_data_lake.bucket_arns["model_artifacts"]
  raw_events_bucket_arn      = module.s3_data_lake.bucket_arns["raw_events"]
  redacted_events_bucket_arn = module.s3_data_lake.bucket_arns["redacted_events"]
  datasets_bucket_arn        = module.s3_data_lake.bucket_arns["datasets"]
  eval_bucket_arn            = module.s3_data_lake.bucket_arns["datasets"]
  eval_results_bucket_arn    = module.s3_data_lake.bucket_arns["eval_results"]
  checkpoints_bucket_arn     = module.s3_data_lake.bucket_arns["checkpoints"]
  agent_state_bucket_arn     = module.s3_data_lake.bucket_arns["redacted_events"]

  hf_token_secret_arn = var.hf_token_secret_arn

  rl_proofs_queue_arn      = module.eventing.rl_proofs_queue_arn
  proof_receipts_table_arn = module.dynamodb.proof_receipts_table_arn
  proofs_bucket_arn        = module.s3_data_lake.bucket_arns["model_artifacts"]
}

module "karpenter" {
  source            = "../../modules/karpenter"
  name_prefix       = var.name_prefix
  cluster_name      = module.eks.cluster_name
  oidc_provider_arn = module.eks.oidc_provider_arn
  oidc_provider_url = module.eks.oidc_provider_url
}

module "gpu_nodepools" {
  source                    = "../../modules/gpu_nodepools"
  name_prefix               = var.name_prefix
  cluster_name              = module.eks.cluster_name
  discovery_tag             = var.name_prefix
  karpenter_node_role_name  = module.karpenter.node_role_name
  capacity_reservation_tags = var.capacity_reservation_tags
}

module "inference" {
  source                   = "../../modules/inference"
  name_prefix              = var.name_prefix
  discovery_tag            = var.name_prefix
  karpenter_node_role_name = module.karpenter.node_role_name

  replicas             = var.replicas
  gpu_instance_type    = var.gpu_instance_type
  tensor_parallel_size = var.tensor_parallel_size
  gpus_per_node        = var.gpus_per_node
  max_total_gpus       = var.max_total_gpus
  model_id             = var.model_id
  max_model_len        = var.max_model_len

  vllm_image             = "${module.ecr.repository_urls["vllm"]}:latest"
  model_artifacts_bucket = module.s3_data_lake.model_artifacts_bucket
}

module "dynamodb" {
  source              = "../../modules/dynamodb"
  name_prefix         = var.name_prefix
  kms_key_arn         = module.kms.dynamodb_key_arn
  deletion_protection = true
}

module "eventing" {
  source      = "../../modules/eventing"
  name_prefix = var.name_prefix
  kms_key_arn = module.kms.dynamodb_key_arn
}

module "observability" {
  source                 = "../../modules/observability"
  name_prefix            = var.name_prefix
  log_retention_days     = var.log_retention_days
  cloudwatch_kms_key_arn = module.kms.cloudwatch_key_arn
}

module "opensearch" {
  source                 = "../../modules/opensearch"
  name_prefix            = var.name_prefix
  vpc_id                 = module.network.vpc_id
  subnet_ids             = module.network.private_data_subnet_ids
  vpc_cidr               = var.vpc_cidr
  kms_key_arn            = module.kms.opensearch_key_arn
  master_user_password   = var.opensearch_master_password
  zone_awareness_enabled = true
  instance_count         = 3
}

module "aurora" {
  source              = "../../modules/aurora"
  name_prefix         = var.name_prefix
  vpc_id              = module.network.vpc_id
  subnet_ids          = module.network.private_data_subnet_ids
  vpc_cidr            = var.vpc_cidr
  kms_key_arn         = module.kms.ebs_key_arn
  deletion_protection = true
  skip_final_snapshot = false
}

module "waf" {
  source      = "../../modules/waf"
  name_prefix = var.name_prefix
}

module "security_baseline" {
  source                 = "../../modules/security_baseline"
  name_prefix            = var.name_prefix
  cloudtrail_kms_key_arn = module.kms.s3_key_arn
  training_data_bucket_arns = [
    module.s3_data_lake.bucket_arns["raw_events"],
    module.s3_data_lake.bucket_arns["datasets"],
    module.s3_data_lake.bucket_arns["checkpoints"],
    module.s3_data_lake.bucket_arns["model_artifacts"],
  ]
}

module "sagemaker_mlflow" {
  source      = "../../modules/sagemaker_mlflow"
  name_prefix = var.name_prefix
  kms_key_arn = module.kms.s3_key_arn
}

module "sagemaker_hyperpod" {
  source          = "../../modules/sagemaker_hyperpod"
  name_prefix     = var.name_prefix
  enable_hyperpod = var.enable_hyperpod
  subnet_ids      = module.network.private_gpu_subnet_ids
}

resource "random_password" "api_key" {
  length  = 40
  special = false
}

resource "aws_secretsmanager_secret" "api_key" {
  name        = "kairo-${var.env}-api-key"
  description = "Router API key(s) for the ${var.env} environment"
  kms_key_id  = module.kms.ebs_key_arn
}

resource "aws_secretsmanager_secret_version" "api_key" {
  secret_id     = aws_secretsmanager_secret.api_key.id
  secret_string = jsonencode({ "sk-${var.env}-${random_password.api_key.result}" = "default" })

  lifecycle {
    ignore_changes = [secret_string]
  }
}

module "fsx_lustre" {
  source                 = "../../modules/fsx_lustre"
  name_prefix            = var.name_prefix
  enable_fsx             = var.enable_fsx
  subnet_id              = module.network.private_gpu_subnet_ids[0]
  storage_capacity_gib   = var.fsx_storage_capacity_gib
  model_artifacts_bucket = module.s3_data_lake.bucket_ids["model_artifacts"]
  kms_key_arn            = module.kms.s3_key_arn
}

module "efs" {
  source      = "../../modules/efs"
  name_prefix = var.name_prefix
  enable_efs  = var.enable_efs
  vpc_id      = module.network.vpc_id
  vpc_cidr    = var.vpc_cidr
  subnet_ids  = module.network.private_app_subnet_ids
  kms_key_arn = module.kms.ebs_key_arn
}
