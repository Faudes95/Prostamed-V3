from __future__ import annotations

from typing import Any

from clinical_scores import docetaxel_fitness
from prostanet.domains.patient_tracking.arpi_selection_engine import (
    build_arpi_capture_contract,
    candidate_regimens_for_state,
    is_arpi_eligible_state,
)
from prostanet.domains.patient_tracking.palliative_longitudinal import (
    ADVANCED_PALLIATIVE_STATES,
    PALLIATIVE_GOALS_FIELDS,
    PALLIATIVE_URGENT_FIELDS,
    build_palliative_monitoring_package,
    build_palliative_transition_bundle,
)
from prostanet.domains.patient_tracking.survivorship_longitudinal import (
    build_survivorship_monitoring_package,
    build_survivorship_transition_bundle,
)
from prostanet.domains.patient_tracking.reconciled_state import build_reconciled_state, derive_post_prostatectomy_course
from prostanet.domains.patient_tracking.therapeutic_family_engine import (
    build_active_regimen_monitoring_package,
    family_label,
    regimen_family_code,
)
from prostanet.shared.gleason_profile import apply_gleason_profile, normalize_gleason_profile
from prostanet.shared.metastatic_profile import build_metastatic_profile, derive_mhspc_burden_context


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No documentado", "No realizado", "Desconocido", "Desconocida", "unknown", "UNKNOWN")


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in values if str(item or "").strip()))


def _text_contains_any(text: str, needles: tuple[str, ...]) -> bool:
    haystack = str(text or "").lower()
    return any(needle in haystack for needle in needles)


def _blocking_input_satisfied(field_name: str, field_values: dict[str, Any]) -> bool:
    value = field_values.get(field_name)
    if field_name == "ecog" and not _is_present(value):
        value = field_values.get("ecog_score") or field_values.get("ecog_performance_status")
    elif field_name == "imaging_negative" and not _is_present(value):
        conventional_status = str(field_values.get("conventional_imaging_status") or "").strip().lower()
        if conventional_status in {"m0", "negative", "negativo", "negative_conventional"}:
            return True
    elif field_name == "castrate_testosterone_confirmed" and not _is_present(value):
        testosterone_status = str(field_values.get("castrate_testosterone_status") or "").strip().lower()
        if testosterone_status in {"confirmed_castrate", "castrate", "confirmed"}:
            return True
        testosterone = _safe_float(field_values.get("testosterone") or field_values.get("testosterone_current"))
        if testosterone is not None and testosterone <= 50:
            return True
    elif field_name == "psa" and not _is_present(value):
        value = field_values.get("bcr_psa") or field_values.get("psa_current") or field_values.get("psa_postop")
    elif field_name == "psa_postop" and not _is_present(value):
        value = field_values.get("bcr_psa") or field_values.get("psa_current") or field_values.get("psa")
    elif field_name == "psadt_months" and not _is_present(value):
        value = field_values.get("psadt_at_bcr")
    elif field_name == "pathologic_stage" and not _is_present(value):
        value = (
            field_values.get("pathologic_stage_group")
            or field_values.get("pathologic_tstage")
            or field_values.get("pathologic_nstage")
            or field_values.get("pathologic_mstage")
        )
    elif field_name == "current_adt_context" and not _is_present(value):
        value = field_values.get("current_treatment") or field_values.get("drug_scheme")
    elif field_name == "metastasis_count" and not _is_present(value):
        value = derive_mhspc_burden_context(field_values).get("metastasis_count")
    elif field_name == "isup_grade" and not _is_present(value):
        value = normalize_gleason_profile(field_values).get("isup_grade")
    elif field_name == "metastasis_site":
        profile = build_metastatic_profile(field_values)
        if str(profile.get("m_substage_resolved") or "M0").upper() != "M0":
            return True
        value = field_values.get("metastasis_site")
    elif field_name == "volume_disease" and not _is_present(value):
        burden = derive_mhspc_burden_context(field_values)
        value = burden.get("volume_disease") if burden.get("volume_disease") in {"high", "low"} else None
    elif field_name == "bone_distribution_documented":
        profile = build_metastatic_profile(field_values)
        if not bool(profile.get("bone_metastasis_present")):
            return True
        burden = derive_mhspc_burden_context(field_values)
        return bool((burden.get("bone_axial_count") or 0) + (burden.get("bone_appendicular_count") or 0) > 0)
    if field_name == "psma_pet_done":
        return str(value or "").strip().lower() in {"1", "true", "si", "sí", "yes"}
    return _is_present(value)


def _descriptor(field_name: str, *, bucket: str, why_now: str, decision_domains_blocked: list[str], capture_target: str) -> dict[str, Any]:
    return {
        "field_name": field_name,
        "bucket": bucket,
        "why_now": why_now,
        "decision_domains_blocked": list(decision_domains_blocked or []),
        "capture_target": capture_target,
    }


def _overlay_values(values: dict[str, Any], *sources: dict[str, Any], keys: set[str]) -> None:
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in keys:
            value = source.get(key)
            if _is_present(value):
                values[key] = value


STATE_RULES = {
    "diagnostic_workup": {
        "blocking_inputs": ["psa", "psad", "pirads_score", "dre_suspicious"],
        "optional_context_inputs": ["family_history_positive", "germline_risk_mutation", "planned_biopsy_route"],
        "decision_domains_blocked": ["diagnostic_confirmation", "biopsy_timing"],
        "why": "La decisión diagnóstica inicial requiere riesgo clínico, densidad de PSA e imagen dirigida.",
        "capture_target": "intake",
        "focus": "official_diagnosis",
    },
    "post_negative_biopsy_followup": {
        "blocking_inputs": ["psa", "psad", "pirads_score", "prior_biopsy_count"],
        "optional_context_inputs": ["persistent_lesion_signal", "prior_biopsy_mri_targeted"],
        "decision_domains_blocked": ["repeat_biopsy", "diagnostic_reopening"],
        "why": "Sin MRI/PSAD y contexto de biopsias previas no puede definirse si debe reabrirse el estudio.",
        "capture_target": "followup",
        "focus": "official_diagnosis",
    },
    "localized_initial": {
        "blocking_inputs": ["gleason_primary", "gleason_secondary", "isup_grade", "psa"],
        "optional_context_inputs": ["clinical_tstage", "num_cores_positive", "total_cores", "max_core_involvement", "prior_mpmri_pirads_score"],
        "decision_domains_blocked": ["risk_stratification", "local_therapy_selection", "active_surveillance"],
        "why": "La estratificación localizada y la selección entre vigilancia activa, cirugía o RT requieren patología y carga tumoral basal.",
        "capture_target": "intake",
        "focus": "official_diagnosis",
    },
    "post_prostatectomy": {
        "blocking_inputs": ["psa_postop", "pathologic_stage"],
        "optional_context_inputs": ["decipher_risk", "ece_status", "svi_status", "lni_status"],
        "decision_domains_blocked": ["post_rp_followup", "salvage_window"],
        "why": "El seguimiento postoperatorio depende de PSA ultrasensible y patología definitiva.",
        "capture_target": "followup",
        "focus": "psa_monitoring",
    },
    "recurrence_bcr": {
        "blocking_inputs": ["psa", "psadt_months"],
        "optional_context_inputs": ["salvage_local_feasible", "psma_pet_done", "conventional_imaging_status", "decipher_risk"],
        "decision_domains_blocked": ["salvage_decision", "restaging"],
        "why": "La recaída bioquímica requiere cinética de PSA, antecedente local y restadificación para decidir rescate temprano.",
        "capture_target": "followup",
        "focus": "restaging",
    },
    "post_radiotherapy_or_local_salvage": {
        "blocking_inputs": ["psa_current", "psa_nadir", "phoenix_delta"],
        "optional_context_inputs": [
            "prior_rt_modality",
            "prior_rt_dose",
            "prior_rt_fields",
            "biopsy_proven_local_recurrence",
            "mpmri_done",
            "mpmri_localized_recurrence",
            "psma_pet_done",
        ],
        "decision_domains_blocked": ["post_rt_confirmation", "post_rt_local_salvage", "restaging"],
        "why": "La recurrencia post-RT no puede cerrar salvage local sin Phoenix o confirmación local equivalente, reestadificación dirigida y matriz real de factibilidad anatómica/funcional.",
        "capture_target": "followup",
        "focus": "restaging",
    },
    "adt_progression_verification": {
        "blocking_inputs": ["testosterone", "current_adt_context", "progression_pattern", "conventional_imaging_status"],
        "optional_context_inputs": ["drug_scheme", "line_of_therapy_number", "psa", "psma_pet_done"],
        "decision_domains_blocked": ["castration_status", "crpc_restage"],
        "why": "No debe confirmarse progresión resistente a castración sin testosterona sérica y patrón de progresión documentado.",
        "capture_target": "followup",
        "focus": "advanced_sequencing",
    },
    "m0_crpc": {
        "blocking_inputs": ["psadt_months", "testosterone", "current_adt_context", "imaging_negative"],
        "optional_context_inputs": [
            "comorbidity_seizure",
            "frailty_status",
            "cv_risk_documented",
            "drug_interaction_reviewed",
            "current_medications",
            "dermatitis_history",
            "conventional_imaging_modality",
            "conventional_imaging_date",
        ],
        "decision_domains_blocked": ["nmcrpc_intensification", "arpi_safety"],
        "why": "La intensificación en nmCRPC depende de PSADT, castración confirmada y perfil de seguridad del ARPI.",
        "capture_target": "followup",
        "focus": "advanced_sequencing",
    },
    "m1_crpc": {
        "blocking_inputs": ["testosterone", "line_of_therapy_number", "drug_scheme", "progression_pattern"],
        "optional_context_inputs": [
            "hrr_status",
            "brca2_status",
            "psma_positive",
            "psma_negative_dominant_lesions",
            "ecog_score",
            "frailty_status",
            "child_pugh_score",
            "cv_risk_documented",
            "drug_interaction_reviewed",
            "current_medications",
            "hepatic_risk_factors",
        ],
        "decision_domains_blocked": ["mcrpc_sequencing", "precision_pathway", "psma_pathway"],
        "why": "La secuenciación en mCRPC exige castración documentada, línea terapéutica, progresión y biomarcadores accionables.",
        "capture_target": "followup",
        "focus": "advanced_sequencing",
    },
    "mcspc_oligo_metachronous": {
        "blocking_inputs": ["metastasis_site", "metastasis_count", "ecog", "bone_distribution_documented"],
        "optional_context_inputs": [
            "psma_pet_done",
            "psma_rads_score",
            "prior_local_therapy_context",
            "comorbidity_seizure",
            "frailty_status",
            "child_pugh_score",
            "cv_risk_documented",
            "drug_interaction_reviewed",
            "hepatic_risk_factors",
        ],
        "decision_domains_blocked": ["mhspc_backbone", "mdt_eligibility"],
        "why": "La definición de oligometástasis real y el backbone sistémico dependen de carga metastásica, distribución ósea, imagen y fitness.",
        "capture_target": "followup",
        "focus": "restaging",
    },
    "mcspc_low_volume_sync_oligo": {
        "blocking_inputs": ["metastasis_site", "metastasis_count", "ecog", "bone_distribution_documented"],
        "optional_context_inputs": [
            "primary_local_treatment_done",
            "psma_pet_done",
            "comorbidity_seizure",
            "frailty_status",
            "child_pugh_score",
            "cv_risk_documented",
            "drug_interaction_reviewed",
            "hepatic_risk_factors",
        ],
        "decision_domains_blocked": ["mhspc_backbone", "primary_rt"],
        "why": "El bajo volumen sincrónico debe estratificarse con distribución ósea documentada para decidir RT al primario, doblete o escalamiento.",
        "capture_target": "followup",
        "focus": "restaging",
    },
    "mcspc_high_volume": {
        "blocking_inputs": ["metastasis_site", "metastasis_count", "ecog", "bone_distribution_documented"],
        "optional_context_inputs": ["performance_status_driver", "bone_pain", "hrr_status", "brca2_status", "dxa_baseline_done"],
        "decision_domains_blocked": ["mhspc_triplet", "precision_pathway", "bone_support"],
        "why": "El mHSPC de alto volumen requiere carga metastásica, distribución ósea documentada, fitness y biomarcadores para elegir doblete/triplete y soporte óseo.",
        "capture_target": "followup",
        "focus": "advanced_sequencing",
    },
}


