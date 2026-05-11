# IEC 62304 §5.5 (Unit verification)
from prostanet.domains.patient_tracking.advanced_release_gate_builder import (
    build_advanced_release_gate,
    merge_advanced_release_gate_into_requirements,
)
from prostanet.domains.patient_tracking.therapeutic_readiness_builder import (
    build_therapeutic_readiness_bundle,
)


def _build_readiness_for_gate(
    *,
    state: str,
    candidate_family: str,
    advanced_followup_bundle: dict,
    staging_adjudication_bundle: dict,
    decision_input_requirements: dict | None = None,
) -> tuple[dict, dict]:
    decision_input_requirements = dict(decision_input_requirements or {})
    gate = build_advanced_release_gate(
        state=state,
        next_best_action={"recommendation_family": candidate_family, "title": "Siguiente paso"},
        candidate_family=candidate_family,
        decision_input_requirements=decision_input_requirements,
        advanced_followup_bundle=advanced_followup_bundle,
        staging_adjudication_bundle=staging_adjudication_bundle,
        signals={"restaging_update_required": staging_adjudication_bundle.get("restaging_update_required")},
    )
    merged = merge_advanced_release_gate_into_requirements(decision_input_requirements, gate)
    readiness = build_therapeutic_readiness_bundle(
        state=state,
        preferred_regimen={"family_code": candidate_family, "regimen_code": "TEST_REGIMEN", "regimen_label": "Test regimen"},
        next_best_action={"title": "Liberar tratamiento", "recommendation_family": candidate_family},
        decision_input_requirements=merged,
        recommendation_block_status="hard_stop" if gate.get("hard_blocking_inputs") else "provisional" if gate.get("decision_blocking_inputs") else "clear",
        recommendation_block_reason=(gate.get("release_gate_reasons") or [""])[0],
        advanced_followup_bundle=advanced_followup_bundle,
        staging_adjudication_bundle=staging_adjudication_bundle,
        advanced_release_gate=gate,
    )
    return gate, readiness


def test_adt_progression_gate_blocks_release_without_testosterone_confirmation():
    gate, readiness = _build_readiness_for_gate(
        state="adt_progression_verification",
        candidate_family="arpi_family",
        advanced_followup_bundle={
            "available": True,
            "confidence_status": "degraded_by_missing_data",
            "missing_inputs": ["testosterone", "testosterone_history", "dxa_baseline_done"],
            "capture_actions": [{"key": "advanced", "title": "Completar seguimiento", "fields": ["testosterone", "testosterone_history"]}],
        },
        staging_adjudication_bundle={"available": True, "missing_critical_inputs": [], "capture_actions": []},
    )

    assert "testosterone" in gate["hard_blocking_inputs"]
    assert readiness["readiness_status"] == "blocked_by_missing_data"
    assert readiness["monitoring_gate_status"] == "blocked_by_missing_data"
    assert readiness["recommendation_block_status"] == "hard_stop"
    assert any("testosterona" in blocker.lower() for blocker in readiness["release_blockers"])


def test_m0_crpc_gate_blocks_release_on_psma_only_upstaging():
    gate, readiness = _build_readiness_for_gate(
        state="m0_crpc",
        candidate_family="arpi_family",
        advanced_followup_bundle={"available": True, "confidence_status": "supported", "missing_inputs": [], "capture_actions": []},
        staging_adjudication_bundle={
            "available": True,
            "psma_only_upstaging": True,
            "concordance_status": "context_changed",
            "adjudication_release_status": "review_needed",
            "superseded_evidence": ["conventional_imaging_status", "psma_positive"],
            "missing_critical_inputs": [],
            "capture_actions": [{"key": "staging", "title": "Cerrar adjudicación", "fields": ["conventional_imaging_status", "psma_positive"]}],
        },
    )

    assert gate["adjudication_gate_status"] == "blocked_by_missing_data"
    assert readiness["readiness_status"] == "blocked_by_missing_data"
    assert "conventional_imaging_status" in readiness["required_to_release"]
    assert any("adjudicación m0/m1" in blocker.lower() for blocker in readiness["release_blockers"])


def test_m0_crpc_gate_degrades_to_conditional_when_only_support_followup_is_missing():
    gate, readiness = _build_readiness_for_gate(
        state="m0_crpc",
        candidate_family="arpi_family",
        advanced_followup_bundle={
            "available": True,
            "confidence_status": "degraded_by_missing_data",
            "missing_inputs": ["dxa_baseline_done", "calcium_vitd_started", "hba1c"],
            "capture_actions": [{"key": "advanced", "title": "Completar bundle ADT", "fields": ["dxa_baseline_done", "calcium_vitd_started", "hba1c"]}],
        },
        staging_adjudication_bundle={"available": True, "concordance_status": "concordant", "missing_critical_inputs": [], "capture_actions": []},
    )

    assert gate["hard_blocking_inputs"] == []
    assert readiness["readiness_status"] == "conditional_pending_closure"
    assert readiness["release_confidence_status"] == "degraded"
    assert readiness["monitoring_gate_status"] == "conditional_pending_closure"


