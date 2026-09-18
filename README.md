# Claim Adjudication Assist

A LangGraph multi-agent system for health insurance claim intake and adjudication, on AWS.

Learning / training-grade project with production-grade *structure* — simple agent logic, real
infrastructure patterns. Every cloud dependency sits behind a small Python interface with two
implementations, `local` and `aws`, selected by `APP_ENV`. `APP_ENV=local` runs the whole graph
with no AWS, no Redis, no Kubernetes. All data is synthetic — no real PHI or PII enters this
project at any point.

Full design and the delivery plan live in [docs/DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md).
Architecture diagram and component walkthrough: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
What to demo and why: [docs/TEACHING_NOTES.md](docs/TEACHING_NOTES.md).

## Status

All fifteen delivery phases are built. **P0–P12 are fully local, free, and verified** (101
tests passing, lint and mypy clean, the same suite passing inside the built Docker image).
**P13–P15** (Terraform, Kubernetes deploy, live Textract capture) are authored and validated
where that's possible without an AWS account — `terraform validate` passes on every module —
but never applied against real AWS in this repo's history, since that starts real billing.
Deploying is a deliberate action you take when ready; see the runbook below.

| Phase | What | Verified |
|---|---|---|
| P0–P11 | Agents, graph, RAG, memory/tradeoff, observability, streaming API, full test suite | ✅ `make test` — 101 passed |
| P12 | Dockerfile, entrypoint, compose parity | ✅ `make docker-test` — 101 passed inside the container |
| P13 | Terraform: network, RDS, ElastiCache, EKS, ECR, IAM/IRSA, Secrets, S3, budget | ✅ `terraform validate` (plan/apply need real AWS credentials) |
| P14 | Kubernetes manifests, migrate/seed Jobs, `infra-deploy.yml` | ✅ manifests hand-reviewed (no live cluster available to dry-run against) |
| P15 | Textract `--mode capture`, docs | ✅ capture code path built in P1; this README/architecture/teaching-notes set |

## Quickstart — run it locally

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -e ".[local,testdata,dev]"

cp .env.example .env
# edit .env and set OPENAI_API_KEY

make fixtures                        # generates every PDF/JSON fixture, offline, free
docker compose -f docker-compose.local.yml up -d   # postgres+pgvector, prometheus, grafana
make migrate
make seed                            # the one step that spends OpenAI credit — a few cents
make run-local
curl localhost:8000/healthz          # {"status":"ok"}
```

Submit a claim and watch it stream:

```bash
python scripts/stream_client.py --file tests/fixtures/claims/CLM-001.pdf
```

Skip Docker entirely with `VECTOR_BACKEND=numpy` in `.env` — everything then runs on the
in-memory vector store and the SQLite checkpointer. Full step-by-step walkthrough, including
the interesting failure-path fixtures and the Grafana dashboard, is in
**Runbook — Running Locally** in [docs/DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md).

## Testing

```bash
make test          # full suite — FakeChatModel doubles, no network, no OpenAI spend
make test-e2e       # parametrised end-to-end over testdata/manifest.yaml's 14 scenarios
make lint            # ruff + mypy
make docker-test     # builds the image's `test` stage and runs the same suite inside it
```

CI (`.github/workflows/ci.yml`) runs all of the above plus `python -m testdata.generate verify`
on every push/PR, with a 70% coverage gate on `src/app/graph`, `src/app/validation` and
`src/app/memory`.

## Containers

```bash
make docker-build    # runtime image — target under 500MB, non-root, HEALTHCHECK on /healthz
make docker-run       # runs it locally on :8000
make docker-test       # test-stage image: regenerates fixtures at build time, runs pytest
```

`docker-compose.local.yml` includes an `app` service behind the `app` profile, so
`docker compose --profile app up -d` runs the containerized app alongside Postgres,
Prometheus and Grafana — the same stack `make up` starts, plus the app itself.

## Deploying to AWS

**This costs money** — roughly $150–200/month if left running (EKS control plane, NAT
gateway, RDS, ElastiCache, ALB). Plan to destroy the same day you test.

1. `infra/terraform/bootstrap` creates the remote state bucket + lock table (run once).
2. `infra/terraform` provisions everything else: VPC (single NAT gateway), RDS Postgres,
   ElastiCache Redis, EKS (one managed node group), ECR, IRSA roles, a Secrets Manager
   *shell* (the OpenAI key is injected out-of-band, never in `.tf`), and a $50 budget alert.
3. `scripts/render_k8s_config.sh` turns `terraform output -json` into
   `k8s/configmap.yaml` and `k8s/serviceaccount.rendered.yaml` — no endpoint is ever
   typed by hand into a manifest.
4. `k8s/job-db-migrate.yaml` and `k8s/job-seed-data.yaml` must complete before the
   `Deployment` rolls.
5. `.github/workflows/infra-deploy.yml` runs all of the above via GitHub OIDC role
   assumption (no long-lived AWS keys as repo secrets), gated behind an `aws-deploy`
   environment approval. `.github/workflows/infra-destroy.yml` is `workflow_dispatch`
   only and requires typing `destroy`.
6. `scripts/destroy_all.sh` / `make destroy` tears down in the order that actually works
   (Ingress → LoadBalancer Services → S3 object versions → ECR images → secrets →
   `terraform destroy` → CloudWatch log groups), then verifies zero resources remain
   tagged `Project=claim-adjudication`.

The full step-by-step is **Runbook — Deploying To AWS** in
[docs/DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md). None of these steps have been run
against a real AWS account from this repository — `terraform validate` is the extent of
what's been verified without live credentials.

## The six agents

| Agent | LLM | Technique |
|---|---|---|
| ClaimIntakeAgent | Yes | Zero-shot OCR-to-fields extraction |
| ClaimValidatorAgent | **No** | Deterministic Pydantic + business rules |
| FieldRepairAgent | Yes | Few-shot re-extraction from raw OCR text |
| HeuristicFallbackAgent | **No** | Regex/heuristic last resort |
| PolicyAdjudicatorAgent | Yes | Chain-of-thought + GraphRAG (networkx ∪ pgvector) |
| DecisionAuditorAgent | Yes | Deterministic checks + LLM critique, self-healing loop |

Two agents never call a model — that's deliberate, and worth noticing: not every node in
an agentic system needs an LLM. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the
full graph and [docs/TEACHING_NOTES.md](docs/TEACHING_NOTES.md) for which fixture proves
which agent actually does its job.

## Non-goals

No fine-tuning, no multi-model routing, no human-in-the-loop UI beyond a
`needs_human_review` flag, no production auth beyond a static API-key header, no
multi-tenancy. Each agent stays under ~150 lines. Full list in
[docs/DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md#non-goals).
