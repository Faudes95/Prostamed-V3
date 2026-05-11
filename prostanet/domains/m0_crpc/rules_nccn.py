from __future__ import annotations

from prostanet.shared.advanced_support_normalizer import normalize_advanced_support_payload
from prostanet.shared.metastatic_profile import resolve_metastatic_state_context


def _flag(payload: dict, key: str, default: str = "0") -> bool:
    return str(payload.get(key, default)).strip().lower() in {"1", "true", "yes", "si", "sí"}


def evaluate_m0_crpc(payload: dict) -> dict:
    payload = normalize_advanced_support_payload(payload, state="m0_crpc")
    psadt = float(payload.get("psadt_months", 999) or 999)
    seizure_risk = _flag(payload, "comorbidity_seizure")
    castrate_confirmed = _flag(payload, "castrate_testosterone_confirmed")
    imaging_negative = _flag(payload, "imaging_negative")
    frailty_status = str(payload.get("frailty_status", "Fit") or "Fit").strip()
    cardio_risk = _flag(payload, "cv_risk_documented")
    ddi_review_status = str(payload.get("ddi_review_status") or "").strip().lower()
    ddi_reviewed = ddi_review_status == "completed"
    current_medications = str(payload.get("current_medications") or "").strip()
    dermatitis_history = _flag(payload, "dermatitis_history")
    conventional_imaging_modality = str(payload.get("conventional_imaging_modality", "Desconocida") or "Desconocida").strip()
    conventional_imaging_date = str(payload.get("conventional_imaging_date") or "").strip()
    current_medications_present = bool(current_medications)
    metastatic_state_context = resolve_metastatic_state_context(payload)
    metastatic_stage_resolved = str(metastatic_state_context.get("metastatic_stage_resolved") or "M0")
    metastatic_detection_basis = str(metastatic_state_context.get("metastatic_detection_basis") or "unknown")
    restaging_update_required = bool(metastatic_state_context.get("restaging_update_required"))
    high_risk_nmcrpc = castrate_confirmed and imaging_negative and psadt <= 10
    observe_only = castrate_confirmed and imaging_negative and psadt > 10
    prefer_darolutamide = high_risk_nmcrpc and (
        seizure_risk
        or frailty_status.lower() in {"vulnerable", "frail"}
        or cardio_risk
        or (current_medications_present and not ddi_reviewed)
    )
    selection_safety_profile = {
        "seizure_risk": seizure_risk,
        "frailty_status": frailty_status,
        "cardio_risk": cardio_risk,
        "ddi_review_status": ddi_review_status,
        "current_medications_present": current_medications_present,
        "dermatitis_history": dermatitis_history,
        "conventional_imaging_modality": conventional_imaging_modality,
        "conventional_imaging_date": conventional_imaging_date,
        "metastatic_stage_resolved": metastatic_stage_resolved,
        "metastatic_detection_basis": metastatic_detection_basis,
        "advanced_pro_bundle": dict(payload.get("advanced_pro_bundle") or {}),
        "cognitive_screening_bundle": dict(payload.get("cognitive_screening_bundle") or {}),
    }
    if not castrate_confirmed:
        return {
            "label": "CRPC no confirmada",
            "high_risk_nmcrpc": False,
            "prefer_darolutamide": False,
            "observe_only": False,
            "castrate_confirmed": False,
            "imaging_negative": imaging_negative,
            "candidate_regimens_under_consideration": ["ADT_MONO"],
            "selection_safety_profile": selection_safety_profile,
            "recommendation": "Confirm castrate-range testosterone and optimize androgen deprivation before assigning a non-metastatic castration-resistant state.",
        }
    if not imaging_negative:
        if metastatic_stage_resolved != "M0":
            if restaging_update_required:
                recommendation = str(
                    metastatic_state_context.get("restaging_update_reason")
                    or "El caso ya corresponde a M1; se requiere restadificación actualizada para dirigir el curso clínico actual."
                )
            elif metastatic_detection_basis == "psma_only":
                recommendation = "Metástasis documentadas por PET PSMA; el caso ya corresponde a M1."
            elif metastatic_detection_basis == "conventional":
                recommendation = "Metástasis documentadas por imagen convencional; el caso ya corresponde a M1."
            elif metastatic_detection_basis == "both":
                recommendation = "Metástasis documentadas por PET PSMA e imagen convencional; el caso ya corresponde a M1."
            else:
                recommendation = "Existe enfermedad metastásica documentada; m0 CRPC ya no es elegible."
        else:
            recommendation = "Do not intensify as nmCRPC until conventional imaging confirms the disease remains non-metastatic."
        return {
            "label": "M1 documentado o imagen no concluyente" if metastatic_stage_resolved != "M0" else "Imagen positiva o no concluyente",
            "high_risk_nmcrpc": False,
            "prefer_darolutamide": False,
            "observe_only": False,
            "castrate_confirmed": True,
            "imaging_negative": False,
            "candidate_regimens_under_consideration": (
                ["ADT_PROGRESSION_VERIFICATION", "RESTAGING"]
                if metastatic_stage_resolved != "M0"
                else ["RESTAGING", "M1_RECLASSIFICATION"]
            ),
            "selection_safety_profile": selection_safety_profile,
            "metastatic_stage_resolved": metastatic_stage_resolved,
            "metastatic_detection_basis": metastatic_detection_basis,
            "restaging_update_required": restaging_update_required,
            "recommendation": recommendation,
        }
    candidate_regimens = ["OBSERVATION"] if observe_only else ["ADT_ENZALUTAMIDE", "ADT_APALUTAMIDE", "ADT_DAROLUTAMIDE"]
    return {
        "label": "M0 CRPC",
        "high_risk_nmcrpc": high_risk_nmcrpc,
        "prefer_darolutamide": prefer_darolutamide,
        "observe_only": observe_only,
        "castrate_confirmed": True,
        "imaging_negative": True,
        "candidate_regimens_under_consideration": candidate_regimens,
        "selection_safety_profile": selection_safety_profile,
        "darolutamide_preference_reasons": [
            reason
            for reason, active in (
                ("Riesgo convulsivo", seizure_risk),
                ("Fragilidad relativa", frailty_status.lower() in {"vulnerable", "frail"}),
                ("Riesgo cardiovascular", cardio_risk),
                ("Polifarmacia con revisión DDI pendiente", current_medications_present and not ddi_reviewed),
            )
            if active
        ],
        "enzalutamide_caution_reasons": [
            reason
            for reason, active in (
                ("Riesgo convulsivo o vulnerabilidad neurológica", seizure_risk),
                ("Revisión DDI pendiente con polifarmacia", current_medications_present and not ddi_reviewed),
                ("Fragilidad/carga de caídas", frailty_status.lower() in {"vulnerable", "frail"}),
            )
            if active
        ],
        "apalutamide_caution_reasons": [
            reason
            for reason, active in (
                ("Riesgo convulsivo o vulnerabilidad neurológica", seizure_risk),
                ("Antecedente dermatológico relevante", dermatitis_history),
                ("Revisión DDI pendiente con polifarmacia", current_medications_present and not ddi_reviewed),
            )
            if active
        ],
        "recommendation": (
            "Use ARPI intensification when PSADT is short, testosterone remains castrate and conventional imaging is still negative."
            if high_risk_nmcrpc
            else "Observe with continued ADT when PSADT exceeds 10 months and imaging remains negative."
        ),
    }
