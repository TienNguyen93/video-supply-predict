"""
Central configuration — single source of truth for all services.
All values can be overridden via environment variables or a .env file.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root — two levels up from this file (src/config.py → repo root)
PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # App
    # ------------------------------------------------------------------
    app_env: str = Field(default="development", description="development | staging | production")
    log_level: str = Field(default="INFO")
    project_root: Path = PROJECT_ROOT

    # ------------------------------------------------------------------
    # DuckDB
    # ------------------------------------------------------------------
    duckdb_path: Path = Field(
        default=PROJECT_ROOT / "data" / "warehouse.duckdb",
        description="Path to the DuckDB file (volume-mounted in Docker)",
    )

    # ------------------------------------------------------------------
    # MLflow
    # ------------------------------------------------------------------
    mlflow_tracking_uri: str = Field(
        default="http://mlflow:5000",
        description="MLflow tracking server URI",
    )
    mlflow_experiment_name: str = Field(default="demand-signal-quantile")
    mlflow_model_name: str = Field(default="demand-lift-lgbm")

    # ------------------------------------------------------------------
    # LLM — Groq
    # ------------------------------------------------------------------
    groq_api_key: str | None = Field(default=None)
    groq_model: str = Field(default="llama3-70b-8192")

    # ------------------------------------------------------------------
    # Slack
    # ------------------------------------------------------------------
    slack_webhook_url: str | None = Field(default=None)

    # ------------------------------------------------------------------
    # FastAPI
    # ------------------------------------------------------------------
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)
    api_workers: int = Field(default=2)

    # ------------------------------------------------------------------
    # Streamlit
    # ------------------------------------------------------------------
    streamlit_api_base_url: str = Field(
        default="http://fastapi:8000",
        description="Internal URL Streamlit uses to call the FastAPI service",
    )
    dashboard_refresh_interval_s: int = Field(default=60)

    # ------------------------------------------------------------------
    # Synthetic data
    # ------------------------------------------------------------------
    num_skus: int = Field(default=50)
    num_videos: int = Field(default=200)
    snapshot_hours: int = Field(default=48)
    random_seed: int = Field(default=42)

    # ------------------------------------------------------------------
    # Airflow
    # ------------------------------------------------------------------
    airflow_home: Path = Field(default=PROJECT_ROOT / "airflow_home")

    @field_validator("duckdb_path", "airflow_home", mode="before")
    @classmethod
    def _expand_path(cls, v: str | Path) -> Path:
        return Path(v).expanduser().resolve()

    @field_validator("app_env")
    @classmethod
    def _validate_env(cls, v: str) -> str:
        allowed = {"development", "staging", "production"}
        if v not in allowed:
            raise ValueError(f"app_env must be one of {allowed}")
        return v

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def groq_available(self) -> bool:
        return bool(self.groq_api_key)

    @property
    def slack_available(self) -> bool:
        return bool(self.slack_webhook_url)

    @property
    def configs_dir(self) -> Path:
        return self.project_root / "configs"

    @property
    def model_params_path(self) -> Path:
        return self.configs_dir / "model_params.yaml"

    @property
    def risk_thresholds_path(self) -> Path:
        return self.configs_dir / "risk_thresholds.yaml"


# ---------------------------------------------------------------------------
# Module-level singleton — import this everywhere
# ---------------------------------------------------------------------------
settings = Settings()
