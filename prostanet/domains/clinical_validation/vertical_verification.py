from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
import os
from typing import Any

import tracking_db

from prostanet.domains.clinical_validation.guideline_oracle import (
    build_guideline_oracle_catalog,
)
from prostanet.domains.clinical_validation.longitudinal_concordance_engine import (
    evaluate_validation_seed,
)
from prostanet.domains.clinical_validation.trajectory_catalog import (
    build_trajectory_catalog,
)
from prostanet.domains.clinical_validation.trajectory_seed_service import (
    DEFAULT_BASE_URL,
    capture_patient_validation_snapshot,
    seed_trajectory_case,
    validation_db_context,
)
from prostanet.domains.clinical_validation.visual_validation_runner import (
    attach_visual_artifacts,
)
from prostanet.application.module_registry import ModuleRegistry
from prostanet.domains.clinical_assessments.service import ClinicalAssessmentService
from prostanet.domains.patient_tracking.service import PatientTrackingService


TARGET_SCENARIO_FAMILIES = (
    "diagnostic_workup",
    "post_negative_biopsy_followup",
    "localized_initial",
    "active_surveillance",
    "mHSPC",
    "post_radiotherapy_or_local_salvage",
    "adt_progression_verification",
    "m0_crpc",
    "m1_crpc",
    "post_prostatectomy",
    "recurrence_bcr",
    # Auditoría #21 (cierre OOS-13): EPIC 9 añadió 18 trayectorias con
    # `scenario_family="epic9_hardening"` (ref. Auditoría #20 línea 1570).
    # `_filtered_trajectories` las omitía silenciosamente, provocando que
    # `run_vertical_verification` reportara 54 seeded_cases vs 72 esperados.
    "epic9_hardening",
)
DIAGNOSTIC_FAMILIES = {"diagnostic_workup", "post_negative_biopsy_followup"}
LOCALIZED_FAMILIES = {"localized_initial", "active_surveillance"}
MHSPC_FAMILIES = {"mHSPC"}
POST_RT_FAMILIES = {"post_radiotherapy_or_local_salvage"}
CRPC_FAMILIES = {"adt_progression_verification", "m0_crpc", "m1_crpc"}
POST_RP_FAMILIES = {"post_prostatectomy", "recurrence_bcr"}
DIAGNOSTIC_STATES = {"diagnostic_workup", "post_negative_biopsy_followup"}
LOCALIZED_STATES = {"localized_initial"}
MHSPC_STATES = {
    "mcspc_low_volume_sync_oligo",
    "mcspc_oligo_metachronous",
    "mcspc_high_volume",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
}
POST_RT_STATES = {"recurrence_bcr", "post_radiotherapy_or_local_salvage"}
CRPC_STATES = {"adt_progression_verification", "m0_crpc", "m1_crpc"}
POST_RP_STATES = {"post_prostatectomy", "recurrence_bcr"}
MHSPC_REQUIRED_KEYS = {
    "phenotype_summary",
    "preferred_frontline_regimen",
    "frontline_regimen_rankings",
    "triplet_decision",
    "docetaxel_fitness",
    "qa_validation",
    "final_presented_recommendation",
}
DIAGNOSTIC_REQUIRED_KEYS = {
    "diagnostic_track",
    "biopsy_readiness",
    "mri_quality_or_repeat_need",
    "risk_refiners",
    "qa_validation",
    "final_presented_recommendation",
}
LOCALIZED_REQUIRED_KEYS = {
    "localized_track",
    "active_surveillance_eligibility",
    "active_surveillance_course",
    "upgrade_triggers",
    "preferred_local_strategy",
    "final_presented_recommendation",
}
POST_RT_REQUIRED_KEYS = {
    "post_rt_course",
    "post_rt_salvage_window_status",
    "post_rt_failure_definition",
    "post_rt_transition_bundle",
    "post_rt_local_salvage_ranking",
    "restaging_strategy",
    "local_salvage_pathway",
    "systemic_redirection_status",
    "final_presented_recommendation",
}
CRPC_REQUIRED_KEYS = {
    "state_family",
    "rule_based_recommendation",
    "sequence_candidates",
    "safety_gates",
    "qa_validation",
    "confidence",
    "final_presented_recommendation",
}
POST_RP_REQUIRED_KEYS = {
    "post_prostatectomy_course",
    "salvage_window_status",
    "restaging_strategy",
    "local_salvage_pathway",
    "blocking_inputs",
    "why_changed_today",
    "final_presented_recommendation",
}
REPRESENTATIVE_SCENARIOS = {
    "mhspc_first": [
        "mhspc_low_volume_sync_doublet",
        "mhspc_oligometachronous_mdt",
        "mhspc_high_volume_triplet",
        "mhspc_high_volume_fitness_limited",
    ],
    "diagnostic_to_biopsy_first": [
        "diagnostic_low_psa_recheck",
        "diagnostic_high_targeted_biopsy",
        "post_negative_biopsy_reopen_due_to_mri",
    ],
    "localized_surveillance_first": [
        "localized_very_low_active_surveillance",
        "active_surveillance_confirmatory_overdue",
        "active_surveillance_upgrade_conversion",
    ],
    "post_rt_salvage_first": [
        "post_rt_psa_rise_restage",
        "post_rt_local_salvage_candidate",
        "post_rt_oligomet_mdt_candidate",
        "post_rt_systemic_redirection",
    ],
    "crpc_first": [
        "adt_progression_non_castrate",
        "m0_crpc_contraindication_refines_choice",
        "m1_crpc_abiraterone_hepatic_safety",
    ],
    "post_rp_salvage_first": [
        "post_prostatectomy_stable",
        "post_prostatectomy_persistent_psa",
        "bcr_post_rp_local_pelvic",
        "bcr_post_rp_disseminated_psma",
    ],
}


@dataclass
class AuditAssertion:
    key: str
    passed: bool
    expected: Any
    actual: Any
    severity: str = "normal"
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "passed": bool(self.passed),
            "expected": self.expected,
            "actual": self.actual,
            "severity": self.severity,
            "message": self.message,
        }


def _text(value: Any) -> str:
    return str(value or "").strip()


def _contains(text: Any, needle: str) -> bool:
    return str(needle or "").lower() in str(text or "").lower()


def _assertion(
    key: str,
    passed: bool,
    expected: Any,
    actual: Any,
    *,
    severity: str = "normal",
    message: str = "",
) -> dict[str, Any]:
    return AuditAssertion(
        key=key,
        passed=passed,
        expected=expected,
        actual=actual,
        severity=severity,
        message=message,
    ).to_dict()


def _snapshot_field_values(snapshot: dict[str, Any]) -> dict[str, Any]:
    patient = dict(snapshot.get("patient_record") or {})
    truth = dict((patient.get("longitudinal_truth_snapshot") or {}).get("field_values") or {})
    values = {}
    for source in (
        patient.get("baseline") or {},
        truth,
        dict((patient.get("latest_assessment") or {}).get("input_snapshot") or {}),
        (patient.get("follow_ups") or [{}])[-1] if patient.get("follow_ups") else {},
        (((patient.get("stage_visits") or [{}])[-1].get("visit_bundle") or {}).get("payload") or {}) if patient.get("stage_visits") else {},
        patient.get("bcr") or {},
        patient.get("surgery") or {},
        patient.get("genomics") or patient.get("genomic_profile") or {},
        patient.get("psma_structured_profile") or {},
    ):
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if value not in (None, "", [], {}, "No aplica", "No documentado", "No realizado", "Desconocido", "Desconocida"):
                values[key] = value
    return values


