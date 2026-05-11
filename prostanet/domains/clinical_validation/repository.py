from __future__ import annotations

import hashlib
import json
from typing import Any

import tracking_db


def _connect():
    return tracking_db._connect()


def _json_blob(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _parse_json(value: Any, default: Any):
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _stable_key(prefix: str, payload: dict[str, Any]) -> str:
    digest = hashlib.sha1(_json_blob(payload).encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


def persist_patient_clinical_ledger(
    patient_id: int,
    *,
    decision_trace: dict[str, Any],
    guideline_plan: dict[str, Any],
    signals: dict[str, Any],
    missing_input_requirements: dict[str, Any],
    latest_clinically_decisive_visit: dict[str, Any] | None = None,
    event_id: int | None = None,
) -> None:
    patient_id = int(patient_id)
    latest_clinically_decisive_visit = dict(latest_clinically_decisive_visit or {})
    effective_state = str(signals.get("effective_state") or signals.get("reconciled_state") or signals.get("state") or "")
    effective_track = str(signals.get("effective_management_track") or signals.get("reconciled_management_track") or signals.get("management_track") or "")

    decision_payload = {
        "patient_id": patient_id,
        "event_id": event_id,
        "effective_state": effective_state,
        "effective_management_track": effective_track,
        "headline": decision_trace.get("headline"),
        "visibility_status": decision_trace.get("visibility_status"),
        "latest_clinically_decisive_visit": latest_clinically_decisive_visit,
        "decision_trace": decision_trace,
    }
    guideline_payload = {
        "patient_id": patient_id,
        "event_id": event_id,
        "effective_state": effective_state,
        "effective_management_track": effective_track,
        "guideline_basis": guideline_plan.get("schedule_evidence_basis") or [],
        "guideline_plan": guideline_plan,
    }
    transition_payload = {
        "patient_id": patient_id,
        "event_id": event_id,
        "from_state": signals.get("explicit_state") or signals.get("state"),
        "to_state": effective_state,
        "management_track": effective_track,
        "headline": decision_trace.get("headline"),
        "why_changed": decision_trace.get("why_changed") or [],
        "latest_clinically_decisive_visit": latest_clinically_decisive_visit,
        "signals": {
            "state_conflict_flag": signals.get("state_conflict_flag"),
            "state_conflict_reason": signals.get("state_conflict_reason"),
        },
    }
    missing_payload = {
        "patient_id": patient_id,
        "event_id": event_id,
        "effective_state": effective_state,
        "effective_management_track": effective_track,
        "blocking_inputs": missing_input_requirements.get("blocking_inputs") or [],
        "required_to_recalculate": missing_input_requirements.get("required_to_recalculate") or [],
        "optional_context_inputs": missing_input_requirements.get("optional_context_inputs") or [],
        "decision_domains_blocked": missing_input_requirements.get("decision_domains_blocked") or [],
        "why_these_fields_now": missing_input_requirements.get("why_these_fields_now") or [],
        "capture_block": missing_input_requirements.get("capture_block") or {},
    }

    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO decision_snapshots (
            snapshot_key, patient_id, event_id, state, management_track, headline, snapshot_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(snapshot_key) DO UPDATE SET
            event_id=excluded.event_id,
            state=excluded.state,
            management_track=excluded.management_track,
            headline=excluded.headline,
            snapshot_json=excluded.snapshot_json,
            updated_at=CURRENT_TIMESTAMP
        """,
        (
            _stable_key("decision", decision_payload),
            patient_id,
            event_id,
            effective_state,
            effective_track,
            str(decision_trace.get("headline") or ""),
            _json_blob(decision_payload),
        ),
    )
    cursor.execute(
        """
        INSERT INTO guideline_plan_snapshots (
            snapshot_key, patient_id, event_id, state, management_track, guideline_basis_json, snapshot_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(snapshot_key) DO UPDATE SET
            event_id=excluded.event_id,
            state=excluded.state,
            management_track=excluded.management_track,
            guideline_basis_json=excluded.guideline_basis_json,
            snapshot_json=excluded.snapshot_json,
            updated_at=CURRENT_TIMESTAMP
        """,
        (
            _stable_key("guideline", guideline_payload),
            patient_id,
            event_id,
            effective_state,
            effective_track,
            _json_blob(guideline_payload.get("guideline_basis") or []),
            _json_blob(guideline_payload),
        ),
    )
    cursor.execute(
        """
        INSERT INTO state_transition_snapshots (
            snapshot_key, patient_id, event_id, from_state, to_state, management_track, reason, snapshot_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(snapshot_key) DO UPDATE SET
            event_id=excluded.event_id,
            from_state=excluded.from_state,
            to_state=excluded.to_state,
            management_track=excluded.management_track,
            reason=excluded.reason,
            snapshot_json=excluded.snapshot_json,
            updated_at=CURRENT_TIMESTAMP
        """,
        (
            _stable_key("transition", transition_payload),
            patient_id,
            event_id,
            str(transition_payload.get("from_state") or ""),
            effective_state,
            effective_track,
            str(decision_trace.get("headline") or ""),
            _json_blob(transition_payload),
        ),
    )
    cursor.execute(
        """
        INSERT INTO missing_input_requests (
            request_key, patient_id, event_id, state, management_track,
            blocking_inputs_json, required_to_recalculate_json, optional_context_inputs_json,
            decision_domains_blocked_json, rationale_json, snapshot_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(request_key) DO UPDATE SET
            event_id=excluded.event_id,
            state=excluded.state,
            management_track=excluded.management_track,
            blocking_inputs_json=excluded.blocking_inputs_json,
            required_to_recalculate_json=excluded.required_to_recalculate_json,
            optional_context_inputs_json=excluded.optional_context_inputs_json,
            decision_domains_blocked_json=excluded.decision_domains_blocked_json,
            rationale_json=excluded.rationale_json,
            snapshot_json=excluded.snapshot_json,
            updated_at=CURRENT_TIMESTAMP
        """,
        (
            _stable_key("missing", missing_payload),
            patient_id,
            event_id,
            effective_state,
            effective_track,
            _json_blob(missing_payload.get("blocking_inputs") or []),
            _json_blob(missing_payload.get("required_to_recalculate") or []),
            _json_blob(missing_payload.get("optional_context_inputs") or []),
            _json_blob(missing_payload.get("decision_domains_blocked") or []),
            _json_blob(missing_payload.get("why_these_fields_now") or []),
            _json_blob(missing_payload),
        ),
    )
    conn.commit()
    conn.close()


def _history_query(table_name: str, patient_id: int, column_name: str = "snapshot_json") -> list[dict[str, Any]]:
    conn = _connect()
    conn.row_factory = tracking_db.sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        f"SELECT * FROM {table_name} WHERE patient_id = ? ORDER BY updated_at DESC, id DESC LIMIT 20",
        (patient_id,),
    )
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    history = []
    for row in rows:
        row["payload"] = _parse_json(row.get(column_name), {})
        history.append(row)
    return history


def get_patient_ledger_histories(patient_id: int) -> dict[str, Any]:
    return {
        "decision_snapshot_history": _history_query("decision_snapshots", patient_id),
        "guideline_plan_history": _history_query("guideline_plan_snapshots", patient_id),
        "state_transition_history": _history_query("state_transition_snapshots", patient_id),
        "missing_input_history": _history_query("missing_input_requests", patient_id),
        "validation_annotations": get_patient_validation_annotations(patient_id),
    }


def save_validation_run_report(report: dict[str, Any]) -> None:
    run_id = str(report.get("run_id") or "").strip()
    if not run_id:
        raise ValueError("validation report requires run_id")

    conn = _connect()
    cursor = conn.cursor()
    summary = dict(report.get("summary") or {})
    cursor.execute(
        """
        INSERT INTO validation_runs (
            run_id, cohort_mode, base_url, total_trajectories, passed, failed, critical_failures,
            ui_contradictions, missing_input_prompt_accuracy, guideline_concordance_pct,
            data_accumulation_completeness_pct, top_failing_scenario_families_json, report_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(run_id) DO UPDATE SET
            cohort_mode=excluded.cohort_mode,
            base_url=excluded.base_url,
            total_trajectories=excluded.total_trajectories,
            passed=excluded.passed,
            failed=excluded.failed,
            critical_failures=excluded.critical_failures,
            ui_contradictions=excluded.ui_contradictions,
            missing_input_prompt_accuracy=excluded.missing_input_prompt_accuracy,
            guideline_concordance_pct=excluded.guideline_concordance_pct,
            data_accumulation_completeness_pct=excluded.data_accumulation_completeness_pct,
            top_failing_scenario_families_json=excluded.top_failing_scenario_families_json,
            report_json=excluded.report_json
        """,
        (
            run_id,
            report.get("cohort_mode", "isolated_temp_db"),
            report.get("base_url", ""),
            int(summary.get("total_trajectories") or 0),
            int(summary.get("passed") or 0),
            int(summary.get("failed") or 0),
            int(summary.get("critical_failures") or 0),
            int(summary.get("ui_contradictions") or 0),
            float(summary.get("missing_input_prompt_accuracy") or 0.0),
            float(summary.get("guideline_concordance_pct") or 0.0),
            float(summary.get("data_accumulation_completeness_pct") or 0.0),
            _json_blob(summary.get("top_failing_scenario_families") or []),
            _json_blob(report),
        ),
    )
    cursor.execute("DELETE FROM validation_run_cases WHERE run_id = ?", (run_id,))
    cursor.execute("DELETE FROM validation_visual_artifacts WHERE run_id = ?", (run_id,))
    for case in list(report.get("cases") or []):
        cursor.execute(
            """
            INSERT INTO validation_run_cases (
                run_id, case_key, scenario_id, scenario_family, patient_id, patient_nss,
                case_status, critical_failure, ui_contradictions_json, expected_json, actual_json,
                assertions_json, report_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                run_id,
                case.get("case_key"),
                case.get("scenario_id"),
                case.get("scenario_family"),
                case.get("patient_id"),
                case.get("patient_nss", ""),
                case.get("case_status", "failed"),
                1 if case.get("critical_failure") else 0,
                _json_blob(case.get("ui_contradictions") or []),
                _json_blob(case.get("expected") or {}),
                _json_blob(case.get("actual") or {}),
                _json_blob(case.get("assertions") or []),
                _json_blob(case),
            ),
        )
        for artifact in list(case.get("visual_artifacts") or []):
            cursor.execute(
                """
                INSERT INTO validation_visual_artifacts (
                    run_id, case_key, patient_id, artifact_type, artifact_path, artifact_text, assertion_key, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    run_id,
                    case.get("case_key"),
                    case.get("patient_id"),
                    artifact.get("artifact_type", "snapshot"),
                    artifact.get("artifact_path", ""),
                    artifact.get("artifact_text", ""),
                    artifact.get("assertion_key", ""),
                    artifact.get("status", "generated"),
                ),
            )
    conn.commit()
    conn.close()


def get_validation_run(run_id: str) -> dict[str, Any] | None:
    conn = _connect()
    conn.row_factory = tracking_db.sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM validation_runs WHERE run_id = ?", (run_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    payload = dict(row)
    payload["top_failing_scenario_families"] = _parse_json(payload.pop("top_failing_scenario_families_json", None), [])
    payload["report"] = _parse_json(payload.get("report_json"), {})
    return payload


def get_validation_case(run_id: str, case_key: str) -> dict[str, Any] | None:
    conn = _connect()
    conn.row_factory = tracking_db.sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM validation_run_cases WHERE run_id = ? AND case_key = ?",
        (run_id, case_key),
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    payload = dict(row)
    payload["ui_contradictions"] = _parse_json(payload.pop("ui_contradictions_json", None), [])
    payload["expected"] = _parse_json(payload.pop("expected_json", None), {})
    payload["actual"] = _parse_json(payload.pop("actual_json", None), {})
    payload["assertions"] = _parse_json(payload.pop("assertions_json", None), [])
    payload["report"] = _parse_json(payload.get("report_json"), {})
    payload["visual_artifacts"] = get_validation_case_artifacts(run_id, case_key)
    return payload


def get_validation_case_artifacts(run_id: str, case_key: str) -> list[dict[str, Any]]:
    conn = _connect()
    conn.row_factory = tracking_db.sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM validation_visual_artifacts WHERE run_id = ? AND case_key = ? ORDER BY id ASC",
        (run_id, case_key),
    )
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def get_validation_report(run_id: str) -> dict[str, Any] | None:
    run = get_validation_run(run_id)
    if not run:
        return None
    report = dict(run.get("report") or {})
    if report.get("cases"):
        return report
    conn = _connect()
    conn.row_factory = tracking_db.sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        "SELECT case_key FROM validation_run_cases WHERE run_id = ? ORDER BY id ASC",
        (run_id,),
    )
    case_keys = [str(row["case_key"]) for row in cursor.fetchall()]
    conn.close()
    report["cases"] = [get_validation_case(run_id, case_key) for case_key in case_keys]
    return report


def list_validation_runs(limit: int = 10) -> list[dict[str, Any]]:
    conn = _connect()
    conn.row_factory = tracking_db.sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM validation_runs ORDER BY created_at DESC, id DESC LIMIT ?", (int(limit),))
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    payload = []
    for row in rows:
        row["top_failing_scenario_families"] = _parse_json(row.pop("top_failing_scenario_families_json", None), [])
        row.pop("report_json", None)
        payload.append(row)
    return payload


def get_latest_validation_summary() -> dict[str, Any]:
    runs = list_validation_runs(limit=1)
    if not runs:
        return {
            "available": False,
            "total_trajectories": 0,
            "passed": 0,
            "failed": 0,
            "critical_failures": 0,
            "ui_contradictions": 0,
            "missing_input_prompt_accuracy": 0.0,
            "guideline_concordance_pct": 0.0,
            "data_accumulation_completeness_pct": 0.0,
            "top_failing_scenario_families": [],
        }
    latest = runs[0]
    latest["available"] = True
    return latest


def get_patient_validation_annotations(patient_id: int) -> list[dict[str, Any]]:
    conn = _connect()
    conn.row_factory = tracking_db.sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT run_id, case_key, scenario_id, scenario_family, case_status, critical_failure, report_json, created_at
        FROM validation_run_cases
        WHERE patient_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 8
        """,
        (int(patient_id),),
    )
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    annotations = []
    for row in rows:
        annotations.append(
            {
                "run_id": row.get("run_id"),
                "case_key": row.get("case_key"),
                "scenario_id": row.get("scenario_id"),
                "scenario_family": row.get("scenario_family"),
                "case_status": row.get("case_status"),
                "critical_failure": bool(row.get("critical_failure")),
                "created_at": row.get("created_at"),
                "report": _parse_json(row.get("report_json"), {}),
            }
        )
    return annotations


__all__ = [
    "get_latest_validation_summary",
    "get_patient_ledger_histories",
    "get_validation_case",
    "get_validation_report",
    "get_validation_run",
    "list_validation_runs",
    "persist_patient_clinical_ledger",
    "save_validation_run_report",
]
