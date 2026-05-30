from __future__ import annotations

from prostanet.domains.diagnostic_workup.derivations import (
    derive_dre_context,
    derive_mri_context,
    derive_psad_context,
)


def classify_diagnostic_workup_eau(payload: dict) -> dict:
    psa = _safe_float(payload.get("psa"), default=0.0)
    psad = derive_psad_context(payload, psa_value=psa).value or 0.0
    pirads = derive_mri_context(payload).pirads or 0
    dre_suspicious = derive_dre_context(payload).is_suspicious
    psa_velocity = _safe_float(payload.get("psa_velocity_ng_ml_year"), default=0.0)

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
        recommendation = "La Asociación Europea de Urología favorece seguimiento con antígeno prostático específico, cálculo de densidad al disponer de volumen prostático y revaloración antes de repetir procedimientos invasivos."

    return {
        "label": label,
        "risk_group": risk_group,
        "recommendation": recommendation,
    }


def _safe_float(value, *, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return default
