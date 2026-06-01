"""
Action node — Groq-powered PO drafting and alert card generation.

Depending on the triage result:
  - CRITICAL → drafts a Purchase Order with quantity = P90 demand × EOQ
  - WARNING  → drafts a Slack alert card with key numbers + recommendation
  - WATCH/NORMAL → no action (should not reach this node)

All outputs require human approval — the agent never acts autonomously.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime

import duckdb
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.agents.state import ActionResult, ActionType, AgentState, RiskTier
from src.config import settings

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Rate-limited Groq call
# ---------------------------------------------------------------------------
@retry(
    retry=retry_if_exception_type((Exception,)),
    wait=wait_exponential(multiplier=2, min=4, max=60),
    stop=stop_after_attempt(5),
    reraise=True,
)
def _call_groq(prompt: str) -> str:
    """Call Groq API with rate limiting and retries."""
    import time

    time.sleep(2.0)  # Rate limiting safety delay to avoid exceeding RPM
    from langchain_groq import ChatGroq

    llm = ChatGroq(  # type: ignore[call-arg]
        model=settings.groq_model,
        api_key=settings.groq_api_key,
        temperature=0.2,
        max_tokens=1024,
        request_timeout=30,
    )

    response = llm.invoke(prompt)
    content = response.content
    if not isinstance(content, str):
        raise TypeError("Expected string response from LLM")
    return content


# ---------------------------------------------------------------------------
# EOQ calculation
# ---------------------------------------------------------------------------
def _calculate_order_quantity(
    baseline_daily_demand: float,
    p90_lift: float,
    lead_time_days: int,
    current_stock: int,
    safety_stock_days: int = 3,
) -> int:
    """
    Calculate recommended order quantity using a simplified EOQ approach.

    Quantity = (P90 daily demand × (lead_time + safety_buffer)) - current_stock
    Minimum order = 1 unit.
    """
    p90_daily = baseline_daily_demand * p90_lift
    cover_days = lead_time_days + safety_stock_days
    target_stock = math.ceil(p90_daily * cover_days)
    order_qty = max(target_stock - current_stock, 1)
    return order_qty


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------
def _build_po_prompt(state: AgentState, order_qty: int, est_cost: float) -> str:
    """Build the PO drafting prompt for CRITICAL tier."""
    sku = state.sku_input
    inv = state.investigation

    return f"""You are a supply chain operations assistant. \
Draft a Purchase Order memo for urgent approval.

## Situation
{inv.summary if inv else "N/A"}

## SKU Details
- **SKU**: {sku.sku_id} — {sku.sku_name}
- **Category**: {sku.category}
- **Current Stock**: {sku.current_stock:,} units
- **Days of Cover**: {sku.days_of_cover:.1f} days (under P90 scenario)
- **Supplier Lead Time**: {sku.supplier_lead_time_days} days

## ML Predictions
- P10: {sku.p10_demand_lift:.2f}x | P50: {sku.p50_demand_lift:.2f}x
- P90: {sku.p90_demand_lift:.2f}x

## Recommended Order
- **Quantity**: {order_qty:,} units
- **Estimated Cost**: ${est_cost:,.2f}
- **Urgency**: CRITICAL — stock will deplete before standard replenishment

## Your Task
Draft a concise, professional Purchase Order memo (5-8 lines) that includes:
1. Subject line with SKU and urgency
2. Quantity and estimated cost
3. Justification referencing the demand spike prediction
4. Requested delivery timeline
5. Note that this requires human approval before submission

Keep it professional and actionable. No marketing language."""


def _build_alert_prompt(state: AgentState) -> str:
    """Build the alert card prompt for WARNING tier."""
    sku = state.sku_input
    inv = state.investigation

    return f"""You are a supply chain operations assistant. \
Draft a Slack alert card for human review.

## Situation
{inv.summary if inv else "N/A"}

