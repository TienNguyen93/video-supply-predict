from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import duckdb
import pytest

from src.agents.graph import run_pipeline_for_at_risk_skus
from src.config import settings
from src.features.velocity import enrich_events_dataframe
from src.ingestion.generators.sku_generator import generate_sku_catalog
from src.ingestion.generators.video_generator import (
    generate_engagement_events,
    generate_video_sku_bridges,
    generate_videos,
)
from src.ingestion.loader import DuckDBLoader
from src.models.score import main as run_scoring
from src.models.train import train_models


@pytest.mark.integration
def test_end_to_end_pipeline(tmp_db_path: Path):
    """
    Verify the entire pipeline integration:
    1. Seed small synthetic dataset into temporary DuckDB
    2. Run dbt locally to compile intermediate tables and marts
    3. Train LightGBM quantile models
    4. Run scoring/inference
    5. Run LangGraph agents triage and action PO generation
    """
    # Override settings path
    settings.duckdb_path = tmp_db_path

    # Set DUCKDB_PATH in env so dbt picks it up
    os.environ["DUCKDB_PATH"] = str(tmp_db_path)

    # 1. Seed small synthetic dataset
    skus = generate_sku_catalog(num_skus=5, seed=42)
    sku_ids = [s.sku_id for s in skus]
    sku_sensitivity_map = {s.sku_id: s.viral_sensitivity for s in skus}

    videos = generate_videos(sku_ids=sku_ids, num_videos=10, seed=42)
    bridges = generate_video_sku_bridges(videos)

    all_events = []
    for video in videos:
        events = generate_engagement_events(
            video=video,
            sku_sensitivity_map=sku_sensitivity_map,
            snapshot_hours=24,
            seed_offset=42000,
        )
        all_events.extend(events)

    with DuckDBLoader(db_path=str(tmp_db_path)) as loader:
        loader.initialise_schema()
        loader.load_skus(skus)
        loader.load_videos(videos)
        loader.load_bridges(bridges)
        loader.load_events(all_events)

        raw_df = loader._con.execute("SELECT * FROM raw.engagement_events").df()
        enriched_df = enrich_events_dataframe(raw_df)  # noqa: F841
        loader._con.execute(
            "CREATE OR REPLACE TABLE raw.engagement_events_enriched AS SELECT * FROM enriched_df"
        )

    # 2. Run dbt run via subprocess
    # Run dbt compile/run on the test database
    dbt_run = subprocess.run(
        ["dbt", "run", "--project-dir", "dbt", "--profiles-dir", "dbt"],
        capture_output=True,
        text=True,
    )
    assert dbt_run.returncode == 0, f"dbt run failed:\n{dbt_run.stdout}\n{dbt_run.stderr}"

    # 3. Train LightGBM model
    # Mock MLflow logging to run locally and offline if MLflow server is down
    local_mlruns = settings.project_root / "mlruns"
    local_uri = f"file:///{local_mlruns.as_posix()}"
    with patch("src.models.train.get_mlflow_tracking_uri", return_value=local_uri):
        train_models()

    # Verify model file was saved locally
    model_pickle = settings.project_root / "data" / "models" / "quantile_models.pkl"
    assert model_pickle.exists(), "Quantile model pickle not found after training"

    # 4. Run model scoring
    # Force scorer to load the fallback local pickle model we just trained
    with patch("mlflow.pyfunc.load_model", side_effect=Exception("MLflow offline")):
        run_scoring()

    # Force a SKU to be at-risk to ensure the agent pipeline triggers
    con = duckdb.connect(str(tmp_db_path))
    con.execute(
        """
        UPDATE marts.mart_sku_risk
        SET p10_demand_lift = 1.1,
            p50_demand_lift = 1.8,
            p90_demand_lift = 2.5,
            current_stock = 10,
            supplier_lead_time_days = 5
        WHERE sku_id = 'SKU-0001'
        """
    )
    con.close()

    # Verify that predictions columns are populated and not all null
    con = duckdb.connect(str(tmp_db_path))
    scored_videos = con.execute(
        "SELECT p10_demand_lift, p50_demand_lift, p90_demand_lift FROM marts.mart_scored_videos"
    ).df()
    assert len(scored_videos) > 0
    assert not scored_videos["p90_demand_lift"].isna().all()

    # 5. Run LangGraph agent triage
    # Mock Groq API calls to avoid hitting rate limits or requiring real keys during testing
    settings.groq_api_key = "dummy-key"

    mock_investigation_response = """### Summary
Mocked investigation report. Product has high viral demand.

### Confidence Assessment
The model is very confident.

### Key Factors
- Main factor 1
- Main factor 2

### Historical Comparison
This is similar to other viral events."""

    mock_action_response = "Mocked PO draft content."

    with (
        patch("src.agents.investigation._call_groq", return_value=mock_investigation_response),
        patch("src.agents.action._call_groq", return_value=mock_action_response),
    ):
        run_pipeline_for_at_risk_skus()

    # Verify alerts table is populated
    alerts = con.execute(
        "SELECT sku_id, risk_tier, investigation_summary, action_draft "
        "FROM raw.agent_alerts WHERE sku_id = 'SKU-0001'"
    ).df()
    con.close()

    assert len(alerts) > 0
    assert "Mocked investigation report" in alerts.iloc[0]["investigation_summary"]
