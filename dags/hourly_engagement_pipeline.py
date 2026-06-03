"""
Hourly Engagement Pipeline DAG.
Orchestrates: Ingestion Inbound → dbt Transform → Model Scoring → Agent Triage & Alerting.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator
from scripts.run_hourly_ingestion import ingest_next_hour

from src.agents.graph import run_pipeline_for_at_risk_skus
from src.models.score import main as run_scoring

default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "start_date": datetime(2024, 1, 1),
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


def task_ingest_engagement() -> None:
    """Wrapper task to run simulated hourly ingestion."""
    count = ingest_next_hour()
    print(f"Hourly simulation: Ingested {count} snapshots.")


def task_run_agentic_triage() -> None:
    """Wrapper task to run LangGraph triage/PO creation."""
    results = run_pipeline_for_at_risk_skus()
    print(f"Agentic triage completed. Handled {len(results)} at-risk SKUs.")


with DAG(
    "hourly_engagement_pipeline",
    default_args=default_args,
    description="Simulate hourly snapshots, transform features, score, and agent triage",
    schedule="@hourly",
    catchup=False,
) as dag:
    ingest_snapshots = PythonOperator(
        task_id="ingest_snapshots",
        python_callable=task_ingest_engagement,
    )

    # dbt transforms run via local CLI in Airflow Scheduler environment
    dbt_transforms = BashOperator(
        task_id="dbt_transforms",
        bash_command=("dbt run --project-dir /opt/airflow/dbt --profiles-dir /opt/airflow/dbt"),
    )

    run_scorer = PythonOperator(
        task_id="run_scorer",
        python_callable=run_scoring,
    )

    run_agents = PythonOperator(
        task_id="run_agents",
        python_callable=task_run_agentic_triage,
    )

    ingest_snapshots >> dbt_transforms >> run_scorer >> run_agents
