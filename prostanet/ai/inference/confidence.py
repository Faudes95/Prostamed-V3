"""
Multi-Model Confidence — agreement, calibration, and ensemble metrics.

Measures inter-model agreement, agent consensus, calibration quality,
and temporal consistency to produce a trustworthiness score for any
recommendation produced by the ProstaNet AI pipeline.
"""

from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)


# ── Public API ────────────────────────────────────────────────────────────────


def compute_model_agreement(
    predictions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """
    Compute agreement metrics across multiple model predictions.

    Args:
        predictions: dict mapping model_id → prediction values

    Returns:
        agreement_score (0-100), concordant_signals, discordant_signals
    """
    concordant: list[str] = []
    discordant: list[str] = []
    signal_types: list[str] = []

    # ── State transition vs Anomaly detector ──
    state_pred = predictions.get("state_transition", {})
    anomaly_pred = predictions.get("anomaly_detector", {})

    state_prob = state_pred.get("predicted_state_probability", 0)
    is_anomalous = anomaly_pred.get("is_anomalous", False)

    if state_prob > 0.6 and is_anomalous:
        concordant.append("state_transition + anomaly_detector agree on progression signal")
        signal_types.append("concordant_progression")
    elif state_prob > 0.6 and not is_anomalous:
        discordant.append("state_transition predicts progression but no lab anomalies detected")
        signal_types.append("discordant_progression_no_anomaly")
    elif state_prob <= 0.6 and is_anomalous:
        discordant.append("anomaly_detector flags issues but state_transition predicts stability")
        signal_types.append("discordant_anomaly_no_progression")

    # ── Survival vs Treatment response ──
    survival_pred = predictions.get("deep_surv", {})
    treatment_pred = predictions.get("treatment_response", {})

    if survival_pred and treatment_pred:
        concordant.append("both survival and treatment models available")
        signal_types.append("dual_model_available")

        # If both suggest same top treatment → strong concordance
        surv_best = survival_pred.get("best_treatment", "")
        tx_best = treatment_pred.get("recommended_treatment", "")
        if surv_best and tx_best and surv_best.lower() == tx_best.lower():
            concordant.append(f"survival and treatment models agree on {surv_best}")
            signal_types.append("concordant_treatment_selection")
        elif surv_best and tx_best and surv_best.lower() != tx_best.lower():
            discordant.append(f"survival recommends {surv_best} vs treatment recommends {tx_best}")
            signal_types.append("discordant_treatment_selection")

    # ── Treatment response confidence check ──
    tx_confidence = treatment_pred.get("confidence", 0)
    if tx_confidence and tx_confidence > 0.8:
        concordant.append("treatment_response model has high self-confidence")
    elif tx_confidence and tx_confidence < 0.4:
        discordant.append("treatment_response model has low self-confidence")

    total = len(concordant) + len(discordant)
    score = (len(concordant) / total) * 100 if total > 0 else 50.0

    return {
        "agreement_score": round(score, 1),
        "concordant_signals": concordant,
        "discordant_signals": discordant,
        "signal_types": signal_types,
        "models_available": list(predictions.keys()),
        "total_signals": total,
    }


def compute_agent_consensus(
    agent_outputs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """
    Evaluate consensus among clinical AI agents.

    Checks whether CDA, TOA, PSA, and RIA agents produce
    mutually consistent recommendations and alerts.

    Returns:
        consensus_score (0-100), agreements, disagreements, details
    """
    agreements: list[str] = []
    disagreements: list[str] = []

    cda = agent_outputs.get("cda", {})
    toa = agent_outputs.get("toa", {})
    psa_agent = agent_outputs.get("psa", {})
    ria = agent_outputs.get("ria", {})

    # ── CDA vs TOA: top treatment recommendation ──
    cda_recs = cda.get("recommendations", [])
    toa_recs = toa.get("recommendations", [])

    cda_top = _extract_action(cda_recs[0]) if cda_recs else ""
    toa_top = _extract_action(toa_recs[0]) if toa_recs else ""

    if cda_top and toa_top:
        if _similar_action(cda_top, toa_top):
            agreements.append(f"CDA and TOA agree: {cda_top}")
        else:
            disagreements.append(f"CDA recommends '{cda_top}' but TOA ranks '{toa_top}' first")

    # ── PSA alerts vs CDA urgency ──
    psa_alerts = psa_agent.get("alerts", [])
    critical_alerts = [a for a in psa_alerts if _get_severity(a) == "critical"]

    if critical_alerts:
        cda_confidence = cda.get("confidence_score", 0)
        if cda_confidence and cda_confidence >= 70:
            agreements.append("PSA raised critical alerts and CDA shows high confidence action")
        elif cda_confidence and cda_confidence < 50:
            disagreements.append("PSA raised critical alerts but CDA has low confidence")

    # ── RIA trial eligibility vs state ──
    ria_trials = ria.get("metadata", {}).get("eligible_trials", [])
    if ria_trials and not cda_recs:
        disagreements.append("RIA identified eligible trials but CDA produced no recommendations")
    elif ria_trials and cda_recs:
        agreements.append(f"RIA found {len(ria_trials)} eligible trials alongside CDA recommendations")

    # ── Confidence spread ──
    confidences = []
    for key in ["cda", "toa", "psa", "ria"]:
        c = agent_outputs.get(key, {}).get("confidence_score")
        if c is not None and c > 0:
            confidences.append(c)

    spread = max(confidences) - min(confidences) if len(confidences) >= 2 else 0
    if spread > 30:
        disagreements.append(f"High confidence spread across agents ({spread:.0f} points)")
    elif spread <= 15 and len(confidences) >= 2:
        agreements.append(f"Tight confidence spread ({spread:.0f} points) — agents agree")

    total = len(agreements) + len(disagreements)
    score = (len(agreements) / total) * 100 if total > 0 else 50.0

    return {
        "consensus_score": round(score, 1),
        "agreements": agreements,
        "disagreements": disagreements,
        "agent_confidences": {
            k: agent_outputs.get(k, {}).get("confidence_score")
            for k in ["cda", "toa", "psa", "ria"]
            if agent_outputs.get(k, {}).get("confidence_score") is not None
        },
        "confidence_spread": round(spread, 1),
        "agents_reporting": len(confidences),
    }


def compute_calibration_quality(
    historical_predictions: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Assess how well-calibrated past predictions were.

    Uses historical prediction–outcome pairs to measure whether
    stated probabilities match observed frequencies (Brier score,
    bin-level calibration, discrimination).

    Args:
        historical_predictions: list of dicts with:
            - predicted_probability: float (0-1)
            - outcome_observed: bool or int (0/1)
            - model_id: str (optional)

    Returns:
        brier_score, calibration_error, discrimination_index, per_model breakdown
    """
    if not historical_predictions:
        return {
            "brier_score": None,
            "calibration_error": None,
            "discrimination_index": None,
            "n_predictions": 0,
            "quality_label": "insufficient_data",
        }

    probs: list[float] = []
    outcomes: list[int] = []

    for entry in historical_predictions:
        p = entry.get("predicted_probability")
        o = entry.get("outcome_observed")
        if p is not None and o is not None:
            probs.append(float(p))
            outcomes.append(int(bool(o)))

    n = len(probs)
    if n < 5:
        return {
            "brier_score": None,
            "calibration_error": None,
            "discrimination_index": None,
            "n_predictions": n,
            "quality_label": "insufficient_data",
        }

    # Brier Score (lower is better, 0 = perfect)
    brier = sum((p - o) ** 2 for p, o in zip(probs, outcomes)) / n

    # Calibration error (5 bins)
    cal_error = _bin_calibration_error(probs, outcomes, n_bins=5)

    # Discrimination (separation of predicted probs for positive vs negative)
    pos_probs = [p for p, o in zip(probs, outcomes) if o == 1]
    neg_probs = [p for p, o in zip(probs, outcomes) if o == 0]
    if pos_probs and neg_probs:
        mean_pos = sum(pos_probs) / len(pos_probs)
        mean_neg = sum(neg_probs) / len(neg_probs)
        discrimination = mean_pos - mean_neg
    else:
        discrimination = 0.0

    # Quality label
    if brier < 0.1 and cal_error < 0.05:
        quality = "excellent"
    elif brier < 0.2 and cal_error < 0.10:
        quality = "good"
    elif brier < 0.3:
        quality = "moderate"
    else:
        quality = "poor"

    # Per-model breakdown
    per_model: dict[str, dict[str, Any]] = {}
    model_groups: dict[str, list[tuple[float, int]]] = {}
    for entry in historical_predictions:
        mid = entry.get("model_id", "unknown")
        p = entry.get("predicted_probability")
        o = entry.get("outcome_observed")
        if p is not None and o is not None:
            model_groups.setdefault(mid, []).append((float(p), int(bool(o))))

    for mid, pairs in model_groups.items():
        mp, mo = zip(*pairs)
        mb = sum((p - o) ** 2 for p, o in pairs) / len(pairs)
        per_model[mid] = {
            "brier_score": round(mb, 4),
            "n_predictions": len(pairs),
        }

    return {
        "brier_score": round(brier, 4),
        "calibration_error": round(cal_error, 4),
        "discrimination_index": round(discrimination, 4),
        "n_predictions": n,
        "quality_label": quality,
        "per_model": per_model,
    }


def compute_temporal_consistency(
    prediction_history: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Measure consistency of predictions over time for the same patient.

    Stable patients should produce stable predictions; sudden jumps
    without new data suggest model instability.

    Args:
        prediction_history: list of dicts sorted by timestamp with:
            - timestamp: str (ISO 8601)
            - predicted_state: str
            - confidence: float

    Returns:
        stability_score, state_changes, confidence_volatility
    """
    if len(prediction_history) < 2:
        return {
            "stability_score": 100.0,
            "state_changes": 0,
            "confidence_volatility": 0.0,
            "n_predictions": len(prediction_history),
        }

    states = [p.get("predicted_state", "") for p in prediction_history]
    confidences = [p.get("confidence", 50.0) for p in prediction_history]

    # Count state changes
    state_changes = sum(1 for i in range(1, len(states)) if states[i] != states[i - 1])

    # Confidence volatility (std dev of confidence deltas)
    deltas = [abs(confidences[i] - confidences[i - 1]) for i in range(1, len(confidences))]
    avg_delta = sum(deltas) / len(deltas) if deltas else 0
    volatility = math.sqrt(sum((d - avg_delta) ** 2 for d in deltas) / len(deltas)) if deltas else 0

    # Stability score: penalize frequent state changes and high volatility
    n = len(prediction_history)
    change_rate = state_changes / (n - 1)
    stability = max(0.0, 100.0 - (change_rate * 60) - (volatility * 2))

    return {
        "stability_score": round(stability, 1),
        "state_changes": state_changes,
        "change_rate": round(change_rate, 4),
        "confidence_volatility": round(volatility, 2),
        "avg_confidence_delta": round(avg_delta, 2),
        "n_predictions": n,
    }


def compute_composite_trustworthiness(
    model_agreement: dict[str, Any] | None = None,
    agent_consensus: dict[str, Any] | None = None,
    calibration: dict[str, Any] | None = None,
    temporal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Aggregate all confidence dimensions into a single trustworthiness score.

    Weights:
        model_agreement:    25%
        agent_consensus:    30%
        calibration:        25%
        temporal_consistency: 20%
    """
    weights = {
        "model_agreement": 0.25,
        "agent_consensus": 0.30,
        "calibration": 0.25,
        "temporal_consistency": 0.20,
    }

    components: dict[str, float] = {}
    available_weight = 0.0

    if model_agreement:
        components["model_agreement"] = model_agreement.get("agreement_score", 50.0)
        available_weight += weights["model_agreement"]

    if agent_consensus:
        components["agent_consensus"] = agent_consensus.get("consensus_score", 50.0)
        available_weight += weights["agent_consensus"]

    if calibration and calibration.get("quality_label") != "insufficient_data":
        # Convert Brier score to 0–100 (lower brier = higher trust)
        brier = calibration.get("brier_score", 0.25)
        cal_score = max(0.0, (1 - brier * 4) * 100)  # 0.25 → 0, 0 → 100
        components["calibration"] = cal_score
        available_weight += weights["calibration"]

    if temporal:
        components["temporal_consistency"] = temporal.get("stability_score", 50.0)
        available_weight += weights["temporal_consistency"]

    # Weighted average with renormalization for missing components
    if available_weight > 0:
        composite = sum(
            components[k] * weights.get(k, 0) / available_weight
            for k in components
        )
    else:
        composite = 50.0

    composite = max(0.0, min(100.0, composite))

    # Trust level
    if composite >= 80:
        trust_level = "high"
        trust_label = "Recomendación confiable — presentar directamente"
    elif composite >= 60:
        trust_level = "moderate"
        trust_label = "Recomendación con caveats — revisar datos faltantes"
    elif composite >= 40:
        trust_level = "low"
        trust_label = "Confianza baja — solicitar más datos"
    else:
        trust_level = "very_low"
        trust_label = "Confianza insuficiente — escalar a especialista"

    return {
        "trustworthiness_score": round(composite, 1),
        "trust_level": trust_level,
        "trust_label": trust_label,
        "components": {k: round(v, 1) for k, v in components.items()},
        "available_dimensions": len(components),
        "total_dimensions": 4,
    }


# ── Helpers ───────────────────────────────────────────────────────────────────


def _extract_action(rec: Any) -> str:
    if isinstance(rec, dict):
        return rec.get("action", "") or rec.get("recommendation", "")
    return getattr(rec, "action", "") or ""


def _get_severity(alert: Any) -> str:
    if isinstance(alert, dict):
        return alert.get("severity", "")
    return getattr(alert, "severity", "") or ""


def _similar_action(a: str, b: str) -> bool:
    """Loose comparison of clinical action strings."""
    a_lower = a.lower().strip()
    b_lower = b.lower().strip()
    if a_lower == b_lower:
        return True
    # Check if one contains the other
    return a_lower in b_lower or b_lower in a_lower


def _bin_calibration_error(
    probs: list[float], outcomes: list[int], n_bins: int = 5
) -> float:
    """Average absolute calibration error across bins."""
    pairs = sorted(zip(probs, outcomes))
    n = len(pairs)
    bin_size = max(1, n // n_bins)
    total_error = 0.0
    n_actual_bins = 0

    for b in range(n_bins):
        start = b * bin_size
        end = start + bin_size if b < n_bins - 1 else n
        if start >= n:
            break
        bin_probs = [p for p, _ in pairs[start:end]]
        bin_outcomes = [o for _, o in pairs[start:end]]
        if not bin_probs:
            continue
        mean_pred = sum(bin_probs) / len(bin_probs)
        obs_rate = sum(bin_outcomes) / len(bin_outcomes)
        total_error += abs(mean_pred - obs_rate)
        n_actual_bins += 1

    return total_error / max(1, n_actual_bins)
