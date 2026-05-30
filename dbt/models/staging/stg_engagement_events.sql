/*
  stg_engagement_events
  ─────────────────────
  Staging view over raw.engagement_events.

  Responsibilities:
    - Rename columns to project-standard names (no transformation)
    - Cast types explicitly (BOOLEAN → BOOLEAN, etc.)
    - Add _loaded_at metadata column
    - Filter out sentinel rows with zero views at hour 0 where they add no signal
      (videos that had genuinely zero views at hour 0 still have all later hours)

  Intentionally NOT computed here (done in intermediate):
    - Rolling velocity features  (require window functions across rows)
    - Encoded categorical features
    - SKU viral sensitivity join
*/
{{ config(materialized='view', schema='staging') }}

SELECT
    -- ── Identity ─────────────────────────────────────────────
    event_id,
    video_id,
    posted_at,
    snapshot_at,
    hours_since_post,

    -- ── Content context ───────────────────────────────────────
    platform,
    creator_id,
    creator_tier,
    sku_ids_json,           -- JSON array string; parsed in intermediate
    video_duration_s,
    CAST(has_link_in_bio AS BOOLEAN)   AS has_link_in_bio,

    -- ── Cumulative engagement counts ─────────────────────────
    view_count,
    like_count,
    comment_count,
    share_count,
    save_count,
    click_to_product,
    add_to_cart,

    -- ── Engagement rates (count / view_count) ────────────────
    save_rate,
    share_rate,
    click_rate,
    cart_rate,
    like_rate,

    -- ── Hourly deltas (velocity inputs) ──────────────────────
    views_delta_1h,
    saves_delta_1h,
    shares_delta_1h,
    save_velocity,          -- saves_delta_1h / views_delta_1h

    -- ── Platform signals ──────────────────────────────────────
    CAST(is_on_foryou AS BOOLEAN)      AS is_on_foryou,
    trending_rank,          -- nullable
    region_codes_json,      -- JSON array string

    -- ── Labels ───────────────────────────────────────────────
    demand_lift_24h,        -- nullable; null during real-time inference
    CAST(is_viral AS BOOLEAN)          AS is_viral,

    -- ── Metadata ─────────────────────────────────────────────
    CURRENT_TIMESTAMP                  AS _loaded_at

FROM {{ source('raw', 'engagement_events') }}
