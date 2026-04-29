from __future__ import annotations

from typing import Any


def _is_true(value: Any) -> bool:
    return str(value).lower() in {"1", "true", "yes", "si", "on"}


def _present(value: Any) -> bool:
    return value not in (None, "", "No aplica", "No realizado", "Desconocido", "Desconocida")


def build_decision_quality(module_id: str, payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    eligible = result.get("eligible_treatments", []) or []
    primary = result.get("nccn_primary", {}) or {}
    comparison = (result.get("eau_comparison", {}) or {}).get("comparison", {}) or {}
    missing = list(result.get("missing_critical_inputs", []) or [])
    recommendation_family = ""
    if eligible:
        first = eligible[0]
        recommendation_family = first if isinstance(first, str) else str(first.get("name", "")).strip()
    recommendation_family = recommendation_family or primary.get("tratamiento_principal") or primary.get("label") or result.get("state", module_id)

    why_not_more_confident: list[str] = []
    unsupported_or_escalate = False
    adverse_variant_type = str(payload.get("adverse_histology_variant_type", "none") or "none")
    if adverse_variant_type == "none" and _is_true(payload.get("rare_histology_variant")):
        adverse_variant_type = "other_aggressive_unspecified"

    if missing:
        why_not_more_confident.append(
            "Faltan datos clinicos que podrian cambiar la conducta: " + ", ".join(str(item) for item in missing) + "."
        )

    if str(comparison.get("status", "")).strip() not in {"", "coincide"}:
        why_not_more_confident.append(
            "Existe una diferencia relevante entre NCCN y EAU que debe contextualizarse con revision clinica."
        )

    if adverse_variant_type not in {"none", ""}:
        why_not_more_confident.append(
            f"Variante histológica adversa documentada: {adverse_variant_type}."
        )
    if adverse_variant_type in {"small_cell_neuroendocrine", "sarcomatoid", "signet_ring", "mixed_multiple", "other_aggressive", "other_aggressive_unspecified"}:
        unsupported_or_escalate = True
        why_not_more_confident.append(
            "Variante histológica agresiva poco común documentada: se recomienda revisión por experto o tumor board."
        )

    if _is_true(payload.get("neuroendocrine_features")):
        unsupported_or_escalate = True
        why_not_more_confident.append(
            "Rasgos neuroendocrinos emergentes documentados: el motor modular debe escalar a revision humana."
        )

    if module_id in {"m0_crpc", "m1_crpc"} and not _is_true(payload.get("castrate_testosterone_confirmed")):
        why_not_more_confident.append(
            "No existe confirmacion estructurada de testosterona en rango de castracion."
        )

    if module_id == "adt_progression_verification":
        castrate_status = str(payload.get("castrate_testosterone_status", "unknown") or "unknown")
        if castrate_status != "confirmed_castrate":
            why_not_more_confident.append(
                "El caso sigue en verificación porque la testosterona en rango de castración no está confirmada."
            )
        if str(payload.get("conventional_imaging_status", "not_restaged") or "not_restaged") == "not_restaged":
            why_not_more_confident.append(
                "Falta reestadificación convencional suficiente para separar con certeza M0 CRPC de M1 CRPC."
            )

    if module_id == "m1_crpc" and _is_true(payload.get("psma_positive")) and _is_true(payload.get("psma_negative_dominant_lesions")):
        why_not_more_confident.append(
            "La elegibilidad PSMA no es limpia porque existen lesiones dominantes PSMA-negativas."
        )

    if (
        module_id == "localized_initial"
        and not all(
            _present(payload.get(field))
            for field in ("ecog_score", "charlson_score", "frailty_status", "g8_score", "anesthesia_surgical_fitness")
        )
    ):
        why_not_more_confident.append(
            "Falta estructura objetiva de fitness/comorbilidad (ECOG, Charlson, G8/frailty o aptitud anestésica) para sostener la decisión local con máxima confianza."
        )

    if module_id in {"post_prostatectomy", "recurrence_bcr", "post_radiotherapy_or_local_salvage"} and primary.get("risk_group") in {"HIGH", "VERY HIGH", "REGIONAL N1M0"} and not _present(payload.get("life_expectancy_years")):
        why_not_more_confident.append(
            "La expectativa de vida no esta estructurada y sigue siendo importante para modular la intensidad del tratamiento."
        )

    requires_human_review = unsupported_or_escalate or bool(why_not_more_confident)
    if unsupported_or_escalate:
        confidence_category = "escalar"
    elif why_not_more_confident:
        confidence_category = "vigilada"
    else:
        confidence_category = "alta"

    return {
        "state_classification": result.get("state_classification_override", result.get("state", module_id)),
        "recommendation_family": recommendation_family,
        "confidence_category": confidence_category,
        "requires_human_review": requires_human_review,
        "unsupported_or_escalate": unsupported_or_escalate,
        "why_not_more_confident": why_not_more_confident,
    }
