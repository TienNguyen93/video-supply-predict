"""
Video and engagement timeseries generator.

Simulates realistic viral engagement trajectories for short-form video content.

Growth model:
  - Non-viral videos: slow, steady accumulation; ~1k–20k total views over 48h
  - Viral videos:     power-law spike in the first 6–24h driven by FYP/Explore
                      placement; 50k–5M total views over 48h

For each video, 48 hourly snapshots are generated. Each snapshot records:
  - Cumulative counts (view, like, share, save, click, cart)
  - Hourly deltas (velocity)
  - Derived engagement rates
  - Demand lift label (derived from engagement × SKU viral sensitivity)
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

import numpy as np

from src.ingestion.schemas import (
    CreatorTier,
    EngagementEvent,
    Platform,
    VideoRecord,
    VideoSKUBridge,
)


# ---------------------------------------------------------------------------
# Creator tier engagement multipliers
# ---------------------------------------------------------------------------

_TIER_MULTIPLIERS: dict[CreatorTier, dict[str, float]] = {
    CreatorTier.NANO:   {"reach": 0.4,  "engagement": 1.30},  # small audience, high ER
    CreatorTier.MICRO:  {"reach": 0.70, "engagement": 1.15},
    CreatorTier.MID:    {"reach": 1.00, "engagement": 1.00},  # baseline
    CreatorTier.MACRO:  {"reach": 2.50, "engagement": 0.85},
    CreatorTier.MEGA:   {"reach": 8.00, "engagement": 0.65},
}

_PLATFORM_VIRAL_PROB: dict[Platform, float] = {
    Platform.TIKTOK:    0.15,  # FYP is highly democratised
    Platform.INSTAGRAM: 0.08,  # Explore is more follower-weighted
    Platform.YOUTUBE:   0.05,  # Shorts algorithm is slower to surface
}

_REGIONS_BY_PLATFORM: dict[Platform, list[str]] = {
    Platform.TIKTOK:    ["US", "GB", "AU", "CA", "DE", "FR", "BR", "MX"],
    Platform.INSTAGRAM: ["US", "BR", "IN", "GB", "DE", "FR", "IT", "ES"],
    Platform.YOUTUBE:   ["US", "IN", "BR", "JP", "KR", "GB", "DE", "MX"],
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _hourly_view_curve(
    hour: int,
    peak_hour: int,
    total_views: float,
    viral: bool,
    rng: random.Random,
) -> float:
    """
    Return the fraction of total_views expected at `hour` (0-indexed).

    Uses a log-normal-shaped curve centred on `peak_hour`, with more
    front-loading for viral content.
    """
    # Gaussian kernel centred on peak, normalised to sum ~= 1
    sigma = 4.0 if viral else 10.0
    weights = [math.exp(-0.5 * ((h - peak_hour) / sigma) ** 2) for h in range(48)]
    total_w = sum(weights)
    fractions = [w / total_w for w in weights]

    # Cumulative fraction up to this hour
    cumulative = sum(fractions[: hour + 1])
    return cumulative * total_views


def _add_noise(value: float, noise_pct: float, rng: random.Random) -> float:
    """Add ±noise_pct multiplicative noise to value."""
    return max(0.0, value * (1.0 + rng.uniform(-noise_pct, noise_pct)))


# ---------------------------------------------------------------------------
# Per-video engagement parameter sampling
# ---------------------------------------------------------------------------


def _sample_video_params(
    platform: Platform,
    creator_tier: CreatorTier,
    is_viral: bool,
    rng: random.Random,
) -> dict:
    """Sample engagement rate parameters for a single video."""
    tier_mult = _TIER_MULTIPLIERS[creator_tier]
    eng_mult = tier_mult["engagement"]

    # Base engagement rates (loosely calibrated to real TikTok/IG benchmarks)
    if is_viral:
        total_views = rng.uniform(50_000, 5_000_000) * tier_mult["reach"]
        like_rate_base = rng.uniform(0.06, 0.18) * eng_mult
        save_rate_base = rng.uniform(0.04, 0.14) * eng_mult
        share_rate_base = rng.uniform(0.02, 0.08) * eng_mult
        click_rate_base = rng.uniform(0.02, 0.08)
        comment_rate_base = rng.uniform(0.005, 0.02) * eng_mult
        peak_hour = rng.randint(4, 16)   # viral content peaks early
    else:
        total_views = rng.uniform(500, 20_000) * tier_mult["reach"]
        like_rate_base = rng.uniform(0.02, 0.08) * eng_mult
        save_rate_base = rng.uniform(0.005, 0.03) * eng_mult
        share_rate_base = rng.uniform(0.002, 0.015) * eng_mult
        click_rate_base = rng.uniform(0.003, 0.02)
        comment_rate_base = rng.uniform(0.001, 0.008) * eng_mult
        peak_hour = rng.randint(8, 28)

    cart_rate_base = click_rate_base * rng.uniform(0.15, 0.35)  # 15–35% of clicks → cart

    return {
        "total_views": total_views,
        "like_rate": min(like_rate_base, 0.50),
        "save_rate": min(save_rate_base, 0.30),
        "share_rate": min(share_rate_base, 0.20),
        "click_rate": min(click_rate_base, 0.20),
        "comment_rate": min(comment_rate_base, 0.10),
        "cart_rate": min(cart_rate_base, 0.10),
        "peak_hour": peak_hour,
    }


# ---------------------------------------------------------------------------
# Demand lift calculation
# ---------------------------------------------------------------------------


def _compute_demand_lift(
    total_views: float,
    click_rate: float,
    cart_rate: float,
    sku_viral_sensitivities: list[float],
    rng: random.Random,
) -> float:
    """
    Derive the 24h demand lift multiplier from engagement signals.

    Lift = (carts driven by video / baseline_daily_demand_equivalent)
    We normalise so that a typical viral video with moderate SKU sensitivity ≈ 2–5x.
    """
    avg_sensitivity = sum(sku_viral_sensitivities) / len(sku_viral_sensitivities)
    # Views at 24h (cumulative up to hour 24 is roughly 85% for viral, 60% for normal)
    views_24h = total_views * rng.uniform(0.55, 0.90)
    carts_24h = views_24h * click_rate * cart_rate
    # Normalisation: assume baseline_daily_demand equivalent = 50 units for this formula
    raw_lift = (carts_24h * avg_sensitivity) / 50.0
    # Cap at 20x with some noise
    lift = min(_add_noise(raw_lift, 0.15, rng), 20.0)
    return round(max(lift, 0.1), 3)


# ---------------------------------------------------------------------------
# Main generator functions
# ---------------------------------------------------------------------------


def generate_videos(
    sku_ids: list[str],
    num_videos: int = 200,
    seed: int = 42,
) -> list[VideoRecord]:
    """
    Generate video metadata records.

    Each video is tagged with 1–3 SKUs drawn from the catalog.
    Platform and creator tier are sampled with realistic distributions.

    Args:
        sku_ids: All available SKU IDs in the catalog.
        num_videos: Total number of video records to generate.
        seed: Random seed.

    Returns:
        List of VideoRecord objects.
    """
    rng = random.Random(seed)

    platform_weights = [0.55, 0.30, 0.15]  # TikTok dominant
    platforms = [Platform.TIKTOK, Platform.INSTAGRAM, Platform.YOUTUBE]

    tier_weights = [0.25, 0.35, 0.20, 0.12, 0.08]  # micro-heavy distribution
    tiers = list(CreatorTier)

    # Reference date: simulate 90 days of historical data
    reference_date = datetime(2024, 1, 1, tzinfo=timezone.utc)

    videos: list[VideoRecord] = []
    for i in range(num_videos):
        platform = rng.choices(platforms, weights=platform_weights, k=1)[0]
        creator_tier = rng.choices(tiers, weights=tier_weights, k=1)[0]

        is_viral = rng.random() < _PLATFORM_VIRAL_PROB[platform]

        # Post time: random within the 90-day window, skewed to business hours
        days_offset = rng.randint(0, 89)
        hour_offset = rng.choices(range(24), weights=[
            1, 1, 1, 1, 1, 2, 4, 6, 8, 9, 10, 10,
            10, 10, 9, 9, 10, 12, 12, 11, 9, 7, 4, 2,
        ], k=1)[0]
        posted_at = reference_date + timedelta(days=days_offset, hours=hour_offset)

        # Tag 1–3 SKUs per video (power-law: most videos tag 1)
        n_skus = rng.choices([1, 2, 3], weights=[0.65, 0.25, 0.10], k=1)[0]
        tagged_skus = rng.sample(sku_ids, k=min(n_skus, len(sku_ids)))

        # Regions: sample 1–4 from platform-typical regions
        regions_pool = _REGIONS_BY_PLATFORM[platform]
        n_regions = rng.randint(1, min(4, len(regions_pool)))
        regions = rng.sample(regions_pool, k=n_regions)

        video = VideoRecord(
            video_id=f"vid_{i + 1:04d}",
            platform=platform,
            creator_id=f"creator_{rng.randint(1000, 9999)}",
            creator_tier=creator_tier,
            posted_at=posted_at,
            video_duration_s=rng.randint(10, 180),
            has_link_in_bio=rng.random() < 0.60,
            sku_ids=tagged_skus,
            region_codes=regions,
            is_viral=is_viral,
        )
        videos.append(video)

    return videos


def generate_engagement_events(
    video: VideoRecord,
    sku_sensitivity_map: dict[str, float],
    snapshot_hours: int = 48,
    seed_offset: int = 0,
) -> list[EngagementEvent]:
    """
    Generate hourly engagement snapshots for a single video.

    Args:
        video: The VideoRecord to generate snapshots for.
        sku_sensitivity_map: Maps sku_id → viral_sensitivity for SKUs in this video.
        snapshot_hours: Number of hourly snapshots to produce (default 48).
        seed_offset: Added to video index for reproducible per-video variation.

    Returns:
        List of EngagementEvent objects (one per hour).
    """
    rng = random.Random(hash(video.video_id) + seed_offset)

    params = _sample_video_params(video.platform, video.creator_tier, video.is_viral, rng)

    total_views = params["total_views"]
    peak_hour = params["peak_hour"]
    like_rate = params["like_rate"]
    save_rate = params["save_rate"]
    share_rate = params["share_rate"]
    click_rate = params["click_rate"]
    comment_rate = params["comment_rate"]
    cart_rate = params["cart_rate"]

    # Compute demand lift label (using all tagged SKU sensitivities)
    sensitivities = [sku_sensitivity_map.get(s, 1.0) for s in video.sku_ids]
    demand_lift_24h = _compute_demand_lift(total_views, click_rate, cart_rate, sensitivities, rng)
    is_viral_threshold = 1.8
    is_effectively_viral = video.is_viral or demand_lift_24h >= is_viral_threshold

    # FYP/Explore placement correlates with virality
    is_on_foryou = video.is_viral or rng.random() < 0.20
    trending_rank: int | None = rng.randint(1, 50) if video.is_viral and rng.random() < 0.3 else None

    events: list[EngagementEvent] = []
    prev_views = 0
    prev_saves = 0
    prev_shares = 0

    for hour in range(snapshot_hours):
        # Cumulative views at this hour
        raw_views = _hourly_view_curve(hour, peak_hour, total_views, video.is_viral, rng)
        cum_views = int(_add_noise(raw_views, 0.05, rng))
        cum_views = max(cum_views, prev_views)  # strictly non-decreasing

        if cum_views == 0:
            # First few hours might have 0 views for non-viral
            events.append(_zero_snapshot(video, hour, is_on_foryou, trending_rank, demand_lift_24h, is_effectively_viral))
            continue

        # Apply slight rate drift over time (engagement rates decay slowly)
        decay = max(0.5, 1.0 - hour * 0.008)
        h_save_rate = min(save_rate * decay * _add_noise(1.0, 0.08, rng), 0.5)
        h_share_rate = min(share_rate * decay * _add_noise(1.0, 0.08, rng), 0.3)
        h_like_rate = min(like_rate * decay * _add_noise(1.0, 0.06, rng), 0.7)
        h_click_rate = min(click_rate * _add_noise(1.0, 0.10, rng), 0.3)
        h_comment_rate = min(comment_rate * decay * _add_noise(1.0, 0.12, rng), 0.15)
        h_cart_rate = min(cart_rate * _add_noise(1.0, 0.12, rng), 0.15)

        cum_likes = int(cum_views * h_like_rate)
        cum_saves = int(cum_views * h_save_rate)
        cum_shares = int(cum_views * h_share_rate)
        cum_comments = int(cum_views * h_comment_rate)
        cum_clicks = int(cum_views * h_click_rate)
        cum_carts = int(cum_views * h_cart_rate)

        views_delta = max(cum_views - prev_views, 0)
        saves_delta = max(cum_saves - prev_saves, 0)
        shares_delta = max(cum_shares - prev_shares, 0)

        # Velocity = rate based on this hour's incremental engagement
        save_velocity = saves_delta / views_delta if views_delta > 0 else 0.0

        snapshot_at = video.posted_at + timedelta(hours=hour)
        posted_date = video.posted_at.strftime("%Y%m%d")
        event_id = f"evt_{posted_date}_{video.video_id}_h{hour:02d}"

        event = EngagementEvent(
            event_id=event_id,
            video_id=video.video_id,
            posted_at=video.posted_at,
            snapshot_at=snapshot_at,
            hours_since_post=hour,
            platform=video.platform,
            creator_id=video.creator_id,
            creator_tier=video.creator_tier,
            sku_ids=video.sku_ids,
            video_duration_s=video.video_duration_s,
            has_link_in_bio=video.has_link_in_bio,
            view_count=cum_views,
            like_count=cum_likes,
            comment_count=cum_comments,
            share_count=cum_shares,
            save_count=cum_saves,
            click_to_product=cum_clicks,
            add_to_cart=cum_carts,
            save_rate=round(h_save_rate, 5),
            share_rate=round(h_share_rate, 5),
            click_rate=round(h_click_rate, 5),
            cart_rate=round(h_cart_rate, 5),
            like_rate=round(h_like_rate, 5),
            views_delta_1h=views_delta,
            saves_delta_1h=saves_delta,
            shares_delta_1h=shares_delta,
            save_velocity=round(save_velocity, 6),
            is_on_foryou=is_on_foryou,
            trending_rank=trending_rank,
            region_codes=video.region_codes,
            demand_lift_24h=round(demand_lift_24h, 4),
            is_viral=is_effectively_viral,
        )
        events.append(event)
        prev_views = cum_views
        prev_saves = cum_saves
        prev_shares = cum_shares

    return events


def _zero_snapshot(
    video: VideoRecord,
    hour: int,
    is_on_foryou: bool,
    trending_rank: int | None,
    demand_lift_24h: float,
    is_viral: bool,
) -> EngagementEvent:
    """Return an all-zero snapshot for the first hours before any views."""
    snapshot_at = video.posted_at + timedelta(hours=hour)
    posted_date = video.posted_at.strftime("%Y%m%d")
    return EngagementEvent(
        event_id=f"evt_{posted_date}_{video.video_id}_h{hour:02d}",
        video_id=video.video_id,
        posted_at=video.posted_at,
        snapshot_at=snapshot_at,
        hours_since_post=hour,
        platform=video.platform,
        creator_id=video.creator_id,
        creator_tier=video.creator_tier,
        sku_ids=video.sku_ids,
        video_duration_s=video.video_duration_s,
        has_link_in_bio=video.has_link_in_bio,
        view_count=0,
        like_count=0,
        comment_count=0,
        share_count=0,
        save_count=0,
        click_to_product=0,
        add_to_cart=0,
        save_rate=0.0,
        share_rate=0.0,
        click_rate=0.0,
        cart_rate=0.0,
        like_rate=0.0,
        views_delta_1h=0,
        saves_delta_1h=0,
        shares_delta_1h=0,
        save_velocity=0.0,
        is_on_foryou=is_on_foryou,
        trending_rank=trending_rank,
        region_codes=video.region_codes,
        demand_lift_24h=demand_lift_24h,
        is_viral=is_viral,
    )


def generate_video_sku_bridges(videos: list[VideoRecord]) -> list[VideoSKUBridge]:
    """
    Produce the normalised video ↔ SKU mapping table.
    One row per (video_id, sku_id) pair.
    """
    bridges: list[VideoSKUBridge] = []
    for video in videos:
        for sku_id in video.sku_ids:
            bridges.append(
                VideoSKUBridge(
                    video_id=video.video_id,
                    sku_id=sku_id,
                    platform=video.platform,
                    posted_at=video.posted_at,
                )
            )
    return bridges
