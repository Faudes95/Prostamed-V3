# -*- coding: utf-8 -*-
"""
VISION / PSMAfore — elegibilidad estructurada para Lu-177 PSMA-617.

Formaliza los criterios de ensayos pivote:

- **VISION** (Sartor NEJM 2021;385:1091, category 1): mCRPC PSMA+ post-ARPI
  y post-taxano, SUVmax ≥ hígado en lesión índice, sin lesiones dominantes
  PSMA-negativas en imagen convencional, ECOG 0-2, función medular/hepática/
  renal preservada.
- **PSMAfore** (Morris Lancet 2024;404:1227, category 1): mCRPC PSMA+ post-ARPI
  pre-taxano, mismos criterios PET y de fitness, con opción de diferir
  docetaxel.
- **TheraP** (Hofman Lancet 2021;397:797): criterio SUVmax ≥20 en ≥1 lesión
  + SUVmean ≥10 en todas las lesiones medibles — NO requerido por VISION pero
  usado como ancla de confianza extra cuando se reporta.

Este módulo NO decide por sí mismo: devuelve un bundle estructurado que el
servicio consume para graduar la prioridad del regimen LU177_PSMA617 entre
`preferred` (VISION pleno), `selected_candidate` (PSMAfore / criterios
parciales) y `not_eligible` (bloqueo duro).

Referencias:
  Sartor NEJM 2021 (VISION)
  Morris Lancet 2024 (PSMAfore)
  Hofman Lancet 2021 (TheraP)
  NCCN PROS-11 v5.2026 (Lu-177 PSMA)
  EAU 2026 §6.11 (radioligandos)
"""
from __future__ import annotations

from typing import Any

from prostanet.shared.numeric_validation import (
    PSMA_LIVER_SUV_FLOOR,
    validate_vision_psma_ratio,
)


