from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from prostanet.shared.clinical_fact_policies import compute_freshness_status, normalize_certainty_tier
from prostanet.shared.epic26 import normalize_epic26_payload
from prostanet.shared.metastatic_profile import resolve_metastatic_state_context


@dataclass(frozen=True)
class FactSpec:
    fact_key: str
    domain: str
    value_type: str
    legacy_aliases: tuple[str, ...] = ()
    blocking: bool = False
    consumers: tuple[str, ...] = ()


FACT_SPECS: dict[str, FactSpec] = {
    "baseline_psa": FactSpec("baseline_psa", "biochemical", "number", ("psa",), True, ("decision_input_requirements", "profile")),
    "current_psa": FactSpec("current_psa", "biochemical", "number", ("psa_current", "psa"), True, ("decision_input_requirements", "governance")),
    "psa_postop": FactSpec("psa_postop", "biochemical", "number", (), True, ("decision_input_requirements", "governance", "profile")),
    "psadt_months": FactSpec("psadt_months", "biochemical", "number", ("psadt_at_bcr",), True, ("decision_input_requirements", "governance", "profile")),
    "repeat_psa_value": FactSpec("repeat_psa_value", "biochemical", "number", (), False, ("decision_input_requirements", "governance")),
    "repeat_psa_date": FactSpec("repeat_psa_date", "biochemical", "date", (), False, ("decision_input_requirements", "governance")),
    "testosterone": FactSpec("testosterone", "biochemical", "number", ("testosterone_current", "testosterone_baseline"), True, ("decision_input_requirements", "governance")),
    "castrate_testosterone_status": FactSpec("castrate_testosterone_status", "systemic_context", "text", (), True, ("decision_input_requirements", "governance")),
    "conventional_imaging_status": FactSpec("conventional_imaging_status", "staging", "text", (), True, ("decision_input_requirements", "governance", "profile")),
    "conventional_imaging_date": FactSpec("conventional_imaging_date", "staging", "date", (), False, ("decision_input_requirements", "profile")),
    "progression_pattern": FactSpec("progression_pattern", "staging", "text", (), True, ("decision_input_requirements", "governance")),
    "known_cancer_diagnosis": FactSpec("known_cancer_diagnosis", "diagnostic", "boolean", (), True, ("reconciled_state", "contradictions")),
    "pirads_score": FactSpec("pirads_score", "diagnostic", "number", ("prior_mpmri_pirads_score", "pirads_v21_score"), True, ("decision_input_requirements", "profile")),
    "mri_fact_date": FactSpec("mri_fact_date", "diagnostic", "date", ("mpmri_date",), False, ("decision_input_requirements", "profile")),
    "biopsy_date": FactSpec("biopsy_date", "pathology", "date", (), False, ("decision_input_requirements", "profile")),
    "confirmatory_biopsy_done": FactSpec("confirmatory_biopsy_done", "pathology", "boolean", (), False, ("decision_input_requirements", "governance", "profile")),
    "confirmatory_biopsy_date": FactSpec("confirmatory_biopsy_date", "pathology", "date", (), False, ("decision_input_requirements", "profile")),
    "targeted_biopsy_status": FactSpec("targeted_biopsy_status", "pathology", "text", (), False, ("decision_input_requirements", "profile")),
    "histology_subtype": FactSpec("histology_subtype", "pathology", "text", (), True, ("official_diagnosis", "profile")),
    "gleason_primary": FactSpec("gleason_primary", "pathology", "number", (), True, ("decision_input_requirements", "profile")),
    "gleason_secondary": FactSpec("gleason_secondary", "pathology", "number", (), True, ("decision_input_requirements", "profile")),
    "isup_grade": FactSpec("isup_grade", "pathology", "number", (), True, ("decision_input_requirements", "profile")),
    "genomic_classifier_result": FactSpec("genomic_classifier_result", "precision", "text", ("genomic_classifier", "decipher_risk"), False, ("localized_modality", "profile")),
    "genomic_classifier_report_date": FactSpec("genomic_classifier_report_date", "precision", "date", ("genomic_report_date",), False, ("localized_modality", "profile")),
    "metastatic_stage_resolved": FactSpec("metastatic_stage_resolved", "metastatic_context", "text", ("m_substage_resolved",), True, ("reconciled_state", "profile", "governance")),
    "metastatic_detection_basis": FactSpec("metastatic_detection_basis", "metastatic_context", "text", (), True, ("reconciled_state", "profile", "governance")),
    "metastasis_assessment_date": FactSpec("metastasis_assessment_date", "metastatic_context", "date", (), False, ("reconciled_state", "profile")),
    "metastasis_document_source": FactSpec("metastasis_document_source", "metastatic_context", "text", (), False, ("reconciled_state", "profile")),
    "ecog_score": FactSpec("ecog_score", "fitness", "number", ("ecog", "ecog_current"), True, ("decision_input_requirements", "governance")),
    "charlson_score": FactSpec("charlson_score", "fitness", "number", ("charlson_index",), True, ("decision_input_requirements", "governance", "profile")),
    "frailty_status": FactSpec("frailty_status", "frailty", "text", (), True, ("decision_input_requirements", "governance", "profile")),
    "g8_score": FactSpec("g8_score", "frailty", "number", (), True, ("localized_modality", "governance", "profile")),
    "anesthesia_surgical_fitness": FactSpec("anesthesia_surgical_fitness", "fitness", "text", (), True, ("localized_modality", "governance", "profile")),
    "radiotherapy_feasibility": FactSpec("radiotherapy_feasibility", "fitness", "text", (), False, ("localized_modality", "governance", "profile")),
    "patient_priority_profile": FactSpec("patient_priority_profile", "preferences", "text", (), False, ("localized_modality", "governance", "profile")),
    "mini_cog_score": FactSpec("mini_cog_score", "frailty", "number", (), False, ("mhspc_selector", "governance")),
    "ipss_total": FactSpec("ipss_total", "pros", "number", ("ipss_score",), False, ("localized_modality", "profile")),
    "iief5_score": FactSpec("iief5_score", "pros", "number", ("iief5", "iief5_score"), False, ("localized_modality", "profile")),
    "epic26_urinary_incontinence_domain": FactSpec("epic26_urinary_incontinence_domain", "pros", "number", (), False, ("localized_modality", "profile")),
    "epic26_urinary_irritative_domain": FactSpec("epic26_urinary_irritative_domain", "pros", "number", (), False, ("localized_modality", "profile")),
    "epic26_urinary_domain": FactSpec("epic26_urinary_domain", "pros", "number", (), False, ("localized_modality", "profile")),
    "epic26_sexual_domain": FactSpec("epic26_sexual_domain", "pros", "number", (), False, ("localized_modality", "profile")),
    "epic26_bowel_domain": FactSpec("epic26_bowel_domain", "pros", "number", (), False, ("localized_modality", "profile")),
    "epic26_hormonal_domain": FactSpec("epic26_hormonal_domain", "pros", "number", (), False, ("localized_modality", "profile")),
    "epic26_overall_urinary_bother": FactSpec("epic26_overall_urinary_bother", "pros", "number", (), False, ("localized_modality", "profile")),
    "hrr_status": FactSpec("hrr_status", "precision", "text", (), False, ("precision_pathway", "profile")),
    "hrr_gene": FactSpec("hrr_gene", "precision", "text", (), False, ("precision_pathway", "profile")),
    "biomarker_source": FactSpec("biomarker_source", "precision", "text", (), False, ("precision_pathway", "profile")),
    "molecular_report_date": FactSpec("molecular_report_date", "precision", "date", ("molecular_assay_date",), False, ("precision_pathway", "profile")),
    "msi_status": FactSpec("msi_status", "precision", "text", (), False, ("precision_pathway", "profile")),
    "psma_pet_done": FactSpec("psma_pet_done", "precision", "boolean", ("psma_done",), False, ("precision_pathway", "profile")),
    "psma_study_date": FactSpec("psma_study_date", "precision", "date", ("psma_pet_date",), False, ("precision_pathway", "profile")),
    "psma_positive": FactSpec("psma_positive", "precision", "boolean", (), False, ("precision_pathway", "profile")),
    "psma_negative_dominant_lesions": FactSpec("psma_negative_dominant_lesions", "precision", "boolean", (), False, ("precision_pathway", "profile")),
    "current_adt_context": FactSpec("current_adt_context", "systemic_context", "text", (), True, ("decision_input_requirements", "governance")),
    "current_medications": FactSpec("current_medications", "supportive", "text", (), False, ("governance", "profile")),
    "ddi_review_status": FactSpec("ddi_review_status", "supportive", "text", ("drug_interaction_reviewed",), False, ("governance", "profile")),
    "cv_risk_documented": FactSpec("cv_risk_documented", "supportive", "boolean", (), False, ("governance", "profile")),
    "hemoglobin": FactSpec("hemoglobin", "laboratory", "number", (), False, ("governance", "profile")),
    "creatinine": FactSpec("creatinine", "laboratory", "number", (), False, ("governance", "profile")),
    "potassium": FactSpec("potassium", "laboratory", "number", (), False, ("governance", "profile")),
    "line_of_therapy_number": FactSpec("line_of_therapy_number", "systemic_context", "number", ("line_of_therapy",), False, ("governance", "profile")),
    "salvage_local_feasible": FactSpec("salvage_local_feasible", "salvage", "boolean", (), False, ("decision_input_requirements", "governance", "profile")),
    "psa_nadir": FactSpec("psa_nadir", "biochemical", "number", (), False, ("decision_input_requirements", "governance", "profile")),
    "psa_nadir_date": FactSpec("psa_nadir_date", "biochemical", "date", (), False, ("decision_input_requirements", "profile")),
    "phoenix_delta": FactSpec("phoenix_delta", "biochemical", "number", (), False, ("decision_input_requirements", "governance", "profile")),
    "biopsy_proven_local_recurrence": FactSpec("biopsy_proven_local_recurrence", "salvage", "boolean", (), False, ("decision_input_requirements", "governance", "profile")),
    "mpmri_done": FactSpec("mpmri_done", "staging", "boolean", (), False, ("decision_input_requirements", "profile")),
    "mpmri_localized_recurrence": FactSpec("mpmri_localized_recurrence", "staging", "boolean", (), False, ("decision_input_requirements", "profile")),
    # ── EPIC 2 — Función renal basal (CKD-EPI 2021) ───────────────────────
    "egfr_ml_min": FactSpec("egfr_ml_min", "renal", "number", ("egfr", "egfr_ml_min_1_73m2"), False, ("decision_input_requirements", "governance", "profile")),
    "creatinine_mg_dl": FactSpec("creatinine_mg_dl", "renal", "number", ("creatinine", "serum_creatinine"), False, ("decision_input_requirements", "governance", "profile")),
    "egfr_formula": FactSpec("egfr_formula", "renal", "text", (), False, ("governance", "profile")),
    "egfr_date": FactSpec("egfr_date", "renal", "date", (), False, ("decision_input_requirements", "profile")),
    # ── EPIC 2 — Marcadores pronósticos Halabi 2014 ───────────────────────
    "albumin_g_dl": FactSpec("albumin_g_dl", "laboratory", "number", ("albumin", "serum_albumin"), False, ("decision_input_requirements", "governance", "profile")),
    "ldh_u_l": FactSpec("ldh_u_l", "laboratory", "number", ("ldh", "serum_ldh"), False, ("decision_input_requirements", "governance", "profile")),
    "hemoglobin_g_dl": FactSpec("hemoglobin_g_dl", "laboratory", "number", ("hemoglobin", "hgb"), False, ("decision_input_requirements", "governance", "profile")),
    "alkaline_phosphatase_u_l": FactSpec("alkaline_phosphatase_u_l", "laboratory", "number", ("alp",), False, ("decision_input_requirements", "governance", "profile")),
    "labs_baseline_date": FactSpec("labs_baseline_date", "laboratory", "date", (), False, ("decision_input_requirements", "profile")),
    # ── EPIC 2 — Terapia de privación androgénica (timeline) ──────────────
    "adt_start_date": FactSpec("adt_start_date", "systemic_context", "date", (), False, ("decision_input_requirements", "governance", "profile")),
    "adt_primary_agent": FactSpec("adt_primary_agent", "systemic_context", "text", (), False, ("governance", "profile")),
    "adt_intent": FactSpec("adt_intent", "systemic_context", "text", (), False, ("governance", "profile")),
    # ── EPIC 2 — Sitios viscerales estructurados (Halabi HR) ──────────────
    "visceral_lung": FactSpec("visceral_lung", "metastatic_context", "boolean", (), False, ("governance", "profile")),
    "visceral_liver": FactSpec("visceral_liver", "metastatic_context", "boolean", (), False, ("governance", "profile")),
    "visceral_adrenal": FactSpec("visceral_adrenal", "metastatic_context", "boolean", (), False, ("governance", "profile")),
    "visceral_cns": FactSpec("visceral_cns", "metastatic_context", "boolean", (), False, ("governance", "profile")),
    # ── EPIC 2 — Genomic classifier numeric scores ────────────────────────
    "decipher_score_numeric": FactSpec("decipher_score_numeric", "precision", "number", (), False, ("localized_modality", "profile")),
    "prolaris_ccp_score": FactSpec("prolaris_ccp_score", "precision", "number", (), False, ("localized_modality", "profile")),
    "oncotype_gps": FactSpec("oncotype_gps", "precision", "number", (), False, ("localized_modality", "profile")),
    "genomic_classifier_date": FactSpec("genomic_classifier_date", "precision", "date", (), False, ("localized_modality", "profile")),
    # ── EPIC 2 — Germline vs somatic testing ──────────────────────────────
    "germline_testing_performed": FactSpec("germline_testing_performed", "precision", "boolean", (), False, ("precision_pathway", "governance", "profile")),
    "germline_pathogenic_variant": FactSpec("germline_pathogenic_variant", "precision", "text", (), False, ("precision_pathway", "governance", "profile")),
    "germline_test_date": FactSpec("germline_test_date", "precision", "date", (), False, ("precision_pathway", "profile")),
    "somatic_testing_performed": FactSpec("somatic_testing_performed", "precision", "boolean", (), False, ("precision_pathway", "governance", "profile")),
    "somatic_pathogenic_variant": FactSpec("somatic_pathogenic_variant", "precision", "text", (), False, ("precision_pathway", "governance", "profile")),
    "family_history_cancer": FactSpec("family_history_cancer", "precision", "boolean", (), False, ("precision_pathway", "profile")),
    # ── EPIC 2 — Medicación estructurada ──────────────────────────────────
    "medication_list": FactSpec("medication_list", "supportive", "text", ("current_medications",), False, ("governance", "profile")),
}


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No documentado", "Desconocido", "Desconocida", "unknown", "UNKNOWN")


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