def _top_treatments(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    top = []
    for item in list(bundle.get("sequence_candidates") or [])[:3]:
        top.append(
            {
                "label": _text(item.get("drug_label") or item.get("label")),
                "blocked": bool(item.get("blocked")),
                "blocked_by": list(item.get("blocked_by") or []),
                "is_preferred": bool(item.get("is_preferred", False)),
                "confidence": item.get("confidence"),
            }
        )
    if top:
        return top
    primary = dict(bundle.get("rule_based_recommendation") or {})
    if primary:
        return [
            {
                "label": _text(primary.get("recommended_action")),
                "blocked": False,
                "blocked_by": [],
                "is_preferred": True,
                "confidence": (bundle.get("confidence") or {}).get("composite_score"),
            }
        ]
    return []


def _latest_state_from_row(row: dict[str, Any]) -> str:
    return _text(row.get("latest_assessment_state") or row.get("current_state"))


def _vertical_from_family(family: str) -> str:
    if family in MHSPC_FAMILIES:
        return "mhspc_first"
    if family in DIAGNOSTIC_FAMILIES:
        return "diagnostic_to_biopsy_first"
    if family in LOCALIZED_FAMILIES:
        return "localized_surveillance_first"
    if family in POST_RT_FAMILIES:
        return "post_rt_salvage_first"
    if family in CRPC_FAMILIES:
        return "crpc_first"
    if family in POST_RP_FAMILIES:
        return "post_rp_salvage_first"
    return "other"


def _vertical_from_snapshot(snapshot: dict[str, Any]) -> str:
    longitudinal_bundle = dict(snapshot.get("longitudinal_bundle") or {})
    for bundle_key, vertical_name in (
        ("mhspc_copilot_bundle", "mhspc_first"),
        ("diagnostic_biopsy_bundle", "diagnostic_to_biopsy_first"),
        ("localized_surveillance_bundle", "localized_surveillance_first"),
        ("post_rt_salvage_bundle", "post_rt_salvage_first"),
        ("crpc_copilot_bundle", "crpc_first"),
        ("post_rp_salvage_bundle", "post_rp_salvage_first"),
    ):
        bundle = dict(longitudinal_bundle.get(bundle_key) or {})
        if bundle.get("available"):
            return vertical_name
    state = _text((snapshot.get("signals") or {}).get("effective_state"))
    if state in MHSPC_STATES:
        return "mhspc_first"
    if state in DIAGNOSTIC_STATES:
        return "diagnostic_to_biopsy_first"
    if state in LOCALIZED_STATES:
        return "localized_surveillance_first"
    if state in POST_RT_STATES and _snapshot_has_post_rt_context(snapshot):
        return "post_rt_salvage_first"
    if state in CRPC_STATES:
        return "crpc_first"
    if state in POST_RP_STATES and _snapshot_has_post_rp_context(snapshot):
        return "post_rp_salvage_first"
    return "other"


def _snapshot_has_post_rp_context(snapshot: dict[str, Any]) -> bool:
    patient = dict(snapshot.get("patient_record") or {})
    latest_assessment = dict(patient.get("latest_assessment") or {})
    bcr = dict(patient.get("bcr") or {})
    primary_treatment = _text(bcr.get("primary_treatment")).upper()
    if patient.get("surgery"):
        return True
    if primary_treatment in {"RP", "POST_RP", "RADICAL PROSTATECTOMY", "PROSTATECTOMY"}:
        return True
    if _text((patient.get("prior_history") or {}).get("current_state")) == "post_prostatectomy":
        return True
    for source in (
        patient.get("baseline") or {},
        (patient.get("longitudinal_truth_snapshot") or {}).get("field_values") or {},
        latest_assessment.get("input_snapshot") or {},
    ):
        if not isinstance(source, dict):
            continue
        if str(source.get("prior_prostatectomy", "")).strip().lower() in {"1", "true", "yes", "si", "sí"}:
            return True
        if any(_text(source.get(field)) for field in ("rp_date", "prostatectomy_date", "pathologic_stage", "pathological_stage")):
            return True
        if any(source.get(field) not in (None, "", "No documentado", "No realizado") for field in ("surgical_margin", "surgical_margin_status", "margin_location")):
            return True
    return False


def _snapshot_has_post_rt_context(snapshot: dict[str, Any]) -> bool:
    if _snapshot_has_post_rp_context(snapshot):
        return False
    patient = dict(snapshot.get("patient_record") or {})
    latest_assessment = dict(patient.get("latest_assessment") or {})
    bcr = dict(patient.get("bcr") or {})
    primary_treatment = _text(bcr.get("primary_treatment")).upper()
    if primary_treatment in {"RT", "RADIOTHERAPY", "EBRT", "RT_PRIMARY"}:
        return True
    for source in (
        patient.get("baseline") or {},
        (patient.get("longitudinal_truth_snapshot") or {}).get("field_values") or {},
        latest_assessment.get("input_snapshot") or {},
    ):
        if not isinstance(source, dict):
            continue
        if str(source.get("prior_radiation", "")).strip().lower() in {"1", "true", "yes", "si", "sí"}:
            return True
        if any(_text(source.get(field)) for field in ("radiation_date", "prior_rt_date")):
            return True
    return False


@contextmanager
def _temporary_vertical_flags() -> Any:
    overrides = {
        "ENABLE_MHSPC_COPILOT": "1",
        "ENABLE_DIAGNOSTIC_BIOPSY_COPILOT": "1",
        "ENABLE_LOCALIZED_SURVEILLANCE_COPILOT": "1",
        "ENABLE_POST_RT_SALVAGE_COPILOT": "1",
        "ENABLE_CRPC_COPILOT": "1",
        "ENABLE_POST_RP_SALVAGE_COPILOT": "1",
        "PROSTANET_AI_RUNTIME_MODE": "shadow",
    }
    previous = {key: os.environ.get(key) for key in overrides}
    try:
        for key, value in overrides.items():
            os.environ[key] = value
        import prostanet.ai.config as ai_config_module

        ai_config_module._config = None
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        import prostanet.ai.config as ai_config_module

        ai_config_module._config = None


def _filtered_trajectories() -> list[dict[str, Any]]:
    trajectories = [
        item
        for item in build_trajectory_catalog()
        if str(item.get("scenario_family") or "") in TARGET_SCENARIO_FAMILIES
    ]
    return build_guideline_oracle_catalog(trajectories)


def _representative_trajectory_map() -> dict[str, dict[str, Any]]:
    catalog = {str(item.get("scenario_id") or ""): item for item in _filtered_trajectories()}
    selected: dict[str, dict[str, Any]] = {}
    for scenario_ids in REPRESENTATIVE_SCENARIOS.values():
        for scenario_id in scenario_ids:
            trajectory = catalog.get(scenario_id)
            if trajectory:
                selected[scenario_id] = trajectory
    return selected


def _build_seeded_case_map(seed_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("case_key") or ""): dict(item) for item in list(seed_payload.get("cases") or [])}


