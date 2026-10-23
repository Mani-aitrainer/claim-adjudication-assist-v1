#!/usr/bin/env bash
# Ordered teardown — `terraform destroy` alone hangs or orphans resources without these
# steps first. See Runbook — Deploying To AWS, Step 15. Requires kubectl pointed at the
# cluster and AWS credentials with the same permissions used to deploy.
#
# By default the Terraform state backend (S3 state bucket + DynamoDB lock table from
# infra/terraform/bootstrap) is kept, so the next deploy can skip bootstrap. To remove it
# too, for a fully clean account:
#
#   DESTROY_STATE_BACKEND=true ./scripts/destroy_all.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="${PROJECT:-claim-adjudication}"
AWS_REGION="${AWS_REGION:-us-east-1}"
NAMESPACE="claim-adjudication"
DESTROY_STATE_BACKEND="${DESTROY_STATE_BACKEND:-false}"

# Deletes every object version and delete marker, 200 at a time, so the bucket itself can
# be deleted. The JSON goes inline, not via file:///tmp/..., because aws.exe on Windows
# can't open a Git Bash /tmp path.
empty_versioned_bucket() {
  local bucket="$1" payload
  aws s3 rm "s3://${bucket}" --recursive >/dev/null 2>&1 || true
  for _ in $(seq 1 500); do
    payload="$(aws s3api list-object-versions --bucket "$bucket" --max-items 200 --output json 2>/dev/null \
      | python3 -c "
import json, sys
raw = sys.stdin.read().strip()
data = json.loads(raw) if raw else {}
objs = [{'Key': v['Key'], 'VersionId': v['VersionId']}
        for v in (data.get('Versions') or []) + (data.get('DeleteMarkers') or [])]
print(json.dumps({'Objects': objs, 'Quiet': True}) if objs else '')
")"
    [ -z "$payload" ] && return 0
    aws s3api delete-objects --bucket "$bucket" --delete "$payload" >/dev/null || return 0
  done
}

# The Kubernetes steps are skipped when there's no reachable cluster — which is the
# normal case for a PARTIAL apply (EKS never finished, or the app was never deployed).
# Without this guard `set -e` would kill the script here and `terraform destroy` would
# never run, which is the opposite of what you want when tearing down a half-built stack.
if kubectl cluster-info >/dev/null 2>&1; then
  CLUSTER_REACHABLE=true
else
  CLUSTER_REACHABLE=false
  echo "note: no reachable Kubernetes cluster — skipping steps 1 and 2 (nothing to drain)"
fi

echo "== 1/9: deleting the Ingress (releases the ALB, which Terraform does not own) =="
if [ "$CLUSTER_REACHABLE" = true ]; then
  kubectl delete ingress claim-adjudication -n "$NAMESPACE" --ignore-not-found --wait=true --timeout=180s
else
  echo "  skipped (no cluster)"
fi

echo "== 2/9: deleting any LoadBalancer-type Services =="
if [ "$CLUSTER_REACHABLE" = true ]; then
  kubectl get svc -n "$NAMESPACE" -o json 2>/dev/null \
    | python3 -c "import json,sys; svcs=json.load(sys.stdin)['items']; print('\n'.join(s['metadata']['name'] for s in svcs if s['spec'].get('type')=='LoadBalancer'))" \
    | xargs -r -n1 kubectl delete svc -n "$NAMESPACE" --wait=true --timeout=180s
else
  echo "  skipped (no cluster)"
fi

echo "== 3/9: emptying the S3 documents bucket (including versions and delete markers) =="
BUCKET="$(jq -r '.documents_bucket.value' "${REPO_ROOT}/.tf-outputs.json" 2>/dev/null || true)"
if [ -n "$BUCKET" ] && [ "$BUCKET" != "null" ]; then
  empty_versioned_bucket "$BUCKET"
else
  echo "no documents_bucket in .tf-outputs.json — skipping"
fi

echo "== 4/9: deleting all ECR images =="
ECR_REPO="$(jq -r '.ecr_repository_url.value | split("/") | .[-1]' "${REPO_ROOT}/.tf-outputs.json" 2>/dev/null || true)"
if [ -n "$ECR_REPO" ] && [ "$ECR_REPO" != "null" ]; then
  IMAGE_IDS="$(aws ecr list-images --repository-name "$ECR_REPO" --region "$AWS_REGION" --query 'imageIds' --output json 2>/dev/null || echo '[]')"
  if [ "$IMAGE_IDS" != "[]" ]; then
    aws ecr batch-delete-image --repository-name "$ECR_REPO" --region "$AWS_REGION" --image-ids "$IMAGE_IDS" || true
  fi
