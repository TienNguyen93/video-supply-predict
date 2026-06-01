"""
Weekly Model Retraining DAG.
Trains new LightGBM quantile regression models and promotes the champion to Production.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

from src.config import settings
from src.models.registry import promote_latest_model_version
from src.models.train import train_models

default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "start_date": datetime(2024, 1, 1),
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


def task_retrain_models() -> None:
    """Wrapper task to run weekly model retraining."""
    train_models()
    print("Model retraining run completed.")


def task_promote_model() -> None:
    """Wrapper task to promote the latest model to Production in MLflow."""
    success = promote_latest_model_version(settings.mlflow_model_name)
    if success:
        print("Model version promoted successfully to Production.")
    else:
        print("Model promotion skipped or failed.")


with DAG(
    "weekly_model_retraining",
    default_args=default_args,
    description="Retrain LightGBM models and register in MLflow weekly",
    schedule_interval="0 3 * * 0",
    catchup=False,
) as dag:
    retrain_models = PythonOperator(
        task_id="retrain_models",
        python_callable=task_retrain_models,
    )

    promote_model = PythonOperator(
        task_id="promote_model",
        python_callable=task_promote_model,
    )

    retrain_models >> promote_model
