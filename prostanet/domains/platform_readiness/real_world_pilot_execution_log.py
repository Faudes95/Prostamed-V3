"""No-PHI execution log for the prospective real-world pilot.

The log answers a different question than the runbook: not "what should we
do?", but "what proof do we have right now and what is still blocked?". It is
read-only and never stores patient identifiers or mutates clinical facts.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

from prostanet.domains.platform_readiness.prospective_real_world_completion_queue import (
    build_prospective_real_world_completion_queue,
)
from prostanet.domains.platform_readiness.real_world_pilot_packet import (
    build_real_world_pilot_packet,
)
from prostanet.domains.platform_readiness.real_world_sample_maturity import (
    build_real_world_sample_maturity_gate,
)
from prostanet.shared.utc_time import utc_now_iso


REAL_WORLD_PILOT_EXECUTION_LOG_VERSION = "real_world_pilot_execution_log_v1"

DIRECT_IDENTIFIER_KEYS = {
    "nss",
    "patient_id",
    "patient_ref",
    "patient_name",
    "full_name",
    "dob",
    "date_of_birth",
    "profile_url",
    "capture_url",
}


def build_real_world_pilot_execution_log(
    *,
    scope: str = "summary",
    limit: int = 100,
    real_world_sample_maturity: Mapping[str, Any] | None = None,
    prospective_real_world_completion_queue: Mapping[str, Any] | None = None,
    real_world_pilot_packet: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a no-PHI operational log for the real-world pilot."""
    scope_key = "summary" if str(scope or "").strip().lower() == "summary" else "full"
    safe_limit = max(1, min(int(limit or 100), 500))
    sample = dict(
        real_world_sample_maturity
        or build_real_world_sample_maturity_gate(scope="summary", limit=safe_limit)
    )
    queue = dict(
        prospective_real_world_completion_queue
        or build_prospective_real_world_completion_queue(
            scope="summary",
            limit=safe_limit,
            real_world_sample_maturity=sample,
        )
    )
    packet = dict(
        real_world_pilot_packet
        or build_real_world_pilot_packet(
            scope="summary",
            limit=safe_limit,
            real_world_sample_maturity=sample,
            prospective_real_world_completion_queue=queue,
        )
    )
    dry_run = _dry_run_contract_evidence()
    entries = _build_log_entries(sample, queue, packet, dry_run)
    summary = _build_summary(entries, sample, queue, packet, dry_run)
    payload: dict[str, Any] = {
        "available": True,
        "source": "prospective_real_world_pilot_execution_log",
        "version": REAL_WORLD_PILOT_EXECUTION_LOG_VERSION,
        "computed_at": utc_now_iso(),
        "scope": scope_key,
        "read_only": True,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "external_transfer_performed": False,
        "clinical_values_captured_here": False,
        "deidentified_export_written": False,
        "clinical_internal_surface": True,
        "summary": summary,
        "execution_log_preview": entries[:5],
        "recommended_next_actions": _recommended_actions(summary),
        "trace_contract": _trace_contract(),
        "no_phi_scan": _scan_for_phi(
            {
                "summary": summary,
                "execution_log_preview": entries,
                "recommended_next_actions": _recommended_actions(summary),
                "trace_contract": _trace_contract(),
            }
        ),
    }
    if scope_key == "full":
        payload["execution_log"] = entries
        payload["dry_run_evidence"] = dry_run
        payload["governance_policy"] = _governance_policy()
    return payload


