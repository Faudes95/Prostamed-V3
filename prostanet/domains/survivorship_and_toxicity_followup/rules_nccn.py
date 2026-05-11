from __future__ import annotations

from typing import Any


def classify_survivorship_nccn(
    payload: dict[str, Any],
    *,
    transition_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bundle = dict(transition_bundle or {})
    track = str(bundle.get("survivorship_track") or "survivorship_followup")
    trigger = str(bundle.get("trigger_status") or "observe")
    dominant_domain = str(bundle.get("dominant_late_effect_domain") or "general_survivorship")
    missing_inputs = list(bundle.get("missing_inputs") or [])
    stale_inputs = list(bundle.get("stale_inputs") or [])

    reasons = list(bundle.get("trigger_reasons") or [])
    if not reasons:
        reasons = ["El seguimiento de survivorship debe priorizar la secuela dominante con captura estructurada."]
    if missing_inputs or stale_inputs:
        reasons.append(
            "Persisten brechas de captura que deben cerrarse antes de asumir un seguimiento de survivorship estable."
        )

    if trigger == "reenter_oncologic_decision":
        label = "Reabrir decisión oncológica desde survivorship"
        recommendation = (
            "La secuela o toxicidad dominante ya puede cambiar elegibilidad o seguridad terapéutica y obliga a reingresar la decisión oncológica."
        )
    elif track == "late_effect_intervention":
        label = "Intervención activa de secuelas tardías"
        recommendation = (
            "Priorizar intervención dirigida, referencias específicas y control estructurado de secuelas tardías."
        )
    elif track == "toxicity_recovery":
        label = "Recuperación funcional y de toxicidad"
        recommendation = (
            "Sostener rehabilitación y recuperación funcional con metas medibles, sin abrir una falsa ruta oncológica."
        )
    else:
        label = "Seguimiento estructurado de survivorship"
        recommendation = (
            "Mantener seguimiento protocolizado de survivorship, prevención secundaria y calidad de vida según exposiciones previas."
        )

    return {
        "label": label,
        "recommendation": recommendation,
        "track": track,
        "dominant_domain": dominant_domain,
        "reasons": reasons,
        "capture_readiness": "incomplete" if (missing_inputs or stale_inputs) else "complete",
        "guideline_basis": [
            "NCCN 2026 Survivorship",
            "NCCN 2026 Supportive Care",
        ],
    }
