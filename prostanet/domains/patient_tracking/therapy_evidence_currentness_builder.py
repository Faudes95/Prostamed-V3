from __future__ import annotations

from typing import Any

from prostanet.shared.clinical_fact_policies import compute_freshness_status
from prostanet.shared.ui_value_normalizer import normalize_field_label


MHSPC_STATES = {
    "mcspc_oligo_metachronous",
    "mcspc_low_volume_sync_oligo",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "mcspc_high_volume",
}

ADVANCED_CURRENTNESS_STATES = {
    "m0_crpc",
    "m1_crpc",
} | MHSPC_STATES

_MISSING_SENTINELS = {
    "",
    "none",
    "null",
    "nan",
    "n/a",
    "unknown",
    "desconocido",
    "desconocida",
    "no documentado",
    "no documentada",
    "no aplica",
    "not_restaged",
}

_FIELD_ALIASES = {
    "testosterone": ["testosterone_value"],
    "castrate_testosterone_status": ["castrate_status_resolved"],
    "ddi_review_status": ["drug_interaction_reviewed"],
    "molecular_report_date": ["molecular_assay_date"],
    "psma_study_date": ["psma_pet_date"],
}

_FIELD_DATE_FIELDS = {
    "testosterone": ["latest_testosterone_date", "testosterone_date", "visit_date"],
    "castrate_testosterone_status": ["latest_testosterone_date", "testosterone_date", "visit_date"],
    "current_adt_context": ["visit_date", "latest_testosterone_date"],
    "conventional_imaging_status": ["conventional_imaging_date", "restaging_imaging_date"],
    "conventional_imaging_date": ["conventional_imaging_date", "restaging_imaging_date"],
    "progression_pattern": ["conventional_imaging_date", "restaging_imaging_date"],
    "ecog_score": ["ecog_date", "visit_date"],
    "g8_score": ["g8_date", "visit_date"],
    "mini_cog_score": ["mini_cog_date", "visit_date"],
    "current_medications": ["visit_date"],
    "ddi_review_status": ["ddi_review_date", "visit_date"],
    "cv_risk_documented": ["cv_risk_date", "visit_date"],
    "hemoglobin": ["cbc_date", "visit_date"],
    "creatinine": ["renal_function_date", "chemistry_panel_date", "visit_date"],
    "potassium": ["chemistry_panel_date", "visit_date"],
    "hrr_status": ["molecular_report_date", "molecular_assay_date"],
    "hrr_gene": ["molecular_report_date", "molecular_assay_date"],
    "biomarker_source": ["molecular_report_date", "molecular_assay_date"],
    "molecular_report_date": ["molecular_report_date", "molecular_assay_date"],
    "psma_study_date": ["psma_study_date", "psma_pet_date"],
    "psma_positive": ["psma_study_date", "psma_pet_date"],
    "psma_negative_dominant_lesions": ["psma_study_date", "psma_pet_date"],
}

_POLICY_KEY_BY_FIELD = {
    "castrate_testosterone_status": "testosterone",
    "conventional_imaging_status": "conventional_imaging_date",
    "progression_pattern": "conventional_imaging_date",
    "hrr_status": "molecular_report_date",
    "hrr_gene": "molecular_report_date",
    "biomarker_source": "molecular_report_date",
    "psma_positive": "psma_study_date",
    "psma_negative_dominant_lesions": "psma_study_date",
}

_TRACEABILITY_FIELDS = {"hrr_status", "hrr_gene", "biomarker_source", "molecular_report_date"}
_BOOLEAN_FALSE_VALUES = {"0", "false", "no"}

_STATUS_RANK = {
    "current": 0,
    "aging": 1,
    "unknown": 2,
    "stale": 3,
}

