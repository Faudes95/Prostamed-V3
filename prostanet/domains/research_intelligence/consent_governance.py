from __future__ import annotations

import json
import math
from typing import Any

from prostanet.domains.research_intelligence.consent_repository import (
    create_intake_draft,
    ensure_current_consent_version,
    finalize_intake_draft,
    get_intake_draft,
    get_patient_consent_summary,
    sign_intake_draft,
)


_TRUE_VALUES = {"1", "true", "yes", "si", "sí"}
_FIRST_REAL_SOURCE_CONTEXTS = {
    "first_real_wizard_v2",
    "first_real_patient_dry_run_v2",
    "first_real_institutional_launch_rehearsal_v2",
}


def _is_truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in _TRUE_VALUES


def _history_rows(value: Any) -> list[dict[str, Any]]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        raw_rows = value
    elif isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        raw_rows = parsed if isinstance(parsed, list) else []
    else:
        return []
    return [row for row in raw_rows if isinstance(row, dict)]


def _valid_psa_history_count(payload: dict[str, Any]) -> int:
    rows = _history_rows(payload.get("psa_history")) or _history_rows(payload.get("ape_history"))
    seen: set[tuple[str, float]] = set()
    for row in rows:
        raw_value = row.get("psa_value", row.get("value", row.get("psa", row.get("ape"))))
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value) or value < 0:
            continue
        sample_date = str(row.get("sample_date") or row.get("date") or row.get("collected_at") or "").strip()
        if not sample_date:
            continue
        seen.add((sample_date, round(value, 4)))
    return len(seen)


def _requires_first_real_ape_series(payload: dict[str, Any], source_context: str) -> bool:
    if not _is_truthy(payload.get("is_real_patient")):
        return False
    source_key = str(source_context or "").strip()
    return (
        source_key in _FIRST_REAL_SOURCE_CONTEXTS
        or str(payload.get("real_world_enrollment_mode") or "").strip() == "prospective_v2"
    )


def validate_first_real_ape_series(payload: dict[str, Any], *, source_context: str) -> None:
    if not _requires_first_real_ape_series(payload, source_context):
        return
    valid_count = _valid_psa_history_count(payload)
    if valid_count < 2:
        raise ValueError(
            "Para primer paciente real prospectivo se requieren al menos 2 mediciones APE con fecha antes de iniciar consentimiento."
        )


def get_current_consent_payload() -> dict[str, Any]:
    version = ensure_current_consent_version()
    return {
        "current_version": {
            "version_code": version.get("version_code"),
            "title": version.get("title"),
            "consent_text": version.get("consent_text"),
            "html_snapshot": version.get("html_snapshot"),
            "effective_at": version.get("effective_at"),
        }
    }


def create_consent_draft(payload: dict[str, Any], *, source_context: str) -> dict[str, Any]:
    validate_first_real_ape_series(payload, source_context=source_context)
    return create_intake_draft(payload, source_context=source_context)


def get_consent_draft_payload(draft_id: int) -> dict[str, Any] | None:
    return get_intake_draft(draft_id)


def sign_consent_draft_payload(draft_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    return sign_intake_draft(
        draft_id,
        signer_name=payload.get("signer_name"),
        signature_data_url=payload.get("signature_data_url"),
        accepted=bool(payload.get("accepted")),
        audit_metadata=payload.get("audit_metadata") or {},
    )


def finalize_consent_draft_payload(draft_id: int) -> dict[str, Any]:
    return finalize_intake_draft(draft_id)


def build_consent_dashboard_payload(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    signed = 0
    missing = 0
    recent = []
    for record in records:
        identity = record.get("identity") or {}
        summary = get_patient_consent_summary(identity.get("id")) if identity.get("id") else {}
        if summary.get("status") == "signed":
            signed += 1
        else:
            missing += 1
        if identity.get("id") and len(recent) < 10:
            recent.append(
                {
                    "patient_id": identity.get("id"),
                    "nss": identity.get("nss"),
                    "full_name": identity.get("full_name"),
                    "status": summary.get("status", "missing"),
                    "signed_at": summary.get("signed_at"),
                    "version_code": summary.get("consent_version_code"),
                }
            )
    return {
        "total_patients": total,
        "signed_count": signed,
        "missing_count": missing,
        "coverage_pct": round((signed / total) * 100, 1) if total else 0.0,
        "recent_consents": recent,
        "current_version": get_current_consent_payload()["current_version"],
    }
