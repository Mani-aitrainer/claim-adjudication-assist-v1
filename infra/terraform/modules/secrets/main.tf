/*
Secret SHELL only — Terraform creates the named secret, but never sets its value.
The OpenAI API key is injected out-of-band (Runbook — Deploying To AWS, Step 5):

  aws secretsmanager put-secret-value --secret-id ... --secret-string '{"OPENAI_API_KEY":"..."}'

so the key never appears in .tf, state diffs, or plan output.
*/

resource "aws_secretsmanager_secret" "openai_api_key" {
  name        = var.secret_name
  description = "OpenAI API key for the claim adjudication app. Value set out-of-band via aws secretsmanager put-secret-value — never via Terraform."

  # 0 = delete immediately on destroy, with no recovery window.
  #
  # This matters more than it looks. The AWS default is a 7-30 day recovery window, during
  # which the NAME stays reserved — so a destroy/recreate cycle fails on the next apply
  # with "You can't create this secret because a secret with this name is already
  # scheduled for deletion." For a teaching stack that gets torn down and rebuilt
  # repeatedly, that's a dead end. A real deployment would keep the recovery window.
  recovery_window_in_days = 0

  lifecycle {
    # protect the value already injected out-of-band from being clobbered by a re-apply
    ignore_changes = [description]
  }
}
