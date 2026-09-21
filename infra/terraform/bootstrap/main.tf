/*
Bootstrap the Terraform remote state backend — S3 bucket + DynamoDB lock table.
Run once, manually, before `terraform init` in the root module. Uses its own local
state (deliberately not remote — there is nothing to bootstrap the bootstrap with).
*/

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

variable "aws_region" {
  description = "AWS region for the state backend."
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Project slug, used to name the state bucket and lock table."
  type        = string
  default     = "claim-adjudication"
}

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "tfstate" {
  # Region is part of the name on purpose: S3 bucket names are a single global
  # namespace, and reusing a name across regions blocks on delete propagation.
  bucket = "${var.project}-tfstate-${data.aws_caller_identity.current.account_id}-${var.aws_region}"

  tags = {
    Project     = "claim-adjudication"
    Environment = "learning"
    Owner       = "mani"
    ManagedBy   = "terraform"
  }
}

resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket                  = aws_s3_bucket.tfstate.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_dynamodb_table" "tf_lock" {
  name         = "${var.project}-tfstate-lock"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  tags = {
    Project     = "claim-adjudication"
    Environment = "learning"
    Owner       = "mani"
    ManagedBy   = "terraform"
  }
}

output "state_bucket" {
  value = aws_s3_bucket.tfstate.bucket
}

output "lock_table" {
  value = aws_dynamodb_table.tf_lock.name
}
