"""Clinical Fact Ledger release gate.

Read-only matrix that verifies canonical facts are ready to be reused before
adding another clinical layer, integration, or population analytic surface.
"""
from __future__ import annotations

from collections import Counter
import inspect
from typing import Any, Iterable, Mapping

from prostanet.domains.platform_readiness.audit import (
    DOCUMENTED_NON_SCHEMA_FACT_SOURCES,
    build_platform_readiness_audit,
)
from prostanet.shared.clinical_fact_policies import resolve_freshness_policy
from prostanet.shared.clinical_fact_registry import (
    FACT_SPECS,
    FactSpec,
    build_legacy_shadow_payload,
    extract_canonical_fact_candidates,
)
from prostanet.shared.utc_time import utc_now_iso


LEDGER_RELEASE_GATE_VERSION = "clinical_fact_ledger_release_gate_v1"

DOMAIN_OWNERS = {
    "biochemical": "urology_oncology_data_owner",
    "diagnostic": "diagnostic_workup_owner",
    "pathology": "pathology_owner",
    "staging": "imaging_staging_owner",
    "precision": "precision_medicine_owner",
    "systemic_context": "systemic_treatment_owner",
    "metastatic_context": "metastatic_disease_owner",
    "fitness": "baseline_fitness_owner",
    "frailty": "geriatric_oncology_owner",
    "pros": "patient_reported_outcomes_owner",
    "supportive": "supportive_care_owner",
    "renal": "renal_laboratory_owner",
    "laboratory": "laboratory_owner",
    "salvage": "salvage_local_therapy_owner",
    "preferences": "shared_decision_making_owner",
}

DOMAIN_PERSISTENCE_TARGETS = {
    "biochemical": ("clinical_baseline", "biomarker_longitudinal", "patient_clinical_facts"),
    "diagnostic": ("clinical_baseline", "mri_facts", "patient_clinical_facts"),
    "pathology": ("biopsy_details", "structured_biopsy_sessions", "patient_clinical_facts"),
    "staging": ("imaging_studies", "patient_clinical_facts"),
    "precision": ("genomic_reports", "imaging_studies", "patient_clinical_facts"),
    "systemic_context": ("prior_clinical_history", "treatment_courses", "patient_clinical_facts"),
    "metastatic_context": ("clinical_baseline", "imaging_studies", "patient_clinical_facts"),
    "fitness": ("patient_demographics", "follow_ups", "patient_clinical_facts"),
    "frailty": ("patient_demographics", "follow_ups", "patient_clinical_facts"),
    "pros": ("patient_reported_outcomes", "patient_demographics", "patient_clinical_facts"),
    "supportive": ("medication_review", "follow_ups", "patient_clinical_facts"),
    "renal": ("laboratory_results", "patient_clinical_facts"),
    "laboratory": ("laboratory_results", "follow_ups", "patient_clinical_facts"),
    "salvage": ("bcr_state", "imaging_studies", "patient_clinical_facts"),
    "preferences": ("shared_decision_notes", "patient_clinical_facts"),
}

LEDGER_SURFACE_CONTRACTS = (
    {"rule": "/api/clinical-fact-ledger/dictionary", "method": "GET", "surface": "ledger_dictionary", "required": False},
    {"rule": "/api/patients/<patient_ref>/clinical-fact-ledger", "method": "GET", "surface": "ledger_patient_detail", "required": False},
    {"rule": "/api/patients/<patient_ref>/clinical-fact-ledger/summary", "method": "GET", "surface": "ledger_patient_summary", "required": True},
    {"rule": "/patient_profile/<nss>", "method": "GET", "surface": "profile_v2", "required": True},
    {"rule": "/wizard/<module_id>", "method": "GET", "surface": "wizard_v2", "required": True},
    {"rule": "/api/clinical-assessments/draft", "method": "POST", "surface": "draft_context", "required": True},
    {"rule": "/api/register_patient", "method": "POST", "surface": "registration", "required": True},
    {"rule": "/api/platform-readiness/ledger-release-gate", "method": "GET", "surface": "ledger_release_gate", "required": True},
)