ABIRATERONE_RULE = {
    "blocking_inputs": ["ast", "alt", "bilirubin", "potassium", "systolic_bp", "glucose"],
    "optional_context_inputs": ["weight_kg", "edema_grade", "hba1c"],
    "decision_domains_blocked": ["abiraterone_safety", "hepatic_monitoring"],
    "why": "Abiraterona requiere monitorización hepática, potasio, presión arterial y glucosa para continuar con seguridad.",
}


PSMA_RULE = {
    "blocking_inputs": [
        "psma_radioligand",
        "psma_rads_score",
        "psma_uptake_pattern",
        "psma_negative_dominant_lesions",
    ],
    "optional_context_inputs": [
        "psma_index_lesion_suvmax",
        "psma_total_lesions",
        "psma_lesion_locations",
        "psma_management_changed",
    ],
    "decision_domains_blocked": ["psma_pathway", "radioligand_selection"],
    "why": "La vía PSMA/radioligando necesita fenotipo estructurado, confianza diagnóstica y discordancia biológica documentada.",
}


ACTIVE_SURVEILLANCE_RULE = {
    "blocking_inputs": ["confirmatory_biopsy_done", "mri_interval_months", "psa", "num_cores_positive"],
    "optional_context_inputs": ["max_core_involvement", "pirads_score", "upgrade_detected"],
    "decision_domains_blocked": ["as_reclassification", "conversion_to_treatment"],
    "why": "La vigilancia activa solo puede sostenerse con biopsia confirmatoria, MRI seriada y triggers de reclasificación actualizados.",
}


DOCETAXEL_HIGH_VOLUME_STATES = {
    "mcspc_high_volume",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
}


LOCALIZED_PRO_FIELDS = [
    "epic26_urinary_domain",
    "epic26_sexual_domain",
    "epic26_bowel_domain",
    "epic26_hormonal_domain",
    "ipss_total",
    "iief5_score",
    "eq5d_vas",
]


ADVANCED_PRO_FIELDS = [
    "fact_p_total",
    "eortc_qlq_c30_global_health",
    "eortc_qlq_c30_physical",
    "eortc_qlq_c30_role",
    "eortc_qlq_c30_emotional",
    "eortc_qlq_c30_fatigue",
    "eortc_qlq_c30_pain",
    "bpi_worst_pain",
    "facit_fatigue_total",
    "eq5d_vas",
    "anxiety_score",
]


DOCETAXEL_ELIGIBILITY_RULE = {
    "decision_domains_blocked": ["mhspc_triplet"],
    "why": "El triplete con docetaxel solo puede cerrarse cuando biometría, pruebas hepáticas, alergias relevantes y contexto funcional están vigentes y documentados.",
}


def _field_values(patient: dict[str, Any]) -> dict[str, Any]:
    snapshot = patient.get("longitudinal_truth_snapshot") or {}
    values = dict(snapshot.get("field_values") or {})
    baseline = dict(patient.get("baseline") or {})
    assessment_inputs = dict(((patient.get("latest_assessment") or {}).get("input_snapshot") or {}))
    latest_followup = (patient.get("follow_ups") or [{}])[-1] if patient.get("follow_ups") else {}
    latest_followup_payload = (((latest_followup.get("visit_bundle") or {}).get("payload")) or {}) if latest_followup else {}
    latest_stage_visit = (patient.get("stage_visits") or [{}])[-1] if patient.get("stage_visits") else {}
    stage_payload = (((latest_stage_visit.get("visit_bundle") or {}).get("payload")) or {}) if latest_stage_visit else {}
    latest_signal_snapshot = dict(patient.get("latest_signal_snapshot") or {})
    latest_biopsy = (patient.get("biopsies") or [{}])[-1] if patient.get("biopsies") else {}
    bcr = dict(patient.get("bcr") or {})
    as_protocol = dict(patient.get("active_surveillance_protocol") or {})
    as_legacy = dict(patient.get("active_surveillance") or {})
    latest_treatment = (patient.get("treatments") or [{}])[-1] if patient.get("treatments") else {}
    regimen_json = dict(latest_treatment.get("regimen_json") or {}) if isinstance(latest_treatment.get("regimen_json"), dict) else {}

    for source in (baseline, assessment_inputs, latest_signal_snapshot, latest_followup, latest_followup_payload, stage_payload, latest_biopsy, bcr, as_protocol, as_legacy, latest_treatment, regimen_json):
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if _is_present(value) and not _is_present(values.get(key)):
                values[key] = value

    _overlay_values(
        values,
        latest_followup,
        latest_followup_payload,
        stage_payload,
        latest_treatment,
        regimen_json,
        keys={
            "conventional_imaging_status",
            "progression_pattern",
            "line_of_therapy_number",
            "line_of_therapy",
            "drug_scheme",
            "current_treatment",
            "psma_pet_done",
            "psma_positive",
            "psma_radioligand",
            "psma_rads_score",
            "psma_uptake_pattern",
            "psma_negative_dominant_lesions",
            "psma_stage_after_psma",
            "psadt_months",
            "testosterone",
            "testosterone_current",
            "current_adt_context",
            "mcrpc_line_context",
            "prior_therapy",
        },
    )

    values = apply_gleason_profile(values)

    if not _is_present(values.get("management_track")) and _is_present(latest_followup.get("management_track")):
        values["management_track"] = latest_followup.get("management_track")
    if not _is_present(values.get("state")) and _is_present(latest_followup.get("state_at_visit")):
        values["state"] = latest_followup.get("state_at_visit")
    if not _is_present(values.get("psma_pet_done")) and _is_present(patient.get("baseline", {}).get("psma_pet_done")):
        values["psma_pet_done"] = patient.get("baseline", {}).get("psma_pet_done")
    psma_profile = dict(patient.get("psma_structured_profile") or {})
    if not _is_present(values.get("psma_pet_done")) and psma_profile.get("available"):
        values["psma_pet_done"] = 1
    if not _is_present(values.get("psma_rads_score")) and _is_present(psma_profile.get("psma_rads_score")):
        values["psma_rads_score"] = psma_profile.get("psma_rads_score")
    if not _is_present(values.get("psma_uptake_pattern")) and _is_present(psma_profile.get("psma_uptake_pattern")):
        values["psma_uptake_pattern"] = psma_profile.get("psma_uptake_pattern")
    if not _is_present(values.get("line_of_therapy_number")) and _is_present(latest_treatment.get("line_of_therapy")):
        values["line_of_therapy_number"] = latest_treatment.get("line_of_therapy")
    if not _is_present(values.get("line_of_therapy_number")) and _is_present(values.get("line_of_therapy")):
        values["line_of_therapy_number"] = values.get("line_of_therapy")
    if not _is_present(values.get("drug_scheme")) and _is_present(latest_treatment.get("drug_scheme")):
        values["drug_scheme"] = latest_treatment.get("drug_scheme")
    if not _is_present(values.get("psa")) and _is_present(bcr.get("bcr_psa")):
        values["psa"] = bcr.get("bcr_psa")
    if not _is_present(values.get("psa_postop")) and _is_present(bcr.get("bcr_psa")):
        values["psa_postop"] = bcr.get("bcr_psa")
    if not _is_present(values.get("psadt_months")) and _is_present(bcr.get("psadt_at_bcr")):
        values["psadt_months"] = bcr.get("psadt_at_bcr")
    testosterone_value = _safe_float(values.get("testosterone")) or _safe_float(values.get("testosterone_current")) or _safe_float(values.get("testosterone_value"))
    if testosterone_value is not None and not _is_present(values.get("castrate_testosterone_status")):
        values["castrate_testosterone_status"] = "confirmed_castrate" if testosterone_value <= 50 else "not_castrate"
    return values


