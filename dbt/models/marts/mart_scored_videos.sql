/*
  mart_scored_videos
  ──────────────────
  ML-ready feature table. One row per video — the LATEST snapshot.

  Purpose:
    - Served to the LightGBM scoring pipeline (src/models/score.py) at inference time
    - Used as training data when demand_lift_24h IS NOT NULL
    - Read by the Streamlit dashboard trending feed

  Column layout:
    - Identity & context (for display)
    - ML feature columns (no raw counts; rates and velocity only)
    - Label: demand_lift_24h (null for real-time rows)
    - ML model outputs: p10/p50/p90 (null until Phase 4 scoring runs)
    - Metadata
*/
{{ config(materialized='table', schema='marts') }}

WITH ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY video_id
            ORDER BY hours_since_post DESC
        ) AS _rn
    FROM {{ ref('int_engagement_features') }}
),

latest AS (
    SELECT * EXCLUDE (_rn)
    FROM ranked
    WHERE _rn = 1
)

SELECT
    -- ── Identity ─────────────────────────────────────────────────────
    video_id,
    event_id                                        AS latest_event_id,
    posted_at,
    snapshot_at                                     AS last_snapshot_at,
    hours_since_post                                AS hours_observed,
    view_count,

    -- ── Context (for display / debugging) ────────────────────────────
    platform,
    creator_id,
    creator_tier,
    sku_ids_json,

    -- ── ML Feature columns ────────────────────────────────────────────
    -- Categorical (encoded)
    platform_encoded,
    creator_tier_encoded,

    -- Content
    video_duration_s,
    has_link_in_bio_int                             AS has_link_in_bio,

    -- Engagement rates (robust to view-count scale)
    save_rate,
    share_rate,
    click_rate,
    cart_rate,
    like_rate,

    -- Velocity (3-hour rolling)
    views_velocity_3h,
    saves_velocity_3h,
    shares_velocity_3h,
    views_acceleration,

    -- Hourly deltas
    views_delta_1h,
    saves_delta_1h,
    shares_delta_1h,
    save_velocity,

    -- Composite score
    engagement_score,

    -- Platform signals
    is_on_foryou_int                                AS is_on_foryou,
    COALESCE(trending_rank, -1)                     AS trending_rank,   -- -1 = not trending

    -- SKU sensitivity
    sku_viral_sensitivity,
    sku_viral_sensitivity_max,

    -- Time features
    posted_hour_of_day,
    posted_day_of_week,
    snapshot_hour_of_day,
    snapshot_day_of_week,

    -- ── Labels & predictions ─────────────────────────────────────────
    demand_lift_24h,                                -- training label; null at inference
    is_viral,

    -- Prediction columns — populated by src/models/score.py (Phase 4)
    NULL::DOUBLE                                    AS p10_demand_lift,
    NULL::DOUBLE                                    AS p50_demand_lift,
    NULL::DOUBLE                                    AS p90_demand_lift,
    NULL::VARCHAR                                   AS risk_tier_predicted,

    -- ── Metadata ─────────────────────────────────────────────────────
    CURRENT_TIMESTAMP                               AS mart_refreshed_at

FROM latest
