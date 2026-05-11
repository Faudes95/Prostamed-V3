from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import tracking_db


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def upsert_definition(definition: dict[str, Any]) -> None:
    conn = tracking_db._connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO quality_indicator_definitions (
            indicator_key, title, clinical_definition, benchmark_target, domain, metadata_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(indicator_key) DO UPDATE SET
            title = excluded.title,
            clinical_definition = excluded.clinical_definition,
            benchmark_target = excluded.benchmark_target,
            domain = excluded.domain,
            metadata_json = excluded.metadata_json,
            updated_at = excluded.updated_at
        """,
        (
            definition.get("indicator_key"),
            definition.get("title"),
            definition.get("clinical_definition"),
            definition.get("benchmark_target"),
            definition.get("domain"),
            json.dumps(definition, ensure_ascii=False, default=str),
            _now_iso(),
        ),
    )
    conn.commit()
    conn.close()


def replace_results(results: list[dict[str, Any]]) -> None:
    conn = tracking_db._connect()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM quality_indicator_results")
    for result in results:
        cursor.execute(
            """
            INSERT INTO quality_indicator_results (
                indicator_key, numerator, denominator, percentage, trend_json, result_payload_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.get("indicator_key"),
                int(result.get("numerator") or 0),
                int(result.get("denominator") or 0),
                float(result.get("percentage") or 0.0),
                json.dumps(result.get("trend") or {}, ensure_ascii=False, default=str),
                json.dumps(result, ensure_ascii=False, default=str),
                _now_iso(),
            ),
        )
    conn.commit()
    conn.close()


def list_results() -> list[dict[str, Any]]:
    conn = tracking_db._connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT qir.*, qid.title, qid.clinical_definition, qid.benchmark_target, qid.domain
        FROM quality_indicator_results qir
        LEFT JOIN quality_indicator_definitions qid ON qid.indicator_key = qir.indicator_key
        ORDER BY qid.domain ASC, qid.title ASC
        """
    )
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    for row in rows:
        row["trend"] = json.loads(row.pop("trend_json", "{}") or "{}")
        row["payload"] = json.loads(row.pop("result_payload_json", "{}") or "{}")
    return rows
