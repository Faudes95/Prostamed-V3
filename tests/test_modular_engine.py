# IEC 62304 §5.5 (Unit verification)
import re
import sqlite3
from datetime import date, timedelta

from clinical_scores import calculate_all_scores
from prostanet.application.module_registry import ModuleRegistry
from prostanet.shared.presentation_text import humanize_result, humanize_schema, resolve_option_label


def _recent_docetaxel_labs(**overrides):
    payload = {
        "cbc_date": (date.today() - timedelta(days=3)).isoformat(),
        "anc": 2200,
        "platelets": 210000,
        "liver_panel_date": (date.today() - timedelta(days=4)).isoformat(),
        "bilirubin": 0.8,
        "ast": 32,
        "alt": 30,
        "alp": 110,
        "taxane_hypersensitivity_history": 0,
        "polysorbate_hypersensitivity": 0,
    }
    payload.update(overrides)
    return payload


def test_modular_metadata_and_hub_routes_are_available(app_client):
    client, _ = app_client

    root_response = client.get("/", follow_redirects=False)
    assert root_response.status_code == 302
    assert root_response.headers["Location"].endswith("/clinical-hub")

    calculator_response = client.get("/calculator", follow_redirects=False)
    assert calculator_response.status_code == 302
    assert calculator_response.headers["Location"].endswith("/clinical-hub")

    modules_response = client.get("/api/modules")
    assert modules_response.status_code == 200
    modules_data = modules_response.get_json()
    assert modules_data["success"] is True
    module_ids = {item["module"] for item in modules_data["modules"]}
    assert "diagnostic_workup" in module_ids
    assert "post_negative_biopsy_followup" in module_ids
    assert "localized_initial" in module_ids
    assert "recurrence_bcr" in module_ids
    assert "post_radiotherapy_or_local_salvage" in module_ids
    assert "survivorship_and_toxicity_followup" in module_ids
    assert "adt_progression_verification" in module_ids
    assert "m1_crpc" in module_ids

    guideline_response = client.get("/api/guidelines/metadata")
    assert guideline_response.status_code == 200
    guideline_data = guideline_response.get_json()
    assert guideline_data["success"] is True
    assert guideline_data["guidelines"]["nccn_2026"]["version"] == "5.2026"
    assert guideline_data["guidelines"]["eau_2026"]["version"] == "2026"

    schema_response = client.get("/api/modules/localized_initial/schema")
    assert schema_response.status_code == 200
    schema_data = schema_response.get_json()
    assert schema_data["success"] is True
    assert "ISUP grade group" not in str(schema_data)
    assert "Grupo de grado de la Sociedad Internacional de Patología Urológica" in str(schema_data)
    localized_fields = {field["name"] for field in schema_data["schema"]["fields"]}
    assert "prior_mpmri_pirads_score" in localized_fields
    assert "adverse_histology_variant_type" in localized_fields
    assert "frailty_status" in localized_fields
    assert "g8_score" in localized_fields
    assert "anesthesia_surgical_fitness" in localized_fields
    assert "radiotherapy_feasibility" in localized_fields
    assert "patient_priority_profile" in localized_fields
    assert "epic26_response_packet" in localized_fields
    assert "epic26_urinary_domain" not in localized_fields

    diagnostic_schema_response = client.get("/api/modules/diagnostic_workup/schema")
    assert diagnostic_schema_response.status_code == 200
    diagnostic_schema_data = diagnostic_schema_response.get_json()
    lesion_field = next(
        field for field in diagnostic_schema_data["schema"]["fields"] if field["name"] == "index_lesion_location"
    )
    assert lesion_field["field_type"] == "select"
    assert lesion_field["default"] == "No especificada"
    assert "Zona periférica posterior" in lesion_field["options"]

    classifier_schema_response = client.get("/api/modules/state-classifier/schema")
    assert classifier_schema_response.status_code == 200
    classifier_schema_data = classifier_schema_response.get_json()
    classifier_fields = {field["name"]: field for field in classifier_schema_data["schema"]["fields"]}
    assert classifier_fields["prior_prostatectomy"]["label"] == "Prostatectomía radical previa por cáncer de próstata"
    assert classifier_fields["prior_radiation"]["label"] == "Radioterapia previa por cáncer de próstata"
    assert classifier_fields["bcr_detected"]["label"] == "Recurrencia bioquímica y segunda recurrencia bioquímica sin metástasis"
    assert classifier_fields["bcr2"]["label"] == "Segunda recurrencia bioquímica tras tratamiento local"
    assert "Oligometastatic" not in classifier_fields["metastasis_site"]["options"]

    # Faubot LXXXIV.b: post-LXXX `/clinical-hub` rendea v2 por default; este
    # test legacy assertía contenido v1, opt-out con `?v=legacy` preserva intent.
    hub_response = client.get("/clinical-hub?v=legacy")
    assert hub_response.status_code == 200
    hub_html = hub_response.get_data(as_text=True)
    assert "Centro clínico por estadio" in hub_html
    assert "Legacy calculator" not in hub_html
    assert "Diagnóstico confirmado de cáncer de próstata" in hub_html
    assert "Biopsia prostática previa benigna" in hub_html
    assert "Contexto de progresión sistémica" in hub_html
    assert "No aplica / sin contexto de progresión bajo ADT" in hub_html
    assert "Progresión bajo ADT: verificar castración" in hub_html
    assert "1. Confirmación diagnóstica" in hub_html
    assert "2. Tratamiento local previo y recurrencia" in hub_html
    assert "3. Enfermedad metastásica conocida" in hub_html
    assert "4. Progresión bajo ADT / CRPC" in hub_html
    assert "Seguimiento y secuelas" in hub_html
    assert "Survivorship y toxicidad por tratamiento" in hub_html
    assert "Prostatectomía radical previa por cáncer de próstata" in hub_html
    assert "Radioterapia previa por cáncer de próstata" in hub_html
    assert "Recurrencia bioquímica y segunda recurrencia bioquímica sin metástasis" in hub_html
    assert "Segunda recurrencia bioquímica tras tratamiento local" in hub_html
    assert "Sí, abrir asistente de BCR" not in hub_html
    assert "No, abrir seguimiento post-tratamiento local" not in hub_html
    assert "Este contexto solo aplica cuando ya existe cáncer de próstata confirmado" in hub_html
    assert 'name="volume_disease"' not in hub_html
    assert 'value="Oligometastatic"' not in hub_html
    assert "Distribución de metástasis óseas" in hub_html
    assert "Esqueleto axial" in hub_html
    assert "Esqueleto apendicular" in hub_html
    assert "md:hidden" in hub_html

    # Faubot LXXXIV.b: post-LXXX `/patients` rendea v2 por default; opt-out
    # con `?v=legacy` preserva contrato v1 (ui_theme.css + clinical_selects.js).
    patients_html = client.get("/patients?v=legacy").get_data(as_text=True)
    assert "ui_theme.css" in patients_html
    assert "clinical_selects.js" in patients_html
    assert "Registro longitudinal de pacientes" in patients_html
    assert "Nuevo caso clínico" in patients_html


def test_localized_wizard_embeds_occam_inputs_inside_dynamic_widget(app_client):
    client, _ = app_client

    response = client.get("/wizard/localized_initial")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert 'data-occam-widget="1"' in html
    assert "Entradas estructuradas del modelo OCCAM" in html
    assert "Variantes opcionales del modelo OCCAM" in html
    assert html.count('name="occam_diabetes"') == 1
    assert html.count('name="occam_education"') == 1
    assert html.count("Pronóstico de otras causas (OCCAM)") == 0
    assert "lg:grid-cols-[minmax(0,1.1fr)_minmax(360px,0.9fr)]" not in html
    occam_match = re.search(r'class="([^"]*md:col-span-2[^"]*)"[^>]*data-field-wrapper[^>]*data-field-name="life_expectancy_years"', html)
    epic_match = re.search(r'class="([^"]*md:col-span-2[^"]*)"[^>]*data-field-wrapper[^>]*data-field-name="epic26_response_packet"', html)
    assert occam_match is not None
    assert epic_match is not None
    assert "xl:grid-cols-[minmax(300px,0.9fr)_minmax(0,1.1fr)]" in html
    assert "xl:grid-cols-[minmax(280px,0.85fr)_minmax(0,1.15fr)]" in html

    # Faubot LXXXIV.b: post-LXXX `/dashboard` rendea v2 por default; opt-out
    # con `?v=legacy` preserva contrato v1 (ui_theme.css + clinical_selects.js).
    dashboard_html = client.get("/dashboard?v=legacy").get_data(as_text=True)
    assert "ui_theme.css" in dashboard_html
    assert "clinical_selects.js" in dashboard_html
    assert "Panorama longitudinal de la cohorte" in dashboard_html
    assert "/api/dashboard/summary" in dashboard_html
    assert "/api/dashboard/analytics" in dashboard_html
    assert "/api/dashboard/calibration" in dashboard_html
    assert "Promise.all([\n                    fetch('/api/patients').then(r => r.json()),\n                    fetch('/api/dashboard_stats')" not in dashboard_html


def test_state_classifier_routes_patients_to_expected_modules(app_client):
    client, _ = app_client

    localized = client.post("/api/state-classifier", json={"metastasis_site": "M0"})
    assert localized.status_code == 200
    assert localized.get_json()["state"] == "localized_initial"
    assert "No se detectaron tratamientos locales previos" in localized.get_json()["classification_reason"]

    diagnostic = client.post(
        "/api/state-classifier",
        json={"known_cancer_diagnosis": 0, "prior_negative_biopsy": 0, "metastasis_site": "M0"},
    )
    assert diagnostic.status_code == 200
    assert diagnostic.get_json()["state"] == "diagnostic_workup"

    diagnostic_residual = client.post(
        "/api/state-classifier",
        json={
            "known_cancer_diagnosis": 0,
            "prior_negative_biopsy": 0,
            "prior_prostatectomy": 1,
            "prior_radiation": 1,
            "bcr2": 1,
            "systemic_progression_context": "confirmed_crpc",
            "current_adt_context": "medical_adt_continuous",
            "castrate_testosterone_status": "confirmed_castrate",
            "conventional_imaging_status": "M1",
            "metastasis_site": "Bone",
            "metastasis_count": 4,
            "metachronous_metastasis": 1,
            "volume_disease": "High",
        },
    )
    assert diagnostic_residual.status_code == 200
    assert diagnostic_residual.get_json()["state"] == "diagnostic_workup"

    benign_followup = client.post(
        "/api/state-classifier",
        json={"known_cancer_diagnosis": 0, "prior_negative_biopsy": 1, "metastasis_site": "M0"},
    )
    assert benign_followup.status_code == 200
    assert benign_followup.get_json()["state"] == "post_negative_biopsy_followup"

    benign_followup_residual = client.post(
        "/api/state-classifier",
        json={
            "known_cancer_diagnosis": 0,
            "prior_negative_biopsy": 1,
            "prior_prostatectomy": 1,
            "bcr2": 1,
            "systemic_progression_context": "progression_on_adt_verify_castration",
            "current_adt_context": "medical_adt_continuous",
            "castrate_testosterone_status": "unknown",
            "metastasis_site": "Bone",
            "metastasis_count": 3,
            "volume_disease": "High",
        },
    )
    assert benign_followup_residual.status_code == 200
    assert benign_followup_residual.get_json()["state"] == "post_negative_biopsy_followup"

    recurrence = client.post(
        "/api/state-classifier",
        json={"prior_prostatectomy": 1, "psa_current": 0.4, "metastasis_site": "M0"},
    )
    assert recurrence.status_code == 200
    recurrence_payload = recurrence.get_json()
    assert recurrence_payload["state"] == "post_prostatectomy"
    assert "vigilancia reforzada" in recurrence_payload["classification_reason"].lower()

    confirmed_recurrence = client.post(
        "/api/state-classifier",
        json={"prior_prostatectomy": 1, "psa_current": 0.4, "bcr_confirmed": 1, "metastasis_site": "M0"},
    )
    assert confirmed_recurrence.status_code == 200
    assert confirmed_recurrence.get_json()["state"] == "recurrence_bcr"

    longitudinal_confirmed_recurrence = client.post(
        "/api/state-classifier",
        json={
            "prior_prostatectomy": 1,
            "metastasis_site": "M0",
            "psa_history": [
                {"value": 0.22, "date": "2026-01-01"},
                {"value": 0.31, "date": "2026-04-15"},
            ],
        },
    )
    assert longitudinal_confirmed_recurrence.status_code == 200
    assert longitudinal_confirmed_recurrence.get_json()["state"] == "recurrence_bcr"

    bcr_post_prostatectomy = client.post(
        "/api/state-classifier",
        json={"prior_prostatectomy": 1, "bcr_detected": 1, "metastasis_site": "M0"},
    )
    assert bcr_post_prostatectomy.status_code == 200
    assert bcr_post_prostatectomy.get_json()["state"] == "recurrence_bcr"

    post_prostatectomy_followup = client.post(
        "/api/state-classifier",
        json={"prior_prostatectomy": 1, "bcr_detected": 0, "metastasis_site": "M0"},
    )
    assert post_prostatectomy_followup.status_code == 200
    assert post_prostatectomy_followup.get_json()["state"] == "post_prostatectomy"

    post_rt_recurrence = client.post(
        "/api/state-classifier",
        json={
            "prior_prostatectomy": 0,
            "prior_radiation": 1,
            "psa_current": 1.4,
            "phoenix_failure_confirmed": 1,
            "metastasis_site": "M0",
        },
    )
    assert post_rt_recurrence.status_code == 200
    assert post_rt_recurrence.get_json()["state"] == "post_radiotherapy_or_local_salvage"

    bcr_post_radiation = client.post(
        "/api/state-classifier",
        json={"prior_prostatectomy": 0, "prior_radiation": 1, "bcr_detected": 1, "metastasis_site": "M0"},
    )
    assert bcr_post_radiation.status_code == 200
    assert bcr_post_radiation.get_json()["state"] == "recurrence_bcr"

    post_rt_followup = client.post(
        "/api/state-classifier",
        json={"prior_prostatectomy": 0, "prior_radiation": 1, "bcr_detected": 0, "metastasis_site": "M0"},
    )
    assert post_rt_followup.status_code == 200
    assert post_rt_followup.get_json()["state"] == "post_radiotherapy_followup"

    crpc = client.post(
        "/api/state-classifier",
        json={"castration_resistant": 1, "metastasis_site": "Bone"},
    )
    assert crpc.status_code == 200
    assert crpc.get_json()["state"] == "m1_crpc"

    psma_only_crpc = client.post(
        "/api/state-classifier",
        json={
            "known_cancer_diagnosis": 1,
            "systemic_progression_context": "confirmed_crpc",
            "current_adt_context": "medical_adt_continuous",
            "castrate_testosterone_status": "confirmed_castrate",
            "conventional_imaging_status": "M0",
            "psma_stage_after_psma": "M1A",
            "psma_pet_done": 1,
            "psma_positive": 1,
        },
    )
    assert psma_only_crpc.status_code == 200
    psma_only_payload = psma_only_crpc.get_json()
    assert psma_only_payload["state"] == "adt_progression_verification"
    assert psma_only_payload["psma_only_upstaging"] is True
    assert psma_only_payload["metastatic_detection_basis"] == "psma_only"
    assert psma_only_payload["restaging_update_required"] is True

    adt_verification = client.post(
        "/api/state-classifier",
        json={
            "known_cancer_diagnosis": 1,
            "systemic_progression_context": "progression_on_adt_verify_castration",
            "current_adt_context": "medical_adt_continuous",
            "castrate_testosterone_status": "unknown",
            "progression_pattern": "biochemical_only",
            "conventional_imaging_status": "not_restaged",
            "prior_prostatectomy": 1,
        },
    )
    assert adt_verification.status_code == 200
    assert adt_verification.get_json()["state"] == "adt_progression_verification"

    gated_high_volume = client.post(
        "/api/state-classifier",
        json={
            "known_cancer_diagnosis": 1,
            "systemic_progression_context": "progression_on_adt_verify_castration",
            "current_adt_context": "medical_adt_continuous",
            "castrate_testosterone_status": "unknown",
            "progression_pattern": "radiographic",
            "conventional_imaging_status": "not_restaged",
            "metastasis_site": "Bone",
            "bone_site_entries": [
                {"site_key": "thoracic_spine", "lesion_count": 3},
                {"site_key": "femur", "lesion_count": 1},
            ],
            "metachronous_metastasis": 0,
        },
    )
    assert gated_high_volume.status_code == 200
    gated_high_volume_payload = gated_high_volume.get_json()
    assert gated_high_volume_payload["state"] == "mcspc_high_volume_sync"
    assert gated_high_volume_payload["phenotype_state"] == "mcspc_high_volume_sync"
    assert gated_high_volume_payload["progression_gate_active"] is True
    assert gated_high_volume_payload["progression_gate_target"] == "adt_progression_verification"
    assert gated_high_volume_payload["systemic_progression_context_resolved"] == "progression_on_adt_verify_castration"
    assert "bloqueada" in gated_high_volume_payload["classification_reason"].lower()


