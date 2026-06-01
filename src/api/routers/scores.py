"""
Scores router.
Exposes endpoints to trigger the ML scoring and SKU risk update pipelines.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException

from src.models.score import Scorer

log = structlog.get_logger(__name__)
router = APIRouter()


@router.post("/score")
def trigger_scoring() -> dict[str, str | int]:
    """
    Trigger the model scoring pipeline to:
      1. Predict demand lifts on any unscored videos.
      2. Recompute SKU-level inventory risk positions and tiers.
    """
    try:
        log.info("API: triggering scoring pipeline")
        scorer = Scorer()
        scored_count = scorer.score_unpredicted_videos()
        scorer.update_sku_risk_table()

        log.info("API: scoring pipeline complete", scored_count=scored_count)
        return {
            "status": "success",
            "scored_videos_count": scored_count,
            "message": f"Successfully scored {scored_count} new videos and updated SKU risk tiers.",
        }
    except Exception as e:
        log.error("API: scoring execution failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Scoring pipeline execution failed: {e}",
        ) from e