def build_real_world_pilot_execution_log_markdown_bytes(
    log: Mapping[str, Any] | None = None,
) -> bytes:
    """Return a no-PHI markdown execution log."""
    payload = dict(log or build_real_world_pilot_execution_log(scope="full", limit=100))
    summary = payload.get("summary") or {}
    lines = [
        "# Bitacora operacional del piloto real-world",
        "",
        f"- Version: {payload.get('version')}",
        f"- Estado: {summary.get('log_status')}",
        f"- Dry-run: {summary.get('dry_run_contract_status')}",
        f"- Pacientes reales actuales: {summary.get('real_patient_count', 0)}",
        f"- Siguiente paso: {summary.get('operational_next_step')}",
        "",
        "## Entradas",
    ]
    for entry in payload.get("execution_log") or payload.get("execution_log_preview") or []:
        lines.append(
            f"- [{entry.get('status')}] {entry.get('title')} "
            f"({entry.get('evidence_key')}): {entry.get('evidence')}"
        )
    lines.extend(["", "## Politica"])
    for item in payload.get("governance_policy") or []:
        lines.append(f"- {item.get('policy')}: {item.get('rule')}")
    lines.append("")
    return "\n".join(lines).encode("utf-8")


def _build_summary(
    entries: list[Mapping[str, Any]],
    sample: Mapping[str, Any],
    queue: Mapping[str, Any],
    packet: Mapping[str, Any],
    dry_run: Mapping[str, Any],
) -> dict[str, Any]:
    sample_summary = sample.get("summary") or {}
    queue_summary = queue.get("summary") or {}
    packet_summary = packet.get("summary") or {}
    real_count = int(sample_summary.get("real_patient_count") or queue_summary.get("real_patient_count") or 0)
    ready_count = int(queue_summary.get("registry_ready_real_count") or 0)
    block_count = sum(1 for item in entries if item.get("status") == "block")
    watch_count = sum(1 for item in entries if item.get("status") == "watch")
    dry_run_status = "pass" if dry_run.get("contract_present") else "block"
    return {
        "log_status": _log_status(dry_run_status, real_count, ready_count, block_count),
        "dry_run_contract_status": dry_run_status,
        "real_patient_count": real_count,
        "synthetic_patient_count": int(sample_summary.get("synthetic_patient_count") or 0),
        "registry_ready_real_count": ready_count,
        "blocked_real_patient_count": int(queue_summary.get("blocked_real_patient_count") or 0),
        "entry_count": len(entries),
        "block_count": block_count,
        "watch_count": watch_count,
        "pass_count": sum(1 for item in entries if item.get("status") == "pass"),
        "packet_status": packet_summary.get("packet_status") or "unknown",
        "sample_maturity_status": sample_summary.get("sample_maturity_status") or "unknown",
        "completion_queue_status": queue_summary.get("queue_status") or "unknown",
        "external_validation_claim_allowed": False,
        "real_world_claim_allowed": bool(queue_summary.get("real_world_claim_allowed")) and ready_count > 0,
        "operational_next_step": _operational_next_step(dry_run_status, real_count, ready_count),
        "evidence_claim_policy": "La bitacora puede demostrar operabilidad, pero no permite claims clinicos real-world sin cohorte real suficiente.",
    }


def _log_status(dry_run_status: str, real_count: int, ready_count: int, block_count: int) -> str:
    if dry_run_status != "pass":
        return "dry_run_contract_missing"
    if real_count <= 0:
        return "dry_run_verified_waiting_first_real_patient"
    if block_count:
        return "real_pilot_execution_blocked"
    if ready_count > 0:
        return "first_real_ready_for_method_review"
    return "real_pilot_capture_in_progress"


def _operational_next_step(dry_run_status: str, real_count: int, ready_count: int) -> str:
    if dry_run_status != "pass":
        return "Restaurar y ejecutar dry-run V2 antes de capturar pacientes reales."
    if real_count <= 0:
        return "Ejecutar captura institucional del primer paciente real siguiendo el paquete V2."
    if ready_count <= 0:
        return "Cerrar completitud real-only y APE longitudinal del primer real capturado."
    return "Preparar revision metodologica no-PHI y primer freeze interno real-world."


