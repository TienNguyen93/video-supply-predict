/*
  int_sku_inventory
  ─────────────────
  Intermediate table — enriched SKU inventory with demand signal context.

  Joins the SKU catalog with engagement data to add:
    - how many active videos are currently tagging this SKU
    - the maximum engagement score across those videos (proxy for demand pressure)
    - estimated viral demand multiplier (max of latest engagement-based lift proxy)

  This table feeds mart_sku_risk which the Streamlit dashboard reads.
  The ML-predicted demand lifts (P10/P50/P90) are added by the scoring
  pipeline in Phase 4 and written to raw.sku_predictions; this model
  reads those if they exist.
*/
{{ config(materialized='table', schema='intermediate') }}

WITH sku AS (
    SELECT * FROM {{ ref('stg_sku_catalog') }}
),

-- Latest snapshot per video (hours_since_post = max available)
latest_events AS (
    SELECT *
    FROM (
        SELECT
            *,
            ROW_NUMBER() OVER (
                PARTITION BY video_id
                ORDER BY hours_since_post DESC
            ) AS _rn
        FROM {{ ref('int_engagement_features') }}
    )
    WHERE _rn = 1
),

-- Per-SKU demand signal aggregated from active videos
sku_demand_signal AS (
    SELECT
        vsb.sku_id,
        COUNT(DISTINCT vsb.video_id)                AS active_video_count,
        MAX(le.view_count)                          AS max_view_count,
        MAX(le.engagement_score)                    AS max_engagement_score,
        AVG(le.engagement_score)                    AS avg_engagement_score,
        -- Proxy for expected demand lift (before ML scoring)
        -- Uses: engagement_score * sku_viral_sensitivity / normalisation_constant
        MAX(
            le.engagement_score
            * le.sku_viral_sensitivity
            / 0.20   -- normalisation: score of 0.20 ≈ 1x lift baseline
        )                                           AS demand_pressure_proxy,
        BOOL_OR(le.is_viral)                        AS has_viral_video
    FROM {{ source('raw', 'video_sku_bridge') }}    vsb
    INNER JOIN latest_events le ON vsb.video_id = le.video_id
    GROUP BY vsb.sku_id
)

SELECT
    -- ── SKU catalog fields ────────────────────────────────────────────
    s.sku_id,
    s.sku_name,
    s.category,
    s.unit_price_usd,
    s.baseline_daily_demand,
    s.current_stock,
    s.supplier_lead_time_days,
    s.reorder_point,
    s.viral_sensitivity,
    s.days_of_cover,
    s.inventory_risk_tier,
    s.is_below_reorder,

    -- ── Social demand signal ──────────────────────────────────────────
    COALESCE(ds.active_video_count,    0)           AS active_video_count,
    COALESCE(ds.max_view_count,        0)           AS max_view_count,
    COALESCE(ds.max_engagement_score,  0.0)         AS max_engagement_score,
    COALESCE(ds.avg_engagement_score,  0.0)         AS avg_engagement_score,
    COALESCE(ds.demand_pressure_proxy, 0.0)         AS demand_pressure_proxy,
    COALESCE(ds.has_viral_video,       FALSE)       AS has_viral_video,

    -- ── Urgency composite ─────────────────────────────────────────────
    -- Combines inventory risk with social signal intensity
    -- Higher = more urgent to investigate
    ROUND(
        CASE s.inventory_risk_tier
            WHEN 'CRITICAL' THEN 4.0
            WHEN 'WARNING'  THEN 3.0
            WHEN 'WATCH'    THEN 2.0
            ELSE                 1.0
        END
        * (1.0 + COALESCE(ds.demand_pressure_proxy, 0.0)),
    3)                                              AS urgency_score,

    CURRENT_TIMESTAMP                               AS refreshed_at

FROM sku s
LEFT JOIN sku_demand_signal ds ON s.sku_id = ds.sku_id
