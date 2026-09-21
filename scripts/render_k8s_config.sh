#!/usr/bin/env bash
# Generates k8s/configmap.yaml and k8s/serviceaccount.yaml from .tf-outputs.json +
# the live config/*.yaml files. Never hand-edit either generated file — re-run this
# script after any `terraform apply` or config change instead.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUTS_FILE="${REPO_ROOT}/.tf-outputs.json"
NAMESPACE="claim-adjudication"

if [ ! -f "$OUTPUTS_FILE" ]; then
  echo "error: $OUTPUTS_FILE not found — run 'terraform output -json > .tf-outputs.json' first" >&2
  exit 1
fi

jq_out() { jq -r ".$1.value" "$OUTPUTS_FILE"; }

RDS_ENDPOINT="$(jq_out rds_endpoint)"
DOCUMENTS_BUCKET="$(jq_out documents_bucket)"
OPENAI_SECRET_NAME="$(jq_out openai_secret_name)"
AWS_REGION="$(jq_out aws_region)"
APP_IRSA_ROLE_ARN="$(jq_out app_irsa_role_arn)"
ALB_CONTROLLER_ROLE_ARN="$(jq_out alb_controller_role_arn)"

# --- *.rendered.yaml — substitute the IRSA role ARN placeholders --------------------
# Written to separate, gitignored files so the tracked templates keep their placeholder
# ARNs rather than being overwritten with one account's real ARNs on every render.
sed "s#__APP_IRSA_ROLE_ARN__#${APP_IRSA_ROLE_ARN}#" \
  "${REPO_ROOT}/k8s/serviceaccount.yaml" > "${REPO_ROOT}/k8s/serviceaccount.rendered.yaml"

# The ALB controller's ServiceAccount must exist before `helm install ... --set
# serviceAccount.create=false` runs, or the controller has no IAM identity.
sed "s#__ALB_CONTROLLER_ROLE_ARN__#${ALB_CONTROLLER_ROLE_ARN}#" \
  "${REPO_ROOT}/k8s/alb-controller-serviceaccount.yaml" \
  > "${REPO_ROOT}/k8s/alb-controller-serviceaccount.rendered.yaml"

# --- configmap.yaml — agents.yaml + tradeoff.yaml as files, plus non-secret env -----
kubectl create configmap claim-adjudication-config \
  --namespace "$NAMESPACE" \
  --from-file=agents.yaml="${REPO_ROOT}/config/agents.yaml" \
  --from-file=tradeoff.yaml="${REPO_ROOT}/config/tradeoff.yaml" \
  --from-literal=APP_ENV=aws \
  --from-literal=USE_REDIS=true \
  --from-literal=USE_TEXTRACT=true \
  --from-literal=USE_S3=true \
  --from-literal=USE_SECRETS_MANAGER=true \
  --from-literal=VECTOR_BACKEND=pgvector \
  --from-literal=POSTGRES_DSN="postgresql://claims@${RDS_ENDPOINT}/claims" \
  --from-literal=AWS_REGION="$AWS_REGION" \
  --from-literal=SECRET_NAME_OPENAI="$OPENAI_SECRET_NAME" \
  --from-literal=DOCUMENTS_DIR="s3://${DOCUMENTS_BUCKET}" \
  --from-literal=DOCUMENTS_BUCKET="$DOCUMENTS_BUCKET" \
  --dry-run=client -o yaml \
  > "${REPO_ROOT}/k8s/configmap.yaml"

echo "wrote k8s/configmap.yaml, k8s/serviceaccount.rendered.yaml and"
echo "      k8s/alb-controller-serviceaccount.rendered.yaml from ${OUTPUTS_FILE}"
