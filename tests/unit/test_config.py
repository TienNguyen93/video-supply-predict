"""
Placeholder tests for Phase 1 scaffold.
Real tests are added in each feature phase.
"""

from __future__ import annotations

import pytest


@pytest.mark.unit
def test_settings_loads():
    """Config module imports without errors and has expected defaults."""
    from src.config import settings

    assert settings.app_env in {"development", "staging", "production"}
    assert settings.num_skus > 0
    assert settings.num_videos > 0
    assert settings.snapshot_hours > 0


@pytest.mark.unit
def test_settings_paths_exist():
    """Config paths reference files that exist in the repo."""
    from src.config import settings

    assert settings.configs_dir.exists(), f"configs/ dir not found at {settings.configs_dir}"
    assert settings.model_params_path.exists(), "configs/model_params.yaml missing"
    assert settings.risk_thresholds_path.exists(), "configs/risk_thresholds.yaml missing"
