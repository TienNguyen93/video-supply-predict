"""
LangGraph state schema and type definitions for the agentic pipeline.

The graph processes SKU risk events through three nodes:
  1. Triage (pure logic) — classifies risk tier and routes
  2. Investigation (Groq LLM) — generates context-rich analysis
  3. Action (Groq LLM) — drafts PO or alert card for human review
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class RiskTier(StrEnum):
    """Risk classification tiers — evaluated in precedence order."""

    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    WATCH = "WATCH"
    NORMAL = "NORMAL"


class ActionType(StrEnum):
    """Actions the pipeline can recommend."""

    DRAFT_PURCHASE_ORDER = "draft_purchase_order"
    DRAFT_ALERT = "draft_alert"
    LOG_AND_RECHECK = "log_and_recheck"
    NONE = "none"


class SKURiskInput(BaseModel):
    """Input payload for the agentic pipeline — one SKU at a time."""

    sku_id: str
    sku_name: str
    category: str
    current_stock: int
    baseline_daily_demand: float
    supplier_lead_time_days: int
    unit_price_usd: float = 0.0

    # ML predictions (from Scorer)
    p10_demand_lift: float
    p50_demand_lift: float
    p90_demand_lift: float

    # Engagement context
    active_video_count: int = 0
    max_engagement_score: float = 0.0
    top_video_ids: list[str] = Field(default_factory=list)

    # Computed
    days_of_cover: float = 0.0
    projected_stockout_days: float = 0.0


class TriageResult(BaseModel):
    """Output of the triage node."""

    risk_tier: RiskTier
    action_type: ActionType
    reasoning: str
    should_continue: bool  # True if CRITICAL or WARNING


class InvestigationResult(BaseModel):
    """Output of the investigation node."""

    summary: str  # Plain-language analysis
    confidence_assessment: str
    key_factors: list[str] = Field(default_factory=list)
    historical_comparison: str = ""


class ActionResult(BaseModel):
    """Output of the action node."""

    action_type: ActionType
    draft_content: str  # PO text or alert card markdown
    recommended_quantity: int | None = None
    estimated_cost_usd: float | None = None
    urgency_note: str = ""


class AgentState(BaseModel):
    """
    LangGraph state object — passed through all nodes.
    Each node reads from and writes to this shared state.
    """

    # --- Input ---
    sku_input: SKURiskInput

    # --- Node outputs ---
    triage: TriageResult | None = None
    investigation: InvestigationResult | None = None
    action: ActionResult | None = None

    # --- Metadata ---
    alert_id: str = ""
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
    errors: list[str] = Field(default_factory=list)
    llm_calls: int = 0  # Track rate limiting

    # --- Extra context for LLM prompts ---
    extra_context: dict[str, Any] = Field(default_factory=dict)
