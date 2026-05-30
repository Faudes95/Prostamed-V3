"""Real-world sample maturity gate for prospective ProstaMed evidence.

The platform already protects inferential analytics by marking patients as
synthetic by default. This read model makes that protection operational: it
separates QA/smoke/demo records from real hospital evidence and defines the
minimum gates before ProstaMed can claim internal real-world signal or prepare
multicenter validation.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from typing import Any, Mapping

from prostanet.domains.platform_readiness.nas_pilot_evidence_vault import (
    build_nas_pilot_evidence_vault,
)
from prostanet.domains.platform_readiness.pilot_adoption_command_center import (
    build_pilot_adoption_command_center,
)
from prostanet.shared.utc_time import utc_now_iso


REAL_WORLD_SAMPLE_MATURITY_VERSION = "real_world_sample_maturity_gate_v1"

MIN_REAL_FOR_INTERNAL_SIGNAL = 30
MIN_REAL_FOR_EXTERNAL_PREFLIGHT = 50
MIN_REAL_FOR_MULTICENTER_READY = 100
MIN_REGISTRY_READY_PCT = 80.0

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


def build_real_world_sample_maturity_gate(
    *,
    scope: str = "summary",
    limit: int = 100,
    registry: Any | None = None,
    registered_rules: Any | None = None,
    pilot_adoption_command_center: Mapping[str, Any] | None = None,
    nas_pilot_evidence_vault: Mapping[str, Any] | None = None,
    prospective_pilot_governance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a read-only gate separating QA records from real-world evidence."""
    scope_key = "summary" if str(scope or "").strip().lower() == "summary" else "full"
    safe_limit = max(1, min(int(limit or 100), 500))
    rows = _load_identity_rows(limit=safe_limit)
    counts = _load_counts()
    nas_vault = dict(nas_pilot_evidence_vault or build_nas_pilot_evidence_vault(scope="summary", limit=safe_limit))
    adoption = dict(
        pilot_adoption_command_center
        or build_pilot_adoption_command_center(
            scope="summary",
            limit=safe_limit,
            real_only=False,
            nas_pilot_evidence_vault=nas_vault,
        )
    )
    real_adoption = build_pilot_adoption_command_center(
        scope="summary",
        limit=safe_limit,
        real_only=True,
        nas_pilot_evidence_vault=nas_vault,
    )
    pilot = dict(prospective_pilot_governance or _lightweight_pilot_snapshot())
    summary = _build_summary(counts, adoption, real_adoption, nas_vault, pilot)
    payload: dict[str, Any] = {
        "available": True,
        "source": "patient_identity_real_world_sample_maturity",
        "version": REAL_WORLD_SAMPLE_MATURITY_VERSION,
        "computed_at": utc_now_iso(),
        "scope": scope_key,
        "read_only": True,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "external_transfer_performed": False,
        "deidentified": True,
        "clinical_values_captured_here": False,
        "summary": summary,
        "thresholds": _thresholds(),
        "cohort_split": counts,
        "qa_policy": _qa_policy(),
        "write_surface_contract": _write_surface_contract(),
        "recommended_next_actions": _recommended_actions(summary),
        "summary_no_phi_scan": _scan_for_phi({"summary": summary, "cohort_split": counts}),
    }
    if scope_key == "full":
        payload.update(
            {
                "recent_cohort_rows": [_identity_row_to_safe_row(row) for row in rows],
                "readiness_checklist": _readiness_checklist(summary),
                "prospective_enrollment_packet": _prospective_enrollment_packet(summary),
                "no_phi_scan": _scan_for_phi(
                    {
                        "summary": summary,
                        "recent_cohort_rows": [_identity_row_to_safe_row(row) for row in rows],
                        "readiness_checklist": _readiness_checklist(summary),
                        "prospective_enrollment_packet": _prospective_enrollment_packet(summary),
                    }
                ),
            }
        )
    return payload


