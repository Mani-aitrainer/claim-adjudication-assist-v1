output "app_role_arn" {
  value = aws_iam_role.app.arn
}

output "alb_controller_role_arn" {
  value = aws_iam_role.alb_controller.arn
}
