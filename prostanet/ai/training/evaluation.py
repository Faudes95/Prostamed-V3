"""
Model Evaluation — clinical and statistical metrics.

Provides C-index, calibration, AUC, and domain-specific clinical metrics
for validating each model type.
"""

from __future__ import annotations

import logging
from typing import Any

import torch
import numpy as np

logger = logging.getLogger(__name__)


def concordance_index(
    predicted_risk: list[float],
    event_times: list[float],
    event_observed: list[int],
) -> float:
    """
    Compute Harrell's concordance index (C-index).

    Measures the probability that for a random pair of subjects,
    the one who experienced the event first had a higher predicted risk.
    """
    n = len(predicted_risk)
    if n < 2:
        return 0.5

    concordant = 0
    discordant = 0
    tied = 0

    for i in range(n):
        for j in range(i + 1, n):
            if event_observed[i] == 0 and event_observed[j] == 0:
                continue

            if event_times[i] < event_times[j] and event_observed[i] == 1:
                if predicted_risk[i] > predicted_risk[j]:
                    concordant += 1
                elif predicted_risk[i] < predicted_risk[j]:
                    discordant += 1
                else:
                    tied += 1
            elif event_times[j] < event_times[i] and event_observed[j] == 1:
                if predicted_risk[j] > predicted_risk[i]:
                    concordant += 1
                elif predicted_risk[j] < predicted_risk[i]:
                    discordant += 1
                else:
                    tied += 1

    total = concordant + discordant + tied
    if total == 0:
        return 0.5
    return (concordant + 0.5 * tied) / total


def calibration_score(
    predicted_probabilities: list[float],
    observed_events: list[int],
    n_bins: int = 10,
) -> dict[str, Any]:
    """
    Compute calibration metrics (Hosmer-Lemeshow style).

    Returns bin-level calibration data and overall calibration error.
    """
    n = len(predicted_probabilities)
    if n == 0:
        return {"calibration_error": 0, "bins": []}

    pairs = sorted(zip(predicted_probabilities, observed_events))
    bin_size = max(1, n // n_bins)

    bins: list[dict[str, float]] = []
    total_error = 0.0

    for b in range(n_bins):
        start = b * bin_size
        end = start + bin_size if b < n_bins - 1 else n
        if start >= n:
            break

        bin_preds = [p for p, _ in pairs[start:end]]
        bin_events = [e for _, e in pairs[start:end]]

        mean_pred = sum(bin_preds) / len(bin_preds)
        observed_rate = sum(bin_events) / len(bin_events)
        error = abs(mean_pred - observed_rate)
        total_error += error

        bins.append({
            "bin": b,
            "mean_predicted": round(mean_pred, 4),
            "observed_rate": round(observed_rate, 4),
            "calibration_error": round(error, 4),
            "count": len(bin_preds),
        })

    return {
        "calibration_error": round(total_error / max(1, len(bins)), 4),
        "bins": bins,
    }


def state_prediction_accuracy(
    predicted_states: list[int],
    true_states: list[int],
    num_classes: int = 13,
) -> dict[str, Any]:
    """
    Evaluate state transition prediction accuracy.

    Returns overall accuracy and per-class metrics.
    """
    n = len(predicted_states)
    if n == 0:
        return {"accuracy": 0, "per_class": {}}

    correct = sum(p == t for p, t in zip(predicted_states, true_states))
    accuracy = correct / n

    # Per-class precision/recall
    from prostanet.ai.config import IDX_TO_STATE

    per_class: dict[str, dict[str, float]] = {}
    for cls_idx in range(num_classes):
        tp = sum(
            1 for p, t in zip(predicted_states, true_states)
            if p == cls_idx and t == cls_idx
        )
        fp = sum(
            1 for p, t in zip(predicted_states, true_states)
            if p == cls_idx and t != cls_idx
        )
        fn = sum(
            1 for p, t in zip(predicted_states, true_states)
            if p != cls_idx and t == cls_idx
        )

        precision = tp / max(1, tp + fp)
        recall = tp / max(1, tp + fn)
        f1 = 2 * precision * recall / max(1e-8, precision + recall)

        state_name = IDX_TO_STATE.get(cls_idx, f"state_{cls_idx}")
        per_class[state_name] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": tp + fn,
        }

    return {
        "accuracy": round(accuracy, 4),
        "total_samples": n,
        "per_class": per_class,
    }


def treatment_response_metrics(
    predicted_psa50: list[float],
    true_psa50: list[int],
    predicted_rpfs: list[float],
    true_rpfs: list[float],
) -> dict[str, Any]:
    """Evaluate treatment response predictions."""
    n = len(predicted_psa50)
    if n == 0:
        return {}

    # PSA50 AUC (binary classification)
    auc = _simple_auc(predicted_psa50, true_psa50)

    # rPFS MAE
    rpfs_errors = [abs(p - t) for p, t in zip(predicted_rpfs, true_rpfs)]
    mae = sum(rpfs_errors) / n

    return {
        "psa50_auc": round(auc, 4),
        "rpfs_mae_months": round(mae, 2),
        "n_samples": n,
    }


def _simple_auc(scores: list[float], labels: list[int]) -> float:
    """Compute AUC using the trapezoidal rule."""
    pairs = sorted(zip(scores, labels), reverse=True)
    tp = 0
    fp = 0
    total_pos = sum(labels)
    total_neg = len(labels) - total_pos
    if total_pos == 0 or total_neg == 0:
        return 0.5

    auc = 0.0
    prev_fp = 0

    for _, label in pairs:
        if label == 1:
            tp += 1
        else:
            fp += 1
            auc += tp

    return auc / (total_pos * total_neg)


def evaluate_model_suite(
    records: list[dict[str, Any]],
    model_registry: Any = None,
) -> dict[str, Any]:
    """Run evaluation across all available models."""
    results: dict[str, Any] = {}

    if not model_registry:
        return {"error": "No model registry provided"}

    # State Transition
    state_model = model_registry.get("state_transition")
    if state_model:
        from prostanet.ai.config import STATE_TO_IDX

        preds = []
        trues = []
        for record in records:
            state = record.get("reconciled_state", "")
            if state not in STATE_TO_IDX:
                continue
            try:
                result = state_model.predict(record)
                pred_state = result.values.get("predicted_state", "")
                if pred_state in STATE_TO_IDX:
                    preds.append(STATE_TO_IDX[pred_state])
                    trues.append(STATE_TO_IDX[state])
            except Exception:
                continue

        if preds:
            results["state_transition"] = state_prediction_accuracy(preds, trues)

    return results
