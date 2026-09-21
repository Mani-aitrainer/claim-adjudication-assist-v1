/* ElastiCache Redis 7, single node, private subnet group, encryption in transit. */

resource "aws_elasticache_subnet_group" "this" {
  name       = "${var.project}-redis-subnets"
  subnet_ids = var.private_subnet_ids
}

resource "aws_security_group" "redis" {
  name_prefix = "${var.project}-redis-"
  vpc_id      = var.vpc_id
  description = "Allow Redis from the EKS node security group only."

  ingress {
    description     = "Redis from EKS nodes"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [var.eks_node_security_group_id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  lifecycle {
    create_before_destroy = true
  }
}

/*
Encryption in transit is only available through a replication group, not the plain
aws_elasticache_cluster resource — so this uses a single-node replication group
(num_cache_clusters = 1) to get transit encryption on a "single node" deployment.
*/
resource "aws_elasticache_replication_group" "this" {
  replication_group_id = "${var.project}-redis"
  description          = "Single-node Redis cache for the claim adjudication cache layer."
  engine               = "redis"
  engine_version       = "7.1"
  node_type            = var.node_type
  num_cache_clusters   = 1
  port                 = 6379
  subnet_group_name    = aws_elasticache_subnet_group.this.name
  security_group_ids   = [aws_security_group.redis.id]

  transit_encryption_enabled = true
  at_rest_encryption_enabled = true
}