def _seed_vertical_cohort_safely(
    trajectories: list[dict[str, Any]],
    *,
    base_url: str,
) -> dict[str, Any]:
    run_id = f"vertical-audit-{int(datetime.now(UTC).timestamp())}"
    seeded_cases: list[dict[str, Any]] = []
    registry = ModuleRegistry()
    assessment_service = ClinicalAssessmentService()
    tracking_service = PatientTrackingService()
    with validation_db_context(cohort_mode="isolated_temp_db") as context:
        for index, trajectory in enumerate(trajectories, start=1):
            try:
                seeded_cases.append(
                    seed_trajectory_case(
                        trajectory,
                        run_id=run_id,
                        case_index=index,
                        base_url=base_url,
                        registry=registry,
                        assessment_service=assessment_service,
                        tracking_service=tracking_service,
                    )
                )
            except Exception as exc:
                seeded_cases.append(
                    {
                        "run_id": run_id,
                        "case_key": f"{run_id}:{trajectory.get('scenario_id')}",
                        "scenario_id": trajectory.get("scenario_id"),
                        "scenario_family": trajectory.get("scenario_family"),
                        "title": trajectory.get("title"),
                        "patient_id": None,
                        "patient_nss": "",
                        "baseline_oracle": trajectory.get("baseline_oracle", {}),
                        "clinical_oracle": trajectory.get("clinical_oracle", {}),
                        "guideline_oracle": trajectory.get("guideline_oracle", {}),
                        "baseline": {},
                        "visits": [],
                        "final": {},
                        "seed_error": str(exc),
                    }
                )
        return {
            "run_id": run_id,
            "cohort_mode": context["cohort_mode"],
            "db_path": context["db_path"],
            "base_url": base_url,
            "generated_at": datetime.now(UTC).date().isoformat(),
            "cases": seeded_cases,
        }


def _required_contract_assertions(bundle: dict[str, Any], *, required_keys: set[str], prefix: str) -> list[dict[str, Any]]:
    return [
        _assertion(
            f"{prefix}_{key}",
            key in bundle and bundle.get(key) not in (None, ""),
            "present",
            bundle.get(key),
            severity="critical",
            message=f"El contrato visible debe exponer '{key}'.",
        )
        for key in sorted(required_keys)
    ]


