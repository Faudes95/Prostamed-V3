"""Flow-level persistence QA matrix for the Clinical Fact Ledger.

This layer converts the global Ledger release gate into explicit V2 flow
contracts. It stays read-only and answers where each canonical fact must be
captured, persisted, reused, or audited before the platform grows.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Callable, Iterable, Mapping

from prostanet.domains.platform_readiness.ledger_release_gate import (
    build_ledger_release_gate,
)
from prostanet.shared.utc_time import utc_now_iso


LEDGER_PERSISTENCE_MATRIX_VERSION = "ledger_persistence_qa_matrix_v1"


def _has_any_consumer(row: Mapping[str, Any], values: set[str]) -> bool:
    return bool(set(row.get("consumers") or ()) & values)


def _all_facts(row: Mapping[str, Any]) -> bool:
    return bool(row.get("fact_key"))


def _wizard_fact(row: Mapping[str, Any]) -> bool:
    return bool(
        row.get("blocking")
        or row.get("schema_appearances_count")
        or row.get("documented_non_schema_source")
    )


def _profile_fact(row: Mapping[str, Any]) -> bool:
    return "profile" in set(row.get("consumers") or ())


def _decision_fact(row: Mapping[str, Any]) -> bool:
    return bool(
        row.get("blocking")
        or _has_any_consumer(
            row,
            {
                "decision_input_requirements",
                "localized_modality",
                "precision_pathway",
                "reconciled_state",
                "official_diagnosis",
                "gates",
            },
        )
    )


def _governance_fact(row: Mapping[str, Any]) -> bool:
    return bool(row.get("blocking") or _has_any_consumer(row, {"governance", "profile"}))


FLOW_CONTRACTS: tuple[dict[str, Any], ...] = (
    {
        "flow_key": "wizard_v2",
        "label": "Wizard V2",
        "route": "/wizard/<module_id>",
        "method": "GET",
        "selector": _wizard_fact,
        "requires_capture": True,
        "requires_persistence": False,
        "requires_extractor": False,
        "requires_no_recapture": True,
        "purpose": "Captura guiada sin recaptura ni campos irrelevantes.",
    },
    {
        "flow_key": "draft_context",
        "label": "Draft clinico",
        "route": "/api/clinical-assessments/draft",
        "method": "POST",
        "selector": _wizard_fact,
        "requires_capture": True,
        "requires_persistence": True,
        "requires_extractor": False,
        "requires_no_recapture": True,
        "purpose": "Congela payload y contexto Ledger sin contaminar input_snapshot.",
    },
    {
        "flow_key": "registration",
        "label": "Registro longitudinal",
        "route": "/api/register_patient",
        "method": "POST",
        "selector": _all_facts,
        "requires_capture": False,
        "requires_persistence": True,
        "requires_extractor": True,
        "requires_no_recapture": True,
        "purpose": "Materializa hechos clinicos reutilizables en baseline, series y patient_clinical_facts.",
    },
    {
        "flow_key": "profile_v2",
        "label": "Perfil V2",
        "route": "/patient_profile/<nss>",
        "method": "GET",
        "selector": _profile_fact,
        "requires_capture": False,
        "requires_persistence": True,
        "requires_extractor": False,
        "requires_no_recapture": False,
        "purpose": "Muestra lineage, frescura y reutilizacion oficial del paciente.",
    },
    {
        "flow_key": "decision_today",
        "label": "DECISION HOY",
        "route": "/api/patients/<patient_ref>/decision-today",
        "method": "GET",
        "selector": _decision_fact,
        "requires_capture": True,
        "requires_persistence": True,
        "requires_extractor": False,
        "requires_no_recapture": True,
        "purpose": "Evita recomendar con datos decisivos ambiguos o no persistidos.",
    },
    {
        "flow_key": "schedule",
        "label": "Schedule clinico",
        "route": "/api/patients/<patient_ref>/schedule",
        "method": "GET",
        "selector": _governance_fact,
        "requires_capture": False,
        "requires_persistence": True,
        "requires_extractor": False,
        "requires_no_recapture": False,
        "purpose": "Alinea plan de seguimiento con hechos vigentes y auditables.",
    },
    {
        "flow_key": "redecision",
        "label": "Re-decision",
        "route": "/api/redecision/today",
        "method": "GET",
        "selector": _decision_fact,
        "requires_capture": True,
        "requires_persistence": True,
        "requires_extractor": False,
        "requires_no_recapture": True,
        "purpose": "Prioriza pacientes bloqueados por datos faltantes o contradictorios.",
    },
    {
        "flow_key": "population_dashboard",
        "label": "Cohortes / epidemiologia",
        "route": "/api/population/cohort-dashboard",
        "method": "GET",
        "selector": _governance_fact,
        "requires_capture": False,
        "requires_persistence": True,
        "requires_extractor": False,
        "requires_no_recapture": False,
        "purpose": "Hace trazable cada metrica poblacional hasta fuente clinica.",
    },
)


def build_ledger_persistence_matrix(
    registry: Any | None = None,
    *,
    registered_rules: Iterable[Any] | None = None,
    scope: str = "full",
    row_limit: int = 500,
    release_gate: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the V2 flow-level persistence QA matrix."""
    scope_key = str(scope or "full").strip().lower()
    include_rows = scope_key != "summary"
    max_rows = max(50, min(int(row_limit or 500), 3000))
    registered_rule_list = list(registered_rules or [])

    gate = dict(release_gate or {})
    if not gate or "matrix" not in gate:
        gate = build_ledger_release_gate(
            registry,
            registered_rules=registered_rule_list,
            scope="full",
            field_limit=2000,
        )
    route_status = _build_route_status(registered_rule_list, release_gate=gate)

    rows: list[dict[str, Any]] = []
    for flow in FLOW_CONTRACTS:
        for fact_row in gate.get("matrix") or []:
            selector: Callable[[Mapping[str, Any]], bool] = flow["selector"]
            if not selector(fact_row):
                continue
            rows.append(_build_flow_fact_row(flow, fact_row, route_status))

    flow_summary = _build_flow_summary(rows, route_status)
    summary = _build_summary(flow_summary, rows, route_status)
    payload: dict[str, Any] = {
        "available": True,
        "source": "ledger_persistence_qa_matrix",
        "version": LEDGER_PERSISTENCE_MATRIX_VERSION,
        "computed_at": utc_now_iso(),
        "scope": "summary" if scope_key == "summary" else "full",
        "read_only": True,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "summary": summary,
        "flow_summary": flow_summary,
        "route_contracts": route_status,
        "recommendations": _build_recommendations(summary, flow_summary),
    }
    if include_rows:
        payload["matrix"] = rows[:max_rows]
    return payload


