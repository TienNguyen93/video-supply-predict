/*
  stg_sku_catalog
  ───────────────
  Staging view over raw.sku_catalog.

  Adds two derived columns that are cheap to compute once and reused
  across all downstream models:
    - days_of_cover           : current_stock / baseline_daily_demand
    - inventory_risk_tier     : CRITICAL / WARNING / WATCH / NORMAL
                                (thresholds from configs/risk_thresholds.yaml)

  Risk tier thresholds (mirrored from YAML for SQL convenience):
    CRITICAL  stock covers < lead_time days
    WARNING   stock covers < lead_time * 2 days
    WATCH     stock covers < 30 days
    NORMAL    all other cases
*/
{{ config(materialized='view', schema='staging') }}

WITH base AS (
    SELECT
        sku_id,
        name                                        AS sku_name,
        category,
        unit_price_usd,
        baseline_daily_demand,
        current_stock,
        supplier_lead_time_days,
        reorder_point,
        viral_sensitivity,
        created_at,
        -- Days of cover: how long current stock lasts at baseline demand
        CAST(current_stock AS DOUBLE)
            / NULLIF(baseline_daily_demand, 0.0)    AS days_of_cover
    FROM {{ source('raw', 'sku_catalog') }}
)

SELECT
    sku_id,
    sku_name,
    category,
    unit_price_usd,
    baseline_daily_demand,
    current_stock,
    supplier_lead_time_days,
    reorder_point,
    viral_sensitivity,
    created_at,
    ROUND(days_of_cover, 2)                         AS days_of_cover,

    -- Inventory risk tier derived from days-of-cover vs lead time
    CASE
        WHEN days_of_cover < supplier_lead_time_days           THEN 'CRITICAL'
        WHEN days_of_cover < CAST(supplier_lead_time_days AS DOUBLE) * 2.0   THEN 'WARNING'
        WHEN days_of_cover < 30.0                              THEN 'WATCH'
        ELSE                                                        'NORMAL'
    END                                             AS inventory_risk_tier,

    -- Binary flags for quick filtering
    CASE WHEN current_stock <= reorder_point THEN TRUE ELSE FALSE END
                                                    AS is_below_reorder

FROM base
