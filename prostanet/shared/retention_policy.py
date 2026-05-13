"""Retention policy helpers for ProstaMed electronic records.

The policy is intentionally deterministic and conservative. It does not delete
records by itself; it classifies records so operational jobs, review workflows,
and archive procedures can decide what to retain, archive, or purge with human
oversight when needed.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping


RETENTION_POLICY_VERSION = "prostamed_retention_policy_v1"


@dataclass(frozen=True)
class RetentionRule:
    record_class: str
    label: str
    retention_days: int
    retention_trigger: str
    disposition: str
    contains_phi: bool
    archive_required: bool
    purge_after_signature: bool = False
    notes: str = ""


@dataclass(frozen=True)
class RetentionEvaluation:
    record_class: str
    status: str
    retention_until: str
    disposition: str
    archive_required: bool
    legal_hold: bool
    reason: str


RETENTION_RULES: dict[str, RetentionRule] = {
    "patient_clinical_record": RetentionRule(
        record_class="patient_clinical_record",
        label="Patient clinical record",
        retention_days=3650,
        retention_trigger="last_clinical_use_or_record_close",
        disposition="retain_secure_archive_then_legal_review_before_purge",
        contains_phi=True,
        archive_required=True,
        notes="Internal v1 minimum for ProstaMed clinical records; institutional policy may extend.",
    ),
    "clinical_decision_audit": RetentionRule(
        record_class="clinical_decision_audit",
        label="Decision Today and clinical decision audit bundles",
        retention_days=3650,
        retention_trigger="decision_signature_or_creation",
        disposition="retain_secure_archive_then_legal_review_before_purge",
        contains_phi=True,
        archive_required=True,
    ),
    "signed_source_document": RetentionRule(
        record_class="signed_source_document",
        label="Signed source document or verified extracted fact bundle",
        retention_days=3650,
        retention_trigger="signature_or_verification_date",
        disposition="retain_secure_archive_then_legal_review_before_purge",
        contains_phi=True,
        archive_required=True,
    ),
    "qms_release_validation": RetentionRule(
        record_class="qms_release_validation",
        label="QMS, validation, release, and rollback evidence",
        retention_days=3650,
        retention_trigger="release_or_quality_review_date",
        disposition="retain_secure_archive",
        contains_phi=False,
        archive_required=True,
    ),
    "voice_raw_audio_pending_review": RetentionRule(
        record_class="voice_raw_audio_pending_review",
        label="Raw Cortana audio pending medical review",
        retention_days=7,
        retention_trigger="capture_time",
        disposition="purge_after_review_signature_or_expiry",
        contains_phi=True,
        archive_required=False,
        purge_after_signature=True,
        notes="Raw audio is temporary. Keep only signed transcript/provenance after review.",
    ),
    "voice_temporary_transcript": RetentionRule(
        record_class="voice_temporary_transcript",
        label="Temporary unverified Cortana transcript",
        retention_days=30,
        retention_trigger="capture_time",
        disposition="purge_after_review_signature_or_expiry",
        contains_phi=True,
        archive_required=False,
        purge_after_signature=True,
    ),
    "verified_voice_transcript": RetentionRule(
        record_class="verified_voice_transcript",
        label="Reviewed and signed voice transcript/source document",
        retention_days=3650,
        retention_trigger="signature_date",
        disposition="retain_secure_archive_then_legal_review_before_purge",
        contains_phi=True,
        archive_required=True,
    ),
    "deidentified_research_dataset": RetentionRule(
        record_class="deidentified_research_dataset",
        label="Approved de-identified research/readiness dataset",
        retention_days=9125,
        retention_trigger="dataset_version_release",
        disposition="retain_research_archive_or_protocol_defined_disposition",
        contains_phi=False,
        archive_required=True,
        notes="Requires consent/protocol approval and de-identification before long retention.",
    ),
    "security_audit_log": RetentionRule(
        record_class="security_audit_log",
        label="Security and access audit log without PHI payload",
        retention_days=730,
        retention_trigger="log_event_time",
        disposition="retain_security_archive",
        contains_phi=False,
        archive_required=True,
    ),
    "debug_log_no_phi": RetentionRule(
        record_class="debug_log_no_phi",
        label="Debug/application log without PHI payload",
        retention_days=90,
        retention_trigger="log_event_time",
        disposition="purge_after_expiry",
        contains_phi=False,
        archive_required=False,
    ),
    "temporary_work_file": RetentionRule(
        record_class="temporary_work_file",
        label="Temporary work file or staging artifact",
        retention_days=30,
        retention_trigger="creation_time",
        disposition="purge_after_expiry",
        contains_phi=False,
        archive_required=False,
    ),
}


def retention_schedule() -> dict[str, dict[str, Any]]:
    """Return a serializable copy of the official v1 retention schedule."""

    return {key: asdict(value) for key, value in RETENTION_RULES.items()}


def get_retention_rule(record_class: str) -> RetentionRule:
    """Return a retention rule or raise a clear error for unknown classes."""

    key = str(record_class or "").strip()
    if key not in RETENTION_RULES:
        raise KeyError(f"unknown retention record_class: {record_class}")
    return RETENTION_RULES[key]


def _parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value or "").strip()
        if not text:
            raise ValueError("created_at is required")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso_date(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def evaluate_retention(
    record_class: str,
    created_at: str | datetime,
    *,
    now: str | datetime | None = None,
    signed_or_reviewed: bool = False,
    legal_hold: bool = False,
) -> dict[str, Any]:
    """Classify a record according to the retention policy.

    Status values:
    - ``retain``: still within retention period.
    - ``eligible_for_purge``: past retention period and no archive/legal hold
      condition blocks disposition.
    - ``purge_after_signature``: temporary voice/audio artifact can be removed
      after review signature.
    - ``legal_hold``: retention is extended by legal or quality hold.
    """

    rule = get_retention_rule(record_class)
    start = _parse_dt(created_at)
    current = _parse_dt(now) if now is not None else datetime.now(timezone.utc)
    retention_until = start + timedelta(days=rule.retention_days)

    if legal_hold:
        status = "legal_hold"
        reason = "legal_or_quality_hold_extends_retention"
    elif rule.purge_after_signature and signed_or_reviewed:
        status = "purge_after_signature"
        reason = "temporary_artifact_signed_or_reviewed"
    elif current >= retention_until:
        status = "eligible_for_purge"
        reason = "retention_period_elapsed"
    else:
        status = "retain"
        reason = "within_retention_period"

    return asdict(
        RetentionEvaluation(
            record_class=rule.record_class,
            status=status,
            retention_until=_iso_date(retention_until),
            disposition=rule.disposition,
            archive_required=rule.archive_required,
            legal_hold=bool(legal_hold),
            reason=reason,
        )
    )


def classify_record_from_context(context: Mapping[str, Any]) -> str:
    """Map common ProstaMed source contexts into retention record classes."""

    source = str(context.get("source") or context.get("source_type") or "").lower()
    record_type = str(context.get("record_type") or context.get("type") or "").lower()
    status = str(context.get("status") or "").lower()

    if "voice" in source and "audio" in record_type and status != "signed":
        return "voice_raw_audio_pending_review"
    if "voice" in source and "transcript" in record_type and status != "signed":
        return "voice_temporary_transcript"
    if "voice" in source and "transcript" in record_type and status == "signed":
        return "verified_voice_transcript"
    if "decision" in record_type or "decision_today" in source:
        return "clinical_decision_audit"
    if "qms" in source or "release" in record_type or "validation" in record_type:
        return "qms_release_validation"
    if "research" in source or "dataset" in record_type:
        return "deidentified_research_dataset"
    if "security" in source or "access" in record_type:
        return "security_audit_log"
    if "debug" in source or "log" in record_type:
        return "debug_log_no_phi"
    return "patient_clinical_record"
