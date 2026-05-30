"""Real-only prospective completion queue for hospital evidence.

This read model is the operational bridge between "a patient is real" and
"this patient can safely contribute to real-world evidence". It reuses the
existing adoption, APE and sample-maturity gates; it does not capture clinical
facts, create orders, train models or export PHI.
"""
from __future__ import annotations

import csv
import io
import re
from collections import Counter
from typing import Any, Mapping

from prostanet.domains.platform_readiness.ape_longitudinal_completion_sprint import (
    build_ape_longitudinal_completion_sprint,
)
from prostanet.domains.platform_readiness.pilot_adoption_command_center import (
    build_pilot_adoption_command_center,
)
from prostanet.domains.platform_readiness.real_world_sample_maturity import (
    build_real_world_sample_maturity_gate,
)
from prostanet.shared.utc_time import utc_now_iso


PROSPECTIVE_REAL_WORLD_COMPLETION_QUEUE_VERSION = "prospective_real_world_completion_queue_v1"

DIRECT_IDENTIFIER_KEYS = {
    "nss",
    "patient_id",
    "patient_ref",
    "patient_name",
    "full_name",
    "dob",
    "date_of_birth",
    "profile_url",
    "capture_route",
    "capture_url",
}


def build_prospective_real_world_completion_queue(
    *,
    scope: str = "summary",
    limit: int = 100,
    real_world_sample_maturity: Mapping[str, Any] | None = None,
    pilot_adoption_command_center: Mapping[str, Any] | None = None,
    ape_longitudinal_completion_sprint: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a read-only real-patient completion queue."""
    scope_key = "summary" if str(scope or "").strip().lower() == "summary" else "full"
    safe_limit = max(1, min(int(limit or 100), 500))
    sample = dict(
        real_world_sample_maturity
        or build_real_world_sample_maturity_gate(scope="summary", limit=safe_limit)
    )
    adoption = dict(
        pilot_adoption_command_center
        or build_pilot_adoption_command_center(scope="full", limit=safe_limit, real_only=True)
    )
    ape = dict(
        ape_longitudinal_completion_sprint
        or build_ape_longitudinal_completion_sprint(
            scope="full",
            limit=safe_limit,
            real_only=True,
            adoption_command_center=adoption,
        )
    )
    identity_audit = _load_real_identity_audit(limit=safe_limit)
    ape_by_ref = {
        str(row.get("patient_ref") or ""): row
        for row in ape.get("ape_worklist") or []
    }
    rows = [
        _build_queue_row(row, identity_audit.get(str(row.get("patient_ref") or ""), {}), ape_by_ref)
        for row in adoption.get("patient_worklist") or []
    ]
    rows = sorted(rows, key=_queue_sort_key)[:safe_limit]
    summary = _build_summary(rows, sample, adoption, ape)
    recommended_actions = _recommended_actions(
        summary,
        rows,
        include_phi_routes=scope_key == "full",
    )
    payload: dict[str, Any] = {
        "available": True,
        "source": "real_only_prospective_completion_queue",
        "version": PROSPECTIVE_REAL_WORLD_COMPLETION_QUEUE_VERSION,
        "computed_at": utc_now_iso(),
        "scope": scope_key,
        "read_only": True,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "external_transfer_performed": False,
        "clinical_values_captured_here": False,
        "clinical_internal_surface": True,
        "deidentified_export_written": False,
        "summary": summary,
        "status_summary": _status_summary(rows),
        "dominant_gap_summary": _dominant_gap_summary(rows),
        "queue_preview": _no_phi_rows(rows[:safe_limit]),
        "recommended_next_actions": recommended_actions,
        "trace_contract": _trace_contract(),
        "summary_no_phi_scan": _scan_for_phi(
            {
                "summary": summary,
                "status_summary": _status_summary(rows),
                "dominant_gap_summary": _dominant_gap_summary(rows),
                "queue_preview": _no_phi_rows(rows[:safe_limit]),
                "recommended_next_actions": _recommended_actions(summary, rows, include_phi_routes=False),
            }
        ),
    }
    if scope_key == "full":
        payload["real_patient_queue"] = rows
        payload["drilldown_policy"] = {
            "surface": "patient_profile_v2",
            "profile_route_template": "/patient_profile/<patient_ref>?v=2",
            "capture_route_policy": "Internal PHI route only; exports use subject_id.",
            "clinical_identifiers_included": True,
        }
    return payload


def build_prospective_real_world_completion_csv_bytes(
    queue: Mapping[str, Any] | None = None,
) -> bytes:
    payload = dict(queue or build_prospective_real_world_completion_queue(scope="full", limit=500))
    rows = _no_phi_rows(payload.get("real_patient_queue") or payload.get("queue_preview") or [])
    output = io.StringIO()
    fieldnames = [
        "subject_id",
        "evidence_use_status",
        "priority",
        "effective_state",
        "completeness_pct",
        "missing_fact_count",
        "dominant_gap_family",
        "top_missing_key",
        "ape_status",
        "claim_allowed",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in fieldnames})
    return output.getvalue().encode("utf-8")


def _connect():
    import tracking_db

    return tracking_db._connect()


def _load_real_identity_audit(*, limit: int) -> dict[str, dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT nss, COALESCE(is_synthetic, 1) AS is_synthetic,
                   real_patient_consent_signed_at,
                   real_patient_consent_actor_user_id,
                   created_at
            FROM patient_identity
            WHERE COALESCE(is_synthetic, 1) = 0
            ORDER BY COALESCE(created_at, '') DESC, id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            item = dict(row)
            result[str(item.get("nss") or "")] = {
                "consent_present": bool(str(item.get("real_patient_consent_signed_at") or "").strip()),
                "actor_present": item.get("real_patient_consent_actor_user_id") is not None,
                "created_month": _month(item.get("created_at")),
            }
        return result
    finally:
        conn.close()


def _build_queue_row(
    adoption_row: Mapping[str, Any],
    identity: Mapping[str, Any],
    ape_by_ref: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    patient_ref = str(adoption_row.get("patient_ref") or "")
    missing_fields = list(adoption_row.get("missing_fields") or [])
    dominant = _dominant_missing(missing_fields)
    ape_row = dict(ape_by_ref.get(patient_ref) or {})
    blockers = _blockers(adoption_row, identity, ape_row)
    status = _evidence_use_status(adoption_row, identity, ape_row, blockers)
    top_missing = missing_fields[0] if missing_fields else {}
    claim_allowed = status == "registry_ready_internal_signal_candidate"
    return {
        "patient_ref": patient_ref,
        "subject_id": adoption_row.get("subject_id") or "",
        "profile_url": adoption_row.get("profile_url") or (f"/patient_profile/{patient_ref}?v=2" if patient_ref else ""),
        "effective_state": adoption_row.get("effective_state") or "",
        "latest_assessment_module": adoption_row.get("latest_assessment_module") or "",
        "completeness_pct": float(adoption_row.get("completeness_pct") or 0),
        "registry_ready": bool(adoption_row.get("registry_ready")),
        "fact_count": int(adoption_row.get("fact_count") or 0),
        "psa_point_count": int(adoption_row.get("psa_point_count") or 0),
        "treatment_count": int(adoption_row.get("treatment_count") or 0),
        "event_count": int(adoption_row.get("event_count") or 0),
        "missing_fact_count": int(adoption_row.get("missing_fact_count") or 0),
        "missing_fields": missing_fields,
        "dominant_gap_family": dominant.get("family") or "",
        "top_missing_key": top_missing.get("key") or "",
        "top_missing_label": top_missing.get("label") or "",
        "top_capture_route": top_missing.get("capture_route") or ape_row.get("capture_url") or "",
        "ape_status": ape_row.get("ape_status") or ("history_ready" if int(adoption_row.get("psa_point_count") or 0) >= 2 else "missing_or_single_point"),
        "valid_psa_point_count": int(ape_row.get("valid_psa_point_count") or adoption_row.get("psa_point_count") or 0),
        "ape_capture_url": ape_row.get("capture_url") or "",
        "consent_present": bool(identity.get("consent_present")),
        "actor_present": bool(identity.get("actor_present")),
        "created_month": identity.get("created_month") or "",
        "blockers": blockers,
        "evidence_use_status": status,
        "priority": _priority(status, blockers, adoption_row),
        "claim_allowed": claim_allowed,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
    }


def _dominant_missing(missing_fields: list[Mapping[str, Any]]) -> dict[str, Any]:
    if not missing_fields:
        return {}
    families = Counter(str(item.get("family") or "unknown") for item in missing_fields)
    family = families.most_common(1)[0][0]
    return {"family": family, "count": int(families[family])}


def _blockers(
    row: Mapping[str, Any],
    identity: Mapping[str, Any],
    ape_row: Mapping[str, Any],
) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    if not identity.get("consent_present"):
        blockers.append({"key": "consent_missing", "label": "Consentimiento real no documentado", "family": "governance"})
    if not identity.get("actor_present"):
        blockers.append({"key": "actor_missing", "label": "Actor clinico no documentado", "family": "governance"})
    if not row.get("latest_assessment_module"):
        blockers.append({"key": "assessment_missing", "label": "Evaluacion clinica vinculada faltante", "family": "workflow"})
    if int(row.get("psa_point_count") or 0) <= 0:
        blockers.append({"key": "ape_missing", "label": "APE no documentado", "family": "biochemical"})
    elif str(ape_row.get("ape_status") or "") not in {"", "history_ready"}:
        blockers.append({"key": "ape_history_incomplete", "label": "Historial APE insuficiente", "family": "biochemical"})
    if not row.get("registry_ready"):
        blockers.append({"key": "registry_incomplete", "label": "Completitud registry-ready incompleta", "family": "registry"})
    return blockers


def _evidence_use_status(
    row: Mapping[str, Any],
    identity: Mapping[str, Any],
    ape_row: Mapping[str, Any],
    blockers: list[Mapping[str, str]],
) -> str:
    blocker_keys = {item.get("key") for item in blockers}
    if "consent_missing" in blocker_keys or "actor_missing" in blocker_keys:
        return "blocked_missing_consent_audit"
    if "assessment_missing" in blocker_keys:
        return "blocked_no_decision_assessment"
    if "ape_missing" in blocker_keys:
        return "blocked_no_ape"
    if "ape_history_incomplete" in blocker_keys:
        return "needs_ape_history"
    if not row.get("registry_ready"):
        return "needs_registry_completion"
    if identity.get("consent_present") and identity.get("actor_present") and row.get("registry_ready"):
        return "registry_ready_internal_signal_candidate"
    return "needs_review"


def _priority(status: str, blockers: list[Mapping[str, str]], row: Mapping[str, Any]) -> str:
    if status.startswith("blocked"):
        return "critical"
    if status in {"needs_ape_history", "needs_registry_completion"}:
        return "high" if float(row.get("completeness_pct") or 0) < 80 else "medium"
    if status == "registry_ready_internal_signal_candidate":
        return "ready"
    return "medium"


def _queue_sort_key(row: Mapping[str, Any]) -> tuple[int, float, str]:
    ranks = {"critical": 0, "high": 1, "medium": 2, "ready": 3, "routine": 4}
    return (
        ranks.get(str(row.get("priority") or ""), 9),
        float(row.get("completeness_pct") or 0),
        str(row.get("subject_id") or ""),
    )


def _build_summary(
    rows: list[Mapping[str, Any]],
    sample: Mapping[str, Any],
    adoption: Mapping[str, Any],
    ape: Mapping[str, Any],
) -> dict[str, Any]:
    sample_summary = sample.get("summary") or {}
    adoption_summary = adoption.get("summary") or {}
    ape_summary = ape.get("summary") or {}
    ready_count = sum(1 for row in rows if row.get("claim_allowed"))
    blocked_count = sum(1 for row in rows if str(row.get("priority")) == "critical")
    real_count = int(sample_summary.get("real_patient_count") or adoption_summary.get("patient_count") or len(rows))
    return {
        "queue_status": _queue_status(real_count, ready_count, blocked_count, rows),
        "real_patient_count": real_count,
        "queued_real_patient_count": len(rows),
        "registry_ready_real_count": ready_count,
        "blocked_real_patient_count": blocked_count,
        "high_priority_real_patient_count": sum(1 for row in rows if row.get("priority") == "high"),
        "registry_ready_real_pct": _pct(ready_count, real_count),
        "mean_real_completeness_pct": round(
            sum(float(row.get("completeness_pct") or 0) for row in rows) / len(rows),
            1,
        ) if rows else 0.0,
        "sample_maturity_status": sample_summary.get("sample_maturity_status"),
        "sample_maturity_score_pct": sample_summary.get("sample_maturity_score_pct", 0),
        "real_patient_registry_ready_pct_from_adoption": adoption_summary.get("registry_ready_pct", 0),
        "ape_history_ready_pct": ape_summary.get("history_ready_pct", 0),
        "external_validation_claim_allowed": bool(sample_summary.get("external_validation_claim_allowed")) and ready_count >= 100,
        "real_world_claim_allowed": bool(sample_summary.get("real_world_claim_allowed")) and ready_count > 0,
        "recommended_next_move": _recommended_next_move(real_count, ready_count, blocked_count, rows),
    }


def _queue_status(real_count: int, ready_count: int, blocked_count: int, rows: list[Mapping[str, Any]]) -> str:
    if real_count <= 0:
        return "no_real_patients_enrolled"
    if blocked_count:
        return "real_patients_blocked"
    if ready_count == real_count and real_count:
        return "real_registry_ready"
    if rows:
        return "real_completion_in_progress"
    return "needs_review"


def _recommended_next_move(real_count: int, ready_count: int, blocked_count: int, rows: list[Mapping[str, Any]]) -> str:
    if real_count <= 0:
        return "Capturar primer paciente real prospectivo con consentimiento y actor clinico."
    if blocked_count:
        first = next((row for row in rows if row.get("priority") == "critical"), {})
        return f"Cerrar bloqueante {first.get('top_missing_label') or first.get('evidence_use_status') or 'real-only'} en el primer paciente real."
    if ready_count <= 0:
        return "Cerrar completitud registry-ready y APE longitudinal en pacientes reales."
    return "Preparar freeze no-PHI real-world interno y revisar metodologia."


def _status_summary(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    counts = Counter(str(row.get("evidence_use_status") or "unknown") for row in rows)
    return [{"status": key, "count": int(value)} for key, value in sorted(counts.items())]


def _dominant_gap_summary(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    counts = Counter(str(row.get("dominant_gap_family") or "none") for row in rows)
    return [{"family": key, "count": int(value)} for key, value in sorted(counts.items())]


def _recommended_actions(
    summary: Mapping[str, Any],
    rows: list[Mapping[str, Any]],
    *,
    include_phi_routes: bool = False,
) -> list[dict[str, Any]]:
    if int(summary.get("real_patient_count") or 0) <= 0:
        return [
            {
                "priority": "critical",
                "title": "Capturar primer paciente real prospectivo",
                "action": "Usar el panel V2 de muestra real, firma electronica y actor clinico.",
                "route": "/clinical-hub?real_world_enrollment=1#pm2OfficialClassifier",
            }
        ]
    actions = []
    for row in rows[:5]:
        if row.get("claim_allowed"):
            continue
        route = "/platform-readiness#prospective-real-world-completion-queue"
        if include_phi_routes:
            route = row.get("top_capture_route") or row.get("ape_capture_url") or row.get("profile_url") or route
        actions.append(
            {
                "priority": row.get("priority") or "high",
                "title": row.get("top_missing_label") or row.get("evidence_use_status") or "Cerrar completitud real",
                "action": "Cerrar el faltante dominante para que el paciente real pueda entrar a evidencia.",
                "route": route,
            }
        )
    return actions or [
        {
            "priority": "medium",
            "title": "Preparar primer freeze real-world",
            "action": "La cohorte real esta lista para paquete interno no-PHI.",
            "route": "/api/platform-readiness/research-pack-materializer?scope=full&real_only=1",
        }
    ]


def _trace_contract() -> dict[str, Any]:
    return {
        "official_real_enrollment_surface": "components/real_world_enrollment_panel.html",
        "official_registration_surface": "/api/register_patient",
        "official_longitudinal_ape_surface": "/longitudinal-capture/<patient_ref>?decision_field=psa_history",
        "profile_surface": "/patient_profile/<patient_ref>?v=2",
        "writes_only": "none",
        "clinical_values_captured_here": False,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "external_transfer_performed": False,
        "no_phi_export": "/api/platform-readiness/prospective-real-world-completion-queue/export",
    }


def _no_phi_rows(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "subject_id": row.get("subject_id") or "",
            "evidence_use_status": row.get("evidence_use_status") or "",
            "priority": row.get("priority") or "",
            "effective_state": row.get("effective_state") or "",
            "completeness_pct": row.get("completeness_pct") or 0,
            "missing_fact_count": row.get("missing_fact_count") or 0,
            "dominant_gap_family": row.get("dominant_gap_family") or "",
            "top_missing_key": row.get("top_missing_key") or "",
            "ape_status": row.get("ape_status") or "",
            "claim_allowed": bool(row.get("claim_allowed")),
        }
        for row in rows
    ]


def _pct(numerator: int, denominator: int) -> float:
    return round((int(numerator or 0) / max(1, int(denominator or 0))) * 100, 1)


def _month(value: Any) -> str:
    text = str(value or "").strip()
    return text[:7] if len(text) >= 7 else ""


def _scan_for_phi(payload: Mapping[str, Any]) -> dict[str, Any]:
    direct_keys: list[str] = []
    phi_hits: list[str] = []

    def walk(value: Any, path: str = "") -> None:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                key_text = str(key)
                nested_path = f"{path}.{key_text}" if path else key_text
                if key_text.lower() in DIRECT_IDENTIFIER_KEYS:
                    direct_keys.append(nested_path)
                walk(nested, nested_path)
        elif isinstance(value, list | tuple):
            for index, nested in enumerate(value):
                walk(nested, f"{path}[{index}]")
        elif isinstance(value, str):
            if re.search(r"/patient_profile/|/longitudinal-capture/|\\b\\d{10,}\\b|\\bNSS\\b", value, re.IGNORECASE):
                phi_hits.append(path)

    walk(payload)
    return {
        "no_phi_status": "pass" if not direct_keys and not phi_hits else "block",
        "direct_identifier_key_count": len(direct_keys),
        "phi_like_value_count": len(phi_hits),
        "direct_identifier_keys": direct_keys[:20],
        "phi_like_value_paths": phi_hits[:20],
    }


__all__ = [
    "PROSPECTIVE_REAL_WORLD_COMPLETION_QUEUE_VERSION",
    "build_prospective_real_world_completion_csv_bytes",
    "build_prospective_real_world_completion_queue",
]
