"""
Unit tests for the scoring and inference layer.
"""

from __future__ import annotations

import pandas as pd

from src.models.score import Scorer


def test_scorer_initialization():
    """Verify that Scorer initializes successfully (falling back if needed)."""
    scorer = Scorer()
    assert scorer.model is not None
    assert scorer.load_type in ["mlflow", "local_pickle", "rule_based_fallback"]


def test_scorer_predict_shape():
    """Verify that predict returns correct shape and columns."""
    scorer = Scorer()

    # Create sample feature input
    x = pd.DataFrame(
        {
            "engagement_score": [0.01, 0.05, 0.15, 0.30],
            "sku_viral_sensitivity": [1.0, 1.5, 2.0, 2.5],
            "is_on_foryou": [0, 0, 1, 1],
            "hours_since_post": [12, 24, 36, 48],
            "save_velocity": [0.002, 0.005, 0.012, 0.025],
            "share_rate": [0.001, 0.003, 0.008, 0.015],
            "cart_rate": [0.0005, 0.001, 0.003, 0.006],
            "like_rate": [0.005, 0.012, 0.028, 0.045],
            "click_rate": [0.002, 0.004, 0.010, 0.018],
            "views_delta_1h": [120, 350, 1200, 2800],
            "saves_delta_1h": [4, 15, 65, 180],
            "shares_delta_1h": [2, 8, 35, 95],
            "has_link_in_bio": [1, 1, 1, 1],
            "video_duration_s": [15, 30, 45, 60],
            "creator_tier_encoded": [1, 2, 3, 4],
            "platform_encoded": [0, 1, 2, 0],
        }
    )

    preds = scorer.predict(x)

    assert isinstance(preds, pd.DataFrame)
    assert len(preds) == 4
    for quantile in ["p10", "p50", "p90"]:
        col = f"{quantile}_demand_lift"
        assert col in preds.columns
        assert not preds[col].isna().any()
        assert (preds[col] >= 0).all()


def test_scorer_predict_empty():
    """Verify that predict handles empty input DataFrame gracefully."""
    scorer = Scorer()
    preds = scorer.predict(pd.DataFrame())
    assert preds.empty
    assert list(preds.columns) == ["p10_demand_lift", "p50_demand_lift", "p90_demand_lift"]


def test_quantile_monotonicity():
    """Verify that P10 <= P50 <= P90 predictions for the same inputs."""
    scorer = Scorer()
    x = pd.DataFrame(
        {
            "engagement_score": [0.01, 0.10, 0.25],
            "sku_viral_sensitivity": [1.0, 2.0, 3.0],
            "is_on_foryou": [0, 1, 1],
            "hours_since_post": [12, 24, 36],
            "save_velocity": [0.001, 0.005, 0.020],
            "share_rate": [0.001, 0.005, 0.020],
            "cart_rate": [0.001, 0.005, 0.020],
            "like_rate": [0.001, 0.005, 0.020],
            "click_rate": [0.001, 0.005, 0.020],
            "views_delta_1h": [100, 500, 1000],
            "saves_delta_1h": [5, 25, 50],
            "shares_delta_1h": [5, 25, 50],
            "has_link_in_bio": [1, 1, 1],
            "video_duration_s": [30, 30, 30],
            "creator_tier_encoded": [2, 2, 2],
            "platform_encoded": [0, 0, 0],
        }
    )

    preds = scorer.predict(x)
    p10 = preds["p10_demand_lift"].to_numpy()
    p50 = preds["p50_demand_lift"].to_numpy()
    p90 = preds["p90_demand_lift"].to_numpy()

    assert (p10 <= p50).all()
    assert (p50 <= p90).all()
