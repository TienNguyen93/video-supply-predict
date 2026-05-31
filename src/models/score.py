"""
Inference and scoring pipeline.
Defines the Scorer class, which loads the champion model (from MLflow or local fallback),
predicts demand lifts for new videos, updates video marts, aggregates lifts per SKU,
computes ML-driven risk tiers, and updates the SKU risk dashboard table.
"""

from __future__ import annotations

import json
import pickle
from typing import Any

import duckdb
import mlflow
import numpy as np
import pandas as pd
import structlog
import yaml

from src.config import settings

log = structlog.get_logger()


class Scorer:
    """
    Manages loading the trained quantile regression models, generating predictions,
    and updating the scored databases in DuckDB.
    """

    def __init__(self) -> None:
        self.model: Any = None
        self.load_type: str = "none"

        # Load hyperparameters to get expected feature columns
        with open(settings.model_params_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
        self.feature_cols = config["feature_columns"]

        self._load_model()

    def _load_model(self) -> None:
        """
        Attempts to load the model from:
        1. The MLflow Model Registry (stage: "Production")
        2. A local fallback pickle file (data/models/quantile_models.pkl)
        3. A rule-based baseline fallback (graceful degradation)
        """
        # 1. Try MLflow
        try:
            from src.models.train import get_mlflow_tracking_uri

            tracking_uri = get_mlflow_tracking_uri()
            mlflow.set_tracking_uri(tracking_uri)

            model_uri = f"models:/{settings.mlflow_model_name}/Production"
            self.model = mlflow.pyfunc.load_model(model_uri)
            self.load_type = "mlflow"
            log.info("Successfully loaded champion model from MLflow registry", uri=model_uri)
            return
        except Exception as e:
            log.warning(
                "Could not load model from MLflow registry, trying local fallback", error=str(e)
            )

        # 2. Try Local Pickle
        pickle_path = settings.project_root / "data" / "models" / "quantile_models.pkl"
        if pickle_path.exists():
            try:
                with open(pickle_path, "rb") as f:
                    local_models = pickle.load(f)

                # Wrap local models to mimic the MLflow wrapper predict interface
                class LocalWrapper:
                    def __init__(self, models: dict[str, Any]) -> None:
                        self.models = models

                    def predict(self, model_input: pd.DataFrame) -> pd.DataFrame:
                        preds = {}
                        for q, m in self.models.items():
                            preds[f"{q}_demand_lift"] = m.predict(model_input)
                        return pd.DataFrame(preds)

                self.model = LocalWrapper(local_models)
                self.load_type = "local_pickle"
                log.info(
                    "Successfully loaded fallback model from local pickle file",
                    path=str(pickle_path),
                )
                return
            except Exception as e:
                log.warning("Failed to load local pickle fallback", error=str(e))

        # 3. Rule-based Baseline Fallback (Graceful Degradation)
        class RuleBasedFallbackModel:
            def predict(self, model_input: pd.DataFrame) -> pd.DataFrame:
                # Simulates lift based on features: engagement_score and sku_viral_sensitivity
                engagement = model_input.get("engagement_score", 0.0)
                sensitivity = model_input.get("sku_viral_sensitivity", 1.0)
                is_on_foryou = model_input.get("is_on_foryou", 0.0)

                # Baseline lift proxy
                base_lift = engagement * sensitivity * 10.0
                if hasattr(is_on_foryou, "to_numpy"):
                    base_lift += is_on_foryou * 0.5
                else:
                    base_lift += float(is_on_foryou) * 0.5

                # Quantile estimates
                p50 = np.maximum(base_lift, 0.1)
                p10 = np.maximum(p50 * 0.4, 0.02)
                p90 = np.maximum(p50 * 2.2, 0.2)

                return pd.DataFrame(
                    {
                        "p10_demand_lift": p10,
                        "p50_demand_lift": p50,
                        "p90_demand_lift": p90,
                    }
                )

        self.model = RuleBasedFallbackModel()
        self.load_type = "rule_based_fallback"
        log.info("Using rule-based baseline fallback model")

    def predict(self, features_df: pd.DataFrame) -> pd.DataFrame:
        """Produce predictions for P10, P50, and P90 quantiles."""
        if features_df.empty:
            return pd.DataFrame(columns=["p10_demand_lift", "p50_demand_lift", "p90_demand_lift"])

        # Filter to expected feature columns
        x = features_df[self.feature_cols]

        # Depending on whether the model is loaded from MLflow or local
        if self.load_type == "mlflow":
            # MLflow wrapper predict takes a context parameter as first argument internally
            return self.model.predict(x)
        else:
            return self.model.predict(x)

    def score_unpredicted_videos(self) -> int:
        """
        Identify unpredicted videos in DuckDB, generate predictions,
        and update their rows in marts.mart_scored_videos.
        Returns the number of videos scored.
        """
        # 1. Fetch unpredicted videos from marts.mart_scored_videos
        con = duckdb.connect(str(settings.duckdb_path))
        try:
            # Select videos where predictions are still NULL
            unscored_df = con.execute("""
                SELECT * FROM marts.mart_scored_videos
                WHERE p90_demand_lift IS NULL
            """).df()
        except Exception as e:
            log.error("Failed to query marts.mart_scored_videos", error=str(e))
            con.close()
            return 0

        if unscored_df.empty:
            log.info("No new unscored videos found in marts.mart_scored_videos")
            con.close()
            return 0

        log.info("Scoring unscored videos", count=len(unscored_df))

        # 2. Load hyperparameters to get feature columns
        with open(settings.model_params_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
        feature_cols = config["feature_columns"]

        # Rename columns to match expected features if necessary
        # Note: the features are already generated by dbt and match the params
        x = unscored_df[feature_cols]

        # 3. Generate predictions
        preds_df = self.predict(x)

        # 4. Update table directly in DuckDB
        scored_count = 0
        for idx, row in unscored_df.iterrows():
            video_id = row["video_id"]
            p10 = float(preds_df.loc[idx, "p10_demand_lift"])
            p50 = float(preds_df.loc[idx, "p50_demand_lift"])
            p90 = float(preds_df.loc[idx, "p90_demand_lift"])

            # Classify video-level risk tier based on P90 lift
            if p90 >= 3.0:
                v_risk = "CRITICAL"
            elif p90 >= 2.0:
                v_risk = "WARNING"
            elif p90 >= 1.5:
                v_risk = "WATCH"
            else:
                v_risk = "NORMAL"

            con.execute(
                """
                UPDATE marts.mart_scored_videos
                SET
                    p10_demand_lift = ?,
                    p50_demand_lift = ?,
                    p90_demand_lift = ?,
                    risk_tier_predicted = ?
                WHERE video_id = ?
            """,
                (p10, p50, p90, v_risk, video_id),
            )
            scored_count += 1

        con.close()
        log.info("Updated video prediction columns in DuckDB", count=scored_count)
        return scored_count

    def update_sku_risk_table(self) -> None:
        """
        Recompute SKU-level ML predictions and risk tiers, and update marts.mart_sku_risk.
        For each SKU, we aggregate predictions from its active videos (by taking the MAX lift),
        evaluate the combined lift + inventory thresholds, and compute projected stockout days.
        """
        # Load thresholds config
        with open(settings.risk_thresholds_path, encoding="utf-8") as f:
            thresholds = yaml.safe_load(f)
        tiers_config = thresholds["tiers"]

        con = duckdb.connect(str(settings.duckdb_path))
        try:
            # Get SKU inventory records
            skus_df = con.execute("SELECT * FROM marts.mart_sku_risk").df()
            # Get all scored videos with active predictions
            scored_videos = con.execute("""
                SELECT video_id, sku_ids_json, p10_demand_lift, p50_demand_lift, p90_demand_lift
                FROM marts.mart_scored_videos
                WHERE p90_demand_lift IS NOT NULL
            """).df()
        except Exception as e:
            log.error("Failed to query tables for SKU risk computation", error=str(e))
            con.close()
            return

        log.info("Updating SKU risk dashboard table", skus=len(skus_df))

        # Build video-to-SKU mapping list to quickly aggregate predictions
        # (Since sku_ids_json is a JSON array in each video row)
        sku_predictions: dict[str, list[dict[str, float]]] = {}
        for _, video in scored_videos.iterrows():
            try:
                sku_ids = json.loads(video["sku_ids_json"])
                for sku_id in sku_ids:
                    if sku_id not in sku_predictions:
                        sku_predictions[sku_id] = []
                    sku_predictions[sku_id].append(
                        {
                            "p10": video["p10_demand_lift"],
                            "p50": video["p50_demand_lift"],
                            "p90": video["p90_demand_lift"],
                        }
                    )
            except Exception:
                continue

        # Update each SKU
        for _, sku in skus_df.iterrows():
            sku_id = sku["sku_id"]
            baseline_demand = float(sku["baseline_daily_demand"])
            current_stock = int(sku["current_stock"])
            lead_time = int(sku["supplier_lead_time_days"])

            # 1. Aggregate predictions (MAX lift across all active videos)
            preds = sku_predictions.get(sku_id, [])
            if preds:
                p10_lift = max(p["p10"] for p in preds)
                p50_lift = max(p["p50"] for p in preds)
                p90_lift = max(p["p90"] for p in preds)
            else:
                # No active videos tagging this SKU means demand is at baseline (multiplier = 1.0)
                p10_lift = 1.0
                p50_lift = 1.0
                p90_lift = 1.0

            # 2. Compute Days of Cover under P90 scenario
            # Ensure p90_lift doesn't cause division by zero or negative
            effective_p90 = max(p90_lift, 0.01)
            p90_daily_demand = baseline_demand * effective_p90
            projected_days = current_stock / p90_daily_demand

            # 3. Classify ML Risk Tier
            # Evaluate conditions in precedence order: CRITICAL -> WARNING -> WATCH -> NORMAL
            ml_risk = "NORMAL"

            # CRITICAL check
            crit_cond = tiers_config["CRITICAL"]["conditions"]
            crit_doc_max = crit_cond["days_cover_max"]
            crit_buffer = crit_cond["lead_time_buffer_days"]
            if p90_lift >= crit_cond["p90_lift_min"] and (
                projected_days < crit_doc_max or projected_days < (lead_time + crit_buffer)
            ):
                ml_risk = "CRITICAL"

            # WARNING check
            if ml_risk == "NORMAL":
                warn_cond = tiers_config["WARNING"]["conditions"]
                warn_doc_max = warn_cond["days_cover_max"]
                warn_buffer = warn_cond["lead_time_buffer_days"]
                if p90_lift >= warn_cond["p90_lift_min"] and (
                    projected_days < warn_doc_max or projected_days < (lead_time + warn_buffer)
                ):
                    ml_risk = "WARNING"

            # WATCH check
            if ml_risk == "NORMAL":
                watch_cond = tiers_config["WATCH"]["conditions"]
                watch_doc_max = watch_cond["days_cover_max"]
                if p90_lift >= watch_cond["p90_lift_min"] and projected_days < watch_doc_max:
                    ml_risk = "WATCH"

            # Write predictions and risk tier back to mart_sku_risk
            con.execute(
                """
                UPDATE marts.mart_sku_risk
                SET
                    p10_demand_lift = ?,
                    p50_demand_lift = ?,
                    p90_demand_lift = ?,
                    ml_risk_tier = ?,
                    projected_stockout_days = ?
                WHERE sku_id = ?
            """,
                (p10_lift, p50_lift, p90_lift, ml_risk, projected_days, sku_id),
            )

        con.close()
        log.info("Updated SKU risk table predictions and tiers")


def main() -> None:
    """Scoring pipeline entrypoint."""
    scorer = Scorer()
    # 1. Score unpredicted videos
    scorer.score_unpredicted_videos()
    # 2. Update SKU risk predictions & tiers
    scorer.update_sku_risk_table()


if __name__ == "__main__":
    main()