def build_decision_input_requirements(
    patient: dict[str, Any],
    *,
    effective_state: str = "",
    effective_management_track: str = "",
    latest_assessment: dict[str, Any] | None = None,
    next_best_action: dict[str, Any] | None = None,
) -> dict[str, Any]:
    field_values = _field_values(patient)
    reconciliation = build_reconciled_state(patient, latest_assessment or patient.get("latest_assessment"))
    current_state = (
        effective_state
        or str(field_values.get("state") or "")
        or (latest_assessment or {}).get("state")
        or (patient.get("latest_assessment") or {}).get("state")
        or (patient.get("prior_history") or {}).get("current_state")
        or "diagnostic_workup"
    )
    phenotype_state = str(reconciliation.get("phenotype_state") or current_state)
    progression_gate_active = bool(reconciliation.get("progression_gate_active"))
    progression_gate_reason = str(reconciliation.get("progression_gate_reason") or "")
    current_track = (
        effective_management_track
        or str(field_values.get("management_track") or "")
        or patient.get("schedule_management_track")
        or ""
    )
    treatment_text = str(field_values.get("current_treatment") or field_values.get("drug_scheme") or "").lower()
    psma_profile = dict(patient.get("psma_structured_profile") or {})
    post_prostatectomy_course = derive_post_prostatectomy_course(patient)

    hard_blocking_inputs: list[str] = []
    decision_blocking_inputs: list[str] = []
    supportive_gaps: list[str] = []
    required_to_recalculate: list[str] = []
    optional_context_inputs: list[str] = []
    decision_domains_blocked: list[str] = []
    why_these_fields_now: list[str] = []
    blocking_input_descriptors: list[dict[str, Any]] = []
    focus = "clinical_completion"
    capture_target = "followup" if patient.get("follow_ups") or patient.get("stage_visits") else "intake"
    candidate_regimens_under_consideration: list[str] = []
    regimen_specific_blocks: dict[str, dict[str, Any]] = {}
    selection_safety_profile: dict[str, Any] = {}
    arpi_capture_contract: dict[str, Any] = {
        "arpi_required_fields": [],
        "arpi_missing_inputs": [],
        "arpi_stale_inputs": [],
        "arpi_profile_completeness": "not_applicable",
        "arpi_preference_readiness": "not_applicable",
        "candidate_regimens": [],
    }
    palliative_capture_contract: dict[str, Any] = {
        "palliative_required_fields": [],
        "palliative_missing_inputs": [],
        "palliative_stale_inputs": [],
        "palliative_capture_block": {},
        "goals_of_care_capture_block": {},
        "palliative_trigger_status": "observe",
        "care_mode": "observe",
    }
    post_rt_capture_contract: dict[str, Any] = {
        "post_rt_required_fields": [],
        "post_rt_missing_inputs": [],
        "post_rt_confirmation_block": {},
        "post_rt_local_salvage_block": {},
    }

    def add_fields(fields: list[str], *, bucket: str, why: str, domains: list[str]) -> None:
        target = hard_blocking_inputs if bucket == "hard_blocking_inputs" else decision_blocking_inputs if bucket == "decision_blocking_inputs" else supportive_gaps
        for field in fields:
            if not str(field or "").strip():
                continue
            target.append(field)
            blocking_input_descriptors.append(
                _descriptor(
                    str(field),
                    bucket=bucket,
                    why_now=why,
                    decision_domains_blocked=domains,
                    capture_target=capture_target,
                )
            )

    state_rule = STATE_RULES.get(current_state, {})
    if not state_rule and current_state in DOCETAXEL_HIGH_VOLUME_STATES - {"mcspc_high_volume"}:
        state_rule = STATE_RULES.get("mcspc_high_volume", {})
    if state_rule:
        add_fields(
            list(state_rule.get("blocking_inputs", [])),
            bucket="hard_blocking_inputs",
            why=str(state_rule.get("why", "")),
            domains=list(state_rule.get("decision_domains_blocked", [])),
        )
        required_to_recalculate.extend(state_rule.get("blocking_inputs", []))
        optional_context_inputs.extend(state_rule.get("optional_context_inputs", []))
        decision_domains_blocked.extend(state_rule.get("decision_domains_blocked", []))
        why_these_fields_now.append(state_rule.get("why", ""))
        focus = state_rule.get("focus", focus)
        capture_target = state_rule.get("capture_target", capture_target)

    docetaxel_bundle: dict[str, Any] = {}
    taxane_competes_now = False
    if current_state in DOCETAXEL_HIGH_VOLUME_STATES and not progression_gate_active:
        taxane_competes_now = True
        docetaxel_bundle = docetaxel_fitness({**field_values, "state": current_state})
        candidate_regimens_under_consideration.extend(
            ["ADT_DAROLUTAMIDE", "ADT_ENZALUTAMIDE", "ADT_APALUTAMIDE", "ADT_ABIRATERONE", "ADT_DOCETAXEL"]
        )
    elif current_state == "m1_crpc":
        prior_therapy_hint = str(field_values.get("prior_therapy") or "").lower()
        prior_docetaxel_cycles_hint = _safe_float(field_values.get("prior_docetaxel_cycles")) or 0.0
        prior_docetaxel_hint = prior_docetaxel_cycles_hint >= 6 or "docetax" in prior_therapy_hint
        line_context_hint = str(field_values.get("mcrpc_line_context") or field_values.get("line_context") or "").lower()
        taxane_competes_now = (not prior_docetaxel_hint) and line_context_hint in {"", "first_line_mcrpc", "post_arpi_pre_taxane", "pre_taxane"}
        if taxane_competes_now:
            docetaxel_bundle = docetaxel_fitness({**field_values, "state": current_state, "force_docetaxel_verification": 1})
            candidate_regimens_under_consideration.append("DOCETAXEL")
            regimen_specific_blocks["DOCETAXEL"] = {
                "blocking_inputs": _dedupe(
                    list(docetaxel_bundle.get("docetaxel_missing_inputs") or [])
                    + list(docetaxel_bundle.get("docetaxel_stale_inputs") or [])
                ),
                "verification_status": str(docetaxel_bundle.get("docetaxel_verification_status") or ""),
                "base_eligibility": str(docetaxel_bundle.get("docetaxel_base_eligibility") or ""),
            }
    if docetaxel_bundle:
        verification_status = str(docetaxel_bundle.get("docetaxel_verification_status") or "verified")
        if bool(docetaxel_bundle.get("docetaxel_required_now")) and verification_status in {"pending_labs", "stale_labs"}:
            pending_docetaxel_fields = _dedupe(
                list(docetaxel_bundle.get("docetaxel_missing_inputs") or [])
                + list(docetaxel_bundle.get("docetaxel_stale_inputs") or [])
            )
            add_fields(
                pending_docetaxel_fields,
                bucket="decision_blocking_inputs",
                why=DOCETAXEL_ELIGIBILITY_RULE["why"],
                domains=DOCETAXEL_ELIGIBILITY_RULE["decision_domains_blocked"],
            )
            required_to_recalculate.extend(pending_docetaxel_fields)
            optional_context_inputs.extend(["performance_status_driver", "bone_pain"])
            decision_domains_blocked.extend(DOCETAXEL_ELIGIBILITY_RULE["decision_domains_blocked"])
            why_these_fields_now.append(DOCETAXEL_ELIGIBILITY_RULE["why"])
            focus = "advanced_sequencing"

    if is_arpi_eligible_state(current_state):
        arpi_capture_contract = build_arpi_capture_contract(
            current_state,
            field_values,
            candidate_regimens=candidate_regimens_for_state(current_state, field_values),
        )
        arpi_required_fields = list(arpi_capture_contract.get("arpi_required_fields") or [])
        if arpi_required_fields:
            add_fields(
                arpi_required_fields,
                bucket="decision_blocking_inputs",
                why="La selección molecular ARPI exige contexto oncológico, seguridad discriminadora y bundle basal de monitorización; un dato ausente no puede asumirse como ausencia de riesgo.",
                domains=["arpi_selection", "arpi_safety", "arpi_monitoring"],
            )
            required_to_recalculate.extend(arpi_required_fields)
            decision_domains_blocked.extend(["arpi_selection", "arpi_safety", "arpi_monitoring"])
            why_these_fields_now.append(
                "La preferencia molecular ARPI solo puede cerrarse con bundle completo de escenario, seguridad y monitoreo basal."
            )
            candidate_regimens_under_consideration.extend(list(arpi_capture_contract.get("candidate_regimens") or []))
            regimen_specific_blocks["ARPI_SELECTION"] = {
                "blocking_inputs": list(arpi_capture_contract.get("arpi_required_fields") or []),
                "missing_inputs": list(arpi_capture_contract.get("arpi_missing_inputs") or []),
                "stale_inputs": list(arpi_capture_contract.get("arpi_stale_inputs") or []),
                "profile_completeness": str(arpi_capture_contract.get("arpi_profile_completeness") or ""),
            }

    latest_psa = _safe_float(field_values.get("psa") or field_values.get("psa_postop"))
    prior_radiation = str(field_values.get("prior_radiation") or field_values.get("prior_secondary_rt") or "").strip().lower() in {"1", "true", "yes", "si", "sí"}
    salvage_feasible = str(field_values.get("salvage_local_feasible") or "").strip().lower()
    psma_done = str(field_values.get("psma_pet_done") or "").strip().lower()
    psadt_months = _safe_float(field_values.get("psadt_months"))
    line_of_therapy = _safe_float(field_values.get("line_of_therapy_number"))
    hrr_status = str(field_values.get("hrr_status") or "").strip().lower()
    brca2_status = str(field_values.get("brca2_status") or "").strip().lower()
    progression_pattern = str(field_values.get("progression_pattern") or "").strip().lower()
    treatment_text = treatment_text.lower()
    seizure_risk_documented = _blocking_input_satisfied("comorbidity_seizure", field_values) or _blocking_input_satisfied("seizure_history", field_values)
    frailty_documented = _blocking_input_satisfied("frailty_status", field_values)
    ddi_documented = _blocking_input_satisfied("drug_interaction_reviewed", field_values)
    hepatic_documented = _blocking_input_satisfied("child_pugh_score", field_values) or _blocking_input_satisfied("hepatic_risk_factors", field_values)
    current_meds_documented = _blocking_input_satisfied("current_medications", field_values)
    selection_safety_profile = {
        "seizure_risk_documented": seizure_risk_documented,
        "frailty_documented": frailty_documented,
        "ddi_reviewed": field_values.get("drug_interaction_reviewed"),
        "current_medications_present": bool(str(field_values.get("current_medications") or "").strip()),
        "cardio_risk_documented": _blocking_input_satisfied("cv_risk_documented", field_values),
        "hepatic_context_documented": hepatic_documented,
        "docetaxel_verification_status": str(docetaxel_bundle.get("docetaxel_verification_status") or ""),
        "arpi_profile_completeness": str(arpi_capture_contract.get("arpi_profile_completeness") or "not_applicable"),
        "arpi_preference_readiness": str(arpi_capture_contract.get("arpi_preference_readiness") or "not_applicable"),
        "arpi_missing_inputs": list(arpi_capture_contract.get("arpi_missing_inputs") or []),
        "arpi_stale_inputs": list(arpi_capture_contract.get("arpi_stale_inputs") or []),
    }

    if current_state in {"mcspc_low_volume_sync_oligo", "mcspc_oligo_metachronous"}:
        candidate_regimens_under_consideration.extend(
            ["ADT_DAROLUTAMIDE", "ADT_ENZALUTAMIDE", "ADT_APALUTAMIDE", "ADT_ABIRATERONE", "LOCAL_MDT"]
        )
        low_volume_safety_fields = [
            "comorbidity_seizure",
            "frailty_status",
            "child_pugh_score",
            "cv_risk_documented",
            "drug_interaction_reviewed",
            "hepatic_risk_factors",
        ]
        add_fields(
            low_volume_safety_fields,
            bucket="decision_blocking_inputs",
            why="En bajo volumen/oligometastásico la competencia real es entre dobletes hormonales y control local; los discriminadores de seguridad ARPI deben documentarse explícitamente.",
            domains=["mhspc_backbone", "arpi_safety"],
        )
        required_to_recalculate.extend(low_volume_safety_fields)
        regimen_specific_blocks["ARPI_DOUBLETS_LOW_VOLUME"] = {
            "blocking_inputs": low_volume_safety_fields,
            "triplet_policy": "not_applicable",
        }

    if current_state == "m0_crpc" and psadt_months is not None and psadt_months <= 10:
        nmcrpc_arpi_fields = [
            "comorbidity_seizure",
            "frailty_status",
            "cv_risk_documented",
            "drug_interaction_reviewed",
            "current_medications",
            "dermatitis_history",
            "conventional_imaging_modality",
            "conventional_imaging_date",
        ]
        candidate_regimens_under_consideration.extend(["ADT_DAROLUTAMIDE", "ADT_ENZALUTAMIDE", "ADT_APALUTAMIDE"])
        add_fields(
            nmcrpc_arpi_fields,
            bucket="decision_blocking_inputs",
            why="En nmCRPC de alto riesgo la selección entre darolutamida, enzalutamida y apalutamida depende de seguridad neurológica, fragilidad, DDI, perfil cutáneo y documentación de imagen convencional.",
            domains=["nmcrpc_intensification", "arpi_safety"],
        )
        required_to_recalculate.extend(nmcrpc_arpi_fields)
        regimen_specific_blocks["NMCRPC_ARPI"] = {
            "blocking_inputs": nmcrpc_arpi_fields,
            "candidate_regimens": ["ADT_DAROLUTAMIDE", "ADT_ENZALUTAMIDE", "ADT_APALUTAMIDE"],
        }
    elif current_state == "m0_crpc":
        candidate_regimens_under_consideration.append("OBSERVATION")

    if current_state == "m1_crpc":
        prior_therapy_text = str(field_values.get("prior_therapy") or "").lower()
        line_context_text = str(field_values.get("mcrpc_line_context") or "").lower()
        prior_abiraterone = "abirater" in prior_therapy_text
        abiraterone_competes = line_context_text in {"", "first_line_mcrpc"} and not prior_abiraterone
        if abiraterone_competes:
            candidate_regimens_under_consideration.append("ADT_ABIRATERONE")
            regimen_specific_blocks["ADT_ABIRATERONE"] = {
                "blocking_inputs": list(ABIRATERONE_RULE["blocking_inputs"]) + list(ABIRATERONE_RULE["optional_context_inputs"]),
                "reason": ABIRATERONE_RULE["why"],
            }
            add_fields(
                list(ABIRATERONE_RULE["blocking_inputs"]),
                bucket="decision_blocking_inputs",
                why="Abiraterona sigue compitiendo como opción en mCRPC y requiere datos metabólicos/hepáticos aun si el paciente todavía no la recibe.",
                domains=ABIRATERONE_RULE["decision_domains_blocked"],
            )
            required_to_recalculate.extend(ABIRATERONE_RULE["blocking_inputs"])
        if taxane_competes_now and docetaxel_bundle:
            selection_safety_profile["taxane_competes_now"] = True
            candidate_regimens_under_consideration.append("DOCETAXEL")

    if current_state == "post_prostatectomy":
        if post_prostatectomy_course == "persistent_psa":
            add_fields(
                ["psadt_months", "salvage_local_feasible"],
                bucket="decision_blocking_inputs",
                why="El PSA persistente postoperatorio exige distinguir vigilancia intensificada vs evaluación temprana de rescate.",
                domains=["salvage_decision"],
            )
            required_to_recalculate.extend(["psadt_months", "salvage_local_feasible"])
            optional_context_inputs.extend(["decipher_risk", "conventional_imaging_status"])
            decision_domains_blocked.extend(["salvage_decision"])
            why_these_fields_now.append("El PSA persistente posoperatorio aún no equivale a BCR, pero sí obliga a definir cinética y factibilidad de rescate.")
            focus = "restaging"
            if salvage_feasible in {"0", "false", "no"} or (latest_psa is not None and latest_psa >= 0.2):
                add_fields(
                    ["psma_pet_done"],
                    bucket="decision_blocking_inputs",
                    why="Si el rescate local ya no es claramente directo, se necesita imagen para redefinir el carril terapéutico.",
                    domains=["restaging"],
                )
                required_to_recalculate.append("psma_pet_done")
                decision_domains_blocked.append("restaging")

    if current_state == "localized_initial":
        add_fields(
            ["clinical_tstage"],
            bucket="decision_blocking_inputs",
            why="El T clínico sigue siendo relevante para cerrar riesgo localizado y escoger entre cirugía, RT o vigilancia.",
            domains=["risk_stratification", "local_therapy_selection"],
        )
        required_to_recalculate.append("clinical_tstage")

    if current_state == "recurrence_bcr":
        if salvage_feasible not in {"1", "true", "yes", "si", "sí"}:
            add_fields(
                ["salvage_local_feasible"],
                bucket="decision_blocking_inputs",
                why="La decisión entre rescate local e intensificación sistémica sigue abierta hasta documentar factibilidad local.",
                domains=["salvage_decision"],
            )
            required_to_recalculate.append("salvage_local_feasible")
        if psadt_months is None:
            why_these_fields_now.append("La recaída bioquímica necesita PSADT antes de cerrar el carril de rescate.")
        if (
            salvage_feasible in {"0", "false", "no"}
            or prior_radiation
            or (latest_psa is not None and latest_psa >= 0.5)
            or (post_prostatectomy_course == "true_bcr" and salvage_feasible in {"1", "true", "yes", "si", "sí"} and latest_psa is not None and latest_psa >= 0.2)
        ) and psma_done not in {"1", "true", "si", "sí", "yes"}:
            add_fields(
                ["psma_pet_done"],
                bucket="decision_blocking_inputs",
                why="La imagen dirigida cambia la decisión cuando el rescate local no es claramente directo o el contexto es post-RT.",
                domains=["restaging"],
            )
            required_to_recalculate.append("psma_pet_done")
            decision_domains_blocked.append("restaging")
            why_these_fields_now.append("Se necesita PSMA-PET para diferenciar rescate local aún factible frente a redirección sistémica.")
            focus = "restaging"
        if psma_done in {"1", "true", "si", "sí", "yes"}:
            add_fields(
                ["psma_rads_score", "psma_uptake_pattern"],
                bucket="decision_blocking_inputs",
                why="Una PSMA realizada pero no estructurada todavía no permite cerrar si la ruta sigue siendo local o ya sistémica.",
                domains=["restaging", "psma_pathway"],
            )
            required_to_recalculate.extend(["psma_rads_score", "psma_uptake_pattern"])
            add_fields(
                ["psma_radioligand", "psma_negative_dominant_lesions"],
                bucket="supportive_gaps",
                why="Estos datos refinan la confianza diagnóstica y la comparabilidad longitudinal de la imagen PSMA.",
                domains=["psma_pathway"],
            )
            optional_context_inputs.extend(["psma_radioligand", "psma_negative_dominant_lesions"])

    if current_state == "post_radiotherapy_or_local_salvage":
        candidate_regimens_under_consideration.extend(
            [
                "POST_RT_CONFIRMATION",
                "SALVAGE_PROSTATECTOMY",
                "SALVAGE_CRYOTHERAPY",
                "SALVAGE_HIFU",
                "SALVAGE_BRACHYTHERAPY",
                "PSMA_GUIDED_MDT",
                "SYSTEMIC_RESTAGING",
            ]
        )
        confirmation_fields = [
            "psa_current",
            "psa_nadir",
            "phoenix_delta",
            "biopsy_proven_local_recurrence",
            "mpmri_done",
            "mpmri_localized_recurrence",
        ]
        local_salvage_fields = [
            "prior_rt_modality",
            "prior_rt_dose",
            "prior_rt_fields",
            "biopsy_date",
            "biopsy_grade_group",
            "mpmri_date",
            "local_recurrence_site",
            "urinary_burden",
            "incontinence_burden",
            "urethral_stricture_history",
            "bowel_burden",
            "rectal_toxicity_grade",
            "prostate_volume",
            "anesthesia_surgical_fitness",
            "salvage_expertise_available",
            "psma_pet_done",
        ]
        psma_structured_fields = [
            "psma_radioligand",
            "psma_rads_score",
            "psma_uptake_pattern",
            "psma_stage_after_psma",
        ]
        add_fields(
            confirmation_fields,
            bucket="hard_blocking_inputs",
            why="No debe abrirse salvage curativo post-RT sin definir Phoenix o documentar falla local equivalente con base histológica/radiográfica.",
            domains=["post_rt_confirmation"],
        )
        add_fields(
            local_salvage_fields,
            bucket="decision_blocking_inputs",
            why="La modalidad de salvage local post-RT exige anatomía local, toxicidad GU/GI previa, aptitud anestésica y disponibilidad real de expertise.",
            domains=["post_rt_local_salvage", "restaging"],
        )
        required_to_recalculate.extend(confirmation_fields + local_salvage_fields)
        decision_domains_blocked.extend(["post_rt_confirmation", "post_rt_local_salvage", "restaging"])
        why_these_fields_now.extend(
            [
                "Phoenix o confirmación local equivalente deben cerrarse antes de sostener una vía curativa post-RT.",
                "La modalidad local preferente post-RT depende de anatomía local, toxicidad GU/GI previa, aptitud quirúrgica y expertise disponible.",
            ]
        )
        if psma_done in {"1", "true", "si", "sí", "yes"}:
            add_fields(
                psma_structured_fields,
                bucket="decision_blocking_inputs",
                why="La PSMA debe estar estructurada para distinguir rescate glandular puro, MDT oligorrecurrente o redirección sistémica.",
                domains=["restaging", "psma_pathway", "post_rt_local_salvage"],
            )
            required_to_recalculate.extend(psma_structured_fields)
            decision_domains_blocked.extend(["psma_pathway"])
        confirmation_missing = [
            field for field in confirmation_fields
            if not _blocking_input_satisfied(field, field_values)
        ]
        local_missing = [
            field for field in local_salvage_fields + (psma_structured_fields if psma_done in {"1", "true", "si", "sí", "yes"} else [])
            if not _blocking_input_satisfied(field, field_values)
        ]
        regimen_specific_blocks["POST_RT_CONFIRMATION"] = {
            "blocking_inputs": confirmation_fields,
            "missing_inputs": confirmation_missing,
        }
        regimen_specific_blocks["POST_RT_LOCAL_SALVAGE"] = {
            "blocking_inputs": local_salvage_fields + (psma_structured_fields if psma_done in {"1", "true", "si", "sí", "yes"} else []),
            "missing_inputs": local_missing,
        }
        post_rt_capture_contract = {
            "post_rt_required_fields": _dedupe(confirmation_fields + local_salvage_fields + (psma_structured_fields if psma_done in {"1", "true", "si", "sí", "yes"} else [])),
            "post_rt_missing_inputs": _dedupe(confirmation_missing + local_missing),
            "post_rt_confirmation_block": {
                "title": "Confirmar fallo bioquímico post-RT",
                "summary": "Cierra Phoenix o documenta una confirmación local equivalente antes de abrir salvage curativo.",
                "fields": confirmation_missing or confirmation_fields,
                "capture_target": "followup",
                "focus": "post_rt_confirmation",
            },
            "post_rt_local_salvage_block": {
                "title": "Completar matriz de salvage local post-RT",
                "summary": "Documenta reestadificación, toxicidad y factibilidad anatómica/funcional para elegir modalidad local o redirigir a sistémico.",
                "fields": local_missing or local_salvage_fields + (psma_structured_fields if psma_done in {"1", "true", "si", "sí", "yes"} else []),
                "capture_target": "followup",
                "focus": "post_rt_local_salvage",
            },
        }

    if _text_contains_any(treatment_text, ("abirater", "zytiga")):
        add_fields(
            ["ast", "alt", "bilirubin"],
            bucket="hard_blocking_inputs",
            why=ABIRATERONE_RULE["why"],
            domains=ABIRATERONE_RULE["decision_domains_blocked"],
        )
        add_fields(
            ["potassium", "systolic_bp", "glucose"],
            bucket="decision_blocking_inputs",
            why=ABIRATERONE_RULE["why"],
            domains=ABIRATERONE_RULE["decision_domains_blocked"],
        )
        required_to_recalculate.extend(["ast", "alt", "bilirubin"])
        optional_context_inputs.extend(ABIRATERONE_RULE["optional_context_inputs"])
        decision_domains_blocked.extend(ABIRATERONE_RULE["decision_domains_blocked"])
        why_these_fields_now.append(ABIRATERONE_RULE["why"])
        focus = "adt_safety"

    if (_text_contains_any(treatment_text, ("lutec", "pluvicto")) or (
        current_state in {"recurrence_bcr", "m1_crpc", "post_radiotherapy_or_local_salvage"} and (
            psma_profile.get("available")
            or str(field_values.get("psma_pet_done") or "").strip().lower() in {"1", "true", "si", "sí", "yes"}
        )
    )):
        psma_required_fields = ["psma_rads_score", "psma_uptake_pattern"] if psma_done in {"1", "true", "si", "sí", "yes"} else []
        if _text_contains_any(treatment_text, ("lutec", "pluvicto")):
            psma_required_fields = ["psma_radioligand", "psma_rads_score", "psma_uptake_pattern", "psma_negative_dominant_lesions"]
        add_fields(
            psma_required_fields,
            bucket="decision_blocking_inputs",
            why=PSMA_RULE["why"],
            domains=PSMA_RULE["decision_domains_blocked"],
        )
        required_to_recalculate.extend([field for field in psma_required_fields if field in {"psma_rads_score", "psma_uptake_pattern", "psma_negative_dominant_lesions"}])
        add_fields(
            [field for field in PSMA_RULE["optional_context_inputs"] if field not in psma_required_fields],
            bucket="supportive_gaps",
            why=PSMA_RULE["why"],
            domains=PSMA_RULE["decision_domains_blocked"],
        )
        optional_context_inputs.extend(PSMA_RULE["optional_context_inputs"])
        decision_domains_blocked.extend(PSMA_RULE["decision_domains_blocked"])
        why_these_fields_now.append(PSMA_RULE["why"])
        focus = "biomarker_eligibility"

    as_track_active = current_track in {"active_surveillance", "as_surveillance"}
    as_signal_present = any(
        _is_present(field_values.get(field))
        for field in ("confirmatory_biopsy_done", "confirmatory_biopsy_planned", "mri_interval_months", "upgrade_detected")
    )
    if as_track_active or current_state == "active_surveillance" or as_signal_present:
        add_fields(
            ["confirmatory_biopsy_done", "mri_interval_months"],
            bucket="hard_blocking_inputs",
            why=ACTIVE_SURVEILLANCE_RULE["why"],
            domains=ACTIVE_SURVEILLANCE_RULE["decision_domains_blocked"],
        )
        add_fields(
            ["psa", "num_cores_positive"],
            bucket="decision_blocking_inputs",
            why=ACTIVE_SURVEILLANCE_RULE["why"],
            domains=ACTIVE_SURVEILLANCE_RULE["decision_domains_blocked"],
        )
        required_to_recalculate.extend(ACTIVE_SURVEILLANCE_RULE["blocking_inputs"])
        optional_context_inputs.extend(ACTIVE_SURVEILLANCE_RULE["optional_context_inputs"])
        decision_domains_blocked.extend(ACTIVE_SURVEILLANCE_RULE["decision_domains_blocked"])
        why_these_fields_now.append(ACTIVE_SURVEILLANCE_RULE["why"])
        focus = "official_diagnosis"

    if current_state == "m0_crpc":
        if psadt_months is not None and psadt_months > 10 and line_of_therapy in (None, 0):
            supportive_gaps.extend(_dedupe(["seizure_history", "cv_risk_documented"]))
        if progression_pattern and progression_pattern not in {"biochemical_only", "mixed"}:
            add_fields(
                ["conventional_imaging_status"],
                bucket="decision_blocking_inputs",
                why="La intensificación nmCRPC pierde precisión si el patrón de progresión ya no parece exclusivamente bioquímico.",
                domains=["nmcrpc_intensification"],
            )

    if current_state == "m1_crpc":
        prior_therapy_text = str(field_values.get("prior_therapy") or "").lower()
        line_context_text = str(field_values.get("mcrpc_line_context") or "").lower()
        has_prior_taxane = any(token in prior_therapy_text for token in ("docetax", "cabazitax"))
        has_prior_arpi = any(token in prior_therapy_text for token in ("abirater", "enza", "apalut", "darolut"))
        card_or_vision_context = (
            has_prior_taxane
            and (
                has_prior_arpi
                or "post_arpi" in line_context_text
                or "post_taxane" in line_context_text
                or "later_line" in line_context_text
            )
        )
        if card_or_vision_context:
            for field in ("line_of_therapy_number", "drug_scheme", "progression_pattern"):
                hard_blocking_inputs = [item for item in hard_blocking_inputs if item != field]
                decision_blocking_inputs = [item for item in decision_blocking_inputs if item != field]
            blocking_input_descriptors = [
                item for item in blocking_input_descriptors
                if item.get("field_name") not in {"line_of_therapy_number", "drug_scheme", "progression_pattern"}
            ]
            add_fields(
                ["psma_radioligand", "psma_rads_score", "psma_uptake_pattern", "psma_negative_dominant_lesions"],
                bucket="decision_blocking_inputs",
                why="En el contexto CARD/VISION la elegibilidad PSMA estructurada pesa más que volver a pedir la línea ya conocida.",
                domains=["psma_pathway", "mcrpc_sequencing"],
            )
            required_to_recalculate.extend(["psma_rads_score", "psma_uptake_pattern", "psma_negative_dominant_lesions"])
            decision_domains_blocked.extend(["psma_pathway", "mcrpc_sequencing"])
            why_these_fields_now.append("La decisión post-taxano debe cerrarse con PSMA estructurada antes de elegir CARD/VISION o radiofármaco.")
        if line_of_therapy is not None and line_of_therapy <= 1 and not _text_contains_any(treatment_text, ("abirater", "enzalut", "apalut", "darolut")):
            add_fields(
                ["drug_scheme"],
                bucket="decision_blocking_inputs",
                why="La m1CRPC temprana debe documentar con claridad si ya recibió ARPI antes de secuenciar nuevas rutas.",
                domains=["mcrpc_sequencing"],
            )
        if hrr_status not in {"positivo", "positive", "pathogenic"} and brca2_status not in {"positivo", "positive", "pathogenic"}:
            supportive_gaps.extend(["hrr_status", "brca2_status"])

    if progression_gate_active and phenotype_state in {"mcspc_oligo_metachronous", "mcspc_low_volume_sync_oligo", "mcspc_high_volume", "mcspc_high_volume_sync", "mcspc_high_volume_metachronous"}:
        phenotype_fields = {"metastasis_site", "metastasis_count", "bone_distribution_documented", "volume_disease"}
        hard_blocking_inputs = [item for item in hard_blocking_inputs if item not in phenotype_fields]
        decision_blocking_inputs = [item for item in decision_blocking_inputs if item not in phenotype_fields]
        required_to_recalculate = [item for item in required_to_recalculate if item not in phenotype_fields]
        blocking_input_descriptors = [
            item for item in blocking_input_descriptors
            if item.get("field_name") not in phenotype_fields
        ]
        add_fields(
            ["testosterone", "current_adt_context", "progression_pattern", "conventional_imaging_status"],
            bucket="hard_blocking_inputs",
            why=progression_gate_reason or "El fenotipo metastásico ya está resuelto, pero aún falta cerrar si la progresión bajo ADT sigue siendo sensible o ya migró a CRPC.",
            domains=["castration_status", "crpc_restage"],
        )
        required_to_recalculate.extend(["testosterone", "current_adt_context", "progression_pattern", "conventional_imaging_status"])
        decision_domains_blocked.extend(["castration_status", "crpc_restage"])
        why_these_fields_now.append(
            progression_gate_reason or "El fenotipo metastásico ya está claro; ahora la decisión depende de verificar castración e imagen convencional suficiente."
        )
        focus = "advanced_sequencing"
        capture_target = "followup"

    hard_blocking_inputs = _dedupe(hard_blocking_inputs)
    decision_blocking_inputs = _dedupe(decision_blocking_inputs)
    supportive_gaps = _dedupe(supportive_gaps)
    present_blocking = [field for field in _dedupe(hard_blocking_inputs + decision_blocking_inputs) if _blocking_input_satisfied(field, field_values)]
    missing_hard = [field for field in hard_blocking_inputs if not _blocking_input_satisfied(field, field_values)]
    missing_decision = [field for field in decision_blocking_inputs if not _blocking_input_satisfied(field, field_values)]
    missing_supportive = [field for field in supportive_gaps if not _blocking_input_satisfied(field, field_values)]
    if str(docetaxel_bundle.get("docetaxel_verification_status") or "") == "stale_labs":
        stale_docetaxel_fields = [
            field
            for field in list(docetaxel_bundle.get("docetaxel_stale_inputs") or [])
            if field in hard_blocking_inputs or field in decision_blocking_inputs or field in supportive_gaps
        ]
        if stale_docetaxel_fields:
            present_blocking = [field for field in present_blocking if field not in stale_docetaxel_fields]
            missing_decision = _dedupe(missing_decision + stale_docetaxel_fields)
    missing_blocking = _dedupe(missing_hard + missing_decision)
    headline = str((next_best_action or {}).get("title") or "").strip()
    filtered_descriptors = [
        item for item in blocking_input_descriptors
        if item.get("field_name") in set(missing_blocking + missing_supportive)
    ]
    result_snapshot = dict(((latest_assessment or patient.get("latest_assessment") or {}).get("result_snapshot")) or {})
    preferred_regimen = dict(result_snapshot.get("preferred_frontline_regimen") or {})
    sequence_bundle = dict(result_snapshot.get("sequence_transition_bundle") or {})
    active_regimen_code = str(
        preferred_regimen.get("regimen_code")
        or field_values.get("drug_scheme")
        or field_values.get("current_treatment")
        or ""
    )
    active_family_code = str(
        preferred_regimen.get("family_code")
        or sequence_bundle.get("active_family")
        or regimen_family_code(active_regimen_code, fallback="observation_family")
    )
    active_monitoring_package = build_active_regimen_monitoring_package(
        active_regimen_code,
        family_code=active_family_code,
        field_values=field_values,
    )
    family_missing_inputs = {
        str(code): _dedupe(list((profile or {}).get("missing_inputs") or []))
        for code, profile in dict(result_snapshot.get("comparative_eligibility_matrix") or {}).items()
        if _dedupe(list((profile or {}).get("missing_inputs") or []))
    }
    family_stale_inputs = {
        str(code): _dedupe(list((profile or {}).get("stale_inputs") or []))
        for code, profile in dict(result_snapshot.get("comparative_eligibility_matrix") or {}).items()
        if _dedupe(list((profile or {}).get("stale_inputs") or []))
    }
    if active_family_code:
        family_missing_inputs[active_family_code] = _dedupe(
            list(family_missing_inputs.get(active_family_code) or [])
            + list(active_monitoring_package.get("missing_inputs") or [])
        )
        family_stale_inputs[active_family_code] = _dedupe(
            list(family_stale_inputs.get(active_family_code) or [])
            + list(active_monitoring_package.get("stale_inputs") or [])
        )
    monitoring_required_fields = _dedupe(list(active_monitoring_package.get("required_visit_fields") or []))
    trigger_status = str(sequence_bundle.get("trigger_status") or "")
    monitoring_capture_title = (
        f"Monitorizar {active_monitoring_package.get('active_regimen_label') or family_label(active_family_code)}"
        if monitoring_required_fields
        else "Completar monitorizacion activa"
    )
    monitoring_capture_summary = str(
        sequence_bundle.get("line_change_reason")
        or active_monitoring_package.get("monitoring_focus")
        or "La decision terapeutica activa requiere monitorizacion estructurada."
    )
    if trigger_status in {"hold", "switch", "redirect_local", "redirect_systemic"}:
        monitoring_capture_summary = (
            f"{monitoring_capture_summary} La agenda debe abrir seguridad, reestadificacion y reevaluacion de linea."
        ).strip()

    palliative_transition_bundle = build_palliative_transition_bundle(
        patient,
        state=current_state,
        management_track=current_track,
        latest_assessment=latest_assessment,
        field_values=field_values,
    )
    palliative_monitoring_package = build_palliative_monitoring_package(
        patient,
        state=current_state,
        management_track=current_track,
        latest_assessment=latest_assessment,
        field_values=field_values,
        transition_bundle=palliative_transition_bundle,
    )
    palliative_required_fields = (
        _dedupe(list(palliative_transition_bundle.get("required_visit_fields") or []))
        if current_state in ADVANCED_PALLIATIVE_STATES
        else []
    )
    palliative_missing_inputs = _dedupe(list(palliative_transition_bundle.get("missing_inputs") or []))
    palliative_stale_inputs = _dedupe(list(palliative_transition_bundle.get("stale_inputs") or []))
    palliative_trigger_status = str(palliative_transition_bundle.get("trigger_status") or "observe")
    palliative_domains = ["palliative_support", "goals_of_care", "symptom_control"]
    if palliative_required_fields and palliative_trigger_status in {"urgent_local_palliation", "redirect_supportive_only", "hospice_candidate"}:
        add_fields(
            palliative_missing_inputs or palliative_stale_inputs or palliative_required_fields,
            bucket="decision_blocking_inputs",
            why="El carril paliativo dominante exige cerrar carga sintomatica, objetivos de cuidado y alertas oncológicas urgentes antes de sostener la conducta visible.",
            domains=palliative_domains,
        )
        required_to_recalculate.extend(palliative_missing_inputs or palliative_stale_inputs or palliative_required_fields)
        decision_domains_blocked.extend(palliative_domains)
        why_these_fields_now.append(
            "La conducta visible actual depende de confirmar control sintomatico, elegibilidad hospice y objetivos de cuidado."
        )
    elif palliative_required_fields and palliative_trigger_status not in {"", "observe"}:
        add_fields(
            palliative_missing_inputs or palliative_stale_inputs or palliative_required_fields,
            bucket="supportive_gaps",
            why="El soporte paliativo concurrente requiere captura estructurada de sintomas, seguridad opioide y objetivos de cuidado.",
            domains=palliative_domains,
        )
        why_these_fields_now.append(
            "La integracion paliativa concurrente requiere bundle estructurado de sintomas, urgencias y soporte familiar."
        )
    if palliative_required_fields:
        family_missing_inputs["palliative_support_family"] = _dedupe(
            list(family_missing_inputs.get("palliative_support_family") or []) + palliative_missing_inputs
        )
        family_stale_inputs["palliative_support_family"] = _dedupe(
            list(family_stale_inputs.get("palliative_support_family") or []) + palliative_stale_inputs
        )
    palliative_capture_contract = {
        "palliative_required_fields": palliative_required_fields,
        "palliative_missing_inputs": palliative_missing_inputs,
        "palliative_stale_inputs": palliative_stale_inputs,
        "palliative_trigger_status": palliative_trigger_status,
        "care_mode": str(palliative_transition_bundle.get("care_mode") or "observe"),
        "palliative_capture_block": {
            "title": "Completar bundle paliativo activo",
            "summary": str(
                palliative_transition_bundle.get("trigger_status_label")
                or palliative_monitoring_package.get("monitoring_focus")
                or "Completar sintomas, seguridad opioide y urgencias oncologicas."
            ),
            "fields": palliative_missing_inputs or palliative_stale_inputs or palliative_required_fields,
            "capture_target": "followup",
            "focus": "palliative_support",
            "trigger_status": palliative_trigger_status,
            "care_mode": str(palliative_transition_bundle.get("care_mode") or "observe"),
            "recommended_cadence": str(palliative_monitoring_package.get("recommended_cadence") or ""),
        },
        "goals_of_care_capture_block": {
            "title": "Completar objetivos de cuidado",
            "summary": "Documenta voluntades anticipadas, representante y preferencia por confort cuando el carril paliativo ya influye la conducta.",
            "fields": [
                field
                for field in PALLIATIVE_GOALS_FIELDS
                if field in set(palliative_required_fields)
            ],
            "capture_target": "followup",
            "focus": "goals_of_care",
            "care_mode": str(palliative_transition_bundle.get("care_mode") or "observe"),
        },
    }

    survivorship_transition_bundle = build_survivorship_transition_bundle(
        patient,
        state=current_state,
        management_track=current_track,
        latest_assessment=latest_assessment,
        field_values=field_values,
    )
    survivorship_monitoring_package = build_survivorship_monitoring_package(
        patient,
        state=current_state,
        management_track=current_track,
        latest_assessment=latest_assessment,
        field_values=field_values,
        transition_bundle=survivorship_transition_bundle,
    )
    survivorship_required_fields = _dedupe(list(survivorship_transition_bundle.get("required_visit_fields") or []))
    survivorship_missing_inputs = _dedupe(list(survivorship_transition_bundle.get("missing_inputs") or []))
    survivorship_stale_inputs = _dedupe(list(survivorship_transition_bundle.get("stale_inputs") or []))
    survivorship_trigger_status = str(survivorship_transition_bundle.get("trigger_status") or "observe")
    survivorship_capture_fields = (
        survivorship_missing_inputs or survivorship_stale_inputs or survivorship_required_fields
    )
    survivorship_domains = ["survivorship", "late_effects", "toxicity_recovery"]
    if survivorship_required_fields and survivorship_trigger_status == "reenter_oncologic_decision":
        add_fields(
            survivorship_capture_fields,
            bucket="decision_blocking_inputs",
            why="La secuela dominante ya puede cambiar elegibilidad o conducta oncológica y debe cerrarse antes de sostener la recomendación visible.",
            domains=survivorship_domains,
        )
        required_to_recalculate.extend(survivorship_capture_fields)
        decision_domains_blocked.extend(survivorship_domains)
        why_these_fields_now.append(
            "La toxicidad o secuela tardía actual puede reabrir la decisión oncológica y exige captura estructurada."
        )
    elif survivorship_required_fields and survivorship_trigger_status not in {"", "observe"}:
        add_fields(
            survivorship_capture_fields,
            bucket="supportive_gaps",
            why="El carril de survivorship activo requiere cerrar secuelas tardías, recuperación funcional y prevención secundaria con captura estructurada.",
            domains=survivorship_domains,
        )
        why_these_fields_now.append(
            "Hoy la visita está dominada por toxicidad, secuelas tardías o rehabilitación, no solo por la vigilancia tumoral."
        )
    if survivorship_required_fields:
        family_missing_inputs["survivorship_followup_family"] = _dedupe(
            list(family_missing_inputs.get("survivorship_followup_family") or []) + survivorship_missing_inputs
        )
        family_stale_inputs["survivorship_followup_family"] = _dedupe(
            list(family_stale_inputs.get("survivorship_followup_family") or []) + survivorship_stale_inputs
        )
    survivorship_capture_contract = {
        "survivorship_required_fields": survivorship_required_fields,
        "survivorship_missing_inputs": survivorship_missing_inputs,
        "survivorship_stale_inputs": survivorship_stale_inputs,
        "survivorship_trigger_status": survivorship_trigger_status,
        "late_effect_domain_blocks": list(survivorship_transition_bundle.get("late_effect_domain_blocks") or []),
        "survivorship_capture_block": {
            "title": "Completar survivorship y toxicidad activa",
            "summary": str(
                survivorship_transition_bundle.get("trigger_status_label")
                or survivorship_monitoring_package.get("recommended_cadence")
                or "Completar secuelas tardías, recuperación funcional y prevención secundaria."
            ),
            "fields": survivorship_capture_fields,
            "capture_target": "followup",
            "focus": str(survivorship_transition_bundle.get("survivorship_track") or "survivorship_followup"),
            "recommended_cadence": str(survivorship_monitoring_package.get("recommended_cadence") or ""),
        },
    }

    if current_state in ADVANCED_PALLIATIVE_STATES or current_state in {
        "adt_progression_verification",
        "m0_crpc",
        "m1_crpc",
        "mcspc_oligo_metachronous",
        "mcspc_low_volume_sync_oligo",
        "mcspc_high_volume",
        "mcspc_high_volume_sync",
        "mcspc_high_volume_metachronous",
    }:
        pro_required_fields = ADVANCED_PRO_FIELDS
        pro_focus = "advanced_shared_decision"
        pro_minimum_fields = ["eq5d_vas", "bpi_worst_pain"]
    else:
        pro_required_fields = LOCALIZED_PRO_FIELDS
        pro_focus = "localized_shared_decision"
        pro_minimum_fields = ["eq5d_vas", "ipss_total"]
    pro_missing_inputs = [field for field in pro_required_fields if not _blocking_input_satisfied(field, field_values)]
    pro_capture_block = {
        "title": "Completar PROs decisionales",
        "summary": "Los PROs deben cuantificar calidad de vida, dolor y dominios funcionales antes de cerrar decisión compartida.",
        "fields": pro_missing_inputs or pro_required_fields,
        "capture_target": "followup",
        "focus": pro_focus,
    }

    recommendation_block_status = "clear"
    recommendation_block_reason = "La recomendación tiene los datos mínimos para sostener una conducta visible."
    allowed_actions_while_blocked = ["recomendacion_final", "shared_decision", "planificacion"]
    if missing_hard:
        recommendation_block_status = "hard_stop"
        recommendation_block_reason = (
            "Faltan datos críticos que cambian la conducta clínica: "
            + ", ".join(missing_hard[:6])
        )
        allowed_actions_while_blocked = ["captura_critica", "recoleccion_documental", "revaluacion"]
    elif missing_decision:
        recommendation_block_status = "provisional"
        recommendation_block_reason = (
            "La recomendación sigue abierta hasta cerrar datos decisionales: "
            + ", ".join(missing_decision[:6])
        )
        allowed_actions_while_blocked = ["captura_dirigida", "discusion_compartida_provisional", "monitorizacion_temporal"]
    elif next_best_action and any(field in pro_missing_inputs for field in pro_minimum_fields):
        recommendation_block_status = "provisional"
        recommendation_block_reason = (
            "Faltan PROs mínimos para modular intensidad terapéutica y decisión compartida: "
            + ", ".join(field for field in pro_minimum_fields if field in pro_missing_inputs)
        )
        allowed_actions_while_blocked = ["captura_dirigida", "discusion_compartida_provisional", "monitorizacion_temporal"]

    return {
        "available": bool(hard_blocking_inputs or decision_blocking_inputs or optional_context_inputs or supportive_gaps or palliative_required_fields or survivorship_required_fields),
        "effective_state": current_state,
        "effective_management_track": current_track,
        "blocking_inputs": missing_blocking,
        "hard_blocking_inputs": missing_hard,
        "decision_blocking_inputs": missing_decision,
        "supportive_gaps": missing_supportive,
        "required_to_recalculate": _dedupe(required_to_recalculate + missing_blocking),
        "optional_context_inputs": _dedupe(optional_context_inputs),
        "decision_domains_blocked": _dedupe(decision_domains_blocked),
        "why_these_fields_now": [item for item in _dedupe(why_these_fields_now) if item],
        "ready_inputs": present_blocking,
        "docetaxel_verification_status": str(docetaxel_bundle.get("docetaxel_verification_status") or ""),
        "docetaxel_required_now": bool(docetaxel_bundle.get("docetaxel_required_now")),
        "docetaxel_missing_inputs": _dedupe(list(docetaxel_bundle.get("docetaxel_missing_inputs") or [])),
        "docetaxel_stale_inputs": _dedupe(list(docetaxel_bundle.get("docetaxel_stale_inputs") or [])),
        "docetaxel_lab_snapshot": dict(docetaxel_bundle.get("docetaxel_lab_snapshot") or {}),
        "candidate_regimens_under_consideration": _dedupe(candidate_regimens_under_consideration),
        "candidate_families_under_consideration": _dedupe(
            [
                regimen_family_code(item, fallback="observation_family")
                for item in candidate_regimens_under_consideration
            ]
        ),
        "regimen_specific_blocks": regimen_specific_blocks,
        "selection_safety_profile": selection_safety_profile,
        "arpi_required_fields": list(arpi_capture_contract.get("arpi_required_fields") or []),
        "arpi_missing_inputs": list(arpi_capture_contract.get("arpi_missing_inputs") or []),
        "arpi_stale_inputs": list(arpi_capture_contract.get("arpi_stale_inputs") or []),
        "arpi_profile_completeness": str(arpi_capture_contract.get("arpi_profile_completeness") or "not_applicable"),
        "arpi_preference_readiness": str(arpi_capture_contract.get("arpi_preference_readiness") or "not_applicable"),
        "post_rt_required_fields": list(post_rt_capture_contract.get("post_rt_required_fields") or []),
        "post_rt_missing_inputs": list(post_rt_capture_contract.get("post_rt_missing_inputs") or []),
        "palliative_required_fields": list(palliative_capture_contract.get("palliative_required_fields") or []),
        "palliative_missing_inputs": list(palliative_capture_contract.get("palliative_missing_inputs") or []),
        "palliative_stale_inputs": list(palliative_capture_contract.get("palliative_stale_inputs") or []),
        "palliative_capture_block": dict(palliative_capture_contract.get("palliative_capture_block") or {}),
        "goals_of_care_capture_block": dict(palliative_capture_contract.get("goals_of_care_capture_block") or {}),
        "survivorship_required_fields": list(survivorship_capture_contract.get("survivorship_required_fields") or []),
        "survivorship_missing_inputs": list(survivorship_capture_contract.get("survivorship_missing_inputs") or []),
        "survivorship_capture_block": dict(survivorship_capture_contract.get("survivorship_capture_block") or {}),
        "late_effect_domain_blocks": list(survivorship_capture_contract.get("late_effect_domain_blocks") or []),
        "pro_required_fields": pro_required_fields,
        "pro_missing_inputs": pro_missing_inputs,
        "pro_capture_block": pro_capture_block,
        "post_rt_confirmation_block": dict(post_rt_capture_contract.get("post_rt_confirmation_block") or {}),
        "post_rt_local_salvage_block": dict(post_rt_capture_contract.get("post_rt_local_salvage_block") or {}),
        "family_missing_inputs": family_missing_inputs,
        "family_stale_inputs": family_stale_inputs,
        "recommendation_block_status": recommendation_block_status,
        "recommendation_block_reason": recommendation_block_reason,
        "allowed_actions_while_blocked": allowed_actions_while_blocked,
        "monitoring_required_fields": monitoring_required_fields,
        "monitoring_capture_block": {
            "title": monitoring_capture_title,
            "summary": monitoring_capture_summary,
            "fields": monitoring_required_fields,
            "capture_target": "followup",
            "focus": str(active_monitoring_package.get("monitoring_focus") or ""),
            "family_code": active_family_code,
            "active_regimen_code": active_regimen_code,
            "recommended_cadence": str(active_monitoring_package.get("recommended_cadence") or ""),
            "trigger_status": trigger_status,
        },
        "headline": headline,
        "blocking_input_descriptors": filtered_descriptors,
        "capture_block": {
            "title": "Completar datos críticos para recalcular la conducta",
            "summary": (
                "La decisión actual necesita datos complementarios antes de cerrar la recomendación."
                if missing_blocking
                else "La decisión ya tiene inputs mínimos, pero aún puede refinarse con contexto adicional."
            ),
            "fields": missing_blocking or missing_supportive or _dedupe(required_to_recalculate),
            "capture_target": capture_target,
            "focus": focus,
        },
    }


