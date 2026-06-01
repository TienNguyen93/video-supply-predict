"""
MLflow model registry manager.
Handles transitions between model stages (Production, Staging, Archived).
"""

from __future__ import annotations

import structlog
from mlflow.tracking import MlflowClient

log = structlog.get_logger()


def promote_model_to_production(model_name: str, version: int | str) -> bool:
    """
    Promote a specific model version to the "Production" stage in MLflow registry,
    and archive any existing production models.
    """
    try:
        # Initialise MLflow client
        # If remote server is unreachable, MlflowClient will use the current set tracking URI
        client = MlflowClient()

        # Parse version to int if possible
        v_str = str(version)

        log.info(
            "Promoting model version to Production",
            model_name=model_name,
            version=v_str,
        )

        # Transition the requested version to Production
        client.transition_model_version_stage(
            name=model_name,
            version=v_str,
            stage="Production",
            archive_existing_versions=True,  # Automatically archives older Production versions
        )

        log.info(
            "Model promoted successfully",
            model_name=model_name,
            version=v_str,
            stage="Production",
        )
        return True

    except Exception as e:
        log.error(
            "Failed to promote model in registry",
            model_name=model_name,
            version=version,
            error=str(e),
        )
        return False


def get_latest_production_version(model_name: str) -> str | None:
    """
    Retrieve the version number of the model currently in the "Production" stage.
    Returns None if no model is in Production.
    """
    try:
        client = MlflowClient()
        latest_versions = client.get_latest_versions(model_name, stages=["Production"])
        if latest_versions:
            return latest_versions[0].version
    except Exception as e:
        log.warning(
            "Failed to check production version in registry",
            model_name=model_name,
            error=str(e),
        )
    return None


def promote_latest_model_version(model_name: str) -> bool:
    """Find the latest registered version of a model and promote it to Production."""
    try:
        client = MlflowClient()
        # Fetch latest versions across stages
        versions = client.get_latest_versions(
            model_name, stages=["None", "Staging", "Archived", "Production"]
        )
        if not versions:
            log.warning("No registered model versions found to promote", model_name=model_name)
            return False
        latest_version = max(int(v.version) for v in versions)
        return promote_model_to_production(model_name, latest_version)
    except Exception as e:
        log.error("Failed to promote latest model version", model_name=model_name, error=str(e))
        return False
