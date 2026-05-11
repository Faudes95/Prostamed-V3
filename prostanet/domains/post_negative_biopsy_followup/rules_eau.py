from __future__ import annotations


def classify_post_negative_biopsy_eau(payload: dict) -> dict:
    psa = float(payload.get("psa", 0) or 0)
    psad = float(payload.get("psad", 0) or 0)
    if not psad:
        prostate_volume = float(payload.get("prostate_volume_ml", 0) or 0)
        if psa and prostate_volume:
            psad = psa / prostate_volume
    pirads = int(float(payload.get("pirads_score", 0) or 0))
    dre_suspicious = _is_true(payload.get("dre_suspicious"))
    psa_velocity = float(payload.get("psa_velocity_ng_ml_year", 0) or 0)
    persistent_lesion = _is_true(payload.get("persistent_lesion_signal"))

    if psad >= 0.15 or pirads >= 4 or dre_suspicious or psa >= 10 or psa_velocity >= 0.75 or persistent_lesion:
        label = "Reapertura diagnóstica tras biopsia benigna"
        risk_group = "BENIGN_BIOPSY_REOPEN"
        recommendation = "La Asociación Europea de Urología favorece reimagen y eventual rebiopsia si reaparece una señal clínica consistente después de una biopsia benigna."
    else:
        label = "Seguimiento de baja intensidad tras biopsia benigna"
        risk_group = "BENIGN_BIOPSY_LOW_INTENSITY"
        recommendation = "La Asociación Europea de Urología permite seguimiento de baja intensidad tras biopsia benigna cuando la densidad del antígeno prostático específico y la sospecha clínica permanecen bajas."

    return {
        "label": label,
        "risk_group": risk_group,
        "recommendation": recommendation,
    }


def _is_true(value) -> bool:
    return str(value).lower() in {"1", "true", "yes", "si", "on"}
