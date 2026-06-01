"""
Videos router.
Exposes endpoints to retrieve trending video analytics.
"""

from __future__ import annotations

import duckdb
import pandas as pd
import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.config import settings

log = structlog.get_logger(__name__)
router = APIRouter()


class TrendingVideoResponse(BaseModel):
    video_id: str
    platform: str
    creator_id: str
    creator_tier: str
    sku_ids_json: str
    total_views: int
    save_rate_pct: float
    share_rate_pct: float
    click_rate_pct: float
    cart_rate_pct: float
    engagement_score: float
    engagement_tier: str
    views_velocity_3h: float | None = 0.0
    views_acceleration: float | None = 0.0
    is_on_foryou: bool
    age_label: str
    hours_observed: int
    posted_at: str | None = None
    last_snapshot_at: str | None = None
    is_viral: bool
    p50_demand_lift: float | None = None
    p90_demand_lift: float | None = None
    risk_tier_predicted: str | None = None
    rank: int
    mart_refreshed_at: str | None = None


@router.get("/videos/trending", response_model=list[TrendingVideoResponse])
def get_trending_videos(
    limit: int = Query(default=50, ge=1, le=100, description="Number of trending videos to return"),
) -> list[dict]:
    """
    Retrieve top-trending videos sorted by engagement score.
    """
    con = duckdb.connect(str(settings.duckdb_path))
    try:
        query = "SELECT * FROM marts.mart_trending_videos LIMIT ?"
        df = con.execute(query, (limit,)).df()
    except Exception as e:
        log.error("API: failed to query marts.mart_trending_videos", error=str(e))
        con.close()
        raise HTTPException(status_code=500, detail=f"Database query failed: {e}") from e
    finally:
        con.close()

    if df.empty:
        return []

    # Format datetime columns as ISO string
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.strftime("%Y-%m-%dT%H:%M:%SZ").fillna("")

    # Replace NaNs/Nulls with None
    df = df.where(pd.notnull(df), None)

    return df.to_dict(orient="records")