def _first_present(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if _is_present(value):
            return value
    return None


def get_fact_spec(fact_key: str) -> FactSpec | None:
    return FACT_SPECS.get(str(fact_key or "").strip())


def iter_registered_fact_specs() -> list[FactSpec]:
    return list(FACT_SPECS.values())


def _coerce_value(spec: FactSpec, value: Any) -> Any:
    if not _is_present(value):
        return None
    if spec.value_type == "number":
        if isinstance(value, bool):
            return int(value)
        return _safe_float(value) if "." in str(value) else _safe_int(value)
    if spec.value_type == "boolean":
        return str(value).strip().lower() in {"1", "true", "yes", "si", "sí"}
    return value


def _append_fact(
    facts: list[dict[str, Any]],
    spec: FactSpec,
    value: Any,
    *,
    source_type: str,
    source_record_type: str,
    source_record_id: Any = None,
    source_date: str = "",
    observed_at: str = "",
    state_context: str = "",
    management_track: str = "",
    certainty_tier: str = "wizard_or_intake",
    clinician_verified: bool = False,
    verification_note: str = "",
) -> None:
    coerced = _coerce_value(spec, value)
    if not _is_present(coerced):
        return
    freshness_status, freshness_expires_at = compute_freshness_status(
        spec.fact_key,
        source_date=source_date,
        observed_at=observed_at,
    )
    facts.append(
        {
            "fact_key": spec.fact_key,
            "value": coerced,
            "normalized_value_text": str(coerced),
            "source_type": source_type,
            "source_record_type": source_record_type,
            "source_record_id": source_record_id,
            "source_date": source_date or observed_at or "",
            "observed_at": observed_at or source_date or "",
            "state_context": state_context,
            "management_track": management_track,
            "certainty_tier": normalize_certainty_tier(
                certainty_tier,
                clinician_verified=clinician_verified,
                document_verified=source_type == "source_document",
            ),
            "freshness_status": freshness_status,
            "freshness_expires_at": freshness_expires_at,
            "clinician_verified": bool(clinician_verified),
            "verification_note": verification_note or "",
            "domain": spec.domain,
            "value_type": spec.value_type,
            "blocking": bool(spec.blocking),
            "consumers": list(spec.consumers),
        }
    )


def _extract_simple_fact(
    payload: dict[str, Any],
    facts: list[dict[str, Any]],
    fact_key: str,
    *,
    source_type: str,
    source_record_type: str,
    source_record_id: Any = None,
    source_date: str = "",
    observed_at: str = "",
    state_context: str = "",
    management_track: str = "",
    certainty_tier: str = "wizard_or_intake",
    clinician_verified: bool = False,
    verification_note: str = "",
) -> None:
    spec = get_fact_spec(fact_key)
    if not spec:
        return
    value = _first_present(payload, fact_key, *spec.legacy_aliases)
    _append_fact(
        facts,
        spec,
        value,
        source_type=source_type,
        source_record_type=source_record_type,
        source_record_id=source_record_id,
        source_date=source_date,
        observed_at=observed_at,
        state_context=state_context,
        management_track=management_track,
        certainty_tier=certainty_tier,
        clinician_verified=clinician_verified,
        verification_note=verification_note,
    )


def extract_canonical_fact_candidates(
    payload: dict[str, Any] | None,
    *,
    source_type: str,
    source_record_type: str,
    source_record_id: Any = None,
    source_date: str = "",
    observed_at: str = "",
    state_context: str = "",
    management_track: str = "",
    certainty_tier: str = "wizard_or_intake",
    clinician_verified: bool = False,
    verification_note: str = "",
) -> list[dict[str, Any]]:
    payload = dict(payload or {})
    facts: list[dict[str, Any]] = []
    for fact_key in (
        "baseline_psa",
        "current_psa",
        "psa_postop",
        "psadt_months",
        "repeat_psa_value",
        "repeat_psa_date",
        "testosterone",
        "castrate_testosterone_status",
        "conventional_imaging_status",
        "conventional_imaging_date",
        "progression_pattern",
        "known_cancer_diagnosis",
        "pirads_score",
        "mri_fact_date",
        "biopsy_date",
        "confirmatory_biopsy_done",
        "confirmatory_biopsy_date",
        "targeted_biopsy_status",
        "histology_subtype",
        "gleason_primary",
        "gleason_secondary",
        "isup_grade",
        "genomic_classifier_result",
        "genomic_classifier_report_date",
        "ecog_score",
        "g8_score",
        "mini_cog_score",
        "ipss_total",
        "iief5_score",
        "epic26_urinary_incontinence_domain",
        "epic26_urinary_irritative_domain",
        "epic26_urinary_domain",
        "epic26_sexual_domain",
        "epic26_bowel_domain",
        "epic26_hormonal_domain",
        "epic26_overall_urinary_bother",
        "hrr_status",
        "hrr_gene",
        "biomarker_source",
        "molecular_report_date",
        "msi_status",
        "psma_pet_done",
        "psma_study_date",
        "psma_positive",
        "psma_negative_dominant_lesions",
        "current_adt_context",
        "current_medications",
        "ddi_review_status",
        "cv_risk_documented",
        "hemoglobin",
        "creatinine",
        "potassium",
        "line_of_therapy_number",
        "salvage_local_feasible",
        "psa_nadir",
        "psa_nadir_date",
        "phoenix_delta",
        "biopsy_proven_local_recurrence",
        "mpmri_done",
        "mpmri_localized_recurrence",
    ):
        _extract_simple_fact(
            payload,
            facts,
            fact_key,
            source_type=source_type,
            source_record_type=source_record_type,
            source_record_id=source_record_id,
            source_date=source_date,
            observed_at=observed_at,
            state_context=state_context,
            management_track=management_track,
            certainty_tier=certainty_tier,
            clinician_verified=clinician_verified,
            verification_note=verification_note,
        )

    metastatic_context = resolve_metastatic_state_context(payload)
    for fact_key, value in (
        ("metastatic_stage_resolved", metastatic_context.get("metastatic_stage_resolved")),
        ("metastatic_detection_basis", metastatic_context.get("metastatic_detection_basis")),
        ("metastasis_assessment_date", metastatic_context.get("metastasis_assessment_date")),
        ("metastasis_document_source", payload.get("metastasis_document_source")),
    ):
        spec = get_fact_spec(fact_key)
        if spec:
            _append_fact(
                facts,
                spec,
                value,
                source_type=source_type,
                source_record_type=source_record_type,
                source_record_id=source_record_id,
                source_date=source_date or str(metastatic_context.get("metastasis_assessment_date") or ""),
                observed_at=observed_at,
                state_context=state_context,
                management_track=management_track,
                certainty_tier=certainty_tier,
                clinician_verified=clinician_verified,
                verification_note=verification_note,
            )
    return facts


def build_legacy_shadow_payload(patient: dict[str, Any]) -> dict[str, Any]:
    baseline = dict(patient.get("baseline") or {})
    latest_followup = (patient.get("follow_ups") or [{}])[-1] if patient.get("follow_ups") else {}
    demographics = dict(patient.get("demographics") or {})
    prior_history = dict(patient.get("prior_history") or {})
    latest_assessment = dict(patient.get("latest_assessment") or {})
    truth_values = dict((patient.get("longitudinal_truth_snapshot") or {}).get("field_values") or {})
    latest_biopsy = (patient.get("biopsies") or [{}])[-1] if patient.get("biopsies") else {}
    latest_structured_biopsy = (patient.get("structured_biopsy_sessions") or [{}])[-1] if patient.get("structured_biopsy_sessions") else {}
    latest_imaging = (patient.get("imaging_studies") or [{}])[-1] if patient.get("imaging_studies") else {}
    latest_mri_fact = (patient.get("mri_facts") or [{}])[-1] if patient.get("mri_facts") else {}
    latest_genomic = dict(patient.get("genomics") or {})
    if not latest_genomic and patient.get("genomic_reports"):
        latest_genomic = dict((patient.get("genomic_reports") or [{}])[0] or {})
    bcr = dict(patient.get("bcr") or {})
    as_protocol = dict(patient.get("active_surveillance_protocol") or {})
    shadow = {
        "baseline_psa": baseline.get("baseline_psa"),
        "current_psa": latest_followup.get("psa_current"),
        "psa_postop": _first_present(truth_values, "psa_postop") or baseline.get("psa_postop") or latest_followup.get("psa_postop"),
        "psadt_months": _first_present(truth_values, "psadt_months") or latest_followup.get("psadt_months") or bcr.get("psadt_months"),
        "repeat_psa_value": _first_present(latest_assessment.get("input_snapshot") or {}, "repeat_psa_value"),
        "repeat_psa_date": _first_present(latest_assessment.get("input_snapshot") or {}, "repeat_psa_date"),
        "testosterone": patient.get("latest_testosterone_value") or latest_followup.get("testosterone_current") or baseline.get("testosterone_baseline"),
        "castrate_testosterone_status": _first_present(
            truth_values,
            "castrate_testosterone_status",
        )
        or _first_present(latest_assessment.get("input_snapshot") or {}, "castrate_testosterone_status"),
        "known_cancer_diagnosis": _first_present(
            truth_values,
            "known_cancer_diagnosis",
        )
        or _first_present(latest_assessment.get("input_snapshot") or {}, "known_cancer_diagnosis"),
        "pirads_score": _first_present(
            latest_assessment.get("input_snapshot") or {},
            "pirads_score",
            "prior_mpmri_pirads_score",
        ),
        "mri_fact_date": _first_present(latest_assessment.get("input_snapshot") or {}, "mpmri_date", "mri_fact_date")
        or latest_mri_fact.get("mpmri_date")
        or latest_mri_fact.get("study_date")
        or latest_imaging.get("mpmri_date"),
        "biopsy_date": latest_biopsy.get("biopsy_date") or latest_structured_biopsy.get("biopsy_date"),
        "confirmatory_biopsy_done": _first_present(
            truth_values,
            "confirmatory_biopsy_done",
        )
        or _first_present(latest_assessment.get("input_snapshot") or {}, "confirmatory_biopsy_done")
        or as_protocol.get("confirmatory_biopsy_done"),
        "confirmatory_biopsy_date": _first_present(
            latest_assessment.get("input_snapshot") or {},
            "confirmatory_biopsy_date",
        )
        or as_protocol.get("confirmatory_biopsy_date")
        or latest_structured_biopsy.get("biopsy_date"),
        "targeted_biopsy_status": _first_present(
            latest_assessment.get("input_snapshot") or {},
            "targeted_biopsy_status",
            "planned_biopsy_type",
        ),
        "histology_subtype": baseline.get("histology_subtype"),
        "gleason_primary": baseline.get("gleason_primary"),
        "gleason_secondary": baseline.get("gleason_secondary"),
        "isup_grade": baseline.get("isup_grade"),
        "genomic_classifier_result": _first_present(
            latest_assessment.get("input_snapshot") or {},
            "genomic_classifier_result",
            "genomic_classifier",
        )
        or latest_genomic.get("genomic_classifier_result")
        or latest_genomic.get("genomic_classifier")
        or latest_genomic.get("decipher_risk"),
        "genomic_classifier_report_date": _first_present(
            latest_assessment.get("input_snapshot") or {},
            "genomic_classifier_report_date",
            "genomic_report_date",
        )
        or latest_genomic.get("genomic_classifier_report_date")
        or latest_genomic.get("genomic_report_date"),
        "ecog_score": _first_present(latest_followup, "ecog_current", "ecog"),
        "g8_score": demographics.get("g8_score") or latest_followup.get("g8_score"),
        "mini_cog_score": demographics.get("mini_cog_score") or latest_followup.get("mini_cog_score"),
        "ipss_total": demographics.get("ipss_score"),
        "iief5_score": demographics.get("iief5_score"),
        "epic26_urinary_incontinence_domain": _first_present(
            latest_assessment.get("input_snapshot") or {},
            "epic26_urinary_incontinence_domain",
            "epic26_urinary_domain",
            "baseline_urinary_qol",
        )
        or prior_history.get("baseline_urinary_qol"),
        "epic26_urinary_irritative_domain": _first_present(
            latest_assessment.get("input_snapshot") or {},
            "epic26_urinary_irritative_domain",
            "epic26_urinary_domain",
            "baseline_urinary_qol",
        )
        or prior_history.get("baseline_urinary_qol"),
        "epic26_urinary_domain": _first_present(
            latest_assessment.get("input_snapshot") or {},
            "epic26_urinary_domain",
            "epic26_urinary_incontinence_domain",
            "baseline_urinary_qol",
        )
        or prior_history.get("baseline_urinary_qol"),
        "epic26_sexual_domain": _first_present(
            latest_assessment.get("input_snapshot") or {},
            "epic26_sexual_domain",
            "baseline_sexual_qol",
        )
        or prior_history.get("baseline_sexual_qol"),
        "epic26_bowel_domain": _first_present(
            latest_assessment.get("input_snapshot") or {},
            "epic26_bowel_domain",
            "baseline_bowel_qol",
        )
        or prior_history.get("baseline_bowel_qol"),
        "epic26_hormonal_domain": _first_present(
            latest_assessment.get("input_snapshot") or {},
            "epic26_hormonal_domain",
        ),
        "epic26_overall_urinary_bother": _first_present(
            latest_assessment.get("input_snapshot") or {},
            "epic26_overall_urinary_bother",
        ),
        "hrr_status": baseline.get("hrr_status") or (patient.get("genomics") or {}).get("hrr_overall"),
        "msi_status": baseline.get("msi_status") or (patient.get("genomics") or {}).get("msi_status"),
        "psma_pet_done": _first_present(truth_values, "psma_pet_done") or latest_imaging.get("psma_pet_done"),
        "current_adt_context": _first_present(truth_values, "current_adt_context") or _first_present(latest_assessment.get("input_snapshot") or {}, "current_adt_context"),
        "line_of_therapy_number": _first_present(truth_values, "line_of_therapy_number") or _first_present(latest_assessment.get("input_snapshot") or {}, "line_of_therapy_number"),
        "salvage_local_feasible": _first_present(truth_values, "salvage_local_feasible") or bcr.get("salvage_local_feasible"),
        "psa_nadir": _first_present(truth_values, "psa_nadir") or latest_followup.get("psa_nadir"),
        "psa_nadir_date": _first_present(truth_values, "psa_nadir_date") or latest_followup.get("psa_nadir_date"),
        "phoenix_delta": _first_present(truth_values, "phoenix_delta") or latest_followup.get("phoenix_delta"),
        "biopsy_proven_local_recurrence": _first_present(truth_values, "biopsy_proven_local_recurrence") or latest_followup.get("biopsy_proven_local_recurrence"),
        "mpmri_done": _first_present(truth_values, "mpmri_done") or latest_followup.get("mpmri_done"),
        "mpmri_localized_recurrence": _first_present(truth_values, "mpmri_localized_recurrence") or latest_followup.get("mpmri_localized_recurrence"),
        "metastasis_site": baseline.get("metastasis_site"),
        "metastatic_disease_known": baseline.get("metastasis_site") not in (None, "", "M0"),
        "m_substage_resolved": baseline.get("m_substage_resolved"),
        "metastasis_assessment_date": baseline.get("metastasis_assessment_date"),
        "metastasis_document_source": baseline.get("metastasis_document_source"),
        "psma_stage_after_psma": _first_present((patient.get("imaging") or [{}])[0], "psma_stage_after_psma"),
        "psma_positive": _first_present((patient.get("imaging") or [{}])[0], "psma_result"),
    }
    return normalize_epic26_payload(shadow)