def _build_treatment_assertions(snapshot: dict[str, Any], *, bundle: dict[str, Any], vertical: str) -> list[dict[str, Any]]:
    values = _snapshot_field_values(snapshot)
    assertions: list[dict[str, Any]] = []
    top_treatments = _top_treatments(bundle)
    top_labels = " | ".join(item.get("label", "") for item in top_treatments)
    effective_state = _text(bundle.get("effective_state") or (snapshot.get("signals") or {}).get("effective_state"))

    if vertical == "crpc_first":
        testosterone = values.get("testosterone_value", values.get("testosterone", values.get("testosterone_baseline")))
        try:
            testosterone_value = float(testosterone) if testosterone not in (None, "") else None
        except (TypeError, ValueError):
            testosterone_value = None
        if effective_state in {"m0_crpc", "m1_crpc"} and testosterone_value is not None:
            assertions.append(
                _assertion(
                    "crpc_requires_castrate_testosterone",
                    testosterone_value <= 50,
                    "<= 50 ng/dL",
                    testosterone_value,
                    severity="critical",
                    message="La secuenciación CRPC no debe activarse sin castración confirmada.",
                )
            )
        if effective_state == "m0_crpc":
            psadt = values.get("psadt_months")
            try:
                psadt_value = float(psadt) if psadt not in (None, "") else None
            except (TypeError, ValueError):
                psadt_value = None
            if psadt_value is not None and psadt_value > 10:
                primary = _text((bundle.get("rule_based_recommendation") or {}).get("recommended_action"))
                assertions.append(
                    _assertion(
                        "m0_psadt_slow_prefers_surveillance",
                        any(_contains(primary, token) for token in ("monitor", "vigil", "observ")),
                        "vigilancia/monitorización",
                        primary,
                        severity="critical",
                        message="PSADT >10 meses debe favorecer vigilancia estrecha antes que escalada automática.",
                    )
                )
            seizure = str(values.get("comorbidity_seizure", values.get("seizure_history", "0"))).strip() in {"1", "true", "True", "si", "sí", "yes"}
            if seizure and top_treatments:
                assertions.append(
                    _assertion(
                        "m0_seizure_prefers_darolutamide",
                        _contains(top_treatments[0].get("label"), "darolut"),
                        "Darolutamida",
                        top_treatments[0].get("label"),
                        severity="critical",
                        message="El riesgo convulsivo debe preservar darolutamida como opción preferente visible.",
                    )
                )
        if effective_state == "m1_crpc":
            ast = values.get("ast")
            alt = values.get("alt")
            bilirubin = values.get("bilirubin")
            try:
                ast_value = float(ast) if ast not in (None, "") else 0.0
                alt_value = float(alt) if alt not in (None, "") else 0.0
                bilirubin_value = float(bilirubin) if bilirubin not in (None, "") else 0.0
            except (TypeError, ValueError):
                ast_value = alt_value = bilirubin_value = 0.0
            if ast_value > 90 or alt_value > 120 or bilirubin_value >= 2:
                assertions.append(
                    _assertion(
                        "m1_hepatic_safety_blocks_abiraterone",
                        "abirater" not in top_labels.lower(),
                        "Sin abiraterona preferente",
                        top_labels,
                        severity="critical",
                        message="La hepatotoxicidad relevante debe bloquear abiraterona como opción visible preferente.",
                    )
                )
            hrr_positive = _contains(values.get("hrr_status"), "Positivo") or _text(values.get("hrr_gene")) not in {"", "Desconocido"}
            biomarker_source = _text(values.get("biomarker_source"))
            hrr_gene = _text(values.get("hrr_gene"))
            if hrr_positive and (biomarker_source in {"", "Desconocida", "Desconocido"} or hrr_gene in {"", "Desconocido"}):
                assertions.append(
                    _assertion(
                        "m1_hrr_traceability_before_parp",
                        "olapar" not in top_labels.lower() and "parp" not in top_labels.lower(),
                        "PARP no preferente sin trazabilidad",
                        top_labels,
                        severity="critical",
                        message="No debe priorizarse PARP sin gen HRR y fuente molecular trazables.",
                    )
                )
            psma_partial = _text(values.get("psma_rads_score")) == "3" or _text(values.get("psma_radioligand")) in {"", "Desconocido"}
            psma_negative_dominant = str(values.get("psma_negative_dominant_lesions", "0")).strip() in {"1", "true", "True"}
            if psma_partial or psma_negative_dominant:
                assertions.append(
                    _assertion(
                        "m1_psma_partial_blocks_lu177",
                        "lu-177" not in top_labels.lower() and "pluvicto" not in top_labels.lower(),
                        "Sin Lu-177 elegible pleno",
                        top_labels,
                        severity="critical",
                        message="La elegibilidad PSMA parcial o discordante no debe aparecer como vía plena a Lu-177.",
                    )
                )
            prior_therapy = _text(values.get("prior_therapy"))
            if any(token in prior_therapy.lower() for token in ("abirater", "enza", "apalut", "darolut")) and any(token in prior_therapy.lower() for token in ("docetax", "cabazitax")):
                assertions.append(
                    _assertion(
                        "m1_card_avoids_arpi_to_arpi_swap",
                        not any(_contains(item.get("label"), token) for item in top_treatments[:1] for token in ("abirater", "enzalut", "apalut", "darolut")),
                        "No ARPI->ARPI preferente",
                        top_treatments[0].get("label") if top_treatments else "",
                        severity="critical",
                        message="Tras ARPI y taxano previos no debe verse un intercambio ARPI-ARPI como preferencia dominante.",
                    )
                )

    if vertical == "post_rp_salvage_first":
        course = _text(bundle.get("post_prostatectomy_course"))
        salvage_window = _text(bundle.get("salvage_window_status"))
        state = _text(bundle.get("effective_state") or effective_state)
        if course == "persistent_psa":
            if salvage_window == "pending_inputs":
                assertions.append(
                    _assertion(
                        "persistent_psa_pending_inputs_stays_post_prostatectomy",
                        state == "post_prostatectomy",
                        "post_prostatectomy",
                        state,
                        severity="critical",
                        message="El PSA persistente sólo debe seguir en post prostatectomía mientras faltan inputs decisivos para cerrar salvage.",
                    )
                )
            elif salvage_window in {"open", "open_pending_restaging", "closed", "redirect_systemic"}:
                assertions.append(
                    _assertion(
                        "persistent_psa_decisive_context_promotes_bcr",
                        state == "recurrence_bcr",
                        "recurrence_bcr",
                        state,
                        severity="critical",
                        message="El PSA persistente con ventana de salvage ya clasificada debe operar como recurrencia bioquímica.",
                    )
                )
        if course == "stable_surveillance":
            assertions.append(
                _assertion(
                    "stable_surveillance_keeps_window_closed",
                    salvage_window == "closed",
                    "closed",
                    salvage_window,
                    severity="critical",
                    message="La vigilancia estable debe mantener la ventana de salvage cerrada.",
                )
            )
        if course == "true_bcr":
            salvage_feasible = str(values.get("salvage_local_feasible", "1")).strip() in {"1", "true", "True"}
            if salvage_feasible:
                assertions.append(
                    _assertion(
                        "true_bcr_keeps_salvage_visible",
                        salvage_window in {"open", "open_pending_restaging"},
                        "open/open_pending_restaging",
                        salvage_window,
                        severity="critical",
                        message="La BCR verdadera con factibilidad local debe mantener visible la ventana de salvage.",
                    )
                )
        psma_stage = _text(values.get("psma_stage_after_psma"))
        conventional_stage = _text(values.get("conventional_imaging_status"))
        if psma_stage in {"M1a", "M1b", "M1c"} or conventional_stage in {"M1", "M1A", "M1B", "M1C"}:
            local_path = dict(bundle.get("local_salvage_pathway") or {})
            assertions.append(
                _assertion(
                    "disseminated_pattern_redirects_systemic",
                    salvage_window == "redirect_systemic" and not bool(local_path.get("visible")),
                    "redirect_systemic + sin rescate local visible",
                    {"salvage_window_status": salvage_window, "local_salvage_visible": bool(local_path.get("visible"))},
                    severity="critical",
                    message="Un patrón PSMA/conventional M1 debe redirigir fuera del rescate local aislado.",
                )
            )
    if vertical == "mhspc_first":
        state = effective_state
        volume = _text(bundle.get("volume_disease"))
        primary = _text((bundle.get("rule_based_recommendation") or {}).get("recommended_action"))
        top_label = _text((bundle.get("preferred_frontline_regimen") or {}).get("regimen_label") or (bundle.get("preferred_frontline_regimen") or {}).get("display_label"))
        docetaxel_bundle = dict(bundle.get("docetaxel_fitness") or {})
        docetaxel_default = _text(docetaxel_bundle.get("docetaxel_default_intensification")).lower()
        docetaxel_fit = docetaxel_default == "yes"
        if state == "mcspc_low_volume_sync_oligo":
            assertions.append(
                _assertion(
                    "mhspc_low_volume_keeps_rt_primary_visible",
                    any(_contains(primary, token) for token in ("rt", "radioterapia")) or bool(bundle.get("rt_primary_candidate")),
                    "RT primaria visible",
                    {"recommended_action": primary, "rt_primary_candidate": bundle.get("rt_primary_candidate")},
                    severity="critical",
                    message="El mHSPC sincrónico de bajo volumen debe mantener visible la RT al primario.",
                )
            )
        if state == "mcspc_oligo_metachronous":
            assertions.append(
                _assertion(
                    "mhspc_oligo_metachronous_keeps_mdt_candidate",
                    bool(bundle.get("mdt_candidate")),
                    True,
                    bundle.get("mdt_candidate"),
                    severity="critical",
                    message="El mHSPC oligometacrónico debe mantener MDT como candidato visible.",
                )
            )
        if state in {"mcspc_high_volume", "mcspc_high_volume_sync"} and docetaxel_fit:
            triplet_bundle = bundle.get("triplet_decision") or {}
            triplet_text = " ".join(
                [
                    _text(triplet_bundle.get("decision")),
                    _text(triplet_bundle.get("status_label")),
                    _text(triplet_bundle.get("summary")),
                    _text(triplet_bundle.get("primary_reason")),
                    _text(triplet_bundle.get("preferred_triplet_backbone_label")),
                    top_label,
                ]
            ).lower()
            assertions.append(
                _assertion(
                    "mhspc_high_volume_fit_keeps_triplet_competitive",
                    "triplet" in triplet_text or "triplete" in triplet_text or "docetaxel" in triplet_text,
                    "Triplete competitivo / visible",
                    {"triplet_decision": bundle.get("triplet_decision"), "preferred_regimen": top_label},
                    severity="critical",
                    message="El alto volumen apto a docetaxel debe abrir discusión real de triplete.",
                )
            )
        frailty = _text(values.get("frailty_status"))
        if state in {"mcspc_high_volume", "mcspc_high_volume_metachronous"} and (
            docetaxel_default != "yes" or frailty.lower() in {"vulnerable", "frail", "fragil", "frágil"}
        ):
            assertions.append(
                _assertion(
                    "mhspc_high_volume_frailty_avoids_triplet_default",
                    "triplet" not in top_label.lower(),
                    "Sin triplete dominante",
                    top_label,
                    severity="critical",
                    message="En alto volumen metacrónico o fitness limitado no debe quedar triplete como default visible.",
                )
            )
        if volume:
            assertions.append(
                _assertion(
                    "mhspc_volume_resolved",
                    volume.lower() in {"low", "high", "bajo volumen", "alto volumen"},
                    "volumen resuelto",
                    volume,
                    severity="normal",
                    message="El bundle mHSPC debe exponer volumen derivado visible.",
                )
            )
    if vertical == "diagnostic_to_biopsy_first":
        track = _text(bundle.get("diagnostic_track"))
        primary = _text((bundle.get("rule_based_recommendation") or {}).get("recommended_action"))
        pirads = _text(values.get("pirads_score"))
        psad = values.get("psad")
        try:
            psad_value = float(psad) if psad not in (None, "") else None
        except (TypeError, ValueError):
            psad_value = None
        if track == "low_suspicion_surveillance":
            assertions.append(
                _assertion(
                    "diagnostic_low_suspicion_keeps_surveillance",
                    any(_contains(primary, token) for token in ("seguimiento", "monitor", "repetir")) and "biops" not in primary.lower(),
                    "seguimiento / vigilancia corta",
                    primary,
                    severity="critical",
                    message="La sospecha baja debe mantener una ruta diagnóstica conservadora.",
                )
            )
        if track in {"targeted_biopsy_ready", "reopen_after_negative_biopsy"} or pirads in {"4", "5"} or (psad_value is not None and psad_value >= 0.15):
            assertions.append(
                _assertion(
                    "diagnostic_high_signal_crosses_biopsy_threshold",
                    "biops" in primary.lower(),
                    "biopsia visible",
                    primary,
                    severity="critical",
                    message="MRI/PSAD altos o reapertura posbiopsia benigna deben hacer visible la biopsia.",
                )
            )
    if vertical == "localized_surveillance_first":
        track = _text(bundle.get("localized_track"))
        primary = _text((bundle.get("rule_based_recommendation") or {}).get("recommended_action"))
        preferred = _text((bundle.get("preferred_local_strategy") or {}).get("label") or (bundle.get("preferred_local_strategy") or {}).get("name"))
        upgrade_detected = str(values.get("upgrade_detected", "")).strip().lower() in {"1", "true", "yes", "si", "sí"}
        if track == "stable_active_surveillance":
            assertions.append(
                _assertion(
                    "localized_stable_as_keeps_surveillance_visible",
                    any(_contains(primary, token) for token in ("surveillance", "vigil", "seguimiento")) or "surveillance" in preferred.lower(),
                    "vigilancia activa visible",
                    {"recommended_action": primary, "preferred_strategy": preferred},
                    severity="critical",
                    message="La vigilancia activa estable debe seguir visible como conducta longitudinal.",
                )
            )
        if track == "as_exit_due_to_upgrade" or upgrade_detected:
            assertions.append(
                _assertion(
                    "localized_upgrade_exits_as",
                    "surveillance" not in preferred.lower(),
                    "Salida de AS",
                    preferred,
                    severity="critical",
                    message="El upgrade histológico o de carga no debe dejar AS como estrategia preferente visible.",
                )
            )
    if vertical == "post_rt_salvage_first":
        window = _text(bundle.get("post_rt_salvage_window_status"))
        local_path = dict(bundle.get("local_salvage_pathway") or {})
        psma_stage = _text(values.get("psma_stage_after_psma"))
        conventional_stage = _text(values.get("conventional_imaging_status"))
        if psma_stage in {"M1a", "M1b", "M1c"} or conventional_stage in {"M1", "M1A", "M1B", "M1C"}:
            assertions.append(
                _assertion(
                    "post_rt_disseminated_pattern_redirects_systemic",
                    window == "redirect_systemic" and not bool(local_path.get("visible")),
                    "redirect_systemic + sin rescate local visible",
                    {"window": window, "local_salvage_visible": bool(local_path.get("visible"))},
                    severity="critical",
                    message="El patrón diseminado post-RT debe bloquear rescate local aislado.",
                )
            )
        elif window == "local_salvage_candidate":
            assertions.append(
                _assertion(
                    "post_rt_local_pattern_keeps_salvage_visible",
                    bool(local_path.get("visible")),
                    True,
                    local_path.get("visible"),
                    severity="critical",
                    message="La recurrencia post-RT local/pélvica debe mantener visible el rescate local.",
                )
            )
    return assertions


