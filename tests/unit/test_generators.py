"""
Unit tests for the data generators.

Tests: output shape, statistical sanity, reproducibility, SKU diversity.
No I/O — generators are pure functions.
"""

from __future__ import annotations

import pytest

from src.ingestion.generators.sku_generator import generate_sku_catalog
from src.ingestion.generators.video_generator import (
    generate_engagement_events,
    generate_video_sku_bridges,
    generate_videos,
)
from src.ingestion.schemas import EngagementEvent, Platform, SKURecord, VideoRecord

# ---------------------------------------------------------------------------
# SKU Generator
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSKUGenerator:
    def test_returns_correct_count(self):
        skus = generate_sku_catalog(num_skus=50)
        assert len(skus) == 50

    def test_all_are_sku_records(self):
        skus = generate_sku_catalog(num_skus=10)
        assert all(isinstance(s, SKURecord) for s in skus)

    def test_sku_ids_are_unique(self):
        skus = generate_sku_catalog(num_skus=50)
        ids = [s.sku_id for s in skus]
        assert len(ids) == len(set(ids))

    def test_reproducible_with_same_seed(self):
        skus_a = generate_sku_catalog(num_skus=20, seed=42)
        skus_b = generate_sku_catalog(num_skus=20, seed=42)
        assert [s.sku_id for s in skus_a] == [s.sku_id for s in skus_b]
        assert [s.name for s in skus_a] == [s.name for s in skus_b]

    def test_different_seeds_give_different_output(self):
        skus_a = generate_sku_catalog(num_skus=20, seed=1)
        skus_b = generate_sku_catalog(num_skus=20, seed=2)
        # At least some field should differ
        assert [s.baseline_daily_demand for s in skus_a] != [
            s.baseline_daily_demand for s in skus_b
        ]

    def test_categories_are_diverse(self):
        skus = generate_sku_catalog(num_skus=50)
        categories = {s.category for s in skus}
        assert len(categories) >= 5, "Expected at least 5 categories represented"

    def test_stock_scenarios_include_all_risk_levels(self):
        """Verify the generator produces healthy, warning, and critical stock positions."""
        skus = generate_sku_catalog(num_skus=50, seed=42)
        covers = [s.days_of_cover for s in skus]
        assert any(c > 14 for c in covers), "No healthy stock positions"
        assert any(7 <= c <= 14 for c in covers), "No warning zone positions"
        assert any(c < 7 for c in covers), "No critical stock positions"

    def test_viral_sensitivity_in_range(self):
        skus = generate_sku_catalog(num_skus=50)
        for s in skus:
            assert 0.0 <= s.viral_sensitivity <= 5.0

    def test_baseline_demand_positive(self):
        skus = generate_sku_catalog(num_skus=50)
        assert all(s.baseline_daily_demand > 0 for s in skus)

    def test_smaller_catalog(self):
        skus = generate_sku_catalog(num_skus=5)
        assert len(skus) == 5


# ---------------------------------------------------------------------------
# Video Generator
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestVideoGenerator:
    @pytest.fixture
    def sku_ids(self):
        skus = generate_sku_catalog(num_skus=20, seed=42)
        return [s.sku_id for s in skus]

    def test_returns_correct_count(self, sku_ids):
        videos = generate_videos(sku_ids=sku_ids, num_videos=50)
        assert len(videos) == 50

    def test_all_are_video_records(self, sku_ids):
        videos = generate_videos(sku_ids=sku_ids, num_videos=10)
        assert all(isinstance(v, VideoRecord) for v in videos)

    def test_video_ids_are_unique(self, sku_ids):
        videos = generate_videos(sku_ids=sku_ids, num_videos=50)
        ids = [v.video_id for v in videos]
        assert len(ids) == len(set(ids))

    def test_reproducible_with_same_seed(self, sku_ids):
        videos_a = generate_videos(sku_ids=sku_ids, num_videos=20, seed=42)
        videos_b = generate_videos(sku_ids=sku_ids, num_videos=20, seed=42)
        assert [v.video_id for v in videos_a] == [v.video_id for v in videos_b]

    def test_platforms_are_diverse(self, sku_ids):
        videos = generate_videos(sku_ids=sku_ids, num_videos=100, seed=42)
        platforms = {v.platform for v in videos}
        assert platforms == {Platform.TIKTOK, Platform.INSTAGRAM, Platform.YOUTUBE}

    def test_viral_videos_are_minority(self, sku_ids):
        """Viral videos should be <30% of the dataset."""
        videos = generate_videos(sku_ids=sku_ids, num_videos=200, seed=42)
        viral_pct = sum(1 for v in videos if v.is_viral) / len(videos)
        assert viral_pct < 0.30, f"Too many viral videos: {viral_pct:.1%}"

    def test_all_videos_have_at_least_one_sku(self, sku_ids):
        videos = generate_videos(sku_ids=sku_ids, num_videos=50)
        assert all(len(v.sku_ids) >= 1 for v in videos)

    def test_all_sku_ids_are_valid(self, sku_ids):
        sku_set = set(sku_ids)
        videos = generate_videos(sku_ids=sku_ids, num_videos=50)
        for v in videos:
            for sid in v.sku_ids:
                assert sid in sku_set, f"Unknown SKU {sid} in video {v.video_id}"


