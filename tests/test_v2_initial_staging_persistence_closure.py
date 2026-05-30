"""V2 initial-staging persistence closure.

These tests protect the current product rule before adding more clinical logic:
facts captured during initial staging must persist once, flow into the APE tower,
feed Ledger/Decision Hoy, and render in Profile V2 without asking the clinician
to recapture the same PSA scalar.
"""
from __future__ import annotations

import json


def test_localized_initial_staging_persists_ape_once_to_ledger_profile_and_decision(app_client):
    client, _db_path = app_client
    import tracking_db

    wizard_payload = {
        "age": 65,
        "psa": 12.6,
        "clinical_tstage": "T2b",
        "gleason_primary": 4,
        "gleason_secondary": 3,
        "isup_grade": 3,
        "num_cores_positive": 4,
        "total_cores": 12,
        "prostate_volume_ml": 42,
        "nodal_status": "N0",
        "metastasis_site": "M0",
        "ecog_score": "0",
        "ipss_score": 7,
        "iief5_score": 18,
        "life_expectancy_years": 12,
    }
    draft = client.post(
        "/api/clinical-assessments/draft",
        json={"module_id": "localized_initial", "payload": wizard_payload},
    )
    assert draft.status_code == 200
    draft_data = draft.get_json()
    assert draft_data["success"] is True
    assessment_id = draft_data["assessment_id"]

    visible_registration_fields = {field["name"] for field in draft_data["deduped_visible_fields"]}
    imported_fields = {field["name"]: field for field in draft_data["imported_clinical_fields"]}
    assert "psa" in imported_fields
    assert visible_registration_fields & {"psa", "baseline_psa", "psa_baseline_ng_ml", "ape"} == set()
    assert "psa_history" in visible_registration_fields
    assert visible_registration_fields.isdisjoint(
        {"testosterone_history", "hemoglobin", "alp", "ldh", "albumin", "dxa_baseline_done"}
    )

    patient_ref = "QA-V2-PERSIST-001"
    registration_payload = {
        "assessment_id": assessment_id,
        "assessment_state": "localized_initial",
        "nss": patient_ref,
        "full_name": "Paciente Persistencia V2 QA",
        "dob": "1961-05-29",
        "psa_history": [
            {"sample_date": "2026-04-01", "psa_value": 11.8, "context": "pretratamiento"},
            {"sample_date": "2026-05-01", "psa_value": 12.6, "context": "pretratamiento"},
        ],
    }
    assert "baseline_psa" not in registration_payload
    assert "psa" not in registration_payload

    register = client.post("/api/register_patient", json=registration_payload)
    assert register.status_code == 200
    register_data = register.get_json()
    assert register_data["success"] is True
    psa_summary = register_data["registration_metadata"]["psa_history_summary"]
    assert psa_summary["points_received"] == 2
    assert psa_summary["points_persisted"] == 2
    assert round(float(psa_summary["baseline_psa"]), 1) == 12.6

    core = tracking_db.load_patient_record_core(patient_ref)
    assert core is not None
    latest_assessment = core["latest_assessment"]
    assert latest_assessment["module_id"] == "localized_initial"
    assert latest_assessment["state"] == "localized_initial"
    assert int(latest_assessment["patient_id"]) == int(register_data["patient_id"])
    assert "clinical_fact_ledger_wizard_context" not in (latest_assessment.get("input_snapshot") or {})

    record = tracking_db.build_patient_record_derivatives(core)
    biomarkers = [
        row
        for row in record.get("biomarker_longitudinal") or []
        if str(row.get("biomarker_type") or "").upper() == "PSA"
    ]
    assert len(biomarkers) == 2
    assert [round(float(row["value"]), 1) for row in biomarkers] == [11.8, 12.6]
    assert record["baseline"]["baseline_psa"] == 12.6

    ledger = client.get(f"/api/patients/{patient_ref}/clinical-fact-ledger/summary")
    assert ledger.status_code == 200
    ledger_data = ledger.get_json()
    assert ledger_data["source_clinical_facts_mutated"] is False
    priority = {item["fact_key"]: item for item in ledger_data["priority_facts"]}
    assert priority["baseline_psa"]["value_known"] is True
    assert priority["current_psa"]["value_known"] is True
    assert ledger_data["summary"]["reusable_priority_fact_count"] >= 2

    decision = client.get(f"/api/patients/{patient_ref}/decision-today")
    assert decision.status_code == 200
    decision_data = decision.get_json()
    assert decision_data["success"] is True
    assert decision_data["resolved_patient_ref"] == patient_ref

    schedule = client.get(f"/api/patients/{patient_ref}/schedule")
    assert schedule.status_code == 200
    assert schedule.get_json()["success"] is True

    profile = client.get(f"/patient_profile/{patient_ref}?v=2")
    assert profile.status_code == 200
    profile_html = profile.get_data(as_text=True)
    assert "patient_profile_v2_real_context" in profile_html
    assert "psaTreatmentTimelineChart" in profile_html
    assert "psaCombinedTimelineChart" in profile_html
    assert "Clinical Fact Ledger v1" in profile_html
    assert "12.6" in profile_html
    assert "Paciente Persistencia V2 QA" in profile_html

    serialized = json.dumps(
        {
            "register": register_data,
            "ledger": ledger_data,
            "decision": decision_data,
        },
        ensure_ascii=False,
        default=str,
    )
    assert "could not convert string to float" not in serialized
