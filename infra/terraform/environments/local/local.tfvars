region       = "us-east-1"
aws_endpoint = "http://localhost:4566"

env         = "local"
name_prefix = "kairo-cloud-local"
model       = "kairo-model-4b"

model_id             = "MODEL_PROVIDER/Model-4B"
fast_model_id        = "MODEL_PROVIDER/Model-1.7B"
require_gpu          = false
tensor_parallel_size = 1
replicas             = 1
max_model_len        = 4096
gpu_instance_type    = "t3.large"
gpus_per_node        = 0
max_total_gpus       = 0

enable_guardduty          = false
enable_security_hub       = false
enable_macie              = false
enable_sagemaker_mlflow   = false
enable_hyperpod           = false
enable_fsx                = false
enable_cloudtrail         = false
enable_secrets_encryption = false
