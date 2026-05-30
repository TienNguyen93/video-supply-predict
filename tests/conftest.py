"""
Shared pytest fixtures for the serene-hypatia test suite.
Provides: temporary DuckDB connection, sample engagement events, settings override.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest


# ---------------------------------------------------------------------------
# Settings override — point to a temp DuckDB during tests
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def tmp_db_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Return a path to a temporary DuckDB file for the test session."""
    base = tmp_path_factory.mktemp("data")
    return base / "test_warehouse.duckdb"


@pytest.fixture(scope="session")
def db_conn(tmp_db_path: Path) -> duckdb.DuckDBPyConnection:
    """Session-scoped DuckDB connection pointing to temp file."""
    con = duckdb.connect(str(tmp_db_path))
    con.execute("CREATE SCHEMA IF NOT EXISTS raw;")
    con.execute("CREATE SCHEMA IF NOT EXISTS staging;")
    con.execute("CREATE SCHEMA IF NOT EXISTS intermediate;")
    con.execute("CREATE SCHEMA IF NOT EXISTS marts;")
    yield con
    con.close()


# ---------------------------------------------------------------------------
# Sample data factories
# ---------------------------------------------------------------------------
@pytest.fixture
def sample_engagement_event() -> dict:
    """A single valid engagement event dict for use in unit tests."""
    return {
        "event_id": "evt_20240315_v001_h03",
        "video_id": "vid_001",
        "posted_at": "2024-03-15T00:00:00Z",
        "snapshot_at": "2024-03-15T03:00:00Z",
        "hours_since_post": 3,
        "platform": "tiktok",
        "creator_id": "creator_8821",
        "creator_tier": "micro",
        "sku_ids": ["SKU-0042", "SKU-0119"],
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
