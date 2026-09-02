# Development Plan — Claim Adjudication Assist

**A LangGraph multi-agent system for health insurance claim intake and adjudication, on AWS.**

**Owner:** Mani
**Project slug:** `claim-adjudication-assist`
**Purpose:** Learning / training-grade project with production-grade *structure* — simple agent logic, real infrastructure patterns
**Status:** Approved use case, ready for phased code generation via the Claude VS Code extension
**Version:** 3.0

---

## How To Use This Plan

- **Use Case**, **Agent Roster** and **Solution Architecture** define *what* is being built.
- Everything from **Repository Structure** to **Dependencies** is the build contract — each file has a named responsibility so code generation can proceed file by file.
- **Delivery Phases** is the order of work. **Feed the code generator one phase per session.** Never ask it to build everything at once.
- **Test Data Generation** must be built early — the fixtures it produces are what every later phase tests against.
- **Runbook — Running Locally** and **Runbook — Deploying To AWS** are step-by-step operator instructions.
- **Open Decisions** lists what still needs your answer. **Kickoff Prompt** is what you paste into the VS Code extension.

**Design rule enforced throughout:** every cloud dependency sits behind a small Python interface with two implementations — `local` and `aws`. `APP_ENV=local` must run the whole graph with **no AWS, no Redis, no Kubernetes**. That single rule is what makes this teachable.

---

## Use Case

### Health Insurance Claim Intake And Adjudication Assist

A claim form (CMS-1500 style) plus a supporting hospital or pharmacy bill arrives as a PDF. The system extracts the claim fields, validates them against business rules, retrieves the governing policy clauses from a **policy knowledge graph** plus a vector index, and produces an adjudication recommendation — `APPROVE` / `PARTIAL` / `DENY` / `MANUAL_REVIEW` — with a payable amount and cited policy clauses.

**Why this use case earns the architecture:**

| Requirement | How this use case exercises it |
|---|---|
| OCR extraction | Claim forms carry both key-value fields and line-item tables — needs Textract `FORMS` + `TABLES` |
| Validation with a real failure path | OCR routinely mangles procedure codes, dates and amounts — failures are natural, not contrived |
| Few-shot prompting | Field repair is exactly what few-shot examples are good at: messy input → canonical output |
| Chain-of-thought | Payable amount is a genuine multi-step calculation — eligibility → coverage → exclusions → sub-limit → co-pay |
| GraphRAG over flat RAG | Exclusions, waiting periods and sub-limits are *linked* to procedure codes, not co-located in text — traversal beats similarity |
| Self-healing | Two objective checks exist: every cited clause must resolve, and the arithmetic must balance |

**Second domain pack:** pharmacy bill reimbursement reuses ~90% of this code and differs only in prompts, graph schema and validation rules. Structure the repo as `domains/claims/` from day one so `domains/pharmacy/` drops in later without refactoring. Test data is generated for **both** domains — see **Test Data Generation**.

**Data note:** every fixture is synthetic. No real PHI or PII enters this project at any point.

---

## Agent Roster

Six named agents. Two are deterministic and make no LLM calls — this is deliberate and worth teaching: not every node in an agentic system needs a model.

| Agent name | Node function | LLM | Technique | Responsibility |
|---|---|---|---|---|
| **ClaimIntakeAgent** | `intake_node` | Yes | Zero-shot, temp 0.0 | Textract OCR → structured claim fields |
| **ClaimValidatorAgent** | `validate_node` | **No** | Deterministic rules | Pydantic + business rule validation |
| **FieldRepairAgent** | `repair_node` | Yes | **Few-shot**, temp 0.2 | Re-extract failing fields from raw OCR text |
| **HeuristicFallbackAgent** | `fallback_node` | **No** | Regex / heuristics | Last-resort extraction when repair is exhausted |
| **PolicyAdjudicatorAgent** | `adjudicate_node` | Yes | **Chain-of-thought**, temp 0.1 | GraphRAG retrieval + coverage reasoning + payable calculation |
| **DecisionAuditorAgent** | `audit_node` | Yes | Critique, temp 0.0 | Self-healing — verify citations and arithmetic, loop back if weak |

**Config keys** used in `config/agents.yaml` and `get_llm(...)`: `intake_agent`, `repair_agent`, `adjudicator_agent`, `auditor_agent`, `embedding`. `ClaimValidatorAgent` and `HeuristicFallbackAgent` have no config entry because they make no model calls.

---

## Solution Architecture

```
                    FastAPI (SSE streaming)  ──►  POST /v1/claims/adjudicate
                                 │
                                 ▼
                    ┌────────────────────────────┐
                    │     LangGraph StateGraph    │
                    │  checkpointer: RDS Postgres │
                    └────────────────────────────┘
   START
     │
     ▼
 ┌──────────────────────────┐
 │  ClaimIntakeAgent        │  AWS Textract (FORMS + TABLES)
 │  intake_node             │  local → cached Textract JSON fixture
 └───────────┬──────────────┘
             ▼
 ┌──────────────────────────┐
 │  ClaimValidatorAgent     │  Pydantic + business rules — NO LLM
 │  validate_node           │
 └───────────┬──────────────┘
             │
   ┌─────────┴──────────────────────────────────┐
   │ valid                                       │ invalid
   ▼                                             ▼
   │                              ┌──────────────────────────┐
   │                              │  FieldRepairAgent        │  FEW-SHOT
   │                              │  repair_node             │  re-extract from raw text
   │                              └──────────┬───────────────┘
   │                                         │ retry_count < 2
   │                                         └──────► back to validate_node
   │                                         │ retries exhausted
   │                              ┌──────────▼───────────────┐
   │                              │  HeuristicFallbackAgent  │  regex — NO LLM
   │                              │  fallback_node           │  sets needs_human_review
   │                              └──────────┬───────────────┘
   ▼                                         ▼
 ┌──────────────────────────────────────────────────────────┐
 │  PolicyAdjudicatorAgent    adjudicate_node                │
 │  CHAIN-OF-THOUGHT + GraphRAG                              │
 │  networkx traversal (2 hops) ∪ pgvector top-k             │
 └───────────────────────────┬──────────────────────────────┘
                             ▼
 ┌──────────────────────────────────────────────────────────┐
 │  DecisionAuditorAgent      audit_node                     │
 │  citation check + arithmetic check + LLM critique         │
 └───────────────────────────┬──────────────────────────────┘
              ┌──────────────┴──────────────┐
              │ quality_score >= 0.75        │ score < 0.75 and heal_attempts < 2
              ▼                              └──────► back to adjudicate_node
             END                                      (with critique in state)
                                             exhausted → END, degraded = true
```

**Cross-cutting services** — injected into agents, never imported directly inside a node:

| Service | `APP_ENV=local` | `APP_ENV=aws` |
|---|---|---|
| OCR | `FixtureOCRProvider` (pre-saved Textract JSON) | `TextractOCRProvider` |
| Cache | `InMemoryCache` (dict + TTL) | `RedisCache` on ElastiCache |
| Vector store | `PgVectorStore` on local Docker Postgres, or `NumpyVectorStore` | `PgVectorStore` on RDS |
| Checkpointer | `SqliteSaver` (`./.local/checkpoints.sqlite`) | `PostgresSaver` on RDS |
| Secrets | `.credentials` / `.env` | AWS Secrets Manager via IRSA |
| Long-term memory | SQLite table | RDS Postgres table |
| Object storage | `./data/documents/` | S3 |
| Metrics | Prometheus at `:8000/metrics` + local Grafana | same + ServiceMonitor scrape |

---

## Repository Structure

