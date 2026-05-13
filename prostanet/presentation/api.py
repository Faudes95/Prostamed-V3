from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request
import tracking_db

from prostanet.application.module_registry import ModuleRegistry
from prostanet.domains.clinical_assessments.service import ClinicalAssessmentService
from prostanet.domains.clinical_assessments.scenario_harness import run_scenario_harness
from prostanet.domains.clinical_validation import (
    DEFAULT_BASE_URL as VALIDATION_DEFAULT_BASE_URL,
    list_trajectory_summaries,
    run_longitudinal_validation,
    run_vertical_verification,
)
from prostanet.domains.clinical_validation.repository import (
    get_validation_case,
    get_validation_report,
    get_validation_run,
    list_validation_runs,
    save_validation_run_report,
)
from prostanet.domains.patient_tracking.service import PatientTrackingService
from prostanet.shared.converters import safe_bool, safe_float, safe_int
from prostanet.shared.presentation_text import (
    humanize_assessment,
    humanize_care_overlays,
    humanize_evidence,
    humanize_guidelines,
    humanize_module_listing,
    humanize_registration_context,
    humanize_result,
    humanize_schema,
    humanize_sources,
    humanize_state_timeline,
)
from prostanet.domains.research_intelligence.comparative_effectiveness import (
    run_propensity_analysis,
)
from prostanet.domains.research_intelligence.consent_governance import (
    create_consent_draft,
    finalize_consent_draft_payload,
    get_consent_draft_payload,
    get_current_consent_payload,
    sign_consent_draft_payload,
)
from prostanet.domains.research_intelligence.dynamic_cohorting import (
    create_dynamic_cohort,
    get_dynamic_cohort_payload,
    list_dynamic_cohort_payload,
)
from prostanet.domains.research_intelligence.institutional_benchmarking import (
    build_institutional_benchmark_payload,
)
from prostanet.domains.research_intelligence.multivariate_analysis import (
    build_cox_payload,
    build_logistic_payload,
)
from prostanet.domains.research_intelligence.operational_outcomes import (
    build_operational_outcomes_payload,
)
from prostanet.domains.research_intelligence.quality_indicators import (
    build_quality_indicator_payload,
)
from prostanet.domains.research_intelligence.research_exports import (
    build_cdisc_mapping_payload,
    build_csv_export_payload,
    build_redcap_export_payload,
)
from prostanet.domains.research_intelligence.survival_registry import (
    build_survival_registry_payload,
)


modular_api = Blueprint("modular_api", __name__)
registry = ModuleRegistry()
assessment_service = ClinicalAssessmentService()
tracking_service = PatientTrackingService()


def _parse_json() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError("Se requiere un cuerpo JSON valido.")
    return data


def _coerce_payload(payload: dict, schema: dict) -> dict:
    coerced = dict(payload)
    for field in schema.get("fields", []):
        name = field["name"]
        value = coerced.get(name)
        if value in (None, ""):
            continue
        text = str(value)
        if field.get("field_type") == "number":
            coerced[name] = float(text) if "." in text else int(float(text))
            continue
        if field.get("field_type") == "select":
            try:
                numeric = float(text)
            except (TypeError, ValueError):
                continue
            coerced[name] = numeric if "." in text else int(numeric)
    return coerced


def _validated_bool(value, field_name: str, *, default=None):
    parsed = safe_bool(value, default=default)
    if value not in (None, "") and parsed is None:
        raise ValueError(f"Valor no válido para '{field_name}'. Use true/false, 1/0, si/no o yes/no.")
    return parsed


def _serialize_alerts(alerts):
    """Acepta tanto ClinicalAlert como dicts ya serializados."""
    serialized = []
    for alert in alerts or []:
        if isinstance(alert, dict):
            serialized.append(alert)
        elif hasattr(alert, "to_dict"):
            serialized.append(alert.to_dict())
        elif hasattr(alert, "__dict__"):
            serialized.append(dict(alert.__dict__))
        else:
            serialized.append({"value": alert})
    return serialized


def _resolve_patient_api_ref(patient_ref: str):
    resolved = tracking_db.resolve_patient_ref(patient_ref)
    if not resolved:
        return None, (jsonify({"success": False, "error": "Paciente no encontrado."}), 404)
    return resolved, None


@modular_api.route("/api/state-classifier", methods=["POST"])
def state_classifier() -> tuple:
    try:
        payload = _coerce_payload(_parse_json(), registry.get_state_classifier_schema())
        result = registry.classify_state(payload)
        result["state_label"] = humanize_module_listing({"module": result["state"], "title": result["state"], "core_questions": []})["title"]
        return jsonify({"success": True, **result})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except KeyError:
        return jsonify({"success": False, "error": "Modulo no soportado."}), 404
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/modules", methods=["GET"])
def list_modules() -> tuple:
    modules = [humanize_module_listing(module) for module in registry.list_modules()]
    return jsonify({"success": True, "modules": modules})


@modular_api.route("/api/modules/state-classifier/schema", methods=["GET"])
def state_classifier_schema() -> tuple:
    return jsonify({"success": True, "schema": humanize_schema(registry.get_state_classifier_schema())})


@modular_api.route("/api/modules/<module_id>/schema", methods=["GET"])
def module_schema(module_id: str) -> tuple:
    try:
        return jsonify({"success": True, "schema": humanize_schema(registry.get_module_schema(module_id))})
    except KeyError:
        return jsonify({"success": False, "error": "Modulo no soportado."}), 404


@modular_api.route("/api/modules/<module_id>/evaluate", methods=["POST"])
def evaluate_module(module_id: str) -> tuple:
    try:
        schema = registry.get_module_schema(module_id)
        payload = _coerce_payload(_parse_json(), schema)
        return jsonify({"success": True, "result": humanize_result(registry.evaluate_module(module_id, payload))})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except KeyError:
        return jsonify({"success": False, "error": "Modulo no soportado."}), 404
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/clinical-assessments/draft", methods=["POST"])
def create_clinical_assessment_draft() -> tuple:
    try:
        data = _parse_json()
        module_id = str(data.get("module_id", "")).strip()
        if not module_id:
            raise ValueError("Se requiere el identificador del módulo clínico.")

        schema = registry.get_module_schema(module_id)
        payload = _coerce_payload(data.get("payload", {}), schema)
        result = registry.evaluate_module(module_id, payload)
        assessment_id = assessment_service.create_draft(
            module_id=module_id,
            state=result["state"],
            input_snapshot=payload,
            result_snapshot=result,
            guideline_versions=registry.get_guidelines_metadata(),
        )
        if assessment_id is None:
            raise RuntimeError("No se pudo crear el borrador de evaluación clínica.")

        assessment = assessment_service.get_draft(assessment_id)
        registration_context = tracking_service.build_registration_context(
            module_schema=schema,
            module_id=module_id,
            state=result["state"],
            assessment_input=payload,
        )

        return jsonify(
            {
                "success": True,
                "assessment_id": assessment_id,
                "assessment": humanize_assessment(assessment) if assessment else None,
                "result": humanize_result(result),
                **humanize_registration_context(registration_context),
            }
        )
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except KeyError:
        return jsonify({"success": False, "error": "Modulo no soportado."}), 404
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/clinical-assessments/<int:assessment_id>", methods=["GET"])
def get_clinical_assessment_draft(assessment_id: int) -> tuple:
    assessment = assessment_service.get_draft(assessment_id)
    if not assessment:
        return jsonify({"success": False, "error": "Evaluación clínica no encontrada."}), 404
    module_id = assessment.get("module_id", "")
    schema = registry.get_module_schema(module_id) if module_id else {"fields": []}
    registration_context = tracking_service.build_registration_context(
        module_schema=schema,
        module_id=module_id,
        state=assessment.get("state", ""),
        assessment_input=assessment.get("input_snapshot", {}) or {},
        assessment_result=assessment.get("result_snapshot", {}) or {},
    )
    return jsonify(
        {
            "success": True,
            "assessment": humanize_assessment(assessment),
            **humanize_registration_context(registration_context),
        }
    )


@modular_api.route("/api/modules/<module_id>/evidence", methods=["GET"])
def module_evidence(module_id: str) -> tuple:
    try:
        return jsonify({"success": True, "evidence": humanize_evidence(registry.get_module_evidence(module_id))})
    except KeyError:
        return jsonify({"success": False, "error": "Modulo no soportado."}), 404


@modular_api.route("/api/modules/<module_id>/sources", methods=["GET"])
def module_sources(module_id: str) -> tuple:
    try:
        return jsonify({"success": True, "sources": humanize_sources(registry.get_module_sources(module_id))})
    except KeyError:
        return jsonify({"success": False, "error": "Modulo no soportado."}), 404


@modular_api.route("/api/guidelines/metadata", methods=["GET"])
def guideline_metadata() -> tuple:
    return jsonify({"success": True, "guidelines": humanize_guidelines(registry.get_guidelines_metadata())})


@modular_api.route("/api/clinical-calibration", methods=["GET"])
def clinical_calibration() -> tuple:
    summary = run_scenario_harness(registry)
    return jsonify({"success": True, "calibration": summary})


@modular_api.route("/api/validation/trajectories", methods=["GET"])
def validation_trajectories() -> tuple:
    trajectories = list_trajectory_summaries()
    family_counts: dict[str, int] = {}
    for item in trajectories:
        family = str(item.get("scenario_family") or "")
        family_counts[family] = family_counts.get(family, 0) + 1
    return jsonify(
        {
            "success": True,
            "total_trajectories": len(trajectories),
            "family_counts": family_counts,
            "trajectories": trajectories,
            "recent_runs": list_validation_runs(limit=5),
        }
    )


@modular_api.route("/api/validation/run", methods=["POST"])
def validation_run() -> tuple:
    try:
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            data = {}
        report = run_longitudinal_validation(
            base_url=str(data.get("base_url") or VALIDATION_DEFAULT_BASE_URL),
            cohort_mode=str(data.get("cohort_mode") or "isolated_temp_db"),
            visual_mode=str(data.get("visual_mode") or "playwright_real"),
        )
        save_validation_run_report(report)
        return jsonify({"success": True, **report})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/validation/run/<run_id>", methods=["GET"])
def validation_run_detail(run_id: str) -> tuple:
    payload = get_validation_run(run_id)
    if not payload:
        return jsonify({"success": False, "error": "Corrida de validación no encontrada."}), 404
    return jsonify({"success": True, "run": payload, "report": get_validation_report(run_id)})


@modular_api.route("/api/validation/run/<run_id>/cases/<case_id>", methods=["GET"])
def validation_run_case(run_id: str, case_id: str) -> tuple:
    payload = get_validation_case(run_id, case_id)
    if not payload:
        return jsonify({"success": False, "error": "Caso de validación no encontrado."}), 404
    return jsonify({"success": True, "case": payload})


@modular_api.route("/api/validation/run/<run_id>/report", methods=["GET"])
def validation_run_report(run_id: str) -> tuple:
    payload = get_validation_report(run_id)
    if not payload:
        return jsonify({"success": False, "error": "Reporte de validación no encontrado."}), 404
    return jsonify({"success": True, "report": payload})


@modular_api.route("/api/validation/vertical-audit", methods=["POST"])
def validation_vertical_audit() -> tuple:
    try:
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            data = {}
        report = run_vertical_verification(
            app=current_app._get_current_object(),
            base_url=str(data.get("base_url") or VALIDATION_DEFAULT_BASE_URL),
            visual_mode=str(data.get("visual_mode") or "textual"),
            live_limit_per_vertical=int(data.get("live_limit_per_vertical") or 2),
            seed_live_samples_when_missing=bool(safe_bool(data.get("seed_live_samples_when_missing"), default=False)),
        )
        return jsonify({"success": True, "report": report})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<nss>/state-timeline", methods=["GET"])
def patient_state_timeline(nss: str) -> tuple:
    from tracking_db import get_patient_state_timeline

    timeline = get_patient_state_timeline(nss)
    if timeline is None:
        return jsonify({"success": False, "error": "Paciente no encontrado."}), 404
    return jsonify({"success": True, "state_timeline": humanize_state_timeline(timeline)})


@modular_api.route("/api/patients/<nss>/recompute-care-plan", methods=["POST"])
def recompute_patient_care_plan_route(nss: str) -> tuple:
    from tracking_db import get_patient_state_timeline, recompute_patient_care_plan

    success, result = recompute_patient_care_plan(nss)
    if not success:
        status = 404 if "no encontrado" in str(result).lower() else 400
        return jsonify({"success": False, "error": str(result)}), status
    assessment = humanize_assessment(result)
    timeline = get_patient_state_timeline(nss) or []
    return jsonify(
        {
            "success": True,
            "assessment": assessment,
            "state_timeline": humanize_state_timeline(timeline),
            "care_overlays": humanize_care_overlays(
                assessment.get("display_result", {}).get("care_overlays", [])
            ),
        }
    )


# ══════════════════════════════════════════════════════════════════════════════
# ══  COPILOTO CLÍNICO — Scheduling, Alertas, Response Assessment
# ══════════════════════════════════════════════════════════════════════════════


