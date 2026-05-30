"""Initial-staging capture sequence guards.

These checks make the product rule explicit before more clinical logic is added:
initial staging may reuse APE/PSA and open longitudinal series, but it should not
ask the clinician for duplicate APE aliases or systemic follow-up fields that do
not belong to the current state.
"""
from __future__ import annotations

import re
from pathlib import Path


PSA_ALIASES = {"psa", "psa_value", "baseline_psa", "psa_baseline_ng_ml", "ape", "ape_basal"}
SYSTEMIC_FOLLOWUP_FIELDS = {
    "testosterone_value",
    "testosterone_history",
    "ctcae_grade_max",
    "hemoglobin",
    "alp",
    "ldh",
    "albumin",
}


def _router_field_names(router: dict) -> set[str]:
    return {
        field.get("name")
        for group in router.get("group_order") or []
        for field in group.get("fields") or []
        if field.get("name")
    }


def test_initial_staging_router_uses_single_ape_and_defers_systemic_followup():
    from prostanet.presentation.clinical_field_router import build_clinical_field_router

    localized = build_clinical_field_router("localized_initial", phase="longitudinal_followup")
    localized_names = _router_field_names(localized)
    assert localized_names & PSA_ALIASES == {"psa_value"}
    assert localized_names.isdisjoint(SYSTEMIC_FOLLOWUP_FIELDS)
    assert "imaging_modality_used_for_m_staging" in localized_names

    diagnostic = build_clinical_field_router("diagnostic_workup", phase="longitudinal_followup")
    diagnostic_names = _router_field_names(diagnostic)
    assert diagnostic_names & PSA_ALIASES == {"psa_value"}
    assert "prostate_volume_ml" in diagnostic_names
    assert "psa_density" not in diagnostic_names
    assert "psad" not in diagnostic_names
    assert diagnostic_names.isdisjoint(SYSTEMIC_FOLLOWUP_FIELDS | {"ecog_score"})


def test_clinical_field_router_api_keeps_localized_longitudinal_stage_relevant(app_client):
    client, _db_path = app_client

    response = client.get("/api/clinical-field-router/localized_initial?phase=longitudinal_followup")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    names = _router_field_names(payload)
    assert names & PSA_ALIASES == {"psa_value"}
    assert names.isdisjoint(SYSTEMIC_FOLLOWUP_FIELDS)


def test_localized_wizard_occam_is_available_but_not_prepopulated(app_client):
    client, _db_path = app_client

    response = client.get("/wizard/localized_initial")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert 'data-occam-widget="1"' in html
    assert 'data-occam-input="1"' in html
    assert 'data-occam-derived-input="1"' in html
    assert "function buildWizardPayload" in html
    assert "occamTouched" in html
    assert 'name="life_expectancy_years" value="15"' not in html
    assert not re.search(r'name="occam_height_cm"[^>]*value="170"', html)
    assert not re.search(r'name="occam_weight_kg"[^>]*value="78"', html)


def test_initial_staging_wizards_do_not_preload_example_clinical_facts(app_client):
    client, _db_path = app_client

    localized = client.get("/wizard/localized_initial").get_data(as_text=True)
    assert 'value="" selected>No documentado</option>' in localized
    assert not re.search(r'name="psa"[^>]*value="8\.5"', localized)
    assert not re.search(r'<option value="T2a" selected>', localized)
    assert not re.search(r'name="num_cores_positive"[^>]*value="2"', localized)
    assert not re.search(r'name="prostate_volume_ml"[^>]*value="40"', localized)

    diagnostic = client.get("/wizard/diagnostic_workup").get_data(as_text=True)
    assert 'value="" selected>No documentado</option>' in diagnostic
    assert not re.search(r'name="psa"[^>]*value="5\.8"', diagnostic)
    assert not re.search(r'<option value="Normal" selected>', diagnostic)


def test_localized_draft_without_occam_inputs_does_not_import_occam_defaults(app_client):
    client, _db_path = app_client

    draft = client.post(
        "/api/clinical-assessments/draft",
        json={
            "module_id": "localized_initial",
            "payload": {
                "age": 65,
                "psa": 12.2,
                "clinical_tstage": "T2b",
                "gleason_primary": 4,
                "gleason_secondary": 3,
                "isup_grade": 3,
                "num_cores_positive": 4,
                "total_cores": 12,
                "prostate_volume_ml": 40,
                "nodal_status": "N0",
                "metastasis_site": "M0",
            },
        },
    )
    assert draft.status_code == 200
    payload = draft.get_json()
    imported_names = {field.get("name") for field in payload.get("imported_clinical_fields", [])}

    assert "life_expectancy_years" not in imported_names
    assert not any(name and name.startswith("occam_") for name in imported_names)


def test_psa_history_line_context_options_are_state_scoped_for_longitudinal_capture():
    root = Path(__file__).resolve().parents[1]
    registration_js = (root / "static/js/registration_context_ui.js").read_text()
    longitudinal_js = (root / "static/js/longitudinal_capture_helpers.js").read_text()
    wizard_html = (root / "templates/clinical_wizard.html").read_text()

    assert "lineContextOptionsForState" in registration_js
    assert "lineContextOptionsForState" in longitudinal_js
    assert 'allowedValues = [""];' in registration_js
    assert 'allowedValues = [""];' in longitudinal_js
    assert "clinicalState: registrationAssessmentState.value" in wizard_html
    assert "${renderLineContextOptions(row.line_of_therapy_context || \"\", clinicalState)}" in registration_js
    assert "${renderLineContextOptions(row.line_of_therapy_context || \"\", clinicalState)}" in longitudinal_js


def test_localized_longitudinal_capture_v2_filters_default_surface_by_state(app_client):
    client, _db_path = app_client

    draft = client.post(
        "/api/clinical-assessments/draft",
        json={
            "module_id": "localized_initial",
            "payload": {
                "age": 65,
                "psa": 12.2,
                "clinical_tstage": "T2b",
                "gleason_primary": 4,
                "gleason_secondary": 3,
                "isup_grade": 3,
                "num_cores_positive": 4,
                "total_cores": 12,
                "prostate_volume_ml": 40,
                "nodal_status": "N0",
                "metastasis_site": "M0",
                "life_expectancy_years": 12,
            },
        },
    )
    assert draft.status_code == 200
    assessment_id = draft.get_json()["assessment_id"]

    patient_ref = "QA-STAGE-CAPTURE-001"
    register = client.post(
        "/api/register_patient",
        json={
            "assessment_id": assessment_id,
            "assessment_state": "localized_initial",
            "nss": patient_ref,
            "full_name": "Paciente Secuencia Captura",
            "dob": "1961-05-29",
            "psa_history": [{"sample_date": "2026-05-01", "psa_value": 12.2}],
        },
    )
    assert register.status_code == 200

    response = client.get(f"/longitudinal-capture/{patient_ref}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "pm2-longitudinal-state-localized_initial" in html
    assert "pm2-state-scoped-default" in html
    assert "disabledByClinicalScope" in html

    visible_cards = set(re.findall(r'data-capture-card="([^"]+)"', html))
    assert {"psa_new", "imaging", "biopsy_capture"} <= visible_cards
    assert visible_cards.isdisjoint({"lab_panel", "ctcae", "dexa", "treatment_change"})

    context_match = re.search(
        r'<script id="longitudinalClinicalFactLedgerContext" type="application/json">(.*?)</script>',
        html,
    )
    assert context_match
    assert "psa_baseline_ng_ml" not in html
