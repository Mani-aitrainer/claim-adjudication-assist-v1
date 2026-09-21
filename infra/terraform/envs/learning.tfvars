# Learning-profile variable values. Everything else uses the defaults in variables.tf.
#
# Fill in budget_alert_email before `terraform apply` — AWS Budgets requires a
# subscriber address and has no sane default.

aws_region  = "us-east-1"
environment = "learning"

budget_limit_usd   = 50
budget_alert_email = "CHANGE-ME@example.com"