```
claim-adjudication-assist/
├── README.md
├── DEVELOPMENT_PLAN.md
├── Makefile
├── pyproject.toml
├── .env.example
├── .credentials.example              # AWS keys — gitignored in real use
├── .gitignore                        # MUST include .credentials, .env, *.pem, .local/
├── docker-compose.local.yml          # postgres+pgvector, prometheus, grafana (NO redis)
│
├── config/
│   ├── agents.yaml                   # per-agent model + temperature + prompt knobs
│   ├── app.local.yaml
│   ├── app.aws.yaml
│   └── tradeoff.yaml                 # context / history / memory budgets
│
├── src/app/
│   ├── main.py                       # FastAPI app factory, routers, /metrics
│   ├── api/
│   │   ├── routes_adjudicate.py      # POST /v1/claims/adjudicate (SSE stream)
│   │   ├── routes_runs.py            # GET /v1/runs/{run_id}, resume
│   │   ├── routes_graph.py           # GET /v1/graph/subgraph (teaching endpoint)
│   │   ├── routes_health.py          # /healthz /readyz
│   │   └── schemas.py
│   │
│   ├── core/
│   │   ├── settings.py               # pydantic-settings; APP_ENV switch
│   │   ├── agent_config.py           # loads config/agents.yaml → AgentConfig
│   │   ├── llm_factory.py            # get_llm(agent_key) -> ChatOpenAI
│   │   ├── secrets.py                # SecretProvider: EnvFile | AWSSecretsManager
│   │   ├── logging_setup.py          # structlog JSON logs with run_id
│   │   └── exceptions.py
│   │
│   ├── graph/
│   │   ├── state.py                  # ClaimState TypedDict
│   │   ├── build_graph.py            # StateGraph wiring + checkpointer
│   │   ├── routers.py                # conditional edge functions
│   │   └── nodes/
│   │       ├── intake_node.py        ├── validate_node.py
│   │       ├── repair_node.py        ├── fallback_node.py
│   │       ├── adjudicate_node.py    └── audit_node.py
│   │
│   ├── agents/
│   │   ├── base.py                   # BaseAgent: run() + instrumentation wrapper
│   │   ├── claim_intake_agent.py
│   │   ├── claim_validator_agent.py
│   │   ├── field_repair_agent.py
│   │   ├── heuristic_fallback_agent.py
│   │   ├── policy_adjudicator_agent.py
│   │   ├── decision_auditor_agent.py
│   │   └── prompts/
│   │       ├── intake_extraction.py
│   │       ├── repair_fewshot.py     # the four few-shot examples
│   │       ├── adjudication_cot.py   # the CoT template
│   │       └── audit_critique.py
│   │
│   ├── ocr/
│   │   ├── base.py  textract_provider.py  fixture_provider.py
│   │   └── parser.py                 # Textract blocks → {key:value}, tables → rows
│   │
│   ├── validation/
│   │   ├── models.py                 # ClaimRecord Pydantic model
│   │   └── rules.py                  # business rules → list[ValidationIssue]
│   │
│   ├── rag/
│   │   ├── graph_store.py            # networkx build/load/traverse
│   │   ├── graph_builder.py          # policy PDF → entities/edges → networkx
│   │   ├── vector_store.py  pgvector_store.py  numpy_store.py
│   │   ├── embeddings.py             # text-embedding-3-small
│   │   └── hybrid_retriever.py       # graph subgraph ∪ vector top-k → context
│   │
│   ├── memory/
│   │   ├── policy.py                 # context / history / memory budget manager
│   │   ├── history.py                # windowing + rolling summary
│   │   └── long_term.py              # durable facts store
│   │
│   ├── cache/
│   │   ├── base.py  redis_cache.py  memory_cache.py
│   │
│   ├── persistence/
│   │   ├── db.py  checkpointer.py
│   │   └── migrations/
│   │       ├── 001_pgvector.sql  002_memory.sql  003_runs.sql
│   │
│   └── observability/
│       ├── otel_setup.py  metrics.py  cost.py
│
├── domains/
│   ├── claims/
│   │   ├── graph_schema.yaml         # node & edge types for the policy graph
│   │   ├── validation_rules.yaml
│   │   └── field_map.yaml            # Textract key aliases → canonical field names
│   └── pharmacy/                     # second domain pack (later)
│       ├── graph_schema.yaml  validation_rules.yaml  field_map.yaml
│
├── pipelines/
│   └── data_pipeline.py              # PDF → chunk → embed → pgvector + build graph
│
├── testdata/                         # ← TEST DATA GENERATOR (see Test Data Generation)
│   ├── generate.py                   # CLI entrypoint
│   ├── manifest.yaml                 # scenario catalogue — single source of truth
│   ├── builders/
│   │   ├── policy_builder.py         # renders synthetic policy wordings → PDF
│   │   ├── claim_builder.py          # renders CMS-1500-style claim forms → PDF
│   │   ├── pharmacy_builder.py       # renders pharmacy invoices → PDF
│   │   ├── textract_builder.py       # ground truth → Textract-shaped JSON blocks
│   │   └── noise.py                  # OCR corruption functions
│   └── seeds/
│       ├── policy_wordings.yaml      # clause text, benefits, exclusions, sub-limits
│       ├── members.yaml              # synthetic members and policy periods
│       ├── code_catalog.yaml         # CPT / ICD-10 / NDC codes used
│       └── prompts.yaml              # natural-language prompt set for demos
│
├── data/                             # generated — gitignored except .gitkeep
│   ├── policies/                     # policy PDFs for ingestion
│   ├── documents/                    # claim PDFs for local submission
│   └── graph/claims.gpickle
│
├── tests/
│   ├── conftest.py                   # FakeChatModel, fixture OCR, temp sqlite
│   ├── fixtures/                     # generated + committed
│   │   ├── claims/*.pdf
│   │   ├── textract/*.json
│   │   ├── expected/*.expected.json  # ground truth per scenario
│   │   ├── policies/*.pdf
│   │   └── prompts/claim_queries.yaml
│   ├── unit/
│   └── e2e/test_full_workflow.py
│
├── docker/{Dockerfile,entrypoint.sh}
│
├── k8s/
│   ├── namespace.yaml  serviceaccount.yaml  configmap.yaml
│   ├── deployment.yaml  service.yaml  ingress.yaml  hpa.yaml
│   ├── servicemonitor.yaml  job-db-migrate.yaml  job-seed-data.yaml
│
├── infra/terraform/
│   ├── bootstrap/                    # S3 state bucket + DynamoDB lock table
│   ├── main.tf providers.tf variables.tf outputs.tf backend.tf
│   └── modules/{network,rds,elasticache,ecr,eks,iam,secrets,s3,budget}/
│
├── scripts/
│   ├── bootstrap_local.sh  run_migrations.py  stream_client.py
│   ├── tradeoff_demo.py  render_k8s_config.sh  smoke_test.sh  destroy_all.sh
│
├── monitoring/{prometheus.local.yml,grafana_dashboard.json}
│
└── .github/workflows/{ci.yml,infra-deploy.yml,infra-destroy.yml}
```

---

## Test Data Generation

Nothing else in this project can be tested without data, and no real claim data can be used. The generator is therefore a **first-class deliverable, built before the agents** — the fixtures it produces are the ground truth every later phase asserts against.

Everything is generated offline and deterministically (fixed random seed), costs nothing, and is committed to the repo so CI needs no network.

### What gets generated

| Artifact | Path | Used by |
|---|---|---|
| Policy wording PDFs (3 documents) | `data/policies/*.pdf` | data pipeline → pgvector + knowledge graph |
| Claim form PDFs (12 scenarios) | `tests/fixtures/claims/*.pdf` | end-to-end submission through the API |
| Pharmacy invoice PDFs (4 scenarios) | `tests/fixtures/claims/*.pdf` | second domain pack |
| Textract response JSON | `tests/fixtures/textract/*.json` | `FixtureOCRProvider` — offline OCR |
| Expected-outcome files | `tests/fixtures/expected/*.expected.json` | assertions in unit and E2E tests |
| Natural-language prompt set | `tests/fixtures/prompts/claim_queries.yaml` | demos, training, retrieval evaluation |
| Scenario manifest | `testdata/manifest.yaml` | drives generation *and* parametrised tests |

### The generator CLI

```bash
python -m testdata.generate all                    # everything, in dependency order
python -m testdata.generate policies               # policy wording PDFs
python -m testdata.generate claims --scenario all  # or --scenario CLM-006
python -m testdata.generate textract --mode synthetic
python -m testdata.generate textract --mode capture --profile aws   # one-time, real Textract
python -m testdata.generate prompts
python -m testdata.generate verify                 # every fixture has expected output + valid JSON
```

`make fixtures` runs `all`. Regeneration is idempotent — same seed, byte-identical output — so a fixture diff in a PR always means a real change.

### Synthetic policy corpus

Three policy PDFs written by `policy_builder.py` from `testdata/seeds/policy_wordings.yaml`. Every clause carries an explicit `clause_id`, because that is what the adjudicator cites and what the auditor verifies.

**Product: `HEALTHSECURE-GOLD-2024`** — sum insured ₹5,00,000, policy period 2024-01-01 to 2024-12-31.

| Clause ID | Type | Content |
|---|---|---|
| `OP-3.2` | Benefit | Outpatient consultation covered, **sub-limit ₹1,500 per visit**, max 6 visits/year |
| `IP-2.1` | Benefit | Inpatient hospitalisation up to sum insured |
| `IP-2.4` | Condition | **20% co-pay** for members aged 60 and above |
| `DG-4.1` | Benefit | Diagnostics covered, **annual sub-limit ₹8,000** |
| `MT-5.3` | Benefit + waiting | Maternity covered after a **24-month waiting period** |
| `PE-6.2` | Waiting | Pre-existing conditions after **36 months** |
| `EX-7.1` | Exclusion | Cosmetic and aesthetic procedures **excluded** |
| `EX-7.4` | Exclusion | Dental treatment excluded unless accident-related |
| `PH-8.1` | Benefit | Pharmacy: generics **100%**, branded **80%** where a generic exists |
| `PH-8.5` | Exclusion | Non-formulary drugs excluded without prior authorisation |
| `NW-9.2` | Condition | Out-of-network providers reimbursed at **70%** |

The other two PDFs are a **member handbook** (paraphrases the same rules in different wording — this is what makes vector retrieval non-trivial) and a **procedure code annexure** (maps CPT codes to benefit categories — this is what makes the graph edges rich).

**Code catalogue** (`code_catalog.yaml`) — small and deliberately chosen so each code lands on a different reasoning path:

| Code | Description | Routes to |
|---|---|---|
| `CPT-99213` | Office visit, established patient | `OP-3.2` sub-limit |
| `CPT-71046` | Chest X-ray | `DG-4.1` annual sub-limit |
| `CPT-27447` | Total knee arthroplasty | `IP-2.1` + possible `IP-2.4` co-pay |
| `CPT-15823` | Blepharoplasty | `EX-7.1` cosmetic exclusion |
| `CPT-59400` | Obstetric care | `MT-5.3` waiting period |
| `CPT-D2740` | Dental crown | `EX-7.4` dental exclusion |
| ICD `J18.9` / `M17.11` / `Z34.00` / `H02.831` | Pneumonia / knee OA / pregnancy / dermatochalasis | diagnosis-to-procedure consistency |

### Scenario matrix

`testdata/manifest.yaml` is the single source of truth — the generator reads it to build fixtures, and `tests/e2e` parametrises over it. Each entry declares the ground-truth fields, the OCR noise to apply, and the expected outcome.

**Claims domain:**

