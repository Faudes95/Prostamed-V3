# IEC 62304 §5.5 (Unit verification)
from __future__ import annotations

from prostanet.domains.patient_tracking.master_followup_plan import (
    build_master_followup_plan,
)
from prostanet.domains.patient_tracking.runtime_signal_snapshot_builder import (
    build_runtime_signal_snapshot,
)


def test_runtime_signal_snapshot_projects_decision_evidence_currentness_fields():
    bundle = {
        "signals": {
            "effective_state": "recurrence_bcr",
            "reconciled_state": "recurrence_bcr",
            "metastatic_stage_resolved": "M0",
        },
        "next_best_action": {
            "title": "Activar salvage temprano",
            "rationale": "PSA y ventana de rescate siguen siendo el eje clínico.",
            "recommendation_family": "salvage_rt_family",
        },
        "decision_governance_bundle": {"status": "ready"},
        "decision_evidence_currentness_bundle": {
            "selected_decision_evidence_status": "aging",
            "selected_decision_release_status": "aging_review_needed",
            "refresh_actions": ["Actualizar PSA/PSADT y reestadificación antes de cerrar la ruta de rescate"],
        },
        "guideline_followup_plan": {"schedule_evidence_basis": ["EAU"]},
        "window_worklist_bundle": {},
    }

    projection = build_runtime_signal_snapshot(
        patient_record={"identity": {"id": 501}},
        bundle=bundle,
        latest_snapshot={},
        decision_input_requirements={"blocking_inputs": [], "hard_blocking_inputs": []},
        outcome_bundle={"outcome_events_summary": {"event_count": 0}},
        prognostic_bundle={"prognostic_modifiers": []},
        psa_forecast_bundle={"reliability": {"status": "ok"}},
        live_benchmark_bundle={"reliability": {"status": "ok"}},
        vertical_bundles={
            "active_copilot_bundle": {},
            "crpc_copilot_bundle": {},
            "post_rp_salvage_bundle": {},
            "mhspc_copilot_bundle": {},
            "diagnostic_biopsy_bundle": {},
            "localized_surveillance_bundle": {},
            "post_rt_salvage_bundle": {},
            "current_state": "recurrence_bcr",
            "current_track": "salvage_route",
        },
        kernel_bundles={
            "clinical_fact_bundle": {
                "facts": [{"fact_key": "psa_current", "value": 0.41}],
                "freshness_summary": {"overall_status": "aging"},
            },
            "fact_conflict_summary": {"open_conflicts": 0},
            "contradiction_resolution_bundle": {"block_status": "note", "critical_unresolved_count": 0},
            "state_reclassification_bundle": {"visible": False},
        },
        qa_passed=True,
        sequence_summary={"status": "sequenced"},
        ui_contradiction_flags=[],
    )

    signals = projection["signals"]
    assert signals["effective_state_final"] == "recurrence_bcr"
    assert signals["selected_decision_evidence_status"] == "aging"
    assert signals["selected_decision_release_status"] == "aging_review_needed"
    assert signals["decision_evidence_currentness_bundle"]["refresh_actions"] == [
        "Actualizar PSA/PSADT y reestadificación antes de cerrar la ruta de rescate"
    ]


def test_master_followup_plan_surfaces_decision_currentness_actions_and_gaps():
    plan = build_master_followup_plan(
        patient={"id": 777},
        state="localized_initial",
        management_track="active_surveillance",
        agenda_board={
            "stage_protocol": {
                "title": "Seguimiento localizado",
                "cadence_summary": "Seguimiento con PSA, MRI y confirmación histológica.",
                "evidence_basis": ["EAU 2026 localized disease"],
            },
            "protocol_trace": {
                "anchor_date": "2026-04-01",
                "anchor_source": "stage_visit_records.visit_date",
                "anchor_is_fallback": False,
            },
            "active_items": [
                {
                    "agenda_key": "psa_review",
                    "title": "Actualizar PSA",
                    "status": "due",
                    "due_at": "2026-05-01",
                    "item_type": "lab_panel",
                    "summary": "PSA seriado para sostener vigilancia activa.",
                    "required_inputs": ["psa"],
                }
            ],
            "encounters": [
                {
                    "encounter_key": "localized_review",
                    "title": "Revisión localizada",
                    "status": "scheduled",
                    "due_at": "2026-05-10",
                    "visit_modality": "presential",
                    "tasks": [{"title": "Revisar PSA y MRI"}],
                    "guideline_basis": ["EAU 2026 localized disease"],
                    "decision_domains_covered": ["localized_initial"],
                }
            ],
        },
        signals={
            "decision_evidence_currentness_bundle": {
                "selected_decision_evidence_status": "stale",
                "selected_decision_release_status": "blocked_by_stale_evidence",
                "refresh_actions": ["Actualizar PSA, MRI y soporte confirmatorio antes de sostener la decisión local"],
                "stale_evidence_fields": ["Biopsia confirmatoria realizada"],
                "aging_evidence_fields": ["Fecha de resonancia magnética"],
                "traceability_gaps": ["Clasificador genómico"],
            },
            "therapeutic_readiness_bundle": {},
            "advanced_followup_bundle": {},
            "staging_adjudication_bundle": {},
            "pending_adjudications": [],
            "critical_missing": [],
            "prognostic_capture_targets": [],
            "prognostic_modifiers": [],
            "cadence_adjusted_by": [],
            "backbone_alignment": {},
        },
        copilot_alerts=[],
        next_best_action={"title": "Mantener vigilancia activa"},
        plan_key="localized-currentness-check",
        calendar_horizon_months=12,
    )

    assert plan["summary"]["selected_decision_evidence_status"] == "stale"
    assert plan["summary"]["selected_decision_release_status"] == "blocked_by_stale_evidence"
    assert plan["summary"]["decision_refresh_action_count"] == 1
    assert "Actualizar PSA, MRI y soporte confirmatorio antes de sostener la decisión local" in plan["highlight_actions"]
    assert "Evidencia decisional vencida: Biopsia confirmatoria realizada" in plan["gaps_to_close"]
    assert "Evidencia decisional por revisar: Fecha de resonancia magnética" in plan["gaps_to_close"]
    assert "Brecha de trazabilidad: Clasificador genómico" in plan["gaps_to_close"]


