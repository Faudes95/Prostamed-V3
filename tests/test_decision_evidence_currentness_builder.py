# IEC 62304 §5.5 (Unit verification)
from __future__ import annotations

from datetime import date, timedelta

from prostanet.domains.patient_tracking.clinical_decision_governance import (
    build_clinical_decision_governance_bundle,
)
from prostanet.domains.patient_tracking.decision_evidence_currentness_builder import (
    build_decision_evidence_currentness_bundle,
)


def test_decision_currentness_marks_diagnostic_workup_current_with_recent_psa_and_mri():
    today = date.today().isoformat()
    bundle = build_decision_evidence_currentness_bundle(
        state="diagnostic_workup",
        field_values={
            "psa": 6.2,
            "psa_current_date": today,
            "psad": 0.18,
            "pirads_score": 4,
            "mpmri_date": today,
            "dre_suspicious": 1,
        },
        minimum_decisive_dataset_bundle={
            "required_fields": ["psa", "psad", "pirads_score", "dre_suspicious"],
            "dataset_status": "clear",
        },
        next_best_action={"title": "Activar biopsia dirigida", "recommendation_family": "diagnostic_confirmation"},
    )

    assert bundle["available"] is True
    assert bundle["selected_decision_evidence_status"] == "current"
    assert bundle["selected_decision_release_status"] == "ready_to_release"
    assert bundle["release_blocked_by_stale_evidence"] is False


def test_decision_currentness_marks_post_negative_followup_aging_when_mri_is_stale():
    stale_mri = (date.today() - timedelta(days=420)).isoformat()
    bundle = build_decision_evidence_currentness_bundle(
        state="post_negative_biopsy_followup",
        field_values={
            "psa": 5.8,
            "psa_current_date": date.today().isoformat(),
            "psad": 0.16,
            "pirads_score": 4,
            "mpmri_date": stale_mri,
            "prior_biopsy_count": 1,
            "biopsy_date": (date.today() - timedelta(days=200)).isoformat(),
        },
        minimum_decisive_dataset_bundle={
            "required_fields": ["psa", "psad", "pirads_score", "prior_biopsy_count"],
            "dataset_status": "clear",
        },
        next_best_action={"title": "Reabrir estudio diagnóstico", "recommendation_family": "diagnostic_confirmation"},
    )

    assert bundle["selected_decision_evidence_status"] == "aging"
    assert bundle["selected_decision_release_status"] == "aging_review_needed"
    assert bundle["refresh_actions"] == [
        "Actualizar PSA, mpMRI y soporte histológico antes de sostener el seguimiento post-biopsia negativa"
    ]
    assert "Fecha de resonancia magnética" in " ".join(bundle["aging_evidence_fields"])


def test_decision_currentness_blocks_bcr_release_when_psa_is_stale():
    stale_psa_date = (date.today() - timedelta(days=260)).isoformat()
    bundle = build_decision_evidence_currentness_bundle(
        state="recurrence_bcr",
        field_values={
            "psa_current": 0.41,
            "psa_current_date": stale_psa_date,
            "psadt_months": 7.4,
            "salvage_local_feasible": 1,
            "psma_pet_done": 1,
        },
        minimum_decisive_dataset_bundle={
            "required_fields": ["psa", "psadt_months", "salvage_local_feasible", "psma_pet_done"],
            "dataset_status": "clear",
        },
        next_best_action={"title": "Activar salvage temprano", "recommendation_family": "salvage_rt_family"},
    )

    assert bundle["selected_decision_evidence_status"] == "stale"
    assert bundle["selected_decision_release_status"] == "blocked_by_stale_evidence"
    assert bundle["release_blocked_by_stale_evidence"] is True
    assert bundle["refresh_actions"] == [
        "Actualizar PSA/PSADT y reestadificación antes de cerrar la ruta de rescate"
    ]


def test_decision_currentness_blocks_active_surveillance_when_confirmatory_biopsy_is_missing():
    today = date.today().isoformat()
    bundle = build_decision_evidence_currentness_bundle(
        state="localized_initial",
        management_track="active_surveillance",
        field_values={
            "clinical_risk_group": "low",
            "life_expectancy_years": 15,
            "pirads_score": 3,
            "mpmri_date": today,
            "isup_grade": 1,
            "clinical_tstage": "T1c",
            "positive_cores": 2,
            "total_cores": 12,
            "conventional_imaging_status": "M0",
            "psa": 5.1,
            "psa_current_date": today,
        },
        minimum_decisive_dataset_bundle={
            "required_fields": [
                "clinical_risk_group",
                "life_expectancy_years",
                "pirads_score",
                "isup_grade",
                "clinical_tstage",
                "positive_cores",
                "total_cores",
                "conventional_imaging_status",
            ],
            "dataset_status": "clear",
        },
        next_best_action={"title": "Mantener vigilancia activa", "recommendation_family": "active_surveillance_family"},
    )

    assert bundle["selected_decision_release_status"] == "blocked_by_stale_evidence"
    assert "Biopsia confirmatoria realizada" in " ".join(bundle["stale_evidence_fields"])


