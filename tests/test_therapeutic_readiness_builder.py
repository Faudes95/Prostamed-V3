# IEC 62304 §5.5 (Unit verification)
from prostanet.domains.patient_tracking.therapeutic_readiness_builder import (
    build_therapeutic_readiness_bundle,
)


def test_readiness_bundle_marks_missing_data_for_salvage_window():
    bundle = build_therapeutic_readiness_bundle(
        state="recurrence_bcr",
        preferred_regimen={
            "family_code": "salvage_rt_family",
            "regimen_code": "SALVAGE_RT_ALONE",
            "regimen_label": "Salvage RT",
            "required_missing_fields": ["psadt_months"],
            "stale_inputs": ["psma_positive"],
        },
        next_best_action={"title": "Cerrar ventana de salvage"},
        decision_input_requirements={
            "hard_blocking_inputs": ["psadt_months"],
            "decision_blocking_inputs": ["psma_positive"],
            "family_missing_inputs": {"salvage_rt_family": ["psadt_months"]},
            "family_stale_inputs": {"salvage_rt_family": ["psma_positive"]},
        },
        comparative_eligibility_matrix={
            "salvage_rt_family": {
                "family_code": "salvage_rt_family",
                "eligibility_status": "conditional",
                "missing_inputs": ["psadt_months"],
                "stale_inputs": ["psma_positive"],
            }
        },
        therapeutic_window_bundle={
            "top_active_window": {
                "window_key": "post_rp_salvage_window",
                "opportunity_loss_risk": "confirmed",
                "what_closes_this_window": "Completar PSADT y restadificación",
            },
            "opportunity_loss_summary": {"critical_windows_open_count": 1},
        },
        recommendation_block_status="hard_stop",
        recommendation_block_reason="Faltan datos críticos que cambian la conducta clínica: psadt_months",
    )

    assert bundle["readiness_status"] == "blocked_by_missing_data"
    assert bundle["candidate_family"] == "salvage_rt_family"
    assert "psadt_months" in bundle["required_to_release"]
    traceability = {item["key"]: item["status"] for item in bundle["traceable_evidence_requirements"]}
    assert traceability["psa_dynamics"] == "missing"


def test_readiness_bundle_marks_ready_when_release_is_clear():
    bundle = build_therapeutic_readiness_bundle(
        state="m0_crpc",
        preferred_regimen={
            "family_code": "arpi_family",
            "regimen_code": "ADT_DAROLUTAMIDE",
            "regimen_label": "ADT + darolutamida",
        },
        comparative_eligibility_matrix={
            "arpi_family": {
                "family_code": "arpi_family",
                "eligibility_status": "eligible",
                "variant_ranking": {"preferred_regimen_code": "ADT_DAROLUTAMIDE"},
            }
        },
        decision_input_requirements={},
        recommendation_block_status="clear",
        recommendation_block_reason="La recomendación tiene los datos mínimos para sostener una conducta visible.",
        signals={"castrate_testosterone_status": "confirmed_castrate"},
    )

    assert bundle["readiness_status"] == "ready_to_release"
    assert bundle["required_to_release"] == []
    assert bundle["candidate_regimen_code"] == "ADT_DAROLUTAMIDE"


def test_readiness_bundle_exposes_aging_review_needed_for_selected_nmcrpc_therapy():
    bundle = build_therapeutic_readiness_bundle(
        state="m0_crpc",
        preferred_regimen={
            "family_code": "arpi_family",
            "regimen_code": "ADT_DAROLUTAMIDE",
            "regimen_label": "ADT + darolutamida",
        },
        comparative_eligibility_matrix={
            "arpi_family": {
                "family_code": "arpi_family",
                "eligibility_status": "eligible",
                "variant_ranking": {"preferred_regimen_code": "ADT_DAROLUTAMIDE"},
            }
        },
        decision_input_requirements={},
        recommendation_block_status="clear",
        recommendation_block_reason="La recomendación tiene los datos mínimos para sostener una conducta visible.",
        signals={
            "testosterone": 18,
            "latest_testosterone_date": "2026-04-10",
            "castrate_testosterone_status": "confirmed_castrate",
            "current_adt_context": "medical_adt_continuous",
            "conventional_imaging_status": "M0",
            "conventional_imaging_date": "2025-12-15",
            "progression_pattern": "biochemical_only",
        },
    )

    assert bundle["selected_therapy_evidence_status"] == "aging"
    assert bundle["selected_therapy_release_status"] == "aging_review_needed"
    assert bundle["release_status_by_therapy"]["ADT_DAROLUTAMIDE"]["refresh_action_needed"] == (
        "Actualizar reestadificación convencional y confirmar castración actual"
    )


