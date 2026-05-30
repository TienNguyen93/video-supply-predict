"""
Unit tests for Pydantic schemas.

Tests: field validation, enum coercion, derived properties,
       model_validator constraints.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from pydantic import ValidationError

from src.ingestion.schemas import (
    CreatorTier,
    EngagementEvent,
    Platform,
    RiskTier,
    SKUCategory,
    SKURecord,
    VideoRecord,
    VideoSKUBridge,
)


# ---------------------------------------------------------------------------
# SKURecord
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSKURecord:
    def _valid_sku(self, **overrides) -> dict:
        base = {
            "sku_id": "SKU-0001",
            "name": "Hydrating Serum",
            "category": SKUCategory.BEAUTY,
            "unit_price_usd": 29.99,
            "baseline_daily_demand": 50.0,
            "current_stock": 300,
            "supplier_lead_time_days": 14,
            "reorder_point": 200,
            "viral_sensitivity": 2.5,
            "created_at": datetime.now(tz=timezone.utc),
        }
        base.update(overrides)
        return base

    def test_valid_sku_parses(self):
        sku = SKURecord(**self._valid_sku())
        assert sku.sku_id == "SKU-0001"
        assert sku.category == SKUCategory.BEAUTY

    def test_days_of_cover_property(self):
        sku = SKURecord(**self._valid_sku(current_stock=700, baseline_daily_demand=50.0))
        assert sku.days_of_cover == pytest.approx(14.0)

    def test_days_of_cover_zero_demand(self):
        # Should not raise, should return inf
        sku = SKURecord(**self._valid_sku(baseline_daily_demand=0.001))
        # Just check it doesn't explode
        assert sku.days_of_cover > 0

    def test_is_below_reorder(self):
        sku = SKURecord(**self._valid_sku(current_stock=100, reorder_point=200))
        assert sku.is_below_reorder is True

    def test_is_not_below_reorder(self):
        sku = SKURecord(**self._valid_sku(current_stock=500, reorder_point=200))
        assert sku.is_below_reorder is False

    def test_negative_price_rejected(self):
        with pytest.raises(ValidationError):
            SKURecord(**self._valid_sku(unit_price_usd=-1.0))

    def test_zero_demand_rejected(self):
        with pytest.raises(ValidationError):
            SKURecord(**self._valid_sku(baseline_daily_demand=0))

    def test_viral_sensitivity_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            SKURecord(**self._valid_sku(viral_sensitivity=10.0))


# ---------------------------------------------------------------------------
# VideoRecord
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestVideoRecord:
    def _valid_video(self, **overrides) -> dict:
        base = {
            "video_id": "vid_0001",
            "platform": Platform.TIKTOK,
            "creator_id": "creator_1234",
            "creator_tier": CreatorTier.MICRO,
            "posted_at": datetime(2024, 3, 15, 12, 0, tzinfo=timezone.utc),
            "video_duration_s": 38,
            "has_link_in_bio": True,
            "sku_ids": ["SKU-0001"],
            "region_codes": ["US", "GB"],
            "is_viral": True,
        }
        base.update(overrides)
        return base

    def test_valid_video_parses(self):
        v = VideoRecord(**self._valid_video())
        assert v.platform == Platform.TIKTOK
        assert v.creator_tier == CreatorTier.MICRO

    def test_empty_sku_ids_rejected(self):
        with pytest.raises(ValidationError, match="at least one SKU"):
            VideoRecord(**self._valid_video(sku_ids=[]))

    def test_platform_enum_from_string(self):
        v = VideoRecord(**self._valid_video(platform="instagram"))
        assert v.platform == Platform.INSTAGRAM

    def test_creator_tier_enum_from_string(self):
        v = VideoRecord(**self._valid_video(creator_tier="mega"))
        assert v.creator_tier == CreatorTier.MEGA


# ---------------------------------------------------------------------------
# EngagementEvent
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEngagementEvent:
    def _valid_event(self, **overrides) -> dict:
        posted = datetime(2024, 3, 15, 0, 0, tzinfo=timezone.utc)
        snap = datetime(2024, 3, 15, 3, 0, tzinfo=timezone.utc)
        base = {
            "event_id": "evt_20240315_vid_0001_h03",
            "video_id": "vid_0001",
            "posted_at": posted,
            "snapshot_at": snap,
            "hours_since_post": 3,
            "platform": Platform.TIKTOK,
            "creator_id": "creator_1234",
            "creator_tier": CreatorTier.MICRO,
            "sku_ids": ["SKU-0042"],
            "video_duration_s": 38,
            "has_link_in_bio": True,
            "view_count": 28400,
            "like_count": 3100,
            "comment_count": 412,
            "share_count": 890,
            "save_count": 2380,
            "click_to_product": 1140,
            "add_to_cart": 290,
            "save_rate": 0.0838,
            "share_rate": 0.0313,
            "click_rate": 0.0401,
            "cart_rate": 0.0102,
            "like_rate": 0.1091,
            "views_delta_1h": 4200,
            "saves_delta_1h": 380,
            "shares_delta_1h": 140,
            "save_velocity": 0.0905,
            "is_on_foryou": True,
            "trending_rank": None,
            "region_codes": ["US", "GB", "AU"],
            "demand_lift_24h": 4.2,
            "is_viral": True,
        }
        base.update(overrides)
        return base

    def test_valid_event_parses(self, sample_engagement_event):
        e = EngagementEvent(**sample_engagement_event)
        assert e.view_count == 28400
        assert e.is_viral is True
        assert e.demand_lift_24h == pytest.approx(4.2)

    def test_snapshot_before_posted_rejected(self):
        posted = datetime(2024, 3, 15, 12, 0, tzinfo=timezone.utc)
        snap = datetime(2024, 3, 15, 11, 0, tzinfo=timezone.utc)  # 1h before posting
        with pytest.raises(ValidationError, match="snapshot_at must be >= posted_at"):
            EngagementEvent(**self._valid_event(posted_at=posted, snapshot_at=snap))

    def test_demand_lift_nullable(self):
        e = EngagementEvent(**self._valid_event(demand_lift_24h=None))
        assert e.demand_lift_24h is None

    def test_rate_above_one_rejected(self):
        with pytest.raises(ValidationError):
            EngagementEvent(**self._valid_event(save_rate=1.5))

    def test_negative_view_count_rejected(self):
        with pytest.raises(ValidationError):
            EngagementEvent(**self._valid_event(view_count=-1))

    def test_trending_rank_nullable(self):
        e = EngagementEvent(**self._valid_event(trending_rank=5))
        assert e.trending_rank == 5
        e2 = EngagementEvent(**self._valid_event(trending_rank=None))
        assert e2.trending_rank is None
