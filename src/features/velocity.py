"""
Python-side velocity and engagement rate feature computation.

Runs *before* dbt on freshly ingested raw events. The output is written back
to DuckDB so dbt staging models can pick it up cleanly.

Why here instead of dbt?
  - Rolling window calculations (e.g., 3h velocity) require stateful iteration
    that is awkward in SQL but trivial in pandas.
  - dbt handles the denormalisation and join logic; Python handles the maths.

Functions exported:
  - compute_velocity_features(df)   : adds rolling velocity columns in-place
  - compute_engagement_rates(df)    : recalculates clean rates from deltas
  - enrich_events_dataframe(df)     : convenience wrapper calling both
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import structlog

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Velocity features
# ---------------------------------------------------------------------------


def compute_velocity_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add rolling velocity columns to an engagement events DataFrame.

    Expects columns: video_id, hours_since_post, views_delta_1h,
    saves_delta_1h, shares_delta_1h.

    Adds:
      - views_velocity_3h  : sum of views_delta_1h over last 3 hours
      - saves_velocity_3h  : sum of saves_delta_1h over last 3 hours
      - shares_velocity_3h : sum of shares_delta_1h over last 3 hours
      - views_acceleration : views_delta_1h - lag_1(views_delta_1h) per video
      - engagement_score   : composite score = save_rate * 2 + share_rate * 3 + click_rate * 5

    Args:
        df: DataFrame with raw engagement events, sorted by (video_id, hours_since_post).

    Returns:
        DataFrame with new columns appended.
    """
    required_cols = {
        "video_id", "hours_since_post",
        "views_delta_1h", "saves_delta_1h", "shares_delta_1h",
        "save_rate", "share_rate", "click_rate",
    }
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"compute_velocity_features: missing columns {missing}")

    df = df.copy()
    df = df.sort_values(["video_id", "hours_since_post"]).reset_index(drop=True)

    # --------------- Rolling 3-hour windows (grouped by video) ---------------
    for col, out in [
        ("views_delta_1h",  "views_velocity_3h"),
        ("saves_delta_1h",  "saves_velocity_3h"),
        ("shares_delta_1h", "shares_velocity_3h"),
    ]:
        df[out] = (
            df.groupby("video_id")[col]
            .transform(lambda x: x.rolling(window=3, min_periods=1).sum())
            .fillna(0)
            .astype(int)
        )

    # --------------- Acceleration (first-order difference of hourly views) ---
    df["views_acceleration"] = (
        df.groupby("video_id")["views_delta_1h"]
        .transform(lambda x: x.diff().fillna(0))
        .astype(int)
    )

    # --------------- Composite engagement score ------------------------------
    df["engagement_score"] = (
        df["save_rate"] * 2.0
        + df["share_rate"] * 3.0
        + df["click_rate"] * 5.0
    ).round(6)

    log.debug(
        "Velocity features computed",
        n_rows=len(df),
        n_videos=df["video_id"].nunique(),
    )
    return df


# ---------------------------------------------------------------------------
# Engagement rate cleaning
# ---------------------------------------------------------------------------


def compute_engagement_rates(df: pd.DataFrame) -> pd.DataFrame:
    """
    Recompute clean engagement rates from cumulative counts and view_count.

    Protects against division-by-zero and clips rates to [0, 1].
    Overwrites existing rate columns if present.

    Args:
        df: DataFrame with view_count, like_count, save_count, share_count,
            click_to_product, add_to_cart columns.

    Returns:
        DataFrame with refreshed rate columns.
    """
    required = {"view_count", "like_count", "save_count", "share_count", "click_to_product", "add_to_cart"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"compute_engagement_rates: missing columns {missing}")

    df = df.copy()

    safe_views = df["view_count"].replace(0, np.nan)

    df["like_rate"] = (df["like_count"] / safe_views).clip(0, 1).fillna(0).round(6)
    df["save_rate"] = (df["save_count"] / safe_views).clip(0, 1).fillna(0).round(6)
    df["share_rate"] = (df["share_count"] / safe_views).clip(0, 1).fillna(0).round(6)
    df["click_rate"] = (df["click_to_product"] / safe_views).clip(0, 1).fillna(0).round(6)
    df["cart_rate"] = (df["add_to_cart"] / safe_views).clip(0, 1).fillna(0).round(6)

    return df


# ---------------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------------


def enrich_events_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Full enrichment pipeline:
      1. Recompute engagement rates from raw counts.
      2. Compute velocity features.

    Args:
        df: Raw engagement events DataFrame (from raw.engagement_events).

    Returns:
        Enriched DataFrame ready for dbt staging.
    """
    df = compute_engagement_rates(df)
    df = compute_velocity_features(df)

    log.info(
        "Events enriched",
        total_rows=len(df),
        viral_rows=int(df["is_viral"].sum()) if "is_viral" in df.columns else "unknown",
    )
    return df
