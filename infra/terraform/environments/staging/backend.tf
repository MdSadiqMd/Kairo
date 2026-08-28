terraform {
  # Isolated per-environment remote state. Never shares state with dev or prod.
  backend "s3" {
    bucket       = "kairo-tfstate-staging"
    key          = "staging/terraform.tfstate"
    region       = "us-west-2"
    encrypt      = true
    use_lockfile = true
  }
}
