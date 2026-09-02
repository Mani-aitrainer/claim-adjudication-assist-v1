.PHONY: install fixtures up down run-local test test-e2e lint docker-build docker-test docker-run docker-push tf-plan tf-apply deploy destroy

install:
	python -m venv .venv
	. .venv/bin/activate; pip install --upgrade pip; pip install -e ".[local,testdata,dev]"

fixtures:
	python -m testdata.generate all
	python -m testdata.generate verify

up:
	docker compose -f docker-compose.local.yml up -d

down:
	docker compose -f docker-compose.local.yml down

migrate:
	python scripts/run_migrations.py --env local

seed:
	python -m pipelines.data_pipeline ingest --source ./data/policies/ --domain claims --rebuild-graph
	python -m pipelines.data_pipeline verify --domain claims

run-local:
	uvicorn app.main:app --reload --port 8000 --app-dir src

test:
	pytest

test-e2e:
	pytest tests/e2e -q

lint:
	ruff check src tests testdata pipelines scripts
	mypy src testdata pipelines scripts

docker-build:
	docker build -f docker/Dockerfile --target runtime -t claim-adjudication-assist:latest .

docker-test:
	docker build -f docker/Dockerfile --target test -t claim-adjudication-assist:test .
	docker run --rm claim-adjudication-assist:test

docker-run: docker-build
	docker run --rm -p 8000:8000 --env-file .env claim-adjudication-assist:latest

docker-push:
	@test -n "$(ECR_URL)" || (echo "usage: make docker-push ECR_URL=<account>.dkr.ecr.<region>.amazonaws.com/claim-adjudication" && exit 1)
	docker tag claim-adjudication-assist:latest $(ECR_URL):latest
	docker push $(ECR_URL):latest

tf-plan:
	cd infra/terraform && terraform plan -var-file=envs/learning.tfvars

tf-apply:
	cd infra/terraform && terraform apply -var-file=envs/learning.tfvars

# Steps 6-12 of Runbook — Deploying To AWS: build/push, migrate, seed, deploy, smoke test.
# Assumes `terraform apply` has already run and .tf-outputs.json exists.
deploy:
	./scripts/render_k8s_config.sh
	kubectl apply -f k8s/namespace.yaml
	kubectl apply -f k8s/serviceaccount.rendered.yaml
	kubectl apply -f k8s/configmap.yaml
	kubectl apply -f k8s/job-db-migrate.yaml
	kubectl wait --for=condition=complete job/db-migrate -n claim-adjudication --timeout=300s
	kubectl apply -f k8s/job-seed-data.yaml
	kubectl wait --for=condition=complete job/seed-data -n claim-adjudication --timeout=900s
	kubectl apply -f k8s/deployment.yaml
	kubectl apply -f k8s/service.yaml
	kubectl apply -f k8s/ingress.yaml
	kubectl apply -f k8s/hpa.yaml
	kubectl apply -f k8s/servicemonitor.yaml
	kubectl rollout status deployment/claim-adjudication -n claim-adjudication

destroy:
	./scripts/destroy_all.sh