else
  echo "no ecr repository in .tf-outputs.json — skipping"
fi

echo "== 5/9: force-deleting Secrets Manager secrets (no recovery window) =="
for secret in "${PROJECT}/openai-api-key"; do
  aws secretsmanager delete-secret --secret-id "$secret" --force-delete-without-recovery \
    --region "$AWS_REGION" 2>/dev/null || true
done

echo "== 6/9: terraform destroy =="
cd "${REPO_ROOT}/infra/terraform"
# init is idempotent and required if .terraform/ was cleaned or this is a fresh clone —
# without it destroy fails with "Backend initialization required".
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
terraform init -reconfigure -backend-config="bucket=${PROJECT}-tfstate-${ACCOUNT_ID}-${AWS_REGION}"
terraform destroy -auto-approve -var-file=envs/learning.tfvars

echo "== 7/9: deleting leftover CloudWatch log groups =="
for prefix in "/aws/eks/${PROJECT}" "/aws/rds/${PROJECT}"; do
  aws logs describe-log-groups --log-group-name-prefix "$prefix" --region "$AWS_REGION" \
    --query 'logGroups[].logGroupName' --output text 2>/dev/null \
    | tr '\t' '\n' | xargs -r -n1 -I{} aws logs delete-log-group --log-group-name {} --region "$AWS_REGION"
done

STATE_BUCKET="${PROJECT}-tfstate-${ACCOUNT_ID}-${AWS_REGION}"
LOCK_TABLE="${PROJECT}-tfstate-lock"

echo "== 8/9: Terraform state backend (bucket ${STATE_BUCKET}, table ${LOCK_TABLE}) =="
if [ "$DESTROY_STATE_BACKEND" = true ]; then
  empty_versioned_bucket "$STATE_BUCKET"
  aws s3api delete-bucket --bucket "$STATE_BUCKET" --region "$AWS_REGION" 2>/dev/null || true
  aws dynamodb delete-table --table-name "$LOCK_TABLE" --region "$AWS_REGION" >/dev/null 2>&1 || true
  aws dynamodb wait table-not-exists --table-name "$LOCK_TABLE" --region "$AWS_REGION" || true
  # bootstrap's local state now describes resources that are gone; the next deploy
  # re-runs bootstrap (Step 3) from scratch
  rm -f "${REPO_ROOT}/infra/terraform/bootstrap/terraform.tfstate" \
        "${REPO_ROOT}/infra/terraform/bootstrap/terraform.tfstate.backup"
  echo "  deleted. The next deploy must start at Step 3 (bootstrap)."
else
  echo "  kept, so the next deploy can skip bootstrap. To delete it: DESTROY_STATE_BACKEND=true"
fi

echo "== 9/9: verifying nothing tagged Project=${PROJECT} remains =="
ARNS="$(aws resourcegroupstaggingapi get-resources \
  --tag-filters "Key=Project,Values=${PROJECT}" \
  --region "$AWS_REGION" --query 'ResourceTagMappingList[].ResourceARN' --output text | tr '\t' '\n')"
REMAINING=""
for arn in $ARNS; do
  case "$arn" in
    None) continue ;;
    *":natgateway/"*)
      # a deleted NAT gateway stays in this listing for about an hour
      state="$(aws ec2 describe-nat-gateways --nat-gateway-ids "${arn##*/}" --region "$AWS_REGION" \
        --query 'NatGateways[0].State' --output text 2>/dev/null || echo unknown)"
      [ "$state" = deleted ] && continue ;;
    *":::${STATE_BUCKET}" | *":table/${LOCK_TABLE}")
      # the state backend is expected to remain unless it was asked to be deleted
      [ "$DESTROY_STATE_BACKEND" != true ] && continue ;;
  esac
  REMAINING="${REMAINING}${arn}"$'\n'
done
if [ -n "$REMAINING" ]; then
  echo "WARNING: tagged resources still remain:" >&2
  printf '%s' "$REMAINING" >&2
  exit 1
fi

echo "teardown complete — zero tagged resources remain"
