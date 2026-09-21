/*
Consumed by scripts/render_k8s_config.sh (`terraform output -json > .tf-outputs.json`) —
no endpoint is ever typed by hand into a Kubernetes manifest.
*/

output "ecr_repository_url" {
  value = module.ecr.repository_url
}

output "documents_bucket" {
  value = module.s3.bucket_name
}

output "eks_cluster_name" {
  value = module.eks.cluster_name
}

output "eks_cluster_endpoint" {
  value = module.eks.cluster_endpoint
}

output "rds_endpoint" {
  value = module.rds.endpoint
}

output "rds_master_secret_arn" {
  value = module.rds.master_user_secret_arn
}

output "redis_primary_endpoint" {
  value = module.elasticache.primary_endpoint
}

output "openai_secret_name" {
  value = module.secrets.secret_name
}

output "app_irsa_role_arn" {
  value = module.iam.app_role_arn
}

output "alb_controller_role_arn" {
  value = module.iam.alb_controller_role_arn
}

output "aws_region" {
  value = var.aws_region
}
