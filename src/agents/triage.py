"""
Triage node — pure conditional logic, no LLM.

Evaluates P90 demand lift and inventory position against risk thresholds
to classify the SKU into a risk tier and route to the appropriate action.

Design decision: No LLM for triage — speed and auditability (see AGENTS.md).
"""

from __future__ import annotations

import structlog
import yaml

from src.agents.state import ActionType, AgentState, RiskTier, TriageResult
from src.config import settings

log = structlog.get_logger()


def _load_thresholds() -> dict:
    """Load risk thresholds from YAML config."""
    with open(settings.risk_thresholds_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def triage_node(state: AgentState) -> AgentState:
    """
    Pure-logic triage: classify SKU risk and decide routing.

    Rules (evaluated in precedence order):
      1. CRITICAL: P90 lift >= 3.0x AND days_cover < 7 (or < lead_time)
      2. WARNING:  P90 lift >= 2.0x AND days_cover < 14 (or < lead_time + 2)
      3. WATCH:    P90 lift >= 1.5x AND days_cover < 30
      4. NORMAL:   everything else
    """
    sku = state.sku_input
    thresholds = _load_thresholds()
    tiers_config = thresholds["tiers"]

    p90 = sku.p90_demand_lift
    effective_p90 = max(p90, 0.01)
    p90_daily_demand = sku.baseline_daily_demand * effective_p90
    days_cover = sku.current_stock / p90_daily_demand if p90_daily_demand > 0 else 9999
    lead_time = sku.supplier_lead_time_days

    log.info(
        "triage_node: evaluating",
        sku_id=sku.sku_id,
        p90_lift=p90,
        days_cover=round(days_cover, 1),
        lead_time=lead_time,
    )

    # --- CRITICAL ---
    crit = tiers_config["CRITICAL"]["conditions"]
    if p90 >= crit["p90_lift_min"] and (
        days_cover < crit["days_cover_max"]
        or days_cover < (lead_time + crit["lead_time_buffer_days"])
    ):
        risk_tier = RiskTier.CRITICAL
        action_type = ActionType.DRAFT_PURCHASE_ORDER
        reasoning = (
            f"P90 lift {p90:.2f}x exceeds {crit['p90_lift_min']}x threshold. "
            f"Days of cover ({days_cover:.1f}) < {crit['days_cover_max']} days "
            f"or < lead time ({lead_time}d). Immediate PO required."
        )

    # --- WARNING ---
    elif p90 >= tiers_config["WARNING"]["conditions"]["p90_lift_min"]:
        warn = tiers_config["WARNING"]["conditions"]
        if days_cover < warn["days_cover_max"] or days_cover < (
            lead_time + warn["lead_time_buffer_days"]
        ):
            risk_tier = RiskTier.WARNING
            action_type = ActionType.DRAFT_ALERT
            reasoning = (
                f"P90 lift {p90:.2f}x exceeds {warn['p90_lift_min']}x threshold. "
                f"Days of cover ({days_cover:.1f}) is tight. "
                f"Human review recommended within 4 hours."
            )
        else:
            risk_tier = RiskTier.WATCH
            action_type = ActionType.LOG_AND_RECHECK
            reasoning = (
                f"P90 lift {p90:.2f}x is elevated but inventory "
                f"({days_cover:.1f} days) is comfortable."
            )

    # --- WATCH ---
    elif p90 >= tiers_config["WATCH"]["conditions"]["p90_lift_min"]:
        watch = tiers_config["WATCH"]["conditions"]
        if days_cover < watch["days_cover_max"]:
            risk_tier = RiskTier.WATCH
            action_type = ActionType.LOG_AND_RECHECK
            reasoning = (
                f"P90 lift {p90:.2f}x above {watch['p90_lift_min']}x. "
                f"Monitoring — re-evaluate next cycle."
            )
        else:
            risk_tier = RiskTier.NORMAL
            action_type = ActionType.NONE
            reasoning = (
                f"P90 lift {p90:.2f}x with comfortable inventory ({days_cover:.1f} days cover)."
            )

    # --- NORMAL ---
    else:
        risk_tier = RiskTier.NORMAL
        action_type = ActionType.NONE
        reasoning = f"P90 lift {p90:.2f}x — no significant demand signal."

    should_continue = risk_tier in (RiskTier.CRITICAL, RiskTier.WARNING)

    triage_result = TriageResult(
        risk_tier=risk_tier,
        action_type=action_type,
        reasoning=reasoning,
        should_continue=should_continue,
    )

    log.info(
        "triage_node: result",
        sku_id=sku.sku_id,
        risk_tier=risk_tier.value,
        action_type=action_type.value,
        should_continue=should_continue,
    )

    state.triage = triage_result
    state.sku_input.days_of_cover = days_cover
    return state
