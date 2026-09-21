output "endpoint" {
  value = aws_db_instance.this.endpoint
}

output "db_name" {
  value = aws_db_instance.this.db_name
}

output "master_user_secret_arn" {
  description = "Secrets Manager ARN holding the RDS-managed master password."
  value       = aws_db_instance.this.master_user_secret[0].secret_arn
}
