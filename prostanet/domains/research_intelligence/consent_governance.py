from __future__ import annotations

from typing import Any

from prostanet.domains.research_intelligence.consent_repository import (
    create_intake_draft,
    ensure_current_consent_version,
    finalize_intake_draft,
    get_intake_draft,
    get_patient_consent_summary,
    sign_intake_draft,
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
