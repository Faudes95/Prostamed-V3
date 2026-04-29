# IEC 62304 §5.5 (Unit verification)
from __future__ import annotations

from prostanet.domains.patient_tracking.supportive_care_toxicity_readiness_builder import (
    build_supportive_care_toxicity_readiness_bundle,
)
from prostanet.domains.patient_tracking.therapeutic_readiness_builder import (
    build_therapeutic_readiness_bundle,
)


def _stable_survivorship_bundle(**overrides):
    bundle = {
        "available": True,
        "missing_inputs": [],
        "stale_inputs": [],
        "recommended_interventions": [],
        "recommended_referrals": [],
        "cardiometabolic_status": "stable",
        "bone_health_status": "stable",
        "functional_recovery_status": "stable",
    }
    bundle.update(overrides)
    return bundle


def _stable_palliative_bundle(**overrides):
    bundle = {
        "available": True,
        "missing_inputs": [],
        "stale_inputs": [],
        "recommended_interventions": [],
        "recommended_referrals": [],
        "supportive_priority": "background",
        "care_mode": "standard_oncology",
        "trigger_status": "stable",
        "acute_palliative_alerts": [],
        "bone_event_risk": {"risk_level": "low"},
    }
    bundle.update(overrides)
    return bundle


def test_supportive_bundle_requires_co_management_for_arpi_when_cognition_and_falls_are_high():
    bundle = build_supportive_care_toxicity_readiness_bundle(
        patient_record={},
        state="m0_crpc",
        field_values={
            "mini_cog_score": 2,
            "fall_risk": "high",
            "ddi_review_status": "completed",
            "cv_risk_documented": 1,
        },
        survivorship_transition_bundle=_stable_survivorship_bundle(),
        palliative_transition_bundle=_stable_palliative_bundle(),
    )

    assert bundle["supportive_readiness_status"] == "co_manage_required"
    assert bundle["supportive_priority"] == "co_primary"
    assert bundle["sustainability_status_by_therapy"]["arpi_family"]["status"] == "co_manage_required"
    assert any("cognitivo" in reason.lower() or "caídas" in reason.lower() for reason in bundle["why_support_changes_choice_by_therapy"]["arpi_family"])


def test_supportive_bundle_blocks_taxane_when_fragility_or_toxicity_make_it_unsustainable():
    bundle = build_supportive_care_toxicity_readiness_bundle(
        patient_record={},
        state="m1_crpc",
        field_values={
            "g8_score": 10,
            "ecog": 2,
            "neuropathy_grade": 2,
            "hemoglobin": 9.4,
            "ddi_review_status": "completed",
            "cv_risk_documented": 1,
        },
        survivorship_transition_bundle=_stable_survivorship_bundle(),
        palliative_transition_bundle=_stable_palliative_bundle(),
    )

    assert bundle["supportive_readiness_status"] == "blocking_support_gap"
    assert bundle["supportive_priority"] == "co_primary"
    assert bundle["sustainability_status_by_therapy"]["taxane_family"]["status"] == "blocking_support_gap"
    assert any("taxano" in blocker.lower() for blocker in bundle["hard_support_blockers"])


def test_therapeutic_readiness_projects_supportive_status_into_selected_therapy_release():
    supportive_bundle = build_supportive_care_toxicity_readiness_bundle(
        patient_record={},
        state="m0_crpc",
        field_values={
            "mini_cog_score": 2,
            "fall_risk": "high",
            "ddi_review_status": "completed",
            "cv_risk_documented": 1,
        },
        survivorship_transition_bundle=_stable_survivorship_bundle(),
        palliative_transition_bundle=_stable_palliative_bundle(),
    )

    readiness = build_therapeutic_readiness_bundle(
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
            "conventional_imaging_date": "2026-04-10",
            "progression_pattern": "biochemical_only",
        },
        supportive_care_toxicity_readiness_bundle=supportive_bundle,
    )

    selected = readiness["release_status_by_therapy"]["ADT_DAROLUTAMIDE"]
    assert readiness["supportive_readiness_status"] == "co_manage_required"
    assert readiness["selected_therapy_release_status"] == "co_manage_required"
    assert selected["supportive_readiness_status"] == "co_manage_required"
    assert selected["required_support_actions"]
    assert selected["why_support_changes_choice"]