_THERAPY_FIELD_RULES = {
    "m0_crpc": {
        "default": [
            "testosterone",
            "castrate_testosterone_status",
            "current_adt_context",
            "conventional_imaging_status",
            "conventional_imaging_date",
            "progression_pattern",
        ]
    },
    "mhspc": {
        "arpi_family": [
            "ecog_score",
            "g8_score",
            "mini_cog_score",
            "current_medications",
            "ddi_review_status",
            "cv_risk_documented",
            "testosterone",
            "castrate_testosterone_status",
        ],
        "abiraterone_steroid_family": [
            "ecog_score",
            "g8_score",
            "mini_cog_score",
            "current_medications",
            "ddi_review_status",
            "cv_risk_documented",
            "potassium",
            "testosterone",
            "castrate_testosterone_status",
        ],
        "taxane_family": [
            "ecog_score",
            "g8_score",
            "mini_cog_score",
            "hemoglobin",
            "creatinine",
            "potassium",
            "testosterone",
            "castrate_testosterone_status",
        ],
        "default": [
            "ecog_score",
            "g8_score",
            "mini_cog_score",
            "testosterone",
            "castrate_testosterone_status",
        ],
    },
    "m1_crpc": {
        "parp_family": [
            "testosterone",
            "castrate_testosterone_status",
            "current_adt_context",
            "hrr_status",
            "hrr_gene",
            "biomarker_source",
            "molecular_report_date",
        ],
        "psma_rlt_family": [
            "testosterone",
            "castrate_testosterone_status",
            "current_adt_context",
            "psma_study_date",
            "psma_positive",
            "psma_negative_dominant_lesions",
            "conventional_imaging_status",
            "conventional_imaging_date",
        ],
        "taxane_family": [
            "testosterone",
            "castrate_testosterone_status",
            "current_adt_context",
            "ecog_score",
            "g8_score",
            "mini_cog_score",
            "hemoglobin",
            "creatinine",
            "potassium",
        ],
        "arpi_family": [
            "testosterone",
            "castrate_testosterone_status",
            "current_adt_context",
            "ecog_score",
            "g8_score",
            "mini_cog_score",
            "current_medications",
            "ddi_review_status",
            "cv_risk_documented",
        ],
        "abiraterone_steroid_family": [
            "testosterone",
            "castrate_testosterone_status",
            "current_adt_context",
            "current_medications",
            "ddi_review_status",
            "cv_risk_documented",
            "potassium",
        ],
        "default": [
            "testosterone",
            "castrate_testosterone_status",
            "current_adt_context",
        ],
    },
}

_REFRESH_ACTIONS = {
    ("m0_crpc", "default"): "Actualizar reestadificación convencional y confirmar castración actual",
    ("mhspc", "taxane_family"): "Actualizar fitness, fragilidad y laboratorios antes de sostener intensificación con docetaxel",
    ("mhspc", "arpi_family"): "Actualizar fragilidad, medicación activa y riesgo cardiovascular antes de sostener intensificación",
    ("mhspc", "abiraterone_steroid_family"): "Actualizar riesgo cardiovascular, potasio y revisión de medicación antes de sostener intensificación",
    ("mhspc", "default"): "Actualizar fitness y bundle de soporte antes de sostener intensificación",
    ("m1_crpc", "parp_family"): "Actualizar trazabilidad molecular HRR antes de liberar PARP",
    ("m1_crpc", "psma_rlt_family"): "Actualizar PSMA estructurado y correlación anatómica antes de liberar PSMA-RLT",
    ("m1_crpc", "taxane_family"): "Actualizar castración actual, fitness y laboratorios antes de liberar taxano",
    ("m1_crpc", "arpi_family"): "Actualizar castración actual y bundle de seguridad ARPI antes de liberar terapia",
    ("m1_crpc", "abiraterone_steroid_family"): "Actualizar riesgo cardiovascular, potasio y bundle de seguridad antes de liberar abiraterona",
    ("m1_crpc", "default"): "Actualizar evidencia clínica decisiva antes de liberar la siguiente terapia",
}


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _dedupe(values: list[Any]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _normalize_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _is_present(value: Any) -> bool:
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return True
    return _normalize_text(value).lower() not in _MISSING_SENTINELS


def _is_traceable(value: Any) -> bool:
    return _is_present(value) and _normalize_text(value).lower() not in {"desconocido", "desconocida", "unknown"}


def _field_label(field_name: str) -> str:
    return normalize_field_label(field_name, default=field_name)


def _facts_index(clinical_fact_bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("fact_key") or "").strip(): dict(item)
        for item in list(clinical_fact_bundle.get("facts") or [])
        if isinstance(item, dict) and str(item.get("fact_key") or "").strip()
    }


