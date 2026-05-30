"""Operational packet for the first prospective real-world patient.

This read model turns the real-only gates into a launch runbook. It is
deliberately no-PHI and does not mutate clinical facts, create orders, train
models or export patient-level records.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from prostanet.domains.platform_readiness.prospective_real_world_completion_queue import (
    build_prospective_real_world_completion_queue,
)
from prostanet.domains.platform_readiness.real_world_sample_maturity import (
    build_real_world_sample_maturity_gate,
)
from prostanet.shared.utc_time import utc_now_iso


REAL_WORLD_PILOT_PACKET_VERSION = "real_world_pilot_packet_v1"

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


def build_real_world_pilot_packet(
    *,
    scope: str = "summary",
    limit: int = 100,
    real_world_sample_maturity: Mapping[str, Any] | None = None,
    prospective_real_world_completion_queue: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a no-PHI operational packet for prospective real capture."""
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
    sample_summary = dict(sample.get("summary") or {})
    queue_summary = dict(queue.get("summary") or {})
    checklist = _build_launch_checklist(sample_summary, queue_summary)
    summary = _build_summary(sample_summary, queue_summary, checklist)
    payload: dict[str, Any] = {
        "available": True,
        "source": "prospective_real_world_first_patient_packet",
        "version": REAL_WORLD_PILOT_PACKET_VERSION,
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
        "launch_checklist": checklist if scope_key == "full" else checklist[:5],
        "required_capture_fields": _required_capture_fields(),
        "recommended_next_actions": _recommended_actions(summary),
        "trace_contract": _trace_contract(),
        "no_phi_scan": _scan_for_phi(
            {
                "summary": summary,
                "launch_checklist": checklist,
                "required_capture_fields": _required_capture_fields(),
                "recommended_next_actions": _recommended_actions(summary),
                "trace_contract": _trace_contract(),
            }
        ),
    }
    if scope_key == "full":
        payload["capture_workflow"] = _capture_workflow()
        payload["post_capture_verification"] = _post_capture_verification()
        payload["stop_rules"] = _stop_rules()
        payload["pilot_packet_manifest"] = _pilot_packet_manifest()
    return payload


def build_real_world_pilot_packet_markdown_bytes(
    packet: Mapping[str, Any] | None = None,
) -> bytes:
    """Return a no-PHI markdown runbook for the first real patient pilot."""
    payload = dict(packet or build_real_world_pilot_packet(scope="full", limit=100))
    summary = payload.get("summary") or {}
    lines = [
        "# Paquete operativo: primer paciente real prospectivo",
        "",
        f"- Version: {payload.get('version')}",
        f"- Estado: {summary.get('packet_status')}",
        f"- Pacientes reales actuales: {summary.get('real_patient_count', 0)}",
        f"- Siguiente paso: {summary.get('operational_next_step')}",
        "",
        "## Checklist",
    ]
    for item in payload.get("launch_checklist") or []:
        lines.append(f"- [{item.get('status')}] {item.get('title')}: {item.get('action')}")
    lines.extend(["", "## Flujo V2"])
    for step in payload.get("capture_workflow") or []:
        lines.append(f"{step.get('step')}. {step.get('title')} - {step.get('action')}")
    lines.extend(["", "## Reglas de alto"])
    for rule in payload.get("stop_rules") or []:
        lines.append(f"- {rule.get('title')}: {rule.get('reason')}")
    lines.append("")
    return "\n".join(lines).encode("utf-8")


def _build_summary(
    sample_summary: Mapping[str, Any],
    queue_summary: Mapping[str, Any],
    checklist: list[Mapping[str, Any]],
) -> dict[str, Any]:
    real_count = int(sample_summary.get("real_patient_count") or queue_summary.get("real_patient_count") or 0)
    ready_count = int(queue_summary.get("registry_ready_real_count") or 0)
    blocked_count = int(queue_summary.get("blocked_real_patient_count") or 0)
    block_count = sum(1 for item in checklist if item.get("status") == "block")
    watch_count = sum(1 for item in checklist if item.get("status") == "watch")
    return {
        "packet_status": _packet_status(real_count, ready_count, blocked_count, block_count),
        "real_patient_count": real_count,
        "synthetic_patient_count": int(sample_summary.get("synthetic_patient_count") or 0),
        "registry_ready_real_count": ready_count,
        "blocked_real_patient_count": blocked_count,
        "launch_block_count": block_count,
        "launch_watch_count": watch_count,
        "sample_maturity_status": sample_summary.get("sample_maturity_status") or "unknown",
        "completion_queue_status": queue_summary.get("queue_status") or "unknown",
        "external_validation_claim_allowed": False,
        "real_world_claim_allowed": bool(queue_summary.get("real_world_claim_allowed")) and ready_count > 0,
        "operational_next_step": _operational_next_step(real_count, ready_count, blocked_count),
        "evidence_claim_policy": "No claim real-world hasta tener paciente real consentido, actor documentado, APE longitudinal y registry-ready.",
    }


