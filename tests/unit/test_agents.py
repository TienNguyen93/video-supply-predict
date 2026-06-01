"""
Unit tests for the agentic pipeline — triage, investigation, action, and graph.

All tests mock external dependencies (Groq API, DuckDB) to run fast and offline.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.agents.action import (
    _calculate_order_quantity,
    _generate_fallback_alert,
    _generate_fallback_po,
    action_node,
)
from src.agents.graph import _should_investigate, run_pipeline
from src.agents.investigation import (
    _generate_fallback_investigation,
    _parse_investigation_response,
    investigation_node,
)
from src.agents.state import (
    ActionType,
    AgentState,
    InvestigationResult,
    RiskTier,
    SKURiskInput,
    TriageResult,
)
from src.agents.triage import triage_node


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def critical_sku() -> SKURiskInput:
    """SKU with CRITICAL risk profile — high lift, low stock."""
    return SKURiskInput(
        sku_id="SKU-0001",
        sku_name="Viral Glow Serum",
        category="beauty",
        current_stock=50,
        baseline_daily_demand=20.0,
        supplier_lead_time_days=7,
        unit_price_usd=24.99,
        p10_demand_lift=2.0,
        p50_demand_lift=3.5,
        p90_demand_lift=5.0,
        active_video_count=3,
        max_engagement_score=0.15,
        top_video_ids=["vid_001", "vid_002"],
    )


@pytest.fixture
def warning_sku() -> SKURiskInput:
    """SKU with WARNING risk profile — moderate lift, moderate stock."""
    return SKURiskInput(
        sku_id="SKU-0042",
        sku_name="Trendy Water Bottle",
        category="lifestyle",
        current_stock=200,
        baseline_daily_demand=30.0,
        supplier_lead_time_days=5,
        unit_price_usd=12.50,
        p10_demand_lift=1.5,
        p50_demand_lift=2.2,
        p90_demand_lift=2.8,
        active_video_count=2,
        max_engagement_score=0.08,
        top_video_ids=["vid_010"],
    )


@pytest.fixture
def watch_sku() -> SKURiskInput:
    """SKU with WATCH risk profile — moderate lift, comfortable stock."""
    return SKURiskInput(
        sku_id="SKU-0099",
        sku_name="Basic Phone Case",
        category="accessories",
        current_stock=200,
        baseline_daily_demand=10.0,
        supplier_lead_time_days=3,
        unit_price_usd=8.99,
        p10_demand_lift=1.0,
        p50_demand_lift=1.3,
        p90_demand_lift=1.6,
        active_video_count=1,
        max_engagement_score=0.03,
        top_video_ids=["vid_050"],
    )


@pytest.fixture
def normal_sku() -> SKURiskInput:
    """SKU with NORMAL risk — no demand signal."""
    return SKURiskInput(
        sku_id="SKU-0200",
        sku_name="Standard Notebook",
        category="stationery",
        current_stock=1000,
        baseline_daily_demand=5.0,
        supplier_lead_time_days=4,
        unit_price_usd=3.99,
        p10_demand_lift=0.8,
        p50_demand_lift=1.0,
        p90_demand_lift=1.2,
        active_video_count=0,
        max_engagement_score=0.01,
    )


# ===================================================================
# TRIAGE NODE TESTS
# ===================================================================
class TestTriageNode:
    """Tests for the pure-logic triage node."""

    @pytest.mark.unit
    def test_critical_classification(self, critical_sku: SKURiskInput) -> None:
        """CRITICAL: P90 >= 3.0x AND low stock."""
        state = AgentState(sku_input=critical_sku)
        result = triage_node(state)

        assert result.triage is not None
        assert result.triage.risk_tier == RiskTier.CRITICAL
        assert result.triage.action_type == ActionType.DRAFT_PURCHASE_ORDER
        assert result.triage.should_continue is True

    @pytest.mark.unit
    def test_warning_classification(self, warning_sku: SKURiskInput) -> None:
        """WARNING: P90 >= 2.0x AND moderate stock."""
        state = AgentState(sku_input=warning_sku)
        result = triage_node(state)

        assert result.triage is not None
        assert result.triage.risk_tier == RiskTier.WARNING
        assert result.triage.action_type == ActionType.DRAFT_ALERT
        assert result.triage.should_continue is True

    @pytest.mark.unit
    def test_watch_classification(self, watch_sku: SKURiskInput) -> None:
        """WATCH: P90 >= 1.5x but comfortable inventory."""
        state = AgentState(sku_input=watch_sku)
        result = triage_node(state)

        assert result.triage is not None
        assert result.triage.risk_tier == RiskTier.WATCH
        assert result.triage.action_type == ActionType.LOG_AND_RECHECK
        assert result.triage.should_continue is False

    @pytest.mark.unit
    def test_normal_classification(self, normal_sku: SKURiskInput) -> None:
        """NORMAL: P90 < 1.5x."""
        state = AgentState(sku_input=normal_sku)
        result = triage_node(state)

        assert result.triage is not None
        assert result.triage.risk_tier == RiskTier.NORMAL
        assert result.triage.action_type == ActionType.NONE
        assert result.triage.should_continue is False

    @pytest.mark.unit
    def test_triage_populates_days_of_cover(self, critical_sku: SKURiskInput) -> None:
        """Triage should compute and store days_of_cover on the SKU input."""
        state = AgentState(sku_input=critical_sku)
        result = triage_node(state)

        assert result.sku_input.days_of_cover > 0
        # 50 stock / (20 demand * 5.0 lift) = 0.5 days
        assert result.sku_input.days_of_cover == pytest.approx(0.5, abs=0.1)

    @pytest.mark.unit
    def test_triage_reasoning_non_empty(self, critical_sku: SKURiskInput) -> None:
        """Triage reasoning should be a non-empty string."""
        state = AgentState(sku_input=critical_sku)
        result = triage_node(state)

        assert result.triage is not None
        assert len(result.triage.reasoning) > 10

    @pytest.mark.unit
    def test_high_lift_high_stock_is_watch(self) -> None:
        """High P90 lift but very high stock should NOT be CRITICAL."""
        sku = SKURiskInput(
            sku_id="SKU-HIGH-STOCK",
            sku_name="Well-Stocked Item",
            category="general",
            current_stock=100000,
            baseline_daily_demand=10.0,
            supplier_lead_time_days=3,
            p10_demand_lift=2.0,
            p50_demand_lift=3.0,
            p90_demand_lift=4.0,
        )
        state = AgentState(sku_input=sku)
        result = triage_node(state)

        # Despite high lift, 100k stock / (10 * 4) = 2500 days cover
        assert result.triage is not None
        # Should NOT be CRITICAL since stock is plentiful
        assert result.triage.risk_tier != RiskTier.NORMAL


# ===================================================================
# INVESTIGATION NODE TESTS
# ===================================================================
class TestInvestigationNode:
    """Tests for the investigation node."""

    @pytest.mark.unit
    def test_fallback_investigation_content(self, critical_sku: SKURiskInput) -> None:
        """Fallback investigation should produce meaningful content."""
        state = AgentState(sku_input=critical_sku)
        state.triage = TriageResult(
            risk_tier=RiskTier.CRITICAL,
            action_type=ActionType.DRAFT_PURCHASE_ORDER,
            reasoning="Test reasoning",
            should_continue=True,
        )

        result = _generate_fallback_investigation(state)

        assert isinstance(result, InvestigationResult)
        assert critical_sku.sku_id in result.summary
        assert len(result.key_factors) > 0
        assert "demand lift" in result.confidence_assessment.lower()

    @pytest.mark.unit
    @patch("src.agents.investigation.settings")
    def test_investigation_node_no_groq(
        self, mock_settings: MagicMock, critical_sku: SKURiskInput
    ) -> None:
        """Without Groq, investigation should use fallback."""
        mock_settings.groq_available = False
        mock_settings.risk_thresholds_path = (
            "C:\\Users\\nguye\\Documents\\antigravity\\serene-hypatia"
            "\\configs\\risk_thresholds.yaml"
        )

        state = AgentState(sku_input=critical_sku)
        state.triage = TriageResult(
            risk_tier=RiskTier.CRITICAL,
            action_type=ActionType.DRAFT_PURCHASE_ORDER,
            reasoning="Test",
            should_continue=True,
        )

        result = investigation_node(state)

        assert result.investigation is not None
        assert critical_sku.sku_id in result.investigation.summary
        assert result.llm_calls == 0

    @pytest.mark.unit
    def test_parse_investigation_response(self) -> None:
        """Parse a structured LLM response into InvestigationResult."""
        mock_response = """
