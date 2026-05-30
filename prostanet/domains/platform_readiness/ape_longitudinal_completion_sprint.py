"""APE longitudinal completion sprint for the prospective pilot.

This read model focuses the platform-readiness huddle on the most valuable
longitudinal prerequisite in prostate cancer: reusable PSA/APE history. It
does not capture clinical values. The official write surface remains
``/longitudinal-capture/<patient_ref>?decision_field=psa_history``.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from collections import Counter
from typing import Any, Mapping

from prostanet.domains.platform_readiness.pilot_adoption_command_center import (
    build_pilot_adoption_command_center,
)
from prostanet.domains.platform_readiness.prospective_gap_closure_huddle import (
    build_prospective_gap_closure_huddle,
)
from prostanet.shared.utc_time import utc_now_iso


APE_LONGITUDINAL_COMPLETION_SPRINT_VERSION = "ape_longitudinal_completion_sprint_v1"
APE_CAPTURE_IMPACT_LOOP_VERSION = "ape_capture_impact_loop_v1"

DIRECT_IDENTIFIER_KEYS = {
    "nss",
    "full_name",
    "name",
    "patient_name",
    "dob",
    "date_of_birth",
    "birth_date",
    "patient_id",
    "patient_ref",
    "profile_url",
    "capture_url",
}

PSA_FACT_KEYS = ("baseline_psa", "current_psa")


def build_ape_longitudinal_completion_sprint(
    *,
    scope: str = "summary",
    limit: int = 100,
    real_only: bool = False,
    adoption_command_center: Mapping[str, Any] | None = None,
    gap_huddle: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a read-only sprint queue for closing APE history gaps."""
    scope_key = "summary" if str(scope or "").strip().lower() == "summary" else "full"
    safe_limit = max(1, min(int(limit or 100), 500))
    adoption = dict(
        adoption_command_center
        or build_pilot_adoption_command_center(scope="full", limit=safe_limit, real_only=real_only)
    )
    huddle = dict(
        gap_huddle
        or build_prospective_gap_closure_huddle(
            scope="full",
            limit=safe_limit,
            family="biochemical",
            adoption_command_center=adoption,
        )
    )
    rows = _load_patient_rows(limit=safe_limit, real_only=real_only)
    context = _load_context([int(row["id"]) for row in rows])
    huddle_lookup = _build_huddle_lookup(huddle.get("huddle_items") or [])
    patient_rows = [
        _build_patient_ape_row(row, context, huddle_lookup)
        for row in rows
    ]
    focused_rows = sorted(
        [row for row in patient_rows if row.get("ape_status") != "history_ready"],
        key=lambda row: (
            _priority_rank(row.get("priority")),
            row.get("subject_id") or "",
        ),
    )
    summary = _build_summary(patient_rows, focused_rows, adoption, huddle)
    payload: dict[str, Any] = {
        "available": True,
        "source": "clinical_fact_ledger_v2_ape_longitudinal_completion",
        "version": APE_LONGITUDINAL_COMPLETION_SPRINT_VERSION,
        "computed_at": utc_now_iso(),
        "scope": scope_key,
        "read_only": True,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "external_transfer_performed": False,
        "clinical_internal_surface": True,
        "official_capture_surface": "/longitudinal-capture/<patient_ref>?decision_field=psa_history",
        "summary": summary,
        "status_summary": _build_status_summary(patient_rows),
        "weekly_export_preview": _build_no_phi_export_rows(focused_rows[:safe_limit]),
        "recommended_next_actions": _build_recommended_actions(
            summary,
            focused_rows,
            include_patient_routes=scope_key == "full",
        ),
        "summary_no_phi_scan": _scan_for_phi(
            {
                "summary": summary,
                "status_summary": _build_status_summary(patient_rows),
                "weekly_export_preview": _build_no_phi_export_rows(focused_rows[:safe_limit]),
            }
        ),
    }
    if scope_key == "full":
        payload["ape_worklist"] = focused_rows[:safe_limit]
        payload["trace_contract"] = {
            "official_capture_surface": "/longitudinal-capture/<patient_ref>?decision_field=psa_history",
            "profile_surface": "/patient_profile/<patient_ref>?v=2",
            "clinical_values_captured_here": False,
            "writes_only": "none",
            "source_clinical_facts_mutated": False,
            "duplicate_psa_capture_allowed": False,
        }
    return payload


