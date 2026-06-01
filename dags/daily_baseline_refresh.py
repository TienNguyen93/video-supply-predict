"""
Daily Baseline Refresh DAG.
Simulates daily sales depletion and baseline demand variation in DuckDB.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import duckdb
from airflow import DAG
from airflow.operators.python import PythonOperator

from src.config import settings


def task_refresh_baselines() -> None:
    """Wrapper task to run daily inventory depletion and variation."""
    db_path = str(settings.duckdb_path)
    con = duckdb.connect(db_path)
    try:
        # 1. Simulate daily sales: deplete stock by baseline daily demand
        con.execute(
            "UPDATE raw.sku_catalog "
            "SET current_stock = GREATEST(0, current_stock - "
            "CAST(baseline_daily_demand AS INTEGER))"
        )
        # 2. Daily demand drift: introduce slight +/- 5% variation
        con.execute(
            "UPDATE raw.sku_catalog "
            "SET baseline_daily_demand = ROUND(baseline_daily_demand * "
            "(0.95 + 0.10 * random()), 1)"
        )
        print("Daily baseline and stock refresh complete.")
    finally:
        con.close()


default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "start_date": datetime(2024, 1, 1),
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    "daily_baseline_refresh",
    default_args=default_args,
    description="Deplete current stock and vary baseline demand daily",
    schedule_interval="0 2 * * *",
    catchup=False,
) as dag:
    refresh_baselines = PythonOperator(
        task_id="refresh_baselines",
        python_callable=task_refresh_baselines,
    )
