"""
Evaluation metrics for quantile regression models.
Calculates calibration metrics (quantile coverage), pinball loss, MAE, and MAPE.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import structlog

log = structlog.get_logger()


def calculate_pinball_loss(y_true: np.ndarray, y_pred: np.ndarray, alpha: float) -> float:
    """Calculate pinball (quantile) loss for a given quantile alpha."""
    diff = y_true - y_pred
    return float(np.mean(np.maximum(alpha * diff, (alpha - 1) * diff)))


def calculate_coverage(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Calculate the percentage of true values that are less than or equal to predictions."""
    return float(np.mean(y_true <= y_pred))


def calculate_mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Calculate Mean Absolute Percentage Error (MAPE), handling division by zero."""
    mask = y_true != 0.0
    if not np.any(mask):
        return 0.0
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])))


def calculate_mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Calculate Mean Absolute Error (MAE)."""
    return float(np.mean(np.abs(y_true - y_pred)))


def evaluate_predictions(
    y_true: pd.Series | np.ndarray,
    preds_df: pd.DataFrame,
) -> dict[str, Any]:
    """
    Evaluate prediction calibration and performance across P10, P50, and P90 quantiles.

    Parameters:
        y_true: Ground truth target series (demand_lift_24h).
        preds_df: DataFrame with predictions (p10_demand_lift, p50_demand_lift, p90_demand_lift).

    Returns:
        A dictionary containing computed evaluation metrics.
    """
    y_true_arr = np.asarray(y_true)

    results = {}

    # Check that required columns are in preds_df
    required_cols = ["p10_demand_lift", "p50_demand_lift", "p90_demand_lift"]
    for col in required_cols:
        if col not in preds_df.columns:
            log.warning("Missing prediction column for evaluation", column=col)
            # Create a fallback if missing to avoid KeyError
            preds_df[col] = 0.0

    # P10 Metrics
    p10_preds = preds_df["p10_demand_lift"].to_numpy()
    results["p10_pinball_loss"] = calculate_pinball_loss(y_true_arr, p10_preds, 0.10)
    results["p10_coverage"] = calculate_coverage(y_true_arr, p10_preds)

    # P50 Metrics
    p50_preds = preds_df["p50_demand_lift"].to_numpy()
    results["p50_pinball_loss"] = calculate_pinball_loss(y_true_arr, p50_preds, 0.50)
    results["p50_coverage"] = calculate_coverage(y_true_arr, p50_preds)
    results["p50_mae"] = calculate_mae(y_true_arr, p50_preds)
    results["p50_mape"] = calculate_mape(y_true_arr, p50_preds)

    # P90 Metrics
    p90_preds = preds_df["p90_demand_lift"].to_numpy()
    results["p90_pinball_loss"] = calculate_pinball_loss(y_true_arr, p90_preds, 0.90)
    results["p90_coverage"] = calculate_coverage(y_true_arr, p90_preds)

    # Prediction Interval Width (P90 - P10)
    interval_width = p90_preds - p10_preds
    results["mean_interval_width"] = float(np.mean(interval_width))
    results["median_interval_width"] = float(np.median(interval_width))

    # Log evaluation summary
    log.info(
        "Model evaluation completed",
        p10_coverage=f"{results['p10_coverage'] * 100:.1f}% (target: ~10%)",
        p50_coverage=f"{results['p50_coverage'] * 100:.1f}% (target: ~50%)",
        p90_coverage=f"{results['p90_coverage'] * 100:.1f}% (target: ~90%)",
        p50_mape=f"{results['p50_mape'] * 100:.2f}%",
        p50_mae=f"{results['p50_mae']:.4f}",
    )

    return results
