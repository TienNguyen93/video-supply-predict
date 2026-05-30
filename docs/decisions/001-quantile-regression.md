# ADR 001 — Quantile Regression for Demand Lift Prediction

**Date**: 2024-06  
**Status**: Accepted

---

## Context

We need to predict how much a viral video will amplify demand for tagged SKUs. The prediction must be **actionable** for inventory decisions: replenishment teams need to know not just the expected lift, but the range of plausible outcomes so they can size orders appropriately.

A single point estimate (e.g., "demand will be 3.2× baseline") is not sufficient because:
- Viral events are inherently fat-tailed — the upside can be extreme.
- Stockout cost is asymmetric: stocking too little during a viral event is far more damaging than mild overstock.
- Replenishment decisions require a *risk scenario*, not an average.

## Decision

Train **three separate LightGBM quantile regressors** on the same feature set, each optimising a different quantile loss:

| Model | Quantile (α) | Use |
|---|---|---|
| P10 | 0.10 | Safety stock lower bound; conservative reorder point |
| P50 | 0.50 | Median expected lift; headline number for ops manager |
| P90 | 0.90 | Worst-case lift; drives alert thresholds and PO sizing |

The **P90 prediction is the primary decision variable** for the triage agent.

## Alternatives Considered

- **Single point estimate (MSE loss)**: Simpler to train but gives no uncertainty bounds. Rejected.
- **Conformal prediction intervals**: Model-agnostic, but requires a calibration set and adds complexity. May revisit post-MVP.
- **Bayesian regression (e.g., GPR, BayesianRidge)**: Principled uncertainty, but doesn't scale well to 50+ features and high-cardinality SKU embeddings. Rejected for now.
- **Time-series models (Prophet, NeuralProphet)**: Suitable for the baseline demand signal, but engagement velocity → demand lift is a cross-sectional prediction problem, not a univariate time series. Rejected for this model; used for baseline in `daily_baseline_refresh` DAG.

## Consequences

- Three models to maintain and retrain weekly. MLflow model registry handles versioning.
- P10/P50/P90 can diverge significantly for novel SKUs or platforms. The investigation agent is expected to flag this uncertainty in its summary.
- Feature engineering must be consistent across train and inference (enforced via dbt mart schema + Pydantic schemas).