def build_ledger_release_gate(
    registry: Any | None = None,
    *,
    registered_rules: Iterable[Any] | None = None,
    scope: str = "full",
    field_limit: int = 300,
    readiness_audit: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the read-only Clinical Fact Ledger release gate."""
    scope_key = str(scope or "full").strip().lower()
    include_rows = scope_key != "summary"
    row_limit = max(25, min(int(field_limit or 300), 2000))

    audit = dict(readiness_audit or {})
    if not audit or "field_matrix" not in audit:
        audit = build_platform_readiness_audit(
            registry,
            registered_rules=registered_rules or [],
            scope="full",
            field_limit=max(row_limit, len(FACT_SPECS)),
        )

    field_by_fact = {
        str(row.get("fact_key") or ""): dict(row)
        for row in audit.get("field_matrix") or []
        if row.get("fact_key")
    }
    recapture_by_fact = {
        str(row.get("fact_key") or ""): dict(row)
        for row in audit.get("recapture_aliases") or []
        if row.get("fact_key")
    }
    extractor_coverage = _build_extractor_coverage()
    route_contracts = _build_ledger_surface_contracts(
        registered_rules,
        readiness_routes=(audit.get("route_contracts") or {}).get("routes"),
    )

    rows = []
    for fact_key, spec in FACT_SPECS.items():
        rows.append(
            _build_fact_row(
                fact_key,
                spec,
                field_by_fact.get(fact_key) or {},
                recapture_by_fact.get(fact_key) or {},
                extractor_coverage.get(fact_key) or [],
                route_contracts,
            )
        )
    rows.sort(key=_row_sort_key)

    summary = _build_gate_summary(rows, audit, route_contracts)
    recommendations = _build_gate_recommendations(summary, rows, route_contracts)
    payload: dict[str, Any] = {
        "available": True,
        "source": "clinical_fact_ledger_release_gate",
        "version": LEDGER_RELEASE_GATE_VERSION,
        "computed_at": utc_now_iso(),
        "scope": "summary" if scope_key == "summary" else "full",
        "read_only": True,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "summary": summary,
        "surface_contracts": route_contracts,
        "recommendations": recommendations,
        "top_blockers": [row for row in rows if row["release_status"] == "block"][:10],
        "top_watches": [row for row in rows if row["release_status"] == "watch"][:10],
    }
    if include_rows:
        payload["matrix"] = rows[:row_limit]
        payload["domain_summary"] = _build_domain_summary(rows)
    return payload


def _build_fact_row(
    fact_key: str,
    spec: FactSpec,
    field_row: Mapping[str, Any],
    recapture_row: Mapping[str, Any],
    extractor_sources: list[str],
    surface_contracts: Mapping[str, Any],
) -> dict[str, Any]:
    documented_source = dict(DOCUMENTED_NON_SCHEMA_FACT_SOURCES.get(fact_key) or {})
    schema_appearances_count = int(field_row.get("schema_appearances_count") or 0)
    captured_or_documented = bool(schema_appearances_count or documented_source)
    persistence_targets = list(DOMAIN_PERSISTENCE_TARGETS.get(spec.domain) or ("patient_clinical_facts",))
    persistence_status = _persistence_status(
        captured_or_documented=captured_or_documented,
        documented_source=documented_source,
        extractor_sources=extractor_sources,
    )
    freshness_policy = resolve_freshness_policy(fact_key)
    freshness_status = _freshness_contract_status(freshness_policy)
    surface_status, surface_warnings = _surface_status(spec, surface_contracts)
    recapture_status = _recapture_status(recapture_row, extractor_sources)

    blockers: list[str] = []
    warnings: list[str] = []
    if spec.blocking and not captured_or_documented:
        blockers.append("blocking_fact_without_capture_surface")
    if spec.blocking and persistence_status == "missing":
        blockers.append("blocking_fact_without_persistence_or_documented_source")
    if spec.blocking and surface_status == "missing":
        blockers.append("blocking_fact_without_required_ui_api_surface")
    if freshness_status == "missing" and spec.blocking:
        warnings.append("blocking_fact_has_incomplete_freshness_policy")
    if persistence_status in {"contract_defined", "documented_non_schema_source"}:
        warnings.append(f"persistence_{persistence_status}")
    if not extractor_sources and not documented_source:
        warnings.append("canonical_extractor_not_declared")
    if recapture_status not in {"clean", "normalized_alias"}:
        warnings.append(recapture_status)
    warnings.extend(surface_warnings)
    if not spec.consumers:
        warnings.append("no_declared_downstream_consumers")

    release_status = "block" if blockers else ("watch" if warnings else "pass")
    return {
        "fact_key": fact_key,
        "domain": spec.domain,
        "owner": DOMAIN_OWNERS.get(spec.domain, f"{spec.domain}_owner"),
        "value_type": spec.value_type,
        "blocking": bool(spec.blocking),
        "consumers": list(spec.consumers or []),
        "coverage_status": field_row.get("coverage_status") or (
            "documented_non_schema_source" if documented_source else "not_seen_in_module_schemas"
        ),
        "schema_appearances_count": schema_appearances_count,
        "modules_count": int(field_row.get("modules_count") or 0),
        "modules": list(field_row.get("modules") or []),
        "legacy_aliases": list(field_row.get("legacy_aliases") or spec.legacy_aliases or []),
        "legacy_alias_schema_fields": list(field_row.get("legacy_alias_schema_fields") or []),
        "direct_schema_fields": list(field_row.get("direct_schema_fields") or []),
        "documented_non_schema_source": documented_source,
        "persistence_targets": persistence_targets,
        "persistence_status": persistence_status,
        "extractor_sources": extractor_sources,
        "freshness_policy": freshness_policy,
        "freshness_status": freshness_status,
        "recapture_status": recapture_status,
        "recapture_detail": dict(recapture_row),
        "surface_status": surface_status,
        "release_status": release_status,
        "blockers": blockers,
        "warnings": _dedupe(warnings),
    }


def _build_extractor_coverage() -> dict[str, list[str]]:
    sources = {
        "intake_or_wizard_extractor": _safe_source(extract_canonical_fact_candidates),
        "legacy_shadow_payload": _safe_source(build_legacy_shadow_payload),
    }
    coverage: dict[str, list[str]] = {}
    for fact_key in FACT_SPECS:
        hits = [
            name
            for name, source in sources.items()
            if f'"{fact_key}"' in source or f"'{fact_key}'" in source
        ]
        if fact_key in DOCUMENTED_NON_SCHEMA_FACT_SOURCES:
            hits.append("documented_non_schema_or_derived_source")
        if hits:
            coverage[fact_key] = hits
    return coverage


def _safe_source(func: Any) -> str:
    try:
        return inspect.getsource(func)
    except Exception:
        return ""


def _persistence_status(
    *,
    captured_or_documented: bool,
    documented_source: Mapping[str, Any],
    extractor_sources: list[str],
) -> str:
    if extractor_sources:
        return "covered_by_extractor"
    if documented_source:
        return "documented_non_schema_source"
    if captured_or_documented:
        return "contract_defined"
    return "missing"


def _freshness_contract_status(policy: Mapping[str, Any]) -> str:
    if not policy.get("expires"):
        return "non_expiring"
    if policy.get("current_days") is not None and policy.get("aging_days") is not None:
        return "defined"
    return "missing"


def _recapture_status(recapture_row: Mapping[str, Any], extractor_sources: list[str]) -> str:
    if recapture_row.get("same_module_recapture"):
        return "same_module_watch"
    if recapture_row.get("alias_field_names_seen"):
        if extractor_sources:
            return "normalized_alias"
        return "alias_watch"
    return "clean"


def _surface_status(spec: FactSpec, surface_contracts: Mapping[str, Any]) -> tuple[str, list[str]]:
    missing_surfaces: list[str] = []
    surface_by_name = {
        str(row.get("surface") or ""): bool(row.get("registered"))
        for row in surface_contracts.get("routes") or []
    }
    for surface in ("ledger_patient_summary", "draft_context", "registration"):
        if not surface_by_name.get(surface):
            missing_surfaces.append(surface)
    if "profile" in (spec.consumers or ()) and not surface_by_name.get("profile_v2"):
        missing_surfaces.append("profile_v2")
    if missing_surfaces:
        return "missing", [f"surface_missing:{surface}" for surface in missing_surfaces]
    return "covered", []


def _build_ledger_surface_contracts(
    registered_rules: Iterable[Any] | None,
    *,
    readiness_routes: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    normalized: dict[str, set[str]] = {}
    if registered_rules is not None:
        for raw in registered_rules:
            rule = getattr(raw, "rule", None) or (raw.get("rule") if isinstance(raw, Mapping) else None)
            methods = getattr(raw, "methods", None) or (raw.get("methods") if isinstance(raw, Mapping) else None) or []
            if not rule:
                continue
            normalized.setdefault(str(rule), set()).update(str(method).upper() for method in methods)

    readiness_lookup: dict[tuple[str, str], bool] = {}
    for route in readiness_routes or []:
        readiness_lookup[
            (str(route.get("rule") or ""), str(route.get("method") or "").upper())
        ] = bool(route.get("registered"))

    rows: list[dict[str, Any]] = []
    for contract in LEDGER_SURFACE_CONTRACTS:
        key = (contract["rule"], contract["method"])
        available = contract["method"] in normalized.get(contract["rule"], set())
        if not available and key in readiness_lookup:
            available = readiness_lookup[key]
        rows.append({**contract, "registered": available})
    missing = [row for row in rows if not row["registered"] and row.get("required")]
    optional_missing = [row for row in rows if not row["registered"] and not row.get("required")]
    return {
        "surface_count": len(rows),
        "registered_count": len(rows) - len(missing) - len(optional_missing),
        "missing_count": len(missing),
        "optional_missing_count": len(optional_missing),
        "missing": missing,
        "optional_missing": optional_missing,
        "routes": rows,
    }


def _build_gate_summary(
    rows: list[dict[str, Any]],
    readiness_audit: Mapping[str, Any],
    surface_contracts: Mapping[str, Any],
) -> dict[str, Any]:
    status_counts = Counter(row["release_status"] for row in rows)
    critical_rows = [row for row in rows if row.get("blocking")]
    critical_blocks = [row for row in critical_rows if row["release_status"] == "block"]
    readiness_summary = readiness_audit.get("summary") or {}
    route_missing = int(surface_contracts.get("missing_count") or 0)
    release_status = (
        "release_blocked"
        if critical_blocks or status_counts.get("block") or route_missing
        else "needs_hardening"
        if status_counts.get("watch")
        else "ready_for_next_layer"
    )
    return {
        "facts_total": len(rows),
        "critical_fact_count": len(critical_rows),
        "pass_count": int(status_counts.get("pass") or 0),
        "watch_count": int(status_counts.get("watch") or 0),
        "block_count": int(status_counts.get("block") or 0),
        "critical_block_count": len(critical_blocks),
        "recapture_watch_count": sum(
            1 for row in rows if row.get("recapture_status") not in {"clean", "normalized_alias"}
        ),
        "persistence_watch_count": sum(
            1 for row in rows if row.get("persistence_status") != "covered_by_extractor"
        ),
        "freshness_missing_count": sum(1 for row in rows if row.get("freshness_status") == "missing"),
        "surface_missing_count": route_missing,
        "readiness_status": readiness_summary.get("readiness_status"),
        "release_gate_status": release_status,
        "next_layer_allowed": release_status == "ready_for_next_layer",
    }


def _build_domain_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_domain: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_domain.setdefault(row["domain"], []).append(row)
    summary = []
    for domain, items in sorted(by_domain.items()):
        counts = Counter(item["release_status"] for item in items)
        summary.append(
            {
                "domain": domain,
                "owner": DOMAIN_OWNERS.get(domain, f"{domain}_owner"),
                "facts_total": len(items),
                "pass_count": int(counts.get("pass") or 0),
                "watch_count": int(counts.get("watch") or 0),
                "block_count": int(counts.get("block") or 0),
            }
        )
    return summary


def _build_gate_recommendations(
    summary: Mapping[str, Any],
    rows: list[dict[str, Any]],
    surface_contracts: Mapping[str, Any],
) -> list[dict[str, str]]:
    recommendations: list[dict[str, str]] = []
    if summary.get("block_count"):
        recommendations.append(
            {
                "priority": "P0",
                "title": "Cerrar blockers de facts canónicos antes de nuevas capas",
                "benefit": "Evita conectar genómica, FHIR/OMOP o analítica sobre datos no persistidos o no visibles.",
            }
        )
    if surface_contracts.get("missing_count"):
        recommendations.append(
            {
                "priority": "P0",
                "title": "Registrar las superficies Ledger/V2 faltantes",
                "benefit": "Mantiene coherente el contrato UI/backend para perfil V2, wizard, intake y API de Ledger.",
            }
        )
    if summary.get("recapture_watch_count"):
        recommendations.append(
            {
                "priority": "P1",
                "title": "Resolver alias con riesgo de recaptura",
                "benefit": "Reduce doble captura de APE/PSA, TR, patología y variables de seguimiento sin perder compatibilidad legacy.",
            }
        )
    if summary.get("persistence_watch_count"):
        recommendations.append(
            {
                "priority": "P1",
                "title": "Materializar extractores canónicos pendientes",
                "benefit": "Convierte campos ya capturados en hechos reutilizables por DECISION HOY, perfil V2 y tableros poblacionales.",
            }
        )
    blocking_watch = [row for row in rows if row.get("blocking") and row.get("release_status") == "watch"]
    if blocking_watch:
        recommendations.append(
            {
                "priority": "P1",
                "title": "Endurecer facts bloqueantes en vigilancia",
                "benefit": "Permite que el siguiente salto se base en evidencia clínica suficiente y auditada.",
            }
        )
    recommendations.append(
        {
            "priority": "P2",
            "title": "Usar este gate como requisito de release",
            "benefit": "Hace explícito cuándo ProstaNet puede avanzar a interoperabilidad, investigación o más automatización.",
        }
    )
    return recommendations


def _row_sort_key(row: Mapping[str, Any]) -> tuple[int, int, str, str]:
    status_rank = {"block": 0, "watch": 1, "pass": 2}
    return (
        status_rank.get(str(row.get("release_status") or ""), 3),
        0 if row.get("blocking") else 1,
        str(row.get("domain") or ""),
        str(row.get("fact_key") or ""),
    )


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out
