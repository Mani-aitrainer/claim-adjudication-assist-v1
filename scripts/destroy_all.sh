#!/usr/bin/env bash
# Ordered teardown — `terraform destroy` alone hangs or orphans resources without these
# steps first. See Runbook — Deploying To AWS, Step 15. Requires kubectl pointed at the
# cluster and AWS credentials with the same permissions used to deploy.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="${PROJECT:-claim-adjudication}"
AWS_REGION="${AWS_REGION:-us-east-1}"
NAMESPACE="claim-adjudication"

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

echo "== 1/8: deleting the Ingress (releases the ALB, which Terraform does not own) =="
if [ "$CLUSTER_REACHABLE" = true ]; then
  kubectl delete ingress claim-adjudication -n "$NAMESPACE" --ignore-not-found --wait=true --timeout=180s
else
  echo "  skipped (no cluster)"
fi

echo "== 2/8: deleting any LoadBalancer-type Services =="
if [ "$CLUSTER_REACHABLE" = true ]; then
  kubectl get svc -n "$NAMESPACE" -o json 2>/dev/null \
    | python3 -c "import json,sys; svcs=json.load(sys.stdin)['items']; print('\n'.join(s['metadata']['name'] for s in svcs if s['spec'].get('type')=='LoadBalancer'))" \
    | xargs -r -n1 kubectl delete svc -n "$NAMESPACE" --wait=true --timeout=180s
else
  echo "  skipped (no cluster)"
fi

echo "== 3/8: emptying the S3 documents bucket (including versions and delete markers) =="
BUCKET="$(jq -r '.documents_bucket.value' "${REPO_ROOT}/.tf-outputs.json" 2>/dev/null || true)"
if [ -n "$BUCKET" ] && [ "$BUCKET" != "null" ]; then
  aws s3 rm "s3://${BUCKET}" --recursive || true
  aws s3api list-object-versions --bucket "$BUCKET" --output json 2>/dev/null \
    | python3 -c "
import json, sys
data = json.load(sys.stdin)
keys = [{'Key': v['Key'], 'VersionId': v['VersionId']} for v in data.get('Versions', [])]
keys += [{'Key': v['Key'], 'VersionId': v['VersionId']} for v in data.get('DeleteMarkers', [])]
print(json.dumps({'Objects': keys}))
" > /tmp/delete-payload.json 2>/dev/null || echo '{"Objects":[]}' > /tmp/delete-payload.json
  if [ -s /tmp/delete-payload.json ] && [ "$(python3 -c "import json;print(len(json.load(open('/tmp/delete-payload.json'))['Objects']))")" != "0" ]; then
    aws s3api delete-objects --bucket "$BUCKET" --delete file:///tmp/delete-payload.json || true
  fi
else
  echo "no documents_bucket in .tf-outputs.json — skipping"
fi

echo "== 4/8: deleting all ECR images =="
ECR_REPO="$(jq -r '.ecr_repository_url.value | split("/") | .[-1]' "${REPO_ROOT}/.tf-outputs.json" 2>/dev/null || true)"
if [ -n "$ECR_REPO" ] && [ "$ECR_REPO" != "null" ]; then
  IMAGE_IDS="$(aws ecr list-images --repository-name "$ECR_REPO" --region "$AWS_REGION" --query 'imageIds' --output json 2>/dev/null || echo '[]')"
  if [ "$IMAGE_IDS" != "[]" ]; then
    aws ecr batch-delete-image --repository-name "$ECR_REPO" --region "$AWS_REGION" --image-ids "$IMAGE_IDS" || true
  fi
else
  echo "no ecr repository in .tf-outputs.json — skipping"
fi

echo "== 5/8: force-deleting Secrets Manager secrets (no recovery window) =="
for secret in "${PROJECT}/openai-api-key"; do
  aws secretsmanager delete-secret --secret-id "$secret" --force-delete-without-recovery \
    --region "$AWS_REGION" 2>/dev/null || true
done

echo "== 6/8: terraform destroy =="
cd "${REPO_ROOT}/infra/terraform"
# init is idempotent and required if .terraform/ was cleaned or this is a fresh clone —
# without it destroy fails with "Backend initialization required".
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
terraform init -reconfigure -backend-config="bucket=${PROJECT}-tfstate-${ACCOUNT_ID}-${AWS_REGION}"
terraform destroy -auto-approve -var-file=envs/learning.tfvars

echo "== 7/8: deleting leftover CloudWatch log groups =="
for prefix in "/aws/eks/${PROJECT}" "/aws/rds/${PROJECT}"; do
  aws logs describe-log-groups --log-group-name-prefix "$prefix" --region "$AWS_REGION" \
    --query 'logGroups[].logGroupName' --output text 2>/dev/null \
    | tr '\t' '\n' | xargs -r -n1 -I{} aws logs delete-log-group --log-group-name {} --region "$AWS_REGION"
done

echo "== 8/8: verifying nothing tagged Project=${PROJECT} remains =="
REMAINING="$(aws resourcegroupstaggingapi get-resources \
  --tag-filters "Key=Project,Values=${PROJECT}" \
  --region "$AWS_REGION" --output json)"
COUNT="$(echo "$REMAINING" | python3 -c "import json,sys; print(len(json.load(sys.stdin)['ResourceTagMappingList']))")"
if [ "$COUNT" != "0" ]; then
  echo "WARNING: ${COUNT} tagged resources still remain:" >&2
  echo "$REMAINING" | python3 -c "import json,sys; [print(r['ResourceARN']) for r in json.load(sys.stdin)['ResourceTagMappingList']]" >&2
  exit 1
fi

echo "teardown complete — zero tagged resources remain"
