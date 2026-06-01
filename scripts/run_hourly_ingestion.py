# ruff: noqa: E402
"""
Hourly Ingestion Simulation Script.
Simulates the arrival of the next hour's engagement snapshot for all active videos,
writes them to raw.engagement_events, and runs Python-side velocity feature enrichment.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure repo root is on sys.path
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import duckdb
import structlog

from src.config import settings
from src.features.velocity import enrich_events_dataframe
from src.ingestion.generators.video_generator import generate_engagement_events
from src.ingestion.loader import DuckDBLoader, events_to_dataframe
from src.ingestion.schemas import CreatorTier, Platform, VideoRecord

log = structlog.get_logger()


def ingest_next_hour() -> int:
    """Ingest next hourly snapshot for all videos. Returns count of new events."""
    db_path = str(settings.duckdb_path)
    con = duckdb.connect(db_path)

    # 1. Find max hour currently in DB per video
    try:
        max_hours = con.execute(
            "SELECT video_id, MAX(hours_since_post) FROM raw.engagement_events GROUP BY video_id"
        ).fetchall()
        max_hour_map = dict(max_hours)
    except Exception:
        max_hour_map = {}

    # 2. Get SKU sensitivities
    try:
        sku_rows = con.execute("SELECT sku_id, viral_sensitivity FROM raw.sku_catalog").fetchall()
        sku_sensitivity_map = dict(sku_rows)
    except Exception as e:
        log.error("Failed to read SKU sensitivities", error=str(e))
        con.close()
        return 0

    # 3. Get all videos
    try:
        video_rows = con.execute("SELECT * FROM raw.video_metadata").df()
    except Exception as e:
        log.error("Failed to read video metadata", error=str(e))
        con.close()
        return 0

    con.close()

    new_events = []
    for _, row in video_rows.iterrows():
        vid_id = row["video_id"]
        next_hour = max_hour_map.get(vid_id, -1) + 1
        if next_hour >= 48:
            # Already completed 48h simulation for this video
            continue

        video = VideoRecord(
            video_id=vid_id,
            platform=Platform(row["platform"]),
            creator_id=row["creator_id"],
            creator_tier=CreatorTier(row["creator_tier"]),
            posted_at=row["posted_at"],
            video_duration_s=int(row["video_duration_s"]),
            has_link_in_bio=bool(row["has_link_in_bio"]),
            sku_ids=json.loads(row["sku_ids_json"]),
            region_codes=json.loads(row["region_codes_json"]),
            is_viral=bool(row["is_viral"]),
        )

        all_evts = generate_engagement_events(
            video=video,
            sku_sensitivity_map=sku_sensitivity_map,
            snapshot_hours=48,
            seed_offset=settings.random_seed * 1000,
        )
        if next_hour < len(all_evts):
            new_events.append(all_evts[next_hour])

    if not new_events:
        log.info("Simulation complete: all videos have reached maximum snapshot hours (48h).")
        return 0

    log.info("Loading new hourly events into DuckDB", count=len(new_events))

    # 4. Insert into DuckDB and run feature enrichment
    with DuckDBLoader(db_path=db_path) as loader:
        df = events_to_dataframe(new_events)  # noqa: F841
        loader._con.execute("INSERT OR REPLACE INTO raw.engagement_events SELECT * FROM df")

        log.info("Running velocity feature enrichment on full engagement table...")
        raw_df = loader._con.execute("SELECT * FROM raw.engagement_events").df()
        enriched_df = enrich_events_dataframe(raw_df)

        loader._con.execute("""
            CREATE OR REPLACE TABLE raw.engagement_events_enriched AS
            SELECT * FROM enriched_df
        """)
        log.info("Feature enrichment completed", enriched_rows=len(enriched_df))

    return len(new_events)


if __name__ == "__main__":
    count = ingest_next_hour()
    print(f"Ingested {count} new hourly snapshots.")

