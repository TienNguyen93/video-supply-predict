# **Short Video → Product Demand Signal**  
## Viral engagement → SKU demand lift prediction → automated replenishment alerts

---

## What It Does

Viral product videos cause stockouts within hours — traditional inventory forecasting has no leading indicator from content performance. This system fixes that:

1. **Ingests** hourly video engagement snapshots (views, saves, shares, cart-adds) from a synthetic data generator that mimics TikTok/Instagram/YouTube signals.
2. **Transforms** raw events through a dbt pipeline in DuckDB into ML-ready features.
3. **Predicts** demand lift using three LightGBM quantile regressors (P10/P50/P90), tracked via MLflow.
4. **Triages** each prediction through a LangGraph agent pipeline:
   - **Triage** (deterministic): routes CRITICAL / WARNING / WATCH / NORMAL.
   - **Investigation** (Groq LLM): generates a plain-language explanation for ops managers.
   - **Action** (Groq LLM): drafts a purchase order or Slack alert for human review.
5. **Surfaces** everything in a Streamlit ops dashboard with a human-in-the-loop approval queue.

---

## Architecture

```
[Synthetic Data Gen] → [DuckDB + dbt] → [LightGBM Scorer] → [LangGraph Agent] → [Streamlit]
        ↑                                        ↑                    ↓
   Airflow DAG 1                          MLflow Registry       Slack Webhook
```

---

## Quick Start

### Prerequisites

- Docker Desktop ≥ 4.x with Compose V2
- Python 3.11+ (for local dev/testing)
- A free [Groq API key](https://console.groq.com) (required for LLM agents)

### 1. Clone & Configure

```bash
git clone <repo-url>
cd serene-hypatia
cp .env.example .env
# Edit .env — set GROQ_API_KEY at minimum
```

### 2. Start All Services

```bash
make up
```

| Service | URL | Credentials |
|---|---|---|
| Airflow | http://localhost:8080 | admin / admin |
| MLflow | http://localhost:5000 | — |
| FastAPI | http://localhost:8000 | — |
| FastAPI Docs | http://localhost:8000/docs | — |
| Streamlit | http://localhost:8501 | — |

### 3. Seed Synthetic Data

```bash
make seed
```

This generates 200 videos × 50 SKUs × 48 hourly snapshots and runs dbt transforms.

### 4. Trigger the Pipeline

In the Airflow UI, manually trigger `hourly_engagement_pipeline`. Watch alerts appear in the Streamlit dashboard within minutes.

---

## Stack

| Layer | Technology |
|---|---|
| Data / Pipeline | DuckDB, dbt-duckdb, Apache Airflow 2.x |
| ML | LightGBM (quantile), scikit-learn, MLflow, pandas/numpy |
| Agentic | LangGraph, Groq API (llama3-70b) |
| API | FastAPI, uvicorn |
| Dashboard | Streamlit, Plotly |
| Config | Pydantic BaseSettings |
| Infra | Docker Compose, GitHub Actions |
| Testing | pytest, pytest-cov |

---

## Project Structure

```
serene-hypatia/
├── src/                    # Python package — all application code
│   ├── ingestion/          # Synthetic data generators + DuckDB loader
│   ├── features/           # Python-side feature computation (pre-dbt)
│   ├── models/             # LightGBM train / score / evaluate / registry
│   ├── agents/             # LangGraph nodes: triage, investigation, action
│   ├── api/                # FastAPI app
│   ├── dashboard/          # Streamlit app
│   └── config.py           # Pydantic BaseSettings (single source of truth)
├── dbt/                    # SQL transforms (staging → intermediate → marts)
├── dags/                   # Airflow DAGs (3 DAGs: hourly, daily, weekly)
├── tests/                  # pytest: unit/ + integration/ + conftest.py
├── docker/                 # Dockerfiles + docker-compose.yml
├── configs/                # model_params.yaml, risk_thresholds.yaml, logging.yaml
├── scripts/                # Utility scripts
├── docs/decisions/         # Architecture Decision Records (ADRs)
├── .env.example            # Environment variable reference
├── Makefile                # Dev workflow targets
└── pyproject.toml          # Dependencies + tool config
```

---

## Development

```bash
# Run unit tests (no Docker needed)
make test-unit

# Lint + format
make lint
make fmt

# Type check
make typecheck

# Full test suite (requires Docker up)
make test
```

---

## Architecture Decisions

See [`docs/decisions/`](docs/decisions/) for ADRs covering:
- [001 — Why quantile regression](docs/decisions/001-quantile-regression.md)
- [002 — Why DuckDB over Postgres](docs/decisions/002-duckdb-over-postgres.md)
- [003 — Human-in-the-loop design](docs/decisions/003-human-in-the-loop-design.md)

---

## Contributing

1. Branch from `main`.
2. Run `make lint` and `make test-unit` before pushing.
3. Open a PR — GitHub Actions will run CI automatically.

---

## License

MIT
