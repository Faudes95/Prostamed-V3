"""V2 treatment-value persistence closure.

The business-critical rule is not just that dose/cost APIs work. A clinician
must see the same triplet regimen, local dose warning, critical referral alert,
cost, and PSA-treatment timeline in the official Profile V2 surface.
"""
from __future__ import annotations


def test_triplet_dose_cost_alert_and_timeline_are_visible_in_profile_v2(app_client):
    client, _db_path = app_client
    import tracking_db

    patient_ref = "QA-V2-TX-VALUE-001"
    patient_id, message, _meta = tracking_db.register_new_patient(
        {
            "nss": patient_ref,
            "full_name": "Paciente Triplete Valor V2",
            "dob": "1961-01-01",
            "diagnosis_date": "2026-05-02",
            "assessment_state": "mcspc_high_volume_sync",
            "baseline_psa": "42",
            "ecog_score": "1",
            "psa_history": [
                {"sample_date": "2026-05-02", "psa_value": 42.0, "context": "inicio_triplete"},
                {"sample_date": "2026-06-15", "psa_value": 16.8, "context": "bajo_triplete"},
            ],
            "drug_scheme": "ADT_DOCETAXEL_DAROLUTAMIDE",
            "current_treatment_start_date": "2026-05-02",
            "line_of_therapy_number": "1",
            "line_of_therapy_context": "mHSPC_initial",
            "doses_received_before_unit": "2",
            "local_doses_administered": "4",
            "unit_name": "Unidad local",
            "referral_target": "HGZ",
        }
    )
    assert patient_id is not None, message

    summary_4 = client.get(f"/api/patients/{patient_ref}/treatment-course/current")
    assert summary_4.status_code == 200
    payload_4 = summary_4.get_json()
    assert payload_4["success"] is True
    assert payload_4["current_course"]["regimen_code"] == "ADT_DOCETAXEL_DAROLUTAMIDE"
    assert payload_4["current_course"]["intensity"]["intensity"] == "triplet"
    assert payload_4["current_course"]["local_dose_count"] == 4
    assert payload_4["current_course"]["global_dose_count"] == 6
    assert payload_4["dose_alert"]["severity"] == "warning"
    assert payload_4["cost_summary"]["estimated_total_spend_mxn"] == 190000.0
    assert payload_4["cost_summary"]["estimated_total_medication_spend_mxn"] == 191201.72
    assert payload_4["cost_summary"]["unpriced_backbone_components"] == ["ADT"]

    profile_4 = client.get(f"/patient_profile/{patient_ref}?v=2&refresh=1")
    assert profile_4.status_code == 200
    html_4 = profile_4.get_data(as_text=True)
    assert "patient_profile_v2_real_context" in html_4
    assert 'data-testid="treatment-course-unit-card"' in html_4
    assert "ADT + docetaxel + darolutamida" in html_4
    assert "Triplete" in html_4
    assert "$ 190000.00 MXN" in html_4
    assert "$ 191201.72 MXN" in html_4
    assert "Alerta temprana de referencia" in html_4
    assert "Realizar envio a HGZ o HGR" in html_4
    assert "Validar precio" in html_4 and "ADT" in html_4
    assert "psaTreatmentTimelineChart" in html_4
    assert "psaCombinedTimelineChart" in html_4
    assert "inicio_triplete" in html_4 or "bajo_triplete" in html_4

    course_id = payload_4["current_course"]["treatment_history_id"]
    dose_5 = client.post(
        f"/api/patients/{patient_ref}/treatment-course/{course_id}/dose",
        json={"dose_date": "2026-06-22", "unit_name": "Unidad local", "referral_target": "HGZ"},
    )
    assert dose_5.status_code == 200
    assert dose_5.get_json()["treatment_economic_impact"]["after"]["current_course"]["local_dose_count"] == 5

    dose_6 = client.post(
        f"/api/patients/{patient_ref}/treatment-course/{course_id}/dose",
        json={"dose_date": "2026-07-13", "unit_name": "Unidad local", "referral_target": "HGZ"},
    )
    assert dose_6.status_code == 200
    dose_6_payload = dose_6.get_json()
    assert dose_6_payload["dose_alert"]["severity"] == "critical"
    assert dose_6_payload["treatment_economic_impact"]["critical_alert_now"] is True
    assert dose_6_payload["treatment_economic_impact"]["after"]["cost_summary"]["estimated_total_spend_mxn"] == 285000.0
    assert "Paciente con maximo de dosis otorgadas en esta unidad. Priorizar envio a HGZ o HGR." in (
        dose_6_payload["dose_alert"]["message"]
    )

    profile_6 = client.get(f"/patient_profile/{patient_ref}?v=2&refresh=1")
    assert profile_6.status_code == 200
    html_6 = profile_6.get_data(as_text=True)
    assert "ADT + docetaxel + darolutamida" in html_6
    assert "$ 285000.00 MXN" in html_6
    assert "Maximo de dosis otorgadas en esta unidad" in html_6
    assert "Paciente con maximo de dosis otorgadas en esta unidad. Priorizar envio a HGZ o HGR." in html_6
    assert "psaTreatmentTimelineChart" in html_6
    assert "psaCombinedTimelineChart" in html_6

    impact = client.get(f"/api/patients/{patient_ref}/treatment-economic-impact")
    assert impact.status_code == 200
    impact_payload = impact.get_json()
    assert impact_payload["success"] is True
    assert impact_payload["snapshot"]["source_clinical_facts_mutated"] is False
    assert impact_payload["snapshot"]["external_order_created"] is False
    assert impact_payload["snapshot"]["model_trained"] is False
