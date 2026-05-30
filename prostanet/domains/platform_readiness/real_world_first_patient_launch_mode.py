"""No-PHI launch mode for the first institutional real-world patient.

This layer sits above the pilot packet and execution log. It answers "what
exactly should the operator do next, and what should the platform verify after
capture?" without writing clinical facts or exposing identifiers.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from prostanet.domains.platform_readiness.prospective_real_world_completion_queue import (
    build_prospective_real_world_completion_queue,
)
from prostanet.domains.platform_readiness.real_world_pilot_execution_log import (
    build_real_world_pilot_execution_log,
)
from prostanet.domains.platform_readiness.real_world_pilot_packet import (
    build_real_world_pilot_packet,
)
from prostanet.domains.platform_readiness.real_world_sample_maturity import (
    build_real_world_sample_maturity_gate,
)
from prostanet.shared.utc_time import utc_now_iso


REAL_WORLD_FIRST_PATIENT_LAUNCH_MODE_VERSION = "real_world_first_patient_launch_mode_v1"

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


def build_real_world_first_patient_launch_mode(
    *,
    scope: str = "summary",
    limit: int = 100,
    real_world_sample_maturity: Mapping[str, Any] | None = None,
    prospective_real_world_completion_queue: Mapping[str, Any] | None = None,
    real_world_pilot_packet: Mapping[str, Any] | None = None,
    real_world_pilot_execution_log: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a no-PHI guided launch mode for first real-patient execution."""
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
    execution_log = dict(
        real_world_pilot_execution_log
        or build_real_world_pilot_execution_log(
            scope="summary",
            limit=safe_limit,
            real_world_sample_maturity=sample,
            prospective_real_world_completion_queue=queue,
            real_world_pilot_packet=packet,
        )
    )
    steps = _guided_steps(sample, queue, packet, execution_log)
    checks = _post_capture_auto_checks(sample, queue, execution_log)
    summary = _summary(sample, queue, packet, execution_log, steps, checks)
    actions = _recommended_next_actions(summary)
    trace = _trace_contract()
    payload_for_scan = {
        "summary": summary,
        "guided_steps": steps,
        "post_capture_auto_checks": checks,
        "recommended_next_actions": actions,
        "operator_packet_manifest": _operator_packet_manifest(),
        "trace_contract": trace,
    }
    payload: dict[str, Any] = {
        "available": True,
        "source": "real_world_first_patient_launch_mode",
        "version": REAL_WORLD_FIRST_PATIENT_LAUNCH_MODE_VERSION,
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
        "guided_steps_preview": steps[:5],
        "recommended_next_actions": actions,
        "trace_contract": trace,
        "no_phi_scan": _scan_for_phi(payload_for_scan),
    }
    if scope_key == "full":
        payload["guided_steps"] = steps
        payload["post_capture_auto_checks"] = checks
        payload["operator_packet_manifest"] = _operator_packet_manifest()
        payload["governance_policy"] = _governance_policy()
    return payload


def build_real_world_first_patient_launch_mode_markdown_bytes(
    launch_mode: Mapping[str, Any] | None = None,
) -> bytes:
    """Return a no-PHI markdown guide for institutional first-real launch."""
    payload = dict(
        launch_mode
        or build_real_world_first_patient_launch_mode(scope="full", limit=100)
    )
    summary = payload.get("summary") or {}
    lines = [
        "# Modo de ejecucion institucional del primer real",
        "",
        f"- Version: {payload.get('version')}",
        f"- Estado: {summary.get('launch_mode_status')}",
        f"- Dry-run: {summary.get('dry_run_contract_status')}",
        f"- Pacientes reales actuales: {summary.get('real_patient_count', 0)}",
        f"- Siguiente paso: {summary.get('next_operator_action')}",
        "",
        "## Pasos guiados",
    ]
    for step in payload.get("guided_steps") or payload.get("guided_steps_preview") or []:
        lines.append(
            f"- [{step.get('status')}] {step.get('title')} "
            f"({step.get('step_key')}): {step.get('operator_action')}"
        )
    lines.extend(["", "## Verificaciones despues de captura"])
    for check in payload.get("post_capture_auto_checks") or []:
        lines.append(
            f"- [{check.get('status')}] {check.get('check_key')}: "
            f"{check.get('expected_evidence')}"
        )
    lines.extend(["", "## Politica"])
    for item in payload.get("governance_policy") or []:
        lines.append(f"- {item.get('policy')}: {item.get('rule')}")
    lines.append("")
    return "\n".join(lines).encode("utf-8")


