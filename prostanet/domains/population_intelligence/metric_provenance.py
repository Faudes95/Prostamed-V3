"""Metric provenance binding for the V2 epidemiology command center.

The epidemiology dashboard can run as a live exploratory view, but research
use requires every headline number to point back to a governed pack, hash,
dictionary fields and lineage families. This module adds that binding without
changing the clinical/statistical calculations.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

from prostanet.domains.platform_readiness.research_pack_governance import (
    build_research_pack_freeze_library,
    summarize_research_pack_freeze,
)
from prostanet.shared.utc_time import utc_now_iso


METRIC_PROVENANCE_VERSION = "metric_provenance_binding_v1"
DEIDENTIFIED_PACK_REGISTRY_TYPE = "deidentified_research_pack_v1"
TREATMENT_VALUE_REGISTRY_TYPE = "treatment_value_registry_v2"
SUPPRESSION_POLICY = "n<5 suppressed for subgroup comparisons; patient-level drill-down requires local clinical session."


METRIC_REF_MAP = {
    "primary_patients": {
        "dictionary": ["subject_id", "clinical_state", "current_treatment_regimen"],
        "facts": ["current_treatment_regimen", "clinical_state"],
        "row_families": ["fact_rows", "treatment_rows"],
    },
    "psa50_psa90": {
        "dictionary": ["baseline_psa", "current_psa", "psa_response"],
        "facts": ["baseline_psa", "current_psa"],
        "row_families": ["fact_rows", "biomarker_rows"],
    },
    "completeness": {
        "dictionary": ["baseline_psa", "ecog_performance_status", "current_treatment_regimen"],
        "facts": ["baseline_psa", "ecog_performance_status", "current_treatment_regimen"],
        "row_families": ["fact_rows", "lineage_rows"],
    },
    "open_gaps": {
        "dictionary": ["baseline_psa", "ecog_performance_status", "metastatic_stage_resolved"],
        "facts": ["baseline_psa", "ecog_performance_status", "metastatic_stage_resolved"],
        "row_families": ["fact_rows", "lineage_rows"],
    },
    "spend": {
        "dictionary": ["current_treatment_regimen", "treatment_line", "cost_trace"],
        "facts": ["current_treatment_regimen"],
        "row_families": ["treatment_rows"],
    },
    "cost_per_psa50": {
        "dictionary": ["baseline_psa", "current_psa", "current_treatment_regimen", "cost_trace"],
        "facts": ["baseline_psa", "current_psa", "current_treatment_regimen"],
        "row_families": ["fact_rows", "biomarker_rows", "treatment_rows"],
    },
    "persistence": {
        "dictionary": ["current_treatment_regimen", "treatment_line", "discontinuation"],
        "facts": ["current_treatment_regimen"],
        "row_families": ["treatment_rows", "event_rows"],
    },
    "research_grade": {
        "dictionary": ["baseline_psa", "ecog_performance_status", "metastatic_stage_resolved"],
        "facts": ["baseline_psa", "ecog_performance_status", "metastatic_stage_resolved"],
        "row_families": ["fact_rows", "lineage_rows", "event_rows"],
    },
}


def build_metric_provenance_binding(
    dashboard: Mapping[str, Any],
    *,
    source_freeze_key: str | None = None,
    freeze_limit: int = 8,
) -> dict[str, Any]:
    """Bind dashboard metrics to a live or governed-freeze provenance context."""
    requested_freeze_key = str(source_freeze_key or "").strip()
    freeze = _load_freeze(requested_freeze_key) if requested_freeze_key else None
    freeze_summary = summarize_research_pack_freeze(freeze, include_payload=False) if freeze else None
    pack_payload = freeze.get("payload") if isinstance(freeze, Mapping) else {}
    pack_bundle = _pack_bundle(pack_payload)
    pack_inventory = _pack_inventory(pack_bundle)
    metrics = _build_metric_rows(
        dashboard,
        freeze=freeze,
        freeze_summary=freeze_summary,
        pack_bundle=pack_bundle,
        pack_inventory=pack_inventory,
    )
    source_mode = "governed_freeze_bound" if freeze else "live_cohort_exploratory"
    available_freezes = build_research_pack_freeze_library(
        limit=freeze_limit,
        include_payload=False,
        include_current_preview=False,
    )
    return {
        "available": True,
        "version": METRIC_PROVENANCE_VERSION,
        "computed_at": utc_now_iso(),
        "source_mode": source_mode,
        "requested_freeze_key": requested_freeze_key,
        "source_freeze_key": freeze.get("freeze_key") if freeze else None,
        "payload_sha256": freeze.get("payload_sha256") if freeze else None,
        "registry_type": freeze.get("registry_type") if freeze else None,
        "governance": (freeze_summary or {}).get("governance") or {},
        "cohort_binding_status": _cohort_binding_status(dashboard, freeze_summary, pack_inventory),
        "suppression_policy": SUPPRESSION_POLICY,
        "summary": {
            "metric_count": len(metrics),
            "metrics_bound_to_freeze": sum(1 for item in metrics if item.get("source_freeze_key")),
            "reconstructable_metric_count": sum(
                1 for item in metrics
                if item.get("reconstruction", {}).get("status") in {"exact_pack_count", "raw_rows_available"}
            ),
            "available_freeze_count": (available_freezes.get("summary") or {}).get("freeze_count", 0),
            "no_phi_in_provenance": True,
        },
        "metrics": metrics,
        "pack_inventory": pack_inventory if freeze else {},
        "available_freezes": available_freezes.get("freezes") or [],
        "read_only": True,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "external_transfer_performed": False,
    }


def _load_freeze(freeze_key: str) -> dict[str, Any] | None:
    if not freeze_key:
        return None
    import tracking_db

    freeze = tracking_db.get_research_cohort_freeze(freeze_key)
    if not freeze:
        return None
    if freeze.get("registry_type") not in {DEIDENTIFIED_PACK_REGISTRY_TYPE, TREATMENT_VALUE_REGISTRY_TYPE}:
        return None
    return freeze


def _pack_bundle(pack_payload: Mapping[str, Any] | None) -> dict[str, Any]:
    payload = dict(pack_payload or {})
    bundle = payload.get("bundle")
    if isinstance(bundle, Mapping):
        return dict(bundle)
    if payload.get("version") == "treatment_value_research_pack_v2":
        return {
            "data_dictionary": payload.get("data_dictionary") or [],
            "fact_rows": [],
            "lineage_rows": [],
            "event_rows": [],
            "treatment_rows": payload.get("dataset", {}).get("rows") or [],
            "biomarker_rows": [],
            "registry_summary": payload.get("registry_summary") or {},
        }
    return payload


def _pack_inventory(bundle: Mapping[str, Any]) -> dict[str, Any]:
    row_families = {
        "fact_rows": bundle.get("fact_rows") or [],
        "lineage_rows": bundle.get("lineage_rows") or [],
        "event_rows": bundle.get("event_rows") or [],
        "treatment_rows": bundle.get("treatment_rows") or [],
        "biomarker_rows": bundle.get("biomarker_rows") or [],
    }
    subject_ids = sorted({
        str(row.get("subject_id") or "")
        for rows in row_families.values()
        for row in rows
        if isinstance(row, Mapping) and row.get("subject_id")
    })
    fact_counter = Counter(
        str(row.get("fact_key") or "")
        for row in row_families["fact_rows"]
        if isinstance(row, Mapping) and row.get("fact_key")
    )
    lineage_counter = Counter(
        str(row.get("fact_key") or "")
        for row in row_families["lineage_rows"]
        if isinstance(row, Mapping) and row.get("fact_key")
    )
    return {
        "subject_count_from_rows": len(subject_ids),
        "subject_refs_sample": subject_ids[:10],
        "row_counts": {key: len(rows) for key, rows in row_families.items()},
        "fact_key_counts": dict(fact_counter),
        "lineage_fact_key_counts": dict(lineage_counter),
    }


def _build_metric_rows(
    dashboard: Mapping[str, Any],
    *,
    freeze: Mapping[str, Any] | None,
    freeze_summary: Mapping[str, Any] | None,
    pack_bundle: Mapping[str, Any],
    pack_inventory: Mapping[str, Any],
) -> list[dict[str, Any]]:
    metric_specs = []
    for item in dashboard.get("executive_kpis") or []:
        key = str(item.get("key") or "")
        if not key:
            continue
        metric_specs.append(
            {
                "metric_id": f"executive.{key}",
                "metric_key": key,
                "label": item.get("label") or key,
                "value": item.get("value"),
                "n": _n_for_executive_metric(key, dashboard),
                "metric_family": "executive_kpi",
            }
        )
    for row in dashboard.get("outcome_matrix") or []:
        week = row.get("week")
        for field in (
            "n_patients",
            "psa50_rate_pct",
            "psa90_rate_pct",
            "ecog_improvement_rate_pct",
            "high_grade_toxicity_rate_pct",
            "referral_delay_rate_pct",
            "estimated_spend_to_window_mxn",
            "cost_per_psa50_responder_mxn",
        ):
            metric_specs.append(
                {
                    "metric_id": f"outcome_matrix.{week}.{field}",
                    "metric_key": _canonical_metric_key(field),
                    "label": f"{field} @{week}w",
                    "value": row.get(field),
                    "n": row.get("n_patients"),
                    "metric_family": "outcome_matrix",
                }
            )
    return [
        _bind_metric_spec(spec, freeze, freeze_summary, pack_bundle, pack_inventory)
        for spec in metric_specs
    ]


def _bind_metric_spec(
    spec: Mapping[str, Any],
    freeze: Mapping[str, Any] | None,
    freeze_summary: Mapping[str, Any] | None,
    pack_bundle: Mapping[str, Any],
    pack_inventory: Mapping[str, Any],
) -> dict[str, Any]:
    metric_key = str(spec.get("metric_key") or "")
    refs = METRIC_REF_MAP.get(metric_key, METRIC_REF_MAP.get("research_grade", {}))
    dictionary_refs = _dictionary_refs(pack_bundle.get("data_dictionary") or [], refs.get("dictionary") or [])
    lineage_refs = _lineage_refs(pack_bundle.get("lineage_rows") or [], refs.get("facts") or [])
    row_family_refs = _row_family_refs(pack_bundle, refs.get("row_families") or [])
    return {
        "metric_id": spec.get("metric_id"),
        "metric_key": metric_key,
        "metric_family": spec.get("metric_family"),
        "label": spec.get("label"),
        "value": spec.get("value"),
        "n": spec.get("n"),
        "source_mode": "governed_freeze_bound" if freeze else "live_cohort_exploratory",
        "source_freeze_key": freeze.get("freeze_key") if freeze else None,
        "payload_sha256": freeze.get("payload_sha256") if freeze else None,
        "registry_type": freeze.get("registry_type") if freeze else None,
        "governance_status": ((freeze_summary or {}).get("governance") or {}).get("governance_status"),
        "suppression_policy": SUPPRESSION_POLICY,
        "data_dictionary_refs": dictionary_refs,
        "lineage_refs": lineage_refs,
        "row_family_refs": row_family_refs,
        "subject_refs_sample": list(pack_inventory.get("subject_refs_sample") or [])[:5] if freeze else [],
        "reconstruction": _reconstruction_status(spec, freeze, refs, pack_inventory),
    }


def _canonical_metric_key(field_or_key: str) -> str:
    mapping = {
        "n_patients": "primary_patients",
        "psa50_rate_pct": "psa50_psa90",
        "psa90_rate_pct": "psa50_psa90",
        "ecog_improvement_rate_pct": "completeness",
        "high_grade_toxicity_rate_pct": "research_grade",
        "referral_delay_rate_pct": "open_gaps",
        "estimated_spend_to_window_mxn": "spend",
        "cost_per_psa50_responder_mxn": "cost_per_psa50",
    }
    return mapping.get(field_or_key, field_or_key)


def _n_for_executive_metric(key: str, dashboard: Mapping[str, Any]) -> int | None:
    primary_week = str(dashboard.get("primary_window_weeks") or "")
    primary = None
    for row in dashboard.get("outcome_matrix") or []:
        if str(row.get("week")) == primary_week:
            primary = row
            break
    if not primary:
        return None
    if key in {"primary_patients", "psa50_psa90", "spend", "cost_per_psa50"}:
        return int(primary.get("n_patients") or 0)
    if key == "completeness":
        return int((dashboard.get("completeness_tower") or {}).get("patient_count") or 0)
    if key == "open_gaps":
        return int((dashboard.get("bias_and_readiness", {}).get("capture_worklist") or {}).get("patient_count_with_gaps") or 0)
    return int(primary.get("n_patients") or 0)


def _dictionary_refs(dictionary_rows: list[Mapping[str, Any]], requested: list[str]) -> list[dict[str, Any]]:
    by_field = {
        str(row.get("field") or row.get("name") or ""): row
        for row in dictionary_rows
        if isinstance(row, Mapping)
    }
    refs = []
    for field in requested:
        row = by_field.get(field)
        if row:
            refs.append(
                {
                    "field": field,
                    "domain": row.get("domain") or row.get("source") or "",
                    "mcode_profile": row.get("mcode_profile", ""),
                    "omop_target": row.get("omop_target", ""),
                    "mapping_status": row.get("mapping_status", "mapped"),
                }
            )
        else:
            refs.append({"field": field, "mapping_status": "semantic_ref_not_in_dictionary"})
    return refs


def _lineage_refs(lineage_rows: list[Mapping[str, Any]], fact_keys: list[str]) -> list[dict[str, Any]]:
    refs = []
    for row in lineage_rows:
        if not isinstance(row, Mapping):
            continue
        if fact_keys and row.get("fact_key") not in fact_keys:
            continue
        refs.append(
            {
                "fact_key": row.get("fact_key"),
                "source_type": row.get("source_type"),
                "source_record_ref": row.get("source_record_ref"),
                "source_month": row.get("source_month"),
                "mapping_status": row.get("mapping_status"),
            }
        )
        if len(refs) >= 8:
            break
    return refs


def _row_family_refs(bundle: Mapping[str, Any], families: list[str]) -> list[dict[str, Any]]:
    refs = []
    for family in families:
        rows = bundle.get(family) or []
        refs.append({"family": family, "row_count": len(rows)})
    return refs


def _reconstruction_status(
    spec: Mapping[str, Any],
    freeze: Mapping[str, Any] | None,
    refs: Mapping[str, Any],
    pack_inventory: Mapping[str, Any],
) -> dict[str, Any]:
    if not freeze:
        return {
            "status": "live_not_frozen",
            "detail": "Metric comes from live exploratory cohort; select source_freeze_key to bind to a governed pack.",
        }
    requested_families = refs.get("row_families") or []
    row_counts = pack_inventory.get("row_counts") or {}
    has_family_data = any(int(row_counts.get(family) or 0) > 0 for family in requested_families)
    if spec.get("metric_key") == "primary_patients" and pack_inventory.get("subject_count_from_rows"):
        return {
            "status": "exact_pack_count",
            "pack_subject_count": pack_inventory.get("subject_count_from_rows"),
            "dashboard_n": spec.get("n"),
        }
    if has_family_data:
        return {
            "status": "raw_rows_available",
            "families": {family: row_counts.get(family, 0) for family in requested_families},
        }
    return {
        "status": "dictionary_only",
        "families": {family: row_counts.get(family, 0) for family in requested_families},
    }


def _cohort_binding_status(
    dashboard: Mapping[str, Any],
    freeze_summary: Mapping[str, Any] | None,
    pack_inventory: Mapping[str, Any],
) -> dict[str, Any]:
    if not freeze_summary:
        return {
            "status": "live_cohort_exploratory",
            "detail": "No governed freeze selected; metrics are live and should not be treated as a fixed research snapshot.",
        }
    primary_n = _n_for_executive_metric("primary_patients", dashboard)
    pack_n = int(
        (freeze_summary or {}).get("cohort_subject_count")
        or pack_inventory.get("subject_count_from_rows")
        or 0
    )
    if primary_n is not None and pack_n >= int(primary_n or 0):
        status = "freeze_covers_or_exceeds_dashboard_n"
    else:
        status = "freeze_contextual_binding_review_n"
    return {
        "status": status,
        "dashboard_primary_n": primary_n,
        "pack_subject_count": pack_n,
        "detail": "Use this as provenance binding; formal inference still requires matching cohort criteria and human governance review.",
    }
