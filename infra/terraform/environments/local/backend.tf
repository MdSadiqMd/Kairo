terraform {
  backend "s3" {
    bucket  = "kairo-tfstate-local"
    key     = "local/terraform.tfstate"
    region  = "us-east-1"
    encrypt = true

    kms_key_id = "alias/kairo-tfstate-local"

    endpoints = {
      s3  = "http://localhost:4566"
      sts = "http://localhost:4566"
      kms = "http://localhost:4566"
    }

    use_path_style              = true
    skip_credentials_validation = true
    skip_metadata_api_check     = true
    skip_requesting_account_id  = true
    skip_region_validation      = true
  }
}