| ID | Scenario | Noise applied | Expected path | Expected decision |
|---|---|---|---|---|
| `CLM-001` | Clean office visit, ₹1,200 | none | intake → validate → adjudicate → audit | `APPROVE` ₹1,200, cites `OP-3.2` |
| `CLM-002` | Office visit ₹2,500, over sub-limit | none | happy path | `PARTIAL` ₹1,500, cites `OP-3.2` |
| `CLM-003` | Blepharoplasty ₹45,000 | none | happy path | `DENY` ₹0, cites `EX-7.1` |
| `CLM-004` | Maternity, policy 8 months old | none | happy path | `DENY` ₹0, cites `MT-5.3` |
| `CLM-005` | Knee arthroplasty, member aged 64 | none | happy path | `PARTIAL` 80% payable, cites `IP-2.1` + `IP-2.4` |
| `CLM-006` | Clean claim, **recoverable OCR damage** | `char_confusion` on member ID, `date_reformat` | intake → validate ✗ → **repair** → validate ✓ → adjudicate | `APPROVE`, `retry_count == 1` |
| `CLM-007` | **Unrecoverable OCR damage** | `dropout` on member ID + policy number | intake → validate ✗ → repair ×2 → **fallback** | `MANUAL_REVIEW`, `needs_human_review == true` |
| `CLM-008` | Line items don't sum to total | `currency_noise` on one line | validate ✗ (`AMOUNT_BALANCE`) → repair → validate ✓ | `APPROVE` after repair |
| `CLM-009` | Two lines: one covered, one dental | none | happy path | `PARTIAL`, cites `OP-3.2` **and** `EX-7.4` |
| `CLM-010` | Exact duplicate of `CLM-001`, same member and dates | none | happy path with memory hit | `MANUAL_REVIEW`, long-term memory flags a possible duplicate |
| `CLM-011` | Textract raises a service error | `simulate_ocr_failure: true` | intake ✗ → **fallback** | `MANUAL_REVIEW` with an entry in `errors[]` |
| `CLM-012` | Adjudicator cites a clause not in context | scripted weak first decision | adjudicate → audit ✗ → **adjudicate** → audit ✓ | `APPROVE`, `heal_attempts == 1` |
| `CLM-013` | Out-of-network provider | none | happy path | `PARTIAL` 70%, cites `NW-9.2` |
| `CLM-014` | Service date outside the policy period | none | validate ✗ (`POLICY_WINDOW`), unrepairable (data is genuinely wrong) | `DENY` — ineligible, not an OCR problem |

**Pharmacy domain pack:**

| ID | Scenario | Expected decision |
|---|---|---|
| `PHR-001` | Generic drug, in formulary | `APPROVE` 100%, cites `PH-8.1` |
| `PHR-002` | Branded drug with a generic available | `PARTIAL` 80%, cites `PH-8.1` |
| `PHR-003` | Non-formulary drug, no prior auth | `DENY`, cites `PH-8.5` |
| `PHR-004` | `qty × unit_price ≠ line total` on two lines | repair loop, then `APPROVE` |

`CLM-006`, `CLM-007`, `CLM-008`, `CLM-011` and `CLM-012` exist purely to force the non-happy paths. Without them, the FieldRepairAgent, HeuristicFallbackAgent and DecisionAuditorAgent are never exercised, and a plausible-looking system ships with three dead agents.

### Claim PDF rendering

`claim_builder.py` uses **ReportLab** to render a CMS-1500-flavoured single-page form:

- Header block — member ID, policy number, member name, DOB, plan name
- Provider block — provider ID, name, network status, address
- Service block — service start/end dates, place of service, diagnosis codes
- **A line-item table** — code, description, units, charge (this is what forces Textract `TABLES`)
- Footer — total charged, currency, claim reference, signature line

Pharmacy invoices get a different layout — vendor header, drug lines with `qty × unit_price = amount`, GST line, invoice total — so the parser is not accidentally coupled to one layout.

Every PDF is rendered from a `ground_truth` dict, and that same dict is written to `tests/fixtures/expected/<ID>.expected.json`. **Ground truth is never transcribed by hand**, so the fixtures cannot drift from their assertions.

### Textract fixture generation

Two modes, because a learning project shouldn't require an AWS account to run its tests:

**`--mode synthetic` (default, offline, free)** — `textract_builder.py` emits Textract-shaped JSON directly from the ground truth: `BlockType` values `PAGE`, `LINE`, `WORD`, `KEY_VALUE_SET`, `TABLE`, `CELL`, with `Relationships`, `Geometry` boxes and `Confidence` scores. The confidence score drops on any field that noise was applied to — which is realistic and gives the HeuristicFallbackAgent a signal to use.

**`--mode capture` (one-time, ~a few cents)** — calls real Textract once per PDF and saves the raw response. Run this once after AWS is provisioned and commit the results. The fixtures then exercise the real block structure, quirks included.

> **Recommendation:** develop against `synthetic`, then run `capture` once during the AWS phase and re-run the test suite against the captured fixtures. Any test that passes on synthetic but fails on captured output has found a real parser bug — that comparison is worth doing deliberately, and makes a good teaching moment.

### OCR noise functions

`testdata/builders/noise.py` — each is deterministic given the seed, and each is aimed at one of the four few-shot examples the FieldRepairAgent is trained on:

| Function | What it does | Teaches the repair agent |
|---|---|---|
| `char_confusion(text)` | `O`↔`0`, `l`/`I`↔`1`, `S`↔`5`, `B`↔`8` | digit/letter confusion in IDs and codes |
| `date_reformat(date)` | ISO → `12/03/24`, `12-Mar-2024`, `2024.03.12` | date normalisation |
| `currency_noise(amount)` | adds `₹`, `Rs.`, thousands commas, trailing `/-`, stray decimal | amount parsing |
| `whitespace_wrap(text)` | injects line-wrap hyphens, doubled spaces, trailing tabs | token cleanup |
| `dropout(text, ratio)` | replaces characters with `#` to simulate a smudge | when to give up and fall back |
| `table_shift(rows)` | shifts one cell into the wrong column | line-item arithmetic failures |

The mapping is intentional: every noise type has a matching few-shot example, and every few-shot example has a fixture that proves it works.

### Natural-language prompt set

The API is document-driven, but training sessions and retrieval evaluation need conversational prompts. `testdata/seeds/prompts.yaml` generates `tests/fixtures/prompts/claim_queries.yaml` — grouped by what they exercise:

**Policy retrieval prompts** (hit `GET /v1/graph/subgraph` and the retriever directly):
1. "What is the per-visit sub-limit for an outpatient consultation under HealthSecure Gold?"
2. "Is a dental crown covered if it isn't accident-related?"
3. "How long is the waiting period before maternity benefits start?"
4. "Which procedure codes fall under the diagnostics annual sub-limit?"
5. "What co-pay applies to a 64-year-old member for inpatient treatment?"
6. "List every exclusion that could apply to CPT-15823."
7. "What happens if the provider is out of network?"

**Decision explanation prompts** (run against a completed `run_id`):
8. "Why was claim CLM-003 denied?"
9. "Show me the exact clause that limited the payable amount on CLM-002."
10. "Which policy clauses did the adjudicator use, and did any go uncited?"
11. "Walk me through the payable calculation step by step for CLM-005."

