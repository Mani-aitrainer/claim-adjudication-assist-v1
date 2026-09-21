/*
Remote state — bucket and lock table come from `infra/terraform/bootstrap` (run once,
separately, before this). Values are filled in at `terraform init` time:

  terraform init -backend-config="bucket=${PROJECT}-tfstate-${ACCOUNT_ID}-${AWS_REGION}"

so this repo never hard-codes an account ID.
*/

terraform {
  backend "s3" {
    key            = "claim-adjudication/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "claim-adjudication-tfstate-lock"
    encrypt        = true
  }
}
