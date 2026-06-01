"""
Alerts router.
Provides endpoints to list, approve, and reject/dismiss agent replenishment alerts.
"""

from __future__ import annotations

from datetime import datetime

import duckdb
import pandas as pd
import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.config import settings

log = structlog.get_logger(__name__)
router = APIRouter()


class AlertResponse(BaseModel):
    alert_id: str
    sku_id: str
    sku_name: str | None = None
    category: str | None = None
    unit_price_usd: float | None = 0.0
    days_of_cover: float | None = 0.0
    inventory_risk_tier: str | None = None
    current_stock: int | None = 0
    supplier_lead_time_days: int | None = 0
    active_video_count: int | None = 0
    has_viral_video: bool | None = False
    alert_risk_tier: str
    p10_demand_lift: float | None = None
    p50_demand_lift: float | None = None
    p90_demand_lift: float | None = None
    investigation_summary: str | None = None
    action_draft: str | None = None
    status: str
    approved_at: str | None = None
    approved_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@router.get("/alerts", response_model=list[AlertResponse])
def list_alerts(
    status: str | None = Query(
        default=None, description="Filter by status (PENDING, APPROVED, DISMISSED)"
    ),
    risk_tier: str | None = Query(
        default=None, description="Filter by alert risk tier (CRITICAL, WARNING, WATCH)"
    ),
) -> list[dict]:
    """
    Fetch all replenishment alerts from marts.mart_alert_queue.
    Supports filtering by status and risk_tier.
    """
    con = duckdb.connect(str(settings.duckdb_path))
    try:
        query = "SELECT * FROM marts.mart_alert_queue WHERE 1=1"
        params = []

        if status:
            query += " AND status = ?"
            params.append(status.upper())

        if risk_tier:
            query += " AND alert_risk_tier = ?"
            params.append(risk_tier.upper())

        df = con.execute(query, params).df()
    except Exception as e:
        log.error("API: failed to query marts.mart_alert_queue", error=str(e))
        con.close()
        raise HTTPException(status_code=500, detail=f"Database query failed: {e}") from e
    finally:
        con.close()

    # Graceful dataframe to JSON conversion
    if df.empty:
        return []

    # Format datetimes/Timestamps as ISO strings
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.strftime("%Y-%m-%dT%H:%M:%SZ").fillna("")

    # Replace NaNs/Nulls with None for JSON compliance
    df = df.where(pd.notnull(df), None)

    return df.to_dict(orient="records")


@router.post("/alerts/{alert_id}/approve")
def approve_alert(alert_id: str, approved_by: str = "ops_manager") -> dict[str, str]:
    """
    Approve a pending alert. Updates status to APPROVED.
    """
    con = duckdb.connect(str(settings.duckdb_path))
    try:
        # Check if alert exists
        alert = con.execute(
            "SELECT status FROM raw.agent_alerts WHERE alert_id = ?", (alert_id,)
        ).fetchone()
        if not alert:
            raise HTTPException(status_code=404, detail="Alert not found")

        if alert[0] != "PENDING":
            raise HTTPException(
                status_code=400,
                detail=f"Only PENDING alerts can be approved. Current status: {alert[0]}",
            )

        now = datetime.utcnow()
        con.execute(
            """
            UPDATE raw.agent_alerts
            SET status = 'APPROVED',
                approved_at = ?,
                approved_by = ?,
                updated_at = ?
            WHERE alert_id = ?
            """,
            (now, approved_by, now, alert_id),
        )
        log.info("API: approved alert", alert_id=alert_id, approved_by=approved_by)
        return {"status": "success", "message": f"Alert {alert_id} approved successfully."}
    except HTTPException:
        raise
    except Exception as e:
        log.error("API: failed to approve alert", alert_id=alert_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to approve alert: {e}") from e
    finally:
        con.close()


@router.post("/alerts/{alert_id}/reject")
@router.post("/alerts/{alert_id}/dismiss")
def reject_alert(alert_id: str) -> dict[str, str]:
    """
    Reject/dismiss a pending alert. Updates status to DISMISSED.
    """
    con = duckdb.connect(str(settings.duckdb_path))
    try:
        # Check if alert exists
        alert = con.execute(
            "SELECT status FROM raw.agent_alerts WHERE alert_id = ?", (alert_id,)
        ).fetchone()
        if not alert:
            raise HTTPException(status_code=404, detail="Alert not found")

        if alert[0] != "PENDING":
            raise HTTPException(
                status_code=400,
                detail=f"Only PENDING alerts can be rejected. Current status: {alert[0]}",
            )

        now = datetime.utcnow()
        con.execute(
            """
            UPDATE raw.agent_alerts
            SET status = 'DISMISSED',
                updated_at = ?
            WHERE alert_id = ?
            """,
            (now, alert_id),
        )
        log.info("API: rejected alert", alert_id=alert_id)
        return {"status": "success", "message": f"Alert {alert_id} dismissed successfully."}
    except HTTPException:
        raise
    except Exception as e:
        log.error("API: failed to reject alert", alert_id=alert_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to reject alert: {e}") from e
    finally:
        con.close()
