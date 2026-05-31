"""
Unit tests for the risk tier calculator.
Verifies that classification rules match the parameters in configs/risk_thresholds.yaml.
"""

from __future__ import annotations

import yaml

from src.config import settings


# Helper function to compute risk tier following configs/risk_thresholds.yaml logic
def compute_risk_tier(
    p90_lift: float,
    days_of_cover: float,
    lead_time_days: int,
    thresholds_config: dict,
) -> str:
    tiers_config = thresholds_config["tiers"]

    # CRITICAL check
    crit_cond = tiers_config["CRITICAL"]["conditions"]
    crit_doc_max = crit_cond["days_cover_max"]
    crit_buffer = crit_cond["lead_time_buffer_days"]
    if p90_lift >= crit_cond["p90_lift_min"] and (
        days_of_cover < crit_doc_max or days_of_cover < (lead_time_days + crit_buffer)
    ):
        return "CRITICAL"

    # WARNING check
    warn_cond = tiers_config["WARNING"]["conditions"]
    warn_doc_max = warn_cond["days_cover_max"]
    warn_buffer = warn_cond["lead_time_buffer_days"]
    if p90_lift >= warn_cond["p90_lift_min"] and (
        days_of_cover < warn_doc_max or days_of_cover < (lead_time_days + warn_buffer)
    ):
        return "WARNING"

    # WATCH check
    watch_cond = tiers_config["WATCH"]["conditions"]
    watch_doc_max = watch_cond["days_cover_max"]
    if p90_lift >= watch_cond["p90_lift_min"] and days_of_cover < watch_doc_max:
        return "WATCH"

    return "NORMAL"


def test_risk_thresholds_logic():
    """Verify that mock scenarios are classified into correct risk tiers."""
    with open(settings.risk_thresholds_path, encoding="utf-8") as f:
        thresholds_config = yaml.safe_load(f)

    # 1. Test CRITICAL conditions
    # Scenario A: lift=3.5 (>=3.0), days_cover=5 (<7) -> CRITICAL
    assert compute_risk_tier(3.5, 5.0, 10, thresholds_config) == "CRITICAL"
    # Scenario B: lift=4.0 (>=3.0), days_cover=8, lead_time=10 (days_cover < lead_time) -> CRITICAL
    assert compute_risk_tier(4.0, 8.0, 10, thresholds_config) == "CRITICAL"

    # 2. Test WARNING conditions (if not CRITICAL)
    # Scenario C: lift=2.5 (>=2.0), days_cover=12 (<14) -> WARNING
    assert compute_risk_tier(2.5, 12.0, 15, thresholds_config) == "WARNING"
    # Scenario D: lift=2.1 (>=2.0), cover=15, lead_time=14 (cover < lead_time+2) -> WARNING
    assert compute_risk_tier(2.1, 15.0, 14, thresholds_config) == "WARNING"

    # 3. Test WATCH conditions
    # Scenario E: lift=1.8 (>=1.5), days_cover=25 (<30) -> WATCH
    assert compute_risk_tier(1.8, 25.0, 10, thresholds_config) == "WATCH"

    # 4. Test NORMAL conditions
    # Scenario F: lift=1.2 (<1.5), days_cover=20 -> NORMAL
    assert compute_risk_tier(1.2, 20.0, 5, thresholds_config) == "NORMAL"
    # Scenario G: lift=5.0, days_cover=40 (very comfortable stock) -> NORMAL
    assert compute_risk_tier(5.0, 40.0, 10, thresholds_config) == "NORMAL"


def test_trigger_lift_threshold():
    """Verify trigger lift threshold exists and is positive."""
    with open(settings.risk_thresholds_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    assert "agent_trigger_lift_threshold" in config
    assert config["agent_trigger_lift_threshold"] == 1.5
