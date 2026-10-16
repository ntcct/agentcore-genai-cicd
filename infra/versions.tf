terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.69.1"
    }
    time = {
      source  = "hashicorp/time"
      version = "0.14.2"
    }
  }

  # Partial config: bucket/region passed via -backend-config in CI.
  # use_lockfile = S3-native state locking (no DynamoDB table needed).
  backend "s3" {
    key          = "infra/terraform.tfstate"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = var.project, ManagedBy = "terraform" }
  }
}
