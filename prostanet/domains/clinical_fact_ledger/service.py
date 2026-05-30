from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from datetime import date
from typing import Any

from prostanet.shared.clinical_fact_policies import compute_freshness_status
from prostanet.shared.clinical_fact_registry import (
    FACT_SPECS,
    FactSpec,
    build_legacy_shadow_payload,
    extract_canonical_fact_candidates,
    iter_registered_fact_specs,
)


_MISSING_TEXT = {
    "",
    "no disponible",
    "no documentado",
    "no documentada",
    "desconocido",
    "desconocida",
    "no aplica",
    "na",
    "n/a",
    "none",
    "null",
}

_SOURCE_PRIORITY = {
    "patient_clinical_facts_verified": 100,
    "patient_clinical_facts": 90,
    "biomarker_longitudinal": 85,
    "verified_document_facts": 82,
    "clinical_baseline": 80,
    "patient_demographics": 76,
    "latest_assessment_input": 72,
    "legacy_shadow_payload": 40,
}

_SUMMARY_FACT_KEYS = (
    "baseline_psa",
    "current_psa",
    "psa_density",
    "prostate_volume_ml",
    "dre_suspicious",
    "pirads_score",
    "gleason_primary",
    "gleason_secondary",
    "isup_grade",
    "total_cores_biopsied",
    "ecog_score",
    "metastatic_stage_resolved",
    "castrate_testosterone_status",
    "testosterone",
    "hrr_status",
    "msi_status",
    "psma_pet_done",
    "psma_positive",
)


_PROFILE_V2_CAPTURE_GATES = {
    "castration_quick_capture": {
        "label": "Castration/Testosterona",
        "cta_context_key": "castration_capture_cta",
        "required_fact_keys": ("castrate_testosterone_status",),
        "support_fact_keys": ("testosterone",),
        "context_flags": ("needs_castration_check",),
        "pending_values": ("pending", "not_assessed", "not assessed", "no evaluado"),
    },
    "psma_pet_quick_capture": {
        "label": "PSMA-PET",
        "cta_context_key": "psma_pet_capture_cta",
        "required_fact_keys": ("psma_pet_status", "psma_pet_done", "psma_positive"),
        "support_fact_keys": ("psma_study_date",),
        "context_flags": ("state_psma_eligible", "psa_signal"),
        "pending_values": ("pending", "not_performed", "not performed", "no realizado"),
    },
    "hrr_quick_capture": {
        "label": "HRR/Germline",
        "cta_context_key": "hrr_capture_cta",
        "required_fact_keys": ("hrr_status",),
        "support_fact_keys": ("hrr_gene",),
        "context_flags": ("state_is_advanced", "arpi_active"),
        "pending_values": ("pending", "not_tested", "not tested", "no realizado"),
    },
    "ecog_quick_capture": {
        "label": "ECOG",
        "cta_context_key": "ecog_capture_cta",
        "required_fact_keys": ("ecog_score",),
        "support_fact_keys": (),
        "context_flags": ("arpi_active",),
        "pending_values": (),
    },
}


_LONGITUDINAL_CAPTURE_FORMS = {
    "psa": {
        "label": "APE/PSA longitudinal",
        "section_id": "section-psa_new",
        "policy": "append_series",
        "fact_keys": ("baseline_psa", "current_psa", "psa_current_date"),
        "field_map": {
            "psa_date": "psa_current_date",
            "psa_value": "current_psa",
        },
        "decision_fields": ("psa", "ape", "baseline_psa", "current_psa", "psa_history"),
        "readiness_lanes": ("diagnostic_biopsy_readiness", "bcr_salvage_readiness", "mhspc_precision_readiness", "m1crpc_sequence_readiness"),
    },
    "testosterone": {
        "label": "Testosterona/castracion",
        "section_id": "section-testosterone_history",
        "policy": "refreshable_scalar",
        "fact_keys": ("testosterone", "testosterone_sample_date", "castrate_testosterone_status"),
        "field_map": {
            "date": "testosterone_sample_date",
            "value": "testosterone",
        },
        "decision_fields": ("testosterone", "testosterone_current", "castrate_testosterone_status", "castration_status"),
        "readiness_lanes": ("crpc_confirmation_readiness", "m0crpc_arpi_readiness", "m1crpc_sequence_readiness", "adt_arpi_safety_readiness"),
    },
    "ecog": {
        "label": "ECOG longitudinal",
        "section_id": "section-ecog",
        "policy": "visit_scalar",
        "fact_keys": ("ecog_score",),
        "field_map": {
            "score": "ecog_score",
        },
        "decision_fields": ("ecog", "ecog_score", "actual_ecog"),
        "readiness_lanes": ("adt_arpi_safety_readiness", "supportive_palliative_readiness"),
    },
    "biopsy": {
        "label": "Reporte histopatologico",
        "section_id": "section-biopsy_capture",
        "policy": "event_report",
        "fact_keys": (
            "biopsy_date",
            "gleason_primary",
            "gleason_secondary",
            "isup_grade",
            "total_cores_biopsied",
            "num_cores_positive",
            "percent_pattern_4",
            "perineural_invasion",
            "margin_status",
        ),
        "field_map": {
            "biopsy_date": "biopsy_date",
            "gleason_primary": "gleason_primary",
            "gleason_secondary": "gleason_secondary",
            "isup_grade": "isup_grade",
            "total_cores": "total_cores_biopsied",
            "positive_cores": "num_cores_positive",
            "percent_pattern_4": "percent_pattern_4",
            "perineural_invasion": "perineural_invasion",
            "margin_status": "margin_status",
        },
        "decision_fields": ("biopsy", "biopsy_report", "histopathology", "gleason_primary", "isup_grade", "total_cores", "positive_cores"),
        "readiness_lanes": ("diagnostic_biopsy_readiness", "active_surveillance_readiness", "localized_treatment_readiness"),
    },
    "mri_pirads": {
        "label": "MRI/PI-RADS",
        "section_id": "section-mri_pirads",
        "policy": "event_report",
        "fact_keys": ("pirads_score", "mri_fact_date", "mpmri_done", "mpmri_localized_recurrence"),
        "field_map": {
            "date": "mri_fact_date",
            "mri_modality": "mpmri_done",
            "pirads_score": "pirads_score",
            "extracapsular_extension_suspicion": "clinical_tstage",
            "seminal_vesicle_invasion_suspicion": "clinical_tstage",
        },
        "decision_fields": ("pirads_score", "mri_pirads", "mri", "mpmri", "prior_mpmri_pirads_score"),
        "readiness_lanes": ("diagnostic_biopsy_readiness", "active_surveillance_readiness", "localized_treatment_readiness"),
    },
    "psma_pet": {
        "label": "PSMA-PET",
        "section_id": "section-psma_pet",
        "policy": "event_report",
        "fact_keys": ("psma_pet_status", "psma_pet_done", "psma_positive", "psma_study_date", "psma_tracer", "psma_lesion_count", "psma_index_lesion_suvmax"),
        "field_map": {
            "date": "psma_study_date",
            "tracer": "psma_tracer",
            "psma_suvmax": "psma_index_lesion_suvmax",
            "lesion_count": "psma_lesion_count",
            "distribution": "psma_pet_status",
        },
        "decision_fields": ("psma_pet", "psma_pet_done", "psma_positive", "psma_study_date"),
        "readiness_lanes": ("bcr_salvage_readiness", "m1crpc_sequence_readiness", "psma_rlt_readiness"),
    },
    "hrr_germinal": {
        "label": "HRR germinal",
        "section_id": "section-hrr_germinal",
        "policy": "nonexpiring_precision",
        "fact_keys": ("hrr_status", "hrr_gene", "germline_testing_performed", "germline_pathogenic_variant", "germline_test_date"),
        "field_map": {
            "date": "germline_test_date",
            "germline_testing_done": "germline_testing_performed",
            "germline_pathogenic_variant": "germline_pathogenic_variant",
        },
        "decision_fields": ("hrr_status", "hrr_gene", "germline_testing", "germline_pathogenic_variant"),
        "readiness_lanes": ("parp_hrr_readiness", "m1crpc_sequence_readiness"),
    },
    "hrr_somatic": {
        "label": "HRR somatico",
        "section_id": "section-hrr_somatic",
        "policy": "precision_report",
        "fact_keys": ("somatic_testing_performed", "somatic_pathogenic_variant", "biomarker_source", "molecular_report_date"),
        "field_map": {
            "date": "molecular_report_date",
            "somatic_testing_done": "somatic_testing_performed",
            "biomarker_source": "biomarker_source",
            "somatic_pathogenic_variant": "somatic_pathogenic_variant",
        },
        "decision_fields": ("somatic_testing", "somatic_pathogenic_variant", "biomarker_source", "molecular_report_date"),
        "readiness_lanes": ("parp_hrr_readiness", "m1crpc_sequence_readiness"),
    },
    "visceral_mets": {
        "label": "Contexto metastasico visceral",
        "section_id": "section-visceral_mets",
        "policy": "event_report",
        "fact_keys": ("visceral_liver", "visceral_lung", "visceral_adrenal", "visceral_cns", "metastatic_stage_resolved", "metastasis_assessment_date"),
        "field_map": {
            "date": "metastasis_assessment_date",
            "liver_metastasis": "visceral_liver",
            "lung_metastasis": "visceral_lung",
            "adrenal_metastasis": "visceral_adrenal",
            "brain_metastasis": "visceral_cns",
        },
        "decision_fields": ("volume_disease", "metastasis_site", "metastatic_context", "visceral_mets"),
        "readiness_lanes": ("mhspc_precision_readiness", "m1crpc_sequence_readiness"),
    },
}