def test_governance_bundle_projects_decision_currentness_into_dataset_bundle():
    today = date.today().isoformat()
    bundle = build_clinical_decision_governance_bundle(
        {
            "baseline": {
                "psa": 6.1,
                "pirads_score": 4,
                "dre_suspicious": 1,
                "psad": 0.18,
                "mpmri_date": today,
            },
            "latest_assessment": {
                "input_snapshot": {
                    "psa": 6.1,
                    "psad": 0.18,
                    "pirads_score": 4,
                    "dre_suspicious": 1,
                    "mpmri_date": today,
                    "repeat_psa_value": 6.0,
                    "repeat_psa_date": today,
                }
            },
        },
        state="diagnostic_workup",
        management_track="diagnostic_surveillance",
        latest_assessment={
            "input_snapshot": {
                "psa": 6.1,
                "psad": 0.18,
                "pirads_score": 4,
                "dre_suspicious": 1,
                "mpmri_date": today,
            }
        },
        next_best_action={"title": "Activar biopsia dirigida", "recommendation_family": "diagnostic_confirmation"},
        decision_input_requirements={},
        clinical_fact_bundle={"field_values": {"psa": 6.1, "pirads_score": 4}},
    )

    decision_bundle = bundle["decision_evidence_currentness_bundle"]
    dataset_bundle = bundle["minimum_decisive_dataset_bundle"]
    assert decision_bundle["available"] is True
    assert dataset_bundle["selected_decision_release_status"] == decision_bundle["selected_decision_release_status"]
    assert "decision_evidence_summary" in dataset_bundle


def test_governance_bundle_carries_epic26_guardrail_for_localized_initial():
    today = date.today().isoformat()
    patient = {
        "baseline": {
            "clinical_risk_group": "FAVORABLE INTERMEDIATE",
            "clinical_tstage": "T2a",
            "nodal_status": "N0",
            "metastasis_site": "M0",
            "psa": 8.5,
            "psa_current_date": today,
            "ecog_score": 0,
            "charlson_score": 1,
            "frailty_status": "Fit",
            "g8_score": 16,
            "anesthesia_surgical_fitness": "Fit",
            "radiotherapy_feasibility": "feasible",
            "baseline_obstruction": "mild",
            "ipss_score": 7,
            "iief5_score": 8,
            "patient_priority_profile": "preserve_sexual_function",
            "epic26_sexual_domain": 95,
        },
        "latest_assessment": {
            "input_snapshot": {
                "clinical_risk_group": "FAVORABLE INTERMEDIATE",
                "clinical_tstage": "T2a",
                "nodal_status": "N0",
                "metastasis_site": "M0",
                "psa": 8.5,
                "psa_current_date": today,
                "ecog_score": 0,
                "charlson_score": 1,
                "frailty_status": "Fit",
                "g8_score": 16,
                "anesthesia_surgical_fitness": "Fit",
                "radiotherapy_feasibility": "feasible",
                "baseline_obstruction": "mild",
                "ipss_score": 7,
                "iief5_score": 8,
                "patient_priority_profile": "preserve_sexual_function",
                "epic26_sexual_domain": 95,
            }
        },
    }

    bundle = build_clinical_decision_governance_bundle(
        patient,
        state="localized_initial",
        management_track="definitive_local_therapy",
        latest_assessment=patient["latest_assessment"],
        next_best_action={"title": "Comparar RP vs RT", "recommendation_family": "localized_local_therapy"},
        decision_input_requirements={},
        clinical_fact_bundle={"field_values": patient["latest_assessment"]["input_snapshot"]},
    )

    shared_decision_bundle = bundle["shared_decision_bundle"]
    governance_bundle = bundle["decision_governance_bundle"]
    localized_bundle = bundle["localized_modality_fitness_bundle"]

    assert localized_bundle["dominant_modality"] == "surgery"
    assert shared_decision_bundle["epic26_governance_contract"]["primary_guideline_driver"] == "nccn_2026"
    assert shared_decision_bundle["epic26_governance_contract"]["governance_status"] == "baseline_tradeoff_followup_quality_only"
    assert shared_decision_bundle["epic26_shared_decision_signals"]
    assert governance_bundle["epic26_governance_status"] == "baseline_tradeoff_followup_quality_only"
    assert governance_bundle["epic26_primary_guideline_driver"] == "nccn_2026"
    assert "modalidad dominante" in governance_bundle["epic26_guardrail"].lower()
