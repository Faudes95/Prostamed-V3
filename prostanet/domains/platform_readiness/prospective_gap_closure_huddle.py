"""Weekly huddle workbench for closing prospective pilot capture gaps.

This layer is intentionally event-only. It turns missing fields identified by
the adoption command center into a clinical operations queue, and lets the team
document review without inventing clinical values or hiding unresolved gaps.
"""
from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter
from datetime import date
from typing import Any, Mapping

from prostanet.domains.platform_readiness.pilot_adoption_command_center import (
    build_pilot_adoption_command_center,
)
from prostanet.shared.utc_time import utc_now_iso


PROSPECTIVE_GAP_CLOSURE_HUDDLE_VERSION = "prospective_gap_closure_huddle_v1"

ALLOWED_CLOSURE_STATUSES = {
    "reviewed_still_missing",
    "capture_completed_elsewhere",
    "not_applicable",
    "deferred",
}

DIRECT_IDENTIFIER_KEYS = {
    "full_name",
    "name",
    "patient_name",
    "dob",
    "date_of_birth",
    "birth_date",
}


def build_prospective_gap_closure_huddle(
    *,
    scope: str = "summary",
    limit: int = 100,
    status: str | None = None,
    family: str | None = None,
    adoption_command_center: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the huddle queue derived from current V2 capture gaps."""
    scope_key = "summary" if str(scope or "").strip().lower() == "summary" else "full"
    safe_limit = max(1, min(int(limit or 100), 500))
    adoption = dict(
        adoption_command_center
        or build_pilot_adoption_command_center(scope="full", limit=safe_limit)
    )
    items = _build_huddle_items(adoption.get("patient_worklist") or [])
    closure_lookup = _load_gap_closure_events(items)
    enriched = [_attach_closure_state(item, closure_lookup) for item in items]
    status_filter = str(status or "").strip()
    family_filter = str(family or "").strip()
    if status_filter:
        enriched = [
            item for item in enriched
            if item.get("huddle_status") == status_filter
            or item.get("closure_status") == status_filter
        ]
    if family_filter:
        enriched = [item for item in enriched if item.get("gap_family") == family_filter]
    enriched = sorted(
        enriched,
        key=lambda item: (
            _priority_rank(item.get("priority")),
            item.get("huddle_status") != "open",
            item.get("subject_id") or "",
            item.get("gap_key") or "",
        ),
    )
    summary = _build_summary(enriched, adoption)
    payload: dict[str, Any] = {
        "available": True,
        "source": "pilot_adoption_gap_closure_huddle",
        "version": PROSPECTIVE_GAP_CLOSURE_HUDDLE_VERSION,
        "computed_at": utc_now_iso(),
        "scope": scope_key,
        "read_only": True,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "external_transfer_performed": False,
        "clinical_internal_surface": True,
        "summary": summary,
        "status_options": sorted(ALLOWED_CLOSURE_STATUSES),
        "filters": {
            "status": status_filter,
            "family": family_filter,
            "limit": safe_limit,
        },
        "family_summary": _build_family_summary(enriched),
        "weekly_export_preview": _build_no_phi_export_rows(enriched[:safe_limit]),
        "recommended_huddle_actions": _build_recommended_actions(summary, enriched),
        "summary_no_phi_scan": _scan_for_phi(
            {
                "summary": summary,
                "family_summary": _build_family_summary(enriched),
                "weekly_export_preview": _build_no_phi_export_rows(enriched[:safe_limit]),
            }
        ),
    }
    if scope_key == "full":
        payload["huddle_items"] = enriched[:safe_limit]
        payload["close_contract"] = {
            "required_fields": ["patient_ref", "gap_key", "closure_status", "reviewed_by", "clinical_note"],
            "closure_statuses": sorted(ALLOWED_CLOSURE_STATUSES),
            "writes_only": "patient_events.event_type=pilot_gap_reviewed",
            "source_clinical_facts_mutated": False,
        }
    return payload


def close_prospective_gap_huddle_item(data: Mapping[str, Any]) -> dict[str, Any]:
    """Persist an auditable huddle review event without mutating source facts."""
    raw = dict(data or {})
    raw_scan = _scan_for_phi(raw)
    if raw_scan.get("no_phi_status") != "pass":
        return _error("phi_like_content_rejected", no_phi_scan=raw_scan)
    patient_ref = _clean_text(raw.get("patient_ref"), "")
    gap_key = _clean_text(raw.get("gap_key"), "")
    closure_status = _clean_text(raw.get("closure_status"), "").lower()
    reviewed_by = _clean_text(raw.get("reviewed_by"), "")
    clinical_note = _clean_text(raw.get("clinical_note"), "")
    if not patient_ref:
        return _error("patient_ref_required")
    if not gap_key:
        return _error("gap_key_required")
    if closure_status not in ALLOWED_CLOSURE_STATUSES:
        return _error("unsupported_closure_status", allowed_statuses=sorted(ALLOWED_CLOSURE_STATUSES))
    if not reviewed_by:
        return _error("reviewed_by_required")
    if len(clinical_note) < 6:
        return _error("clinical_note_required")
    identity = _resolve_patient_identity(patient_ref)
    if not identity:
        return _error("patient_not_found")

    current_item = _find_current_gap_item(patient_ref=patient_ref, gap_key=gap_key)
    if not current_item:
        current_item = {
            "patient_ref": patient_ref,
            "subject_id": _subject_id(int(identity["id"])),
            "gap_key": gap_key,
            "gap_label": _clean_text(raw.get("gap_label"), gap_key),
            "gap_family": _clean_text(raw.get("gap_family"), ""),
            "capture_route": "",
            "profile_url": f"/patient_profile/{patient_ref}?v=2",
        }
    payload = {
        "version": PROSPECTIVE_GAP_CLOSURE_HUDDLE_VERSION,
        "patient_ref_hash": _subject_id(int(identity["id"])),
        "gap_key": gap_key,
        "gap_label": current_item.get("gap_label") or gap_key,
        "gap_family": current_item.get("gap_family") or "",
        "closure_status": closure_status,
        "reviewed_by": reviewed_by,
        "clinical_note": clinical_note,
        "selected_action": _clean_text(raw.get("selected_action"), ""),
        "capture_surface": _capture_surface(current_item.get("capture_route")),
        "reviewed_at": utc_now_iso(),
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "external_transfer_performed": False,
        "gap_still_visible_if_missing": True,
    }
    import tracking_db

    event_id = tracking_db.record_patient_event(
        int(identity["id"]),
        event_type="pilot_gap_reviewed",
        event_date=date.today().isoformat(),
        state_context=current_item.get("effective_state") or "",
        management_track="pilot_gap_closure_huddle",
        source_type="platform_readiness_huddle",
        status=closure_status,
        payload=payload,
        mcode_focus={"resource": "clinical-operations-gap-review"},
    )
    if not event_id:
        return _error("event_write_failed")
    refreshed = build_prospective_gap_closure_huddle(scope="full", limit=100)
    refreshed_item = _find_item_in_payload(refreshed, patient_ref=patient_ref, gap_key=gap_key)
    if not refreshed_item:
        current_item = dict(current_item)
        current_item["huddle_status"] = "reviewed_still_open"
        current_item["closure_status"] = closure_status
        current_item["reviewed_by"] = reviewed_by
        current_item["reviewed_at"] = payload["reviewed_at"]
        current_item["gap_still_visible_if_missing"] = True
    return {
        "success": True,
        "version": PROSPECTIVE_GAP_CLOSURE_HUDDLE_VERSION,
        "event_id": event_id,
        "closure_status": closure_status,
        "huddle_item": refreshed_item or current_item,
        "summary": refreshed.get("summary") or {},
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "external_transfer_performed": False,
    }


def build_prospective_gap_huddle_csv_bytes(
    huddle: Mapping[str, Any] | None = None,
) -> bytes:
    payload = dict(huddle or build_prospective_gap_closure_huddle(scope="full", limit=500))
    rows = _build_no_phi_export_rows(payload.get("huddle_items") or [])
    output = io.StringIO()
    fieldnames = [
        "subject_id",
        "gap_key",
        "gap_label",
        "gap_family",
        "priority",
        "huddle_status",
        "closure_status",
        "capture_surface",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in fieldnames})
    return output.getvalue().encode("utf-8")


def _build_huddle_items(worklist: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for patient in worklist:
        for missing in patient.get("missing_fields") or []:
            gap_key = str(missing.get("key") or "")
            if not gap_key:
                continue
            completeness = float(patient.get("completeness_pct") or 0)
            priority = (
                "high" if gap_key in {"psa_any", "psa_history"} or completeness < 60
                else "medium" if gap_key in {"treatment_context", "testosterone", "ecog_score"}
                else "routine"
            )
            items.append(
                {
                    "patient_ref": patient.get("patient_ref"),
                    "subject_id": patient.get("subject_id"),
                    "profile_url": patient.get("profile_url"),
                    "effective_state": patient.get("effective_state"),
                    "latest_assessment_module": patient.get("latest_assessment_module"),
                    "completeness_pct": completeness,
                    "gap_key": gap_key,
                    "gap_label": missing.get("label") or gap_key,
                    "gap_family": missing.get("family") or "",
                    "capture_route": missing.get("capture_route") or "",
                    "priority": priority,
                }
            )
    return items


def _load_gap_closure_events(items: list[Mapping[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    refs = sorted({str(item.get("patient_ref") or "") for item in items if item.get("patient_ref")})
    if not refs:
        return {}
    conn = _connect()
    try:
        placeholders = ",".join("?" for _ in refs)
        rows = conn.execute(
            f"""
            SELECT e.patient_id, i.nss AS patient_ref, e.event_type, e.event_date,
                   e.status, e.payload_json, e.created_at
            FROM patient_events e
            JOIN patient_identity i ON i.id = e.patient_id
            WHERE i.nss IN ({placeholders})
              AND e.event_type = 'pilot_gap_reviewed'
            ORDER BY e.created_at DESC, e.id DESC
            """,
            refs,
        ).fetchall()
    finally:
        conn.close()
    lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        item = dict(row)
        payload = _parse_json_blob(item.get("payload_json"), {})
        gap_key = str(payload.get("gap_key") or "")
        key = (str(item.get("patient_ref") or ""), gap_key)
        if gap_key and key not in lookup:
            lookup[key] = {
                "closure_status": item.get("status") or payload.get("closure_status") or "",
                "reviewed_by": payload.get("reviewed_by") or "",
                "reviewed_at": payload.get("reviewed_at") or item.get("created_at") or "",
                "clinical_note": payload.get("clinical_note") or "",
                "event_date": item.get("event_date") or "",
            }
    return lookup


def _attach_closure_state(
    item: Mapping[str, Any],
    lookup: Mapping[tuple[str, str], Mapping[str, Any]],
) -> dict[str, Any]:
    enriched = dict(item)
    closure = dict(lookup.get((str(item.get("patient_ref") or ""), str(item.get("gap_key") or ""))) or {})
    closure_status = str(closure.get("closure_status") or "")
    enriched["closure_status"] = closure_status
    enriched["reviewed_by"] = closure.get("reviewed_by") or ""
    enriched["reviewed_at"] = closure.get("reviewed_at") or ""
    enriched["huddle_status"] = "reviewed_still_open" if closure_status else "open"
    enriched["gap_still_visible_if_missing"] = True
    return enriched


def _build_summary(items: list[Mapping[str, Any]], adoption: Mapping[str, Any]) -> dict[str, Any]:
    open_count = sum(1 for item in items if item.get("huddle_status") == "open")
    reviewed_count = len(items) - open_count
    high_count = sum(1 for item in items if item.get("priority") == "high")
    patient_count = len({item.get("subject_id") for item in items if item.get("subject_id")})
    adoption_summary = adoption.get("summary") or {}
    return {
        "huddle_item_count": len(items),
        "patient_with_gap_count": patient_count,
        "open_gap_count": open_count,
        "reviewed_gap_count": reviewed_count,
        "high_priority_gap_count": high_count,
        "adoption_patient_count": adoption_summary.get("patient_count") or 0,
        "adoption_registry_ready_pct": adoption_summary.get("registry_ready_pct") or 0,
        "adoption_psa_history_coverage_pct": adoption_summary.get("psa_history_coverage_pct") or 0,
        "huddle_status": "clear" if not items else ("active_with_review" if reviewed_count else "active"),
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "external_transfer_performed": False,
    }


def _build_family_summary(items: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_family: Counter[str] = Counter(str(item.get("gap_family") or "unknown") for item in items)
    return [
        {"family": family, "gap_count": count}
        for family, count in by_family.most_common()
    ]


def _build_no_phi_export_rows(items: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for item in items:
        rows.append(
            {
                "subject_id": item.get("subject_id"),
                "gap_key": item.get("gap_key"),
                "gap_label": item.get("gap_label"),
                "gap_family": item.get("gap_family"),
                "priority": item.get("priority"),
                "huddle_status": item.get("huddle_status") or "open",
                "closure_status": item.get("closure_status") or "",
                "capture_surface": _capture_surface(item.get("capture_route")),
            }
        )
    return rows


def _build_recommended_actions(
    summary: Mapping[str, Any],
    items: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if int(summary.get("open_gap_count") or 0):
        actions.append(
            {
                "priority": "high",
                "title": "Revisar brechas abiertas en huddle semanal",
                "action": f"{summary.get('open_gap_count')} brechas siguen sin revision humana.",
                "route": "/platform-readiness#pilot-gap-huddle-workbench",
            }
        )
    top = items[0] if items else {}
    if top:
        actions.append(
            {
                "priority": top.get("priority") or "medium",
                "title": f"Cerrar {top.get('gap_label')}",
                "action": "Abrir la superficie V2 indicada y documentar cierre o diferimiento.",
                "route": top.get("capture_route") or "/patients",
            }
        )
    if float(summary.get("adoption_psa_history_coverage_pct") or 0) < 80:
        actions.append(
            {
                "priority": "high",
                "title": "Subir cobertura de historial APE",
                "action": "Priorizar brechas APE porque desbloquean seguimiento, outcomes y registro epidemiologico.",
                "route": "/patients",
            }
        )
    return actions[:5]


def _find_current_gap_item(*, patient_ref: str, gap_key: str) -> dict[str, Any] | None:
    huddle = build_prospective_gap_closure_huddle(scope="full", limit=500)
    return _find_item_in_payload(huddle, patient_ref=patient_ref, gap_key=gap_key)


def _find_item_in_payload(
    payload: Mapping[str, Any],
    *,
    patient_ref: str,
    gap_key: str,
) -> dict[str, Any] | None:
    for item in payload.get("huddle_items") or []:
        if str(item.get("patient_ref") or "") == patient_ref and str(item.get("gap_key") or "") == gap_key:
            return dict(item)
    return None


def _resolve_patient_identity(patient_ref: str) -> dict[str, Any] | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id, nss FROM patient_identity WHERE nss = ? LIMIT 1",
            (str(patient_ref),),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _connect():
    import tracking_db

    return tracking_db._connect()


def _error(error: str, **extra: Any) -> dict[str, Any]:
    return {
        "success": False,
        "error": error,
        **extra,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "external_transfer_performed": False,
    }


def _scan_for_phi(value: Any) -> dict[str, Any]:
    hits: list[str] = []
    direct_keys: list[str] = []

    def walk(node: Any, path: str = "") -> None:
        if isinstance(node, Mapping):
            for key, child in node.items():
                key_text = str(key)
                child_path = f"{path}.{key_text}" if path else key_text
                if key_text.lower() in DIRECT_IDENTIFIER_KEYS:
                    direct_keys.append(child_path)
                walk(child, child_path)
            return
        if isinstance(node, list):
            for index, child in enumerate(node):
                walk(child, f"{path}[{index}]")
            return
        text = str(node or "")
        if "/patient_profile/" in text:
            hits.append(path or "value")
        if (
            not _is_hash_like_path(path)
            and not _is_allowed_internal_identifier_path(path)
            and re.search(r"\b\d{10,11}\b", text)
        ):
            hits.append(path or "value")

    walk(value)
    return {
        "direct_identifier_key_count": len(set(direct_keys)),
        "exact_phi_hit_count": len(set(hits)),
        "direct_identifier_keys": sorted(set(direct_keys)),
        "exact_phi_hits": sorted(set(hits)),
        "no_phi_status": "pass" if not direct_keys and not hits else "block",
    }


def _parse_json_blob(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value or "")
    except (TypeError, ValueError):
        return default


def _capture_surface(route: Any) -> str:
    text = str(route or "")
    if "longitudinal-capture" in text:
        return "longitudinal_capture_v2"
    if "patient_profile" in text:
        return "patient_profile_v2"
    if "/wizard/" in text:
        return "wizard_v2"
    return "platform"


def _priority_rank(value: Any) -> int:
    return {"high": 0, "medium": 1, "routine": 2}.get(str(value or ""), 3)


def _clean_text(value: Any, default: str) -> str:
    text = " ".join(str(value or "").strip().split())
    return text or default


def _subject_id(patient_id: int) -> str:
    import hashlib

    return "sub_" + hashlib.sha256(f"prostanet-pilot-adoption:{int(patient_id)}".encode("utf-8")).hexdigest()[:16]


def _is_hash_like_path(path: str) -> bool:
    lowered = str(path or "").lower()
    return any(token in lowered for token in ("subject_id", "sha256", "hash", "checksum", "patient_ref_hash"))


def _is_allowed_internal_identifier_path(path: str) -> bool:
    return str(path or "").lower() in {"patient_ref"}


__all__ = [
    "build_prospective_gap_closure_huddle",
    "close_prospective_gap_huddle_item",
    "build_prospective_gap_huddle_csv_bytes",
]