def merge_staging_adjudication_into_requirements(
    decision_input_requirements: dict[str, Any] | None,
    staging_adjudication_bundle: dict[str, Any] | None,
) -> dict[str, Any]:
    merged = dict(decision_input_requirements or {})
    staging_adjudication_bundle = dict(staging_adjudication_bundle or {})
    if not staging_adjudication_bundle:
        return merged

    missing_critical_inputs = _dedupe(
        list(staging_adjudication_bundle.get("missing_critical_inputs") or [])
        + list(staging_adjudication_bundle.get("discordant_fields") or [])
        + list(staging_adjudication_bundle.get("superseded_evidence") or [])
    )
    if not missing_critical_inputs:
        merged["staging_adjudication_bundle"] = staging_adjudication_bundle
        return merged

    hard_inputs = _dedupe(list(merged.get("hard_blocking_inputs") or []) + missing_critical_inputs)
    decision_inputs = _dedupe(list(merged.get("decision_blocking_inputs") or []))
    blocking_inputs = _dedupe(list(merged.get("blocking_inputs") or []) + hard_inputs + decision_inputs)
    required_to_recalculate = _dedupe(
        list(merged.get("required_to_recalculate") or [])
        + hard_inputs
        + decision_inputs
    )
    domains = _dedupe(
        list(merged.get("decision_domains_blocked") or [])
        + ["staging_adjudication", "restaging_traceability"]
    )
    reasons = _dedupe(
        list(merged.get("why_these_fields_now") or [])
        + list(staging_adjudication_bundle.get("recommended_adjudication_actions") or [])
        + [
            "La decisión no debe liberarse hasta cerrar concordancia anatómica/funcional, trazabilidad PSMA o biomarcadores críticos."
        ]
    )

    merged.update(
        {
            "hard_blocking_inputs": hard_inputs,
            "decision_blocking_inputs": decision_inputs,
            "blocking_inputs": blocking_inputs,
            "required_to_recalculate": required_to_recalculate,
            "decision_domains_blocked": domains,
            "why_these_fields_now": reasons,
            "staging_adjudication_bundle": staging_adjudication_bundle,
        }
    )
    return merged


