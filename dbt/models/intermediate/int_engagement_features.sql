/*
  int_engagement_features
  ───────────────────────
  Intermediate table — the core feature engineering model.

  Builds one row per (video_id, hours_since_post) with:
    1. All raw engagement metrics from stg_engagement_events
    2. Rolling velocity windows (3h) computed in SQL via window functions
    3. View acceleration (first-order delta of views_delta_1h)
    4. Composite engagement score
    5. Encoded categorical features for LightGBM (ordinal integers)
    6. SKU viral sensitivity joined from the bridge table
    7. Time-of-day and day-of-week features

  The demand_lift_24h label is preserved for training; it is null for
  real-time inference rows (future videos not yet in training set).
*/
{{ config(materialized='table', schema='intermediate') }}

WITH events AS (
    SELECT * FROM {{ ref('stg_engagement_events') }}
),

-- ── Velocity windows (rolling 3h sum per video) ───────────────────────────
velocity AS (
    SELECT
        event_id,
        video_id,
        hours_since_post,

        -- 3-hour rolling sums (current + 2 preceding hours in the same video)
        SUM(views_delta_1h) OVER (
            PARTITION BY video_id
            ORDER BY hours_since_post
            ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
        )                                           AS views_velocity_3h,

        SUM(saves_delta_1h) OVER (
            PARTITION BY video_id
            ORDER BY hours_since_post
            ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
        )                                           AS saves_velocity_3h,

        SUM(shares_delta_1h) OVER (
            PARTITION BY video_id
            ORDER BY hours_since_post
            ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
        )                                           AS shares_velocity_3h,

        -- Acceleration: how much views_delta changed vs previous hour
        views_delta_1h - LAG(views_delta_1h, 1, 0) OVER (
            PARTITION BY video_id
            ORDER BY hours_since_post
        )                                           AS views_acceleration

    FROM events
),

-- ── SKU viral sensitivity per video (avg + max across tagged SKUs) ────────
sku_sensitivity AS (
    SELECT
        b.video_id,
        AVG(s.viral_sensitivity)    AS avg_sku_viral_sensitivity,
        MAX(s.viral_sensitivity)    AS max_sku_viral_sensitivity
    FROM {{ source('raw', 'video_sku_bridge') }} b
    INNER JOIN {{ ref('stg_sku_catalog') }}        s ON b.sku_id = s.sku_id
    GROUP BY b.video_id
),

-- ── Assemble final feature set ────────────────────────────────────────────
enriched AS (
    SELECT
        -- Identity
        e.event_id,
        e.video_id,
        e.posted_at,
        e.snapshot_at,
        e.hours_since_post,

        -- Raw engagement
        e.platform,
        e.creator_id,
        e.creator_tier,
        e.sku_ids_json,
        e.video_duration_s,
        e.has_link_in_bio,
        e.view_count,
        e.like_count,
        e.comment_count,
        e.share_count,
        e.save_count,
        e.click_to_product,
        e.add_to_cart,

        -- Rates
        e.save_rate,
        e.share_rate,
        e.click_rate,
        e.cart_rate,
        e.like_rate,

        -- Hourly deltas
        e.views_delta_1h,
        e.saves_delta_1h,
        e.shares_delta_1h,
        e.save_velocity,

        -- Platform signals
        e.is_on_foryou,
        e.trending_rank,

        -- Labels
        e.demand_lift_24h,
        e.is_viral,

        -- ── Velocity features (window functions) ─────────────────────────
        COALESCE(v.views_velocity_3h,  0)           AS views_velocity_3h,
        COALESCE(v.saves_velocity_3h,  0)           AS saves_velocity_3h,
        COALESCE(v.shares_velocity_3h, 0)           AS shares_velocity_3h,
        COALESCE(v.views_acceleration, 0)           AS views_acceleration,

        -- ── Composite engagement score ───────────────────────────────────
        -- Weighted: save_rate x2 + share_rate x3 + click_rate x5
        -- Higher-intent actions (saves, clicks) weighted more than likes
        ROUND(
            e.save_rate  * 2.0 +
            e.share_rate * 3.0 +
            e.click_rate * 5.0,
        6)                                          AS engagement_score,

        -- ── Encoded categoricals (ordinal; stable across runs) ───────────
        CASE e.creator_tier
            WHEN 'nano'    THEN 0
            WHEN 'micro'   THEN 1
            WHEN 'mid'     THEN 2
            WHEN 'macro'   THEN 3
            WHEN 'mega'    THEN 4
            ELSE                1   -- default to micro
        END                                         AS creator_tier_encoded,

        CASE e.platform
            WHEN 'tiktok'    THEN 0
            WHEN 'instagram' THEN 1
            WHEN 'youtube'   THEN 2
            ELSE                  0
        END                                         AS platform_encoded,

        -- ── SKU sensitivity ──────────────────────────────────────────────
        COALESCE(sk.avg_sku_viral_sensitivity, 1.0) AS sku_viral_sensitivity,
        COALESCE(sk.max_sku_viral_sensitivity, 1.0) AS sku_viral_sensitivity_max,

        -- ── Time features ────────────────────────────────────────────────
        EXTRACT(HOUR FROM e.snapshot_at)            AS snapshot_hour_of_day,
        EXTRACT(DOW  FROM e.snapshot_at)            AS snapshot_day_of_week,
        EXTRACT(HOUR FROM e.posted_at)              AS posted_hour_of_day,
        EXTRACT(DOW  FROM e.posted_at)              AS posted_day_of_week,

        -- ── Boolean as integer (for LightGBM) ───────────────────────────
        CAST(e.is_on_foryou    AS INTEGER)          AS is_on_foryou_int,
        CAST(e.has_link_in_bio AS INTEGER)          AS has_link_in_bio_int

    FROM events          e
    LEFT JOIN velocity   v  ON e.event_id  = v.event_id
    LEFT JOIN sku_sensitivity sk ON e.video_id = sk.video_id
)

SELECT * FROM enriched