def test_m1_crpc_gate_blocks_parp_without_hrr_traceability():
    gate, readiness = _build_readiness_for_gate(
        state="m1_crpc",
        candidate_family="parp_family",
        advanced_followup_bundle={"available": True, "confidence_status": "supported", "missing_inputs": [], "capture_actions": []},
        staging_adjudication_bundle={
            "available": True,
            "concordance_status": "concordant",
            "missing_critical_inputs": ["hrr_status", "hrr_gene", "biomarker_source", "molecular_assay_date"],
            "capture_actions": [{"key": "precision", "title": "Cerrar trazabilidad HRR", "fields": ["hrr_status", "hrr_gene", "biomarker_source", "molecular_assay_date"]}],
        },
    )

    assert set(gate["hard_blocking_inputs"]) >= {"hrr_status", "hrr_gene"}
    assert readiness["readiness_status"] == "blocked_by_missing_data"
    assert any("parp" in blocker.lower() or "hrr" in blocker.lower() for blocker in readiness["release_blockers"])


def test_m1_crpc_gate_blocks_psma_rlt_without_psma_traceability():
    gate, readiness = _build_readiness_for_gate(
        state="m1_crpc",
        candidate_family="psma_rlt_family",
        advanced_followup_bundle={"available": True, "confidence_status": "supported", "missing_inputs": [], "capture_actions": []},
        staging_adjudication_bundle={
            "available": True,
            "concordance_status": "discordant",
            "adjudication_release_status": "blocked_pending_adjudication",
            "discordant_fields": ["psma_positive", "psma_negative_dominant_lesions"],
            "missing_critical_inputs": ["psma_positive", "psma_pet_done"],
            "capture_actions": [{"key": "psma", "title": "Cerrar PSMA", "fields": ["psma_positive", "psma_pet_done"]}],
        },
    )

    assert gate["hard_blocking_inputs"]
    assert readiness["readiness_status"] == "blocked_by_missing_data"
    assert readiness["adjudication_gate_status"] == "blocked_by_missing_data"
    assert any("psma-rlt" in blocker.lower() or "psma" in blocker.lower() for blocker in readiness["release_blockers"])


def test_m1_crpc_gate_degrades_to_conditional_when_restaging_is_outdated_but_precision_is_closed():
    gate, readiness = _build_readiness_for_gate(
        state="m1_crpc",
        candidate_family="arpi_family",
        advanced_followup_bundle={"available": True, "confidence_status": "supported", "missing_inputs": [], "capture_actions": []},
        staging_adjudication_bundle={
            "available": True,
            "concordance_status": "context_changed",
            "adjudication_release_status": "review_needed",
            "superseded_evidence": ["conventional_imaging_status", "psma_pet_done"],
            "restaging_update_required": True,
            "missing_critical_inputs": [],
            "capture_actions": [{"key": "restaging", "title": "Actualizar reestadificación", "fields": ["conventional_imaging_date"]}],
        },
    )

    assert gate["decision_blocking_inputs"]
    assert readiness["readiness_status"] == "conditional_pending_closure"
    assert readiness["release_confidence_status"] == "degraded"


def test_mhspc_gate_degrades_triplet_release_when_fitness_and_ddi_are_missing():
    gate, readiness = _build_readiness_for_gate(
        state="mcspc_high_volume_sync",
        candidate_family="taxane_family",
        advanced_followup_bundle={
            "available": True,
            "confidence_status": "degraded_by_missing_data",
            "missing_inputs": ["mini_cog_score", "g8_score"],
            "capture_actions": [{"key": "frailty", "title": "Completar fragilidad", "fields": ["mini_cog_score", "g8_score"]}],
        },
        staging_adjudication_bundle={"available": True, "concordance_status": "concordant", "missing_critical_inputs": [], "capture_actions": []},
        decision_input_requirements={"decision_blocking_inputs": ["ddi_review_status", "cv_risk_documented"]},
    )

    assert gate["decision_blocking_inputs"]
    assert readiness["readiness_status"] == "conditional_pending_closure"
    assert readiness["monitoring_gate_status"] == "conditional_pending_closure"
    assert readiness["release_confidence_status"] == "degraded"


def test_mhspc_gate_keeps_release_ready_when_dataset_is_complete():
    gate, readiness = _build_readiness_for_gate(
        state="mcspc_high_volume_sync",
        candidate_family="taxane_family",
        advanced_followup_bundle={"available": True, "confidence_status": "supported", "missing_inputs": [], "capture_actions": []},
        staging_adjudication_bundle={"available": True, "concordance_status": "concordant", "missing_critical_inputs": [], "capture_actions": []},
    )

    assert gate["hard_blocking_inputs"] == []
    assert gate["decision_blocking_inputs"] == []
    assert readiness["readiness_status"] == "ready_to_release"
    assert readiness["release_confidence_status"] == "supported"
