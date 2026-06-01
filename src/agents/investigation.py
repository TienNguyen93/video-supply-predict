"""
Investigation node — Groq-powered analysis.

Generates a plain-language investigation summary explaining:
  - Why the demand spike is predicted
  - Confidence level and key driving factors
  - Historical comparison with similar viral events

Uses Groq (llama3-70b) with rate limiting via tenacity.
Gracefully degrades to a structured template if Groq is unavailable.
"""

from __future__ import annotations

import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.agents.state import AgentState, InvestigationResult
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
        temperature=0.3,
        max_tokens=1024,
        request_timeout=30,
    )

    response = llm.invoke(prompt)
    content = response.content
    if not isinstance(content, str):
        raise TypeError("Expected string response from LLM")
    return content


def _build_investigation_prompt(state: AgentState) -> str:
    """Build the investigation prompt from state context."""
    sku = state.sku_input
    triage = state.triage
    if triage is None:
        raise ValueError("Triage result is missing from state")

    return f"""You are a supply chain analyst investigating a potential demand spike.

## SKU Details
- **SKU**: {sku.sku_id} — {sku.sku_name}
- **Category**: {sku.category}
- **Current Stock**: {sku.current_stock:,} units
- **Baseline Daily Demand**: {sku.baseline_daily_demand:.1f} units/day
- **Supplier Lead Time**: {sku.supplier_lead_time_days} days
- **Days of Cover (P90 scenario)**: {sku.days_of_cover:.1f} days

## ML Predictions
- **P10 Demand Lift**: {sku.p10_demand_lift:.2f}x (conservative)
- **P50 Demand Lift**: {sku.p50_demand_lift:.2f}x (median)
- **P90 Demand Lift**: {sku.p90_demand_lift:.2f}x (worst-case)

## Triage Assessment
- **Risk Tier**: {triage.risk_tier.value}
- **Reasoning**: {triage.reasoning}

## Social Signal Context
- **Active Videos**: {sku.active_video_count}
- **Max Engagement Score**: {sku.max_engagement_score:.4f}
- **Top Video IDs**: {", ".join(sku.top_video_ids[:5]) if sku.top_video_ids else "N/A"}

## Your Task
Provide a concise investigation report with:
1. **Summary** (2-3 sentences): Why this spike is predicted and its likely magnitude
2. **Confidence Assessment** (1 sentence): How confident the model is based on signal strength
3. **Key Factors** (3-5 bullet points): The main drivers of this prediction
4. **Historical Comparison** (1-2 sentences): How this compares to typical viral product events

Keep the response factual and actionable. Focus on what operations managers need to know.
Format your response with clear section headers."""


def _parse_investigation_response(response: str) -> InvestigationResult:
    """Parse the LLM response into structured InvestigationResult."""
    # Extract sections from the response
    lines = response.strip().split("\n")
    summary_lines: list[str] = []
    confidence = ""
    key_factors: list[str] = []
    historical = ""

    current_section = ""
    for line in lines:
        stripped = line.strip()
        lower = stripped.lower()

        if "summary" in lower and ("**" in stripped or "#" in stripped):
            current_section = "summary"
            continue
        elif "confidence" in lower and ("**" in stripped or "#" in stripped):
            current_section = "confidence"
            continue
        elif "key factor" in lower and ("**" in stripped or "#" in stripped):
            current_section = "factors"
            continue
        elif "historical" in lower and ("**" in stripped or "#" in stripped):
            current_section = "historical"
            continue

        if not stripped:
            continue

        if current_section == "summary":
            summary_lines.append(stripped)
        elif current_section == "confidence":
            confidence += stripped + " "
        elif current_section == "factors":
            # Strip bullet markers
            clean = stripped.lstrip("-*•").strip()
            if clean:
                key_factors.append(clean)
        elif current_section == "historical":
            historical += stripped + " "

    return InvestigationResult(
        summary=" ".join(summary_lines) if summary_lines else response[:500],
        confidence_assessment=confidence.strip() or "Assessment not available.",
        key_factors=key_factors[:5],
        historical_comparison=historical.strip() or "No historical comparison available.",
    )


def _generate_fallback_investigation(state: AgentState) -> InvestigationResult:
    """Generate a structured investigation without LLM (graceful degradation)."""
    sku = state.sku_input
    triage = state.triage
    if triage is None:
        raise ValueError("Triage result is missing from state")

    lift_descriptor = "extreme" if sku.p90_demand_lift >= 3.0 else "significant"
    stock_status = (
        "dangerously low"
        if sku.days_of_cover < sku.supplier_lead_time_days
        else "below comfortable levels"
    )

    summary = (
        f"SKU {sku.sku_id} ({sku.sku_name}) is experiencing {lift_descriptor} "
        f"predicted demand lift of {sku.p90_demand_lift:.1f}x baseline. "
        f"Current stock of {sku.current_stock:,} units provides only "
        f"{sku.days_of_cover:.1f} days of cover under the P90 scenario, "
        f"which is {stock_status} given a {sku.supplier_lead_time_days}-day lead time."
    )

    return InvestigationResult(
        summary=summary,
        confidence_assessment=(
            f"Model predicts demand lift range of {sku.p10_demand_lift:.1f}x "
            f"to {sku.p90_demand_lift:.1f}x, with median at {sku.p50_demand_lift:.1f}x. "
            f"Wide prediction interval indicates moderate uncertainty."
        ),
        key_factors=[
            f"P90 demand lift: {sku.p90_demand_lift:.2f}x baseline",
            f"Days of cover: {sku.days_of_cover:.1f} vs lead time {sku.supplier_lead_time_days}d",
            f"Active viral videos: {sku.active_video_count}",
            f"Max engagement score: {sku.max_engagement_score:.4f}",
            f"Risk tier: {triage.risk_tier.value} — {triage.reasoning}",
        ],
        historical_comparison=(
            "Template-based analysis — no LLM available for historical comparison. "
            "Review engagement trajectory manually."
        ),
    )


def investigation_node(state: AgentState) -> AgentState:
    """
    Investigation node: analyze WHY the spike is predicted.

    Uses Groq LLM if available, falls back to structured template otherwise.
    """
    sku = state.sku_input
    log.info("investigation_node: starting", sku_id=sku.sku_id)

    if settings.groq_available:
        try:
            prompt = _build_investigation_prompt(state)
            response = _call_groq(prompt)
            result = _parse_investigation_response(response)
            state.llm_calls += 1
            log.info(
                "investigation_node: groq analysis complete",
                sku_id=sku.sku_id,
                factors=len(result.key_factors),
            )
        except Exception as e:
            log.warning(
                "investigation_node: groq call failed, using fallback",
                sku_id=sku.sku_id,
                error=str(e),
            )
            result = _generate_fallback_investigation(state)
            state.errors.append(f"Investigation LLM failed: {e}")
    else:
        log.info(
            "investigation_node: no groq key, using fallback template",
            sku_id=sku.sku_id,
        )
        result = _generate_fallback_investigation(state)

    state.investigation = result
    return state
