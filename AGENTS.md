# AGENTS.md — serene-hypatia

Conventions and guardrails for AI agents (Antigravity, Copilot, etc.) working in this codebase.

---

## Project Purpose

End-to-end pipeline: **viral short-video engagement → SKU demand lift prediction → agentic replenishment alerts**.

Stack: DuckDB · dbt · Apache Airflow · LightGBM (quantile P10/P50/P90) · MLflow · LangGraph (Groq) · FastAPI · Streamlit · Docker Compose.

---

## Directory Conventions

| Path | Purpose |
|---|---|
| `src/config.py` | **Single source of truth** for all settings. Always import `from src.config import settings` — never hardcode values. |
| `src/ingestion/` | Data generation + DuckDB writes. No ML logic here. |
| `src/features/` | Python-side feature computation that runs *before* dbt (e.g., velocity calculations on raw events). |
| `src/models/` | LightGBM training, scoring, evaluation, MLflow registry. No data loading here — receive DataFrames. |
| `src/agents/` | LangGraph nodes only. No business logic outside graph nodes. |
| `src/api/` | FastAPI routers. Thin — delegate to `src/models/` and `src/agents/`. |
| `src/dashboard/` | Streamlit app. Calls FastAPI — never calls models/agents directly. |
| `dags/` | Airflow DAGs. Call `src/` modules via PythonOperator. No logic in the DAG file itself. |
| `dbt/` | SQL transforms. Read from raw DuckDB tables, write to staging/intermediate/mart layers. |
| `configs/` | YAML files for model params, risk thresholds, logging. Load via `settings.model_params_path`. |
| `tests/unit/` | Fast, no I/O, no Docker. Use `pytest -m unit`. |
| `tests/integration/` | Requires Docker services up. Use `pytest -m integration`. |

---

## Code Conventions

- **Python 3.11+**. Use `from __future__ import annotations` on all new files.
- **Pydantic v2** for all data models (not v1 compat shims).
- **structlog** for logging — never use `print()` in production code.
- **Type hints required** on all function signatures.
- **Ruff** for linting and formatting (`make lint`). Max line length: 100.
- Imports: stdlib → third-party → first-party (`src.*`) — enforced by ruff isort.

---

## Key Design Decisions

- **No LLM for triage** — the triage node is pure conditional logic for speed and auditability.
- **Human-in-the-loop always** — the action agent drafts POs/alerts but never submits them autonomously.
- **P90 drives alerts** — risk tier is determined by the worst-case (P90) quantile, not median.
- **DuckDB is the warehouse** — no separate Postgres for data; Postgres only used by Airflow metadata (via SQLite in dev).
- **dbt transforms** run inside Airflow tasks via `dbt-duckdb` Python API — no separate dbt container.

---

## Running Locally

```bash
# Start all services
make up

# Seed synthetic data + run dbt
make seed

# Open Airflow UI
open http://localhost:8080     # user: admin / password: admin

# Open Streamlit dashboard
open http://localhost:8501

# Open MLflow
open http://localhost:5000
```

---

## Testing

```bash
make test              # all tests (unit + integration)
make test-unit         # fast unit tests only
make test-integration  # requires Docker services running
make lint              # ruff check + format check
```

---

## Environment Variables

Copy `.env.example` to `.env` and fill in:
- `GROQ_API_KEY` — required for LangGraph investigation + action agents (free at console.groq.com)
- `SLACK_WEBHOOK_URL` — optional; alerts appear in Streamlit queue without it

---

## Agent Guidance

- **Do not modify** `configs/risk_thresholds.yaml` thresholds without updating `tests/unit/test_risk_calculator.py`.
- **Do not add** business logic to DAG files — keep DAGs as thin orchestration glue.
- **Always run** `make lint` before committing.
- **Always add** a test when adding a new function to `src/models/` or `src/agents/`.
- When adding a new env var, add it to both `src/config.py` (as a `Settings` field) and `.env.example`.
