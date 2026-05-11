from __future__ import annotations

from datetime import date
from typing import Any

from prostanet.shared.clinical_fact_policies import certainty_rank, compute_freshness_status
from prostanet.shared.clinical_fact_registry import build_legacy_shadow_payload, extract_canonical_fact_candidates


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No documentado", "Desconocido", "Desconocida", "unknown", "UNKNOWN")


def _parse_date_tuple(value: Any) -> tuple[int, int, int]:
    text = str(value or "")[:10]
    if len(text) != 10 or text.count("-") != 2:
        return (0, 0, 0)
    try:
        year, month, day = text.split("-")
        return (int(year), int(month), int(day))
    except ValueError:
        return (0, 0, 0)


def _candidate_priority(item: dict[str, Any]) -> tuple[int, tuple[int, int, int], tuple[int, int, int], int]:
    return (
        certainty_rank(item.get("certainty_tier")),
        _parse_date_tuple(item.get("source_date")),
        _parse_date_tuple(item.get("observed_at")),
        int(item.get("id") or 0),
    )


def _normalize_fact_record(item: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(item or {})
    if "value_json" in normalized and "value" not in normalized:
        normalized["value"] = normalized.get("value_json")
    if "resolved_value" in normalized and "value" not in normalized:
        normalized["value"] = normalized.get("resolved_value")
    return normalized


def resolve_patient_clinical_facts(
    patient: dict[str, Any],
    *,
    include_inactive: bool = False,
    reference_date: date | None = None,
) -> dict[str, Any]:
    stored_facts = [_normalize_fact_record(item) for item in list(patient.get("patient_clinical_facts") or [])]
    active_facts = [
        item
        for item in stored_facts
        if include_inactive or bool(item.get("is_active", 1))
    ]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in active_facts:
        fact_key = str(item.get("fact_key") or "").strip()
        if not fact_key:
            continue
        grouped.setdefault(fact_key, []).append(item)

    legacy_shadow = build_legacy_shadow_payload(patient)
    fallback_candidates = extract_canonical_fact_candidates(
        legacy_shadow,
        source_type="derived",
        source_record_type="legacy_shadow",
        source_record_id=None,
        source_date=str((patient.get("identity") or {}).get("diagnosis_date") or ""),
        observed_at=str((patient.get("identity") or {}).get("diagnosis_date") or ""),
        state_context=str((patient.get("prior_history") or {}).get("current_state") or ""),
        management_track=str((patient.get("prior_history") or {}).get("management_track") or ""),
        certainty_tier="derived",
    )
    for item in fallback_candidates:
        fact_key = str(item.get("fact_key") or "").strip()
        if fact_key and fact_key not in grouped:
            grouped.setdefault(fact_key, []).append(item)

    resolved_facts: list[dict[str, Any]] = []
    field_values: dict[str, Any] = {}
    for fact_key, items in grouped.items():
        if not items:
            continue
        winner = max(items, key=_candidate_priority)
        freshness_status = winner.get("freshness_status")
        freshness_expires_at = winner.get("freshness_expires_at")
        if not freshness_status:
            freshness_status, freshness_expires_at = compute_freshness_status(
                fact_key,
                source_date=winner.get("source_date"),
                observed_at=winner.get("observed_at"),
                reference_date=reference_date,
            )
        resolved = {
            **winner,
            "fact_key": fact_key,
            "resolved_value": winner.get("value"),
            "resolved_from_fact_key": fact_key,
            "freshness_status": freshness_status,
            "freshness_expires_at": freshness_expires_at,
            "source_type": winner.get("source_type") or "derived",
            "source_record_type": winner.get("source_record_type") or "",
            "source_record_id": winner.get("source_record_id"),
            "source_date": winner.get("source_date") or winner.get("observed_at") or "",
            "observed_at": winner.get("observed_at") or winner.get("source_date") or "",
            "certainty_tier": winner.get("certainty_tier") or "derived",
            "active_versions": len([item for item in items if bool(item.get("is_active", 1))]),
        }
        resolved_facts.append(resolved)
        field_values[fact_key] = resolved.get("resolved_value")

    freshness_summary = build_fact_freshness_summary(resolved_facts)
    return {
        "available": bool(resolved_facts),
        "facts": sorted(resolved_facts, key=lambda item: str(item.get("fact_key") or "")),
        "field_values": field_values,
        "freshness_summary": freshness_summary,
    }


def build_fact_freshness_summary(facts: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {"current": 0, "aging": 0, "stale": 0, "unknown": 0}
    stale_blocking = []
    for item in list(facts or []):
        status = str(item.get("freshness_status") or "unknown")
        if status not in counts:
            status = "unknown"
        counts[status] += 1
        if status in {"aging", "stale"} and item.get("blocking"):
            stale_blocking.append(str(item.get("fact_key") or ""))
    return {
        "available": bool(facts),
        "counts": counts,
        "blocking_facts_not_current": list(dict.fromkeys(stale_blocking)),
        "all_current": counts["aging"] == 0 and counts["stale"] == 0 and counts["unknown"] == 0,
    }


def build_fact_conflict_summary(conflicts: list[dict[str, Any]]) -> dict[str, Any]:
    normalized = [dict(item) for item in list(conflicts or [])]
    unresolved = [item for item in normalized if str(item.get("resolution_status") or "open") not in {"resolved", "dismissed"}]
    severity_counts = {"info": 0, "moderate": 0, "critical": 0}
    for item in unresolved:
        severity = str(item.get("severity") or "moderate")
        if severity not in severity_counts:
            severity = "moderate"
        severity_counts[severity] += 1
    return {
        "available": bool(normalized),
        "total_conflicts": len(normalized),
        "open_conflicts": len(unresolved),
        "severity_counts": severity_counts,
        "critical_open_conflicts": severity_counts["critical"],
        "conflicts": normalized,
    }


def resolve_fact_value(
    patient: dict[str, Any],
    fact_key: str,
    *,
    default: Any = None,
    require_current: bool = False,
) -> Any:
    bundle = resolve_patient_clinical_facts(patient)
    for item in list(bundle.get("facts") or []):
        if str(item.get("fact_key") or "") != str(fact_key or ""):
            continue
        if require_current and str(item.get("freshness_status") or "") != "current":
            return default
        return item.get("resolved_value")
    return default