def _summary(
    sample: Mapping[str, Any],
    queue: Mapping[str, Any],
    packet: Mapping[str, Any],
    execution_log: Mapping[str, Any],
    steps: list[Mapping[str, Any]],
    checks: list[Mapping[str, Any]],
) -> dict[str, Any]:
    sample_summary = sample.get("summary") or {}
    queue_summary = queue.get("summary") or {}
    packet_summary = packet.get("summary") or {}
    log_summary = execution_log.get("summary") or {}
    real_count = int(sample_summary.get("real_patient_count") or queue_summary.get("real_patient_count") or 0)
    ready_count = int(queue_summary.get("registry_ready_real_count") or 0)
    dry_run_status = str(log_summary.get("dry_run_contract_status") or "block")
    block_count = sum(1 for item in steps if item.get("status") == "block")
    watch_count = sum(1 for item in steps if item.get("status") == "watch")
    pass_count = sum(1 for item in steps if item.get("status") == "pass")
    return {
        "launch_mode_status": _launch_mode_status(dry_run_status, real_count, ready_count),
        "dry_run_contract_status": dry_run_status,
        "real_patient_count": real_count,
        "synthetic_patient_count": int(sample_summary.get("synthetic_patient_count") or 0),
        "registry_ready_real_count": ready_count,
        "blocked_real_patient_count": int(queue_summary.get("blocked_real_patient_count") or 0),
        "block_count": block_count,
        "watch_count": watch_count,
        "pass_count": pass_count,
        "post_capture_check_count": len(checks),
        "packet_status": packet_summary.get("packet_status") or "unknown",
        "execution_log_status": log_summary.get("log_status") or "unknown",
        "completion_queue_status": queue_summary.get("queue_status") or "unknown",
        "external_validation_claim_allowed": False,
        "real_world_claim_allowed": bool(queue_summary.get("real_world_claim_allowed")) and ready_count > 0,
        "next_operator_action": _next_operator_action(dry_run_status, real_count, ready_count),
        "evidence_claim_policy": "Modo operativo sin claims: guia captura real V2 y verificaciones; no autoriza evidencia clinica hasta cohorte real registry-ready.",
        "profile_v2_route_policy": "Abrir perfil V2 solo con identificador clinico interno desde la app; no incluirlo en exports no-PHI.",
    }


def _launch_mode_status(dry_run_status: str, real_count: int, ready_count: int) -> str:
    if dry_run_status != "pass":
        return "blocked_until_dry_run_restored"
    if real_count <= 0:
        return "ready_for_institutional_first_real_capture"
    if ready_count <= 0:
        return "first_real_capture_in_progress"
    return "first_real_ready_for_method_review"


def _next_operator_action(dry_run_status: str, real_count: int, ready_count: int) -> str:
    if dry_run_status != "pass":
        return "Restaurar dry-run V2 antes de iniciar captura real."
    if real_count <= 0:
        return "Abrir Centro clinico V2, seleccionar modulo, registrar consentimiento/actor y capturar historia APE."
    if ready_count <= 0:
        return "Usar la cola real-only para cerrar APE, consentimiento, actor o brecha dominante del primer real."
    return "Preparar revision metodologica interna y freeze no-PHI real-only."