def test_m0_crpc_sparse_payload_does_not_assume_castration_or_negative_imaging(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/m0_crpc/evaluate",
        json={
            "psadt_months": 6,
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]

    assert result["preferred_frontline_regimen"]["regimen_code"] == "ADT_MONO"
    assert result["decision_quality"]["requires_human_review"] is True
    assert any("castracion" in item.lower() for item in result["why_not_more_confident"])

    gated_low_volume_metach = client.post(
        "/api/state-classifier",
        json={
            "known_cancer_diagnosis": 1,
            "systemic_progression_context": "progression_on_adt_verify_castration",
            "current_adt_context": "medical_adt_continuous",
            "castrate_testosterone_status": "unknown",
            "progression_pattern": "biochemical_only",
            "conventional_imaging_status": "not_restaged",
            "metastasis_site": "Bone",
            "bone_site_entries": [
                {"site_key": "thoracic_spine", "lesion_count": 2},
                {"site_key": "pelvis_sacrum", "lesion_count": 1},
            ],
            "metachronous_metastasis": 1,
        },
    )
    assert gated_low_volume_metach.status_code == 200
    gated_low_volume_payload = gated_low_volume_metach.get_json()
    assert gated_low_volume_payload["state"] == "mcspc_oligo_metachronous"
    assert gated_low_volume_payload["progression_gate_active"] is True

    nmcrpc = client.post(
        "/api/state-classifier",
        json={
            "known_cancer_diagnosis": 1,
            "systemic_progression_context": "confirmed_crpc",
            "castrate_testosterone_status": "confirmed_castrate",
            "conventional_imaging_status": "M0",
        },
    )
    assert nmcrpc.status_code == 200
    assert nmcrpc.get_json()["state"] == "m0_crpc"

    high_volume_sync = client.post(
        "/api/state-classifier",
        json={
            "known_cancer_diagnosis": 1,
            "metastasis_site": "Bone",
            "bone_site_entries": [
                {"site_key": "thoracic_spine", "lesion_count": 2},
                {"site_key": "pelvis_sacrum", "lesion_count": 2},
                {"site_key": "femur", "lesion_count": 1},
            ],
            "metachronous_metastasis": 0,
        },
    )
    assert high_volume_sync.status_code == 200
    high_volume_sync_payload = high_volume_sync.get_json()
    assert high_volume_sync_payload["state"] == "mcspc_high_volume_sync"
    assert high_volume_sync_payload["derived_metastatic_context"]["volume_disease"] == "high"
    assert high_volume_sync_payload["derived_metastatic_context"]["bone_appendicular_count"] == 1

    high_volume_metachronous = client.post(
        "/api/state-classifier",
        json={
            "known_cancer_diagnosis": 1,
            "metastasis_site": "Bone",
            "bone_site_entries": [
                {"site_key": "thoracic_spine", "lesion_count": 1},
                {"site_key": "lumbar_spine", "lesion_count": 2},
                {"site_key": "humerus", "lesion_count": 1},
            ],
            "metachronous_metastasis": 1,
        },
    )
    assert high_volume_metachronous.status_code == 200
    high_volume_metachronous_payload = high_volume_metachronous.get_json()
    assert high_volume_metachronous_payload["state"] == "mcspc_high_volume_metachronous"
    assert high_volume_metachronous_payload["derived_metastatic_context"]["volume_disease"] == "high"

    low_volume_axial = client.post(
        "/api/state-classifier",
        json={
            "known_cancer_diagnosis": 1,
            "metastasis_site": "Bone",
            "bone_site_entries": [
                {"site_key": "thoracic_spine", "lesion_count": 2},
                {"site_key": "lumbar_spine", "lesion_count": 1},
                {"site_key": "pelvis_sacrum", "lesion_count": 1},
            ],
            "metachronous_metastasis": 0,
        },
    )
    assert low_volume_axial.status_code == 200
    low_volume_axial_payload = low_volume_axial.get_json()
    assert low_volume_axial_payload["state"] == "mcspc_low_volume_sync_oligo"
    assert low_volume_axial_payload["derived_metastatic_context"]["volume_disease"] == "low"
    assert low_volume_axial_payload["derived_metastatic_context"]["bone_appendicular_count"] == 0

    low_volume_metachronous = client.post(
        "/api/state-classifier",
        json={
            "known_cancer_diagnosis": 1,
            "metastasis_site": "Bone",
            "bone_site_entries": [
                {"site_key": "thoracic_spine", "lesion_count": 2},
                {"site_key": "pelvis_sacrum", "lesion_count": 1},
            ],
            "metachronous_metastasis": 1,
        },
    )
    assert low_volume_metachronous.status_code == 200
    low_volume_metachronous_payload = low_volume_metachronous.get_json()
    assert low_volume_metachronous_payload["state"] == "mcspc_oligo_metachronous"
    assert low_volume_metachronous_payload["derived_metastatic_context"]["oligometastatic_operational"] is True


def test_mhspc_modules_use_mixed_metastatic_context_for_logic(app_client):
    client, _ = app_client

    schema_response = client.get("/api/modules/mcspc_high_volume_sync/schema")
    assert schema_response.status_code == 200
    schema_fields = {field["name"] for field in schema_response.get_json()["schema"]["fields"]}
    assert "metastatic_components_capture" in schema_fields
    assert "metastasis_site" not in schema_fields
    assert {
        "cbc_date",
        "anc",
        "platelets",
        "liver_panel_date",
        "bilirubin",
        "ast",
        "alt",
        "alp",
        "taxane_hypersensitivity_history",
        "polysorbate_hypersensitivity",
    }.issubset(schema_fields)
    anc_field = next(field for field in schema_response.get_json()["schema"]["fields"] if field["name"] == "anc")
    performance_driver_field = next(
        field for field in schema_response.get_json()["schema"]["fields"] if field["name"] == "performance_status_driver"
    )
    assert anc_field["conditional_visibility"]["frailty_status"] == ["", "Fit", "Vulnerable"]
    assert performance_driver_field["conditional_visibility"]["ecog_score"] == ["2"]

    response = client.post(
        "/api/modules/mcspc_high_volume_sync/evaluate",
        json={
            "metastatic_components_capture": {
                "metastatic_disease_known": True,
                "components": ["bone", "visceral", "nodes"],
                "bone_site_entries": [
                    {"site_key": "thoracic_spine", "lesion_count": 2},
                    {"site_key": "femur", "lesion_count": 1},
                ],
                "visceral_site_entries": [
                    {"site_key": "liver", "lesion_count": 2},
                ],
                "nonregional_nodal_site_entries": [
                    {"site_key": "retroperitoneal", "lesion_count": 1},
                ],
            },
            "metastatic_disease_known": 1,
            "metastasis_site": "Visceral",
            "bone_site_entries": [
                {"site_key": "thoracic_spine", "lesion_count": 2},
                {"site_key": "femur", "lesion_count": 1},
            ],
            "visceral_site_entries": [
                {"site_key": "liver", "lesion_count": 2},
            ],
            "nonregional_nodal_site_entries": [
                {"site_key": "retroperitoneal", "lesion_count": 1},
            ],
            "metastasis_count": 5,
            "volume_disease": "High",
            "ecog": 1,
            "docetaxel_fit": 1,
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    # BUG ERR-04: supportive-care bundles must NOT pollute ``eligible_treatments``
    # anymore — they live on their own ``supportive_care_bundle`` container.
    supportive_names = [item.get("name", "").lower() for item in (result.get("supportive_care_bundle") or [])]
    assert any("calcio + vitamina d" in name for name in supportive_names)
    assert any("zoledr" in name or "denosumab" in name for name in supportive_names)
    treatment_names = [item["name"].lower() for item in result["eligible_treatments"]]
    assert not any("calcio + vitamina d" in name for name in treatment_names)
    assert result["report_sections"]["bone_health_bundle"]["dxa_baseline_done"] is False
    assert "mixta" in result["report_sections"]["summary"].lower()
    assert "bundle óseo" in result["report_sections"]["summary"].lower()


def test_palliative_transition_triggers_urgent_local_palliation_and_full_agenda_packages():
    from prostanet.domains.patient_tracking.followup_agenda import build_agenda_board
    from prostanet.domains.patient_tracking.palliative_longitudinal import build_palliative_transition_bundle

    today = date.today().isoformat()
    patient = {
        "identity": {"diagnosis_date": "2025-01-10"},
        "latest_assessment": {
            "state": "m1_crpc",
            "result_snapshot": {
                "preferred_frontline_regimen": {
                    "regimen_code": "ADT_DAROLUTAMIDE",
                    "family_code": "arpi_family",
                },
                "sequence_transition_bundle": {
                    "active_family": "arpi_family",
                    "active_regimen_code": "ADT_DAROLUTAMIDE",
                    "trigger_status": "continue",
                },
                "active_regimen_monitoring_package": {
                    "family_code": "arpi_family",
                    "active_regimen_code": "ADT_DAROLUTAMIDE",
                    "active_regimen_label": "ADT + darolutamida",
                    "monitoring_focus": "Seguimiento ARPI",
                    "required_visit_fields": ["psa", "testosterone", "fatigue_score"],
                    "recommended_cadence": "cada 4-6 semanas",
                },
            },
        },
        "follow_ups": [
            {
                "visit_date": today,
                "pain": 9,
                "bpi_worst_pain": 9,
                "bone_pain": 1,
                "opioid_use": 1,
                "breakthrough_pain": 1,
                "bowel_regimen_started": 0,
                "fatigue_score": 7,
                "ecog": 2,
                "refractory_pain": 1,
                "spinal_cord_compression": 1,
                "pathological_fracture_risk": 1,
                "advance_directive_documented": 0,
                "goals_of_care_discussed": 0,
                "healthcare_surrogate_designated": 0,
                "patient_prefers_comfort": 0,
                "prior_systemic_lines": 2,
                "current_treatment": "ADT_DAROLUTAMIDE",
                "drug_scheme": "ADT_DAROLUTAMIDE",
            }
        ],
        "source_documents": [],
    }

    transition = build_palliative_transition_bundle(
        patient,
        state="m1_crpc",
        management_track="on_arpi",
        latest_assessment=patient["latest_assessment"],
    )

    assert transition["care_mode"] == "concurrent_palliative_care"
    assert transition["trigger_status"] == "urgent_local_palliation"
    assert transition["trigger_reasons"]

    agenda = build_agenda_board(patient, "m1_crpc", "concurrent_palliative_care", patient["latest_assessment"])
    agenda_titles = {str(item.get("title") or "") for item in agenda["items"]}
    assert "Control sintomático paliativo" in agenda_titles
    assert "Seguridad analgésica y opioides" in agenda_titles
    assert "Urgencias oncológicas paliativas" in agenda_titles
    assert "Objetivos de cuidado y planeación anticipada" in agenda_titles
    assert "Elegibilidad hospice y soporte exclusivo" in agenda_titles
    assert "Paliación local y RT ósea" in agenda_titles
    assert "Soporte psicosocial y cuidador" in agenda_titles


def test_palliative_transition_can_redirect_to_supportive_only_with_hospice_signal():
    from prostanet.domains.patient_tracking.palliative_longitudinal import build_palliative_transition_bundle

    patient = {
        "identity": {"diagnosis_date": "2024-02-10"},
        "follow_ups": [
            {
                "visit_date": date.today().isoformat(),
                "pain": 6,
                "bpi_worst_pain": 6,
                "ecog": 3,
                "weight_loss_6m_pct": 14,
                "albumin": 2.7,
                "patient_prefers_comfort": 1,
                "prior_systemic_lines": 4,
                "advance_directive_documented": 1,
                "goals_of_care_discussed": 1,
                "healthcare_surrogate_designated": 1,
            }
        ],
        "latest_assessment": {"state": "m1_crpc"},
        "source_documents": [],
    }

    transition = build_palliative_transition_bundle(
        patient,
        state="m1_crpc",
        management_track="on_docetaxel",
        latest_assessment=patient["latest_assessment"],
    )

    assert transition["care_mode"] in {"supportive_only", "hospice_pathway"}
    assert transition["trigger_status"] in {"redirect_supportive_only", "hospice_candidate"}
    assert transition["supportive_priority"] == "dominant"

def test_mhspc_and_m1_crpc_preserve_mixed_metastatic_context_in_explanations():
    from prostanet.domains.mcspc_high_volume.service import McspcHighVolumeSyncService
    from prostanet.domains.patient_tracking.mhspc_copilot_service import MhspcCopilotService

    result = McspcHighVolumeSyncService().evaluate(
        {
            "metastatic_components_capture": {
                "metastatic_disease_known": True,
                "components": ["bone", "visceral", "nodes"],
                "bone_site_entries": [
                    {"site_key": "thoracic_spine", "lesion_count": 2},
                    {"site_key": "femur", "lesion_count": 1},
                ],
                "visceral_site_entries": [{"site_key": "liver", "lesion_count": 2}],
                "nonregional_nodal_site_entries": [{"site_key": "retroperitoneal", "lesion_count": 1}],
            },
            "metastatic_disease_known": 1,
            "metastasis_site": "Visceral",
            "bone_site_entries": [
                {"site_key": "thoracic_spine", "lesion_count": 2},
                {"site_key": "femur", "lesion_count": 1},
            ],
            "visceral_site_entries": [{"site_key": "liver", "lesion_count": 2}],
            "nonregional_nodal_site_entries": [{"site_key": "retroperitoneal", "lesion_count": 1}],
            "metastasis_count": 5,
            "volume_disease": "High",
            "ecog": 1,
            "docetaxel_fit": 1,
        }
    )
    copilot = MhspcCopilotService()
    phenotype_summary = copilot._build_phenotype_summary(
        {
            "metastatic_disease_known": 1,
            "metastasis_site": "Visceral",
            "bone_site_entries": [
                {"site_key": "thoracic_spine", "lesion_count": 2},
                {"site_key": "femur", "lesion_count": 1},
            ],
            "visceral_site_entries": [{"site_key": "liver", "lesion_count": 2}],
            "nonregional_nodal_site_entries": [{"site_key": "retroperitoneal", "lesion_count": 1}],
            "metastasis_count": 5,
            "volume_disease": "High",
            "ecog": 1,
            "docetaxel_fit": 1,
        },
        "mcspc_high_volume_sync",
        result,
    )
    why_changed_today = copilot._build_why_changed_today(
        {
            "metastasis_count": 5,
            "ecog": 1,
        },
        phenotype_summary,
        result,
    )
    assert phenotype_summary["has_mixed_metastatic_sites"] is True
    assert phenotype_summary["bone_present"] is True
    assert phenotype_summary["visceral_present"] is True
    assert phenotype_summary["nonregional_nodal_present"] is True
    assert "mixta" in " ".join(why_changed_today).lower() or "visceral" in " ".join(why_changed_today).lower()

    from prostanet.domains.m1_crpc.service import M1CrpcService

    m1_result = M1CrpcService().evaluate(
        {
            "metastatic_disease_known": 1,
            "castrate_testosterone_status": "confirmed_castrate",
            "testosterone": 18,
            "metastasis_site": "Visceral",
            "bone_site_entries": [
                {"site_key": "thoracic_spine", "lesion_count": 2},
                {"site_key": "femur", "lesion_count": 1},
            ],
            "visceral_site_entries": [
                {"site_key": "liver", "lesion_count": 2},
            ],
            "nonregional_nodal_site_entries": [{"site_key": "retroperitoneal", "lesion_count": 1}],
            "conventional_imaging_status": "M1c",
            "prior_therapy": ["abiraterona"],
            "psma_pet_done": 1,
            "psma_positive": 1,
            "psma_rads_score": "5",
            "psma_uptake_pattern": "difuso",
        }
    )
    assert "mixta" in m1_result["report_sections"]["summary"].lower()
    assert "bundle óseo" in m1_result["report_sections"]["summary"].lower()
    assert m1_result["nccn_primary"]["resumen_del_caso"]
    assert "m1c" in m1_result["nccn_primary"]["resumen_del_caso"].lower()
    assert "retroperitoneal" in m1_result["nccn_primary"]["resumen_del_caso"].lower()


def test_localized_module_uses_nccn_2026_and_eau_2026_logic(app_client):
    client, _ = app_client

    low_payload = {
        "age": 62,
        "psa": 5.0,
        "clinical_tstage": "T1c",
        "gleason_primary": 3,
        "gleason_secondary": 3,
        "isup_grade": 1,
        "num_cores_positive": 2,
        "total_cores": 12,
        "max_core_involvement": 0.10,
        "psad": 0.10,
        "life_expectancy_years": 15,
        "prior_mpmri": 1,
        "prior_mpmri_pirads_score": "2",
        "prior_mpmri_targeted_biopsy_status": "si",
        "confirmatory_biopsy_planned": 1,
        "cribriform_pattern": 0,
        "intraductal_carcinoma": 0,
        "nodal_status": "N0",
        "metastasis_site": "M0",
    }

    response = client.post("/api/modules/localized_initial/evaluate", json=low_payload)
    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["nccn_primary"]["risk_group"] == "LOW"
    assert result["nccn_primary"]["label"] != "Very Low"
    assert result["eau_comparison"]["risk_group"] == "LOW"
    assert result["applicability_badge_key"] in {"preferred", "guideline-consistent"}
    assert result["nccn_primary"]["titulo_clinico"]
    assert result["nccn_primary"]["resumen_del_caso"]
    assert result["nccn_primary"]["trayectoria_recomendada"]
    assert len(result["nccn_primary"]["fundamentos_personalizados"]) >= 2
    assert "structured_summary" in result["report_sections"]

    gg3_payload = low_payload | {
        "psa": 8.5,
        "clinical_tstage": "T2a",
        "gleason_primary": 4,
        "gleason_secondary": 3,
        "isup_grade": 3,
        "num_cores_positive": 4,
        "psad": 0.18,
    }
    response = client.post("/api/modules/localized_initial/evaluate", json=gg3_payload)
    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["nccn_primary"]["risk_group"] == "UNFAVORABLE INTERMEDIATE"
    assert result["eau_comparison"]["risk_group"] == "INTERMEDIATE (UNFAVORABLE)"


def test_adt_progression_verification_requires_castration_before_crpc_redirection(app_client):
    client, _ = app_client

    not_castrate = client.post(
        "/api/modules/adt_progression_verification/evaluate",
        json={
            "current_adt_context": "medical_adt_continuous",
            "castrate_testosterone_status": "not_castrate",
            "testosterone_value": 180,
            "progression_pattern": "biochemical_only",
            "conventional_imaging_status": "M0",
            "psadt_months": 8,
        },
    )
    assert not_castrate.status_code == 200
    not_castrate_result = not_castrate.get_json()["result"]
    assert not_castrate_result["decision_quality"]["state_classification"] == "Fracaso de supresión androgénica o castración inadecuada"
    assert "optimizar" in not_castrate_result["eligible_treatments"][0]["name"].lower()


def test_localized_initial_uses_spanish_copy_for_recommended_trajectory(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/localized_initial/evaluate",
        json={
            "age": 70,
            "life_expectancy_years": 14,
            "psa": 18,
            "clinical_tstage": "T2c",
            "gleason_primary": 4,
            "gleason_secondary": 4,
            "isup_grade": 4,
            "num_cores_positive": 5,
            "total_cores": 12,
            "nodal_status": "N0",
            "metastasis_site": "M0",
            "ecog_score": "0",
            "charlson_score": 1,
            "frailty_status": "Fit",
            "g8_score": 15,
            "anesthesia_surgical_fitness": "Fit",
            "radiotherapy_feasibility": "feasible",
            "brachy_feasibility": "conditional",
            "baseline_obstruction": "none",
            "patient_priority_profile": "maximize_cancer_control,avoid_surgery",
        },
    )
    assert response.status_code == 200
    result = response.get_json()["result"]
    trajectory = result["nccn_primary"]["trayectoria_recomendada"]
    summary = result["nccn_primary"]["resumen_del_caso"]

    assert "plus short-course" not in trajectory
    assert "EBRT plus" not in trajectory
    assert "Consider definitive RT" not in trajectory
    assert "Radioterapia" in trajectory
    assert "terapia de privación androgénica" in trajectory
    assert " High." not in summary

    nmcrpc = client.post(
        "/api/modules/adt_progression_verification/evaluate",
        json={
            "current_adt_context": "medical_adt_continuous",
            "castrate_testosterone_status": "confirmed_castrate",
            "testosterone_value": 18,
            "progression_pattern": "biochemical_only",
            "conventional_imaging_status": "M0",
            "psadt_months": 7,
        },
    )
    assert nmcrpc.status_code == 200
    nmcrpc_result = nmcrpc.get_json()["result"]
    assert nmcrpc_result["decision_quality"]["state_classification"] == "Candidato confirmado a enfermedad resistente a la castración sin metástasis"
    assert "sin metástasis" in nmcrpc_result["eligible_treatments"][0]["name"].lower()

    mcrpc = client.post(
        "/api/modules/adt_progression_verification/evaluate",
        json={
            "current_adt_context": "orchiectomy",
            "orchiectomy_status": 1,
            "castrate_testosterone_status": "confirmed_castrate",
            "testosterone_value": 12,
            "progression_pattern": "radiographic",
            "conventional_imaging_status": "M1",
            "psadt_months": 6,
        },
    )
    assert mcrpc.status_code == 200
    mcrpc_result = mcrpc.get_json()["result"]
    assert mcrpc_result["decision_quality"]["state_classification"] == "Candidato confirmado a enfermedad resistente a la castración con metástasis"
    assert "con metástasis" in mcrpc_result["eligible_treatments"][0]["name"].lower()


def test_localized_initial_uses_pirads_and_histology_variant_to_restrict_active_surveillance(app_client):
    client, _ = app_client

    pirads_high = client.post(
        "/api/modules/localized_initial/evaluate",
        json={
            "age": 63,
            "life_expectancy_years": 15,
            "psa": 5.9,
            "psad": 0.11,
            "clinical_tstage": "T1c",
            "gleason_primary": 3,
            "gleason_secondary": 3,
            "isup_grade": 1,
            "num_cores_positive": 2,
            "total_cores": 12,
            "max_core_involvement": 0.2,
            "percent_pattern_4": 0,
            "prior_mpmri": 1,
            "prior_mpmri_pirads_score": "5",
            "prior_mpmri_targeted_biopsy_status": "no",
            "confirmatory_biopsy_planned": 1,
            "nodal_status": "N0",
            "metastasis_site": "M0",
        },
    )
    assert pirads_high.status_code == 200
    pirads_result = pirads_high.get_json()["result"]
    names = {item["name"] for item in pirads_result["eligible_treatments"]}
    assert "Vigilancia activa" not in names
    assert any("pi-rads 4 o 5" in item.lower() for item in pirads_result["not_recommended"])

    ductal = client.post(
        "/api/modules/localized_initial/evaluate",
        json={
            "age": 65,
            "life_expectancy_years": 14,
            "psa": 7.3,
            "psad": 0.14,
            "clinical_tstage": "T2a",
            "gleason_primary": 3,
            "gleason_secondary": 4,
            "isup_grade": 2,
            "num_cores_positive": 3,
            "total_cores": 12,
            "max_core_involvement": 0.25,
            "percent_pattern_4": 10,
            "prior_mpmri": 1,
            "prior_mpmri_pirads_score": "3",
            "prior_mpmri_targeted_biopsy_status": "si",
            "confirmatory_biopsy_planned": 1,
            "adverse_histology_variant_type": "ductal_predominant",
            "nodal_status": "N0",
            "metastasis_site": "M0",
        },
    )
    assert ductal.status_code == 200
    ductal_result = ductal.get_json()["result"]
    assert "Vigilancia activa" not in {item["name"] for item in ductal_result["eligible_treatments"]}
    assert any("variante histológica adversa específica" in item.lower() for item in ductal_result["not_recommended"])

    small_cell = client.post(
        "/api/modules/localized_initial/evaluate",
        json={
            "age": 64,
            "life_expectancy_years": 16,
            "psa": 6.8,
            "psad": 0.12,
            "clinical_tstage": "T2a",
            "gleason_primary": 3,
            "gleason_secondary": 4,
            "isup_grade": 2,
            "num_cores_positive": 3,
            "total_cores": 12,
            "max_core_involvement": 0.3,
            "percent_pattern_4": 15,
            "prior_mpmri": 1,
            "prior_mpmri_pirads_score": "4",
            "prior_mpmri_targeted_biopsy_status": "si",
            "confirmatory_biopsy_planned": 1,
            "adverse_histology_variant_type": "small_cell_neuroendocrine",
            "nodal_status": "N0",
            "metastasis_site": "M0",
        },
    )
    assert small_cell.status_code == 200
    small_cell_result = small_cell.get_json()["result"]
    assert small_cell_result["decision_quality"]["unsupported_or_escalate"] is True


def test_diagnostic_and_post_negative_biopsy_modules_surface_monitoring_and_sources(app_client):
    client, _ = app_client

    diagnostic_response = client.post(
        "/api/modules/diagnostic_workup/evaluate",
        json={
            "psa": 9.2,
            "psad": 0.18,
            "dre_suspicious": 1,
            "pirads_score": 4,
            "family_history_positive": 1,
            "germline_risk_mutation": 0,
            "prior_negative_biopsy": 0,
        },
    )
    assert diagnostic_response.status_code == 200
    diagnostic_result = diagnostic_response.get_json()["result"]
    assert diagnostic_result["nccn_primary"]["risk_group"] == "DIAGNOSTIC_HIGH"
    assert diagnostic_result["monitoring_plan"]["cadence"]
    assert diagnostic_result["state_transition_targets"]
    assert diagnostic_result["source_citations"]

    sources_response = client.get("/api/modules/diagnostic_workup/sources")
    assert sources_response.status_code == 200
    sources = sources_response.get_json()["sources"]
    assert any(source["guideline_or_trial"] == "NCCN 5.2026" for source in sources)

    benign_response = client.post(
        "/api/modules/post_negative_biopsy_followup/evaluate",
        json={
            "psa": 4.2,
            "psad": 0.09,
            "pirads_score": 0,
            "dre_suspicious": 0,
            "years_since_negative_biopsy": 2,
            "family_history_positive": 0,
        },
    )
    assert benign_response.status_code == 200
    benign_result = benign_response.get_json()["result"]
    assert benign_result["nccn_primary"]["risk_group"] == "BENIGN_BIOPSY_LOW_INTENSITY"
    assert "12 a 24 meses" in benign_result["monitoring_plan"]["cadence"]
    assert any("Palmstedt 2019" in source["guideline_or_trial"] for source in benign_result["source_citations"])


def test_recurrence_module_exposes_bcr2_pathway(app_client):
    client, _ = app_client
    payload = {
        "prior_prostatectomy": 1,
        "prior_radiation": 0,
        "bcr2": 1,
        "psa_current": 0.7,
        "psa_nadir": 0.02,
        "psadt_months": 7,
        "eligible_pelvic_therapy": 0,
        "prior_secondary_rt": 1,
        "imaging_negative": 1,
    }

    response = client.post("/api/modules/recurrence_bcr/evaluate", json=payload)
    assert response.status_code == 200
    result = response.get_json()["result"]
    assert "segunda recurrencia bioquímica" in result["nccn_primary"]["label"].lower()
    treatment_names = {item["name"] for item in result["eligible_treatments"]}
    # EMBARK-like enzalutamida sigue siendo la opción preferida (categoría 1).
    assert "Enzalutamida con o sin leuprorelina" in treatment_names
    # PRESTO/AFT-19 (Aggarwal JCO 2023;41:3253): BCR2 N0M0 post-RP+SRT con
    # PSADT ≤9 m y PSA ≥0.5 ng/mL soporta apalutamida ± abiraterona como
    # intensificación experimental (categoría 2B). La auditoría de pacientes
    # insignia (2026-04-21) exige surface para cerrar la brecha clínica
    # silenciosa identificada.
    assert any(
        "apalutamida" in name.lower() and "presto" in name.lower()
        for name in treatment_names
    ), f"Se esperaba opción PRESTO apalutamida experimental; obtuvo {sorted(treatment_names)}"
    # Conservamos la advertencia contra uso rutinario (PRESTO no es estándar NCCN v5.2026).
    assert any("apalutam" in item.lower() for item in result["not_recommended"])


def test_recurrence_bcr_structured_psma_keeps_salvage_window_visible(app_client):
    client, _ = app_client
    response = client.post(
        "/api/modules/recurrence_bcr/evaluate",
        json={
            "prior_prostatectomy": 1,
            "prior_radiation": 0,
            "bcr2": 0,
            "psa_current": 0.55,
            "psa_nadir": 0.02,
            "psadt_months": 8,
            "eligible_pelvic_therapy": 1,
            "prior_secondary_rt": 0,
            "imaging_negative": 0,
            "psma_pet_done": 1,
            "psma_radioligand": "68Ga-PSMA-11",
            "psma_index_lesion_site": "ganglio pélvico",
            "psma_index_lesion_suvmax": 14.2,
            "psma_uptake_pattern": "focal",
            "psma_rads_score": "4",
            "psma_total_lesions": 1,
            "psma_lesion_locations": ["pelvis"],
            "conventional_stage_before_psma": "M0",
            "psma_stage_after_psma": "M0",
            "psma_management_changed": "Sí",
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    treatment_names = {item["name"] for item in result["eligible_treatments"]}
    assert any("radioterapia de rescate" in name.lower() for name in treatment_names)
    assert any("psma" in name.lower() and "rescate" in name.lower() for name in treatment_names)
    assert any("ventana curativa" in item.lower() for item in result["durations_and_conditions"])


def test_recurrence_bcr_builds_comparative_salvage_bundle_with_preferred_option(app_client):
    client, _ = app_client
    response = client.post(
        "/api/modules/recurrence_bcr/evaluate",
        json={
            "prior_prostatectomy": 1,
            "psa_current": 0.42,
            "psadt_months": 8,
            "eligible_pelvic_therapy": 1,
            "imaging_negative": 1,
        },
    )
    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["preferred_frontline_regimen"]["family_code"] == "salvage_rt_family"
    assert result["preferred_frontline_regimen"]["regimen_code"] == "SALVAGE_RT_ALONE"
    assert result["eligible_treatments"][0]["regimen_code"] == "SALVAGE_RT_ALONE"
    assert "Radioterapia externa" in result["eligible_treatments"][0]["route"]
    assert result["comparative_eligibility_matrix"]["salvage_rt_family"]["variant_ranking"]["preferred_regimen_code"] == "SALVAGE_RT_ALONE"


def test_recurrence_bcr_high_risk_post_rp_prefers_srt_plus_adt_over_rt_alone(app_client):
    client, _ = app_client
    response = client.post(
        "/api/modules/recurrence_bcr/evaluate",
        json={
            "prior_prostatectomy": 1,
            "psa_current": 1.1,
            "psa": 1.1,
            "psadt_months": 3.5,
            "time_to_recurrence_months": 3,
            "salvage_local_feasible": 1,
            "eligible_pelvic_therapy": 1,
            "conventional_imaging_status": "M0",
            "psma_pet_done": 0,
            "pathologic_stage": "pT3b",
            "seminal_vesicle_invasion": 1,
            "surgical_margin": 1,
        },
    )
    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["preferred_frontline_regimen"]["family_code"] == "salvage_rt_family"
    assert result["preferred_frontline_regimen"]["regimen_code"] != "SALVAGE_RT_ALONE"
    assert result["preferred_frontline_regimen"]["regimen_code"] in {
        "SALVAGE_RT_SHORT_HORMONE",
        "SALVAGE_RT_PELVIC_SHORT_HORMONE",
        "SALVAGE_RT_LONG_HORMONE",
    }
    assert result["high_risk_post_rp_salvage"] is True
    assert result["psma_restaging_role"] == "urgent_companion"
    assert "SPPORT" in {item["trial"] for item in result["trial_matches"]}
    assert any(
        "PSMA PET/CT urgente" in item
        for item in result["companion_actions_required_for_preferred_regimen"]
    )


def test_post_rt_requires_phoenix_or_local_confirmation_before_salvage(app_client):
    client, _ = app_client
    response = client.post(
        "/api/modules/post_radiotherapy_or_local_salvage/evaluate",
        json={
            "prior_prostatectomy": 0,
            "prior_radiation": 1,
            "prior_rt_modality": "EBRT",
            "prior_rt_dose": 78,
            "prior_rt_fields": "Próstata",
            "psa_current": 1.4,
            "psa_nadir": 0.4,
            "phoenix_delta": 1.0,
            "psma_pet_done": 1,
            "psma_radioligand": "68Ga-PSMA-11",
            "psma_rads_score": "4",
            "psma_uptake_pattern": "focal",
            "psma_stage_after_psma": "M0",
            "mpmri_done": 1,
            "mpmri_localized_recurrence": 0,
            "biopsy_proven_local_recurrence": 0,
        },
    )
    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["post_rt_failure_definition"]["phoenix_status"] == "not_met"
    assert result["post_rt_transition_bundle"]["transition_status"] == "pending_confirmation"
    assert result["eligible_treatments"][0]["regimen_code"] == "POST_RT_CONFIRMATION"
    assert result["preferred_frontline_regimen"]["regimen_code"] == "POST_RT_CONFIRMATION"


def test_post_rt_local_salvage_candidate_builds_ranked_modality_matrix(app_client):
    client, _ = app_client
    response = client.post(
        "/api/modules/post_radiotherapy_or_local_salvage/evaluate",
        json={
            "prior_prostatectomy": 0,
            "prior_radiation": 1,
            "prior_rt_modality": "EBRT",
            "prior_rt_dose": 78,
            "prior_rt_fields": "Próstata y vesículas seminales",
            "psa_current": 2.3,
            "psa_nadir": 0.1,
            "phoenix_delta": 2.2,
            "biopsy_proven_local_recurrence": 1,
            "biopsy_date": "2026-03-10",
            "biopsy_grade_group": 3,
            "mpmri_done": 1,
            "mpmri_date": "2026-03-05",
            "mpmri_localized_recurrence": 1,
            "local_recurrence_site": "focal peripheral gland",
            "urinary_burden": "Moderada",
            "incontinence_burden": "Leve",
            "urethral_stricture_history": 0,
            "bowel_burden": "Leve",
            "rectal_toxicity_grade": 1,
            "prostate_volume": 30,
            "anesthesia_surgical_fitness": "Apto",
            "salvage_expertise_available": 1,
            "psma_pet_done": 1,
            "psma_radioligand": "68Ga-PSMA-11",
            "psma_rads_score": "4",
            "psma_uptake_pattern": "focal",
            "psma_stage_after_psma": "M0",
        },
    )
    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["post_rt_transition_bundle"]["transition_status"] == "local_salvage_candidate"
    assert result["post_rt_salvage_bundle"]["dominant_local_option"]["regimen_code"] in {
        "SALVAGE_PROSTATECTOMY",
        "SALVAGE_CRYOTHERAPY",
        "SALVAGE_HIFU",
        "SALVAGE_BRACHYTHERAPY",
    }
    assert result["post_rt_local_salvage_ranking"][0]["eligibility_status"] in {"preferred", "preferente"}
    assert result["sequence_transition_bundle"]["trigger_status"] == "redirect_local"


def test_post_rt_oligometastatic_pattern_surfaces_mdt_candidate(app_client):
    client, _ = app_client
    response = client.post(
        "/api/modules/post_radiotherapy_or_local_salvage/evaluate",
        json={
            "prior_prostatectomy": 0,
            "prior_radiation": 1,
            "prior_rt_modality": "EBRT",
            "prior_rt_dose": 78,
            "prior_rt_fields": "Próstata",
            "psa_current": 2.6,
            "psa_nadir": 0.2,
            "phoenix_delta": 2.4,
            "biopsy_proven_local_recurrence": 1,
            "biopsy_date": "2026-03-04",
            "biopsy_grade_group": 3,
            "mpmri_done": 1,
            "mpmri_date": "2026-03-01",
            "mpmri_localized_recurrence": 1,
            "local_recurrence_site": "left base",
            "urinary_burden": "Leve",
            "incontinence_burden": "Leve",
            "urethral_stricture_history": 0,
            "bowel_burden": "Leve",
            "rectal_toxicity_grade": 1,
            "prostate_volume": 28,
            "anesthesia_surgical_fitness": "Apto",
            "salvage_expertise_available": 1,
            "psma_pet_done": 1,
            "psma_radioligand": "18F-DCFPyL",
            "psma_rads_score": "5",
            "psma_uptake_pattern": "oligometastatic",
            "psma_stage_after_psma": "M1a",
            "psma_total_lesions": 2,
        },
    )
    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["post_rt_transition_bundle"]["transition_status"] == "mdt_candidate"
    assert result["post_rt_local_salvage_ranking"][0]["regimen_code"] == "PSMA_GUIDED_MDT"
    assert result["preferred_frontline_regimen"]["regimen_code"] == "PSMA_GUIDED_MDT"


def test_post_rt_disseminated_psma_redirects_systemic_and_hides_local_preference(app_client):
    client, _ = app_client
    response = client.post(
        "/api/modules/post_radiotherapy_or_local_salvage/evaluate",
        json={
            "prior_prostatectomy": 0,
            "prior_radiation": 1,
            "prior_rt_modality": "EBRT",
            "prior_rt_dose": 78,
            "prior_rt_fields": "Próstata",
            "psa_current": 2.4,
            "psa_nadir": 0.1,
            "phoenix_delta": 2.3,
            "biopsy_proven_local_recurrence": 1,
            "biopsy_date": "2026-03-01",
            "biopsy_grade_group": 4,
            "mpmri_done": 1,
            "mpmri_date": "2026-03-01",
            "mpmri_localized_recurrence": 1,
            "local_recurrence_site": "multifocal gland",
            "urinary_burden": "Moderada",
            "incontinence_burden": "Leve",
            "urethral_stricture_history": 0,
            "bowel_burden": "Leve",
            "rectal_toxicity_grade": 1,
            "prostate_volume": 30,
            "anesthesia_surgical_fitness": "Apto",
            "salvage_expertise_available": 1,
            "psma_pet_done": 1,
            "psma_radioligand": "18F-DCFPyL",
            "psma_rads_score": "5",
            "psma_uptake_pattern": "diseminado",
            "psma_stage_after_psma": "M1b",
        },
    )
    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["post_rt_transition_bundle"]["transition_status"] == "redirect_systemic"
    assert result["post_rt_local_salvage_ranking"][0]["regimen_code"] == "SYSTEMIC_RESTAGING"
    assert result["sequence_transition_bundle"]["trigger_status"] == "redirect_systemic"


def test_survivorship_module_schema_uses_exposure_aware_visibility_blocks(app_client):
    client, _ = app_client
    schema = client.get("/api/modules/survivorship_and_toxicity_followup/schema").get_json()["schema"]
    fields = {field["name"]: field for field in schema["fields"]}

    assert fields["neuropathy_grade"]["conditional_visibility"] == {
        "__any__": [{"prior_docetaxel": ["1"]}, {"prior_cabazitaxel": ["1"]}]
    }
    assert fields["fatigue_score"]["conditional_visibility"] == {
        "__any__": [{"prior_docetaxel": ["1"]}, {"prior_cabazitaxel": ["1"]}, {"prior_adt": ["1"]}]
    }
    assert fields["dental_clearance_done"]["conditional_visibility"] == {
        "__any__": [{"on_denosumab": ["1"]}, {"on_zoledronate": ["1"]}]
    }


def test_survivorship_module_prioritizes_post_rp_late_effects_without_reopening_oncology(app_client):
    client, _ = app_client
    response = client.post(
        "/api/modules/survivorship_and_toxicity_followup/evaluate",
        json={
            "oncologic_state_context": "post_prostatectomy",
            "effective_management_track": "survivorship_followup",
            "prior_prostatectomy": 1,
            "prior_radiation": 0,
            "prior_adt": 0,
            "prior_docetaxel": 0,
            "prior_cabazitaxel": 0,
            "on_denosumab": 0,
            "on_zoledronate": 0,
            "ipss_score": 22,
            "pad_count": 4,
            "continence_status": "Severa",
            "leakage_bother": 7,
            "iief5_score": 6,
            "nerve_sparing": "No",
            "pelvic_floor_pt_started": 0,
            "depression_score": 3,
            "anxiety_score": 2,
            "sexual_bother": 7,
            "body_image_distress": 5,
            "return_to_work_status": "Ajustado",
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    bundle = result["survivorship_transition_bundle"]
    assert bundle["survivorship_track"] == "late_effect_intervention"
    assert bundle["trigger_status"] == "refer_specialist"
    assert bundle["dominant_late_effect_domain"] == "urinary_recovery"
    assert "Urología funcional" in bundle["recommended_referrals"]
    assert result["eligible_treatments"][0]["is_preferred"] is True


def test_survivorship_module_routes_systemic_recovery_into_toxicity_recovery_track(app_client):
    client, _ = app_client
    response = client.post(
        "/api/modules/survivorship_and_toxicity_followup/evaluate",
        json={
            "oncologic_state_context": "m1_crpc",
            "effective_management_track": "survivorship_followup",
            "prior_prostatectomy": 0,
            "prior_radiation": 0,
            "prior_adt": 1,
            "adt_duration_months": 18,
            "prior_docetaxel": 1,
            "prior_cabazitaxel": 0,
            "on_denosumab": 0,
            "on_zoledronate": 0,
            "neuropathy_grade": 2,
            "fatigue_score": 8,
            "hemoglobin": 9.4,
            "weight_loss_pct": 11,
            "functional_decline": 1,
            "depression_score": 2,
            "anxiety_score": 2,
            "sexual_bother": 2,
            "body_image_distress": 2,
            "return_to_work_status": "Ajustado",
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    bundle = result["survivorship_transition_bundle"]
    assert bundle["survivorship_track"] == "toxicity_recovery"
    assert bundle["trigger_status"] == "refer_rehabilitation"
    assert bundle["dominant_late_effect_domain"] == "systemic_recovery"
    assert "Rehabilitación oncológica" in bundle["recommended_referrals"]


def test_survivorship_module_surfaces_adt_bone_and_cardiometabolic_followup(app_client):
    client, _ = app_client
    response = client.post(
        "/api/modules/survivorship_and_toxicity_followup/evaluate",
        json={
            "oncologic_state_context": "m0_crpc",
            "effective_management_track": "survivorship_followup",
            "age": 72,
            "prior_prostatectomy": 0,
            "prior_radiation": 0,
            "prior_adt": 1,
            "adt_duration_months": 30,
            "prior_docetaxel": 0,
            "prior_cabazitaxel": 0,
            "on_denosumab": 0,
            "on_zoledronate": 0,
            "systolic_bp": 162,
            "diastolic_bp": 92,
            "hba1c": 6.3,
            "total_cholesterol": 245,
            "hdl_cholesterol": 35,
            "triglycerides": 210,
            "waist_circumference_cm": 108,
            "dxa_t_score_lumbar": -2.6,
            "dxa_t_score_hip": -2.2,
            "vitamin_d_level": 18,
            "calcium_level": 8.8,
            "fall_risk": 1,
            "cognitive_risk": 1,
            "depression_score": 3,
            "anxiety_score": 2,
            "sexual_bother": 4,
            "body_image_distress": 2,
            "return_to_work_status": "Jubilado",
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    bundle = result["survivorship_transition_bundle"]
    assert bundle["survivorship_track"] == "late_effect_intervention"
    assert bundle["cardiometabolic_status"] == "high_risk"
    assert bundle["bone_health_status"] in {"osteoporosis", "bma_safety_issue"}
    assert "Cardio-oncología" in bundle["recommended_referrals"]
    assert "Clínica de salud ósea / endocrinología" in bundle["recommended_referrals"]


def test_psma_structured_fields_are_conditional_in_module_schemas(app_client):
    client, _ = app_client

    recurrence_schema = client.get("/api/modules/recurrence_bcr/schema").get_json()["schema"]
    recurrence_fields = {field["name"]: field for field in recurrence_schema["fields"]}
    assert recurrence_fields["psma_radioligand"]["conditional_visibility"] == {"psma_pet_done": ["1"]}
    assert recurrence_fields["psma_rads_score"]["conditional_visibility"] == {"psma_pet_done": ["1"]}

    post_rt_schema = client.get("/api/modules/post_radiotherapy_or_local_salvage/schema").get_json()["schema"]
    post_rt_fields = {field["name"]: field for field in post_rt_schema["fields"]}
    assert post_rt_fields["psma_radioligand"]["conditional_visibility"] == {"psma_pet_done": ["1"]}
    assert post_rt_fields["psma_rads_score"]["conditional_visibility"] == {"psma_pet_done": ["1"]}

    m1_schema = client.get("/api/modules/m1_crpc/schema").get_json()["schema"]
    m1_fields = {field["name"]: field for field in m1_schema["fields"]}
    assert m1_fields["psma_radioligand"]["conditional_visibility"] == {"psma_pet_done": ["1"]}
    assert m1_fields["psma_rads_score"]["conditional_visibility"] == {"psma_pet_done": ["1"]}


def test_boolean_option_label_resolver_supports_explicit_contextual_and_fallback_labels():
    assert resolve_option_label("psma_positive", "0", ["0", "1"]) == "No"
    assert resolve_option_label("cv_risk_documented", "1", ["0", "1"]) == "Documentado"
    assert resolve_option_label("docetaxel_fit", "1", ["1", "0"]) == "Sí"

    schema = humanize_schema(
        {
            "module": "m1_crpc",
            "title": "Test",
            "description": "",
            "fields": [
                {
                    "name": "docetaxel_fit",
                    "label": "Apto para docetaxel",
                    "field_type": "select",
                    "options": ["1", "0"],
                    "default": "1",
                }
            ],
        }
    )
    display_labels = [item["label"] for item in schema["fields"][0]["display_options"]]
    assert display_labels == ["Sí", "No"]


def test_all_boolean_schema_options_have_human_friendly_labels():
    registry = ModuleRegistry()
    module_ids = [item["module"] for item in registry.list_modules()]

    for module_id in module_ids:
        schema = humanize_schema(registry.get_module_schema(module_id))
        for field in schema["fields"]:
            options = [str(option) for option in field.get("options", [])]
            if field.get("field_type") == "select" and options in (["0", "1"], ["1", "0"]):
                labels = [str(item["label"]) for item in field.get("display_options", [])]
                assert "0" not in labels, f"{module_id}:{field['name']} rendered raw 0"
                assert "1" not in labels, f"{module_id}:{field['name']} rendered raw 1"


def test_capra_s_is_hidden_in_preop_scores_and_available_in_postop_module(app_client):
    preop_scores = calculate_all_scores(
        {
            "age": 65,
            "psa": 6.2,
            "clinical_tstage": "T1c",
            "gleason_primary": 3,
            "gleason_secondary": 3,
            "isup_grade": 1,
            "num_cores_positive": 2,
            "total_cores": 12,
            "pct_cores_positive": 2 / 12,
        }
    )
    assert "capra_s" not in preop_scores

    client, _ = app_client
    postop_response = client.post(
        "/api/modules/post_prostatectomy/evaluate",
        json={
            "psa": 12,
            "psa_postop": 0.03,
            "gleason_primary": 4,
            "gleason_secondary": 3,
            "surgical_margin": 1,
            "ece_status": 1,
            "svi_status": 0,
            "lni_status": 0,
            "pathologic_stage": "pT3a",
        },
    )
    assert postop_response.status_code == 200
    result = postop_response.get_json()["result"]
    assert result["state"] == "post_prostatectomy"
    assert result["report_sections"]["capra_s"]["score"] >= 0
    names = {item["name"] for item in result["eligible_treatments"]}
    assert any("vigilancia posoperatoria" in name.lower() or "planificación temprana de rescate" in name.lower() for name in names)


def test_post_prostatectomy_surfaces_surveillance_vs_salvage_in_comparative_bundle(app_client):
    client, _ = app_client
    postop_response = client.post(
        "/api/modules/post_prostatectomy/evaluate",
        json={
            "psa": 8.7,
            "psa_postop": 0.18,
            "surgical_margin": 1,
            "ece_status": 1,
            "svi_status": 0,
            "lni_status": 0,
            "pathologic_stage": "pT3a",
            "decipher_risk": "Alto",
            "time_to_recurrence_months": 12,
        },
    )
    assert postop_response.status_code == 200
    result = postop_response.get_json()["result"]
    assert result["preferred_frontline_regimen"]["family_code"] in {"salvage_rt_family", "surveillance_family"}
    assert "comparative_eligibility_matrix" in result
    assert "surveillance_family" in result["comparative_eligibility_matrix"]
    assert "salvage_rt_family" in result["comparative_eligibility_matrix"]
    assert result["sequence_transition_bundle"]["active_family"] == result["preferred_frontline_regimen"]["family_code"]
    assert result["active_regimen_monitoring_package"]["family_code"] == result["preferred_frontline_regimen"]["family_code"]


def test_post_prostatectomy_module_promotes_decisive_persistent_psa_to_recurrence_bcr(app_client):
    client, _ = app_client
    postop_response = client.post(
        "/api/modules/post_prostatectomy/evaluate",
        json={
            "psa": 0.31,
            "psa_postop": 0.31,
            "surgical_margin": 0,
            "ece_status": 0,
            "svi_status": 0,
            "lni_status": 0,
            "pathologic_stage": "pT2",
            "psadt_months": 8.0,
            "salvage_local_feasible": 1,
        },
    )
    assert postop_response.status_code == 200
    result = postop_response.get_json()["result"]

    assert result["state"] == "recurrence_bcr"
    assert result["preferred_frontline_regimen"]["family_code"] == "salvage_rt_family"
    assert result["sequence_transition_bundle"]["trigger_status"] in {"redirect_local", "confirm"}


def test_localized_initial_surfaces_preferred_family_and_metadata(app_client):
    client, _ = app_client
    response = client.post(
        "/api/modules/localized_initial/evaluate",
        json={
            "age": 65,
            "psa": 6.1,
            "clinical_tstage": "T1c",
            "isup_grade": 1,
            "num_cores_positive": 2,
            "total_cores": 12,
            "pct_cores_positive": 2 / 12,
            "life_expectancy_years": 14,
            "prior_mpmri": 1,
            "prior_mpmri_pirads_score": 3,
            "confirmatory_biopsy_planned": 1,
            "psad": 0.12,
            "max_core_involvement": 0.2,
        },
    )
    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["preferred_frontline_regimen"]["family_code"] == "active_surveillance_family"
    assert result["eligible_treatments"][0]["regimen_code"] == "ACTIVE_SURVEILLANCE"
    assert "Seguimiento estructurado" in result["eligible_treatments"][0]["route"]
    assert result["comparative_eligibility_matrix"]["active_surveillance_family"]["variant_ranking"]["preferred_regimen_code"] == "ACTIVE_SURVEILLANCE"


def test_localized_initial_modality_bundle_restricts_active_surveillance_when_pirads5_lacks_targeted_confirmation(app_client):
    client, _ = app_client
    response = client.post(
        "/api/modules/localized_initial/evaluate",
        json={
            "age": 63,
            "psa": 6.4,
            "clinical_tstage": "T1c",
            "gleason_primary": 3,
            "gleason_secondary": 3,
            "isup_grade": 1,
            "num_cores_positive": 2,
            "total_cores": 12,
            "life_expectancy_years": 15,
            "clinical_risk_group": "LOW",
            "prior_mpmri": 1,
            "prior_mpmri_pirads_score": 5,
            "prior_mpmri_targeted_biopsy_status": "no",
            "psad": 0.11,
            "prostate_volume_ml": 42,
            "radiotherapy_feasibility": "feasible",
            "anesthesia_surgical_fitness": "Fit",
            "frailty_status": "Fit",
            "g8_score": 16,
        },
    )
    assert response.status_code == 200
    result = response.get_json()["result"]
    modality_bundle = result["localized_modality_fitness_bundle"]
    assert modality_bundle["active_surveillance_status"] == "provisional"
    assert result["preferred_frontline_regimen"]["family_code"] != "active_surveillance_family"
    assert "pi-rads" in " ".join(modality_bundle["why_not_active_surveillance"]).lower()


def test_localized_initial_prefers_radiotherapy_when_surgery_fitness_is_poor(app_client):
    client, _ = app_client
    response = client.post(
        "/api/modules/localized_initial/evaluate",
        json={
            "age": 74,
            "psa": 12.8,
            "clinical_tstage": "T2b",
            "gleason_primary": 3,
            "gleason_secondary": 4,
            "isup_grade": 2,
            "num_cores_positive": 4,
            "total_cores": 12,
            "life_expectancy_years": 11,
            "clinical_risk_group": "FAVORABLE INTERMEDIATE",
            "prior_mpmri": 1,
            "prior_mpmri_pirads_score": 3,
            "nodal_status": "N0",
            "metastasis_site": "M0",
            "prostate_volume_ml": 48,
            "ecog_score": 3,
            "charlson_score": 5,
            "anesthesia_surgical_fitness": "No apto",
            "radiotherapy_feasibility": "feasible",
            "frailty_status": "Frail",
            "g8_score": 12,
            "ipss_score": 10,
            "iief5_score": 17,
            "patient_priority_profile": "preserve_sexual_function,avoid_surgery",
        },
    )
    assert response.status_code == 200
    result = response.get_json()["result"]
    modality_bundle = result["localized_modality_fitness_bundle"]
    assert result["radical_prostatectomy_candidacy_profile"]["candidate_status"] == "not_candidate"
    assert modality_bundle["surgery_status"] == "blocked"
    assert modality_bundle["dominant_modality"] == "radiotherapy"
    assert result["preferred_frontline_regimen"]["family_code"] == "radiotherapy_family"


def test_localized_initial_stays_provisional_when_local_tradeoff_is_real_but_patient_priorities_are_missing(app_client):
    client, _ = app_client
    response = client.post(
        "/api/modules/localized_initial/evaluate",
        json={
            "age": 66,
            "psa": 9.7,
            "clinical_tstage": "T2a",
            "gleason_primary": 3,
            "gleason_secondary": 4,
            "isup_grade": 2,
            "num_cores_positive": 3,
            "total_cores": 12,
            "life_expectancy_years": 14,
            "clinical_risk_group": "FAVORABLE INTERMEDIATE",
            "prior_mpmri": 1,
            "prior_mpmri_pirads_score": 3,
            "nodal_status": "N0",
            "metastasis_site": "M0",
            "prostate_volume_ml": 38,
            "ecog_score": 1,
            "charlson_score": 1,
            "anesthesia_surgical_fitness": "Fit",
            "radiotherapy_feasibility": "feasible",
            "frailty_status": "Fit",
            "g8_score": 15,
            "ipss_score": 6,
            "iief5_score": 20,
        },
    )
    assert response.status_code == 200
    result = response.get_json()["result"]
    modality_bundle = result["localized_modality_fitness_bundle"]
    assert modality_bundle["shared_decision_required"] == "yes"
    assert modality_bundle["modality_fitness_status"] == "provisional"
    assert result["patient_priority_profile"]["available"] is False


def test_localized_initial_keeps_rp_candidacy_open_with_objective_fitness_even_if_pros_are_missing(app_client):
    client, _ = app_client
    response = client.post(
        "/api/modules/localized_initial/evaluate",
        json={
            "age": 64,
            "psa": 8.9,
            "clinical_tstage": "T2a",
            "gleason_primary": 3,
            "gleason_secondary": 4,
            "isup_grade": 2,
            "num_cores_positive": 3,
            "total_cores": 12,
            "clinical_risk_group": "FAVORABLE INTERMEDIATE",
            "prior_mpmri": 1,
            "prior_mpmri_pirads_score": 3,
            "nodal_status": "N0",
            "metastasis_site": "M0",
            "ecog_score": 1,
            "charlson_score": 1,
            "frailty_status": "Fit",
            "g8_score": 15,
            "anesthesia_surgical_fitness": "Fit",
            "radiotherapy_feasibility": "feasible",
        },
    )
    assert response.status_code == 200
    result = response.get_json()["result"]
    rp_profile = result["radical_prostatectomy_candidacy_profile"]
    assert rp_profile["candidate_status"] == "candidate"
    assert "iief5_score" not in rp_profile["missing_candidate_fields"]
    assert "epic26_bowel_domain" not in rp_profile["missing_candidate_fields"]


def test_m0_crpc_prefers_observation_or_darolutamide_by_risk_and_seizure_profile(app_client):
    client, _ = app_client

    observe_response = client.post(
        "/api/modules/m0_crpc/evaluate",
        json={"psadt_months": 14, "castration_resistant": 1, "castrate_testosterone_confirmed": 1, "comorbidity_seizure": 0, "imaging_negative": 1},
    )
    assert observe_response.status_code == 200
    observe_result = observe_response.get_json()["result"]
    assert observe_result["systemic_regimen_scope"] == "nmcrpc_arpi"
    assert observe_result["systemic_regimen_scope_contract"]["scope"] == "nmcrpc_arpi"
    assert "monitorización" in observe_result["eligible_treatments"][0]["name"].lower()
    assert "privación androgénica" in observe_result["eligible_treatments"][0]["name"].lower()
    assert any("tiempo de duplicación del antígeno prostático específico" in item.lower() for item in observe_result["not_recommended"])

    daro_response = client.post(
        "/api/modules/m0_crpc/evaluate",
        json={"psadt_months": 7, "castration_resistant": 1, "castrate_testosterone_confirmed": 1, "comorbidity_seizure": 1, "imaging_negative": 1},
    )
    assert daro_response.status_code == 200
    daro_result = daro_response.get_json()["result"]
    assert daro_result["systemic_regimen_scope"] == "nmcrpc_arpi"
    treatment_names = {item["name"] for item in daro_result["eligible_treatments"]}
    assert "Darolutamida + terapia de privación androgénica" in treatment_names
    daro_tx = next(item for item in daro_result["eligible_treatments"] if item["name"] == "Darolutamida + terapia de privación androgénica")
    assert daro_tx["regimen_code"] == "ADT_DAROLUTAMIDE"
    assert "Oral" in daro_tx["route"]


def test_m0_crpc_monitoring_package_and_trigger_surface_hold_for_active_arpi(app_client):
    client, _ = app_client
    response = client.post(
        "/api/modules/m0_crpc/evaluate",
        json={
            "psadt_months": 6,
            "castration_resistant": 1,
            "castrate_testosterone_confirmed": 1,
            "imaging_negative": 1,
            "comorbidity_seizure": 1,
            "current_treatment": "ADT_DAROLUTAMIDE",
            "systolic_bp": 190,
            "psa": 2.1,
            "testosterone": 18,
        },
    )
    assert response.status_code == 200
    result = response.get_json()["result"]

    assert result["preferred_frontline_regimen"]["regimen_code"] == "ADT_DAROLUTAMIDE"
    assert result["active_regimen_monitoring_package"]["family_code"] == "arpi_family"
    assert {"psa", "testosterone", "systolic_bp", "mini_cog_score"} <= set(
        result["active_regimen_monitoring_package"]["required_visit_fields"]
    )
    assert result["sequence_transition_bundle"]["trigger_status"] == "hold"
    assert "presion" in result["sequence_transition_bundle"]["trigger_evidence"][0].lower()


def test_recurrence_bcr_redirects_systemic_when_salvage_window_closes(app_client):
    client, _ = app_client
    response = client.post(
        "/api/modules/recurrence_bcr/evaluate",
        json={
            "prior_prostatectomy": 1,
            "psa_current": 1.2,
            "psadt_months": 5,
            "eligible_pelvic_therapy": 0,
            "salvage_local_feasible": 0,
            "psma_pet_done": 1,
            "psma_stage_after_psma": "M1b",
            "psma_uptake_pattern": "diseminado",
            "current_treatment": "SALVAGE_RT_ALONE",
        },
    )
    assert response.status_code == 200
    result = response.get_json()["result"]

    assert result["sequence_transition_bundle"]["trigger_status"] == "redirect_systemic"
    assert any("sistemica" in item.lower() or "disemin" in item.lower() for item in result["sequence_transition_bundle"]["trigger_evidence"])


def test_advanced_agenda_uses_active_monitoring_fields_for_therapy_review():
    from prostanet.domains.patient_tracking.followup_agenda import build_agenda_board

    patient = {
        "identity": {"diagnosis_date": date.today().isoformat()},
        "latest_assessment": {
            "state": "m1_crpc",
            "result_snapshot": {
                "preferred_frontline_regimen": {
                    "regimen_code": "ADT_ENZALUTAMIDE",
                    "family_code": "arpi_family",
                },
                "sequence_transition_bundle": {
                    "trigger_status": "continue",
                    "line_change_reason": "El backbone preferente sigue alineado con la trayectoria clínica.",
                },
                "active_regimen_monitoring_package": {
                    "family_code": "arpi_family",
                    "active_regimen_code": "ADT_ENZALUTAMIDE",
                    "active_regimen_label": "Enzalutamida + ADT",
                    "required_visit_fields": ["psa", "testosterone", "systolic_bp", "mini_cog_score"],
                    "monitoring_focus": "ARPI activa: respuesta bioquimica, seguridad neurologica y DDI.",
                    "recommended_cadence": "Cada 4-6 semanas al inicio.",
                },
            },
        },
        "follow_ups": [{"visit_date": date.today().isoformat()}],
        "imaging": [],
    }

    board = build_agenda_board(patient, "m1_crpc", "on_arpi", patient["latest_assessment"])
    therapy_item = next(item for item in board["items"] if item["agenda_key"].endswith(":therapy_review"))
    lab_item = next(item for item in board["items"] if item["agenda_key"].endswith(":labs"))

    assert therapy_item["capture_fields"] == ["psa", "testosterone", "systolic_bp", "mini_cog_score"]
    assert therapy_item["form_scope"]["focus"].startswith("ARPI activa")
    assert set(lab_item["capture_fields"]) == {"psa", "testosterone"}


def test_m0_crpc_does_not_default_to_darolutamide_without_neurologic_reason(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/m0_crpc/evaluate",
        json={
            "psadt_months": 6,
            "castration_resistant": 1,
            "castrate_testosterone_confirmed": 1,
            "comorbidity_seizure": 0,
            "frailty_status": "Fit",
            "cv_risk_documented": 0,
            "drug_interaction_reviewed": 1,
            "imaging_negative": 1,
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    top = result["eligible_treatments"][0]

    assert top["regimen_code"] == "ADT_ENZALUTAMIDE"
    assert "enzalutamida" in top["name"].lower()
    assert top["regimen_code"] != "ADT_DAROLUTAMIDE"


def test_arpi_eligible_schemas_surface_full_discrimination_bundle(app_client):
    client, _ = app_client
    required_fields = {
        "comorbidity_cardio",
        "current_medications",
        "dermatitis_history",
        "cognitive_risk",
        "fall_risk",
        "stroke_history",
        "edema_risk",
        "steroid_intolerance",
        "diabetes_uncontrolled",
    }
    arpi_modules = [
        "mcspc_high_volume_sync",
        "mcspc_high_volume_metachronous",
        "mcspc_low_volume_sync_oligo",
        "mcspc_oligo_metachronous",
        "m0_crpc",
        "m1_crpc",
        "recurrence_bcr",
    ]

    for module_id in arpi_modules:
        response = client.get(f"/api/modules/{module_id}/schema")
        assert response.status_code == 200
        schema = response.get_json()["schema"]
        field_names = {field["name"] for field in schema["fields"]}
        assert required_fields <= field_names, module_id


def test_m0_crpc_surfaces_arpi_benefit_and_provisional_capture_contract(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/m0_crpc/evaluate",
        json={
            "psadt_months": 6,
            "castration_resistant": 1,
            "castrate_testosterone_confirmed": 1,
            "imaging_negative": 1,
            "comorbidity_seizure": 1,
            "cv_risk_documented": 1,
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]

    assert "current_medications" in result["arpi_missing_inputs"]
    assert result["arpi_profile_completeness"] == "partial"
    assert result["arpi_preference_readiness"] == "needs_data"
    assert result["preferred_frontline_regimen"]["benefit_endpoint_used"] == "MFS"
    assert result["preferred_frontline_regimen"]["preference_confidence"] == "provisional"
    assert result["preferred_frontline_regimen"]["priority"] in {"preferred", "preferente"}
    assert result["preferred_frontline_regimen"]["eligibility_status"] in {"preferred", "preferente"}
    assert result["eligible_treatments"][0]["regimen_code"] == result["preferred_frontline_regimen"]["regimen_code"]
    assert result["eligible_treatments"][0]["priority"] in {"preferred", "preferente"}
    assert result["eligible_treatments"][0]["eligibility_status"] in {"preferred", "preferente"}


def test_advanced_modules_surface_sequence_specific_options(app_client):
    client, _ = app_client

    high_volume_response = client.post(
        "/api/modules/mcspc_high_volume/evaluate",
        json={
            "metastasis_count": 6,
            "metastasis_site": "Bone",
            "gleason_score": 9,
            "ecog_score": 1,
            "child_pugh_score": "A",
            "comorbidity_seizure": 0,
            "comorbidity_cardio": 0,
            "anc": 2500,
            "platelets": 220000,
            "hemoglobin": 13.5,
            "alt": 25,
            "ast": 22,
            "alp": 90,
            "bilirubin": 0.8,
            "cbc_date": (date.today() - timedelta(days=3)).isoformat(),
            "liver_panel_date": (date.today() - timedelta(days=3)).isoformat(),
            "peripheral_neuropathy_grade": 0,
            "drug_interaction_reviewed": 1,
            "performance_status_driver": "cancer_related",
            "frailty_status": "Fit",
        },
    )
    assert high_volume_response.status_code == 200
    high_volume_result = high_volume_response.get_json()["result"]
    high_volume_names = {item["name"] for item in high_volume_result["eligible_treatments"]}
    assert any("docetaxel" in name.lower() and "darolut" in name.lower() for name in high_volume_names) or any(
        "docetaxel" in name.lower() and "abirater" in name.lower() for name in high_volume_names
    )

    m1_response = client.post(
        "/api/modules/m1_crpc/evaluate",
        json={
            "hrr_status": "Positivo",
            "hrr_gene": "BRCA2",
            "biomarker_source": "Biopsia metastásica",
            "molecular_report_date": "2026-03-01",
            "msi_status": "inestable",
            "tmb_high": 1,
            "metastasis_site": "Bone",
            "prior_therapy": "Abiraterona, Docetaxel",
            "prior_docetaxel_cycles": 6,
            "castrate_testosterone_confirmed": 1,
            "mcrpc_line_context": "post_taxane",
            "pain_symptoms": "Sintomatico",
            "ecog_performance_status": 1,
            "psma_positive": 1,
            "psma_negative_dominant_lesions": 0,
        },
    )
    assert m1_response.status_code == 200
    m1_result = m1_response.get_json()["result"]
    m1_names = {item["name"] for item in m1_result["eligible_treatments"]}
    m1_by_code = {
        item.get("regimen_code"): item
        for item in m1_result["eligible_treatments"]
        if isinstance(item, dict)
    }
    assert "Olaparib" in m1_names
    assert "Pembrolizumab" in m1_names
    assert "Lutecio-177 dirigido al antígeno prostático específico de membrana" in m1_names
    assert "Cabazitaxel" in m1_names
    assert m1_result["systemic_regimen_scope"] == "mcrpc_sequence"
    assert m1_result["systemic_regimen_scope_contract"]["scope"] == "mcrpc_sequence"
    assert "Oral" in m1_by_code["OLAPARIB"]["route"]
    assert "300 mg cada 12 horas" in m1_by_code["OLAPARIB"]["dose"]
    assert "Intravenosa" in m1_by_code["CABAZITAXEL"]["route"]
    assert "Cada 21 días" in m1_by_code["CABAZITAXEL"]["schedule"]
    assert any("recombinación homóloga" in flag["label"].lower() or "hrr" in flag["label"].lower() for flag in m1_result["benchmarking_flags"])


def test_high_volume_sync_and_metachronous_surface_darolutamide_and_docetaxel_fitness(app_client):
    client, _ = app_client

    sync_response = client.post(
        "/api/modules/mcspc_high_volume_sync/evaluate",
        json={
            "metastasis_count": 7,
            "metastasis_site": "Bone",
            "ecog_score": 1,
            "peripheral_neuropathy_grade": 0,
            "frailty_status": "Fit",
            "child_pugh_score": "A",
            "comorbidity_cardio": 0,
            "cv_risk_documented": 0,
            "drug_interaction_reviewed": 1,
            **_recent_docetaxel_labs(),
        },
    )
    assert sync_response.status_code == 200
    sync_result = sync_response.get_json()["result"]
    assert sync_result["state"] == "mcspc_high_volume_sync"
    assert sync_result["fit_for_docetaxel"] is True
    assert sync_result["triplet_decision"]["status"] == "recommended"
    assert any(
        str(item.get("trial", item.get("study_name", ""))).upper() == "ARASENS"
        and item.get("match") in (True, "Sí", "Si", "si")
        for item in sync_result["trial_matches"]
    )
    assert any(
        str(item.get("trial", item.get("study_name", ""))).upper() == "PEACE-1"
        and item.get("match") in (True, "Sí", "Si", "si")
        for item in sync_result["trial_matches"]
    )

    metach_response = client.post(
        "/api/modules/mcspc_high_volume_metachronous/evaluate",
        json={
            "metastasis_count": 6,
            "metastasis_site": "Bone",
            "ecog_score": 1,
            "peripheral_neuropathy_grade": 2,
            "frailty_status": "Fit",
            "child_pugh_score": "A",
            "comorbidity_cardio": 1,
            "cv_risk_documented": 1,
            "drug_interaction_reviewed": 0,
            **_recent_docetaxel_labs(),
        },
    )
    assert metach_response.status_code == 200
    metach_result = metach_response.get_json()["result"]
    metach_names = {item["name"] for item in metach_result["eligible_treatments"]}
    assert metach_result["state"] == "mcspc_high_volume_metachronous"
    assert metach_result["fit_for_docetaxel"] is True
    assert metach_result["docetaxel_base_eligibility"] == "elegible_with_caution"
    assert metach_result["docetaxel_default_intensification"] == "no"
    assert metach_result["triplet_decision"]["status"] == "not_prioritized"
    assert any("darolutamida" in name.lower() for name in metach_names)
    assert any(
        str(item.get("trial", item.get("study_name", ""))).upper() == "ARASENS"
        and item.get("match") in (False, "No", "False", "no")
        for item in metach_result["trial_matches"]
    )
    assert all(
        str(item.get("trial", item.get("study_name", ""))).upper() != "PEACE-1"
        for item in metach_result["trial_matches"]
    )
    assert "Neuropatía periférica grado 2" in metach_result["docetaxel_caution_reasons"]


def test_high_volume_sync_accepts_structured_gleason_profile_without_manual_score(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/mcspc_high_volume_sync/evaluate",
        json={
            "metastatic_disease_known": 1,
            "metastasis_site": "Bone",
            "metastasis_count": 3,
            "bone_site_entries": [
                {"site_key": "thoracic_spine", "lesion_count": 2},
                {"site_key": "femur", "lesion_count": 1},
            ],
            "gleason_primary": 4,
            "gleason_secondary": 5,
            "gleason_tertiary": 5,
            "ecog_score": 1,
            "peripheral_neuropathy_grade": 0,
            "frailty_status": "Fit",
            "child_pugh_score": "A",
            "comorbidity_cardio": 0,
            "cv_risk_documented": 0,
            "drug_interaction_reviewed": 1,
            **_recent_docetaxel_labs(),
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["state"] == "mcspc_high_volume_sync"
    assert result["fit_for_docetaxel"] is True
    latitude_match = next(
        item
        for item in result["trial_matches"]
        if str(item.get("trial", item.get("study_name", ""))).upper() == "LATITUDE"
    )
    assert latitude_match["match"] in (True, "Sí", "Si", "si")


def test_high_volume_sync_triplet_ranking_changes_with_clinical_profile(app_client):
    client, _ = app_client

    favorable_abiraterone = client.post(
        "/api/modules/mcspc_high_volume_sync/evaluate",
        json={
            "metastatic_disease_known": 1,
            "bone_site_entries": [
                {"site_key": "thoracic_spine", "lesion_count": 3},
                {"site_key": "femur", "lesion_count": 1},
            ],
            "visceral_site_entries": [{"site_key": "liver", "lesion_count": 1}],
            "gleason_primary": 4,
            "gleason_secondary": 5,
            "ecog_score": 0,
            "peripheral_neuropathy_grade": 0,
            "frailty_status": "Fit",
            "child_pugh_score": "A",
            "comorbidity_cardio": 0,
            "cv_risk_documented": 0,
            "drug_interaction_reviewed": 1,
            "diabetes_uncontrolled": 0,
            "steroid_intolerance": 0,
            **_recent_docetaxel_labs(),
        },
    )
    assert favorable_abiraterone.status_code == 200
    favorable_result = favorable_abiraterone.get_json()["result"]
    assert favorable_result["preferred_frontline_regimen"]["regimen_code"] == "ADT_DOCETAXEL_ABIRATERONE"
    assert favorable_result["triplet_decision"]["preferred_triplet_regimen_code"] == "ADT_DOCETAXEL_ABIRATERONE"

    cardio_biased_to_daro = client.post(
        "/api/modules/mcspc_high_volume_sync/evaluate",
        json={
            "metastatic_disease_known": 1,
            "bone_site_entries": [
                {"site_key": "thoracic_spine", "lesion_count": 3},
                {"site_key": "femur", "lesion_count": 1},
            ],
            "gleason_primary": 4,
            "gleason_secondary": 5,
            "ecog_score": 0,
            "peripheral_neuropathy_grade": 0,
            "frailty_status": "Fit",
            "child_pugh_score": "A",
            "comorbidity_cardio": 1,
            "cv_risk_documented": 1,
            "drug_interaction_reviewed": 1,
            "diabetes_uncontrolled": 1,
            **_recent_docetaxel_labs(),
        },
    )
    assert cardio_biased_to_daro.status_code == 200
    cardio_result = cardio_biased_to_daro.get_json()["result"]
    assert cardio_result["preferred_frontline_regimen"]["regimen_code"] == "ADT_DOCETAXEL_DAROLUTAMIDE"
    assert cardio_result["triplet_decision"]["preferred_triplet_regimen_code"] == "ADT_DOCETAXEL_DAROLUTAMIDE"
    first_treatment = cardio_result["eligible_treatments"][0]
    assert first_treatment["component_drugs"]
    assert any(component.get("route") for component in first_treatment["component_drugs"])
    assert any(component.get("dose") for component in first_treatment["component_drugs"])


def test_high_volume_sync_ecog2_driver_changes_docetaxel_default_state(app_client):
    client, _ = app_client

    cancer_related = client.post(
        "/api/modules/mcspc_high_volume_sync/evaluate",
        json={
            "metastatic_disease_known": 1,
            "bone_site_entries": [
                {"site_key": "thoracic_spine", "lesion_count": 3},
                {"site_key": "femur", "lesion_count": 1},
            ],
            "gleason_primary": 4,
            "gleason_secondary": 5,
            "ecog_score": 2,
            "performance_status_driver": "cancer_related",
            "bone_pain": 1,
            "peripheral_neuropathy_grade": 0,
            "frailty_status": "Fit",
            "child_pugh_score": "A",
            "drug_interaction_reviewed": 1,
            **_recent_docetaxel_labs(),
        },
    )
    assert cancer_related.status_code == 200
    cancer_result = cancer_related.get_json()["result"]
    assert cancer_result["docetaxel_default_intensification"] == "conditional"
    assert cancer_result["docetaxel_trial_fit"]["peace1_like"] == "partial"
    assert cancer_result["triplet_decision"]["status"] == "conditional"

    frailty_driven = client.post(
        "/api/modules/mcspc_high_volume_sync/evaluate",
        json={
            "metastatic_disease_known": 1,
            "bone_site_entries": [
                {"site_key": "thoracic_spine", "lesion_count": 3},
                {"site_key": "femur", "lesion_count": 1},
            ],
            "gleason_primary": 4,
            "gleason_secondary": 5,
            "ecog_score": 2,
            "performance_status_driver": "comorbidity_or_frailty",
            "peripheral_neuropathy_grade": 0,
            "frailty_status": "Vulnerable",
            "child_pugh_score": "A",
            "drug_interaction_reviewed": 1,
            "comorbidity_seizure": 1,
            **_recent_docetaxel_labs(),
        },
    )
    assert frailty_driven.status_code == 200
    frailty_result = frailty_driven.get_json()["result"]
    assert frailty_result["docetaxel_default_intensification"] == "no"
    assert frailty_result["triplet_decision"]["status"] == "not_prioritized"
    assert frailty_result["preferred_frontline_regimen"]["regimen_code"] == "ADT_DAROLUTAMIDE"


def test_mhspc_doublets_keep_darolutamide_visible_outside_high_volume(app_client):
    client, _ = app_client

    low_volume = client.post(
        "/api/modules/mcspc_low_volume_sync_oligo/evaluate",
        json={
            "metastasis_count": 2,
            "metastasis_site": "Bone",
            "ecog_score": 0,
            "comorbidity_seizure": 1,
            "cv_risk_documented": 1,
            "drug_interaction_reviewed": 0,
            "rt_primary_received": 0,
        },
    )
    assert low_volume.status_code == 200
    low_result = low_volume.get_json()["result"]
    low_names = {item["name"] for item in low_result["eligible_treatments"]}
    assert any("darolutamida" in name.lower() for name in low_names)
    assert low_result["triplet_decision"]["status"] == "not_applicable"
    assert low_result["preferred_frontline_regimen"]["regimen_code"] == low_result["eligible_treatments"][0]["regimen_code"]
    assert low_result["eligible_treatments"][0]["priority"] in {"preferred", "preferente"}
    assert low_result["eligible_treatments"][0]["eligibility_status"] in {"preferred", "preferente"}
    assert "comparative_eligibility_matrix" in low_result
    low_trials = {str(item.get("trial", item.get("study_name", ""))).upper() for item in low_result["trial_matches"]}
    assert "PEACE-1" not in low_trials
    assert "ARASENS" not in low_trials

    oligo_metach = client.post(
        "/api/modules/mcspc_oligo_metachronous/evaluate",
        json={
            "metastasis_count": 3,
            "metastasis_site": "Bone",
            "ecog_score": 1,
            "comorbidity_cardio": 1,
            "cv_risk_documented": 1,
            "drug_interaction_reviewed": 0,
            "mdt_context": "Discusión multidisciplinaria",
        },
    )
    assert oligo_metach.status_code == 200
    oligo_result = oligo_metach.get_json()["result"]
    oligo_names = {item["name"] for item in oligo_result["eligible_treatments"]}
    assert any("darolutamida" in name.lower() for name in oligo_names)
    assert oligo_result["triplet_decision"]["status"] == "not_applicable"
    assert oligo_result["preferred_frontline_regimen"]["regimen_code"] == oligo_result["eligible_treatments"][0]["regimen_code"]
    assert oligo_result["eligible_treatments"][0]["priority"] in {"preferred", "preferente"}
    assert oligo_result["eligible_treatments"][0]["eligibility_status"] in {"preferred", "preferente"}
    assert "comparative_eligibility_matrix" in oligo_result
    oligo_trials = {str(item.get("trial", item.get("study_name", ""))).upper() for item in oligo_result["trial_matches"]}
    assert "PEACE-1" not in oligo_trials
    assert "ARASENS" not in oligo_trials


def test_m0_crpc_requires_castration_confirmation(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/m0_crpc/evaluate",
        json={"psadt_months": 7, "castration_resistant": 1, "castrate_testosterone_confirmed": 0, "imaging_negative": 1},
    )
    assert response.status_code == 200
    result = response.get_json()["result"]
    assert "no confirmada" in result["nccn_primary"]["label"].lower()
    assert "testosterona en rango de castración" in result["eligible_treatments"][0]["name"].lower()


def test_precision_paths_surface_akeega_and_pre_taxane_pluvicto(app_client):
    client, _ = app_client

    mhspc_response = client.post(
        "/api/modules/mcspc_high_volume/evaluate",
        json={
            "metastasis_count": 8,
            "metastasis_site": "Bone",
            "gleason_score": 9,
            "ecog_score": 1,
            "frailty_status": "Fit",
            "child_pugh_score": "A",
            "comorbidity_seizure": 0,
            "comorbidity_cardio": 0,
            "brca2_status": "Positivo",
            "hrr_gene": "BRCA2",
            "brca2_origin": "germline",
            "molecular_assay_source": "Biopsia metastásica",
            "molecular_assay_date": "2026-02-20",
        },
    )
    assert mhspc_response.status_code == 200
    mhspc_names = {item["name"] for item in mhspc_response.get_json()["result"]["eligible_treatments"]}
    assert any("niraparib" in name.lower() and "abiraterona" in name.lower() for name in mhspc_names)

    m1_response = client.post(
        "/api/modules/m1_crpc/evaluate",
        json={
            "hrr_status": "Negativo",
            "hrr_gene": "Desconocido",
            "biomarker_source": "Biopsia metastásica",
            "molecular_report_date": "2026-03-01",
            "msi_status": "estable",
            "metastasis_site": "Bone",
            "prior_therapy": "Enzalutamida",
            "prior_docetaxel_cycles": 0,
            "castrate_testosterone_confirmed": 1,
            "mcrpc_line_context": "post_arpi_pre_taxane",
            "docetaxel_fit": 0,
            "chemotherapy_delay_candidate": 1,
            "pain_symptoms": "Leve",
            "ecog_performance_status": 1,
            "psma_positive": 1,
            "psma_negative_dominant_lesions": 0,
        },
    )
    assert m1_response.status_code == 200
    m1_names = {item["name"] for item in m1_response.get_json()["result"]["eligible_treatments"]}
    assert "Lutecio-177 dirigido al antígeno prostático específico de membrana" in m1_names


def test_m1_crpc_structured_psma_degrades_pluvicto_confidence_when_partial(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/m1_crpc/evaluate",
        json={
            "hrr_status": "Negativo",
            "hrr_gene": "Desconocido",
            "biomarker_source": "Biopsia metastásica",
            "molecular_report_date": "2026-03-01",
            "msi_status": "estable",
            "metastasis_site": "Bone",
            "prior_therapy": "Enzalutamida",
            "prior_docetaxel_cycles": 0,
            "castrate_testosterone_confirmed": 1,
            "mcrpc_line_context": "post_arpi_pre_taxane",
            "docetaxel_fit": 0,
            "chemotherapy_delay_candidate": 1,
            "pain_symptoms": "Leve",
            "ecog_performance_status": 1,
            "psma_positive": 1,
            "psma_pet_done": 1,
            "psma_negative_dominant_lesions": 1,
            "psma_radioligand": "18F-PSMA-1007",
            "psma_uptake_pattern": "multifocal",
            "psma_rads_score": "3",
            "psma_total_lesions": 3,
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    treatment_names = {item["name"] for item in result["eligible_treatments"]}
    assert "Lutecio-177 dirigido al antígeno prostático específico de membrana" in treatment_names
    assert any("psma como plena" in item.lower() for item in result["not_recommended"])
    assert any("18f-psma-1007" in item.lower() for item in result["not_recommended"])


def test_supportive_documents_are_mapped_without_displacing_guidelines(app_client):
    client, _ = app_client

    response = client.get("/api/modules/m1_crpc/sources")
    assert response.status_code == 200
    sources = response.get_json()["sources"]

    assert any(source["guideline_or_trial"] == "NCCN 5.2026" and source["evidence_role"] == "primary_guideline" for source in sources)
    assert any(source["local_pdf_path"].endswith("/33.pdf") for source in sources)
    assert any(source["local_pdf_path"].endswith("/34.pdf") for source in sources)
    assert any(source["local_pdf_path"].endswith("/35.pdf") for source in sources)
    assert any(source["local_pdf_path"].endswith("/36.pdf") for source in sources)
    assert any(source["local_pdf_path"].endswith("/37.pdf") for source in sources)
    assert any(source["local_pdf_path"].endswith("/40.pdf") for source in sources)
    assert any(source["local_pdf_path"].endswith("/41.pdf") for source in sources)


def test_m1_crpc_surfaces_a_single_tier_one_priority(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/m1_crpc/evaluate",
        json={
            "hrr_status": "Positivo",
            "hrr_gene": "BRCA2",
            "biomarker_source": "ctDNA",
            "molecular_report_date": "2026-03-01",
            "msi_status": "inestable",
            "tmb_high": 1,
            "metastasis_site": "Bone",
            "prior_therapy": "Enzalutamida, Docetaxel",
            "prior_docetaxel_cycles": 6,
            "castrate_testosterone_confirmed": 1,
            "mcrpc_line_context": "post_taxane",
            "docetaxel_fit": 0,
            "chemotherapy_delay_candidate": 1,
            "pain_symptoms": "Sintomatico",
            "ecog_performance_status": 1,
            "psma_positive": 1,
            "psma_negative_dominant_lesions": 0,
        },
    )
    assert response.status_code == 200
    treatments = response.get_json()["result"]["eligible_treatments"]
    preferred = [item for item in treatments if item["priority"] == "preferente"]
    assert len(preferred) == 1
    assert preferred[0]["regimen_code"] in {"OLAPARIB", "PEMBROLIZUMAB", "LU177_PSMA617", "CABAZITAXEL"}
    assert response.get_json()["result"]["preferred_frontline_regimen"]["regimen_code"] == preferred[0]["regimen_code"]


def test_m1_crpc_structured_taxane_bundle_overrides_legacy_docetaxel_boolean(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/m1_crpc/evaluate",
        json={
            "hrr_status": "Negativo",
            "hrr_gene": "Desconocido",
            "biomarker_source": "Biopsia metastásica",
            "molecular_report_date": "2026-03-01",
            "msi_status": "estable",
            "metastasis_site": "Bone",
            "prior_therapy": "ADT",
            "prior_docetaxel_cycles": 0,
            "castrate_testosterone_confirmed": 1,
            "mcrpc_line_context": "first_line_mcrpc",
            "docetaxel_fit": 1,
            "chemotherapy_delay_candidate": 0,
            "pain_symptoms": "Leve",
            "ecog_score": 1,
            "frailty_status": "Fit",
            "child_pugh_score": "A",
            "peripheral_neuropathy_grade": 0,
            **_recent_docetaxel_labs(
                anc=900,
                platelets=180000,
                bilirubin=0.8,
                ast=32,
                alt=28,
                alp=110,
            ),
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    sequence_context = result["report_sections"]["sequence_context"]
    assert sequence_context["docetaxel_base_eligibility"] == "contraindicated"
    assert sequence_context["docetaxel_verification_status"] == "verified"
    assert not any(item["regimen_code"] == "DOCETAXEL" for item in result["eligible_treatments"])
    assert not any(match["trial"] == "TAX 327" and match["match"] for match in result["trial_matches"])


def test_diagnostic_registration_avoids_false_treatment_history_and_hides_advanced_widgets(app_client):
    client, db_path = app_client

    diagnostic_payload = {
        "psa": 8.7,
        "psad": 0.17,
        "dre_suspicious": 1,
        "pirads_score": 4,
        "prostate_volume_ml": 42,
        "planned_biopsy_type": "Dirigida + sistemática",
        "planned_biopsy_route": "Transperineal",
    }
    draft_response = client.post(
        "/api/clinical-assessments/draft",
        json={"module_id": "diagnostic_workup", "payload": diagnostic_payload},
    )
    assert draft_response.status_code == 200
    draft_data = draft_response.get_json()
    assessment_id = draft_data["assessment_id"]
    assert "redirect_url" not in draft_data
    assert draft_data["scope"] == "diagnostic"
    fragment_ids = {fragment["id"] for fragment in draft_data["registration_fragments"]}
    assert "fragment_common_identity_baseline" in fragment_ids
    assert "fragment_diagnostic" in fragment_ids
    assert "fragment_treatment_history" not in fragment_ids

    register_response = client.post(
        "/api/register_patient",
        json={
            "assessment_id": assessment_id,
            "nss": "44444444444",
            "full_name": "Paciente Diagnostico",
            "dob": "1972-04-10",
            "baseline_psa": 8.7,
            "metastasis_site": "M0",
            "volume_disease": "Low",
            "line_of_therapy": 1,
            "drug_scheme": "",
            "assessment_state": "diagnostic_workup",
        },
    )
    assert register_response.status_code == 200

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM treatment_history")
    assert cursor.fetchone()[0] == 0
    cursor.execute("SELECT COUNT(*) FROM biopsy_details")
    assert cursor.fetchone()[0] == 0
    cursor.execute("SELECT COUNT(*) FROM diagnostic_plans")
    assert cursor.fetchone()[0] == 1
    cursor.execute("SELECT COUNT(*) FROM mri_facts")
    assert cursor.fetchone()[0] == 1
    cursor.execute("SELECT COUNT(*) FROM biopsy_trigger_events")
    assert cursor.fetchone()[0] == 1
    conn.close()

    patient_response = client.get("/api/patient/44444444444")
    assert patient_response.status_code == 200
    patient_data = patient_response.get_json()["patient"]
    assert patient_data["treatments"] == []
    assert patient_data["prior_history"]["current_state"] == "diagnostic_workup"
    assert patient_data["biopsies"] == []
    assert patient_data["diagnostic_plans"]
    assert patient_data["mri_facts"]
    assert patient_data["biopsy_triggers"]

    # Faubot LXXXIV.b: post-LXXX `/patient_profile/<nss>` rendea v2 por default;
    # opt-out con `?v=legacy` preserva contrato v1 ("Última evaluación clínica modular").
    profile_html = client.get("/patient_profile/44444444444?v=legacy").get_data(as_text=True)
    assert "Última evaluación clínica modular" in profile_html
    assert "Plan diagnóstico actual" in profile_html
    assert "Historial de biopsias" not in profile_html


def test_clinical_calibration_harness_reaches_full_concordance(app_client):
    client, _ = app_client

    response = client.get("/api/clinical-calibration")
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    calibration = data["calibration"]
    assert calibration["total_cases"] >= 10
    assert calibration["failed_cases"] == 0
    assert calibration["concordance_pct"] == 100.0


def test_validated_algorithms_and_decision_quality_surface_in_localized_module(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/localized_initial/evaluate",
        json={
            "age": 63,
            "life_expectancy_years": 16,
            "psa": 5.8,
            "psad": 0.11,
            "clinical_tstage": "T1c",
            "gleason_primary": 3,
            "gleason_secondary": 3,
            "isup_grade": 1,
            "num_cores_positive": 2,
            "total_cores": 12,
            "max_core_involvement": 0.2,
            "percent_pattern_4": 0,
            "prior_mpmri": 1,
            "prior_mpmri_pirads_score": "2",
            "prior_mpmri_targeted_biopsy_status": "si",
            "confirmatory_biopsy_planned": 1,
            "nodal_status": "N0",
            "metastasis_site": "M0",
            "ecog_score": 0,
            "charlson_score": 1,
            "frailty_status": "Fit",
            "g8_score": 16,
            "anesthesia_surgical_fitness": "Fit",
        },
    )
    assert response.status_code == 200
    result = response.get_json()["result"]
    names = {item["name"] for item in result["validated_algorithms"]}
    assert "CAPRA" in names
    assert "Tablas de Partin" in names
    assert "MSKCC pre-radical prostatectomy nomogram" in names
    assert "PREDICT Prostate" in names
    assert result["decision_quality"]["requires_human_review"] is False
    assert result["decision_quality"]["confidence_category"] in {"alta", "vigilada"}


def test_rich_longitudinal_tables_persist_from_integrated_registration(app_client):
    client, db_path = app_client

    draft_response = client.post(
        "/api/clinical-assessments/draft",
        json={
            "module_id": "localized_initial",
            "payload": {
                "age": 66,
                "life_expectancy_years": 14,
                "psa": 7.1,
                "psad": 0.14,
                "clinical_tstage": "T1c",
                "gleason_primary": 3,
                "gleason_secondary": 4,
                "isup_grade": 2,
                "num_cores_positive": 3,
                "total_cores": 12,
                "max_core_involvement": 0.25,
                "percent_pattern_4": 15,
                "prior_mpmri": 1,
                "prior_mpmri_pirads_score": "3",
                "prior_mpmri_targeted_biopsy_status": "si",
                "prostate_volume_ml": 50,
                "genomic_classifier": "Decipher",
                "genomic_classifier_result": "Intermedio",
                "confirmatory_biopsy_planned": 1,
                "ipss_score": 9,
                "iief5_score": 17,
                "baseline_urinary_qol": 82,
                "baseline_sexual_qol": 68,
                "baseline_bowel_qol": 90,
                "nodal_status": "N0",
                "metastasis_site": "M0",
            },
        },
    )
    assert draft_response.status_code == 200
    assessment_id = draft_response.get_json()["assessment_id"]

    register_response = client.post(
        "/api/register_patient",
        json={
            "assessment_id": assessment_id,
            "assessment_state": "localized_initial",
            "nss": "55555555555",
            "full_name": "Paciente Localizado",
            "dob": "1968-08-20",
            "estado_residencia": "Jalisco",
            "family_history_detail": "Padre con cancer de prostata a los 70 anos",
            "baseline_psa": 7.1,
        },
    )
    assert register_response.status_code == 200
    payload = register_response.get_json()
    assert payload["recommendation_mode"] == "guideline_modular"
    assert payload["processing_summary"]["state"] == "localized_initial"

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM biopsy_details")
    assert cursor.fetchone()[0] == 1
    cursor.execute("SELECT COUNT(*) FROM genomic_profile")
    assert cursor.fetchone()[0] == 1
    cursor.execute("SELECT COUNT(*) FROM patient_pros")
    assert cursor.fetchone()[0] == 1
    cursor.execute("SELECT COUNT(*) FROM active_surveillance")
    assert cursor.fetchone()[0] == 0
    conn.close()
    # Faubot LXXXIV.b: opt-out v=legacy para preservar contrato v1 templates.
    profile_html = client.get("/patient_profile/55555555555?v=legacy").get_data(as_text=True)
    assert "Benchmarking operativo del estado actual" in profile_html
    assert "Torre de control del antígeno prostático específico" in profile_html
    assert "psaTreatmentTimelineChart" in profile_html
    assert "Gráfico de nadador" not in profile_html
    assert "Línea 1" not in profile_html
    patient_response = client.get("/api/patient/55555555555")
    assert patient_response.status_code == 200
    assert patient_response.get_json()["patient"]["active_surveillance"] == {}


def test_clinical_assessment_draft_and_patient_registration_flow(app_client):
    client, db_path = app_client
    payload = {
        "age": 65,
        "psa": 8.5,
        "clinical_tstage": "T2a",
        "gleason_primary": 4,
        "gleason_secondary": 3,
        "isup_grade": 3,
        "num_cores_positive": 4,
        "total_cores": 12,
        "max_core_involvement": 0.2,
        "psad": 0.18,
        "life_expectancy_years": 15,
        "cribriform_pattern": 0,
        "intraductal_carcinoma": 0,
        "nodal_status": "N0",
        "metastasis_site": "M0",
    }

    draft_response = client.post(
        "/api/clinical-assessments/draft",
        json={"module_id": "localized_initial", "payload": payload},
    )
    assert draft_response.status_code == 200
    draft_data = draft_response.get_json()
    assert draft_data["success"] is True
    assessment_id = draft_data["assessment_id"]
    assert "redirect_url" not in draft_data
    assert draft_data["assessment"]["state"] == "localized_initial"
    assert draft_data["scope"] == "localized"
    fragment_ids = {fragment["id"] for fragment in draft_data["registration_fragments"]}
    assert "fragment_common_identity_baseline" in fragment_ids
    assert "fragment_localized" in fragment_ids
    assert "fragment_mexico_cohort_optional" in fragment_ids
    assert draft_data["registration_defaults"]["baseline_psa"] == 8.5
    imported_names = {item["name"] for item in draft_data["imported_clinical_fields"]}
    assert "psa" in imported_names
    assert "clinical_tstage" in imported_names

    intake_redirect = client.get("/patient_intake", follow_redirects=False)
    assert intake_redirect.status_code == 302
    assert intake_redirect.headers["Location"].endswith("/clinical-hub")

    intake_page = client.get(f"/patient_intake?assessment_id={assessment_id}")
    assert intake_page.status_code == 200
    intake_html = intake_page.get_data(as_text=True)
    assert "Compatibilidad modular" in intake_html
    assert "mismo contexto modular del wizard" in intake_html

    draft_detail = client.get(f"/api/clinical-assessments/{assessment_id}")
    assert draft_detail.status_code == 200
    assert draft_detail.get_json()["scope"] == "localized"

    register_response = client.post(
        "/api/register_patient",
        json={
            "assessment_id": assessment_id,
            "nss": "11111111111",
            "full_name": "Paciente Wizard",
            "dob": "1970-01-01",
            "baseline_psa": 8.5,
            "ipss_score": 7,
            "iief5_score": 18,
            "estado_residencia": "Jalisco",
        },
    )
    assert register_response.status_code == 200
    register_data = register_response.get_json()
    assert register_data["success"] is True
    assert register_data["assessment_id"] == assessment_id
    assert register_data["next_routes"]["profile"].endswith("/patient_profile/11111111111")
    assert register_data["assessment"]["display_result"]["nccn_primary"]["titulo_clinico"]
    assert register_data["assessment"]["display_result"]["eau_comparison"]["explicacion_breve"]

    patient_response = client.get("/api/patient/11111111111")
    assert patient_response.status_code == 200
    patient_data = patient_response.get_json()["patient"]
    assert patient_data["latest_assessment"]["id"] == assessment_id
    assert patient_data["prior_history"]["assessment_source"] == "clinical_wizard"
    assert patient_data["prior_history"]["current_state"] == "localized_initial"
    assert patient_data["prior_history"]["management_intent_status"] == "candidate"
    assert patient_data["state_timeline"]
    assert patient_data["demographics"]["estado_residencia"] == "Jalisco"
    assert patient_data["pros"]
    assert patient_data["treatments"] == []

    timeline_response = client.get("/api/patients/11111111111/state-timeline")
    assert timeline_response.status_code == 200
    timeline_data = timeline_response.get_json()["state_timeline"]
    assert timeline_data[-1]["state"] == "localized_initial"
    assert timeline_data[-1]["event_kind"] == "pathology_confirmed"
    assert timeline_data[-1]["management_intent_status"] == "candidate"

    recompute_response = client.post("/api/patients/11111111111/recompute-care-plan")
    assert recompute_response.status_code == 200
    recompute_data = recompute_response.get_json()
    assert recompute_data["assessment"]["display_result"]["monitoring_plan"]["cadence"]

    # Faubot LXXXIV.b: opt-out v=legacy para preservar contrato v1 templates.
    profile_html = client.get("/patient_profile/11111111111?v=legacy").get_data(as_text=True)
    assert "Última evaluación clínica modular" in profile_html
    assert "Línea de estados clínicos persistidos" not in profile_html
    assert "Plan maestro de seguimiento protocolizado" in profile_html
    assert "Siguiente mejor acción" in profile_html
    assert "Motor de Decisión Clínica" not in profile_html


def test_legacy_results_are_normalized_to_enriched_spanish_output():
    legacy = humanize_result(
        {
            "state": "m0_crpc",
            "nccn_primary": {
                "guideline": "NCCN",
                "version": "5.2026",
                "label": "M0 CRPC",
                "recommendation": "Use ARPI intensification when PSADT is short and metastatic imaging is negative.",
            },
            "eau_comparison": {
                "guideline": "EAU",
                "version": "2026",
                "label": "M0 CRPC",
                "comparison": {"summary": "NCCN 2026 y EAU 2026 coinciden en la categoria principal."},
            },
            "eligible_treatments": [{"name": "Darolutamida + ADT", "priority": "preferred", "notes": "Preferred for seizure risk."}],
            "not_recommended": ["Avoid automatic escalation."],
            "missing_critical_inputs": ["psadt_months"],
            "contraindications": [],
            "durations_and_conditions": ["Continue ADT backbone."],
            "evidence_trace": [],
            "trial_matches": [],
            "applicability_badge": "guideline-consistent",
            "report_sections": {"summary": "M0 CRPC risk-adapted intensification pathway."},
        }
    )
    assert legacy["nccn_primary"]["titulo_clinico"]
    assert "antígeno prostático específico" in legacy["nccn_primary"]["trayectoria_recomendada"].lower()
    assert legacy["eau_comparison"]["explicacion_breve"]
    assert legacy["report_sections"]["structured_summary"]["mensaje_para_toma_de_decisiones_compartida"]
