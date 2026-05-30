"""Read-only gate for stage-aware capture integrity.

This module codifies the clinical capture rules that must stay true before
more prostate-cancer logic is added: APE/PSA is captured once, PSAD is derived,
stage wizards do not seed example facts, systemic fields open only in the
right disease state, and longitudinal registration reuses wizard facts instead
of recapturing them.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

from prostanet.domains.patient_tracking.service import PatientTrackingService
from prostanet.shared.converters import safe_float
from prostanet.shared.pivotal_gate_disclosure import filter_schema_for_wizard
from prostanet.shared.utc_time import utc_now_iso


CAPTURE_INTEGRITY_VERSION = "capture_integrity_readiness_v1"

PSA_RECAPTURE_ALIASES = {"baseline_psa", "psa_baseline_ng_ml", "ape", "ape_basal"}
LOCALIZED_SYSTEMIC_NOISE_FIELDS = {
    "rapid_anc_drop_for_docetaxel",
    "rapid_platelet_drop_for_niraparib",
    "bone_marrow_blasts_percent",
    "cumulative_docetaxel_dose_mg_m2",
}
SYSTEMIC_PIVOTAL_NOISE_FIELDS = {
    *LOCALIZED_SYSTEMIC_NOISE_FIELDS,
    "severe_cytopenia_for_parp_inhibitor",
    "cytopenias_corrected_for_radioligand",
    "cytopenias_corrected_for_parp_inhibitor",
    "thrombocytopenia_grade3_for_niraparib",
    "hypertension_grade3_for_niraparib",
    "hypertension_controlled_for_niraparib",
    "mds_or_aml_documented_during_parpi",
    "mds_aml_remission_for_parpi",
    "cytopenia_duration_weeks",
}
LOCALIZED_SYSTEMIC_CONTRAINDICATION_FIELDS = {
    "prior_arpi_exposure_mhspc",
    "darolutamide_hypersensitivity",
    "uncontrolled_hypertension",
    "severe_heart_failure_nyha_iii_iv",
    "uncontrolled_diabetes",
    "no_bone_protective_agent",
    "radium223_candidate",
}
LOCALIZED_SYSTEMIC_BASELINE_FIELDS = {
    "testosterone_baseline",
    "testosterone_history",
    "hemoglobin",
    "alp",
    "ldh",
    "albumin",
    "dxa_baseline_done",
}
LONGITUDINAL_SYSTEMIC_NOISE_FIELDS = {
    "testosterone_value",
    "testosterone_history",
    "ctcae_grade_max",
    "hemoglobin",
    "alp",
    "ldh",
    "albumin",
}
LOCALIZED_UNSELECTED_ROUTE_FIELDS = {
    "as_protocol",
    "confirmatory_biopsy_planned",
    "confirmatory_biopsy_done",
    "confirmatory_biopsy_date",
    "as_exit_reason",
    "as_exit_treatment",
    "rt_intent",
    "modality",
    "target_volume",
    "total_dose_gy",
    "fractions",
    "salvage_psa_at_start",
}
SYSTEMIC_PIVOTAL_DISCLOSURE_TRIGGER = "show_systemic_pivotal_contraindications"

MULTISTAGE_WIZARD_MODULES = (
    "localized_initial",
    "recurrence_bcr",
    "post_prostatectomy",
    "post_radiotherapy_followup",
    "post_radiotherapy_or_local_salvage",
    "mcspc_high_volume_sync",
    "mcspc_low_volume_sync_oligo",
    "mcspc_oligo_metachronous",
    "m0_crpc",
    "m1_crpc",
)


def build_capture_integrity_readiness(
    registry: Any | None = None,
    *,
    scope: str = "full",
) -> dict[str, Any]:
    """Build a read-only capture-integrity gate for V2 clinical flows."""
    if registry is None:
        from prostanet.application.module_registry import ModuleRegistry

        registry = ModuleRegistry()

    scope_key = str(scope or "full").strip().lower()
    include_rows = scope_key != "summary"
    checks: list[dict[str, Any]] = []

    checks.extend(_schema_checks(registry))
    checks.extend(_module_evaluation_checks(registry))
    checks.extend(_registration_context_checks(registry))
    checks.extend(_clinical_field_router_checks())

    summary = _build_summary(checks)
    payload: dict[str, Any] = {
        "available": True,
        "source": "capture_integrity_readiness",
        "version": CAPTURE_INTEGRITY_VERSION,
        "computed_at": utc_now_iso(),
        "scope": "summary" if scope_key == "summary" else "full",
        "read_only": True,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "summary": summary,
        "next_layer_allowed": summary["critical_failure_count"] == 0,
        "surfaces": [
            "wizard:diagnostic_workup",
            "wizard:localized_initial",
            "wizard:recurrence_bcr",
            "wizard:post_prostatectomy",
            "wizard:post_radiotherapy_or_local_salvage",
            "wizard:mcspc_*",
            "wizard:m0_crpc",
            "wizard:m1_crpc",
            "module_evaluate:diagnostic_workup",
            "module_evaluate:localized_initial",
            "registration_context:diagnostic_workup",
            "registration_context:localized_initial",
            "registration_context:m1_crpc",
            "clinical_field_router:diagnostic_workup:longitudinal_followup",
            "clinical_field_router:localized_initial:longitudinal_followup",
            "clinical_field_router:recurrence_bcr:longitudinal_followup",
            "clinical_field_router:mcspc_high_volume_sync:longitudinal_followup",
            "clinical_field_router:m0_crpc:longitudinal_followup",
            "clinical_field_router:m1_crpc:longitudinal_followup",
        ],
        "recommendations": _recommendations(checks),
    }
    if include_rows:
        payload["checks"] = checks
    return payload


def _schema_checks(registry: Any) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    diagnostic_raw = registry.get_module_schema("diagnostic_workup")
    diagnostic_wizard = filter_schema_for_wizard(diagnostic_raw, "diagnostic_workup")
    diagnostic_fields = _field_names(diagnostic_wizard)
    diagnostic_field_set = set(diagnostic_fields)
    diagnostic_by_name = _fields_by_name(diagnostic_wizard)
    diagnostic_psad = diagnostic_by_name.get("psad") or {}

    checks.append(
        _check(
            "diagnostic_wizard_single_ape",
            diagnostic_fields.count("psa") == 1 and diagnostic_field_set.isdisjoint(PSA_RECAPTURE_ALIASES),
            severity="critical",
            surface="wizard:diagnostic_workup",
            message="Diagnostico inicial solicita APE una sola vez en el wizard.",
            evidence={
                "psa_count": diagnostic_fields.count("psa"),
                "recapture_aliases_visible": sorted(diagnostic_field_set & PSA_RECAPTURE_ALIASES),
            },
            action="Mantener APE como scalar unico en wizard y migrar historial a registro longitudinal.",
        )
    )
    checks.append(
        _check(
            "diagnostic_psad_is_derived_or_override_only",
            _field_has_visibility(diagnostic_psad, "show_psad_override", "1")
            and not bool(diagnostic_psad.get("required"))
            and str(diagnostic_psad.get("default") or "") != "0",
            severity="critical",
            surface="wizard:diagnostic_workup",
            message="PSAD diagnostico no se exige manualmente; solo aparece como override externo.",
            evidence={
                "psad_present": "psad" in diagnostic_fields,
                "required": bool(diagnostic_psad.get("required")),
                "default": diagnostic_psad.get("default"),
                "visibility": diagnostic_psad.get("conditional_visibility") or {},
                "derived_from": diagnostic_psad.get("derived_from") or [],
            },
            action="Si falta volumen prostatico, pedir volumen o reportar PSAD no calculable; no pedir PSAD manual por defecto.",
        )
    )

    localized_raw = registry.get_module_schema("localized_initial")
    localized_full_fields = _field_names(localized_raw)
    localized_full_field_set = set(localized_full_fields)
    localized_raw_by_name = _fields_by_name(localized_raw)
    localized_wizard = filter_schema_for_wizard(localized_raw, "localized_initial")
    localized_fields = _field_names(localized_wizard)
    localized_field_set = set(localized_fields)
    localized_by_name = _fields_by_name(localized_wizard)
    localized_psad = localized_by_name.get("psad") or {}

    checks.append(
        _check(
            "localized_wizard_single_ape",
            localized_fields.count("psa") == 1 and localized_field_set.isdisjoint(PSA_RECAPTURE_ALIASES),
            severity="critical",
            surface="wizard:localized_initial",
            message="Estadificacion inicial localizada solicita APE una sola vez.",
            evidence={
                "psa_count": localized_fields.count("psa"),
                "recapture_aliases_visible": sorted(localized_field_set & PSA_RECAPTURE_ALIASES),
            },
            action="No reintroducir baseline_psa/ape como campos paralelos del wizard.",
        )
    )
    checks.append(
        _check(
            "localized_psad_is_derived",
            "psa" in set(localized_psad.get("derived_from") or [])
            and "prostate_volume_ml" in set(localized_psad.get("derived_from") or [])
            and str(localized_psad.get("default") or "") != "0",
            severity="critical",
            surface="wizard:localized_initial",
            message="PSAD localizado se deriva de APE y volumen prostatico, sin default falso en cero.",
            evidence={
                "psad_present": "psad" in localized_fields,
                "required": bool(localized_psad.get("required")),
                "default": localized_psad.get("default"),
                "derived_from": localized_psad.get("derived_from") or [],
                "clinical_role": localized_psad.get("clinical_role") or "",
            },
            action="Conservar compatibilidad API para psad historico, pero mostrarlo como derivado en V2.",
        )
    )
    checks.append(
        _check(
            "localized_systemic_noise_deferred",
            LOCALIZED_SYSTEMIC_NOISE_FIELDS.isdisjoint(localized_field_set)
            and LOCALIZED_SYSTEMIC_NOISE_FIELDS.issubset(localized_full_field_set),
            severity="critical",
            surface="wizard:localized_initial",
            message="Gates sistemicos avanzados no cargan por defecto en estadificacion inicial localizada.",
            evidence={
                "visible_noise_fields": sorted(LOCALIZED_SYSTEMIC_NOISE_FIELDS & localized_field_set),
                "full_schema_retains_fields": sorted(LOCALIZED_SYSTEMIC_NOISE_FIELDS & localized_full_field_set),
            },
            action="Mantener estos campos detras de familias avanzadas o triggers terapeuticos, sin eliminarlos del contrato completo.",
        )
    )
    checks.append(
        _check(
            "localized_systemic_contraindications_gated",
            all(
                _field_has_visibility(localized_raw_by_name.get(field_name) or {}, SYSTEMIC_PIVOTAL_DISCLOSURE_TRIGGER, "1")
                for field_name in LOCALIZED_SYSTEMIC_CONTRAINDICATION_FIELDS
            ),
            severity="critical",
            surface="wizard:localized_initial",
            message="Contraindicaciones sistemicas pivotales existen, pero quedan detras de disclosure explicito.",
            evidence={
                "trigger": SYSTEMIC_PIVOTAL_DISCLOSURE_TRIGGER,
                "field_visibility": {
                    field_name: (localized_raw_by_name.get(field_name) or {}).get("conditional_visibility") or {}
                    for field_name in sorted(LOCALIZED_SYSTEMIC_CONTRAINDICATION_FIELDS)
                },
                "visible_by_default": sorted(LOCALIZED_SYSTEMIC_CONTRAINDICATION_FIELDS & localized_field_set),
            },
            action="Mostrar este bloque solo cuando el clinico abra seguridad sistemica o exista trigger terapeutico real.",
        )
    )

    multistage_noise: dict[str, list[str]] = {}
    multistage_counts: dict[str, int] = {}
    for module_id in MULTISTAGE_WIZARD_MODULES:
        try:
            module_schema = registry.get_module_schema(module_id)
        except Exception as exc:
            multistage_noise[module_id] = [f"schema_error:{exc}"]
            multistage_counts[module_id] = 0
            continue
        wizard_schema = filter_schema_for_wizard(module_schema, module_id)
        names = set(_field_names(wizard_schema))
        multistage_noise[module_id] = sorted(SYSTEMIC_PIVOTAL_NOISE_FIELDS & names)
        multistage_counts[module_id] = len(names)
    checks.append(
        _check(
            "multistage_wizard_systemic_gate_noise_deferred",
            all(not values for values in multistage_noise.values()),
            severity="critical",
            surface="wizard:multi_stage",
            message="Los wizards por estadio no cargan por defecto taxano, PARP, PSMA-RLT o citopenias fuera de disparador clinico.",
            evidence={
                "modules_checked": list(MULTISTAGE_WIZARD_MODULES),
                "visible_noise_by_module": multistage_noise,
                "field_counts_by_module": multistage_counts,
            },
            action="Conservar gates completos en el schema bruto, pero mantenerlos detras de familias/trigger terapeutico por estadio.",
        )
    )
    return checks


def _module_evaluation_checks(registry: Any) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    localized_payload = {
        "age": 65,
        "psa": 12,
        "psad": "No disponible",
        "prostate_volume_ml": "No disponible",
        "clinical_tstage": "T2b",
        "gleason_primary": 4,
        "gleason_secondary": 3,
        "isup_grade": 3,
        "num_cores_positive": 4,
        "total_cores": 12,
        "nodal_status": "N0",
        "metastasis_site": "M0",
        "ecog_score": "0",
    }
    localized_result, localized_error = _safe_evaluate(registry, "localized_initial", localized_payload)
    checks.append(
        _check(
            "localized_evaluate_tolerates_unavailable_psad",
            localized_error == "",
            severity="critical",
            surface="module_evaluate:localized_initial",
            message="El motor localizado no debe fallar si PSAD/volumen llegan como no disponible.",
            evidence={
                "error": localized_error,
                "risk_group": ((localized_result or {}).get("nccn_primary") or {}).get("risk_group") if localized_result else "",
            },
            action="Usar conversion numerica segura y derivacion PSAD cuando exista volumen.",
        )
    )

    dre_outcomes: dict[str, dict[str, Any]] = {}
    for stage in ("T2a", "T2b", "T2c", "T4"):
        result, error = _safe_evaluate(
            registry,
            "diagnostic_workup",
            {
                "age": 65,
                "psa": 12,
                "dre_finding": stage,
                "clinical_tstage_dre_estimate": stage,
                "prostate_volume_ml": 40,
                "biopsy_status": "pending",
                "mpmri_status": "not_done",
            },
        )
        text = json.dumps(result or {}, ensure_ascii=False).lower()
        dre_outcomes[stage] = {
            "error": error,
            "mentions_stage": stage.lower() in text or f"c{stage.lower()}" in text,
            "says_not_suspicious": "no sospechoso" in text,
        }
    checks.append(
        _check(
            "diagnostic_dre_t2a_to_t4_is_suspicious",
            all(not row["error"] and row["mentions_stage"] and not row["says_not_suspicious"] for row in dre_outcomes.values()),
            severity="critical",
            surface="module_evaluate:diagnostic_workup",
            message="TR T2a/T2b/T2c/T4 se interpreta como sospechoso y conserva etiqueta clinica.",
            evidence=dre_outcomes,
            action="Normalizar DRE/TR antes de narrativa NCCN/EAU y no degradar T2+ a tacto no sospechoso.",
        )
    )
    return checks


def _registration_context_checks(registry: Any) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    tracking_service = PatientTrackingService()

    diagnostic_payload = {
        "age": 65,
        "psa": 12,
        "dre_finding": "T2a",
        "clinical_tstage_dre_estimate": "T2a",
        "prostate_volume_ml": 40,
        "biopsy_status": "pending",
        "mpmri_status": "not_done",
    }
    diagnostic_result, _ = _safe_evaluate(registry, "diagnostic_workup", diagnostic_payload)
    diagnostic_context = tracking_service.build_registration_context(
        module_schema=registry.get_module_schema("diagnostic_workup"),
        module_id="diagnostic_workup",
        state="diagnostic_workup",
        assessment_input=diagnostic_payload,
        assessment_result=diagnostic_result or {},
    )
    diagnostic_fields = _registration_field_names(diagnostic_context)
    checks.append(
        _check(
            "diagnostic_registration_psa_history_only",
            "psa_history" in diagnostic_fields
            and "psa" not in diagnostic_fields
            and "baseline_psa" not in diagnostic_fields
            and _registration_has_seeded_psa(diagnostic_context, 12),
            severity="critical",
            surface="registration_context:diagnostic_workup",
            message="Registro diagnostico reutiliza el APE capturado y abre historial longitudinal, no recaptura scalar.",
            evidence={
                "psa_related_visible": sorted(diagnostic_fields & {"psa", "baseline_psa", "psa_history"}),
                "seeded_history": (diagnostic_context.get("registration_defaults") or {}).get("psa_history") or [],
            },
            action="Mantener APE como bloque longitudinal en registro, precargado desde el wizard.",
        )
    )

    localized_payload = {
        "age": 65,
        "psa": 12,
        "clinical_tstage": "T2b",
        "gleason_primary": 4,
        "gleason_secondary": 3,
        "isup_grade": 3,
        "num_cores_positive": 4,
        "total_cores": 12,
        "prostate_volume_ml": 40,
        "nodal_status": "N0",
        "metastasis_site": "M0",
        "ecog_score": "0",
        "charlson_score": 1,
        "frailty_status": "Fit",
        "g8_score": 15,
        "anesthesia_surgical_fitness": "Fit",
        "ipss_score": 7,
        "iief5_score": 18,
        "diagnosis_date": "2026-05-29",
    }
    localized_result, _ = _safe_evaluate(registry, "localized_initial", localized_payload)
    localized_context = tracking_service.build_registration_context(
        module_schema=registry.get_module_schema("localized_initial"),
        module_id="localized_initial",
        state="localized_initial",
        assessment_input=localized_payload,
        assessment_result=localized_result or {},
    )
    localized_fields = _registration_field_names(localized_context)
    localized_fragments = _registration_fragment_ids(localized_context)
    checks.append(
        _check(
            "localized_registration_psa_history_only",
            "psa_history" in localized_fields
            and "psa" not in localized_fields
            and "baseline_psa" not in localized_fields
            and _registration_has_seeded_psa(localized_context, 12),
            severity="critical",
            surface="registration_context:localized_initial",
            message="Registro localizado hereda APE como serie longitudinal y evita recaptura scalar.",
            evidence={
                "psa_related_visible": sorted(localized_fields & {"psa", "baseline_psa", "psa_history"}),
                "seeded_history": (localized_context.get("registration_defaults") or {}).get("psa_history") or [],
            },
            action="No pedir APE dos veces; usar el historial APE como unica puerta longitudinal.",
        )
    )
    checks.append(
        _check(
            "localized_registration_no_systemic_labs",
            LOCALIZED_SYSTEMIC_BASELINE_FIELDS.isdisjoint(localized_fields),
            severity="critical",
            surface="registration_context:localized_initial",
            message="Registro localizado inicial no solicita laboratorio sistemico avanzado no relevante.",
            evidence={"visible_systemic_fields": sorted(LOCALIZED_SYSTEMIC_BASELINE_FIELDS & localized_fields)},
            action="Reservar testosterona seriada, Hb, FA, DHL, albumina y DXA para estados avanzados o trigger explicito.",
        )
    )
    checks.append(
        _check(
            "localized_registration_no_unselected_as_rt",
            LOCALIZED_UNSELECTED_ROUTE_FIELDS.isdisjoint(localized_fields)
            and "fragment_active_surveillance_operational" not in localized_fragments
            and "fragment_radiotherapy_detailed" not in localized_fragments,
            severity="critical",
            surface="registration_context:localized_initial",
            message="Registro localizado intermedio/alto no abre VA o RT detallada si aun no son ruta elegida.",
            evidence={
                "visible_route_fields": sorted(LOCALIZED_UNSELECTED_ROUTE_FIELDS & localized_fields),
                "fragments": sorted(localized_fragments),
            },
            action="Activar captura operacional de VA/RT solo con recomendacion elegible, seleccion de ruta o evidencia ya recibida.",
        )
    )

    advanced_context = tracking_service.build_registration_context(
        module_schema=registry.get_module_schema("m1_crpc"),
        module_id="m1_crpc",
        state="m1_crpc",
        assessment_input={
            "age": 72,
            "psa": 35,
            "metastasis_site": "M1b",
            "ecog_score": "1",
            "line_of_therapy_number": 2,
            "current_treatment": "abiraterone",
        },
        assessment_result={},
    )
    advanced_fields = _registration_field_names(advanced_context)
    checks.append(
        _check(
            "advanced_registration_keeps_systemic_context",
            LOCALIZED_SYSTEMIC_BASELINE_FIELDS.issubset(advanced_fields),
            severity="watch",
            surface="registration_context:m1_crpc",
            message="La reduccion de campos no elimina capacidad sistemica: sigue disponible en enfermedad avanzada.",
            evidence={"advanced_systemic_fields_present": sorted(LOCALIZED_SYSTEMIC_BASELINE_FIELDS & advanced_fields)},
            action="Si un campo sistemico falta en mCRPC, restaurarlo alli en vez de cargarlo en localizado inicial.",
        )
    )
    return checks


def _clinical_field_router_checks() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    try:
        from prostanet.presentation.clinical_field_router import (
            build_clinical_field_router,
        )
    except Exception as exc:
        return [
            _check(
                "clinical_field_router_available",
                False,
                severity="critical",
                surface="clinical_field_router",
                message="El router clinico longitudinal debe estar disponible para evitar recaptura visual.",
                evidence={"error": str(exc)},
                action="Restaurar clinical_field_router antes de validar captura longitudinal.",
            )
        ]

    localized_router = build_clinical_field_router("localized_initial", phase="longitudinal_followup")
    localized_names = _router_field_names(localized_router)
    checks.append(
        _check(
            "localized_longitudinal_router_single_ape",
            (localized_names & {"psa", "psa_value", "baseline_psa", "psa_baseline_ng_ml", "ape", "ape_basal"}) == {"psa_value"},
            severity="critical",
            surface="clinical_field_router:localized_initial:longitudinal_followup",
            message="El router longitudinal localizado sugiere APE solo como nueva medicion seriada.",
            evidence={
                "psa_related_visible": sorted(localized_names & {"psa", "psa_value", "baseline_psa", "psa_baseline_ng_ml", "ape", "ape_basal"}),
            },
            action="Mantener psa_value como serie append-only y no reintroducir alias baseline/APE en seguimiento.",
        )
    )
    checks.append(
        _check(
            "localized_longitudinal_router_no_systemic_noise",
            localized_names.isdisjoint(LONGITUDINAL_SYSTEMIC_NOISE_FIELDS),
            severity="critical",
            surface="clinical_field_router:localized_initial:longitudinal_followup",
            message="Seguimiento localizado inicial no sugiere testosterona, CTCAE o laboratorios sistemicos por defecto.",
            evidence={"visible_systemic_fields": sorted(localized_names & LONGITUDINAL_SYSTEMIC_NOISE_FIELDS)},
            action="Abrir esos campos solo con carril ARPI/CRPC/metastasico o trigger terapeutico explicito.",
        )
    )

    diagnostic_router = build_clinical_field_router("diagnostic_workup", phase="longitudinal_followup")
    diagnostic_names = _router_field_names(diagnostic_router)
    checks.append(
        _check(
            "diagnostic_longitudinal_router_no_manual_psad",
            "psa_value" in diagnostic_names
            and "prostate_volume_ml" in diagnostic_names
            and diagnostic_names.isdisjoint({"psad", "psa_density"}),
            severity="critical",
            surface="clinical_field_router:diagnostic_workup:longitudinal_followup",
            message="Seguimiento diagnostico pide APE/volumen y no pide densidad APE manual.",
            evidence={
                "psa_related_visible": sorted(diagnostic_names & {"psa", "psa_value", "psad", "psa_density", "prostate_volume_ml"}),
            },
            action="Calcular PSAD al tener volumen; nunca usar densidad manual como campo longitudinal principal.",
        )
    )
    checks.append(
        _check(
            "diagnostic_longitudinal_router_no_systemic_noise",
            diagnostic_names.isdisjoint(LONGITUDINAL_SYSTEMIC_NOISE_FIELDS | {"ecog_score"}),
            severity="critical",
            surface="clinical_field_router:diagnostic_workup:longitudinal_followup",
            message="Sospecha diagnostica no sugiere campos sistemicos o ECOG por defecto en seguimiento.",
            evidence={"visible_systemic_fields": sorted(diagnostic_names & (LONGITUDINAL_SYSTEMIC_NOISE_FIELDS | {"ecog_score"}))},
            action="Reservar esos campos para estados avanzados o carriles explicitos.",
        )
    )
    bcr_router = build_clinical_field_router("recurrence_bcr", phase="longitudinal_followup")
    bcr_names = _router_field_names(bcr_router)
    mcspc_router = build_clinical_field_router("mcspc_high_volume_sync", phase="longitudinal_followup")
    mcspc_names = _router_field_names(mcspc_router)
    m0_router = build_clinical_field_router("m0_crpc", phase="longitudinal_followup")
    m0_names = _router_field_names(m0_router)
    m1_router = build_clinical_field_router("m1_crpc", phase="longitudinal_followup")
    m1_names = _router_field_names(m1_router)
    systemic_followup_minimum = {"psa_value", "testosterone_value", "ecog_score", "ctcae_grade_max"}
    checks.append(
        _check(
            "multistage_longitudinal_router_stage_specific",
            {"psa_value", "bcr_psa", "psma_pet_staging_recent"} <= bcr_names
            and bcr_names.isdisjoint({"testosterone_value", "ctcae_grade_max"})
            and systemic_followup_minimum <= mcspc_names
            and systemic_followup_minimum <= m0_names
            and systemic_followup_minimum <= m1_names
            and "bcr_psa" not in (mcspc_names | m0_names | m1_names),
            severity="critical",
            surface="clinical_field_router:multi_stage:longitudinal_followup",
            message="El registro longitudinal cambia de superficie segun estadio: BCR conserva PSA/PSMA de rescate; mHSPC/m0/m1 abren castracion, ECOG y toxicidad.",
            evidence={
                "bcr_relevant": sorted(bcr_names & {"psa_value", "bcr_psa", "psma_pet_staging_recent", "testosterone_value", "ctcae_grade_max"}),
                "mcspc_relevant": sorted(mcspc_names & (systemic_followup_minimum | {"bcr_psa"})),
                "m0_relevant": sorted(m0_names & (systemic_followup_minimum | {"bcr_psa"})),
                "m1_relevant": sorted(m1_names & (systemic_followup_minimum | {"bcr_psa"})),
            },
            action="Usar el router por estado como frontera antes de agregar nuevos carriles longitudinales.",
        )
    )
    return checks


def _safe_evaluate(registry: Any, module_id: str, payload: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str]:
    try:
        result = registry.evaluate_module(module_id, dict(payload))
        return result if isinstance(result, dict) else {}, ""
    except Exception as exc:
        return None, str(exc)


def _check(
    key: str,
    condition: bool,
    *,
    severity: str,
    surface: str,
    message: str,
    evidence: Mapping[str, Any],
    action: str,
) -> dict[str, Any]:
    return {
        "key": key,
        "status": "pass" if condition else "fail",
        "severity": severity,
        "surface": surface,
        "message": message,
        "evidence": dict(evidence),
        "recommended_action": action,
    }


def _build_summary(checks: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [check for check in checks if check.get("status") != "pass"]
    critical_failed = [check for check in failed if check.get("severity") == "critical"]
    watch_failed = [check for check in failed if check.get("severity") != "critical"]
    status = (
        "capture_integrity_blocked"
        if critical_failed
        else "capture_integrity_watch"
        if watch_failed
        else "capture_integrity_ready"
    )
    check_count = len(checks)
    pass_count = check_count - len(failed)
    return {
        "capture_integrity_status": status,
        "check_count": check_count,
        "pass_count": pass_count,
        "failed_count": len(failed),
        "critical_failure_count": len(critical_failed),
        "watch_failure_count": len(watch_failed),
        "pass_rate_pct": round((pass_count / check_count) * 100, 1) if check_count else 0.0,
        "primary_gate": "multi_stage_no_recapture_stage_relevance_v2",
        "next_operator_action": (
            "Cerrar checks criticos antes de agregar logica clinica."
            if critical_failed
            else "Continuar con validacion visual/registro longitudinal y expansion controlada."
        ),
    }


def _recommendations(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for check in checks:
        if check.get("status") == "pass":
            continue
        rows.append(
            {
                "severity": check.get("severity") or "watch",
                "surface": check.get("surface") or "",
                "check_key": check.get("key") or "",
                "action": check.get("recommended_action") or "",
            }
        )
    if rows:
        return rows
    return [
        {
            "severity": "info",
            "surface": "capture_integrity",
            "check_key": "ready_for_next_layer",
            "action": "La captura multiestadio, evaluacion y registro longitudinal estan protegidos contra recaptura y campos fuera de estado para el set trazador.",
        }
    ]


def _field_names(schema: Mapping[str, Any]) -> list[str]:
    return [str(field.get("name") or "") for field in schema.get("fields") or [] if str(field.get("name") or "")]


def _fields_by_name(schema: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(field.get("name") or ""): dict(field or {})
        for field in schema.get("fields") or []
        if str(field.get("name") or "")
    }


def _field_has_visibility(field: Mapping[str, Any], trigger: str, value: str) -> bool:
    visibility = field.get("conditional_visibility") or {}
    if not isinstance(visibility, Mapping):
        return False
    raw_values = visibility.get(trigger)
    if raw_values is None:
        return False
    if isinstance(raw_values, (list, tuple, set)):
        values = {str(item) for item in raw_values}
    else:
        values = {str(raw_values)}
    return str(value) in values


def _registration_field_names(context: Mapping[str, Any]) -> set[str]:
    names = {str(field.get("name") or "") for field in context.get("deduped_visible_fields") or [] if str(field.get("name") or "")}
    for fragment in context.get("registration_fragments") or []:
        for field in fragment.get("fields") or []:
            name = str(field.get("name") or "")
            if name:
                names.add(name)
    return names


def _registration_fragment_ids(context: Mapping[str, Any]) -> set[str]:
    return {str(fragment.get("id") or "") for fragment in context.get("registration_fragments") or [] if str(fragment.get("id") or "")}


def _registration_has_seeded_psa(context: Mapping[str, Any], expected_value: float) -> bool:
    history = (context.get("registration_defaults") or {}).get("psa_history") or []
    if not isinstance(history, list):
        return False
    for row in history:
        if not isinstance(row, Mapping):
            continue
        value = safe_float(row.get("psa_value") or row.get("value"), default=None)
        if value is not None and abs(float(value) - float(expected_value)) < 0.001:
            return True
    return False


def _router_field_names(router: Mapping[str, Any]) -> set[str]:
    return {
        str(field.get("name") or "")
        for group in router.get("group_order") or []
        for field in group.get("fields") or []
        if str(field.get("name") or "")
    }