def _packet_status(real_count: int, ready_count: int, blocked_count: int, block_count: int) -> str:
    if real_count <= 0:
        return "ready_to_capture_first_real_patient"
    if blocked_count or block_count:
        return "real_capture_blocked_until_gaps_close"
    if ready_count > 0:
        return "first_real_patient_ready_for_internal_signal_review"
    return "real_capture_in_progress"


def _operational_next_step(real_count: int, ready_count: int, blocked_count: int) -> str:
    if real_count <= 0:
        return "Registrar primer paciente real desde V2 con consentimiento, actor clinico y serie APE inicial."
    if blocked_count:
        return "Cerrar bloqueantes de consentimiento, actor, evaluacion o APE en la cola real-only."
    if ready_count <= 0:
        return "Completar APE longitudinal y campos registry-ready antes de usar evidencia."
    return "Revisar primer freeze interno no-PHI y metodologia de cohorte."


def _build_launch_checklist(
    sample_summary: Mapping[str, Any],
    queue_summary: Mapping[str, Any],
) -> list[dict[str, Any]]:
    real_count = int(sample_summary.get("real_patient_count") or 0)
    real_without_consent = int(sample_summary.get("real_without_identity_consent_count") or 0)
    real_without_actor = int(sample_summary.get("real_without_actor_count") or 0)
    ready_count = int(queue_summary.get("registry_ready_real_count") or 0)
    blocked_count = int(queue_summary.get("blocked_real_patient_count") or 0)
    return [
        {
            "key": "v2_enrollment_surface",
            "title": "Panel V2 de muestra real disponible",
            "status": "pass",
            "evidence": "clinical_wizard.html y patient_intake.html incluyen real_world_enrollment_panel.",
            "action": "Usar V2; legacy no cuenta como cierre.",
        },
        {
            "key": "registration_guard",
            "title": "Guardia backend de consentimiento y actor",
            "status": "pass",
            "evidence": "register_patient rechaza muestra real sin consentimiento firmado y actor_user_id.",
            "action": "No capturar paciente real si falta actor clinico responsable.",
        },
        {
            "key": "first_real_patient",
            "title": "Primer paciente real prospectivo",
            "status": "block" if real_count <= 0 else "pass",
            "evidence": f"{real_count} pacientes reales en la base visible.",
            "action": "Activar Paciente real en V2 y documentar consentimiento." if real_count <= 0 else "Mantener separacion QA vs real.",
        },
        {
            "key": "consent_actor_integrity",
            "title": "Consentimiento y actor completos",
            "status": "block" if real_count and (real_without_consent or real_without_actor) else ("watch" if real_count <= 0 else "pass"),
            "evidence": f"{real_without_consent} sin consentimiento; {real_without_actor} sin actor.",
            "action": "Corregir auditoria de consentimiento antes de usar evidencia real.",
        },
        {
            "key": "ape_longitudinal_initial_series",
            "title": "APE longitudinal inicial",
            "status": "watch" if real_count <= 0 else ("pass" if float(queue_summary.get("ape_history_ready_pct") or 0) >= 80 else "block"),
            "evidence": f"{queue_summary.get('ape_history_ready_pct', 0)}% de historia APE lista en real-only.",
            "action": "Capturar al menos dos mediciones APE con fecha y contexto.",
        },
        {
            "key": "registry_ready_minimum",
            "title": "Completitud registry-ready",
            "status": "watch" if real_count <= 0 else ("pass" if ready_count > 0 and not blocked_count else "block"),
            "evidence": f"{ready_count} reales listos; {blocked_count} bloqueados.",
            "action": "Cerrar la brecha dominante en la cola real-only.",
        },
        {
            "key": "no_phi_export_ready",
            "title": "Export no-PHI preparado",
            "status": "pass",
            "evidence": "Los paquetes y colas salen con subject_id y sin identificadores directos.",
            "action": "Usar exports no-PHI para revision, investigacion y direccion.",
        },
    ]


def _required_capture_fields() -> list[dict[str, str]]:
    return [
        {"field": "assessment_id", "why": "Vincula el paciente a evaluacion clinica y DECISION HOY."},
        {"field": "assessment_state", "why": "Define etapa clinica inicial para la captura progresiva."},
        {"field": "is_real_patient=1", "why": "Separa evidencia real de QA/sintetico."},
        {"field": "consent_signed=1", "why": "Prueba minima de consentimiento para uso secundario."},
        {"field": "actor_user_id", "why": "Responsable clinico auditable de la verificacion."},
        {"field": "psa_history", "why": "Evita APE aislado; habilita torre APE, tendencias y outcomes."},
        {"field": "registration_context", "why": "Preserva tratamiento, regimen, dosis y contexto longitudinal si existe."},
    ]


