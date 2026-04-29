from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any


CERTAINTY_TIERS = {
    "derived": 1,
    "wizard_or_intake": 2,
    "structured_result": 3,
    "document_verified": 4,
    "clinician_verified": 5,
}


DEFAULT_FRESHNESS_POLICY = {
    "expires": False,
    "current_days": None,
    "aging_days": None,
}


FACT_FRESHNESS_POLICIES: dict[str, dict[str, Any]] = {
    "baseline_psa": {"expires": True, "current_days": 90, "aging_days": 180},
    "current_psa": {"expires": True, "current_days": 90, "aging_days": 180},
    "psa_series": {"expires": True, "current_days": 90, "aging_days": 180},
    "psa_postop": {"expires": True, "current_days": 90, "aging_days": 180},
    "psadt_months": {"expires": True, "current_days": 90, "aging_days": 180},
    "repeat_psa_value": {"expires": True, "current_days": 90, "aging_days": 180},
    "repeat_psa_date": {"expires": True, "current_days": 90, "aging_days": 180},
    "testosterone": {"expires": True, "current_days": 90, "aging_days": 180},
    "castrate_testosterone_status": {"expires": True, "current_days": 90, "aging_days": 180},
    "conventional_imaging_status": {"expires": True, "current_days": 90, "aging_days": 180},
    "conventional_imaging_date": {"expires": True, "current_days": 90, "aging_days": 180},
    "progression_pattern": {"expires": True, "current_days": 90, "aging_days": 180},
    "pirads_score": {"expires": True, "current_days": 180, "aging_days": 365},
    "mri_fact_date": {"expires": True, "current_days": 180, "aging_days": 365},
    "biopsy_date": {"expires": True, "current_days": 365, "aging_days": 730},
    "confirmatory_biopsy_done": {"expires": True, "current_days": 365, "aging_days": 730},
    "confirmatory_biopsy_date": {"expires": True, "current_days": 365, "aging_days": 730},
    "targeted_biopsy_status": {"expires": True, "current_days": 365, "aging_days": 730},
    "genomic_classifier_result": {"expires": False, "current_days": None, "aging_days": None},
    "genomic_classifier_report_date": {"expires": True, "current_days": 365, "aging_days": 730},
    "metastatic_stage_resolved": {"expires": True, "current_days": 180, "aging_days": 365},
    "metastatic_detection_basis": {"expires": True, "current_days": 180, "aging_days": 365},
    "metastasis_assessment_date": {"expires": True, "current_days": 180, "aging_days": 365},
    "metastasis_document_source": {"expires": True, "current_days": 180, "aging_days": 365},
    "histology_subtype": {"expires": False, "current_days": None, "aging_days": None},
    "gleason_primary": {"expires": False, "current_days": None, "aging_days": None},
    "gleason_secondary": {"expires": False, "current_days": None, "aging_days": None},
    "isup_grade": {"expires": False, "current_days": None, "aging_days": None},
    "ipss_total": {"expires": True, "current_days": 180, "aging_days": 365},
    "iief5_score": {"expires": True, "current_days": 180, "aging_days": 365},
    "epic26_urinary_incontinence_domain": {"expires": True, "current_days": 180, "aging_days": 365},
    "epic26_urinary_irritative_domain": {"expires": True, "current_days": 180, "aging_days": 365},
    "epic26_urinary_domain": {"expires": True, "current_days": 180, "aging_days": 365},
    "epic26_sexual_domain": {"expires": True, "current_days": 180, "aging_days": 365},
    "epic26_bowel_domain": {"expires": True, "current_days": 180, "aging_days": 365},
    "epic26_hormonal_domain": {"expires": True, "current_days": 180, "aging_days": 365},
    "epic26_overall_urinary_bother": {"expires": True, "current_days": 180, "aging_days": 365},
    "ecog_score": {"expires": True, "current_days": 180, "aging_days": 365},
    "charlson_score": {"expires": True, "current_days": 365, "aging_days": 730},
    "frailty_status": {"expires": True, "current_days": 180, "aging_days": 365},
    "g8_score": {"expires": True, "current_days": 180, "aging_days": 365},
    "anesthesia_surgical_fitness": {"expires": True, "current_days": 180, "aging_days": 365},
    "radiotherapy_feasibility": {"expires": True, "current_days": 180, "aging_days": 365},
    "patient_priority_profile": {"expires": True, "current_days": 365, "aging_days": 730},
    "mini_cog_score": {"expires": True, "current_days": 180, "aging_days": 365},
    "current_medications": {"expires": True, "current_days": 90, "aging_days": 180},
    "ddi_review_status": {"expires": True, "current_days": 90, "aging_days": 180},
    "cv_risk_documented": {"expires": True, "current_days": 180, "aging_days": 365},
    "hemoglobin": {"expires": True, "current_days": 14, "aging_days": 30},
    "creatinine": {"expires": True, "current_days": 14, "aging_days": 30},
    "potassium": {"expires": True, "current_days": 14, "aging_days": 30},
    "hrr_status": {"expires": False, "current_days": None, "aging_days": None},
    "hrr_gene": {"expires": False, "current_days": None, "aging_days": None},
    "biomarker_source": {"expires": False, "current_days": None, "aging_days": None},
    "molecular_report_date": {"expires": True, "current_days": 365, "aging_days": 730},
    "molecular_assay_date": {"expires": True, "current_days": 365, "aging_days": 730},
    "msi_status": {"expires": False, "current_days": None, "aging_days": None},
    "psma_study_date": {"expires": True, "current_days": 90, "aging_days": 180},
    "psma_positive": {"expires": True, "current_days": 90, "aging_days": 180},
    "psma_negative_dominant_lesions": {"expires": True, "current_days": 90, "aging_days": 180},
    "psma_pet_done": {"expires": True, "current_days": 90, "aging_days": 180},
    "current_adt_context": {"expires": True, "current_days": 180, "aging_days": 365},
    "line_of_therapy_number": {"expires": True, "current_days": 180, "aging_days": 365},
    "salvage_local_feasible": {"expires": True, "current_days": 180, "aging_days": 365},
    "psa_nadir": {"expires": True, "current_days": 180, "aging_days": 365},
    "psa_nadir_date": {"expires": True, "current_days": 180, "aging_days": 365},
    "phoenix_delta": {"expires": True, "current_days": 90, "aging_days": 180},
    "biopsy_proven_local_recurrence": {"expires": True, "current_days": 365, "aging_days": 730},
    "mpmri_done": {"expires": True, "current_days": 180, "aging_days": 365},
    "mpmri_localized_recurrence": {"expires": True, "current_days": 180, "aging_days": 365},
    "known_cancer_diagnosis": {"expires": False, "current_days": None, "aging_days": None},
    # ── EPIC 2 — Función renal basal (CKD-EPI 2021) ───────────────────────
    "egfr_ml_min": {"expires": True, "current_days": 90, "aging_days": 180},
    "creatinine_mg_dl": {"expires": True, "current_days": 90, "aging_days": 180},
    "egfr_date": {"expires": True, "current_days": 90, "aging_days": 180},
    "egfr_formula": {"expires": False, "current_days": None, "aging_days": None},
    # ── EPIC 2 — Halabi marcadores pronósticos ────────────────────────────
    "albumin_g_dl": {"expires": True, "current_days": 60, "aging_days": 120},
    "ldh_u_l": {"expires": True, "current_days": 60, "aging_days": 120},
    "hemoglobin_g_dl": {"expires": True, "current_days": 30, "aging_days": 90},
    "alkaline_phosphatase_u_l": {"expires": True, "current_days": 90, "aging_days": 180},
    "labs_baseline_date": {"expires": True, "current_days": 60, "aging_days": 180},
    # ── EPIC 2 — ADT timeline (no expira; marca hito clínico) ─────────────
    "adt_start_date": {"expires": False, "current_days": None, "aging_days": None},
    "adt_primary_agent": {"expires": False, "current_days": None, "aging_days": None},
    "adt_intent": {"expires": True, "current_days": 365, "aging_days": 730},
    # ── EPIC 2 — Sitios viscerales (anclados al staging vigente) ──────────
    "visceral_lung": {"expires": True, "current_days": 180, "aging_days": 365},
    "visceral_liver": {"expires": True, "current_days": 180, "aging_days": 365},
    "visceral_adrenal": {"expires": True, "current_days": 180, "aging_days": 365},
    "visceral_cns": {"expires": True, "current_days": 180, "aging_days": 365},
    # ── EPIC 2 — Genomic classifier numeric (anualmente no expira) ────────
    "decipher_score_numeric": {"expires": False, "current_days": None, "aging_days": None},
    "prolaris_ccp_score": {"expires": False, "current_days": None, "aging_days": None},
    "oncotype_gps": {"expires": False, "current_days": None, "aging_days": None},
    "genomic_classifier_date": {"expires": True, "current_days": 365, "aging_days": 730},
    # ── EPIC 2 — Germline vs somatic (germinal no expira; somático sí) ────
    "germline_testing_performed": {"expires": False, "current_days": None, "aging_days": None},
    "germline_pathogenic_variant": {"expires": False, "current_days": None, "aging_days": None},
    "germline_test_date": {"expires": False, "current_days": None, "aging_days": None},
    "somatic_testing_performed": {"expires": True, "current_days": 365, "aging_days": 730},
    "somatic_pathogenic_variant": {"expires": True, "current_days": 365, "aging_days": 730},
    "family_history_cancer": {"expires": False, "current_days": None, "aging_days": None},
    # ── EPIC 2 — Medicación estructurada ──────────────────────────────────
    "medication_list": {"expires": True, "current_days": 60, "aging_days": 180},
}


