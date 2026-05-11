from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import tracking_db

from clinical_scores import clavien_dindo_grade


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _persist_operational_rows(patient_id: int, surgery: dict[str, Any], pros: list[dict[str, Any]]) -> None:
    conn = tracking_db._connect()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM operational_outcome_events WHERE patient_id = ?", (int(patient_id),))
    cursor.execute("DELETE FROM functional_recovery_snapshots WHERE patient_id = ?", (int(patient_id),))
    cursor.execute("DELETE FROM clavien_dindo_events WHERE patient_id = ?", (int(patient_id),))

    surgery_date = surgery.get("surgery_date") or surgery.get("rp_date") or ""
    margin_status = surgery.get("margin_status") or surgery.get("surgical_margin")
    if margin_status not in (None, ""):
        cursor.execute(
            """
            INSERT INTO operational_outcome_events (
                patient_id, event_type, event_date, severity, payload_json, created_at
            ) VALUES (?, 'positive_margin', ?, ?, ?, ?)
            """,
            (
                int(patient_id),
                surgery_date or _now_iso()[:10],
                str(margin_status),
                json.dumps({"margin_status": margin_status, "margin_location": surgery.get("margin_location")}, ensure_ascii=False, default=str),
                _now_iso(),
            ),
        )

    complication_text = str(surgery.get("postop_complications") or surgery.get("surgical_complications") or "").strip()
    if complication_text:
        grade = clavien_dindo_grade(complication_text)
        cursor.execute(
            """
            INSERT INTO clavien_dindo_events (
                patient_id, surgery_date, grade, event_label, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                int(patient_id),
                surgery_date or _now_iso()[:10],
                str(grade),
                complication_text[:120],
                json.dumps({"complication_text": complication_text}, ensure_ascii=False, default=str),
                _now_iso(),
            ),
        )

    for pro in pros or []:
        cursor.execute(
            """
            INSERT INTO functional_recovery_snapshots (
                patient_id, snapshot_date, urinary_recovery_status, sexual_recovery_status,
                continence_pads_per_day, pde5i_use, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(patient_id),
                pro.get("assessment_date") or _now_iso()[:10],
                pro.get("continence_status") or "",
                pro.get("erectile_function_status") or "",
                _safe_float(pro.get("pads_per_day")),
                pro.get("pde5i_use") or "",
                json.dumps(pro, ensure_ascii=False, default=str),
                _now_iso(),
            ),
        )
    conn.commit()
    conn.close()


def build_operational_outcomes_payload(records: list[dict[str, Any]]) -> dict[str, Any]:
    positive_margin = 0
    surgery_count = 0
    continence_recovered = 0
    potency_recovered = 0
    clavien_distribution: dict[str, int] = {}
    recovery_timeline = []

    for record in records:
        identity = record.get("identity") or {}
        patient_id = identity.get("id")
        surgery = dict(record.get("surgery") or {})
        pros = list(record.get("pros") or [])
        if patient_id:
            _persist_operational_rows(int(patient_id), surgery, pros)
        if surgery:
            surgery_count += 1
            if str(surgery.get("margin_status") or surgery.get("surgical_margin") or "").lower() in {"positive", "1", "positivo"}:
                positive_margin += 1
            complication_text = str(surgery.get("postop_complications") or surgery.get("surgical_complications") or "").strip()
            if complication_text:
                grade = str(clavien_dindo_grade(complication_text))
                clavien_distribution[grade] = clavien_distribution.get(grade, 0) + 1
        latest_pro = pros[-1] if pros else {}
        if str(latest_pro.get("continence_status") or "").lower() in {"continent", "continente", "dry"}:
            continence_recovered += 1
        if str(latest_pro.get("erectile_function_status") or "").lower() in {"functional", "recuperada", "adequate"}:
            potency_recovered += 1
        if latest_pro:
            recovery_timeline.append(
                {
                    "patient_id": patient_id,
                    "snapshot_date": latest_pro.get("assessment_date"),
                    "continence_status": latest_pro.get("continence_status"),
                    "erectile_function_status": latest_pro.get("erectile_function_status"),
                }
            )

    return {
        "surgery_count": surgery_count,
        "positive_margin_count": positive_margin,
        "positive_margin_rate": round((positive_margin / surgery_count) * 100, 1) if surgery_count else 0.0,
        "continence_recovered_count": continence_recovered,
        "potency_recovered_count": potency_recovered,
        "clavien_distribution": clavien_distribution,
        "recovery_timeline": recovery_timeline[:20],
    }
