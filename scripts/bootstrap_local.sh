#!/usr/bin/env bash
# One-shot local bootstrap: venv, fixtures, local infra, migrations, seed data.
# Equivalent to Runbook — Running Locally, Steps 1-6.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [ ! -d .venv ]; then
  python3.12 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate 2>/dev/null || source .venv/Scripts/activate
pip install --upgrade pip
pip install -e ".[local,testdata,dev]"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "wrote .env from .env.example — set OPENAI_API_KEY before continuing"
fi

python -m testdata.generate all
python -m testdata.generate verify

docker compose -f docker-compose.local.yml up -d
echo "waiting for postgres to accept connections..."
until docker exec claims-postgres pg_isready -U claims >/dev/null 2>&1; do
  sleep 1
done

python scripts/run_migrations.py --env local
python -m pipelines.data_pipeline ingest --source ./data/policies/ --domain claims --rebuild-graph
python -m pipelines.data_pipeline verify --domain claims

echo "bootstrap complete — run 'make run-local' to start the API"
