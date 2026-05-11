from __future__ import annotations

from typing import Any


def classify_survivorship_eau(
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
        reasons = ["EAU 2026 requiere que la toxicidad tardía y la recuperación funcional se sigan con captura estructurada."]
    if missing_inputs or stale_inputs:
        reasons.append(
            "La comparación EAU favorece cerrar los dominios faltantes antes de reducir la intensidad del seguimiento."
        )

    if trigger == "reenter_oncologic_decision":
        label = "Secuela tardía que reabre decisión oncológica"
        recommendation = (
            "La secuela dominante ya afecta elegibilidad o seguridad de tratamiento y debe reingresar a la ruta oncológica principal."
        )
    elif track == "late_effect_intervention":
        label = "Intervención sobre efectos tardíos"
        recommendation = (
            "Priorizar la toxicidad tardía y las referencias específicas según el dominio funcional dominante."
        )
    elif track == "toxicity_recovery":
        label = "Rehabilitación y recuperación"
        recommendation = (
            "Sostener rehabilitación, PROs y recuperación funcional como conducta visible principal de la visita."
        )
    else:
        label = "Seguimiento de survivorship"
        recommendation = (
            "Mantener vigilancia estructurada de secuelas, salud ósea, salud cardiometabólica y recuperación psicosexual."
        )

    return {
        "label": label,
        "recommendation": recommendation,
        "track": track,
        "dominant_domain": dominant_domain,
        "reasons": reasons,
        "capture_readiness": "incomplete" if (missing_inputs or stale_inputs) else "complete",
        "guideline_basis": [
            "EAU 2026 survivorship and quality of life",
            "EAU 2026 treatment toxicity follow-up",
        ],
    }
