from __future__ import annotations

from prostanet.domains.adt_progression_verification.rules_nccn import _normalize_castrate_status


def classify_eau(payload: dict) -> dict:
    castrate_status = _normalize_castrate_status(payload)
    imaging_status = str(payload.get("conventional_imaging_status", "not_restaged") or "not_restaged").upper()

    if castrate_status == "not_castrate":
        return {
            "label": "Supresión androgénica inadecuada",
            "risk_group": "ADT_FAILURE",
            "classification": "suppression_failure_or_inadequate_castration",
            "recommendation": "Verificar y optimizar la supresión androgénica antes de catalogar enfermedad resistente a la castración.",
        }
    if castrate_status != "confirmed_castrate":
        return {
            "label": "Progresión bajo ADT pendiente de verificación",
            "risk_group": "ADT_VERIFICATION",
            "classification": "biochemical_progression_on_adt_pending_verification",
            "recommendation": "La EAU 2026 también exige confirmar testosterona en rango de castración y reestadificar antes de etiquetar CRPC.",
        }
    if imaging_status == "M1":
        return {
            "label": "Candidato confirmado a M1 CRPC",
            "risk_group": "M1_CRPC_CANDIDATE",
            "classification": "confirmed_mcrpc_candidate",
            "recommendation": "Si la progresión ocurre con testosterona en rango de castración y metástasis en imagen convencional, el caso entra a la vía de M1 CRPC.",
        }
    if imaging_status == "M0":
        return {
            "label": "Candidato confirmado a M0 CRPC",
            "risk_group": "M0_CRPC_CANDIDATE",
            "classification": "confirmed_nmcrpc_candidate",
            "recommendation": "Si la progresión ocurre con testosterona en rango de castración y sin metástasis en imagen convencional, el caso entra a la vía de M0 CRPC.",
        }
    return {
        "label": "Progresión bajo ADT pendiente de reestadificación",
        "risk_group": "ADT_VERIFICATION",
        "classification": "biochemical_progression_on_adt_pending_verification",
        "recommendation": "Completar reestadificación convencional antes de asignar M0 CRPC o M1 CRPC.",
    }

