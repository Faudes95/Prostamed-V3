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
    # EPIC 31.A (Explore EXP-12 CRIT) — flag explícito de confirmación m0CRPC.
    # El gate pivotal 55 (PSADT≤10m → SPARTAN/PROSPER/ARAMIS) requiere este
    # flag como input. Pre-EPIC31 el flag estaba referenciado en YAML pero NO
    # en FACT_SPECS → gate fallaba si el clinical_state_classifier lo computa.
    "m0_crpc_state_confirmed": FactSpec(
        "m0_crpc_state_confirmed", "staging", "boolean",
        ("m0_crpc_confirmed", "m0_crpc_documented"), True,
        ("decision_input_requirements", "governance", "profile", "gates"),
    ),
    # EPIC 31.E (EXP-15 HIGH) — testosterone staleness sentinel. Si la última
    # testosterona fue medida hace >90 días, la clasificación CRPC vs HSPC
    # no es confiable; el classifier debe degrade castration_status a
    # "verification_pending" en lugar de asumir castrate.
    "testosterone_sample_date": FactSpec(
        "testosterone_sample_date", "biochemical", "date",
        ("last_testosterone_date",), False,
        ("decision_input_requirements", "governance", "profile"),
    ),
    "repeat_psa_value": FactSpec("repeat_psa_value", "biochemical", "number", (), False, ("decision_input_requirements", "governance")),
    "repeat_psa_date": FactSpec("repeat_psa_date", "biochemical", "date", (), False, ("decision_input_requirements", "governance")),
    "testosterone": FactSpec("testosterone", "biochemical", "number", ("testosterone_current", "testosterone_baseline"), True, ("decision_input_requirements", "governance")),
    "castrate_testosterone_status": FactSpec("castrate_testosterone_status", "systemic_context", "text", (), True, ("decision_input_requirements", "governance")),
    "conventional_imaging_status": FactSpec("conventional_imaging_status", "staging", "text", (), True, ("decision_input_requirements", "governance", "profile")),
    "conventional_imaging_date": FactSpec("conventional_imaging_date", "staging", "date", (), False, ("decision_input_requirements", "profile")),
    "progression_pattern": FactSpec("progression_pattern", "staging", "text", (), True, ("decision_input_requirements", "governance")),
    "known_cancer_diagnosis": FactSpec("known_cancer_diagnosis", "diagnostic", "boolean", (), True, ("reconciled_state", "contradictions")),
    "pirads_score": FactSpec("pirads_score", "diagnostic", "number", ("prior_mpmri_pirads_score", "pirads_v21_score"), True, ("decision_input_requirements", "profile")),
    "dre_suspicious": FactSpec("dre_suspicious", "diagnostic", "boolean", ("dre_abnormal", "digital_rectal_exam_suspicious"), True, ("decision_input_requirements", "governance", "profile")),
    "mri_fact_date": FactSpec("mri_fact_date", "diagnostic", "date", ("mpmri_date",), False, ("decision_input_requirements", "profile")),
    "biopsy_date": FactSpec("biopsy_date", "pathology", "date", (), False, ("decision_input_requirements", "profile")),
    "confirmatory_biopsy_done": FactSpec("confirmatory_biopsy_done", "pathology", "boolean", (), False, ("decision_input_requirements", "governance", "profile")),
    "confirmatory_biopsy_date": FactSpec("confirmatory_biopsy_date", "pathology", "date", (), False, ("decision_input_requirements", "profile")),
    "targeted_biopsy_status": FactSpec("targeted_biopsy_status", "pathology", "text", (), False, ("decision_input_requirements", "profile")),
    "histology_subtype": FactSpec("histology_subtype", "pathology", "text", (), True, ("official_diagnosis", "profile")),
    "gleason_primary": FactSpec("gleason_primary", "pathology", "number", (), True, ("decision_input_requirements", "profile")),
    "gleason_secondary": FactSpec("gleason_secondary", "pathology", "number", (), True, ("decision_input_requirements", "profile")),
    "isup_grade": FactSpec("isup_grade", "pathology", "number", (), True, ("decision_input_requirements", "profile")),
    # EPIC 42.B.1 — Risk-stratified localized discriminators identified as CRITICAL
    # missing por EPIC 39 inventory (Critic / NCCN PROS-2/3/4/5 risk stratification).
    # Without these in registry, intake form drops them silently and classifier
    # cannot distinguish very_low_risk_localized (AS) from low_risk (AS/tx choice).
    "psa_density": FactSpec("psa_density", "biochemical", "number",
                             ("psad", "psa_density_ratio"), True,
                             ("decision_input_requirements", "profile", "localized_modality")),
    "total_cores_biopsied": FactSpec("total_cores_biopsied", "pathology", "number",
                                      ("biopsy_total_cores", "cores_total"), True,
                                      ("decision_input_requirements", "profile")),
    "prostate_volume_ml": FactSpec("prostate_volume_ml", "diagnostic", "number",
                                    ("prostate_volume",), False,
                                    ("decision_input_requirements", "profile")),
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
    # EPIC 34.A Phase 6 — Granular PSMA-PET specs introducidos para record_psma_pet_capture
    # (status taxonómico de 6 valores + count + SUVmax + tracer). Estos facts son leídos
    # por trial_matching_engine._psma_positive() (psma_index_lesion_suvmax) y por gate 71
    # (psma_lesion_count). Sin registry entry, _persist_canonical_facts_from_payload los
    # dropea silenciosamente.
    "psma_pet_status": FactSpec("psma_pet_status", "precision", "text", (), False, ("precision_pathway", "profile", "trial_matcher")),
    "psma_lesion_count": FactSpec("psma_lesion_count", "precision", "number", (), False, ("precision_pathway", "profile", "trial_matcher")),
    "psma_index_lesion_suvmax": FactSpec("psma_index_lesion_suvmax", "precision", "number", ("psma_suvmax",), False, ("precision_pathway", "profile", "trial_matcher")),
    "psma_tracer": FactSpec("psma_tracer", "precision", "text", (), False, ("precision_pathway", "profile")),
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
    # ── EPIC 22b.5 — Post-RP pathology canonical facts ─────────────────────
    # These close the documented integration gaps:
    #   (1) RP Gleason never canonicalized → post_rp_salvage_copilot
    #       was reading diagnostic Gleason instead of RP piece Gleason.
    #   (2) Surgical margin status never in fact registry → salvage copilot
    #       was reading hardcoded fallback.
    #   (3) Percent pattern 4 capturable but not canonical → very-low-risk
    #       AS eligibility could not be enforced.
    # All declared `blocking=False` (additive only) per EPIC 22 constraint:
    # NO regression on existing classifications until EPIC 22d gates enable.
    "gleason_at_rp": FactSpec(
        "gleason_at_rp", "pathology", "text",
        ("gleason_score_at_rp", "rp_specimen_gleason", "gleason_pieza_rp"),
        False,
        ("decision_input_requirements", "post_rp_salvage_copilot",
         "risk_stratified_localized_copilot", "profile"),
    ),
    "gleason_primary_pattern_at_rp": FactSpec(
        "gleason_primary_pattern_at_rp", "pathology", "number",
        ("rp_gleason_primary", "gleason_primary_rp"),
        False,
        ("decision_input_requirements", "post_rp_salvage_copilot", "profile"),
    ),
    "gleason_secondary_pattern_at_rp": FactSpec(
        "gleason_secondary_pattern_at_rp", "pathology", "number",
        ("rp_gleason_secondary", "gleason_secondary_rp"),
        False,
        ("decision_input_requirements", "post_rp_salvage_copilot", "profile"),
    ),
    "tumor_stage_at_rp": FactSpec(
        "tumor_stage_at_rp", "pathology", "text",
        ("pT_stage", "pathologic_t_stage", "rp_pT"),
        False,
        ("decision_input_requirements", "post_rp_salvage_copilot", "profile"),
    ),
    "margin_status": FactSpec(
        "margin_status", "pathology", "text",
        ("surgical_margin_status", "rp_margin_status", "estado_margenes"),
        False,
        ("decision_input_requirements", "post_rp_salvage_copilot",
         "risk_stratified_localized_copilot", "profile"),
    ),
    "percent_pattern_4": FactSpec(
        "percent_pattern_4", "pathology", "number",
        ("pattern_4_pct", "pct_pattern_4", "porcentaje_patron_4"),
        False,
        ("decision_input_requirements", "risk_stratified_localized_copilot",
         "active_surveillance_eligibility", "profile"),
    ),
    "perineural_invasion": FactSpec(
        "perineural_invasion", "pathology", "boolean",
        ("pni", "invasion_perineural"),
        False,
        ("decision_input_requirements", "post_rp_salvage_copilot", "profile"),
    ),
    "percent_positive_cores": FactSpec(
        "percent_positive_cores", "pathology", "number",
        ("pct_positive_cores", "core_positive_pct", "porcentaje_cores_positivos"),
        False,
        ("decision_input_requirements", "risk_stratified_localized_copilot",
         "active_surveillance_eligibility", "profile"),
    ),
    # ── EPIC 22b.5 — NEPC / Aggressive variant biomarkers (rare but decision-changing) ──
    # NEPC differentiation triples 1-year mortality risk versus typical mCRPC and
    # routes to platinum-based chemotherapy (not ARSI). Capturing these as
    # canonical facts lets the nepc_differentiation copilot (EPIC 22c) read them.
    "chromogranin_a_value": FactSpec(
        "chromogranin_a_value", "pathology", "number", ("cga",),
        False, ("nepc_differentiation_copilot", "profile"),
    ),
    "synaptophysin_biopsy_positive": FactSpec(
        "synaptophysin_biopsy_positive", "pathology", "boolean", (),
        False, ("nepc_differentiation_copilot", "profile"),
    ),
    "small_cell_morphology": FactSpec(
        "small_cell_morphology", "pathology", "boolean", (),
        False, ("nepc_differentiation_copilot", "profile"),
    ),
    "nse_value": FactSpec(
        "nse_value", "pathology", "number",
        ("neuron_specific_enolase",),
        False, ("nepc_differentiation_copilot", "profile"),
    ),
    # ═════════════════════════════════════════════════════════════════
    # EPIC 46.A (FAUBOT CXXXII) — Latin Decision-Impacting Fields
    # ═════════════════════════════════════════════════════════════════
    # Estos 4 facts tienen IMPACTO DIRECTO en recomendación clínica
    # (no son captura "para research"). El backend tiene infra wired:
    #   - ETHNICITY_RISK_MODIFIERS (natural_history_tracker.py:40)
    #     modifica incidence_rr / mortality_rr / gleason_high_risk_rr
    #     según ancestría. Hoy defaultea a europeo_caucasico → invalida
    #     la diferenciación. Este fact activa el cálculo correcto.
    #   - recommendation_arbiter usa los 3 access flags para filter
    #     terapias localmente inviables (Lu-PSMA, ARSIs) y sugerir
    #     alternativas accesibles dentro de la realidad del paciente.
    "primary_ancestry": FactSpec(
        "primary_ancestry", "systemic_context", "text",
        ("ethnicity", "self_reported_ancestry", "ancestria_principal"),
        False,
        ("decision_input_requirements", "profile", "natural_history",
         "ethnicity_risk_modifier"),
    ),
    "psma_pet_local_access": FactSpec(
        "psma_pet_local_access", "systemic_context", "boolean",
        ("psma_pet_available_locally",),
        False,
        ("decision_input_requirements", "profile", "decision_arbiter",
         "treatment_access_filter"),
    ),
    "lu_psma_local_access": FactSpec(
        "lu_psma_local_access", "systemic_context", "boolean",
        ("lu_psma_617_available_locally", "vision_therapy_available"),
        False,
        ("decision_input_requirements", "profile", "decision_arbiter",
         "treatment_access_filter"),
    ),
    "arsi_local_access": FactSpec(
        "arsi_local_access", "systemic_context", "boolean",
        ("arsi_drugs_available_locally", "abi_enza_accessible"),
        False,
        ("decision_input_requirements", "profile", "decision_arbiter",
         "treatment_access_filter"),
    ),
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
        # EPIC 42.B.1 — new pathology + biochemical discriminators
        "psa_density",
        "total_cores_biopsied",
        "prostate_volume_ml",
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
        # EPIC 34.A Phase 6 — granular PSMA-PET capture aux facts
        "psma_pet_status",
        "psma_lesion_count",
        "psma_index_lesion_suvmax",
        "psma_tracer",
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
        # ── EPIC 22b.5 — Post-RP pathology + AS eligibility canonical facts ──
        "gleason_at_rp",
        "gleason_primary_pattern_at_rp",
        "gleason_secondary_pattern_at_rp",
        "tumor_stage_at_rp",
        "margin_status",
        "percent_pattern_4",
        "perineural_invasion",
        "percent_positive_cores",
        # ── EPIC 22b.5 — NEPC differentiation biomarkers ──
        "chromogranin_a_value",
        "synaptophysin_biopsy_positive",
        "small_cell_morphology",
        "nse_value",
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
        "dre_suspicious": _first_present(
            latest_assessment.get("input_snapshot") or {},
            "dre_suspicious",
            "dre_abnormal",
            "digital_rectal_exam_suspicious",
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