def test_master_followup_plan_surfaces_adjudication_and_supportive_actions_without_contradiction():
    plan = build_master_followup_plan(
        patient={"id": 778},
        state="m0_crpc",
        management_track="systemic_control",
        agenda_board={
            "stage_protocol": {
                "title": "Seguimiento avanzada",
                "cadence_summary": "Seguimiento con imagen, labs y seguridad terapéutica.",
                "evidence_basis": ["EAU 2026 advanced disease"],
            },
            "protocol_trace": {
                "anchor_date": "2026-04-01",
                "anchor_source": "stage_visit_records.visit_date",
                "anchor_is_fallback": False,
            },
            "active_items": [],
            "encounters": [],
        },
        signals={
            "decision_evidence_currentness_bundle": {},
            "therapeutic_readiness_bundle": {
                "readiness_status": "blocked_by_missing_data",
                "candidate_regimen_label": "Darolutamida + ADT",
                "monitoring_gate_status": "supported",
                "adjudication_gate_status": "blocked_by_missing_data",
            },
            "advanced_followup_bundle": {},
            "staging_adjudication_bundle": {
                "concordance_status": "context_changed",
                "adjudication_release_status": "review_needed",
                "recommended_adjudication_actions": [
                    "Reconciliar el upstaging por PSMA con la imagen convencional más reciente."
                ],
                "discordant_fields": ["psma_positive"],
                "superseded_evidence": ["conventional_imaging_status"],
            },
            "supportive_care_toxicity_readiness_bundle": {
                "supportive_readiness_status": "co_manage_required",
                "supportive_priority": "co_primary",
                "required_support_actions": [
                    "Completar evaluación de caídas/cognición y plan de mitigación antes de sostener ARPI."
                ],
                "missing_support_inputs": ["mini_cog_score"],
                "stale_support_inputs": ["hba1c"],
            },
            "pending_adjudications": [
                {"title": "Contexto cambió y requiere adjudicación clínica"}
            ],
            "critical_missing": [],
            "prognostic_capture_targets": [],
            "prognostic_modifiers": [],
            "cadence_adjusted_by": [],
            "backbone_alignment": {},
        },
        copilot_alerts=[],
        next_best_action={"title": "Darolutamida + terapia de privación androgénica"},
        plan_key="advanced-adjudication-support-check",
        calendar_horizon_months=12,
    )

    assert plan["summary"]["adjudication_release_status"] == "review_needed"
    assert plan["summary"]["supportive_readiness_status"] == "co_manage_required"
    assert plan["summary"]["supportive_priority"] == "co_primary"
    assert "Reconciliar el upstaging por PSMA con la imagen convencional más reciente." in plan["highlight_actions"]
    assert "Completar evaluación de caídas/cognición y plan de mitigación antes de sostener ARPI." in plan["highlight_actions"]
    assert "Discordancia clínica: PSMA positivo / negativo dominante" not in plan["gaps_to_close"]
    assert "Discordancia clínica: Expresión global de PSMA" in plan["gaps_to_close"]
    assert "Evidencia superseded: Imagen convencional actual" in plan["gaps_to_close"]
    assert "Soporte requerido: Mini-Cog" in plan["gaps_to_close"]
    assert "Soporte por actualizar: Hemoglobina glucosilada" in plan["gaps_to_close"]
