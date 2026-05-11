# -*- coding: utf-8 -*-
"""EPIC 8 — Terapia focal: reglas NCCN PROS-C (cat 2B) + EAU 2026 §7.5.

Criterios de elegibilidad NCCN:

- Intermedio favorable (ISUP 2, PSA < 15, T1c-T2a) — cat 2B.
- Lesión índice única o dominante unilateral, documentada en mpMRI.
- Próstata ≤ 50-60 mL (HIFU) o ≤ 80 mL (crio) — volumen variable por tecnología.
- Sin lesión apical anterior profunda (HIFU evita apex por retroceso del haz).
- Sin obstrucción urinaria severa (IPSS ≥ 20 o retención).
- Expectativa de vida ≥ 10 años (equilibrio entre salvage y duración).
- Paciente informado sobre:
  * 20-30 % requiere re-focal o salvage en 5 años.
  * Alternativas: AS, RP, RT.

Evidencia:
- Stabile A et al. Eur Urol 2019;76:572 (HIFU mid-term outcomes).
- Guillaumier S et al. Eur Urol 2018;74:422 (HIFU failure-free 5y).
- Ward JF et al. BJU Int 2012;109:1648 (crioablación focal).
- Klotz L et al. J Urol 2021;205:769 (TULSA-Pro registro).
- NCCN PROS-C v5.2026 (categoría 2B).
"""
from __future__ import annotations

from typing import Any


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _is_true(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "si", "sí", "on"}


def _unilateral_lesion(payload: dict) -> bool:
    text = str(payload.get("lesion_unilateral") or "").lower()
    return "unilateral" in text


def _nccn_risk_group(payload: dict) -> str:
    raw = str(payload.get("nccn_risk_group") or "").strip().lower().replace(" ", "_")
    if "very_high" in raw:
        return "very_high"
    if "unfavorable" in raw:
        return "unfavorable_intermediate"
    if "favorable" in raw or "favorable_intermediate" in raw:
        return "favorable_intermediate"
    if "high" in raw:
        return "high"
    if raw in {"low", "very_low"}:
        return raw
    return ""


def _isup_grade(payload: dict) -> int:
    raw = payload.get("isup_grade")
    try:
        return int(float(raw)) if raw not in (None, "") else 0
    except (TypeError, ValueError):
        return 0


def classify_focal_therapy_nccn(payload: dict) -> dict:
    psa = _to_float(payload.get("psa"))
    isup = _isup_grade(payload)
    risk_group = _nccn_risk_group(payload)
    lesion_maxdim = _to_float(payload.get("lesion_maxdim_mm"))
    prostate_vol = _to_float(payload.get("prostate_volume_ml"))
    lesion_apical = _is_true(payload.get("lesion_location_apical"))
    obstructive = _is_true(payload.get("urinary_obstructive_symptoms"))
    unilateral = _unilateral_lesion(payload)
    life_expectancy = _to_float(payload.get("life_expectancy_years"), default=0.0)
    modality = str(payload.get("focal_modality_preferred") or "").lower()

    reasons: list[str] = []
    exclusion_reasons: list[str] = []
    cautions: list[str] = []

    # Eligibility gate
    eligible = True

    if risk_group and risk_group not in {"favorable_intermediate", "low", "very_low"}:
        eligible = False
        exclusion_reasons.append(
            f"Grupo NCCN {risk_group} no elegible — terapia focal sólo aprobada en intermedio favorable/bajo riesgo."
        )
    elif not risk_group:
        cautions.append("Grupo de riesgo NCCN no determinado — confirmar antes de ofrecer terapia focal.")

    if isup and isup > 2:
        eligible = False
        exclusion_reasons.append(
            f"ISUP {isup} supera el límite de elegibilidad NCCN para terapia focal (≤ ISUP 2)."
        )

    if psa and psa > 15:
        eligible = False
        exclusion_reasons.append(
            f"PSA {psa:g} ng/mL > 15 — supera el umbral de elegibilidad focal (NCCN PROS-C cat 2B)."
        )

    if not unilateral:
        eligible = False
        exclusion_reasons.append(
            "La lesión no está documentada como unilateral en mpMRI — terapia focal requiere lesión índice unilateral o dominante."
        )

    if lesion_maxdim and lesion_maxdim > 15:
        cautions.append(
            f"Lesión de {lesion_maxdim:g} mm es grande; el control tumoral es menos predecible, preferir vigilancia más frecuente post-focal."
        )

    if lesion_apical and "hifu" in modality:
        eligible = False
        exclusion_reasons.append(
            "Lesión apical anterior profunda no es abordable por HIFU — considerar crioablación o RP."
        )

    if prostate_vol and prostate_vol > 60 and "hifu" in modality:
        cautions.append(
            f"Próstata {prostate_vol:g} mL supera límite HIFU estándar (≤ 60 mL) — considerar debulking o crioablación."
        )
    if prostate_vol and prostate_vol > 80:
        exclusion_reasons.append(
            "Próstata > 80 mL dificulta cualquier modalidad focal; reconsiderar AS o RP."
        )
        eligible = False

    if obstructive:
        cautions.append(
            "Síntomas obstructivos urinarios significativos — optimizar IPSS antes de focal para evitar retención post-procedimiento."
        )

    if life_expectancy and life_expectancy < 10:
        cautions.append(
            "Esperanza de vida < 10 años reduce el beneficio esperado frente a vigilancia activa."
        )

    # Recommendation
    if eligible:
        label = "Candidato a terapia focal selectiva"
        recommendation = (
            "Ofrecer terapia focal (HIFU/crio/TULSA) como alternativa a AS o RP/RT, con monitoreo post-procedimiento estricto "
            "(mpMRI + biopsia al año, PSA cada 3 meses los primeros 2 años). Evidencia NCCN PROS-C cat 2B."
        )
        if "hifu" in modality:
            reasons.append("HIFU con lesión índice unilateral documentada: Stabile Eur Urol 2019 (failure-free 5y ~80 %).")
        elif "crio" in modality:
            reasons.append("Crioablación focal: Ward BJU Int 2012.")
        elif "tulsa" in modality:
            reasons.append("TULSA-Pro: Klotz J Urol 2021.")
        else:
            reasons.append("Seleccionar modalidad según disponibilidad local y características de la lesión (ver literatura específica).")
    else:
        label = "No elegible para terapia focal"
        recommendation = (
            "No ofrecer terapia focal. Priorizar vigilancia activa (si intermedio favorable unilateral con lesión pequeña) "
            "o tratamiento de glándula entera (RP/RT) según preferencia del paciente."
        )

    return {
        "eligible": eligible,
        "label": label,
        "recommendation": recommendation,
        "risk_group": risk_group or "favorable_intermediate",
        "reasons": reasons,
        "exclusion_reasons": exclusion_reasons,
        "cautions": cautions,
        "modality_recommended": modality if modality else "no_definida",
    }


def focal_therapy_eligibility(payload: dict) -> dict:
    """Alias corto para consumir desde ``localized_initial`` u otros dominios."""
    return classify_focal_therapy_nccn(payload)
