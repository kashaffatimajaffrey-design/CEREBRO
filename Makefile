.PHONY: help setup up down logs test test-backend typecheck lint fmt db-shell models datasets train-email train-anomaly clean

help:  ## Show this help
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n",$$1,$$2}'

setup: ## First-time setup: env files and secret generation
	@test -f backend/.env  || (cp backend/.env.example backend/.env   && echo "created backend/.env")
	@test -f frontend/.env || (cp frontend/.env.example frontend/.env && echo "created frontend/.env")
	@echo ""
	@echo "Add these to backend/.env:"
	@echo "  SECRET_KEY=$$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')"
	@echo "  TOKEN_ENCRYPTION_KEY=$$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')"
	@echo ""
	@echo "Then: make up"

up: ## Start the stack (PROFILE=llm to include Ollama)
	docker compose $(if $(PROFILE),--profile $(PROFILE),) up -d --build
	@echo "API   http://localhost:8000/docs"
	@echo "MinIO http://localhost:9001"
	@echo "Frontend: cd frontend && npm install && npm run dev"

down: ## Stop the stack
	docker compose down

logs: ## Tail API logs
	docker compose logs -f api

test: test-backend typecheck ## Run everything

test-backend: ## Backend test suite
	cd backend && python3 tests/test_forensics.py \
	 && python3 tests/test_anomaly.py \
	 && python3 tests/test_security.py \
	 && python3 tests/test_rag.py \
	 && python3 tests/test_queries.py

typecheck: ## Frontend type check
	cd frontend && npm run typecheck

lint: ## Lint the backend
	cd backend && ruff check services/ tests/ && mypy services/ --ignore-missing-imports

fmt: ## Auto-format the backend
	cd backend && ruff format services/ tests/ && ruff check --fix services/ tests/

db-shell: ## psql into the running database
	docker compose exec db psql -U $${POSTGRES_USER:-cerebro} -d $${POSTGRES_DB:-cerebro}

models: ## Pull the local Ollama model
	docker compose exec ollama ollama pull $${OLLAMA_MODEL:-qwen2.5:7b-instruct}

datasets: ## Download training data (SpamAssassin now; prints links for gated sets)
	cd backend && python3 scripts/fetch_datasets.py

train-email: ## Train + evaluate the phishing classifier on SpamAssassin
	cd backend && python3 scripts/train_email_classifier.py \
	 --phishing data/email/spam --benign data/email/ham \
	 --out models/email_classifier.joblib

train-anomaly: ## Fit + evaluate the anomaly detector (needs CIC-IDS2017 CSVs)
	cd backend && python3 scripts/train_anomaly.py \
	 --csv-dir data/network/cicids2017 --out models/anomaly_detector.joblib

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf backend/.pytest_cache backend/.mypy_cache backend/.ruff_cache frontend/dist frontend/node_modules
