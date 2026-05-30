/*
  mart_trending_videos
  ────────────────────
  Top-trending videos ranked by engagement score — for the Streamlit
  "viral feed" panel.

  Shows the top 50 videos by engagement_score from the latest snapshots,
  with human-readable metrics for display.
*/
{{ config(materialized='table', schema='marts') }}

WITH scored AS (
    SELECT * FROM {{ ref('mart_scored_videos') }}
),

-- Compute a display-friendly hours label
display AS (
    SELECT
        *,
        CASE
            WHEN hours_observed < 1   THEN '< 1 hour'
            WHEN hours_observed < 24  THEN CAST(hours_observed AS VARCHAR) || ' hours'
            ELSE CAST(CAST(hours_observed / 24 AS INTEGER) AS VARCHAR) || ' days'
        END                                         AS age_label,

        -- Estimated total views (proxy: use view velocity × observed hours)
        -- view_count is cumulative so it IS total views
        view_count                                  AS total_views,

        -- Engagement tier for UI badge
        CASE
            WHEN engagement_score >= 0.20 THEN 'MEGA'
            WHEN engagement_score >= 0.10 THEN 'HIGH'
            WHEN engagement_score >= 0.05 THEN 'MODERATE'
            ELSE                               'LOW'
        END                                         AS engagement_tier
    FROM scored
)

SELECT
    -- Display identity
    video_id,
    platform,
    creator_id,
    creator_tier,
    sku_ids_json,

    -- Core metrics
    total_views,
    ROUND(save_rate  * 100, 2)                      AS save_rate_pct,
    ROUND(share_rate * 100, 2)                      AS share_rate_pct,
    ROUND(click_rate * 100, 2)                      AS click_rate_pct,
    ROUND(cart_rate  * 100, 2)                      AS cart_rate_pct,
    ROUND(engagement_score, 4)                      AS engagement_score,
    engagement_tier,

    -- Velocity
    views_velocity_3h,
    views_acceleration,

    -- Context
    is_on_foryou,
    age_label,
    hours_observed,
    posted_at,
    last_snapshot_at,
    is_viral,

    -- Predicted lift (null until Phase 4)
    p50_demand_lift,
    p90_demand_lift,
    risk_tier_predicted,

    -- Rank by engagement score (descending)
    ROW_NUMBER() OVER (ORDER BY engagement_score DESC) AS rank,

    mart_refreshed_at

FROM display
QUALIFY ROW_NUMBER() OVER (ORDER BY engagement_score DESC) <= 50
ORDER BY engagement_score DESC