def build_patient_ape_completion_snapshot(patient_ref: str) -> dict[str, Any]:
    """Build the current APE completion state for one patient.

    This is intentionally a read model. It does not write biomarkers, facts,
    orders, external exports, or model artifacts. It exists so write surfaces
    can show the impact of a longitudinal PSA/APE append without duplicating
    capture logic.
    """
    row = _load_patient_row_by_ref(str(patient_ref or "").strip())
    if not row:
        return {
            "available": False,
            "version": APE_LONGITUDINAL_COMPLETION_SPRINT_VERSION,
            "patient_ref": str(patient_ref or ""),
            "error": "patient_not_found",
            "read_only": True,
            "source_clinical_facts_mutated": False,
            "external_order_created": False,
            "model_trained": False,
            "external_transfer_performed": False,
        }
    context = _load_context([int(row["id"])])
    patient_row = _build_patient_ape_row(row, context, {})
    return {
        "available": True,
        "version": APE_LONGITUDINAL_COMPLETION_SPRINT_VERSION,
        "computed_at": utc_now_iso(),
        "read_only": True,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "external_transfer_performed": False,
        "clinical_internal_surface": True,
        "patient_ref": patient_row.get("patient_ref"),
        "subject_id": patient_row.get("subject_id"),
        "ape_status": patient_row.get("ape_status"),
        "priority": patient_row.get("priority"),
        "effective_state": patient_row.get("effective_state"),
        "psa_point_count": patient_row.get("psa_point_count"),
        "valid_psa_point_count": patient_row.get("valid_psa_point_count"),
        "dated_psa_point_count": patient_row.get("dated_psa_point_count"),
        "missing_sample_date_count": patient_row.get("missing_sample_date_count"),
        "baseline_source": patient_row.get("baseline_source"),
        "baseline_sample_date": patient_row.get("baseline_sample_date"),
        "registry_unlock_potential": bool(patient_row.get("registry_unlock_potential")),
        "capture_url": patient_row.get("capture_url"),
        "profile_url": patient_row.get("profile_url"),
        "ledger_lineage": patient_row.get("ledger_lineage") or [],
        "after_capture_expected": patient_row.get("after_capture_expected") or {},
        "capture_surface": patient_row.get("capture_surface"),
        "no_duplicate_capture_policy": patient_row.get("no_duplicate_capture_policy"),
    }