def detect_ui_contradiction_flags(
    patient: dict[str, Any],
    *,
    effective_state: str = "",
    effective_management_track: str = "",
    decision_trace: dict[str, Any] | None = None,
    schedule_bundle: dict[str, Any] | None = None,
    transition_resolution: dict[str, Any] | None = None,
    care_intent_contract: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    effective_state = effective_state or patient.get("schedule_state") or ""
    effective_management_track = effective_management_track or patient.get("schedule_management_track") or ""
    decision_trace = dict(decision_trace or {})
    schedule_bundle = dict(schedule_bundle or {})
    transition_resolution = dict(transition_resolution or {})
    care_intent_contract = dict(care_intent_contract or {})
    latest_assessment = dict(patient.get("latest_assessment") or {})
    field_values = _field_values(patient)

    if (
        latest_assessment.get("state")
        and effective_state
        and latest_assessment.get("state") != effective_state
        and str(decision_trace.get("visibility_status") or "") in {"actionable", "contextual"}
        and transition_resolution.get("policy") != "auto_applied"
        and not str(decision_trace.get("headline") or "").lower().startswith("confirmar transición a")
    ):
        flags.append(
            {
                "key": "assessment_vs_effective_state",
                "severity": "warning",
                "title": "El assessment basal ya no coincide con el estado efectivo",
                "details": f"Assessment={latest_assessment.get('state')} vs efectivo={effective_state}.",
            }
        )

    schedule_state = str(schedule_bundle.get("schedule_state") or patient.get("schedule_state") or "")
    schedule_track = str(schedule_bundle.get("schedule_management_track") or patient.get("schedule_management_track") or "")
    override_reason = str(schedule_bundle.get("schedule_override_reason") or patient.get("schedule_override_reason") or "")
    if schedule_state and effective_state and schedule_state != effective_state and not override_reason:
        flags.append(
            {
                "key": "effective_state_vs_schedule_state",
                "severity": "critical",
                "title": "La agenda muestra un estado distinto sin motivo de override",
                "details": f"Efectivo={effective_state} vs agenda={schedule_state}.",
            }
        )
    if schedule_track and effective_management_track and schedule_track != effective_management_track and not override_reason:
        flags.append(
            {
                "key": "effective_track_vs_schedule_track",
                "severity": "critical",
                "title": "El track de agenda no coincide con el track efectivo",
                "details": f"Efectivo={effective_management_track} vs agenda={schedule_track}.",
            }
        )

    headline = str(decision_trace.get("headline") or "").lower()
    castrate_status = str(field_values.get("castrate_testosterone_status") or "").strip()
    if "castración inadecuada" in headline and castrate_status == "confirmed_castrate":
        flags.append(
            {
                "key": "stale_castration_failure_narrative",
                "severity": "critical",
                "title": "Narrativa stale de castración inadecuada",
                "details": "La narrativa principal aún sugiere falla de castración aunque la testosterona longitudinal ya está en rango de castración.",
            }
        )

    if care_intent_contract and schedule_bundle:
        consistency = schedule_bundle.get("action_schedule_consistency")
        if consistency is False:
            flags.append(
                {
                    "key": "care_intent_vs_schedule",
                    "severity": "critical",
                    "title": "La agenda no sigue la intención clínica compartida",
                    "details": f"Intención={care_intent_contract.get('intent_key')} pero schedule_primary_intent={schedule_bundle.get('schedule_primary_intent')}.",
                }
            )

    return flags


__all__ = [
    "build_decision_input_requirements",
    "merge_staging_adjudication_into_requirements",
    "detect_ui_contradiction_flags",
]