def _is_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in _MISSING_TEXT
    if value in ([], {}):
        return False
    return True


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (date,)):
        return value.isoformat()
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def _normalized_compare_value(value: Any) -> str:
    value = _jsonable(value)
    if isinstance(value, bool):
        return f"bool:{int(value)}"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and math.isnan(value):
            return "missing:nan"
        return f"num:{float(value):.10g}"
    if isinstance(value, (dict, list)):
        return "json:" + json.dumps(value, ensure_ascii=False, sort_keys=True)
    text = str(value or "").strip()
    lowered = text.lower()
    if lowered in {"true", "yes", "si", "sí", "1"}:
        return "bool:1"
    if lowered in {"false", "no", "0"}:
        return "bool:0"
    try:
        return f"num:{float(text):.10g}"
    except (TypeError, ValueError):
        return "str:" + lowered


def _alias_map() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for spec in iter_registered_fact_specs():
        aliases[spec.fact_key] = spec.fact_key
        for alias in spec.legacy_aliases:
            aliases[str(alias)] = spec.fact_key
    return aliases


def _observed_key_for_payload(payload: dict[str, Any], spec: FactSpec) -> str:
    for key in (spec.fact_key, *spec.legacy_aliases):
        if _is_present(payload.get(key)):
            return key
    return spec.fact_key


def _source_priority(source: dict[str, Any]) -> int:
    source_type = str(source.get("source_type") or "")
    if source_type == "patient_clinical_facts" and source.get("clinician_verified"):
        return _SOURCE_PRIORITY["patient_clinical_facts_verified"]
    return _SOURCE_PRIORITY.get(source_type, 10)


def _source_sort_key(source: dict[str, Any]) -> tuple[int, str, int]:
    source_date = str(source.get("source_date") or source.get("observed_at") or "")
    try:
        record_id = int(source.get("source_record_id") or 0)
    except (TypeError, ValueError):
        record_id = 0
    return (_source_priority(source), source_date, record_id)