## SKU Details
- **SKU**: {sku.sku_id} — {sku.sku_name}
- **Category**: {sku.category}
- **Current Stock**: {sku.current_stock:,} units
- **Days of Cover**: {sku.days_of_cover:.1f} days
- **Supplier Lead Time**: {sku.supplier_lead_time_days} days

## ML Predictions
- P10: {sku.p10_demand_lift:.2f}x | P50: {sku.p50_demand_lift:.2f}x
- P90: {sku.p90_demand_lift:.2f}x

## Key Factors
{chr(10).join(f"- {f}" for f in (inv.key_factors if inv else []))}

## Your Task
Draft a concise Slack alert message (4-6 lines) with:
1. 🟠 WARNING header with SKU name
2. Current stock situation vs predicted demand
3. Key risk factors (2-3 bullets)
4. Recommended action for the ops team
5. Deadline for review (4 hours)

Use Slack markdown formatting. Keep it scannable."""


# ---------------------------------------------------------------------------
# Fallback drafts (no LLM)
# ---------------------------------------------------------------------------
def _generate_fallback_po(state: AgentState, order_qty: int, est_cost: float) -> str:
    """Generate a structured PO without LLM."""
    sku = state.sku_input
    return (
        f"🔴 URGENT PURCHASE ORDER — {sku.sku_id} ({sku.sku_name})\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Quantity: {order_qty:,} units | Est. Cost: ${est_cost:,.2f}\n"
        f"Current Stock: {sku.current_stock:,} units "
        f"({sku.days_of_cover:.1f} days cover)\n"
        f"P90 Demand Lift: {sku.p90_demand_lift:.2f}x baseline\n"
        f"Lead Time: {sku.supplier_lead_time_days} days\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ REQUIRES HUMAN APPROVAL before submission to supplier.\n"
        f"Deadline: Immediate — stock projected to deplete before next order cycle."
    )


def _generate_fallback_alert(state: AgentState) -> str:
    """Generate a structured alert card without LLM."""
    sku = state.sku_input
    return (
        f"🟠 WARNING — Elevated Demand Risk: {sku.sku_id} ({sku.sku_name})\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• P90 Demand Lift: {sku.p90_demand_lift:.2f}x baseline\n"
        f"• Current Stock: {sku.current_stock:,} units "
        f"({sku.days_of_cover:.1f} days cover)\n"
        f"• Active Viral Videos: {sku.active_video_count}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 Action: Review within 4 hours. Consider expedited order if trend continues."
    )


# ---------------------------------------------------------------------------
# Slack notification
# ---------------------------------------------------------------------------
def _send_slack_notification(message: str) -> bool:
    """Send a Slack notification if webhook URL is configured."""
    if not settings.slack_webhook_url:
        log.info("slack notification skipped — no webhook URL configured")
        return False

    import httpx

    try:
        resp = httpx.post(
            settings.slack_webhook_url,
            json={"text": message},
            timeout=10.0,
        )
        resp.raise_for_status()
        log.info("slack notification sent successfully")
        return True
    except Exception as e:
        log.warning("slack notification failed", error=str(e))
        return False


# ---------------------------------------------------------------------------
# DuckDB alert persistence
# ---------------------------------------------------------------------------
def _persist_alert(state: AgentState) -> str:
    """Insert alert into raw.agent_alerts and return the alert_id."""
    alert_id = f"alert_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    sku = state.sku_input
    triage = state.triage
    investigation = state.investigation
    action = state.action

    try:
        con = duckdb.connect(str(settings.duckdb_path))
        con.execute(
            """
            INSERT INTO raw.agent_alerts (
                alert_id, sku_id, risk_tier,
                p10_demand_lift, p50_demand_lift, p90_demand_lift,
                investigation_summary, action_draft, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')
            """,
            (
                alert_id,
                sku.sku_id,
                triage.risk_tier.value if triage else "UNKNOWN",
                sku.p10_demand_lift,
                sku.p50_demand_lift,
                sku.p90_demand_lift,
                investigation.summary if investigation else "",
                action.draft_content if action else "",
            ),
        )
        con.close()
        log.info("alert persisted to DuckDB", alert_id=alert_id, sku_id=sku.sku_id)
    except Exception as e:
        log.error("failed to persist alert", error=str(e), sku_id=sku.sku_id)
        # Don't fail the pipeline — the alert is still generated in memory
        state.errors.append(f"Alert persistence failed: {e}")

    return alert_id


# ---------------------------------------------------------------------------
# Action node
# ---------------------------------------------------------------------------
def action_node(state: AgentState) -> AgentState:
    """
    Action node: draft PO or alert card based on triage result.

    CRITICAL → Purchase Order with EOQ quantity
    WARNING  → Slack alert card
    All outputs are PENDING human approval.
    """
    sku = state.sku_input
    triage = state.triage
    log.info(
        "action_node: starting",
        sku_id=sku.sku_id,
        risk_tier=triage.risk_tier.value if triage else "UNKNOWN",
    )

    if triage and triage.risk_tier == RiskTier.CRITICAL:
        # Calculate order quantity
        order_qty = _calculate_order_quantity(
            baseline_daily_demand=sku.baseline_daily_demand,
            p90_lift=sku.p90_demand_lift,
            lead_time_days=sku.supplier_lead_time_days,
            current_stock=sku.current_stock,
        )
        est_cost = order_qty * sku.unit_price_usd

        # Draft PO
        if settings.groq_available:
            try:
                prompt = _build_po_prompt(state, order_qty, est_cost)
                draft_content = _call_groq(prompt)
                state.llm_calls += 1
            except Exception as e:
                log.warning("action_node: groq PO draft failed", error=str(e))
                draft_content = _generate_fallback_po(state, order_qty, est_cost)
                state.errors.append(f"Action LLM failed: {e}")
        else:
            draft_content = _generate_fallback_po(state, order_qty, est_cost)

        result = ActionResult(
            action_type=ActionType.DRAFT_PURCHASE_ORDER,
            draft_content=draft_content,
            recommended_quantity=order_qty,
            estimated_cost_usd=est_cost,
            urgency_note="IMMEDIATE — stock depletion imminent under P90 scenario",
        )

    elif triage and triage.risk_tier == RiskTier.WARNING:
        # Draft alert card
        if settings.groq_available:
            try:
                prompt = _build_alert_prompt(state)
                draft_content = _call_groq(prompt)
                state.llm_calls += 1
            except Exception as e:
                log.warning("action_node: groq alert draft failed", error=str(e))
                draft_content = _generate_fallback_alert(state)
                state.errors.append(f"Action LLM failed: {e}")
        else:
            draft_content = _generate_fallback_alert(state)

        result = ActionResult(
            action_type=ActionType.DRAFT_ALERT,
            draft_content=draft_content,
            urgency_note="Review within 4 hours — demand trend accelerating",
        )

    else:
        # WATCH or NORMAL — should not reach action node, but handle gracefully
        result = ActionResult(
            action_type=ActionType.LOG_AND_RECHECK,
            draft_content="No action required — monitoring engagement trend.",
        )

    state.action = result

    # Persist alert to DuckDB
    alert_id = _persist_alert(state)
    state.alert_id = alert_id
    state.completed_at = datetime.utcnow()

    # Send Slack notification for CRITICAL/WARNING
    if triage and triage.risk_tier in (RiskTier.CRITICAL, RiskTier.WARNING):
        slack_msg = (
            f"{'🔴' if triage.risk_tier == RiskTier.CRITICAL else '🟠'} "
            f"*{triage.risk_tier.value}* — {sku.sku_id} ({sku.sku_name})\n"
            f"P90 Lift: {sku.p90_demand_lift:.2f}x | "
            f"Stock: {sku.current_stock:,} units | "
            f"Cover: {sku.days_of_cover:.1f}d\n"
            f"Alert ID: {alert_id}"
        )
        _send_slack_notification(slack_msg)

    log.info(
        "action_node: complete",
        sku_id=sku.sku_id,
        action_type=result.action_type.value,
        alert_id=alert_id,
    )

    return state