def _flag(payload: dict, key: str, default: str = "0") -> bool:
    return str(payload.get(key, default)).strip().lower() in {"1", "true", "yes", "si", "sí"}


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def evaluate_vision_eligibility(payload: dict, *, m1_context: dict | None = None) -> dict[str, Any]:
    """Devuelve un bundle estructurado para Lu-177 PSMA-617.

    Args:
        payload: payload clínico completo.
        m1_context: contexto ya calculado por evaluate_m1_crpc (opcional).

    Returns:
        dict con campos::
            {
              "regimen_code": "LU177_PSMA617",
              "eligibility_label": "vision_full" | "psmafore_pre_taxane"
                                   | "partial" | "not_eligible",
              "priority": "preferred" | "selected_candidate" | "not_eligible",
              "hard_blocks": [...],
              "cautions": [...],
              "missing_inputs": [...],
              "suv_ratio_met": bool | None,
              "trial_refs": [...],
            }
    """
    m1 = m1_context or {}

    psma_positive = bool(m1.get("psma_positive")) or _flag(payload, "psma_positive")
    psma_pet_done = _flag(payload, "psma_pet_done")
    psma_negative_dominant = _flag(payload, "psma_negative_dominant_lesions")
    prior_arpi = bool(m1.get("prior_arpi"))
    prior_docetaxel = bool(m1.get("prior_docetaxel"))
    prior_lu177 = (
        _flag(payload, "prior_lu177_psma617")
        or "lu177" in str(payload.get("prior_therapy", "")).lower()
        or "pluvicto" in str(payload.get("prior_therapy", "")).lower()
    )
    chemotherapy_delay_candidate = _flag(payload, "chemotherapy_delay_candidate") or bool(
        m1.get("chemotherapy_delay_candidate")
    )

    ecog = _safe_int(
        payload.get("ecog_score") or payload.get("ecog_performance_status") or payload.get("ecog")
    ) or 1

    # SUV per-lesión e hígado (criterio formal VISION)
    # EPIC 3 FIX-VISION-1: `psma_index_lesion_suvmax` es la lesión índice (pico),
    # mientras que `psma_lesion_suvmax_minimum` es el SUVmax de la lesión más
    # débil. VISION exige que TODAS las lesiones medibles tengan SUV ≥ hígado;
    # si la más débil está por debajo, existe clon dominante PSMA-negativo.
    lesion_suv = _safe_float(
        payload.get("psma_index_lesion_suvmax")
        or payload.get("psma_lesion_suvmax_minimum")
    )
    lesion_suv_minimum = _safe_float(payload.get("psma_lesion_suvmax_minimum"))
    liver_suv = _safe_float(
        payload.get("psma_suvmean_liver") or payload.get("psma_liver_suvmean")
    )
    ratio_result, ratio_error = validate_vision_psma_ratio(lesion_suv, liver_suv)
    suv_lesion_checked, suv_liver_checked = ratio_result if isinstance(ratio_result, tuple) else (None, None)
    suv_ratio_met: bool | None
    if suv_lesion_checked is None or suv_liver_checked is None:
        suv_ratio_met = None
    else:
        suv_ratio_met = ratio_error is None

    # Función medular/renal/hepática (VISION criterios laboratorio)
    hb = _safe_float(payload.get("hemoglobin") or payload.get("hb"))
    platelets = _safe_float(payload.get("platelets"))
    anc = _safe_float(payload.get("anc"))
    egfr = _safe_float(payload.get("egfr_ml_min") or payload.get("egfr"))
    bilirubin = _safe_float(payload.get("bilirubin"))
    albumin = _safe_float(payload.get("albumin_g_dl") or payload.get("albumin"))

    hard_blocks: list[str] = []
    cautions: list[str] = []
    missing: list[str] = []

    if prior_lu177:
        hard_blocks.append(
            "Exposición previa a Lu-177 PSMA-617 documentada — re-tratamiento fuera de indicación VISION estándar."
        )
    if not psma_positive:
        hard_blocks.append("PSMA-PET no positivo o sin documentación — VISION exige PSMA positivo trazable.")
    if not psma_pet_done:
        missing.append("psma_pet_done")
        cautions.append("PSMA-PET estructurado no documentado — VISION requiere informe estructurado.")
    if psma_negative_dominant:
        hard_blocks.append(
            "Lesiones dominantes PSMA-negativas en imagen convencional — excluidas en VISION "
            "(riesgo de subtratamiento de clones negativos)."
        )
    if not prior_arpi:
        hard_blocks.append("Sin exposición previa a ARPI — VISION/PSMAfore exigen al menos un ARPI previo.")

    if ecog >= 3:
        hard_blocks.append(f"ECOG {ecog} ≥3 — fuera de ventana VISION (ECOG 0-2).")
    elif ecog == 2:
        cautions.append("ECOG 2 — vigilar tolerancia; VISION incluyó ECOG 0-2.")

    # SUVmax lesión vs hígado
    if lesion_suv is None:
        missing.append("psma_index_lesion_suvmax")
        cautions.append(
            "SUVmax lesión índice no reportada — VISION documenta SUV lesión ≥ SUV hígado como criterio formal."
        )
    if liver_suv is None:
        missing.append("psma_suvmean_liver")
        cautions.append(
            f"SUV medio hepático no reportado — VISION exige comparación lesión≥hígado (piso {PSMA_LIVER_SUV_FLOOR})."
        )
    if ratio_error and lesion_suv is not None and liver_suv is not None:
        hard_blocks.append(f"VISION SUV-ratio: {ratio_error}")

    # EPIC 3 FIX-VISION-1: hard-block cuando la lesión más débil esté por debajo
    # del hígado. Eso denota clon dominante PSMA-negativo y es criterio de
    # exclusión formal de VISION (riesgo de infratratar enfermedad visible).
    if (
        lesion_suv_minimum is not None
        and liver_suv is not None
        and lesion_suv_minimum < liver_suv
    ):
        hard_blocks.append(
            f"SUVmax mínimo entre lesiones {lesion_suv_minimum:.1f} < SUV hígado "
            f"{liver_suv:.1f} — implica lesión dominante PSMA-negativa, criterio "
            "de exclusión VISION (Sartor NEJM 2021)."
        )
        suv_ratio_met = False

    # Función renal (Lu-177 depende de excreción renal)
    if egfr is None:
        missing.append("egfr_ml_min")
    elif egfr < 30:
        hard_blocks.append(
            f"eGFR {egfr:.0f} mL/min <30 — riesgo de toxicidad renal acumulativa con radioligando (excluido en VISION)."
        )
    elif egfr < 50:
        cautions.append(
            f"eGFR {egfr:.0f} mL/min 30-50 — dosis ajustada y monitoreo renal estrecho; VISION incluyó ≥50."
        )

    # Función medular
    if hb is None:
        missing.append("hemoglobin")
    elif hb < 9:
        hard_blocks.append(f"Hemoglobina {hb:.1f} g/dL <9 — fuera de criterio VISION.")
    elif hb < 10:
        cautions.append(f"Hemoglobina {hb:.1f} g/dL 9-10 — estabilizar y transfundir antes de iniciar.")

    if platelets is None:
        missing.append("platelets")
    elif platelets < 100_000:
        hard_blocks.append(f"Plaquetas {platelets:.0f} <100k — fuera de criterio VISION.")
    elif platelets < 150_000:
        cautions.append(f"Plaquetas {platelets:.0f} 100-150k — monitorizar toxicidad hematológica acumulativa.")

    if anc is None:
        missing.append("anc")
    elif anc < 1500:
        hard_blocks.append(f"ANC {anc:.0f} <1500 — fuera de criterio VISION.")

    if bilirubin is not None and bilirubin > 3:
        hard_blocks.append(f"Bilirrubina {bilirubin:.1f} mg/dL >3 — excluida en VISION.")
    if albumin is not None and albumin < 2.5:
        cautions.append(f"Albúmina {albumin:.1f} g/dL <2.5 — fragilidad nutricional; vigilar tolerancia.")

    # ── Clasificación final ─────────────────────────────────────────
    eligibility_label: str
    priority: str
    trial_refs: list[str] = []

    if hard_blocks:
        eligibility_label = "not_eligible"
        priority = "not_eligible"
        trial_refs.append("VISION (Sartor NEJM 2021)")
    elif prior_docetaxel and suv_ratio_met is True:
        # VISION pleno: post-ARPI + post-docetaxel + SUV ratio ok
        eligibility_label = "vision_full"
        priority = "preferred"
        trial_refs.extend(["VISION (Sartor NEJM 2021)", "TheraP (Hofman Lancet 2021)"])
    elif not prior_docetaxel and chemotherapy_delay_candidate and suv_ratio_met is True:
        # PSMAfore pre-taxano con racional para diferir docetaxel
        eligibility_label = "psmafore_pre_taxane"
        priority = "preferred"
        trial_refs.append("PSMAfore (Morris Lancet 2024)")
    elif suv_ratio_met is None or missing:
        # Elegibilidad parcial por datos incompletos
        eligibility_label = "partial"
        priority = "selected_candidate"
        trial_refs.append("VISION (Sartor NEJM 2021)")
        cautions.append(
            "Elegibilidad VISION/PSMAfore parcial: completar SUV per-lesión, SUV hígado y bundle hematológico."
        )
    else:
        eligibility_label = "partial"
        priority = "selected_candidate"
        trial_refs.append("VISION (Sartor NEJM 2021)")

    return {
        "regimen_code": "LU177_PSMA617",
        "drug_label": "Lutecio-177 PSMA-617 (Pluvicto)",
        "eligibility_label": eligibility_label,
        "priority": priority,
        "eligible": priority != "not_eligible",
        "hard_blocks": hard_blocks,
        "cautions": cautions,
        "missing_inputs": missing,
        "suv_ratio_met": suv_ratio_met,
        "suv_lesion": suv_lesion_checked,
        "suv_liver": suv_liver_checked,
        "ecog": ecog,
        "prior_arpi": prior_arpi,
        "prior_docetaxel": prior_docetaxel,
        "prior_lu177": prior_lu177,
        "chemotherapy_delay_candidate": chemotherapy_delay_candidate,
        "trial_refs": trial_refs,
        "evidence_tier": "A",
        "standard_schedule": "7.4 GBq IV cada 6 semanas × 6 ciclos (dosis acumulada 44.4 GBq).",
        "rationale": (
            "Lu-177 PSMA-617 mejora SG y rPFS en mCRPC PSMA+ post-ARPI; VISION lo valida post-taxano "
            "y PSMAfore pre-taxano cuando existe racional para diferir docetaxel. Exige PSMA estructurado "
            "(SUV lesión ≥ hígado), reserva medular/renal preservada y ausencia de lesiones dominantes "
            "PSMA-negativas."
        ),
    }


__all__ = ["evaluate_vision_eligibility"]
