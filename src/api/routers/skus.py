"""
SKUs router.
Exposes endpoints to retrieve SKU-level risk metrics and inventory details.
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


class SKURiskResponse(BaseModel):
    sku_id: str
    sku_name: str
    category: str
    unit_price_usd: float
    baseline_daily_demand: float
    current_stock: int
    supplier_lead_time_days: int
    reorder_point: int
    days_of_cover: float
    is_below_reorder: bool
    inventory_risk_tier: str
    viral_sensitivity: float
    active_video_count: int
    max_view_count: int | None = 0
    max_engagement_score: float | None = 0.0
    avg_engagement_score: float | None = 0.0
    demand_pressure_proxy: float | None = 0.0
    has_viral_video: bool
    urgency_score: float
    p10_demand_lift: float | None = None
    p50_demand_lift: float | None = None
    p90_demand_lift: float | None = None
    ml_risk_tier: str | None = None
    projected_stockout_days: float | None = None
    latest_alert_id: str | None = None
    alert_status: str | None = None
    refreshed_at: str | None = None


@router.get("/skus/risk", response_model=list[SKURiskResponse])
def get_sku_risks(
    category: str | None = Query(default=None, description="Filter SKUs by product category"),
    ml_risk_tier: str | None = Query(default=None, description="Filter SKUs by ML risk tier"),
) -> list[dict]:
    """
    Retrieve SKU inventory positions and ML-predicted risk levels.
    """
    con = duckdb.connect(str(settings.duckdb_path))
    try:
        query = "SELECT * FROM marts.mart_sku_risk WHERE 1=1"
        params = []

        if category:
            query += " AND category = ?"
            params.append(category)

        if ml_risk_tier:
            query += " AND ml_risk_tier = ?"
            params.append(ml_risk_tier.upper())

        df = con.execute(query, params).df()
    except Exception as e:
        log.error("API: failed to query marts.mart_sku_risk", error=str(e))
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
