from __future__ import annotations


def classify_diagnostic_workup_eau(payload: dict) -> dict:
    psa = float(payload.get("psa", 0) or 0)
    psad = float(payload.get("psad", 0) or 0)
    if not psad:
        prostate_volume = float(payload.get("prostate_volume_ml", 0) or 0)
        if psa and prostate_volume:
            psad = psa / prostate_volume
    pirads = int(float(payload.get("pirads_score", 0) or 0))
    dre_suspicious = _is_true(payload.get("dre_suspicious"))
    psa_velocity = float(payload.get("psa_velocity_ng_ml_year", 0) or 0)

    if pirads >= 4 or dre_suspicious or psad >= 0.15 or psa >= 10 or psa_velocity >= 0.75:
        label = "Alta sospecha diagnóstica"
        risk_group = "DIAGNOSTIC_HIGH"
        recommendation = "La Asociación Europea de Urología favorece resonancia magnética multiparamétrica y biopsia dirigida más sistemática cuando persisten marcadores de sospecha clínicamente significativa."
    elif pirads == 3 or psad >= 0.10 or psa >= 4:
        label = "Sospecha diagnóstica intermedia"
        risk_group = "DIAGNOSTIC_INTERMEDIATE"
        recommendation = "La Asociación Europea de Urología favorece individualizar resonancia magnética y biopsia según densidad del antígeno prostático específico y hallazgos clínicos."
    else:
        label = "Sospecha diagnóstica baja"
        risk_group = "DIAGNOSTIC_LOW"
        recommendation = "La Asociación Europea de Urología favorece seguimiento con antígeno prostático específico, densidad del antígeno prostático específico y revaloración antes de repetir procedimientos invasivos."

    return {
        "label": label,
        "risk_group": risk_group,
        "recommendation": recommendation,
    }


def _is_true(value) -> bool:
    return str(value).lower() in {"1", "true", "yes", "si", "on"}
