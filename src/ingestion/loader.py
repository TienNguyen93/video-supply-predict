"""
DuckDB ingestion loader.

Writes generated records to the raw schema in DuckDB.
Three tables are created / replaced:
  - raw.sku_catalog          : one row per SKU
  - raw.video_metadata       : one row per video
  - raw.video_sku_bridge     : normalised video ↔ SKU mapping
  - raw.engagement_events    : one row per (video, hour) snapshot

Design notes:
  - Uses pandas DataFrames as the intermediary (fast DuckDB ↔ pandas connector).
  - sku_ids and region_codes are stored as JSON strings for broad compatibility;
    dbt staging models will cast them to arrays as needed.
  - All writes are transactional (DuckDB auto-commits on connection close).
  - The loader is idempotent: re-running replaces existing raw tables.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb
import pandas as pd
import structlog

from src.ingestion.schemas import EngagementEvent, SKURecord, VideoRecord, VideoSKUBridge

if TYPE_CHECKING:
    pass

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_DDL_RAW_SCHEMA = "CREATE SCHEMA IF NOT EXISTS raw;"

_DDL_SKU_CATALOG = """
CREATE OR REPLACE TABLE raw.sku_catalog (
    sku_id                 VARCHAR PRIMARY KEY,
    name                   VARCHAR NOT NULL,
    category               VARCHAR NOT NULL,
    unit_price_usd         DOUBLE NOT NULL,
    baseline_daily_demand  DOUBLE NOT NULL,
    current_stock          INTEGER NOT NULL,
    supplier_lead_time_days INTEGER NOT NULL,
    reorder_point          INTEGER NOT NULL,
    viral_sensitivity      DOUBLE NOT NULL,
    created_at             TIMESTAMPTZ NOT NULL
);
"""

_DDL_VIDEO_METADATA = """
CREATE OR REPLACE TABLE raw.video_metadata (
    video_id           VARCHAR PRIMARY KEY,
    platform           VARCHAR NOT NULL,
    creator_id         VARCHAR NOT NULL,
    creator_tier       VARCHAR NOT NULL,
    posted_at          TIMESTAMPTZ NOT NULL,
    video_duration_s   INTEGER NOT NULL,
    has_link_in_bio    BOOLEAN NOT NULL,
    sku_ids_json       VARCHAR NOT NULL,      -- JSON array string
    region_codes_json  VARCHAR NOT NULL,      -- JSON array string
    is_viral           BOOLEAN NOT NULL
);
"""

_DDL_VIDEO_SKU_BRIDGE = """
CREATE OR REPLACE TABLE raw.video_sku_bridge (
    video_id   VARCHAR NOT NULL,
    sku_id     VARCHAR NOT NULL,
    platform   VARCHAR NOT NULL,
    posted_at  TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (video_id, sku_id)
);
"""

_DDL_ENGAGEMENT_EVENTS = """
CREATE OR REPLACE TABLE raw.engagement_events (
    event_id           VARCHAR PRIMARY KEY,
    video_id           VARCHAR NOT NULL,
    posted_at          TIMESTAMPTZ NOT NULL,
    snapshot_at        TIMESTAMPTZ NOT NULL,
    hours_since_post   INTEGER NOT NULL,
    platform           VARCHAR NOT NULL,
    creator_id         VARCHAR NOT NULL,
    creator_tier       VARCHAR NOT NULL,
    sku_ids_json       VARCHAR NOT NULL,      -- JSON array string
    video_duration_s   INTEGER NOT NULL,
    has_link_in_bio    BOOLEAN NOT NULL,
    view_count         INTEGER NOT NULL,
    like_count         INTEGER NOT NULL,
    comment_count      INTEGER NOT NULL,
    share_count        INTEGER NOT NULL,
    save_count         INTEGER NOT NULL,
    click_to_product   INTEGER NOT NULL,
    add_to_cart        INTEGER NOT NULL,
    save_rate          DOUBLE NOT NULL,
    share_rate         DOUBLE NOT NULL,
    click_rate         DOUBLE NOT NULL,
    cart_rate          DOUBLE NOT NULL,
    like_rate          DOUBLE NOT NULL,
    views_delta_1h     INTEGER NOT NULL,
    saves_delta_1h     INTEGER NOT NULL,
    shares_delta_1h    INTEGER NOT NULL,
    save_velocity      DOUBLE NOT NULL,
    is_on_foryou       BOOLEAN NOT NULL,
    trending_rank      INTEGER,               -- nullable
    region_codes_json  VARCHAR NOT NULL,      -- JSON array string
    demand_lift_24h    DOUBLE,                -- null during real-time inference
    is_viral           BOOLEAN NOT NULL
);
"""

_DDL_AGENT_ALERTS = """
CREATE TABLE IF NOT EXISTS raw.agent_alerts (
    alert_id               VARCHAR PRIMARY KEY,
    sku_id                 VARCHAR NOT NULL,
    risk_tier              VARCHAR NOT NULL,
    p10_demand_lift        DOUBLE,
    p50_demand_lift        DOUBLE,
    p90_demand_lift        DOUBLE,
    investigation_summary  VARCHAR,
    action_draft           VARCHAR,
    status                 VARCHAR NOT NULL DEFAULT 'PENDING',
    approved_at            TIMESTAMPTZ,
    approved_by            VARCHAR,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
);
"""

_ALL_DDL = [
    _DDL_RAW_SCHEMA,
    _DDL_SKU_CATALOG,
    _DDL_VIDEO_METADATA,
    _DDL_VIDEO_SKU_BRIDGE,
    _DDL_ENGAGEMENT_EVENTS,
    _DDL_AGENT_ALERTS,  # app-managed; CREATE IF NOT EXISTS (not OR REPLACE)
]


# ---------------------------------------------------------------------------
# DataFrame converters
# ---------------------------------------------------------------------------


def skus_to_dataframe(skus: list[SKURecord]) -> pd.DataFrame:
    """Convert SKURecord list to a pandas DataFrame matching raw.sku_catalog."""
    rows = []
    for s in skus:
        rows.append(
            {
                "sku_id": s.sku_id,
                "name": s.name,
                "category": s.category.value,
                "unit_price_usd": s.unit_price_usd,
                "baseline_daily_demand": s.baseline_daily_demand,
                "current_stock": s.current_stock,
                "supplier_lead_time_days": s.supplier_lead_time_days,
                "reorder_point": s.reorder_point,
                "viral_sensitivity": s.viral_sensitivity,
                "created_at": s.created_at,
            }
        )
    return pd.DataFrame(rows)


def videos_to_dataframe(videos: list[VideoRecord]) -> pd.DataFrame:
    """Convert VideoRecord list to a pandas DataFrame matching raw.video_metadata."""
    rows = []
    for v in videos:
        rows.append(
            {
                "video_id": v.video_id,
                "platform": v.platform.value,
                "creator_id": v.creator_id,
                "creator_tier": v.creator_tier.value,
                "posted_at": v.posted_at,
                "video_duration_s": v.video_duration_s,
                "has_link_in_bio": v.has_link_in_bio,
                "sku_ids_json": json.dumps(v.sku_ids),
                "region_codes_json": json.dumps(v.region_codes),
                "is_viral": v.is_viral,
            }
        )
    return pd.DataFrame(rows)


def bridges_to_dataframe(bridges: list[VideoSKUBridge]) -> pd.DataFrame:
    """Convert VideoSKUBridge list to a pandas DataFrame."""
    rows = []
    for b in bridges:
        rows.append(
            {
                "video_id": b.video_id,
                "sku_id": b.sku_id,
                "platform": b.platform.value,
                "posted_at": b.posted_at,
            }
        )
    return pd.DataFrame(rows)


def events_to_dataframe(events: list[EngagementEvent]) -> pd.DataFrame:
    """Convert EngagementEvent list to a pandas DataFrame matching raw.engagement_events."""
    rows = []
    for e in events:
        rows.append(
            {
                "event_id": e.event_id,
                "video_id": e.video_id,
                "posted_at": e.posted_at,
                "snapshot_at": e.snapshot_at,
                "hours_since_post": e.hours_since_post,
                "platform": e.platform.value,
                "creator_id": e.creator_id,
                "creator_tier": e.creator_tier.value,
                "sku_ids_json": json.dumps(e.sku_ids),
                "video_duration_s": e.video_duration_s,
                "has_link_in_bio": e.has_link_in_bio,
                "view_count": e.view_count,
                "like_count": e.like_count,
                "comment_count": e.comment_count,
                "share_count": e.share_count,
                "save_count": e.save_count,
                "click_to_product": e.click_to_product,
                "add_to_cart": e.add_to_cart,
                "save_rate": e.save_rate,
                "share_rate": e.share_rate,
                "click_rate": e.click_rate,
                "cart_rate": e.cart_rate,
                "like_rate": e.like_rate,
                "views_delta_1h": e.views_delta_1h,
                "saves_delta_1h": e.saves_delta_1h,
                "shares_delta_1h": e.shares_delta_1h,
                "save_velocity": e.save_velocity,
                "is_on_foryou": e.is_on_foryou,
                "trending_rank": e.trending_rank,
                "region_codes_json": json.dumps(e.region_codes),
                "demand_lift_24h": e.demand_lift_24h,
                "is_viral": e.is_viral,
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


class DuckDBLoader:
    """
    Manages DuckDB connections and batch-writes generated data to raw tables.

    Usage:
        loader = DuckDBLoader(db_path)
        loader.initialise_schema()
        loader.load_skus(skus)
        loader.load_videos(videos)
        loader.load_bridges(bridges)
        loader.load_events(events)
        loader.close()
    """

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._con: duckdb.DuckDBPyConnection = duckdb.connect(str(self.db_path))
        log.info("DuckDB connection opened", path=str(self.db_path))

    def initialise_schema(self) -> None:
        """Create raw schema and all tables (idempotent — uses CREATE OR REPLACE)."""
        for ddl in _ALL_DDL:
            self._con.execute(ddl)
        log.info("Raw schema initialised")

    def load_skus(self, skus: list[SKURecord]) -> int:
        """Write SKU records to raw.sku_catalog. Returns row count inserted."""
        if not skus:
            return 0
        df = skus_to_dataframe(skus)
        self._con.execute("INSERT OR REPLACE INTO raw.sku_catalog SELECT * FROM df")
        n = len(df)
        log.info("SKUs loaded", count=n)
        return n

    def load_videos(self, videos: list[VideoRecord]) -> int:
        """Write video records to raw.video_metadata."""
        if not videos:
            return 0
        df = videos_to_dataframe(videos)
        self._con.execute("INSERT OR REPLACE INTO raw.video_metadata SELECT * FROM df")
        n = len(df)
        log.info("Videos loaded", count=n)
        return n

    def load_bridges(self, bridges: list[VideoSKUBridge]) -> int:
        """Write video–SKU bridge records to raw.video_sku_bridge."""
        if not bridges:
            return 0
        df = bridges_to_dataframe(bridges)
        self._con.execute("INSERT OR REPLACE INTO raw.video_sku_bridge SELECT * FROM df")
        n = len(df)
        log.info("Video–SKU bridges loaded", count=n)
        return n

    def load_events(self, events: list[EngagementEvent], batch_size: int = 5_000) -> int:
        """
        Write engagement events to raw.engagement_events in batches.
        Batching prevents memory spikes for large datasets.
        """
        if not events:
            return 0
        total = 0
        for i in range(0, len(events), batch_size):
            batch = events[i : i + batch_size]
            df = events_to_dataframe(batch)  # noqa: F841
            self._con.execute("INSERT OR REPLACE INTO raw.engagement_events SELECT * FROM df")
            total += len(batch)
        log.info("Engagement events loaded", count=total)
        return total

    def row_counts(self) -> dict[str, int]:
        """Return row counts for all raw tables (useful for verification)."""
        tables = ["sku_catalog", "video_metadata", "video_sku_bridge", "engagement_events"]
        counts = {}
        for table in tables:
            result = self._con.execute(f"SELECT COUNT(*) FROM raw.{table}").fetchone()
            counts[f"raw.{table}"] = result[0] if result else 0
        return counts

    def close(self) -> None:
        self._con.close()
        log.info("DuckDB connection closed")

    def __enter__(self) -> DuckDBLoader:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
