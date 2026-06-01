"""
Training script for LightGBM quantile regression models.
Trains P10, P50, and P90 models, logs parameters and metrics to MLflow,
and registers a unified model wrapper.
"""

from __future__ import annotations

import pickle
from typing import Any

import duckdb
import lightgbm as lgb
import mlflow
import mlflow.pyfunc
import numpy as np
import pandas as pd
import requests
import structlog
import yaml
from sklearn.model_selection import train_test_split

from src.config import settings

log = structlog.get_logger()

# Local model save path for fallback loading
MODEL_SAVE_DIR = settings.project_root / "data" / "models"
MODEL_SAVE_PATH = MODEL_SAVE_DIR / "quantile_models.pkl"


class QuantileLGBMModel(mlflow.pyfunc.PythonModel):  # type: ignore[name-defined]
    """
    Unified MLflow pyfunc wrapper for three quantile models (P10, P50, P90).
    Allows running predictions for all three quantiles in a single inference call.
    """

    def __init__(self, models: dict[str, Any]) -> None:
        self.models = models

    def predict(self, context: Any, model_input: pd.DataFrame) -> pd.DataFrame:
        """
        Produce predictions for P10, P50, and P90 quantiles.
        Returns a DataFrame with columns: p10_demand_lift, p50_demand_lift, p90_demand_lift
        """
        preds = {}
        for q, model in self.models.items():
            preds[f"{q}_demand_lift"] = model.predict(model_input)
        return pd.DataFrame(preds)


def get_mlflow_tracking_uri() -> str:
    """
    Resolve MLflow tracking URI.
    If the remote MLflow server is unreachable (e.g. running locally without Docker),
    falls back to the local mlruns directory.
    """
    uri = settings.mlflow_tracking_uri
    try:
        # Check if remote server is reachable
        response = requests.get(uri, timeout=1.0)
        if response.status_code == 200:
            log.info("MLflow remote server reachable", uri=uri)
            return uri
    except Exception:
        pass

    local_path = settings.project_root / "mlruns"
    local_uri = f"file:///{local_path.as_posix()}"
    log.info("MLflow falling back to local filesystem", uri=local_uri)
    return local_uri


def pinball_loss(y_true: np.ndarray, y_pred: np.ndarray, alpha: float) -> float:
    """Calculate pinball (quantile) loss for a given alpha."""
    diff = y_true - y_pred
    return float(np.mean(np.maximum(alpha * diff, (alpha - 1) * diff)))


def train_models() -> dict[str, lgb.LGBMRegressor] | None:
    """
    Main training function.
    Reads model configuration, fetches historical data from DuckDB, trains P10/P50/P90 models,
    logs results to MLflow, and saves local copies.
    """
    # 1. Load configurations
    if not settings.model_params_path.exists():
        log.error(
            "Model parameters configuration file not found", path=str(settings.model_params_path)
        )
        return None

    with open(settings.model_params_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    feature_cols = config["feature_columns"]
    target_col = config["target_column"]
    base_params = config["base"]
    quantile_overrides = config["quantile_overrides"]
    early_stopping_rounds = config.get("early_stopping_rounds", 50)
    split_ratio = config.get("train_val_split", 0.8)

    # 2. Fetch data from DuckDB
    db_path = str(settings.duckdb_path)
    log.info("Loading training data from DuckDB", db_path=db_path)
    try:
        con = duckdb.connect(db_path)
        # We only train on records where demand_lift_24h (historical label) is present
        query = f"SELECT * FROM marts.mart_scored_videos WHERE {target_col} IS NOT NULL"
        df = con.execute(query).df()
        con.close()
    except Exception as e:
        log.error("Failed to load training data from DuckDB", error=str(e))
        return None

    if len(df) == 0:
        log.error("No historical training data found in marts.mart_scored_videos")
        return None

    log.info("Training data loaded", rows=len(df))

    # Pre-check feature columns exist
    missing_cols = [c for c in feature_cols if c not in df.columns]
    if missing_cols:
        log.error("Feature columns missing from mart table", missing=missing_cols)
        return None

    x = df[feature_cols]
    y = df[target_col]

    # Split into train/validation sets
    x_train, x_val, y_train, y_val = train_test_split(
        x, y, train_size=split_ratio, random_state=base_params.get("random_state", 42)
    )

    # 3. MLflow Setup
    tracking_uri = get_mlflow_tracking_uri()
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(settings.mlflow_experiment_name)

    trained_models = {}
    metrics = {}

    log.info("Starting model training for quantiles (P10, P50, P90)")

    # 4. Train each quantile estimator
    with mlflow.start_run() as run:
        # Log basic training parameters
        mlflow.log_params(base_params)
        mlflow.log_param("num_features", len(feature_cols))
        mlflow.log_param("train_size", len(x_train))
        mlflow.log_param("val_size", len(x_val))

        for q_name, override in quantile_overrides.items():
            log.info("Training quantile estimator", quantile=q_name, alpha=override["alpha"])

            # Merge base params with overrides
            params = {**base_params, **override}

            # Create LGBMRegressor
            model = lgb.LGBMRegressor(**params)

            # Fit with early stopping callback
            model.fit(
                x_train,
                y_train,
                eval_set=[(x_val, y_val)],
                callbacks=[
                    lgb.early_stopping(stopping_rounds=early_stopping_rounds, verbose=False)
                ],
            )

            # Evaluate model
            preds_val = model.predict(x_val)
            q_loss = pinball_loss(y_val.to_numpy(), preds_val, override["alpha"])

            # Log metrics for this quantile
            metrics[f"{q_name}_quantile_loss"] = q_loss
            mlflow.log_metric(f"{q_name}_quantile_loss", q_loss)

            if q_name == "p50":
                # Log median metrics
                mae = float(np.mean(np.abs(y_val.to_numpy() - preds_val)))
                # Prevent division by zero in MAPE
                val_nz = y_val.to_numpy()
                val_nz_mask = val_nz != 0
                if np.sum(val_nz_mask) > 0:
                    mape = float(
                        np.mean(
                            np.abs(
                                (val_nz[val_nz_mask] - preds_val[val_nz_mask]) / val_nz[val_nz_mask]
                            )
                        )
                    )
                else:
                    mape = 0.0
                metrics["p50_mae"] = mae
                metrics["p50_mape"] = mape
                mlflow.log_metric("p50_mae", mae)
                mlflow.log_metric("p50_mape", mape)

            trained_models[q_name] = model

        log.info("Training complete", metrics=metrics)

        # 5. Local Fallback Serialization
        # Save raw model estimators to local pkl file
        MODEL_SAVE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with open(MODEL_SAVE_PATH, "wb") as f:
                pickle.dump(trained_models, f)
            log.info("Trained models saved locally as fallback", path=str(MODEL_SAVE_PATH))
        except Exception as e:
            log.warning("Failed to save models locally", error=str(e))

        # 6. Log Wrapper model to MLflow
        wrapper_model = QuantileLGBMModel(trained_models)
        mlflow.pyfunc.log_model(
            artifact_path="model",
            python_model=wrapper_model,
            registered_model_name=settings.mlflow_model_name,
        )
        log.info(
            "Registered unified QuantileLGBMModel in MLflow",
            model_name=settings.mlflow_model_name,
            run_id=run.info.run_id,
        )

    return trained_models


if __name__ == "__main__":
    train_models()
