"""No-PHI verifier for the first-real V2 launch handoff.

The launch mode tells the operator what to do. This verifier proves that the
handoff is wired: V2 entry, wizard, consent/actor, PSA history, Profile V2 and
real-only queue. It is intentionally read-only and relies on contracts/source
evidence rather than creating a patient.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from prostanet.domains.platform_readiness.prospective_real_world_completion_queue import (
    build_prospective_real_world_completion_queue,
)
from prostanet.domains.platform_readiness.real_world_first_patient_launch_mode import (
    build_real_world_first_patient_launch_mode,
)
from prostanet.domains.platform_readiness.real_world_sample_maturity import (
    build_real_world_sample_maturity_gate,
)
from prostanet.shared.utc_time import utc_now_iso


REAL_WORLD_LAUNCH_FLOW_VERIFIER_VERSION = "real_world_launch_flow_verifier_v1"

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


def build_real_world_launch_flow_verifier(
    *,
    scope: str = "summary",
    limit: int = 100,
    registered_rules: Iterable[Any] | None = None,
    real_world_sample_maturity: Mapping[str, Any] | None = None,
    prospective_real_world_completion_queue: Mapping[str, Any] | None = None,
    real_world_first_patient_launch_mode: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a read-only no-PHI verifier for the first-real V2 launch path."""
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
    launch = dict(
        real_world_first_patient_launch_mode
        or build_real_world_first_patient_launch_mode(
            scope="summary",
            limit=safe_limit,
            real_world_sample_maturity=sample,
            prospective_real_world_completion_queue=queue,
        )
    )
    route_contracts = _route_contracts(registered_rules)
    ui_contracts = _ui_contracts()
    persistence_contracts = _persistence_contracts()
    matrix = route_contracts + ui_contracts + persistence_contracts + _launch_state_contracts(
        sample,
        queue,
        launch,
    )
    summary = _summary(matrix, sample, queue, launch)
    preview = matrix[:8]
    payload_for_scan = {
        "summary": summary,
        "verification_preview": preview,
        "recommended_next_actions": _recommended_next_actions(summary),
        "trace_contract": _trace_contract(),
    }
    payload: dict[str, Any] = {
        "available": True,
        "source": "real_world_launch_flow_verifier",
        "version": REAL_WORLD_LAUNCH_FLOW_VERIFIER_VERSION,
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
        "verification_preview": preview,
        "recommended_next_actions": _recommended_next_actions(summary),
        "trace_contract": _trace_contract(),
        "no_phi_scan": _scan_for_phi(payload_for_scan),
    }
    if scope_key == "full":
        payload["verification_matrix"] = matrix
        payload["operator_handoff"] = _operator_handoff()
        payload["post_capture_evidence_targets"] = _post_capture_evidence_targets()
        payload["governance_policy"] = _governance_policy()
        payload["no_phi_scan"] = _scan_for_phi(
            {
                **payload_for_scan,
                "verification_matrix": matrix,
                "operator_handoff": _operator_handoff(),
                "post_capture_evidence_targets": _post_capture_evidence_targets(),
                "governance_policy": _governance_policy(),
            }
        )
    return payload


def build_real_world_launch_flow_verifier_markdown_bytes(
    verifier: Mapping[str, Any] | None = None,
) -> bytes:
    """Return a no-PHI markdown summary of the V2 launch handoff verifier."""
    payload = dict(verifier or build_real_world_launch_flow_verifier(scope="full", limit=100))
    summary = payload.get("summary") or {}
    lines = [
        "# Verificador del handoff V2 del primer real",
        "",
        f"- Version: {payload.get('version')}",
        f"- Estado: {summary.get('flow_verifier_status')}",
        f"- Sincronizacion UI/backend: {summary.get('ui_backend_sync_status')}",
        f"- Pacientes reales actuales: {summary.get('real_patient_count', 0)}",
        f"- Siguiente paso: {summary.get('next_operator_action')}",
        "",
        "## Contratos",
    ]
    for item in payload.get("verification_matrix") or payload.get("verification_preview") or []:
        lines.append(
            f"- [{item.get('status')}] {item.get('key')} "
            f"({item.get('family')}): {item.get('evidence')}"
        )
    lines.extend(["", "## Evidencia post-captura"])
    for item in payload.get("post_capture_evidence_targets") or []:
        lines.append(f"- {item.get('target')}: {item.get('expected')}")
    lines.append("")
    return "\n".join(lines).encode("utf-8")


