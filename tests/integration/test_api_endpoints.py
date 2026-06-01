"""
Integration tests for the FastAPI layer.
Tests health checks, alert querying/updates, trending feeds, and trigger scoring.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import duckdb
import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.config import settings


@pytest.fixture(autouse=True)
def mock_mlflow_load() -> None:
    """Mock mlflow.pyfunc.load_model to raise an exception, forcing fallback to rule-based model."""
    with patch("mlflow.pyfunc.load_model", side_effect=Exception("MLflow offline for testing")):
        yield


@pytest.fixture(autouse=True)
def setup_test_db(tmp_db_path: Path):
    """
    Autouse fixture that overrides the settings.duckdb_path with the temp test DB,
    initializes schemas, creates tables, and seeds mock records.
    """
    orig_path = settings.duckdb_path
    settings.duckdb_path = tmp_db_path

    con = duckdb.connect(str(tmp_db_path))
    con.execute("CREATE SCHEMA IF NOT EXISTS raw;")
    con.execute("CREATE SCHEMA IF NOT EXISTS marts;")

    # Drop existing tables to ensure clean state per test
    con.execute("DROP TABLE IF EXISTS raw.agent_alerts;")
    con.execute("DROP TABLE IF EXISTS marts.mart_alert_queue;")
    con.execute("DROP TABLE IF EXISTS marts.mart_sku_risk;")
    con.execute("DROP TABLE IF EXISTS marts.mart_trending_videos;")

    # 1. Create raw.agent_alerts
    con.execute(
        """
        CREATE TABLE raw.agent_alerts (
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
    )

    # 2. Create marts.mart_alert_queue
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS marts.mart_alert_queue (
            alert_id               VARCHAR PRIMARY KEY,
            sku_id                 VARCHAR NOT NULL,
            sku_name               VARCHAR,
            category               VARCHAR,
            unit_price_usd         DOUBLE,
            days_of_cover          DOUBLE,
            inventory_risk_tier    VARCHAR,
            current_stock          INTEGER,
            supplier_lead_time_days INTEGER,
            active_video_count     INTEGER,
            has_viral_video        BOOLEAN,
            alert_risk_tier        VARCHAR,
            p10_demand_lift        DOUBLE,
            p50_demand_lift        DOUBLE,
            p90_demand_lift        DOUBLE,
            investigation_summary  VARCHAR,
            action_draft           VARCHAR,
            status                 VARCHAR NOT NULL,
            approved_at            TIMESTAMPTZ,
            approved_by            VARCHAR,
            created_at             TIMESTAMPTZ,
            updated_at             TIMESTAMPTZ
        );
        """
    )

    # 3. Create marts.mart_sku_risk
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS marts.mart_sku_risk (
            sku_id                 VARCHAR PRIMARY KEY,
            sku_name               VARCHAR NOT NULL,
            category               VARCHAR NOT NULL,
            unit_price_usd         DOUBLE NOT NULL,
            baseline_daily_demand  DOUBLE NOT NULL,
            current_stock          INTEGER NOT NULL,
            supplier_lead_time_days INTEGER NOT NULL,
            reorder_point          INTEGER NOT NULL,
            days_of_cover          DOUBLE NOT NULL,
            is_below_reorder       BOOLEAN NOT NULL,
            inventory_risk_tier    VARCHAR NOT NULL,
            viral_sensitivity      DOUBLE NOT NULL,
            active_video_count     INTEGER NOT NULL,
            max_view_count         INTEGER,
            max_engagement_score   DOUBLE,
            avg_engagement_score   DOUBLE,
            demand_pressure_proxy  DOUBLE,
            has_viral_video        BOOLEAN NOT NULL,
            urgency_score          DOUBLE NOT NULL,
            p10_demand_lift        DOUBLE,
            p50_demand_lift        DOUBLE,
            p90_demand_lift        DOUBLE,
            ml_risk_tier           VARCHAR,
            projected_stockout_days DOUBLE,
            latest_alert_id        VARCHAR,
            alert_status           VARCHAR,
            refreshed_at           TIMESTAMPTZ
        );
        """
    )

    # 4. Create marts.mart_trending_videos
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS marts.mart_trending_videos (
            video_id               VARCHAR PRIMARY KEY,
            platform               VARCHAR NOT NULL,
            creator_id             VARCHAR NOT NULL,
            creator_tier           VARCHAR NOT NULL,
            sku_ids_json           VARCHAR NOT NULL,
            total_views            INTEGER NOT NULL,
            save_rate_pct          DOUBLE NOT NULL,
            share_rate_pct         DOUBLE NOT NULL,
            click_rate_pct         DOUBLE NOT NULL,
            cart_rate_pct          DOUBLE NOT NULL,
            engagement_score       DOUBLE NOT NULL,
            engagement_tier        VARCHAR NOT NULL,
            views_velocity_3h      DOUBLE,
            views_acceleration     DOUBLE,
            is_on_foryou           BOOLEAN NOT NULL,
            age_label              VARCHAR NOT NULL,
            hours_observed         INTEGER NOT NULL,
            posted_at              TIMESTAMPTZ,
            last_snapshot_at       TIMESTAMPTZ,
            is_viral               BOOLEAN NOT NULL,
            p50_demand_lift        DOUBLE,
            p90_demand_lift        DOUBLE,
            risk_tier_predicted    VARCHAR,
            rank                   INTEGER NOT NULL,
            mart_refreshed_at      TIMESTAMPTZ
        );
        """
    )

    # Seed mock data
    con.execute(
        """
        INSERT INTO raw.agent_alerts (alert_id, sku_id, risk_tier, status, action_draft)
        VALUES ('alert_1', 'SKU_1', 'CRITICAL', 'PENDING', 'Draft Purchase Order content');
        """
    )

    con.execute(
        """
        INSERT INTO marts.mart_alert_queue (
            alert_id, sku_id, sku_name, alert_risk_tier, status, action_draft
        ) VALUES (
            'alert_1', 'SKU_1', 'Test SKU 1', 'CRITICAL', 'PENDING', 'Draft Purchase Order content'
        );
        """
    )

    con.execute(
        """
        INSERT INTO marts.mart_sku_risk (
            sku_id, sku_name, category, unit_price_usd, baseline_daily_demand, current_stock,
            supplier_lead_time_days, reorder_point, days_of_cover, is_below_reorder,
            inventory_risk_tier, viral_sensitivity, active_video_count, has_viral_video,
            urgency_score, ml_risk_tier
        ) VALUES (
            'SKU_1', 'Test SKU 1', 'beauty', 10.0, 5.0, 50, 7, 20, 10.0, false, 'NORMAL',
            1.2, 0, false, 1.0, 'NORMAL'
        );
        """
    )

    con.execute(
        """
        INSERT INTO marts.mart_trending_videos (
            video_id, platform, creator_id, creator_tier, sku_ids_json, total_views,
            save_rate_pct, share_rate_pct, click_rate_pct, cart_rate_pct, engagement_score,
            engagement_tier, is_on_foryou, age_label, hours_observed, is_viral, rank
        ) VALUES (
            'vid_1', 'tiktok', 'creator_1', 'micro', '["SKU_1"]', 1000,
            1.2, 2.5, 4.0, 0.8, 0.12, 'HIGH', true, '12 hours', 12, false, 1
        );
        """
    )

    con.close()

    yield

    settings.duckdb_path = orig_path


class TestFastAPILayer:
    """Integration tests for all FastAPI endpoints."""

    @pytest.mark.integration
    def test_root_and_healthchecks(self) -> None:
        """Verify root and health check endpoints work."""
        client = TestClient(app)

        # 1. Test root "/"
        resp = client.get("/")
        assert resp.status_code == 200
        assert "message" in resp.json()

        # 2. Test root "/health" (used by Docker Compose)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"

        # 3. Test API v1 "/api/v1/health"
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"

    @pytest.mark.integration
    def test_alerts_listing_and_filtering(self) -> None:
        """Verify alerts listing and query parameter filtering."""
        client = TestClient(app)

        # Retrieve all alerts
        resp = client.get("/api/v1/alerts")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["alert_id"] == "alert_1"

        # Filter by status
        resp = client.get("/api/v1/alerts?status=PENDING")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

        resp = client.get("/api/v1/alerts?status=APPROVED")
        assert resp.status_code == 200
        assert len(resp.json()) == 0

        # Filter by risk_tier
        resp = client.get("/api/v1/alerts?risk_tier=CRITICAL")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    @pytest.mark.integration
    def test_alerts_approve_lifecycle(self) -> None:
        """Verify alert approval flow and validation checks."""
        client = TestClient(app)

        # 1. Approve PENDING alert
        resp = client.post("/api/v1/alerts/alert_1/approve?approved_by=ops_user")
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

        # Check status updated in DB
        con = duckdb.connect(str(settings.duckdb_path))
        status = con.execute(
            "SELECT status, approved_by FROM raw.agent_alerts WHERE alert_id = 'alert_1'"
        ).fetchone()
        assert status[0] == "APPROVED"
        assert status[1] == "ops_user"
        con.close()

        # 2. Re-approving should fail
        resp = client.post("/api/v1/alerts/alert_1/approve")
        assert resp.status_code == 400

        # 3. Approving non-existent alert should fail
        resp = client.post("/api/v1/alerts/invalid_id/approve")
        assert resp.status_code == 404

    @pytest.mark.integration
    def test_alerts_reject_lifecycle(self) -> None:
        """Verify alert rejection flow."""
        client = TestClient(app)

        # 1. Reject PENDING alert
        resp = client.post("/api/v1/alerts/alert_1/reject")
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

        # Check status updated in DB to DISMISSED
        con = duckdb.connect(str(settings.duckdb_path))
        status = con.execute(
            "SELECT status FROM raw.agent_alerts WHERE alert_id = 'alert_1'"
        ).fetchone()
        assert status[0] == "DISMISSED"
        con.close()

        # 2. Rejecting non-existent alert should fail
        resp = client.post("/api/v1/alerts/invalid_id/reject")
        assert resp.status_code == 404

    @pytest.mark.integration
    def test_videos_feed(self) -> None:
        """Verify retrieving trending videos feed."""
        client = TestClient(app)
        resp = client.get("/api/v1/videos/trending")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["video_id"] == "vid_1"

    @pytest.mark.integration
    def test_skus_risk_data(self) -> None:
        """Verify retrieving SKU inventory risk tiers."""
        client = TestClient(app)

        resp = client.get("/api/v1/skus/risk")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["sku_id"] == "SKU_1"

        # Filter by tier
        resp = client.get("/api/v1/skus/risk?ml_risk_tier=NORMAL")
        assert len(resp.json()) == 1

        resp = client.get("/api/v1/skus/risk?ml_risk_tier=CRITICAL")
        assert len(resp.json()) == 0

    @pytest.mark.integration
    @patch("src.api.routers.scores.Scorer")
    def test_trigger_scoring(self, mock_scorer_class: MagicMock) -> None:
        """Verify POST /score instantiates Scorer and triggers scoring pipelines."""
        mock_scorer = MagicMock()
        mock_scorer.score_unpredicted_videos.return_value = 10
        mock_scorer_class.return_value = mock_scorer

        client = TestClient(app)
        resp = client.post("/api/v1/score")

        assert resp.status_code == 200
        assert resp.json()["status"] == "success"
        assert resp.json()["scored_videos_count"] == 10
        mock_scorer.score_unpredicted_videos.assert_called_once()
        mock_scorer.update_sku_risk_table.assert_called_once()
