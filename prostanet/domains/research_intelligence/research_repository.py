from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import tracking_db


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def persist_json_run(table_name: str, payload: dict[str, Any], *, run_key: str | None = None) -> int:
    conn = tracking_db._connect()
    try:
        cursor = conn.cursor()
        payload_json = json.dumps(payload, ensure_ascii=False, default=str)
        timestamp = _now_iso()
        if table_name == "research_multivariate_runs":
            key = run_key or payload.get("run_key")
            cursor.execute(
                """
                INSERT INTO research_multivariate_runs (
                    run_key, analysis_type, cohort_key, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(run_key) DO UPDATE SET
                    analysis_type = excluded.analysis_type,
                    cohort_key = excluded.cohort_key,
                    payload_json = excluded.payload_json,
                    created_at = excluded.created_at
                """,
                (
                    key,
                    payload.get("analysis_type"),
                    payload.get("cohort_key"),
                    payload_json,
                    timestamp,
                ),
            )
        elif table_name == "research_propensity_runs":
            key = run_key or payload.get("run_key")
            cursor.execute(
                """
                INSERT INTO research_propensity_runs (
                    run_key, cohort_key, treatment_field, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(run_key) DO UPDATE SET
                    cohort_key = excluded.cohort_key,
                    treatment_field = excluded.treatment_field,
                    payload_json = excluded.payload_json,
                    created_at = excluded.created_at
                """,
                (
                    key,
                    payload.get("cohort_key"),
                    payload.get("treatment_field"),
                    payload_json,
                    timestamp,
                ),
            )
        elif table_name == "research_survival_snapshots":
            key = run_key or payload.get("snapshot_key")
            cursor.execute(
                """
                INSERT INTO research_survival_snapshots (
                    snapshot_key, endpoint, cohort_key, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(snapshot_key) DO UPDATE SET
                    endpoint = excluded.endpoint,
                    cohort_key = excluded.cohort_key,
                    payload_json = excluded.payload_json,
                    created_at = excluded.created_at
                """,
                (
                    key,
                    payload.get("endpoint"),
                    payload.get("cohort_key"),
                    payload_json,
                    timestamp,
                ),
            )
        else:
            raise ValueError(f"Tabla de research no soportada: {table_name}")
        row_id = cursor.lastrowid
        conn.commit()
        return int(row_id or 0)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_recent_runs(table_name: str, limit: int = 10) -> list[dict[str, Any]]:
    conn = tracking_db._connect()
    cursor = conn.cursor()
    cursor.execute(
        f"SELECT * FROM {table_name} ORDER BY created_at DESC, id DESC LIMIT ?",
        (int(limit),),
    )
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    for row in rows:
        row["payload"] = json.loads(row.pop("payload_json", "{}") or "{}")
    return rows