def _append_source(
    sources_by_fact: dict[str, list[dict[str, Any]]],
    *,
    fact_key: str,
    observed_key: str | None,
    value: Any,
    source_type: str,
    source_record_type: str,
    source_record_id: Any = None,
    source_date: Any = "",
    observed_at: Any = "",
    certainty_tier: str = "",
    clinician_verified: bool = False,
    freshness_status: str | None = None,
    freshness_expires_at: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    canonical_key = _alias_map().get(str(fact_key or ""), str(fact_key or ""))
    spec = FACT_SPECS.get(canonical_key)
    if not spec or not _is_present(value):
        return
    computed_freshness, computed_expires = compute_freshness_status(
        canonical_key,
        source_date=source_date,
        observed_at=observed_at,
    )
    source = {
        "fact_key": canonical_key,
        "observed_key": observed_key or canonical_key,
        "value": _jsonable(value),
        "normalized_value": _normalized_compare_value(value),
        "source_type": source_type,
        "source_record_type": source_record_type,
        "source_record_id": source_record_id,
        "source_date": str(source_date or ""),
        "observed_at": str(observed_at or ""),
        "certainty_tier": certainty_tier or "",
        "freshness_status": freshness_status or computed_freshness,
        "freshness_expires_at": freshness_expires_at or computed_expires,
        "clinician_verified": bool(clinician_verified),
        "metadata": metadata or {},
    }
    sources_by_fact[canonical_key].append(source)


def _append_sources_from_payload(
    sources_by_fact: dict[str, list[dict[str, Any]]],
    payload: dict[str, Any],
    *,
    source_type: str,
    source_record_type: str,
    source_record_id: Any = None,
    source_date: Any = "",
    observed_at: Any = "",
    certainty_tier: str = "structured_payload",
    clinician_verified: bool = False,
) -> None:
    if not payload:
        return
    candidates = extract_canonical_fact_candidates(
        payload,
        source_type=source_type,
        source_record_type=source_record_type,
        source_record_id=source_record_id,
        source_date=str(source_date or ""),
        observed_at=str(observed_at or source_date or ""),
        certainty_tier=certainty_tier,
        clinician_verified=clinician_verified,
    )
    for candidate in candidates:
        spec = FACT_SPECS.get(candidate.get("fact_key"))
        if not spec:
            continue
        _append_source(
            sources_by_fact,
            fact_key=spec.fact_key,
            observed_key=_observed_key_for_payload(payload, spec),
            value=candidate.get("value"),
            source_type=source_type,
            source_record_type=source_record_type,
            source_record_id=source_record_id,
            source_date=candidate.get("source_date") or source_date,
            observed_at=candidate.get("observed_at") or observed_at,
            certainty_tier=candidate.get("certainty_tier") or certainty_tier,
            clinician_verified=bool(candidate.get("clinician_verified") or clinician_verified),
            freshness_status=candidate.get("freshness_status"),
            freshness_expires_at=candidate.get("freshness_expires_at"),
        )


def _append_patient_clinical_facts(
    sources_by_fact: dict[str, list[dict[str, Any]]],
    rows: list[dict[str, Any]],
) -> int:
    inactive_count = 0
    aliases = _alias_map()
    for row in rows or []:
        if not bool(row.get("is_active", True)):
            inactive_count += 1
            continue
        observed_key = str(row.get("fact_key") or "")
        canonical_key = aliases.get(observed_key, observed_key)
        value = row.get("value")
        if not _is_present(value):
            value = row.get("normalized_value_text")
        _append_source(
            sources_by_fact,
            fact_key=canonical_key,
            observed_key=observed_key,
            value=value,
            source_type="patient_clinical_facts",
            source_record_type=str(row.get("source_record_type") or "patient_clinical_facts"),
            source_record_id=row.get("source_record_id") or row.get("id"),
            source_date=row.get("source_date") or "",
            observed_at=row.get("observed_at") or row.get("updated_at") or row.get("created_at") or "",
            certainty_tier=str(row.get("certainty_tier") or ""),
            clinician_verified=bool(row.get("clinician_verified")),
            freshness_status=row.get("freshness_status"),
            freshness_expires_at=row.get("freshness_expires_at"),
            metadata={"row_id": row.get("id"), "state_context": row.get("state_context")},
        )
    return inactive_count


def _append_biomarker_sources(
    sources_by_fact: dict[str, list[dict[str, Any]]],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    psa_rows = [
        row for row in rows or []
        if str(row.get("biomarker_type") or "").strip().upper() == "PSA"
        and _is_present(row.get("value"))
        and _is_present(row.get("sample_date"))
    ]
    testosterone_rows = [
        row for row in rows or []
        if str(row.get("biomarker_type") or "").strip().upper() in {"TESTOSTERONA", "TESTOSTERONE"}
        and _is_present(row.get("value"))
        and _is_present(row.get("sample_date"))
    ]

    def by_date(row: dict[str, Any]) -> tuple[str, int]:
        try:
            return (str(row.get("sample_date") or ""), int(row.get("id") or 0))
        except (TypeError, ValueError):
            return (str(row.get("sample_date") or ""), 0)

    psa_rows = sorted(psa_rows, key=by_date)
    pretreatment_contexts = {"baseline", "diagnostic", "pretratamiento", "pretreatment", "initial"}
    pretreatment_rows = [
        row for row in psa_rows
        if str(row.get("context") or "").strip().lower() in pretreatment_contexts
    ] or psa_rows
    baseline_psa_row = pretreatment_rows[-1] if pretreatment_rows else {}
    latest_psa_row = psa_rows[-1] if psa_rows else {}
    if baseline_psa_row:
        _append_source(
            sources_by_fact,
            fact_key="baseline_psa",
            observed_key="psa_history",
            value=baseline_psa_row.get("value"),
            source_type="biomarker_longitudinal",
            source_record_type="biomarker_longitudinal",
            source_record_id=baseline_psa_row.get("id"),
            source_date=baseline_psa_row.get("sample_date"),
            observed_at=baseline_psa_row.get("created_at"),
            certainty_tier="structured_series",
            metadata={"biomarker_type": "PSA", "context": baseline_psa_row.get("context")},
        )
    if latest_psa_row:
        _append_source(
            sources_by_fact,
            fact_key="current_psa",
            observed_key="psa_history",
            value=latest_psa_row.get("value"),
            source_type="biomarker_longitudinal",
            source_record_type="biomarker_longitudinal",
            source_record_id=latest_psa_row.get("id"),
            source_date=latest_psa_row.get("sample_date"),
            observed_at=latest_psa_row.get("created_at"),
            certainty_tier="structured_series",
            metadata={"biomarker_type": "PSA", "context": latest_psa_row.get("context")},
        )
    testosterone_rows = sorted(testosterone_rows, key=by_date)
    if testosterone_rows:
        latest_testosterone = testosterone_rows[-1]
        _append_source(
            sources_by_fact,
            fact_key="testosterone",
            observed_key="testosterone_history",
            value=latest_testosterone.get("value"),
            source_type="biomarker_longitudinal",
            source_record_type="biomarker_longitudinal",
            source_record_id=latest_testosterone.get("id"),
            source_date=latest_testosterone.get("sample_date"),
            observed_at=latest_testosterone.get("created_at"),
            certainty_tier="structured_series",
            metadata={"biomarker_type": latest_testosterone.get("biomarker_type")},
        )
        _append_source(
            sources_by_fact,
            fact_key="testosterone_sample_date",
            observed_key="testosterone_history",
            value=latest_testosterone.get("sample_date"),
            source_type="biomarker_longitudinal",
            source_record_type="biomarker_longitudinal",
            source_record_id=latest_testosterone.get("id"),
            source_date=latest_testosterone.get("sample_date"),
            observed_at=latest_testosterone.get("created_at"),
            certainty_tier="structured_series",
            metadata={"biomarker_type": latest_testosterone.get("biomarker_type")},
        )
    return {
        "psa_history_points": len(psa_rows),
        "testosterone_history_points": len(testosterone_rows),
        "psa_latest_sample_date": latest_psa_row.get("sample_date") if latest_psa_row else None,
    }


def _append_verified_document_facts(
    sources_by_fact: dict[str, list[dict[str, Any]]],
    rows: list[dict[str, Any]],
) -> None:
    aliases = _alias_map()
    for row in rows or []:
        observed_key = str(row.get("fact_key") or row.get("field_key") or "")
        canonical_key = aliases.get(observed_key, observed_key)
        _append_source(
            sources_by_fact,
            fact_key=canonical_key,
            observed_key=observed_key,
            value=row.get("value"),
            source_type="verified_document_facts",
            source_record_type="verified_document_fact",
            source_record_id=row.get("id"),
            source_date=row.get("source_date") or row.get("created_at"),
            observed_at=row.get("verified_at") or row.get("created_at"),
            certainty_tier="document_verified",
            clinician_verified=True,
            metadata={"document_id": row.get("document_id")},
        )


def _build_fact_item(spec: FactSpec, sources: list[dict[str, Any]]) -> dict[str, Any]:
    ordered_sources = sorted(sources, key=_source_sort_key, reverse=True)
    distinct_values = sorted({source["normalized_value"] for source in ordered_sources})
    current = ordered_sources[0] if ordered_sources else {}
    raw_has_conflict = len(distinct_values) > 1
    conflict_resolved_by_reconciliation = bool(
        raw_has_conflict
        and current.get("source_type") == "patient_clinical_facts"
        and current.get("source_record_type") == "ledger_reconciliation"
        and current.get("clinician_verified")
    )
    alias_observations = [
        {
            "observed_key": source.get("observed_key"),
            "source_type": source.get("source_type"),
            "source_record_id": source.get("source_record_id"),
        }
        for source in ordered_sources
        if source.get("observed_key") and source.get("observed_key") != spec.fact_key
    ]
    has_conflict = raw_has_conflict and not conflict_resolved_by_reconciliation
    duplicate_same_value = len(ordered_sources) > 1 and not has_conflict
    if conflict_resolved_by_reconciliation:
        recapture_risk = "resolved_watch"
    elif has_conflict and spec.blocking:
        recapture_risk = "high"
    elif has_conflict:
        recapture_risk = "moderate"
    elif alias_observations or duplicate_same_value:
        recapture_risk = "watch"
    else:
        recapture_risk = "none"
    return {
        "fact_key": spec.fact_key,
        "domain": spec.domain,
        "value_type": spec.value_type,
        "legacy_aliases": list(spec.legacy_aliases),
        "blocking": bool(spec.blocking),
        "consumers": list(spec.consumers),
        "value_known": bool(current),
        "current_value": current.get("value"),
        "current_source": current.get("source_type"),
        "current_observed_key": current.get("observed_key"),
        "freshness_status": current.get("freshness_status") or "missing",
        "freshness_expires_at": current.get("freshness_expires_at"),
        "source_count": len(ordered_sources),
        "distinct_value_count": len(distinct_values),
        "has_conflict": has_conflict,
        "raw_has_conflict": raw_has_conflict,
        "conflict_resolved_by_reconciliation": conflict_resolved_by_reconciliation,
        "duplicate_same_value": duplicate_same_value,
        "alias_observations": alias_observations,
        "recapture_risk": recapture_risk,
        "sources": ordered_sources,
    }


def build_patient_clinical_fact_ledger(patient_record: dict[str, Any]) -> dict[str, Any]:
    patient_record = dict(patient_record or {})
    identity = dict(patient_record.get("identity") or {})
    latest_assessment = dict(patient_record.get("latest_assessment") or {})
    latest_input = dict(latest_assessment.get("input_snapshot") or {})
    sources_by_fact: dict[str, list[dict[str, Any]]] = defaultdict(list)

    inactive_fact_count = _append_patient_clinical_facts(
        sources_by_fact,
        list(patient_record.get("patient_clinical_facts") or []),
    )
    _append_sources_from_payload(
        sources_by_fact,
        dict(patient_record.get("baseline") or {}),
        source_type="clinical_baseline",
        source_record_type="clinical_baseline",
        source_date=identity.get("diagnosis_date") or "",
        observed_at=identity.get("created_at") or "",
        certainty_tier="structured_baseline",
    )
    _append_sources_from_payload(
        sources_by_fact,
        dict(patient_record.get("demographics") or {}),
        source_type="patient_demographics",
        source_record_type="patient_demographics",
        source_date=identity.get("created_at") or "",
        observed_at=identity.get("created_at") or "",
        certainty_tier="structured_demographics",
    )
    _append_sources_from_payload(
        sources_by_fact,
        latest_input,
        source_type="latest_assessment_input",
        source_record_type="clinical_assessment",
        source_record_id=latest_assessment.get("id"),
        source_date=latest_assessment.get("assessment_date") or latest_assessment.get("created_at") or "",
        observed_at=latest_assessment.get("created_at") or "",
        certainty_tier="wizard_or_intake",
    )
    _append_biomarker_metadata = _append_biomarker_sources(
        sources_by_fact,
        list(patient_record.get("biomarker_longitudinal") or []),
    )
    _append_verified_document_facts(
        sources_by_fact,
        list(patient_record.get("verified_document_facts") or []),
    )
    try:
        shadow_payload = build_legacy_shadow_payload(patient_record)
    except Exception:
        shadow_payload = {}
    _append_sources_from_payload(
        sources_by_fact,
        shadow_payload,
        source_type="legacy_shadow_payload",
        source_record_type="derived_shadow_payload",
        source_date=latest_assessment.get("created_at") or "",
        observed_at=latest_assessment.get("created_at") or "",
        certainty_tier="derived_shadow",
    )

    facts = [
        _build_fact_item(spec, sources_by_fact.get(spec.fact_key, []))
        for spec in iter_registered_fact_specs()
    ]
    source_counter = Counter()
    for item in facts:
        for source in item.get("sources") or []:
            source_counter[source.get("source_type") or "unknown"] += 1
    known_facts = [item for item in facts if item["value_known"]]
    blocking = [item for item in facts if item["blocking"]]
    blocking_missing = [item for item in blocking if not item["value_known"]]
    conflicts = [item for item in facts if item["has_conflict"]]
    alias_watch = [item for item in facts if item["alias_observations"]]
    recapture_watch = [item for item in facts if item["recapture_risk"] != "none"]
    return {
        "patient": {
            "patient_id": identity.get("id"),
            "nss": identity.get("nss"),
            "full_name": identity.get("full_name"),
        },
        "summary": {
            "registered_fact_count": len(facts),
            "known_fact_count": len(known_facts),
            "missing_fact_count": len(facts) - len(known_facts),
            "blocking_fact_count": len(blocking),
            "blocking_known_count": len(blocking) - len(blocking_missing),
            "blocking_missing_count": len(blocking_missing),
            "conflict_count": len(conflicts),
            "alias_observation_count": len(alias_watch),
            "recapture_watch_count": len(recapture_watch),
            "inactive_fact_row_count": inactive_fact_count,
            "source_counts": dict(sorted(source_counter.items())),
            **_append_biomarker_metadata,
        },
        "facts": facts,
        "known_facts": [item for item in facts if item["value_known"]],
        "blocking_missing": blocking_missing,
        "conflicts": conflicts,
        "recapture_watch": recapture_watch,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
    }


def _summarize_fact_for_ui(item: dict[str, Any]) -> dict[str, Any]:
    sources = list(item.get("sources") or [])
    source_types = []
    for source in sources:
        source_type = source.get("source_type") or "unknown"
        if source_type not in source_types:
            source_types.append(source_type)
    status = "known" if item.get("value_known") else "missing"
    if item.get("has_conflict"):
        status = "conflict"
    elif item.get("recapture_risk") == "watch":
        status = "watch"
    return {
        "fact_key": item.get("fact_key"),
        "domain": item.get("domain"),
        "current_value": item.get("current_value"),
        "value_known": item.get("value_known"),
        "current_source": item.get("current_source"),
        "current_observed_key": item.get("current_observed_key"),
        "freshness_status": item.get("freshness_status"),
        "source_count": item.get("source_count"),
        "source_types": source_types,
        "has_conflict": item.get("has_conflict"),
        "recapture_risk": item.get("recapture_risk"),
        "blocking": item.get("blocking"),
        "status": status,
        "profile_hint": _fact_profile_hint(item),
    }


def _fact_profile_hint(item: dict[str, Any]) -> str:
    if item.get("has_conflict"):
        return "Resolver contradiccion antes de usar este dato para decision."
    if item.get("recapture_risk") == "watch":
        return "Dato ya documentado en varias fuentes concordantes; evitar recaptura."
    if item.get("value_known"):
        return "Dato disponible; reutilizar desde Ledger."
    if item.get("blocking"):
        return "Dato bloqueante faltante; capturar de forma dirigida."
    return "Dato opcional o contextual no documentado."


def build_patient_clinical_fact_ledger_summary(
    patient_record: dict[str, Any] | None = None,
    *,
    ledger: dict[str, Any] | None = None,
    focus_fact_keys: tuple[str, ...] = _SUMMARY_FACT_KEYS,
) -> dict[str, Any]:
    """Compact V2 summary for UI anti-recapture and provenance chips."""
    full_ledger = dict(ledger or build_patient_clinical_fact_ledger(patient_record or {}))
    facts = list(full_ledger.get("facts") or [])
    fact_map = {item.get("fact_key"): item for item in facts if item.get("fact_key")}
    priority_facts = [
        _summarize_fact_for_ui(fact_map[key])
        for key in focus_fact_keys
        if key in fact_map
    ]
    conflicts = list(full_ledger.get("conflicts") or [])
    recapture_watch = list(full_ledger.get("recapture_watch") or [])
    blocking_missing = list(full_ledger.get("blocking_missing") or [])
    known_priority = [item for item in priority_facts if item.get("value_known")]
    reusable_known = [
        item for item in priority_facts
        if item.get("value_known") and not item.get("has_conflict")
    ]
    summary = dict(full_ledger.get("summary") or {})
    return {
        "version": "clinical_fact_ledger_summary_v1",
        "patient": full_ledger.get("patient") or {},
        "summary": {
            **summary,
            "priority_fact_count": len(priority_facts),
            "priority_known_count": len(known_priority),
            "reusable_priority_fact_count": len(reusable_known),
            "ui_reuse_rate_pct": round((len(reusable_known) / len(priority_facts)) * 100, 1) if priority_facts else None,
        },
        "priority_facts": priority_facts,
        "conflict_queue": [_summarize_fact_for_ui(item) for item in conflicts[:12]],
        "recapture_watch": [_summarize_fact_for_ui(item) for item in recapture_watch[:12]],
        "blocking_missing": [_summarize_fact_for_ui(item) for item in blocking_missing[:12]],
        "source_counts": summary.get("source_counts") or {},
        "ui_contract": {
            "read_only": True,
            "pre_fill_known_facts": True,
            "hide_known_non_conflicting_fields": True,
            "show_conflicts_before_reuse": True,
            "source_clinical_facts_mutated": False,
            "external_order_created": False,
            "model_trained": False,
        },
        "next_action": (
            "Resolver contradicciones antes de decision." if conflicts
            else "Usar facts conocidos para prellenar y evitar recaptura." if reusable_known
            else "Capturar datos bloqueantes faltantes de forma dirigida."
        ),
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
    }


def build_decision_today_ledger_quality(
    patient_record: dict[str, Any] | None = None,
    *,
    ledger: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read-only data-quality contract consumed by DECISION HOY.

    The therapeutic engine should not silently downgrade, overwrite, order or
    train anything because of Ledger state. This bundle only explains whether
    the current decision is clear, conditioned by open conflicts, or relying on
    clinician-reconciled facts that should remain auditable.
    """
    full_ledger = dict(ledger or build_patient_clinical_fact_ledger(patient_record or {}))
    patient = dict(full_ledger.get("patient") or {})
    conflicts = list(full_ledger.get("conflicts") or [])
    critical_conflicts = [item for item in conflicts if item.get("blocking")]
    resolved_watch = [
        item for item in (full_ledger.get("facts") or [])
        if item.get("conflict_resolved_by_reconciliation")
    ]
    recapture_watch = [
        item for item in (full_ledger.get("recapture_watch") or [])
        if not item.get("has_conflict")
    ]
    if critical_conflicts:
        status = "blocked_by_critical_conflict"
        severity = "critical"
        label = "DECISION HOY condicionada por conflicto critico Ledger"
        message = "Resolver conflictos clinicos bloqueantes antes de liberar o cerrar una decision electiva."
    elif conflicts:
        status = "conditioned_by_open_conflict"
        severity = "warning"
        label = "DECISION HOY condicionada por conflicto Ledger"
        message = "Hay contradicciones no bloqueantes; revise fuente ganadora para evitar recaptura o recomendacion ambigua."
    elif resolved_watch:
        status = "uses_reconciled_facts"
        severity = "watch"
        label = "DECISION HOY usa facts reconciliados"
        message = "No hay conflicto abierto; existen discordancias historicas resueltas bajo vigilancia auditable."
    else:
        status = "clear"
        severity = "ok"
        label = "Ledger claro para DECISION HOY"
        message = "Sin conflictos abiertos que condicionen la decision actual."

    def decision_fact(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "fact_key": item.get("fact_key"),
            "domain": item.get("domain"),
            "blocking": bool(item.get("blocking")),
            "current_value": item.get("current_value"),
            "current_source": item.get("current_source"),
            "source_count": item.get("source_count"),
            "distinct_value_count": item.get("distinct_value_count"),
            "freshness_status": item.get("freshness_status"),
            "consumers": list(item.get("consumers") or []),
            "can_change_decision": bool(item.get("blocking") or item.get("consumers")),
        }

    patient_ref = patient.get("nss") or ""
    return {
        "version": "clinical_fact_ledger_decision_quality_v1",
        "status": status,
        "severity": severity,
        "label": label,
        "message": message,
        "patient_ref": patient_ref,
        "conflict_count": len(conflicts),
        "critical_conflict_count": len(critical_conflicts),
        "resolved_watch_count": len(resolved_watch),
        "recapture_watch_count": len(recapture_watch),
        "decision_conditioned": bool(conflicts),
        "requires_reconciliation": bool(conflicts),
        "uses_reconciled_facts": bool(resolved_watch),
        "open_conflicts": [decision_fact(item) for item in conflicts[:8]],
        "critical_conflicts": [decision_fact(item) for item in critical_conflicts[:8]],
        "resolved_watch": [decision_fact(item) for item in resolved_watch[:8]],
        "reconciliation_cta": {
            "label": "Reconciliar hechos clinicos",
            "href": f"/clinical-fact-reconciliation/{patient_ref}" if patient_ref else "",
        },
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
    }


def _dominant_reconciliation_conflict(queue: list[dict[str, Any]]) -> dict[str, Any]:
    if not queue:
        return {}
    critical = [
        item for item in queue
        if item.get("blocking") or str(item.get("severity") or "").lower() == "critical"
    ]
    return dict((critical or queue)[0] or {})


def _compact_decision_quality_for_population(quality: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": quality.get("status") or "clear",
        "severity": quality.get("severity") or "ok",
        "label": quality.get("label") or "",
        "message": quality.get("message") or "",
        "conflict_count": int(quality.get("conflict_count") or 0),
        "critical_conflict_count": int(quality.get("critical_conflict_count") or 0),
        "resolved_watch_count": int(quality.get("resolved_watch_count") or 0),
        "requires_reconciliation": bool(quality.get("requires_reconciliation")),
        "uses_reconciled_facts": bool(quality.get("uses_reconciled_facts")),
    }


def build_clinical_fact_reconciliation_population(
    patient_records: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    *,
    limit: int = 50,
    include_clear: bool = False,
) -> dict[str, Any]:
    """Population worklist for open Ledger conflicts.

    This layer is intentionally read-only: it helps a service detect which
    patients need clinician-led reconciliation, but it never writes facts,
    creates orders, or trains models.
    """
    max_rows = max(1, min(int(limit or 50), 250))
    records = [record for record in (patient_records or []) if isinstance(record, dict)]
    rows: list[dict[str, Any]] = []
    skipped = 0
    for record in records:
        try:
            ledger = build_patient_clinical_fact_ledger(record)
            bundle = build_patient_clinical_fact_reconciliation_bundle(record, ledger=ledger, limit=24)
            quality = build_decision_today_ledger_quality(record, ledger=ledger)
        except Exception:
            skipped += 1
            continue
        bundle_summary = dict(bundle.get("summary") or {})
        conflict_count = int(bundle_summary.get("conflict_count") or 0)
        critical_count = int(bundle_summary.get("critical_conflict_count") or 0)
        if not include_clear and conflict_count <= 0:
            continue
        patient = dict((ledger.get("patient") or {}) or (record.get("identity") or {}))
        identity = dict(record.get("identity") or {})
        patient_ref = str(patient.get("nss") or identity.get("nss") or "").strip()
        queue = list(bundle.get("queue") or [])
        dominant = _dominant_reconciliation_conflict(queue)
        decision_quality = _compact_decision_quality_for_population(quality)
        priority_score = (
            critical_count * 100
            + conflict_count * 10
            + (5 if decision_quality.get("status") == "blocked_by_critical_conflict" else 0)
            + int(bundle_summary.get("resolved_watch_count") or 0)
        )
        rows.append({
            "version": "clinical_fact_reconciliation_population_row_v1",
            "patient_ref": patient_ref,
            "patient": {
                "patient_id": patient.get("patient_id") or identity.get("id"),
                "nss": patient_ref,
                "full_name": patient.get("full_name") or identity.get("full_name") or patient_ref,
            },
            "display_name": patient.get("full_name") or identity.get("full_name") or patient_ref,
            "conflict_count": conflict_count,
            "critical_conflict_count": critical_count,
            "resolved_watch_count": int(bundle_summary.get("resolved_watch_count") or 0),
            "registered_fact_count": bundle_summary.get("registered_fact_count"),
            "known_fact_count": bundle_summary.get("known_fact_count"),
            "dominant_conflict": {
                "fact_key": dominant.get("fact_key") or "",
                "domain": dominant.get("domain") or "",
                "severity": dominant.get("severity") or "",
                "blocking": bool(dominant.get("blocking")),
                "current_value": dominant.get("current_value"),
                "current_source": dominant.get("current_source") or "",
                "source_count": dominant.get("source_count") or 0,
                "distinct_value_count": dominant.get("distinct_value_count") or 0,
                "freshness_status": dominant.get("freshness_status") or "",
            },
            "decision_quality": decision_quality,
            "priority_score": priority_score,
            "primary_action": {
                "label": "Abrir reconciliacion Ledger",
                "href": f"/clinical-fact-reconciliation/{patient_ref}" if patient_ref else "",
                "action_mode": "reconcile_clinical_fact",
                "decision_field": dominant.get("fact_key") or "",
            },
            "source_clinical_facts_mutated": False,
            "external_order_created": False,
            "model_trained": False,
        })
    rows.sort(
        key=lambda item: (
            int(item.get("priority_score") or 0),
            int(item.get("critical_conflict_count") or 0),
            int(item.get("conflict_count") or 0),
            str(item.get("patient_ref") or ""),
        ),
        reverse=True,
    )
    visible_rows = rows[:max_rows]
    return {
        "version": "clinical_fact_reconciliation_population_v1",
        "generated_from": "clinical_fact_ledger",
        "candidate_patient_count": len(records),
        "skipped_patient_count": skipped,
        "summary": {
            "visible_patient_count": len(visible_rows),
            "open_conflict_patient_count": sum(1 for item in rows if int(item.get("conflict_count") or 0) > 0),
            "critical_patient_count": sum(1 for item in rows if int(item.get("critical_conflict_count") or 0) > 0),
            "total_conflict_count": sum(int(item.get("conflict_count") or 0) for item in rows),
            "total_critical_conflict_count": sum(int(item.get("critical_conflict_count") or 0) for item in rows),
            "clear_patient_count": sum(1 for item in rows if int(item.get("conflict_count") or 0) == 0),
        },
        "patients": visible_rows,
        "ui_contract": {
            "read_only": True,
            "population_queue": True,
            "opens_patient_reconciliation": True,
            "source_clinical_facts_mutated": False,
            "external_order_created": False,
            "model_trained": False,
        },
        "next_action": (
            "Resolver primero conflictos criticos que bloquean DECISION HOY."
            if any(int(item.get("critical_conflict_count") or 0) > 0 for item in rows)
            else "Revisar contradicciones moderadas para reducir recaptura."
            if rows
            else "Sin conflictos Ledger abiertos en los pacientes escaneados."
        ),
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
    }


def build_patient_clinical_fact_ledger_wizard_context(
    patient_record: dict[str, Any] | None = None,
    *,
    ledger: dict[str, Any] | None = None,
    module_schema: dict[str, Any] | None = None,
    module_id: str = "",
) -> dict[str, Any]:
    """Read-only field reuse contract for V2 wizards.

    Known non-conflicting facts can be prefilled and hidden from recapture.
    Conflicting facts stay visible so the clinician can resolve them.
    """
    full_ledger = dict(ledger or build_patient_clinical_fact_ledger(patient_record or {}))
    facts = list(full_ledger.get("facts") or [])
    fact_map = {item.get("fact_key"): item for item in facts if item.get("fact_key")}
    aliases = _alias_map()
    fields: dict[str, dict[str, Any]] = {}
    reusable: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []

    for raw_field in (module_schema or {}).get("fields") or []:
        if not isinstance(raw_field, dict):
            continue
        field_name = str(raw_field.get("name") or "").strip()
        if not field_name:
            continue
        fact_key = aliases.get(field_name)
        if not fact_key or fact_key not in fact_map:
            continue
        fact = _summarize_fact_for_ui(fact_map[fact_key])
        action = "capture_if_needed"
        if fact.get("has_conflict"):
            action = "resolve_conflict_before_reuse"
        elif fact.get("value_known"):
            action = "reuse_prefill_hide"
        elif fact.get("blocking"):
            action = "capture_missing_blocking"
        field_item = {
            **fact,
            "field_name": field_name,
            "field_label": raw_field.get("label") or field_name,
            "field_type": raw_field.get("field_type") or raw_field.get("type") or "text",
            "required": bool(raw_field.get("required")),
            "action": action,
            "source_clinical_facts_mutated": False,
            "external_order_created": False,
            "model_trained": False,
        }
        fields[field_name] = field_item
        if action == "reuse_prefill_hide":
            reusable.append(field_item)
        elif action == "resolve_conflict_before_reuse":
            conflicts.append(field_item)
        elif action == "capture_missing_blocking":
            missing.append(field_item)

    summary = dict(full_ledger.get("summary") or {})
    return {
        "version": "clinical_fact_ledger_wizard_context_v1",
        "module_id": module_id or (module_schema or {}).get("module") or "",
        "patient": full_ledger.get("patient") or {},
        "summary": {
            "schema_field_count": len((module_schema or {}).get("fields") or []),
            "mapped_field_count": len(fields),
            "reusable_field_count": len(reusable),
            "conflict_field_count": len(conflicts),
            "missing_blocking_field_count": len(missing),
            "ledger_known_fact_count": summary.get("known_fact_count"),
            "ledger_registered_fact_count": summary.get("registered_fact_count"),
        },
        "field_prefills": fields,
        "reusable_fields": reusable,
        "conflict_fields": conflicts,
        "missing_blocking_fields": missing,
        "ui_contract": {
            "read_only": True,
            "pre_fill_known_facts": True,
            "hide_known_non_conflicting_fields": True,
            "show_conflicts_before_reuse": True,
            "source_clinical_facts_mutated": False,
            "external_order_created": False,
            "model_trained": False,
        },
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
    }


def _value_text(value: Any) -> str:
    return str(value if value is not None else "").strip().lower()


def _is_truthy_fact_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = _value_text(value)
    return text in {"1", "true", "yes", "si", "sí", "positive", "positivo", "done", "realizado"}


def _fact_is_current(item: dict[str, Any] | None) -> bool:
    return bool(
        item
        and item.get("value_known")
        and not item.get("has_conflict")
        and item.get("freshness_status") == "current"
    )


def _fact_source_trace(item: dict[str, Any] | None) -> dict[str, Any]:
    if not item:
        return {}
    return {
        "fact_key": item.get("fact_key"),
        "current_value": item.get("current_value"),
        "current_source": item.get("current_source"),
        "current_observed_key": item.get("current_observed_key"),
        "freshness_status": item.get("freshness_status"),
        "source_count": item.get("source_count"),
        "has_conflict": item.get("has_conflict"),
        "raw_has_conflict": item.get("raw_has_conflict"),
        "conflict_resolved_by_reconciliation": item.get("conflict_resolved_by_reconciliation"),
    }


def _gate_context_active(spec: dict[str, Any], cta_payload: dict[str, Any]) -> bool:
    if bool(cta_payload.get("available")):
        return True
    return any(bool(cta_payload.get(flag)) for flag in spec.get("context_flags") or ())


def _gate_actionable_fact(
    gate_key: str,
    spec: dict[str, Any],
    fact_map: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    pending_values = {_value_text(value) for value in spec.get("pending_values") or ()}
    required_fact_keys = tuple(spec.get("required_fact_keys") or ())
    for fact_key in required_fact_keys:
        fact = fact_map.get(fact_key)
        if not _fact_is_current(fact):
            continue
        value = fact.get("current_value")
        text_value = _value_text(value)
        if text_value in pending_values:
            continue
        if gate_key == "psma_pet_quick_capture":
            if fact_key == "psma_pet_done" and not _is_truthy_fact_value(value):
                continue
            if fact_key == "psma_pet_status" and text_value in {"negative", "positivo", "positive", "positive_metastatic", "positive_oligometastatic", "positive_local_recurrence"}:
                return fact
            if fact_key == "psma_positive":
                return fact
            if fact_key == "psma_pet_done":
                return fact
            continue
        return fact
    return None


def _build_capture_gate_decision(
    gate_key: str,
    spec: dict[str, Any],
    fact_map: dict[str, dict[str, Any]],
    cta_payload: dict[str, Any],
) -> dict[str, Any]:
    clinical_context_active = _gate_context_active(spec, cta_payload)
    required_fact_keys = tuple(spec.get("required_fact_keys") or ())
    support_fact_keys = tuple(spec.get("support_fact_keys") or ())
    relevant_fact_keys = (*required_fact_keys, *support_fact_keys)
    relevant_facts = [fact_map[key] for key in relevant_fact_keys if key in fact_map]
    conflicts = [fact for fact in relevant_facts if fact.get("has_conflict")]
    known = [fact for fact in relevant_facts if fact.get("value_known")]
    stale = [
        fact for fact in known
        if not fact.get("has_conflict") and fact.get("freshness_status") != "current"
    ]
    missing_required = [
        key for key in required_fact_keys
        if not (fact_map.get(key) or {}).get("value_known")
    ]
    actionable_fact = _gate_actionable_fact(gate_key, spec, fact_map)

    if conflicts:
        action = "resolve_conflict_before_capture"
        capture_allowed = False
        suppress_recapture = clinical_context_active
        tone = "danger"
        message = "Ledger detecto contradiccion; revisar fuente antes de capturar de nuevo."
    elif actionable_fact:
        action = "reuse_existing_fact"
        capture_allowed = False
        suppress_recapture = clinical_context_active
        tone = "success"
        message = f"{spec['label']} reutilizado desde Ledger; no pedir recaptura en Perfil V2."
    elif stale:
        action = "refresh_stale_fact"
        capture_allowed = clinical_context_active
        suppress_recapture = False
        tone = "warning"
        message = f"{spec['label']} existe pero esta envejecido; pedir actualizacion dirigida si el contexto clinico lo exige."
    elif missing_required:
        action = "capture_missing"
        capture_allowed = clinical_context_active
        suppress_recapture = False
        tone = "warning" if clinical_context_active else "muted"
        message = f"{spec['label']} no esta documentado en Ledger; capturar solo si el contexto V2 esta activo."
    else:
        action = "capture_if_clinically_needed"
        capture_allowed = clinical_context_active
        suppress_recapture = False
        tone = "muted"
        message = f"{spec['label']} sin bloqueo Ledger; usar la logica clinica de la CTA."

    return {
        "gate_key": gate_key,
        "label": spec.get("label"),
        "cta_context_key": spec.get("cta_context_key"),
        "clinical_context_active": clinical_context_active,
        "cta_available_before_ledger": bool(cta_payload.get("available")),
        "action": action,
        "capture_allowed": capture_allowed,
        "suppress_recapture": suppress_recapture,
        "suppressed_by_ledger": suppress_recapture,
        "tone": tone,
        "message": message,
        "required_fact_keys": list(required_fact_keys),
        "support_fact_keys": list(support_fact_keys),
        "known_fact_keys": [fact.get("fact_key") for fact in known if fact.get("fact_key")],
        "missing_fact_keys": missing_required,
        "conflict_fact_keys": [fact.get("fact_key") for fact in conflicts if fact.get("fact_key")],
        "stale_fact_keys": [fact.get("fact_key") for fact in stale if fact.get("fact_key")],
        "reused_fact_key": actionable_fact.get("fact_key") if actionable_fact else "",
        "source_trace": [_fact_source_trace(fact) for fact in relevant_facts],
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
    }


def build_patient_profile_v2_capture_governance(
    patient_record: dict[str, Any] | None = None,
    *,
    ledger: dict[str, Any] | None = None,
    cta_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read-only governance layer for Profile V2 quick-capture CTAs.

    The existing CTA logic decides whether a clinical context needs a capture.
    This layer only prevents unnecessary recapture or blind overwrite when the
    Clinical Fact Ledger already has a current fact, stale fact, or conflict.
    """
    full_ledger = dict(ledger or build_patient_clinical_fact_ledger(patient_record or {}))
    fact_map = {
        item.get("fact_key"): item
        for item in (full_ledger.get("facts") or [])
        if isinstance(item, dict) and item.get("fact_key")
    }
    cta_context = dict(cta_context or {})
    gates = []
    for gate_key, spec in _PROFILE_V2_CAPTURE_GATES.items():
        context_key = str(spec.get("cta_context_key") or "")
        cta_payload = dict(cta_context.get(context_key) or {})
        gates.append(_build_capture_gate_decision(gate_key, spec, fact_map, cta_payload))
    gates_by_key = {gate["gate_key"]: gate for gate in gates}
    active_gates = [gate for gate in gates if gate.get("clinical_context_active")]
    suppressed_gates = [gate for gate in gates if gate.get("suppressed_by_ledger")]
    conflict_gates = [gate for gate in gates if gate.get("action") == "resolve_conflict_before_capture"]
    refresh_gates = [gate for gate in gates if gate.get("action") == "refresh_stale_fact"]
    missing_gates = [gate for gate in gates if gate.get("action") == "capture_missing"]
    return {
        "version": "patient_profile_v2_capture_governance_v1",
        "patient": full_ledger.get("patient") or {},
        "summary": {
            "gate_count": len(gates),
            "active_gate_count": len(active_gates),
            "suppressed_gate_count": len(suppressed_gates),
            "conflict_gate_count": len(conflict_gates),
            "refresh_gate_count": len(refresh_gates),
            "missing_gate_count": len(missing_gates),
        },
        "gates": gates,
        "gates_by_key": gates_by_key,
        "ui_contract": {
            "read_only": True,
            "prevent_profile_v2_recapture": True,
            "show_conflicts_before_reuse": True,
            "source_clinical_facts_mutated": False,
            "external_order_created": False,
            "model_trained": False,
        },
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
    }


def _longitudinal_form_targeted(
    spec: dict[str, Any],
    *,
    decision_field: str = "",
    readiness_lane: str = "",
    moment: str = "",
) -> bool:
    normalized_decision_field = _value_text(decision_field)
    normalized_readiness_lane = _value_text(readiness_lane)
    normalized_moment = _value_text(moment)
    decision_fields = {_value_text(item) for item in spec.get("decision_fields") or ()}
    readiness_lanes = {_value_text(item) for item in spec.get("readiness_lanes") or ()}
    section_id = _value_text(spec.get("section_id"))
    return bool(
        (normalized_decision_field and normalized_decision_field in decision_fields)
        or (normalized_readiness_lane and normalized_readiness_lane in readiness_lanes)
        or (normalized_moment and normalized_moment in {section_id.replace("section-", ""), section_id})
    )


def _build_longitudinal_field_decision(
    form_key: str,
    spec: dict[str, Any],
    field_name: str,
    fact_key: str,
    fact_map: dict[str, dict[str, Any]],
    *,
    targeted: bool,
) -> dict[str, Any]:
    policy = str(spec.get("policy") or "")
    fact = fact_map.get(fact_key) if fact_key else None
    value_known = bool(fact and fact.get("value_known"))
    has_conflict = bool(fact and fact.get("has_conflict"))
    freshness_status = str((fact or {}).get("freshness_status") or "missing")
    current_value = (fact or {}).get("current_value")
    source_trace = _fact_source_trace(fact)

    capture_allowed = True
    suppress_recapture = False
    tone = "muted"

    if not fact_key:
        action = "capture_if_clinically_needed"
        message = "Campo sin fact canonico; capturar solo si aporta a la visita actual."
    elif policy == "append_series":
        action = "append_new_measurement"
        tone = "info" if targeted else "muted"
        message = "Nueva medicion fechada; Ledger conserva el valor previo como referencia."
    elif has_conflict and targeted:
        action = "resolve_conflict_before_capture"
        capture_allowed = False
        suppress_recapture = True
        tone = "danger"
        message = "Conflicto Ledger; revisar fuentes antes de escribir otro valor."
    elif value_known and freshness_status == "current" and targeted:
        action = "reuse_existing_fact"
        capture_allowed = False
        suppress_recapture = True
        tone = "success"
        message = f"Ya vigente en Ledger: {current_value}."
    elif value_known and freshness_status != "current" and targeted:
        action = "refresh_stale_fact"
        tone = "warning"
        message = "Dato previo envejecido; actualizacion dirigida permitida."
    elif not value_known and targeted:
        action = "capture_missing"
        tone = "warning"
        message = "Faltante para el carril actual; captura dirigida permitida."
    elif value_known:
        action = "existing_fact_visible_append_if_new_event"
        tone = "info"
        message = "Dato ya documentado; capturar solo si es un evento nuevo."
    else:
        action = "capture_if_clinically_needed"
        message = "Sin bloqueo Ledger; usar secuencia clinica."

    return {
        "form_key": form_key,
        "field_name": field_name,
        "fact_key": fact_key,
        "action": action,
        "capture_allowed": capture_allowed,
        "suppress_recapture": suppress_recapture,
        "suppressed_by_ledger": suppress_recapture,
        "tone": tone,
        "message": message,
        "value_known": value_known,
        "current_value": current_value,
        "current_source": (fact or {}).get("current_source"),
        "current_observed_key": (fact or {}).get("current_observed_key"),
        "freshness_status": freshness_status,
        "has_conflict": has_conflict,
        "source_trace": source_trace,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
    }


def _build_longitudinal_capture_form_decision(
    form_key: str,
    spec: dict[str, Any],
    fact_map: dict[str, dict[str, Any]],
    *,
    decision_field: str = "",
    readiness_lane: str = "",
    moment: str = "",
) -> dict[str, Any]:
    fact_keys = tuple(spec.get("fact_keys") or ())
    facts = [fact_map[key] for key in fact_keys if key in fact_map]
    known = [fact for fact in facts if fact.get("value_known")]
    conflicts = [fact for fact in facts if fact.get("has_conflict")]
    current_known = [
        fact for fact in known
        if not fact.get("has_conflict") and fact.get("freshness_status") == "current"
    ]
    stale_known = [
        fact for fact in known
        if not fact.get("has_conflict") and fact.get("freshness_status") != "current"
    ]
    missing = [key for key in fact_keys if not (fact_map.get(key) or {}).get("value_known")]
    targeted = _longitudinal_form_targeted(
        spec,
        decision_field=decision_field,
        readiness_lane=readiness_lane,
        moment=moment,
    )
    policy = str(spec.get("policy") or "")
    field_map = {
        str(field_name): str(fact_key)
        for field_name, fact_key in (spec.get("field_map") or {}).items()
        if str(field_name or "").strip()
    }
    field_decisions = {
        field_name: _build_longitudinal_field_decision(
            form_key,
            spec,
            field_name,
            fact_key,
            fact_map,
            targeted=targeted,
        )
        for field_name, fact_key in field_map.items()
    }
    field_suppressed = [
        item for item in field_decisions.values()
        if item.get("suppress_recapture") or item.get("capture_allowed") is False
    ]
    field_conflicts = [
        item for item in field_decisions.values()
        if item.get("action") == "resolve_conflict_before_capture"
    ]
    field_missing = [
        item for item in field_decisions.values()
        if item.get("action") == "capture_missing"
    ]
    field_stale = [
        item for item in field_decisions.values()
        if item.get("action") == "refresh_stale_fact"
    ]

    capture_allowed = True
    suppress_recapture = False
    tone = "muted"
    if policy == "append_series":
        action = "append_longitudinal_measurement"
        message = (
            f"{spec['label']}: agregar solo nueva medicion fechada; "
            "no recapturar ni sobrescribir baseline."
        )
        tone = "info" if targeted else "muted"
    elif conflicts and targeted:
        action = "resolve_conflict_before_capture"
        capture_allowed = False
        suppress_recapture = True
        tone = "danger"
        message = f"{spec['label']}: Ledger detecto contradiccion; resolver fuente antes de capturar."
    elif current_known and targeted and policy in {"visit_scalar", "refreshable_scalar"}:
        action = "reuse_existing_fact"
        capture_allowed = False
        suppress_recapture = True
        tone = "success"
        message = f"{spec['label']}: dato vigente en Ledger; evitar recaptura en captura longitudinal."
    elif field_suppressed and targeted:
        action = "reuse_known_fields_capture_gaps"
        capture_allowed = True
        suppress_recapture = False
        tone = "info"
        message = f"{spec['label']}: Ledger protege campos ya conocidos y deja capturar brechas o nuevo evento."
    elif stale_known and targeted:
        action = "refresh_stale_fact"
        tone = "warning"
        message = f"{spec['label']}: existe dato previo pero esta envejecido; actualizar con captura dirigida."
    elif missing and targeted:
        action = "capture_missing"
        tone = "warning"
        message = f"{spec['label']}: faltante para el carril actual; captura dirigida permitida."
    elif current_known:
        action = "existing_fact_visible_append_if_new_event"
        tone = "info"
        message = f"{spec['label']}: Ledger ya tiene dato reutilizable; capture solo si es un nuevo evento fechado."
    else:
        action = "capture_if_clinically_needed"
        message = f"{spec['label']}: sin bloqueo Ledger; usar secuencia clinica."

    return {
        "form_key": form_key,
        "label": spec.get("label"),
        "section_id": spec.get("section_id"),
        "policy": policy,
        "targeted": targeted,
        "action": action,
        "capture_allowed": capture_allowed,
        "suppress_recapture": suppress_recapture,
        "tone": tone,
        "message": message,
        "fact_keys": list(fact_keys),
        "known_fact_keys": [fact.get("fact_key") for fact in known if fact.get("fact_key")],
        "current_fact_keys": [fact.get("fact_key") for fact in current_known if fact.get("fact_key")],
        "missing_fact_keys": missing,
        "conflict_fact_keys": [fact.get("fact_key") for fact in conflicts if fact.get("fact_key")],
        "stale_fact_keys": [fact.get("fact_key") for fact in stale_known if fact.get("fact_key")],
        "field_map": field_map,
        "field_decisions": field_decisions,
        "field_decisions_list": list(field_decisions.values()),
        "field_decision_count": len(field_decisions),
        "field_suppressed_count": len(field_suppressed),
        "field_conflict_count": len(field_conflicts),
        "field_missing_count": len(field_missing),
        "field_stale_count": len(field_stale),
        "source_trace": [_fact_source_trace(fact) for fact in facts],
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
    }


def build_longitudinal_capture_ledger_context(
    patient_record: dict[str, Any] | None = None,
    *,
    ledger: dict[str, Any] | None = None,
    decision_field: str = "",
    readiness_lane: str = "",
    moment: str = "",
) -> dict[str, Any]:
    """Read-only Ledger contract for the V2 longitudinal capture surface.

    Unlike Profile V2 quick CTAs, this page is allowed to append legitimate
    time-series events. The contract therefore blocks only targeted recapture of
    already-current scalar/report facts or targeted capture over conflicts.
    """
    full_ledger = dict(ledger or build_patient_clinical_fact_ledger(patient_record or {}))
    fact_map = {
        item.get("fact_key"): item
        for item in (full_ledger.get("facts") or [])
        if isinstance(item, dict) and item.get("fact_key")
    }
    forms = [
        _build_longitudinal_capture_form_decision(
            form_key,
            spec,
            fact_map,
            decision_field=decision_field,
            readiness_lane=readiness_lane,
            moment=moment,
        )
        for form_key, spec in _LONGITUDINAL_CAPTURE_FORMS.items()
    ]
    targeted_forms = [item for item in forms if item.get("targeted")]
    suppressed_forms = [item for item in forms if item.get("suppress_recapture")]
    conflict_forms = [item for item in forms if item.get("action") == "resolve_conflict_before_capture"]
    append_series_forms = [item for item in forms if item.get("action") == "append_longitudinal_measurement"]
    field_decisions = [
        field_decision
        for form in forms
        for field_decision in (form.get("field_decisions_list") or [])
    ]
    suppressed_fields = [
        item for item in field_decisions
        if item.get("suppress_recapture") or item.get("capture_allowed") is False
    ]
    conflict_fields = [
        item for item in field_decisions
        if item.get("action") == "resolve_conflict_before_capture"
    ]
    return {
        "version": "longitudinal_capture_ledger_context_v1",
        "patient": full_ledger.get("patient") or {},
        "decision_field": decision_field or "",
        "readiness_lane": readiness_lane or "",
        "moment": moment or "",
        "summary": {
            "form_count": len(forms),
            "targeted_form_count": len(targeted_forms),
            "suppressed_form_count": len(suppressed_forms),
            "conflict_form_count": len(conflict_forms),
            "append_series_form_count": len(append_series_forms),
            "field_decision_count": len(field_decisions),
            "suppressed_field_count": len(suppressed_fields),
            "conflict_field_count": len(conflict_fields),
        },
        "forms": forms,
        "forms_by_key": {item["form_key"]: item for item in forms},
        "ui_contract": {
            "read_only": True,
            "append_only_surface": True,
            "prevent_targeted_recapture": True,
            "allow_new_time_series_measurements": True,
            "source_clinical_facts_mutated": False,
            "external_order_created": False,
            "model_trained": False,
        },
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
    }


def _reconciliation_source_option(
    source: dict[str, Any],
    *,
    source_index: int,
    current_normalized_value: str,
) -> dict[str, Any]:
    normalized_value = str(source.get("normalized_value") or "")
    return {
        "source_index": source_index,
        "fact_key": source.get("fact_key"),
        "observed_key": source.get("observed_key"),
        "value": source.get("value"),
        "normalized_value": normalized_value,
        "source_type": source.get("source_type"),
        "source_record_type": source.get("source_record_type"),
        "source_record_id": source.get("source_record_id"),
        "source_date": source.get("source_date") or "",
        "observed_at": source.get("observed_at") or "",
        "certainty_tier": source.get("certainty_tier") or "",
        "freshness_status": source.get("freshness_status") or "missing",
        "clinician_verified": bool(source.get("clinician_verified")),
        "is_current": normalized_value == current_normalized_value,
        "metadata": source.get("metadata") or {},
    }


def build_patient_clinical_fact_reconciliation_bundle(
    patient_record: dict[str, Any] | None = None,
    *,
    ledger: dict[str, Any] | None = None,
    limit: int = 24,
) -> dict[str, Any]:
    """Actionable V2 queue for clinician-led fact conflict reconciliation."""
    full_ledger = dict(ledger or build_patient_clinical_fact_ledger(patient_record or {}))
    patient = dict(full_ledger.get("patient") or {})
    conflicts = [
        item for item in (full_ledger.get("facts") or [])
        if item.get("has_conflict")
    ][: max(int(limit or 24), 1)]
    resolved_watch = [
        item for item in (full_ledger.get("facts") or [])
        if item.get("conflict_resolved_by_reconciliation")
    ][:12]
    queue = []
    for item in conflicts:
        sources = list(item.get("sources") or [])
        current_source = sources[0] if sources else {}
        current_normalized = str(current_source.get("normalized_value") or "")
        source_options = [
            _reconciliation_source_option(
                source,
                source_index=index,
                current_normalized_value=current_normalized,
            )
            for index, source in enumerate(sources)
        ]
        distinct_values = {}
        for option in source_options:
            key = option.get("normalized_value") or ""
            distinct_values.setdefault(key, {
                "normalized_value": key,
                "value": option.get("value"),
                "source_count": 0,
                "source_indices": [],
            })
            distinct_values[key]["source_count"] += 1
            distinct_values[key]["source_indices"].append(option.get("source_index"))
        queue.append({
            "fact_key": item.get("fact_key"),
            "domain": item.get("domain"),
            "blocking": bool(item.get("blocking")),
            "severity": "critical" if item.get("blocking") else "moderate",
            "current_value": item.get("current_value"),
            "current_source": item.get("current_source"),
            "current_observed_key": item.get("current_observed_key"),
            "freshness_status": item.get("freshness_status"),
            "source_count": item.get("source_count"),
            "distinct_value_count": item.get("distinct_value_count"),
            "source_options": source_options,
            "distinct_values": list(distinct_values.values()),
            "recommended_action": "Seleccionar una fuente ganadora y firmar nota clinica breve.",
        })
    return {
        "version": "clinical_fact_reconciliation_bundle_v1",
        "patient": patient,
        "summary": {
            "conflict_count": len(conflicts),
            "critical_conflict_count": sum(1 for item in conflicts if item.get("blocking")),
            "resolved_watch_count": len(resolved_watch),
            "queue_count": len(queue),
            "registered_fact_count": (full_ledger.get("summary") or {}).get("registered_fact_count"),
            "known_fact_count": (full_ledger.get("summary") or {}).get("known_fact_count"),
        },
        "queue": queue,
        "resolved_watch": [
            {
                "fact_key": item.get("fact_key"),
                "current_value": item.get("current_value"),
                "current_source": item.get("current_source"),
                "source_count": item.get("source_count"),
            }
            for item in resolved_watch
        ],
        "ui_contract": {
            "requires_clinician_signature": True,
            "creates_verified_reconciliation_fact": True,
            "original_sources_mutated": False,
            "external_order_created": False,
            "model_trained": False,
        },
        "next_action": (
            "Resolver conflictos criticos antes de DECISION HOY."
            if any(item.get("blocking") for item in conflicts)
            else "Resolver contradicciones moderadas para quitar recaptura."
            if conflicts
            else "Sin conflictos abiertos; usar facts reconciliados como fuente canonica."
        ),
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
    }


def build_clinical_fact_dictionary(*, scope: str = "summary") -> dict[str, Any]:
    specs = list(iter_registered_fact_specs())
    domains = Counter(spec.domain for spec in specs)
    items = [
        {
            "fact_key": spec.fact_key,
            "domain": spec.domain,
            "value_type": spec.value_type,
            "legacy_aliases": list(spec.legacy_aliases),
            "blocking": bool(spec.blocking),
            "consumers": list(spec.consumers),
        }
        for spec in specs
    ]
    payload = {
        "summary": {
            "registered_fact_count": len(specs),
            "blocking_fact_count": sum(1 for spec in specs if spec.blocking),
            "domain_counts": dict(sorted(domains.items())),
            "alias_count": sum(len(spec.legacy_aliases) for spec in specs),
        },
        "facts": items if scope == "full" else [],
    }
    return payload
