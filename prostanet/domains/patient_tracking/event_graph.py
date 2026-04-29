from __future__ import annotations

from copy import deepcopy
from typing import Any


STATE_EVENT_EXPECTATIONS = {
    "diagnostic_workup": ["clinical_baseline", "mri_facts", "diagnostic_plan", "biopsy_trigger", "family_history_detail", "structured_biopsy"],
    "post_negative_biopsy_followup": ["clinical_baseline", "mri_facts", "diagnostic_plan", "biopsy_trigger"],
    "localized_initial": ["clinical_baseline", "biopsy_details", "patient_pros", "structured_biopsy", "active_surveillance_protocol", "survival_endpoint"],
    "post_prostatectomy": ["clinical_baseline", "surgical_details", "patient_pros", "radiation_detail", "survival_endpoint"],
    "recurrence_bcr": ["clinical_baseline", "biochemical_recurrence", "imaging_studies", "radiation_detail", "survival_endpoint"],
    "adt_progression_verification": ["clinical_baseline", "imaging_studies", "survival_endpoint"],
    "mcspc_oligo_metachronous": ["clinical_baseline", "genomic_profile", "treatment_history", "patient_pros", "skeletal_event", "radiation_detail", "survival_endpoint", "vital_status_update"],
    "mcspc_low_volume_sync_oligo": ["clinical_baseline", "genomic_profile", "treatment_history", "patient_pros", "skeletal_event", "radiation_detail", "survival_endpoint", "vital_status_update"],
    "mcspc_high_volume_sync": ["clinical_baseline", "genomic_profile", "treatment_history", "patient_pros", "skeletal_event", "survival_endpoint", "vital_status_update"],
    "mcspc_high_volume_metachronous": ["clinical_baseline", "genomic_profile", "treatment_history", "patient_pros", "skeletal_event", "survival_endpoint", "vital_status_update"],
    "mcspc_high_volume": ["clinical_baseline", "genomic_profile", "treatment_history", "patient_pros", "skeletal_event", "survival_endpoint", "vital_status_update"],
    "m0_crpc": ["clinical_baseline", "genomic_profile", "treatment_history", "patient_pros", "survival_endpoint", "vital_status_update"],
    "m1_crpc": ["clinical_baseline", "genomic_profile", "treatment_history", "patient_pros", "imaging_studies", "skeletal_event", "radiation_detail", "survival_endpoint", "vital_status_update"],
}


def _present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No realizado", "Desconocido", "Desconocida")


def _latest(items: list[dict[str, Any]]) -> dict[str, Any]:
    return dict(items[-1]) if items else {}


def build_processing_summary(state: str, payload: dict[str, Any], record: dict[str, Any] | None = None) -> dict[str, Any]:
    expected = STATE_EVENT_EXPECTATIONS.get(state, ["clinical_baseline"])
    persisted = []
    if record:
        if record.get("baseline"):
            persisted.append("clinical_baseline")
        if record.get("imaging"):
            persisted.append("imaging_studies")
        if record.get("genomics"):
            persisted.append("genomic_profile")
        if record.get("biopsies"):
            persisted.append("biopsy_details")
        if record.get("pros"):
            persisted.append("patient_pros")
        if record.get("bcr"):
            persisted.append("biochemical_recurrence")
        if record.get("surgery"):
            persisted.append("surgical_details")
        if record.get("radiation"):
            persisted.append("radiation_details")
        if record.get("treatments"):
            persisted.append("treatment_history")
        if record.get("family_history"):
            persisted.append("family_history_detail")
        if record.get("diagnostic_plans"):
            persisted.append("diagnostic_plan")
        if record.get("mri_facts"):
            persisted.append("mri_facts")
        if record.get("biopsy_triggers"):
            persisted.append("biopsy_trigger")

    return {
        "state": state,
        "expected_event_targets": expected,
        "persisted_event_targets": persisted,
        "missing_event_targets": [item for item in expected if item not in persisted],
        "tracked_input_count": len([key for key, value in payload.items() if _present(value)]),
    }


