#!/usr/bin/env bash
# Smoke test against a running deployment — checks health and submits CLM-001 through
# the SSE stream, asserting a `final` event with a decision arrives. Used against the
# ALB URL after deploy (Runbook step 12) but works against any base URL.
#
#   ./scripts/smoke_test.sh https://<alb-hostname>
#   ./scripts/smoke_test.sh http://localhost:8000
set -euo pipefail

BASE_URL="${1:?usage: smoke_test.sh <base-url>}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FIXTURE="${REPO_ROOT}/tests/fixtures/claims/CLM-001.pdf"

echo "== healthz =="
curl -sf "${BASE_URL}/healthz" | tee /dev/stderr | grep -q '"status":"ok"'

echo "== readyz =="
curl -sf "${BASE_URL}/readyz" | tee /dev/stderr | grep -q '"status":"ok"'

echo "== submit CLM-001 =="
if [ ! -f "$FIXTURE" ]; then
  echo "error: $FIXTURE not found — run 'make fixtures' first" >&2
  exit 1
fi

STREAM="$(curl -sf -N -X POST "${BASE_URL}/v1/claims/adjudicate" \
  -F "file=@${FIXTURE}" \
  -H "Accept: text/event-stream")"

if ! echo "$STREAM" | grep -q "^event: final"; then
  echo "smoke test FAILED — no 'final' event in the stream" >&2
  echo "$STREAM" >&2
  exit 1
fi

echo "smoke test passed — final event received"
