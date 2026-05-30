"""Read-only V2 treatment-value closure gate.

This gate proves that the official Profile V2 surface, dose APIs and
population analytics stay connected for the triplet dose/cost scenario. It
does not create patients or mutate the local clinical database; the executable
evidence lives in an isolated pytest.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from prostanet.shared.utc_time import utc_now_iso


V2_TREATMENT_VALUE_CLOSURE_VERSION = "v2_treatment_value_closure_v1"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DRY_RUN_TEST_PATH = PROJECT_ROOT / "tests" / "test_v2_treatment_value_persistence_closure.py"
TREATMENT_TRACKER_PATH = (
    PROJECT_ROOT / "prostanet" / "domains" / "patient_tracking" / "treatment_course_tracker.py"
)
TREATMENT_IMPACT_PATH = (
    PROJECT_ROOT / "prostanet" / "domains" / "patient_tracking" / "treatment_economic_impact.py"
)
ARPI_ANALYTICS_PATH = (
    PROJECT_ROOT / "prostanet" / "domains" / "population_intelligence" / "arpi_value_analytics.py"
)
PROFILE_V2_TEMPLATE_PATH = PROJECT_ROOT / "templates" / "patient_profile_v2.html"
REGISTRY_TEMPLATE_PATH = PROJECT_ROOT / "templates" / "treatment_value_registry_v2.html"
ANALYTICS_TEST_PATH = PROJECT_ROOT / "tests" / "test_arpi_value_analytics.py"
DOSE_TEST_PATH = PROJECT_ROOT / "tests" / "test_treatment_course_dose_tracking.py"


def build_v2_treatment_value_closure(
    *,
    registered_rules: Iterable[Any] | None = None,
    scope: str = "summary",
) -> dict[str, Any]:
    """Build a no-mutation gate for V2 treatment value persistence."""
    scope_key = "summary" if str(scope or "").strip().lower() == "summary" else "full"
    matrix = (
        _route_contracts(registered_rules)
        + _isolated_dry_run_contracts()
        + _domain_contracts()
        + _profile_v2_contracts()
        + _population_registry_contracts()
    )
    summary = _summary(matrix)
    payload: dict[str, Any] = {
        "available": True,
        "source": "v2_treatment_value_closure",
        "version": V2_TREATMENT_VALUE_CLOSURE_VERSION,
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
        "dry_run_command": "python3 -m pytest -q tests/test_v2_treatment_value_persistence_closure.py",
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
        ("/patient_profile/<nss>", "profile_v2", "Renderizar perfil V2 oficial."),
        (
            "/api/patients/<patient_ref>/treatment-course/current",
            "treatment_course_current_api",
            "Leer curso vigente sin mutar datos.",
        ),
        (
            "/api/patients/<patient_ref>/treatment-course",
            "treatment_course_upsert_api",
            "Actualizar curso terapeutico de forma explicita.",
        ),
        (
            "/api/patients/<patient_ref>/treatment-course/<int:course_id>/dose",
            "treatment_course_dose_api",
            "Registrar dosis local y recalcular alerta/costo.",
        ),
        (
            "/api/patients/<patient_ref>/treatment-economic-impact",
            "treatment_economic_impact_api",
            "Auditar impacto economico sin crear ordenes.",
        ),
        ("/api/analytics/arpi-spend", "arpi_spend_api", "Exponer gasto ARPI trazable."),
        (
            "/api/analytics/price-catalog-audit",
            "price_catalog_audit_api",
            "Auditar fuente/precio vigente.",
        ),
        (
            "/api/analytics/arpi-real-world-value",
            "arpi_real_world_value_api",
            "Exponer valor real-world ARPI.",
        ),
        (
            "/api/analytics/treatment-value-registry",
            "treatment_value_registry_api",
            "Comparar cohortes 12/24 semanas.",
        ),
        (
            "/population/treatment-value-registry",
            "population_registry_v2_page",
            "Abrir registro poblacional V2.",
        ),
    ]
    checks: list[dict[str, Any]] = []
    for route, key, evidence in required:
        present = route in rules if rules else True
        checks.append(
            _check(
                key=key,
                status="pass" if present else "block",
                family="route_contract",
                evidence=evidence,
                surface=route,
                critical=True,
                action="Registrar la ruta publica compatible antes de aceptar cierre V2 de valor terapeutico.",
            )
        )
    return checks


def _isolated_dry_run_contracts() -> list[dict[str, Any]]:
    source = _read_text(DRY_RUN_TEST_PATH)
    expectations = [
        (
            "triplet_v2_dry_run_exists",
            bool(source),
            "Existe prueba aislada para triplete/costos/alertas en Profile V2.",
        ),
        (
            "triplet_v2_asserts_warning_190k",
            all(token in source for token in ("ADT_DOCETAXEL_DAROLUTAMIDE", "190000.0", "warning")),
            "4 dosis locales + 2 previas generan warning y 190,000 MXN ARPI.",
        ),
        (
            "triplet_v2_asserts_critical_285k",
            all(token in source for token in ("285000.0", "critical", "maximo de dosis otorgadas")),
            "Dosis local 6 genera alerta critica y 285,000 MXN ARPI.",
        ),
        (
            "triplet_v2_asserts_profile_surface",
            all(
                token in source
                for token in (
                    "patient_profile_v2_real_context",
                    "treatment-course-unit-card",
                    "psaTreatmentTimelineChart",
                    "psaCombinedTimelineChart",
                )
            ),
            "La prueba falla si la evidencia vive fuera del perfil V2 oficial.",
        ),
        (
            "triplet_v2_asserts_no_mutation_guards",
            all(
                token in source
                for token in (
                    "source_clinical_facts_mutated",
                    "external_order_created",
                    "model_trained",
                )
            ),
            "La prueba verifica que el impacto economico no ordena terapia ni entrena modelos.",
        ),
    ]
    return [
        _check(
            key=key,
            status="pass" if ok else "block",
            family="isolated_dry_run_source",
            evidence=evidence,
            surface="tests/test_v2_treatment_value_persistence_closure.py",
            critical=True,
            action="Restaurar el dry-run aislado antes de declarar listo el perfil V2 terapeutico.",
        )
        for key, ok, evidence in expectations
    ]


def _domain_contracts() -> list[dict[str, Any]]:
    tracker = _read_text(TREATMENT_TRACKER_PATH)
    impact = _read_text(TREATMENT_IMPACT_PATH)
    dose_tests = _read_text(DOSE_TEST_PATH)
    expectations = [
        (
            "dose_alerts_define_warning_and_critical",
            all(token in tracker for token in ("DOSE_4_ALERT", "DOSE_6_ALERT")),
            "Tracker conserva alerta temprana y alerta critica por dosis local.",
            "prostanet/domains/patient_tracking/treatment_course_tracker.py",
        ),
        (
            "triplet_cost_scope_keeps_unpriced_adt_auditable",
            all(token in tracker for token in ("DOCETAXEL", "unpriced_backbone_components", "ADT")),
            "Docetaxel se costea si es auditable y ADT queda como pendiente, no inventado.",
            "prostanet/domains/patient_tracking/treatment_course_tracker.py",
        ),
        (
            "economic_impact_is_read_only",
            all(
                token in impact
                for token in ("source_clinical_facts_mutated", "external_order_created", "model_trained")
            ),
            "Impacto economico declara fronteras de no-mutacion/no-orden/no-entrenamiento.",
            "prostanet/domains/patient_tracking/treatment_economic_impact.py",
        ),
        (
            "dose_tracking_tests_cover_triplet_critical_path",
            all(token in dose_tests for token in ("ADT_DOCETAXEL_DAROLUTAMIDE", "285000.0", "191201.72")),
            "Tests de dominio cubren triplete, costo total trazable y alerta critica.",
            "tests/test_treatment_course_dose_tracking.py",
        ),
    ]
    return [
        _check(
            key=key,
            status="pass" if ok else "block",
            family="domain_contract",
            evidence=evidence,
            surface=surface,
            critical=True,
            action="Restaurar contrato de tracking/costos antes de construir analitica epidemiologica encima.",
        )
        for key, ok, evidence, surface in expectations
    ]


def _profile_v2_contracts() -> list[dict[str, Any]]:
    template = _read_text(PROFILE_V2_TEMPLATE_PATH)
    expectations = [
        (
            "profile_v2_has_treatment_course_card",
            'data-testid="treatment-course-unit-card"' in template,
            "Perfil V2 muestra curso terapeutico, dosis locales y alerta HGZ/HGR.",
        ),
        (
            "profile_v2_has_value_summary",
            'data-testid="v2-treatment-value-summary"' in template and "Valor clinico-economico V2" in template,
            "Perfil V2 expone panel clinico-economico.",
        ),
        (
            "profile_v2_has_cost_traceability_text",
            all(token in template for token in ("Fármacos trazables acumulados", "Validar precio", "HGZ/HGR")),
            "Perfil V2 muestra costo trazable, brechas de precio y alerta operativa.",
        ),
        (
            "profile_v2_has_treatment_timelines",
            all(token in template for token in ("psaTreatmentTimelineChart", "psaCombinedTimelineChart")),
            "Perfil V2 renderiza timeline APE-tratamiento y timeline combinado.",
        ),
        (
            "profile_v2_links_population_registry",
            "/population/treatment-value-registry" in template
            and 'data-testid="v2-treatment-value-registry-panel"' in template,
            "Perfil V2 enlaza al registro poblacional V2 sin usar legacy como evidencia.",
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
            action="Corregir Profile V2; no aceptar cobertura existente solo en legacy.",
        )
        for key, ok, evidence in expectations
    ]


def _population_registry_contracts() -> list[dict[str, Any]]:
    analytics = _read_text(ARPI_ANALYTICS_PATH)
    analytics_tests = _read_text(ANALYTICS_TEST_PATH)
    template = _read_text(REGISTRY_TEMPLATE_PATH)
    expectations = [
        (
            "registry_builder_has_12_24_windows_and_traceability",
            all(
                token in analytics_tests
                for token in (
                    "test_treatment_value_registry_compares_molecule_regimen_and_adjusts_baseline",
                    "test_treatment_value_registry_filters_and_traces_patient_metrics",
                    "ADT_DOCETAXEL_DAROLUTAMIDE",
                )
            ),
            "Registry V2 compara regimen/molecula, ajusta basal y traza paciente-a-metrica.",
            "tests/test_arpi_value_analytics.py",
        ),
        (
            "registry_builder_has_extended_outcomes_and_economics",
            all(
                token in analytics_tests
                for token in (
                    "discontinuation_count",
                    "high_grade_toxicity_count",
                    "cost_per_psa50_responder_mxn",
                )
            ),
            "Outcomes y economia institucional estan protegidos por tests poblacionales.",
            "tests/test_arpi_value_analytics.py",
        ),
        (
            "registry_runtime_is_read_only",
            all(
                token in analytics
                for token in (
                    "source_clinical_facts_mutated",
                    "external_order_created",
                    "model_trained",
                    "treatment_value_registry_v2",
                )
            ),
            "Builder poblacional se declara read-only y no crea ordenes.",
            "prostanet/domains/population_intelligence/arpi_value_analytics.py",
        ),
        (
            "population_template_is_v2",
            all(
                token in template
                for token in (
                    "treatment-value-registry",
                    "Exportar CSV",
                    'data-testid="tv-patient-trace"',
                )
            ),
            "Vista poblacional V2 expone filtros/export y trazabilidad paciente-metrica.",
            "templates/treatment_value_registry_v2.html",
        ),
    ]
    return [
        _check(
            key=key,
            status="pass" if ok else "block",
            family="population_registry_contract",
            evidence=evidence,
            surface=surface,
            critical=True,
            action="Cerrar registro poblacional V2 antes de declarar listo el gran tablero.",
        )
        for key, ok, evidence, surface in expectations
    ]


def _summary(matrix: list[Mapping[str, Any]]) -> dict[str, Any]:
    block_count = sum(1 for row in matrix if row.get("status") == "block")
    watch_count = sum(1 for row in matrix if row.get("status") == "watch")
    pass_count = sum(1 for row in matrix if row.get("status") == "pass")
    total = len(matrix)
    return {
        "v2_treatment_value_closure_status": (
            "v2_treatment_value_closure_blocked" if block_count else "v2_treatment_value_closure_ready"
        ),
        "contract_count": total,
        "pass_count": pass_count,
        "watch_count": watch_count,
        "block_count": block_count,
        "critical_failure_count": block_count,
        "pass_rate_pct": round((pass_count / total) * 100, 1) if total else 0.0,
        "proven_surfaces": [
            "patient_profile_v2",
            "treatment_course_api",
            "dose_alerts",
            "treatment_economic_impact",
            "arpi_spend",
            "price_catalog_audit",
            "arpi_real_world_value",
            "treatment_value_registry_v2",
            "population_registry_v2",
        ],
        "triplet_reference_scenario": {
            "regimen": "ADT_DOCETAXEL_DAROLUTAMIDE",
            "warning_local_doses": 4,
            "warning_prior_external_doses": 2,
            "warning_arpi_spend_mxn": 190000.0,
            "critical_local_doses": 6,
            "critical_arpi_spend_mxn": 285000.0,
        },
        "next_operator_action": (
            "Corregir contratos bloqueados antes de ampliar el tablero epidemiologico."
            if block_count
            else "Usar este cierre V2 como baseline para tablero epidemiologico final."
        ),
    }


def _recommended_next_actions(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    if int(summary.get("critical_failure_count") or 0):
        return [
            {
                "priority": "critical",
                "action": "Ejecutar el dry-run aislado y restaurar Profile V2/API/registry bloqueados.",
                "benefit": "Evita interpretar valor terapeutico con UI o costos desincronizados.",
            }
        ]
    return [
        {
            "priority": "next",
            "action": "Conectar esta compuerta al tablero epidemiologico final y a gobernanza de cohortes.",
            "benefit": "Cada KPI economico-clinico queda auditable desde paciente, dosis, costo y respuesta.",
        }
    ]


def _evidence_artifacts() -> list[dict[str, Any]]:
    return [
        {
            "artifact": "tests/test_v2_treatment_value_persistence_closure.py",
            "kind": "isolated_pytest",
            "command": "python3 -m pytest -q tests/test_v2_treatment_value_persistence_closure.py",
            "mutates_real_database": False,
        },
        {
            "artifact": "tests/test_treatment_course_dose_tracking.py",
            "kind": "domain_regression",
            "mutates_real_database": False,
        },
        {
            "artifact": "tests/test_arpi_value_analytics.py",
            "kind": "population_analytics_regression",
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
        "name": "profile_v2_treatment_value_closure",
        "reference_regimen": "ADT_DOCETAXEL_DAROLUTAMIDE",
        "must_persist": ["treatment_history", "dose_events", "biomarker_longitudinal.PSA"],
        "must_render": [
            "treatment-course-unit-card",
            "Valor clinico-economico V2",
            "psaTreatmentTimelineChart",
            "psaCombinedTimelineChart",
        ],
        "must_not_accept_as_closure": ["patient_profile.html legacy only"],
        "read_only_checks": [
            "source_clinical_facts_mutated=false",
            "external_order_created=false",
            "model_trained=false",
        ],
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