def _build_bundle_contract_assertions(snapshot: dict[str, Any], *, vertical: str) -> list[dict[str, Any]]:
    bundle_map = dict(snapshot.get("longitudinal_bundle") or {})
    if vertical == "mhspc_first":
        bundle = dict(bundle_map.get("mhspc_copilot_bundle") or {})
        if not bundle.get("available"):
            return [_assertion("mhspc_bundle_available", False, True, False, severity="critical", message="La vertical mHSPC debe exponer un bundle visible durante la auditoría.")]
        return _required_contract_assertions(bundle, required_keys=MHSPC_REQUIRED_KEYS, prefix="mhspc_bundle")
    if vertical == "diagnostic_to_biopsy_first":
        bundle = dict(bundle_map.get("diagnostic_biopsy_bundle") or {})
        if not bundle.get("available"):
            return [_assertion("diagnostic_bundle_available", False, True, False, severity="critical", message="La vertical diagnóstica debe exponer un bundle visible durante la auditoría.")]
        return _required_contract_assertions(bundle, required_keys=DIAGNOSTIC_REQUIRED_KEYS, prefix="diagnostic_bundle")
    if vertical == "localized_surveillance_first":
        bundle = dict(bundle_map.get("localized_surveillance_bundle") or {})
        if not bundle.get("available"):
            return [_assertion("localized_bundle_available", False, True, False, severity="critical", message="La vertical localizada debe exponer un bundle visible durante la auditoría.")]
        return _required_contract_assertions(bundle, required_keys=LOCALIZED_REQUIRED_KEYS, prefix="localized_bundle")
    if vertical == "post_rt_salvage_first":
        bundle = dict(bundle_map.get("post_rt_salvage_bundle") or {})
        if not bundle.get("available"):
            return [_assertion("post_rt_bundle_available", False, True, False, severity="critical", message="La vertical post-RT debe exponer un bundle visible durante la auditoría.")]
        return _required_contract_assertions(bundle, required_keys=POST_RT_REQUIRED_KEYS, prefix="post_rt_bundle")
    if vertical == "crpc_first":
        bundle = dict(bundle_map.get("crpc_copilot_bundle") or {})
        if not bundle.get("available"):
            return [_assertion("crpc_bundle_available", False, True, False, severity="critical", message="La vertical CRPC debe exponer un bundle visible durante la auditoría.")]
        return _required_contract_assertions(bundle, required_keys=CRPC_REQUIRED_KEYS, prefix="crpc_bundle")
    if vertical == "post_rp_salvage_first":
        bundle = dict(bundle_map.get("post_rp_salvage_bundle") or {})
        if not bundle.get("available"):
            return [_assertion("post_rp_bundle_available", False, True, False, severity="critical", message="La vertical post-RP debe exponer un bundle visible durante la auditoría.")]
        return _required_contract_assertions(bundle, required_keys=POST_RP_REQUIRED_KEYS, prefix="post_rp_bundle")
    return []