@modular_api.route("/api/patients/<patient_ref>/schedule", methods=["GET"])
def patient_schedule(patient_ref: str) -> tuple:
    """Genera el calendario de seguimiento programado para el paciente."""
    import tracking_db
    from prostanet.domains.patient_tracking.reconciled_state import build_reconciled_state
    from prostanet.domains.patient_tracking.vertical_runtime import (
        build_decision_delta_since_last_visit,
        build_evidence_basis_current_visit,
        build_runtime_patient,
        build_runtime_payload,
        build_shared_metastatic_summary,
        derive_display_sequence_summary,
        select_primary_vertical_bundle,
    )

    try:
        resolved, error = _resolve_patient_api_ref(patient_ref)
        if error:
            return error
        patient_id = resolved["patient_id"]
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404

        reconciliation = build_reconciled_state(patient, patient.get("latest_assessment"))
        state = reconciliation.get("reconciled_state") or "diagnostic_workup"
        track = request.args.get("track") or reconciliation.get("reconciled_management_track") or "diagnostic_surveillance"

        horizon = int(request.args.get("horizon_months", 12))
        schedule_bundle = tracking_db.sync_scheduled_events(
            patient,
            state=state,
            management_track=track,
            horizon_months=horizon,
        )
        longitudinal_bundle = tracking_db.refresh_longitudinal_intelligence(
            patient_id,
            force_recompute=False,
            record=patient,
            include_live_benchmark=False,
        ) or {}
        latest_result_snapshot = dict((patient.get("latest_assessment") or {}).get("result_snapshot") or {})
        guideline_followup_plan = longitudinal_bundle.get("guideline_followup_plan") or patient.get("guideline_followup_plan", {})
        care_intent_contract = longitudinal_bundle.get("care_intent_contract") or patient.get("care_intent_contract", {})
        transition_resolution = longitudinal_bundle.get("transition_resolution") or patient.get("transition_resolution", {})
        decision_trace = longitudinal_bundle.get("decision_recalculation_trace") or patient.get("decision_recalculation_trace", {})
        latest_decisive_visit = longitudinal_bundle.get("latest_clinically_decisive_visit") or patient.get("latest_clinically_decisive_visit", {})
        decision_input_requirements = longitudinal_bundle.get("decision_input_requirements") or patient.get("decision_input_requirements", {})
        comparative_eligibility_matrix = longitudinal_bundle.get("comparative_eligibility_matrix") or {}
        sequence_transition_bundle = longitudinal_bundle.get("sequence_transition_bundle") or {}
        active_regimen_monitoring_package = longitudinal_bundle.get("active_regimen_monitoring_package") or {}
        palliative_transition_bundle = longitudinal_bundle.get("palliative_transition_bundle") or {}
        palliative_monitoring_package = longitudinal_bundle.get("palliative_monitoring_package") or {}
        crpc_copilot_bundle = longitudinal_bundle.get("crpc_copilot_bundle") or {}
        post_rp_salvage_bundle = longitudinal_bundle.get("post_rp_salvage_bundle") or {}
        mhspc_copilot_bundle = longitudinal_bundle.get("mhspc_copilot_bundle") or {}
        diagnostic_biopsy_bundle = longitudinal_bundle.get("diagnostic_biopsy_bundle") or {}
        localized_surveillance_bundle = longitudinal_bundle.get("localized_surveillance_bundle") or {}
        post_rt_salvage_bundle = longitudinal_bundle.get("post_rt_salvage_bundle") or {}
        _, active_copilot_bundle = select_primary_vertical_bundle(
            {
                "crpc_copilot_bundle": crpc_copilot_bundle,
                "post_rp_salvage_bundle": post_rp_salvage_bundle,
                "mhspc_copilot_bundle": mhspc_copilot_bundle,
                "diagnostic_biopsy_bundle": diagnostic_biopsy_bundle,
                "localized_surveillance_bundle": localized_surveillance_bundle,
                "post_rt_salvage_bundle": post_rt_salvage_bundle,
            }
        )
        qa_passed = (active_copilot_bundle.get("qa_validation") or {}).get("approved")
        sequence_summary = derive_display_sequence_summary(active_copilot_bundle)
        runtime_patient = build_runtime_patient(patient, longitudinal_bundle)
        runtime_payload = build_runtime_payload(
            runtime_patient,
            patient.get("latest_assessment"),
            effective_state=reconciliation.get("reconciled_state", state),
        )
        metastatic_composition_summary = (
            active_copilot_bundle.get("metastatic_composition_summary")
            or build_shared_metastatic_summary(runtime_payload)
        )
        blocked_by_overlay = list(active_copilot_bundle.get("blocked_by_overlay") or [])
        decision_delta_since_last_visit = (
            active_copilot_bundle.get("decision_delta_since_last_visit")
            or build_decision_delta_since_last_visit(
                patient,
                effective_state=reconciliation.get("reconciled_state", state),
                phenotype_state=reconciliation.get("phenotype_state", state),
                rule_based_recommendation=active_copilot_bundle.get("rule_based_recommendation") or {},
                final_presented_recommendation=active_copilot_bundle.get("final_presented_recommendation") or {},
                blocking_groups=active_copilot_bundle.get("blocking_inputs") or [],
                blocked_by_overlay=blocked_by_overlay,
            )
        )
        evidence_basis_current_visit = (
            active_copilot_bundle.get("evidence_basis_current_visit")
            or build_evidence_basis_current_visit(
                active_copilot_bundle.get("guideline_basis")
                or (schedule_bundle.get("master_followup_plan") or {}).get("guideline_basis", []),
                active_copilot_bundle.get("rule_based_recommendation") or {},
                decision_delta_since_last_visit,
            )
        )
        histopathology_summary = active_copilot_bundle.get("histopathology_summary") or ""
        qa_validation = active_copilot_bundle.get("qa_validation") or {}

        return jsonify({
            "success": True,
            "state": schedule_bundle.get("state", state),
            "phenotype_state": reconciliation.get("phenotype_state", state),
            "management_track": schedule_bundle.get("management_track", track),
            "schedule_state": schedule_bundle.get("schedule_state", state),
            "schedule_management_track": schedule_bundle.get("schedule_management_track", track),
            "schedule_override_reason": schedule_bundle.get("schedule_override_reason", ""),
            "reconciled_state": reconciliation.get("reconciled_state", state),
            "state_conflict_flag": reconciliation.get("state_conflict_flag", False),
            "state_conflict_reason": reconciliation.get("state_conflict_reason", ""),
            "progression_gate_active": reconciliation.get("progression_gate_active", False),
            "progression_gate_target": reconciliation.get("progression_gate_target", ""),
            "progression_gate_reason": reconciliation.get("progression_gate_reason", ""),
            "systemic_progression_context_resolved": reconciliation.get("systemic_progression_context_resolved", "none"),
            "anchor_date": schedule_bundle.get("anchor_date", ""),
            "anchor_source": schedule_bundle.get("anchor_source", ""),
            "protocol_trace": schedule_bundle.get("protocol_trace", {}),
            "protocol_label": schedule_bundle.get("protocol_label", ""),
            "schedule": schedule_bundle.get("schedule", []),
            "scheduled_items": schedule_bundle.get("scheduled_items", schedule_bundle.get("schedule", [])),
            "active_schedule": schedule_bundle.get("active_schedule", schedule_bundle.get("schedule", [])),
            "archived_schedule": schedule_bundle.get("archived_schedule", []),
            "scheduled_encounters": schedule_bundle.get("scheduled_encounters", []),
            "encounters": schedule_bundle.get("encounters", []),
            "next_encounter": schedule_bundle.get("next_encounter", {}),
            "master_followup_plan": schedule_bundle.get("master_followup_plan", {}),
            "master_followup_summary": schedule_bundle.get("master_followup_summary", {}),
            "guideline_followup_plan": guideline_followup_plan,
            "transition_resolution": transition_resolution,
            "care_intent_contract": care_intent_contract,
            "next_best_action": longitudinal_bundle.get("next_best_action", {}),
            "decision_recalculation_trace": decision_trace,
            "latest_clinically_decisive_visit": latest_decisive_visit,
            "schedule_primary_intent": guideline_followup_plan.get("schedule_primary_intent", ""),
            "care_intent_key": guideline_followup_plan.get("care_intent_key", ""),
            "action_schedule_consistency": guideline_followup_plan.get("action_schedule_consistency", True),
            "decision_governance_bundle": longitudinal_bundle.get("decision_governance_bundle", {}),
            "recommendation_block_status": longitudinal_bundle.get("recommendation_block_status", ""),
            "recommendation_block_reason": longitudinal_bundle.get("recommendation_block_reason", ""),
            "allowed_actions_while_blocked": longitudinal_bundle.get("allowed_actions_while_blocked", []),
            "decision_blocking_bundle": longitudinal_bundle.get("decision_blocking_bundle", {}),
            "diagnostic_certainty_bundle": longitudinal_bundle.get("diagnostic_certainty_bundle", {}),
            "staging_certainty_bundle": longitudinal_bundle.get("staging_certainty_bundle", {}),
            "minimum_decisive_dataset_bundle": longitudinal_bundle.get("minimum_decisive_dataset_bundle", {}),
            "decision_evidence_currentness_bundle": longitudinal_bundle.get("decision_evidence_currentness_bundle", {}),
            "therapeutic_window_bundle": longitudinal_bundle.get("therapeutic_window_bundle", {}),
            "window_worklist_bundle": longitudinal_bundle.get("window_worklist_bundle", {}),
            "precision_workflow_bundle": longitudinal_bundle.get("precision_workflow_bundle", {}),
            "registry_core_bundle": longitudinal_bundle.get("registry_core_bundle", {}),
            "endpoint_adjudication_bundle": longitudinal_bundle.get("endpoint_adjudication_bundle", {}),
            "data_certainty_bundle": longitudinal_bundle.get("data_certainty_bundle", {}),
            "score_interpretation_catalog_snapshot": longitudinal_bundle.get("score_interpretation_catalog_snapshot", {}),
            "crpc_copilot_status": crpc_copilot_bundle.get("status", "not_applicable"),
            "post_rp_copilot_status": post_rp_salvage_bundle.get("status", "not_applicable"),
            "mhspc_copilot_status": mhspc_copilot_bundle.get("status", "not_applicable"),
            "diagnostic_copilot_status": diagnostic_biopsy_bundle.get("status", "not_applicable"),
            "localized_copilot_status": localized_surveillance_bundle.get("status", "not_applicable"),
            "post_rt_copilot_status": post_rt_salvage_bundle.get("status", "not_applicable"),
            "salvage_window_status": post_rp_salvage_bundle.get("salvage_window_status", ""),
            "salvage_window_reason": post_rp_salvage_bundle.get("salvage_window_reason", ""),
            "post_rt_salvage_window_status": post_rt_salvage_bundle.get("post_rt_salvage_window_status", ""),
            "qa_passed": qa_passed,
            "qa_validation": qa_validation,
            "sequence_summary": sequence_summary,
            "histopathology_summary": histopathology_summary,
            "metastatic_composition_summary": metastatic_composition_summary,
            "decision_delta_since_last_visit": decision_delta_since_last_visit,
            "blocked_by_overlay": blocked_by_overlay,
            "evidence_basis_current_visit": evidence_basis_current_visit,
            "crpc_schedule_overlay": crpc_copilot_bundle.get("crpc_schedule_overlay", {}),
            "post_rp_schedule_overlay": post_rp_salvage_bundle.get("post_rp_schedule_overlay", {}),
            "mhspc_schedule_overlay": mhspc_copilot_bundle.get("mhspc_schedule_overlay", {}),
            "diagnostic_schedule_overlay": diagnostic_biopsy_bundle.get("diagnostic_schedule_overlay", {}),
            "localized_schedule_overlay": localized_surveillance_bundle.get("localized_schedule_overlay", {}),
            "post_rt_schedule_overlay": post_rt_salvage_bundle.get("post_rt_schedule_overlay", {}),
            "mhspc_copilot_bundle": mhspc_copilot_bundle,
            "diagnostic_biopsy_bundle": diagnostic_biopsy_bundle,
            "localized_surveillance_bundle": localized_surveillance_bundle,
            "post_rt_salvage_bundle": post_rt_salvage_bundle,
            "post_rt_failure_definition": post_rt_salvage_bundle.get("post_rt_failure_definition", {}),
            "post_rt_local_salvage_ranking": post_rt_salvage_bundle.get("post_rt_local_salvage_ranking", []),
            "post_rt_transition_bundle": post_rt_salvage_bundle.get("post_rt_transition_bundle", {}),
            "blocking_inputs": decision_input_requirements.get("blocking_inputs", []),
            "hard_blocking_inputs": decision_input_requirements.get("hard_blocking_inputs", []),
            "decision_blocking_inputs": decision_input_requirements.get("decision_blocking_inputs", []),
            "supportive_gaps": decision_input_requirements.get("supportive_gaps", []),
            "required_to_recalculate": decision_input_requirements.get("required_to_recalculate", []),
            "monitoring_required_fields": decision_input_requirements.get("monitoring_required_fields", []),
            "monitoring_capture_block": decision_input_requirements.get("monitoring_capture_block", {}),
            "palliative_required_fields": decision_input_requirements.get("palliative_required_fields", []),
            "palliative_missing_inputs": decision_input_requirements.get("palliative_missing_inputs", []),
            "palliative_stale_inputs": decision_input_requirements.get("palliative_stale_inputs", []),
            "palliative_capture_block": decision_input_requirements.get("palliative_capture_block", {}),
            "goals_of_care_capture_block": decision_input_requirements.get("goals_of_care_capture_block", {}),
            "family_missing_inputs": decision_input_requirements.get("family_missing_inputs", {}),
            "family_stale_inputs": decision_input_requirements.get("family_stale_inputs", {}),
            "plan_key": (schedule_bundle.get("master_followup_plan") or {}).get("plan_key", ""),
            "guideline_basis": (schedule_bundle.get("master_followup_plan") or {}).get("guideline_basis", []),
            "cadence_adjustment_reasons": guideline_followup_plan.get("cadence_adjustment_reasons", []),
            "plan_version": (schedule_bundle.get("master_followup_plan") or {}).get("plan_version", ""),
            "plan_status": (schedule_bundle.get("master_followup_plan") or {}).get("plan_status", "active"),
            "calendar_horizon_months": (schedule_bundle.get("master_followup_plan") or {}).get("calendar_horizon_months", horizon),
            "timeline": (schedule_bundle.get("master_followup_plan") or {}).get("timeline", []),
            "schedule_anchor_strength": schedule_bundle.get("schedule_anchor_strength", "strong"),
            "prognostic_rationale": schedule_bundle.get("prognostic_rationale", (schedule_bundle.get("master_followup_plan") or {}).get("prognostic_rationale", [])),
            "cadence_adjusted_by": schedule_bundle.get("cadence_adjusted_by", (schedule_bundle.get("master_followup_plan") or {}).get("cadence_adjusted_by", [])),
            "backbone_alignment": schedule_bundle.get("backbone_alignment", (schedule_bundle.get("master_followup_plan") or {}).get("backbone_alignment", {})),
            "milestone_plan": schedule_bundle.get("milestone_plan", []),
            "outcome_anchor": schedule_bundle.get("outcome_anchor", {}),
            "pending_adjudication_tasks": schedule_bundle.get("pending_adjudication_tasks", []),
            "outcome_events_summary": schedule_bundle.get("outcome_events_summary", {}),
            "pending_adjudications": schedule_bundle.get("pending_adjudications", []),
            "current_response_state": schedule_bundle.get("current_response_state", {}),
            "current_course_status": schedule_bundle.get("current_course_status", ""),
            "last_adjudicated_event": schedule_bundle.get("last_adjudicated_event", {}),
            "trial_comparable_endpoints": schedule_bundle.get("trial_comparable_endpoints", []),
            "current_trial_comparable_profile": schedule_bundle.get("current_trial_comparable_profile", {}),
            "preferred_frontline_regimen": latest_result_snapshot.get("preferred_frontline_regimen", {}),
            "frontline_regimen_rankings": latest_result_snapshot.get("frontline_regimen_rankings", []),
            "drug_component_metadata": latest_result_snapshot.get("drug_component_metadata", {}),
            "comparative_eligibility_matrix": comparative_eligibility_matrix,
            "sequence_transition_bundle": sequence_transition_bundle,
            "active_regimen_monitoring_package": active_regimen_monitoring_package,
            "palliative_transition_bundle": palliative_transition_bundle,
            "palliative_monitoring_package": palliative_monitoring_package,
            "symptom_burden_profile": longitudinal_bundle.get("symptom_burden_profile", {}),
            "advance_care_planning_status": longitudinal_bundle.get("advance_care_planning_status", {}),
            "hospice_eligibility": longitudinal_bundle.get("hospice_eligibility", {}),
            "acute_palliative_alerts": longitudinal_bundle.get("acute_palliative_alerts", []),
            "recommended_supportive_referrals": longitudinal_bundle.get("recommended_supportive_referrals", []),
            "survivorship_transition_bundle": longitudinal_bundle.get("survivorship_transition_bundle", {}),
            "survivorship_monitoring_package": longitudinal_bundle.get("survivorship_monitoring_package", {}),
            "late_effects_profile": longitudinal_bundle.get("late_effects_profile", {}),
            "functional_recovery_profile": longitudinal_bundle.get("functional_recovery_profile", {}),
            "survivorship_schedule_overlay": longitudinal_bundle.get("survivorship_schedule_overlay", {}),
            "survivorship_plan": longitudinal_bundle.get("survivorship_plan", {}),
            "total_events": len(schedule_bundle.get("scheduled_items", schedule_bundle.get("schedule", []))),
            "resolved_patient_id": patient_id,
            "resolved_patient_ref": resolved.get("nss") or resolved.get("patient_ref") or str(patient_ref),
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<int:patient_id>/outcomes", methods=["GET"])
def patient_outcomes(patient_id: int) -> tuple:
    import tracking_db

    try:
        if not tracking_db.patient_exists(patient_id):
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404
        payload = tracking_db.get_patient_outcomes(patient_id)
        if payload is None:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404
        return jsonify({"success": True, **payload})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/cohorts/benchmarks", methods=["GET"])
def cohort_benchmarks() -> tuple:
    import tracking_db

    try:
        payload = tracking_db.get_cohort_benchmarks()
        return jsonify({"success": True, **payload})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<int:patient_id>/risk-tools", methods=["GET"])
def patient_risk_tools(patient_id: int) -> tuple:
    import tracking_db
    from prostanet.domains.patient_tracking.disease_course_outcomes import build_disease_course_bundle
    from prostanet.domains.patient_tracking.prognostic_impact import build_prognostic_impact_bundle
    from prostanet.domains.patient_tracking.risk_tools import build_risk_tools_panel
    from prostanet.domains.patient_tracking.reconciled_state import build_reconciled_state
    from prostanet.shared.presentation_text import humanize_assessment

    try:
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404
        raw_assessment = patient.get("latest_assessment") or {}
        assessment = humanize_assessment(raw_assessment) if raw_assessment else {}
        reconciliation = build_reconciled_state(patient, raw_assessment)
        state = reconciliation.get("reconciled_state") or raw_assessment.get("state") or (patient.get("prior_history") or {}).get("current_state") or ""
        bundle = build_risk_tools_panel(
            patient=patient,
            state=state,
            raw_assessment=raw_assessment,
            display_assessment=assessment,
        )
        current_trial_profile = dict((patient.get("latest_trial_benchmark_snapshot") or {}).get("current_trial_profile") or {})
        if not current_trial_profile:
            current_trial_profile = build_disease_course_bundle(
                patient,
                state=state,
                management_track=reconciliation.get("reconciled_management_track") or "",
                latest_assessment=raw_assessment,
            ).get("current_trial_comparable_profile", {})
        prognostic_bundle = build_prognostic_impact_bundle(
            patient=patient,
            state=state,
            management_track=reconciliation.get("reconciled_management_track") or "",
            raw_assessment=raw_assessment,
            risk_tools_bundle=bundle,
            current_trial_profile=current_trial_profile,
        )
        return jsonify({"success": True, **bundle, **prognostic_bundle})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<int:patient_id>/schedule/overdue", methods=["GET"])
def patient_overdue(patient_id: int) -> tuple:
    """Detecta eventos de seguimiento vencidos."""
    import tracking_db
    from prostanet.domains.patient_tracking.reconciled_state import build_reconciled_state

    try:
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404

        reconciliation = build_reconciled_state(patient, patient.get("latest_assessment"))
        state = reconciliation.get("reconciled_state") or "diagnostic_workup"
        track = reconciliation.get("reconciled_management_track") or "diagnostic_surveillance"
        schedule_bundle = tracking_db.sync_scheduled_events(
            patient,
            state=state,
            management_track=track,
            horizon_months=int(request.args.get("horizon_months", 12)),
        )
        overdue = [item for item in (schedule_bundle.get("active_schedule") or schedule_bundle.get("schedule") or []) if item.get("status") == "overdue" and not item.get("completed")]

        return jsonify({
            "success": True,
            "reconciled_state": reconciliation.get("reconciled_state", state),
            "state_conflict_flag": reconciliation.get("state_conflict_flag", False),
            "state_conflict_reason": reconciliation.get("state_conflict_reason", ""),
            "anchor_date": schedule_bundle.get("anchor_date", ""),
            "anchor_source": schedule_bundle.get("anchor_source", ""),
            "protocol_trace": schedule_bundle.get("protocol_trace", {}),
            "schedule_anchor_strength": schedule_bundle.get("schedule_anchor_strength", "strong"),
            "overdue_alerts": overdue,
            "overdue_count": len(overdue),
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<int:patient_id>/clinical-alerts", methods=["GET"])
def patient_clinical_alerts(patient_id: int) -> tuple:
    """Retorna la salida canónica de alertas del copiloto para este paciente."""
    import tracking_db

    try:
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404
        bundle = tracking_db.refresh_longitudinal_intelligence(patient_id, force_recompute=False)
        alerts = bundle.get("copilot_alerts", [])
        return jsonify({
            "success": True,
            "alerts": alerts,
            "critical_count": sum(1 for a in alerts if a.get("severity") == "critical"),
            "warning_count": sum(1 for a in alerts if a.get("severity") == "warning"),
            "alert_summary": bundle.get("alert_summary", {}),
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<int:patient_id>/response-assessment", methods=["POST"])
def patient_response_assessment(patient_id: int) -> tuple:
    """Evalúa respuesta terapéutica (RECIST 1.1, PCWG3, PSA)."""
    import tracking_db
    from prostanet.domains.patient_tracking.response_assessment import ResponseAssessmentService

    try:
        data = _parse_json()
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404

        soft_tissue = None
        bone = None
        psa = None

        # Soft tissue assessment (RECIST 1.1)
        st_data = data.get("soft_tissue")
        if st_data:
            current_sum = safe_float(st_data.get("current_sum_mm"), None)
            baseline_sum = safe_float(st_data.get("baseline_sum_mm"), None)
            if current_sum is None or baseline_sum is None:
                raise ValueError("Para evaluar tejidos blandos se requieren 'current_sum_mm' y 'baseline_sum_mm'.")
            soft_tissue = ResponseAssessmentService.assess_soft_tissue(
                current_sum_mm=current_sum,
                baseline_sum_mm=baseline_sum,
                nadir_sum_mm=safe_float(st_data.get("nadir_sum_mm"), None),
                new_lesions=_validated_bool(st_data.get("new_lesions"), "soft_tissue.new_lesions", default=False),
                non_target_progression=_validated_bool(st_data.get("non_target_progression"), "soft_tissue.non_target_progression", default=False),
            )

        # Bone assessment (PCWG3)
        bone_data = data.get("bone")
        if bone_data:
            lesion_count = safe_int(bone_data.get("new_lesion_count"), None)
            if lesion_count is None:
                raise ValueError("Para evaluar respuesta ósea se requiere 'new_lesion_count'.")
            bone = ResponseAssessmentService.assess_bone(
                new_lesion_count=lesion_count,
                prior_scan_new_lesions=safe_int(bone_data.get("prior_scan_new_lesions"), 0),
                is_first_assessment=_validated_bool(bone_data.get("is_first_assessment"), "bone.is_first_assessment", default=False),
            )

        # PSA response
        psa_data = data.get("psa")
        if psa_data:
            baseline_psa = safe_float(psa_data.get("baseline_psa"), None)
            current_psa = safe_float(psa_data.get("current_psa"), None)
            if baseline_psa is None or current_psa is None:
                raise ValueError("Para evaluar respuesta por PSA se requieren 'baseline_psa' y 'current_psa'.")
            psa = ResponseAssessmentService.assess_psa(
                baseline_psa=baseline_psa,
                current_psa=current_psa,
                nadir_psa=safe_float(psa_data.get("nadir_psa"), None),
                confirmed_at_4_weeks=_validated_bool(psa_data.get("confirmed"), "psa.confirmed", default=False),
            )

        if not any((soft_tissue, bone, psa)):
            raise ValueError("Se requiere al menos un bloque válido: 'soft_tissue', 'bone' o 'psa'.")

        # Composite
        composite = ResponseAssessmentService.composite_response(soft_tissue, bone, psa)

        # Persist
        try:
            conn = tracking_db._connect()
            c = conn.cursor()
            c.execute(
                """INSERT INTO response_assessments
                   (patient_id, assessment_date, recist_category, sum_target_diameters,
                    baseline_sum_diameters, nadir_sum_diameters, pcwg3_bone_status,
                    new_bone_lesion_count, psa_response_category, psa_baseline,
                    psa_current, psa_nadir, psa_change_from_baseline_pct,
                    overall_response, clinical_benefit, details_json)
                   VALUES (?,date('now'),?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    patient_id,
                    soft_tissue.category if soft_tissue else None,
                    soft_tissue.sum_target_diameters_mm if soft_tissue else None,
                    soft_tissue.baseline_sum_mm if soft_tissue else None,
                    soft_tissue.nadir_sum_mm if soft_tissue else None,
                    bone.status if bone else None,
                    bone.new_lesion_count if bone else None,
                    psa.category if psa else None,
                    psa.baseline_psa if psa else None,
                    psa.current_psa if psa else None,
                    psa.nadir_psa if psa else None,
                    psa.change_from_baseline_pct if psa else None,
                    composite.overall,
                    1 if composite.clinical_benefit else 0,
                    __import__("json").dumps(composite.to_dict(), ensure_ascii=False),
                ),
            )
            assessment_id = c.lastrowid
            conn.commit()
            conn.close()
            event_id = tracking_db.record_patient_event(
                patient_id,
                event_type="study_resulted",
                event_date=None,
                state_context=(patient.get("latest_assessment") or {}).get("state", ""),
                management_track=(patient.get("latest_signal_snapshot") or {}).get("management_track", ""),
                source_type="response_assessment",
                source_record_id=assessment_id,
                payload={"response": composite.to_dict()},
                mcode_focus={"resource": "response_assessment"},
            )
            tracking_db.refresh_longitudinal_intelligence(patient_id, event_id=event_id, force_recompute=False)
        except Exception as db_err:
            import logging
            logging.getLogger(__name__).warning("Error persisting response assessment: %s", db_err)

        # Enrich with survival context when PD detected
        survival_context = {}
        try:
            survival_context = ResponseAssessmentService.evaluate_with_survival_context(patient, composite)
        except Exception:
            pass

        return jsonify({
            "success": True,
            "response": composite.to_dict(),
            "survival_context": survival_context,
        })
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<int:patient_id>/comorbidity-scores", methods=["POST"])
def patient_comorbidity_scores(patient_id: int) -> tuple:
    """Calcula CCI, G8 y PHI para el paciente."""
    import tracking_db
    from clinical_scores import charlson_comorbidity_index, g8_geriatric_assessment, prostate_health_index

    try:
        data = _parse_json()
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404

        # Merge patient data with incoming data
        score_data = {}
        score_data.update(patient.get("identity", {}))
        score_data.update(patient.get("baseline", {}) or {})
        score_data.update(data)

        results = {}
        results["charlson"] = charlson_comorbidity_index(score_data)
        results["g8"] = g8_geriatric_assessment(score_data)

        # PHI only if biomarkers available
        if score_data.get("free_psa") and score_data.get("p2psa"):
            results["phi"] = prostate_health_index(score_data)

        # Persist CCI if calculated
        try:
            conn = tracking_db._connect()
            c = conn.cursor()
            c.execute(
                "UPDATE patient_demographics SET charlson_score=?, charlson_details_json=?, g8_score=? WHERE patient_id=?",
                (
                    results["charlson"]["age_adjusted_score"],
                    __import__("json").dumps(results["charlson"]),
                    results["g8"]["score"],
                    patient_id,
                ),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

        return jsonify({"success": True, "scores": results})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<int:patient_id>/tumor-board", methods=["GET"])
def patient_tumor_board(patient_id: int) -> tuple:
    """Genera presentación estructurada para tumor board / comité multidisciplinario."""
    import tracking_db
    from prostanet.domains.reporting.tumor_board import TumorBoardPresentation

    try:
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404

        presentation = TumorBoardPresentation.generate(patient)
        return jsonify({"success": True, "tumor_board": presentation})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<int:patient_id>/survivorship-plan", methods=["GET"])
def patient_survivorship_plan(patient_id: int) -> tuple:
    """Genera plan de cuidado de sobrevivencia personalizado."""
    import tracking_db
    from prostanet.domains.patient_tracking.longitudinal_intelligence import build_longitudinal_intelligence_bundle
    from prostanet.domains.patient_tracking.survivorship_longitudinal import (
        build_survivorship_monitoring_package,
        build_survivorship_plan_alias,
        build_survivorship_schedule_overlay,
        build_survivorship_transition_bundle,
    )
    from prostanet.domains.patient_tracking.followup_agenda import infer_management_track

    try:
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404

        latest_assessment = patient.get("latest_assessment")
        state = (latest_assessment or {}).get("state") or "diagnostic_workup"
        track = infer_management_track(patient, state, latest_assessment)
        longitudinal_bundle = build_longitudinal_intelligence_bundle(patient, latest_assessment)
        transition_bundle = dict(longitudinal_bundle.get("survivorship_transition_bundle") or {})
        monitoring_package = dict(longitudinal_bundle.get("survivorship_monitoring_package") or {})
        if not transition_bundle:
            transition_bundle = build_survivorship_transition_bundle(
                patient,
                state=state,
                management_track=track,
                latest_assessment=latest_assessment,
            )
        if not monitoring_package:
            monitoring_package = build_survivorship_monitoring_package(
                patient,
                state=state,
                management_track=track,
                latest_assessment=latest_assessment,
                transition_bundle=transition_bundle,
            )
        schedule_overlay = build_survivorship_schedule_overlay(transition_bundle, monitoring_package)
        plan = build_survivorship_plan_alias(transition_bundle, monitoring_package)
        return jsonify(
            {
                "success": True,
                "survivorship_plan": plan,
                "survivorship_transition_bundle": transition_bundle,
                "survivorship_monitoring_package": monitoring_package,
                "survivorship_schedule_overlay": schedule_overlay,
                "late_effects_profile": longitudinal_bundle.get("late_effects_profile") or {},
                "functional_recovery_profile": longitudinal_bundle.get("functional_recovery_profile") or {},
            }
        )
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<int:patient_id>/structured-biopsy", methods=["POST"])
def patient_structured_biopsy(patient_id: int) -> tuple:
    """Parsea y analiza biopsia estructurada con mapa sextante y concordancia MRI."""
    import tracking_db
    from prostanet.domains.patient_tracking.structured_biopsy import StructuredBiopsyService

    try:
        data = _parse_json()
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404

        parsed = StructuredBiopsyService.parse_structured_biopsy(data)
        summary = StructuredBiopsyService.build_biopsy_summary_for_profile(parsed)

        # Check for upgrade vs previous biopsy
        biopsies = patient.get("biopsies") or []
        previous = biopsies[-1] if biopsies and isinstance(biopsies[-1], dict) else None
        upgrade = StructuredBiopsyService.evaluate_upgrade_from_previous(parsed, previous)
        concordance = StructuredBiopsyService.check_mri_concordance(parsed)
        alerts = StructuredBiopsyService.evaluate_biopsy_alerts(patient_id, parsed, previous)

        return jsonify({
            "success": True,
            "biopsy_summary": summary,
            "upgrade_assessment": upgrade,
            "mri_concordance": concordance,
            "alerts": [a.to_dict() for a in alerts],
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<int:patient_id>/active-surveillance", methods=["GET"])
def patient_active_surveillance(patient_id: int) -> tuple:
    """Evalúa elegibilidad AS multi-protocolo, construye protocolo y agenda."""
    import tracking_db
    from prostanet.domains.patient_tracking.active_surveillance import ActiveSurveillanceService
    from prostanet.domains.patient_tracking.reconciled_state import build_reconciled_state

    try:
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404

        assessment = patient.get("latest_assessment") or {}
        reconciliation = build_reconciled_state(patient, assessment)
        state = reconciliation.get("reconciled_state", "")

        as_data = {}
        as_data.update(patient.get("identity", {}))
        as_data.update(patient.get("baseline", {}) or {})
        if patient.get("prior_history"):
            as_data.update(patient["prior_history"])
        followups = patient.get("follow_ups", [])
        if followups:
            as_data.update(followups[-1])

        eligibility = ActiveSurveillanceService.check_eligibility(as_data, state)
        protocol = ActiveSurveillanceService.build_as_protocol(as_data, state)
        summary = ActiveSurveillanceService.build_as_summary_for_profile(protocol)
        alerts = ActiveSurveillanceService.evaluate_as_alerts(patient_id, protocol)

        return jsonify({
            "success": True,
            "eligibility": [e.__dict__ if hasattr(e, "__dict__") else e for e in eligibility],
            "protocol_summary": summary,
            "alerts": _serialize_alerts(alerts),
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<int:patient_id>/radiotherapy-detail", methods=["GET"])
def patient_radiotherapy_detail(patient_id: int) -> tuple:
    """Historial detallado de radioterapia con validación de fraccionamiento y toxicidad."""
    import tracking_db
    from prostanet.domains.patient_tracking.radiotherapy_detail import RadiotherapyDetailService

    try:
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404

        rt_summary = RadiotherapyDetailService.build_rt_history(patient)
        profile_summary = RadiotherapyDetailService.build_rt_summary_for_profile(rt_summary)
        alerts = RadiotherapyDetailService.evaluate_rt_alerts(patient_id, rt_summary)

        return jsonify({
            "success": True,
            "rt_summary": profile_summary,
            "alerts": _serialize_alerts(alerts),
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<int:patient_id>/skeletal-events", methods=["GET"])
def patient_skeletal_events(patient_id: int) -> tuple:
    """Perfil de eventos esqueléticos, riesgo SRE y cumplimiento BMA."""
    import tracking_db
    from prostanet.domains.patient_tracking.skeletal_events import SkeletalEventService
    from prostanet.domains.patient_tracking.reconciled_state import build_reconciled_state

    try:
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404

        assessment = patient.get("latest_assessment") or {}
        reconciliation = build_reconciled_state(patient, assessment)
        state = reconciliation.get("reconciled_state", "")

        sre_data = {}
        sre_data.update(patient.get("identity", {}))
        sre_data.update(patient.get("baseline", {}) or {})
        if patient.get("prior_history"):
            sre_data.update(patient["prior_history"])
        followups = patient.get("follow_ups", [])
        if followups:
            sre_data.update(followups[-1])
        sre_data["skeletal_events"] = patient.get("skeletal_events") or patient.get("sre_events") or []

        profile = SkeletalEventService.build_sre_profile(sre_data, state)
        summary = SkeletalEventService.build_sre_summary_for_profile(profile)
        alerts = SkeletalEventService.evaluate_sre_alerts(patient_id, profile)

        return jsonify({
            "success": True,
            "sre_profile": summary,
            "alerts": _serialize_alerts(alerts),
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<int:patient_id>/survival-endpoints", methods=["GET"])
def patient_survival_endpoints(patient_id: int) -> tuple:
    """Calcula endpoints de supervivencia (OS, rPFS, MFS, BCR-FS, TTPP, TTSRE, etc.)."""
    import tracking_db
    from prostanet.domains.patient_tracking.survival_endpoints import SurvivalEndpointService
    from prostanet.domains.patient_tracking.reconciled_state import build_reconciled_state

    try:
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404

        assessment = patient.get("latest_assessment") or {}
        reconciliation = build_reconciled_state(patient, assessment)
        state = reconciliation.get("reconciled_state", "")

        survival_status = SurvivalEndpointService.compute_endpoints(patient, state)
        summary = SurvivalEndpointService.build_survival_summary_for_profile(survival_status)
        alerts = SurvivalEndpointService.evaluate_survival_alerts(patient_id, survival_status)

        return jsonify({
            "success": True,
            "survival_status": summary,
            "alerts": _serialize_alerts(alerts),
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<int:patient_id>/psa-forecast", methods=["GET"])
def patient_psa_forecast(patient_id: int) -> tuple:
    """Devuelve forecast prospectivo de PSA para la línea terapéutica actual."""
    import tracking_db

    try:
        if not tracking_db.patient_exists(patient_id):
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404
        bundle = tracking_db.refresh_longitudinal_intelligence(patient_id, force_recompute=False)
        return jsonify(
            {
                "success": True,
                "psa_forecast": bundle.get("psa_forecast", {}),
                "forecast_reliability": bundle.get("forecast_reliability", {}),
            }
        )
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<int:patient_id>/live-benchmark", methods=["GET"])
def patient_live_benchmark(patient_id: int) -> tuple:
    """Devuelve benchmarking vivo del paciente contra cohorte similar y referencia publicada."""
    import tracking_db
    from prostanet.domains.patient_tracking.live_benchmark import resolve_live_benchmark_from_snapshot

    try:
        if not tracking_db.patient_exists(patient_id):
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404
        refresh_requested = str(request.args.get("refresh") or "").strip().lower() in {"1", "true", "yes"}
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404
        if refresh_requested:
            bundle = tracking_db.refresh_longitudinal_intelligence(
                patient_id,
                force_recompute=False,
                record=patient,
                include_live_benchmark=True,
            )
            live_benchmark = bundle.get("live_benchmark", {})
            benchmark_reliability = bundle.get("benchmark_reliability", {})
        else:
            state = str(
                (patient.get("latest_signal_snapshot") or {}).get("effective_state_final")
                or (patient.get("latest_signal_snapshot") or {}).get("effective_state")
                or (patient.get("latest_signal_snapshot") or {}).get("reconciled_state")
                or (patient.get("latest_assessment") or {}).get("state")
                or (patient.get("prior_history") or {}).get("current_state")
                or ""
            )
            management_track = str(
                (patient.get("latest_signal_snapshot") or {}).get("effective_management_track_final")
                or (patient.get("latest_signal_snapshot") or {}).get("effective_management_track")
                or (patient.get("latest_signal_snapshot") or {}).get("reconciled_management_track")
                or patient.get("management_track")
                or ""
            )
            live_benchmark, benchmark_reliability = resolve_live_benchmark_from_snapshot(
                patient,
                state=state,
                management_track=management_track,
            )
        return jsonify(
            {
                "success": True,
                "live_benchmark": live_benchmark,
                "benchmark_reliability": benchmark_reliability,
            }
        )
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/cohorts/survival-curves", methods=["GET"])
def cohort_survival_curves() -> tuple:
    """Devuelve curva Kaplan-Meier y dataset tiempo-evento para un endpoint."""
    import tracking_db
    from prostanet.domains.patient_tracking.survival_analysis import build_survival_curve_payload

    try:
        endpoint_type = str(request.args.get("endpoint_type") or request.args.get("endpoint") or "OS").strip() or "OS"
        state_filter = str(request.args.get("state") or "").strip() or None
        conn = tracking_db._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM patient_identity ORDER BY id ASC")
        patient_ids = [int(row["id"]) for row in cursor.fetchall()]
        conn.close()
        records = [tracking_db.get_patient_full_record(patient_id) for patient_id in patient_ids]
        records = [record for record in records if record]
        payload = build_survival_curve_payload(records, endpoint_type, state_filter=state_filter)
        return jsonify({"success": True, **payload})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/cohorts/survival-analysis", methods=["GET"])
def cohort_survival_analysis() -> tuple:
    """Devuelve análisis Cox PH sobre el endpoint solicitado."""
    import tracking_db
    from prostanet.domains.patient_tracking.survival_analysis import build_cox_analysis_payload
    from prostanet.domains.patient_tracking.psa_forecast import build_psa_forecast_backtest

    try:
        endpoint_type = str(request.args.get("endpoint_type") or request.args.get("endpoint") or "OS").strip() or "OS"
        state_filter = str(request.args.get("state") or "").strip() or None
        conn = tracking_db._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM patient_identity ORDER BY id ASC")
        patient_ids = [int(row["id"]) for row in cursor.fetchall()]
        conn.close()
        records = [tracking_db.get_patient_full_record(patient_id) for patient_id in patient_ids]
        records = [record for record in records if record]
        if endpoint_type.upper() == "PSA_FORECAST":
            payload = build_psa_forecast_backtest(records)
        else:
            payload = build_cox_analysis_payload(records, endpoint_type, state_filter=state_filter)
        return jsonify({"success": True, **payload})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/cohorts/domain-completeness", methods=["GET"])
def cohort_domain_completeness() -> tuple:
    """Resume completitud operativa por dominio longitudinal canónico."""
    import tracking_db
    from prostanet.domains.patient_tracking.survival_analysis import build_domain_completeness_payload

    try:
        conn = tracking_db._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM patient_identity ORDER BY id ASC")
        patient_ids = [int(row["id"]) for row in cursor.fetchall()]
        conn.close()
        records = [tracking_db.get_patient_full_record(patient_id) for patient_id in patient_ids]
        records = [record for record in records if record]
        payload = build_domain_completeness_payload(records)
        return jsonify({"success": True, **payload})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/research/consent/versions/current", methods=["GET"])
def research_current_consent_version() -> tuple:
    try:
        return jsonify({"success": True, **get_current_consent_payload()})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/research/consent/draft", methods=["POST"])
def research_create_consent_draft() -> tuple:
    try:
        data = _parse_json()
        payload = tracking_service.canonicalize_payload(dict(data.get("payload") or data))
        assessment_id = payload.get("assessment_id")
        if assessment_id not in (None, ""):
            assessment = assessment_service.get_draft(int(float(assessment_id)))
            if not assessment:
                raise ValueError("Evaluación clínica no encontrada.")
            payload = tracking_service.merge_assessment_payload(assessment, payload)
        payload["nss"] = str(payload.get("nss", "")).strip()
        payload["full_name"] = str(payload.get("full_name", "")).strip()
        if not payload["nss"] or not payload["full_name"]:
            raise ValueError("Se requieren NSS y nombre completo para iniciar el consentimiento.")
        source_context = str(data.get("source_context") or "wizard")
        return jsonify({"success": True, **create_consent_draft(payload, source_context=source_context)})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/research/consent/draft/<int:draft_id>", methods=["GET"])
def research_get_consent_draft(draft_id: int) -> tuple:
    try:
        draft = get_consent_draft_payload(draft_id)
        if not draft:
            return jsonify({"success": False, "error": "Borrador no encontrado."}), 404
        return jsonify({"success": True, "draft": draft})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/research/consent/draft/<int:draft_id>/sign", methods=["POST"])
def research_sign_consent_draft(draft_id: int) -> tuple:
    try:
        payload = _parse_json()
        result = sign_consent_draft_payload(draft_id, payload)
        return jsonify({"success": True, **result})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/research/consent/draft/<int:draft_id>/finalize", methods=["POST"])
def research_finalize_consent_draft(draft_id: int) -> tuple:
    try:
        result = finalize_consent_draft_payload(draft_id)
        return jsonify({"success": True, **result})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/research/cohorts", methods=["GET", "POST"])
def research_cohorts() -> tuple:
    try:
        if request.method == "GET":
            return jsonify({"success": True, "cohorts": list_dynamic_cohort_payload()})
        data = _parse_json()
        title = str(data.get("title", "")).strip()
        filters = list(data.get("filters") or [])
        if not title or not filters:
            raise ValueError("Se requieren título y filtros para crear una cohorte.")
        cohort = create_dynamic_cohort(
            title=title,
            filters=filters,
            description=str(data.get("description") or "").strip(),
        )
        return jsonify({"success": True, "cohort": cohort})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/research/cohorts/<int:cohort_id>", methods=["GET"])
def research_cohort_detail(cohort_id: int) -> tuple:
    try:
        cohort = get_dynamic_cohort_payload(cohort_id)
        if not cohort:
            return jsonify({"success": False, "error": "Cohorte no encontrada."}), 404
        return jsonify({"success": True, "cohort": cohort})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/research/survival-curves", methods=["GET"])
def research_survival_curves() -> tuple:
    try:
        endpoint = request.args.get("endpoint", "OS")
        cohort_id = request.args.get("cohort_id")
        stratify_by = request.args.get("stratify_by", "reconciled_state")
        payload = build_survival_registry_payload(
            endpoint=endpoint,
            cohort_id=int(cohort_id) if cohort_id not in (None, "") else None,
            stratify_by=stratify_by,
        )
        return jsonify({"success": True, **payload})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/research/survival-analysis/cox", methods=["GET"])
def research_survival_cox() -> tuple:
    try:
        endpoint = request.args.get("endpoint", "OS")
        cohort_id = request.args.get("cohort_id")
        covariates = [item for item in request.args.getlist("covariate") if item]
        payload = build_cox_payload(
            endpoint=endpoint,
            cohort_id=int(cohort_id) if cohort_id not in (None, "") else None,
            covariates=covariates or None,
        )
        return jsonify({"success": True, **payload})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/research/survival-analysis/logistic", methods=["GET"])
def research_logistic() -> tuple:
    try:
        outcome = request.args.get("outcome", "molecular_report_available")
        cohort_id = request.args.get("cohort_id")
        covariates = [item for item in request.args.getlist("covariate") if item]
        payload = build_logistic_payload(
            outcome=outcome,
            cohort_id=int(cohort_id) if cohort_id not in (None, "") else None,
            covariates=covariates or None,
        )
        return jsonify({"success": True, **payload})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/research/propensity", methods=["POST"])
def research_propensity() -> tuple:
    try:
        data = _parse_json()
        payload = run_propensity_analysis(
            cohort_id=int(data.get("cohort_id")),
            treatment_field=str(data.get("treatment_field")),
            treatment_value=str(data.get("treatment_value")),
            control_value=str(data.get("control_value")),
            outcome_field=str(data.get("outcome_field") or "survival_os_event"),
            covariates=list(data.get("covariates") or []),
            caliper=float(data.get("caliper") or 0.2),
        )
        return jsonify({"success": True, **payload})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/research/outcomes/operational", methods=["GET"])
def research_operational_outcomes() -> tuple:
    try:
        conn = tracking_db._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM patient_identity ORDER BY id ASC")
        records = [tracking_db.get_patient_full_record(int(row["id"])) for row in cursor.fetchall()]
        conn.close()
        payload = build_operational_outcomes_payload([record for record in records if record])
        return jsonify({"success": True, **payload})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/research/quality-indicators", methods=["GET"])
def research_quality_indicators() -> tuple:
    try:
        conn = tracking_db._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM patient_identity ORDER BY id ASC")
        records = [tracking_db.get_patient_full_record(int(row["id"])) for row in cursor.fetchall()]
        conn.close()
        payload = build_quality_indicator_payload([record for record in records if record])
        return jsonify({"success": True, **payload})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/research/benchmarks", methods=["GET"])
def research_benchmarks() -> tuple:
    try:
        conn = tracking_db._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM patient_identity ORDER BY id ASC")
        records = [tracking_db.get_patient_full_record(int(row["id"])) for row in cursor.fetchall()]
        conn.close()
        payload = build_institutional_benchmark_payload([record for record in records if record])
        return jsonify({"success": True, **payload})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/research/export/csv", methods=["GET"])
def research_export_csv() -> tuple:
    try:
        cohort_id = request.args.get("cohort_id")
        payload = build_csv_export_payload(cohort_id=int(cohort_id) if cohort_id not in (None, "") else None)
        return jsonify({"success": True, **payload})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/research/export/redcap", methods=["GET"])
def research_export_redcap() -> tuple:
    try:
        cohort_id = request.args.get("cohort_id")
        payload = build_redcap_export_payload(cohort_id=int(cohort_id) if cohort_id not in (None, "") else None)
        return jsonify({"success": True, **payload})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/research/export/cdisc", methods=["GET"])
def research_export_cdisc() -> tuple:
    try:
        cohort_id = request.args.get("cohort_id")
        payload = build_cdisc_mapping_payload(cohort_id=int(cohort_id) if cohort_id not in (None, "") else None)
        return jsonify({"success": True, **payload})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<int:patient_id>/adt-side-effects", methods=["POST"])
def patient_adt_side_effects(patient_id: int) -> tuple:
    """Evaluación de efectos secundarios de ADT (CV, metabólico, óseo)."""
    import tracking_db
    from prostanet.domains.patient_tracking.adt_side_effects import ADTSideEffectService

    try:
        data = _parse_json()
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404

        adt_data = {}
        adt_data.update(patient.get("identity", {}))
        adt_data.update(patient.get("baseline", {}) or {})
        if patient.get("prior_history"):
            adt_data.update(patient["prior_history"])
        followups = patient.get("follow_ups", [])
        if followups:
            adt_data.update(followups[-1])
        adt_data.update(data)

        profile = ADTSideEffectService.full_assessment(adt_data)
        return jsonify({"success": True, "adt_side_effects": profile.to_dict()})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<int:patient_id>/palliative-assessment", methods=["POST"])
def patient_palliative_assessment(patient_id: int) -> tuple:
    """Evaluación paliativa integral."""
    import tracking_db
    from prostanet.domains.palliative_pathway.service import PalliativePathwayService

    try:
        data = _parse_json()
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404

        pall_data = {}
        pall_data.update(patient.get("identity", {}))
        pall_data.update(patient.get("baseline", {}) or {})
        if patient.get("prior_history"):
            pall_data.update(patient["prior_history"])
        followups = patient.get("follow_ups", [])
        if followups:
            pall_data.update(followups[-1])
        pall_data.update(data)

        assessment = PalliativePathwayService.full_assessment(pall_data)
        return jsonify({"success": True, "palliative_assessment": assessment.to_dict()})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/decision-aids/compare", methods=["POST"])
def decision_aids_compare() -> tuple:
    """Genera comparación de opciones de tratamiento para decisión compartida."""
    from prostanet.domains.reporting.decision_aids import DecisionAidService

    try:
        data = _parse_json()
        options = data.get("options", [])
        if not options:
            return jsonify({"success": False, "error": "Se requiere lista de opciones de tratamiento."}), 400

        comparison = DecisionAidService.generate_comparison(
            options=options,
            risk_group=data.get("risk_group", ""),
            patient_priorities=data.get("patient_priorities"),
        )
        return jsonify({"success": True, "decision_aid": comparison})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/decision-aids/patient-summary", methods=["POST"])
def decision_aids_patient_summary() -> tuple:
    """Genera resumen en lenguaje para paciente sobre un tratamiento."""
    from prostanet.domains.reporting.decision_aids import DecisionAidService

    try:
        data = _parse_json()
        treatment = data.get("treatment", "")
        if not treatment:
            return jsonify({"success": False, "error": "Se requiere el tratamiento."}), 400

        summary = DecisionAidService.generate_patient_summary(
            treatment_key=treatment,
            patient_name=data.get("patient_name", "usted"),
        )
        return jsonify({"success": True, "patient_summary": summary})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/diagnostic-calculators", methods=["POST"])
def diagnostic_calculators() -> tuple:
    """Ejecuta calculadoras diagnósticas avanzadas (4Kscore, ERSPC, PHI)."""
    from clinical_scores import four_k_score, erspc_risk_calculator, prostate_health_index

    try:
        data = _parse_json()
        results = {}

        if data.get("psa") and data.get("free_psa"):
            results["four_k_score"] = four_k_score(data)

            if data.get("p2psa"):
                results["phi"] = prostate_health_index(data)

        if data.get("psa"):
            results["erspc"] = erspc_risk_calculator(data)

        if not results:
            return jsonify({"success": False, "error": "Se requiere al menos PSA para ejecutar calculadoras."}), 400

        return jsonify({"success": True, "calculators": results})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<int:patient_id>/response-visualization", methods=["POST"])
def response_visualization(patient_id: int) -> tuple:
    """Genera datos de visualización terapéutica con swimmer legacy y timeline integrado en PSA."""
    from prostanet.domains.reporting.response_visualization import (
        ResponseVisualizationService,
        build_waterfall_from_line_segments,
    )
    from prostanet.domains.patient_tracking.psa_line_monitor import build_psa_by_treatment_line
    from tracking_db import get_full_record

    try:
        record = get_full_record(patient_id)
        if not record:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404

        treatments = record.get("treatments") or []
        baseline_psa = (record.get("baseline") or {}).get("baseline_psa")
        diagnosis_date = (record.get("identity") or {}).get("diagnosis_date")
        lesion_data = record.get("lesion_tracking") or []
        psa_series = record.get("psa_series") or []

        bundle = ResponseVisualizationService.build_visualization_bundle(
            treatments=treatments,
            lesions=lesion_data,
            psa_series=psa_series,
            baseline_psa=float(baseline_psa) if baseline_psa else None,
            diagnosis_date=diagnosis_date,
        )
        monitoring = build_psa_by_treatment_line(record)
        if monitoring.get("line_segments"):
            bundle.waterfall = build_waterfall_from_line_segments(monitoring.get("line_segments") or [])
            if monitoring.get("points") and not bundle.psa_trajectory.get("points"):
                bundle.psa_trajectory["points"] = list(monitoring.get("points") or [])
            if monitoring.get("treatment_bands") and not bundle.psa_trajectory.get("treatment_bands"):
                bundle.psa_trajectory["treatment_bands"] = list(monitoring.get("treatment_bands") or [])
            bundle.psa_trajectory["has_data"] = bool(
                bundle.psa_trajectory.get("points")
                or bundle.psa_trajectory.get("treatment_bands")
                or (bundle.psa_trajectory.get("integrated_treatment_timeline") or {}).get("has_integrated_timeline")
            )

        return jsonify({"success": True, "visualization": bundle.to_dict()})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


# ═══════════════════════════════════════════════════════════════════════
# AI Engine Endpoints — all gated by feature flags (default OFF)
# ═══════════════════════════════════════════════════════════════════════


def _build_ai_registry():
    from prostanet.ai.inference.model_registry import ModelRegistry

    reg = ModelRegistry()
    reg.load_all_available()
    return reg


def _build_rule_based_recommendation(record: dict[str, Any]) -> dict[str, Any]:
    latest_assessment = record.get("latest_assessment", {}) or {}
    result_snapshot = dict(latest_assessment.get("result_snapshot") or {})
    return {
        "source": "rule_based_primary",
        "state": record.get("reconciled_state") or latest_assessment.get("state") or "",
        "module_id": latest_assessment.get("module_id", ""),
        "management_track": (
            record.get("reconciled_management_track")
            or latest_assessment.get("management_track")
            or ""
        ),
        "guideline_basis": (
            (record.get("guideline_followup_plan") or {}).get("schedule_evidence_basis")
            or latest_assessment.get("guideline_versions")
            or {}
        ),
        "preferred_frontline_regimen": result_snapshot.get("preferred_frontline_regimen", {}),
        "frontline_regimen_rankings": result_snapshot.get("frontline_regimen_rankings", []),
        "drug_component_metadata": result_snapshot.get("drug_component_metadata", {}),
        "note": "La lógica rule-based NCCN/EAU permanece como fuente primaria de verdad clínica.",
    }


def _build_crpc_copilot_payload(patient_id: int, longitudinal_bundle: dict[str, Any] | None = None) -> dict[str, Any]:
    longitudinal_bundle = longitudinal_bundle or tracking_db.refresh_longitudinal_intelligence(
        patient_id,
        force_recompute=False,
        include_live_benchmark=False,
    ) or {}
    return dict(longitudinal_bundle.get("crpc_copilot_bundle") or {})


def _build_post_rp_salvage_payload(patient_id: int, longitudinal_bundle: dict[str, Any] | None = None) -> dict[str, Any]:
    longitudinal_bundle = longitudinal_bundle or tracking_db.refresh_longitudinal_intelligence(
        patient_id,
        force_recompute=False,
        include_live_benchmark=False,
    ) or {}
    return dict(longitudinal_bundle.get("post_rp_salvage_bundle") or {})


def _build_mhspc_copilot_payload(patient_id: int, longitudinal_bundle: dict[str, Any] | None = None) -> dict[str, Any]:
    longitudinal_bundle = longitudinal_bundle or tracking_db.refresh_longitudinal_intelligence(
        patient_id,
        force_recompute=False,
        include_live_benchmark=False,
    ) or {}
    return dict(longitudinal_bundle.get("mhspc_copilot_bundle") or {})


def _build_diagnostic_biopsy_payload(patient_id: int, longitudinal_bundle: dict[str, Any] | None = None) -> dict[str, Any]:
    longitudinal_bundle = longitudinal_bundle or tracking_db.refresh_longitudinal_intelligence(
        patient_id,
        force_recompute=False,
        include_live_benchmark=False,
    ) or {}
    return dict(longitudinal_bundle.get("diagnostic_biopsy_bundle") or {})


def _build_localized_surveillance_payload(patient_id: int, longitudinal_bundle: dict[str, Any] | None = None) -> dict[str, Any]:
    longitudinal_bundle = longitudinal_bundle or tracking_db.refresh_longitudinal_intelligence(
        patient_id,
        force_recompute=False,
        include_live_benchmark=False,
    ) or {}
    return dict(longitudinal_bundle.get("localized_surveillance_bundle") or {})


def _build_post_rt_salvage_payload(patient_id: int, longitudinal_bundle: dict[str, Any] | None = None) -> dict[str, Any]:
    longitudinal_bundle = longitudinal_bundle or tracking_db.refresh_longitudinal_intelligence(
        patient_id,
        force_recompute=False,
        include_live_benchmark=False,
    ) or {}
    return dict(longitudinal_bundle.get("post_rt_salvage_bundle") or {})


def _serialize_agent_objects(items: list[Any]) -> list[dict[str, Any]]:
    from dataclasses import asdict, is_dataclass

    serialized: list[dict[str, Any]] = []
    for item in items:
        if is_dataclass(item):
            serialized.append(asdict(item))
        elif isinstance(item, dict):
            serialized.append(item)
    return serialized


def _validate_cda_output(cda_output: dict[str, Any] | None, record: dict[str, Any]) -> dict[str, Any] | None:
    if not cda_output:
        return None
    try:
        from prostanet.agents.contracts import AgentOutput, AgentRecommendation
        from prostanet.agents.quality_assurance_agent import QualityAssuranceAgent

        recommendations = [
            AgentRecommendation(
                action=item.get("action", ""),
                category=item.get("category", ""),
                priority=item.get("priority", "standard"),
                evidence_basis=item.get("evidence_basis", []),
            )
            for item in (cda_output.get("recommendations") or [])
            if isinstance(item, dict)
        ]
        agent_output = AgentOutput(
            agent_id=cda_output.get("agent_id", "clinical_decision_agent"),
            patient_id=cda_output.get("patient_id", 0),
            recommendations=recommendations,
        )
        return QualityAssuranceAgent().validate(agent_output, record).to_dict()
    except Exception:
        return None


@modular_api.route("/api/ai/predict/state-transition/<int:patient_id>", methods=["POST"])
def ai_predict_state_transition(patient_id):
    """Predict next clinical state and time to transition."""
    try:
        from prostanet.ai.inference.prediction_service import PredictionService

        reg = _build_ai_registry()
        service = PredictionService(model_registry=reg)

        record = tracking_db.get_patient_full_record(patient_id)
        if not record:
            return jsonify({"success": False, "error": "Paciente no encontrado"}), 404

        model_status = reg.get_metadata("state_transition")
        result = service.predict_state_transition(patient_id, record)
        if result is None:
            return jsonify({
                "success": False,
                "error": "Modelo no disponible o flag desactivado",
                "advisory_api": True,
                "rule_based_source_of_truth": True,
                "model_status": model_status,
            }), 503

        return jsonify({
            "success": True,
            "advisory_api": True,
            "rule_based_source_of_truth": True,
            "prediction": result,
            "model_status": model_status,
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/ai/predict/treatment-response/<int:patient_id>", methods=["POST"])
def ai_predict_treatment_response(patient_id):
    """Predict treatment response for a specific regimen."""
    try:
        from prostanet.ai.inference.prediction_service import PredictionService

        data = request.get_json(silent=True) or {}
        regimen_id = data.get("regimen_id", 0)

        reg = _build_ai_registry()
        service = PredictionService(model_registry=reg)

        record = tracking_db.get_patient_full_record(patient_id)
        if not record:
            return jsonify({"success": False, "error": "Paciente no encontrado"}), 404

        model_status = reg.get_metadata("treatment_response")
        result = service.predict_treatment_response(patient_id, record, regimen_id=regimen_id)
        if result is None:
            return jsonify({
                "success": False,
                "error": "Modelo no disponible o flag desactivado",
                "advisory_api": True,
                "rule_based_source_of_truth": True,
                "model_status": model_status,
            }), 503

        return jsonify({
            "success": True,
            "advisory_api": True,
            "rule_based_source_of_truth": True,
            "prediction": result,
            "model_status": model_status,
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/ai/predict/survival/<int:patient_id>", methods=["POST"])
def ai_predict_survival(patient_id):
    """Predict personalized survival curves."""
    try:
        from prostanet.ai.inference.prediction_service import PredictionService

        reg = _build_ai_registry()
        service = PredictionService(model_registry=reg)

        record = tracking_db.get_patient_full_record(patient_id)
        if not record:
            return jsonify({"success": False, "error": "Paciente no encontrado"}), 404

        model_status = reg.get_metadata("deep_surv")
        result = service.predict_survival(patient_id, record)
        if result is None:
            return jsonify({
                "success": False,
                "error": "Modelo no disponible o flag desactivado",
                "advisory_api": True,
                "rule_based_source_of_truth": True,
                "model_status": model_status,
            }), 503

        return jsonify({
            "success": True,
            "advisory_api": True,
            "rule_based_source_of_truth": True,
            "prediction": result,
            "model_status": model_status,
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/ai/predict/anomaly/<int:patient_id>", methods=["POST"])
def ai_predict_anomaly(patient_id):
    """Detect anomalies in temporal lab series."""
    try:
        from prostanet.ai.inference.prediction_service import PredictionService

        reg = _build_ai_registry()
        service = PredictionService(model_registry=reg)

        record = tracking_db.get_patient_full_record(patient_id)
        if not record:
            return jsonify({"success": False, "error": "Paciente no encontrado"}), 404

        model_status = reg.get_metadata("anomaly_detector")
        result = service.predict_anomalies(patient_id, record)
        if result is None:
            return jsonify({
                "success": False,
                "error": "Modelo no disponible o flag desactivado",
                "advisory_api": True,
                "rule_based_source_of_truth": True,
                "model_status": model_status,
            }), 503

        return jsonify({
            "success": True,
            "advisory_api": True,
            "rule_based_source_of_truth": True,
            "prediction": result,
            "model_status": model_status,
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/agents/run/<agent_id>/<int:patient_id>", methods=["POST"])
def run_agent(agent_id, patient_id):
    """Run a specific agent for a patient."""
    try:
        from prostanet.agents.contracts import AgentInput
        from datetime import UTC, datetime
        from prostanet.ai.config import get_ai_config

        record = tracking_db.get_patient_full_record(patient_id)
        if not record:
            return jsonify({"success": False, "error": "Paciente no encontrado"}), 404

        data = request.get_json(silent=True) or {}
        trigger_event = data.get("trigger_event", "manual")

        agent_input = AgentInput(
            patient_id=patient_id,
            record=record,
            trigger_event=trigger_event,
            trigger_data=data.get("trigger_data", {}),
            timestamp=datetime.now(UTC).isoformat(),
        )

        reg = _build_ai_registry()
        agent = _instantiate_agent(agent_id, model_registry=reg)
        if not agent:
            return jsonify({"success": False, "error": f"Agente '{agent_id}' no encontrado"}), 404

        from dataclasses import asdict
        output = agent.evaluate_safe(agent_input)
        return jsonify({
            "success": True,
            "runtime_mode": get_ai_config().runtime_mode,
            "rule_based_source_of_truth": True,
            "advisory_api": True,
            "output": asdict(output),
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/agents/audit/<int:patient_id>")
def agent_audit(patient_id):
    """Retrieve agent audit trail for a patient."""
    try:
        from prostanet.engine.audit_log import AuditLogger
        limit = request.args.get("limit", 50, type=int)
        audit = AuditLogger()
        entries = audit.get_patient_audit(patient_id, limit=limit)
        return jsonify({"success": True, "entries": entries})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/agents/recommendation/<int:patient_id>/latest")
def latest_recommendation(patient_id):
    """Get the latest CDA recommendation for a patient."""
    try:
        from prostanet.engine.audit_log import AuditLogger
        audit = AuditLogger()
        rec = audit.get_latest_recommendation(patient_id)
        if not rec:
            return jsonify({"success": False, "error": "No hay recomendaciones"}), 404
        return jsonify({"success": True, "recommendation": rec})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/ai/progression-dashboard/<patient_ref>")
def ai_progression_dashboard(patient_ref):
    """
    Complete disease progression dashboard for longitudinal visualization.

    Returns a unified payload with:
      - PSA time series (observed + trend)
      - State timeline with durations
      - Survival curves (if AI model available)
      - Treatment history + response
      - Risk factor heatmap
      - Natural history summary
      - Upcoming milestone alerts
    """
    try:
        resolved, error = _resolve_patient_api_ref(patient_ref)
        if error:
            return error
        patient_id = resolved["patient_id"]
        record = tracking_db.get_patient_full_record(patient_id)
        if not record:
            return jsonify({"success": False, "error": "Paciente no encontrado"}), 404

        # Natural history
        from prostanet.domains.patient_tracking.natural_history_tracker import (
            analyze_natural_history, NaturalHistoryTracker,
        )
        history = analyze_natural_history(record)

        # PSA time series for chart
        follow_ups = record.get("follow_ups", []) or []
        psa_series = [
            {
                "date": fu.get("visit_date"),
                "psa": fu.get("psa_current"),
                "testosterone": fu.get("testosterone_current"),
                "ecog": fu.get("ecog_current") or fu.get("ecog"),
            }
            for fu in sorted(follow_ups, key=lambda x: x.get("visit_date", ""))
            if fu.get("psa_current") is not None
        ]

        # State timeline for Gantt-style chart
        state_timeline = record.get("state_timeline", []) or []

        # Treatment response timeline
        tx_history = history.get("treatment_history", [])

        # Milestone alerts
        milestones = _build_milestone_alerts(record, history)

        # Risk factor radar
        risk_summary = history.get("risk_summary", {})

        # Survival predictions from AI if available
        survival_curves = {}
        try:
            from prostanet.shared.feature_flags import resolve_feature_flags
            if resolve_feature_flags().get("ENABLE_AI_SURVIVAL_MODEL"):
                from prostanet.ai.inference.prediction_service import PredictionService
                from prostanet.ai.inference.model_registry import ModelRegistry
                from pathlib import Path
                reg = ModelRegistry(models_dir=Path("output/models"))
                reg.load_all_available()
                service = PredictionService(model_registry=reg)
                survival_curves = service.predict_survival(patient_id, record) or {}
        except Exception:
            pass

        return jsonify({
            "success": True,
            "patient_id": patient_id,
            "resolved_patient_ref": resolved.get("nss") or resolved.get("patient_ref") or str(patient_ref),
            "psa_series": psa_series,
            "state_timeline": state_timeline,
            "treatment_history": tx_history,
            "natural_history_summary": {
                "current_state": history.get("current_state"),
                "time_since_diagnosis_months": history.get("time_since_diagnosis_months"),
                "adjusted_os_months": history.get("adjusted_os_months"),
                "psa_nadir": history.get("psa_nadir"),
                "psa_doubling_time_months": history.get("psa_doubling_time_months"),
                "predicted_next_state": history.get("predicted_next_state"),
                "predicted_time_to_transition_months": history.get("predicted_time_to_transition_months"),
                "flags": history.get("flags", []),
                "narrative": history.get("narrative", ""),
            },
            "risk_summary": risk_summary,
            "survival_curves": survival_curves,
            "milestone_alerts": milestones,
            "ethnicity": history.get("ethnicity"),
            "cci": history.get("comorbidity_cci"),
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


def _build_milestone_alerts(
    record: dict, history: dict
) -> list[dict]:
    """Build upcoming clinical milestone alerts."""
    alerts = []
    state = history.get("current_state", "")
    psadt = history.get("psa_doubling_time_months")
    pred_next = history.get("predicted_next_state")
    pred_time = history.get("predicted_time_to_transition_months")

    if psadt and psadt < 6:
        alerts.append({
            "type": "psa_kinetics",
            "severity": "critical",
            "title": "PSADT crítico",
            "message": f"PSADT {psadt} meses — evaluar progresión y cambio terapéutico",
            "timeframe_months": psadt,
        })

    if pred_next and pred_time:
        alerts.append({
            "type": "state_transition",
            "severity": "warning",
            "title": f"Transición predicha → {pred_next}",
            "message": f"El modelo predice transición a {pred_next} en ~{pred_time} meses",
            "timeframe_months": pred_time,
        })

    if state == "m0_crpc":
        alerts.append({
            "type": "imaging",
            "severity": "info",
            "title": "Imagen cada 6 meses en M0-CPRC",
            "message": "PSMA-PET o gammagrafía ósea según NCCN para detección M1",
            "timeframe_months": 6,
        })

    if state in ("m1_crpc",):
        alerts.append({
            "type": "palliative",
            "severity": "info",
            "title": "Evaluar cuidado paliativo",
            "message": "En CPRC metastásico: considerar referencia a cuidados paliativos",
            "timeframe_months": 1,
        })

    return sorted(alerts, key=lambda x: x.get("timeframe_months", 99))


@modular_api.route("/api/ai/natural-history/<patient_ref>")
def ai_natural_history(patient_ref):
    """
    Complete disease natural history analysis.

    Returns the full longitudinal trajectory from diagnosis to current state,
    survival estimates adjusted for comorbidities and ethnicity,
    predicted next transition, PSA kinetics, and risk factors.
    """
    try:
        resolved, error = _resolve_patient_api_ref(patient_ref)
        if error:
            return error
        patient_id = resolved["patient_id"]
        record = tracking_db.get_patient_full_record(patient_id)
        if not record:
            return jsonify({"success": False, "error": "Paciente no encontrado"}), 404

        from prostanet.domains.patient_tracking.natural_history_tracker import (
            analyze_natural_history,
        )
        report = analyze_natural_history(record)
        return jsonify({
            "success": True,
            "patient_id": patient_id,
            "resolved_patient_ref": resolved.get("nss") or resolved.get("patient_ref") or str(patient_ref),
            "natural_history": report,
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/cohort/overview")
def cohort_overview():
    """Population-level cohort overview: size, state distribution, vital status."""
    try:
        from prostanet.domains.research_intelligence.cohort_progression_analytics import (
            CohortProgressionAnalytics,
        )
        analytics = CohortProgressionAnalytics()
        return jsonify({"success": True, "overview": analytics.compute_overview()})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/cohort/transition-matrix")
def cohort_transition_matrix():
    """Empirical state transition probabilities from real patient data."""
    try:
        from prostanet.domains.research_intelligence.cohort_progression_analytics import (
            CohortProgressionAnalytics,
        )
        analytics = CohortProgressionAnalytics()
        return jsonify({"success": True, **analytics.compute_transition_matrix()})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/cohort/treatment-outcomes")
def cohort_treatment_outcomes():
    """Treatment outcome statistics (PSA50, duration, response) across cohort."""
    try:
        from prostanet.domains.research_intelligence.cohort_progression_analytics import (
            CohortProgressionAnalytics,
        )
        state = request.args.get("state")
        min_n = request.args.get("min_n", 3, type=int)
        analytics = CohortProgressionAnalytics()
        return jsonify({
            "success": True,
            **analytics.compute_treatment_outcomes(state=state, min_n=min_n),
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/cohort/risk-stratification")
def cohort_risk_stratification():
    """Cohort risk stratification by ethnicity, age, CCI, and ISUP grade."""
    try:
        from prostanet.domains.research_intelligence.cohort_progression_analytics import (
            CohortProgressionAnalytics,
        )
        analytics = CohortProgressionAnalytics()
        return jsonify({
            "success": True,
            **analytics.compute_risk_stratification(),
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/engine/recalculate/<int:patient_id>", methods=["POST"])
def engine_recalculate(patient_id):
    """Trigger full recalculation pipeline for a patient."""
    try:
        from prostanet.engine.recalculation_pipeline import RecalculationPipeline

        data = request.get_json(silent=True) or {}
        trigger_event = data.get("trigger_event", "manual")

        reg = _build_ai_registry()
        pipeline = RecalculationPipeline(model_registry=reg)
        result = pipeline.run(
            patient_id=patient_id,
            trigger_event=trigger_event,
            trigger_data=data.get("trigger_data", {}),
        )
        return jsonify({"success": True, "result": result})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/engine/confidence/<int:patient_id>")
def engine_confidence(patient_id):
    """Get current confidence score for a patient."""
    try:
        from prostanet.engine.confidence_scoring import ConfidenceScorer

        record = tracking_db.get_patient_full_record(patient_id)
        if not record:
            return jsonify({"success": False, "error": "Paciente no encontrado"}), 404

        scorer = ConfidenceScorer()
        result = scorer.score(record)
        return jsonify({"success": True, "confidence": result})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/ai/models")
def ai_models_list():
    """List available AI models and their status."""
    try:
        from prostanet.ai.config import get_ai_config
        from prostanet.domains.patient_tracking.reconciled_state import build_reconciled_state

        reg = _build_ai_registry()
        return jsonify({
            "success": True,
            "runtime_mode": get_ai_config().runtime_mode,
            "rule_based_source_of_truth": True,
            "models": reg.list_models(),
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


def _instantiate_agent(agent_id: str, **kwargs):
    """Create agent by ID string."""
    agents = {
        "clinical_decision_agent": "prostanet.agents.clinical_decision_agent:ClinicalDecisionAgent",
        "progression_surveillance_agent": "prostanet.agents.progression_surveillance_agent:ProgressionSurveillanceAgent",
        "treatment_optimization_agent": "prostanet.agents.treatment_optimization_agent:TreatmentOptimizationAgent",
        "quality_assurance_agent": "prostanet.agents.quality_assurance_agent:QualityAssuranceAgent",
        "research_intelligence_agent": "prostanet.agents.research_intelligence_agent:ResearchIntelligenceAgent",
    }
    spec = agents.get(agent_id)
    if not spec:
        return None
    module_path, class_name = spec.rsplit(":", 1)
    import importlib
    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    try:
        return cls(**kwargs)
    except TypeError:
        return cls()


# ══════════════════════════════════════════════════════════════
# Full Clinical Intelligence Pipeline — "Elimina al médico de
# primer contacto": runs all 5 agents + confidence scoring
# + guideline validation in a single call.
# ══════════════════════════════════════════════════════════════


@modular_api.route("/api/crpc-copilot/<patient_ref>", methods=["GET"])
def crpc_copilot_bundle(patient_ref):
    try:
        resolved, error = _resolve_patient_api_ref(patient_ref)
        if error:
            return error
        patient_id = resolved["patient_id"]
        record = tracking_db.get_patient_full_record(patient_id)
        if not record:
            return jsonify({"success": False, "error": "Paciente no encontrado"}), 404
        bundle = _build_crpc_copilot_payload(patient_id)
        return jsonify(
            {
                "success": True,
                "patient_id": patient_id,
                "resolved_patient_ref": resolved.get("nss") or resolved.get("patient_ref") or str(patient_ref),
                "crpc_decision_bundle": bundle,
            }
        )
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/post-rp-copilot/<patient_ref>", methods=["GET"])
def post_rp_copilot_bundle(patient_ref):
    try:
        resolved, error = _resolve_patient_api_ref(patient_ref)
        if error:
            return error
        patient_id = resolved["patient_id"]
        record = tracking_db.get_patient_full_record(patient_id)
        if not record:
            return jsonify({"success": False, "error": "Paciente no encontrado"}), 404
        bundle = _build_post_rp_salvage_payload(patient_id)
        return jsonify(
            {
                "success": True,
                "patient_id": patient_id,
                "resolved_patient_ref": resolved.get("nss") or resolved.get("patient_ref") or str(patient_ref),
                "post_rp_decision_bundle": bundle,
            }
        )
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/mhspc-copilot/<patient_ref>", methods=["GET"])
def mhspc_copilot_bundle(patient_ref):
    try:
        resolved, error = _resolve_patient_api_ref(patient_ref)
        if error:
            return error
        patient_id = resolved["patient_id"]
        record = tracking_db.get_patient_full_record(patient_id)
        if not record:
            return jsonify({"success": False, "error": "Paciente no encontrado"}), 404
        bundle = _build_mhspc_copilot_payload(patient_id)
        return jsonify(
            {
                "success": True,
                "patient_id": patient_id,
                "resolved_patient_ref": resolved.get("nss") or resolved.get("patient_ref") or str(patient_ref),
                "mhspc_decision_bundle": bundle,
            }
        )
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/diagnostic-copilot/<patient_ref>", methods=["GET"])
def diagnostic_copilot_bundle(patient_ref):
    try:
        resolved, error = _resolve_patient_api_ref(patient_ref)
        if error:
            return error
        patient_id = resolved["patient_id"]
        record = tracking_db.get_patient_full_record(patient_id)
        if not record:
            return jsonify({"success": False, "error": "Paciente no encontrado"}), 404
        bundle = _build_diagnostic_biopsy_payload(patient_id)
        return jsonify(
            {
                "success": True,
                "patient_id": patient_id,
                "resolved_patient_ref": resolved.get("nss") or resolved.get("patient_ref") or str(patient_ref),
                "diagnostic_decision_bundle": bundle,
            }
        )
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/localized-copilot/<patient_ref>", methods=["GET"])
def localized_copilot_bundle(patient_ref):
    try:
        resolved, error = _resolve_patient_api_ref(patient_ref)
        if error:
            return error
        patient_id = resolved["patient_id"]
        record = tracking_db.get_patient_full_record(patient_id)
        if not record:
            return jsonify({"success": False, "error": "Paciente no encontrado"}), 404
        bundle = _build_localized_surveillance_payload(patient_id)
        return jsonify(
            {
                "success": True,
                "patient_id": patient_id,
                "resolved_patient_ref": resolved.get("nss") or resolved.get("patient_ref") or str(patient_ref),
                "localized_decision_bundle": bundle,
            }
        )
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/post-rt-copilot/<patient_ref>", methods=["GET"])
def post_rt_copilot_bundle(patient_ref):
    try:
        resolved, error = _resolve_patient_api_ref(patient_ref)
        if error:
            return error
        patient_id = resolved["patient_id"]
        record = tracking_db.get_patient_full_record(patient_id)
        if not record:
            return jsonify({"success": False, "error": "Paciente no encontrado"}), 404
        bundle = _build_post_rt_salvage_payload(patient_id)
        return jsonify(
            {
                "success": True,
                "patient_id": patient_id,
                "resolved_patient_ref": resolved.get("nss") or resolved.get("patient_ref") or str(patient_ref),
                "post_rt_decision_bundle": bundle,
            }
        )
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/ai/full-assessment/<patient_ref>", methods=["POST"])
def ai_full_assessment(patient_ref):
    """
    Complete AI clinical assessment.

    Runs the full 5-agent pipeline:
      1. QAA — data quality & safety validation
      2. PSA — PSA kinetics & surveillance
      3. CDA — clinical decision recommendation
      4. TOA — treatment optimization & ranking
      5. RIA — research & trial matching

    Returns a consolidated clinical intelligence report.
    """
    from datetime import UTC, datetime
    from dataclasses import asdict
    import time

    t_start = time.perf_counter()
    try:
        from prostanet.ai.config import get_ai_config
        from prostanet.domains.patient_tracking.reconciled_state import build_reconciled_state

        resolved, error = _resolve_patient_api_ref(patient_ref)
        if error:
            return error
        patient_id = resolved["patient_id"]
        record = tracking_db.get_patient_full_record(patient_id)
        if not record:
            return jsonify({"success": False, "error": "Paciente no encontrado"}), 404

        data = request.get_json(silent=True) or {}
        trigger_event = data.get("trigger_event", "manual_full_assessment")
        runtime_mode = get_ai_config().runtime_mode
        longitudinal_bundle = tracking_db.refresh_longitudinal_intelligence(
            patient_id,
            force_recompute=False,
            record=record,
            include_live_benchmark=False,
        ) or {}

        from prostanet.agents.contracts import AgentInput
        agent_input = AgentInput(
            patient_id=patient_id,
            record=record,
            trigger_event=trigger_event,
            trigger_data=data.get("trigger_data", {}),
            timestamp=datetime.now(UTC).isoformat(),
        )

        # Run agents in clinical priority order
        agent_order = [
            "quality_assurance_agent",   # Safety gate first
            "progression_surveillance_agent",  # Detect alerts
            "clinical_decision_agent",   # Core clinical logic
            "treatment_optimization_agent",    # Treatment ranking
            "research_intelligence_agent",     # Trial matching
        ]

        outputs = {}
        alerts_all = []
        recommendations_all = []
        reg = _build_ai_registry()

        for agent_id in agent_order:
            agent = _instantiate_agent(agent_id, model_registry=reg)
            if agent is None:
                continue
            try:
                out = agent.evaluate_safe(agent_input)
                outputs[agent_id] = asdict(out)
                alerts_all.extend(out.alerts or [])
                recommendations_all.extend(out.recommendations or [])
            except Exception as exc:
                outputs[agent_id] = {"error": str(exc)}

        # Confidence scoring
        confidence_result = {}
        try:
            from prostanet.engine.confidence_scoring import ConfidenceScorer
            scorer = ConfidenceScorer()
            confidence_result = scorer.score(record, list(outputs.values()))
        except Exception:
            pass

        # Clinical explanation
        explanation = {}
        try:
            from prostanet.engine.explanation_engine import ExplanationEngine
            engine = ExplanationEngine()
            state = record.get("latest_assessment", {}).get("state") or ""
            explanation = engine.explain(record, state=state)
        except Exception:
            pass

        elapsed_ms = round((time.perf_counter() - t_start) * 1000)

        # Serialize alerts + recommendations
        def _to_dict(obj):
            if hasattr(obj, "__dataclass_fields__"):
                return asdict(obj)
            return obj

        cda_output = outputs.get("clinical_decision_agent")
        qa_validation = _validate_cda_output(cda_output, record)
        rule_based_recommendation = _build_rule_based_recommendation(record)
        from prostanet.domains.patient_tracking.vertical_runtime import (
            build_decision_delta_since_last_visit,
            build_evidence_basis_current_visit,
            build_histopathology_summary,
            build_runtime_patient,
            build_runtime_payload,
            build_shared_metastatic_summary,
            derive_display_sequence_summary,
            select_primary_vertical_bundle,
        )

        crpc_decision_bundle = _build_crpc_copilot_payload(patient_id, longitudinal_bundle=longitudinal_bundle)
        post_rp_decision_bundle = _build_post_rp_salvage_payload(patient_id, longitudinal_bundle=longitudinal_bundle)
        mhspc_decision_bundle = _build_mhspc_copilot_payload(patient_id, longitudinal_bundle=longitudinal_bundle)
        diagnostic_decision_bundle = _build_diagnostic_biopsy_payload(patient_id, longitudinal_bundle=longitudinal_bundle)
        localized_decision_bundle = _build_localized_surveillance_payload(patient_id, longitudinal_bundle=longitudinal_bundle)
        post_rt_decision_bundle = _build_post_rt_salvage_payload(patient_id, longitudinal_bundle=longitudinal_bundle)
        vertical_bundles = {
            "crpc_decision_bundle": crpc_decision_bundle,
            "post_rp_decision_bundle": post_rp_decision_bundle,
            "mhspc_decision_bundle": mhspc_decision_bundle,
            "diagnostic_decision_bundle": diagnostic_decision_bundle,
            "localized_decision_bundle": localized_decision_bundle,
            "post_rt_decision_bundle": post_rt_decision_bundle,
        }
        _, active_vertical_bundle = select_primary_vertical_bundle(vertical_bundles)
        ai_advisory_overlay = {
            "mode": runtime_mode,
            "qa_validation": qa_validation,
            "confidence": confidence_result,
            "agents_run": list(outputs.keys()),
            "recommendations": [_to_dict(r) for r in recommendations_all],
            "alerts": [_to_dict(a) for a in alerts_all],
            "crpc_copilot_status": crpc_decision_bundle.get("status", "not_applicable"),
            "post_rp_copilot_status": post_rp_decision_bundle.get("status", "not_applicable"),
            "mhspc_copilot_status": mhspc_decision_bundle.get("status", "not_applicable"),
            "diagnostic_copilot_status": diagnostic_decision_bundle.get("status", "not_applicable"),
            "localized_copilot_status": localized_decision_bundle.get("status", "not_applicable"),
            "post_rt_copilot_status": post_rt_decision_bundle.get("status", "not_applicable"),
        }
        for overlay_key, bundle in (
            ("crpc_copilot", crpc_decision_bundle),
            ("post_rp_salvage_copilot", post_rp_decision_bundle),
            ("mhspc_copilot", mhspc_decision_bundle),
            ("diagnostic_biopsy_copilot", diagnostic_decision_bundle),
            ("localized_surveillance_copilot", localized_decision_bundle),
            ("post_rt_salvage_copilot", post_rt_decision_bundle),
        ):
            if bundle.get("available"):
                ai_advisory_overlay[overlay_key] = bundle
        if active_vertical_bundle.get("available"):
            rule_based_recommendation = active_vertical_bundle.get("rule_based_recommendation") or rule_based_recommendation
            ai_advisory_overlay["qa_validation"] = active_vertical_bundle.get("qa_validation") or qa_validation
            ai_advisory_overlay["active_vertical_bundle"] = active_vertical_bundle
            ai_advisory_overlay["sequence_summary"] = derive_display_sequence_summary(active_vertical_bundle)
        top_recommendation = ai_advisory_overlay["recommendations"][0] if ai_advisory_overlay["recommendations"] else None
        can_present_advisory = (
            runtime_mode == "advisory"
            and bool(top_recommendation)
            and (
                ai_advisory_overlay.get("qa_validation") is None
                or ai_advisory_overlay.get("qa_validation", {}).get("approved", False)
            )
        )
        final_presented_recommendation = (
            {
                "source": "rule_based_plus_ai_advisory",
                "state": rule_based_recommendation.get("state", ""),
                "primary_recommendation": top_recommendation,
                "qa_passed": (
                    ai_advisory_overlay.get("qa_validation", {}).get("approved", False)
                    if ai_advisory_overlay.get("qa_validation")
                    else None
                ),
            }
            if can_present_advisory
            else rule_based_recommendation
        )
        active_vertical_status = str(active_vertical_bundle.get("status") or "").strip().lower()
        if active_vertical_bundle.get("available") and active_vertical_status not in {
            "",
            "shadow",
            "shadow-blocked",
            "unavailable",
            "not_applicable",
            "advisory_candidate",
        }:
            final_presented_recommendation = (
                active_vertical_bundle.get("final_presented_recommendation")
                or final_presented_recommendation
            )
        signals_snapshot = dict(record.get("latest_signal_snapshot") or {})
        reconciliation_snapshot = build_reconciled_state(record, record.get("latest_assessment"))
        progression_gate_active = bool(
            active_vertical_bundle.get("progression_gate_active")
            or signals_snapshot.get("progression_gate_active")
            or reconciliation_snapshot.get("progression_gate_active")
        )
        progression_gate_target = (
            active_vertical_bundle.get("progression_gate_target")
            or signals_snapshot.get("progression_gate_target")
            or reconciliation_snapshot.get("progression_gate_target")
            or ""
        )
        progression_gate_reason = (
            active_vertical_bundle.get("progression_gate_reason")
            or signals_snapshot.get("progression_gate_reason")
            or reconciliation_snapshot.get("progression_gate_reason")
            or ""
        )
        systemic_progression_context_resolved = (
            active_vertical_bundle.get("systemic_progression_context_resolved")
            or signals_snapshot.get("systemic_progression_context_resolved")
            or reconciliation_snapshot.get("systemic_progression_context_resolved")
            or "none"
        )
        phenotype_state = (
            active_vertical_bundle.get("phenotype_state")
            or signals_snapshot.get("phenotype_state")
            or reconciliation_snapshot.get("phenotype_state")
            or record.get("latest_signal_snapshot", {}).get("phenotype_state", "")
        )

        if progression_gate_active and not str(final_presented_recommendation.get("recommended_action") or "").strip():
            final_presented_recommendation = {
                "source": progression_gate_target or "adt_progression_verification",
                "state_family": phenotype_state or active_vertical_bundle.get("state_family") or "",
                "recommended_action": "Confirmar testosterona en rango de castración y reestadificación convencional antes de intensificar la enfermedad metastásica.",
                "rationale": progression_gate_reason or "El fenotipo metastásico ya está resuelto, pero la progresión resistente sigue bloqueada hasta cerrar castración y reestadificación.",
                "systemic_progression_context_resolved": systemic_progression_context_resolved,
            }
        runtime_patient = build_runtime_patient(record, None)
        runtime_payload = build_runtime_payload(
            runtime_patient,
            record.get("latest_assessment"),
            effective_state=active_vertical_bundle.get("effective_state") or phenotype_state or "",
        )
        metastatic_composition_summary = (
            active_vertical_bundle.get("metastatic_composition_summary")
            or build_shared_metastatic_summary(runtime_payload)
        )
        blocked_by_overlay = list(active_vertical_bundle.get("blocked_by_overlay") or [])
        decision_delta_since_last_visit = (
            active_vertical_bundle.get("decision_delta_since_last_visit")
            or build_decision_delta_since_last_visit(
                record,
                effective_state=active_vertical_bundle.get("effective_state") or phenotype_state or "",
                phenotype_state=phenotype_state or active_vertical_bundle.get("phenotype_state") or "",
                rule_based_recommendation=rule_based_recommendation,
                final_presented_recommendation=final_presented_recommendation,
                blocking_groups=active_vertical_bundle.get("blocking_inputs") or [],
                blocked_by_overlay=blocked_by_overlay,
            )
        )
        evidence_basis_current_visit = (
            active_vertical_bundle.get("evidence_basis_current_visit")
            or build_evidence_basis_current_visit(
                active_vertical_bundle.get("guideline_basis") or rule_based_recommendation.get("guideline_basis") or [],
                rule_based_recommendation,
                decision_delta_since_last_visit,
            )
        )
        effective_state = (
            active_vertical_bundle.get("effective_state")
            or reconciliation_snapshot.get("reconciled_state")
            or (record.get("latest_assessment") or {}).get("state")
            or ""
        )
        effective_management_track = (
            active_vertical_bundle.get("effective_management_track")
            or reconciliation_snapshot.get("reconciled_management_track")
            or ""
        )
        histopathology_summary = (
            active_vertical_bundle.get("histopathology_summary")
            or build_histopathology_summary(runtime_payload)
            or ""
        )
        qa_validation_top_level = active_vertical_bundle.get("qa_validation") or qa_validation or {}

        return jsonify({
            "success": True,
            "patient_id": patient_id,
            "resolved_patient_ref": resolved.get("nss") or resolved.get("patient_ref") or str(patient_ref),
            "trigger_event": trigger_event,
            "runtime_mode": runtime_mode,
            "rule_based_source_of_truth": True,
            "advisory_api": True,
            "agents_run": list(outputs.keys()),
            "agent_outputs": outputs,
            "consolidated_alerts": [_to_dict(a) for a in alerts_all],
            "consolidated_recommendations": [_to_dict(r) for r in recommendations_all],
            "confidence": confidence_result,
            "explanation": explanation,
            "rule_based_recommendation": rule_based_recommendation,
            "ai_advisory_overlay": ai_advisory_overlay,
            "effective_state": effective_state,
            "effective_management_track": effective_management_track,
            "phenotype_state": phenotype_state,
            "progression_gate_active": progression_gate_active,
            "progression_gate_target": progression_gate_target,
            "progression_gate_reason": progression_gate_reason,
            "systemic_progression_context_resolved": systemic_progression_context_resolved,
            "histopathology_summary": histopathology_summary,
            "metastatic_composition_summary": metastatic_composition_summary,
            "decision_delta_since_last_visit": decision_delta_since_last_visit,
            "blocked_by_overlay": blocked_by_overlay,
            "evidence_basis_current_visit": evidence_basis_current_visit,
            "qa_validation": qa_validation_top_level,
            "crpc_decision_bundle": crpc_decision_bundle,
            "post_rp_decision_bundle": post_rp_decision_bundle,
            "mhspc_decision_bundle": mhspc_decision_bundle,
            "diagnostic_decision_bundle": diagnostic_decision_bundle,
            "localized_decision_bundle": localized_decision_bundle,
            "post_rt_decision_bundle": post_rt_decision_bundle,
            "post_rt_failure_definition": post_rt_decision_bundle.get("post_rt_failure_definition", {}),
            "post_rt_local_salvage_ranking": post_rt_decision_bundle.get("post_rt_local_salvage_ranking", []),
            "post_rt_transition_bundle": post_rt_decision_bundle.get("post_rt_transition_bundle", {}),
            "final_presented_recommendation": final_presented_recommendation,
            "elapsed_ms": elapsed_ms,
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


# ══════════════════════════════════════════════════════════════
# NLP Clinical Document Extraction
# ══════════════════════════════════════════════════════════════


@modular_api.route("/api/ai/nlp/extract", methods=["POST"])
def ai_nlp_extract():
    """
    Extract structured clinical data from unstructured Spanish text.

    Body (JSON):
      - text: raw clinical document text
      - document_type: pathology_report | imaging_report | clinical_note | discharge_summary
      - patient_id: (optional) attach to patient
    """
    try:
        data = request.get_json(silent=True) or {}
        text = data.get("text", "")
        document_type = data.get("document_type", "clinical_note")

        if not text:
            return jsonify({"success": False, "error": "Campo 'text' requerido"}), 400

        from prostanet.ai.models.nlp_extractor import ClinicalNLPExtractor
        extractor = ClinicalNLPExtractor()
        result = extractor.extract(text, document_type=document_type)

        patient_id = data.get("patient_id")
        response = {
            "success": True,
            "entities": result.entities,
            "confidence": result.confidence,
            "document_type": result.document_type,
            "entity_count": len(result.entities),
            "char_count": result.char_count,
        }

        if patient_id:
            response["fieldspec_payload"] = result.to_fieldspec_payload()

        return jsonify(response)
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/ai/nlp/extract/<int:patient_id>", methods=["POST"])
def ai_nlp_extract_for_patient(patient_id):
    """
    Extract and stage clinical data from text, linked to a patient.

    Body: same as /api/ai/nlp/extract
    Returns extraction candidates ready for user review before saving.
    """
    try:
        record = tracking_db.get_patient_full_record(patient_id)
        if not record:
            return jsonify({"success": False, "error": "Paciente no encontrado"}), 404

        data = request.get_json(silent=True) or {}
        text = data.get("text", "")
        document_type = data.get("document_type", "clinical_note")

        if not text:
            return jsonify({"success": False, "error": "Campo 'text' requerido"}), 400

        from prostanet.ai.models.nlp_extractor import ClinicalNLPExtractor
        extractor = ClinicalNLPExtractor()
        extraction = extractor.extract_from_document_ingestion(
            document_text=text,
            patient_id=patient_id,
            document_type=document_type,
        )
        return jsonify({"success": True, **extraction})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 3: SOAP Notes, Treatment Sequencer, Population Watchdog,
#          mCRPC Prognostic Score, Terminal Care Pathway
# ══════════════════════════════════════════════════════════════════════════════


@modular_api.route("/api/ai/soap-note/<int:patient_id>", methods=["POST"])
def ai_soap_note(patient_id: int):
    """
    Generate an autonomous SOAP note for a patient visit.

    Integrates: CAPRA/NCCN scores, natural history, guideline recommendations,
    DDI alerts, trial eligibility, and genomic action items.

    Body (optional JSON):
      visit_context: dict   — additional context from the current visit
    Returns: SOAP note text + structured sections + confidence score.
    """
    try:
        record = tracking_db.get_patient_full_record(patient_id)
        if not record:
            return jsonify({"success": False, "error": "Paciente no encontrado"}), 404

        data = request.get_json(silent=True) or {}
        if data.get("visit_context"):
            record.update(data["visit_context"])

        from prostanet.domains.patient_tracking.soap_note_generator import SOAPNoteGenerator
        generator = SOAPNoteGenerator()
        soap = generator.generate(record)
        return jsonify({"success": True, "soap_note": soap.to_dict()})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/ai/treatment-sequence/<int:patient_id>", methods=["POST"])
def ai_treatment_sequence(patient_id: int):
    """
    Optimized multi-line treatment sequence for a patient.

    Applies:
      - Cross-resistance rules (ARSI → ARSI block)
      - AR-V7 gates (positive → prefer taxane)
      - NEPC pathway detection
      - HRR/PSMA/BRCA biomarker eligibility
      - ECOG/fitness constraints
      - Formulary availability (IMSS/ISSSTE/privado)
      - Evidence levels from ARASENS, PROfound, VISION, TRITON3

    Body (optional JSON):
      override_state: str   — force a specific clinical state
    Returns: SequencePlan with ranked treatment lines + rationale.
    """
    try:
        record = tracking_db.get_patient_full_record(patient_id)
        if not record:
            return jsonify({"success": False, "error": "Paciente no encontrado"}), 404

        data = request.get_json(silent=True) or {}
        if data.get("override_state"):
            record["current_state"] = data["override_state"]

        import dataclasses
        from prostanet.domains.patient_tracking.treatment_sequencer import TreatmentSequencer
        sequencer = TreatmentSequencer()
        plan = sequencer.optimize(record)
        return jsonify({"success": True, "sequence_plan": dataclasses.asdict(plan)})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/ai/population-watchdog", methods=["POST"])
def ai_population_watchdog():
    """
    Run population-level watchdog scan across all active patients.

    Checks:
      - PSA kinetics (PSADT alerts)
      - Testosterone escape in castrate-intent states
      - Safety labs (Hgb, ALP, LDH)
      - Protocol compliance windows
      - Biomarker gaps (HRR, PSMA-PET)
      - Treatment efficacy (PCWG3 / PSA50 response)
      - ECOG deterioration trends
      - AI state transition predictions

    Body (optional JSON):
      state_filter: str   — restrict scan to specific clinical state
      max_patients: int   — limit number of patients scanned (default: 5000)

    Returns: WatchdogReport with prioritized patient alerts.
    Requires: ENABLE_RECALCULATION_ENGINE feature flag ON.
    """
    try:
        data = request.get_json(silent=True) or {}
        state_filter = data.get("state_filter")
        max_patients = int(data.get("max_patients", 5000))

        from prostanet.engine.population_watchdog import PopulationWatchdog
        watchdog = PopulationWatchdog()
        report = watchdog.scan_all(state_filter=state_filter)
        return jsonify({"success": True, "watchdog_report": report})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/ai/population-watchdog/<int:patient_id>", methods=["POST"])
def ai_population_watchdog_patient(patient_id: int):
    """
    Run watchdog scan for a single patient.

    Returns immediate PatientAlert list for the specified patient.
    Faster than full population scan for real-time clinical use.
    """
    try:
        from prostanet.engine.population_watchdog import PopulationWatchdog
        watchdog = PopulationWatchdog()
        alerts = watchdog.scan_patient(patient_id)
        return jsonify({"success": True, "patient_id": patient_id, "alerts": alerts})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/ai/mcrpc-prognosis/<int:patient_id>", methods=["POST"])
def ai_mcrpc_prognosis(patient_id: int):
    """
    ProstaNet mCRPC Integrated Prognostic Score (IPS).

    State-of-the-art prognostic model combining:
      - Halabi 2014 clinical backbone (C-index 0.72, validated in 9,292 patients)
      - AR-V7 status (PROPHECY 2019: HR 2.26 for ARSI)
      - CTC count — CellSearch (de Bono 2008: ≥5 CTC HR 1.76)
      - BRCA2/HRR (PROfound 2020: HR 0.34 with olaparib)
      - MSI-H (KEYNOTE-199: pembrolizumab eligible)
      - PSMA-PET total body volume (VISION 2021)
      - LDH dynamic (direction change as prognostic signal)
    Estimated C-index: 0.77

    Returns: risk_group, median OS, survival probabilities, treatment-modifying
             biomarkers, and actionable next steps.
    """
    try:
        record = tracking_db.get_patient_full_record(patient_id)
        if not record:
            return jsonify({"success": False, "error": "Paciente no encontrado"}), 404

        from prostanet.domains.patient_tracking.halabi_nomogram import predict_mcrpc_prognosis
        result = predict_mcrpc_prognosis(record)
        return jsonify({"success": True, **result})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/ai/terminal-care/<int:patient_id>", methods=["POST"])
def ai_terminal_care(patient_id: int):
    """
    Terminal care pathway assessment for end-stage prostate cancer.

    Evaluates:
      - PCWG3 radiographic and PSA progression criteria
      - Symptom burden (pain, dyspnea, urinary obstruction, fatigue)
      - Emergency alerts (spinal cord compression, hypercalcemia, urosepsis)
      - Evidence-based palliative interventions per symptom cluster
      - Hospice eligibility (≥2/6 criteria including ECOG, Halabi risk group)
      - MDT referral recommendations
      - Goals-of-care determination
      - Prognosis anchor for SPIKES communication framework

    Body (optional JSON):
      include_prognosis: bool  — also run mCRPC IPS (default: true)
    Returns: TerminalCareAssessment with complete palliative care plan.
    """
    try:
        record = tracking_db.get_patient_full_record(patient_id)
        if not record:
            return jsonify({"success": False, "error": "Paciente no encontrado"}), 404

        data = request.get_json(silent=True) or {}
        include_prognosis = data.get("include_prognosis", True)

        # Optionally inject mCRPC IPS so terminal care can use Halabi risk group
        if include_prognosis:
            try:
                from prostanet.domains.patient_tracking.halabi_nomogram import predict_mcrpc_prognosis
                record["halabi_nomogram"] = predict_mcrpc_prognosis(record)
            except Exception:
                pass

        from prostanet.domains.patient_tracking.terminal_care_pathway import TerminalCarePathway
        assessment = TerminalCarePathway.assess(record)
        return jsonify({"success": True, "terminal_care": assessment})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500
