from __future__ import annotations


def test_module_evaluate_ignores_unavailable_display_values(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/diagnostic_workup/evaluate",
        json={
            "age": "No disponible",
            "psa": "No disponible",
            "psad": "No disponible",
            "pirads_score": "No disponible",
            "ipss_score": "No disponible",
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    assert data["result"]["state"] == "diagnostic_workup"


def test_localized_module_accepts_string_numeric_values_from_ui(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/localized_initial/evaluate",
        json={
            "age": "65",
            "psa": "8.5",
            "baseline_psa": "8.5",
            "clinical_tstage": "T2a",
            "gleason_primary": "4",
            "gleason_secondary": "3",
            "isup_grade": "3",
            "num_cores_positive": "4",
            "total_cores": "12",
            "psad": "0.18",
            "psa_density": "0.18",
            "nodal_status": "N0",
            "metastasis_site": "M0",
            "ecog_score": "0",
            "charlson_score": "1",
            "frailty_status": "Fit",
            "g8_score": "15",
            "anesthesia_surgical_fitness": "Fit",
            "ipss_score": "7",
            "iief5_score": "18",
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    assert data["result"]["state"] == "localized_initial"


def test_screening_alias_opens_diagnostic_workup_surfaces(app_client):
    client, _ = app_client

    wizard_response = client.get("/wizard/screening?prefill_source=clinical_hub")
    assert wizard_response.status_code == 200
    html = wizard_response.data.decode("utf-8")
    assert "Estudio diagnóstico antes de confirmar cáncer de próstata" in html

    evidence_response = client.get("/api/modules/screening/evidence")
    assert evidence_response.status_code == 200
    evidence_data = evidence_response.get_json()
    assert evidence_data["success"] is True
    assert evidence_data["evidence"]["module"] == "diagnostic_workup"

    evaluate_response = client.post("/api/modules/screening/evaluate", json={"psa": "No disponible"})
    assert evaluate_response.status_code == 200
    evaluate_data = evaluate_response.get_json()
    assert evaluate_data["success"] is True
    assert evaluate_data["result"]["state"] == "diagnostic_workup"


def test_prepare_longitudinal_registration_ignores_unavailable_values(app_client):
    client, _ = app_client

    response = client.post(
        "/api/clinical-assessments/draft",
        json={
            "module_id": "diagnostic_workup",
            "payload": {
                "age": "No disponible",
                "psa": "No disponible",
                "psad": "No disponible",
                "pirads_score": "No disponible",
                "ipss_score": "No disponible",
            },
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    assert data["assessment_id"]
    assert data["assessment"]["state"] == "diagnostic_workup"
    assert "registration_fragments" in data
