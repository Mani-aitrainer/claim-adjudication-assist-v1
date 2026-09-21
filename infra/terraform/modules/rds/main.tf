/* RDS PostgreSQL 16, private, force_ssl, master password managed by RDS in Secrets Manager. */

resource "aws_db_subnet_group" "this" {
  name       = "${var.project}-db-subnets"
  subnet_ids = var.private_subnet_ids
}

resource "aws_security_group" "rds" {
  name_prefix = "${var.project}-rds-"
  vpc_id      = var.vpc_id
  description = "Allow Postgres from the EKS node security group only."

  ingress {
    description     = "Postgres from EKS nodes"
    from_port       = 5432
    to_port         = 5432
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

resource "aws_db_parameter_group" "force_ssl" {
  name_prefix = "${var.project}-pg16-"
  family      = "postgres16"

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_db_instance" "this" {
  identifier     = "${var.project}-db"
  engine         = "postgres"
  engine_version = "16"
  instance_class = var.instance_class

  allocated_storage = 20
  storage_encrypted = true

  db_name                     = var.db_name
  username                    = var.db_username
  manage_master_user_password = true

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  parameter_group_name   = aws_db_parameter_group.force_ssl.name

  publicly_accessible = false
  skip_final_snapshot = true
  deletion_protection = false

  backup_retention_period = 1
}