def merge_record_into_assessment_payload(assessment_input: dict[str, Any], record: dict[str, Any] | None) -> dict[str, Any]:
    merged = deepcopy(assessment_input or {})
    if not record:
        return merged

    baseline = record.get("baseline") or {}
    demographics = record.get("demographics") or {}
    genomics = record.get("genomics") or {}
    bcr = record.get("bcr") or {}
    surgery = record.get("surgery") or {}
    latest_pro = _latest(record.get("pros") or [])
    latest_followup = _latest(record.get("follow_ups") or [])
    latest_followup_payload = {}
    if isinstance(latest_followup.get("visit_bundle"), dict):
        latest_followup_payload = dict((latest_followup.get("visit_bundle") or {}).get("payload") or {})
    latest_biopsy = _latest(record.get("biopsies") or [])
    latest_mri_fact = _latest(record.get("mri_facts") or [])
    latest_diagnostic_plan = _latest(record.get("diagnostic_plans") or [])
    latest_biopsy_trigger = _latest(record.get("biopsy_triggers") or [])

    latest_mri = {}
    latest_psma = {}
    latest_bone = {}
    latest_conventional = {}
    for study in record.get("imaging") or []:
        study_type = str(study.get("study_type", "")).lower()
        if not latest_mri and "mri" in study_type:
            latest_mri = study
        if not latest_psma and "psma" in study_type:
            latest_psma = study
        if not latest_bone and ("gammagrama" in study_type or "bone" in study_type):
            latest_bone = study
        if not latest_conventional and "convencional" in study_type:
            latest_conventional = study

    merged.update(
        {
            "baseline_psa": merged.get("baseline_psa") or baseline.get("baseline_psa"),
            "testosterone_baseline": merged.get("testosterone_baseline") or baseline.get("testosterone_baseline"),
            "hemoglobin": merged.get("hemoglobin") or baseline.get("hemoglobin"),
            "alp": merged.get("alp") or baseline.get("alp"),
            "ldh": merged.get("ldh") or baseline.get("ldh"),
            "albumin": merged.get("albumin") or baseline.get("albumin"),
            "metastasis_site": merged.get("metastasis_site") or baseline.get("metastasis_site"),
            "volume_disease": merged.get("volume_disease") or baseline.get("volume_disease"),
            "peripheral_neuropathy_grade": merged.get("peripheral_neuropathy_grade") or baseline.get("peripheral_neuropathy_grade"),
            "life_expectancy_years": merged.get("life_expectancy_years") or baseline.get("life_expectancy_years"),
            "dre_suspicious": merged.get("dre_suspicious") if _present(merged.get("dre_suspicious")) else baseline.get("dre_suspicious"),
            "local_treatment_consideration": merged.get("local_treatment_consideration") or baseline.get("local_treatment_consideration"),
            "ipss_score": merged.get("ipss_score") or demographics.get("ipss_score") or latest_pro.get("ipss_total"),
            "iief5_score": merged.get("iief5_score") or demographics.get("iief5_score") or latest_pro.get("iief5_score"),
            "eq5d_vas": merged.get("eq5d_vas") or latest_pro.get("eq5d_vas"),
            "fact_p_total": merged.get("fact_p_total") or latest_pro.get("fact_p_total"),
            "bpi_worst_pain": merged.get("bpi_worst_pain") or latest_pro.get("bpi_worst_pain"),
            "fatigue_score": merged.get("fatigue_score") or latest_pro.get("fatigue_score") or latest_followup.get("fatigue_score"),
            "mini_cog_score": merged.get("mini_cog_score") or latest_followup.get("mini_cog_score"),
            "ddi_review_status": merged.get("ddi_review_status") or latest_followup.get("ddi_review_status"),
            "baseline_qol": merged.get("baseline_qol") or latest_pro.get("eq5d_vas"),
            "hrr_status": merged.get("hrr_status") or genomics.get("hrr_overall"),
            "brca2_status": merged.get("brca2_status") or genomics.get("brca2_status"),
            "msi_status": merged.get("msi_status") or genomics.get("msi_status"),
            "decipher_score": merged.get("decipher_score") or genomics.get("decipher_score"),
            "decipher_risk": merged.get("decipher_risk") or genomics.get("decipher_risk"),
            "gps_score": merged.get("gps_score") or genomics.get("gps_score"),
            "prolaris_score": merged.get("prolaris_score") or genomics.get("prolaris_score"),
            "molecular_report_date": merged.get("molecular_report_date") or genomics.get("test_date"),
            "psa_current": merged.get("psa_current") or bcr.get("bcr_psa"),
            "psadt_months": merged.get("psadt_months") or bcr.get("psadt_at_bcr"),
            "time_to_recurrence_months": merged.get("time_to_recurrence_months") or bcr.get("time_to_bcr_months"),
            "clinical_tstage": merged.get("clinical_tstage") or baseline.get("clinical_tstage"),
            "pathologic_stage": merged.get("pathologic_stage") or surgery.get("pathological_stage"),
            "pathology_gleason_primary": merged.get("pathology_gleason_primary") or surgery.get("pathological_gleason_primary"),
            "pathology_gleason_secondary": merged.get("pathology_gleason_secondary") or surgery.get("pathological_gleason_secondary"),
            "margin_location": merged.get("margin_location") or surgery.get("margin_location"),
            "surgical_margin": merged.get("surgical_margin") if _present(merged.get("surgical_margin")) else surgery.get("surgical_margin_status"),
            "ece_status": merged.get("ece_status") if _present(merged.get("ece_status")) else surgery.get("ece_pathological"),
            "svi_status": merged.get("svi_status") if _present(merged.get("svi_status")) else surgery.get("svi_pathological"),
            "lni_status": merged.get("lni_status") if _present(merged.get("lni_status")) else surgery.get("lni_pathological"),
            "prior_biopsy_count": merged.get("prior_biopsy_count") or len(record.get("biopsies") or []),
            "num_cores_positive": merged.get("num_cores_positive") or latest_biopsy.get("positive_cores"),
            "total_cores": merged.get("total_cores") or latest_biopsy.get("total_cores"),
            "gleason_primary": merged.get("gleason_primary") or latest_biopsy.get("gleason_primary"),
            "gleason_secondary": merged.get("gleason_secondary") or latest_biopsy.get("gleason_secondary"),
            "isup_grade": merged.get("isup_grade") or latest_biopsy.get("isup_grade"),
            "percent_pattern_4": merged.get("percent_pattern_4") or latest_biopsy.get("porcentaje_patron_4"),
            "adverse_histology_variant_type": merged.get("adverse_histology_variant_type") or latest_biopsy.get("adverse_histology_variant_type"),
            "adverse_histology_variant_detail": merged.get("adverse_histology_variant_detail") or latest_biopsy.get("adverse_histology_variant_detail"),
            "rare_histology_variant": merged.get("rare_histology_variant") or ("1" if _present(latest_biopsy.get("adverse_histology_variant_type")) and str(latest_biopsy.get("adverse_histology_variant_type")) not in {"", "none"} else ""),
            "prior_mpmri": merged.get("prior_mpmri") or ("1" if latest_mri else ""),
            "pirads_score": merged.get("pirads_score") or latest_mri_fact.get("pirads_score") or latest_mri.get("pirads_score"),
            "prior_mpmri_pirads_score": merged.get("prior_mpmri_pirads_score") or latest_mri.get("pirads_score"),
            "prior_mpmri_targeted_biopsy_status": merged.get("prior_mpmri_targeted_biopsy_status") or (latest_mri.get("findings", {}) if isinstance(latest_mri.get("findings"), dict) else {}).get("prior_mpmri_targeted_biopsy_status"),
            "index_lesion_location": merged.get("index_lesion_location") or latest_mri_fact.get("lesion_location") or latest_mri.get("pirads_location"),
            "index_lesion_size_mm": merged.get("index_lesion_size_mm") or latest_mri_fact.get("lesion_size_mm") or latest_mri.get("lesion_size_mm"),
            "mpmri_date": merged.get("mpmri_date") or latest_mri_fact.get("fact_date") or latest_mri.get("study_date"),
            "mpmri_quality": merged.get("mpmri_quality") or latest_mri_fact.get("quality") or (latest_mri.get("findings", {}) if isinstance(latest_mri.get("findings"), dict) else {}).get("mpmri_quality"),
            "prostate_volume_ml": merged.get("prostate_volume_ml") or latest_mri_fact.get("prostate_volume_ml"),
            "planned_biopsy_type": merged.get("planned_biopsy_type") or latest_biopsy_trigger.get("planned_biopsy_type"),
            "planned_biopsy_route": merged.get("planned_biopsy_route") or latest_biopsy_trigger.get("planned_biopsy_route"),
            "risk_calculator_pathway": merged.get("risk_calculator_pathway") or latest_diagnostic_plan.get("risk_calculator_pathway"),
            "psma_pet_done": merged.get("psma_pet_done") or ("1" if latest_psma else ""),
            "psma_pet_result": merged.get("psma_pet_result") or latest_psma.get("psma_result"),
            "psma_radioligand": merged.get("psma_radioligand") or latest_psma.get("psma_radioligand"),
            "psma_index_lesion_site": merged.get("psma_index_lesion_site") or latest_psma.get("psma_index_lesion_site"),
            "psma_index_lesion_suvmax": merged.get("psma_index_lesion_suvmax") or latest_psma.get("psma_index_lesion_suvmax") or latest_psma.get("psma_suv_max"),
            "psma_uptake_pattern": merged.get("psma_uptake_pattern") or (latest_psma.get("findings", {}) if isinstance(latest_psma.get("findings"), dict) else {}).get("psma_uptake_pattern"),
            "psma_rads_score": merged.get("psma_rads_score") or latest_psma.get("psma_rads_score"),
            "psma_stage_after_psma": merged.get("psma_stage_after_psma") or latest_psma.get("psma_stage_after_psma"),
            "psma_management_changed": merged.get("psma_management_changed") or latest_psma.get("psma_management_changed"),
            "has_bone_scan": merged.get("has_bone_scan") or ("1" if latest_bone else ""),
        }
    )

    followup_fallback_keys = (
        "life_expectancy_years",
        "local_treatment_consideration",
        "clinical_tstage",
        "nodal_status",
        "clinical_stage_group",
        "clinical_risk_group",
        "histology_subtype",
        "gleason_primary",
        "gleason_secondary",
        "isup_grade",
        "num_cores_positive",
        "total_cores",
        "pathology_gleason_primary",
        "pathology_gleason_secondary",
        "pathologic_stage",
        "surgical_margin",
        "ece_status",
        "svi_status",
        "lni_status",
        "decipher_score",
        "decipher_risk",
        "gps_score",
        "prolaris_score",
        "genomic_classifier",
        "genomic_classifier_result",
        "drug_scheme",
        "current_treatment",
        "peripheral_neuropathy_grade",
    )
    for field_name in followup_fallback_keys:
        if not _present(merged.get(field_name)) and _present(latest_followup_payload.get(field_name)):
            merged[field_name] = latest_followup_payload.get(field_name)

    if not _present(merged.get("conventional_imaging_status")):
        if latest_conventional:
            findings = latest_conventional.get("findings", {}) if isinstance(latest_conventional.get("findings"), dict) else {}
            merged["conventional_imaging_status"] = findings.get("conventional_imaging_status") or ("M0" if findings.get("conventional_imaging_m0") else "")
        elif latest_bone:
            merged["conventional_imaging_status"] = "M1" if str(latest_bone.get("bone_scan_result", "")).lower().startswith("positivo") else "M0"

    if not _present(merged.get("psma_positive")) and latest_psma:
        merged["psma_positive"] = "1" if str(latest_psma.get("psma_result", "")).lower().startswith("pos") else "0"
    if not _present(merged.get("molecular_assay_source")) and _present(genomics.get("actionable_findings")):
        merged["molecular_assay_source"] = merged.get("biomarker_source") or "Documento longitudinal"

    return merged


def derive_management_intent_status(state: str, result: dict[str, Any] | None, record: dict[str, Any] | None) -> str:
    decision_quality = (result or {}).get("decision_quality", {}) or {}
    if decision_quality.get("unsupported_or_escalate"):
        return "escalated"
    if record and (record.get("treatments") or record.get("surgery") or record.get("radiation") or record.get("active_surveillance")):
        return "delivered"
    return "candidate"


def derive_timeline_event_kind(state: str, result: dict[str, Any] | None, record: dict[str, Any] | None) -> str:
    if record and (record.get("treatments") or record.get("surgery") or record.get("radiation") or record.get("active_surveillance")):
        return "procedure_performed"
    if state == "localized_initial" and record and record.get("biopsies"):
        return "pathology_confirmed"
    if state in {"diagnostic_workup", "post_negative_biopsy_followup"}:
        return "recommendation_generated"
    if state == "adt_progression_verification":
        return "recommendation_generated"
    if (result or {}).get("decision_quality", {}).get("unsupported_or_escalate"):
        return "followup_visit_recorded"
    return "management_selected"