def _merged_field_values(
    *,
    clinical_fact_bundle: dict[str, Any],
    signals: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(clinical_fact_bundle.get("field_values") or {})
    for key, value in dict(signals or {}).items():
        if value not in (None, "", [], {}):
            merged[key] = value
    return merged


def _lookup_value(
    field_name: str,
    *,
    field_values: dict[str, Any],
    facts_index: dict[str, dict[str, Any]],
) -> tuple[Any, str]:
    candidates = [field_name, *_FIELD_ALIASES.get(field_name, [])]
    for candidate in candidates:
        if candidate in field_values and field_values.get(candidate) not in (None, "", [], {}):
            return field_values.get(candidate), candidate
    for candidate in candidates:
        fact = dict(facts_index.get(candidate) or {})
        if fact:
            return fact.get("resolved_value"), candidate
    return None, field_name


def _lookup_date(
    field_name: str,
    *,
    field_values: dict[str, Any],
    facts_index: dict[str, dict[str, Any]],
) -> tuple[str, str]:
    for candidate in _FIELD_DATE_FIELDS.get(field_name, []):
        value, _ = _lookup_value(candidate, field_values=field_values, facts_index=facts_index)
        if _is_present(value):
            return _normalize_text(value), candidate
    fact = dict(facts_index.get(field_name) or {})
    if fact and _is_present(fact.get("source_date")):
        return _normalize_text(fact.get("source_date")), "source_date"
    return "", ""


def _state_group(state: str) -> str:
    return "mhspc" if state in MHSPC_STATES else state


def _fields_for_therapy(state: str, family_code: str) -> list[str]:
    group = _THERAPY_FIELD_RULES.get(_state_group(state), {})
    return list(group.get(family_code) or group.get("default") or [])


def _refresh_action_for_therapy(state: str, family_code: str) -> str:
    state_group = _state_group(state)
    return _normalize_text(
        _REFRESH_ACTIONS.get((state_group, family_code))
        or _REFRESH_ACTIONS.get((state_group, "default"))
    )


def _evaluate_field(
    field_name: str,
    *,
    field_values: dict[str, Any],
    facts_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    value, _ = _lookup_value(field_name, field_values=field_values, facts_index=facts_index)
    if not _is_present(value):
        return {
            "field": field_name,
            "label": _field_label(field_name),
            "status": "missing",
            "blocking": True,
            "traceability_gap": field_name in _TRACEABILITY_FIELDS,
            "date_used": "",
        }

    if field_name in _TRACEABILITY_FIELDS and not _is_traceable(value):
        return {
            "field": field_name,
            "label": _field_label(field_name),
            "status": "untraceable",
            "blocking": True,
            "traceability_gap": True,
            "date_used": "",
        }

    policy_key = _POLICY_KEY_BY_FIELD.get(field_name, field_name)
    date_value, _ = _lookup_date(field_name, field_values=field_values, facts_index=facts_index)
    if date_value:
        freshness_status, freshness_expires_at = compute_freshness_status(policy_key, source_date=date_value)
        return {
            "field": field_name,
            "label": _field_label(field_name),
            "status": freshness_status,
            "blocking": freshness_status == "stale",
            "traceability_gap": False,
            "date_used": date_value,
            "freshness_expires_at": freshness_expires_at,
        }

    fact = dict(facts_index.get(field_name) or {})
    fact_status = _normalize_text(fact.get("freshness_status")).lower()
    if fact_status in {"current", "aging", "stale"}:
        return {
            "field": field_name,
            "label": _field_label(field_name),
            "status": fact_status,
            "blocking": fact_status == "stale",
            "traceability_gap": False,
            "date_used": _normalize_text(fact.get("source_date") or fact.get("observed_at")),
            "freshness_expires_at": fact.get("freshness_expires_at"),
        }

    return {
        "field": field_name,
        "label": _field_label(field_name),
        "status": "unknown",
        "blocking": False,
        "traceability_gap": False,
        "date_used": "",
    }


def _overall_evidence_status(field_statuses: list[dict[str, Any]]) -> tuple[str, str]:
    statuses = [str(item.get("status") or "") for item in field_statuses]
    if any(status in {"missing", "untraceable", "stale"} for status in statuses):
        return "stale", "blocked_by_stale_evidence"
    if "aging" in statuses:
        return "aging", "aging_review_needed"
    if "current" in statuses:
        return "current", "ready_to_release"
    return "unknown", "ready_to_release"


def _merge_release_status(base_status: str, evidence_release_status: str) -> str:
    base_status = _normalize_text(base_status) or "ready_to_release"
    if evidence_release_status == "blocked_by_stale_evidence":
        return "blocked_by_stale_evidence"
    if evidence_release_status == "aging_review_needed" and base_status in {
        "ready_to_release",
        "conditional_pending_closure",
    }:
        return "aging_review_needed"
    return base_status


def _family_evidence_status(items: list[dict[str, Any]]) -> str:
    if not items:
        return "unknown"
    return max(
        (str(item.get("evidence_status") or "unknown") for item in items),
        key=lambda value: _STATUS_RANK.get(value, 2),
    )


def build_therapy_evidence_currentness_bundle(
    *,
    state: str,
    clinical_fact_bundle: dict[str, Any] | None = None,
    therapeutic_readiness_bundle: dict[str, Any] | None = None,
    comparative_eligibility_matrix: dict[str, Any] | None = None,
    staging_adjudication_bundle: dict[str, Any] | None = None,
    signals: dict[str, Any] | None = None,
    decision_input_requirements: dict[str, Any] | None = None,
) -> dict[str, Any]:
    clinical_fact_bundle = dict(clinical_fact_bundle or {})
    therapeutic_readiness_bundle = dict(therapeutic_readiness_bundle or {})
    staging_adjudication_bundle = dict(staging_adjudication_bundle or {})
    signals = dict(signals or {})
    decision_input_requirements = dict(decision_input_requirements or {})
    comparative_eligibility_matrix = dict(comparative_eligibility_matrix or {})

    if state not in ADVANCED_CURRENTNESS_STATES:
        return {
            "available": False,
            "selected_therapy_evidence_status": "unknown",
            "selected_therapy_release_status": therapeutic_readiness_bundle.get("readiness_status") or "",
            "evidence_currentness_by_therapy": {},
            "evidence_currentness_by_family": {},
            "refresh_actions": [],
            "evidence_dates_used": [],
            "traceability_gaps": [],
            "stale_evidence_fields": [],
            "aging_evidence_fields": [],
            "release_blocked_by_stale_evidence": False,
            "therapy_rationale_entries": list(therapeutic_readiness_bundle.get("therapy_rationale_entries") or []),
            "release_status_by_therapy": dict(therapeutic_readiness_bundle.get("release_status_by_therapy") or {}),
        }

    entries = [
        dict(item)
        for item in list(therapeutic_readiness_bundle.get("therapy_rationale_entries") or [])
        if isinstance(item, dict)
    ]
    facts_index = _facts_index(clinical_fact_bundle)
    field_values = _merged_field_values(clinical_fact_bundle=clinical_fact_bundle, signals=signals)
    if staging_adjudication_bundle.get("restaging_currentness_status") not in (None, ""):
        field_values.setdefault(
            "conventional_imaging_status",
            signals.get("conventional_imaging_status") or field_values.get("conventional_imaging_status"),
        )

    enriched_entries: list[dict[str, Any]] = []
    evidence_currentness_by_therapy: dict[str, dict[str, Any]] = {}
    release_status_by_therapy = dict(therapeutic_readiness_bundle.get("release_status_by_therapy") or {})
    refreshed_actions: list[str] = []

    for entry in entries:
        therapy_key = _normalize_text(entry.get("therapy_key"))
        family_code = _normalize_text(entry.get("family_code"))
        evidence_fields = _fields_for_therapy(state, family_code)
        field_statuses = [
            _evaluate_field(field_name, field_values=field_values, facts_index=facts_index)
            for field_name in evidence_fields
        ]
        evidence_status, evidence_release_status = _overall_evidence_status(field_statuses)
        traceability_gaps = [
            item["label"]
            for item in field_statuses
            if bool(item.get("traceability_gap"))
        ]
        stale_fields = [
            item["label"]
            for item in field_statuses
            if str(item.get("status") or "") in {"stale", "missing", "untraceable"}
        ]
        aging_fields = [
            item["label"]
            for item in field_statuses
            if str(item.get("status") or "") == "aging"
        ]
        evidence_dates_used = [
            {
                "field": item["field"],
                "label": item["label"],
                "date": item["date_used"],
            }
            for item in field_statuses
            if _normalize_text(item.get("date_used"))
        ]
        refresh_action = ""
        if evidence_release_status != "ready_to_release" or aging_fields:
            refresh_action = _refresh_action_for_therapy(state, family_code)
            if refresh_action:
                refreshed_actions.append(refresh_action)

        merged_release_status = _merge_release_status(
            _normalize_text(entry.get("release_status")),
            evidence_release_status,
        )

        enriched = {
            **entry,
            "evidence_status": evidence_status,
            "release_status": merged_release_status,
            "release_blocked_by_stale_evidence": merged_release_status == "blocked_by_stale_evidence",
            "refresh_action_needed": refresh_action,
            "evidence_dates_used": evidence_dates_used,
            "traceability_gaps": traceability_gaps,
            "stale_evidence_fields": stale_fields,
            "aging_evidence_fields": aging_fields,
        }
        enriched_entries.append(enriched)
        evidence_currentness_by_therapy[therapy_key] = {
            "therapy_label": enriched.get("therapy_label"),
            "family_code": family_code,
            "evidence_status": evidence_status,
            "release_status": merged_release_status,
            "refresh_action_needed": refresh_action,
            "evidence_dates_used": evidence_dates_used,
            "traceability_gaps": traceability_gaps,
            "stale_evidence_fields": stale_fields,
            "aging_evidence_fields": aging_fields,
        }
        release_status_by_therapy.setdefault(therapy_key, {})
        release_status_by_therapy[therapy_key] = {
            **dict(release_status_by_therapy.get(therapy_key) or {}),
            "therapy_label": enriched.get("therapy_label"),
            "family_code": family_code,
            "release_status": merged_release_status,
            "eligibility_status": enriched.get("eligibility_status"),
            "decision_role": enriched.get("decision_role"),
            "evidence_status": evidence_status,
            "release_blocked_by_stale_evidence": merged_release_status == "blocked_by_stale_evidence",
            "refresh_action_needed": refresh_action,
            "evidence_dates_used": evidence_dates_used,
            "traceability_gaps": traceability_gaps,
        }

    selected_entry = next((item for item in enriched_entries if item.get("decision_role") == "selected"), {})
    selected_key = _normalize_text(selected_entry.get("therapy_key"))
    selected_snapshot = dict(evidence_currentness_by_therapy.get(selected_key) or {})

    evidence_currentness_by_family: dict[str, dict[str, Any]] = {}
    grouped_by_family: dict[str, list[dict[str, Any]]] = {}
    for item in enriched_entries:
        grouped_by_family.setdefault(_normalize_text(item.get("family_code")), []).append(item)
    for family_code, family_items in grouped_by_family.items():
        evidence_currentness_by_family[family_code] = {
            "family_code": family_code,
            "evidence_status": _family_evidence_status(family_items),
            "therapy_keys": [_normalize_text(item.get("therapy_key")) for item in family_items if _normalize_text(item.get("therapy_key"))],
        }

    return {
        "available": bool(enriched_entries),
        "selected_therapy_evidence_status": _normalize_text(selected_snapshot.get("evidence_status")) or "unknown",
        "selected_therapy_release_status": _normalize_text(selected_snapshot.get("release_status"))
        or _normalize_text(therapeutic_readiness_bundle.get("readiness_status")),
        "evidence_currentness_by_therapy": evidence_currentness_by_therapy,
        "evidence_currentness_by_family": evidence_currentness_by_family,
        "refresh_actions": _dedupe(refreshed_actions),
        "evidence_dates_used": list(selected_snapshot.get("evidence_dates_used") or []),
        "traceability_gaps": list(selected_snapshot.get("traceability_gaps") or []),
        "stale_evidence_fields": list(selected_snapshot.get("stale_evidence_fields") or []),
        "aging_evidence_fields": list(selected_snapshot.get("aging_evidence_fields") or []),
        "release_blocked_by_stale_evidence": bool(selected_snapshot.get("release_status") == "blocked_by_stale_evidence"),
        "therapy_rationale_entries": enriched_entries,
        "release_status_by_therapy": release_status_by_therapy,
        "advanced_release_gate_snapshot": {
            "release_gate_reasons": list(staging_adjudication_bundle.get("release_gate_reasons") or []),
            "decision_blocking_inputs": list(decision_input_requirements.get("decision_blocking_inputs") or []),
        },
    }


__all__ = ["build_therapy_evidence_currentness_bundle"]