def _summary(
    matrix: list[Mapping[str, Any]],
    sample: Mapping[str, Any],
    queue: Mapping[str, Any],
    launch: Mapping[str, Any],
) -> dict[str, Any]:
    sample_summary = sample.get("summary") or {}
    queue_summary = queue.get("summary") or {}
    launch_summary = launch.get("summary") or {}
    block_count = sum(1 for item in matrix if item.get("status") == "block")
    watch_count = sum(1 for item in matrix if item.get("status") == "watch")
    pass_count = sum(1 for item in matrix if item.get("status") == "pass")
    real_count = int(sample_summary.get("real_patient_count") or queue_summary.get("real_patient_count") or 0)
    ready_count = int(queue_summary.get("registry_ready_real_count") or 0)
    return {
        "flow_verifier_status": _status(block_count, real_count, ready_count),
        "ui_backend_sync_status": "pass" if block_count == 0 else "block",
        "real_patient_count": real_count,
        "synthetic_patient_count": int(sample_summary.get("synthetic_patient_count") or 0),
        "registry_ready_real_count": ready_count,
        "launch_mode_status": launch_summary.get("launch_mode_status") or "unknown",
        "dry_run_contract_status": launch_summary.get("dry_run_contract_status") or "unknown",
        "contract_count": len(matrix),
        "pass_count": pass_count,
        "watch_count": watch_count,
        "block_count": block_count,
        "external_validation_claim_allowed": False,
        "real_world_claim_allowed": bool(queue_summary.get("real_world_claim_allowed")) and ready_count > 0,
        "next_operator_action": _next_operator_action(block_count, real_count, ready_count),
        "verification_scope": "V2 entry, wizard, consent actor, PSA history, Profile V2, real-only queue and governed claims.",
    }


def _status(block_count: int, real_count: int, ready_count: int) -> str:
    if block_count:
        return "launch_flow_blocked"
    if real_count <= 0:
        return "launch_flow_verified_waiting_first_real"
    if ready_count <= 0:
        return "first_real_flow_in_progress"
    return "first_real_flow_ready_for_method_review"


def _next_operator_action(block_count: int, real_count: int, ready_count: int) -> str:
    if block_count:
        return "Corregir contratos V2 bloqueados antes de capturar muestra real."
    if real_count <= 0:
        return "Ejecutar primer real desde Clinical Hub V2 con consentimiento, actor e historia APE."
    if ready_count <= 0:
        return "Cerrar completitud real-only del primer real y verificar Perfil V2."
    return "Preparar freeze no-PHI y revision metodologica interna."


def _route_contracts(registered_rules: Iterable[Any] | None) -> list[dict[str, Any]]:
    rules = {str(getattr(rule, "rule", rule)) for rule in (registered_rules or [])}
    required = [
        ("clinical_hub_v2_entry", "/clinical-hub", "Entrada V2 oficial"),
        ("wizard_v2", "/wizard/<module_id>", "Wizard clinico V2"),
        ("assessment_draft_api", "/api/clinical-assessments/draft", "Draft clinico enlazable"),
        ("consent_draft_api", "/api/research/consent/draft", "Consentimiento draft"),
        ("consent_sign_api", "/api/research/consent/draft/<int:draft_id>/sign", "Firma electronica"),
        ("consent_finalize_api", "/api/research/consent/draft/<int:draft_id>/finalize", "Finalizacion de consentimiento"),
        ("profile_v2_internal", "/patient_profile/<nss>", "Perfil V2 interno"),
        ("sample_maturity_api", "/api/platform-readiness/real-world-sample-maturity", "Compuerta muestra real"),
        ("real_only_queue_api", "/api/platform-readiness/prospective-real-world-completion-queue", "Cola real-only"),
        ("launch_mode_api", "/api/platform-readiness/real-world-first-patient-launch-mode", "Modo lanzamiento"),
        ("flow_verifier_api", "/api/platform-readiness/real-world-launch-flow-verifier", "Verificador handoff V2"),
    ]
    items = []
    for key, rule, label in required:
        present = not registered_rules or rule in rules
        evidence = "registrada" if present else "faltante"
        items.append(
            {
                "key": key,
                "family": "route_contract",
                "title": label,
                "status": "pass" if present else "block",
                "surface": key,
                "evidence": evidence,
                "action": "Mantener ruta registrada en app normal." if present else "Registrar ruta antes de captura real.",
            }
        )
    return items


