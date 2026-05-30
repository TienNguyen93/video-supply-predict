/*
  mart_sku_risk
  ─────────────
  Per-SKU risk dashboard table. One row per SKU.

  Purpose:
    - Primary data source for the Streamlit inventory risk panel
    - Feeds the LangGraph triage node (Phase 5) with pre-computed risk tiers
    - Prediction columns (P10/P50/P90) populated by Phase 4 scoring

  Updated by: `dbt run --select mart_sku_risk`
  Refresh cadence: Airflow DAG triggers on every new engagement batch
*/
{{ config(materialized='table', schema='marts') }}

SELECT
    -- ── Identity ─────────────────────────────────────────────────────
    i.sku_id,
    i.sku_name,
    i.category,

    -- ── Inventory position ────────────────────────────────────────────
    i.unit_price_usd,
    i.baseline_daily_demand,
    i.current_stock,
    i.supplier_lead_time_days,
    i.reorder_point,
    i.days_of_cover,
    i.is_below_reorder,

    -- ── Risk assessment ───────────────────────────────────────────────
    i.inventory_risk_tier,              -- based on days_of_cover vs lead_time
    i.viral_sensitivity,

    -- ── Social demand signal ──────────────────────────────────────────
    i.active_video_count,
    i.max_view_count,
    i.max_engagement_score,
    i.avg_engagement_score,
    i.demand_pressure_proxy,
    i.has_viral_video,
    i.urgency_score,                    -- inventory_risk × social_pressure

    -- ── ML predictions (Phase 4) ─────────────────────────────────────
    -- Risk tier is set by P90 (worst-case) quantile per ADR-001
    NULL::DOUBLE                        AS p10_demand_lift,
    NULL::DOUBLE                        AS p50_demand_lift,
    NULL::DOUBLE                        AS p90_demand_lift,
    NULL::VARCHAR                       AS ml_risk_tier,     -- CRITICAL/WARNING/WATCH/NORMAL
    NULL::DOUBLE                        AS projected_stockout_days,

    -- ── Alert state (Phase 5) ────────────────────────────────────────
    NULL::VARCHAR                       AS latest_alert_id,
    NULL::VARCHAR                       AS alert_status,     -- PENDING/APPROVED/DISMISSED

    -- ── Metadata ─────────────────────────────────────────────────────
    i.refreshed_at

FROM {{ ref('int_sku_inventory') }} i
