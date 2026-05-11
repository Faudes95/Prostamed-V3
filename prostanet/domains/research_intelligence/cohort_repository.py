from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import tracking_db


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def save_dynamic_cohort(
    *,
    title: str,
    filters: list[dict[str, Any]],
    description: str = "",
    system_defined: bool = False,
    patient_ids: list[int] | None = None,
) -> dict[str, Any]:
    conn = tracking_db._connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO dynamic_cohorts (
            cohort_key, title, description, filters_json, system_defined, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _slugify(title),
            title,
            description,
            json.dumps(filters, ensure_ascii=False, default=str),
            1 if system_defined else 0,
            _now_iso(),
            _now_iso(),
        ),
    )
    cohort_id = cursor.lastrowid
    for patient_id in patient_ids or []:
        cursor.execute(
            """
            INSERT INTO dynamic_cohort_memberships (cohort_id, patient_id, joined_at)
            VALUES (?, ?, ?)
            """,
            (int(cohort_id), int(patient_id), _now_iso()),
        )
    conn.commit()
    conn.close()
    return get_dynamic_cohort(int(cohort_id)) or {}


def list_dynamic_cohorts() -> list[dict[str, Any]]:
    conn = tracking_db._connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT dc.*, COUNT(dcm.id) AS member_count
        FROM dynamic_cohorts dc
        LEFT JOIN dynamic_cohort_memberships dcm ON dcm.cohort_id = dc.id
        GROUP BY dc.id
        ORDER BY dc.system_defined DESC, dc.updated_at DESC, dc.id DESC
        """
    )
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    for row in rows:
        row["filters"] = json.loads(row.pop("filters_json", "[]") or "[]")
    return rows


def get_dynamic_cohort(cohort_id: int) -> dict[str, Any] | None:
    conn = tracking_db._connect()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM dynamic_cohorts WHERE id = ?", (int(cohort_id),))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None
    cohort = dict(row)
    cohort["filters"] = json.loads(cohort.pop("filters_json", "[]") or "[]")
    cursor.execute(
        """
        SELECT patient_id FROM dynamic_cohort_memberships
        WHERE cohort_id = ?
        ORDER BY patient_id ASC
        """,
        (int(cohort_id),),
    )
    cohort["patient_ids"] = [int(item["patient_id"]) for item in cursor.fetchall()]
    cohort["member_count"] = len(cohort["patient_ids"])
    cohort["size"] = len(cohort["patient_ids"])
    conn.close()
    return cohort


def replace_dynamic_cohort_memberships(cohort_id: int, patient_ids: list[int]) -> dict[str, Any]:
    conn = tracking_db._connect()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM dynamic_cohort_memberships WHERE cohort_id = ?", (int(cohort_id),))
    for patient_id in patient_ids:
        cursor.execute(
            """
            INSERT INTO dynamic_cohort_memberships (cohort_id, patient_id, joined_at)
            VALUES (?, ?, ?)
            """,
            (int(cohort_id), int(patient_id), _now_iso()),
        )
    cursor.execute(
        "UPDATE dynamic_cohorts SET updated_at = ? WHERE id = ?",
        (_now_iso(), int(cohort_id)),
    )
    conn.commit()
    conn.close()
    return get_dynamic_cohort(int(cohort_id)) or {}


def _slugify(title: str) -> str:
    slug = "".join(char.lower() if char.isalnum() else "-" for char in str(title or "").strip())
    slug = "-".join(part for part in slug.split("-") if part)
    return slug[:80] or f"cohort-{int(datetime.now(UTC).timestamp())}"