def _guided_steps(
    sample: Mapping[str, Any],
    queue: Mapping[str, Any],
    packet: Mapping[str, Any],
    execution_log: Mapping[str, Any],
) -> list[dict[str, Any]]:
    sample_summary = sample.get("summary") or {}
    queue_summary = queue.get("summary") or {}
    packet_summary = packet.get("summary") or {}
    log_summary = execution_log.get("summary") or {}
    real_count = int(sample_summary.get("real_patient_count") or 0)
    ready_count = int(queue_summary.get("registry_ready_real_count") or 0)
    dry_run_status = str(log_summary.get("dry_run_contract_status") or "block")
    dry_run_pass = dry_run_status == "pass"
    return [
        {
            "step_key": "confirm_v2_surface",
            "title": "Confirmar superficie V2 oficial",
            "status": "pass" if dry_run_pass else "block",
            "surface": "/clinical-hub?real_world_enrollment=1#pm2OfficialClassifier",
            "operator_action": "Entrar por Centro clinico V2; legacy no cuenta como cierre.",
            "expected_evidence": f"Dry-run V2 {dry_run_status}; paquete {packet_summary.get('packet_status') or 'unknown'}.",
            "benefit": "Evita trabajar sobre perfiles o flujos historicos.",
        },
        {
            "step_key": "select_clinical_module",
            "title": "Seleccionar modulo clinico real",
            "status": "ready" if dry_run_pass else "block",
            "surface": "/clinical-hub?real_world_enrollment=1#pm2OfficialClassifier",
            "operator_action": "Usar el clasificador oficial antes de abrir wizard.",
            "expected_evidence": "Modulo elegido desde V2 y consistente con Decision Hoy.",
            "benefit": "Reduce recaptura y errores de etapa clinica.",
        },
        {
            "step_key": "complete_minimum_assessment",
            "title": "Guardar evaluacion minima",
            "status": "ready" if dry_run_pass else "block",
            "surface": "/wizard/<module_id>",
            "operator_action": "Capturar solo facts clinicos necesarios del modulo y guardar draft.",
            "expected_evidence": "assessment_id creado y enlazable al registro.",
            "benefit": "Conecta wizard, registro y perfil V2 sin duplicar APE.",
        },
        {
            "step_key": "sign_real_world_consent",
            "title": "Firmar consentimiento y actor",
            "status": "ready" if dry_run_pass else "block",
            "surface": "real_world_enrollment_panel_v2",
            "operator_action": "Marcar paciente real, consentimiento firmado y actor clinico responsable.",
            "expected_evidence": "Consentimiento firmado, hash de evidencia y actor presentes.",
            "benefit": "Permite separar muestra real de QA con auditoria institucional.",
        },
        {
            "step_key": "capture_ape_history",
            "title": "Capturar historia APE inicial",
            "status": "ready" if dry_run_pass else "block",
            "surface": "psa_history_v2",
            "operator_action": "Registrar al menos dos mediciones con fecha/contexto; no duplicar APE basal.",
            "expected_evidence": "Torre APE y timeline V2 con serie, no muestra aislada.",
            "benefit": "Habilita outcomes longitudinales y evita recaptura.",
        },
        {
            "step_key": "verify_profile_v2",
            "title": "Verificar Perfil V2",
            "status": "pending" if real_count <= 0 else "ready",
            "surface": "patient_profile_v2",
            "operator_action": "Abrir el perfil V2 desde la app y confirmar consentimiento, APE, linea terapeutica y Decision Hoy.",
            "expected_evidence": "Perfil V2 renderiza charts APE-tratamiento, firma y estado clinico.",
            "benefit": "Prueba que backend y UI interpretan los mismos facts.",
        },
        {
            "step_key": "verify_real_only_queue",
            "title": "Revisar cola real-only",
            "status": "pending" if real_count <= 0 else ("pass" if ready_count else "block"),
            "surface": "/platform-readiness#prospective-real-world-completion-queue",
            "operator_action": "Cerrar la brecha dominante del paciente real capturado.",
            "expected_evidence": f"{ready_count} reales registry-ready; cola {queue_summary.get('queue_status') or 'unknown'}.",
            "benefit": "Hace auditable cada metrica futura paciente-a-gate.",
        },
        {
            "step_key": "freeze_no_phi_evidence",
            "title": "Congelar evidencia no-PHI",
            "status": "block" if ready_count <= 0 else "ready",
            "surface": "/api/platform-readiness/research-pack-materializer?scope=full&real_only=1",
            "operator_action": "Solo congelar paquete cuando el primer real este completo y la cola lo permita.",
            "expected_evidence": "Freeze no-PHI con sample real separada de QA.",
            "benefit": "Prepara investigacion y direccion sin exponer identificadores.",
        },
    ]


def _post_capture_auto_checks(
    sample: Mapping[str, Any],
    queue: Mapping[str, Any],
    execution_log: Mapping[str, Any],
) -> list[dict[str, Any]]:
    sample_summary = sample.get("summary") or {}
    queue_summary = queue.get("summary") or {}
    log_summary = execution_log.get("summary") or {}
    real_count = int(sample_summary.get("real_patient_count") or 0)
    ready_count = int(queue_summary.get("registry_ready_real_count") or 0)
    pending_status = "pending" if real_count <= 0 else "ready"
    return [
        {
            "check_key": "sample_maturity_real_increment",
            "status": pending_status,
            "expected_evidence": "real_patient_count incrementa; QA/sinteticos siguen excluidos.",
            "source": "/api/platform-readiness/real-world-sample-maturity",
        },
        {
            "check_key": "consent_actor_integrity",
            "status": pending_status,
            "expected_evidence": "Sin pacientes reales con consentimiento o actor faltante.",
            "source": "/api/platform-readiness/real-world-sample-maturity",
        },
        {
            "check_key": "ape_history_not_isolated",
            "status": pending_status,
            "expected_evidence": "valid_psa_point_count >= 2 y estado history_ready.",
            "source": "/api/platform-readiness/prospective-real-world-completion-queue?scope=full",
        },
        {
            "check_key": "profile_v2_truth",
            "status": pending_status,
            "expected_evidence": "Perfil V2 muestra firma, torre APE, timeline APE-tratamiento y Decision Hoy.",
            "source": "patient_profile_v2",
        },
        {
            "check_key": "real_only_queue_closure",
            "status": "pending" if real_count <= 0 else ("pass" if ready_count else "block"),
            "expected_evidence": "Paciente real sin bloqueantes de consentimiento, actor, APE o evaluacion.",
            "source": "/platform-readiness#prospective-real-world-completion-queue",
        },
        {
            "check_key": "claims_remain_governed",
            "status": "pass" if not log_summary.get("external_validation_claim_allowed") else "block",
            "expected_evidence": "Claims externos permanecen bloqueados hasta revision metodologica.",
            "source": "/platform-readiness#external-validation-worklist",
        },
    ]