def _build_flow_fact_row(
    flow: Mapping[str, Any],
    fact_row: Mapping[str, Any],
    route_status: Mapping[str, Any],
) -> dict[str, Any]:
    route_registered = bool((route_status.get("by_flow") or {}).get(flow["flow_key"], {}).get("registered"))
    blockers: list[str] = []
    warnings: list[str] = []

    if not route_registered:
        blockers.append("flow_route_missing")
    if flow.get("requires_capture") and not _has_capture_surface(fact_row):
        if fact_row.get("blocking"):
            blockers.append("blocking_fact_not_visible_or_documented_for_flow")
        else:
            warnings.append("fact_not_visible_or_documented_for_flow")
    if flow.get("requires_persistence"):
        if fact_row.get("persistence_status") == "missing":
            if fact_row.get("blocking"):
                blockers.append("blocking_fact_without_persistence")
            else:
                warnings.append("fact_without_persistence")
        elif fact_row.get("persistence_status") != "covered_by_extractor":
            warnings.append(f"persistence_{fact_row.get('persistence_status')}")
    if flow.get("requires_extractor") and not fact_row.get("extractor_sources"):
        if fact_row.get("blocking"):
            blockers.append("blocking_fact_without_registration_extractor")
        else:
            warnings.append("fact_without_registration_extractor")
    if flow.get("requires_no_recapture") and fact_row.get("recapture_status") not in {"clean", "normalized_alias"}:
        warnings.append(str(fact_row.get("recapture_status") or "recapture_watch"))
    if fact_row.get("release_status") == "watch":
        warnings.extend(str(item) for item in fact_row.get("warnings") or [])
    if fact_row.get("release_status") == "block":
        blockers.extend(str(item) for item in fact_row.get("blockers") or ["fact_release_block"])

    status = "block" if blockers else ("watch" if warnings else "pass")
    return {
        "flow_key": flow["flow_key"],
        "flow_label": flow["label"],
        "route": flow["route"],
        "method": flow["method"],
        "route_registered": route_registered,
        "fact_key": fact_row.get("fact_key"),
        "domain": fact_row.get("domain"),
        "owner": fact_row.get("owner"),
        "blocking": bool(fact_row.get("blocking")),
        "consumers": list(fact_row.get("consumers") or []),
        "capture_status": "covered" if _has_capture_surface(fact_row) else "not_visible_or_documented",
        "persistence_status": fact_row.get("persistence_status"),
        "freshness_status": fact_row.get("freshness_status"),
        "recapture_status": fact_row.get("recapture_status"),
        "extractor_sources": list(fact_row.get("extractor_sources") or []),
        "release_gate_status": fact_row.get("release_status"),
        "flow_status": status,
        "blockers": _dedupe(blockers),
        "warnings": _dedupe(warnings),
    }


def _has_capture_surface(fact_row: Mapping[str, Any]) -> bool:
    return bool(
        int(fact_row.get("schema_appearances_count") or 0)
        or fact_row.get("documented_non_schema_source")
    )


