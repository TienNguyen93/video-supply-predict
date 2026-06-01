"""
LangGraph graph wiring — defines the 3-node agentic pipeline.

Graph: triage_node → (conditional) → investigation_node → action_node → END

The triage node is the entry point. If risk is CRITICAL or WARNING,
the graph continues to investigation and action. Otherwise it ends early.

Usage:
    from src.agents.graph import run_pipeline
    result = run_pipeline(sku_risk_input)
"""

from __future__ import annotations

import duckdb
import structlog

from src.agents.action import action_node
from src.agents.investigation import investigation_node
from src.agents.state import (
    AgentState,
    RiskTier,
    SKURiskInput,
)
from src.agents.triage import triage_node
from src.config import settings

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Conditional routing
# ---------------------------------------------------------------------------
def _should_investigate(state: AgentState) -> str:
    """
    Router: decide whether to proceed to investigation or end.
    Returns the name of the next node.
    """
    if state.triage and state.triage.should_continue:
        return "investigation"
    return "end"


# ---------------------------------------------------------------------------
# Graph definition using simple sequential execution
# ---------------------------------------------------------------------------
# Note: We use a simple function-based pipeline rather than the full
# langgraph StateGraph API to keep dependencies minimal and testable.
# The flow is: triage → (conditional) → investigation → action → END
# ---------------------------------------------------------------------------


def run_pipeline(sku_input: SKURiskInput) -> AgentState:
    """
    Execute the 3-node agentic pipeline for a single SKU.

    Flow:
        1. Triage (pure logic) — classify risk tier
        2. If CRITICAL/WARNING: Investigation (Groq) — analyze context
        3. If CRITICAL/WARNING: Action (Groq) — draft PO or alert
        4. Persist alert to DuckDB

    Returns the final AgentState with all node outputs populated.
    """
    log.info("pipeline: starting", sku_id=sku_input.sku_id)

    # Initialize state
    state = AgentState(sku_input=sku_input)

    # Node 1: Triage
    state = triage_node(state)

    # Conditional routing
    next_step = _should_investigate(state)
    if next_step == "end":
        log.info(
            "pipeline: ending after triage (no escalation needed)",
            sku_id=sku_input.sku_id,
            risk_tier=state.triage.risk_tier.value if state.triage else "UNKNOWN",
        )
        return state

    # Node 2: Investigation
    state = investigation_node(state)

    # Node 3: Action
    state = action_node(state)

    log.info(
        "pipeline: complete",
        sku_id=sku_input.sku_id,
        risk_tier=state.triage.risk_tier.value if state.triage else "UNKNOWN",
        action_type=state.action.action_type.value if state.action else "none",
        alert_id=state.alert_id,
        llm_calls=state.llm_calls,
        errors=len(state.errors),
    )

    return state


# ---------------------------------------------------------------------------
# Batch processing — run pipeline for all at-risk SKUs
# ---------------------------------------------------------------------------
def run_pipeline_for_at_risk_skus() -> list[AgentState]:
    """
    Fetch all SKUs with ML risk tier CRITICAL or WARNING from DuckDB,
    and run the agentic pipeline for each.

    Called by the Airflow hourly pipeline after scoring completes.
    Returns list of pipeline results.
    """
    import yaml

    with open(settings.risk_thresholds_path, encoding="utf-8") as f:
        thresholds = yaml.safe_load(f)

    trigger_threshold = thresholds.get("agent_trigger_lift_threshold", 1.5)

    con = duckdb.connect(str(settings.duckdb_path))
    try:
        at_risk_skus = con.execute(
            """
            SELECT
                sku_id,
                sku_name,
                category,
                current_stock,
                baseline_daily_demand,
                supplier_lead_time_days,
                unit_price_usd,
                p10_demand_lift,
                p50_demand_lift,
                p90_demand_lift,
                active_video_count,
                max_engagement_score
            FROM marts.mart_sku_risk
            WHERE p90_demand_lift IS NOT NULL
              AND p90_demand_lift >= ?
            ORDER BY p90_demand_lift DESC
            """,
            (trigger_threshold,),
        ).df()
    except Exception as e:
        log.error("failed to fetch at-risk SKUs", error=str(e))
        con.close()
        return []

    # Fetch top video IDs per SKU for context
    top_videos_by_sku: dict[str, list[str]] = {}
    try:
        video_rows = con.execute(
            """
            SELECT sku_ids_json, video_id, p90_demand_lift
            FROM marts.mart_scored_videos
            WHERE p90_demand_lift IS NOT NULL
            ORDER BY p90_demand_lift DESC
            """
        ).df()
        for _, row in video_rows.iterrows():
            import json

            try:
                sku_ids = json.loads(row["sku_ids_json"])
                for sid in sku_ids:
                    if sid not in top_videos_by_sku:
                        top_videos_by_sku[sid] = []
                    if len(top_videos_by_sku[sid]) < 5:
                        top_videos_by_sku[sid].append(row["video_id"])
            except Exception:
                continue
    except Exception as e:
        log.warning("could not fetch top videos", error=str(e))

    con.close()

    if at_risk_skus.empty:
        log.info("no at-risk SKUs found above trigger threshold", threshold=trigger_threshold)
        return []

    log.info("processing at-risk SKUs", count=len(at_risk_skus))

    results: list[AgentState] = []
    for _, row in at_risk_skus.iterrows():
        sku_input = SKURiskInput(
            sku_id=row["sku_id"],
            sku_name=row["sku_name"],
            category=row["category"],
            current_stock=int(row["current_stock"]),
            baseline_daily_demand=float(row["baseline_daily_demand"]),
            supplier_lead_time_days=int(row["supplier_lead_time_days"]),
            unit_price_usd=float(row.get("unit_price_usd", 0.0)),
            p10_demand_lift=float(row["p10_demand_lift"]),
            p50_demand_lift=float(row["p50_demand_lift"]),
            p90_demand_lift=float(row["p90_demand_lift"]),
            active_video_count=int(row.get("active_video_count", 0)),
            max_engagement_score=float(row.get("max_engagement_score", 0.0)),
            top_video_ids=top_videos_by_sku.get(row["sku_id"], []),
        )
        result = run_pipeline(sku_input)
        results.append(result)

    log.info(
        "batch pipeline complete",
        total_skus=len(results),
        critical=sum(1 for r in results if r.triage and r.triage.risk_tier == RiskTier.CRITICAL),
        warning=sum(1 for r in results if r.triage and r.triage.risk_tier == RiskTier.WARNING),
    )

    return results


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------
def main() -> None:
    """Run the agentic pipeline for all at-risk SKUs."""
    results = run_pipeline_for_at_risk_skus()
    for r in results:
        tier = r.triage.risk_tier.value if r.triage else "UNKNOWN"
        action = r.action.action_type.value if r.action else "none"
        print(f"  {r.sku_input.sku_id}: {tier} → {action} (alert: {r.alert_id})")


if __name__ == "__main__":
    main()
