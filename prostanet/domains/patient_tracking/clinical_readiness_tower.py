"""Clinical Readiness & Safety Tower.

Deterministic patient-level read model that answers whether the next clinical
decision is ready, blocked by missing data, overdue, actively unsafe, or not
applicable. It orchestrates existing longitudinal truth, router fields,
therapeutic/supportive readiness, gates, trials and vertical copilots without
inventing treatment lines, PSA, testosterone or trial eligibility.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import re
from typing import Any, Iterable, Mapping


READINESS_STATUS_VALUES = (
    "ready",
    "requires_data",
    "overdue",
    "active_risk",
    "not_applicable",
)

READINESS_LANE_ORDER = (
    "diagnostic_biopsy_readiness",
    "active_surveillance_readiness",
    "localized_treatment_readiness",
    "patient_twin_readiness",
    "bcr_salvage_readiness",
    "mhspc_precision_readiness",
    "crpc_confirmation_readiness",
    "m0crpc_arpi_readiness",
    "m1crpc_sequence_readiness",
    "parp_hrr_readiness",
    "psma_rlt_readiness",
    "adt_arpi_safety_readiness",
    "supportive_palliative_readiness",
)

EVIDENCE_ANCHORS = (
    {
        "label": "EAU Prostate Cancer Follow-up",
        "url": "https://uroweb.org/guidelines/prostate-cancer/chapter/followup",
    },
    {
        "label": "FDA enzalutamide BCR high-risk",
        "url": "https://www.fda.gov/drugs/resources-information-approved-drugs/fda-approves-enzalutamide-non-metastatic-castration-sensitive-prostate-cancer-biochemical-recurrence",
    },
    {
        "label": "FDA niraparib + abiraterone BRCA2 mCSPC",
        "url": "https://www.fda.gov/drugs/resources-information-approved-drugs/fda-approves-niraparib-and-abiraterone-acetate-plus-prednisone-brca2-mutated-metastatic-castration",
    },
    {
        "label": "FDA oncology approvals",
        "url": "https://www.fda.gov/drugs/resources-information-approved-drugs/oncology-cancer-hematologic-malignancies-approval-notifications",
    },
)

LANE_LABELS = {
    "diagnostic_biopsy_readiness": "Diagnostico y biopsia",
    "active_surveillance_readiness": "Vigilancia activa",
    "localized_treatment_readiness": "Tratamiento localizado",
    "patient_twin_readiness": "Patient Twin: preferencias y PROs",
    "bcr_salvage_readiness": "BCR y rescate",
    "mhspc_precision_readiness": "mHSPC precision",
    "crpc_confirmation_readiness": "Confirmacion CRPC",
    "m0crpc_arpi_readiness": "m0CRPC y ARPI",
    "m1crpc_sequence_readiness": "m1CRPC secuencia",
    "parp_hrr_readiness": "PARP / HRR",
    "psma_rlt_readiness": "PSMA RLT",
    "adt_arpi_safety_readiness": "Seguridad ADT / ARPI",
    "supportive_palliative_readiness": "Soporte y paliacion",
}

LANE_PHASES = {
    "diagnostic_biopsy_readiness": "initial_wizard",
    "active_surveillance_readiness": "longitudinal_followup",
    "localized_treatment_readiness": "initial_wizard",
    "patient_twin_readiness": "longitudinal_followup",
    "bcr_salvage_readiness": "initial_wizard",
    "mhspc_precision_readiness": "initial_wizard",
    "crpc_confirmation_readiness": "initial_wizard",
    "m0crpc_arpi_readiness": "longitudinal_followup",
    "m1crpc_sequence_readiness": "initial_wizard",
    "parp_hrr_readiness": "longitudinal_followup",
    "psma_rlt_readiness": "longitudinal_followup",
    "adt_arpi_safety_readiness": "longitudinal_followup",
    "supportive_palliative_readiness": "longitudinal_followup",
}

LANE_REQUIRED_FIELDS = {
    "diagnostic_biopsy_readiness": (
        "psa_value",
        "psa_density",
        "mri_pirads_score",
        "dre_suspicious",
        "biopsy_status",
        "family_history",
        "germline_risk",
    ),
    "active_surveillance_readiness": (
        "confirmatory_biopsy_status",
        "serial_mri_status",
        "psa_value",
        "positive_cores_count",
        "isup_grade_group",
        "cribriform_intrductal_status",
    ),
    "localized_treatment_readiness": (
        "risk_group",
        "life_expectancy_years",
        "urinary_function_baseline",
        "sexual_function_baseline",
        "bowel_function_baseline",
        "rp_rt_as_tradeoff_documented",
        "localized_patient_values",
    ),
    "patient_twin_readiness": (
        "patient_values",
        "baseline_pro",
        "toxicity_tolerance",
        "decision_tradeoff",
        "redecision_threshold",
    ),
    "bcr_salvage_readiness": (
        "post_local_context",
        "psa_value",
        "psa_doubling_time_months",
        "salvage_context_marker",
    ),
    "mhspc_precision_readiness": (
        "m1_composition",
        "chaarted_volume_classification",
        "latitude_high_risk_criteria_count",
        "metastatic_timing",
        "ecog_score",
    ),
    "crpc_confirmation_readiness": (
        "current_adt_context",
        "testosterone_value",
        "progression_pattern",
        "conventional_imaging_status",
        "m0_m1_reconciled",
    ),
    "m0crpc_arpi_readiness": (
        "psa_doubling_time_months",
        "conventional_imaging_status",
        "testosterone_value",
        "arpi_safety_baseline",
    ),
    "m1crpc_sequence_readiness": (
        "real_treatment_line",
        "progression_pattern",
        "ecog_score",
        "taxane_exposure",
        "arpi_exposure",
        "testosterone_value",
    ),
    "parp_hrr_readiness": (
        "hrr_brca_status",
        "molecular_report_source",
        "molecular_report_date",
        "line_context",
        "hemoglobin",
        "renal_function",
    ),
    "psma_rlt_readiness": (
        "psma_pet_status",
        "psma_negative_dominant_lesions",
        "bone_marrow_reserve",
        "renal_function",
        "hepatic_function",
        "line_context",
    ),
    "adt_arpi_safety_readiness": (
        "testosterone_value",
        "glucose_or_hba1c",
        "lipids",
        "blood_pressure",
        "bone_health",
        "falls_cognition",
    ),
    "supportive_palliative_readiness": (
        "pain_score",
        "ecog_score",
        "weight_cachexia_status",
        "sre_spinal_cord_risk",
        "goals_of_care_status",
    ),
}

LANE_OPTIONAL_FIELDS = {
    "diagnostic_biopsy_readiness": ("phi_value", "fourkscore_value", "repeat_psa_value"),
    "active_surveillance_readiness": ("exit_trigger_status", "psa_kinetics", "mri_progression_status"),
    "localized_treatment_readiness": ("comorbidity_index", "patient_preferences", "frailty_status"),
    "patient_twin_readiness": (
        "urinary_function_baseline",
        "sexual_function_baseline",
        "bowel_function_baseline",
        "goals_of_care_status",
    ),
    "bcr_salvage_readiness": ("surgical_margins_status", "pathological_t_stage", "decipher_score", "psma_pet_status"),
    "mhspc_precision_readiness": ("fit_for_docetaxel", "fit_for_arpi", "organ_function", "bone_health"),
    "crpc_confirmation_readiness": ("psa_value", "radiographic_progression_status", "symptomatic_progression_status"),
    "m0crpc_arpi_readiness": ("drug_interaction_review", "qt_or_cardiac_baseline", "dexa_status"),
    "m1crpc_sequence_readiness": ("hrr_brca_status", "psma_pet_status", "bone_marrow_reserve", "renal_function", "hepatic_function"),
    "parp_hrr_readiness": ("platelets", "neutrophils", "prior_platinum_exposure"),
    "psma_rlt_readiness": ("prior_taxane_exposure", "prior_arpi_exposure", "fdg_discordance_status"),
    "adt_arpi_safety_readiness": ("ecg_qtc", "echo_lvef", "calcium_vitamin_d", "drug_interaction_review"),
    "supportive_palliative_readiness": ("bpi_score", "esas_score", "advance_directive_status", "concurrent_palliative_care"),
}

FIELD_ALIASES = {
    "psa_value": ("psa_value", "psa", "psa_current", "baseline_psa", "psa_baseline", "psa_baseline_ng_ml", "bcr_psa"),
    "psa_density": ("psa_density", "psad", "psa_density_ng_ml2", "psa_density_ng_ml_cc"),
    "mri_pirads_score": (
        "mri_pirads_score",
        "pirads_score",
        "pirads",
        "mri_pi_rads",
        "mri_pirads",
        "prior_mpmri_pirads_score",
        "pirads_v21_score",
    ),
    "dre_suspicious": ("dre_suspicious", "dre_abnormal", "digital_rectal_exam_suspicious", "dre_finding"),
    "biopsy_status": (
        "biopsy_status",
        "planned_biopsy_type",
        "planned_biopsy_route",
        "biopsy_date",
        "biopsy_result",
        "primary_biopsy_completed_or_planned",
        "primary_biopsy_not_performed",
        "prior_negative_biopsy",
        "prior_negative_biopsy_documented",
        "targeted_biopsy_status",
        "prior_mpmri_targeted_biopsy_status",
    ),
    "family_history": (
        "family_history",
        "family_history_positive",
        "family_history_pca_under_55",
        "family_history_brca_breast_ovarian",
        "germline_family_history",
    ),
    "germline_risk": (
        "germline_risk",
        "germline_risk_mutation",
        "germline_test_indicated",
        "germline_family_history",
        "brca_family_history",
        "lynch_germline_test_indicated",
        "germline_test_refused_reason",
    ),
    "confirmatory_biopsy_status": ("confirmatory_biopsy_status", "confirmatory_biopsy_done", "confirmatory_biopsy_date"),
    "serial_mri_status": ("serial_mri_status", "mri_followup_status", "mri_progression_status"),
    "positive_cores_count": ("positive_cores_count", "cores_positive", "biopsy_positive_cores"),
    "isup_grade_group": ("isup_grade_group", "isup_grade", "grade_group", "gleason_grade_group"),
    "cribriform_intrductal_status": (
        "cribriform_intrductal_status",
        "cribriform_intraductal_status",
        "cribriform_pattern_present",
        "intraductal_carcinoma_present",
    ),
    "risk_group": ("risk_group", "clinical_risk_group", "nccn_risk_group", "eau_risk_group"),
    "life_expectancy_years": ("life_expectancy_years", "life_expectancy_months"),
    "urinary_function_baseline": ("urinary_function_baseline", "ipss_score", "baseline_ipss"),
    "sexual_function_baseline": ("sexual_function_baseline", "iief5_score", "baseline_iief5"),
    "bowel_function_baseline": ("bowel_function_baseline", "baseline_bowel_function", "bowel_symptom_score"),
    "rp_rt_as_tradeoff_documented": ("rp_rt_as_tradeoff_documented", "shared_decision_local_options", "decision_rp_vs_rt_active"),
    "patient_values": (
        "patient_values",
        "patient_value_profile",
        "patient_priority_profile",
        "patient_preferences",
        "patient_preference",
        "goal_of_care",
        "goals_of_care_status",
        "values",
    ),
    "localized_patient_values": (
        "localized_patient_values",
        "patient_values",
        "patient_value_profile",
        "patient_priority_profile",
        "patient_preferences",
        "patient_preference",
        "goal_of_care",
        "goals_of_care_status",
        "values",
    ),
    "baseline_pro": (
        "baseline_pro",
        "baseline_pro_documented",
        "epic26_baseline",
        "epic26_total",
        "epic26_urinary_domain",
        "epic26_sexual_domain",
        "epic26_bowel_domain",
        "esas_score",
        "pain_score",
        "urinary_function_baseline",
        "sexual_function_baseline",
        "bowel_function_baseline",
    ),
    "toxicity_tolerance": (
        "toxicity_tolerance",
        "toxicity_tolerance_profile",
        "safety_priorities",
        "ctcae_or_pro_ctcae",
        "pro_ctcae_baseline",
        "unacceptable_toxicity_threshold",
    ),
    "decision_tradeoff": (
        "decision_tradeoff",
        "decision_tradeoff_documented",
        "rp_rt_as_tradeoff_documented",
        "shared_decision_local_options",
        "patient_preferences_vs_recommendation",
    ),
    "redecision_threshold": (
        "redecision_threshold",
        "new_decision_threshold",
        "progression_threshold",
        "unacceptable_toxicity_threshold",
        "patient_redecision_trigger",
    ),
    "post_local_context": (
        "post_local_context",
        "prior_prostatectomy",
        "prior_radiation",
        "prior_radical_prostatectomy_documented",
        "prior_radiation_therapy_documented",
        "primary_treatment",
        "prior_local_therapy",
        "definitive_local_therapy",
        "local_therapy_context",
    ),
    "psa_doubling_time_months": (
        "psa_doubling_time_months",
        "psadt",
        "psadt_months",
        "psa_doubling_time",
        "psa_dt",
        "tdpa",
        "psadt_at_bcr",
    ),
    "salvage_context_marker": (
        "salvage_context_marker",
        "bcr_detected",
        "bcr_confirmed",
        "bcr_date",
        "bcr_psa",
        "phoenix_criteria_met",
        "phoenix_failure_confirmed",
        "phoenix_delta",
        "psa_nadir_post_rt",
        "psa_rise_above_nadir_ng_ml",
        "psa_current",
        "psa_nadir",
    ),
    "m1_composition": (
        "m1_composition",
        "metastasis_site",
        "clinical_m_stage",
        "bone_lesion_count_total",
        "bone_appendicular_count",
        "visceral_metastasis_present",
        "nonregional_nodal_count",
    ),
    "chaarted_volume_classification": ("chaarted_volume_classification", "volume_disease", "volume_classification"),
    "latitude_high_risk_criteria_count": ("latitude_high_risk_criteria_count", "latitude_risk_count"),
    "metastatic_timing": ("metastatic_timing", "metachronous_metastasis", "synchronous_metastasis"),
    "ecog_score": ("ecog_score", "ecog", "ecog_current", "performance_status_ecog"),
    "current_adt_context": ("current_adt_context", "adt_status", "current_adt_status", "adt_active", "current_adt"),
    "testosterone_value": (
        "testosterone_value",
        "testosterone_current",
        "testosterone",
        "testosterone_baseline",
        "latest_testosterone_value",
    ),
    "progression_pattern": (
        "progression_pattern",
        "systemic_progression_context",
        "progression_context",
        "psa_progression",
        "radiographic_progression",
        "clinical_progression",
    ),
    "conventional_imaging_status": ("conventional_imaging_status", "imaging_status", "conventional_imaging_m_stage"),
    "m0_m1_reconciled": ("m0_m1_reconciled", "metastatic_stage_resolved", "m_substage_resolved", "metastasis_site"),
    "arpi_safety_baseline": ("arpi_safety_baseline", "arpi_toxicity_review", "arpi_blood_pressure_monitoring"),
    "real_treatment_line": ("real_treatment_line", "line_of_therapy_number", "line_of_therapy", "current_treatment", "drug_scheme"),
    "taxane_exposure": ("taxane_exposure", "prior_docetaxel_exposure", "prior_taxane_exposure", "docetaxel_prior"),
    "arpi_exposure": ("arpi_exposure", "prior_arpi_exposure", "prior_arsi_exposure", "abiraterone_prior"),
    "hrr_brca_status": ("hrr_brca_status", "hrr_status", "hrr_overall", "brca1_status", "brca2_status", "atm_status"),
    "molecular_report_source": ("molecular_report_source", "test_type", "genomic_test_type", "molecular_assay_source"),
    "molecular_report_date": ("molecular_report_date", "test_date", "genomic_test_date", "molecular_assay_date"),
    "line_context": ("line_context", "line_of_therapy_number", "line_of_therapy", "real_treatment_line"),
    "hemoglobin": ("hemoglobin", "hb", "hgb", "hemoglobin_g_dl"),
    "renal_function": ("renal_function", "egfr", "egfr_ml_min", "creatinine_clearance", "creatinine"),
    "psma_pet_status": (
        "psma_pet_status",
        "psma_pet_positive_current",
        "psma_result",
        "psma_pet_done",
        "psma_pet_staging_recent",
        "psma_pet_for_salvage",
    ),
    "psma_negative_dominant_lesions": (
        "psma_negative_dominant_lesions",
        "fdg_discordance_status",
        "psma_negative_lesion_dominant",
    ),
    "bone_marrow_reserve": ("bone_marrow_reserve", "platelets", "anc", "hemoglobin"),
    "hepatic_function": ("hepatic_function", "ast", "alt", "bilirubin", "liver_function_status"),
    "glucose_or_hba1c": ("glucose_or_hba1c", "glucose", "fasting_glucose", "hba1c"),
    "lipids": ("lipids", "ldl", "hdl", "triglycerides", "total_cholesterol"),
    "blood_pressure": ("blood_pressure", "systolic_blood_pressure", "diastolic_blood_pressure", "bp_systolic", "bp_diastolic"),
    "bone_health": ("bone_health", "dexa_status", "dexa_due", "vitamin_d_level", "calcium_level"),
    "falls_cognition": ("falls_cognition", "fall_risk_score_high", "cognitive_concerns_documented", "moca_current"),
    "pain_score": ("pain_score", "pain", "bpi_worst_pain", "pain_nrs"),
    "weight_cachexia_status": ("weight_cachexia_status", "weight_loss_percent", "cachexia_status", "weight_kg"),
    "sre_spinal_cord_risk": ("sre_spinal_cord_risk", "spinal_cord_compression_risk", "sre_risk", "pathologic_fracture_risk"),
    "goals_of_care_status": ("goals_of_care_status", "goals_of_care_discussed", "advance_care_planning_status"),
}

FIELD_LABELS = {
    "psa_value": "PSA/APE real",
    "psa_density": "Densidad de PSA",
    "mri_pirads_score": "MRI / PI-RADS",
    "dre_suspicious": "Tacto rectal",
    "biopsy_status": "Biopsia",
    "family_history": "Antecedente familiar",
    "germline_risk": "Riesgo germinal",
    "repeat_psa_value": "PSA repetido",
    "confirmatory_biopsy_status": "Biopsia confirmatoria",
    "serial_mri_status": "MRI seriada",
    "positive_cores_count": "Cilindros positivos",
    "isup_grade_group": "ISUP",
    "cribriform_intrductal_status": "Cribriforme/intraductal",
    "risk_group": "Riesgo NCCN/EAU",
    "life_expectancy_years": "Vida esperada",
    "urinary_function_baseline": "Funcion urinaria basal",
    "sexual_function_baseline": "Funcion sexual basal",
    "bowel_function_baseline": "Funcion intestinal basal",
    "rp_rt_as_tradeoff_documented": "Tradeoffs RP/RT/AS",
    "patient_values": "Valores y prioridades del paciente",
    "localized_patient_values": "Valores para decidir AS/RP/RT",
    "baseline_pro": "PRO basal minimo",
    "toxicity_tolerance": "Tolerancia/toxicidad aceptable",
    "decision_tradeoff": "Tradeoff de decision documentado",
    "redecision_threshold": "Umbral de nueva decision",
    "post_local_context": "Contexto post-local",
    "psa_doubling_time_months": "PSADT",
    "salvage_context_marker": "Criterio BCR/Phoenix",
    "m1_composition": "Composicion M1",
    "chaarted_volume_classification": "Volumen CHAARTED",
    "latitude_high_risk_criteria_count": "Riesgo LATITUDE",
    "metastatic_timing": "Sincrono/metacronico",
    "ecog_score": "ECOG",
    "current_adt_context": "ADT actual",
    "testosterone_value": "Testosterona",
    "progression_pattern": "Patron de progresion",
    "conventional_imaging_status": "Imagen convencional",
    "m0_m1_reconciled": "M0/M1 reconciliado",
    "arpi_safety_baseline": "Seguridad ARPI basal",
    "real_treatment_line": "Linea terapeutica real",
    "taxane_exposure": "Exposicion a taxano",
    "arpi_exposure": "Exposicion ARPI/ARSI",
    "hrr_brca_status": "HRR/BRCA",
    "molecular_report_source": "Fuente molecular",
    "molecular_report_date": "Fecha reporte molecular",
    "line_context": "Contexto de linea",
    "hemoglobin": "Hemoglobina",
    "renal_function": "Funcion renal",
    "psma_pet_status": "PSMA PET",
    "psma_negative_dominant_lesions": "Lesiones dominantes PSMA-negativas",
    "bone_marrow_reserve": "Reserva medular",
    "hepatic_function": "Funcion hepatica",
    "glucose_or_hba1c": "Glucosa/HbA1c",
    "lipids": "Lipidos",
    "blood_pressure": "Presion arterial",
    "bone_health": "DEXA / vitamina D / calcio",
    "falls_cognition": "Caidas/cognicion",
    "pain_score": "Dolor/BPI",
    "weight_cachexia_status": "Peso/cachexia",
    "sre_spinal_cord_risk": "SRE/compresion medular",
    "goals_of_care_status": "Objetivos de cuidado",
}

EMPTY_VALUES = {
    "",
    "none",
    "null",
    "unknown",
    "desconocido",
    "not_tested",
    "not tested",
    "pending",
    "pendiente",
    "no_documentado",
    "no documentado",
    "sin dato",
    "sin datos",
    "na",
    "n/a",
    "—",
    "-",
}

PLACEHOLDER_TREATMENT_VALUES = {
    "",
    "0",
    "none",
    "null",
    "unknown",
    "desconocido",
    "no documentado",
    "sin linea terapeutica documentada",
    "sin línea terapéutica documentada",
    "no treatment",
    "sin tratamiento",
    "—",
    "-",
}

ARPI_TOKENS = ("abiraterone", "enzalutamide", "apalutamide", "darolutamide", "arpi", "arsi")
ADT_TOKENS = ("adt", "leuprolide", "goserelin", "triptorelin", "degarelix", "relugolix", "orquiectomia", "orchiectomy")
PARP_TOKENS = ("parp", "olaparib", "rucaparib", "niraparib", "talazoparib")
PSMA_RLT_TOKENS = ("psma_rlt", "lutetium", "lu-177", "lu177", "pluvicto", "radioligand")


def fields_for_readiness_lane(lane_key: str | None) -> set[str]:
    """Return canonical and alias fields relevant to a readiness lane."""
    key = _normalize_readiness_lane_key(lane_key)
    if key not in READINESS_LANE_ORDER:
        return set()
    fields = set(LANE_REQUIRED_FIELDS.get(key, ())) | set(LANE_OPTIONAL_FIELDS.get(key, ()))
    expanded = set(fields)
    for field in fields:
        expanded.update(FIELD_ALIASES.get(field, (field,)))
    return expanded


def build_clinical_readiness_tower(
    patient_record: Mapping[str, Any] | None,
    *,
    longitudinal_bundle: Mapping[str, Any] | None = None,
    state: str = "",
    management_track: str = "",
    patient_ref: str = "",
) -> dict[str, Any]:
    """Build the official clinical readiness tower bundle."""
    patient = dict(patient_record or {})
    bundle = dict(longitudinal_bundle or {})
    values = _extract_patient_values(patient, bundle)
    effective_state = _effective_state(values, bundle, state)
    effective_track = _first_text(
        management_track,
        values.get("management_track"),
        values.get("current_track"),
        (bundle.get("signals") or {}).get("effective_management_track_final"),
        (bundle.get("signals") or {}).get("effective_management_track"),
        (bundle.get("signals") or {}).get("reconciled_management_track"),
    )
    patient_identifier = _first_text(
        patient_ref,
        (patient.get("identity") or {}).get("nss"),
        patient.get("nss"),
        patient.get("patient_ref"),
    )
    treatment_lines = _real_treatment_lines(patient)
    values["real_treatment_line_count"] = len(treatment_lines)
    if treatment_lines:
        values["real_treatment_line"] = treatment_lines[-1].get("label") or treatment_lines[-1].get("drug_scheme")
        values.setdefault("line_context", treatment_lines[-1].get("line_of_therapy"))

    context = {
        "state": effective_state,
        "management_track": effective_track,
        "patient_ref": patient_identifier,
        "values": values,
        "bundle": bundle,
        "patient": patient,
        "real_treatment_lines": treatment_lines,
        "candidate_family": _candidate_family(bundle, values),
    }

    lanes = [_build_lane(lane_key, context) for lane_key in READINESS_LANE_ORDER]
    status_counts: dict[str, int] = {status: 0 for status in READINESS_STATUS_VALUES}
    for lane in lanes:
        status_counts[lane["status"]] = status_counts.get(lane["status"], 0) + 1
    priority_lane = _priority_lane(lanes)
    capture_plan = _build_capture_plan(lanes, effective_state, patient_identifier)
    gate_summary = summarize_readiness_gate_contracts()
    trial_summary = _trial_contract_summary()
    dominant_blocker = _dominant_blocker(lanes)

    return {
        "available": True,
        "source": "clinical_readiness_tower",
        "version": "clinical_readiness_tower_v1",
        "patient_ref": patient_identifier,
        "state": effective_state,
        "management_track": effective_track,
        "summary": {
            "lane_count": len(lanes),
            "active_lane_count": sum(1 for lane in lanes if lane["status"] != "not_applicable"),
            "status_counts": status_counts,
            "priority_lane_key": priority_lane.get("key", ""),
            "priority_lane_label": priority_lane.get("label", ""),
            "dominant_blocker": dominant_blocker,
            "has_real_treatment_line": bool(treatment_lines),
            "real_treatment_line_count": len(treatment_lines),
            "real_treatment_lines": treatment_lines,
            "gate_contract_total": gate_summary.get("total_gates", 0),
            "gate_contract_covered": gate_summary.get("covered_gates", 0),
            "trial_contract_total": trial_summary.get("total_trials", 0),
            "trial_requires_data_on_empty_payload": trial_summary.get("requires_data_on_empty_payload", 0),
            "safety_note": (
                "No se infieren terapias, PSA/APE, testosterona ni elegibilidad de trials "
                "sin datos reales persistidos."
            ),
        },
        "lanes": lanes,
        "capture_plan": capture_plan,
        "audit": {
            "allowed_status_values": list(READINESS_STATUS_VALUES),
            "gate_contract_summary": gate_summary,
            "readiness_gate_contract_matrix": build_readiness_gate_contract_matrix(),
            "trial_contract_summary": trial_summary,
            "sources_used": _sources_used(patient, bundle, values),
            "missing_fields_by_lane": {
                lane["key"]: list(lane.get("missing_fields") or [])
                for lane in lanes
                if lane.get("missing_fields")
            },
            "evidence_anchors": list(EVIDENCE_ANCHORS),
        },
    }


@lru_cache(maxsize=1)
def build_readiness_gate_contract_matrix() -> list[dict[str, Any]]:
    """Map every pivotal gate to a readiness lane and capture surface."""
    try:
        from prostanet.shared.clinical_contract_audit import build_gate_contract_matrix
    except Exception:
        return []

    matrix: list[dict[str, Any]] = []
    for row in build_gate_contract_matrix():
        row_dict = row.to_dict() if hasattr(row, "to_dict") else dict(row)
        lane_key = _lane_for_gate(row_dict)
        row_dict["readiness_lane"] = lane_key
        row_dict["readiness_lane_label"] = LANE_LABELS.get(lane_key, lane_key)
        row_dict["readiness_status"] = (
            "covered" if row_dict.get("coverage_status") == "covered" and lane_key else "uncovered"
        )
        row_dict["readiness_capture_surface"] = LANE_PHASES.get(lane_key, row_dict.get("capture_phase", ""))
        matrix.append(row_dict)
    return matrix


@lru_cache(maxsize=1)
def summarize_readiness_gate_contracts() -> dict[str, Any]:
    matrix = build_readiness_gate_contract_matrix()
    total = len(matrix)
    covered = [row for row in matrix if row.get("readiness_status") == "covered"]
    by_lane: dict[str, int] = {}
    for row in covered:
        lane = str(row.get("readiness_lane") or "unassigned")
        by_lane[lane] = by_lane.get(lane, 0) + 1
    return {
        "total_gates": total,
        "covered_gates": len(covered),
        "uncovered_gates": [row for row in matrix if row.get("readiness_status") != "covered"],
        "by_lane": by_lane,
    }


def _build_lane(lane_key: str, context: Mapping[str, Any]) -> dict[str, Any]:
    applicable, reason = _lane_applicability(lane_key, context)
    required = list(LANE_REQUIRED_FIELDS.get(lane_key, ()))
    optional = list(LANE_OPTIONAL_FIELDS.get(lane_key, ()))
    if not applicable:
        status = "not_applicable"
        missing: list[str] = []
        fields_to_capture: list[str] = []
    else:
        missing = _missing_fields(required, context)
        status = _lane_status(lane_key, missing, context)
        fields_to_capture = missing + [
            field for field in optional if _should_offer_optional(field, context)
        ]

    impacted = _impacted_contracts_for_lane(lane_key)
    cta_url = _capture_url(
        lane_key=lane_key,
        state=str(context.get("state") or ""),
        patient_ref=str(context.get("patient_ref") or ""),
    )
    return {
        "key": lane_key,
        "label": LANE_LABELS.get(lane_key, lane_key),
        "status": status,
        "applicable": applicable,
        "reason": reason if reason else _status_reason(status, missing),
        "missing_fields": missing,
        "display_missing_fields": [_field_label(field) for field in missing],
        "fields_to_capture": fields_to_capture[:16],
        "display_fields_to_capture": [_field_label(field) for field in fields_to_capture[:16]],
        "capture_surface": LANE_PHASES.get(lane_key, "longitudinal_followup"),
        "cta_url": cta_url,
        "impacted_gates_count": len(impacted["gates"]),
        "impacted_trials_count": len(impacted["trials"]),
        "gates_impacted": impacted["gates"][:10],
        "trials_impacted": impacted["trials"][:10],
        "evidence_anchors": list(EVIDENCE_ANCHORS),
        "source_bundles": _source_bundles_for_lane(lane_key, context),
    }


def _lane_applicability(lane_key: str, context: Mapping[str, Any]) -> tuple[bool, str]:
    state = str(context.get("state") or "").lower()
    track = str(context.get("management_track") or "").lower()
    values = dict(context.get("values") or {})
    candidate_family = str(context.get("candidate_family") or "").lower()
    has_treatment = int(values.get("real_treatment_line_count") or 0) > 0
    has_adt_or_arpi = _real_treatment_has_tokens(context, ADT_TOKENS + ARPI_TOKENS)
    transition_to_crpc = _has_value(values, "progression_pattern") or "crpc" in state

    if lane_key == "diagnostic_biopsy_readiness":
        active = any(token in state for token in ("screening", "diagnostic", "negative_biopsy", "post_negative"))
        return active, "Carril activo solo en sospecha, screening o biopsia negativa."
    if lane_key == "active_surveillance_readiness":
        active = "localized" in state and (
            _has_value(values, "active_surveillance_eligibility_evaluation")
            or "surveillance" in track
            or "active_surveillance" in candidate_family
        )
        return active, "Seguimiento AS activo si el estado localizado documenta vigilancia activa."
    if lane_key == "localized_treatment_readiness":
        active = "localized" in state
        return active, "Carril activo para enfermedad localizada inicial."
    if lane_key == "patient_twin_readiness":
        active = any(
            token in state
            for token in (
                "localized",
                "bcr",
                "post_prostatectomy",
                "post_radiotherapy",
                "salvage",
                "crpc",
                "palliative",
                "paliativo",
            )
        )
        return active, "Patient Twin se activa en decisiones sensibles a preferencias, PROs, toxicidad y umbrales de redecision."
    if lane_key == "bcr_salvage_readiness":
        active = "bcr" in state or "salvage" in state or "post_radiotherapy" in state or "post_prostatectomy" in state
        return active, "Carril activo para BCR, post-RP, post-RT o rescate local."
    if lane_key == "mhspc_precision_readiness":
        active = state.startswith("mcspc") or "mhspc" in state or "mcspc" in state
        return active, "Carril activo para enfermedad metastasica sensible a castracion."
    if lane_key == "crpc_confirmation_readiness":
        active = "crpc" in state or "adt_progression" in state or transition_to_crpc
        return active, "CRPC requiere progresion, castracion e imagen convencional documentada."
    if lane_key == "m0crpc_arpi_readiness":
        active = "m0_crpc" in state or "m0crpc" in state
        return active, "Carril activo solo para m0CRPC."
    if lane_key == "m1crpc_sequence_readiness":
        active = "m1_crpc" in state or "m1crpc" in state
        return active, "Carril activo solo para m1CRPC."
    if lane_key == "parp_hrr_readiness":
        active = (
            ("crpc" in state or "mcspc" in state)
            and (
                any(token in candidate_family for token in PARP_TOKENS)
                or _hrr_positive_or_pending(values)
                or _real_treatment_has_tokens(context, PARP_TOKENS)
            )
        )
        return active, "PARP/HRR se activa solo cuando compite clinicamente por estado, linea o biomarcador."
    if lane_key == "psma_rlt_readiness":
        active = (
            "m1_crpc" in state
            and (
                any(token in candidate_family for token in PSMA_RLT_TOKENS)
                or _has_value(values, "psma_pet_status")
                or _real_treatment_has_tokens(context, PSMA_RLT_TOKENS)
            )
        )
        return active, "PSMA-RLT se activa solo en m1CRPC cuando la opcion compite clinicamente."
    if lane_key == "adt_arpi_safety_readiness":
        active = has_adt_or_arpi or any(token in candidate_family for token in ARPI_TOKENS)
        return active, "Seguridad ADT/ARPI solo aparece si hay terapia real o decision pendiente de esa familia."
    if lane_key == "supportive_palliative_readiness":
        active = (
            any(token in state for token in ("crpc", "mcspc", "palliative", "paliativo"))
            or _has_value(values, "pain_score")
            or has_treatment
        )
        return active, "Soporte/paliacion se activa por enfermedad avanzada, sintomas o tratamiento real."
    return False, "Carril no reconocido."


def _lane_status(lane_key: str, missing: list[str], context: Mapping[str, Any]) -> str:
    if _lane_has_active_risk(lane_key, context):
        return "active_risk"
    if missing:
        return "requires_data"
    if _lane_overdue(lane_key, context):
        return "overdue"
    return "ready"


def _lane_has_active_risk(lane_key: str, context: Mapping[str, Any]) -> bool:
    bundle = dict(context.get("bundle") or {})
    supportive = dict(bundle.get("supportive_care_toxicity_readiness_bundle") or {})
    therapeutic = dict(bundle.get("therapeutic_readiness_bundle") or {})
    active_safety = list((bundle.get("signals") or {}).get("active_safety") or [])
    if lane_key == "supportive_palliative_readiness":
        return str(supportive.get("supportive_readiness_status") or "").lower() in {"active_risk", "blocked"} or bool(active_safety)
    if lane_key in {"adt_arpi_safety_readiness", "m1crpc_sequence_readiness", "parp_hrr_readiness", "psma_rlt_readiness"}:
        if str(therapeutic.get("readiness_status") or "").lower() in {"active_risk", "blocked", "hard_stop"}:
            return True
        blockers = therapeutic.get("blocking_reasons") or therapeutic.get("hard_blocking_inputs") or []
        return bool(blockers and not _missing_fields(LANE_REQUIRED_FIELDS.get(lane_key, ()), context))
    return False


def _lane_overdue(lane_key: str, context: Mapping[str, Any]) -> bool:
    bundle = dict(context.get("bundle") or {})
    supportive = dict(bundle.get("supportive_care_toxicity_readiness_bundle") or {})
    advanced = dict(bundle.get("advanced_followup_bundle") or {})
    if lane_key in {"adt_arpi_safety_readiness", "supportive_palliative_readiness"}:
        text = " ".join(
            str(item).lower()
            for item in (
                list(supportive.get("overdue_items") or [])
                + list(advanced.get("overdue_items") or [])
                + list((bundle.get("signals") or {}).get("awaiting_review") or [])
            )
        )
        return bool(text and any(token in text for token in ("overdue", "vencid", "dexa", "toxicity", "ctcae", "bp", "pa")))
    return False


def _missing_fields(fields: Iterable[str], context: Mapping[str, Any]) -> list[str]:
    values = dict(context.get("values") or {})
    missing: list[str] = []
    for field in fields:
        if _field_satisfied(field, values, context):
            continue
        missing.append(field)
    return missing


def _field_satisfied(field: str, values: Mapping[str, Any], context: Mapping[str, Any]) -> bool:
    if field == "post_local_context":
        return any(
            _has_positive_or_text_value(values, item)
            for item in (
                "prior_prostatectomy",
                "prior_radiation",
                "prior_radical_prostatectomy_documented",
                "prior_radiation_therapy_documented",
                "primary_treatment",
                "prior_local_therapy",
                "definitive_local_therapy",
                "local_therapy_context",
            )
        )
    if field == "salvage_context_marker":
        return (
            any(
                _has_positive_or_text_value(values, item)
                for item in (
                    "bcr_detected",
                    "bcr_confirmed",
                    "phoenix_criteria_met",
                    "phoenix_failure_confirmed",
                )
            )
            or any(
                _has_value(values, item)
                for item in (
                    "bcr_date",
                    "bcr_psa",
                    "phoenix_delta",
                    "psa_nadir_post_rt",
                    "psa_rise_above_nadir_ng_ml",
                    "psa_current",
                    "psa_nadir",
                )
            )
        )
    if field == "dre_suspicious":
        return _has_documented_value(values, field)
    if field == "biopsy_status":
        return any(
            _has_documented_value(values, item)
            for item in (
                "biopsy_status",
                "planned_biopsy_type",
                "planned_biopsy_route",
                "biopsy_date",
                "biopsy_result",
                "primary_biopsy_completed_or_planned",
                "primary_biopsy_not_performed",
                "prior_negative_biopsy",
                "prior_negative_biopsy_documented",
                "targeted_biopsy_status",
                "prior_mpmri_targeted_biopsy_status",
            )
        )
    if field == "mri_pirads_score":
        return any(
            _has_documented_value(values, item)
            for item in (
                "mri_pirads_score",
                "pirads_score",
                "pirads",
                "mri_pi_rads",
                "mri_pirads",
                "prior_mpmri_pirads_score",
                "pirads_v21_score",
            )
        )
    if field == "family_history":
        return _has_documented_value(values, field)
    if field == "germline_risk":
        return _has_documented_value(values, field)
    if field == "patient_values":
        return any(_has_value(values, item) for item in ("patient_values", "patient_preferences", "goal_of_care", "goals_of_care_status"))
    if field == "baseline_pro":
        if any(_has_value(values, item) for item in ("baseline_pro", "baseline_pro_documented", "epic26_baseline", "epic26_total", "esas_score")):
            return True
        return all(
            _has_value(values, item)
            for item in ("urinary_function_baseline", "sexual_function_baseline", "bowel_function_baseline")
        )
    if field == "toxicity_tolerance":
        return any(_has_value(values, item) for item in ("toxicity_tolerance", "safety_priorities", "pro_ctcae_baseline", "unacceptable_toxicity_threshold"))
    if field == "decision_tradeoff":
        return any(_has_value(values, item) for item in ("decision_tradeoff", "rp_rt_as_tradeoff_documented", "shared_decision_local_options", "patient_preferences_vs_recommendation"))
    if field == "redecision_threshold":
        return any(_has_value(values, item) for item in ("redecision_threshold", "new_decision_threshold", "progression_threshold", "unacceptable_toxicity_threshold", "patient_redecision_trigger"))
    if field == "testosterone_value":
        if _has_value(values, field):
            return True
        status = str(_value_for(values, "castrate_testosterone_status") or "").lower()
        return status in {"confirmed_castrate", "castrate", "castracion_confirmada"}
    if field == "m1_composition":
        stage = str(_value_for(values, "m1_composition") or "").upper()
        if stage in {"M1A", "M1B", "M1C"}:
            return True
        return any(
            _has_value(values, token)
            for token in ("bone_lesion_count_total", "visceral_metastasis_present", "nonregional_nodal_count")
        )
    if field == "m0_m1_reconciled":
        return bool(_first_text(_value_for(values, "m0_m1_reconciled"), _value_for(values, "metastasis_site")))
    if field == "real_treatment_line":
        return int(values.get("real_treatment_line_count") or 0) > 0
    if field == "arpi_safety_baseline":
        return any(_has_value(values, item) for item in ("blood_pressure", "falls_cognition", "bone_health", "arpi_safety_baseline"))
    if field == "hrr_brca_status":
        value = str(_value_for(values, field) or "").lower()
        return bool(value and value not in EMPTY_VALUES)
    if field == "renal_function":
        return any(_has_value(values, item) for item in ("renal_function", "egfr", "creatinine_clearance"))
    if field == "hepatic_function":
        return any(_has_value(values, item) for item in ("hepatic_function", "ast", "alt", "bilirubin"))
    if field == "bone_marrow_reserve":
        return any(_has_value(values, item) for item in ("bone_marrow_reserve", "hemoglobin", "platelets", "anc"))
    if field == "glucose_or_hba1c":
        return any(_has_value(values, item) for item in ("glucose_or_hba1c", "glucose", "hba1c"))
    if field == "lipids":
        return any(_has_value(values, item) for item in ("lipids", "ldl", "triglycerides", "total_cholesterol"))
    if field == "blood_pressure":
        return any(_has_value(values, item) for item in ("blood_pressure", "systolic_blood_pressure", "bp_systolic"))
    if field == "bone_health":
        return any(_has_value(values, item) for item in ("bone_health", "dexa_status", "dexa_due", "vitamin_d_level", "calcium_level"))
    if field == "falls_cognition":
        return any(_has_value(values, item) for item in ("falls_cognition", "fall_risk_score_high", "moca_current", "cognitive_concerns_documented"))
    if field == "taxane_exposure":
        return _has_value(values, field) or _real_treatment_has_tokens(context, ("docetaxel", "cabazitaxel", "taxane"))
    if field == "arpi_exposure":
        return _has_value(values, field) or _real_treatment_has_tokens(context, ARPI_TOKENS)
    if field == "line_context":
        return _has_value(values, field) or int(values.get("real_treatment_line_count") or 0) > 0
    return _has_value(values, field)


def _extract_patient_values(patient: Mapping[str, Any], bundle: Mapping[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}

    def absorb(source: Any) -> None:
        if isinstance(source, Mapping):
            for key, value in source.items():
                if isinstance(value, (Mapping, list, tuple)):
                    continue
                if _is_present(value):
                    values[str(key)] = value

    identity = patient.get("identity") or {}
    latest_assessment = patient.get("latest_assessment") or {}
    latest_snapshot = patient.get("latest_signal_snapshot") or {}
    latest_followup = _latest_mapping(patient.get("followups"))
    latest_treatment = _latest_mapping(patient.get("treatments"))
    latest_genomic = _latest_mapping(patient.get("genomics") or patient.get("genomic_profile"))
    if isinstance(latest_treatment.get("regimen_json"), Mapping):
        absorb(latest_treatment.get("regimen_json"))
    absorb(identity)
    absorb(patient.get("baseline") or {})
    absorb(patient.get("prior_history") or {})
    absorb(latest_assessment.get("input_snapshot") or {})
    absorb(latest_assessment)
    absorb((bundle.get("longitudinal_truth_snapshot") or {}).get("field_values") or {})
    absorb(bundle.get("signals") or {})
    absorb(latest_snapshot)
    absorb(latest_followup)
    absorb(latest_treatment)
    absorb(latest_genomic)
    _absorb_biomarkers(values, patient.get("biomarker_longitudinal") or [])
    _absorb_imaging(values, patient.get("imaging_studies") or patient.get("imaging") or [])
    return values


def _absorb_biomarkers(values: dict[str, Any], biomarkers: Iterable[Any]) -> None:
    psa_points: list[tuple[str, Any]] = []
    testosterone_points: list[tuple[str, Any]] = []
    for item in biomarkers:
        if not isinstance(item, Mapping):
            continue
        biomarker_type = str(item.get("biomarker_type") or item.get("type") or item.get("name") or "").upper()
        date = str(item.get("sample_date") or item.get("date") or "")
        value = item.get("value", item.get("result"))
        if value is None:
            continue
        if biomarker_type in {"PSA", "APE"} or "PSA" in biomarker_type or "APE" in biomarker_type:
            psa_points.append((date, value))
        if "TESTOST" in biomarker_type:
            testosterone_points.append((date, value))
    if psa_points:
        psa_points.sort(key=lambda item: item[0])
        values["psa_value"] = psa_points[-1][1]
        values["latest_psa_date"] = psa_points[-1][0]
    if testosterone_points:
        testosterone_points.sort(key=lambda item: item[0])
        values["testosterone_value"] = testosterone_points[-1][1]
        values["latest_testosterone_date"] = testosterone_points[-1][0]


def _absorb_imaging(values: dict[str, Any], imaging: Iterable[Any]) -> None:
    for item in imaging:
        if not isinstance(item, Mapping):
            continue
        study_type = str(item.get("study_type") or item.get("modality") or "").lower()
        if "psma" in study_type or item.get("psma_result"):
            values["psma_pet_status"] = item.get("psma_result") or item.get("result") or item.get("status") or "documented"
        findings = item.get("findings_json") or {}
        if isinstance(findings, Mapping):
            for key, value in findings.items():
                if _is_present(value):
                    values[str(key)] = value


def _real_treatment_lines(patient: Mapping[str, Any]) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    for raw in patient.get("treatments") or []:
        if not isinstance(raw, Mapping):
            continue
        regimen = raw.get("regimen_json") if isinstance(raw.get("regimen_json"), Mapping) else {}
        label = _first_text(
            raw.get("drug_scheme"),
            raw.get("current_treatment"),
            raw.get("regimen_code"),
            regimen.get("drug_scheme_label"),
            regimen.get("drug_scheme"),
            regimen.get("regimen_label"),
        )
        if not _is_real_treatment_label(label):
            continue
        lines.append(
            {
                "line_of_therapy": _first_text(raw.get("line_of_therapy"), raw.get("line_number"), regimen.get("line_of_therapy_number")),
                "label": label,
                "drug_scheme": label,
                "start_date": _first_text(raw.get("start_date"), regimen.get("start_date")),
                "end_date": _first_text(raw.get("end_date"), regimen.get("end_date")),
                "source": "treatment_history",
            }
        )
    return lines


def _latest_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, (list, tuple)) and value:
        for item in reversed(value):
            if isinstance(item, Mapping):
                return item
    return {}


def _is_real_treatment_label(label: Any) -> bool:
    text = str(label or "").strip().lower()
    if text in PLACEHOLDER_TREATMENT_VALUES:
        return False
    return bool(text)


def _effective_state(values: Mapping[str, Any], bundle: Mapping[str, Any], explicit_state: str) -> str:
    signals = bundle.get("signals") or {}
    state = _first_text(
        explicit_state,
        signals.get("effective_state_final"),
        signals.get("effective_state"),
        signals.get("reconciled_state"),
        values.get("effective_state_final"),
        values.get("effective_state"),
        values.get("current_state"),
        values.get("state"),
        values.get("disease_state"),
        values.get("stage"),
    )
    return state or "diagnostic_workup"


def _candidate_family(bundle: Mapping[str, Any], values: Mapping[str, Any]) -> str:
    therapeutic = bundle.get("therapeutic_readiness_bundle") or {}
    action = bundle.get("next_best_action") or {}
    signals = bundle.get("signals") or {}
    return _first_text(
        therapeutic.get("candidate_family"),
        therapeutic.get("recommendation_family"),
        action.get("recommendation_family"),
        signals.get("effective_recommendation_family"),
        values.get("recommendation_family"),
    )


def _value_for(values: Mapping[str, Any], canonical: str) -> Any:
    for alias in FIELD_ALIASES.get(canonical, (canonical,)):
        if alias in values and _is_present(values.get(alias)):
            return values.get(alias)
    return None


def _has_value(values: Mapping[str, Any], canonical: str) -> bool:
    return _is_present(_value_for(values, canonical))


def _has_documented_value(values: Mapping[str, Any], canonical: str) -> bool:
    for alias in FIELD_ALIASES.get(canonical, (canonical,)):
        if alias not in values:
            continue
        value = values.get(alias)
        if value is None:
            continue
        if isinstance(value, bool):
            return True
        if isinstance(value, (int, float)):
            return True
        if isinstance(value, (list, tuple, set, dict)):
            return bool(value)
        text = str(value).strip().lower()
        if not text:
            continue
        if text in {"unknown", "desconocido", "pending", "pendiente", "sin dato", "sin datos", "n/a", "na", "—", "-"}:
            continue
        return True
    return False


def _has_positive_or_text_value(values: Mapping[str, Any], canonical: str) -> bool:
    for alias in FIELD_ALIASES.get(canonical, (canonical,)):
        if alias not in values:
            continue
        value = values.get(alias)
        if value is True:
            return True
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, (list, tuple, set, dict)):
            return bool(value)
        text = str(value or "").strip().lower()
        if not text or text in EMPTY_VALUES or text in {"0", "false", "no", "negative", "negativo"}:
            continue
        return True
    return False


def _is_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    text = str(value).strip().lower()
    return text not in EMPTY_VALUES


def _first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text and text.lower() not in EMPTY_VALUES:
            return text
    return ""


def _real_treatment_has_tokens(context: Mapping[str, Any], tokens: Iterable[str]) -> bool:
    token_tuple = tuple(str(token).lower() for token in tokens)
    for line in context.get("real_treatment_lines") or []:
        text = str(line.get("label") or line.get("drug_scheme") or "").lower()
        if any(token in text for token in token_tuple):
            return True
    return False


def _hrr_positive_or_pending(values: Mapping[str, Any]) -> bool:
    value = str(_value_for(values, "hrr_brca_status") or "").lower()
    if not value:
        return False
    return any(token in value for token in ("positive", "positivo", "mutated", "brca", "hrr", "pending", "pendiente"))


def _supportive_bundle_active(context: Mapping[str, Any]) -> bool:
    supportive = dict((context.get("bundle") or {}).get("supportive_care_toxicity_readiness_bundle") or {})
    status = str(supportive.get("supportive_readiness_status") or supportive.get("status") or "").lower()
    return bool(status and status not in {"not_applicable", "unavailable", "shadow"})


def _should_offer_optional(field: str, context: Mapping[str, Any]) -> bool:
    values = dict(context.get("values") or {})
    return not _field_satisfied(field, values, context)


def _field_label(field: str) -> str:
    return FIELD_LABELS.get(field, field.replace("_", " "))


def _status_reason(status: str, missing: list[str]) -> str:
    if status == "ready":
        return "Datos minimos suficientes para liberar el carril."
    if status == "requires_data":
        labels = ", ".join(_field_label(field) for field in missing[:3])
        return f"Faltan datos decisivos: {labels}."
    if status == "overdue":
        return "Hay datos de seguimiento vencidos antes de liberar la decision."
    if status == "active_risk":
        return "Existe riesgo activo o bloqueo de seguridad documentado."
    return "No aplica al estado clinico actual."


def _capture_url(*, lane_key: str, state: str, patient_ref: str) -> str:
    phase = LANE_PHASES.get(lane_key, "longitudinal_followup")
    if phase == "initial_wizard":
        return f"/wizard/{state or 'localized_initial'}?readiness_lane={lane_key}"
    if patient_ref:
        return f"/longitudinal-capture/{patient_ref}?readiness_lane={lane_key}"
    return f"/clinical-hub#pm2OfficialClassifier"


def _build_capture_plan(lanes: list[dict[str, Any]], state: str, patient_ref: str) -> dict[str, Any]:
    groups: list[dict[str, Any]] = []
    seen: set[str] = set()
    for lane in lanes:
        if lane.get("status") not in {"requires_data", "overdue", "active_risk"}:
            continue
        fields = [field for field in lane.get("fields_to_capture") or [] if field not in seen]
        seen.update(fields)
        if not fields:
            continue
        groups.append(
            {
                "lane_key": lane["key"],
                "lane_label": lane["label"],
                "status": lane["status"],
                "capture_surface": lane["capture_surface"],
                "cta_url": lane.get("cta_url") or _capture_url(
                    lane_key=lane["key"],
                    state=state,
                    patient_ref=patient_ref,
                ),
                "fields": fields,
                "display_fields": [_field_label(field) for field in fields],
            }
        )
    return {
        "total_missing_fields": len(seen),
        "groups": groups,
        "empty_message": "No hay campos pendientes por la torre." if not groups else "",
    }


def _priority_lane(lanes: list[dict[str, Any]]) -> dict[str, Any]:
    priority_statuses = ("active_risk", "requires_data", "overdue", "ready")
    for status in priority_statuses:
        for lane in lanes:
            if lane.get("status") == status:
                return lane
    return {}


def _dominant_blocker(lanes: list[dict[str, Any]]) -> str:
    for lane in lanes:
        if lane.get("status") in {"active_risk", "requires_data", "overdue"}:
            return f"{lane.get('label')}: {lane.get('reason')}"
    return "Sin bloqueo dominante."


def _source_bundles_for_lane(lane_key: str, context: Mapping[str, Any]) -> list[str]:
    sources = ["longitudinal_truth_snapshot", "decision_input_requirements", "clinical_field_router"]
    if lane_key in {"m1crpc_sequence_readiness", "parp_hrr_readiness", "psma_rlt_readiness", "adt_arpi_safety_readiness"}:
        sources.append("therapeutic_readiness_bundle")
    if lane_key in {"adt_arpi_safety_readiness", "supportive_palliative_readiness"}:
        sources.append("supportive_care_toxicity_readiness_bundle")
    if lane_key.startswith("crpc") or "crpc" in lane_key:
        sources.append("crpc_copilot_bundle")
    if lane_key == "bcr_salvage_readiness":
        sources.extend(["post_rp_salvage_bundle", "post_rt_salvage_bundle"])
    if lane_key == "mhspc_precision_readiness":
        sources.append("mhspc_copilot_bundle")
    if lane_key == "diagnostic_biopsy_readiness":
        sources.append("diagnostic_biopsy_bundle")
    if lane_key in {"active_surveillance_readiness", "localized_treatment_readiness"}:
        sources.append("localized_surveillance_bundle")
    return sources


def _sources_used(patient: Mapping[str, Any], bundle: Mapping[str, Any], values: Mapping[str, Any]) -> list[str]:
    sources = []
    if patient.get("baseline"):
        sources.append("baseline")
    if patient.get("latest_assessment"):
        sources.append("latest_assessment")
    if patient.get("biomarker_longitudinal"):
        sources.append("biomarker_longitudinal")
    if patient.get("treatments"):
        sources.append("treatment_history")
    if bundle.get("longitudinal_truth_snapshot"):
        sources.append("longitudinal_truth_snapshot")
    for key in (
        "therapeutic_readiness_bundle",
        "supportive_care_toxicity_readiness_bundle",
        "decision_input_requirements",
        "signals",
    ):
        if bundle.get(key):
            sources.append(key)
    if values:
        sources.append("merged_patient_values")
    return sorted(set(sources))


@lru_cache(maxsize=1)
def _trial_contract_summary() -> dict[str, Any]:
    try:
        from prostanet.shared.trial_criteria_registry import TRIAL_CRITERIA_REGISTRY
        from prostanet.shared.trial_eligibility_engine import evaluate_trial_eligibility
    except Exception:
        return {"total_trials": 0, "requires_data_on_empty_payload": 0, "empty_payload_failures": []}

    failures: list[str] = []
    for trial_id in TRIAL_CRITERIA_REGISTRY:
        result = evaluate_trial_eligibility({}, trial_id)
        if result.get("eligible") is True or result.get("status") != "requires_data":
            failures.append(str(trial_id))
    return {
        "total_trials": len(TRIAL_CRITERIA_REGISTRY),
        "requires_data_on_empty_payload": len(TRIAL_CRITERIA_REGISTRY) - len(failures),
        "empty_payload_failures": failures,
        "status_contract": "eligible | ineligible | requires_data",
    }


def _impacted_contracts_for_lane(lane_key: str) -> dict[str, list[str]]:
    gates = [
        row.get("gate_code", "")
        for row in build_readiness_gate_contract_matrix()
        if row.get("readiness_lane") == lane_key and row.get("gate_code")
    ]
    return {
        "gates": gates,
        "trials": _trials_for_lane(lane_key),
    }


def _trials_for_lane(lane_key: str) -> list[str]:
    try:
        from prostanet.shared.trial_criteria_registry import TRIAL_CRITERIA_REGISTRY
    except Exception:
        return []
    text_map = {
        "mhspc_precision_readiness": ("CHAARTED", "LATITUDE", "ARASENS", "PEACE", "STAMPEDE", "TITAN"),
        "m0crpc_arpi_readiness": ("SPARTAN", "PROSPER", "ARAMIS"),
        "m1crpc_sequence_readiness": ("TAX", "TROPIC", "CARD", "VISION", "PROFOUND", "ALSYMPCA"),
        "parp_hrr_readiness": ("PROFOUND", "TRITON", "TALAPRO", "MAGNITUDE", "PROPEL"),
        "psma_rlt_readiness": ("VISION", "PSMA"),
        "bcr_salvage_readiness": ("EMBARK", "RTOG", "RADICALS", "GETUG", "SPPORT"),
        "localized_treatment_readiness": ("PROTECT", "PIVOT", "SPCG"),
        "active_surveillance_readiness": ("PRIAS", "PASS", "PROTECT"),
    }
    needles = text_map.get(lane_key, ())
    if not needles:
        return []
    result = []
    for trial_id in TRIAL_CRITERIA_REGISTRY:
        upper = str(trial_id).upper()
        if any(needle.upper() in upper for needle in needles):
            result.append(str(trial_id))
    return result


def _lane_for_gate(row: Mapping[str, Any]) -> str:
    fields = " ".join(str(item) for item in row.get("trigger_fields") or []).lower()
    code = str(row.get("gate_code") or "").lower()
    text = f"{code} {fields}"
    token_text = " " + re.sub(r"[^a-z0-9]+", " ", text) + " "
    if any(token in text for token in (
        "ctcae", "toxicity", "toxicidad", "fall", "cognitive", "qtc",
        "lvef", "dexa", "glucose", "hypertension", "abiraterone",
        "enzalutamide", "apalutamide", "darolutamide", "steroid",
        "cortisol", "adrenal", "hepatotoxic", "cardiac", "fracture",
    )):
        return "adt_arpi_safety_readiness"
    if any(token in text for token in ("pain", "palliative", "sre", "spinal", "cachexia", "goals")):
        return "supportive_palliative_readiness"
    if any(token in text for token in ("hrr", "brca", "atm", "parp", "olaparib", "rucaparib", "niraparib", "talazoparib")):
        return "parp_hrr_readiness"
    if any(token in text for token in ("psma", "lutetium", "lu177", "radioligand")):
        return "psma_rlt_readiness"
    if any(token in text for token in ("docetaxel", "cabazitaxel", "taxane", "ar-v7", "ar_v7")) or " line " in token_text:
        return "m1crpc_sequence_readiness"
    if any(token in text for token in ("m0_crpc", "nmcrpc", "psadt")):
        return "m0crpc_arpi_readiness"
    if any(token in text for token in ("testosterone", "castrate", "adt_progression", "progression", "conventional_imaging")):
        return "crpc_confirmation_readiness"
    if any(token in text for token in ("chaarted", "latitude", "volume", "visceral", "bone", "nonregional", "metast")) or " m1 " in token_text:
        return "mhspc_precision_readiness"
    if any(token in text for token in ("bcr", "phoenix", "nadir", "salvage", "prostatectomy", "margin", "post_rt")):
        return "bcr_salvage_readiness"
    if any(token in text for token in ("surveillance", "confirmatory", "isup", "core", "cribriform", "intraductal")):
        return "active_surveillance_readiness"
    if any(token in text for token in ("biopsy", "pirads", "4k", "screen")) or " phi " in token_text or " dre " in token_text:
        return "diagnostic_biopsy_readiness"
    return "localized_treatment_readiness"


def _normalize_readiness_lane_key(lane_key: str | None) -> str:
    key = str(lane_key or "").strip()
    aliases = {
        "patient_twin_preference_pro_readiness": "patient_twin_readiness",
        "localized_function_preference_minimum": "localized_treatment_readiness",
        "preference_function_baseline": "localized_treatment_readiness",
        "patient_twin_preference_pro_minimum": "patient_twin_readiness",
        "diagnostic_truth_minimum": "diagnostic_biopsy_readiness",
        "diagnostic_data_completion": "diagnostic_biopsy_readiness",
        "diagnostic_minimum_dataset": "diagnostic_biopsy_readiness",
        "bcr_salvage_window_minimum": "bcr_salvage_readiness",
        "bcr_data_completion": "bcr_salvage_readiness",
    }
    return aliases.get(key, key)
