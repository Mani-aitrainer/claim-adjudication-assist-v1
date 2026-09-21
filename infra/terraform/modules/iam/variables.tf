variable "project" {
  type = string
}

variable "oidc_provider_arn" {
  type = string
}

variable "oidc_issuer_url" {
  type = string
}

variable "namespace" {
  type    = string
  default = "claim-adjudication"
}

variable "app_service_account" {
  type    = string
  default = "claim-adjudication"
}

variable "openai_secret_arn" {
  type = string
}

variable "rds_master_secret_arn" {
  type = string
}

variable "documents_bucket_arn" {
  type = string
}