def _ui_contracts() -> list[dict[str, Any]]:
    root = Path(__file__).resolve().parents[3]
    checks = [
        {
            "key": "clinical_hub_launch_strip_v2",
            "family": "ui_contract",
            "path": root / "templates" / "demos" / "stage_clinical_center_v2_redesign.html",
            "tokens": [
                'data-testid="first-real-v2-launch-strip"',
                'data-testid="first-real-v2-operator-checklist"',
                "data-first-real-session-step",
                "first_real_launch_checklist.js",
                "real_world_launch_requested",
                "module_wizard_href",
                "real_world_enrollment=1",
                "/platform-readiness#real-world-first-patient-launch-mode",
                "/api/platform-readiness/real-world-first-patient-launch-mode/download",
            ],
            "title": "Clinical Hub V2 muestra launch strip query-gated",
        },
        {
            "key": "quick_classifier_real_world_handoff_v2",
            "family": "ui_contract",
            "path": root / "static" / "js" / "clinical_hub_quick_classifier.js",
            "tokens": [
                "buildWizardHref",
                "isRealWorldLaunchMode",
                "real_world_enrollment",
                'params.set("prefill_source", "clinical_hub")',
                'params.set("real_world_enrollment", "1")',
                "ProstaNetFirstRealLaunchChecklist",
                "module_classified",
                "data-legacy-wizard-link",
            ],
            "title": "Clasificador V2 preserva contexto real-world hacia wizard",
        },
        {
            "key": "wizard_real_world_panel_v2",
            "family": "ui_contract",
            "path": root / "templates" / "clinical_wizard.html",
            "tokens": [
                "real_world_launch_requested",
                'data-testid="first-real-wizard-handoff-guard"',
                'data-testid="first-real-wizard-registration-guard"',
                'include "components/real_world_enrollment_panel.html"',
                "real_world_enrollment_panel.js",
                "first_real_launch_checklist.js",
                "recordFirstRealLaunchStep",
                "requireFirstRealApeSeriesBeforeConsent",
                "first_real_wizard_v2",
                "registration_prepared",
                "registration_context_ui.js",
            ],
            "title": "Wizard V2 conserva contexto real-world y panel de registro",
        },
        {
            "key": "first_real_operator_checklist_js_v2",
            "family": "ui_contract",
            "path": root / "static" / "js" / "first_real_launch_checklist.js",
            "tokens": [
                "sessionStorage",
                "MIN_VALID_PSA_HISTORY_POINTS",
                "recordStep",
                "recordStepStatus",
                "validPsaHistoryRows",
                "hasPsaHistorySeries",
                "launch_strip_opened",
                "classifier_opened",
                "module_classified",
                "wizard_context_preserved",
                "registration_prepared",
                "real_panel_activated",
                "actor_present",
                "ape_payload_ready",
            ],
            "title": "Checklist operatorio V2 conserva estado local no-PHI",
        },
        {
            "key": "enrollment_panel_requires_actor",
            "family": "ui_contract",
            "path": root / "templates" / "components" / "real_world_enrollment_panel.html",
            "tokens": [
                'name="is_real_patient" value="1"',
                'name="consent_signed" value="0"',
                "data-real-world-consent-flag",
                'name="actor_user_id"',
            ],
            "title": "Panel de registro exige muestra real, consentimiento y actor",
        },
        {
            "key": "enrollment_panel_js_promotes_consent",
            "family": "ui_contract",
            "path": root / "static" / "js" / "real_world_enrollment_panel.js",
            "tokens": [
                'consentFlag.value = enabled ? "1" : "0"',
                "data-real-world-toggle",
                "actorInput.required = enabled",
            ],
            "title": "JS del panel activa consentimiento y actor al marcar real",
        },
        {
            "key": "profile_v2_truth_surface",
            "family": "ui_contract",
            "path": root / "templates" / "patient_profile_v2.html",
            "tokens": [
                "psaTreatmentTimelineChart",
                "psaCombinedTimelineChart",
                "Consentimiento de uso secundario de datos",
                "Firma electrónica del paciente",
            ],
            "title": "Perfil V2 renderiza consentimiento y APE-tratamiento",
        },
    ]
    return [_file_contract(check) for check in checks]


