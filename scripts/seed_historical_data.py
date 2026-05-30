"""
Seed script — generates synthetic data and loads it into DuckDB.

Usage:
    python scripts/seed_historical_data.py [--skus N] [--videos N] [--hours N] [--seed N]

This script:
  1. Generates a SKU catalog (default: 50 SKUs)
  2. Generates video metadata (default: 200 videos)
  3. Generates 48 hourly engagement snapshots per video
  4. Loads all data into DuckDB (raw schema)
  5. Runs Python-side feature enrichment and writes enriched events back

Runtime: ~15–30 seconds for the default 200×48 = 9,600 events.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Ensure repo root is on sys.path when run as a script
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import argparse

import structlog

from src.config import settings
from src.ingestion.generators.sku_generator import generate_sku_catalog
from src.ingestion.generators.video_generator import (
    generate_engagement_events,
    generate_video_sku_bridges,
    generate_videos,
)
from src.ingestion.loader import DuckDBLoader
from src.features.velocity import enrich_events_dataframe

# Configure structlog for human-readable CLI output
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="%H:%M:%S"),
        structlog.dev.ConsoleRenderer(),
    ]
)
log = structlog.get_logger()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed serene-hypatia with synthetic data")
    parser.add_argument("--skus",   type=int, default=settings.num_skus,    help="Number of SKUs")
    parser.add_argument("--videos", type=int, default=settings.num_videos,   help="Number of videos")
    parser.add_argument("--hours",  type=int, default=settings.snapshot_hours, help="Snapshots per video")
    parser.add_argument("--seed",   type=int, default=settings.random_seed,  help="Random seed")
    parser.add_argument("--db",     type=str, default=str(settings.duckdb_path), help="DuckDB file path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    t0 = time.perf_counter()

    log.info(
        "Starting seed",
        skus=args.skus,
        videos=args.videos,
        hours=args.hours,
        seed=args.seed,
        db=args.db,
    )

    # ------------------------------------------------------------------ #
    # 1. Generate SKU catalog
    # ------------------------------------------------------------------ #
    log.info("Generating SKU catalog...")
    skus = generate_sku_catalog(num_skus=args.skus, seed=args.seed)
    log.info("SKU catalog generated", count=len(skus))

    # Build lookup maps for downstream use
    sku_ids = [s.sku_id for s in skus]
    sku_sensitivity_map = {s.sku_id: s.viral_sensitivity for s in skus}

    # ------------------------------------------------------------------ #
    # 2. Generate video metadata
    # ------------------------------------------------------------------ #
    log.info("Generating video metadata...")
    videos = generate_videos(sku_ids=sku_ids, num_videos=args.videos, seed=args.seed)
    viral_count = sum(1 for v in videos if v.is_viral)
    log.info(
        "Videos generated",
        total=len(videos),
        viral=viral_count,
        viral_pct=f"{viral_count / len(videos) * 100:.1f}%",
    )

    # Video–SKU bridge
    bridges = generate_video_sku_bridges(videos)

    # ------------------------------------------------------------------ #
    # 3. Generate hourly engagement snapshots
    # ------------------------------------------------------------------ #
    log.info("Generating engagement snapshots (this may take a moment)...")
    all_events = []
    for i, video in enumerate(videos):
        events = generate_engagement_events(
            video=video,
            sku_sensitivity_map=sku_sensitivity_map,
            snapshot_hours=args.hours,
            seed_offset=args.seed * 1000,
        )
        all_events.extend(events)

        if (i + 1) % 50 == 0:
            log.info("Progress", videos_processed=i + 1, events_so_far=len(all_events))

    log.info("Engagement snapshots generated", total=len(all_events))

    # ------------------------------------------------------------------ #
    # 4. Load into DuckDB
    # ------------------------------------------------------------------ #
    log.info("Loading data into DuckDB...")
    with DuckDBLoader(db_path=args.db) as loader:
        loader.initialise_schema()
        loader.load_skus(skus)
        loader.load_videos(videos)
        loader.load_bridges(bridges)
        loader.load_events(all_events)

        # ------------------------------------------------------------------ #
        # 5. Enrich events with Python-side velocity features
        # ------------------------------------------------------------------ #
        log.info("Running velocity feature enrichment...")
        raw_df = loader._con.execute("SELECT * FROM raw.engagement_events").df()
        enriched_df = enrich_events_dataframe(raw_df)

        # Write enriched events to a separate table for dbt to pick up
        loader._con.execute("""
            CREATE OR REPLACE TABLE raw.engagement_events_enriched AS
            SELECT * FROM enriched_df
        """)
        log.info("Enriched events written", rows=len(enriched_df))

        # Print summary
        counts = loader.row_counts()

    # ------------------------------------------------------------------ #
    # 6. Summary
    # ------------------------------------------------------------------ #
    elapsed = time.perf_counter() - t0
    log.info("=" * 55)
    log.info("Seed complete", elapsed_s=f"{elapsed:.1f}s")
    log.info("DuckDB row counts:")
    for table, count in counts.items():
        log.info(f"  {table:45s} {count:>8,d} rows")
    log.info("=" * 55)
    log.info("Next step: run `make dbt-run` to transform raw -> marts")


if __name__ == "__main__":
    main()