def _build_log_entries(
    sample: Mapping[str, Any],
    queue: Mapping[str, Any],
    packet: Mapping[str, Any],
    dry_run: Mapping[str, Any],
) -> list[dict[str, Any]]:
    sample_summary = sample.get("summary") or {}
    queue_summary = queue.get("summary") or {}
    packet_summary = packet.get("summary") or {}
    real_count = int(sample_summary.get("real_patient_count") or 0)
    ready_count = int(queue_summary.get("registry_ready_real_count") or 0)
    return [
        {
            "evidence_key": "dry_run_v2_end_to_end",
            "title": "Dry-run V2 de primer paciente real",
            "status": "pass" if dry_run.get("contract_present") else "block",
            "evidence": dry_run.get("evidence") or "Contrato de prueba no localizado.",
            "benefit": "Prueba consentimiento, actor, APE longitudinal, Perfil V2 y gates antes de tocar la base real.",
            "action": "Mantener esta prueba verde en cada cambio de registro real.",
            "surface": "tests/test_platform_readiness_audit.py",
        },
        {
            "evidence_key": "real_sample_gate",
            "title": "Compuerta QA vs muestra real",
            "status": "pass",
            "evidence": f"{real_count} reales y {sample_summary.get('synthetic_patient_count', 0)} QA/sinteticos separados.",
            "benefit": "Evita que validaciones, demos o smoke tests contaminen evidencia hospitalaria.",
            "action": "Seguir usando is_synthetic=0 solo con consentimiento y actor.",
            "surface": "/api/platform-readiness/real-world-sample-maturity",
        },
        {
            "evidence_key": "first_real_capture",
            "title": "Primer paciente real institucional",
            "status": "block" if real_count <= 0 else "pass",
            "evidence": f"{real_count} pacientes reales en la base viva.",
            "benefit": "Permite pasar de operabilidad QA a evidencia institucional prospectiva.",
            "action": "Capturar primer real con el panel V2." if real_count <= 0 else "Revisar completitud del real capturado.",
            "surface": "/clinical-hub?real_world_enrollment=1#pm2OfficialClassifier",
        },
        {
            "evidence_key": "real_only_completion_queue",
            "title": "Cola real-only de completitud",
            "status": "watch" if real_count <= 0 else ("pass" if ready_count else "block"),
            "evidence": f"{ready_count} reales registry-ready; estado {queue_summary.get('queue_status') or 'unknown'}.",
            "benefit": "Cada metrica futura puede rastrearse paciente-a-gate.",
            "action": "Cerrar brecha dominante por paciente real.",
            "surface": "/platform-readiness#prospective-real-world-completion-queue",
        },
        {
            "evidence_key": "operational_packet",
            "title": "Paquete operativo no-PHI",
            "status": "pass" if packet_summary.get("packet_status") else "block",
            "evidence": f"Estado paquete: {packet_summary.get('packet_status') or 'missing'}.",
            "benefit": "Convierte estrategia en pasos ejecutables para el equipo.",
            "action": "Usar el markdown no-PHI como checklist de campo.",
            "surface": "/api/platform-readiness/real-world-pilot-packet/download",
        },
        {
            "evidence_key": "no_phi_exports",
            "title": "Exports y summaries no-PHI",
            "status": "pass" if _no_phi_status(sample, queue, packet) else "block",
            "evidence": "Los summaries y descargas operativas se basan en subject_id/checklists, no en identificadores directos.",
            "benefit": "Permite direccion, investigacion y auditoria sin filtrar PHI.",
            "action": "Mantener PHI solo en scope=full clinico interno.",
            "surface": "/api/platform-readiness",
        },
        {
            "evidence_key": "claims_governance",
            "title": "Gobernanza de claims real-world",
            "status": "block" if real_count <= 0 else ("watch" if ready_count <= 0 else "pass"),
            "evidence": "Sin claims clinicos/economicos externos hasta tener cohorte real suficiente y paquete metodologico.",
            "benefit": "Protege credibilidad institucional, investigacion y comercializacion futura.",
            "action": "Separar operabilidad, senal interna y validacion externa.",
            "surface": "/platform-readiness#external-validation-worklist",
        },
    ]


def _no_phi_status(*payloads: Mapping[str, Any]) -> bool:
    for payload in payloads:
        scan = payload.get("no_phi_scan") or payload.get("summary_no_phi_scan")
        if scan and scan.get("no_phi_status") != "pass":
            return False
    return True