def build_real_world_sample_maturity_csv_bytes(
    gate: Mapping[str, Any] | None = None,
) -> bytes:
    payload = dict(gate or build_real_world_sample_maturity_gate(scope="full", limit=500))
    rows = payload.get("recent_cohort_rows") or []
    output = io.StringIO()
    fieldnames = [
        "subject_id",
        "evidence_lane",
        "cohort_status",
        "consent_status",
        "created_month",
        "diagnosis_month",
        "synthetic_reason",
        "evidence_usage",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in fieldnames})
    return output.getvalue().encode("utf-8")


def _connect():
    import tracking_db

    return tracking_db._connect()


def _load_counts() -> dict[str, Any]:
    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT COUNT(*) AS total_patient_count,
                   SUM(CASE WHEN COALESCE(is_synthetic, 1) = 0 THEN 1 ELSE 0 END) AS real_patient_count,
                   SUM(CASE WHEN COALESCE(is_synthetic, 1) = 1 THEN 1 ELSE 0 END) AS synthetic_patient_count,
                   SUM(CASE WHEN COALESCE(is_synthetic, 1) = 0
                             AND real_patient_consent_signed_at IS NOT NULL
                             AND TRIM(real_patient_consent_signed_at) <> ''
                            THEN 1 ELSE 0 END) AS real_with_identity_consent_count,
                   SUM(CASE WHEN COALESCE(is_synthetic, 1) = 0
                             AND (real_patient_consent_signed_at IS NULL OR TRIM(real_patient_consent_signed_at) = '')
                            THEN 1 ELSE 0 END) AS real_without_identity_consent_count,
                   SUM(CASE WHEN COALESCE(is_synthetic, 1) = 0
                             AND real_patient_consent_actor_user_id IS NOT NULL
                            THEN 1 ELSE 0 END) AS real_with_actor_count,
                   SUM(CASE WHEN COALESCE(is_synthetic, 1) = 0
                             AND real_patient_consent_actor_user_id IS NULL
                            THEN 1 ELSE 0 END) AS real_without_actor_count,
                   SUM(CASE WHEN COALESCE(is_synthetic, 1) = 1
                             AND real_patient_consent_signed_at IS NOT NULL
                             AND TRIM(real_patient_consent_signed_at) <> ''
                            THEN 1 ELSE 0 END) AS synthetic_with_identity_consent_count
            FROM patient_identity
            """
        ).fetchone()
        reason_rows = conn.execute(
            """
            SELECT COALESCE(synthetic_flag_reason, 'real_or_unspecified') AS reason,
                   COUNT(*) AS count
            FROM patient_identity
            GROUP BY COALESCE(synthetic_flag_reason, 'real_or_unspecified')
            ORDER BY count DESC, reason ASC
            """
        ).fetchall()
        consent_rows = _safe_consent_rows(conn)
        counts = {key: int(row[key] or 0) for key in row.keys()}
        total = counts["total_patient_count"]
        real = counts["real_patient_count"]
        synthetic = counts["synthetic_patient_count"]
        counts.update(
            {
                "real_ratio_pct": round((real / total) * 100, 1) if total else 0.0,
                "synthetic_ratio_pct": round((synthetic / total) * 100, 1) if total else 0.0,
                "synthetic_reason_breakdown": [
                    {"reason": str(item["reason"]), "count": int(item["count"] or 0)}
                    for item in reason_rows
                ],
                "signed_patient_consent_rows": consent_rows["signed_patient_consent_rows"],
                "unique_signed_consent_patients": consent_rows["unique_signed_consent_patients"],
            }
        )
        return counts
    finally:
        conn.close()


def _safe_consent_rows(conn) -> dict[str, int]:
    tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "patient_consents" not in tables:
        return {"signed_patient_consent_rows": 0, "unique_signed_consent_patients": 0}
    row = conn.execute(
        """
        SELECT COUNT(*) AS signed_rows,
               COUNT(DISTINCT patient_id) AS signed_patients
        FROM patient_consents
        WHERE LOWER(COALESCE(status, '')) IN ('signed', 'active', 'consented')
        """
    ).fetchone()
    return {
        "signed_patient_consent_rows": int(row["signed_rows"] or 0),
        "unique_signed_consent_patients": int(row["signed_patients"] or 0),
    }


def _load_identity_rows(*, limit: int) -> list[dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT id, diagnosis_date, created_at,
                   COALESCE(is_synthetic, 1) AS is_synthetic,
                   synthetic_flag_reason,
                   real_patient_consent_signed_at,
                   real_patient_consent_actor_user_id
            FROM patient_identity
            ORDER BY COALESCE(created_at, '') DESC, id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _lightweight_pilot_snapshot() -> dict[str, Any]:
    return {
        "summary": {
            "pilot_status": "lightweight_sample_snapshot",
            "pilot_gate_score": 0,
            "pilot_block_count": 0,
            "ready_for_external_deployment": False,
        },
        "gate_matrix": [],
    }


def _build_summary(
    counts: Mapping[str, Any],
    adoption: Mapping[str, Any],
    real_adoption: Mapping[str, Any],
    nas_vault: Mapping[str, Any],
    pilot: Mapping[str, Any],
) -> dict[str, Any]:
    real_count = int(counts.get("real_patient_count") or 0)
    total = int(counts.get("total_patient_count") or 0)
    consent_gap = int(counts.get("real_without_identity_consent_count") or 0)
    actor_gap = int(counts.get("real_without_actor_count") or 0)
    synthetic_with_consent = int(counts.get("synthetic_with_identity_consent_count") or 0)
    adoption_summary = adoption.get("summary") or {}
    real_adoption_summary = real_adoption.get("summary") or {}
    nas_summary = nas_vault.get("summary") or {}
    pilot_summary = pilot.get("summary") or {}
    real_registry_ready_pct = float(real_adoption_summary.get("registry_ready_pct") or 0)
    nas_completion = float(nas_summary.get("completion_pct") or 0)
    pilot_block_count = int(pilot_summary.get("pilot_block_count") or 0)

    if real_count <= 0:
        status = "blocked_no_real_world_sample"
    elif consent_gap or actor_gap:
        status = "blocked_real_patient_consent_audit_gap"
    elif real_count < MIN_REAL_FOR_INTERNAL_SIGNAL:
        status = "needs_prospective_enrollment"
    elif real_registry_ready_pct < MIN_REGISTRY_READY_PCT:
        status = "needs_real_cohort_completeness"
    elif pilot_block_count:
        status = "needs_pilot_governance_closure"
    elif real_count < MIN_REAL_FOR_EXTERNAL_PREFLIGHT:
        status = "ready_for_internal_real_world_signal"
    elif real_count < MIN_REAL_FOR_MULTICENTER_READY:
        status = "ready_for_external_preflight_not_multicenter"
    else:
        status = "ready_for_multicenter_preflight"

    score = _score(
        real_count=real_count,
        consent_gap=consent_gap,
        actor_gap=actor_gap,
        real_registry_ready_pct=real_registry_ready_pct,
        nas_completion=nas_completion,
        pilot_block_count=pilot_block_count,
    )
    return {
        "sample_maturity_status": status,
        "sample_maturity_score_pct": score,
        "evidence_grade": _evidence_grade(real_count, status),
        "total_patient_count": total,
        "real_patient_count": real_count,
        "synthetic_patient_count": int(counts.get("synthetic_patient_count") or 0),
        "real_ratio_pct": counts.get("real_ratio_pct", 0),
        "real_with_identity_consent_count": int(counts.get("real_with_identity_consent_count") or 0),
        "real_without_identity_consent_count": consent_gap,
        "real_with_actor_count": int(counts.get("real_with_actor_count") or 0),
        "real_without_actor_count": actor_gap,
        "synthetic_with_identity_consent_count": synthetic_with_consent,
        "unique_signed_consent_patients": int(counts.get("unique_signed_consent_patients") or 0),
        "all_patient_registry_ready_pct": adoption_summary.get("registry_ready_pct", 0),
        "real_patient_registry_ready_pct": real_registry_ready_pct,
        "real_patient_count_in_adoption_sample": real_adoption_summary.get("patient_count", 0),
        "real_patient_high_priority_gap_count": real_adoption_summary.get("high_priority_gap_count", 0),
        "nas_evidence_completion_pct": nas_completion,
        "pilot_status": pilot_summary.get("pilot_status"),
        "pilot_block_count": pilot_block_count,
        "min_real_for_internal_signal": MIN_REAL_FOR_INTERNAL_SIGNAL,
        "min_real_for_external_preflight": MIN_REAL_FOR_EXTERNAL_PREFLIGHT,
        "min_real_for_multicenter_ready": MIN_REAL_FOR_MULTICENTER_READY,
        "real_world_claim_allowed": status in {
            "ready_for_internal_real_world_signal",
            "ready_for_external_preflight_not_multicenter",
            "ready_for_multicenter_preflight",
        },
        "external_validation_claim_allowed": status == "ready_for_multicenter_preflight",
        "recommended_next_move": _recommended_next_move(status),
    }


def _score(
    *,
    real_count: int,
    consent_gap: int,
    actor_gap: int,
    real_registry_ready_pct: float,
    nas_completion: float,
    pilot_block_count: int,
) -> float:
    sample_points = min(real_count / MIN_REAL_FOR_EXTERNAL_PREFLIGHT, 1.0) * 35
    consent_points = 20 if real_count and not consent_gap and not actor_gap else 0
    completeness_points = min(real_registry_ready_pct / MIN_REGISTRY_READY_PCT, 1.0) * 20 if real_count else 0
    nas_points = min(nas_completion / 100, 1.0) * 10
    governance_points = 15 if pilot_block_count == 0 else 0
    return round(sample_points + consent_points + completeness_points + nas_points + governance_points, 1)


def _evidence_grade(real_count: int, status: str) -> str:
    if real_count <= 0:
        return "qa_only_no_real_world_claim"
    if status in {"blocked_real_patient_consent_audit_gap", "needs_prospective_enrollment"}:
        return "prospective_seed_not_inferential"
    if status == "ready_for_internal_real_world_signal":
        return "internal_signal_only"
    if status == "ready_for_external_preflight_not_multicenter":
        return "external_preflight_signal"
    if status == "ready_for_multicenter_preflight":
        return "multicenter_preflight_ready"
    return "needs_hardening"


def _identity_row_to_safe_row(row: Mapping[str, Any]) -> dict[str, Any]:
    is_synthetic = int(row.get("is_synthetic") or 1) == 1
    consent_signed = bool(str(row.get("real_patient_consent_signed_at") or "").strip())
    actor_present = row.get("real_patient_consent_actor_user_id") is not None
    return {
        "subject_id": _subject_id(int(row.get("id") or 0)),
        "evidence_lane": "qa_synthetic" if is_synthetic else "real_world",
        "cohort_status": "synthetic_excluded_from_inference" if is_synthetic else "real_inferential_candidate",
        "consent_status": (
            "not_applicable_qa"
            if is_synthetic and not consent_signed
            else "signed_with_actor"
            if consent_signed and actor_present
            else "signed_missing_actor"
            if consent_signed
            else "missing"
        ),
        "created_month": _month(row.get("created_at")),
        "diagnosis_month": _month(row.get("diagnosis_date")),
        "synthetic_reason": str(row.get("synthetic_flag_reason") or ""),
        "evidence_usage": (
            "QA, smoke, visual validation and synthetic fixtures only"
            if is_synthetic
            else "Eligible for real-world evidence only after consent and completeness gates"
        ),
    }


def _readiness_checklist(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        _check(
            "real_patient_seed",
            "Primer paciente real prospectivo capturado",
            int(summary.get("real_patient_count") or 0) > 0,
            f"{summary.get('real_patient_count', 0)} reales",
            "Registrar paciente real solo con consentimiento/aviso aprobado y actor clinico.",
        ),
        _check(
            "consent_audit",
            "Consentimiento y actor documentados",
            int(summary.get("real_without_identity_consent_count") or 0) == 0
            and int(summary.get("real_without_actor_count") or 0) == 0
            and int(summary.get("real_patient_count") or 0) > 0,
            f"sin consentimiento={summary.get('real_without_identity_consent_count', 0)}; sin actor={summary.get('real_without_actor_count', 0)}",
            "Usar mark-real o intake real solo con timestamp y actor_user_id.",
        ),
        _check(
            "internal_sample_size",
            "n real minimo para senal interna",
            int(summary.get("real_patient_count") or 0) >= MIN_REAL_FOR_INTERNAL_SIGNAL,
            f"meta n>={MIN_REAL_FOR_INTERNAL_SIGNAL}",
            "Capturar prospectivamente hasta n real suficiente antes de analizar outcomes.",
        ),
        _check(
            "real_registry_completeness",
            "Completitud real registry-ready",
            float(summary.get("real_patient_registry_ready_pct") or 0) >= MIN_REGISTRY_READY_PCT,
            f"{summary.get('real_patient_registry_ready_pct', 0)}%",
            "Cerrar APE, estadio, patologia, tratamiento y decision en V2 real-only.",
        ),
        _check(
            "nas_governance",
            "NAS/protocolo sin bloqueos de piloto",
            int(summary.get("pilot_block_count") or 0) == 0,
            f"pilot_block_count={summary.get('pilot_block_count', 0)}",
            "Cerrar governance pack y evidence vault antes de reclutar de forma sostenida.",
        ),
    ]


def _check(key: str, title: str, passed: bool, evidence: str, action: str) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "status": "pass" if passed else "block",
        "evidence": evidence,
        "action": action,
    }


def _prospective_enrollment_packet(summary: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "packet_name": "Primer flujo prospectivo real ProstaMed",
        "current_status": summary.get("sample_maturity_status"),
        "claim_boundary": "QA/sinteticos no cuentan para evidencia hospitalaria; real-world claims empiezan solo con pacientes reales consentidos.",
        "minimum_steps": [
            "Aprobar protocolo/aviso o consentimiento local.",
            "Crear o seleccionar paciente real en intake oficial con is_real_patient y consent_signed.",
            "Documentar actor clinico responsable de consentimiento.",
            "Completar APE longitudinal, estadio, patologia/tratamiento y Decision Today en V2.",
            "Revisar huddle de brechas real-only semanalmente.",
            "Congelar paquete no-PHI cuando n real y completitud crucen umbrales.",
        ],
        "success_metric": "n real >= 30, consentimiento/actor 100%, registry-ready real >= 80%, sin bloques de piloto.",
    }


def _recommended_actions(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    status = str(summary.get("sample_maturity_status") or "")
    actions = []
    if status == "blocked_no_real_world_sample":
        actions.append(
            {
                "priority": "critical",
                "title": "Iniciar primer registro prospectivo real",
                "action": "No usar cohortes sinteticas para claims; activar protocolo/consentimiento y capturar el primer paciente real.",
                "route": "/clinical-hub?real_world_enrollment=1#pm2OfficialClassifier",
            }
        )
    if int(summary.get("real_without_identity_consent_count") or 0) or int(summary.get("real_without_actor_count") or 0):
        actions.append(
            {
                "priority": "critical",
                "title": "Corregir auditoria de consentimiento real",
                "action": "Cada paciente real debe tener timestamp de consentimiento y actor_user_id verificable.",
                "route": "/api/cohort/breakdown",
            }
        )
    if float(summary.get("real_patient_registry_ready_pct") or 0) < MIN_REGISTRY_READY_PCT:
        actions.append(
            {
                "priority": "high",
                "title": "Cerrar completitud real-only",
                "action": "Usar Platform Readiness y huddle para cerrar APE, estadio, patologia, tratamiento y Decision Today en pacientes reales.",
                "route": "/api/platform-readiness/pilot-adoption-command-center?scope=full&real_only=1",
            }
        )
    if not actions:
        actions.append(
            {
                "priority": "medium",
                "title": "Preparar freeze no-PHI real-world",
                "action": "Congelar paquete audit_ready real-world y preparar revision externa.",
                "route": "/api/platform-readiness/research-pack-materializer?scope=full",
            }
        )
    return actions


def _recommended_next_move(status: str) -> str:
    return {
        "blocked_no_real_world_sample": "Capturar primer paciente real prospectivo con consentimiento/actor antes de claims.",
        "blocked_real_patient_consent_audit_gap": "Cerrar auditoria de consentimiento/actor en pacientes marcados como reales.",
        "needs_prospective_enrollment": "Continuar enrolamiento prospectivo hasta n real suficiente para senal interna.",
        "needs_real_cohort_completeness": "Cerrar completitud real-only antes de congelar outcomes.",
        "needs_pilot_governance_closure": "Cerrar bloqueos de governance/NAS antes de escalar captura real.",
        "ready_for_internal_real_world_signal": "Congelar primer paquete interno real-world y revisar metodologia.",
        "ready_for_external_preflight_not_multicenter": "Preparar paquete no-PHI para revision externa, aun no multicentro.",
        "ready_for_multicenter_preflight": "Preparar onboarding multicentro con protocolo y diccionario minimo.",
    }.get(status, "Revisar gate de muestra real.")


def _thresholds() -> dict[str, Any]:
    return {
        "min_real_for_internal_signal": MIN_REAL_FOR_INTERNAL_SIGNAL,
        "min_real_for_external_preflight": MIN_REAL_FOR_EXTERNAL_PREFLIGHT,
        "min_real_for_multicenter_ready": MIN_REAL_FOR_MULTICENTER_READY,
        "min_registry_ready_pct": MIN_REGISTRY_READY_PCT,
    }


def _qa_policy() -> dict[str, Any]:
    return {
        "synthetic_default": True,
        "synthetic_records_allowed_for": ["smoke tests", "visual validation", "QA", "demo fixtures"],
        "synthetic_records_excluded_from": ["inferential KPIs", "hospital evidence", "external validation claims"],
        "real_patient_requires": ["is_synthetic=0", "real_patient_consent_signed_at", "actor_user_id"],
        "canonical_breakdown_api": "/api/cohort/breakdown",
    }


def _write_surface_contract() -> dict[str, Any]:
    return {
        "official_registration_surface": "/api/register_patient",
        "promotion_surface": "/api/patients/<patient_ref>/mark-real",
        "v2_enrollment_panel": "components/real_world_enrollment_panel.html",
        "registration_real_flags": ["is_real_patient", "consent_signed", "consent_signed_at", "actor_user_id"],
        "writes_only_identity_metadata": True,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "external_transfer_performed": False,
    }


def _subject_id(patient_id: int) -> str:
    return "sub_" + hashlib.sha256(f"prostanet-real-world-sample:{patient_id}".encode("utf-8")).hexdigest()[:16]


def _month(value: Any) -> str:
    text = str(value or "").strip()
    return text[:7] if len(text) >= 7 else ""


def _scan_for_phi(payload: Mapping[str, Any]) -> dict[str, Any]:
    hits: list[str] = []
    direct_keys: list[str] = []

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
            if re.search(r"/patient_profile/|\\b\\d{10,}\\b|\\bNSS\\b", value, re.IGNORECASE):
                hits.append(path)

    walk(payload)
    return {
        "no_phi_status": "pass" if not hits and not direct_keys else "block",
        "direct_identifier_key_count": len(direct_keys),
        "phi_like_value_count": len(hits),
        "direct_identifier_keys": direct_keys[:20],
        "phi_like_value_paths": hits[:20],
    }


__all__ = [
    "REAL_WORLD_SAMPLE_MATURITY_VERSION",
    "build_real_world_sample_maturity_gate",
    "build_real_world_sample_maturity_csv_bytes",
]
