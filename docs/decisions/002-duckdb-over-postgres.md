# ADR 002 — DuckDB as the Analytical Warehouse

**Date**: 2024-06  
**Status**: Accepted

---

## Context

We need an analytical warehouse that:
1. Supports dbt for SQL-based transformations.
2. Is fast enough for ad-hoc feature queries during model training and scoring.
3. Is simple to run in Docker without a separate database server process.
4. Handles a dataset of ~200 videos × 48 hourly snapshots × 50 SKUs = ~480,000 rows initially, scaling to millions over time.

## Decision

Use **DuckDB** as the analytical warehouse, mounted as a single file on a Docker volume shared between the Airflow, FastAPI, and Streamlit containers.

Reasons:
- **No server process**: DuckDB is embedded. No need for a separate Postgres/ClickHouse container for analytics.
- **dbt-duckdb**: First-class dbt adapter. Runs dbt models as DuckDB SQL — fast and schema-consistent.
- **Columnar performance**: Sub-second queries on millions of rows without indexing.
- **Portability**: The entire warehouse is one `.duckdb` file — easy to snapshot, backup, and share.
- **Python-native**: Direct pandas ↔ DuckDB integration without JDBC/ODBC overhead.

## Alternatives Considered

- **PostgreSQL**: Excellent for transactional data (Airflow metadata uses it in prod). Not optimal for analytical column scans. Adding it as an analytics store would add a second DB to maintain.
- **ClickHouse**: Excellent columnar performance, but heavyweight for a demo/MVP. No official dbt adapter as robust as dbt-duckdb.
- **SQLite**: Row-oriented, no analytical functions. Rejected.
- **Parquet files + DuckDB queries**: Viable, but dbt requires a persistent connection target. DuckDB file is simpler.

## Consequences

- **Concurrent writes**: DuckDB supports one writer at a time. Airflow tasks that write to DuckDB must not run in parallel. DAG tasks are serialized where needed via `max_active_tasks=1` on write tasks.
- **Scale ceiling**: DuckDB is suitable up to ~100 GB on a single node. Above this, migrate to ClickHouse or BigQuery. Not a concern for MVP.
- **Airflow metadata**: Uses SQLite (`airflow.db`) in development. Production deployment should switch to Postgres via `AIRFLOW__DATABASE__SQL_ALCHEMY_CONN`.
