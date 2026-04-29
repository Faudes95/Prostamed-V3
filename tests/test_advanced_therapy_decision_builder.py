# IEC 62304 §5.5 (Unit verification)
from __future__ import annotations

from prostanet.domains.clinical_validation.oracle_contracts import (
    build_advanced_therapy_oracle_contract,
    match_advanced_therapy_panel,
)
from prostanet.domains.patient_tracking.advanced_therapy_decision_builder import (
    build_advanced_therapy_decision_panel,
)
from prostanet.domains.patient_tracking.therapeutic_readiness_builder import (
    build_therapeutic_readiness_bundle,
)


def _nmcrpc_matrix() -> dict[str, object]:
    return {
        "arpi_family": {
            "family_code": "arpi_family",
            "family_label": "ARPI",
            "eligibility_status": "eligible",
            "winner_reason": "Darolutamida priorizada por riesgo convulsivo y menor carga SNC.",
            "variant_ranking": {
                "eligible_regimens_ranked": [
                    {
                        "regimen_code": "ADT_DAROLUTAMIDE",
                        "name": "Darolutamida + ADT",
                        "eligibility_status": "preferred",
                        "why_this_rank": ["Menor penetración SNC con eficacia preservada en nmCRPC."],
                    },
                    {
                        "regimen_code": "ADT_ENZALUTAMIDE",
                        "name": "Enzalutamida + ADT",
                        "eligibility_status": "eligible_nonpreferred",
                        "why_this_rank": ["Sigue siendo opción viable si Darolutamida no está disponible."],
                        "caution_flags": ["Mayor carga neurocognitiva potencial."],
                    },
                ],
                "nonpreferred_or_ineligible_regimens": [
                    {
                        "regimen_code": "ADT_APALUTAMIDE",
                        "name": "Apalutamida + ADT",
                        "eligibility_status": "hard_blocked",
                        "hard_blocks": ["Antecedente de dermatitis severa."],
                    }
                ],
            },
        }
    }


def test_readiness_bundle_exposes_therapy_specific_release_maps_for_nmcrpc():
    bundle = build_therapeutic_readiness_bundle(
        state="m0_crpc",
        preferred_regimen={
            "family_code": "arpi_family",
            "regimen_code": "ADT_DAROLUTAMIDE",
            "regimen_label": "Darolutamida + ADT",
        },
        next_best_action={"title": "Darolutamida + terapia de privación androgénica"},
        comparative_eligibility_matrix=_nmcrpc_matrix(),
        decision_input_requirements={},
        recommendation_block_status="clear",
        recommendation_block_reason="La recomendación tiene los datos mínimos para sostener una conducta visible.",
        signals={
            "testosterone": 18,
            "latest_testosterone_date": "2026-04-10",
            "castrate_testosterone_status": "confirmed_castrate",
            "current_adt_context": "medical_adt_continuous",
            "conventional_imaging_status": "M0",
            "conventional_imaging_date": "2026-04-10",
            "progression_pattern": "biochemical_only",
        },
    )

    assert bundle["readiness_status"] == "ready_to_release"
    assert bundle["release_status_by_therapy"]["ADT_DAROLUTAMIDE"]["decision_role"] == "selected"
    assert bundle["release_status_by_therapy"]["ADT_DAROLUTAMIDE"]["release_status"] == "ready_to_release"
    assert bundle["release_status_by_therapy"]["ADT_ENZALUTAMIDE"]["decision_role"] == "runner_up"
    assert bundle["hard_blockers_by_therapy"]["ADT_APALUTAMIDE"] == ["Antecedente de dermatitis severa."]
    assert "ADT_DAROLUTAMIDE" in {item["therapy_key"] for item in bundle["therapy_rationale_entries"]}