def _bundle_for_vertical(snapshot: dict[str, Any], vertical: str) -> dict[str, Any]:
    longitudinal_bundle = dict(snapshot.get("longitudinal_bundle") or {})
    if vertical == "mhspc_first":
        return dict(longitudinal_bundle.get("mhspc_copilot_bundle") or {})
    if vertical == "diagnostic_to_biopsy_first":
        return dict(longitudinal_bundle.get("diagnostic_biopsy_bundle") or {})
    if vertical == "localized_surveillance_first":
        return dict(longitudinal_bundle.get("localized_surveillance_bundle") or {})
    if vertical == "post_rt_salvage_first":
        return dict(longitudinal_bundle.get("post_rt_salvage_bundle") or {})
    if vertical == "crpc_first":
        return dict(longitudinal_bundle.get("crpc_copilot_bundle") or {})
    if vertical == "post_rp_salvage_first":
        return dict(longitudinal_bundle.get("post_rp_salvage_bundle") or {})
    return {}


def _pick_live_patients(limit_per_vertical: int, *, base_url: str) -> list[dict[str, Any]]:
    conn = tracking_db._connect()
    conn.row_factory = tracking_db.sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        """
        WITH latest_assessment AS (
            SELECT ca.patient_id, ca.state
            FROM clinical_assessments ca
            INNER JOIN (
                SELECT patient_id, MAX(id) AS max_id
                FROM clinical_assessments
                GROUP BY patient_id
            ) latest
                ON latest.max_id = ca.id
        )
        SELECT
            pi.id,
            pi.nss,
            pi.full_name,
            COALESCE(la.state, pch.current_state, '') AS current_state
        FROM patient_identity pi
        LEFT JOIN latest_assessment la ON la.patient_id = pi.id
        LEFT JOIN prior_clinical_history pch ON pch.patient_id = pi.id
        ORDER BY pi.id DESC
        """
    )
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        snapshot = capture_patient_validation_snapshot(int(row.get("id")), base_url=base_url)
        vertical = _vertical_from_snapshot(snapshot)
        if vertical == "other":
            continue
        enriched_row = {**row, "_prefetched_snapshot": snapshot, "selected_vertical": vertical}
        grouped[vertical].append(enriched_row)
        if all(len(grouped.get(vertical_name, [])) >= limit_per_vertical for vertical_name in REPRESENTATIVE_SCENARIOS):
            break
    selected: list[dict[str, Any]] = []
    for vertical in REPRESENTATIVE_SCENARIOS:
        selected.extend(grouped.get(vertical, [])[:limit_per_vertical])
    return selected