# ---------------------------------------------------------------------------
# Engagement Event Generator
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEngagementEventGenerator:
    @pytest.fixture
    def sample_video_and_map(self):
        skus = generate_sku_catalog(num_skus=10, seed=42)
        sku_ids = [s.sku_id for s in skus]
        sku_map = {s.sku_id: s.viral_sensitivity for s in skus}
        videos = generate_videos(sku_ids=sku_ids, num_videos=5, seed=42)
        return videos[0], sku_map

    def test_returns_correct_snapshot_count(self, sample_video_and_map):
        video, sku_map = sample_video_and_map
        events = generate_engagement_events(
            video=video, sku_sensitivity_map=sku_map, snapshot_hours=48
        )
        assert len(events) == 48

    def test_all_are_engagement_events(self, sample_video_and_map):
        video, sku_map = sample_video_and_map
        events = generate_engagement_events(
            video=video, sku_sensitivity_map=sku_map, snapshot_hours=48
        )
        assert all(isinstance(e, EngagementEvent) for e in events)

    def test_event_ids_are_unique(self, sample_video_and_map):
        video, sku_map = sample_video_and_map
        events = generate_engagement_events(
            video=video, sku_sensitivity_map=sku_map, snapshot_hours=48
        )
        ids = [e.event_id for e in events]
        assert len(ids) == len(set(ids))

    def test_view_count_is_non_decreasing(self, sample_video_and_map):
        video, sku_map = sample_video_and_map
        events = generate_engagement_events(
            video=video, sku_sensitivity_map=sku_map, snapshot_hours=48
        )
        view_counts = [e.view_count for e in events]
        for i in range(1, len(view_counts)):
            assert view_counts[i] >= view_counts[i - 1], (
                f"View count decreased at hour {i}: {view_counts[i - 1]} → {view_counts[i]}"
            )

    def test_hours_since_post_is_sequential(self, sample_video_and_map):
        video, sku_map = sample_video_and_map
        events = generate_engagement_events(
            video=video, sku_sensitivity_map=sku_map, snapshot_hours=48
        )
        assert [e.hours_since_post for e in events] == list(range(48))

    def test_demand_lift_24h_is_set(self, sample_video_and_map):
        """demand_lift_24h should be populated for all historical events."""
        video, sku_map = sample_video_and_map
        events = generate_engagement_events(
            video=video, sku_sensitivity_map=sku_map, snapshot_hours=48
        )
        assert all(e.demand_lift_24h is not None for e in events)

    def test_demand_lift_positive(self, sample_video_and_map):
        video, sku_map = sample_video_and_map
        events = generate_engagement_events(
            video=video, sku_sensitivity_map=sku_map, snapshot_hours=48
        )
        assert all(e.demand_lift_24h > 0 for e in events)

    def test_rates_in_bounds(self, sample_video_and_map):
        video, sku_map = sample_video_and_map
        events = generate_engagement_events(
            video=video, sku_sensitivity_map=sku_map, snapshot_hours=48
        )
        for e in events:
            assert 0 <= e.save_rate <= 1
            assert 0 <= e.share_rate <= 1
            assert 0 <= e.click_rate <= 1
            assert 0 <= e.cart_rate <= 1
            assert 0 <= e.like_rate <= 1

    def test_snapshot_at_is_after_posted_at(self, sample_video_and_map):
        video, sku_map = sample_video_and_map
        events = generate_engagement_events(
            video=video, sku_sensitivity_map=sku_map, snapshot_hours=48
        )
        for e in events:
            assert e.snapshot_at >= e.posted_at

    def test_viral_video_has_higher_peak_views(self):
        """On average, viral videos should have more views than non-viral."""
        skus = generate_sku_catalog(num_skus=10, seed=42)
        sku_map = {s.sku_id: s.viral_sensitivity for s in skus}
        sku_ids = [s.sku_id for s in skus]

        # Generate enough videos to get at least a few viral/non-viral
        videos = generate_videos(sku_ids=sku_ids, num_videos=100, seed=1)
        viral_videos = [v for v in videos if v.is_viral][:5]
        nonviral_videos = [v for v in videos if not v.is_viral][:5]

        assert viral_videos and nonviral_videos, "Need both viral and non-viral videos"

        def peak_views(vids):
            total = 0
            for v in vids:
                events = generate_engagement_events(v, sku_map, snapshot_hours=48)
                total += max(e.view_count for e in events)
            return total / len(vids)

        avg_viral = peak_views(viral_videos)
        avg_nonviral = peak_views(nonviral_videos)
        assert avg_viral > avg_nonviral, (
            f"Viral avg views {avg_viral:.0f} not greater than non-viral {avg_nonviral:.0f}"
        )


# ---------------------------------------------------------------------------
# Bridge Generator
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestVideoSKUBridgeGenerator:
    def test_bridge_count_matches_total_tags(self):
        skus = generate_sku_catalog(num_skus=20, seed=42)
        sku_ids = [s.sku_id for s in skus]
        videos = generate_videos(sku_ids=sku_ids, num_videos=20, seed=42)
        bridges = generate_video_sku_bridges(videos)
        expected = sum(len(v.sku_ids) for v in videos)
        assert len(bridges) == expected

    def test_bridge_video_ids_match_videos(self):
        skus = generate_sku_catalog(num_skus=10, seed=42)
        sku_ids = [s.sku_id for s in skus]
        videos = generate_videos(sku_ids=sku_ids, num_videos=10, seed=42)
        bridges = generate_video_sku_bridges(videos)
        video_id_set = {v.video_id for v in videos}
        assert all(b.video_id in video_id_set for b in bridges)
