"""
Healthcheck router.
Provides endpoint for checking system status, database connection, and model loading.
"""

from __future__ import annotations

import duckdb
import structlog
from fastapi import APIRouter, HTTPException

from src.config import settings
from src.models.score import Scorer

log = structlog.get_logger(__name__)
router = APIRouter()


@router.get("/health")
def get_health() -> dict[str, str]:
    """
    Check system health by validating DuckDB accessibility and Scorer model load status.
    Returns 200 if OK, raises 500 otherwise.
    """
    # 1. Test DuckDB Connection
    try:
        con = duckdb.connect(str(settings.duckdb_path))
        # Simple query to check the DB is readable
        con.execute("SELECT 1")
        con.close()
    except Exception as e:
        log.error("Health check failed: DuckDB connection error", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Database connection failed: {e}",
        ) from e

    # 2. Test Scorer Model Loading
    try:
        scorer = Scorer()
        model_load_type = scorer.load_type
    except Exception as e:
        log.error("Health check failed: Scorer initialization error", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Model scorer failed to initialize: {e}",
        ) from e

    return {
        "status": "healthy",
        "database": "connected",
        "model_load_type": model_load_type,
    }