def _persistence_contracts() -> list[dict[str, Any]]:
    root = Path(__file__).resolve().parents[3]
    test_file = root / "tests" / "test_platform_readiness_audit.py"
    checks = [
        {
            "key": "dry_run_v2_contract",
            "family": "persistence_contract",
            "path": test_file,
            "tokens": [
                "test_first_real_patient_dry_run_v2_persists_consent_ape_profile_and_gates",
                "biomarker_longitudinal",
                "patient_consents",
                "consent_signature_evidence",
                "psaTreatmentTimelineChart",
                "psaCombinedTimelineChart",
            ],
            "title": "Dry-run prueba persistencia real V2",
        },
        {
            "key": "institutional_launch_rehearsal_contract",
            "family": "persistence_contract",
            "path": test_file,
            "tokens": [
                "test_first_real_institutional_launch_rehearsal_v2_from_strip_to_profile",
                "first-real-v2-launch-strip",
                "real_world_enrollment_panel.js",
                "valid_psa_point_count",
                "launch_flow_verifier_after",
            ],
            "title": "Ensayo institucional prueba handoff completo V2",
        },
        {
            "key": "launch_strip_contract",
            "family": "persistence_contract",
            "path": test_file,
            "tokens": [
                "test_clinical_hub_v2_first_real_launch_strip_is_query_gated_and_no_phi",
                "first-real-v2-launch-strip",
                "first-real-v2-operator-checklist",
                "ready_for_institutional_first_real_capture",
            ],
            "title": "Test protege handoff Clinical Hub V2",
        },
        {
            "key": "first_real_ape_series_guard_contract",
            "family": "persistence_contract",
            "path": test_file,
            "tokens": [
                "test_first_real_consent_requires_two_dated_ape_points",
                "first_real_wizard_v2",
                "2 mediciones APE",
                "real_world_enrollment_mode",
            ],
            "title": "Test bloquea consentimiento del primer real con APE aislado",
        },
        {
            "key": "launch_mode_no_phi_contract",
            "family": "persistence_contract",
            "path": test_file,
            "tokens": [
                "test_real_world_first_patient_launch_mode_guides_v2_capture_without_phi",
                "no_phi_scan",
                "capture_ape_history",
                "verify_profile_v2",
            ],
            "title": "Test protege Launch Mode no-PHI",
        },
    ]
    return [_file_contract(check) for check in checks]


def _file_contract(check: Mapping[str, Any]) -> dict[str, Any]:
    path = Path(check["path"])
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {
            "key": check["key"],
            "family": check["family"],
            "title": check["title"],
            "status": "block",
            "surface": path.name,
            "evidence": "archivo no legible",
            "action": "Restaurar archivo requerido.",
        }
    missing = [token for token in check["tokens"] if token not in text]
    return {
        "key": check["key"],
        "family": check["family"],
        "title": check["title"],
        "status": "pass" if not missing else "block",
        "surface": path.name,
        "evidence": f"{len(check['tokens']) - len(missing)}/{len(check['tokens'])} anclas presentes",
        "missing_anchors": missing[:10],
        "action": "Mantener contrato verde." if not missing else "Restaurar anclas faltantes.",
    }


def _launch_state_contracts(
    sample: Mapping[str, Any],
    queue: Mapping[str, Any],
    launch: Mapping[str, Any],
) -> list[dict[str, Any]]:
    sample_summary = sample.get("summary") or {}
    queue_summary = queue.get("summary") or {}
    launch_summary = launch.get("summary") or {}
    real_count = int(sample_summary.get("real_patient_count") or 0)
    ready_count = int(queue_summary.get("registry_ready_real_count") or 0)
    dry_run_pass = launch_summary.get("dry_run_contract_status") == "pass"
    no_claim = not launch_summary.get("external_validation_claim_allowed")
    return [
        {
            "key": "dry_run_status_pass",
            "family": "state_contract",
            "title": "Dry-run V2 vigente",
            "status": "pass" if dry_run_pass else "block",
            "surface": "launch_mode",
            "evidence": str(launch_summary.get("dry_run_contract_status") or "unknown"),
            "action": "Ejecutar primer real solo si dry-run permanece en pass.",
        },
        {
            "key": "sample_boundary_clear",
            "family": "state_contract",
            "title": "Frontera QA vs real",
            "status": "watch" if real_count <= 0 else "pass",
            "surface": "sample_maturity",
            "evidence": f"{real_count} reales; {sample_summary.get('synthetic_patient_count', 0)} QA/sinteticos",
            "action": "Capturar primer real consentido." if real_count <= 0 else "Mantener separacion real-only.",
        },
        {
            "key": "real_only_queue_ready_after_capture",
            "family": "state_contract",
            "title": "Cola real-only post-captura",
            "status": "watch" if real_count <= 0 else ("pass" if ready_count else "block"),
            "surface": "completion_queue",
            "evidence": f"{ready_count} reales registry-ready",
            "action": "Usar cola tras capturar el primer real.",
        },
        {
            "key": "claims_governed",
            "family": "state_contract",
            "title": "Claims gobernados",
            "status": "pass" if no_claim else "block",
            "surface": "governance",
            "evidence": "claims externos bloqueados" if no_claim else "claim externo abierto prematuramente",
            "action": "Mantener claims externos bloqueados hasta revision metodologica.",
        },
    ]


