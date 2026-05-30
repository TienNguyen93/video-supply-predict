/*
  mart_alert_queue
  ────────────────
  View over raw.agent_alerts — the human-review queue for the Streamlit
  "Action Required" panel.

  IMPORTANT: dbt does NOT own writes to this table.
  The LangGraph action agent (Phase 5) INSERTs rows into raw.agent_alerts
  via FastAPI. This model is a VIEW so dbt can rebuild it without
  destroying alert data.

  raw.agent_alerts is created by DuckDBLoader.initialise_schema() and
  is idempotent via CREATE TABLE IF NOT EXISTS.
*/
{{ config(materialized='view', schema='marts') }}

WITH alerts AS (
    SELECT * FROM {{ source('raw', 'agent_alerts') }}
),

enriched AS (
    SELECT
        a.alert_id,
        a.sku_id,

        -- SKU context (joined from risk mart)
        r.sku_name,
        r.category,
        r.unit_price_usd,
        r.days_of_cover,
        r.inventory_risk_tier,
        r.current_stock,
        r.supplier_lead_time_days,
        r.active_video_count,
        r.has_viral_video,

        -- Alert details
        a.risk_tier                                 AS alert_risk_tier,
        a.p90_demand_lift,
        a.p50_demand_lift,
        a.p10_demand_lift,

        -- Agent outputs
        a.investigation_summary,
        a.action_draft,

        -- Human review state
        a.status,                                   -- PENDING / APPROVED / DISMISSED
        a.approved_at,
        a.approved_by,

        -- Urgency for queue ordering
        CASE a.risk_tier
            WHEN 'CRITICAL' THEN 1
            WHEN 'WARNING'  THEN 2
            WHEN 'WATCH'    THEN 3
            ELSE                 4
        END                                         AS sort_order,

        a.created_at,
        a.updated_at

    FROM alerts a
    LEFT JOIN {{ ref('mart_sku_risk') }} r ON a.sku_id = r.sku_id
)

SELECT * FROM enriched
ORDER BY sort_order ASC, created_at DESC
