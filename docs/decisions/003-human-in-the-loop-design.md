# ADR 003 — Human-in-the-Loop Agent Design

**Date**: 2024-06  
**Status**: Accepted

---

## Context

The action agent can draft purchase orders for CRITICAL-tier SKUs and Slack alerts for WARNING-tier SKUs. There is a design choice: should the agent **submit** these actions autonomously, or require **human approval** before any action is taken?

The system operates on inventory data that directly affects business cash flow:
- A false-positive CRITICAL alert that auto-submits a PO for 10,000 units of a $50 SKU = $500,000 committed unnecessarily.
- A missed CRITICAL that causes a stockout during a viral event = lost revenue + customer trust damage.

## Decision

**All agent outputs require human approval**. The agent's role is to:
1. Detect the signal (model scores).
2. Gather context (investigation agent).
3. Draft the action (PO or Slack alert).
4. Present the draft in the Streamlit review queue.

A human operator clicks **Approve** or **Reject** (with optional edit) before anything is sent externally.

## No-LLM Triage

The triage node (Step 1) uses **pure conditional logic** — no LLM. This makes routing deterministic, fast (~1ms), and auditable. The LLM is only invoked for the investigation summary (Step 2) and action draft (Step 3), where natural language generation adds clear value.

## Alternatives Considered

- **Fully autonomous**: Agent auto-approves POs under a dollar threshold. Rejected — threshold tuning is hard, and liability implications are unclear in early deployment.
- **Async Slack approval**: Agent posts to Slack with Approve/Reject buttons (Block Kit). Appealing but adds complexity (Slack OAuth, event subscriptions, stateful approval tracking). Planned for a future milestone.
- **Probabilistic gating**: Only auto-approve when model confidence is very high (P10/P90 interval is narrow). Interesting idea — added to backlog.

## Consequences

- The Streamlit review queue becomes a critical UX component. It must be fast and clear.
- Alert cooldown logic (4 hours per SKU) prevents queue flooding.
- Approval/rejection events are logged to DuckDB for model feedback (future: use rejections as negative training signal).
