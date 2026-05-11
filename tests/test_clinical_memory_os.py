from __future__ import annotations

from prostanet.domains.patient_tracking.clinical_memory_os import (
    build_clinical_memory_os,
    build_similar_cohort_mirror,
)


def _patient(
    *,
    state: str = "m1_crpc",
    nss: str = "MEM-001",
    with_treatment: bool = True,
    with_biomarkers: bool = True,
    progression: bool = False,
    toxicity_grade: int | None = None,
    signed_consent: bool = True,
) -> dict:
    biomarker_rows = []
    if with_biomarkers:
        biomarker_rows = [
            {"biomarker_type": "PSA", "sample_date": "2026-01-01", "value": 10.0},
            {"biomarker_type": "PSA", "sample_date": "2026-03-01", "value": 5.0},
            {"biomarker_type": "TESTOSTERONA", "sample_date": "2026-03-01", "value": 18.0},
        ]
    return {
        "identity": {"id": 1, "nss": nss, "dob": "1958-01-01"},
        "baseline": {"baseline_psa": 10.0, "ecog_score": 1},
        "latest_assessment": {"state": state, "created_at": "2026-01-02"},
        "prior_history": {"current_state": state, "management_track": "systemic"},
        "biomarker_longitudinal": biomarker_rows,
        "psa_series": [
            {"sample_date": "2026-01-01", "value": 10.0},
            {"sample_date": "2026-03-01", "value": 5.0},
        ] if with_biomarkers else [],
        "testosterone_series": [
            {"sample_date": "2026-03-01", "value": 18.0},
        ] if with_biomarkers else [],
        "treatments": [
            {"line_of_therapy": 1, "drug_scheme": "ADT + docetaxel", "start_date": "2026-01-05"}
        ] if with_treatment else [],
        "outcome_events": [
            {"event_key": "prog-1", "event_type": "radiographic_progression", "event_date": "2026-04-01"}
        ] if progression else [],
        "treatment_adverse_events": [
            {"ctcae_term": "fatigue", "ctcae_grade": toxicity_grade, "event_date": "2026-03-15"}
        ] if toxicity_grade is not None else [],
        "stage_visits": [{"visit_date": "2026-03-01"}],
        "consent_summary": {"status": "signed" if signed_consent else "missing"},
        "patient_clinical_facts": [{"fact_key": "psa", "value": 5.0}],
    }


def _board_bundle(status: str = "releaseable") -> dict:
    return {
        "tumor_board_os": {
            "summary": {
                "board_status": "released" if status == "releaseable" else "requires_data",
                "winner_option_key": "mcrpc_sequence",
                "winner_option_label": "Secuenciacion m1CRPC",
            },
            "recommendation": {"finality": "released", "title": "Secuenciar m1CRPC"},
            "options": [
                {
                    "key": "mcrpc_sequence",
                    "label": "Secuenciacion m1CRPC",
                    "status": status,
                    "gates_impacted": ["GATE_001"],
                    "trials_impacted": ["TRIAL_001"],
                }
            ],
        },
        "clinical_readiness_tower": {"capture_plan": {"missing_fields": []}},
    }


def test_tumor_board_release_creates_decision_episode():
    memory = build_clinical_memory_os(
        _patient(),
        longitudinal_bundle=_board_bundle(),
        state="m1_crpc",
    )

    episode = memory["decision_episodes"][0]
    assert episode["decision_origin"] == "tumor_board_os"
    assert episode["winner_option_key"] == "mcrpc_sequence"
    assert episode["gates_impacted"] == ["GATE_001"]
    assert episode["trials_impacted"] == ["TRIAL_001"]


def test_care_pathway_completed_action_updates_episode_execution_counts():
    bundle = {
        **_board_bundle(),
        "care_pathway_os": {
            "pathway_actions": [
                {"action_key": "tb:mcrpc_sequence", "status": "completed"},
                {"action_key": "schedule:psa", "status": "blocked"},
            ]
        },
    }

    memory = build_clinical_memory_os(_patient(), longitudinal_bundle=bundle, state="m1_crpc")
    episode = memory["decision_episodes"][0]

    assert episode["pathway_completed_count"] == 1
    assert episode["pathway_blocked_count"] == 1


def test_real_psa_and_testosterone_update_expected_vs_observed_on_track():
    memory = build_clinical_memory_os(_patient(), longitudinal_bundle=_board_bundle(), state="m1_crpc")

    observed = memory["expected_vs_observed"]
    assert observed["status"] == "on_track"
    assert observed["observed"]["psa_delta_pct"] == -50.0
    assert observed["observed"]["testosterone_point_count"] >= 1


def test_patient_without_treatment_does_not_get_therapeutic_attribution():
    memory = build_clinical_memory_os(
        _patient(with_treatment=False),
        longitudinal_bundle=_board_bundle(),
        state="m1_crpc",
    )

    assert memory["expected_vs_observed"]["status"] == "insufficient_data"
    assert memory["outcome_attribution"]["primary_cause"] == "no_real_treatment_line"
    assert memory["outcome_attribution"]["therapeutic_attribution_allowed"] is False


def test_documented_progression_requires_redecision():
    memory = build_clinical_memory_os(
        _patient(progression=True),
        longitudinal_bundle=_board_bundle(),
        state="m1_crpc",
    )

    assert memory["expected_vs_observed"]["status"] == "requires_redecision"
    assert memory["summary"]["requires_redecision"] is True
    assert memory["redecision_reasons"]


def test_limiting_toxicity_is_attributed_without_fabricating_outcome():
    memory = build_clinical_memory_os(
        _patient(toxicity_grade=3),
        longitudinal_bundle=_board_bundle(),
        state="m1_crpc",
    )

    assert memory["expected_vs_observed"]["status"] == "toxicity_limited"
    assert memory["outcome_attribution"]["primary_cause"] == "toxicity_limited"
    assert memory["audit"]["no_fabricated_biomarkers"] is True


def test_similar_cohort_with_few_cases_returns_insufficient_size():
    patient = _patient()
    cohort = [_patient(nss="MEM-002"), _patient(nss="MEM-003")]

    mirror = build_similar_cohort_mirror(patient, cohort_records=cohort, state="m1_crpc")

    assert mirror["status"] == "insufficient_cohort_size"
    assert mirror["minimum_required"] == 5


def test_ai_readiness_blocks_without_consent_or_mature_outcome():
    memory = build_clinical_memory_os(
        _patient(signed_consent=False, with_biomarkers=False),
        longitudinal_bundle=_board_bundle(),
        state="m1_crpc",
    )

    assert memory["ai_readiness"]["status"] == "blocked"
    assert "consent_missing" in memory["ai_readiness"]["blockers"]
    assert memory["ai_readiness"]["model_release_allowed"] is False


def test_clinical_memory_os_api_and_profile_contracts_are_registered():
    from pathlib import Path

    app_source = Path("app.py").read_text(encoding="utf-8")
    profile_template = Path("templates/patient_profile_v2.html").read_text(encoding="utf-8")
    patients_template = Path("templates/patients_v2.html").read_text(encoding="utf-8")

    assert "/api/patients/<patient_ref>/clinical-memory-os" in app_source
    assert "/api/patient/<patient_ref>/clinical-memory-os" in app_source
    assert "/api/patients/<patient_ref>/outcome-episodes" in app_source
    assert "/api/cohorts/similar-patients" in app_source
    assert "Clinical Memory OS" in profile_template
    assert "pm2ClinicalMemoryOS" in profile_template
    assert "Memory OS" in patients_template
