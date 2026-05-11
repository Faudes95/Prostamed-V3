from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import tracking_db


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def seed_reference(reference: dict[str, Any]) -> None:
    conn = tracking_db._connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO benchmark_reference_library (
            benchmark_key, title, endpoint, source_label, population_summary, reference_payload_json,
            comparability_tier, effective_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(benchmark_key) DO UPDATE SET
            title = excluded.title,
            endpoint = excluded.endpoint,
            source_label = excluded.source_label,
            population_summary = excluded.population_summary,
            reference_payload_json = excluded.reference_payload_json,
            comparability_tier = excluded.comparability_tier,
            effective_at = excluded.effective_at
        """,
        (
            reference.get("benchmark_key"),
            reference.get("title"),
            reference.get("endpoint"),
            reference.get("source_label"),
            reference.get("population_summary"),
            json.dumps(reference, ensure_ascii=False, default=str),
            reference.get("comparability_tier", "limited"),
            reference.get("effective_at") or _now_iso(),
            _now_iso(),
        ),
    )
    conn.commit()
    conn.close()


def list_references() -> list[dict[str, Any]]:
    conn = tracking_db._connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT * FROM benchmark_reference_library
        ORDER BY endpoint ASC, title ASC
        """
    )
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    for row in rows:
        row["payload"] = json.loads(row.pop("reference_payload_json", "{}") or "{}")
    return rows


def persist_comparison(comparison: dict[str, Any]) -> int:
    conn = tracking_db._connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO benchmark_comparisons (
            benchmark_key, cohort_key, comparison_payload_json, created_at
        ) VALUES (?, ?, ?, ?)
        """,
        (
            comparison.get("benchmark_key"),
            comparison.get("cohort_key"),
            json.dumps(comparison, ensure_ascii=False, default=str),
            _now_iso(),
        ),
    )
    row_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return int(row_id)
