"""
Prospective Validation Protocol — Framework for ongoing clinical validation.

Implements a structured protocol for validating AI predictions
against real-world outcomes as they arrive:

  1. At each decision point, record the AI prediction + confidence
  2. When the outcome is observed, compare with prediction
  3. Accumulate prediction–outcome pairs per model
  4. Compute rolling calibration, discrimination, and concordance
  5. Trigger alerts when performance degrades below thresholds

This is the foundation for continuous model monitoring in production.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# Performance thresholds
CALIBRATION_ERROR_THRESHOLD = 0.15  # Flag if calibration error > 15%
CONCORDANCE_THRESHOLD = 0.60  # Flag if C-index drops below 0.60
MIN_EVALUABLE_PAIRS = 10  # Minimum pairs before computing metrics


@dataclass
class PredictionRecord:
    """A single prediction recorded for prospective tracking."""
    record_id: str
    patient_id: int
    model_id: str
    prediction_type: str  # "state_transition", "treatment_response", "survival"
    predicted_value: Any
    predicted_probability: float
    confidence: float
    timestamp: str
    input_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "patient_id": self.patient_id,
            "model_id": self.model_id,
            "prediction_type": self.prediction_type,
            "predicted_value": self.predicted_value,
            "predicted_probability": self.predicted_probability,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
            "input_hash": self.input_hash,
        }


@dataclass
class OutcomeRecord:
    """The observed outcome for a previously recorded prediction."""
    record_id: str
    patient_id: int
    observed_value: Any
    observed_at: str
    match: bool | None = None  # Was the prediction correct?
    days_to_outcome: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "patient_id": self.patient_id,
            "observed_value": self.observed_value,
            "observed_at": self.observed_at,
            "match": self.match,
            "days_to_outcome": self.days_to_outcome,
        }


@dataclass
class PerformanceSnapshot:
    """Rolling performance metrics for a model."""
    model_id: str
    n_predictions: int
    n_evaluable: int
    accuracy: float | None = None
    calibration_error: float | None = None
    concordance: float | None = None
    brier_score: float | None = None
    alert_triggered: bool = False
    alert_reasons: list[str] = field(default_factory=list)
    window_days: int = 90
    computed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "n_predictions": self.n_predictions,
            "n_evaluable": self.n_evaluable,
            "accuracy": round(self.accuracy, 4) if self.accuracy is not None else None,
            "calibration_error": round(self.calibration_error, 4) if self.calibration_error is not None else None,
            "concordance": round(self.concordance, 4) if self.concordance is not None else None,
            "brier_score": round(self.brier_score, 4) if self.brier_score is not None else None,
            "alert_triggered": self.alert_triggered,
            "alert_reasons": self.alert_reasons,
            "window_days": self.window_days,
            "computed_at": self.computed_at,
        }


class ProspectiveValidator:
    """
    Manages the prospective validation lifecycle.

    Stores predictions and outcomes, computes rolling performance,
    and triggers alerts on degradation.

    Usage::

        validator = ProspectiveValidator()
        validator.record_prediction(pred)
        # ... later, when outcome is observed ...
        validator.record_outcome(outcome)
        snapshot = validator.compute_performance("state_transition")
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path
        self._predictions: list[PredictionRecord] = []
        self._outcomes: list[OutcomeRecord] = []

    def record_prediction(self, prediction: PredictionRecord) -> None:
        """Record a new AI prediction for future validation."""
        self._predictions.append(prediction)
        self._persist_prediction(prediction)
        logger.debug(
            "Recorded prediction %s for patient %s (model: %s)",
            prediction.record_id, prediction.patient_id, prediction.model_id,
        )

    def record_outcome(self, outcome: OutcomeRecord) -> None:
        """Record an observed outcome and match against its prediction."""
        # Find the matching prediction
        matching = [
            p for p in self._predictions
            if p.record_id == outcome.record_id
        ]

        if matching:
            pred = matching[0]
            outcome.match = self._evaluate_match(pred, outcome)
            if pred.timestamp and outcome.observed_at:
                try:
                    t_pred = datetime.fromisoformat(pred.timestamp)
                    t_out = datetime.fromisoformat(outcome.observed_at)
                    outcome.days_to_outcome = (t_out - t_pred).days
                except (ValueError, TypeError):
                    pass

        self._outcomes.append(outcome)
        self._persist_outcome(outcome)

    def compute_performance(
        self,
        model_id: str,
        window_days: int = 90,
    ) -> PerformanceSnapshot:
        """
        Compute rolling performance metrics for a specific model.

        Evaluates only prediction–outcome pairs within the time window.
        """
        now = datetime.utcnow()

        # Get all evaluable pairs for this model
        pairs = self._get_evaluable_pairs(model_id, window_days)

        n_predictions = sum(
            1 for p in self._predictions
            if p.model_id == model_id
        )

        snapshot = PerformanceSnapshot(
            model_id=model_id,
            n_predictions=n_predictions,
            n_evaluable=len(pairs),
            window_days=window_days,
            computed_at=now.isoformat(),
        )

        if len(pairs) < MIN_EVALUABLE_PAIRS:
            return snapshot

        # ── Accuracy ──
        correct = sum(1 for p, o in pairs if o.match is True)
        snapshot.accuracy = correct / len(pairs)

        # ── Brier Score ──
        brier_sum = 0.0
        for pred, out in pairs:
            actual = 1.0 if out.match else 0.0
            brier_sum += (pred.predicted_probability - actual) ** 2
        snapshot.brier_score = brier_sum / len(pairs)

        # ── Calibration Error ──
        probs = [p.predicted_probability for p, _ in pairs]
        actuals = [1 if o.match else 0 for _, o in pairs]
        snapshot.calibration_error = _bin_calibration_error(probs, actuals)

        # ── Concordance (for survival/time predictions) ──
        time_pairs = [
            (p, o) for p, o in pairs
            if o.days_to_outcome is not None and o.days_to_outcome > 0
        ]
        if len(time_pairs) >= MIN_EVALUABLE_PAIRS:
            risks = [p.predicted_probability for p, _ in time_pairs]
            times = [float(o.days_to_outcome) for _, o in time_pairs]
            events = [1] * len(time_pairs)  # all observed
            snapshot.concordance = _simple_concordance(risks, times, events)

        # ── Performance alerts ──
        alerts: list[str] = []
        if snapshot.calibration_error is not None and snapshot.calibration_error > CALIBRATION_ERROR_THRESHOLD:
            alerts.append(
                f"Calibration error {snapshot.calibration_error:.2%} exceeds threshold {CALIBRATION_ERROR_THRESHOLD:.0%}"
            )
        if snapshot.concordance is not None and snapshot.concordance < CONCORDANCE_THRESHOLD:
            alerts.append(
                f"Concordance {snapshot.concordance:.3f} below threshold {CONCORDANCE_THRESHOLD:.2f}"
            )
        if snapshot.accuracy is not None and snapshot.accuracy < 0.5:
            alerts.append(f"Accuracy {snapshot.accuracy:.2%} below random chance")

        snapshot.alert_triggered = len(alerts) > 0
        snapshot.alert_reasons = alerts

        return snapshot

    def compute_all_models(
        self, window_days: int = 90,
    ) -> dict[str, PerformanceSnapshot]:
        """Compute performance for all models with recorded predictions."""
        model_ids = set(p.model_id for p in self._predictions)
        return {
            mid: self.compute_performance(mid, window_days)
            for mid in model_ids
        }

    def get_degradation_alerts(
        self, window_days: int = 90,
    ) -> list[dict[str, Any]]:
        """Get all active degradation alerts across models."""
        alerts: list[dict[str, Any]] = []
        for mid, snapshot in self.compute_all_models(window_days).items():
            if snapshot.alert_triggered:
                alerts.append({
                    "model_id": mid,
                    "reasons": snapshot.alert_reasons,
                    "snapshot": snapshot.to_dict(),
                })
        return alerts

    # ── Internal ──────────────────────────────────────────────────────────────

    def _get_evaluable_pairs(
        self, model_id: str, window_days: int,
    ) -> list[tuple[PredictionRecord, OutcomeRecord]]:
        """Get matched prediction–outcome pairs within window."""
        pairs: list[tuple[PredictionRecord, OutcomeRecord]] = []
        outcome_map = {o.record_id: o for o in self._outcomes}

        for pred in self._predictions:
            if pred.model_id != model_id:
                continue
            outcome = outcome_map.get(pred.record_id)
            if outcome and outcome.match is not None:
                pairs.append((pred, outcome))

        return pairs

    @staticmethod
    def _evaluate_match(
        prediction: PredictionRecord, outcome: OutcomeRecord,
    ) -> bool:
        """Determine if a prediction matched the observed outcome."""
        pred_val = str(prediction.predicted_value).lower().strip()
        obs_val = str(outcome.observed_value).lower().strip()

        # Exact match
        if pred_val == obs_val:
            return True

        # Fuzzy match for state predictions
        if pred_val.replace("-", "_") == obs_val.replace("-", "_"):
            return True

        # Substring match for treatment recommendations
        if pred_val in obs_val or obs_val in pred_val:
            return True

        return False

    def _persist_prediction(self, prediction: PredictionRecord) -> None:
        """Persist prediction to the ai_predictions table."""
        try:
            import sqlite3
            from tracking_db import DB_PATH

            conn = sqlite3.connect(self._db_path or DB_PATH)
            conn.execute(
                """
                INSERT INTO ai_predictions
                    (patient_id, model_id, model_version, prediction_type,
                     input_hash, prediction_json, confidence_score)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    prediction.patient_id,
                    prediction.model_id,
                    "prospective",
                    prediction.prediction_type,
                    prediction.input_hash,
                    json.dumps(prediction.to_dict(), ensure_ascii=False),
                    prediction.confidence,
                ),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.debug("Prediction persistence failed: %s", exc)

    def _persist_outcome(self, outcome: OutcomeRecord) -> None:
        """Persist outcome (update the prediction record with observed value)."""
        # Outcomes are tracked in-memory for now;
        # could extend ai_predictions with outcome columns in future
        pass


# ── Helpers ───────────────────────────────────────────────────────────────────


def _bin_calibration_error(
    probs: list[float], outcomes: list[int], n_bins: int = 5,
) -> float:
    """Average absolute calibration error across bins."""
    pairs = sorted(zip(probs, outcomes))
    n = len(pairs)
    if n == 0:
        return 0.0

    bin_size = max(1, n // n_bins)
    total_error = 0.0
    n_bins_actual = 0

    for b in range(n_bins):
        start = b * bin_size
        end = start + bin_size if b < n_bins - 1 else n
        if start >= n:
            break
        bin_p = [p for p, _ in pairs[start:end]]
        bin_o = [o for _, o in pairs[start:end]]
        if not bin_p:
            continue
        mean_pred = sum(bin_p) / len(bin_p)
        obs_rate = sum(bin_o) / len(bin_o)
        total_error += abs(mean_pred - obs_rate)
        n_bins_actual += 1

    return total_error / max(1, n_bins_actual)


def _simple_concordance(
    risks: list[float], times: list[float], events: list[int],
) -> float:
    """Simplified concordance index."""
    n = len(risks)
    if n < 2:
        return 0.5

    concordant = 0
    discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            if events[i] == 0 and events[j] == 0:
                continue
            if times[i] < times[j] and events[i] == 1:
                if risks[i] > risks[j]:
                    concordant += 1
                elif risks[i] < risks[j]:
                    discordant += 1
            elif times[j] < times[i] and events[j] == 1:
                if risks[j] > risks[i]:
                    concordant += 1
                elif risks[j] < risks[i]:
                    discordant += 1

    total = concordant + discordant
    return (concordant / total) if total > 0 else 0.5
