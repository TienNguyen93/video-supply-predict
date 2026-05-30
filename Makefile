# ============================================================
# Makefile — serene-hypatia
# Run all commands from the repo root.
# Docker Compose lives in docker/ — all targets account for this.
# ============================================================

.PHONY: help up down build logs seed test test-unit test-integration lint fmt typecheck clean

COMPOSE = docker compose -f docker/docker-compose.yml
PYTHON  = python

# Default: show help
help:
	@echo ""
	@echo "  serene-hypatia — Short Video → Demand Signal"
	@echo ""
	@echo "  Infrastructure:"
	@echo "    make up              Start all Docker services"
	@echo "    make down            Stop and remove containers"
	@echo "    make build           Rebuild all images (no cache)"
	@echo "    make logs            Tail all container logs"
	@echo "    make logs-airflow    Tail Airflow scheduler logs"
	@echo ""
	@echo "  Data & Pipeline:"
	@echo "    make seed            Generate synthetic data + run dbt transforms"
	@echo "    make dbt-run         Run dbt models only"
	@echo "    make dbt-test        Run dbt tests only"
	@echo ""
	@echo "  Testing:"
	@echo "    make test            Run all tests (unit + integration)"
	@echo "    make test-unit       Run unit tests only (no Docker needed)"
	@echo "    make test-integration Run integration tests (needs Docker up)"
	@echo "    make cov             Run tests with HTML coverage report"
	@echo ""
	@echo "  Code Quality:"
	@echo "    make lint            Run ruff linter"
	@echo "    make fmt             Run ruff formatter"
	@echo "    make typecheck       Run mypy"
	@echo ""
	@echo "  Cleanup:"
	@echo "    make clean           Remove __pycache__, .coverage, build artifacts"
	@echo "    make clean-data      Remove local DuckDB + MLflow artifacts"
	@echo ""

# ------------------------------------------------------------------
# Infrastructure
# ------------------------------------------------------------------
up:
	@echo "→ Starting all services..."
	$(COMPOSE) up -d
	@echo "✓ Services up"
	@echo "  Airflow:   http://localhost:8080  (admin / admin)"
	@echo "  MLflow:    http://localhost:5000"
	@echo "  FastAPI:   http://localhost:8000"
	@echo "  Streamlit: http://localhost:8501"

down:
	$(COMPOSE) down

build:
	$(COMPOSE) build --no-cache

logs:
	$(COMPOSE) logs -f

logs-airflow:
	$(COMPOSE) logs -f airflow-scheduler

ps:
	$(COMPOSE) ps

# ------------------------------------------------------------------
# Data & Pipeline
# ------------------------------------------------------------------
seed:
	@echo "→ Creating data directory..."
	mkdir -p data
	@echo "→ Seeding synthetic data..."
	$(PYTHON) scripts/seed_historical_data.py
	@echo "→ Running dbt transforms..."
	$(MAKE) dbt-run
	@echo "✓ Seed complete"

dbt-run:
	$(COMPOSE) exec airflow-scheduler \
		dbt run --project-dir /opt/airflow/dbt --profiles-dir /opt/airflow/dbt

dbt-test:
	$(COMPOSE) exec airflow-scheduler \
		dbt test --project-dir /opt/airflow/dbt --profiles-dir /opt/airflow/dbt

# ------------------------------------------------------------------
# Testing
# ------------------------------------------------------------------
test: test-unit test-integration

test-unit:
	$(PYTHON) -m pytest tests/unit -v -m unit --tb=short

test-integration:
	$(PYTHON) -m pytest tests/integration -v -m integration --tb=short

cov:
	$(PYTHON) -m pytest tests/ --cov=src --cov-report=html --cov-report=term-missing
	@echo "→ Open htmlcov/index.html for the full report"

# ------------------------------------------------------------------
# Code Quality
# ------------------------------------------------------------------
lint:
	$(PYTHON) -m ruff check src/ tests/ dags/

fmt:
	$(PYTHON) -m ruff format src/ tests/ dags/
	$(PYTHON) -m ruff check --fix src/ tests/ dags/

typecheck:
	$(PYTHON) -m mypy src/

# ------------------------------------------------------------------
# Cleanup
# ------------------------------------------------------------------
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .coverage htmlcov/ .pytest_cache/ .ruff_cache/ .mypy_cache/
	rm -rf build/ dist/ *.egg-info/

clean-data:
	rm -rf data/ mlruns/ mlartifacts/
	@echo "⚠ Local DuckDB and MLflow artifacts removed"