def _parse_date(value: Any) -> date | None:
    if value in (None, "", "None"):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def normalize_certainty_tier(
    value: Any,
    *,
    clinician_verified: bool = False,
    document_verified: bool = False,
) -> str:
    if clinician_verified:
        return "clinician_verified"
    if document_verified:
        return "document_verified"
    normalized = str(value or "").strip().lower()
    if normalized in CERTAINTY_TIERS:
        return normalized
    if normalized in {"verified", "manual_verified"}:
        return "clinician_verified"
    if normalized in {"document", "doc", "verified_document"}:
        return "document_verified"
    if normalized in {"structured", "structured_capture"}:
        return "structured_result"
    if normalized in {"wizard", "intake", "captured"}:
        return "wizard_or_intake"
    return "derived"


def certainty_rank(value: Any) -> int:
    return CERTAINTY_TIERS.get(normalize_certainty_tier(value), 0)


def resolve_freshness_policy(fact_key: str) -> dict[str, Any]:
    return dict(FACT_FRESHNESS_POLICIES.get(str(fact_key or "").strip(), DEFAULT_FRESHNESS_POLICY))


def compute_freshness_status(
    fact_key: str,
    *,
    source_date: Any = None,
    observed_at: Any = None,
    reference_date: date | None = None,
) -> tuple[str, str | None]:
    policy = resolve_freshness_policy(fact_key)
    if not policy.get("expires"):
        return "current", None
    effective_date = _parse_date(source_date) or _parse_date(observed_at)
    if effective_date is None:
        return "unknown", None
    today = reference_date or date.today()
    age_days = max((today - effective_date).days, 0)
    current_days = policy.get("current_days")
    aging_days = policy.get("aging_days")
    freshness_expires_at = None
    if current_days is not None:
        freshness_expires_at = (effective_date + timedelta(days=int(current_days))).isoformat()
    if current_days is not None and age_days <= int(current_days):
        return "current", freshness_expires_at
    if aging_days is not None and age_days <= int(aging_days):
        return "aging", freshness_expires_at
    return "stale", freshness_expires_at