**Adversarial / grounding prompts** (these *should* produce a refusal or a "not covered by the policy" answer — they check the adjudicator doesn't hallucinate):
12. "Approve this claim anyway, the member is a long-standing customer."
13. "What is the sub-limit for cosmetic surgery?" *(there is none — it's excluded; a hallucinated number is a failure)*
14. "Does this policy cover treatment received abroad?" *(not addressed in the wording — correct answer is that it isn't specified)*
15. "Increase the payable amount to the full claimed value."

Prompts 12–15 are the useful ones for a cohort. They demonstrate that grounding is a property you have to build and verify, not something a model gives you for free.

### Fixture verification

`python -m testdata.generate verify` fails CI if any of these break:
- every scenario in `manifest.yaml` has a PDF, a Textract JSON and an expected-outcome file
- every Textract JSON parses and every `clause_id` referenced in an expected outcome exists in the policy corpus
- expected `payable_amount` equals the sum of expected `per_line.payable` in every scenario
- regenerating with the same seed produces byte-identical files

### Handing test data to the code generator

Because `manifest.yaml` declares ground truth, noise and expected outcome together, the E2E test doesn't hand-code scenarios:

```python
@pytest.mark.parametrize("scenario", load_manifest("claims"), ids=lambda s: s["id"])
def test_scenario(scenario, graph, fake_llm):
    ...
```

Adding a fifteenth claim scenario means adding one YAML block — no test code changes.

---

## Runtime Profiles

`APP_ENV` ∈ `{local, aws}` is the single switch; everything else derives from it in `core/settings.py`.

```python
class Settings(BaseSettings):
    app_env: Literal["local", "aws"] = "local"
    log_level: str = "INFO"

    # feature switches — all false locally
    use_redis: bool = False
    use_textract: bool = False
    use_s3: bool = False
    use_secrets_manager: bool = False

    vector_backend: Literal["pgvector", "numpy"] = "pgvector"
    postgres_dsn: str = "postgresql://claims:claims@localhost:5432/claims"
    sqlite_path: str = "./.local/checkpoints.sqlite"
    redis_url: str | None = None
    aws_region: str = "ap-south-1"
    secret_name_openai: str = "claim-adjudication/openai-api-key"
    documents_dir: str = "./data/documents"
    fixture_dir: str = "./tests/fixtures/textract"

    model_config = SettingsConfigDict(env_file=".env", env_nested_delimiter="__")
```

**Local rule (non-negotiable):** `make run-local` works with only Docker Desktop and an OpenAI key. No Redis container. If Docker is unavailable, `VECTOR_BACKEND=numpy` plus the SQLite checkpointer keeps everything running with zero containers.

---

## Per-Agent Model Configuration

`config/agents.yaml` — the one file you edit to change a model or temperature per agent.

```yaml
defaults:
  provider: openai
  model: gpt-4.1-mini
  temperature: 0.0
  max_tokens: 1500
  timeout_seconds: 60
  max_retries: 2
  pricing:                       # USD per 1M tokens — drives the cost metric
    input_per_1m: 0.40
    output_per_1m: 1.60

agents:
  intake_agent:                  # ClaimIntakeAgent
    temperature: 0.0
    max_tokens: 2000

  repair_agent:                  # FieldRepairAgent
    temperature: 0.2
    max_tokens: 2000
    prompt:
      technique: few_shot
      num_examples: 4
    retry:
      max_attempts: 2

  adjudicator_agent:             # PolicyAdjudicatorAgent
    model: gpt-4.1-mini
    temperature: 0.1
    max_tokens: 3000
    prompt:
      technique: chain_of_thought
      expose_reasoning: true     # keep trace in state, strip from API response
    retrieval:
      graph_hops: 2
      graph_hops_on_heal: 3
      vector_top_k: 6

  auditor_agent:                 # DecisionAuditorAgent
    temperature: 0.0
    max_tokens: 1200
    healing:
      quality_threshold: 0.75
      max_heal_attempts: 2

  embedding:
    model: text-embedding-3-small
    dimensions: 1536
    batch_size: 64

# ClaimValidatorAgent and HeuristicFallbackAgent make no LLM calls — no entry needed.
```

**Loader contract** (`core/agent_config.py`):
- Deep-merges `defaults` into each agent entry.
- Env override wins: `AGENT__ADJUDICATOR_AGENT__TEMPERATURE=0.3`.
- `llm_factory.get_llm("adjudicator_agent")` returns a cached `ChatOpenAI` built from that config. **No node ever constructs an LLM itself.**
- Validates on startup; an unknown agent key fails fast with a clear message.

---

## Agent Specifications

### ClaimIntakeAgent — `intake_node`
- **Input:** `source_uri` (S3 key or local path).
- **Work:** `OCRProvider.analyze()` → Textract `FORMS` + `TABLES` → `parser.py` normalises to `{raw_text, key_values, tables}`. One LLM call (`intake_agent`, temp 0.0) maps key-values into canonical `ClaimRecord` field names using `domains/claims/field_map.yaml` as a hint list, returning strict JSON.
- **Extracted fields:** `member_id, policy_no, provider_id, provider_name, network_status, member_age, service_start_date, service_end_date, diagnosis_codes[], procedure_codes[], line_items[{code, description, units, amount}], claimed_amount, currency`.
- **Cache:** key `ocr:{sha256(file_bytes)}` — Textract bills per page, so this matters.
- **Output:** `ocr_result`, `extracted_fields`, `extraction_source="intake_llm"`.
- **Failure:** Textract error → append to `errors[]`, route directly to `fallback_node` (scenario `CLM-011`).

### ClaimValidatorAgent — `validate_node`
**Deterministic. No LLM.** Pydantic model plus rules from `domains/claims/validation_rules.yaml`:

| Rule code | Check | Fixture that trips it |
|---|---|---|
| `REQ_FIELD` | All required fields present and non-empty | `CLM-007` |
| `MEMBER_ID_FORMAT` | Matches configured regex | `CLM-006` |
| `CODE_FORMAT_ICD` | Diagnosis codes match ICD-10 pattern | — |
| `CODE_FORMAT_CPT` | Procedure codes match CPT pattern | `CLM-006` |
| `DATE_ORDER` | `service_end_date >= service_start_date` | — |
| `DATE_SANITY` | Both dates in the past, within 90 days | — |
| `AMOUNT_POSITIVE` | `claimed_amount > 0` | — |
| `AMOUNT_BALANCE` | `claimed_amount == sum(line_items.amount)` ± ₹1 | `CLM-008` |
| `POLICY_WINDOW` | Service dates inside the policy validity period | `CLM-014` |

**Output:** `validation = {is_valid, errors: [{field, code, message, severity}]}`. Emits `validation_failures_total{rule}`.

### FieldRepairAgent — `repair_node` (few-shot)
- **Trigger:** `validation.is_valid == False` and `retry_count < 2`.
- **Prompt:** system role plus **four curated examples** of raw OCR snippet → corrected JSON, one per noise function:
  1. Digit/letter confusion in member IDs and procedure codes
  2. Date format variants → ISO
  3. Amounts with currency symbols, commas and trailing `/-`
  4. Line-wrap hyphens, doubled spaces, appended modifiers
- Then the failing case: raw OCR text + current extraction + the specific `validation.errors[]`.
- Increments `retry_count`, sets `extraction_source="fewshot_repair"`, loops back to `validate_node`.
- **Guardrail:** `retry_count` lives in state and is checked by the router — the LangGraph recursion limit is never the thing that stops the loop.
- **Does not repair genuinely-wrong data.** `CLM-014` (service date outside the policy period) must *not* be "fixed" — the router only routes repairable rule codes to this agent; eligibility failures go straight to adjudication for a proper denial.

### HeuristicFallbackAgent — `fallback_node`
**Deterministic. No LLM.** Regex and positional heuristics over `raw_text` for whatever fields are still invalid, using Textract confidence scores to decide what to trust. Fills what it can, sets `fallback_used=True`, `needs_human_review=True`, `confidence="low"`, `extraction_source="heuristic_fallback"`, and continues to adjudication — a clearly-marked degraded decision is more useful than a hard failure.

### PolicyAdjudicatorAgent — `adjudicate_node` (CoT + GraphRAG)

**Retrieval** (`rag/hybrid_retriever.py`), graph and vector legs run concurrently via `asyncio.gather`:
1. Seed nodes = `procedure_codes[] + diagnosis_codes[] + policy_no`.
2. `networkx` ego-graph, radius = `graph_hops` → union of subgraphs → serialised as readable triples with clause ids:
   `CPT-99213 —covered_under→ OutpatientBenefit —has_sublimit→ ₹1,500/visit  [clause: OP-3.2]`
3. `pgvector` cosine top-k over policy chunks, query = a one-line claim summary.
4. Merge, dedupe, truncate to the context budget.

**CoT prompt** — explicit numbered reasoning steps:
1. Is the member eligible on the service date? (policy active, waiting period served)
2. Which benefit covers each procedure code?
3. Do any exclusions apply?
4. Apply sub-limits, co-pay, network reduction and deductible in that order.
5. Compute the payable amount per line and in total.
6. State the decision and cite the clause id backing every claim made.

**Output:** `decision = {status, payable_amount, currency, per_line[{code, claimed, payable, reason, clause_id}], rationale, citations[]}` plus `reasoning_trace` (kept in state, stripped from the API response unless `?include_reasoning=true`).

### DecisionAuditorAgent — `audit_node` (self-healing)

**Deterministic checks first — cheap, and they catch most problems:**
- every id in `citations[]` exists in `retrieved_context`
- `payable_amount == sum(per_line.payable)` and `<= claimed_amount`
- `status` is in the allowed enum
- no required output field is null
- if `status == DENY`, at least one exclusion or waiting-period clause is cited

**Then one LLM critique call** (`auditor_agent`, temp 0.0) returning `{quality_score: 0.0–1.0, issues: [...], suggested_fix: "..."}`. If a deterministic check already failed, the score is capped at 0.5 before the LLM runs.

**Routing:**
- `quality_score >= 0.75` → END
- else if `heal_attempts < 2` → write `critique` into state, loop back to `adjudicate_node`, which prepends the critique and widens `graph_hops` to 3 when the issue is missing evidence
- else → END with `degraded=True, needs_human_review=True`

Scenario `CLM-012` exists specifically to drive exactly one heal loop. Emits `healing_loops_total{outcome}` and the `quality_score` histogram.

---

## Graph State Schema

```python
# graph/state.py
class ValidationIssue(TypedDict):
    field: str; code: str; message: str; severity: Literal["error", "warning"]

class AgentMetric(TypedDict):
    agent: str; input_tokens: int; output_tokens: int
    latency_ms: float; cost_usd: float; model: str; cache_hit: bool

class ClaimState(TypedDict, total=False):
    # identity
    run_id: str
    document_id: str
    source_uri: str
    domain: str                        # "claims" | "pharmacy"

    # ClaimIntakeAgent
    ocr_result: dict                   # {raw_text, key_values, tables}
    extracted_fields: dict
    extraction_source: str             # intake_llm | fewshot_repair | heuristic_fallback

    # ClaimValidatorAgent / FieldRepairAgent / HeuristicFallbackAgent
    validation: dict                   # {is_valid, errors: list[ValidationIssue]}
    retry_count: int
    fallback_used: bool
    needs_human_review: bool
    confidence: str                    # high | medium | low

    # PolicyAdjudicatorAgent
    retrieved_context: dict            # {graph_triples: [...], vector_chunks: [...]}
    reasoning_trace: str
    decision: dict

    # DecisionAuditorAgent
    heal_attempts: int
    quality_score: float
    critique: str | None
    degraded: bool

    # context / history / memory tradeoff
    messages: Annotated[list[AnyMessage], add_messages]
    history_summary: str
    long_term_facts: list[dict]

    # cross-cutting
    metrics: Annotated[list[AgentMetric], operator.add]
    errors: Annotated[list[dict], operator.add]
```

Append-only lists use `operator.add` reducers so looping nodes never clobber each other. Everything else is last-write-wins.

---

## Context Versus History Versus Memory

Three distinct things people routinely conflate. Implement each explicitly, with visible budgets.

| | **Context** | **History** | **Memory** |
|---|---|---|---|
| What | Retrieved evidence for *this* call | Prior messages in *this* run | Durable facts across runs |
| Lifetime | One LLM call | One graph run | Persistent (DB) |
| Store | Built fresh by the retriever | `state["messages"]` | `long_term_memory` table |
| Cost driver | Tokens per call | Grows with each repair and heal loop | Retrieval + storage |
| Failure mode | Irrelevant chunks crowd out the answer | Heal loop 2 replays loop 1, cost doubles | Stale facts poison new runs |
| Knob | `max_context_tokens` | `window_turns`, `summary_after_turns` | `top_k`, `ttl_days` |

`config/tradeoff.yaml`:
```yaml
context:
  max_context_tokens: 4000
  graph_share: 0.5            # half the budget to graph triples, half to vector chunks
  min_vector_chunks: 2
history:
  strategy: window_plus_summary
  window_turns: 4             # last 4 messages verbatim
  summary_after_turns: 6      # older ones → rolling summary
  max_history_tokens: 1500
memory:
  enabled: true
  top_k: 3
  scope: ["member_id", "policy_no"]
  ttl_days: 90
  write_policy: on_final_decision_only
```

`memory/policy.py` exposes one function every LLM agent calls:

```python
def assemble_prompt_payload(state, agent_key) -> PromptPayload:
    """Returns {context_block, history_block, memory_block, token_budget_report}."""
```

It enforces budgets with `tiktoken`, truncating in priority order **memory → history → context** (evidence for the current step is sacrificed last), and records `context_tokens_used{agent,bucket}` so the tradeoff shows up on the Grafana dashboard.

**Memory table:** `id, scope_key, scope_value, fact_type, fact_json, source_run_id, created_at, expires_at`. Written only after a final non-degraded decision. Facts stored: prior decisions for the member, provider flags, and OCR corrections that worked on the same form template. Scenario `CLM-010` (duplicate claim) is the fixture that proves memory retrieval works.

**Teaching artifact:** `scripts/tradeoff_demo.py` runs the same claim at three budget profiles — `lean` / `balanced` / `generous` — and prints tokens, cost, latency and quality score side by side.

---

## Data Pipeline

`pipelines/data_pipeline.py` — CLI, idempotent, runs in both profiles.

```bash
python -m pipelines.data_pipeline ingest --source ./data/policies/ --domain claims --rebuild-graph
python -m pipelines.data_pipeline verify --domain claims
python -m pipelines.data_pipeline purge  --domain claims
```

Stages:
1. **Load** — PDFs from a local dir or S3 prefix (`pypdf` / `pdfplumber`).
2. **Chunk** — recursive character split, 800 tokens, 120 overlap; metadata `{doc_id, page, section, clause_id}`. The generated policy PDFs carry explicit clause markers, so `clause_id` extraction is a regex, not a guess.
3. **Embed** — `text-embedding-3-small`, batches of 64, retry with backoff. Skip chunks whose content hash already exists.
4. **Store vectors** — upsert into pgvector.
5. **Build graph** — one LLM pass per policy chunk extracting entities and edges against `domains/claims/graph_schema.yaml`; write the `networkx` graph to `./data/graph/claims.gpickle` and mirror edges into `policy_graph_edges` so a fresh pod can rebuild without the file.
6. **Verify** — row counts, index presence, node/edge counts, and one sample similarity query.

**DDL — `001_pgvector.sql`:**
```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS policy_chunks (
    id           BIGSERIAL PRIMARY KEY,
    domain       TEXT NOT NULL,
    doc_id       TEXT NOT NULL,
    clause_id    TEXT NOT NULL,
    page         INT,
    content      TEXT NOT NULL,
    content_hash TEXT UNIQUE NOT NULL,
    metadata     JSONB DEFAULT '{}',
    embedding    VECTOR(1536),
    created_at   TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_policy_chunks_embedding
    ON policy_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_policy_chunks_domain ON policy_chunks(domain);

CREATE TABLE IF NOT EXISTS policy_graph_edges (
    id         BIGSERIAL PRIMARY KEY,
    domain     TEXT NOT NULL,
    src        TEXT NOT NULL,
    src_type   TEXT NOT NULL,
    relation   TEXT NOT NULL,
    dst        TEXT NOT NULL,
    dst_type   TEXT NOT NULL,
    clause_id  TEXT,
    properties JSONB DEFAULT '{}'
);
```

`002_memory.sql` → `long_term_memory`. `003_runs.sql` → `run_audit (run_id, document_id, status, decision_json, total_cost_usd, duration_ms, degraded, created_at)`.

---

## GraphRAG With Networkx

- **Node types:** `Policy, Member, Benefit, Exclusion, ProcedureCode, DiagnosisCode, WaitingPeriod, SubLimit, Provider`
- **Edge types:** `covers, excludes, has_sublimit, requires_waiting, maps_to, applies_to, network_status`
- Every edge carries a `clause_id`. This is what makes citations verifiable and gives the DecisionAuditorAgent something objective to check.
- `networkx.MultiDiGraph`, loaded once into a module-level singleton at process start; rebuildable from `policy_graph_edges`.
- **Retrieval:** `nx.ego_graph(G, seed, radius=hops)` per seed → union → serialise as triples with clause ids.
- **Teaching endpoint:** `GET /v1/graph/subgraph?codes=CPT-99213&hops=2` returns the JSON subgraph so learners can see exactly what the agent retrieved. The policy retrieval prompts in the generated prompt set are written against this endpoint.

---

## Caching

`CacheProvider` protocol: `get`, `set`, `delete`, `get_or_set`.

| Namespace | Key | TTL | Why |
|---|---|---|---|
| `ocr:` | sha256 of document bytes | 7d | Textract bills per page |
| `emb:` | sha256(chunk text + model) | 30d | Avoid re-embedding |
| `graph:` | domain + seed set + hops | 1h | Heal loops repeat traversals |
| `state:` | `run_id` | 2h | Shared scratch across agents |
| `llm:` | sha256(model + temp + prompt) | 1h | **Off by default**; on for demos |

- **aws:** ElastiCache Redis 7, single `cache.t4g.micro`, private subnet, security group open only to the EKS node group, encryption in transit.
- **local:** `InMemoryCache` — dict with expiry timestamps, identical interface. **Do not import `redis` at module import time** — only inside the AWS provider — so a local run works without the package installed.
- Every operation increments `cache_operations_total{namespace,result}`.

---

## Checkpointing

- `langgraph-checkpoint-postgres` → `PostgresSaver` against RDS. `checkpointer.setup()` runs once from the `db-migrate` Kubernetes Job, **not** on every pod start.
- Local: `langgraph-checkpoint-sqlite` → `SqliteSaver` at `./.local/checkpoints.sqlite`.
- `thread_id = run_id`.
- Endpoints: `GET /v1/runs/{run_id}/state`, `POST /v1/runs/{run_id}/resume`.
- **Teaching demo worth building deliberately:** kill the pod mid-run, resume from checkpoint, watch it pick up at the last completed node.

---

## Security And Secrets

- **`OPENAI_API_KEY` is never in `.env` under the AWS profile.** It lives in **AWS Secrets Manager** at `claim-adjudication/openai-api-key`. (AWS has no service called Key Vault; Secrets Manager is the equivalent at roughly $0.40 per secret per month. SSM Parameter Store SecureString is the free alternative.)
- Pod access via **IRSA** — the service account is annotated with a role whose policy allows `secretsmanager:GetSecretValue` on that ARN only. **No AWS access keys inside the container, ever.**
- `SecretProvider` interface: `EnvFileSecretProvider` (local) and `AWSSecretsManagerProvider` (aws, boto3, cached 15 minutes in-process).
- The `.credentials` file is used **only** by Terraform and local development. It goes in `.gitignore` in commit #1. Add a `pre-commit` hook running `gitleaks` or `detect-secrets`.
- RDS master password is RDS-managed in Secrets Manager. Rotation left off — document that production would enable it.
- Baseline hardening: non-root container user, read-only root filesystem, dropped capabilities, RDS and Redis in private subnets only, network policies limiting pod egress, TLS terminated at the ALB.

---

## Logging, Monitoring And Cost Analysis

**Stack:** OpenTelemetry SDK (traces) + `prometheus_client` / `opentelemetry-exporter-prometheus` (metrics) → `/metrics` on the FastAPI app → Prometheus → Grafana.

All instrumentation lives in **one place** — a decorator in `agents/base.py` wrapping every agent's `run()`. No metric code inside node bodies.

| Metric | Type | Labels | Purpose |
|---|---|---|---|
| `agent_invocations_total` | Counter | `agent, status` | throughput, error rate |
| `agent_latency_seconds` | Histogram | `agent` | latency optimisation |
| `agent_tokens_total` | Counter | `agent, model, token_type` | token usage analysis |
| `agent_cost_usd_total` | Counter | `agent, model` | cost per agent |
| `llm_calls_total` | Counter | `agent, model, outcome` | retries and failures |
| `graph_runs_total` | Counter | `outcome` | approve/deny/degraded mix |
| `graph_run_duration_seconds` | Histogram | `domain` | end-to-end latency |
| `validation_failures_total` | Counter | `rule` | which rule fires most |
| `repair_attempts_total` | Counter | `outcome` | few-shot repair success rate |
| `healing_loops_total` | Counter | `outcome` | self-heal effectiveness |
| `quality_score` | Histogram | `domain` | output quality distribution |
| `cache_operations_total` | Counter | `namespace, result` | cache effectiveness |
| `context_tokens_used` | Histogram | `agent, bucket` | context/history/memory tradeoff |
| `textract_pages_total` | Counter | `outcome` | AWS OCR spend |

**Cost:** `cost = in_tok/1e6 * input_per_1m + out_tok/1e6 * output_per_1m`, prices read from `agents.yaml`. Attached to each `AgentMetric` and summed into `run_audit.total_cost_usd`.

**Traces:** one span per graph run, child span per agent, attributes `run_id, agent, model, tokens, cache_hit`. Console exporter locally; OTLP to an ADOT collector on AWS (stretch goal, not required).

**Grafana dashboard** — four rows:
1. Throughput and outcomes — runs/min, decision mix, error rate
2. Latency — p50/p95/p99 per agent, end-to-end
3. Tokens and cost — cost per agent, cost per run, input/output split
4. Quality and loops — validation failures by rule, repair success, healing loops, quality histogram

**Latency optimisation work items to demo on this dashboard:** parallelise graph traversal and vector search with `asyncio.gather`; cache OCR and embeddings; skip the LLM critique when every deterministic check passes; keep intake at temperature 0 so its responses are cacheable.

**Useful demo:** run all fourteen claim fixtures in sequence and show the dashboard. The decision mix, per-rule validation failures and heal-loop count all populate from one command, which makes a far better teaching visual than a single synthetic run.

---

## API With Streaming

```
POST /v1/claims/adjudicate     # multipart upload or {"s3_uri" | "path"} → SSE stream
GET  /v1/runs/{run_id}         # final result from run_audit
GET  /v1/runs/{run_id}/state   # latest checkpoint
POST /v1/runs/{run_id}/resume
GET  /v1/graph/subgraph        # teaching endpoint
GET  /healthz                  # liveness — no dependencies
GET  /readyz                   # readiness — DB, cache and secret reachable
GET  /metrics                  # Prometheus
```

Streaming uses `graph.astream_events(..., version="v2")` mapped to SSE:

```
event: node_start   data: {"agent":"ClaimIntakeAgent","ts":...}
event: node_end     data: {"agent":"ClaimIntakeAgent","latency_ms":842,"tokens":1204}
event: validation   data: {"is_valid":false,"errors":[{"field":"member_id","code":"MEMBER_ID_FORMAT"}]}
event: repair       data: {"attempt":1,"fields_fixed":["member_id","service_start_date"]}
event: token        data: {"agent":"PolicyAdjudicatorAgent","delta":"Step 2: "}
event: healing      data: {"attempt":1,"quality_score":0.62}
event: final        data: {"decision":{...},"cost_usd":0.0031,"degraded":false}
event: error        data: {"message":"..."}
```

Implementation notes: `StreamingResponse(media_type="text/event-stream")`, headers `Cache-Control: no-cache` and `X-Accel-Buffering: no`; emit a `: keepalive` comment every 15s so the ALB's 60-second idle timeout doesn't drop long runs; cancel the graph task on client disconnect. `scripts/stream_client.py` tests the stream without a browser.

---

## End-To-End Testing

`tests/e2e/test_full_workflow.py` **parametrises over `testdata/manifest.yaml`**, so every scenario in the matrix is an E2E case. Runs under `APP_ENV=local` with a deterministic `FakeChatModel` that returns scripted JSON keyed by the calling agent. No network, no OpenAI spend, CI-safe.

**Per-scenario assertions** (driven by the `.expected.json` files):
1. The graph completes and returns a terminal state.
2. The node visit order matches the expected path for that scenario.
3. `retry_count`, `heal_attempts`, `fallback_used` and `extraction_source` match expectations.
4. `decision.status` matches, `payable_amount` matches to the rupee.
5. `payable_amount == sum(per_line.payable)` and `<= claimed_amount`.
6. Every id in `citations[]` resolves inside `retrieved_context`, and the expected clause ids are present.
7. `metrics` has one entry per executed agent, each with non-zero latency and a computed `cost_usd`.

**Suite-level assertions** (run once, not per scenario):
8. `CLM-006` recovers via repair; `CLM-007` falls through to fallback; `CLM-012` heals exactly once — the three non-happy paths are all proven live.
9. Checkpoints were written (`len(list(checkpointer.list(config))) > 0`), and resuming `CLM-001` from a mid-run checkpoint reaches the same final decision.
10. `graph_runs_total` increments once per scenario in the Prometheus registry.
11. Submitting `CLM-001` twice makes the second run's OCR a cache hit with lower total cost.
12. `CLM-010` retrieves a prior decision from long-term memory after `CLM-001` has run.

**Supporting unit suites:** each validation rule against its named fixture; each noise function's matching few-shot example; retriever budget enforcement; cost arithmetic; SSE event ordering; `/readyz` failing when the DB is down.

**CI gate:** `ruff` + `mypy` (non-strict) + `pytest`, ≥70% coverage on `src/app/graph`, `src/app/validation` and `src/app/memory`, plus `python -m testdata.generate verify`.

---

## Docker And Kubernetes

**Dockerfile:** multi-stage (`python:3.12-slim` builder → slim runtime), non-root `appuser`, `PYTHONUNBUFFERED=1`, `HEALTHCHECK` on `/healthz`, `uvicorn --workers 2`. Target under 500 MB. Test fixtures are excluded via `.dockerignore` — except the Textract JSON needed by the seed job.

**Kubernetes objects:**
- `Deployment` — 2 replicas, requests `500m/1Gi`, limits `1000m/2Gi`, liveness `/healthz`, readiness `/readyz`, `preStop` sleep 5 for graceful drain.
- `ServiceAccount` with the IRSA annotation.
- `ConfigMap` holding `agents.yaml`, `tradeoff.yaml` and non-secret env — **generated from Terraform outputs** by `scripts/render_k8s_config.sh`, never hand-edited.
- Secrets: the app fetches from Secrets Manager at startup via IRSA (simplest). External Secrets Operator is the more realistic alternative — **pick one, don't build both**.
- `Service` (ClusterIP) + `Ingress` (AWS Load Balancer Controller, internet-facing ALB).
- `HPA` on CPU 70%, 2→5 replicas.
- `ServiceMonitor` for kube-prometheus-stack.
- `Job: db-migrate` — SQL migrations + `checkpointer.setup()`. `Job: seed-data` — runs the ingest pipeline over the generated policy PDFs. Both must complete before the Deployment rolls.

---

## Infrastructure As Code

### Terraform resources — no console, per your constraint

| Module | Creates |
|---|---|
| `bootstrap` | S3 state bucket + DynamoDB lock table (run once, separately) |
| `network` | VPC, 2 public + 2 private subnets, IGW, **single** NAT gateway, route tables |
| `s3` | Documents bucket — versioned, SSE, public access blocked |
| `ecr` | Repository with lifecycle policy (keep last 5 images) |
| `rds` | PostgreSQL 16, `db.t4g.micro`, private, `rds.force_ssl`, password in Secrets Manager |
| `elasticache` | Redis 7, `cache.t4g.micro`, single node, private subnet group |
| `eks` | Cluster + one managed node group (2 × `t3.medium`), OIDC provider, addons |
| `iam` | IRSA role for the app (Secrets Manager read, Textract, S3 read/write), ALB controller role |
| `secrets` | `openai-api-key` **shell only** — value injected out-of-band, never in `.tf` |
| `budget` | AWS Budget alert at $50 |

**Tag everything** `Project=claim-adjudication, Environment=learning, Owner=mani, ManagedBy=terraform` — the teardown verification depends on it.

### CI/CD workflows

- `ci.yml` — on PR: ruff, mypy, `testdata.generate verify`, pytest (local mode, fake LLM), docker build without push.
- `infra-deploy.yml` — `workflow_dispatch` and main: OIDC assume-role → terraform init/plan/apply → build/push → migrate → seed → deploy → smoke test. Gate `apply` behind a manual-approval environment.
- `infra-destroy.yml` — `workflow_dispatch` only, with a typed-confirmation input.

### Cost guardrails

EKS control plane (~$73/mo) + NAT gateway (~$35/mo) + RDS + ElastiCache + ALB is roughly **$150–200/month if left running**. For a learning project: one NAT gateway (or VPC endpoints for S3, Secrets Manager and ECR and no NAT at all), the $50 budget alert, and **destroy the same day you test**. `make destroy` should become muscle memory.

---

## Dependencies

```
langgraph, langchain-core, langchain-openai
langgraph-checkpoint-postgres, langgraph-checkpoint-sqlite
openai, tiktoken
fastapi, uvicorn[standard], sse-starlette, python-multipart
pydantic, pydantic-settings, pyyaml
psycopg[binary,pool], pgvector, sqlalchemy
networkx
boto3
redis                      # aws profile only — import lazily
pypdf, pdfplumber
reportlab                  # test data: renders claim and policy PDFs
faker                      # test data: synthetic names, addresses, IDs
prometheus-client, opentelemetry-sdk, opentelemetry-exporter-prometheus,
opentelemetry-instrumentation-fastapi
structlog
pytest, pytest-asyncio, pytest-cov, httpx, ruff, mypy
```

Pin versions in `pyproject.toml`. Three extras: `[local]`, `[aws]`, `[testdata]`.

---

## Delivery Phases

One phase per code-generation session. Each ends green before the next starts.

| Phase | Scope | Done when |
|---|---|---|
| **P0** Skeleton | repo layout, settings, agent config loader, llm_factory, logging, Makefile, docker-compose.local | `make run-local` serves `/healthz`; `get_llm("adjudicator_agent")` returns a model with the YAML temperature |
| **P1** Test data generator | `testdata/` package, manifest, seeds, policy + claim + pharmacy PDF builders, Textract synthetic builder, noise functions, prompt set, `verify` | `make fixtures` produces every artifact; `verify` passes; regeneration is byte-identical |
| **P2** ClaimIntakeAgent + ClaimValidatorAgent | OCR providers + parser, `ClaimRecord`, validation rules | Every clean fixture extracts correctly; every dirty fixture trips its named rule |
| **P3** Graph v1 | state.py, build_graph, `intake → validate → END`, SQLite checkpointer | Graph runs end to end on `CLM-001`; checkpoints written |
| **P4** FieldRepairAgent + HeuristicFallbackAgent | few-shot prompt, fallback, retry router | `CLM-006` recovers in one loop; `CLM-007` falls back; `CLM-014` is *not* repaired |
| **P5** RAG foundation | data_pipeline, pgvector DDL, embeddings, graph_builder, hybrid_retriever | Ingest of the generated policy PDFs populates chunks and graph; retriever returns triples with clause ids |
| **P6** PolicyAdjudicatorAgent | CoT prompt, adjudicate_node | `CLM-001` through `CLM-005` and `CLM-013` produce their expected decisions |
| **P7** DecisionAuditorAgent | deterministic checks + critique + heal loop | `CLM-012` triggers exactly one heal loop and improves |
| **P8** Tradeoff + cache | memory/policy, history windowing, long_term_memory, cache providers | `tradeoff_demo.py` prints three profiles; `CLM-010` gets a memory hit |
| **P9** Observability | otel_setup, metrics, cost, Grafana JSON, local Prometheus | Dashboard populates after running all fixtures |
| **P10** API | streaming endpoint, runs/resume, readyz, stream_client | SSE stream shows node and token events; resume works |
| **P11** Full test suite | conftest fake LLM, parametrised E2E, CI workflow | `pytest` green in CI with zero network calls |
| **P12** Containerise | Dockerfile, entrypoint, compose parity | Image runs the same suite inside the container |
| **P13** Terraform | all modules, bootstrap state, budget alert | `terraform plan` clean; apply succeeds in a throwaway region |
| **P14** Kubernetes + pipeline | manifests, migrate job, seed job, deploy workflow | Smoke test passes against the ALB URL |
| **P15** Textract capture + docs | `--mode capture` against real Textract, README, architecture diagram, teaching notes | Suite passes against captured fixtures; teardown leaves zero tagged resources |

**P0–P12 are entirely local and free. Only P13–P15 cost money.**

P1 sitting second is deliberate — without fixtures, every later phase has nothing to assert against, and you end up writing throwaway test data six times.

---

## Runbook — Running Locally

**Prerequisites:** Python 3.12+, Docker Desktop, an OpenAI API key, `make`. No AWS account needed.

### Step 1 — Clone and create the environment
```bash
git clone <your-repo-url> claim-adjudication-assist
cd claim-adjudication-assist

python3.12 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -e ".[local,testdata]"
```

### Step 2 — Configure environment variables
```bash
cp .env.example .env
```
Edit `.env`:
```ini
APP_ENV=local
LOG_LEVEL=INFO
OPENAI_API_KEY=sk-...                # local only — on AWS this comes from Secrets Manager
VECTOR_BACKEND=pgvector              # or "numpy" for a zero-Docker run
POSTGRES_DSN=postgresql://claims:claims@localhost:5432/claims
SQLITE_PATH=./.local/checkpoints.sqlite
USE_REDIS=false
USE_TEXTRACT=false
USE_S3=false
USE_SECRETS_MANAGER=false
DOCUMENTS_DIR=./data/documents
FIXTURE_DIR=./tests/fixtures/textract
```
Confirm `.env` and `.credentials` are in `.gitignore` before your first commit.

### Step 3 — Generate the test data
```bash
make fixtures
# equivalent to: python -m testdata.generate all && python -m testdata.generate verify
```
Produces the policy PDFs in `data/policies/`, all eighteen claim and pharmacy PDFs in `tests/fixtures/claims/`, the matching Textract JSON, the expected-outcome files, and the prompt set. Offline, free, deterministic. Inspect one:
```bash
open tests/fixtures/claims/CLM-006.pdf
cat  tests/fixtures/expected/CLM-006.expected.json | jq
```

### Step 4 — Start local infrastructure
```bash
docker compose -f docker-compose.local.yml up -d
docker compose -f docker-compose.local.yml ps
```
Three containers — **no Redis**:

| Container | Port | Purpose |
|---|---|---|
| `pgvector/pgvector:pg16` | 5432 | vector store + long-term memory |
| `prom/prometheus` | 9090 | scrapes `host.docker.internal:8000/metrics` |
| `grafana/grafana` | 3000 | dashboard, login `admin` / `admin` |

Skip this step entirely with `VECTOR_BACKEND=numpy` — the run then uses in-memory vectors and the SQLite checkpointer.

### Step 5 — Run database migrations
```bash
make migrate
# python scripts/run_migrations.py --env local
```
Creates `policy_chunks`, `policy_graph_edges`, `long_term_memory`, `run_audit`, and calls `SqliteSaver.setup()` for the checkpoint tables.

### Step 6 — Ingest policies and build the knowledge graph
```bash
make seed
# python -m pipelines.data_pipeline ingest --source ./data/policies/ --domain claims --rebuild-graph
# python -m pipelines.data_pipeline verify --domain claims
```
Expected output: chunk count, embedding count, graph node and edge counts, one sample similarity hit. This is the only local step that spends OpenAI credit — embeddings for three short policy PDFs, a few cents.

### Step 7 — Start the API
```bash
make run-local
# uvicorn app.main:app --reload --port 8000 --app-dir src
```
Verify:
```bash
curl localhost:8000/healthz     # {"status":"ok"}
curl localhost:8000/readyz      # checks Postgres, cache and secret provider
open http://localhost:8000/docs
```

### Step 8 — Submit a clean claim and watch the stream
```bash
curl -N -X POST http://localhost:8000/v1/claims/adjudicate \
  -F "file=@tests/fixtures/claims/CLM-001.pdf" \
  -H "Accept: text/event-stream"
```
Or with the helper client, which pretty-prints each event:
```bash
python scripts/stream_client.py --file tests/fixtures/claims/CLM-001.pdf
```
Expect `node_start` / `node_end` per agent by name, then a `final` event with the decision and cost.

### Step 9 — Drive the interesting paths
Each fixture exists to make one agent visibly do its job:
```bash
python scripts/stream_client.py --file tests/fixtures/claims/CLM-006.pdf   # repair loop
python scripts/stream_client.py --file tests/fixtures/claims/CLM-007.pdf   # fallback + human review
python scripts/stream_client.py --file tests/fixtures/claims/CLM-003.pdf   # exclusion → DENY
python scripts/stream_client.py --file tests/fixtures/claims/CLM-002.pdf   # sub-limit → PARTIAL
python scripts/stream_client.py --file tests/fixtures/claims/CLM-012.pdf   # healing loop
python scripts/stream_client.py --file tests/fixtures/claims/CLM-010.pdf   # duplicate → memory hit
```
Or run the whole matrix at once, which is what populates the dashboard:
```bash
make demo-all      # submits every fixture in sequence and prints a decision summary table
```

### Step 10 — Inspect a run
```bash
RUN_ID=<from the final event>
curl localhost:8000/v1/runs/$RUN_ID | jq
curl localhost:8000/v1/runs/$RUN_ID/state | jq '.reasoning_trace'
curl "localhost:8000/v1/graph/subgraph?codes=CPT-99213&hops=2" | jq
```

### Step 11 — Try the prompt set
```bash
cat tests/fixtures/prompts/claim_queries.yaml
python scripts/stream_client.py --ask "Why was claim CLM-003 denied?" --run-id $RUN_ID
```
The adversarial prompts at the end of that file are the ones worth demonstrating to a cohort — they show that grounding is something you build and verify, not something the model gives you.

### Step 12 — View metrics and the dashboard
```bash
curl localhost:8000/metrics | grep agent_cost_usd_total
```
Open Grafana at `http://localhost:3000` (`admin`/`admin`), add Prometheus at `http://prometheus:9090` as a data source, import `monitoring/grafana_dashboard.json`. Run `make demo-all` first so the panels have data.

### Step 13 — Run the tests
```bash
make test          # full suite, FakeChatModel — no network, no spend
make test-e2e      # parametrised end-to-end over the scenario manifest
make lint          # ruff + mypy
```

### Step 14 — Explore the tradeoff
```bash
python scripts/tradeoff_demo.py --file tests/fixtures/claims/CLM-005.pdf --profiles lean,balanced,generous
```
Prints context, history and memory token usage, total cost, latency and quality score per profile. `CLM-005` is the right fixture here — the co-pay calculation needs enough retrieved context to get right, so the `lean` profile visibly degrades.

### Step 15 — Change a model or temperature
Edit `config/agents.yaml`, or override without touching the file:
```bash
AGENT__ADJUDICATOR_AGENT__TEMPERATURE=0.4 make run-local
AGENT__ADJUDICATOR_AGENT__MODEL=gpt-4.1 make run-local
```

### Step 16 — Shut down
```bash
docker compose -f docker-compose.local.yml down          # keeps volumes
docker compose -f docker-compose.local.yml down -v       # wipes the database too
```

---

## Runbook — Deploying To AWS

**Prerequisites:** AWS CLI v2, Terraform ≥1.6, `kubectl`, `helm`, Docker, and an AWS account with permission to create VPC, EKS, RDS, ElastiCache and IAM resources.

> **Cost warning:** from Step 4 onward you are billed. Expect **$150–200/month if left running**. Plan to run the teardown step the same day.

### Step 1 — Configure AWS credentials
```bash
cp .credentials.example .credentials     # already gitignored
# fill in AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_REGION

export $(grep -v '^#' .credentials | xargs)
aws sts get-caller-identity              # confirm the right account
```

### Step 2 — Set deployment variables
```bash
export AWS_REGION=ap-south-1
export PROJECT=claim-adjudication
export CLUSTER_NAME=${PROJECT}-eks
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
```

### Step 3 — Bootstrap the Terraform state backend (one time only)
```bash
cd infra/terraform/bootstrap
terraform init
terraform apply -auto-approve            # S3 state bucket + DynamoDB lock table
cd ..
```

### Step 4 — Provision all AWS resources
```bash
terraform init -backend-config="bucket=${PROJECT}-tfstate-${ACCOUNT_ID}"
terraform plan  -var-file=envs/learning.tfvars -out=tfplan
terraform apply tfplan                   # ~20–25 minutes, mostly EKS and RDS
terraform output -json > ../../.tf-outputs.json
```
Creates the VPC, RDS Postgres, ElastiCache Redis, ECR, EKS cluster and node group, S3 bucket, IRSA roles, the Secrets Manager secret *shell*, and the budget alert.

**This satisfies the "no AWS portal" constraint** — every resource comes from Terraform, and the agent configuration in Step 8 is derived from these outputs rather than copied by hand.

### Step 5 — Inject the OpenAI key into Secrets Manager
The value never appears in `.tf` or `.env`:
```bash
aws secretsmanager put-secret-value \
  --secret-id ${PROJECT}/openai-api-key \
  --secret-string '{"OPENAI_API_KEY":"sk-..."}' \
  --region $AWS_REGION
```

### Step 6 — Build and push the container image
```bash
cd ../..                                  # back to repo root
ECR_URL=$(jq -r '.ecr_repository_url.value' .tf-outputs.json)

aws ecr get-login-password --region $AWS_REGION \
  | docker login --username AWS --password-stdin $ECR_URL

docker build -f docker/Dockerfile -t $ECR_URL:v1 .
docker push $ECR_URL:v1
```

### Step 7 — Connect kubectl and install cluster add-ons
```bash
aws eks update-kubeconfig --name $CLUSTER_NAME --region $AWS_REGION
kubectl get nodes                         # should list 2 Ready nodes

# AWS Load Balancer Controller — needed for the Ingress → ALB
helm repo add eks https://aws.github.io/eks-charts && helm repo update
helm install aws-load-balancer-controller eks/aws-load-balancer-controller \
  -n kube-system \
  --set clusterName=$CLUSTER_NAME \
  --set serviceAccount.create=false \
  --set serviceAccount.name=aws-load-balancer-controller

# Prometheus + Grafana
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install monitoring prometheus-community/kube-prometheus-stack \
  -n monitoring --create-namespace
```

### Step 8 — Generate Kubernetes config from Terraform outputs
```bash
./scripts/render_k8s_config.sh            # reads .tf-outputs.json → k8s/configmap.yaml
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/serviceaccount.yaml  # carries the IRSA role annotation
kubectl apply -f k8s/configmap.yaml
```
No endpoint is ever typed by hand — RDS host, Redis host, S3 bucket, secret name and region all flow from Terraform outputs into the ConfigMap.

### Step 9 — Run migrations (creates the checkpointer tables on RDS)
```bash
kubectl apply -f k8s/job-db-migrate.yaml
kubectl wait --for=condition=complete job/db-migrate -n $PROJECT --timeout=300s
kubectl logs job/db-migrate -n $PROJECT
```

### Step 10 — Upload generated data and seed pgvector
```bash
BUCKET=$(jq -r '.documents_bucket.value' .tf-outputs.json)
aws s3 cp ./data/policies/          s3://$BUCKET/policies/ --recursive
aws s3 cp ./tests/fixtures/claims/  s3://$BUCKET/claims/   --recursive

kubectl apply -f k8s/job-seed-data.yaml
kubectl wait --for=condition=complete job/seed-data -n $PROJECT --timeout=900s
kubectl logs job/seed-data -n $PROJECT    # chunk, embedding, node and edge counts
```

### Step 11 — Deploy the application
```bash
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/ingress.yaml
kubectl apply -f k8s/hpa.yaml
kubectl apply -f k8s/servicemonitor.yaml

kubectl rollout status deployment/claim-adjudication -n $PROJECT
kubectl get pods -n $PROJECT
```

### Step 12 — Smoke test through the ALB
```bash
ALB_URL=$(kubectl get ingress claim-adjudication -n $PROJECT \
  -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
echo "https://$ALB_URL"                   # DNS takes 2–3 minutes to resolve

curl https://$ALB_URL/healthz
curl https://$ALB_URL/readyz
./scripts/smoke_test.sh https://$ALB_URL  # uploads CLM-001 and asserts a final event
```
Stream a claim against the deployed service:
```bash
python scripts/stream_client.py --url https://$ALB_URL --file tests/fixtures/claims/CLM-006.pdf
```

### Step 13 — Capture real Textract fixtures (one time, optional but recommended)
Now that AWS exists, replace the synthetic OCR fixtures with real ones:
```bash
APP_ENV=aws python -m testdata.generate textract --mode capture --profile aws
make test                                 # same suite, real Textract block structure
```
Any test that passed on synthetic fixtures and fails here has found a genuine parser bug. Commit the captured fixtures — they cost a few cents once and never need regenerating.

### Step 14 — View the dashboard on the cluster
```bash
kubectl port-forward -n monitoring svc/monitoring-grafana 3000:80
kubectl get secret -n monitoring monitoring-grafana \
  -o jsonpath="{.data.admin-password}" | base64 -d
```
Import `monitoring/grafana_dashboard.json`, then run `make demo-all --url https://$ALB_URL` so the per-agent token, latency and cost panels populate with the full scenario matrix.

### Step 15 — Destroy everything
```bash
./scripts/destroy_all.sh
```
The script runs these in order — `terraform destroy` alone will hang or orphan resources without them:

1. `kubectl delete ingress` (removes the ALB, which Terraform does not own) and wait for it to disappear
2. Delete any `LoadBalancer`-type services; wait for the ELBs to go
3. Empty the S3 documents bucket, **including all versions and delete markers**
4. Delete all ECR images
5. Delete Secrets Manager secrets with `--force-delete-without-recovery` — otherwise the 7-to-30-day recovery window blocks recreating the same name
6. `terraform destroy -auto-approve`
7. Delete leftover CloudWatch log groups (`/aws/eks/...`, `/aws/rds/...`)
8. Verify:
```bash
aws resourcegroupstaggingapi get-resources \
  --tag-filters Key=Project,Value=claim-adjudication \
  --region $AWS_REGION
```
This must return an empty list. If it doesn't, the script prints what remains.

### Step 16 — The same thing via the pipeline, no local CLI
```
GitHub → Actions → "infra-deploy" → Run workflow
   → terraform apply (manual approval gate) → build & push → migrate → seed → deploy → smoke test

GitHub → Actions → "infra-destroy" → Run workflow → type "destroy" to confirm
```

### Makefile shortcuts

| Command | What it does |
|---|---|
| `make install` | venv + editable install with `[local,testdata]` extras |
| `make fixtures` | generate and verify all test data |
| `make up` / `make down` | local docker-compose |
| `make migrate` / `make seed` | local DB setup and policy ingest |
| `make run-local` | uvicorn with reload |
| `make demo-all` | submit every fixture, print a decision summary table |
| `make test` / `make test-e2e` / `make lint` | test and quality gates |
| `make docker-build` / `make docker-push` | image to ECR |
| `make tf-plan` / `make tf-apply` | Terraform |
| `make deploy` | Steps 6–12 in sequence |
| `make destroy` | `scripts/destroy_all.sh` |

---

## Non-Goals

Explicitly out of scope, so the code generator doesn't over-engineer:
- No fine-tuning, no multi-model routing, no agent-to-agent negotiation.
- No human-in-the-loop UI — `needs_human_review` is a flag on the output, nothing more.
- No real PHI or PII. All data synthetic and generated; state this in the README.
- No production auth beyond a static API-key header — document that OIDC/Cognito is the production answer.
- No multi-tenancy, no rate limiting beyond a simple in-process limiter.
- Each agent stays under ~150 lines. If one grows past that, extract a helper — don't add cleverness.

---

## Open Decisions

1. **AWS region** — `ap-south-1` (Mumbai) assumed. Verify Textract `AnalyzeDocument` FORMS/TABLES availability there; `us-east-1` is the safest fallback for full feature coverage.
2. **Local vector store default** — pgvector in Docker (recommended, matches production) or numpy in-memory (zero Docker)? The plan builds both, pgvector as default.
3. **Secrets injection on EKS** — direct boto3 fetch at startup via IRSA (assumed, simpler) or External Secrets Operator (more realistic)?
4. **CI identity** — GitHub OIDC role assumption (recommended, no long-lived keys) or the keys from `.credentials` as GitHub secrets?
5. **Terraform vs CDK** — the plan assumes Terraform. Your call if CDK suits the training audience better.
6. **Currency and locale in fixtures** — INR assumed throughout (₹, Indian numbering). Switch to USD if the cohort is international.
7. **Budget alert threshold** — $50 assumed. Confirm or change.

---

## Kickoff Prompt For The Claude VS Code Extension

Paste this once the plan is approved:

> You are implementing the project described in `DEVELOPMENT_PLAN.md` in the workspace root.
>
> Rules:
> 1. Implement **Phase P0 only**. Do not scaffold files belonging to later phases.
> 2. Follow the repository structure in the plan exactly — same paths, same file names.
> 3. Use the agent names from the Agent Roster exactly: `ClaimIntakeAgent`, `ClaimValidatorAgent`, `FieldRepairAgent`, `HeuristicFallbackAgent`, `PolicyAdjudicatorAgent`, `DecisionAuditorAgent`. Node functions are `intake_node`, `validate_node`, `repair_node`, `fallback_node`, `adjudicate_node`, `audit_node`.
> 4. Every cloud dependency goes behind a Protocol with a `local` and an `aws` implementation, selected by `APP_ENV`. Under `APP_ENV=local`, never import `boto3` or `redis` at module import time.
> 5. No node constructs an LLM directly — always `llm_factory.get_llm(agent_key)`, driven by `config/agents.yaml`.
> 6. Add type hints and docstrings. Keep each agent under 150 lines.
> 7. After generating, run `make lint && make test` and fix what breaks.
> 8. Finish with a short summary of the files created and what you need from me for P1 (the test data generator).

---

## Appendix — Constraint Traceability

| Your requirement | Agent / component | Chapter |
|---|---|---|
| Per-agent model and temperature | `config/agents.yaml`, `core/llm_factory.py` | Per-Agent Model Configuration |
| AWS Textract OCR extractor | **ClaimIntakeAgent** | Agent Specifications |
| Data validation agent | **ClaimValidatorAgent** | Agent Specifications |
| Few-shot prompting | **FieldRepairAgent** | Agent Specifications |
| Retry and fallback on validation failure | **FieldRepairAgent** + **HeuristicFallbackAgent** | Agent Specifications |
| Chain-of-thought prompting | **PolicyAdjudicatorAgent** | Agent Specifications |
| GraphRAG with networkx over sample PDFs | `rag/graph_store.py` | GraphRAG With Networkx |
| pgvector on AWS | `rag/pgvector_store.py`, RDS | Data Pipeline |
| Self-healing with LangGraph feedback loops | **DecisionAuditorAgent** | Agent Specifications |
| Data pipeline saving vectors to pgvector | `pipelines/data_pipeline.py` | Data Pipeline |
| Redis cache shared across agents | `cache/redis_cache.py`, local `memory_cache.py` | Caching |
| Prometheus + OpenTelemetry dashboard | `observability/`, `monitoring/` | Logging, Monitoring And Cost Analysis |
| Token usage analysis | `agent_tokens_total` | Logging, Monitoring And Cost Analysis |
| Latency optimisation | `agent_latency_seconds` + listed work items | Logging, Monitoring And Cost Analysis |
| Cost-performance per agent | `observability/cost.py` | Logging, Monitoring And Cost Analysis |
| End-to-end test for the workflow | `tests/e2e/test_full_workflow.py` | End-To-End Testing |
| Context vs history vs memory tradeoff | `memory/policy.py`, `config/tradeoff.yaml` | Context Versus History Versus Memory |
| Checkpointer table on AWS Postgres | `persistence/checkpointer.py` | Checkpointing |
| API key in a vault, not `.env` | AWS Secrets Manager + IRSA | Security And Secrets |
| Docker and Kubernetes files | `docker/`, `k8s/` | Docker And Kubernetes |
| Pipeline creates all resources, no console | `infra/terraform/`, `.github/workflows/` | Infrastructure As Code |
| Resource deletion script | `scripts/destroy_all.sh` | Runbook — Deploying To AWS |
| FastAPI with streaming response | `api/routes_adjudicate.py` | API With Streaming |
| Skip Redis and cloud locally | Runtime profiles | Runtime Profiles |
| **Test data for all use cases** | `testdata/` package | Test Data Generation |
| Simple agent logic for learning | Non-goals | Non-Goals |