def test_readiness_bundle_blocks_by_safety_when_contraindications_exist():
    bundle = build_therapeutic_readiness_bundle(
        state="m1_crpc",
        preferred_regimen={
            "family_code": "taxane_family",
            "regimen_code": "DOCETAXEL",
            "contraindication_reasons": ["Neuropatía periférica grado 3."],
        },
        comparative_eligibility_matrix={
            "taxane_family": {
                "family_code": "taxane_family",
                "eligibility_status": "contraindicated",
                "hard_blocks": ["Neuropatía periférica grado 3."],
            }
        },
        decision_input_requirements={},
        recommendation_block_status="clear",
    )

    assert bundle["readiness_status"] == "blocked_by_safety"
    assert bundle["safety_blockers"] == ["Neuropatía periférica grado 3."]


def test_readiness_bundle_marks_palliative_priority_when_supportive_intent_dominates():
    bundle = build_therapeutic_readiness_bundle(
        state="m1_crpc",
        preferred_regimen={
            "family_code": "psma_rlt_family",
            "regimen_code": "LU177_PSMA617",
            "regimen_label": "Lu-177 PSMA",
        },
        care_intent_contract={
            "care_goal": "Control sintomático dominante",
            "supportive_priority": "dominant",
            "palliative_trigger_status": "redirect_supportive_only",
        },
        palliative_transition_bundle={
            "care_mode": "supportive_only",
            "trigger_status": "redirect_supportive_only",
            "care_goal": "Priorizar alivio sintomático y objetivos de cuidado.",
        },
    )

    assert bundle["readiness_status"] == "palliative_priority"
    assert bundle["competing_intent"]["status"] == "palliative_priority"


def test_readiness_bundle_requires_traceable_molecular_evidence_for_parp():
    bundle = build_therapeutic_readiness_bundle(
        state="m1_crpc",
        preferred_regimen={
            "family_code": "parp_family",
            "regimen_code": "OLAPARIB",
            "regimen_label": "Olaparib",
            "required_missing_fields": ["hrr_status"],
        },
        comparative_eligibility_matrix={
            "parp_family": {
                "family_code": "parp_family",
                "eligibility_status": "conditional",
                "missing_inputs": ["hrr_status"],
            }
        },
        decision_input_requirements={
            "decision_blocking_inputs": ["hrr_status"],
            "family_missing_inputs": {"parp_family": ["hrr_status"]},
        },
        recommendation_block_status="provisional",
        recommendation_block_reason="La recomendación sigue abierta hasta cerrar datos decisionales: hrr_status",
    )

    assert bundle["readiness_status"] == "conditional_pending_closure"
    traceability = {item["key"]: item["status"] for item in bundle["traceable_evidence_requirements"]}
    assert traceability["molecular_traceability"] == "missing"
    assert "hrr_status" in bundle["required_to_release"]


def test_readiness_bundle_keeps_generic_salvage_intent_aligned_with_salvage_rt_family():
    bundle = build_therapeutic_readiness_bundle(
        state="recurrence_bcr",
        preferred_regimen={
            "family_code": "salvage_rt_family",
            "regimen_code": "SALVAGE_RT_ALONE",
            "regimen_label": "Salvage RT",
            "required_missing_fields": ["psadt_months"],
        },
        care_intent_contract={
            "recommendation_family": "salvage",
            "care_goal": "Mantener ventana de rescate curativo abierta.",
        },
        decision_input_requirements={
            "hard_blocking_inputs": ["psadt_months"],
            "family_missing_inputs": {"salvage_rt_family": ["psadt_months"]},
        },
        recommendation_block_status="hard_stop",
        recommendation_block_reason="Faltan datos críticos que cambian la conducta clínica: psadt_months",
    )

    assert bundle["readiness_status"] == "blocked_by_missing_data"
    assert bundle["competing_intent"]["status"] == "aligned"


