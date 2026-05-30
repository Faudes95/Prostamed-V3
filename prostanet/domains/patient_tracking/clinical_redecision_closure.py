"""Clinical Re-Decision Closure Loop read models.

This module turns a `DECISION HOY` redecision signal into an operational,
auditable workbench payload. It does not write data, order treatment, mutate
clinical facts, or train models.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Iterable, Mapping
from urllib.parse import quote, urlencode

try:
    from prostanet.domains.patient_tracking.clinical_decision_today_fusion_kernel import (
        FIELD_LABELS,
        FIELD_TO_LANE,
    )
except Exception:  # pragma: no cover - fallback for isolated imports
    FIELD_LABELS = {}
    FIELD_TO_LANE = {}


SUPPORTED_REDECISION_STATES = {"diagnostic_workup", "localized_initial", "m1_crpc"}
REDECISION_CLOSURE_EVENT_TYPE = "clinical_redecision_closed"
ALLOWED_CLOSURE_STATUSES = {
    "resolved_after_recompute",
    "tumor_board_required",
    "followup_scheduled",
    "still_blocked",
}

STATUS_LABELS = {
    "open": "Abierta",
    "resolved_after_recompute": "Resuelta tras recálculo",
    "tumor_board_required": "Requiere Tumor Board",
    "followup_scheduled": "Seguimiento programado",
    "still_blocked": "Sigue bloqueada",
}


def build_patient_redecision_bundle(
    patient_record: Mapping[str, Any] | None,
    *,
    decision_today: Mapping[str, Any] | None,
    autodrive: Mapping[str, Any] | None = None,
    patient_ref: str = "",
) -> dict[str, Any]:
    """Build a patient-level redecision workbench bundle."""
    patient = dict(patient_record or {})
    decision_bundle = dict(decision_today or {})
    autodrive_bundle = dict(autodrive or {})
    decision = dict(decision_bundle.get("decision_today") or {})
    state = str(
        decision_bundle.get("state")
        or autodrive_bundle.get("state")
        or (patient.get("latest_assessment") or {}).get("state")
        or (patient.get("prior_history") or {}).get("current_state")
        or ""
    ).strip()
    state_label = str(
        decision_bundle.get("state_label")
        or autodrive_bundle.get("state_label")
        or state
        or "Sin clasificar"
    )
    decision_state = str(
        decision_bundle.get("decision_state")
        or decision.get("status")
        or decision.get("state")
        or ""
    ).strip()
    resolved_ref = _first_text(
        patient_ref,
        decision_bundle.get("patient_ref"),
        autodrive_bundle.get("patient_ref"),
        (patient.get("identity") or {}).get("nss"),
        patient.get("nss"),
        (patient.get("identity") or {}).get("id"),
    )
    patient_name = _first_text(
        decision_bundle.get("patient_name"),
        autodrive_bundle.get("patient_name"),
        (patient.get("identity") or {}).get("full_name"),
        patient.get("full_name"),
        "Paciente",
    )
    missing_fields = _normalize_missing_fields(
        decision_bundle.get("unified_missing_fields") or [],
        patient_ref=resolved_ref,
        fallback_lane=str(decision_bundle.get("primary_lane") or ""),
    )
    if not missing_fields:
        missing_fields = _normalize_missing_fields(
            decision_bundle.get("missing_field_keys") or [],
            patient_ref=resolved_ref,
            fallback_lane=str(decision_bundle.get("primary_lane") or ""),
        )
    if not missing_fields:
        missing_fields = _normalize_missing_fields(
            _missing_from_autodrive(autodrive_bundle),
            patient_ref=resolved_ref,
            fallback_lane="clinical_data_completion",
        )

    next_action = dict(decision_bundle.get("next_safe_action") or {})
    top_queue = _top_queue_item(autodrive_bundle)
    closure_state = latest_redecision_closure(patient.get("patient_events") or [])
    support_level = "v1_supported" if state in SUPPORTED_REDECISION_STATES else "out_of_scope_v1"
    is_active_redecision = decision_state == "redecision_required"
    queue_eligible = is_active_redecision and state in SUPPORTED_REDECISION_STATES
    priority_status = _first_text(
        top_queue.get("priority_status"),
        (autodrive_bundle.get("summary") or {}).get("priority_status"),
        "critical_today" if is_active_redecision else "watchlist",
    )
    priority_score = _priority_score(
        decision_state=decision_state,
        missing_count=len(missing_fields),
        priority_status=priority_status,
        closure_state=closure_state,
    )
    primary_missing = missing_fields[0] if missing_fields else {}
    capture_plan = _build_capture_plan(missing_fields, next_action=next_action, top_queue=top_queue)

    return {
        "available": True,
        "source": "clinical_redecision_closure_loop",
        "version": "clinical_redecision_closure_v1",
        "patient_ref": str(resolved_ref),
        "patient_name": patient_name,
        "state": state,
        "state_label": state_label,
        "support_level": support_level,
        "supported_states": sorted(SUPPORTED_REDECISION_STATES),
        "decision_state": decision_state,
        "decision_today": decision_bundle,
        "decision_title": _first_text(
            decision.get("title"),
            decision_bundle.get("title"),
            next_action.get("title"),
            "Reabrir decisión clínica",
        ),
        "clinical_rationale": _first_text(
            decision_bundle.get("clinical_rationale"),
            decision.get("rationale"),
            next_action.get("reason"),
        ),
        "risk_avoided": _first_text(decision.get("risk_avoided"), next_action.get("risk_avoided")),
        "missing_fields": missing_fields,
        "primary_missing_field": primary_missing,
        "capture_plan": capture_plan,
        "next_safe_action": next_action,
        "closure_state": closure_state,
        "queue_eligible": queue_eligible,
        "priority_status": priority_status,
        "priority_score": priority_score,
        "audit": {
            "deterministic_v1": True,
            "read_model_only": True,
            "source_clinical_facts_mutated": False,
            "external_order_created": False,
            "model_trained": False,
            "closure_event_type": REDECISION_CLOSURE_EVENT_TYPE,
        },
    }


def build_redecision_population(
    patient_bundles: Iterable[Mapping[str, Any]] | None,
    *,
    stage: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    """Build population queue from patient redecision bundles."""
    stage_filter = str(stage or "").strip().lower()
    max_limit = max(1, min(int(limit or 50), 250))
    rows: list[dict[str, Any]] = []
    for bundle in patient_bundles or []:
        if not isinstance(bundle, Mapping):
            continue
        if stage_filter and stage_filter not in str(bundle.get("state") or "").lower():
            continue
        if not bundle.get("queue_eligible"):
            continue
        rows.append(_queue_item(bundle))
    rows = sorted(
        rows,
        key=lambda item: (
            -int(item.get("priority_score") or 0),
            str(item.get("patient_ref") or ""),
        ),
    )[:max_limit]
    lane_counts: dict[str, int] = {}
    state_counts: dict[str, int] = {}
    for row in rows:
        lane = str(row.get("readiness_lane") or "sin_carril")
        lane_counts[lane] = lane_counts.get(lane, 0) + 1
        state = str(row.get("state") or "sin_estado")
        state_counts[state] = state_counts.get(state, 0) + 1
    return {
        "available": True,
        "source": "clinical_redecision_closure_loop",
        "version": "clinical_redecision_closure_population_v1",
        "scope": "full",
        "summary": {
            "queue_count": len(rows),
            "supported_states": sorted(SUPPORTED_REDECISION_STATES),
            "lane_counts": lane_counts,
            "state_counts": state_counts,
            "top_action_title": rows[0].get("title") if rows else "Sin re-decisiones activas",
        },
        "today_queue": rows,
        "redecision_triggers": rows,
        "audit": {
            "deterministic_v1": True,
            "read_model_only": True,
            "source_clinical_facts_mutated": False,
            "external_order_created": False,
            "model_trained": False,
        },
    }


def summarize_redecision_population(population: Mapping[str, Any] | None) -> dict[str, Any]:
    payload = dict(population or {})
    queue = list(payload.get("today_queue") or [])
    return {
        "available": payload.get("available", True),
        "source": payload.get("source", "clinical_redecision_closure_loop"),
        "version": payload.get("version", "clinical_redecision_closure_population_v1"),
        "scope": "summary",
        "summary": payload.get("summary") or {},
        "queue_count": len(queue),
        "today_queue": queue[:10],
        "audit": {
            "deterministic_v1": True,
            "read_model_only": True,
            "summary_payload": True,
            "source_clinical_facts_mutated": False,
            "external_order_created": False,
            "model_trained": False,
        },
    }


def latest_redecision_closure(events: Iterable[Mapping[str, Any]] | None) -> dict[str, Any]:
    closures = []
    for event in events or []:
        if not isinstance(event, Mapping):
            continue
        if str(event.get("event_type") or "") != REDECISION_CLOSURE_EVENT_TYPE:
            continue
        payload = _json_dict(event.get("payload") or event.get("payload_json") or {})
        closures.append(
            {
                "available": True,
                "event_id": event.get("id"),
                "event_date": event.get("event_date"),
                "created_at": event.get("created_at"),
                "closure_status": str(
                    payload.get("closure_status")
                    or event.get("status")
                    or "recorded"
                ),
                "closure_label": STATUS_LABELS.get(
                    str(payload.get("closure_status") or event.get("status") or ""),
                    str(payload.get("closure_status") or event.get("status") or "Registrado"),
                ),
                "reviewed_by": payload.get("reviewed_by") or "",
                "clinical_note": payload.get("clinical_note") or "",
                "next_followup_date": payload.get("next_followup_date") or "",
                "missing_fields_at_closure": list(payload.get("missing_fields_at_closure") or []),
            }
        )
    if not closures:
        return {"available": False, "closure_status": "open", "closure_label": STATUS_LABELS["open"]}
    return sorted(
        closures,
        key=lambda item: (
            str(item.get("created_at") or ""),
            str(item.get("event_date") or ""),
            int(item.get("event_id") or 0),
        ),
        reverse=True,
    )[0]


def validate_closure_request(payload: Mapping[str, Any], bundle: Mapping[str, Any]) -> tuple[bool, str, dict[str, Any]]:
    data = dict(payload or {})
    closure_status = str(data.get("closure_status") or "").strip()
    clinical_note = str(data.get("clinical_note") or "").strip()
    missing_fields = list(bundle.get("missing_fields") or [])
    acknowledged = [str(item) for item in data.get("acknowledged_missing_fields") or [] if str(item).strip()]

    if closure_status not in ALLOWED_CLOSURE_STATUSES:
        return False, "closure_status no permitido", {}
    if not clinical_note:
        return False, "clinical_note es obligatorio", {}
    if closure_status == "resolved_after_recompute" and str(bundle.get("decision_state") or "") == "redecision_required":
        return False, "No se puede cerrar como resuelta: DECISION HOY sigue en redecision_required", {}
    if closure_status == "still_blocked" and not (missing_fields or acknowledged):
        return False, "still_blocked requiere campos faltantes reconocidos", {}
    followup = str(data.get("next_followup_date") or "").strip()
    if followup:
        try:
            datetime.strptime(followup, "%Y-%m-%d")
        except ValueError:
            return False, "next_followup_date debe usar YYYY-MM-DD", {}

    normalized = {
        "closure_status": closure_status,
        "reviewed_by": str(data.get("reviewed_by") or "clinician").strip() or "clinician",
        "clinical_note": clinical_note,
        "selected_action_key": str(data.get("selected_action_key") or "").strip(),
        "acknowledged_missing_fields": acknowledged,
        "next_followup_date": followup,
    }
    return True, "", normalized


def closure_event_payload(closure: Mapping[str, Any], bundle: Mapping[str, Any]) -> dict[str, Any]:
    missing = list(bundle.get("missing_fields") or [])
    return {
        **dict(closure or {}),
        "decision_state_at_closure": bundle.get("decision_state"),
        "decision_title_at_closure": bundle.get("decision_title"),
        "patient_ref": bundle.get("patient_ref"),
        "state": bundle.get("state"),
        "missing_fields_at_closure": [item.get("field") for item in missing if isinstance(item, Mapping)],
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
    }


def _queue_item(bundle: Mapping[str, Any]) -> dict[str, Any]:
    missing = dict(bundle.get("primary_missing_field") or {})
    cta = dict((missing.get("cta") or {}) if missing else {})
    if not cta:
        cta = dict((bundle.get("next_safe_action") or {}).get("cta") or {})
    readiness_lane = str(missing.get("readiness_lane") or cta.get("readiness_lane") or "")
    return {
        "patient_ref": bundle.get("patient_ref"),
        "patient_name": bundle.get("patient_name"),
        "state": bundle.get("state"),
        "state_label": bundle.get("state_label"),
        "decision_state": bundle.get("decision_state"),
        "priority_status": bundle.get("priority_status"),
        "priority_score": bundle.get("priority_score"),
        "title": bundle.get("decision_title"),
        "reason": bundle.get("clinical_rationale"),
        "risk_avoided": bundle.get("risk_avoided"),
        "missing_field": missing.get("field") or "",
        "missing_label": missing.get("label") or "",
        "missing_count": len(bundle.get("missing_fields") or []),
        "readiness_lane": readiness_lane,
        "closure_state": bundle.get("closure_state") or {},
        "cta": cta or {
            "label": "Abrir workbench",
            "href": f"/redecision-workbench/{quote(str(bundle.get('patient_ref') or ''))}",
            "action_mode": "review",
        },
        "workbench_href": f"/redecision-workbench/{quote(str(bundle.get('patient_ref') or ''))}",
    }


def _normalize_missing_fields(
    fields: Iterable[Any],
    *,
    patient_ref: str,
    fallback_lane: str = "",
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in fields or []:
        if isinstance(raw, Mapping):
            field = str(raw.get("field") or raw.get("key") or raw.get("name") or "").strip()
            label = str(raw.get("label") or FIELD_LABELS.get(field) or field).strip()
            lane = str(raw.get("readiness_lane") or FIELD_TO_LANE.get(field) or fallback_lane or "clinical_data_completion")
            cta = dict(raw.get("cta") or {})
        else:
            field = str(raw or "").strip()
            label = str(FIELD_LABELS.get(field) or field).strip()
            lane = str(FIELD_TO_LANE.get(field) or fallback_lane or "clinical_data_completion")
            cta = {}
        if not field or field in seen:
            continue
        seen.add(field)
        if not cta.get("href"):
            query = urlencode({"decision_lane": lane, "decision_field": field})
            cta = {
                "label": "Capturar dato",
                "href": f"/longitudinal-capture/{quote(str(patient_ref))}?{query}",
                "action_mode": "capture",
                "patient_ref": str(patient_ref),
                "readiness_lane": lane,
                "decision_field": field,
            }
        rows.append(
            {
                "field": field,
                "label": label,
                "readiness_lane": lane,
                "capture_surface": "longitudinal_capture",
                "cta": cta,
            }
        )
    return rows


def _build_capture_plan(
    missing_fields: list[Mapping[str, Any]],
    *,
    next_action: Mapping[str, Any],
    top_queue: Mapping[str, Any],
) -> list[dict[str, Any]]:
    plan = [dict(item) for item in missing_fields]
    if plan:
        return plan
    for source in (next_action, top_queue):
        cta = dict(source.get("cta") or {}) if isinstance(source, Mapping) else {}
        if cta.get("href"):
            return [
                {
                    "field": str(cta.get("decision_field") or ""),
                    "label": str(source.get("label") or cta.get("label") or "Abrir acción"),
                    "readiness_lane": str(cta.get("readiness_lane") or ""),
                    "capture_surface": "longitudinal_capture" if "longitudinal-capture" in str(cta.get("href")) else "patient_profile",
                    "cta": cta,
                }
            ]
    return []


def _missing_from_autodrive(autodrive: Mapping[str, Any]) -> list[str]:
    fields: list[str] = []
    for item in list(autodrive.get("today_queue") or []) + list(autodrive.get("autodrive_actions") or []):
        if isinstance(item, Mapping):
            fields.extend(str(field) for field in item.get("missing_fields") or [] if str(field).strip())
    return fields


def _top_queue_item(autodrive: Mapping[str, Any]) -> dict[str, Any]:
    for item in autodrive.get("today_queue") or autodrive.get("autodrive_actions") or []:
        if isinstance(item, Mapping):
            return dict(item)
    return {}


def _priority_score(*, decision_state: str, missing_count: int, priority_status: str, closure_state: Mapping[str, Any]) -> int:
    score = 40
    if decision_state == "redecision_required":
        score = 96
    if priority_status == "critical_today":
        score += 8
    elif priority_status == "high_today":
        score += 5
    score += min(int(missing_count or 0), 8)
    if (closure_state or {}).get("closure_status") == "still_blocked":
        score += 3
    return min(score, 100)


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""