def build_ape_capture_impact(
    patient_ref: str,
    *,
    before_snapshot: Mapping[str, Any] | None = None,
    kind: str = "psa",
    append_result: Mapping[str, Any] | None = None,
    recompute_result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare APE completion before and after a longitudinal write."""
    before = dict(before_snapshot or build_patient_ape_completion_snapshot(patient_ref))
    after = build_patient_ape_completion_snapshot(patient_ref)
    before_status = before.get("ape_status") or ""
    after_status = after.get("ape_status") or ""
    before_points = int(before.get("valid_psa_point_count") or 0)
    after_points = int(after.get("valid_psa_point_count") or 0)
    gap_closed = before_status != "history_ready" and after_status == "history_ready"
    status_changed = before_status != after_status
    point_delta = after_points - before_points
    recompute = dict(recompute_result or {})
    arpi_windows = dict(recompute.get("arpi_response_windows") or {})
    refreshed_surfaces = [
        "patient_profile_v2_psa_tower",
        "ape_longitudinal_completion_sprint",
        "clinical_fact_ledger_lineage",
    ]
    if recompute.get("success"):
        refreshed_surfaces.extend(["decision_today", "patient_autodrive"])
    if arpi_windows:
        refreshed_surfaces.append("arpi_response_windows")
    return {
        "available": bool(after.get("available")),
        "version": APE_CAPTURE_IMPACT_LOOP_VERSION,
        "computed_at": utc_now_iso(),
        "patient_ref": str(patient_ref or ""),
        "kind_appended": str(kind or ""),
        "read_only_impact_model": True,
        "append_success": bool((append_result or {}).get("success")),
        "appended_id": (append_result or {}).get("appended_id"),
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "external_transfer_performed": False,
        "before": _impact_snapshot_summary(before),
        "after": _impact_snapshot_summary(after),
        "point_count_delta": point_delta,
        "status_changed": status_changed,
        "gap_closed": gap_closed,
        "registry_ready_after_capture": after_status == "history_ready",
        "registry_unlock_now": gap_closed and bool(after.get("registry_unlock_potential")),
        "recompute_success": bool(recompute.get("success")),
        "decision_changed": bool(recompute.get("decision_changed")),
        "alerts_count": int(recompute.get("alerts_count") or 0),
        "arpi_response_windows": arpi_windows,
        "refreshed_surfaces": refreshed_surfaces,
        "next_surfaces": {
            "profile_v2": after.get("profile_url") or f"/patient_profile/{patient_ref}?v=2",
            "sprint": "/platform-readiness#ape-longitudinal-completion-sprint",
            "decision_today": f"/api/patients/{patient_ref}/decision-today",
            "longitudinal_capture": after.get("capture_url") or f"/longitudinal-capture/{patient_ref}?decision_field=psa_history",
        },
        "clinical_message": _impact_message(
            before_status=before_status,
            after_status=after_status,
            point_delta=point_delta,
            gap_closed=gap_closed,
        ),
    }


def build_ape_longitudinal_completion_csv_bytes(
    sprint: Mapping[str, Any] | None = None,
) -> bytes:
    """Return a no-PHI CSV for the weekly APE completion sprint."""
    payload = dict(sprint or build_ape_longitudinal_completion_sprint(scope="full", limit=500))
    rows = _build_no_phi_export_rows(payload.get("ape_worklist") or [])
    output = io.StringIO()
    fieldnames = [
        "subject_id",
        "ape_status",
        "priority",
        "effective_state",
        "psa_point_count",
        "valid_psa_point_count",
        "baseline_source",
        "registry_unlock_potential",
        "capture_surface",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in fieldnames})
    return output.getvalue().encode("utf-8")


def _connect():
    import tracking_db

    return tracking_db._connect()


def _load_patient_rows(*, limit: int, real_only: bool) -> list[dict[str, Any]]:
    conn = _connect()
    try:
        where = "WHERE COALESCE(is_synthetic, 1) = 0" if real_only else ""
        rows = conn.execute(
            f"""
            SELECT id, nss, diagnosis_date, created_at,
                   COALESCE(is_synthetic, 1) AS is_synthetic
            FROM patient_identity
            {where}
            ORDER BY COALESCE(created_at, '') DESC, id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _load_patient_row_by_ref(patient_ref: str) -> dict[str, Any] | None:
    if not patient_ref:
        return None
    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT id, nss, diagnosis_date, created_at,
                   COALESCE(is_synthetic, 1) AS is_synthetic
            FROM patient_identity
            WHERE nss = ?
            LIMIT 1
            """,
            (patient_ref,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _load_context(patient_ids: list[int]) -> dict[str, Any]:
    from collections import defaultdict

    context: dict[str, Any] = {
        "facts_by_patient": defaultdict(dict),
        "biomarkers_by_patient": defaultdict(list),
        "assessments_by_patient": defaultdict(list),
        "prior_history_by_patient": {},
    }
    if not patient_ids:
        return context
    placeholders = ",".join("?" for _ in patient_ids)
    conn = _connect()
    try:
        for row in conn.execute(
            f"""
            SELECT patient_id, fact_key, normalized_value_text, source_type,
                   source_record_type, source_record_id, source_date,
                   observed_at, freshness_status, clinician_verified, updated_at
            FROM patient_clinical_facts
            WHERE patient_id IN ({placeholders}) AND COALESCE(is_active, 1) = 1
            ORDER BY patient_id ASC, fact_key ASC, updated_at DESC, id DESC
            """,
            patient_ids,
        ).fetchall():
            item = dict(row)
            context["facts_by_patient"][int(item["patient_id"])].setdefault(str(item["fact_key"]), item)
        for row in conn.execute(
            f"""
            SELECT patient_id, biomarker_type, value, unit, sample_date,
                   lab_source, created_at
            FROM biomarker_longitudinal
            WHERE patient_id IN ({placeholders})
            ORDER BY patient_id ASC, COALESCE(sample_date, '') ASC, id ASC
            """,
            patient_ids,
        ).fetchall():
            item = dict(row)
            context["biomarkers_by_patient"][int(item["patient_id"])].append(item)
        for row in conn.execute(
            f"""
            SELECT id, patient_id, module_id, state, status, created_at
            FROM clinical_assessments
            WHERE patient_id IN ({placeholders})
            ORDER BY patient_id ASC, COALESCE(created_at, '') DESC, id DESC
            """,
            patient_ids,
        ).fetchall():
            item = dict(row)
            context["assessments_by_patient"][int(item["patient_id"])].append(item)
        prior_columns = _table_columns(conn, "prior_clinical_history")
        if "patient_id" in prior_columns:
            selected = [
                column for column in (
                    "patient_id",
                    "current_state",
                    "management_track",
                    "latest_assessment_id",
                    "assessment_module",
                    "assessment_state",
                )
                if column in prior_columns
            ]
            for row in conn.execute(
                f"""
                SELECT {', '.join(selected)}
                FROM prior_clinical_history
                WHERE patient_id IN ({placeholders})
                """,
                patient_ids,
            ).fetchall():
                item = dict(row)
                context["prior_history_by_patient"][int(item["patient_id"])] = item
    finally:
        conn.close()
    return context


def _build_patient_ape_row(
    row: Mapping[str, Any],
    context: Mapping[str, Any],
    huddle_lookup: Mapping[tuple[str, str], Mapping[str, Any]],
) -> dict[str, Any]:
    patient_id = int(row["id"])
    patient_ref = str(row.get("nss") or "")
    facts = dict((context.get("facts_by_patient") or {}).get(patient_id) or {})
    biomarkers = list((context.get("biomarkers_by_patient") or {}).get(patient_id) or [])
    assessments = list((context.get("assessments_by_patient") or {}).get(patient_id) or [])
    prior_history = dict((context.get("prior_history_by_patient") or {}).get(patient_id) or {})
    state = _effective_state(assessments, prior_history)
    psa_points = [
        item for item in biomarkers
        if str(item.get("biomarker_type") or "").upper() == "PSA"
    ]
    valid_points = [item for item in psa_points if _as_float(item.get("value")) is not None]
    dated_points = [item for item in valid_points if str(item.get("sample_date") or "").strip()]
    psa_facts = {key: dict(facts.get(key) or {}) for key in PSA_FACT_KEYS if facts.get(key)}
    status = _classify_ape_status(psa_points, valid_points, dated_points, psa_facts)
    priority = _priority_for_status(status, state)
    baseline = _select_baseline(psa_facts, dated_points, valid_points)
    huddle_item = dict(
        huddle_lookup.get((patient_ref, "psa_history"))
        or huddle_lookup.get((patient_ref, "psa_any"))
        or {}
    )
    capture_url = _capture_url(patient_ref, state)
    profile_url = f"/patient_profile/{patient_ref}?v=2" if patient_ref else ""
    registry_unlock_potential = status != "history_ready" and bool(assessments)
    return {
        "patient_ref": patient_ref,
        "subject_id": _subject_id(patient_id),
        "profile_url": profile_url,
        "capture_url": capture_url,
        "effective_state": state,
        "latest_assessment_module": (assessments[0] or {}).get("module_id") if assessments else prior_history.get("assessment_module") or "",
        "created_at": row.get("created_at") or "",
        "is_synthetic": bool(row.get("is_synthetic")),
        "ape_status": status,
        "priority": priority,
        "psa_point_count": len(psa_points),
        "valid_psa_point_count": len(valid_points),
        "dated_psa_point_count": len(dated_points),
        "missing_sample_date_count": max(len(valid_points) - len(dated_points), 0),
        "ledger_psa_fact_count": len(psa_facts),
        "baseline_value": baseline.get("value"),
        "baseline_sample_date": baseline.get("sample_date") or "",
        "baseline_source": baseline.get("source") or "",
        "ledger_lineage": _ledger_lineage(psa_facts),
        "huddle_status": huddle_item.get("huddle_status") or ("open" if status != "history_ready" else "not_needed"),
        "huddle_gap_key": huddle_item.get("gap_key") or ("psa_history" if status != "missing_psa" else "psa_any"),
        "registry_unlock_potential": registry_unlock_potential,
        "after_capture_expected": _after_capture_expected(status, registry_unlock_potential),
        "capture_surface": "longitudinal_capture_v2",
        "no_duplicate_capture_policy": "reuse existing baseline/current PSA and append only missing longitudinal points",
    }


def _classify_ape_status(
    psa_points: list[Mapping[str, Any]],
    valid_points: list[Mapping[str, Any]],
    dated_points: list[Mapping[str, Any]],
    psa_facts: Mapping[str, Mapping[str, Any]],
) -> str:
    if not psa_points and not psa_facts:
        return "missing_psa"
    if psa_points and not valid_points:
        return "uninterpretable_series"
    if valid_points and len(dated_points) < len(valid_points):
        return "missing_sample_date"
    if not psa_points and psa_facts:
        return "isolated_psa_snapshot"
    if len(valid_points) == 1:
        return "single_psa_point"
    if len(valid_points) < 2:
        return "insufficient_history"
    return "history_ready"


def _priority_for_status(status: str, state: str) -> str:
    if status in {"missing_psa", "uninterpretable_series"}:
        return "critical"
    if status in {"single_psa_point", "isolated_psa_snapshot", "missing_sample_date", "insufficient_history"}:
        return "high"
    if "crpc" in str(state or "").lower() and status != "history_ready":
        return "high"
    return "routine"


def _select_baseline(
    psa_facts: Mapping[str, Mapping[str, Any]],
    dated_points: list[Mapping[str, Any]],
    valid_points: list[Mapping[str, Any]],
) -> dict[str, Any]:
    baseline_fact = dict(psa_facts.get("baseline_psa") or {})
    if baseline_fact:
        return {
            "value": baseline_fact.get("normalized_value_text") or "",
            "sample_date": baseline_fact.get("source_date") or baseline_fact.get("observed_at") or "",
            "source": baseline_fact.get("source_type") or baseline_fact.get("source_record_type") or "patient_clinical_facts",
        }
    ordered = sorted(
        dated_points or valid_points,
        key=lambda item: str(item.get("sample_date") or item.get("created_at") or ""),
    )
    if not ordered:
        return {"value": "", "sample_date": "", "source": ""}
    point = dict(ordered[0])
    return {
        "value": point.get("value"),
        "sample_date": point.get("sample_date") or "",
        "source": point.get("lab_source") or "biomarker_longitudinal",
    }


def _ledger_lineage(psa_facts: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    lineage = []
    for fact_key in PSA_FACT_KEYS:
        fact = dict(psa_facts.get(fact_key) or {})
        if not fact:
            continue
        lineage.append(
            {
                "fact_key": fact_key,
                "source_type": fact.get("source_type") or "",
                "source_record_type": fact.get("source_record_type") or "",
                "source_date": fact.get("source_date") or fact.get("observed_at") or "",
                "freshness_status": fact.get("freshness_status") or "",
                "clinician_verified": bool(fact.get("clinician_verified")),
            }
        )
    return lineage


def _build_huddle_lookup(items: list[Mapping[str, Any]]) -> dict[tuple[str, str], Mapping[str, Any]]:
    lookup: dict[tuple[str, str], Mapping[str, Any]] = {}
    for item in items:
        patient_ref = str(item.get("patient_ref") or "")
        gap_key = str(item.get("gap_key") or "")
        if patient_ref and gap_key:
            lookup[(patient_ref, gap_key)] = item
    return lookup


def _build_summary(
    patient_rows: list[Mapping[str, Any]],
    focused_rows: list[Mapping[str, Any]],
    adoption: Mapping[str, Any],
    huddle: Mapping[str, Any],
) -> dict[str, Any]:
    patient_count = len(patient_rows)
    missing_count = sum(1 for row in patient_rows if row.get("ape_status") == "missing_psa")
    single_count = sum(1 for row in patient_rows if row.get("ape_status") == "single_psa_point")
    isolated_count = sum(1 for row in patient_rows if row.get("ape_status") == "isolated_psa_snapshot")
    date_missing_count = sum(1 for row in patient_rows if row.get("ape_status") == "missing_sample_date")
    uninterpretable_count = sum(1 for row in patient_rows if row.get("ape_status") == "uninterpretable_series")
    ready_count = sum(1 for row in patient_rows if row.get("ape_status") == "history_ready")
    unlock_count = sum(1 for row in focused_rows if row.get("registry_unlock_potential"))
    high_count = sum(1 for row in focused_rows if row.get("priority") in {"critical", "high"})
    adoption_summary = adoption.get("summary") or {}
    huddle_summary = huddle.get("summary") or {}
    status = (
        "no_patients_captured" if patient_count == 0
        else "ape_history_ready" if not focused_rows
        else "ape_completion_sprint_active"
    )
    return {
        "patient_count": patient_count,
        "ape_gap_patient_count": len(focused_rows),
        "missing_psa_patient_count": missing_count,
        "single_psa_patient_count": single_count,
        "isolated_psa_snapshot_patient_count": isolated_count,
        "missing_sample_date_patient_count": date_missing_count,
        "uninterpretable_series_patient_count": uninterpretable_count,
        "history_ready_patient_count": ready_count,
        "psa_history_coverage_pct": _pct(ready_count, patient_count),
        "adoption_psa_history_coverage_pct": adoption_summary.get("psa_history_coverage_pct") or 0,
        "potential_registry_unlock_count": unlock_count,
        "high_priority_ape_gap_count": high_count,
        "huddle_open_gap_count": huddle_summary.get("open_gap_count") or 0,
        "sprint_status": status,
        "clinical_values_captured_here": False,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "external_transfer_performed": False,
    }


def _build_status_summary(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter(str(row.get("ape_status") or "unknown") for row in rows)
    return [
        {
            "ape_status": status,
            "patient_count": count,
            "priority": _priority_for_status(status, ""),
        }
        for status, count in counter.most_common()
    ]


def _build_no_phi_export_rows(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    export_rows = []
    for row in rows:
        export_rows.append(
            {
                "subject_id": row.get("subject_id"),
                "ape_status": row.get("ape_status"),
                "priority": row.get("priority"),
                "effective_state": row.get("effective_state"),
                "psa_point_count": row.get("psa_point_count"),
                "valid_psa_point_count": row.get("valid_psa_point_count"),
                "baseline_source": row.get("baseline_source"),
                "registry_unlock_potential": bool(row.get("registry_unlock_potential")),
                "capture_surface": row.get("capture_surface") or "longitudinal_capture_v2",
            }
        )
    return export_rows


def _build_recommended_actions(
    summary: Mapping[str, Any],
    rows: list[Mapping[str, Any]],
    *,
    include_patient_routes: bool,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if int(summary.get("missing_psa_patient_count") or 0):
        actions.append(
            {
                "priority": "critical",
                "title": "Recuperar APE no documentado",
                "action": f"{summary.get('missing_psa_patient_count')} pacientes no tienen APE reutilizable en Ledger ni serie longitudinal.",
                "route": "/platform-readiness#ape-longitudinal-completion-sprint",
            }
        )
    if int(summary.get("single_psa_patient_count") or 0) or int(summary.get("isolated_psa_snapshot_patient_count") or 0):
        actions.append(
            {
                "priority": "high",
                "title": "Convertir APE aislado en serie",
                "action": "Abrir captura longitudinal para agregar fechas/mediciones sin recapturar el baseline.",
                "route": "/platform-readiness#ape-longitudinal-completion-sprint",
            }
        )
    top = rows[0] if rows else {}
    if top:
        actions.append(
            {
                "priority": top.get("priority") or "high",
                "title": f"Cerrar {top.get('ape_status')}",
                "action": "Abrir longitudinal capture V2 y confirmar lineage en Perfil V2.",
                "route": (top.get("capture_url") if include_patient_routes else "/platform-readiness#ape-longitudinal-completion-sprint") or "/patients",
            }
        )
    return actions[:5]


def _effective_state(assessments: list[Mapping[str, Any]], prior_history: Mapping[str, Any]) -> str:
    if assessments:
        latest = dict(assessments[0] or {})
        return str(latest.get("state") or latest.get("module_id") or "")
    return str(
        prior_history.get("current_state")
        or prior_history.get("assessment_state")
        or prior_history.get("assessment_module")
        or "unknown"
    )


def _capture_url(patient_ref: str, state: str) -> str:
    if not patient_ref:
        return "/patients"
    lane = str(state or "pilot").strip() or "pilot"
    return f"/longitudinal-capture/{patient_ref}?decision_lane={lane}&decision_field=psa_history"


def _after_capture_expected(status: str, registry_unlock_potential: bool) -> dict[str, Any]:
    return {
        "target_status": "history_ready",
        "minimum_points_required": 2,
        "registry_ready_may_unlock": bool(registry_unlock_potential),
        "expected_effect": (
            "DECISION HOY, Perfil V2, ARPI value y tablero epidemiologico reutilizan la misma serie APE."
            if status != "history_ready"
            else "Sin captura adicional requerida."
        ),
    }


def _table_columns(conn: Any, table_name: str) -> set[str]:
    try:
        return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    except Exception:
        return set()


def _pct(part: int, total: int) -> float:
    return round((float(part) / float(total)) * 100, 1) if total else 0.0


def _as_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _priority_rank(value: Any) -> int:
    return {"critical": 0, "high": 1, "medium": 2, "routine": 3}.get(str(value or ""), 4)


def _subject_id(patient_id: int) -> str:
    return "sub_" + hashlib.sha256(f"prostanet-pilot-adoption:{int(patient_id)}".encode("utf-8")).hexdigest()[:16]


def _impact_snapshot_summary(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "available": bool(snapshot.get("available")),
        "ape_status": snapshot.get("ape_status") or "",
        "priority": snapshot.get("priority") or "",
        "effective_state": snapshot.get("effective_state") or "",
        "psa_point_count": int(snapshot.get("psa_point_count") or 0),
        "valid_psa_point_count": int(snapshot.get("valid_psa_point_count") or 0),
        "dated_psa_point_count": int(snapshot.get("dated_psa_point_count") or 0),
        "missing_sample_date_count": int(snapshot.get("missing_sample_date_count") or 0),
        "registry_unlock_potential": bool(snapshot.get("registry_unlock_potential")),
        "baseline_source": snapshot.get("baseline_source") or "",
        "baseline_sample_date": snapshot.get("baseline_sample_date") or "",
    }


def _impact_message(
    *,
    before_status: str,
    after_status: str,
    point_delta: int,
    gap_closed: bool,
) -> str:
    if gap_closed:
        return "APE longitudinal completo: la torre V2 y el sprint poblacional ya pueden reutilizar la serie."
    if point_delta > 0 and after_status == "single_psa_point":
        return "APE guardado como primer punto longitudinal; falta al menos una medicion fechada adicional para cerrar historia."
    if point_delta > 0:
        return "APE longitudinal actualizado; revisar si la fecha/valor adicional cierra criterios de seguimiento."
    if before_status == after_status:
        return "Sin cambio en completitud APE; verificar duplicado, fecha o calidad del dato."
    return "Estado APE actualizado."


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
        if "/patient_profile/" in text or "/longitudinal-capture/" in text:
            hits.append(path or "value")
        if not _is_hash_like_path(path) and re.search(r"\b\d{10,11}\b", text):
            hits.append(path or "value")

    walk(value)
    return {
        "direct_identifier_key_count": len(set(direct_keys)),
        "exact_phi_hit_count": len(set(hits)),
        "direct_identifier_keys": sorted(set(direct_keys)),
        "exact_phi_hits": sorted(set(hits)),
        "no_phi_status": "pass" if not direct_keys and not hits else "block",
    }


def _is_hash_like_path(path: str) -> bool:
    lowered = str(path or "").lower()
    return any(token in lowered for token in ("subject_id", "sha256", "hash", "checksum", "patient_ref_hash"))


__all__ = [
    "build_ape_longitudinal_completion_sprint",
    "build_ape_longitudinal_completion_csv_bytes",
    "build_patient_ape_completion_snapshot",
    "build_ape_capture_impact",
]
