from __future__ import annotations


def classify_post_negative_biopsy(payload: dict) -> dict:
    psa = float(payload.get("psa", 0) or 0)
    psad = float(payload.get("psad", 0) or 0)
    if not psad:
        prostate_volume = float(payload.get("prostate_volume_ml", 0) or 0)
        if psa and prostate_volume:
            psad = psa / prostate_volume
    pirads = int(float(payload.get("pirads_score", 0) or 0))
    dre_suspicious = _is_true(payload.get("dre_suspicious"))
    family_history = _is_true(payload.get("family_history_positive"))
    psa_velocity = float(payload.get("psa_velocity_ng_ml_year", 0) or 0)
    post_biopsy_mri = _is_true(payload.get("post_biopsy_mri"))
    persistent_lesion = _is_true(payload.get("persistent_lesion_signal"))
    prior_biopsy_mri_targeted = _is_true(payload.get("prior_biopsy_mri_targeted"))
    prior_biopsy_count = int(float(payload.get("prior_biopsy_count", 1) or 1))

    reopen = (
        psa >= 10
        or psad >= 0.15
        or pirads >= 4
        or dre_suspicious
        or psa_velocity >= 0.75
        or (post_biopsy_mri and persistent_lesion)
        or (pirads == 3 and not prior_biopsy_mri_targeted and prior_biopsy_count >= 1)
    )
    if reopen:
        label = "Reapertura diagnóstica tras biopsia benigna"
        risk_group = "BENIGN_BIOPSY_REOPEN"
        recommendation = "Reabrir el estudio diagnóstico con resonancia magnética multiparamétrica, revisión del antígeno prostático específico y nueva consideración de biopsia dirigida más sistemática."
    else:
        label = "Seguimiento de baja intensidad tras biopsia benigna"
        risk_group = "BENIGN_BIOPSY_LOW_INTENSITY"
        recommendation = "Mantener seguimiento de baja intensidad con antígeno prostático específico periódico y reactivar imagen o biopsia solo si reaparece una señal clínica consistente."

    reasons = []
    if reopen:
        reasons.append("La combinación de antígeno prostático específico, densidad, tacto rectal o resonancia magnética multiparamétrica reabre una sospecha clínicamente significativa.")
    else:
        reasons.append("La sospecha clínica actual se mantiene baja después de una biopsia benigna inicial.")
    if family_history:
        reasons.append("La historia familiar obliga a no perder trazabilidad aunque el seguimiento sea de baja intensidad.")
    if persistent_lesion:
        reasons.append("Existe persistencia de lesión sospechosa posterior a la biopsia, lo que impide seguimiento pasivo puro.")

    return {
        "label": label,
        "risk_group": risk_group,
        "recommendation": recommendation,
        "reopen_diagnostic_workup": reopen,
        "prior_biopsy_count": prior_biopsy_count,
        "reasons": reasons,
    }


def _is_true(value) -> bool:
    return str(value).lower() in {"1", "true", "yes", "si", "on"}
