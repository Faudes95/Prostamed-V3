"""Operational evidence vault for the local NAS prospective pilot.

The vault stores non-PHI attestations for the operational watches that remain
after clinical readiness is green: NAS deployment proof, restore drill,
role-based access, consent/data-use, training, incident response and protocol
approval. It deliberately does not store patient identifiers or clinical facts.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from datetime import date, datetime, timedelta
from typing import Any, Mapping

from prostanet.shared.utc_time import utc_now_iso


NAS_PILOT_EVIDENCE_VAULT_VERSION = "nas_pilot_operations_evidence_vault_v1"

EVIDENCE_STATUSES = ("draft", "verified", "expired", "blocked")
DIRECT_IDENTIFIER_KEYS = {
    "nss",
    "patient_id",
    "patient_ref",
    "patient_name",
    "full_name",
    "dob",
    "date_of_birth",
    "profile_url",
    "local_patient_id",
}
PHI_SENTINELS = (
    "/patient_profile/",
    "REG-VALUE-",
    "ARPI-VALUE-",
)

OPERATIONAL_GATE_SPECS: dict[str, dict[str, Any]] = {
    "nas_local_operations": {
        "label": "NAS/local deployment operations",
        "evidence_type": "nas_deployment_attestation",
        "owner": "it_nas_owner",
        "reviewer_role": "it_nas_owner",
        "expires_days": 180,
        "required_evidence": [
            "Docker/local runbook",
            "Static IP/firewall boundary",
            "UPS and RAID/SMART health check",
            "Local health check URL",
        ],
    },
    "backup_restore_drill": {
        "label": "Backup and restore drill",
        "evidence_type": "backup_restore_drill",
        "owner": "it_nas_owner",
        "reviewer_role": "it_nas_owner",
        "expires_days": 90,
        "required_evidence": [
            "Backup target",
            "Restore date",
            "Restored artifact hash",
            "Responsible operator",
        ],
    },
    "access_control_roles": {
        "label": "Role-based clinical access",
        "evidence_type": "access_control_roles",
        "owner": "security_owner",
        "reviewer_role": "security_owner",
        "expires_days": 180,
        "required_evidence": [
            "Roles mapped",
            "Unique credentials enabled",
            "PHI/read/export permissions separated",
            "Audit log reviewed",
        ],
    },
    "consent_and_data_use": {
        "label": "Consent, privacy notice and data-use boundary",
        "evidence_type": "consent_data_use_approval",
        "owner": "ethics_privacy_owner",
        "reviewer_role": "ethics_privacy_owner",
        "expires_days": 365,
        "required_evidence": [
            "Privacy notice or consent pathway",
            "ARCO response process",
            "No external transfer boundary",
            "Publication approval rule",
        ],
    },
    "training_and_adoption": {
        "label": "Training and adoption plan",
        "evidence_type": "training_completion",
        "owner": "clinical_operations_owner",
        "reviewer_role": "clinical_operations_owner",
        "expires_days": 180,
        "required_evidence": [
            "Attending training",
            "Senior resident training",
            "Junior resident training",
            "Capture adherence target",
        ],
    },
    "incident_response_contingency": {
        "label": "Incident response and downtime contingency",
        "evidence_type": "incident_response_contingency",
        "owner": "security_owner",
        "reviewer_role": "security_owner",
        "expires_days": 365,
        "required_evidence": [
            "PHI incident response",
            "Power-loss procedure",
            "NAS failure procedure",
            "Downtime capture fallback",
        ],
    },
    "prospective_protocol_approval": {
        "label": "Prospective protocol approval",
        "evidence_type": "prospective_protocol_approval",
        "owner": "principal_investigator",
        "reviewer_role": "principal_investigator",
        "expires_days": 365,
        "required_evidence": [
            "Inclusion/exclusion",
            "Endpoints",
            "Use boundary",
            "Review cadence",
        ],
    },
}


def build_nas_pilot_evidence_vault(
    *,
    scope: str = "summary",
    gate_key: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Return a no-PHI operational evidence vault summary."""
    scope_key = "summary" if str(scope or "").strip().lower() == "summary" else "full"
    safe_limit = max(1, min(int(limit or 100), 500))
    gate_filter = str(gate_key or "").strip()
    import tracking_db

    rows = tracking_db.list_pilot_operational_evidence(
        limit=safe_limit,
        gate_key=gate_filter or None,
        include_payload=scope_key == "full",
    )
    gates = _build_gate_statuses(rows)
    summary = _build_summary(gates, rows)
    payload: dict[str, Any] = {
        "available": True,
        "source": "nas_pilot_operations_evidence_vault",
        "version": NAS_PILOT_EVIDENCE_VAULT_VERSION,
        "computed_at": utc_now_iso(),
        "scope": scope_key,
        "read_only": True,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "external_transfer_performed": False,
        "deidentified": True,
        "gate_key_filter": gate_filter,
        "summary": summary,
        "gate_statuses": gates,
        "evidence_statuses": list(EVIDENCE_STATUSES),
        "evidence_types": [spec["evidence_type"] for spec in OPERATIONAL_GATE_SPECS.values()],
    }
    if scope_key == "full":
        payload["evidence_records"] = rows
        payload["evidence_form_schema"] = build_nas_pilot_evidence_form_schema()
        payload["no_phi_scan"] = _scan_for_phi(payload)
    return payload


