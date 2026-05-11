"""
Confidence Scoring — multi-source composite confidence for recommendations.

Aggregates data completeness, model agreement, guideline concordance,
historical calibration, and data recency into a single 0–100 score.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from prostanet.ai.config import CONFIDENCE_WEIGHTS

logger = logging.getLogger(__name__)


class ConfidenceScorer:
    """Compute composite confidence for a clinical recommendation."""

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self.weights = weights or dict(CONFIDENCE_WEIGHTS)

    def score(
        self,
        record: dict[str, Any],
        agent_outputs: list[dict[str, Any]] | None = None,
        guideline_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return composite score plus per-component breakdown."""
        components: dict[str, float] = {}

        components["data_completeness"] = self._score_data_completeness(record)
        components["model_agreement"] = self._score_model_agreement(agent_outputs or [])
        components["guideline_concordance"] = self._score_guideline_concordance(
            agent_outputs or [], guideline_result
        )
        components["calibration"] = self._score_calibration(agent_outputs or [])
        components["recency"] = self._score_data_recency(record)

        composite = sum(
            components[k] * self.weights.get(k, 0) for k in components
        )
        composite = max(0.0, min(100.0, composite))

        # Action threshold
        if composite >= 80:
            action_level = "high"
            action_label = "Presentar recomendación directamente"
        elif composite >= 50:
            action_level = "moderate"
            action_label = "Presentar con advertencias y datos faltantes"
        else:
            action_level = "low"
            action_label = "Solicitar más datos o escalar a especialista"

        return {
            "composite_score": round(composite, 1),
            "components": {k: round(v, 1) for k, v in components.items()},
            "weights_used": dict(self.weights),
            "action_level": action_level,
            "action_label": action_label,
        }

    @staticmethod
    def _score_data_completeness(record: dict) -> float:
        """0–100 based on presence of critical clinical fields."""
        required = [
            ("identity", "diagnosis_date"),
            ("baseline", "baseline_psa"),
            ("baseline", "ecog_score"),
            ("baseline", "gleason_primary"),
            ("baseline", "gleason_secondary"),
            ("baseline", "clinical_tstage"),
            ("baseline", "hemoglobin"),
        ]
        present = 0
        for section, field in required:
            val = record.get(section)
            if isinstance(val, dict) and val.get(field) not in (None, "", "Desconocido"):
                present += 1
        base = (present / len(required)) * 80

        # Bonus for genomic profile and follow-up data
        genomic = record.get("genomic_profile") or {}
        if genomic.get("hrr_status"):
            base += 10
        if record.get("follow_ups") or record.get("follow_up_visits"):
            base += 10
        return min(100.0, base)

    @staticmethod
    def _score_model_agreement(outputs: list[dict]) -> float:
        """0–100 based on how many agent outputs agree on top recommendation."""
        if len(outputs) < 2:
            return 50.0  # neutral when insufficient data

        top_actions: list[str] = []
        for out in outputs:
            recs = out.get("recommendations", [])
            if recs:
                first = recs[0] if isinstance(recs[0], dict) else {}
                top_actions.append(first.get("action", ""))

        if not top_actions:
            return 50.0

        # Simple majority agreement
        from collections import Counter

        counts = Counter(top_actions)
        most_common_count = counts.most_common(1)[0][1] if counts else 0
        agreement_ratio = most_common_count / len(top_actions) if top_actions else 0
        return agreement_ratio * 100

    @staticmethod
    def _score_guideline_concordance(
        outputs: list[dict], guideline_result: dict | None
    ) -> float:
        """0–100 based on whether AI recommendations match guideline evaluation."""
        if not guideline_result:
            return 50.0  # neutral

        guideline_treatments = set()
        for tx in guideline_result.get("eligible_treatments", []):
            guideline_treatments.add(tx.get("regimen_code", "").lower())

        if not guideline_treatments:
            return 60.0

        ai_actions = set()
        for out in outputs:
            for rec in out.get("recommendations", []):
                action = rec.get("action", "") if isinstance(rec, dict) else ""
                ai_actions.add(action.lower())

        if not ai_actions:
            return 50.0

        overlap = ai_actions & guideline_treatments
        if overlap:
            return 90.0
        return 40.0

    @staticmethod
    def _score_calibration(outputs: list[dict]) -> float:
        """0–100 based on retrospective calibration metadata when available."""
        scores: list[float] = []
        for out in outputs:
            metadata = out.get("metadata", {}) or {}
            for key in (
                "historical_calibration_score",
                "calibration_score",
                "cohort_calibration_score",
            ):
                value = metadata.get(key)
                try:
                    if value is not None:
                        scores.append(float(value))
                        break
                except (TypeError, ValueError):
                    continue
        if not scores:
            return 50.0
        return max(0.0, min(100.0, sum(scores) / len(scores)))

    @staticmethod
    def _score_data_recency(record: dict) -> float:
        """0–100 based on how recent the latest clinical data is."""
        follow_ups = record.get("follow_ups") or record.get("follow_up_visits") or []
        if not follow_ups:
            return 20.0

        last_visit = follow_ups[-1]
        visit_date_str = last_visit.get("visit_date")
        if not visit_date_str:
            return 30.0

        try:
            visit_date = datetime.strptime(str(visit_date_str)[:10], "%Y-%m-%d")
            days_old = (datetime.now() - visit_date).days
            if days_old <= 30:
                return 100.0
            elif days_old <= 90:
                return 80.0
            elif days_old <= 180:
                return 60.0
            elif days_old <= 365:
                return 40.0
            else:
                return 20.0
        except (ValueError, TypeError):
            return 30.0
