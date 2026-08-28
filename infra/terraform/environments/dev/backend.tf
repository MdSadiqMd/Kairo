terraform {
  # Remote state per environment: versioned + encrypted S3 bucket with native
  # S3 state locking (use_lockfile, Terraform >= 1.10). State is isolated per env so
  # a dev apply can never touch prod state. The state bucket itself is the one
  # resource bootstrapped outside Terraform (qctl up Phase 0).
  backend "s3" {
    bucket       = "kairo-tfstate-dev"
    key          = "dev/terraform.tfstate"
    region       = "us-west-2"
    encrypt      = true
    use_lockfile = true
  }
}
