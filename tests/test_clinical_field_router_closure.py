from __future__ import annotations

from pathlib import Path


ROOT = Path("/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6")
OFFICIAL_CLASSIFIER = "/clinical-hub#pm2OfficialClassifier"


def _names(router: dict) -> set[str]:
    return {
        field["name"]
        for group in router["group_order"]
        for field in group["fields"]
    }


def _flat_name_blob(names: set[str]) -> str:
    return " ".join(sorted(names)).lower()


def test_router_bcr_initial_includes_salvage_and_excludes_crpc_domains():
    from prostanet.presentation.clinical_field_router import build_clinical_field_router

    router = build_clinical_field_router("recurrence_bcr", phase="initial_wizard")
    names = _names(router)
    blob = _flat_name_blob(names)

    assert {"psa_doubling_time_months", "prior_prostatectomy", "prior_radiation"} <= names
    assert {"salvage_rt_consideration_active", "psma_pet_staging_recent"} & names
    assert not any(token in blob for token in ("hrr", "parp", "castrate", "testosterone", "arpi", "ctcae"))
    assert router["summary"]["total_fields"] < 80


def test_router_m1_crpc_initial_includes_crpc_refiners_not_isolated_bcr():
    from prostanet.presentation.clinical_field_router import build_clinical_field_router

    router = build_clinical_field_router("m1_crpc", phase="initial_wizard")
    names = _names(router)
    blob = _flat_name_blob(names)

    assert {"hrr_status", "psma_pet_positive_current", "prior_treatment_lines_count"} <= names
    assert {"castrate_testosterone_status", "testosterone_value"} <= names
    assert not any(token in blob for token in ("bcr_detected", "phoenix", "psa_nadir_post_rt"))
    assert router["summary"]["total_fields"] < 80


def test_router_m0_crpc_longitudinal_prioritizes_monitoring_and_arpi_safety():
    from prostanet.presentation.clinical_field_router import build_clinical_field_router

    router = build_clinical_field_router("m0_crpc", phase="longitudinal_followup")
    names = _names(router)

    assert {"psa_value", "testosterone_value", "conventional_imaging_status"} <= names
    assert {"arpi_toxicity_review", "arpi_blood_pressure_monitoring", "dexa_due"} <= names
    assert router["groups"]["monitoring"]["field_count"] > 0
    assert router["summary"]["total_fields"] < 90


def test_router_localized_initial_includes_local_risk_and_excludes_crpc():
    from prostanet.presentation.clinical_field_router import build_clinical_field_router

    router = build_clinical_field_router("localized_initial", phase="initial_wizard")
    names = _names(router)
    blob = _flat_name_blob(names)

    assert {"clinical_risk_group", "gleason_score", "clinical_tstage"} <= names
    assert {"nodal_status", "metastasis_site", "life_expectancy_years"} <= names
    assert "hrr_status" not in names
    assert not any(token in blob for token in ("parp", "castrate", "testosterone", "arpi"))


def test_field_router_endpoint_and_new_patient_routes_point_to_official_classifier():
    import app as app_module

    flask_app = app_module.create_app({"TESTING": True, "LOAD_MODEL": False})
    with flask_app.test_client() as client:
        api = client.get("/api/clinical-field-router/recurrence_bcr?phase=initial_wizard")
        assert api.status_code == 200
        body = api.get_json()
        assert body["success"] is True
        assert body["groups"]["required"]["field_count"] > 0

        for path in (
            "/intake-wizard",
            "/intake-wizard?v=legacy",
            "/patient_intake",
            "/patient_intake?v=2",
            "/patient_intake?v=2&keep_legacy=1",
        ):
            response = client.get(path, follow_redirects=False)
            assert response.status_code in (301, 302, 303, 307, 308)
            assert OFFICIAL_CLASSIFIER in response.headers.get("Location", "")

        draft = client.get("/patient_intake?assessment_id=draft-001", follow_redirects=False)
        assert draft.status_code == 200


def test_visible_entry_points_do_not_link_to_retired_intake_routes():
    sidebar = (ROOT / "templates/components/pm2_sidebar.html").read_text()
    patients = (ROOT / "templates/patients_v2.html").read_text()
    calculator = (ROOT / "templates/calculator.html").read_text()

    visible_templates = "\n".join([sidebar, patients, calculator])
    assert OFFICIAL_CLASSIFIER in visible_templates
    assert 'href="/intake-wizard"' not in visible_templates
    assert 'href="/patient_intake"' not in visible_templates
    assert "/patient_intake?v=2" not in visible_templates
    assert "Wizard intake" not in visible_templates
    assert "Stage-Aware intake" not in visible_templates


def test_clinical_hub_does_not_autoload_stage_canvas_before_classification():
    from prostanet.presentation.v2_adapters import stage_center_to_v2

    template = (ROOT / "templates/demos/stage_clinical_center_v2_redesign.html").read_text()
    data = stage_center_to_v2()

    assert data["default_stage"] == ""
    assert 'data-stage-placeholder' in template
    assert '{% if stage_key != default_stage %}style="display:none"{% endif %}' in template


def test_clinical_hub_and_draft_intake_expose_transversal_navigation():
    hub = (ROOT / "templates/demos/stage_clinical_center_v2_redesign.html").read_text()
    draft = (ROOT / "templates/patient_intake.html").read_text()
    combined = "\n".join([hub, draft])

    assert 'aria-label="Navegación transversal de plataforma"' in hub
    assert 'aria-label="Navegación transversal de ingreso clínico"' in draft
    for href in (
        "/clinical-hub#pm2OfficialClassifier",
        "/patients",
        "/dashboard",
        "/clinical-hub",
    ):
        assert href in combined


def test_shared_logo_rules_preserve_full_asset_without_cropping():
    ui_theme = (ROOT / "static/ui_theme.css").read_text()
    v2_theme = (ROOT / "static/css/prostamed_v2.css").read_text()

    assert ".pm-auth-logo" in ui_theme
    assert "--pm2-logo-sidebar-width" in v2_theme
    assert "--pm2-logo-stage-width" in v2_theme
    assert ".pm2-demo-intake-logo" in v2_theme
    assert ".pm2-mobile-brand" in v2_theme
    assert "object-fit: cover" not in ui_theme
    assert "mask-image:" not in ui_theme