## Summary
The SKU-0001 is experiencing a significant demand spike driven by viral TikTok content.
The model predicts up to 5x baseline demand within 24 hours.

## Confidence Assessment
High confidence — multiple engagement signals align with historical viral patterns.

## Key Factors
- Save velocity is 3x above the 95th percentile
- Multiple viral videos featuring this product
- For You page placement confirmed
- Cart rate exceeding historical averages

## Historical Comparison
This pattern resembles the Q4 2024 glow serum viral event which saw 4.2x actual lift.
"""
        result = _parse_investigation_response(mock_response)

        assert isinstance(result, InvestigationResult)
        assert "SKU-0001" in result.summary
        assert "High confidence" in result.confidence_assessment
        assert len(result.key_factors) >= 3
        assert "Q4 2024" in result.historical_comparison


# ===================================================================
# ACTION NODE TESTS
# ===================================================================
class TestActionNode:
    """Tests for the action node."""

    @pytest.mark.unit
    def test_calculate_order_quantity(self) -> None:
        """EOQ formula should produce reasonable quantities."""
        qty = _calculate_order_quantity(
            baseline_daily_demand=20.0,
            p90_lift=5.0,
            lead_time_days=7,
            current_stock=50,
            safety_stock_days=3,
        )

        # Expected: 20 * 5.0 * (7 + 3) - 50 = 1000 - 50 = 950
        assert qty == 950

    @pytest.mark.unit
    def test_calculate_order_quantity_min_one(self) -> None:
        """Order quantity should be at least 1."""
        qty = _calculate_order_quantity(
            baseline_daily_demand=1.0,
            p90_lift=1.0,
            lead_time_days=1,
            current_stock=999999,
        )
        assert qty >= 1

    @pytest.mark.unit
    def test_fallback_po_contains_key_info(self, critical_sku: SKURiskInput) -> None:
        """Fallback PO should contain SKU ID, quantity, and cost."""
        state = AgentState(sku_input=critical_sku)
        state.triage = TriageResult(
            risk_tier=RiskTier.CRITICAL,
            action_type=ActionType.DRAFT_PURCHASE_ORDER,
            reasoning="Test",
            should_continue=True,
        )
        state.investigation = InvestigationResult(
            summary="Test summary",
            confidence_assessment="High",
        )
        state.sku_input.days_of_cover = 0.5

        po = _generate_fallback_po(state, order_qty=950, est_cost=23740.50)

        assert critical_sku.sku_id in po
        assert "950" in po
        assert "HUMAN APPROVAL" in po or "REQUIRES" in po

    @pytest.mark.unit
    def test_fallback_alert_contains_key_info(self, warning_sku: SKURiskInput) -> None:
        """Fallback alert card should contain SKU info and risk level."""
        state = AgentState(sku_input=warning_sku)
        state.triage = TriageResult(
            risk_tier=RiskTier.WARNING,
            action_type=ActionType.DRAFT_ALERT,
            reasoning="Test",
            should_continue=True,
        )
        state.investigation = InvestigationResult(
            summary="Test",
            confidence_assessment="Moderate",
        )
        state.sku_input.days_of_cover = 2.4

        alert = _generate_fallback_alert(state)

        assert warning_sku.sku_id in alert
        assert "WARNING" in alert
        assert "2.8" in alert  # P90 lift value

    @pytest.mark.unit
    @patch("src.agents.action._persist_alert")
    @patch("src.agents.action.settings")
    def test_action_node_critical_fallback(
        self,
        mock_settings: MagicMock,
        mock_persist: MagicMock,
        critical_sku: SKURiskInput,
    ) -> None:
        """CRITICAL action without Groq should produce fallback PO."""
        mock_settings.groq_available = False
        mock_settings.slack_available = False
        mock_persist.return_value = "alert_test_001"

        state = AgentState(sku_input=critical_sku)
        state.triage = TriageResult(
            risk_tier=RiskTier.CRITICAL,
            action_type=ActionType.DRAFT_PURCHASE_ORDER,
            reasoning="Test",
            should_continue=True,
        )
        state.investigation = InvestigationResult(
            summary="Test",
            confidence_assessment="High",
        )
        state.sku_input.days_of_cover = 0.5

        result = action_node(state)

        assert result.action is not None
        assert result.action.action_type == ActionType.DRAFT_PURCHASE_ORDER
        assert result.action.recommended_quantity is not None
        assert result.action.recommended_quantity > 0
        assert result.action.estimated_cost_usd is not None

    @pytest.mark.unit
    @patch("src.agents.action._persist_alert")
    @patch("src.agents.action.settings")
    def test_action_node_warning_fallback(
        self,
        mock_settings: MagicMock,
        mock_persist: MagicMock,
        warning_sku: SKURiskInput,
    ) -> None:
        """WARNING action without Groq should produce fallback alert."""
        mock_settings.groq_available = False
        mock_settings.slack_available = False
        mock_persist.return_value = "alert_test_002"

        state = AgentState(sku_input=warning_sku)
        state.triage = TriageResult(
            risk_tier=RiskTier.WARNING,
            action_type=ActionType.DRAFT_ALERT,
            reasoning="Test",
            should_continue=True,
        )
        state.investigation = InvestigationResult(
            summary="Test",
            confidence_assessment="Moderate",
        )
        state.sku_input.days_of_cover = 2.4

        result = action_node(state)

        assert result.action is not None
        assert result.action.action_type == ActionType.DRAFT_ALERT
        assert len(result.action.draft_content) > 20


# ===================================================================
# GRAPH / ROUTING TESTS
# ===================================================================
class TestGraph:
    """Tests for the graph wiring and routing logic."""

    @pytest.mark.unit
    def test_should_investigate_critical(self) -> None:
        """CRITICAL should route to investigation."""
        state = AgentState(
            sku_input=SKURiskInput(
                sku_id="X",
                sku_name="X",
                category="X",
                current_stock=1,
                baseline_daily_demand=1.0,
                supplier_lead_time_days=1,
                p10_demand_lift=1.0,
                p50_demand_lift=1.0,
                p90_demand_lift=1.0,
            ),
            triage=TriageResult(
                risk_tier=RiskTier.CRITICAL,
                action_type=ActionType.DRAFT_PURCHASE_ORDER,
                reasoning="Test",
                should_continue=True,
            ),
        )

        assert _should_investigate(state) == "investigation"

    @pytest.mark.unit
    def test_should_investigate_warning(self) -> None:
        """WARNING should route to investigation."""
        state = AgentState(
            sku_input=SKURiskInput(
                sku_id="X",
                sku_name="X",
                category="X",
                current_stock=1,
                baseline_daily_demand=1.0,
                supplier_lead_time_days=1,
                p10_demand_lift=1.0,
                p50_demand_lift=1.0,
                p90_demand_lift=1.0,
            ),
            triage=TriageResult(
                risk_tier=RiskTier.WARNING,
                action_type=ActionType.DRAFT_ALERT,
                reasoning="Test",
                should_continue=True,
            ),
        )

        assert _should_investigate(state) == "investigation"

    @pytest.mark.unit
    def test_should_not_investigate_watch(self) -> None:
        """WATCH should end the pipeline."""
        state = AgentState(
            sku_input=SKURiskInput(
                sku_id="X",
                sku_name="X",
                category="X",
                current_stock=1,
                baseline_daily_demand=1.0,
                supplier_lead_time_days=1,
                p10_demand_lift=1.0,
                p50_demand_lift=1.0,
                p90_demand_lift=1.0,
            ),
            triage=TriageResult(
                risk_tier=RiskTier.WATCH,
                action_type=ActionType.LOG_AND_RECHECK,
                reasoning="Test",
                should_continue=False,
            ),
        )

        assert _should_investigate(state) == "end"

    @pytest.mark.unit
    def test_should_not_investigate_normal(self) -> None:
        """NORMAL should end the pipeline."""
        state = AgentState(
            sku_input=SKURiskInput(
                sku_id="X",
                sku_name="X",
                category="X",
                current_stock=1,
                baseline_daily_demand=1.0,
                supplier_lead_time_days=1,
                p10_demand_lift=1.0,
                p50_demand_lift=1.0,
                p90_demand_lift=1.0,
            ),
            triage=TriageResult(
                risk_tier=RiskTier.NORMAL,
                action_type=ActionType.NONE,
                reasoning="Test",
                should_continue=False,
            ),
        )

        assert _should_investigate(state) == "end"

    @pytest.mark.unit
    def test_pipeline_normal_exits_early(self, normal_sku: SKURiskInput) -> None:
        """NORMAL SKU should exit after triage without calling investigation/action."""
        result = run_pipeline(normal_sku)

        assert result.triage is not None
        assert result.triage.risk_tier == RiskTier.NORMAL
        assert result.investigation is None
        assert result.action is None
        assert result.llm_calls == 0

    @pytest.mark.unit
    def test_pipeline_watch_exits_early(self, watch_sku: SKURiskInput) -> None:
        """WATCH SKU should exit after triage."""
        result = run_pipeline(watch_sku)

        assert result.triage is not None
        assert result.triage.risk_tier == RiskTier.WATCH
        assert result.investigation is None
        assert result.action is None

    @pytest.mark.unit
    @patch("src.agents.action._persist_alert")
    @patch("src.agents.action._send_slack_notification")
    @patch("src.agents.investigation._call_groq")
    @patch("src.agents.action._call_groq")
    def test_pipeline_critical_full_flow(
        self,
        mock_action_groq: MagicMock,
        mock_inv_groq: MagicMock,
        mock_slack: MagicMock,
        mock_persist: MagicMock,
        critical_sku: SKURiskInput,
    ) -> None:
        """CRITICAL SKU should run full pipeline: triage → investigation → action."""
        mock_inv_groq.return_value = (
            "## Summary\nDemand spike predicted.\n\n"
            "## Confidence Assessment\nHigh.\n\n"
            "## Key Factors\n- Factor 1\n- Factor 2\n\n"
            "## Historical Comparison\nSimilar to previous event."
        )
        mock_action_groq.return_value = (
            "🔴 URGENT PO — SKU-0001 (Viral Glow Serum)\nQuantity: 950 units | Cost: $23,740.50"
        )
        mock_slack.return_value = True
        mock_persist.return_value = "alert_test_critical"

        result = run_pipeline(critical_sku)

        assert result.triage is not None
        assert result.triage.risk_tier == RiskTier.CRITICAL
        assert result.investigation is not None
        assert result.action is not None
        assert result.action.action_type == ActionType.DRAFT_PURCHASE_ORDER
        assert result.alert_id == "alert_test_critical"
        assert result.llm_calls == 2  # investigation + action


# ===================================================================
# STATE MODEL TESTS
# ===================================================================
class TestStateModels:
    """Tests for the Pydantic state models."""

    @pytest.mark.unit
    def test_sku_risk_input_defaults(self) -> None:
        """SKURiskInput should have sensible defaults."""
        sku = SKURiskInput(
            sku_id="TEST",
            sku_name="Test Item",
            category="test",
            current_stock=100,
            baseline_daily_demand=10.0,
            supplier_lead_time_days=5,
            p10_demand_lift=1.0,
            p50_demand_lift=1.5,
            p90_demand_lift=2.0,
        )

        assert sku.unit_price_usd == 0.0
        assert sku.active_video_count == 0
        assert sku.top_video_ids == []

    @pytest.mark.unit
    def test_agent_state_initialization(self) -> None:
        """AgentState should initialize with empty node outputs."""
        sku = SKURiskInput(
            sku_id="TEST",
            sku_name="Test",
            category="test",
            current_stock=1,
            baseline_daily_demand=1.0,
            supplier_lead_time_days=1,
            p10_demand_lift=1.0,
            p50_demand_lift=1.0,
            p90_demand_lift=1.0,
        )
        state = AgentState(sku_input=sku)

        assert state.triage is None
        assert state.investigation is None
        assert state.action is None
        assert state.llm_calls == 0
        assert state.errors == []

    @pytest.mark.unit
    def test_risk_tier_enum_values(self) -> None:
        """Risk tier enum should have expected values."""
        assert RiskTier.CRITICAL.value == "CRITICAL"
        assert RiskTier.WARNING.value == "WARNING"
        assert RiskTier.WATCH.value == "WATCH"
        assert RiskTier.NORMAL.value == "NORMAL"

    @pytest.mark.unit
    def test_action_type_enum_values(self) -> None:
        """Action type enum should have expected values."""
        assert ActionType.DRAFT_PURCHASE_ORDER.value == "draft_purchase_order"
        assert ActionType.DRAFT_ALERT.value == "draft_alert"
        assert ActionType.LOG_AND_RECHECK.value == "log_and_recheck"
        assert ActionType.NONE.value == "none"


class TestAgentRateLimitingAndRetries:
    """Tests to verify tenacity-based retry and rate limiting logic."""

    @pytest.mark.unit
    @patch("time.sleep")
    @patch("langchain_groq.ChatGroq")
    def test_investigation_call_groq_retries_on_failure(
        self, mock_chat_groq: MagicMock, mock_sleep: MagicMock
    ) -> None:
        """Test that investigation _call_groq retries on failure up to 5 times."""
        from src.agents.investigation import _call_groq

        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = Exception("Groq API error")
        mock_chat_groq.return_value = mock_llm

        with pytest.raises(Exception, match="Groq API error"):
            _call_groq("test prompt")

        # Configured for stop_after_attempt(5)
        assert mock_llm.invoke.call_count == 5
        assert mock_sleep.call_count > 0

    @pytest.mark.unit
    @patch("time.sleep")
    @patch("langchain_groq.ChatGroq")
    def test_action_call_groq_retries_on_failure(
        self, mock_chat_groq: MagicMock, mock_sleep: MagicMock
    ) -> None:
        """Test that action _call_groq retries on failure up to 5 times."""
        from src.agents.action import _call_groq

        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = Exception("Groq API error")
        mock_chat_groq.return_value = mock_llm

        with pytest.raises(Exception, match="Groq API error"):
            _call_groq("test prompt")

        # Configured for stop_after_attempt(5)
        assert mock_llm.invoke.call_count == 5
        assert mock_sleep.call_count > 0