def test_advanced_panel_groups_selected_viable_and_blocked_options_without_hiding_local_adjuncts():
    readiness = build_therapeutic_readiness_bundle(
        state="m0_crpc",
        preferred_regimen={
            "family_code": "arpi_family",
            "regimen_code": "ADT_DAROLUTAMIDE",
            "regimen_label": "Darolutamida + ADT",
        },
        next_best_action={"title": "Darolutamida + terapia de privación androgénica"},
        comparative_eligibility_matrix=_nmcrpc_matrix(),
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

    panel = build_advanced_therapy_decision_panel(
        state="m0_crpc",
        therapeutic_readiness_bundle=readiness,
        active_copilot_bundle={},
        local_adjuncts_visible=[
            {
                "label": "RT al primario",
                "rationale": "Permanece visible como adjunto local contextual.",
                "priority": "candidate",
                "source": "mhspc_copilot_bundle",
            }
        ],
    )

    assert panel["available"] is True
    assert panel["selected_therapy"]["therapy_label"] == "Darolutamida + ADT"
    assert panel["selected_therapy"]["evidence_status"] == "aging"
    assert panel["selected_therapy"]["release_status"] == "aging_review_needed"
    assert panel["selected_therapy"]["refresh_action_needed"] == "Actualizar reestadificación convencional y confirmar castración actual"
    assert any(item["therapy_label"] == "Enzalutamida + ADT" for item in panel["other_viable_options"])
    assert any(item["therapy_label"] == "RT al primario" for item in panel["other_viable_options"])
    assert any(item["therapy_label"] == "Apalutamida + ADT" for item in panel["blocked_or_deferred_options"])


def test_advanced_panel_matcher_accepts_selected_blocked_prerequisite_and_local_adjunct_aliases():
    contract = build_advanced_therapy_oracle_contract(
        {
            "expected_selected_therapy_family": "parp_family",
            "expected_selected_therapy_aliases": ["Olaparib"],
            "expected_blocked_therapy_aliases": ["Lu-177 PSMA-617"],
            "expected_prerequisite_actions": ["Completar HRR"],
            "expected_local_adjuncts": ["RT al primario"],
            "expected_selected_evidence_status": "aging",
            "expected_release_status": "aging_review_needed",
            "expected_refresh_actions": ["Actualizar evidencia"],
            "expected_stale_block_fields": ["molecular_report_date"],
        }
    )

    matched = match_advanced_therapy_panel(
        selected_texts=["Olaparib", "PARP / precisión", "Revisar vigencia", "Actualizar evidencia: Completar HRR"],
        viable_texts=["Enzalutamida + ADT"],
        blocked_texts=["Lu-177 PSMA-617", "PSMA incompleto", "Fecha del estudio molecular"],
        prerequisite_texts=["Completar HRR: hrr_status, molecular_report_date"],
        local_adjunct_texts=["RT al primario"],
        contract=contract,
    )

    assert matched["selected_matched"] is True
    assert matched["blocked_matched"] is True
    assert matched["prerequisite_matched"] is True
    assert matched["local_adjunct_matched"] is True
    assert matched["selected_evidence_status_matched"] is True
    assert matched["release_status_matched"] is True
    assert matched["refresh_action_matched"] is True
    assert matched["stale_block_fields_matched"] is True


def test_advanced_panel_surfaces_supportive_status_for_selected_therapy():
    readiness = build_therapeutic_readiness_bundle(
        state="m0_crpc",
        preferred_regimen={
            "family_code": "arpi_family",
            "regimen_code": "ADT_DAROLUTAMIDE",
            "regimen_label": "Darolutamida + ADT",
        },
        next_best_action={"title": "Darolutamida + terapia de privación androgénica"},
        comparative_eligibility_matrix=_nmcrpc_matrix(),
        decision_input_requirements={},
        recommendation_block_status="clear",
        recommendation_block_reason="La recomendación tiene los datos mínimos para sostener una conducta visible.",
        supportive_care_toxicity_readiness_bundle={
            "supportive_readiness_status": "co_manage_required",
            "supportive_priority": "co_primary",
            "required_support_actions": ["Completar evaluación de caídas/cognición y plan de mitigación antes de sostener ARPI."],
            "hard_support_blockers": [],
            "recommended_referrals": ["Oncogeriatría"],
            "supportive_domains_active": ["frailty_cognition_falls"],
            "sustainability_status_by_therapy": {
                "arpi_family": {
                    "status": "co_manage_required",
                    "required_support_actions": ["Completar evaluación de caídas/cognición y plan de mitigación antes de sostener ARPI."],
                    "hard_support_blockers": [],
                    "why_support_changes_choice": ["El riesgo de caídas o deterioro cognitivo obliga co-manejo antes de sostener ARPI."],
                }
            },
        },
        signals={
            "testosterone": 18,
            "latest_testosterone_date": "2026-04-10",
            "castrate_testosterone_status": "confirmed_castrate",
            "current_adt_context": "medical_adt_continuous",
            "conventional_imaging_status": "M0",
            "conventional_imaging_date": "2026-04-10",
            "progression_pattern": "biochemical_only",
        },
    )

    panel = build_advanced_therapy_decision_panel(
        state="m0_crpc",
        therapeutic_readiness_bundle=readiness,
        active_copilot_bundle={},
        local_adjuncts_visible=[],
    )

    assert panel["supportive_readiness_status"] == "co_manage_required"
    assert panel["selected_therapy"]["release_status"] == "co_manage_required"
    assert panel["selected_therapy"]["supportive_readiness_status"] == "co_manage_required"
    assert panel["selected_therapy"]["required_support_actions"] == [
        "Completar evaluación de caídas/cognición y plan de mitigación antes de sostener ARPI."
    ]