def _build_route_status(
    registered_rules: Iterable[Any] | None,
    *,
    release_gate: Mapping[str, Any],
) -> dict[str, Any]:
    normalized: dict[str, set[str]] = {}
    for raw in registered_rules or []:
        rule = getattr(raw, "rule", None) or (raw.get("rule") if isinstance(raw, Mapping) else None)
        methods = getattr(raw, "methods", None) or (raw.get("methods") if isinstance(raw, Mapping) else None) or []
        if not rule:
            continue
        normalized.setdefault(str(rule), set()).update(str(method).upper() for method in methods)

    release_routes = {
        (str(row.get("rule") or ""), str(row.get("method") or "").upper()): bool(row.get("registered"))
        for row in ((release_gate.get("surface_contracts") or {}).get("routes") or [])
    }
    rows = []
    by_flow: dict[str, dict[str, Any]] = {}
    for flow in FLOW_CONTRACTS:
        key = (flow["route"], flow["method"])
        registered = flow["method"] in normalized.get(flow["route"], set())
        if not registered and key in release_routes:
            registered = release_routes[key]
        row = {
            "flow_key": flow["flow_key"],
            "label": flow["label"],
            "rule": flow["route"],
            "method": flow["method"],
            "registered": registered,
            "purpose": flow["purpose"],
        }
        rows.append(row)
        by_flow[flow["flow_key"]] = row
    missing = [row for row in rows if not row["registered"]]
    return {
        "flow_count": len(rows),
        "registered_count": len(rows) - len(missing),
        "missing_count": len(missing),
        "missing": missing,
        "routes": rows,
        "by_flow": by_flow,
    }


def _build_flow_summary(
    rows: list[dict[str, Any]],
    route_status: Mapping[str, Any],
) -> list[dict[str, Any]]:
    by_flow: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_flow.setdefault(str(row.get("flow_key") or ""), []).append(row)

    summaries: list[dict[str, Any]] = []
    route_by_flow = route_status.get("by_flow") or {}
    for flow in FLOW_CONTRACTS:
        flow_rows = by_flow.get(flow["flow_key"], [])
        counts = Counter(row.get("flow_status") for row in flow_rows)
        route_registered = bool((route_by_flow.get(flow["flow_key"]) or {}).get("registered"))
        flow_status = (
            "block"
            if counts.get("block") or not route_registered
            else "watch"
            if counts.get("watch")
            else "pass"
        )
        summaries.append(
            {
                "flow_key": flow["flow_key"],
                "label": flow["label"],
                "route": flow["route"],
                "method": flow["method"],
                "registered": route_registered,
                "facts_evaluated": len(flow_rows),
                "pass_count": int(counts.get("pass") or 0),
                "watch_count": int(counts.get("watch") or 0),
                "block_count": int(counts.get("block") or 0),
                "flow_status": flow_status,
                "purpose": flow["purpose"],
            }
        )
    return summaries


def _build_summary(
    flow_summary: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    route_status: Mapping[str, Any],
) -> dict[str, Any]:
    row_counts = Counter(row.get("flow_status") for row in rows)
    flow_counts = Counter(flow.get("flow_status") for flow in flow_summary)
    status = (
        "release_blocked"
        if row_counts.get("block") or route_status.get("missing_count")
        else "needs_hardening"
        if row_counts.get("watch")
        else "ready_for_next_layer"
    )
    return {
        "flow_count": len(flow_summary),
        "facts_flow_rows_total": len(rows),
        "flow_pass_count": int(flow_counts.get("pass") or 0),
        "flow_watch_count": int(flow_counts.get("watch") or 0),
        "flow_block_count": int(flow_counts.get("block") or 0),
        "fact_pass_count": int(row_counts.get("pass") or 0),
        "fact_watch_count": int(row_counts.get("watch") or 0),
        "fact_block_count": int(row_counts.get("block") or 0),
        "route_missing_count": int(route_status.get("missing_count") or 0),
        "matrix_status": status,
        "next_layer_allowed": status == "ready_for_next_layer",
    }


def _build_recommendations(
    summary: Mapping[str, Any],
    flow_summary: list[dict[str, Any]],
) -> list[dict[str, str]]:
    recommendations: list[dict[str, str]] = []
    blocked_flows = [row["label"] for row in flow_summary if row.get("flow_status") == "block"]
    watched_flows = [row["label"] for row in flow_summary if row.get("flow_status") == "watch"]
    if blocked_flows:
        recommendations.append(
            {
                "priority": "P0",
                "title": "Cerrar flujos V2 bloqueados por persistencia",
                "benefit": "Evita que un dato viaje por UI/backend sin fuente canonica o sin ruta activa.",
            }
        )
    if watched_flows:
        recommendations.append(
            {
                "priority": "P1",
                "title": "Convertir warnings por flujo en pruebas de regresion",
                "benefit": "Transforma aliases, extractores parciales y campos derivados en contratos vivos.",
            }
        )
    if summary.get("fact_watch_count"):
        recommendations.append(
            {
                "priority": "P1",
                "title": "Priorizar facts watch con alto impacto clinico",
                "benefit": "Cierra recaptura de APE/TR/patologia y prepara decisiones auditables por paciente.",
            }
        )
    recommendations.append(
        {
            "priority": "P2",
            "title": "Usar la matriz por flujo como checklist de release V2",
            "benefit": "Cada despliegue futuro debe probar wizard -> draft -> registro -> perfil -> decision -> cohorte.",
        }
    )
    return recommendations


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out