def _operator_packet_manifest() -> list[dict[str, Any]]:
    return [
        {"component": "Entrada V2", "kind": "ui", "route": "/clinical-hub?real_world_enrollment=1#pm2OfficialClassifier", "required": True},
        {"component": "Runbook operativo", "kind": "markdown", "route": "/api/platform-readiness/real-world-pilot-packet/download", "required": True},
        {"component": "Bitacora piloto", "kind": "markdown", "route": "/api/platform-readiness/real-world-pilot-execution-log/download", "required": True},
        {"component": "Modo lanzamiento", "kind": "markdown", "route": "/api/platform-readiness/real-world-first-patient-launch-mode/download", "required": True},
        {"component": "Cola real-only", "kind": "ui", "route": "/platform-readiness#prospective-real-world-completion-queue", "required": True},
        {"component": "Muestra real", "kind": "api", "route": "/api/platform-readiness/real-world-sample-maturity?scope=summary", "required": True},
        {"component": "Perfil V2", "kind": "route_policy", "route": "patient_profile_v2_from_internal_app_only", "required": True},
    ]


def _recommended_next_actions(summary: Mapping[str, Any]) -> list[dict[str, str]]:
    status = str(summary.get("launch_mode_status") or "")
    if status == "blocked_until_dry_run_restored":
        return [
            {
                "priority": "critical",
                "title": "Restaurar dry-run V2",
                "action": "No iniciar captura real hasta que el contrato de primer real vuelva a pasar.",
                "route": "/platform-readiness#real-world-pilot-execution-log",
            }
        ]
    if status == "ready_for_institutional_first_real_capture":
        return [
            {
                "priority": "critical",
                "title": "Ejecutar primer real institucional",
                "action": "Abrir V2, seleccionar modulo, firmar consentimiento/actor y capturar historia APE inicial.",
                "route": "/clinical-hub?real_world_enrollment=1#pm2OfficialClassifier",
            }
        ]
    if status == "first_real_capture_in_progress":
        return [
            {
                "priority": "high",
                "title": "Cerrar completitud del primer real",
                "action": "Usar la cola real-only para cerrar APE, consentimiento, actor o evaluacion faltante.",
                "route": "/platform-readiness#prospective-real-world-completion-queue",
            }
        ]
    return [
        {
            "priority": "medium",
            "title": "Preparar revision metodologica",
            "action": "Generar paquete no-PHI real-only y revisar readiness de primera senal interna.",
            "route": "/api/platform-readiness/research-pack-materializer?scope=full&real_only=1",
        }
    ]


def _trace_contract() -> dict[str, Any]:
    return {
        "official_entry_surface": "/clinical-hub?real_world_enrollment=1#pm2OfficialClassifier",
        "launch_mode_api": "/api/platform-readiness/real-world-first-patient-launch-mode",
        "download": "/api/platform-readiness/real-world-first-patient-launch-mode/download",
        "completion_queue": "/api/platform-readiness/prospective-real-world-completion-queue",
        "sample_maturity": "/api/platform-readiness/real-world-sample-maturity",
        "writes_only": "none",
        "clinical_values_captured_here": False,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
    }


def _governance_policy() -> list[dict[str, str]]:
    return [
        {
            "policy": "V2 como superficie oficial",
            "rule": "El lanzamiento cuenta solo si pasa por V2 y Perfil V2.",
        },
        {
            "policy": "Sin captura en readiness",
            "rule": "Este modo guia y verifica; los hechos clinicos se capturan en flujos clinicos oficiales.",
        },
        {
            "policy": "Sin APE aislado",
            "rule": "La evidencia longitudinal requiere serie con fecha y contexto.",
        },
        {
            "policy": "Sin claims prematuros",
            "rule": "Operabilidad no equivale a evidencia clinica, economica o epidemiologica validada.",
        },
    ]


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
    "REAL_WORLD_FIRST_PATIENT_LAUNCH_MODE_VERSION",
    "build_real_world_first_patient_launch_mode",
    "build_real_world_first_patient_launch_mode_markdown_bytes",
]