def test_readiness_bundle_surfaces_psma_as_companion_in_high_risk_post_rp_salvage():
    bundle = build_therapeutic_readiness_bundle(
        state="recurrence_bcr",
        preferred_regimen={
            "family_code": "salvage_rt_family",
            "regimen_code": "SALVAGE_RT_SHORT_HORMONE",
            "regimen_label": "SRT + ADT corta",
        },
        care_intent_contract={
            "recommendation_family": "salvage",
            "care_goal": "Mantener ventana curativa con intensificación local.",
        },
        decision_input_requirements={
            "decision_blocking_inputs": [],
            "family_missing_inputs": {"salvage_rt_family": []},
            "treatment_shaping_companion_inputs": ["psma_pet_done"],
            "treatment_shaping_companion_actions": [
                {
                    "key": "post_rp_salvage_psma_companion",
                    "title": "Completar PSMA PET/CT como companion urgente del salvage",
                    "summary": "La PSMA debe definir lecho solo versus lecho + pelvis, sin retrasar la SRT si sale negativa.",
                    "fields": ["psma_pet_done"],
                    "display_fields_summary": ["PSMA-PET realizada"],
                }
            ],
        },
        recommendation_block_status="clear",
        recommendation_block_reason="La recomendación principal ya tiene datos mínimos para sostener una conducta visible.",
    )

    assert bundle["readiness_status"] == "ready_to_release"
    assert bundle["required_to_release"] == []
    assert bundle["treatment_shaping_companion_inputs"] == ["psma_pet_done"]
    assert bundle["treatment_shaping_companion_actions"][0]["key"] == "post_rp_salvage_psma_companion"
    assert any(
        action["title"] == "Completar PSMA PET/CT como companion urgente del salvage"
        for action in bundle["capture_actions"]
    )


def test_readiness_bundle_prioritizes_residual_adjudication_cta_before_generic_blocks():
    bundle = build_therapeutic_readiness_bundle(
        state="m0_crpc",
        preferred_regimen={
            "family_code": "arpi_family",
            "regimen_code": "ADT_DAROLUTAMIDE",
            "regimen_label": "ADT + darolutamida",
            "required_missing_fields": ["psadt_months"],
        },
        comparative_eligibility_matrix={
            "arpi_family": {
                "family_code": "arpi_family",
                "eligibility_status": "conditional",
                "missing_inputs": ["psadt_months"],
            }
        },
        decision_input_requirements={
            "hard_blocking_inputs": ["psadt_months"],
            "family_missing_inputs": {"arpi_family": ["psadt_months"]},
            "capture_block": {
                "title": "Completar datos críticos para recalcular la conducta",
                "summary": "La decisión actual necesita datos complementarios antes de cerrar la recomendación.",
                "fields": ["psadt_months", "ecog_score"],
                "focus": "arpi_family",
                "capture_target": "followup",
            },
            "palliative_capture_block": {
                "title": "Completar bundle paliativo activo",
                "summary": "Sin activacion paliativa dominante",
                "fields": ["fatigue_score", "pain"],
                "focus": "palliative_support",
                "capture_target": "followup",
            },
        },
        advanced_release_gate={
            "hard_blocking_inputs": ["conventional_imaging_status", "psma_positive"],
            "decision_blocking_inputs": [],
            "confidence_decay_inputs": [],
            "release_gate_reasons": [
                "La adjudicación M0/M1 sigue incompleta o discordante; no debe liberarse el carril nmCRPC todavía."
            ],
            "confidence_decay_reasons": [],
            "monitoring_gate_status": "blocked_by_missing_data",
            "adjudication_gate_status": "blocked_by_missing_data",
            "release_confidence_status": "blocked",
        },
        staging_adjudication_bundle={
            "available": True,
            "psma_only_upstaging": True,
            "concordance_status": "context_changed",
            "adjudication_release_status": "review_needed",
            "superseded_evidence": ["conventional_imaging_status", "psma_positive"],
            "missing_critical_inputs": [],
            "capture_actions": [],
        },
        recommendation_block_status="hard_stop",
        recommendation_block_reason="Faltan datos críticos que cambian la conducta clínica: psadt_months",
    )

    actions = list(bundle["capture_actions"] or [])
    assert actions[0]["key"] == "therapeutic_readiness_remaining_gate_fields"
    assert actions[0]["raw_fields"] == ["conventional_imaging_status", "psma_positive"]
    assert actions[1]["key"] == "capture_block"
