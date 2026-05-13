from __future__ import annotations
# IEC 62304 §5.7 (software system testing).

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_confirmed_registration_blocks_without_structured_diagnosis(app_client):
    client, _ = app_client

    response = client.post(
        "/api/register_patient",
        json={
            "known_cancer_diagnosis": "1",
            "assessment_state": "localized_initial",
            "nss": "DX-GATE-001",
            "full_name": "Paciente Confirmado Incompleto",
            "dob": "1965-01-01",
            "ecog_score": 0,
        },
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["success"] is False
    assert payload["clinical_gate"]["blocked"] is True
    assert "subtipo histológico" in payload["error"]
    assert "Gleason primario" in payload["clinical_gate"]["missing_fields"]
    assert "Gleason secundario" in payload["clinical_gate"]["missing_fields"]


def test_confirmed_registration_opens_when_official_diagnosis_is_structured(app_client):
    client, _ = app_client

    response = client.post(
        "/api/register_patient",
        json={
            "known_cancer_diagnosis": "1",
            "assessment_state": "localized_initial",
            "nss": "DX-GATE-002",
            "full_name": "Paciente Gleason Nueve",
            "dob": "1959-02-03",
            "histology_subtype": "Adenocarcinoma acinar",
            "gleason_primary": 5,
            "gleason_secondary": 4,
            "clinical_tstage": "cT3b",
            "nodal_status": "N0",
            "metastasis_site": "M0",
            "clinical_risk_group": "muy_alto",
            "baseline_psa": 42.0,
            "ecog_score": 0,
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    context = payload["official_diagnosis_context"]
    assert context["official_diagnosis_status"] == "complete"
    assert "Adenocarcinoma acinar de próstata Gleason 9 (5+4), ISUP 5" in payload["official_diagnosis"]
    assert "riesgo muy alto" in payload["official_diagnosis"]


def test_suspected_diagnostic_registration_remains_provisional_without_pathology(app_client):
    client, _ = app_client

    response = client.post(
        "/api/register_patient",
        json={
            "known_cancer_diagnosis": "0",
            "assessment_state": "diagnostic_workup",
            "nss": "DX-GATE-003",
            "full_name": "Paciente Sospecha",
            "dob": "1970-05-05",
            "psa": 8.1,
            "ecog_score": 0,
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    context = payload["official_diagnosis_context"]
    assert context["official_diagnosis_display_status"] == "provisional"
    assert "Sospecha" in context["official_diagnosis"]


def test_official_diagnosis_preview_exposes_option_one_gate(app_client):
    client, _ = app_client

    response = client.post(
        "/api/official-diagnosis/preview",
        json={
            "known_cancer_diagnosis": "1",
            "_classified_state": "localized_initial",
            "nss": "DX-GATE-004",
            "full_name": "Paciente Preview",
            "histology_subtype": "Adenocarcinoma acinar",
            "gleason_primary": 5,
            "gleason_secondary": 4,
            "clinical_tstage": "cT3a",
            "nodal_status": "N0",
            "metastasis_site": "M0",
            "clinical_risk_group": "muy_alto",
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["clinical_gate"]["blocked"] is False
    assert "Gleason 9 (5+4), ISUP 5" in payload["official_diagnosis"]


def test_quick_schema_collects_confirmed_diagnosis_structure():
    from prostanet.presentation.v2_adapters import quick_classify_schema

    schema = quick_classify_schema()
    fields = {field["name"]: field for field in schema["fields"]}

    for field_name in (
        "histology_subtype",
        "gleason_primary",
        "gleason_secondary",
        "nodal_status",
        "clinical_stage_group",
        "clinical_risk_group",
    ):
        assert field_name in fields
        assert fields[field_name]["conditional_visibility"] == {"known_cancer_diagnosis": ["1"]}
    assert fields["histology_subtype"]["required"] is True
    assert fields["gleason_primary"]["required"] is True
    assert fields["gleason_secondary"]["required"] is True


def test_intake_wizard_submit_preserves_previous_step_identity_fields():
    html = (PROJECT_ROOT / "templates" / "intake_stage_aware_v2.html").read_text()

    assert "function iwFieldSubmittable" in html
    assert "const payload = { ...(window.iwState.payload || {}) };" in html
    assert "const payload = iwCollectPersistablePayload();" in html
    assert "if (window.iwState.classifiedState) payload.assessment_state" in html
