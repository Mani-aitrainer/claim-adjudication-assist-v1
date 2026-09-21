data "aws_caller_identity" "current" {}

module "network" {
  source             = "./modules/network"
  project            = var.project
  vpc_cidr           = var.vpc_cidr
  availability_zones = var.availability_zones
}

module "ecr" {
  source  = "./modules/ecr"
  project = var.project
}

module "s3" {
  source     = "./modules/s3"
  project    = var.project
  account_id = data.aws_caller_identity.current.account_id
}

module "eks" {
  source             = "./modules/eks"
  project            = var.project
  vpc_id             = module.network.vpc_id
  public_subnet_ids  = module.network.public_subnet_ids
  private_subnet_ids = module.network.private_subnet_ids
  cluster_version    = var.eks_cluster_version
  node_instance_type = var.eks_node_instance_type
  node_desired_size  = var.eks_node_desired_size
}

module "rds" {
  source                     = "./modules/rds"
  project                    = var.project
  vpc_id                     = module.network.vpc_id
  private_subnet_ids         = module.network.private_subnet_ids
  eks_node_security_group_id = module.eks.node_security_group_id
  instance_class             = var.db_instance_class
  db_name                    = var.db_name
  db_username                = var.db_username
}

module "elasticache" {
  source                     = "./modules/elasticache"
  project                    = var.project
  vpc_id                     = module.network.vpc_id
  private_subnet_ids         = module.network.private_subnet_ids
  eks_node_security_group_id = module.eks.node_security_group_id
  node_type                  = var.redis_node_type
}

module "secrets" {
  source      = "./modules/secrets"
  secret_name = var.openai_secret_name
}

module "iam" {
  source                = "./modules/iam"
  project               = var.project
  oidc_provider_arn     = module.eks.oidc_provider_arn
  oidc_issuer_url       = module.eks.oidc_issuer_url
  openai_secret_arn     = module.secrets.secret_arn
  rds_master_secret_arn = module.rds.master_user_secret_arn
  documents_bucket_arn  = module.s3.bucket_arn
}

module "budget" {
  source      = "./modules/budget"
  project     = var.project
  limit_usd   = var.budget_limit_usd
  alert_email = var.budget_alert_email
}
