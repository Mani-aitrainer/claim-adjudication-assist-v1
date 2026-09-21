variable "aws_region" {
  description = "AWS region. us-east-1 (N. Virginia) — chosen over ap-south-1 (Mumbai) because it has full Textract AnalyzeDocument FORMS/TABLES coverage. Changing this also means changing availability_zones below and the region in backend.tf."
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Project slug, used as a prefix for every resource name."
  type        = string
  default     = "claim-adjudication"
}

variable "environment" {
  description = "Environment tag. This is a learning project, not a production deployment."
  type        = string
  default     = "learning"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.42.0.0/16"
}

variable "availability_zones" {
  description = "Two AZs — enough for the plan's 2 public + 2 private subnet layout."
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]
}

variable "db_instance_class" {
  description = "RDS Postgres instance class."
  type        = string
  default     = "db.t4g.micro"
}

variable "db_name" {
  type    = string
  default = "claims"
}

variable "db_username" {
  type    = string
  default = "claims"
}

variable "redis_node_type" {
  description = "ElastiCache Redis node type."
  type        = string
  default     = "cache.t4g.micro"
}

variable "eks_cluster_version" {
  type    = string
  default = "1.30"
}

variable "eks_node_instance_type" {
  type    = string
  default = "t3.medium"
}

variable "eks_node_desired_size" {
  type    = number
  default = 2
}

variable "openai_secret_name" {
  description = "Secrets Manager secret name for the OpenAI API key. Value is injected out-of-band (Runbook step 5) — never in .tf."
  type        = string
  default     = "claim-adjudication/openai-api-key"
}

variable "budget_limit_usd" {
  description = "Monthly AWS Budget alert threshold in USD."
  type        = number
  default     = 50
}

variable "budget_alert_email" {
  description = "Email address to notify when the budget threshold is crossed."
  type        = string
}