def _seed_missing_live_samples(
    selected_rows: list[dict[str, Any]],
    *,
    base_url: str,
    limit_per_vertical: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected_by_vertical = Counter(str(row.get("selected_vertical") or _vertical_from_family(_latest_state_from_row(row))) for row in selected_rows)
    selected = list(selected_rows)
    seeded_cases: list[dict[str, Any]] = []
    trajectory_map = _representative_trajectory_map()
    for vertical, scenario_ids in REPRESENTATIVE_SCENARIOS.items():
        if selected_by_vertical.get(vertical, 0) >= limit_per_vertical:
            continue
        for scenario_id in scenario_ids:
            trajectory = trajectory_map.get(scenario_id)
            if not trajectory:
                continue
            try:
                condensed_payload = dict(trajectory.get("baseline_payload") or {})
                first_visit = dict((trajectory.get("visits") or [{}])[0] or {})
                condensed_payload.update(dict(first_visit.get("payload") or {}))
                condensed_trajectory = {
                    **dict(trajectory),
                    "baseline_payload": condensed_payload,
                    "baseline_oracle": trajectory.get("clinical_oracle", trajectory.get("baseline_oracle", {})),
                    "visits": [],
                }
                case = seed_trajectory_case(
                    condensed_trajectory,
                    run_id=f"liveaudit-{vertical}",
                    case_index=len(seeded_cases) + 1,
                    base_url=base_url,
                )
            except Exception:
                continue
            patient_id = int(case.get("patient_id"))
            selected.append(
                {
                    "id": patient_id,
                    "nss": case.get("patient_nss"),
                    "full_name": case.get("title"),
                    "current_state": case.get("scenario_family"),
                    "seeded_for_audit": True,
                    "selected_vertical": vertical,
                }
            )
            seeded_cases.append(case)
            selected_by_vertical[vertical] += 1
            if selected_by_vertical.get(vertical, 0) >= limit_per_vertical:
                break
    return selected, seeded_cases


def _fetch_json(client: Any, method: str, path: str, *, json_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if method == "POST":
        response = client.post(path, json=json_payload or {})
    else:
        response = client.get(path)
    payload = response.get_json(silent=True) or {}
    return {
        "status_code": response.status_code,
        "payload": payload,
    }


def _api_contract_assertions(
    patient_ref: str,
    snapshot: dict[str, Any],
    *,
    client: Any,
    vertical: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    signals = _fetch_json(client, "GET", f"/api/patients/{patient_ref}/signals")
    schedule = _fetch_json(client, "GET", f"/api/patients/{patient_ref}/schedule")
    full_assessment = _fetch_json(client, "POST", f"/api/ai/full-assessment/{patient_ref}")
    copilot_path = {
        "mhspc_first": "/api/mhspc-copilot",
        "diagnostic_to_biopsy_first": "/api/diagnostic-copilot",
        "localized_surveillance_first": "/api/localized-copilot",
        "post_rt_salvage_first": "/api/post-rt-copilot",
        "crpc_first": "/api/crpc-copilot",
        "post_rp_salvage_first": "/api/post-rp-copilot",
    }.get(vertical, "/api/crpc-copilot")
    copilot = _fetch_json(client, "GET", f"{copilot_path}/{patient_ref}")
    bundle = _bundle_for_vertical(snapshot, vertical)
    assertions = [
        _assertion("signals_status_code", signals["status_code"] == 200, 200, signals["status_code"], severity="critical"),
        _assertion("schedule_status_code", schedule["status_code"] == 200, 200, schedule["status_code"], severity="critical"),
        _assertion("full_assessment_status_code", full_assessment["status_code"] == 200, 200, full_assessment["status_code"], severity="critical"),
        _assertion("copilot_status_code", copilot["status_code"] == 200, 200, copilot["status_code"], severity="critical"),
    ]
    if all(item["passed"] for item in assertions):
        signals_payload = dict(signals["payload"] or {})
        schedule_payload = dict(schedule["payload"] or {})
        assessment_payload = dict(full_assessment["payload"] or {})
        copilot_payload = dict(copilot["payload"] or {})
        copilot_bundle_key = {
            "mhspc_first": "mhspc_decision_bundle",
            "diagnostic_to_biopsy_first": "diagnostic_decision_bundle",
            "localized_surveillance_first": "localized_decision_bundle",
            "post_rt_salvage_first": "post_rt_decision_bundle",
            "crpc_first": "crpc_decision_bundle",
            "post_rp_salvage_first": "post_rp_decision_bundle",
        }.get(vertical, "crpc_decision_bundle")
        endpoint_bundle = dict(copilot_payload.get(copilot_bundle_key) or {})
        expected_state = _text(bundle.get("effective_state"))
        assertions.extend(
            [
                _assertion(
                    "signals_matches_bundle_state",
                    _text(signals_payload.get("effective_state_final") or signals_payload.get("effective_state")) == expected_state,
                    expected_state,
                    signals_payload.get("effective_state_final") or signals_payload.get("effective_state"),
                    severity="critical",
                    message="Signals debe reflejar la misma verdad longitudinal que el bundle del copiloto.",
                ),
                _assertion(
                    "schedule_matches_bundle_state",
                    _text(schedule_payload.get("schedule_state")) == expected_state,
                    expected_state,
                    schedule_payload.get("schedule_state"),
                    severity="critical",
                    message="Schedule debe anclarse al mismo estado efectivo del bundle.",
                ),
                _assertion(
                    "full_assessment_final_matches_bundle",
                    _text(((assessment_payload.get("final_presented_recommendation") or {}).get("recommended_action")))
                    == _text(((bundle.get("final_presented_recommendation") or {}).get("recommended_action"))),
                    (bundle.get("final_presented_recommendation") or {}).get("recommended_action"),
                    (assessment_payload.get("final_presented_recommendation") or {}).get("recommended_action"),
                    severity="critical",
                    message="Full assessment debe publicar la misma recomendación final visible que el bundle longitudinal.",
                ),
                _assertion(
                    "copilot_endpoint_matches_bundle_status",
                    _text(endpoint_bundle.get("status")) == _text(bundle.get("status")),
                    bundle.get("status"),
                    endpoint_bundle.get("status"),
                    severity="critical",
                    message="El endpoint del copiloto debe devolver el mismo estado visible que el bundle longitudinal.",
                ),
            ]
        )
    return assertions, {
        "signals": signals,
        "schedule": schedule,
        "full_assessment": full_assessment,
        "copilot": copilot,
    }


def _coalesce_case_status(assertions: list[dict[str, Any]], ui_contradictions: list[dict[str, Any]]) -> tuple[str, bool]:
    critical_failure = any((not item.get("passed")) and item.get("severity") == "critical" for item in assertions)
    passed = all(item.get("passed") for item in assertions) and not ui_contradictions
    return ("passed" if passed else "failed"), critical_failure


def _case_from_seed_result(case_payload: dict[str, Any], case_result: dict[str, Any]) -> dict[str, Any]:
    snapshot = dict(case_payload.get("final") or {})
    vertical = _vertical_from_family(str(case_payload.get("scenario_family") or ""))
    bundle = _bundle_for_vertical(snapshot, vertical)
    extra_assertions = _build_bundle_contract_assertions(snapshot, vertical=vertical) + _build_treatment_assertions(snapshot, bundle=bundle, vertical=vertical)
    ui_contradictions = list(case_result.get("ui_contradictions") or [])
    all_assertions = list(case_result.get("assertions") or []) + extra_assertions
    case_status, critical_failure = _coalesce_case_status(all_assertions, ui_contradictions)
    return {
        **dict(case_result),
        "cohort": "seeded",
        "vertical": vertical,
        "top_treatments": _top_treatments(bundle),
        "bundle_contract_assertions": extra_assertions,
        "api_contract_assertions": [],
        "assertions": all_assertions,
        "case_status": case_status,
        "critical_failure": critical_failure,
        "actual": {
            **dict(case_result.get("actual") or {}),
            "top_treatments": _top_treatments(bundle),
        },
    }


def _seed_error_case(case_payload: dict[str, Any]) -> dict[str, Any]:
    message = _text(case_payload.get("seed_error") or "No se pudo sembrar el caso.")
    return {
        "case_key": case_payload.get("case_key"),
        "scenario_id": case_payload.get("scenario_id"),
        "scenario_family": case_payload.get("scenario_family"),
        "title": case_payload.get("title"),
        "patient_id": case_payload.get("patient_id"),
        "patient_nss": case_payload.get("patient_nss", ""),
        "cohort": "seeded",
        "vertical": _vertical_from_family(str(case_payload.get("scenario_family") or "")),
        "expected": {
            "baseline_oracle": case_payload.get("baseline_oracle", {}),
            "clinical_oracle": case_payload.get("clinical_oracle", {}),
            "guideline_oracle": case_payload.get("guideline_oracle", {}),
        },
        "actual": {
            "effective_state": "",
            "effective_management_track": "",
            "next_best_action": {},
            "guideline_basis": [],
            "blocking_inputs": [],
            "active_alert_titles": [],
            "top_treatments": [],
        },
        "assertions": [
            _assertion(
                "seed_case_execution",
                False,
                "case seeded successfully",
                message,
                severity="critical",
                message="La auditoría no pudo sembrar este caso del catálogo.",
            )
        ],
        "visit_reports": [],
        "case_status": "failed",
        "critical_failure": True,
        "ui_contradictions": [],
        "guideline_concordance_pct": 0.0,
        "missing_input_prompt_accuracy": 0.0,
        "data_accumulation_complete": False,
        "visual_artifacts": [],
        "profile_url": "",
        "signals_url": "",
        "schedule_url": "",
        "decision_trace_url": "",
        "top_treatments": [],
        "bundle_contract_assertions": [],
        "api_contract_assertions": [],
    }


def _live_case_payload(row: dict[str, Any], *, base_url: str) -> dict[str, Any]:
    patient_id = int(row.get("id"))
    snapshot = dict(row.get("_prefetched_snapshot") or {}) or capture_patient_validation_snapshot(patient_id, base_url=base_url)
    vertical = _vertical_from_snapshot(snapshot)
    bundle = _bundle_for_vertical(snapshot, vertical)
    actual = {
        "effective_state": _text((snapshot.get("signals") or {}).get("effective_state")),
        "effective_management_track": _text((snapshot.get("signals") or {}).get("effective_management_track")),
        "next_best_action": dict(snapshot.get("next_best_action") or {}),
        "guideline_basis": list((snapshot.get("schedule") or {}).get("master_followup_plan", {}).get("guideline_basis") or (snapshot.get("signals") or {}).get("guideline_basis") or []),
        "blocking_inputs": list((snapshot.get("signals") or {}).get("blocking_inputs") or []),
        "active_alert_titles": [
            _text(item.get("title") or item.get("label") or item.get("description"))
            for item in list((snapshot.get("labs") or {}).get("active_alerts") or [])
        ],
        "top_treatments": _top_treatments(bundle),
    }
    return {
        "case_key": f"current_db:{patient_id}:{vertical}",
        "scenario_id": _text(row.get("current_state")),
        "scenario_family": _text(row.get("current_state")),
        "title": _text(row.get("full_name") or row.get("nss") or f"Paciente {patient_id}"),
        "patient_id": patient_id,
        "patient_nss": _text(row.get("nss")),
        "cohort": "current_db",
        "vertical": vertical,
        "actual": actual,
        "profile_url": ((snapshot.get("urls") or {}).get("profile") or ""),
        "signals_url": ((snapshot.get("urls") or {}).get("signals") or ""),
        "schedule_url": ((snapshot.get("urls") or {}).get("schedule") or ""),
        "decision_trace_url": ((snapshot.get("urls") or {}).get("decision_trace") or ""),
        "snapshot": snapshot,
    }


def _enrich_live_case(case_payload: dict[str, Any], *, client: Any) -> dict[str, Any]:
    snapshot = dict(case_payload.get("snapshot") or {})
    vertical = str(case_payload.get("vertical") or "")
    bundle = _bundle_for_vertical(snapshot, vertical)
    patient_ref = _text(case_payload.get("patient_nss") or case_payload.get("patient_id"))
    bundle_assertions = _build_bundle_contract_assertions(snapshot, vertical=vertical)
    treatment_assertions = _build_treatment_assertions(snapshot, bundle=bundle, vertical=vertical)
    api_assertions, api_payloads = _api_contract_assertions(patient_ref, snapshot, client=client, vertical=vertical)
    all_assertions = bundle_assertions + treatment_assertions + api_assertions
    case_status, critical_failure = _coalesce_case_status(all_assertions, [])
    return {
        **dict(case_payload),
        "top_treatments": _top_treatments(bundle),
        "bundle_contract_assertions": bundle_assertions,
        "treatment_assertions": treatment_assertions,
        "api_contract_assertions": api_assertions,
        "api_payloads": api_payloads,
        "assertions": all_assertions,
        "case_status": case_status,
        "critical_failure": critical_failure,
    }


def _findings_from_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    priority_map = {"critical": 0, "high": 1, "normal": 2}
    for case in cases:
        for item in list(case.get("assertions") or []):
            if item.get("passed"):
                continue
            severity = item.get("severity") or "normal"
            findings.append(
                {
                    "priority": priority_map.get(severity, 2),
                    "severity": severity,
                    "cohort": case.get("cohort"),
                    "vertical": case.get("vertical"),
                    "case_key": case.get("case_key"),
                    "patient_ref": case.get("patient_nss") or case.get("patient_id"),
                    "title": item.get("message") or item.get("key"),
                    "details": {
                        "expected": item.get("expected"),
                        "actual": item.get("actual"),
                        "assertion_key": item.get("key"),
                    },
                }
            )
        for contradiction in list(case.get("ui_contradictions") or []):
            findings.append(
                {
                    "priority": priority_map.get(str(contradiction.get("severity") or "critical"), 0),
                    "severity": contradiction.get("severity", "critical"),
                    "cohort": case.get("cohort"),
                    "vertical": case.get("vertical"),
                    "case_key": case.get("case_key"),
                    "patient_ref": case.get("patient_nss") or case.get("patient_id"),
                    "title": contradiction.get("title") or contradiction.get("key"),
                    "details": contradiction,
                }
            )
    findings.sort(key=lambda item: (item["priority"], str(item.get("cohort")), str(item.get("case_key"))))
    return findings


def _build_summary(cases: list[dict[str, Any]], *, seeded_live_samples: int = 0) -> dict[str, Any]:
    total = len(cases)
    passed = sum(1 for item in cases if item.get("case_status") == "passed")
    failed = total - passed
    critical_failures = sum(1 for item in cases if item.get("critical_failure"))
    ui_contradictions = sum(len(item.get("ui_contradictions") or []) for item in cases)
    by_vertical = Counter(str(item.get("vertical") or "") for item in cases)
    return {
        "total_cases": total,
        "passed": passed,
        "failed": failed,
        "critical_failures": critical_failures,
        "ui_contradictions": ui_contradictions,
        "vertical_distribution": dict(by_vertical),
        "seeded_live_samples": seeded_live_samples,
    }


def _build_live_coverage(cases: list[dict[str, Any]]) -> dict[str, int]:
    coverage = Counter()
    for item in cases:
        coverage[str(item.get("vertical") or "")] += 1
    return dict(coverage)


def _build_client(app: Any | None = None) -> Any:
    if app is not None:
        return app.test_client()
    from app import create_app

    db_path = tracking_db.get_db_path()
    flask_app = create_app(
        {
            "TESTING": True,
            "LOAD_MODEL": False,
            "DB_PATH": str(db_path),
        }
    )
    return flask_app.test_client()


def run_vertical_verification(
    *,
    app: Any | None = None,
    base_url: str = DEFAULT_BASE_URL,
    visual_mode: str = "textual",
    live_limit_per_vertical: int = 2,
    seed_live_samples_when_missing: bool = False,
) -> dict[str, Any]:
    generated_at = datetime.now(UTC).isoformat()
    trajectories = _filtered_trajectories()
    with _temporary_vertical_flags():
        seeded_payload = _seed_vertical_cohort_safely(
            trajectories,
            base_url=base_url,
        )
        seeded_case_map = _build_seeded_case_map(seeded_payload)
        evaluable_seed_payload = {
            **dict(seeded_payload),
            "cases": [item for item in list(seeded_payload.get("cases") or []) if not item.get("seed_error")],
        }
        seeded_evaluated = [
            _case_from_seed_result(seeded_case_map[str(item.get("case_key") or "")], item)
            for item in evaluate_validation_seed(evaluable_seed_payload)
        ]
        seeded_evaluated.extend(
            _seed_error_case(case_payload)
            for case_payload in list(seeded_payload.get("cases") or [])
            if case_payload.get("seed_error")
        )

        live_rows = _pick_live_patients(live_limit_per_vertical, base_url=base_url)
        seeded_live_cases: list[dict[str, Any]] = []
        if seed_live_samples_when_missing:
            live_rows, seeded_live_cases = _seed_missing_live_samples(
                live_rows,
                base_url=base_url,
                limit_per_vertical=live_limit_per_vertical,
            )

        live_case_payloads = [_live_case_payload(row, base_url=base_url) for row in live_rows]
        with _build_client(app) as client:
            live_cases = [_enrich_live_case(item, client=client) for item in live_case_payloads]
        live_cases = attach_visual_artifacts(live_cases, visual_mode=visual_mode)
        for case in live_cases:
            case_status, critical_failure = _coalesce_case_status(
                list(case.get("assertions") or []) + list(case.get("dom_assertions") or []),
                list(case.get("ui_contradictions") or []),
            )
            case["assertions"] = list(case.get("assertions") or []) + list(case.get("dom_assertions") or [])
            case["case_status"] = case_status
            case["critical_failure"] = critical_failure

    report = {
        "generated_at": generated_at,
        "base_url": base_url,
        "visual_mode": visual_mode,
        "target_scenario_families": list(TARGET_SCENARIO_FAMILIES),
        "seeded": {
            "run_id": seeded_payload.get("run_id"),
            "summary": _build_summary(seeded_evaluated),
            "cases": seeded_evaluated,
        },
        "current_db": {
            "summary": {
                **_build_summary(live_cases, seeded_live_samples=len(seeded_live_cases)),
                "sample_coverage": _build_live_coverage(live_cases),
                "seeded_sample_scenarios": [item.get("scenario_id") for item in seeded_live_cases],
            },
            "cases": live_cases,
        },
    }
    report["findings"] = _findings_from_cases(seeded_evaluated + live_cases)
    report["summary"] = {
        "seeded": report["seeded"]["summary"],
        "current_db": report["current_db"]["summary"],
        "total_findings": len(report["findings"]),
    }
    return report


__all__ = ["run_vertical_verification"]
