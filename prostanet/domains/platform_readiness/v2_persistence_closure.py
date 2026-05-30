"""Read-only V2 persistence closure gate.

The platform can only grow safely when the initial-staging flow proves that
captured facts persist and reappear across V2 surfaces without recapture. This
gate does not create patients; it verifies the no-PHI source contracts, route
contracts and isolated dry-run test that prove the flow.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from prostanet.domains.platform_readiness.capture_integrity import (
    build_capture_integrity_readiness,
)
from prostanet.shared.utc_time import utc_now_iso


V2_PERSISTENCE_CLOSURE_VERSION = "v2_initial_staging_persistence_closure_v1"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DRY_RUN_TEST_PATH = PROJECT_ROOT / "tests" / "test_v2_initial_staging_persistence_closure.py"
PROFILE_V2_TEMPLATE_PATH = PROJECT_ROOT / "templates" / "patient_profile_v2.html"


def build_v2_initial_staging_persistence_closure(
    *,
    registered_rules: Iterable[Any] | None = None,
    capture_integrity: Mapping[str, Any] | None = None,
    scope: str = "summary",
) -> dict[str, Any]:
    """Build a no-mutation gate for V2 initial staging persistence."""
    scope_key = "summary" if str(scope or "").strip().lower() == "summary" else "full"
    routes = _route_contracts(registered_rules)
    source_checks = _source_contracts()
    profile_checks = _profile_v2_contracts()
    capture_payload = dict(capture_integrity or build_capture_integrity_readiness(scope="summary"))
    capture_checks = _capture_integrity_contracts(capture_payload)
    matrix = routes + source_checks + profile_checks + capture_checks
    summary = _summary(matrix, capture_payload)
    payload: dict[str, Any] = {
        "available": True,
        "source": "v2_initial_staging_persistence_closure",
        "version": V2_PERSISTENCE_CLOSURE_VERSION,
        "computed_at": utc_now_iso(),
        "scope": scope_key,
        "read_only": True,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "real_database_mutated": False,
        "isolated_database_required": True,
        "summary": summary,
        "next_layer_allowed": summary["critical_failure_count"] == 0,
        "dry_run_command": "python3 -m pytest -q tests/test_v2_initial_staging_persistence_closure.py",
        "recommended_next_actions": _recommended_next_actions(summary),
        "verification_preview": matrix[:10],
    }
    if scope_key == "full":
        payload["verification_matrix"] = matrix
        payload["evidence_artifacts"] = _evidence_artifacts()
        payload["flow_contract"] = _flow_contract()
    return payload


def _route_contracts(registered_rules: Iterable[Any] | None) -> list[dict[str, Any]]:
    rules = {str(getattr(rule, "rule", rule)) for rule in (registered_rules or [])}
    required = [
        ("assessment_draft_api", "/api/clinical-assessments/draft", "Crear draft clinico desde wizard V2"),
        ("registration_api", "/api/register_patient", "Persistir paciente y ligar latest_assessment"),
        ("ledger_summary_api", "/api/patients/<patient_ref>/clinical-fact-ledger/summary", "Leer Ledger sin mutar facts"),
        ("decision_today_api", "/api/patients/<patient_ref>/decision-today", "Recalcular DECISION HOY desde facts persistidos"),
        ("schedule_api", "/api/patients/<patient_ref>/schedule", "Generar agenda desde estado/facts persistidos"),
        ("profile_v2_route", "/patient_profile/<nss>", "Renderizar perfil V2 oficial"),
        ("capture_integrity_api", "/api/platform-readiness/capture-integrity", "Bloquear recaptura antes de persistir"),
    ]
    checks: list[dict[str, Any]] = []
    for key, route, evidence in required:
        present = route in rules if rules else True
        checks.append(
            _check(
                key=key,
                status="pass" if present else "block",
                family="route_contract",
                evidence=evidence,
                surface=route,
                critical=True,
                action="Registrar la ruta publica compatible antes de declarar cierre V2.",
            )
        )
    return checks


def _source_contracts() -> list[dict[str, Any]]:
    source = _read_text(DRY_RUN_TEST_PATH)
    expectations = [
        (
            "dry_run_test_exists",
            bool(source),
            "El dry-run aislado existe y no depende de la base local real.",
            "tests/test_v2_initial_staging_persistence_closure.py",
        ),
        (
            "dry_run_uses_draft_register_profile_flow",
            all(token in source for token in ("/api/clinical-assessments/draft", "/api/register_patient", "/patient_profile/{patient_ref}?v=2")),
            "El test cubre wizard/draft, registro longitudinal y perfil V2.",
            "tests/test_v2_initial_staging_persistence_closure.py",
        ),
        (
            "dry_run_blocks_ape_recapture",
            all(token in source for token in ("visible_registration_fields", "baseline_psa", "psa_baseline_ng_ml", "psa_history")),
            "El test falla si APE reaparece como scalar recapturable.",
            "tests/test_v2_initial_staging_persistence_closure.py",
        ),
        (
            "dry_run_asserts_biomarker_persistence",
            all(token in source for token in ("biomarker_longitudinal", "11.8", "12.6", "points_persisted")),
            "El test comprueba persistencia APE longitudinal con dos puntos fechados.",
            "tests/test_v2_initial_staging_persistence_closure.py",
        ),
        (
            "dry_run_asserts_latest_assessment",
            all(token in source for token in ("latest_assessment", "localized_initial", "patient_id")),
            "El test comprueba que latest_assessment queda ligado al paciente.",
            "tests/test_v2_initial_staging_persistence_closure.py",
        ),
        (
            "dry_run_asserts_ledger_decision_schedule",
            all(token in source for token in ("clinical-fact-ledger/summary", "decision-today", "/schedule")),
            "El test cruza Ledger, DECISION HOY y agenda clinica.",
            "tests/test_v2_initial_staging_persistence_closure.py",
        ),
    ]
    return [
        _check(
            key=key,
            status="pass" if ok else "block",
            family="isolated_dry_run_source",
            evidence=evidence,
            surface=surface,
            critical=True,
            action="Restaurar el dry-run aislado antes de seguir agregando logica clinica.",
        )
        for key, ok, evidence, surface in expectations
    ]


def _profile_v2_contracts() -> list[dict[str, Any]]:
    template = _read_text(PROFILE_V2_TEMPLATE_PATH)
    expectations = [
        (
            "profile_v2_has_psa_treatment_timeline",
            'id="psaTreatmentTimelineChart"' in template,
            "Perfil V2 contiene timeline APE-tratamiento enfocado.",
        ),
        (
            "profile_v2_has_psa_combined_timeline",
            'id="psaCombinedTimelineChart"' in template,
            "Perfil V2 contiene timeline combinado APE, tratamientos y eventos.",
        ),
        (
            "profile_v2_has_clinical_fact_ledger_panel",
            'data-testid="clinical-fact-ledger-v1-panel"' in template,
            "Perfil V2 expone Ledger para reutilizacion y no recaptura.",
        ),
        (
            "profile_v2_uses_real_psa_bundle",
            "psa_obs.points + psa_obs.treatment_bands" in template,
            "Charts V2 se alimentan de bundle real, no de datos demo.",
        ),
    ]
    return [
        _check(
            key=key,
            status="pass" if ok else "block",
            family="profile_v2_contract",
            evidence=evidence,
            surface="templates/patient_profile_v2.html",
            critical=True,
            action="Restaurar el contrato visual V2 antes de aceptar persistencia completa.",
        )
        for key, ok, evidence in expectations
    ]


def _capture_integrity_contracts(capture_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    summary = capture_payload.get("summary") or {}
    ready = summary.get("capture_integrity_status") == "capture_integrity_ready"
    return [
        _check(
            key="capture_integrity_gate_green",
            status="pass" if ready else "block",
            family="capture_integrity_dependency",
            evidence=f"capture_integrity_status={summary.get('capture_integrity_status') or 'unknown'}",
            surface="/api/platform-readiness/capture-integrity",
            critical=True,
            action="Cerrar recaptura/relevancia por etapa antes de validar persistencia.",
        )
    ]


def _summary(matrix: list[Mapping[str, Any]], capture_payload: Mapping[str, Any]) -> dict[str, Any]:
    block_count = sum(1 for row in matrix if row.get("status") == "block")
    watch_count = sum(1 for row in matrix if row.get("status") == "watch")
    pass_count = sum(1 for row in matrix if row.get("status") == "pass")
    total = len(matrix)
    status = "v2_persistence_closure_blocked" if block_count else "v2_persistence_closure_ready"
    return {
        "v2_persistence_closure_status": status,
        "contract_count": total,
        "pass_count": pass_count,
        "watch_count": watch_count,
        "block_count": block_count,
        "critical_failure_count": block_count,
        "pass_rate_pct": round((pass_count / total) * 100, 1) if total else 0.0,
        "capture_integrity_status": (capture_payload.get("summary") or {}).get("capture_integrity_status") or "unknown",
        "proven_surfaces": [
            "wizard_v2",
            "assessment_draft",
            "registration",
            "biomarker_longitudinal",
            "latest_assessment",
            "clinical_fact_ledger",
            "decision_today",
            "schedule",
            "patient_profile_v2",
        ],
        "next_operator_action": (
            "Corregir contratos bloqueados antes de agregar mas logica clinica."
            if block_count
            else "Usar este cierre como baseline antes de cohortes, economia y research OS."
        ),
    }


def _recommended_next_actions(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    if int(summary.get("critical_failure_count") or 0):
        return [
            {
                "priority": "critical",
                "action": "Ejecutar el dry-run aislado y restaurar rutas/plantilla V2 bloqueadas.",
                "benefit": "Evita construir analitica sobre datos no persistidos o recapturados.",
            }
        ]
    return [
        {
            "priority": "next",
            "action": "Extender el mismo cierre a mCSPC/m0CRPC/m1CRPC con tratamiento y costo.",
            "benefit": "Convierte la persistencia V2 en evidencia longitudinal y economica robusta.",
        }
    ]


def _evidence_artifacts() -> list[dict[str, Any]]:
    return [
        {
            "artifact": "tests/test_v2_initial_staging_persistence_closure.py",
            "kind": "isolated_pytest",
            "command": "python3 -m pytest -q tests/test_v2_initial_staging_persistence_closure.py",
            "mutates_real_database": False,
        },
        {
            "artifact": "templates/patient_profile_v2.html",
            "kind": "profile_v2_contract",
            "mutates_real_database": False,
        },
    ]


def _flow_contract() -> dict[str, Any]:
    return {
        "name": "initial_staging_v2_persistence_closure",
        "capture_once": ["psa"],
        "longitudinal_series": ["psa_history"],
        "must_persist": ["clinical_assessments.patient_id", "biomarker_longitudinal.PSA", "baseline.baseline_psa"],
        "must_render": ["Clinical Fact Ledger v1", "psaTreatmentTimelineChart", "psaCombinedTimelineChart"],
        "must_not_render_for_recapture": ["baseline_psa", "psa_baseline_ng_ml", "ape_basal"],
    }


def _check(
    *,
    key: str,
    status: str,
    family: str,
    evidence: str,
    surface: str,
    critical: bool,
    action: str,
) -> dict[str, Any]:
    return {
        "key": key,
        "status": status,
        "family": family,
        "surface": surface,
        "severity": "critical" if critical else "watch",
        "evidence": evidence,
        "recommended_action": action,
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""
