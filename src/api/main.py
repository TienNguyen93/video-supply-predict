"""
FastAPI application entrypoint.
Initialises the API, registers middleware, maps healthcheck endpoints, and mounts routers.
"""

from __future__ import annotations

import duckdb
import structlog
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from src.api.routers import alerts, health, scores, skus, videos
from src.config import settings
from src.models.score import Scorer

log = structlog.get_logger(__name__)

# Initialize FastAPI application
app = FastAPI(
    title="Serene Hypatia Replenishment API",
    description="Backend API for viral short-video demand signals and replenishment alerts",
    version="1.0.0",
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for dev/docker microservice communication
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["system"])
def root_healthcheck() -> dict[str, str]:
    """
    Health check endpoint at root level to satisfy Docker Compose healthchecks.
    Checks database connection and model scorer status.
    """
    try:
        con = duckdb.connect(str(settings.duckdb_path))
        con.execute("SELECT 1")
        con.close()
    except Exception as e:
        log.error("Root health check failed: DuckDB connection error", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Database connection failed: {e}",
        ) from e

    try:
        scorer = Scorer()
        model_load_type = scorer.load_type
    except Exception as e:
        log.error("Root health check failed: Scorer initialization error", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Model scorer failed to initialize: {e}",
        ) from e

    return {
        "status": "healthy",
        "database": "connected",
        "model_load_type": model_load_type,
    }


# Register v1 API routers
app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(scores.router, prefix="/api/v1", tags=["scores"])
app.include_router(alerts.router, prefix="/api/v1", tags=["alerts"])
app.include_router(videos.router, prefix="/api/v1", tags=["videos"])
app.include_router(skus.router, prefix="/api/v1", tags=["skus"])


@app.get("/")
def read_root() -> dict[str, str]:
    """API root message."""
    return {"message": "Welcome to the Serene Hypatia Replenishment API. Use /docs for Swagger UI."}