def _operator_handoff() -> list[dict[str, str]]:
    return [
        {
            "step": "1",
            "surface": "clinical_hub_v2_launch_strip",
            "operator_action": "Abrir el launch strip y clasificar por V2.",
        },
        {
            "step": "2",
            "surface": "wizard_v2",
            "operator_action": "Guardar draft clinico con facts minimos y APE sin duplicacion manual.",
        },
        {
            "step": "3",
            "surface": "real_world_enrollment_panel_v2",
            "operator_action": "Firmar consentimiento, documentar actor y registrar historia APE.",
        },
        {
            "step": "4",
            "surface": "patient_profile_v2",
            "operator_action": "Confirmar consentimiento, torre APE, linea terapeutica y Decision Hoy.",
        },
        {
            "step": "5",
            "surface": "real_only_completion_queue",
            "operator_action": "Cerrar brecha dominante antes de usar evidencia.",
        },
    ]


def _post_capture_evidence_targets() -> list[dict[str, str]]:
    return [
        {"target": "sample_maturity", "expected": "reales incrementa y QA queda separado"},
        {"target": "consent_actor", "expected": "consentimiento firmado y actor presentes"},
        {"target": "psa_history", "expected": "dos o mas mediciones APE con fecha/contexto"},
        {"target": "profile_v2", "expected": "charts APE-tratamiento y firma visibles"},
        {"target": "real_only_queue", "expected": "estado history_ready o brecha dominante explicita"},
        {"target": "claims_governance", "expected": "sin claim externo hasta revision metodologica"},
    ]


def _recommended_next_actions(summary: Mapping[str, Any]) -> list[dict[str, str]]:
    status = str(summary.get("flow_verifier_status") or "")
    if status == "launch_flow_blocked":
        return [
            {
                "priority": "critical",
                "title": "Corregir contratos V2 bloqueados",
                "action": "No capturar primer real hasta que rutas, UI y dry-run vuelvan a pass.",
                "route": "/platform-readiness#real-world-launch-flow-verifier",
            }
        ]
    if status == "launch_flow_verified_waiting_first_real":
        return [
            {
                "priority": "critical",
                "title": "Ejecutar primer real desde V2",
                "action": "Usar el launch strip: clasificador, wizard, consentimiento, actor e historia APE.",
                "route": "/clinical-hub?real_world_enrollment=1#pm2OfficialClassifier",
            }
        ]
    return [
        {
            "priority": "high",
            "title": "Cerrar completitud real-only",
            "action": "Revisar cola y perfil V2 antes de freeze no-PHI.",
            "route": "/platform-readiness#prospective-real-world-completion-queue",
        }
    ]


def _trace_contract() -> dict[str, Any]:
    return {
        "entry_surface": "/clinical-hub?real_world_enrollment=1#pm2OfficialClassifier",
        "verifier_api": "/api/platform-readiness/real-world-launch-flow-verifier",
        "launch_mode_api": "/api/platform-readiness/real-world-first-patient-launch-mode",
        "readiness_surface": "/platform-readiness#real-world-launch-flow-verifier",
        "writes_only": "none",
        "clinical_values_captured_here": False,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
    }


def _governance_policy() -> list[dict[str, str]]:
    return [
        {"policy": "V2 only", "rule": "El handoff oficial es Clinical Hub V2 -> Wizard V2 -> Perfil V2."},
        {"policy": "No capture from readiness", "rule": "El verificador no escribe pacientes ni hechos clinicos."},
        {"policy": "No isolated PSA", "rule": "El primer real debe llevar historia APE con fecha/contexto."},
        {"policy": "No premature claims", "rule": "Operabilidad y evidencia clinica se mantienen separadas."},
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
    "REAL_WORLD_LAUNCH_FLOW_VERIFIER_VERSION",
    "build_real_world_launch_flow_verifier",
    "build_real_world_launch_flow_verifier_markdown_bytes",
]
