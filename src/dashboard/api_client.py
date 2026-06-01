"""
API Client for Streamlit dashboard.
Fetches data from FastAPI backend and provides local-development fallback.
"""

from __future__ import annotations

import socket

import httpx
import structlog

from src.config import settings

log = structlog.get_logger(__name__)


class APIClient:
    """Decoupled client to communicate with FastAPI endpoints."""

    def __init__(self) -> None:
        self.base_url = self._resolve_base_url()
        log.info("APIClient initialized", resolved_url=self.base_url)

    def _resolve_base_url(self) -> str:
        """Dynamically fall back to localhost if fastapi host is not resolvable."""
        url = settings.streamlit_api_base_url
        if "fastapi:" in url:
            try:
                # Fast hostname resolution check
                socket.gethostbyname("fastapi")
            except socket.gaierror:
                # Fallback to localhost for local testing
                fallback_url = url.replace("fastapi:", "localhost:")
                log.info(
                    "fastapi host unreachable, falling back to localhost",
                    original=url,
                    fallback=fallback_url,
                )
                return fallback_url
        return url

    def _get_client(self) -> httpx.Client:
        """Create a client with timeouts."""
        return httpx.Client(base_url=self.base_url, timeout=10.0)

    def check_health(self) -> dict | None:
        """Fetch system health info."""
        try:
            with self._get_client() as client:
                resp = client.get("/api/v1/health")
                if resp.status_code == 200:
                    return resp.json()
        except Exception as e:
            log.warning("API: health check failed", error=str(e))
        return None

    def fetch_alerts(self, status: str | None = None, risk_tier: str | None = None) -> list[dict]:
        """Fetch all alerts, optionally filtered."""
        try:
            params = {}
            if status:
                params["status"] = status
            if risk_tier:
                params["risk_tier"] = risk_tier

            with self._get_client() as client:
                resp = client.get("/api/v1/alerts", params=params)
                if resp.status_code == 200:
                    return resp.json()
        except Exception as e:
            log.error("API: failed to fetch alerts", error=str(e))
        return []

    def approve_alert(self, alert_id: str, approved_by: str = "ops_manager") -> bool:
        """Approve a pending alert."""
        try:
            with self._get_client() as client:
                resp = client.post(
                    f"/api/v1/alerts/{alert_id}/approve",
                    params={"approved_by": approved_by},
                )
                if resp.status_code == 200:
                    return True
                log.error(
                    "API: failed to approve alert",
                    status_code=resp.status_code,
                    body=resp.text,
                )
        except Exception as e:
            log.error("API: approve alert request failed", error=str(e))
        return False

    def reject_alert(self, alert_id: str) -> bool:
        """Reject/dismiss an alert."""
        try:
            with self._get_client() as client:
                resp = client.post(f"/api/v1/alerts/{alert_id}/reject")
                if resp.status_code == 200:
                    return True
                log.error(
                    "API: failed to reject alert",
                    status_code=resp.status_code,
                    body=resp.text,
                )
        except Exception as e:
            log.error("API: reject alert request failed", error=str(e))
        return False

    def fetch_trending_videos(self) -> list[dict]:
        """Fetch latest trending videos."""
        try:
            with self._get_client() as client:
                resp = client.get("/api/v1/videos/trending")
                if resp.status_code == 200:
                    return resp.json()
        except Exception as e:
            log.error("API: failed to fetch trending videos", error=str(e))
        return []

    def fetch_sku_risk(self, ml_risk_tier: str | None = None) -> list[dict]:
        """Fetch SKU inventory risk tiers."""
        try:
            params = {}
            if ml_risk_tier:
                params["ml_risk_tier"] = ml_risk_tier

            with self._get_client() as client:
                resp = client.get("/api/v1/skus/risk", params=params)
                if resp.status_code == 200:
                    return resp.json()
        except Exception as e:
            log.error("API: failed to fetch SKU risk data", error=str(e))
        return []

    def trigger_scoring(self) -> dict | None:
        """Trigger models scoring pipeline."""
        try:
            with self._get_client() as client:
                resp = client.post("/api/v1/score")
                if resp.status_code == 200:
                    return resp.json()
                log.error(
                    "API: failed to trigger scoring",
                    status_code=resp.status_code,
                    body=resp.text,
                )
        except Exception as e:
            log.error("API: trigger scoring request failed", error=str(e))
        return None
