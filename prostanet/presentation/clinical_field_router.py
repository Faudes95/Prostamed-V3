"""Clinical Field Router for state-scoped capture surfaces.

This module keeps the official quick classifier as the single entry point, while
preserving the clinically valuable progressive refiners as a reusable library.
The router returns compact, context-aware groups for the state wizard and the
longitudinal follow-up screen instead of exposing a flat high-volume form.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping


VALID_PHASES = {"classifier", "initial_wizard", "longitudinal_followup"}
GROUP_ORDER = ("required", "decision_refiners", "monitoring", "optional")

GROUP_LABELS = {
    "required": "Minimos del contexto",
    "decision_refiners": "Refinadores de decision",
    "monitoring": "Seguimiento y seguridad",
    "optional": "Opcionales utiles",
}

GROUP_LIMITS = {
    "classifier": {
        "required": 60,
        "decision_refiners": 0,
        "monitoring": 0,
        "optional": 0,
    },
    "initial_wizard": {
        "required": 12,
        "decision_refiners": 20,
        "monitoring": 8,
        "optional": 8,
    },
    "longitudinal_followup": {
        "required": 10,
        "decision_refiners": 14,
        "monitoring": 26,
        "optional": 8,
    },
}

CRPC_DENY_KEYWORDS = (
    "hrr", "brca", "atm", "parp", "parpi", "arpi", "arsi", "ar-v7",
    "ar_v7", "castrate", "testosterone", "crpc", "lutetium", "lu177",
    "lu-177", "radium", "ra-223", "sipuleucel", "cabazitaxel",
    "docetaxel", "ctcae", "apalutamide", "darolutamide", "enzalutamide",
    "abiraterone", "niraparib", "olaparib", "rucaparib", "talazoparib",
)

BCR_DENY_KEYWORDS = CRPC_DENY_KEYWORDS + (
    "visceral_crisis", "new_visceral", "widespread_bone", "psma_new_lesion",
    "psma_suvmax", "actinium", "radioligand",
)

M0_CRPC_DENY_KEYWORDS = (
    "bcr_", "phoenix", "psa_nadir_post_rt", "months_post_rt",
    "psa_bounce", "surgical_margin", "pathological_t",
    "prior_radical_prostatectomy", "salvage_rt", "visceral_metastasis",
    "visceral_metastases", "liver_metastasis", "m1", "bone_lesion_count",
    "bone_metastasis", "nonregional", "metachronous",
)

M1_CRPC_DENY_KEYWORDS = (
    "bcr_", "phoenix", "psa_nadir_post_rt", "months_post_rt",
    "psa_bounce", "surgical_margin", "pathological_t",
    "time_from_definitive_treatment",
)

LOCALIZED_DENY_KEYWORDS = (
    "bcr_", "phoenix", "psa_nadir_post_rt", "months_post_rt",
    "salvage", "castrate", "testosterone", "crpc", "hrr", "brca",
    "parp", "arpi", "ar_v7", "ar-v7", "lutetium", "radium", "ctcae",
    "visceral_metastasis", "bone_metastasis", "metastases_count",
    "psma_new_lesion", "psma_suvmax",
)

METASTATIC_INCLUDE_KEYWORDS = (
    "psa", "gleason", "ecog", "metastasis", "metastatic", "bone",
    "visceral", "nodal", "nonregional", "m1", "volume", "latitude",
    "chaarted", "metachronous", "synchronous", "sync", "appendicular",
    "adt", "treatment", "line", "imaging", "hormone",
)

POLICIES = {
    "recurrence_bcr": {
        "include": (
            "psa", "bcr", "biochemical", "doubling", "psadt", "salvage",
            "post-rp", "post_rp", "rp", "prostatectomy", "radiotherapy",
            "radiation", "rt", "phoenix", "nadir", "margin", "pathological",
            "gleason", "time_from_definitive", "psma_pet_staging",
            "re_irradiation", "pelvic_rt", "cribriform",
        ),
        "exclude": BCR_DENY_KEYWORDS,
    },
    "post_prostatectomy": {
        "include": (
            "psa", "prostatectomy", "post-rp", "post_rp", "rp",
            "pathological", "surgical", "margin", "lymph", "bcr",
            "gleason", "salvage",
        ),
        "exclude": BCR_DENY_KEYWORDS,
    },
    "post_radiotherapy_followup": {
        "include": (
            "psa", "radiotherapy", "radiation", "rt", "nadir", "phoenix",
            "bounce", "months_post_rt", "psa_rise", "ecog", "imaging",
        ),
        "exclude": CRPC_DENY_KEYWORDS,
    },
    "post_radiotherapy_or_local_salvage": {
        "include": (
            "psa", "radiotherapy", "radiation", "rt", "nadir", "phoenix",
            "bounce", "salvage", "re_irradiation", "pelvic_rt", "ecog",
            "imaging", "local",
        ),
        "exclude": CRPC_DENY_KEYWORDS,
    },
    "localized_initial": {
        "include": (
            "psa", "gleason", "isup", "clinical_t", "clinical_n",
            "clinical_m", "clinical_tstage", "nodal", "stage", "risk",
            "life_expectancy", "life expectancy", "age", "ecog", "charlson",
            "active_surveillance", "surveillance", "decision_rp_vs_rt",
            "rp_vs_rt", "prostatectomy", "radiotherapy", "histology",
            "tertiary", "cribriform", "intraductal", "svi", "nomogram",
        ),
        "exclude": LOCALIZED_DENY_KEYWORDS,
    },
    "m0_crpc": {
        "include": (
            "psa", "doubling", "psadt", "crpc", "castrate", "testosterone",
            "adt", "arpi", "arsi", "apalutamide", "darolutamide",
            "enzalutamide", "conventional", "imaging", "m0", "ecog",
            "progression", "hypertension", "fall", "mobility", "dexa",
            "dxa", "bone_protection", "ctcae", "qtc", "lvef",
        ),
        "exclude": M0_CRPC_DENY_KEYWORDS,
    },
    "m1_crpc": {
        "include": (
            "psa", "crpc", "castrate", "testosterone", "adt", "hrr",
            "brca", "atm", "parp", "psma", "lutetium", "lu177", "lu-177",
            "radium", "ra-223", "metastasis", "metastatic", "bone",
            "visceral", "liver", "line", "therapy", "treatment", "ecog",
            "ar_v7", "ar-v7", "docetaxel", "cabazitaxel", "genomic",
            "progression", "ctcae", "cytopenia", "hb", "platelets",
        ),
        "exclude": M1_CRPC_DENY_KEYWORDS,
    },
    "adt_progression_verification": {
        "include": (
            "psa", "adt", "castrate", "testosterone", "progression",
            "conventional", "imaging", "m0", "m1", "ecog",
        ),
        "exclude": (
            "parp", "hrr", "brca", "lutetium", "radium", "salvage",
            "phoenix", "psa_nadir_post_rt",
        ),
    },
    "diagnostic_workup": {
        "include": (
            "psa", "dre", "biopsy", "mri", "pirads", "phi", "4k",
            "age", "family", "screening", "density", "psad", "repeat",
        ),
        "exclude": CRPC_DENY_KEYWORDS + ("salvage", "metastasis"),
    },
    "post_negative_biopsy_followup": {
        "include": (
            "psa", "dre", "biopsy", "negative", "mri", "pirads", "phi",
            "4k", "age", "density", "psad", "repeat",
        ),
        "exclude": CRPC_DENY_KEYWORDS + ("salvage", "metastasis"),
    },
    "screening": {
        "include": (
            "psa", "dre", "screening", "family", "age", "repeat", "phi",
            "4k", "density", "psad",
        ),
        "exclude": CRPC_DENY_KEYWORDS + ("salvage", "metastasis"),
    },
}

STATE_ALIASES = {
    "mcspc_high_volume": "mcspc_high_volume_sync",
}

STATE_FIELD_ALLOWLISTS = {
    "recurrence_bcr": {
        "psa_value", "psa_doubling_time_months", "prior_prostatectomy",
        "prior_radiation", "time_from_definitive_treatment_months",
        "gleason_score", "bcr_detected", "bcr_date", "bcr_psa",
        "prior_radical_prostatectomy_documented",
        "bcr_high_risk_aggressive_documented",
        "bcr_aggressive_treated_for_salvage",
        "salvage_rt_consideration_active", "psma_pet_staging_recent",
        "prior_radiation_therapy_documented", "prior_pelvic_radiation",
        "re_irradiation_pelvic_contraindicated",
        "salvage_re_rt_protocol_documented", "psa_nadir_post_rt",
        "psa_rise_above_nadir_ng_ml", "months_post_rt",
        "psa_bounce_documented_post_rt",
        "psa_elevation_unconfirmed_post_rt", "surgical_margins_status",
        "pathological_t_stage", "cribriform_pattern_present",
        "etnia", "seguridad_social",
    },
    "localized_initial": {
        "psa_value", "psa_baseline_ng_ml", "gleason_score",
        "gleason_primary", "gleason_secondary", "clinical_tstage",
        "clinical_t_stage", "clinical_n_stage", "clinical_m_stage",
        "nodal_status", "metastasis_site", "clinical_risk_group",
        "clinical_stage_group", "life_expectancy_years",
        "life_expectancy_months", "age", "ecog_score",
        "charlson_comorbidity_index", "decision_rp_vs_rt_active",
        "active_surveillance_eligibility_evaluation",
        "svi_risk_nomogram_percent", "svi_risk_high_documented",
        "has_adverse_tertiary_pattern", "intraductal_carcinoma_present",
        "cribriform_pattern_present", "histology_subtype",
        "planning_radical_prostatectomy",
        "high_bleeding_risk_documented_pre_rp", "etnia",
        "seguridad_social",
    },
    "m0_crpc": {
        "psa_value", "psa_doubling_time_months",
        "castrate_testosterone_status", "testosterone_value",
        "castrate_testosterone_status_confirmed",
        "conventional_imaging_status",
        "imaging_modality_used_for_m_staging", "ecog_score",
        "no_active_arpi_for_m0_crpc",
        "psadt_progressive_for_arpi_eligibility",
        "arpi_already_initiated_for_m0_crpc",
        "psa_baseline_pre_arpi", "psa_change_percent_since_arpi_start",
        "psa_weeks_since_arpi_start", "psa_flare_documented_first_month_arpi",
        "qtc_baseline_ms", "lvef_baseline_percent",
        "qtc_corrected_for_arpi", "lvef_decline_for_arpi",
        "lvef_recovered_for_arpi", "hypertension_ctcae_grade",
        "systolic_blood_pressure", "diastolic_blood_pressure",
        "fall_event_documented", "fall_risk_score_high",
        "mobility_decline_longitudinal", "hypothyroidism_documented_during_treatment",
        "arpi_toxicity_review", "arpi_blood_pressure_monitoring",
        "dexa_due", "ctcae_grade_max", "etnia", "seguridad_social",
    },
}

MCSPC_FIELD_ALLOWLIST = {
    "psa_value", "metastasis_site", "bone_lesion_count_total",
    "bone_appendicular_count", "visceral_metastasis_present",
    "metachronous_metastasis", "ecog_score", "gleason_score",
    "chaarted_volume_classification", "latitude_high_risk_criteria_count",
    "nonregional_nodal_count", "visceral_site_entries",
    "imaging_modality_used_for_m_staging", "conventional_imaging_status",
    "bone_scan_multifoci_positive", "visceral_metastases_documented",
    "etnia", "seguridad_social",
}


def build_clinical_field_router(
    state: str,
    phase: str = "initial_wizard",
    captured_so_far: Mapping[str, Any] | None = None,
    readiness_lane: str | None = None,
) -> dict[str, Any]:
    """Return state-aware fields for classifier, wizard, or longitudinal use."""
    normalized_state = _normalize_state(state)
    normalized_phase = _normalize_phase(phase)
    captured = dict(captured_so_far or {})
    readiness_focus = _readiness_focus_fields(readiness_lane)

    if normalized_phase == "classifier":
        return _build_classifier_router(normalized_state)

    progressive = _build_progressive_capture(normalized_state, captured)
    candidates = _candidate_groups(progressive, normalized_state, normalized_phase)
    groups: dict[str, dict[str, Any]] = {}

    used_names: set[str] = set()
    for group_key in GROUP_ORDER:
        filtered = _filter_fields(
            candidates.get(group_key, []),
            state=normalized_state,
            phase=normalized_phase,
            group_key=group_key,
            readiness_focus=readiness_focus,
        )
        unique_for_context = []
        for field in filtered:
            name = field.get("name")
            if not name or name in used_names:
                continue
            used_names.add(name)
            unique_for_context.append(field)
        limited = unique_for_context[: GROUP_LIMITS[normalized_phase][group_key]]
        groups[group_key] = _group_payload(group_key, limited, normalized_phase)

    total_fields = sum(group["field_count"] for group in groups.values())
    return {
        "state": normalized_state,
        "phase": normalized_phase,
        "source": "clinical_field_router",
        "stage_label": progressive.get("stage_label") or normalized_state,
        "groups": groups,
        "group_order": [groups[key] for key in GROUP_ORDER],
        "summary": {
            "total_fields": total_fields,
            "saturation_guard": True,
            "max_fields_allowed": sum(GROUP_LIMITS[normalized_phase].values()),
            "source_total_fields_available": (
                progressive.get("summary", {}).get("total_fields_available")
            ),
            "routing_policy": _policy_name(normalized_state),
            "readiness_lane": str(readiness_lane or ""),
            "readiness_filter_active": bool(readiness_focus),
        },
        "audit_note": (
            "Clinical Field Router · official classifier remains entry gate · "
            "progressive refiners are routed by state and phase"
        ),
    }


def _build_classifier_router(state: str) -> dict[str, Any]:
    from prostanet.presentation.v2_adapters import quick_classify_schema

    schema = quick_classify_schema()
    fields = [_normalize_field(field) for field in schema.get("fields", [])]
    groups = {
        "required": _group_payload("required", fields, "classifier"),
        "decision_refiners": _group_payload("decision_refiners", [], "classifier"),
        "monitoring": _group_payload("monitoring", [], "classifier"),
        "optional": _group_payload("optional", [], "classifier"),
    }
    return {
        "state": state,
        "phase": "classifier",
        "source": "clinical_field_router",
        "stage_label": "Clasificador oficial",
        "groups": groups,
        "group_order": [groups[key] for key in GROUP_ORDER],
        "summary": {
            "total_fields": len(fields),
            "saturation_guard": True,
            "max_fields_allowed": GROUP_LIMITS["classifier"]["required"],
            "routing_policy": "official_quick_classifier",
        },
        "audit_note": "Classifier phase uses quick_classify_schema() as authoritative contract",
    }


def _build_progressive_capture(state: str, captured: Mapping[str, Any]) -> dict[str, Any]:
    try:
        from prostanet.presentation.progressive_capture_builder import (
            build_stage_aware_capture,
        )

        return build_stage_aware_capture(state, captured)
    except Exception:
        return {
            "stage_label": state,
            "stage_key": state,
            "disease_state": state,
            "always_visible": [],
            "expandable_groups": [],
            "summary": {"total_fields_available": 0},
        }


def _candidate_groups(
    progressive: Mapping[str, Any],
    state: str,
    phase: str,
) -> dict[str, list[dict[str, Any]]]:
    expandable = {
        group.get("key"): list(group.get("fields") or [])
        for group in progressive.get("expandable_groups", [])
        if isinstance(group, Mapping)
    }
    seeds = _seed_groups(state, phase)
    return {
        "required": [
            *seeds.get("required", []),
            *list(progressive.get("always_visible") or []),
        ],
        "decision_refiners": [
            *seeds.get("decision_refiners", []),
            *expandable.get("decision_refiners", []),
        ],
        "monitoring": [
            *seeds.get("monitoring", []),
            *expandable.get("monitoring", []),
        ],
        "optional": [
            *seeds.get("optional", []),
            *expandable.get("demographics_lifestyle", []),
            *expandable.get("research", []),
        ],
    }


def _filter_fields(
    raw_fields: Iterable[Any],
    *,
    state: str,
    phase: str,
    group_key: str,
    readiness_focus: set[str] | None = None,
) -> list[dict[str, Any]]:
    policy = _policy_for_state(state)
    fields = []
    for raw_field in raw_fields:
        field = _normalize_field(raw_field)
        if not field.get("name"):
            continue
        if readiness_focus and not _field_matches_focus(field, readiness_focus):
            continue
        if _field_allowed(field, policy, state=state, phase=phase, group_key=group_key):
            fields.append(field)
    return _dedupe_fields(fields)


def _readiness_focus_fields(readiness_lane: str | None) -> set[str]:
    if not readiness_lane:
        return set()
    try:
        from prostanet.domains.patient_tracking.clinical_readiness_tower import (
            fields_for_readiness_lane,
        )

        return fields_for_readiness_lane(readiness_lane)
    except Exception:
        return set()


def _field_matches_focus(field: Mapping[str, Any], focus: set[str]) -> bool:
    if not focus:
        return True
    name = str(field.get("name") or "")
    if name in focus:
        return True
    text = _field_search_text(field)
    return any(token.lower() in text for token in focus if token)


def _field_allowed(
    field: Mapping[str, Any],
    policy: Mapping[str, tuple[str, ...]],
    *,
    state: str,
    phase: str,
    group_key: str,
) -> bool:
    if field.get("_router_seeded"):
        return True

    allowlist = _name_allowlist_for_state(state)
    if allowlist is not None and field.get("name") not in allowlist:
        return False

    text = _field_search_text(field)
    if any(token in text for token in policy.get("exclude", ())):
        return False

    include_tokens = policy.get("include", ())
    if include_tokens and not any(token in text for token in include_tokens):
        return False

    if phase == "initial_wizard" and group_key == "monitoring":
        return any(
            token in text
            for token in (
                "imaging", "psa", "testosterone", "ecog", "toxicity",
                "hypertension", "ctcae", "dexa", "dxa", "fall", "bone",
            )
        )
    return True


def _name_allowlist_for_state(state: str) -> set[str] | None:
    if state in STATE_FIELD_ALLOWLISTS:
        return STATE_FIELD_ALLOWLISTS[state]
    if state.startswith("mcspc"):
        return MCSPC_FIELD_ALLOWLIST
    return None


def _policy_for_state(state: str) -> Mapping[str, tuple[str, ...]]:
    if state in POLICIES:
        return POLICIES[state]
    if state.startswith("mcspc"):
        return {
            "include": METASTATIC_INCLUDE_KEYWORDS,
            "exclude": (
                "hrr", "parp", "brca", "ar_v7", "ar-v7", "crpc",
                "castrate", "testosterone", "ctcae", "lutetium", "radium",
                "phoenix", "psa_nadir_post_rt",
            ),
        }
    if "crpc" in state and state.startswith("m1"):
        return POLICIES["m1_crpc"]
    if "crpc" in state:
        return POLICIES["m0_crpc"]
    return {
        "include": (
            "psa", "gleason", "stage", "risk", "ecog", "age", "imaging",
            "biopsy", "histology", "treatment",
        ),
        "exclude": (),
    }


def _policy_name(state: str) -> str:
    if state in POLICIES:
        return state
    if state.startswith("mcspc"):
        return "mcspc_metastatic"
    if "crpc" in state:
        return "crpc_generic"
    return "generic"


def _seed_groups(state: str, phase: str) -> dict[str, list[dict[str, Any]]]:
    groups = {key: [] for key in GROUP_ORDER}
    if state == "recurrence_bcr":
        groups["required"].extend(_fields(
            "psa_value", "psa_doubling_time_months", "prior_prostatectomy",
            "prior_radiation", "time_from_definitive_treatment_months",
        ))
        groups["decision_refiners"].extend(_fields(
            "bcr_detected", "bcr_date", "bcr_psa",
            "prior_radical_prostatectomy_documented",
            "salvage_rt_consideration_active", "psma_pet_staging_recent",
            "psa_nadir_post_rt", "psa_rise_above_nadir_ng_ml",
            "surgical_margins_status", "pathological_t_stage",
        ))
    elif state == "m1_crpc":
        groups["required"].extend(_fields(
            "psa_value", "castrate_testosterone_status", "testosterone_value",
            "current_adt_context", "progression_pattern",
            "conventional_imaging_status", "prior_treatment_lines_count", "metastasis_site",
            "visceral_metastasis_present", "hrr_status",
        ))
        groups["decision_refiners"].extend(_fields(
            "brca1_status", "brca2_status", "atm_status",
            "psma_pet_positive_current", "psma_pet_max_suvmax_lesion",
            "ar_v7_status", "line_of_therapy_number",
            "prior_docetaxel_exposure", "prior_arpi_exposure",
            "psma_negative_dominant_lesions", "hemoglobin",
            "creatinine_clearance", "hepatic_function",
        ))
        if phase == "longitudinal_followup":
            groups["monitoring"].extend(_fields(
                "psa_value", "testosterone_value", "psma_new_lesion_count",
                "ctcae_grade_max", "cytopenia_duration_weeks",
            ))
    elif state == "m0_crpc":
        groups["required"].extend(_fields(
            "psa_value", "psa_doubling_time_months",
            "castrate_testosterone_status", "testosterone_value",
            "conventional_imaging_status", "imaging_modality_used_for_m_staging",
        ))
        groups["decision_refiners"].extend(_fields(
            "no_active_arpi_for_m0_crpc",
            "psadt_progressive_for_arpi_eligibility",
            "arpi_already_initiated_for_m0_crpc",
        ))
        if phase == "longitudinal_followup":
            groups["monitoring"].extend(_fields(
                "arpi_toxicity_review", "arpi_blood_pressure_monitoring",
                "dexa_due", "ctcae_grade_max", "fall_risk_score_high",
                "mobility_decline_longitudinal",
            ))
    elif state == "localized_initial":
        groups["required"].extend(_fields(
            "psa_baseline_ng_ml", "gleason_score", "gleason_primary",
            "gleason_secondary", "clinical_tstage", "nodal_status",
            "metastasis_site", "clinical_risk_group",
            "life_expectancy_years",
        ))
        groups["decision_refiners"].extend(_fields(
            "decision_rp_vs_rt_active",
            "active_surveillance_eligibility_evaluation",
            "svi_risk_nomogram_percent", "has_adverse_tertiary_pattern",
            "intraductal_carcinoma_present",
        ))
    elif state.startswith("mcspc"):
        groups["required"].extend(_fields(
            "psa_value", "metastasis_site", "bone_lesion_count_total",
            "bone_appendicular_count", "visceral_metastasis_present",
            "metachronous_metastasis", "ecog_score",
        ))
        groups["decision_refiners"].extend(_fields(
            "chaarted_volume_classification",
            "latitude_high_risk_criteria_count",
            "nonregional_nodal_count",
            "visceral_site_entries",
        ))
    elif state in {"screening", "diagnostic_workup", "post_negative_biopsy_followup"}:
        groups["required"].extend(_fields(
            "psa", "repeat_psa_value", "dre_suspicious",
            "prior_negative_biopsy", "pirads_score",
        ))
        groups["decision_refiners"].extend(_fields(
            "psad", "phi_value", "fourkscore_value",
            "planned_biopsy_type", "planned_biopsy_route",
        ))
    elif state == "adt_progression_verification":
        groups["required"].extend(_fields(
            "psa_value", "current_adt_context", "testosterone_value",
            "castrate_testosterone_status", "systemic_progression_context",
            "conventional_imaging_status",
        ))

    if phase == "longitudinal_followup":
        groups["monitoring"].extend(_fields(
            "psa_value", "testosterone_value", "ecog_score",
            "imaging_modality_used_for_m_staging", "ctcae_grade_max",
        ))
    groups["optional"].extend(_fields("etnia", "seguridad_social"))
    return groups


def _fields(*names: str) -> list[dict[str, Any]]:
    return [_seed_field(name) for name in names]


SYNTHETIC_FIELDS: dict[str, dict[str, Any]] = {
    "psa_value": {"label": "PSA actual", "field_type": "number", "unit": "ng/mL"},
    "psa": {"label": "PSA actual de sospecha", "field_type": "number", "unit": "ng/mL"},
    "repeat_psa_value": {"label": "PSA repetido", "field_type": "number", "unit": "ng/mL"},
    "psa_baseline_ng_ml": {"label": "PSA basal al diagnostico", "field_type": "number", "unit": "ng/mL"},
    "psa_doubling_time_months": {"label": "PSADT", "field_type": "number", "unit": "meses"},
    "prior_prostatectomy": {"label": "Prostatectomia radical previa", "field_type": "select", "options": ["0", "1"]},
    "prior_radiation": {"label": "Radioterapia primaria previa", "field_type": "select", "options": ["0", "1"]},
    "time_from_definitive_treatment_months": {"label": "Meses desde tratamiento local definitivo", "field_type": "number"},
    "bcr_detected": {"label": "BCR confirmada", "field_type": "select", "options": ["0", "1"]},
    "bcr_date": {"label": "Fecha de BCR", "field_type": "date"},
    "bcr_psa": {"label": "PSA al momento de BCR", "field_type": "number", "unit": "ng/mL"},
    "psa_nadir_post_rt": {"label": "PSA nadir post-RT", "field_type": "number", "unit": "ng/mL"},
    "surgical_margins_status": {"label": "Margenes quirurgicos", "field_type": "select", "options": ["negative", "positive", "unknown"]},
    "pathological_t_stage": {"label": "pT patologico", "field_type": "select", "options": ["pT2", "pT3a", "pT3b", "pT4", "unknown"]},
    "gleason_score": {"label": "Gleason score", "field_type": "number"},
    "gleason_primary": {"label": "Gleason primario", "field_type": "select", "options": ["3", "4", "5"]},
    "gleason_secondary": {"label": "Gleason secundario", "field_type": "select", "options": ["3", "4", "5"]},
    "clinical_tstage": {"label": "cT", "field_type": "select", "options": ["cT1c", "cT2a", "cT2b", "cT2c", "cT3a", "cT3b", "cT4"]},
    "nodal_status": {"label": "cN", "field_type": "select", "options": ["N0", "N1", "Nx"]},
    "metastasis_site": {"label": "cM / sitio metastasico", "field_type": "select", "options": ["M0", "M1a", "M1b", "M1c"]},
    "clinical_risk_group": {"label": "Grupo de riesgo clinico", "field_type": "select"},
    "life_expectancy_years": {"label": "Esperanza de vida estimada", "field_type": "number", "unit": "anos"},
    "castrate_testosterone_status": {"label": "Castracion bioquimica", "field_type": "select", "options": ["unknown", "confirmed_castrate", "not_castrate"]},
    "testosterone_value": {"label": "Testosterona", "field_type": "number", "unit": "ng/dL"},
    "current_adt_context": {"label": "Contexto actual de ADT", "field_type": "select", "options": ["no_adt", "active_adt", "orchiectomy", "unknown"]},
    "progression_pattern": {"label": "Patron de progresion", "field_type": "select", "options": ["psa", "radiographic", "clinical", "mixed", "none"]},
    "conventional_imaging_status": {"label": "Imagen convencional", "field_type": "select", "options": ["M0", "M1", "unknown"]},
    "prior_treatment_lines_count": {"label": "Lineas sistemicas previas", "field_type": "number"},
    "line_of_therapy_number": {"label": "Linea sistemica actual", "field_type": "number"},
    "hrr_status": {"label": "HRR status", "field_type": "select", "options": ["not_tested", "negative", "hrr_positive", "pending"]},
    "psma_pet_positive_current": {"label": "PSMA-PET positivo actual", "field_type": "select", "options": ["0", "1"]},
    "psma_pet_max_suvmax_lesion": {"label": "SUVmax maximo PSMA-PET", "field_type": "number"},
    "psma_negative_dominant_lesions": {"label": "Lesiones dominantes PSMA-negativas", "field_type": "select", "options": ["unknown", "absent", "present"]},
    "hemoglobin": {"label": "Hemoglobina", "field_type": "number", "unit": "g/dL"},
    "creatinine_clearance": {"label": "Depuracion de creatinina", "field_type": "number", "unit": "mL/min"},
    "hepatic_function": {"label": "Funcion hepatica", "field_type": "select", "options": ["normal", "mild_impairment", "moderate_impairment", "severe_impairment", "unknown"]},
    "prior_docetaxel_exposure": {"label": "Exposicion previa a docetaxel", "field_type": "select", "options": ["0", "1"]},
    "prior_arpi_exposure": {"label": "Exposicion previa a ARPI/ARSI", "field_type": "select", "options": ["0", "1"]},
    "conventional_imaging_status": {"label": "Imagen convencional vigente", "field_type": "select", "options": ["NOT_RESTAGED", "M0", "M1"]},
    "imaging_modality_used_for_m_staging": {"label": "Modalidad de imagen para M", "field_type": "select"},
    "current_adt_context": {"label": "Contexto ADT actual", "field_type": "select"},
    "systemic_progression_context": {"label": "Contexto de progresion sistemica", "field_type": "select"},
    "arpi_toxicity_review": {"label": "Revision de toxicidad ARPI", "field_type": "select", "options": ["none", "grade1_2", "grade3_plus"]},
    "arpi_blood_pressure_monitoring": {"label": "Monitoreo PA bajo ARPI", "field_type": "select", "options": ["current", "overdue", "not_applicable"]},
    "dexa_due": {"label": "DEXA / salud osea pendiente", "field_type": "select", "options": ["not_due", "due", "overdue"]},
    "ctcae_grade_max": {"label": "Toxicidad CTCAE maxima", "field_type": "select", "options": ["0", "1", "2", "3", "4", "5"]},
    "bone_lesion_count_total": {"label": "Lesiones oseas totales", "field_type": "number"},
    "bone_appendicular_count": {"label": "Lesiones oseas apendiculares", "field_type": "number"},
    "visceral_metastasis_present": {"label": "Metastasis visceral presente", "field_type": "select", "options": ["0", "1"]},
    "metachronous_metastasis": {"label": "Metastasis metacronica", "field_type": "select", "options": ["0", "1"]},
    "chaarted_volume_classification": {"label": "Volumen CHAARTED", "field_type": "select", "options": ["low_volume", "high_volume", "unknown"]},
    "latitude_high_risk_criteria_count": {"label": "Criterios LATITUDE alto riesgo", "field_type": "number"},
    "nonregional_nodal_count": {"label": "Ganglios no regionales", "field_type": "number"},
    "visceral_site_entries": {"label": "Organos viscerales documentados", "field_type": "structured"},
    "ecog_score": {"label": "ECOG", "field_type": "select", "options": ["0", "1", "2", "3", "4"]},
    "dre_suspicious": {"label": "DRE sospechoso", "field_type": "select", "options": ["0", "1", "unknown"]},
    "prior_negative_biopsy": {"label": "Biopsia previa negativa", "field_type": "select", "options": ["0", "1"]},
    "pirads_score": {"label": "PI-RADS", "field_type": "select", "options": ["0", "2", "3", "4", "5"]},
    "psad": {"label": "Densidad PSA", "field_type": "number"},
    "phi_value": {"label": "PHI", "field_type": "number"},
    "fourkscore_value": {"label": "4Kscore", "field_type": "number"},
    "planned_biopsy_type": {"label": "Tipo de biopsia prevista", "field_type": "select"},
    "planned_biopsy_route": {"label": "Via de biopsia prevista", "field_type": "select"},
    "etnia": {"label": "Etnia / raza", "field_type": "select"},
    "seguridad_social": {"label": "Seguridad social / aseguradora", "field_type": "select"},
}


def _seed_field(name: str) -> dict[str, Any]:
    spec = dict(SYNTHETIC_FIELDS.get(name, {}))
    spec.setdefault("label", name.replace("_", " ").title())
    spec.setdefault("field_type", "text")
    spec.setdefault("type", spec["field_type"])
    spec.setdefault("clinical_role", "decision_refiner")
    spec["name"] = name
    spec["_router_seeded"] = True
    return spec


def _normalize_field(raw_field: Any) -> dict[str, Any]:
    if hasattr(raw_field, "to_dict"):
        try:
            data = dict(raw_field.to_dict())
        except Exception:
            data = {}
    elif isinstance(raw_field, Mapping):
        data = dict(raw_field)
    else:
        data = {
            "name": getattr(raw_field, "name", ""),
            "label": getattr(raw_field, "label", ""),
            "field_type": getattr(raw_field, "field_type", "text"),
            "required": getattr(raw_field, "required", False),
            "options": list(getattr(raw_field, "options", []) or []),
            "clinical_role": getattr(raw_field, "clinical_role", ""),
        }

    field_type = data.get("field_type") or data.get("type") or "text"
    name = str(data.get("name") or "").strip()
    data["name"] = name
    data["field_type"] = field_type
    data["type"] = field_type
    data.setdefault("label", name.replace("_", " ").title())
    data.setdefault("required", False)
    data.setdefault("clinical_role", "optional")
    data["help_text"] = data.get("help_text") or data.get("help") or ""
    return data


def _dedupe_fields(fields: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for field in fields:
        normalized = _normalize_field(field)
        name = normalized["name"]
        if not name or name in seen:
            continue
        seen.add(name)
        deduped.append(normalized)
    return deduped


def _field_search_text(field: Mapping[str, Any]) -> str:
    parts = [
        field.get("name", ""),
        field.get("label", ""),
        field.get("help_text", ""),
        field.get("clinical_role", ""),
        field.get("group", ""),
    ]
    return " ".join(str(part).lower() for part in parts if part is not None)


def _group_payload(group_key: str, fields: list[dict[str, Any]], phase: str) -> dict[str, Any]:
    return {
        "key": group_key,
        "label": GROUP_LABELS[group_key],
        "phase": phase,
        "fields": fields,
        "field_count": len(fields),
    }


def _normalize_state(state: str) -> str:
    value = (state or "diagnostic_workup").strip()
    return STATE_ALIASES.get(value, value)


def _normalize_phase(phase: str) -> str:
    value = (phase or "initial_wizard").strip()
    return value if value in VALID_PHASES else "initial_wizard"
