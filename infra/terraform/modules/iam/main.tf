/*
IRSA roles: one for the app pod (Secrets Manager read + Textract + S3 read/write) and
one for the AWS Load Balancer Controller. Both trust the EKS OIDC provider, scoped to a
specific Kubernetes ServiceAccount via the sub claim.
*/

data "aws_iam_policy_document" "app_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${replace(var.oidc_issuer_url, "https://", "")}:sub"
      values   = ["system:serviceaccount:${var.namespace}:${var.app_service_account}"]
    }

    condition {
      test     = "StringEquals"
      variable = "${replace(var.oidc_issuer_url, "https://", "")}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "app" {
  name               = "${var.project}-app-irsa"
  assume_role_policy = data.aws_iam_policy_document.app_assume.json
}

data "aws_iam_policy_document" "app_permissions" {
  statement {
    sid       = "SecretsManagerRead"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.openai_secret_arn, var.rds_master_secret_arn]
  }

  statement {
    sid       = "TextractAnalyze"
    effect    = "Allow"
    actions   = ["textract:AnalyzeDocument", "textract:DetectDocumentText"]
    resources = ["*"]
  }

  statement {
    sid       = "S3DocumentsReadWrite"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
    resources = [var.documents_bucket_arn, "${var.documents_bucket_arn}/*"]
  }
}

resource "aws_iam_role_policy" "app" {
  name   = "${var.project}-app-permissions"
  role   = aws_iam_role.app.id
  policy = data.aws_iam_policy_document.app_permissions.json
}

# ---- AWS Load Balancer Controller ------------------------------------------

data "aws_iam_policy_document" "alb_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${replace(var.oidc_issuer_url, "https://", "")}:sub"
      values   = ["system:serviceaccount:kube-system:aws-load-balancer-controller"]
    }

    condition {
      test     = "StringEquals"
      variable = "${replace(var.oidc_issuer_url, "https://", "")}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "alb_controller" {
  name               = "${var.project}-alb-controller"
  assume_role_policy = data.aws_iam_policy_document.alb_assume.json
}

# The AWS Load Balancer Controller policy is the long, upstream-published document —
# fetched at apply time rather than hand-copied, so it never drifts from the version
# the Helm chart expects.
data "http" "alb_controller_policy" {
  url = "https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/v2.9.0/docs/install/iam_policy.json"
}

resource "aws_iam_policy" "alb_controller" {
  name   = "${var.project}-alb-controller-policy"
  policy = data.http.alb_controller_policy.response_body
}

resource "aws_iam_role_policy_attachment" "alb_controller" {
  role       = aws_iam_role.alb_controller.name
  policy_arn = aws_iam_policy.alb_controller.arn
}