def _capture_workflow() -> list[dict[str, str]]:
    return [
        {
            "step": "1",
            "title": "Abrir Centro clinico V2",
            "action": "Usar el clasificador oficial y seleccionar el modulo clinico real del paciente.",
            "surface": "/clinical-hub?real_world_enrollment=1#pm2OfficialClassifier",
        },
        {
            "step": "2",
            "title": "Completar evaluacion minima",
            "action": "Guardar draft clinico con APE, etapa, patologia/biopsia o sospecha segun el caso.",
            "surface": "/wizard/<module_id>",
        },
        {
            "step": "3",
            "title": "Activar muestra real",
            "action": "En registro V2 marcar Paciente real, confirmar firma y capturar actor_user_id.",
            "surface": "real_world_enrollment_panel_v2",
        },
        {
            "step": "4",
            "title": "Capturar historial APE",
            "action": "Agregar serie inicial con fechas; evitar repetir el APE basal como campo aislado.",
            "surface": "longitudinal_capture_v2",
        },
        {
            "step": "5",
            "title": "Verificar perfil V2",
            "action": "Confirmar consentimiento, torre APE, DECISION HOY y linea terapeutica actual si aplica.",
            "surface": "patient_profile_v2",
        },
        {
            "step": "6",
            "title": "Revisar cola real-only",
            "action": "Confirmar si el paciente queda registry-ready o que brecha dominante debe cerrarse.",
            "surface": "/platform-readiness#prospective-real-world-completion-queue",
        },
    ]


def _post_capture_verification() -> list[dict[str, str]]:
    return [
        {"check": "sample_maturity", "evidence": "real_patient_count incrementa y synthetic_patient_count no se mezcla."},
        {"check": "completion_queue", "evidence": "Paciente real aparece solo en scope=full interno; summary queda no-PHI."},
        {"check": "profile_v2", "evidence": "Consentimiento, APE y tratamiento se renderizan en V2, no legacy."},
        {"check": "no_phi_exports", "evidence": "CSV/Markdown usan subject_id y no NSS/nombre/fecha nacimiento."},
    ]


def _stop_rules() -> list[dict[str, str]]:
    return [
        {
            "title": "Sin consentimiento firmado",
            "reason": "Debe quedar QA/sintetico; no entra a evidencia real.",
        },
        {
            "title": "Sin actor clinico",
            "reason": "No hay responsable auditable de la verificacion de uso secundario.",
        },
        {
            "title": "APE aislado",
            "reason": "No alcanza para outcomes longitudinales; capturar historia antes de claims.",
        },
        {
            "title": "Conflicto critico Ledger",
            "reason": "Primero reconciliar fact critico antes de usar metricas o recomendaciones.",
        },
    ]


def _pilot_packet_manifest() -> list[dict[str, Any]]:
    return [
        {"component": "Real-world sample maturity", "kind": "api", "url": "/api/platform-readiness/real-world-sample-maturity?scope=summary", "required": True},
        {"component": "Real-only completion queue", "kind": "api", "url": "/api/platform-readiness/prospective-real-world-completion-queue?scope=summary", "required": True},
        {"component": "Operational packet", "kind": "markdown", "url": "/api/platform-readiness/real-world-pilot-packet/download", "required": True},
        {"component": "Platform readiness", "kind": "ui", "url": "/platform-readiness", "required": True},
    ]


def _recommended_actions(summary: Mapping[str, Any]) -> list[dict[str, str]]:
    status = str(summary.get("packet_status") or "")
    if status == "ready_to_capture_first_real_patient":
        return [
            {
                "priority": "critical",
                "title": "Capturar primer paciente real prospectivo",
                "action": "Abrir V2, activar muestra real, documentar consentimiento y actor, y capturar APE longitudinal.",
                "route": "/clinical-hub?real_world_enrollment=1#pm2OfficialClassifier",
            }
        ]
    if status == "real_capture_blocked_until_gaps_close":
        return [
            {
                "priority": "critical",
                "title": "Cerrar bloqueantes real-only",
                "action": "Revisar cola real-only y cerrar consentimiento, actor, evaluacion, APE o registry-ready.",
                "route": "/platform-readiness#prospective-real-world-completion-queue",
            }
        ]
    return [
        {
            "priority": "medium",
            "title": "Preparar revision metodologica interna",
            "action": "Generar paquete no-PHI y revisar si la primera senal real es defensible.",
            "route": "/api/platform-readiness/research-pack-materializer?scope=full&real_only=1",
        }
    ]


def _trace_contract() -> dict[str, Any]:
    return {
        "official_entry_surface": "/clinical-hub?real_world_enrollment=1#pm2OfficialClassifier",
        "official_enrollment_component": "components/real_world_enrollment_panel.html",
        "official_registration_api": "/api/register_patient",
        "readiness_surface": "/platform-readiness",
        "completion_queue_api": "/api/platform-readiness/prospective-real-world-completion-queue",
        "download": "/api/platform-readiness/real-world-pilot-packet/download",
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
    "REAL_WORLD_PILOT_PACKET_VERSION",
    "build_real_world_pilot_packet",
    "build_real_world_pilot_packet_markdown_bytes",
]