def build_nas_pilot_evidence_form_schema() -> dict[str, Any]:
    return {
        "gate_options": [
            {
                "gate_key": key,
                "label": spec["label"],
                "evidence_type": spec["evidence_type"],
                "owner": spec["owner"],
                "reviewer_role": spec["reviewer_role"],
                "expires_days": spec["expires_days"],
                "required_evidence": list(spec["required_evidence"]),
            }
            for key, spec in OPERATIONAL_GATE_SPECS.items()
        ],
        "status_options": list(EVIDENCE_STATUSES),
        "required_fields": ["gate_key", "title", "verified_by", "reviewer_role", "audit_note"],
    }


def attest_nas_pilot_evidence(data: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and persist a non-PHI operational evidence attestation."""
    raw = dict(data or {})
    raw_scan = _scan_for_phi(raw)
    if not _no_phi_passed(raw_scan):
        return {
            "success": False,
            "error": "phi_like_content_rejected",
            "no_phi_scan": raw_scan,
            "source_clinical_facts_mutated": False,
            "external_order_created": False,
            "model_trained": False,
            "external_transfer_performed": False,
        }
    gate_key = str(raw.get("gate_key") or "").strip()
    if gate_key not in OPERATIONAL_GATE_SPECS:
        return {"success": False, "error": "unsupported_gate_key", "allowed_gates": sorted(OPERATIONAL_GATE_SPECS)}
    spec = OPERATIONAL_GATE_SPECS[gate_key]
    status = str(raw.get("evidence_status") or "verified").strip().lower()
    if status not in EVIDENCE_STATUSES:
        return {"success": False, "error": "unsupported_evidence_status", "allowed_statuses": list(EVIDENCE_STATUSES)}
    title = _clean_text(raw.get("title"), spec["label"])
    verified_by = _clean_text(raw.get("verified_by"), "clinician")
    reviewer_role = _clean_text(raw.get("reviewer_role"), spec["reviewer_role"])
    audit_note = _clean_text(
        raw.get("audit_note"),
        "Operational evidence attested for local ProstaMed NAS pilot readiness.",
    )
    evidence_date = _normalize_date(raw.get("evidence_date")) or date.today().isoformat()
    expires_at = _normalize_date(raw.get("expires_at")) or _add_days(evidence_date, int(spec["expires_days"]))
    payload = {
        "gate_key": gate_key,
        "evidence_type": str(raw.get("evidence_type") or spec["evidence_type"]),
        "title": title,
        "evidence_status": status,
        "evidence_date": evidence_date,
        "expires_at": expires_at,
        "verified_by": verified_by,
        "reviewer_role": reviewer_role,
        "evidence_ref": _clean_text(raw.get("evidence_ref"), ""),
        "audit_note": audit_note,
        "required_evidence": list(spec["required_evidence"]),
        "attestation_details": _sanitize_metadata(raw.get("attestation_details") or raw.get("metadata") or {}),
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "external_transfer_performed": False,
    }
    scan = _scan_for_phi(payload)
    if not _no_phi_passed(scan):
        return {
            "success": False,
            "error": "phi_like_content_rejected",
            "no_phi_scan": scan,
            "source_clinical_facts_mutated": False,
            "external_order_created": False,
            "model_trained": False,
            "external_transfer_performed": False,
        }
    canonical = _canonical_json(payload)
    payload_sha256 = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    evidence_hash = _clean_text(raw.get("evidence_hash"), payload_sha256)
    evidence_key = _clean_text(raw.get("evidence_key"), f"nasvault_{payload_sha256[:12]}")
    record = {
        **payload,
        "evidence_key": evidence_key,
        "evidence_hash": evidence_hash,
        "payload": payload,
        "payload_sha256": payload_sha256,
    }
    import tracking_db

    saved = tracking_db.save_pilot_operational_evidence(record)
    if not saved.get("success"):
        return saved
    vault = build_nas_pilot_evidence_vault(scope="summary")
    return {
        "success": True,
        "created_or_updated": True,
        "version": NAS_PILOT_EVIDENCE_VAULT_VERSION,
        "evidence": saved.get("evidence"),
        "summary": vault.get("summary") or {},
        "gate_status": (vault.get("gate_statuses") or {}).get(gate_key) or {},
        "no_phi_scan": scan,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "external_transfer_performed": False,
    }


def build_nas_pilot_evidence_vault_zip_bytes(vault: Mapping[str, Any] | None = None) -> bytes:
    """Build a local, no-PHI evidence ZIP for leadership/committee review."""
    payload = dict(vault or build_nas_pilot_evidence_vault(scope="full"))
    gate_rows = list((payload.get("gate_statuses") or {}).values())
    evidence_rows = list(payload.get("evidence_records") or [])
    files = {
        "README.md": _build_readme(payload),
        "evidence_vault.json": json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        "gate_status.csv": _csv_from_rows(gate_rows),
        "evidence_manifest.csv": _csv_from_rows(_evidence_manifest_rows(evidence_rows)),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename, content in sorted(files.items()):
            archive.writestr(filename, content)
    return buffer.getvalue()


def latest_gate_status_from_vault(
    vault: Mapping[str, Any],
    gate_key: str,
) -> dict[str, Any]:
    return dict((vault.get("gate_statuses") or {}).get(gate_key) or {})


def _build_gate_statuses(rows: list[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    by_gate: dict[str, list[Mapping[str, Any]]] = {key: [] for key in OPERATIONAL_GATE_SPECS}
    for row in rows:
        gate_key = str(row.get("gate_key") or "")
        if gate_key in by_gate:
            by_gate[gate_key].append(row)
    today = date.today()
    statuses: dict[str, dict[str, Any]] = {}
    for gate_key, spec in OPERATIONAL_GATE_SPECS.items():
        gate_rows = sorted(
            by_gate.get(gate_key) or [],
            key=lambda item: (str(item.get("evidence_date") or ""), str(item.get("created_at") or "")),
            reverse=True,
        )
        latest = gate_rows[0] if gate_rows else {}
        latest_status = str(latest.get("evidence_status") or "").lower()
        expires_at = str(latest.get("expires_at") or "")
        expired = _is_expired(expires_at, today)
        if latest_status == "blocked":
            gate_status = "block"
        elif latest_status == "verified" and not expired:
            gate_status = "pass"
        else:
            gate_status = "watch"
        statuses[gate_key] = {
            "gate_key": gate_key,
            "label": spec["label"],
            "owner": spec["owner"],
            "reviewer_role": spec["reviewer_role"],
            "evidence_type": spec["evidence_type"],
            "gate_status": gate_status,
            "latest_evidence_key": latest.get("evidence_key"),
            "latest_status": latest_status or "missing",
            "latest_title": latest.get("title"),
            "evidence_date": latest.get("evidence_date"),
            "expires_at": expires_at,
            "expired": expired,
            "verified_count": sum(1 for item in gate_rows if str(item.get("evidence_status") or "").lower() == "verified"),
            "record_count": len(gate_rows),
            "required_evidence": list(spec["required_evidence"]),
            "missing_reason": "" if gate_rows else "No operational evidence attested yet.",
        }
    return statuses


def _build_summary(
    gate_statuses: Mapping[str, Mapping[str, Any]],
    rows: list[Mapping[str, Any]],
) -> dict[str, Any]:
    pass_count = sum(1 for item in gate_statuses.values() if item.get("gate_status") == "pass")
    watch_count = sum(1 for item in gate_statuses.values() if item.get("gate_status") == "watch")
    block_count = sum(1 for item in gate_statuses.values() if item.get("gate_status") == "block")
    gate_count = len(gate_statuses)
    return {
        "gate_count": gate_count,
        "pass_count": pass_count,
        "watch_count": watch_count,
        "block_count": block_count,
        "verified_gate_count": pass_count,
        "evidence_record_count": len(rows),
        "completion_pct": round((pass_count / gate_count) * 100, 1) if gate_count else 0.0,
        "vault_status": "blocked" if block_count else ("complete" if pass_count == gate_count else "needs_operational_evidence"),
        "ready_for_internal_pilot_without_watches": pass_count == gate_count and block_count == 0,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "external_transfer_performed": False,
    }


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
        for sentinel in PHI_SENTINELS:
            if sentinel in text:
                hits.append(path or "value")
        if not _is_machine_hash_path(path) and re.search(r"\b\d{10,11}\b", text):
            hits.append(path or "value")

    walk(value)
    return {
        "direct_identifier_key_count": len(set(direct_keys)),
        "exact_phi_hit_count": len(set(hits)),
        "direct_identifier_keys": sorted(set(direct_keys)),
        "exact_phi_hits": sorted(set(hits)),
        "no_phi_status": "pass" if not direct_keys and not hits else "block",
    }


def _no_phi_passed(scan: Mapping[str, Any]) -> bool:
    return int(scan.get("direct_identifier_key_count") or 0) == 0 and int(scan.get("exact_phi_hit_count") or 0) == 0


def _sanitize_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    allowed: dict[str, Any] = {}
    for key, item in value.items():
        key_text = str(key).strip()
        if not key_text or key_text.lower() in DIRECT_IDENTIFIER_KEYS:
            continue
        if isinstance(item, (str, int, float, bool)) or item is None:
            allowed[key_text] = item
        elif isinstance(item, list):
            allowed[key_text] = [str(part)[:180] for part in item[:20]]
        elif isinstance(item, Mapping):
            allowed[key_text] = {
                str(inner_key)[:80]: str(inner_value)[:180]
                for inner_key, inner_value in list(item.items())[:20]
                if str(inner_key).lower() not in DIRECT_IDENTIFIER_KEYS
            }
    return allowed


def _is_machine_hash_path(path: str) -> bool:
    lowered = str(path or "").lower()
    return any(
        token in lowered
        for token in (
            "evidence_hash",
            "payload_sha256",
            "bundle_sha256",
            "sha256",
            "checksum",
            "evidence_key",
        )
    )


def _build_readme(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") or {}
    return "\n".join(
        [
            "# NAS Pilot Operations Evidence Vault",
            "",
            "Read-only, no-PHI operational evidence package for the ProstaMed local prospective pilot.",
            "",
            f"Version: {payload.get('version')}",
            f"Vault status: {summary.get('vault_status')}",
            f"Completion: {summary.get('completion_pct')}%",
            "",
            "This package contains operational attestations only. It does not mutate clinical facts, create external orders, train models or transfer patient data.",
        ]
    )


def _evidence_manifest_rows(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "evidence_key": row.get("evidence_key"),
            "gate_key": row.get("gate_key"),
            "evidence_type": row.get("evidence_type"),
            "title": row.get("title"),
            "evidence_status": row.get("evidence_status"),
            "evidence_date": row.get("evidence_date"),
            "expires_at": row.get("expires_at"),
            "verified_by": row.get("verified_by"),
            "reviewer_role": row.get("reviewer_role"),
            "evidence_hash": row.get("evidence_hash"),
            "payload_sha256": row.get("payload_sha256"),
        }
        for row in rows
    ]


def _csv_from_rows(rows: list[Mapping[str, Any]]) -> str:
    if not rows:
        return ""
    output = io.StringIO()
    fieldnames = sorted({str(key) for row in rows for key in row.keys()})
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _csv_cell(row.get(key)) for key in fieldnames})
    return output.getvalue()


def _csv_cell(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return "" if value is None else str(value)


def _is_expired(value: str, today: date) -> bool:
    parsed = _parse_date(value)
    return bool(parsed and parsed < today)


def _normalize_date(value: Any) -> str:
    parsed = _parse_date(str(value or "")[:10])
    return parsed.isoformat() if parsed else ""


def _parse_date(value: str) -> date | None:
    text = str(value or "").strip()[:10]
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _add_days(date_text: str, days: int) -> str:
    parsed = _parse_date(date_text) or date.today()
    return (parsed + timedelta(days=max(1, int(days or 1)))).isoformat()


def _clean_text(value: Any, default: str) -> str:
    text = " ".join(str(value or "").strip().split())
    return text or default


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