def _dry_run_contract_evidence() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[3]
    test_file = root / "tests" / "test_platform_readiness_audit.py"
    try:
        text = test_file.read_text(encoding="utf-8")
    except OSError:
        return {
            "contract_present": False,
            "test_file": "tests/test_platform_readiness_audit.py",
            "evidence": "No se pudo leer el archivo de prueba del dry-run.",
            "required_assertions_present": [],
            "missing_assertions": ["test_file_readable"],
        }
    required = {
        "test_first_real_patient_dry_run_v2_persists_consent_ape_profile_and_gates": "dry-run e2e",
        "real_patient_consent_actor_user_id": "actor clinico",
        "biomarker_longitudinal": "APE longitudinal",
        "patient_consents": "consentimiento",
        "consent_signature_evidence": "firma electronica",
        "psaTreatmentTimelineChart": "Perfil V2 timeline tratamiento",
        "psaCombinedTimelineChart": "Perfil V2 timeline combinado",
        "summary_no_phi_scan": "summary no-PHI",
    }
    present = [label for token, label in required.items() if token in text]
    missing = [label for token, label in required.items() if token not in text]
    return {
        "contract_present": not missing,
        "test_file": "tests/test_platform_readiness_audit.py",
        "evidence": f"{len(present)}/{len(required)} asserts/anchors de dry-run presentes.",
        "required_assertions_present": present,
        "missing_assertions": missing,
    }


def _recommended_actions(summary: Mapping[str, Any]) -> list[dict[str, str]]:
    status = str(summary.get("log_status") or "")
    if status == "dry_run_verified_waiting_first_real_patient":
        return [
            {
                "priority": "critical",
                "title": "Ejecutar primer paciente real institucional",
                "action": "Usar el paquete V2; capturar consentimiento, actor, APE longitudinal y verificar cola real-only.",
                "route": "/clinical-hub?real_world_enrollment=1#pm2OfficialClassifier",
            }
        ]
    if status == "dry_run_contract_missing":
        return [
            {
                "priority": "critical",
                "title": "Restaurar dry-run V2",
                "action": "La bitacora no debe avanzar sin prueba e2e de primer real.",
                "route": "/platform-readiness#real-world-pilot-execution-log",
            }
        ]
    return [
        {
            "priority": "high",
            "title": "Cerrar gates real-only",
            "action": "Usar la cola real-only y el perfil V2 para completar el primer real.",
            "route": "/platform-readiness#prospective-real-world-completion-queue",
        }
    ]


def _governance_policy() -> list[dict[str, str]]:
    return [
        {
            "policy": "No mezclar QA con evidencia",
            "rule": "is_synthetic=1 queda excluido de claims clinicos, economicos y epidemiologicos.",
        },
        {
            "policy": "No usar real sin consentimiento",
            "rule": "is_synthetic=0 requiere consentimiento firmado y actor clinico.",
        },
        {
            "policy": "No usar APE aislado para outcomes",
            "rule": "La senal real-world requiere historia APE con fecha y contexto.",
        },
        {
            "policy": "No claim externo",
            "rule": "Validacion externa requiere cohorte real, paquete no-PHI y revision metodologica.",
        },
    ]


def _trace_contract() -> dict[str, Any]:
    return {
        "official_entry_surface": "/clinical-hub?real_world_enrollment=1#pm2OfficialClassifier",
        "pilot_packet": "/api/platform-readiness/real-world-pilot-packet",
        "completion_queue": "/api/platform-readiness/prospective-real-world-completion-queue",
        "sample_maturity": "/api/platform-readiness/real-world-sample-maturity",
        "download": "/api/platform-readiness/real-world-pilot-execution-log/download",
        "writes_only": "none",
        "clinical_values_captured_here": False,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
    }


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
            if re.search(r"\b\d{10,}\b|\bNSS\b", value, re.IGNORECASE):
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
    "REAL_WORLD_PILOT_EXECUTION_LOG_VERSION",
    "build_real_world_pilot_execution_log",
    "build_real_world_pilot_execution_log_markdown_bytes",
]
