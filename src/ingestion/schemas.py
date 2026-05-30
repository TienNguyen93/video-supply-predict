"""
Pydantic v2 data models for the ingestion layer.

Three core models:
  - SKURecord        : product catalog entry with inventory state
  - VideoRecord      : video metadata (platform, creator, tagged SKUs)
  - EngagementEvent  : hourly engagement snapshot tied to a single video

Derived models used for DuckDB writes:
  - VideoSKUBridge   : normalised video ↔ SKU mapping table
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class Platform(str, Enum):
    TIKTOK = "tiktok"
    INSTAGRAM = "instagram"
    YOUTUBE = "youtube"


class CreatorTier(str, Enum):
    NANO = "nano"      # < 10k followers
    MICRO = "micro"    # 10k – 100k
    MID = "mid"        # 100k – 500k
    MACRO = "macro"    # 500k – 1M
    MEGA = "mega"      # > 1M


class SKUCategory(str, Enum):
    APPAREL = "apparel"
    BEAUTY = "beauty"
    ELECTRONICS = "electronics"
    HOME = "home"
    FITNESS = "fitness"
    FOOD = "food"
    TOYS = "toys"
    ACCESSORIES = "accessories"


class RiskTier(str, Enum):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    WATCH = "WATCH"
    NORMAL = "NORMAL"


# ---------------------------------------------------------------------------
# SKU Catalog
# ---------------------------------------------------------------------------


class SKURecord(BaseModel):
    """A product in the catalog with inventory state and demand history."""

    sku_id: str = Field(..., description="Unique SKU identifier, e.g. SKU-0042")
    name: str = Field(..., description="Human-readable product name")
    category: SKUCategory
    unit_price_usd: Annotated[float, Field(gt=0)]
    baseline_daily_demand: Annotated[float, Field(gt=0, description="Average units sold per day (no viral event)")]
    current_stock: Annotated[int, Field(ge=0, description="Current on-hand units")]
    supplier_lead_time_days: Annotated[int, Field(gt=0, le=90)]
    reorder_point: Annotated[int, Field(ge=0, description="Stock level that triggers a reorder")]
    viral_sensitivity: Annotated[
        float,
        Field(ge=0.0, le=5.0, description="Multiplier: how much this SKU amplifies viral-driven demand (0=none, 5=extreme)"),
    ]
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def days_of_cover(self) -> float:
        """How many days current stock lasts at baseline demand."""
        if self.baseline_daily_demand == 0:
            return float("inf")
        return self.current_stock / self.baseline_daily_demand

    @property
    def is_below_reorder(self) -> bool:
        return self.current_stock <= self.reorder_point


# ---------------------------------------------------------------------------
# Video Metadata
# ---------------------------------------------------------------------------


class VideoRecord(BaseModel):
    """Metadata about a video post — static, does not change over time."""

    video_id: str = Field(..., description="Unique video identifier, e.g. vid_001")
    platform: Platform
    creator_id: str
    creator_tier: CreatorTier
    posted_at: datetime
    video_duration_s: Annotated[int, Field(gt=0, le=600)]
    has_link_in_bio: bool
    sku_ids: list[str] = Field(default_factory=list, description="SKUs tagged in this video")
    region_codes: list[str] = Field(default_factory=list, description="Target regions, e.g. ['US', 'GB']")
    is_viral: bool = Field(default=False)

    @field_validator("sku_ids")
    @classmethod
    def _sku_ids_not_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("A video must be tagged with at least one SKU")
        return v


# ---------------------------------------------------------------------------
# Video–SKU Bridge (normalised)
# ---------------------------------------------------------------------------


class VideoSKUBridge(BaseModel):
    """Normalised mapping: one row per (video_id, sku_id) pair."""

    video_id: str
    sku_id: str
    platform: Platform
    posted_at: datetime


# ---------------------------------------------------------------------------
# Hourly Engagement Snapshot
# ---------------------------------------------------------------------------


class EngagementEvent(BaseModel):
    """
    A single hourly snapshot of a video's engagement metrics.
    One video produces `snapshot_hours` rows in the raw.engagement_events table.
    """

    # --- Identity ---
    event_id: str = Field(..., description="Unique dedup key: evt_{date}_{video_id}_{hour:02d}h")
    video_id: str
    posted_at: datetime
    snapshot_at: datetime
    hours_since_post: Annotated[int, Field(ge=0)]

    # --- Content context (denormalised from VideoRecord for query convenience) ---
    platform: Platform
    creator_id: str
    creator_tier: CreatorTier
    sku_ids: list[str]
    video_duration_s: int
    has_link_in_bio: bool

    # --- Cumulative counts (since posting) ---
    view_count: Annotated[int, Field(ge=0)]
    like_count: Annotated[int, Field(ge=0)]
    comment_count: Annotated[int, Field(ge=0)]
    share_count: Annotated[int, Field(ge=0)]
    save_count: Annotated[int, Field(ge=0)]
    click_to_product: Annotated[int, Field(ge=0)]
    add_to_cart: Annotated[int, Field(ge=0)]

    # --- Rates (derived: count / views) ---
    save_rate: Annotated[float, Field(ge=0.0, le=1.0)]
    share_rate: Annotated[float, Field(ge=0.0, le=1.0)]
    click_rate: Annotated[float, Field(ge=0.0, le=1.0)]
    cart_rate: Annotated[float, Field(ge=0.0, le=1.0)]
    like_rate: Annotated[float, Field(ge=0.0, le=1.0)]

    # --- Velocity (delta since previous snapshot) ---
    views_delta_1h: Annotated[int, Field(ge=0)]
    saves_delta_1h: Annotated[int, Field(ge=0)]
    shares_delta_1h: Annotated[int, Field(ge=0)]
    save_velocity: Annotated[float, Field(ge=0.0)]  # save_rate based on this hour's delta

    # --- Platform signals ---
    is_on_foryou: bool  # TikTok FYP / Instagram Explore placement
    trending_rank: int | None = None
    region_codes: list[str]

    # --- Labels (training only; null in real-time inference) ---
    demand_lift_24h: float | None = Field(
        default=None,
        description="Actual demand multiplier vs baseline, observed 24h after posting. "
        "Available only in historical data; null during real-time scoring.",
    )
    is_viral: bool = False

    @model_validator(mode="after")
    def _validate_snapshot_after_post(self) -> "EngagementEvent":
        if self.snapshot_at < self.posted_at:
            raise ValueError("snapshot_at must be >= posted_at")
        return self

    @field_validator("sku_ids")
    @classmethod
    def _sku_ids_not_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("sku_ids must contain at least one SKU")
        return v
