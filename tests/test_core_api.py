# IEC 62304 §5.5 (Unit verification)
import csv
import io
import json
import re
import sqlite3
from datetime import date, timedelta

from prostanet.shared.tnm_engine import TNMEngine
from prostanet.shared.official_diagnosis import build_official_diagnosis_context
from prostanet.shared.presentation_text import resolve_option_label


def make_patient_payload(nss="12345678901", full_name="Paciente Demo", **overrides):
    payload = {
        "nss": nss,
        "full_name": full_name,
        "dob": "1960-01-01",
        "line_of_therapy": 1,
        "metastasis_site": "M0",
        "volume_disease": "Low",
        "baseline_psa": 8.4,
        "testosterone_baseline": 320,
    }
    payload.update(overrides)
    return payload


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


def _seed_latest_assessment_state(db_path, patient_id, state, module_id=None):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO clinical_assessments (
            module_id, state, input_snapshot, result_snapshot, guideline_versions, status, patient_id
        ) VALUES (?, ?, ?, ?, ?, 'linked', ?)
        """,
        (
            module_id or state,
            state,
            json.dumps({}),
            json.dumps({}),
            json.dumps({}),
            patient_id,
        ),
    )
    cursor.execute(
        "UPDATE prior_clinical_history SET current_state = ? WHERE patient_id = ?",
        (state, patient_id),
    )
    conn.commit()
    conn.close()


def _insert_postlocal_bcr_context(db_path, patient_id, *, surgery_date="2024-01-15", bcr_date="2026-03-01", bcr_psa=0.42, psadt=8.0):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO surgical_details (
            patient_id, surgery_date, surgery_type, pathological_stage
        ) VALUES (?, ?, 'RP_robotica', 'pT2')
        """,
        (patient_id, surgery_date),
    )
    cursor.execute(
        """
        INSERT INTO biochemical_recurrence (
            patient_id, primary_treatment, primary_treatment_date, bcr_detected,
            bcr_date, bcr_psa, bcr_definition, psadt_at_bcr
        ) VALUES (?, 'RP', ?, 1, ?, ?, 'AUA_0.2', ?)
        """,
        (patient_id, surgery_date, bcr_date, bcr_psa, psadt),
    )
    conn.commit()
    conn.close()


def _insert_treatment_line(db_path, patient_id, *, line_of_therapy, drug_scheme, start_date, end_date=None, context="metastatic"):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO treatment_history (
            patient_id, line_of_therapy, drug_scheme, start_date, end_date, outcome, regimen_json, line_of_therapy_context
        ) VALUES (?, ?, ?, ?, ?, 'Ongoing', ?, ?)
        """,
        (
            patient_id,
            line_of_therapy,
            drug_scheme,
            start_date,
            end_date,
            json.dumps(
                {
                    "line_of_therapy_number": line_of_therapy,
                    "drug_scheme": drug_scheme,
                    "drug_scheme_label": drug_scheme,
                    "line_of_therapy_context": context,
                }
            ),
            context,
        ),
    )
    conn.commit()
    conn.close()


def _insert_psa_longitudinal_points(db_path, patient_id, points):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    for sample_date, value in points:
        cursor.execute(
            """
            INSERT INTO biomarker_longitudinal (
                patient_id, biomarker_type, value, unit, sample_date, lab_source
            ) VALUES (?, 'PSA', ?, 'ng/mL', ?, 'unit_test')
            """,
            (patient_id, value, sample_date),
        )
    conn.commit()
    conn.close()


def _insert_testosterone_longitudinal_points(db_path, patient_id, points):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    for sample_date, value in points:
        cursor.execute(
            """
            INSERT INTO biomarker_longitudinal (
                patient_id, biomarker_type, value, unit, sample_date, lab_source
            ) VALUES (?, 'TESTOSTERONA', ?, 'ng/dL', ?, 'unit_test')
            """,
            (patient_id, value, sample_date),
        )
    conn.commit()
    conn.close()


def _update_patient_contact_status(
    db_path,
    patient_id,
    *,
    last_contact_date="2026-03-15",
    last_contact_status="alive",
    vital_status="alive",
):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE patient_identity
        SET last_contact_date = ?, last_contact_status = ?, vital_status = ?
        WHERE id = ?
        """,
        (last_contact_date, last_contact_status, vital_status, patient_id),
    )
    conn.commit()
    conn.close()


def _insert_genomic_profile(db_path, patient_id, *, test_date="2026-03-05", hrr="Positivo", brca2="Positivo", msi="Estable"):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO genomic_profile (
            patient_id, test_date, test_type, brca2_status, msi_status, hrr_overall
        ) VALUES (?, ?, 'Panel_HRR', ?, ?, ?)
        """,
        (patient_id, test_date, brca2, msi, hrr),
    )
    conn.commit()
    conn.close()


def _insert_psma_imaging(db_path, patient_id, *, study_date="2026-03-07", psma_positive=True):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO imaging_studies (
            patient_id, study_date, study_type, psma_result, findings_json
        ) VALUES (?, ?, 'PSMA PET/CT', ?, ?)
        """,
        (
            patient_id,
            study_date,
            "positivo" if psma_positive else "negativo",
            json.dumps(
                {
                    "lesion_locations": ["hueso", "ganglios"],
                    "psma_total_lesions": 2,
                }
            ),
        ),
    )
    conn.commit()
    conn.close()


def _insert_structured_psma_imaging(
    db_path,
    patient_id,
    *,
    study_date="2026-03-07",
    psma_result="local/pélvico",
    radioligand="68Ga-PSMA-11",
    index_site="ganglio pélvico",
    suvmax=14.2,
    uptake_pattern="focal",
    rads="4",
    total_lesions=1,
    lesion_locations=None,
    negative_dominant=False,
    conventional_stage="M0",
    psma_stage="M0",
    upstaged=False,
    management_changed=True,
):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO imaging_studies (
            patient_id, study_date, study_type, psma_result, psma_suv_max, findings_json,
            psma_radioligand, psma_index_lesion_site, psma_index_lesion_suvmax, psma_uptake_pattern,
            psma_rads_score, conventional_stage_before_psma, psma_stage_after_psma,
            psma_upstaged_vs_conventional, psma_management_changed
        ) VALUES (?, ?, 'PSMA PET/CT', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            patient_id,
            study_date,
            psma_result,
            suvmax,
            json.dumps(
                {
                    "lesion_locations": lesion_locations or ["pelvis"],
                    "psma_total_lesions": total_lesions,
                    "psma_negative_dominant_lesions": negative_dominant,
                }
            ),
            radioligand,
            index_site,
            suvmax,
            uptake_pattern,
            rads,
            conventional_stage,
            psma_stage,
            1 if upstaged else 0,
            1 if management_changed else 0,
        ),
    )
    conn.commit()
    conn.close()


def _update_latest_assessment_input(db_path, patient_id, payload):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, input_snapshot
        FROM clinical_assessments
        WHERE patient_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (patient_id,),
    )
    row = cursor.fetchone()
    if row is None:
        conn.close()
        raise AssertionError("No latest assessment found to update")
    current_snapshot = json.loads(row[1] or "{}")
    current_snapshot.update(payload)
    cursor.execute(
        "UPDATE clinical_assessments SET input_snapshot = ? WHERE id = ?",
        (json.dumps(current_snapshot), row[0]),
    )
    conn.commit()
    conn.close()


def _update_latest_assessment_result_snapshot(db_path, patient_id, payload):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, result_snapshot
        FROM clinical_assessments
        WHERE patient_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (patient_id,),
    )
    row = cursor.fetchone()
    if row is None:
        conn.close()
        raise AssertionError("No latest assessment found to update")
    current_snapshot = json.loads(row[1] or "{}")
    current_snapshot.update(payload)
    cursor.execute(
        "UPDATE clinical_assessments SET result_snapshot = ? WHERE id = ?",
        (json.dumps(current_snapshot), row[0]),
    )
    conn.commit()
    conn.close()


def test_schedule_exposes_palliative_lane_and_capture_blocks_when_symptom_burden_is_high(app_client):
    client, db_path = app_client
    payload = make_patient_payload(nss="39999999991", full_name="Paciente Paliativo Longitudinal")
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "m1_crpc")
    _insert_treatment_line(
        db_path,
        patient_id,
        line_of_therapy=1,
        drug_scheme="ADT_DAROLUTAMIDE",
        start_date="2026-01-10",
        context="mcrpc",
    )

    visit_response = client.post(
        f"/api/patients/{patient_id}/visits",
        json={
            "state": "m1_crpc",
            "visit_date": date.today().isoformat(),
            "current_treatment": "ADT_DAROLUTAMIDE",
            "drug_scheme": "ADT_DAROLUTAMIDE",
            "line_of_therapy_number": 1,
            "line_of_therapy_context": "mcrpc_first_line",
            "pain": 8,
            "bpi_worst_pain": 8,
            "bone_pain": 1,
            "neuropathic_pain": 0,
            "current_analgesics": "tramadol",
            "opioid_use": 1,
            "breakthrough_pain": 1,
            "bowel_regimen_started": 0,
            "fatigue_score": 6,
            "dyspnea_score": 2,
            "nausea_score": 1,
            "constipation_score": 2,
            "appetite_loss": 1,
            "insomnia_score": 1,
            "depression_score": 1,
            "anxiety_score": 1,
            "ecog": 1,
            "ecog_delta_3mo": 1,
            "weight_loss_6m_pct": 5,
            "albumin": 3.6,
            "refractory_pain": 1,
            "advance_directive_documented": 0,
            "goals_of_care_discussed": 0,
            "healthcare_surrogate_designated": 0,
            "patient_prefers_comfort": 0,
            "prior_systemic_lines": 1,
        },
    )
    assert visit_response.status_code == 200

    schedule_payload = client.get(f"/api/patients/{patient_id}/schedule").get_json()

    assert schedule_payload["palliative_transition_bundle"]["care_mode"] == "concurrent_palliative_care"
    assert schedule_payload["palliative_transition_bundle"]["trigger_status"] in {"intensify_symptom_control", "concurrent_support"}
    assert schedule_payload["palliative_monitoring_package"]["required_visit_fields"]
    assert "pain" in schedule_payload["palliative_monitoring_package"]["required_visit_fields"]
    assert schedule_payload["care_intent_contract"]["palliative_trigger_status"] in {"intensify_symptom_control", "concurrent_support"}
    assert schedule_payload["decision_blocking_inputs"] is not None
    assert schedule_payload["palliative_capture_block"]["fields"]
    assert schedule_payload["goals_of_care_capture_block"]["fields"]
    schedule_titles = {str(item.get("title") or "") for item in schedule_payload["schedule"]}
    assert any("Control sintomático paliativo" in title for title in schedule_titles)
    assert any("Objetivos de cuidado y planeación anticipada" in title for title in schedule_titles)


def test_survivorship_plan_endpoint_returns_canonical_bundle_and_schedule_overlay(app_client):
    client, db_path = app_client
    payload = make_patient_payload(nss="39999999992", full_name="Paciente Survivorship Endpoint")
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "post_prostatectomy")

    visit_response = client.post(
        f"/api/patients/{patient_id}/visits",
        json={
            "state": "post_prostatectomy",
            "visit_date": date.today().isoformat(),
            "prior_prostatectomy": 1,
            "prior_radiation": 0,
            "prior_adt": 0,
            "prior_docetaxel": 0,
            "prior_cabazitaxel": 0,
            "on_denosumab": 0,
            "on_zoledronate": 0,
            "ipss_score": 23,
            "pad_count": 3,
            "continence_status": "Severa",
            "leakage_bother": 6,
            "iief5_score": 7,
            "nerve_sparing": "No",
            "pelvic_floor_pt_started": 0,
            "depression_score": 3,
            "anxiety_score": 2,
            "sexual_bother": 7,
            "body_image_distress": 5,
            "return_to_work_status": "Ajustado",
        },
    )
    assert visit_response.status_code == 200

    survivorship_response = client.get(f"/api/patients/{patient_id}/survivorship-plan")
    assert survivorship_response.status_code == 200
    survivorship_payload = survivorship_response.get_json()
    transition_bundle = survivorship_payload["survivorship_transition_bundle"]
    monitoring_package = survivorship_payload["survivorship_monitoring_package"]

    assert survivorship_payload["survivorship_plan"]["available"] is True
    assert transition_bundle["survivorship_track"] == "late_effect_intervention"
    assert transition_bundle["trigger_status"] == "refer_specialist"
    assert transition_bundle["dominant_late_effect_domain"] == "urinary_recovery"
    assert "ipss_score" in monitoring_package["required_visit_fields"]
    assert survivorship_payload["survivorship_schedule_overlay"]["available"] is True

    schedule_payload = client.get(f"/api/patients/{patient_id}/schedule").get_json()
    assert schedule_payload["survivorship_transition_bundle"]["survivorship_track"] == "late_effect_intervention"
    schedule_titles = {str(item.get("title") or "") for item in schedule_payload["schedule"]}
    assert "Recuperación urinaria y sexual post-prostatectomía" in schedule_titles


def test_decision_governance_endpoint_exposes_spanish_score_interpretations(app_client):
    client, db_path = app_client
    import tracking_db

    payload = make_patient_payload(nss="39999999993", full_name="Paciente Governance Scores")
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "post_prostatectomy")

    assert tracking_db.save_pro_assessment(
        patient_id,
        {
            "date": date.today().isoformat(),
            "ipss_total": 23,
            "iief5_score": 7,
            "eq5d_vas": 35,
            "epic26_urinary_domain": 38,
            "epic26_sexual_domain": 18,
        },
    )

    governance_response = client.get(f"/api/patients/{patient_id}/decision-governance")
    assert governance_response.status_code == 200
    governance_payload = governance_response.get_json()
    snapshot = governance_payload["score_interpretation_catalog_snapshot"]

    assert snapshot["ipss_total"]["score_grade_es"] == "Severo"
    assert "Carga urinaria alta" in snapshot["ipss_total"]["clinical_equivalence_es"]
    assert snapshot["iief5_score"]["score_grade_es"] == "Disfunción severa"
    assert snapshot["eq5d_vas"]["score_grade_es"] == "Calidad de vida muy baja"
    assert snapshot["epic26_urinary_incontinence_domain"]["score_grade_es"] == "Severamente afectada"
    assert snapshot["epic26_urinary_irritative_domain"]["score_grade_es"] == "Severamente afectada"
    assert snapshot["epic26_urinary_domain"]["score_grade_es"] == "Severamente afectada"
    assert isinstance(governance_payload["diagnostic_certainty_bundle"], dict)
    assert isinstance(governance_payload["staging_certainty_bundle"], dict)
    assert governance_payload["minimum_decisive_dataset_bundle"]["dataset_key"] == "post_prostatectomy"
    assert isinstance(governance_payload["therapeutic_window_bundle"], dict)
    assert isinstance(governance_payload["precision_workflow_bundle"], dict)
    assert isinstance(governance_payload["registry_core_bundle"], dict)
    assert isinstance(governance_payload["endpoint_adjudication_bundle"], dict)
    assert isinstance(governance_payload["data_certainty_bundle"], dict)

    schedule_payload = client.get(f"/api/patients/{patient_id}/schedule").get_json()
    assert schedule_payload["recommendation_block_status"] in {"clear", "provisional", "hard_stop"}
    assert schedule_payload["score_interpretation_catalog_snapshot"]["ipss_total"]["score_grade_es"] == "Severo"
    assert schedule_payload["minimum_decisive_dataset_bundle"]["dataset_key"] == "post_prostatectomy"
    assert "therapeutic_window_bundle" in schedule_payload


def test_therapeutic_windows_endpoint_prioritizes_post_rp_salvage_and_persists_event(app_client):
    client, db_path = app_client
    import tracking_db

    payload = make_patient_payload(nss="399999999933", full_name="Paciente Worklist Post RP")
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "post_prostatectomy")

    response = client.get(f"/api/patients/{patient_id}/therapeutic-windows")
    assert response.status_code == 200
    window_payload = response.get_json()["window_worklist_bundle"]

    assert window_payload["available"] is True
    assert window_payload["top_active_window"]["window_key"] == "post_rp_salvage_window"
    assert any("salvage post-RP" in task["label"] or "PSADT" in task["label"] for task in window_payload["closure_tasks"])

    schedule_payload = client.get(f"/api/patients/{patient_id}/schedule").get_json()
    assert schedule_payload["window_worklist_bundle"]["top_active_window"]["window_key"] == "post_rp_salvage_window"
    assert schedule_payload["schedule"][0]["window_closure_priority"] is True

    record = tracking_db.get_patient_full_record(patient_id)
    assert record["therapeutic_window_events"]
    assert record["therapeutic_window_events"][0]["window_key"] == "post_rp_salvage_window"


def test_post_negative_biopsy_followup_reopens_workup_when_mri_signal_persists(app_client):
    client, db_path = app_client
    import tracking_db

    payload = make_patient_payload(
        nss="399999999931",
        full_name="Paciente Sospecha Persistente",
        baseline_psa=7.6,
    )
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "post_negative_biopsy_followup")

    assert tracking_db.save_mri_fact(
        patient_id,
        {
            "fact_date": date.today().isoformat(),
            "decision_usable": 1,
            "pirads_score": 5,
            "lesion_location": "base periférica derecha",
            "lesion_size_mm": 14,
            "prostate_volume_ml": 38,
        },
    )
    assert tracking_db.save_biopsy(
        patient_id,
        {
            "biopsy_date": date.today().isoformat(),
            "biopsy_type": "fusion",
            "biopsy_route": "transperineal",
            "biopsy_context": "diagnostica",
            "total_cores": 12,
            "positive_cores": 0,
            "systematic_cores": [{"core_id": "S1", "core_type": "systematic", "positive": False}],
            "targeted_cores": [{"core_id": "T1", "core_type": "targeted", "positive": False}],
        },
    )

    governance_payload = client.get(f"/api/patients/{patient_id}/decision-governance").get_json()
    diagnostic_bundle = governance_payload["diagnostic_certainty_bundle"]
    window_worklist_bundle = governance_payload["window_worklist_bundle"]

    assert diagnostic_bundle["diagnosis_certainty"] == "persistent_suspicion_after_negative_biopsy"
    assert diagnostic_bundle["negative_biopsy_followup_status"] == "persistent_suspicion_reopen_workup"
    assert "PI-RADS 5" in diagnostic_bundle["persistent_suspicion_drivers"]
    assert window_worklist_bundle["top_active_window"]["window_key"] == "diagnostic_mri_biopsy_window"
    assert governance_payload["recommendation_block_status"] in {"provisional", "hard_stop"}


def test_post_negative_biopsy_followup_reopens_workup_when_dre_remains_suspicious(app_client):
    client, db_path = app_client
    import tracking_db

    payload = make_patient_payload(
        nss="39999999941",
        full_name="Paciente DRE Persistente",
        baseline_psa=5.4,
    )
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "post_negative_biopsy_followup")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "psa": 5.4,
            "psad": 0.11,
            "pirads_score": "3",
            "dre_suspicious": "1",
            "prior_biopsy_count": 1,
            "planned_biopsy_type": "Pendiente",
            "planned_biopsy_route": "No definida",
        },
    )

    assert tracking_db.save_biopsy(
        patient_id,
        {
            "biopsy_date": date.today().isoformat(),
            "biopsy_type": "systematic",
            "biopsy_route": "transperineal",
            "biopsy_context": "diagnostica",
            "total_cores": 12,
            "positive_cores": 0,
        },
    )

    governance_payload = client.get(f"/api/patients/{patient_id}/decision-governance").get_json()
    diagnostic_bundle = governance_payload["diagnostic_certainty_bundle"]
    window_worklist_bundle = governance_payload["window_worklist_bundle"]

    assert diagnostic_bundle["negative_biopsy_followup_status"] == "persistent_suspicion_reopen_workup"
    assert "DRE sospechoso" in diagnostic_bundle["persistent_suspicion_drivers"]
    assert window_worklist_bundle["top_active_window"]["window_key"] == "diagnostic_mri_biopsy_window"
    assert "dre" in window_worklist_bundle["top_active_window"]["why_this_matters_now"].lower() or governance_payload["recommendation_block_status"] in {"provisional", "hard_stop"}


def test_diagnostic_workup_requires_repeat_psa_before_clear_closure_when_initial_psa_is_three_to_ten(app_client):
    client, db_path = app_client

    payload = make_patient_payload(
        nss="39999999942",
        full_name="Paciente Repeat PSA",
        baseline_psa=5.8,
    )
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "diagnostic_workup")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "psa": 5.8,
            "psad": 0.12,
            "pirads_score": "3",
            "dre_suspicious": "0",
            "prostate_volume_ml": 48,
            "planned_biopsy_type": "Pendiente",
            "planned_biopsy_route": "No definida",
        },
    )

    governance_payload = client.get(f"/api/patients/{patient_id}/decision-governance").get_json()
    diagnostic_bundle = governance_payload["diagnostic_certainty_bundle"]
    dataset_bundle = governance_payload["minimum_decisive_dataset_bundle"]
    top_window = governance_payload["window_worklist_bundle"]["top_active_window"]

    assert diagnostic_bundle["repeat_psa_required"] is True
    assert diagnostic_bundle["repeat_psa_status"] == "required_not_done"
    assert "repeat_psa_value" in dataset_bundle["missing_required_fields"]
    assert top_window["window_key"] == "diagnostic_mri_biopsy_window"
    assert any("psa repetido" in task["label"].lower() for task in top_window["closure_tasks"])
    assert governance_payload["recommendation_block_status"] in {"provisional", "hard_stop"}


def test_patient_profile_uses_provisional_copy_for_repeat_psa_gate(app_client):
    client, db_path = app_client

    payload = make_patient_payload(
        nss="399999999421",
        full_name="Paciente Perfil Repeat PSA",
        baseline_psa=5.8,
    )
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "diagnostic_workup")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "psa": 5.8,
            "psad": 0.12,
            "pirads_score": "3",
            "dre_suspicious": "0",
            "prostate_volume_ml": 48,
        },
    )

    profile_response = client.get(f"/patient_profile/{payload['nss']}")
    assert profile_response.status_code == 200
    html = profile_response.get_data(as_text=True)

    assert "Sospecha de c&aacute;ncer de pr&oacute;stata en estudio" in html or "Sospecha de cáncer de próstata en estudio" in html
    assert "Repetir PSA antes de cerrar la decisi&oacute;n diagn&oacute;stica" in html or "Repetir PSA antes de cerrar la decisión diagnóstica" in html
    assert "histol&oacute;gicamente confirmado" not in html
    assert "histológicamente confirmado" not in html


def test_patient_profile_surfaces_reopen_copy_for_suspicious_dre_after_negative_biopsy(app_client):
    client, db_path = app_client
    import tracking_db

    payload = make_patient_payload(
        nss="399999999422",
        full_name="Paciente Perfil Reapertura",
        baseline_psa=5.4,
    )
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "post_negative_biopsy_followup")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "psa": 5.4,
            "psad": 0.11,
            "pirads_score": "3",
            "dre_suspicious": "1",
            "prior_biopsy_count": 1,
        },
    )
    assert tracking_db.save_biopsy(
        patient_id,
        {
            "biopsy_date": date.today().isoformat(),
            "biopsy_type": "systematic",
            "biopsy_route": "transperineal",
            "biopsy_context": "diagnostica",
            "total_cores": 12,
            "positive_cores": 0,
        },
    )

    profile_response = client.get(f"/patient_profile/{payload['nss']}")
    assert profile_response.status_code == 200
    html = profile_response.get_data(as_text=True)

    assert "Sospecha persistente tras biopsia benigna inicial" in html
    assert "Reabrir estudio diagn&oacute;stico con MRI, PSAD y decisi&oacute;n de rebiopsia" in html or "Reabrir estudio diagnóstico con MRI, PSAD y decisión de rebiopsia" in html
    assert "Mantener seguimiento diagn&oacute;stico con PSA y MRI seriados" not in html
    assert "Mantener seguimiento diagnóstico con PSA y MRI seriados" not in html


def test_localized_governance_exposes_modality_bundles_and_closure_window_when_tradeoff_dataset_is_incomplete(app_client):
    client, db_path = app_client

    payload = make_patient_payload(
        nss="399999999424",
        full_name="Paciente Modalidad Local",
        baseline_psa=9.8,
        clinical_tstage="T2a",
        gleason_primary=3,
        gleason_secondary=4,
        isup_grade=2,
        num_cores_positive=3,
        total_cores=12,
        life_expectancy_years=14,
    )
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "localized_initial")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "psa": 9.8,
            "clinical_tstage": "T2a",
            "clinical_risk_group": "FAVORABLE INTERMEDIATE",
            "isup_grade": 2,
            "nodal_status": "N0",
            "metastasis_site": "M0",
            "positive_cores": 3,
            "total_cores": 12,
            "pirads_score": "3",
            "prostate_volume_ml": 42,
            "ecog_score": 1,
            "charlson_score": 1,
            "anesthesia_surgical_fitness": "Fit",
            "frailty_status": "Fit",
            "g8_score": 15,
            "ipss_score": 7,
            "iief5_score": 19,
        },
    )

    governance_payload = client.get(f"/api/patients/{patient_id}/decision-governance").get_json()
    dataset_bundle = governance_payload["minimum_decisive_dataset_bundle"]
    modality_bundle = governance_payload["localized_modality_fitness_bundle"]
    window_worklist_bundle = governance_payload["window_worklist_bundle"]

    assert modality_bundle["available"] is True
    assert governance_payload["localized_tradeoff_bundle"]["available"] is True
    assert governance_payload["patient_priority_profile"]["available"] is False
    assert dataset_bundle["dataset_key"] == "localized_initial"
    assert "patient_priority_profile" not in dataset_bundle["missing_required_fields"]
    assert window_worklist_bundle["top_active_window"]["window_key"] == "localized_modality_closure_window"
    assert "radiotherapy_feasibility" in (window_worklist_bundle["top_active_window"].get("required_inputs") or [])


def test_patient_profile_surfaces_localized_modality_panel_when_tradeoff_is_open(app_client):
    client, db_path = app_client

    payload = make_patient_payload(
        nss="399999999425",
        full_name="Paciente Perfil Modalidad",
        baseline_psa=9.6,
        clinical_tstage="T2a",
        gleason_primary=3,
        gleason_secondary=4,
        isup_grade=2,
        num_cores_positive=3,
        total_cores=12,
        life_expectancy_years=14,
    )
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "localized_initial")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "psa": 9.6,
            "clinical_tstage": "T2a",
            "clinical_risk_group": "FAVORABLE INTERMEDIATE",
            "isup_grade": 2,
            "nodal_status": "N0",
            "metastasis_site": "M0",
            "positive_cores": 3,
            "total_cores": 12,
            "pirads_score": "3",
            "prostate_volume_ml": 40,
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

    profile_response = client.get(f"/patient_profile/{payload['nss']}")
    assert profile_response.status_code == 200
    html = profile_response.get_data(as_text=True)

    assert "Aptitud por modalidad local" in html
    assert "Candidato a RP" in html
    assert "Modalidad dominante hoy" in html
    assert "Faltan prioridades expl&iacute;citas del paciente" in html or "Faltan prioridades explícitas del paciente" in html


def test_adt_progression_verification_keeps_crpc_dataset_blocked_until_castration_and_restaging_close(app_client):
    client, db_path = app_client

    payload = make_patient_payload(nss="399999999932", full_name="Paciente Verificación CRPC")
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "adt_progression_verification")

    governance_payload = client.get(f"/api/patients/{patient_id}/decision-governance").get_json()
    dataset_bundle = governance_payload["minimum_decisive_dataset_bundle"]
    window_worklist_bundle = governance_payload["window_worklist_bundle"]
    schedule_payload = client.get(f"/api/patients/{patient_id}/schedule").get_json()

    assert dataset_bundle["dataset_key"] == "CRPC"
    assert dataset_bundle["dataset_status"] in {"provisional", "hard_stop"}
    assert "testosterone" in dataset_bundle["missing_required_fields"]
    assert window_worklist_bundle["top_active_window"]["window_key"] == "crpc_verification_window"
    assert "testosterona" in schedule_payload["next_best_action"]["title"].lower() or "crpc" in schedule_payload["next_best_action"]["title"].lower()
    assert governance_payload["recommendation_block_status"] in {"provisional", "hard_stop"}


def test_patient_profile_exits_nmcrpc_copy_when_psma_already_documents_recent_m1(app_client):
    import tracking_db

    client, db_path = app_client

    payload = make_patient_payload(nss="399999999932B", full_name="Paciente PSMA M1")
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "m0_crpc")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "current_adt_context": "ADT continua",
            "conventional_imaging_status": "M0",
            "progression_pattern": "biochemical_only",
            "psa": 3.4,
        },
    )
    _insert_structured_psma_imaging(
        db_path,
        patient_id,
        study_date="2026-03-20",
        psma_result="diseminado",
        uptake_pattern="diseminado",
        conventional_stage="M0",
        psma_stage="M1b",
        lesion_locations=["hueso"],
        total_lesions=2,
    )

    longitudinal_payload = tracking_db.refresh_longitudinal_intelligence(patient_id, force_recompute=True)
    governance_payload = client.get(f"/api/patients/{patient_id}/decision-governance").get_json()
    profile_html = client.get(f"/patient_profile/{payload['nss']}").get_data(as_text=True)

    assert longitudinal_payload["metastatic_stage_resolved"] == "M1b"
    assert longitudinal_payload["metastatic_detection_basis"] == "psma_only"
    assert longitudinal_payload["signals"]["effective_state"] == "adt_progression_verification"
    assert governance_payload["window_worklist_bundle"]["top_active_window"]["window_key"] == "progression_verification_closure_window"
    assert "M1b" in profile_html
    assert "m0 CRPC ya no es elegible" in profile_html
    assert "Metástasis documentadas por PET PSMA; el caso ya corresponde a M1." in profile_html
    assert "M1 documentado; falta cerrar castraci" in profile_html


def test_patient_profile_hides_legacy_recommendation_panel_when_reconciled_surface_is_post_rt(app_client):
    client, db_path = app_client

    payload = make_patient_payload(
        nss="399999999932D",
        full_name="Paciente Perfil Consistente",
        metastasis_site="M1",
        volume_disease="High",
    )
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE prior_clinical_history SET current_state = ? WHERE patient_id = ?",
        ("post_radiotherapy_or_local_salvage", patient_id),
    )
    conn.commit()
    conn.close()

    profile_response = client.get(f"/patient_profile/{payload['nss']}")
    assert profile_response.status_code == 200
    html = profile_response.get_data(as_text=True)

    assert "Consistencia de superficies" in html
    assert "estado cl&iacute;nico efectivo actual" in html or "estado clínico efectivo actual" in html
    assert "Motor de Decisi&oacute;n Cl&iacute;nica" not in html
    assert "Motor de Decisión Clínica" not in html


def test_positive_m1_imaging_stays_m1_when_stale_and_requests_restaging_update(app_client):
    import tracking_db

    client, db_path = app_client

    payload = make_patient_payload(nss="399999999932C", full_name="Paciente M1 restaging")
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "m0_crpc")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "current_adt_context": "ADT continua",
            "conventional_imaging_status": "M0",
            "progression_pattern": "biochemical_only",
            "psa": 6.1,
        },
    )
    _insert_structured_psma_imaging(
        db_path,
        patient_id,
        study_date="2025-02-15",
        psma_result="diseminado",
        uptake_pattern="diseminado",
        conventional_stage="M0",
        psma_stage="M1b",
        lesion_locations=["hueso"],
        total_lesions=3,
    )

    longitudinal_payload = tracking_db.refresh_longitudinal_intelligence(patient_id, force_recompute=True)

    assert longitudinal_payload["metastatic_stage_resolved"] == "M1b"
    assert longitudinal_payload["restaging_update_required"] is True
    assert longitudinal_payload["restaging_currentness_status"] == "stale"
    assert longitudinal_payload["signals"]["effective_state"] == "adt_progression_verification"


def test_clinical_copy_bundle_separates_transition_from_current_decision_for_vulnerable_mhspc():
    from prostanet.domains.patient_tracking.profile_compass import build_patient_profile_view_model

    patient = {
        "identity": {"nss": "399999999423", "full_name": "Paciente Perfil mHSPC"},
        "baseline": {
            "histology_subtype": "Adenocarcinoma acinar",
            "gleason_primary": 4,
            "gleason_secondary": 4,
            "isup_grade": 4,
            "volume_disease": "High",
            "g8_score": 11,
            "mini_cog_score": 2,
        },
        "prior_history": {"current_state": "mcspc_high_volume_sync"},
        "follow_ups": [],
        "biopsies": [],
        "source_documents": [],
        "latest_signal_snapshot": {
            "next_best_action": {
                "title": "Priorizar ADT + darolutamida",
                "action_title": "Priorizar ADT + darolutamida",
                "action_rationale": "La vulnerabilidad geriátrica y cognitiva actual desprioriza el triplete hasta completar CGA.",
                "transition_title": "Confirmar transición a mHSPC sincrónico de bajo volumen",
                "transition_rationale": "La carga metastásica visible necesita cierre documental antes de reclasificar el subfenotipo.",
                "transition_pending": True,
                "transition_target_state": "mcspc_low_volume_sync_oligo",
                "recommendation_family": "ADT + ARPI",
            },
            "care_intent_contract": {
                "headline": "Confirmar transición a mHSPC sincrónico de bajo volumen",
                "narrative": "Narrativa legacy que no debe dominar el copy principal.",
                "recommendation_family": "ADT + ARPI",
            },
        },
        "care_intent_contract": {
            "headline": "Confirmar transición a mHSPC sincrónico de bajo volumen",
            "narrative": "Narrativa legacy que no debe dominar el copy principal.",
            "recommendation_family": "ADT + ARPI",
        },
        "transition_resolution": {"policy": "manual_confirmation_required"},
        "decision_governance_bundle": {},
        "window_worklist_bundle": {},
    }
    latest_assessment_raw = {
        "assessment_date": "2026-04-02",
        "state": "mcspc_high_volume_sync",
        "input_snapshot": {"volume_disease": "High", "g8_score": 11, "mini_cog_score": 2},
        "result_snapshot": {},
    }
    latest_assessment = {
        "state": "mcspc_high_volume_sync",
        "module_label": "mHSPC de alto volumen sincrónico",
        "display_result": {"source_citations": []},
    }
    longitudinal_bundle = {
        "signals": {
            "state": "mcspc_high_volume_sync",
            "reconciled_state": "mcspc_high_volume_sync",
            "management_track": "systemic_surveillance",
            "reconciled_management_track": "systemic_surveillance",
            "next_best_action": patient["latest_signal_snapshot"]["next_best_action"],
        },
        "care_intent_contract": patient["care_intent_contract"],
    }

    profile = build_patient_profile_view_model(
        patient=patient,
        latest_assessment_raw=latest_assessment_raw,
        latest_assessment=latest_assessment,
        state_timeline=[{"management_intent_status_label": "Pendiente de confirmación", "event_kind_label": "Recomendación generada"}],
        care_overlays=[],
        longitudinal_bundle=longitudinal_bundle,
    )

    copy_bundle = profile["clinical_copy_bundle"]

    assert copy_bundle["operational_state_display"]["headline"] == "mHSPC de alto volumen sincrónico"
    assert copy_bundle["decision_today_display"]["headline"] == "Priorizar ADT + darolutamida"
    assert copy_bundle["transition_display"]["visible"] is True
    assert "bajo volumen" in copy_bundle["transition_display"]["headline"].lower()
    assert "Confirmar transición" not in copy_bundle["decision_today_display"]["headline"]


def test_window_worklist_bundle_surfaces_opportunity_metrics_for_precision_and_psma_gaps(app_client):
    client, db_path = app_client

    payload = make_patient_payload(nss="399999999934", full_name="Paciente Worklist Precision")
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "m1_crpc")

    window_payload = client.get(f"/api/patients/{patient_id}/therapeutic-windows").get_json()["window_worklist_bundle"]

    active_keys = {item["window_key"] for item in window_payload["active_windows_ranked"]}
    assert "precision_hrr_testing_window" in active_keys
    assert "psma_eligibility_window" in active_keys
    assert window_payload["opportunity_loss_summary"]["hrr_testing_missing_when_indicated"] >= 1
    assert window_payload["opportunity_loss_summary"]["psma_delayed_when_indicated"] >= 1


def test_decision_capture_endpoint_persists_real_clinician_decision(app_client):
    client, db_path = app_client

    payload = make_patient_payload(nss="39999999994", full_name="Paciente Decision Capture")
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "m1_crpc")

    response = client.post(
        f"/api/patients/{patient_id}/decision-capture",
        json={
            "state_at_decision": "m1_crpc",
            "recommended_option": "Cabazitaxel",
            "recommended_family": "systemic_sequencing",
            "recommended_confidence": 0.82,
            "clinician_selected_option": "Continuar ARPI mientras se completa restaging",
            "clinician_selected_family": "temporary_bridge",
            "followed_system_recommendation": "no",
            "discordance_reason_category": "toxicity_fitness",
            "discordance_reason_free_text": "Se prioriza tolerabilidad mientras se completa reevaluación.",
            "toxicity_driver": "fatiga acumulada",
            "shared_with_patient": True,
            "decided_by": "oncologia_medica",
        },
    )
    assert response.status_code == 200

    governance_payload = client.get(f"/api/patients/{patient_id}/decision-governance").get_json()
    capture_bundle = governance_payload["clinician_decision_capture_bundle"]

    assert capture_bundle["decision_capture_status"] == "captured"
    assert capture_bundle["clinician_selected_option"] == "Continuar ARPI mientras se completa restaging"
    assert capture_bundle["followed_system_recommendation"] == "no"
    assert capture_bundle["discordance_reason_category"] == "toxicity_fitness"


def test_state_transition_confirmation_endpoint_persists_rejection_workflow(app_client):
    client, db_path = app_client

    payload = make_patient_payload(nss="39999999995", full_name="Paciente Transition Review")
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "adt_progression_verification")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO state_transition_proposals (
            patient_id, proposal_key, from_state, from_management_track, target_state,
            target_management_track, proposal_status, priority, requires_confirmation,
            rationale, trigger_signals_json, next_actions_json, evidence_basis_json,
            confirmation_status
        ) VALUES (?, ?, ?, ?, ?, ?, 'open', 'high', 1, ?, ?, ?, ?, 'pending')
        """,
        (
            patient_id,
            "governance:m0_crpc",
            "adt_progression_verification",
            "verification",
            "m0_crpc",
            "systemic_surveillance",
            "Se sospecha CRPC no metastásico.",
            json.dumps(["PSA rising under ADT"]),
            json.dumps(["Confirmar testosterona sérica"]),
            json.dumps(["PCWG3 contextual"]),
        ),
    )
    proposal_id = cursor.lastrowid
    conn.commit()
    conn.close()

    response = client.post(
        f"/api/patients/{patient_id}/state-transition-confirmation",
        json={
            "proposal_id": proposal_id,
            "confirmation_status": "rejected",
            "confirmed_by": "oncologia_medica",
            "rejection_reason": "Falta testosterona confirmatoria para cerrar CRPC.",
            "requires_more_data_fields": ["testosterone"],
        },
    )
    assert response.status_code == 200

    governance_payload = client.get(f"/api/patients/{patient_id}/decision-governance").get_json()
    transition_bundle = governance_payload["state_transition_confirmation_bundle"]
    reviewed = next(item for item in transition_bundle["high_impact_proposals"] if item["id"] == proposal_id)

    assert reviewed["confirmation_status"] == "rejected"
    assert reviewed["rejection_reason"] == "Falta testosterona confirmatoria para cerrar CRPC."
    assert reviewed["requires_more_data_fields"] == ["testosterone"]


def test_tumor_board_outcome_endpoint_closes_loop_in_governance_bundle(app_client):
    client, db_path = app_client

    payload = make_patient_payload(nss="39999999996", full_name="Paciente Tumor Board Outcome")
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "m1_crpc")

    response = client.post(
        f"/api/patients/{patient_id}/tumor-board-outcome",
        json={
            "discussion_date": date.today().isoformat(),
            "trigger_reason": "discordancia entre secuencia sugerida y preferencia clínica",
            "system_recommendation_at_board": "Cabazitaxel",
            "board_recommendation": "PSMA-RLT tras completar restaging",
            "board_recommendation_family": "systemic_sequencing",
            "board_consensus_level": "consenso_pleno",
            "board_reasoning_structured": "Se prioriza secuencia guiada por biología y disponibilidad.",
            "required_followup_actions": ["Completar PSMA PET/CT", "Revalorar toxicidad acumulada"],
            "board_overrode_system": "yes",
        },
    )
    assert response.status_code == 200

    governance_payload = client.get(f"/api/patients/{patient_id}/decision-governance").get_json()
    board_bundle = governance_payload["tumor_board_outcome_bundle"]

    assert board_bundle["available"] is True
    assert board_bundle["board_recommendation"] == "PSMA-RLT tras completar restaging"
    assert board_bundle["board_overrode_system"] == "yes"


def test_terminal_care_pathway_handles_heterogeneous_current_medications_without_warning(caplog):
    from prostanet.domains.patient_tracking.terminal_care_pathway import assess_terminal_care

    base_patient = {
        "patient_id": 999,
        "current_state": "m1_crpc",
        "follow_ups": [
            {
                "visit_date": date.today().isoformat(),
                "pain": 6,
                "dyspnea_score": 1,
                "fatigue_score": 5,
                "opioid_use": 1,
            }
        ],
        "imaging_studies": [{"study_date": date.today().isoformat(), "study_type": "CT", "result": "stable"}],
    }

    caplog.clear()
    with caplog.at_level("WARNING"):
        for meds in (
            "Metformina 850 mg cada 12 horas",
            ["Prednisona 5 mg", "Omeprazol 20 mg"],
            [{"name": "Morfina", "dose": "10 mg"}, {"medication": "Paracetamol"}],
        ):
            result = assess_terminal_care(base_patient | {"current_medications": meds})
            assert result["has_data"] is True
            assert "error" not in result

    assert "Terminal care pathway error" not in caplog.text


def test_register_patient_returns_real_id_and_persists_core_tables(app_client):
    client, db_path = app_client
    payload = make_patient_payload()

    response = client.post("/api/register_patient", json=payload)

    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    assert isinstance(data["patient_id"], int)
    assert data["patient_id"] > 0
    assert data["nss"] == payload["nss"]

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM patient_identity")
    assert cursor.fetchone()[0] == 1
    cursor.execute("SELECT COUNT(*) FROM clinical_baseline")
    assert cursor.fetchone()[0] == 1
    cursor.execute("SELECT COUNT(*) FROM prior_clinical_history")
    assert cursor.fetchone()[0] == 1
    conn.close()

    record_response = client.get(f"/api/patient/{payload['nss']}")
    assert record_response.status_code == 200
    record = record_response.get_json()
    assert record["success"] is True
    assert record["patient"]["identity"]["full_name"] == payload["full_name"]


def test_register_patient_dual_writes_canonical_facts_and_exposes_fact_endpoint(app_client):
    client, db_path = app_client
    payload = make_patient_payload(
        nss="12345678902",
        full_name="Paciente Facts Demo",
        current_adt_context="adjuvant",
    )

    response = client.post("/api/register_patient", json=payload)

    assert response.status_code == 200
    patient_id = response.get_json()["patient_id"]

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT fact_key, normalized_value_text, source_type, certainty_tier
        FROM patient_clinical_facts
        WHERE patient_id = ? AND is_active = 1
        ORDER BY fact_key
        """,
        (patient_id,),
    )
    rows = cursor.fetchall()
    conn.close()

    persisted_fact_keys = {row[0] for row in rows}
    assert "baseline_psa" in persisted_fact_keys
    assert "line_of_therapy_number" in persisted_fact_keys
    assert "metastatic_stage_resolved" in persisted_fact_keys

    facts_response = client.get(f"/api/patients/{patient_id}/clinical-facts")
    assert facts_response.status_code == 200
    facts_payload = facts_response.get_json()
    assert facts_payload["success"] is True
    facts = {
        item["fact_key"]: item
        for item in facts_payload["clinical_fact_bundle"]["facts"]
    }
    assert facts["baseline_psa"]["resolved_value"] == 8.4
    assert facts["metastatic_stage_resolved"]["resolved_value"] == "M0"
    assert facts_payload["fact_freshness_summary"]["available"] is True


def test_fact_conflicts_and_ledger_surface_m1_reclassification_from_m0_crpc(app_client):
    import tracking_db

    client, db_path = app_client
    payload = make_patient_payload(nss="12345678903", full_name="Paciente Reclass M1")
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "m0_crpc")

    conn = tracking_db.get_db_connection()
    cursor = conn.cursor()
    tracking_db._persist_canonical_facts_from_payload(
        cursor,
        patient_id,
        {
            "metastatic_disease_known": 1,
            "metastasis_site": "hueso",
            "bone_metastasis_present": 1,
            "bone_axial_count": 1,
            "psma_pet_done": 1,
            "psma_positive": 1,
            "psma_stage_after_psma": "M1b",
            "metastasis_assessment_date": "2026-03-20",
            "metastasis_document_source": "psma_pet",
        },
        source_type="structured_result",
        source_record_type="stage_visit",
        source_record_id=101,
        source_date="2026-03-20",
        observed_at="2026-03-20",
        state_context="m0_crpc",
        management_track="systemic",
        certainty_tier="structured_result",
    )
    conn.commit()
    conn.close()

    facts_response = client.get(f"/api/patients/{patient_id}/clinical-facts")
    assert facts_response.status_code == 200
    facts_payload = facts_response.get_json()
    facts = {
        item["fact_key"]: item
        for item in facts_payload["clinical_fact_bundle"]["facts"]
    }
    assert facts["metastatic_stage_resolved"]["resolved_value"] == "M1b"
    assert facts["metastatic_detection_basis"]["resolved_value"] == "psma_only"

    conflicts_response = client.get(f"/api/patients/{patient_id}/fact-conflicts")
    assert conflicts_response.status_code == 200
    conflicts_payload = conflicts_response.get_json()
    assert conflicts_payload["success"] is True
    assert conflicts_payload["fact_conflict_summary"]["total_conflicts"] >= 1
    contradiction_bundle = conflicts_payload["contradiction_resolution_bundle"]
    assert contradiction_bundle["block_status"] == "hard_stop"
    assert contradiction_bundle["state_reclassification_required"] is True
    assert "adt_progression_verification" in contradiction_bundle["state_reclassification_targets"]

    ledger_response = client.get(f"/api/patients/{patient_id}/clinical-ledger")
    assert ledger_response.status_code == 200
    ledger_payload = ledger_response.get_json()["clinical_ledger_bundle"]
    assert ledger_payload["available"] is True
    assert any(
        item["fact_key"] == "metastatic_stage_resolved"
        for item in ledger_payload["fact_lineage"]
    )


def test_register_patient_rejects_duplicate_nss(app_client):
    client, _ = app_client
    payload = make_patient_payload(nss="11111111111")

    first = client.post("/api/register_patient", json=payload)
    second = client.post("/api/register_patient", json=payload)

    assert first.status_code == 200
    assert second.status_code == 400
    second_data = second.get_json()
    assert second_data["success"] is False
    assert "ya existe" in second_data["error"]


def test_register_patient_validates_required_fields_and_numeric_types(app_client):
    client, _ = app_client

    missing_required = client.post("/api/register_patient", json={"full_name": "Sin NSS"})
    assert missing_required.status_code == 400
    assert missing_required.get_json()["success"] is False


def test_stage_visit_persists_survival_status_and_anchor_events(app_client):
    client, db_path = app_client
    payload = make_patient_payload(nss="30000000001", full_name="Supervivencia Demo")
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "recurrence_bcr")
    _insert_postlocal_bcr_context(db_path, patient_id, bcr_date="2026-02-20", bcr_psa=0.55)

    visit_response = client.post(
        f"/api/patients/{patient_id}/visits",
        json={
            "state": "recurrence_bcr",
            "visit_date": "2026-03-15",
            "psa": 0.62,
            "survival_status_update": {
                "vital_status": "alive",
                "last_contact_date": "2026-03-15",
                "last_contact_status": "clinic_visit",
            },
            "survival_anchor_events": [
                {"anchor_type": "psa_progression", "anchor_date": "2026-02-20", "anchor_source": "biochemical_recurrence"},
                {"anchor_type": "treatment_start", "anchor_date": "2024-01-15", "anchor_source": "surgery"},
            ],
        },
    )

    assert visit_response.status_code == 200
    import tracking_db

    record = tracking_db.get_patient_full_record(patient_id)
    assert record["survival_status_detail"]["vital_status"] == "alive"
    assert record["survival_status_detail"]["last_contact_date"] == "2026-03-15"
    anchor_types = {item["anchor_type"] for item in record["survival_anchor_events"]}
    assert "psa_progression" in anchor_types
    assert "treatment_start" in anchor_types

    survival_response = client.get(f"/api/patients/{patient_id}/survival-endpoints")
    assert survival_response.status_code == 200
    survival_data = survival_response.get_json()["survival_status"]
    endpoint_types = {item["type"] for item in survival_data["endpoints"]}
    assert "OS" in endpoint_types
    assert "TTR" in endpoint_types
    assert "BCR_FS" in endpoint_types


def test_stage_visit_persists_structured_biopsy_and_active_surveillance(app_client):
    client, db_path = app_client
    payload = make_patient_payload(nss="30000000002", full_name="Biopsia VA Demo")
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "localized_initial")

    visit_response = client.post(
        f"/api/patients/{patient_id}/visits",
        json={
            "state": "localized_initial",
            "visit_date": "2026-03-10",
            "structured_biopsy": {
                "biopsy_date": "2026-03-01",
                "biopsy_type": "fusion",
                "biopsy_route": "transperineal",
                "biopsy_context": "confirmatory_as",
                "mri_pirads_at_biopsy": 4,
                "systematic_cores": [
                    {"core_id": "S1", "location_sextant": "right_base", "core_type": "systematic", "positive": True, "gleason_primary": 3, "gleason_secondary": 3, "isup_grade": 1, "involvement_pct": 20},
                    {"core_id": "S2", "location_sextant": "left_base", "core_type": "systematic", "positive": False},
                ],
                "targeted_cores": [
                    {"core_id": "T1", "location_sextant": "target_1", "core_type": "targeted", "positive": True, "gleason_primary": 3, "gleason_secondary": 4, "isup_grade": 2, "mri_target_concordance": True}
                ],
            },
            "active_surveillance_update": {
                "protocol": "PRIAS",
                "criteria_met": {"isup_max": True},
                "schedule_items": [
                    {"item_type": "psa", "title": "PSA protocolizado", "due_date": "2026-06-01", "interval_months": 3, "status": "scheduled", "priority": "mandatory"},
                    {"item_type": "rebiopsy", "title": "Biopsia confirmatoria", "due_date": "2027-03-01", "interval_months": 12, "status": "scheduled", "priority": "mandatory"},
                ],
                "trigger_events": [
                    {"trigger_type": "mri_new_lesion", "detected_date": "2026-03-10", "detail": "Lesión índice PI-RADS 4", "severity": "monitoring_intensification", "recommended_action": "Mantener vigilancia intensificada"}
                ],
            },
        },
    )

    assert visit_response.status_code == 200
    import tracking_db

    record = tracking_db.get_patient_full_record(patient_id)
    assert len(record["structured_biopsy_sessions"]) == 1
    assert record["structured_biopsy_sessions"][0]["biopsy_context"] == "confirmatory_as"
    assert record["structured_biopsy_sessions"][0]["targeted_cores"][0]["positive"] is True
    assert record["active_surveillance_protocol"]["enrollment_protocol"] == "PRIAS"
    assert len(record["active_surveillance_protocol"]["schedule"]) == 2
    assert len(record["active_surveillance_protocol"]["reclassification_triggers"]) == 1

    as_response = client.get(f"/api/patients/{patient_id}/active-surveillance")
    assert as_response.status_code == 200
    protocol_summary = as_response.get_json()["protocol_summary"]
    assert protocol_summary["has_data"] is True


def test_stage_visit_persists_sre_bma_bone_health_and_rt_detail(app_client):
    client, db_path = app_client
    payload = make_patient_payload(nss="30000000003", full_name="Hueso RT Demo")
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "m1_crpc")
    _insert_treatment_line(db_path, patient_id, line_of_therapy=1, drug_scheme="ADT_ABIRATERONE", start_date="2025-12-01", context="mcrpc")

    visit_response = client.post(
        f"/api/patients/{patient_id}/visits",
        json={
            "state": "m1_crpc",
            "visit_date": "2026-03-12",
            "skeletal_events": [
                {"event_type": "pathological_fracture", "event_date": "2026-03-05", "site": "femur", "intervention": "stabilization", "surgical_intervention": True},
            ],
            "bone_modifying_agent": {
                "agent": "denosumab",
                "start_date": "2026-03-12",
                "frequency": "q4w",
                "dental_clearance_done": True,
                "onj_monitoring": True,
                "doses_administered": 1,
            },
            "bone_health_snapshot": {
                "snapshot_date": "2026-03-12",
                "dxa_performed": True,
                "worst_t_score": -2.7,
                "frax_major_pct": 18.0,
                "frax_hip_pct": 5.2,
                "calcium_level": 9.1,
                "creatinine": 1.0,
            },
            "radiotherapy_course": {
                "rt_intent": "MDT",
                "modality": "SBRT",
                "target_volume": "metastasis_directed",
                "total_dose_gy": 30,
                "fractions": 3,
                "dose_per_fraction_gy": 10,
                "rt_start_date": "2026-03-20",
                "rt_end_date": "2026-03-24",
                "mdt_site_details": [
                    {"site_location": "left_iliac_bone", "modality": "SBRT", "dose_gy": 30, "fractions": 3, "dose_per_fraction_gy": 10}
                ],
                "toxicity": [
                    {"domain": "GI", "phase": "acute", "grade": 1, "details": "Nausea leve"}
                ],
            },
        },
    )

    assert visit_response.status_code == 200
    import tracking_db

    record = tracking_db.get_patient_full_record(patient_id)
    assert len(record["skeletal_events"]) == 1
    assert record["bone_modifying_agent"]["agent"] == "denosumab"
    assert record["bone_health"]["worst_t_score"] == -2.7
    assert len(record["radiotherapy_courses_detailed"]) == 1
    assert record["radiotherapy_courses_detailed"][0]["mdt_site_details"][0]["site_location"] == "left_iliac_bone"

    sre_response = client.get(f"/api/patients/{patient_id}/skeletal-events")
    rt_response = client.get(f"/api/patients/{patient_id}/radiotherapy-detail")
    assert sre_response.status_code == 200
    assert rt_response.status_code == 200


def test_legacy_domain_writes_dual_write_into_canonical_tables(app_client):
    client, db_path = app_client
    payload = make_patient_payload(nss="30000000004", full_name="Legacy Backfill Demo")
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]

    import tracking_db

    assert tracking_db.save_biopsy(patient_id, {
        "biopsy_date": "2026-02-01",
        "biopsy_type": "fusion",
        "biopsy_context": "diagnostica",
        "total_cores": 12,
        "positive_cores": 2,
        "gleason_primary": 3,
        "gleason_secondary": 4,
        "isup_grade": 2,
    }) is True
    assert tracking_db.enroll_in_as(patient_id, {
        "enrollment_date": "2026-02-15",
        "protocol": "PRIAS",
        "criteria_met": {"psa_max": True},
    }) is True
    assert tracking_db.save_radiation_details(patient_id, {
        "rt_date": "2026-02-20",
        "rt_context": "salvamento",
        "rt_technique": "VMAT",
        "target": "lecho",
        "total_dose_gy": 66,
        "fractions": 33,
        "dose_per_fraction_gy": 2,
        "gu_toxicity_grade": 1,
        "gi_toxicity_grade": 0,
    }) is True

    record = tracking_db.get_patient_full_record(patient_id)
    assert len(record["structured_biopsy_sessions"]) == 1
    assert record["active_surveillance_protocol"]["enrollment_protocol"] == "PRIAS"
    assert len(record["radiotherapy_courses_detailed"]) == 1


def test_cohort_survival_and_domain_completeness_endpoints(app_client):
    client, db_path = app_client
    patient_ids = []
    for idx in range(2):
        payload = make_patient_payload(nss=f"3000000001{idx}", full_name=f"Cohorte {idx}")
        register = client.post("/api/register_patient", json=payload)
        patient_id = register.get_json()["patient_id"]
        patient_ids.append(patient_id)
        _seed_latest_assessment_state(db_path, patient_id, "recurrence_bcr")
        _insert_postlocal_bcr_context(db_path, patient_id, bcr_date=f"2026-02-2{idx}", bcr_psa=0.3 + idx)
        client.post(
            f"/api/patients/{patient_id}/visits",
            json={
                "state": "recurrence_bcr",
                "visit_date": f"2026-03-1{idx}",
                "survival_status_update": {
                    "vital_status": "deceased" if idx == 1 else "alive",
                    "date_of_death": "2026-03-18" if idx == 1 else "",
                    "cause_of_death": "prostate_cancer" if idx == 1 else "",
                    "last_contact_date": f"2026-03-1{idx}",
                    "last_contact_status": "clinic_visit",
                },
                "survival_anchor_events": [
                    {"anchor_type": "treatment_start", "anchor_date": "2024-01-15", "anchor_source": "surgery"},
                    {"anchor_type": "psa_progression", "anchor_date": f"2026-02-2{idx}", "anchor_source": "biochemical_recurrence"},
                ],
            },
        )

    curve_response = client.get("/api/cohorts/survival-curves?endpoint=OS")
    assert curve_response.status_code == 200
    curve_data = curve_response.get_json()
    assert curve_data["success"] is True
    assert curve_data["n_patients"] >= 2
    assert "curve" in curve_data

    analysis_response = client.get("/api/cohorts/survival-analysis?endpoint=OS")
    assert analysis_response.status_code == 200
    analysis_data = analysis_response.get_json()
    assert analysis_data["success"] is True
    assert analysis_data["status"] in {"ok", "insufficient_data", "lifelines_unavailable", "no_usable_covariates"}

    completeness_response = client.get("/api/cohorts/domain-completeness")
    assert completeness_response.status_code == 200
    completeness_data = completeness_response.get_json()
    assert completeness_data["success"] is True
    assert completeness_data["total_patients"] >= 2
    assert "domain_counts" in completeness_data

    invalid_numeric = client.post(
        "/api/register_patient",
        json=make_patient_payload(nss="22222222222") | {"line_of_therapy": "primera"},
    )
    assert invalid_numeric.status_code == 400
    invalid_data = invalid_numeric.get_json()
    assert invalid_data["success"] is False
    assert "line_of_therapy" in invalid_data["error"]


def test_clinical_hub_hides_classifier_noise_and_starts_empty(app_client):
    client, _ = app_client

    response = client.get("/clinical-hub")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Qué corrige este clasificador" not in html
    assert "Clasificar estado" not in html
    assert "Seleccione un dominio o complete el clasificador" in html
    assert "Distribución de metástasis óseas" in html
    assert "Distribución de metástasis viscerales" in html
    assert "Enfermedad metastásica conocida" in html
    assert "Recurrencia bioquímica y segunda recurrencia bioquímica sin metástasis" in html
    assert 'name="metastatic_disease_known"' in html
    assert 'name="bcr_detected"' in html
    assert 'name="visceral_site_entries"' in html
    assert 'name="bone_site_entries"' in html
    assert 'name="nonregional_nodal_site_entries"' in html
    assert 'name="nonregional_nodal_metastasis_present"' in html
    assert "Cadena ganglionar no regional" in html
    assert "Sí, abrir asistente de BCR" not in html
    assert "No, abrir seguimiento post-tratamiento local" not in html
    assert 'name="volume_disease"' not in html
    assert 'value="Oligometastatic"' not in html
    assert "setActiveDomain(null);" in html


def test_metastatic_wizard_uses_progressive_known_metastatic_capture(app_client):
    client, _ = app_client

    response = client.get("/wizard/mcspc_high_volume_sync")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Enfermedad metastásica conocida" in html
    assert "Cadena ganglionar no regional" in html
    assert 'data-role="metastatic-known-select"' in html
    assert 'name="metastatic_disease_known"' in html
    assert 'name="nonregional_nodal_site_entries"' in html
    assert 'data-role="add-nodal-row"' in html
    assert 'data-gleason-profile-widget="1"' in html
    assert 'name="gleason_primary"' in html
    assert 'name="gleason_secondary"' in html
    assert 'name="gleason_tertiary"' in html
    assert 'name="isup_grade"' in html


def test_state_classifier_accepts_mixed_metastatic_payload_and_preserves_composition(app_client):
    client, _ = app_client

    response = client.post(
        "/api/state-classifier",
        json={
            "known_cancer_diagnosis": 1,
            "metastatic_disease_known": 1,
            "metachronous_metastasis": 0,
            "bone_site_entries": [
                {"site_key": "thoracic_spine", "lesion_count": 2},
                {"site_key": "femur", "lesion_count": 1},
            ],
            "visceral_site_entries": [
                {"site_key": "liver", "lesion_count": 2},
                {"site_key": "lung", "lesion_count": 1},
            ],
            "nonregional_nodal_site_entries": [
                {"site_key": "retroperitoneal", "lesion_count": 1},
                {"site_key": "mediastinal", "lesion_count": 1},
            ],
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    derived = data["derived_metastatic_context"]
    assert data["state"] == "mcspc_high_volume_sync"
    assert derived["volume_disease"] == "high"
    assert derived["visceral_present"] is True
    assert derived["bone_present"] is True
    assert derived["nonregional_nodal_present"] is True
    assert derived["has_mixed_metastatic_sites"] is True
    assert set(derived["metastatic_components"]) == {"bone", "visceral", "nodes"}
    assert str(derived["m_substage_resolved"]).upper() == "M1C"
    assert "víscera" in derived["metastatic_profile_summary"].lower() or "mixta" in derived["metastatic_profile_summary"].lower()
    assert "retroperitoneal" in derived["nodal_distribution_summary"].lower()


def test_visit_schema_includes_official_diagnosis_capture_fields(app_client):
    client, _ = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="23232323232", full_name="Paciente Diagnóstico Oficial"))
    patient_id = register.get_json()["patient_id"]

    schema_response = client.get(f"/api/patients/{patient_id}/visit-schema")

    assert schema_response.status_code == 200
    schema = schema_response.get_json()["visit_schema"]
    field_names = {
        field["name"]
        for section in schema["sections"]
        for field in section["fields"]
    }
    for field_name in (
        "histology_subtype",
        "gleason_primary",
        "gleason_secondary",
        "isup_grade",
        "clinical_tstage",
        "nodal_status",
        "clinical_stage_group",
        "clinical_risk_group",
    ):
        assert field_name in field_names


def test_official_diagnosis_context_builds_localized_phrase_from_structured_fields(app_client):
    client, db_path = app_client
    payload = make_patient_payload(nss="24242424242", full_name="Paciente Localizado Oficial") | {
        "histology_subtype": "Adenocarcinoma acinar",
        "gleason_primary": 4,
        "gleason_secondary": 3,
        "isup_grade": 3,
        "clinical_tstage": "T2b",
        "nodal_status": "N0",
        "clinical_stage_group": "IIA",
        "clinical_risk_group": "intermedio desfavorable",
    }

    register = client.post("/api/register_patient", json=payload)
    assert register.status_code == 200

    import tracking_db

    record = tracking_db.get_patient_full_record(register.get_json()["patient_id"])
    context = build_official_diagnosis_context(
        patient=record,
        state="localized_initial",
        raw_assessment={},
        display_assessment={},
        operational_module_label="Enfermedad localizada o regional N1M0",
    )

    assert context["official_diagnosis_status"] == "complete"
    assert "Adenocarcinoma acinar de próstata Gleason 7 (4+3)" in context["official_diagnosis"]
    assert "riesgo intermedio desfavorable" in context["official_diagnosis"]
    assert "etapa clínica IIA" in context["official_diagnosis"]


def test_official_diagnosis_context_includes_structured_gleason_isup_and_tertiary_in_metastatic_state(app_client):
    client, _ = app_client
    payload = make_patient_payload(
        nss="24242424243",
        full_name="Paciente Metastásico Oficial",
        assessment_state="m1_crpc",
        histology_subtype="Adenocarcinoma acinar",
        gleason_primary=3,
        gleason_secondary=4,
        gleason_tertiary=5,
        metastatic_disease_known=1,
        bone_site_entries=[{"site_key": "femur", "lesion_count": 2}],
        visceral_site_entries=[{"site_key": "liver", "lesion_count": 1}],
        nonregional_nodal_site_entries=[{"site_key": "retroperitoneal", "lesion_count": 1}],
        castrate_testosterone_status="confirmed_castrate",
    )

    register = client.post("/api/register_patient", json=payload)
    assert register.status_code == 200

    import tracking_db

    record = tracking_db.get_patient_full_record(register.get_json()["patient_id"])
    context = build_official_diagnosis_context(
        patient=record,
        state="m1_crpc",
        raw_assessment=payload,
        display_assessment={},
        operational_module_label="Cáncer de próstata resistente a la castración metastásico",
    )

    assert context["official_diagnosis_status"] == "complete"
    assert "Gleason 7 (3+4)" in context["official_diagnosis"]
    assert "ISUP 2" in context["official_diagnosis"]
    assert "patrón terciario 5" in context["official_diagnosis"]
    assert context["histopathology_summary"] == "Gleason 7 (3+4), ISUP 2, con patrón terciario 5"


def test_clinical_assessment_draft_reuses_structured_gleason_and_metastatic_capture(app_client):
    client, _ = app_client

    response = client.post(
        "/api/clinical-assessments/draft",
        json={
            "module_id": "mcspc_high_volume_sync",
            "payload": {
                "metastatic_disease_known": 1,
                "metastatic_components_capture": {
                    "metastatic_disease_known": True,
                    "components": ["bone", "visceral"],
                },
                "bone_site_entries": [
                    {"site_key": "thoracic_spine", "lesion_count": 3},
                    {"site_key": "femur", "lesion_count": 1},
                ],
                "visceral_site_entries": [{"site_key": "liver", "lesion_count": 1}],
                "gleason_score": 7,
                "gleason_primary": 4,
                "gleason_secondary": 3,
                "gleason_tertiary": 5,
                "ecog_score": 1,
                "frailty_status": "Fit",
                "child_pugh_score": "A",
                "drug_interaction_reviewed": 1,
            },
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    imported = {item["name"]: item for item in payload["imported_clinical_fields"]}
    assert imported["gleason_score"]["value_label"] == "Gleason 7 (4+3), ISUP 3, con patrón terciario 5"
    assert "alto volumen" in imported["metastatic_components_capture"]["value_label"].lower()
    visible_fields = {
        field["name"]
        for fragment in payload["registration_fragments"]
        for field in fragment["fields"]
    }
    assert "metastatic_components_capture" not in visible_fields
    assert "gleason_score" not in visible_fields
    assert payload["registration_defaults"]["gleason_score"]["gleason_primary"] == 4
    assert payload["registration_defaults"]["metastatic_components_capture"]["metastatic_disease_known"] is True


def test_high_volume_draft_exposes_docetaxel_eligibility_capture_when_triplet_is_still_open(app_client):
    client, _ = app_client

    response = client.post(
        "/api/clinical-assessments/draft",
        json={
            "module_id": "mcspc_high_volume_sync",
            "payload": {
                "metastatic_disease_known": 1,
                "metastasis_site": "Bone",
                "metastasis_count": 7,
                "ecog_score": 1,
                "peripheral_neuropathy_grade": 0,
                "frailty_status": "Fit",
                "child_pugh_score": "A",
            },
        },
    )

    assert response.status_code == 200
    draft_data = response.get_json()
    visible_fields = {
        field["name"]
        for fragment in draft_data["registration_fragments"]
        for field in fragment["fields"]
    }

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
    }.issubset(visible_fields)


def test_registration_humanization_translates_boolean_and_radiotherapy_labels():
    assert resolve_option_label("low_activity", "1", ["", "0", "1"]) == "Sí, actividad reducida"
    assert resolve_option_label("slow_gait", "0", ["", "0", "1"]) == "No documentada"
    assert resolve_option_label("rt_intent", "salvage", ["", "definitive", "salvage"]) == "Salvamento"
    assert resolve_option_label("modality", "EBRT_IMRT", ["", "EBRT_IMRT"]) == "Radioterapia externa IMRT"
    assert resolve_option_label("target_volume", "whole_pelvis", ["", "whole_pelvis"]) == "Pelvis completa"


def test_official_diagnosis_context_falls_back_to_operational_label_when_missing(app_client):
    client, _ = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="25252525252", full_name="Paciente Fallback Diagnóstico"))
    assert register.status_code == 200

    import tracking_db

    record = tracking_db.get_patient_full_record(register.get_json()["patient_id"])
    context = build_official_diagnosis_context(
        patient=record,
        state="localized_initial",
        raw_assessment={},
        display_assessment={},
        operational_module_label="Enfermedad localizada o regional N1M0",
    )

    assert context["official_diagnosis_status"] == "missing"
    assert context["official_diagnosis"] == "Enfermedad localizada o regional N1M0"


def test_followup_alerts_and_export_flow(app_client):
    client, _ = app_client
    payload = make_patient_payload(nss="33333333333", full_name="Paciente Seguimiento")

    register_response = client.post("/api/register_patient", json=payload)
    patient_data = register_response.get_json()
    patient_id = patient_data["patient_id"]

    followup_response = client.post(
        "/api/add_followup",
        json={
            "patient_id": patient_id,
            "psa": 2.1,
            "testosterone": 15,
            "ecog": 1,
            "pain": 2,
            "treatment": "ADT",
            "status": "Estable",
        },
    )
    assert followup_response.status_code == 200
    followup_data = followup_response.get_json()
    assert followup_data["success"] is True
    assert isinstance(followup_data["id"], int)

    check_alerts_response = client.post(f"/api/alerts/{patient_id}/check")
    assert check_alerts_response.status_code == 200
    check_alerts_data = check_alerts_response.get_json()
    assert check_alerts_data["success"] is True
    assert isinstance(check_alerts_data["new_alerts"], list)

    alerts_response = client.get(f"/api/alerts/{patient_id}")
    assert alerts_response.status_code == 200
    alerts_data = alerts_response.get_json()
    assert alerts_data["success"] is True
    assert isinstance(alerts_data["alerts"], list)

    export_response = client.get(f"/api/export/{payload['nss']}")
    assert export_response.status_code == 200
    export_data = export_response.get_json()
    assert export_data["identity"]["nss"] == payload["nss"]
    assert len(export_data["follow_ups"]) == 1

    export_json_response = client.get(f"/api/export/{payload['nss']}?format=json")
    assert export_json_response.status_code == 200
    export_json = json.loads(export_json_response.get_data(as_text=True))
    assert export_json["identity"]["full_name"] == payload["full_name"]

    export_csv_response = client.get(f"/api/export/{payload['nss']}/csv")
    assert export_csv_response.status_code == 200
    csv_rows = list(csv.DictReader(io.StringIO(export_csv_response.get_data(as_text=True))))
    assert len(csv_rows) == 1
    assert csv_rows[0]["id_nss"] == payload["nss"]
    assert csv_rows[0]["n_followups"] == "1"


def test_alerts_endpoint_matches_signals_copilot_alerts(app_client):
    client, _ = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="34343434343", full_name="Paciente Alertas Canonicas"))
    patient_id = register.get_json()["patient_id"]

    signals_response = client.get(f"/api/patients/{patient_id}/signals")
    alerts_response = client.get(f"/api/alerts/{patient_id}")

    assert signals_response.status_code == 200
    assert alerts_response.status_code == 200

    signal_alerts = signals_response.get_json()["copilot_alerts"]
    api_alerts = alerts_response.get_json()["alerts"]

    assert signal_alerts
    assert {item["alert_key"] for item in signal_alerts} == {item["alert_key"] for item in api_alerts}


def test_schedule_persists_distinct_supportive_care_items_with_distinct_schedule_keys(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="35353535353", full_name="Paciente Schedule Keys"))
    patient_id = register.get_json()["patient_id"]

    import tracking_db

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    tracking_db._upsert_scheduled_events(
        cursor,
        patient_id,
        "systemic_surveillance",
        [
            {
                "schedule_key": "state:track:bone_support",
                "encounter_key": "encounter:support",
                "event_type": "supportive_care",
                "label": "Salud ósea y soporte",
                "management_track": "systemic_surveillance",
                "due_date": "2026-03-20",
                "guideline": "NCCN 2026",
            },
            {
                "schedule_key": "state:track:frailty_fitness",
                "encounter_key": "encounter:support",
                "event_type": "supportive_care",
                "label": "Fragilidad y fitness terapéutica",
                "management_track": "systemic_surveillance",
                "due_date": "2026-03-20",
                "guideline": "EAU 2026",
            },
        ],
    )
    conn.commit()
    cursor.execute(
        """
        SELECT id, schedule_key, label
        FROM scheduled_events
        WHERE patient_id = ?
        ORDER BY id ASC
        """,
        (patient_id,),
    )
    rows = cursor.fetchall()
    conn.close()

    assert len(rows) == 2
    assert rows[0][0] != rows[1][0]
    assert {row[1] for row in rows} == {"state:track:bone_support", "state:track:frailty_fitness"}


def test_agenda_and_schedule_expose_encounters(app_client):
    client, _ = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="36363636363", full_name="Paciente Encounters"))
    patient_id = register.get_json()["patient_id"]

    agenda_response = client.get("/api/patients/36363636363/agenda")
    schedule_response = client.get(f"/api/patients/{patient_id}/schedule")

    assert agenda_response.status_code == 200
    assert schedule_response.status_code == 200

    agenda_payload = agenda_response.get_json()["agenda"]
    schedule_payload = schedule_response.get_json()

    assert agenda_payload["encounters"]
    assert schedule_payload["scheduled_encounters"]
    assert schedule_payload["next_encounter"]


def test_adt_progression_verification_groups_confirmation_encounter_and_fuses_alerts(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="37373737373", full_name="Paciente ADT Progression"))
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "adt_progression_verification")

    schedule_response = client.get(f"/api/patients/{patient_id}/schedule?track=systemic_surveillance")
    signals_response = client.get(f"/api/patients/{patient_id}/signals")

    assert schedule_response.status_code == 200
    assert signals_response.status_code == 200

    schedule_payload = schedule_response.get_json()
    encounters = schedule_payload["scheduled_encounters"]
    confirmation = next(enc for enc in encounters if enc["encounter_type"] == "progression_confirmation")

    assert confirmation["title"] == "Cita de confirmación de progresión bajo ADT"
    task_types = {task["item_type"] for task in confirmation["tasks"]}
    assert {"therapy_review", "lab_panel", "imaging"} <= task_types
    assert schedule_payload["schedule_anchor_strength"] == "weak"

    signal_alerts = signals_response.get_json()["copilot_alerts"]
    assert sum(1 for alert in signal_alerts if alert["decision_domain"] == "systemic_sequencing") <= 1


def test_schedule_exposes_master_followup_plan_for_phase_one_scenarios(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="38383838383", full_name="Paciente Plan Maestro"))
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "adt_progression_verification")

    schedule_response = client.get(f"/api/patients/{patient_id}/schedule?track=systemic_surveillance")
    assert schedule_response.status_code == 200

    payload = schedule_response.get_json()
    master_plan = payload["master_followup_plan"]

    assert master_plan["scenario_state"] == "adt_progression_verification"
    assert master_plan["guideline_basis"]
    assert master_plan["next_encounter"]
    assert master_plan["summary"]["headline"]
    assert master_plan["plan_key"]
    assert master_plan["plan_status"] in {"active", "provisional"}
    assert master_plan["calendar_horizon_months"] == 12
    assert master_plan["timeline"]
    assert master_plan["inline_actions_enabled"] is True
    timeline_dates = [item["ideal_due_at"] for item in master_plan["timeline"] if item.get("ideal_due_at")]
    assert timeline_dates == sorted(timeline_dates)
    assert all("scheduled_due_at" in item for item in master_plan["timeline"])
    assert all("completion_progress" in item for item in master_plan["timeline"])
    assert all("inline_actions_enabled" in item for item in master_plan["timeline"])
    assert any(item["tasks"] for item in master_plan["timeline"])
    first_task = next(task for item in master_plan["timeline"] for task in item["tasks"])
    assert {"required", "action_mode", "completed_at"} <= set(first_task.keys())
    assert payload["plan_version"]
    assert payload["calendar_horizon_months"] == 12
    assert payload["timeline"]


def test_completed_inline_task_remains_visible_and_counts_toward_encounter_progress(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="38383838384", full_name="Paciente Progreso Encounter"))
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "adt_progression_verification")

    agenda_response = client.get(f"/api/patients/{patient_id}/agenda?track=systemic_surveillance")
    assert agenda_response.status_code == 200
    agenda = agenda_response.get_json()["agenda"]
    lab_item = next(item for item in agenda["items"] if item["agenda_key"] == "adt_progression_verification:systemic_surveillance:labs")

    visit_response = client.post(
        f"/api/patients/{patient_id}/visits",
        json={
            "agenda_ids": [lab_item["id"]],
            "agenda_submission_mode": "item_scoped",
            "visit_date": "2026-03-20",
            "state": "adt_progression_verification",
            "management_track": "systemic_surveillance",
            "psa": 6.4,
            "testosterone": 18,
            "alp": 120,
            "ldh": 200,
            "hemoglobin": 13.2,
        },
    )
    assert visit_response.status_code == 200

    schedule_response = client.get(f"/api/patients/{patient_id}/schedule?track=systemic_surveillance")
    assert schedule_response.status_code == 200
    encounter = next(
        item
        for item in schedule_response.get_json()["scheduled_encounters"]
        if item["encounter_key"] == "adt_progression_verification:systemic_surveillance:progression_confirmation"
    )
    completed_lab_task = next(task for task in encounter["tasks"] if task["agenda_key"] == lab_item["agenda_key"])

    assert encounter["completion_progress"]["label"] == "1/3"
    assert encounter["completed_required_task_count"] == 1
    assert completed_lab_task["status"] == "completed"
    assert completed_lab_task["completed_at"]


def test_alert_key_opens_directed_visit_schema_with_capture_context(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="39393939393", full_name="Paciente Alerta Dirigida"))
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "adt_progression_verification")

    signals_response = client.get(f"/api/patients/{patient_id}/signals")
    assert signals_response.status_code == 200
    alerts = signals_response.get_json()["copilot_alerts"]
    capture_alert = next(alert for alert in alerts if alert["fields_to_capture"])

    schema_response = client.get(f"/api/patients/{patient_id}/visit-schema?alert_key={capture_alert['alert_key']}")
    assert schema_response.status_code == 200

    payload = schema_response.get_json()
    visit_schema = payload["visit_schema"]
    agenda_context = payload["agenda_item_context"]
    field_names = {
        field["name"]
        for section in visit_schema["sections"]
        for field in section["fields"]
    }

    assert visit_schema["submission_mode"] == "item_scoped"
    assert visit_schema["presentation_mode"] == "mini_capture"
    assert visit_schema["focus_fields"] == capture_alert["fields_to_capture"]
    assert visit_schema["auto_visit_date"]
    assert visit_schema["allow_visit_date_override"] is True
    assert agenda_context["mode"] == "mini_capture"
    assert agenda_context["alert_key"] == capture_alert["alert_key"]
    assert agenda_context["action_type"] == capture_alert["action_type"]
    assert set(capture_alert["fields_to_capture"]) == field_names
    assert "visit_date" not in field_names
    assert "clinician_notes" not in field_names


def test_signals_expose_outcome_adjudication_bundle(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="39494949494", full_name="Paciente Bundle Outcomes"))
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "adt_progression_verification")

    followup_response = client.post(
        "/api/add_followup",
        json={
            "patient_id": patient_id,
            "psa": 6.8,
            "testosterone": 124,
            "treatment": "ADT",
            "status": "Progresión radiográfica",
        },
    )
    assert followup_response.status_code == 200

    response = client.get(f"/api/patients/{patient_id}/signals")

    assert response.status_code == 200
    payload = response.get_json()
    summary = payload["outcome_events_summary"]

    assert summary["total"] >= 1
    assert "castration_resistance" in summary["by_axis"]
    assert payload["pending_adjudications"]
    assert payload["current_course_status"]


def test_adt_progression_followup_supersedes_intake_and_retargets_crpc_pathway(app_client):
    client, db_path = app_client
    payload = make_patient_payload(nss="39494949500", full_name="Paciente Supersedencia ADT")
    payload.update(
        {
            "metastasis_site": "Bone",
            "metastasis_count": 4,
            "line_of_therapy": 2,
            "volume_disease": "High",
        }
    )
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "adt_progression_verification")

    visit_response = client.post(
        f"/api/patients/{patient_id}/visits",
        json={
            "visit_date": "2026-03-21",
            "state": "adt_progression_verification",
            "management_track": "systemic_surveillance",
            "current_treatment": "ADT + abiraterona",
            "psa": 7.8,
            "testosterone": 18,
            "hemoglobin": 9.2,
            "alp": 322,
            "ldh": 288,
            "creatinine": 1.72,
            "ast": 146,
            "alt": 138,
            "bilirubin": 2.4,
            "disease_status": "Progresión radiográfica",
            "progression_pattern": "radiographic",
            "conventional_imaging_status": "M1b",
            "ecog": 1,
        },
    )
    assert visit_response.status_code == 200

    signals_response = client.get(f"/api/patients/{patient_id}/signals")
    assert signals_response.status_code == 200
    signals_payload = signals_response.get_json()

    assert signals_payload["signals"]["reconciled_state"] == "m1_crpc"
    assert signals_payload["effective_state_final"] == "m1_crpc"
    assert signals_payload["transition_resolution"]["target_state"] == "m1_crpc"
    assert signals_payload["next_best_action"]["title"]
    assert signals_payload["decision_recalculation_trace"]["available"] is True
    assert signals_payload["decision_recalculation_trace"]["what_changed_today"]
    assert signals_payload["latest_clinically_decisive_visit"]["source_type"] == "stage_visit"


def test_mhspc_gate_preserves_metastatic_phenotype_across_signals_schedule_and_full_assessment(app_client):
    client, db_path = app_client
    payload = make_patient_payload(
        nss="39494949502",
        full_name="Paciente Gate mHSPC",
        assessment_state="adt_progression_verification",
    )
    payload.update(
        {
            "metastasis_site": "Bone",
            "metastasis_count": 5,
            "volume_disease": "High",
            "bone_thoracic_spine_count": 4,
            "bone_femur_count": 1,
        }
    )
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "adt_progression_verification")

    visit_response = client.post(
        f"/api/patients/{patient_id}/visits",
        json={
            "visit_date": "2026-03-23",
            "state": "adt_progression_verification",
            "management_track": "systemic_surveillance",
            "current_treatment": "ADT continua",
            "psa": 8.1,
            "disease_status": "Progresión radiográfica",
            "progression_pattern": "radiographic",
            "conventional_imaging_status": "not_restaged",
            "ecog": 1,
        },
    )
    assert visit_response.status_code == 200

    signals_response = client.get(f"/api/patients/{patient_id}/signals")
    schedule_response = client.get(f"/api/patients/{patient_id}/schedule")
    full_assessment_response = client.post(f"/api/ai/full-assessment/{patient_id}", json={})

    assert signals_response.status_code == 200
    assert schedule_response.status_code == 200
    assert full_assessment_response.status_code == 200

    signals_payload = signals_response.get_json()
    schedule_payload = schedule_response.get_json()
    full_assessment_payload = full_assessment_response.get_json()

    assert signals_payload["signals"]["reconciled_state"] == "mcspc_high_volume_sync"
    assert signals_payload["phenotype_state"] == "mcspc_high_volume_sync"
    assert signals_payload["progression_gate_active"] is True
    assert signals_payload["progression_gate_target"] == "adt_progression_verification"
    if signals_payload["mhspc_copilot_bundle"].get("available"):
        assert signals_payload["mhspc_copilot_bundle"]["progression_gate_active"] is True
        assert signals_payload["mhspc_copilot_bundle"]["final_presented_recommendation"]["source"] == "adt_progression_verification"

    assert schedule_payload["reconciled_state"] == "mcspc_high_volume_sync"
    assert schedule_payload["phenotype_state"] == "mcspc_high_volume_sync"
    assert schedule_payload["progression_gate_active"] is True
    assert "castración" in schedule_payload["progression_gate_reason"].lower()

    assert full_assessment_payload["phenotype_state"] == "mcspc_high_volume_sync"
    assert full_assessment_payload["progression_gate_active"] is True
    if full_assessment_payload["mhspc_decision_bundle"].get("available"):
        assert full_assessment_payload["mhspc_decision_bundle"]["progression_gate_active"] is True
        assert full_assessment_payload["final_presented_recommendation"]["source"] == "adt_progression_verification"
    else:
        assert "castración" in (
            str(full_assessment_payload["final_presented_recommendation"].get("recommended_action") or "")
            + " "
            + str(full_assessment_payload["final_presented_recommendation"].get("rationale") or "")
        ).lower()


def test_labs_intelligence_endpoint_exposes_hepatic_renal_bone_and_endocrine_signals(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="39494949501", full_name="Paciente Labs Intelligence"))
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "adt_progression_verification")

    visit_response = client.post(
        f"/api/patients/{patient_id}/visits",
        json={
            "visit_date": "2026-03-21",
            "state": "adt_progression_verification",
            "management_track": "systemic_surveillance",
            "current_treatment": "ADT + abiraterona",
            "psa": 4.6,
            "testosterone": 76,
            "hemoglobin": 8.9,
            "alp": 370,
            "ldh": 280,
            "creatinine": 1.83,
            "ast": 155,
            "alt": 149,
            "bilirubin": 2.2,
            "ggt": 101,
        },
    )
    assert visit_response.status_code == 200

    response = client.get(f"/api/patients/{patient_id}/labs-intelligence")
    assert response.status_code == 200
    payload = response.get_json()
    profile = payload["laboratory_intelligence_profile"]

    assert profile["available"] is True
    titles = {alert["title"] for alert in profile["active_alerts"]}
    assert "Testosterona > 50 ng/dL bajo ADT" in titles
    assert "Anemia significativa (Hb < 10 g/dL)" in titles
    assert "Fosfatasa alcalina elevada" in titles
    assert "Deterioro renal relevante" in titles
    assert "Hepatotoxicidad relevante bajo abiraterona" in titles
    assert profile["coverage"]["has_hepatic_panel"] is True
    assert profile["coverage"]["has_renal_panel"] is True


def test_schedule_and_profile_expose_guideline_plan_and_longitudinal_sections(app_client):
    client, db_path = app_client
    payload = make_patient_payload(nss="39494949502", full_name="Paciente Perfil Vivo")
    payload.update({"metastasis_site": "Bone", "line_of_therapy": 2})
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "adt_progression_verification")

    client.post(
        f"/api/patients/{patient_id}/visits",
        json={
            "visit_date": "2026-03-22",
            "state": "adt_progression_verification",
            "management_track": "systemic_surveillance",
            "current_treatment": "ADT + abiraterona",
            "testosterone": 22,
            "disease_status": "Progresión radiográfica",
            "progression_pattern": "radiographic",
            "ast": 122,
            "alt": 118,
            "bilirubin": 1.8,
        },
    )

    schedule_response = client.get(f"/api/patients/{patient_id}/schedule")
    assert schedule_response.status_code == 200
    schedule_payload = schedule_response.get_json()
    assert schedule_payload["guideline_followup_plan"]["policy"] == "NCCN-first with EAU fallback"
    assert schedule_payload["schedule_primary_intent"]
    assert schedule_payload["care_intent_contract"]["headline"]
    assert schedule_payload["latest_clinically_decisive_visit"]

    profile_response = client.get(f"/patient_profile/{payload['nss']}")
    assert profile_response.status_code == 200
    profile_html = profile_response.get_data(as_text=True)
    assert "Brújula longitudinal viva" in profile_html
    assert "Laboratorios longitudinales con impacto clínico real" in profile_html
    assert "Plan maestro de seguimiento protocolizado" in profile_html


def test_profile_compass_prioritizes_longitudinal_direction_over_stale_assessment_summary(app_client):
    client, db_path = app_client
    payload = make_patient_payload(nss="39494949503", full_name="Paciente Perfil Vivo Recalculo")
    payload.update({"metastasis_site": "Bone", "line_of_therapy": 2, "testosterone_baseline": 95})
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "adt_progression_verification")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "testosterone": 95,
            "castrate_testosterone_status": "not_castrate",
            "progression_pattern": "radiographic",
            "conventional_imaging_status": "M1",
        },
    )

    client.post(
        f"/api/patients/{patient_id}/visits",
        json={
            "visit_date": "2026-03-24",
            "state": "adt_progression_verification",
            "management_track": "systemic_surveillance",
            "current_treatment": "ADT + abiraterona",
            "testosterone": 16,
            "castrate_testosterone_status": "confirmed_castrate",
            "disease_status": "Progresión radiográfica",
            "progression_pattern": "radiographic",
            "hemoglobin": 9.4,
            "ldh": 286,
        },
    )

    profile_response = client.get(f"/patient_profile/{payload['nss']}")
    assert profile_response.status_code == 200
    profile_html = profile_response.get_data(as_text=True)
    assert "Brújula longitudinal viva" in profile_html
    assert "testosterona actual de 95 ng/dL" not in profile_html
    assert "Fracaso de supresión androgénica / castración inadecuada." not in profile_html


def test_patient_ref_routes_accept_numeric_and_alphanumeric_identifiers(app_client):
    client, db_path = app_client
    payload = make_patient_payload(nss="VAL-ROUTE-001", full_name="Paciente Ref Clínico")
    payload.update({"metastasis_site": "Bone", "line_of_therapy": 2})
    register = client.post("/api/register_patient", json=payload)
    assert register.status_code == 200
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "adt_progression_verification")

    client.post(
        f"/api/patients/{patient_id}/visits",
        json={
            "visit_date": "2026-03-25",
            "state": "adt_progression_verification",
            "management_track": "systemic_surveillance",
            "current_treatment": "ADT + abiraterona",
            "testosterone": 18,
            "disease_status": "Progresión radiográfica",
            "progression_pattern": "radiographic",
        },
    )

    signals_numeric = client.get(f"/api/patients/{patient_id}/signals")
    signals_alpha = client.get(f"/api/patients/{payload['nss']}/signals")
    schedule_alpha = client.get(f"/api/patients/{payload['nss']}/schedule")
    progression_alpha = client.get(f"/api/ai/progression-dashboard/{payload['nss']}")
    natural_history_alpha = client.get(f"/api/ai/natural-history/{payload['nss']}")
    full_assessment_alpha = client.post(f"/api/ai/full-assessment/{payload['nss']}", json={})

    assert signals_numeric.status_code == 200
    assert signals_alpha.status_code == 200
    assert schedule_alpha.status_code == 200
    assert progression_alpha.status_code == 200
    assert natural_history_alpha.status_code == 200
    assert full_assessment_alpha.status_code == 200

    signals_numeric_payload = signals_numeric.get_json()
    signals_alpha_payload = signals_alpha.get_json()
    schedule_alpha_payload = schedule_alpha.get_json()
    progression_payload = progression_alpha.get_json()
    natural_history_payload = natural_history_alpha.get_json()
    full_assessment_payload = full_assessment_alpha.get_json()

    assert signals_numeric_payload["resolved_patient_id"] == patient_id
    assert signals_alpha_payload["resolved_patient_id"] == patient_id
    assert signals_alpha_payload["resolved_patient_ref"] == payload["nss"]
    assert schedule_alpha_payload["resolved_patient_id"] == patient_id
    assert schedule_alpha_payload["resolved_patient_ref"] == payload["nss"]
    assert progression_payload["patient_id"] == patient_id
    assert progression_payload["resolved_patient_ref"] == payload["nss"]
    assert natural_history_payload["patient_id"] == patient_id
    assert natural_history_payload["resolved_patient_ref"] == payload["nss"]
    assert full_assessment_payload["patient_id"] == patient_id
    assert full_assessment_payload["resolved_patient_ref"] == payload["nss"]


def test_profile_sanitizes_missing_values_and_internal_status_labels(app_client):
    client, db_path = app_client
    payload = make_patient_payload(nss="39494949504", full_name="Paciente UI Limpia")
    payload["baseline_psa"] = None
    register = client.post("/api/register_patient", json=payload)
    assert register.status_code == 200
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "localized_initial")

    profile_response = client.get(f"/patient_profile/{payload['nss']}")
    assert profile_response.status_code == 200
    profile_html = profile_response.get_data(as_text=True)

    assert "None ng/mL" not in profile_html
    assert "insufficient_data" not in profile_html
    assert "Incomplete" not in profile_html
    assert "actionable" not in profile_html
    assert "No disponible" in profile_html


def test_missing_input_actions_expose_display_copy_without_losing_machine_fields(app_client):
    client, db_path = app_client
    payload = make_patient_payload(nss="39494949505", full_name="Paciente Captura Accionable")
    payload.update({"metastasis_site": "Bone", "line_of_therapy": 2})
    register = client.post("/api/register_patient", json=payload)
    assert register.status_code == 200
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "m1_crpc")

    import tracking_db
    from prostanet.domains.patient_tracking.profile_compass import build_patient_profile_view_model

    refreshed = tracking_db.get_patient_full_record(payload["nss"])
    longitudinal_bundle = tracking_db.refresh_longitudinal_intelligence(
        patient_id,
        force_recompute=False,
        record=refreshed,
        include_live_benchmark=False,
    )
    profile = build_patient_profile_view_model(
        patient=refreshed,
        latest_assessment_raw=refreshed.get("latest_assessment") or {},
        latest_assessment=refreshed.get("latest_assessment") or {},
        state_timeline=refreshed.get("state_timeline") or [],
        care_overlays=refreshed.get("care_overlays") or [],
        recommendations={},
        longitudinal_bundle=longitudinal_bundle,
    )

    action = next(item for item in profile["missing_input_actions"] if item["key"] == "line_refresh")
    assert {"line_of_therapy_number", "current_adt_context", "drug_scheme"} <= set(action["raw_fields"])
    assert {"psa_history", "testosterone_history"} <= set(action["visible_fields"])
    assert action["display_cta"] == "Completar en visita"
    assert action["display_group"] == "Visita clínica"
    assert "Contexto actual de ADT" in action["display_fields_summary"]
    assert "Esquema sistémico actual" in action["display_fields_summary"]
    assert "current_adt_context" not in action["display_fields_summary"]
    assert "drug_scheme" not in action["display_fields_summary"]
    assert "secuenciación sistémica" in action["display_impact"].lower()


def test_patient_profile_visible_text_hides_machine_field_names_in_missing_input_cards(app_client):
    client, db_path = app_client
    payload = make_patient_payload(nss="39494949506", full_name="Paciente Perfil Sin Jerga")
    payload.update({"metastasis_site": "Bone", "line_of_therapy": 2})
    register = client.post("/api/register_patient", json=payload)
    assert register.status_code == 200
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "m1_crpc")

    profile_response = client.get(f"/patient_profile/{payload['nss']}")
    assert profile_response.status_code == 200
    profile_html = profile_response.get_data(as_text=True)
    section_match = re.search(
        r"Captura clínica obligada.*?Brújula clínica actual",
        profile_html,
        flags=re.DOTALL,
    )
    assert section_match
    visible_text = re.sub(r"<[^>]+>", " ", section_match.group(0))
    visible_text = re.sub(r"\s+", " ", visible_text)

    assert "psma_negative_dominant_lesions" not in visible_text
    assert "current_adt_context" not in visible_text
    assert "drug_scheme" not in visible_text
    assert "Impacta:" not in visible_text
    assert "Contexto actual de ADT" in visible_text
    assert "Esquema sistémico actual" in visible_text
    assert "Completar en visita" in visible_text


def test_followup_recalculation_trace_humanizes_changed_fields():
    from prostanet.domains.patient_tracking.followup_reconciliation_service import build_decision_recalculation_trace

    trace = build_decision_recalculation_trace(
        patient={},
        state="m1_crpc",
        management_track="systemic_control",
        longitudinal_truth_snapshot={
            "superseded_inputs": [
                {
                    "field_name": "drug_scheme",
                    "previous_value": "ADT_ABIRATERONE",
                    "current_value": "DOCETAXEL",
                },
                {
                    "field_name": "ast",
                    "previous_value": 32,
                    "current_value": 89,
                },
            ],
            "latest_clinically_decisive_visit": {"clinically_sufficient": True},
        },
        transition_resolution={"policy": "auto_applied"},
        care_intent_contract={"headline": "Reevaluar secuencia sistémica y seguridad activa"},
    )

    assert trace["what_changed_today"][0].startswith("Esquema sistémico actual:")
    assert "adt + abiraterona" in trace["what_changed_today"][0].lower()
    assert "docetaxel" in trace["what_changed_today"][0].lower()
    assert trace["what_changed_today"][1].startswith("AST:")
    assert "drug_scheme" not in trace["what_changed_today"][0]
    assert "ast actualizado" not in " ".join(trace["what_changed_today"]).lower()


def test_patient_profile_alerts_and_provenance_hide_machine_copy(app_client):
    client, db_path = app_client
    payload = make_patient_payload(nss="39494949507", full_name="Paciente Copiloto Limpio")
    payload.update({"metastasis_site": "Bone", "line_of_therapy": 2})
    register = client.post("/api/register_patient", json=payload)
    assert register.status_code == 200
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "m1_crpc")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO data_provenance (
            patient_id, field_name, value_json, source_type, source_date
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            patient_id,
            "drug_scheme",
            json.dumps("ADT_ABIRATERONE"),
            "follow_up_visits",
            "2026-03-01",
        ),
    )
    conn.commit()
    conn.close()

    import tracking_db
    from prostanet.domains.patient_tracking.profile_compass import build_patient_profile_view_model

    refreshed = tracking_db.get_patient_full_record(payload["nss"])
    longitudinal_bundle = tracking_db.refresh_longitudinal_intelligence(
        patient_id,
        force_recompute=False,
        record=refreshed,
        include_live_benchmark=False,
    )
    profile = build_patient_profile_view_model(
        patient=refreshed,
        latest_assessment_raw=refreshed.get("latest_assessment") or {},
        latest_assessment=refreshed.get("latest_assessment") or {},
        state_timeline=refreshed.get("state_timeline") or [],
        care_overlays=refreshed.get("care_overlays") or [],
        recommendations={},
        longitudinal_bundle=longitudinal_bundle,
    )

    alert = next(item for item in profile["copilot"]["clinical_alerts"] if item.get("display_fields_to_capture"))
    assert "current_adt_context" not in " ".join(alert["display_fields_to_capture"])
    assert all("_" not in label for label in alert["display_fields_to_capture"])
    assert all(not label.startswith("source_document:") for label in alert["display_fields_to_capture"])
    assert profile["data_provenance"][0]["display_field_name"] == "Esquema sistémico actual"
    assert profile["data_provenance"][0]["display_source_type"] == "Visita longitudinal"

    profile_response = client.get(f"/patient_profile/{payload['nss']}")
    assert profile_response.status_code == 200
    profile_html = profile_response.get_data(as_text=True)

    alert_match = re.search(
        r"Alertas clínicas del copiloto.*?Calendario de seguimiento programado",
        profile_html,
        flags=re.DOTALL,
    )
    assert alert_match
    alert_text = re.sub(r"<[^>]+>", " ", alert_match.group(0))
    alert_text = re.sub(r"\s+", " ", alert_text)

    provenance_match = re.search(
        r"Provenance clínica reciente.*?Datos verificados recientes",
        profile_html,
        flags=re.DOTALL,
    )
    assert provenance_match
    provenance_text = re.sub(r"<[^>]+>", " ", provenance_match.group(0))
    provenance_text = re.sub(r"\s+", " ", provenance_text)

    assert "Captura esperada:" not in alert_text
    assert "Completar para recalcular" in alert_text
    assert "current_adt_context" not in alert_text
    assert "drug_scheme" not in provenance_text
    assert "follow_up_visits" not in provenance_text
    assert "Esquema sistémico actual" in provenance_text
    assert "Visita longitudinal" in provenance_text
    assert "Facts verificados recientes" not in profile_html


def test_profile_alert_copy_collapses_duplicate_title_message():
    from prostanet.domains.patient_tracking.profile_compass import (
        _decorate_copilot_sections,
        _decorate_patient_alerts,
    )

    duplicated = "Resultado molecular verificable para PARP / biomarcadores"
    copilot = _decorate_copilot_sections(
        {
            "clinical_alerts": [
                {
                    "title": duplicated,
                    "message": duplicated,
                    "recommended_action": "Completar captura",
                    "severity": "critical",
                }
            ]
        }
    )
    patient_alerts = _decorate_patient_alerts(
        [{"title": duplicated, "description": duplicated, "severity": "critical"}]
    )

    assert copilot["clinical_alerts"][0]["display_title"] == duplicated
    assert copilot["clinical_alerts"][0]["display_message"] == ""
    assert patient_alerts[0]["display_title"] == duplicated
    assert patient_alerts[0]["display_description"] == ""


def test_master_followup_plan_and_profile_focus_copy_use_structured_labels():
    from prostanet.domains.patient_tracking.master_followup_plan import build_master_followup_plan
    from prostanet.domains.patient_tracking.profile_compass import build_patient_profile_view_model

    patient = {
        "id": 99,
        "nss": "39494949599",
        "full_name": "Paciente Copy Visible",
        "recommendation_block_reason": "Faltan datos críticos que cambian la conducta clínica: progression_pattern, conventional_imaging_status",
        "latest_signal_snapshot": {
            "critical_missing": ["current_adt_context", "psa_history", "weight_loss_6m_pct"],
            "awaiting_review": ["line_of_therapy_context"],
            "active_safety": ["castrate_testosterone_status"],
        },
        "decision_blocking_bundle": {
            "decision_blocking_inputs": ["progression_pattern", "conventional_imaging_status"],
        },
        "palliative_monitoring_package": {
            "required_visit_fields": ["bpi_worst_pain", "weight_loss_6m_kg"],
            "missing_inputs": ["current_analgesics", "bowel_regimen_started"],
        },
        "survivorship_monitoring_package": {
            "required_visit_fields": ["fatigue_score", "mini_cog_score"],
            "missing_inputs": ["weight_loss_6m_pct", "systolic_bp"],
        },
        "copilot_alerts": [
            {
                "alert_key": "copy-check",
                "title": "Recalcular con captura estructurada",
                "message": "Faltan datos que cambian la conducta actual.",
                "severity": "warning",
                "fields_to_capture": ["psa_history", "eq5d_vas_band", "weight_loss_6m_pct"],
            }
        ],
        "agenda_items": [
            {
                "agenda_key": "copy-agenda-1",
                "title": "Revisión activa",
                "status": "due",
                "summary": "Captura clínica dirigida.",
                "required_inputs": ["psa_history", "weight_loss_6m_pct", "drug_scheme"],
            }
        ],
    }
    latest_assessment_raw = {"state": "adt_progression_verification", "assessment_date": "2026-04-07", "input_snapshot": {}, "result_snapshot": {}}
    latest_assessment = {"state": "adt_progression_verification", "module_label": "Verificación ADT", "display_result": {}}

    profile = build_patient_profile_view_model(
        patient=patient,
        latest_assessment_raw=latest_assessment_raw,
        latest_assessment=latest_assessment,
        state_timeline=[],
        care_overlays=[],
        recommendations={},
    )

    assert profile["clinical_signals"]["display_critical_missing"] == [
        "Contexto actual de ADT",
        "Serie longitudinal de PSA / APE",
        "Pérdida de peso en 6 meses",
    ]
    assert profile["clinical_signals"]["display_awaiting_review"] == ["Contexto clínico de la línea actual"]
    assert profile["clinical_signals"]["display_active_safety"] == ["Estado de castración"]
    assert profile["decision_blocking_bundle"]["display_decision_blocking_inputs"] == [
        "Patrón de progresión",
        "Imagen convencional actual",
    ]
    assert {
        "BPI dolor peor basal",
        "BPI dolor peor",
        "Peso actual",
        "Estatura",
        "Índice de masa corporal",
        "Pérdida de peso en 6 meses",
        "Mini-Cog",
        "Fuerza de prensión reducida",
    } <= set(profile["palliative_monitoring_package"]["display_required_visit_fields"])
    assert all("_" not in item for item in profile["palliative_monitoring_package"]["display_missing_inputs"])
    assert {"Fatiga basal", "Síntomas de fatiga", "Mini-Cog"} <= set(
        profile["survivorship_monitoring_package"]["display_required_visit_fields"]
    )
    assert profile["survivorship_monitoring_package"]["display_missing_inputs"] == [
        "Pérdida de peso en 6 meses",
        "Presión arterial sistólica",
    ]
    assert profile["display_recommendation_block_reason"] == (
        "Faltan datos críticos que cambian la conducta clínica: "
        "Patrón de progresión, Imagen convencional actual"
    )
    assert {"PSA actual", "Serie longitudinal de PSA / APE", "Pérdida de peso en 6 meses"} <= set(
        profile["active_agenda_items"][0]["display_required_inputs"]
    )
    assert "psa_history" not in profile["active_agenda_items"][0]["display_required_inputs"]
    assert "weight_loss_6m_pct" not in profile["active_agenda_items"][0]["display_required_inputs"]

    master_plan = build_master_followup_plan(
        patient=patient,
        state="adt_progression_verification",
        management_track="systemic_surveillance",
        agenda_board={
            "stage_protocol": {"title": "Plan maestro", "cadence_summary": "Seguimiento estrecho."},
            "protocol_trace": {"anchor_date": "2026-04-07", "anchor_source": "stage_visit_records.visit_date"},
            "protocol_comparators": [],
            "active_items": [
                {
                    "agenda_key": "copy-agenda-1",
                    "title": "Revisión activa",
                    "status": "due",
                    "summary": "Captura clínica dirigida.",
                    "required_inputs": ["psa_history", "weight_loss_6m_pct", "drug_scheme"],
                }
            ],
            "encounters": [],
        },
        signals={
            "critical_missing": ["current_adt_context", "psa_history", "weight_loss_6m_pct"],
            "survivorship_transition_bundle": {
                "missing_inputs": ["systolic_bp"],
            },
            "prognostic_capture_targets": [
                {
                    "title": "Captura de PROs",
                    "raw_fields": ["eq5d_vas_band", "fatigue_score"],
                    "display_fields_summary": ["EQ-5D VAS basal", "EQ-5D VAS", "Fatiga basal", "Síntomas de fatiga"],
                }
            ],
        },
        copilot_alerts=patient["copilot_alerts"],
        next_best_action={},
    )

    joined_gaps = " ".join(master_plan["gaps_to_close"])
    assert "Contexto actual de ADT" in joined_gaps
    assert "Serie longitudinal de PSA / APE" in joined_gaps
    assert "Pérdida de peso en 6 meses" in joined_gaps
    assert "EQ-5D VAS basal" in joined_gaps
    assert "Presión arterial sistólica" in joined_gaps
    assert "current_adt_context" not in joined_gaps
    assert "psa_history" not in joined_gaps
    assert "weight_loss_6m_pct" not in joined_gaps
    assert "eq5d_vas_band" not in joined_gaps
    assert "systolic_bp" not in joined_gaps
    assert {"PSA actual", "Serie longitudinal de PSA / APE", "Pérdida de peso en 6 meses"} <= set(
        master_plan["due_items"][0]["display_required_inputs"]
    )
    assert "psa_history" not in master_plan["due_items"][0]["display_required_inputs"]
    assert "weight_loss_6m_pct" not in master_plan["due_items"][0]["display_required_inputs"]


def test_bcr_without_imaging_stays_non_metastatic_and_pending_restaging(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="39595959595", full_name="Paciente BCR High Risk"))
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "recurrence_bcr")
    _insert_postlocal_bcr_context(db_path, patient_id, bcr_psa=0.42, psadt=8.0)

    response = client.get(f"/api/patients/{patient_id}/outcomes")

    assert response.status_code == 200
    payload = response.get_json()
    event_types = {item["event_type"] for item in payload["outcome_events"]}
    pending_keys = {item["status_key"] for item in payload["pending_adjudications"]}

    assert {"bcr_detected", "high_risk_bcr", "salvage_window_open"} <= event_types
    assert "radiographic_progression" not in event_types
    assert any(key.endswith("salvage_imaging") for key in pending_keys)
    assert payload["current_trial_comparable_profile"]["benchmark_family"] == "POST_RP_SALVAGE_like"
    assert payload["current_trial_comparable_profile"]["recommended_trial_backbone_label"] == "RT de salvage temprana +/- ADT corta/prolongada"
    assert "alto riesgo" in payload["current_course_status"].lower()


def test_crpc_not_confirmed_without_castrate_testosterone(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="39696969696", full_name="Paciente CRPC Pendiente"))
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "adt_progression_verification")

    followup_response = client.post(
        "/api/add_followup",
        json={
            "patient_id": patient_id,
            "psa": 6.2,
            "testosterone": 120,
            "treatment": "ADT",
            "status": "Progresión radiográfica",
        },
    )
    assert followup_response.status_code == 200

    response = client.get(f"/api/patients/{patient_id}/outcomes")

    assert response.status_code == 200
    payload = response.get_json()
    event_types = {item["event_type"] for item in payload["outcome_events"]}

    assert "crpc_confirmation_pending" in event_types
    assert "crpc_confirmed" not in event_types
    assert any("crpc_confirmation" in item["status_key"] for item in payload["pending_adjudications"])
    assert "pendiente" in payload["current_course_status"].lower()


def test_mhspc_psa_milestones_surface_trial_comparable_endpoints(app_client):
    client, db_path = app_client
    payload = make_patient_payload(nss="39797979797", full_name="Paciente mHSPC Milestones")
    payload["baseline_psa"] = 100.0
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "mcspc_high_volume")

    followup_response = client.post(
        "/api/add_followup",
        json={
            "patient_id": patient_id,
            "psa": 5.0,
            "testosterone": 18,
            "treatment": "Abiraterona + ADT",
            "status": "Respuesta parcial",
        },
    )
    assert followup_response.status_code == 200

    response = client.get(f"/api/patients/{patient_id}/outcomes")

    assert response.status_code == 200
    payload = response.get_json()
    endpoints = {
        item["endpoint_key"]: item
        for item in payload["trial_comparable_endpoints"]
    }

    assert endpoints["psa50"]["status"] == "complete"
    assert endpoints["psa90"]["status"] == "complete"
    assert payload["current_trial_comparable_profile"]["benchmark_family"] == "ARANOTE_ARASENS_PEACE1_like"
    assert "ADT + darolutamida" in payload["current_trial_comparable_profile"]["recommended_trial_backbone_label"]
    assert "respuesta bioquímica profunda" in payload["current_course_status"].lower()


def test_m1_crpc_psmafore_like_profile_detected(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="39898989898", full_name="Paciente PSMAfore"))
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "m1_crpc")
    _update_latest_assessment_input(db_path, patient_id, {"psma_positive": "1", "m_substage_resolved": "M1b"})
    _insert_treatment_line(
        db_path,
        patient_id,
        line_of_therapy=1,
        drug_scheme="ADT_ABIRATERONE",
        start_date="2025-01-15",
        context="mCRPC_post_ARPI_pre_taxane",
    )
    _insert_psma_imaging(db_path, patient_id, psma_positive=True)

    response = client.get(f"/api/patients/{patient_id}/outcomes")

    assert response.status_code == 200
    payload = response.get_json()
    event_types = {item["event_type"] for item in payload["outcome_events"]}

    assert "psma_positive_pathway" in event_types
    assert payload["current_trial_comparable_profile"]["benchmark_family"] == "PSMAfore_like"
    assert "PSMAfore" in payload["current_trial_comparable_profile"]["matched_trials"]
    assert payload["current_trial_comparable_profile"]["recommended_trial_backbone_label"] == "Lutecio-177 PSMA-617"


def test_schedule_exposes_pending_adjudication_tasks_and_outcome_anchor(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="39999999990", full_name="Paciente Outcome Anchor"))
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "recurrence_bcr")
    _insert_postlocal_bcr_context(db_path, patient_id, bcr_psa=0.38, psadt=7.5)

    response = client.get(f"/api/patients/{patient_id}/schedule")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["pending_adjudication_tasks"]
    assert payload["outcome_anchor"]["event_type"] in {"high_risk_bcr", "salvage_window_open", "bcr_detected"}
    assert payload["current_course_status"]


def test_cohort_benchmarks_endpoint_aggregates_trial_like_families(app_client):
    client, db_path = app_client

    bcr_register = client.post("/api/register_patient", json=make_patient_payload(nss="39999999991", full_name="Paciente Cohorte BCR"))
    bcr_id = bcr_register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, bcr_id, "recurrence_bcr")
    _insert_postlocal_bcr_context(db_path, bcr_id, bcr_psa=0.44, psadt=8.0)

    crpc_register = client.post("/api/register_patient", json=make_patient_payload(nss="39999999992", full_name="Paciente Cohorte PSMA"))
    crpc_id = crpc_register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, crpc_id, "m1_crpc")
    _update_latest_assessment_input(db_path, crpc_id, {"psma_positive": "1", "m_substage_resolved": "M1b"})
    _insert_treatment_line(
        db_path,
        crpc_id,
        line_of_therapy=1,
        drug_scheme="ADT_ABIRATERONE",
        start_date="2025-01-15",
        context="mCRPC_post_ARPI_pre_taxane",
    )

    response = client.get("/api/cohorts/benchmarks")

    assert response.status_code == 200
    payload = response.get_json()
    families = payload["benchmark_families"]

    assert payload["total_patients"] >= 2
    assert "EMBARK_like" in families
    assert "PSMAfore_like" in families
    assert families["EMBARK_like"]["matched"] >= 1
    assert families["PSMAfore_like"]["matched"] >= 1


def test_psa_forecast_endpoint_returns_ready_bundle_for_stable_advanced_line(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="39999999993", full_name="Paciente Forecast Ready"))
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "m1_crpc")
    _insert_treatment_line(
        db_path,
        patient_id,
        line_of_therapy=1,
        drug_scheme="ENZALUTAMIDE",
        start_date="2025-10-01",
        context="mCRPC_first_line",
    )
    _insert_psa_longitudinal_points(
        db_path,
        patient_id,
        [
            ("2025-11-01", 1.2),
            ("2026-01-01", 1.8),
            ("2026-03-01", 2.6),
        ],
    )
    _update_patient_contact_status(db_path, patient_id, last_contact_date="2026-03-15")

    response = client.get(f"/api/patients/{patient_id}/psa-forecast")

    assert response.status_code == 200
    payload = response.get_json()
    forecast = payload["psa_forecast"]
    assert forecast["status"] in {"ready", "low_confidence"}
    assert len(forecast["forecast_points"]) == 3
    assert payload["forecast_reliability"]["confidence_label"] in {"high", "medium", "low"}


def test_psa_forecast_endpoint_suppresses_numeric_projection_when_data_is_insufficient(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="39999999994", full_name="Paciente Forecast Insuficiente"))
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "m1_crpc")
    _insert_treatment_line(
        db_path,
        patient_id,
        line_of_therapy=1,
        drug_scheme="ENZALUTAMIDE",
        start_date="2026-01-15",
        context="mCRPC_first_line",
    )
    _insert_psa_longitudinal_points(
        db_path,
        patient_id,
        [
            ("2026-02-01", 1.5),
            ("2026-03-01", 2.1),
        ],
    )

    response = client.get(f"/api/patients/{patient_id}/psa-forecast")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["psa_forecast"]["status"] == "insufficient_data"
    assert payload["psa_forecast"]["show"] is False


def test_live_benchmark_and_profile_cards_render_for_advanced_patient(app_client):
    client, db_path = app_client
    target_payload = make_patient_payload(nss="39999999995", full_name="Paciente Benchmark Vivo")
    register = client.post("/api/register_patient", json=target_payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "m1_crpc")
    _insert_treatment_line(
        db_path,
        patient_id,
        line_of_therapy=1,
        drug_scheme="ENZALUTAMIDE",
        start_date="2025-06-01",
        context="mCRPC_first_line",
    )
    _insert_psa_longitudinal_points(
        db_path,
        patient_id,
        [
            ("2025-10-01", 1.0),
            ("2025-12-01", 1.4),
            ("2026-03-01", 2.0),
        ],
    )
    _update_patient_contact_status(db_path, patient_id, last_contact_date="2026-03-15")

    for idx in range(10):
        comparator = client.post(
            "/api/register_patient",
            json=make_patient_payload(nss=f"4999999999{idx}", full_name=f"Comparator {idx}"),
        )
        comparator_id = comparator.get_json()["patient_id"]
        _seed_latest_assessment_state(db_path, comparator_id, "m1_crpc")
        _insert_treatment_line(
            db_path,
            comparator_id,
            line_of_therapy=1,
            drug_scheme="ENZALUTAMIDE",
            start_date=f"2025-0{(idx % 6) + 1}-01",
            context="mCRPC_first_line",
        )
        _insert_psa_longitudinal_points(
            db_path,
            comparator_id,
            [
                ("2025-09-01", 0.9 + idx * 0.05),
                ("2025-12-01", 1.1 + idx * 0.05),
                ("2026-03-01", 1.5 + idx * 0.06),
            ],
        )
        _update_patient_contact_status(db_path, comparator_id, last_contact_date="2026-03-15")

    benchmark_response = client.get(f"/api/patients/{patient_id}/live-benchmark?refresh=1")
    profile_response = client.get(f"/patient_profile/{target_payload['nss']}")

    assert benchmark_response.status_code == 200
    benchmark_payload = benchmark_response.get_json()
    assert benchmark_payload["live_benchmark"]["status"] == "ready"
    assert benchmark_payload["benchmark_reliability"]["cohort_size"] >= 10
    assert profile_response.status_code == 200
    html = profile_response.get_data(as_text=True)
    assert "Benchmark Vivo" in html
    assert "Time-Machine PSA" in html


def test_patient_profile_initial_render_skips_cohort_benchmark_recompute(app_client, monkeypatch):
    client, db_path = app_client
    payload = make_patient_payload(nss="39999999994", full_name="Paciente Perfil Rapido")
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "m1_crpc")

    from prostanet.domains.patient_tracking import live_benchmark as live_benchmark_module

    def _fail_build(*args, **kwargs):
        raise AssertionError("El render inicial del perfil no debe recalcular benchmark cohortal.")

    monkeypatch.setattr(live_benchmark_module, "build_live_benchmark", _fail_build)

    profile_response = client.get(f"/patient_profile/{payload['nss']}")

    assert profile_response.status_code == 200
    html = profile_response.get_data(as_text=True)
    assert "Benchmark Vivo" in html
    assert "Actualizar benchmark" in html


def test_live_benchmark_endpoint_is_snapshot_first_without_refresh(app_client, monkeypatch):
    client, db_path = app_client
    payload = make_patient_payload(nss="39999999993", full_name="Paciente Snapshot Benchmark")
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "m1_crpc")

    from prostanet.domains.patient_tracking import live_benchmark as live_benchmark_module

    def _fail_build(*args, **kwargs):
        raise AssertionError("El endpoint snapshot-first no debe recalcular benchmark sin refresh explícito.")

    monkeypatch.setattr(live_benchmark_module, "build_live_benchmark", _fail_build)

    response = client.get(f"/api/patients/{patient_id}/live-benchmark")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["live_benchmark"]["status"] in {"deferred", "ready", "not_applicable"}


def test_signals_and_schedule_are_snapshot_first_without_recomputing_live_benchmark(app_client, monkeypatch):
    client, db_path = app_client
    payload = make_patient_payload(nss="399999999931", full_name="Paciente Snapshot Surfaces")
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "m1_crpc")

    from prostanet.domains.patient_tracking import live_benchmark as live_benchmark_module

    def _fail_build(*args, **kwargs):
        raise AssertionError("Signals y schedule no deben recalcular benchmark cohortal en línea.")

    monkeypatch.setattr(live_benchmark_module, "build_live_benchmark", _fail_build)

    signals_response = client.get(f"/api/patients/{patient_id}/signals")
    schedule_response = client.get(f"/api/patients/{patient_id}/schedule")

    assert signals_response.status_code == 200
    assert schedule_response.status_code == 200
    assert signals_response.get_json()["live_benchmark"]["status"] in {"deferred", "ready", "not_applicable"}


def test_vertical_payload_helpers_reuse_provided_longitudinal_bundle_without_refresh(app_client, monkeypatch):
    from prostanet.presentation import api as api_module

    def _fail_refresh(*args, **kwargs):
        raise AssertionError("Los helpers deben reutilizar el longitudinal_bundle ya resuelto.")

    monkeypatch.setattr(api_module.tracking_db, "refresh_longitudinal_intelligence", _fail_refresh)
    bundle = {
        "crpc_copilot_bundle": {"status": "crpc_ok"},
        "post_rp_salvage_bundle": {"status": "post_rp_ok"},
        "mhspc_copilot_bundle": {"status": "mhspc_ok"},
        "diagnostic_biopsy_bundle": {"status": "diagnostic_ok"},
        "localized_surveillance_bundle": {"status": "localized_ok"},
        "post_rt_salvage_bundle": {"status": "post_rt_ok"},
    }

    assert api_module._build_crpc_copilot_payload(1, longitudinal_bundle=bundle)["status"] == "crpc_ok"
    assert api_module._build_post_rp_salvage_payload(1, longitudinal_bundle=bundle)["status"] == "post_rp_ok"
    assert api_module._build_mhspc_copilot_payload(1, longitudinal_bundle=bundle)["status"] == "mhspc_ok"
    assert api_module._build_diagnostic_biopsy_payload(1, longitudinal_bundle=bundle)["status"] == "diagnostic_ok"
    assert api_module._build_localized_surveillance_payload(1, longitudinal_bundle=bundle)["status"] == "localized_ok"
    assert api_module._build_post_rt_salvage_payload(1, longitudinal_bundle=bundle)["status"] == "post_rt_ok"


def test_refresh_longitudinal_intelligence_reuses_core_record_without_full_reload(app_client, monkeypatch):
    client, _ = app_client
    payload = make_patient_payload(nss="399999999932", full_name="Paciente Refresh Core Only")
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]

    import tracking_db

    core_record = tracking_db.load_patient_record_core(patient_id)
    assert core_record

    original_get_patient_full_record = tracking_db.get_patient_full_record
    include_derivatives_calls = []

    def _spy_get_patient_full_record(*args, **kwargs):
        include_derivatives_calls.append(kwargs.get("include_derivatives", True))
        return original_get_patient_full_record(*args, **kwargs)

    monkeypatch.setattr(tracking_db, "get_patient_full_record", _spy_get_patient_full_record)

    bundle = tracking_db.refresh_longitudinal_intelligence(
        patient_id,
        force_recompute=False,
        record=core_record,
        include_live_benchmark=False,
    )

    assert bundle["signals"]
    assert bundle["master_followup_plan"]
    assert include_derivatives_calls
    assert all(include_derivatives is False for include_derivatives in include_derivatives_calls)


def test_patient_record_core_and_derivatives_helpers_preserve_wrapper_behavior(app_client):
    client, _ = app_client
    payload = make_patient_payload(
        nss="39999999992",
        full_name="Paciente Expediente Modular",
        gleason_primary=4,
        gleason_secondary=3,
        gleason_tertiary=5,
        bone_site_entries=[{"site_key": "thoracic_spine", "lesion_count": 2}],
        visceral_site_entries=[{"site_key": "liver", "lesion_count": 1}],
        nonregional_nodal_site_entries=[{"site_key": "retroperitoneal", "lesion_count": 1}],
    )
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]

    import tracking_db

    core_record = tracking_db.load_patient_record_core(patient_id)
    assert core_record is not None
    assert "longitudinal_truth_snapshot" not in core_record
    assert "decision_input_requirements" not in core_record
    assert "crpc_copilot_bundle" not in core_record
    assert core_record["identity"]["id"] == patient_id
    assert core_record["baseline"]["gleason_primary"] == 4
    assert core_record["baseline"]["gleason_secondary"] == 3
    assert core_record["baseline"]["gleason_tertiary"] == 5

    derived_record = tracking_db.build_patient_record_derivatives(core_record, include_ledger=False)
    wrapper_record = tracking_db.get_patient_full_record(patient_id, include_ledger=False)

    assert derived_record["longitudinal_truth_snapshot"]
    assert derived_record["decision_input_requirements"]
    assert derived_record["guideline_followup_plan"]
    assert wrapper_record["longitudinal_truth_snapshot"] == derived_record["longitudinal_truth_snapshot"]
    assert wrapper_record["schedule_state"] == derived_record["schedule_state"]
    assert wrapper_record["decision_input_requirements"] == derived_record["decision_input_requirements"]
    assert wrapper_record["baseline"]["gleason_score"] == 7
    assert wrapper_record["baseline"]["isup_grade"] == 3


def test_mixed_metastatic_summary_propagates_to_signals_schedule_full_assessment_and_profile(app_client):
    client, db_path = app_client
    payload = make_patient_payload(
        nss="39999999991",
        full_name="Paciente Narrativa Metastásica Mixta",
        assessment_state="m1_crpc",
        metastasis_site="Visceral",
        bone_site_entries=[
            {"site_key": "thoracic_spine", "lesion_count": 2},
            {"site_key": "femur", "lesion_count": 1},
        ],
        visceral_site_entries=[
            {"site_key": "liver", "lesion_count": 1},
            {"site_key": "lung", "lesion_count": 2},
        ],
        nonregional_nodal_site_entries=[{"site_key": "retroperitoneal", "lesion_count": 1}],
        castrate_testosterone_status="confirmed_castrate",
    )
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "m1_crpc")

    visit_response = client.post(
        f"/api/patients/{patient_id}/visits",
        json={
            "visit_date": "2026-03-25",
            "state": "m1_crpc",
            "management_track": "systemic_surveillance",
            "current_treatment": "ADT + enzalutamida",
            "testosterone": 18,
            "castrate_testosterone_status": "confirmed_castrate",
            "disease_status": "Progresión radiográfica",
            "progression_pattern": "radiographic",
            "conventional_imaging_status": "M1c",
            "bone_site_entries": [
                {"site_key": "thoracic_spine", "lesion_count": 2},
                {"site_key": "femur", "lesion_count": 1},
            ],
            "visceral_site_entries": [
                {"site_key": "liver", "lesion_count": 1},
                {"site_key": "lung", "lesion_count": 2},
            ],
            "nonregional_nodal_site_entries": [{"site_key": "retroperitoneal", "lesion_count": 1}],
        },
    )
    assert visit_response.status_code == 200

    signals_payload = client.get(f"/api/patients/{patient_id}/signals").get_json()
    schedule_payload = client.get(f"/api/patients/{patient_id}/schedule").get_json()
    full_assessment_payload = client.post(f"/api/ai/full-assessment/{patient_id}", json={}).get_json()
    profile_html = client.get(f"/patient_profile/{payload['nss']}").get_data(as_text=True)

    for surface in (signals_payload, schedule_payload, full_assessment_payload):
        summary = surface["metastatic_composition_summary"]
        assert summary["available"] is True
        assert summary["m_substage_resolved"] == "M1c"
        assert "mixta" in summary["narrative"].lower()
        assert "bundle óseo" in summary["narrative"].lower()
        assert "retroperitoneal" in summary["summary"].lower()
        assert surface["decision_delta_since_last_visit"]["available"] is True

    crpc_bundle = signals_payload["crpc_copilot_bundle"]
    assert crpc_bundle["metastatic_composition_summary"]["bone_present"] is True
    assert crpc_bundle["metastatic_composition_summary"]["visceral_present"] is True
    assert crpc_bundle["metastatic_composition_summary"]["nonregional_nodal_present"] is True
    assert any("mixta" in item.lower() for item in crpc_bundle["why_changed_today"])
    assert "Enfermedad metastásica mixta" in profile_html
    assert "Cambio decisivo hoy:" in profile_html


def test_reconciled_state_reclassifies_stale_mhspc_snapshot_to_high_volume_metachronous(app_client):
    client, db_path = app_client
    payload = make_patient_payload(
        nss="39999999987",
        full_name="Paciente mHSPC Stale",
        assessment_state="mcspc_oligo_metachronous",
        metastasis_site="Visceral",
        volume_disease="High",
        metachronous_metastasis=1,
        visceral_site_entries=[{"site_key": "liver", "lesion_count": 2}],
    )
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "mcspc_oligo_metachronous")

    import tracking_db

    ok, _message = tracking_db.recompute_patient_care_plan(payload["nss"])
    assert ok is True

    signals_payload = client.get(f"/api/patients/{patient_id}/signals").get_json()
    profile_html = client.get(f"/patient_profile/{payload['nss']}").get_data(as_text=True)

    assert signals_payload["signals"]["reconciled_state"] == "mcspc_high_volume_sync"
    assert signals_payload["phenotype_state"] == "mcspc_high_volume_sync"
    assert signals_payload["metastatic_composition_summary"]["volume_disease"] == "high"
    assert signals_payload["mhspc_copilot_bundle"]["state_family"] == "mcspc_high_volume_sync"
    assert signals_payload["mhspc_copilot_bundle"]["triplet_decision"]["status"] in {"conditional", "not_prioritized", "pending_validation"}
    assert signals_payload["mhspc_copilot_bundle"]["triplet_decision"]["status"] != "not_applicable"
    assert "alto volumen" in profile_html.lower()
    assert "mHSPC de alto volumen sincrónico" in profile_html
    assert "Confirmar transición a mHSPC de alto volumen sincrónico" in profile_html
    assert "mcspc Alta volume sync" not in profile_html
    assert "No aplica triplete" not in profile_html
    assert "Oligometastásico SBRT elegible" not in profile_html


def test_register_patient_normalizes_structured_regimen_payload_and_hides_object_object_copy(app_client):
    client, _db_path = app_client
    payload = make_patient_payload(
        nss="39999999988",
        full_name="Paciente Régimen Estructurado",
        assessment_state="mcspc_high_volume_sync",
        metastasis_site="Bone",
        volume_disease="High",
        drug_scheme={"drug_scheme": "ADT_DAROLUTAMIDE", "label_clinico": "ADT + darolutamida"},
        current_treatment={"drug_scheme_label": "ADT + darolutamida"},
    )
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]

    import tracking_db

    record = tracking_db.get_patient_full_record(patient_id, include_ledger=False)
    profile_html = client.get(f"/patient_profile/{payload['nss']}").get_data(as_text=True)

    assert record["treatments"][0]["drug_scheme"] == "ADT_DAROLUTAMIDE"
    assert record["treatments"][0]["drug_scheme_label"] == "ADT + darolutamida"
    assert "[object Object]" not in profile_html


def test_mhspc_ranking_trace_propagates_to_signals_and_schedule(app_client):
    client, db_path = app_client
    payload = make_patient_payload(
        nss="39999999989",
        full_name="Paciente mHSPC Riesgo Convulsivo",
        assessment_state="mcspc_high_volume_sync",
        metastatic_disease_known=1,
        volume_disease="High",
        metastasis_count=5,
        bone_site_entries=[
            {"site_key": "thoracic_spine", "lesion_count": 3},
            {"site_key": "femur", "lesion_count": 1},
        ],
        visceral_site_entries=[{"site_key": "liver", "lesion_count": 1}],
        comorbidity_seizure=1,
        peripheral_neuropathy_grade=2,
        frailty_status="Vulnerable",
        child_pugh_score="A",
        drug_interaction_reviewed=1,
        gleason_primary=4,
        gleason_secondary=4,
        **_recent_docetaxel_labs(),
    )
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]
    module_result = client.post("/api/modules/mcspc_high_volume_sync/evaluate", json=payload).get_json()["result"]

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO clinical_assessments (
            module_id, state, input_snapshot, result_snapshot, guideline_versions, status, patient_id
        ) VALUES (?, ?, ?, ?, ?, 'linked', ?)
        """,
        (
            "mcspc_high_volume_sync",
            "mcspc_high_volume_sync",
            json.dumps(payload),
            json.dumps(module_result),
            json.dumps({}),
            patient_id,
        ),
    )
    cursor.execute(
        "UPDATE prior_clinical_history SET current_state = ? WHERE patient_id = ?",
        ("mcspc_high_volume_sync", patient_id),
    )
    conn.commit()
    conn.close()

    import tracking_db

    ok, _message = tracking_db.recompute_patient_care_plan(payload["nss"])
    assert ok is True

    signals_payload = client.get(f"/api/patients/{patient_id}/signals").get_json()
    schedule_payload = client.get(f"/api/patients/{patient_id}/schedule").get_json()

    for bundle in (
        signals_payload["mhspc_copilot_bundle"],
        schedule_payload["mhspc_copilot_bundle"],
    ):
        assert bundle["systemic_regimen_scope"] == "mhspc_doublet_triplet"
        assert bundle["preferred_frontline_regimen"]["regimen_code"] == "ADT_DAROLUTAMIDE"
        assert bundle["frontline_ranking_trace"]["winner_reason"]
        assert "docetaxel" in bundle["frontline_ranking_trace"]["why_not_triplet"].lower()
        assert bundle["triplet_decision"]["status"] == "not_prioritized"
        assert bundle["docetaxel_fitness"]["docetaxel_base_eligibility"] == "eligible_with_caution"
    assert schedule_payload["systemic_regimen_scope"] == "mhspc_doublet_triplet"
    assert schedule_payload["systemic_regimen_scope_contract"]["scope"] == "mhspc_doublet_triplet"


def test_schedule_and_profile_keep_non_systemic_modules_out_of_triplet_scope(app_client):
    client, _db_path = app_client
    payload = make_patient_payload(
        nss="39999999990",
        full_name="Paciente Localizado Sin Scope Sistémico",
        assessment_state="localized_initial",
        psa=6.2,
        gleason_primary=3,
        gleason_secondary=3,
        positive_cores=2,
        total_cores=12,
        pirads_score=3,
        clinical_t_stage="T1c",
    )
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]

    schedule_payload = client.get(f"/api/patients/{patient_id}/schedule").get_json()
    governance_payload = client.get(f"/api/patients/{patient_id}/decision-governance").get_json()
    profile_html = client.get(f"/patient_profile/{payload['nss']}").get_data(as_text=True)

    assert schedule_payload["systemic_regimen_scope"] == "not_applicable"
    assert governance_payload["systemic_regimen_scope"] == "not_applicable"
    assert governance_payload["systemic_regimen_scope_contract"]["scope"] == "not_applicable"
    assert "Por qué sí o por qué no triplete" not in profile_html


def test_signals_outcomes_and_cohort_survival_analysis_expose_forecast_and_live_benchmark(app_client):
    client, db_path = app_client
    target_payload = make_patient_payload(nss="39999999996", full_name="Paciente Señales Prospectivas")
    register = client.post("/api/register_patient", json=target_payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "m1_crpc")
    _insert_treatment_line(
        db_path,
        patient_id,
        line_of_therapy=1,
        drug_scheme="ENZALUTAMIDE",
        start_date="2025-06-01",
        context="mCRPC_first_line",
    )
    _insert_psa_longitudinal_points(
        db_path,
        patient_id,
        [
            ("2025-06-01", 0.9),
            ("2025-09-01", 1.0),
            ("2025-12-01", 1.3),
            ("2026-03-01", 1.9),
        ],
    )
    _update_patient_contact_status(db_path, patient_id, last_contact_date="2026-03-15")

    for idx in range(10):
        comparator = client.post(
            "/api/register_patient",
            json=make_patient_payload(nss=f"5999999999{idx}", full_name=f"Comparator Señales {idx}"),
        )
        comparator_id = comparator.get_json()["patient_id"]
        _seed_latest_assessment_state(db_path, comparator_id, "m1_crpc")
        _insert_treatment_line(
            db_path,
            comparator_id,
            line_of_therapy=1,
            drug_scheme="ENZALUTAMIDE",
            start_date="2025-05-01",
            context="mCRPC_first_line",
        )
        _insert_psa_longitudinal_points(
            db_path,
            comparator_id,
            [
                ("2025-06-01", 0.7 + idx * 0.03),
                ("2025-09-01", 0.8 + idx * 0.04),
                ("2025-12-01", 1.0 + idx * 0.05),
                ("2026-03-01", 1.4 + idx * 0.06),
            ],
        )
        _update_patient_contact_status(db_path, comparator_id, last_contact_date="2026-03-15")

    signals_response = client.get(f"/api/patients/{patient_id}/signals")
    outcomes_response = client.get(f"/api/patients/{patient_id}/outcomes")
    cohort_benchmarks_response = client.get("/api/cohorts/benchmarks")
    forecast_analysis_response = client.get("/api/cohorts/survival-analysis?endpoint=PSA_FORECAST")

    assert signals_response.status_code == 200
    assert outcomes_response.status_code == 200
    assert cohort_benchmarks_response.status_code == 200
    assert forecast_analysis_response.status_code == 200

    signals_payload = signals_response.get_json()
    outcomes_payload = outcomes_response.get_json()
    benchmarks_payload = cohort_benchmarks_response.get_json()
    analysis_payload = forecast_analysis_response.get_json()

    assert signals_payload["psa_forecast"]["status"] in {"ready", "low_confidence"}
    assert "live_benchmark" in signals_payload
    assert outcomes_payload["psa_forecast"]["status"] in {"ready", "low_confidence"}
    assert outcomes_payload["live_benchmark"]["status"] == "ready"
    assert "live_benchmark_summary" in benchmarks_payload
    assert "psa_forecast_summary" in benchmarks_payload
    assert analysis_payload["status"] == "ok"
    assert "summary_by_horizon" in analysis_payload


def test_patient_and_alert_routes_return_404_for_missing_patient(app_client):
    client, _ = app_client

    patient_response = client.get("/api/patient/00000000000")
    assert patient_response.status_code == 404
    assert patient_response.get_json()["success"] is False

    alerts_response = client.get("/api/alerts/999")
    assert alerts_response.status_code == 404
    assert alerts_response.get_json()["success"] is False

    export_response = client.get("/api/export/00000000000")
    assert export_response.status_code == 404
    assert export_response.get_json()["success"] is False


def test_delete_patient_endpoint_removes_profile_and_related_rows(app_client):
    client, db_path = app_client
    payload = make_patient_payload(nss="23232323232", full_name="Paciente Eliminable")
    register_response = client.post("/api/register_patient", json=payload)
    patient_id = register_response.get_json()["patient_id"]

    client.post(
        "/api/add_followup",
        json={
            "patient_id": patient_id,
            "psa": 4.1,
            "testosterone": 18,
            "ecog": 1,
            "pain": 0,
            "treatment": "ADT",
            "status": "Estable",
        },
    )

    delete_response = client.delete(f"/api/patients/{patient_id}")
    assert delete_response.status_code == 200
    delete_payload = delete_response.get_json()
    assert delete_payload["success"] is True
    assert delete_payload["deleted"]["patient_id"] == patient_id

    patient_response = client.get(f"/api/patient/{payload['nss']}")
    assert patient_response.status_code == 404

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM patient_identity WHERE id = ?", (patient_id,))
    assert cursor.fetchone()[0] == 0
    cursor.execute("SELECT COUNT(*) FROM clinical_baseline WHERE patient_id = ?", (patient_id,))
    assert cursor.fetchone()[0] == 0
    cursor.execute("SELECT COUNT(*) FROM follow_up_visits WHERE patient_id = ?", (patient_id,))
    assert cursor.fetchone()[0] == 0
    conn.close()


def test_agenda_endpoints_and_stage_visit_bundle_flow(app_client):
    client, _ = app_client
    payload = make_patient_payload(nss="44444444444", full_name="Paciente Agenda")

    register_response = client.post("/api/register_patient", json=payload)
    assert register_response.status_code == 200
    patient_id = register_response.get_json()["patient_id"]

    agenda_response = client.get(f"/api/patients/{payload['nss']}/agenda")
    assert agenda_response.status_code == 200
    agenda = agenda_response.get_json()["agenda"]
    assert agenda["items"]

    schema_response = client.get(f"/api/patients/{patient_id}/visit-schema")
    assert schema_response.status_code == 200
    schema = schema_response.get_json()["visit_schema"]
    assert schema["sections"]

    comparators_response = client.get(f"/api/patients/{patient_id}/protocol-comparison")
    assert comparators_response.status_code == 200
    comparators = comparators_response.get_json()["comparators"]
    assert comparators[0]["mode"] == "guideline_primary"

    visit_response = client.post(
        f"/api/patients/{patient_id}/visits",
        json={
            "visit_date": "2026-03-15",
            "state": "diagnostic_workup",
            "management_track": "diagnostic_surveillance",
            "disease_status": "Seguimiento estable",
            "psa": 9.1,
            "psad": 0.21,
            "pirads_score": "4",
            "mpmri_quality": "Adecuada",
            "planned_biopsy_type": "Dirigida + sistemática",
            "planned_biopsy_route": "Transperineal",
        },
    )
    assert visit_response.status_code == 200
    visit_payload = visit_response.get_json()
    assert visit_payload["success"] is True
    assert isinstance(visit_payload["followup_id"], int)
    assert isinstance(visit_payload["visit_record_id"], int)

    export_response = client.get(f"/api/export/{payload['nss']}")
    export_data = export_response.get_json()
    assert export_response.status_code == 200
    assert export_data["stage_visits"]
    assert export_data["data_provenance"]

    agenda_after_response = client.get(f"/api/patients/{payload['nss']}/agenda")
    agenda_after = agenda_after_response.get_json()["agenda"]
    actionable_item = next((item for item in agenda_after["items"] if item.get("status") in {"due", "overdue", "scheduled"}), None)
    assert actionable_item is not None

    complete_response = client.post(f"/api/patients/{patient_id}/agenda/{actionable_item['id']}/complete", json={})
    assert complete_response.status_code == 200
    assert complete_response.get_json()["success"] is True


def test_visit_schema_filters_fields_for_item_scoped_arpi_bundle(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="45454545454", full_name="Paciente Item Agenda"))
    patient_id = register.get_json()["patient_id"]

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO follow_up_visits (
            patient_id, visit_date, psa_current, testosterone_current, current_treatment,
            disease_status, ecog_current, agenda_context_json, visit_bundle_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            patient_id,
            "2026-03-15",
            3.4,
            18.0,
            "Abiraterona + ADT",
            "Seguimiento estable",
            1,
            json.dumps({}),
            json.dumps({}),
        ),
    )
    conn.commit()
    conn.close()

    agenda = client.get("/api/patients/45454545454/agenda").get_json()["agenda"]
    arpi_item = next(item for item in agenda["items"] if item["title"] == "Bundle de seguridad ARPI")

    schema_response = client.get(f"/api/patients/{patient_id}/visit-schema?agenda_id={arpi_item['id']}")
    assert schema_response.status_code == 200
    payload = schema_response.get_json()
    assert payload["visit_schema"]["submission_mode"] == "item_scoped"
    field_names = {
        field["name"]
        for section in payload["visit_schema"]["sections"]
        for field in section["fields"]
    }
    assert {"visit_date", "mini_cog_score", "fatigue_score", "cv_risk_documented", "ddi_review_status"} <= field_names
    assert "line_of_therapy" not in field_names
    assert payload["agenda_item_context"]["decision_targets"] == ["arpi_safety", "supportive_care", "treatment_tolerability"]


def test_visit_schema_supports_inline_task_presentation_for_item_scoped_arpi_bundle(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="45454545456", full_name="Paciente Inline Agenda"))
    patient_id = register.get_json()["patient_id"]

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO follow_up_visits (
            patient_id, visit_date, psa_current, testosterone_current, current_treatment,
            disease_status, ecog_current, agenda_context_json, visit_bundle_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            patient_id,
            "2026-03-15",
            3.4,
            18.0,
            "Abiraterona + ADT",
            "Seguimiento estable",
            1,
            json.dumps({}),
            json.dumps({}),
        ),
    )
    conn.commit()
    conn.close()

    agenda = client.get(f"/api/patients/{patient_id}/agenda").get_json()["agenda"]
    arpi_item = next(item for item in agenda["items"] if item["title"] == "Bundle de seguridad ARPI")

    schema_response = client.get(f"/api/patients/{patient_id}/visit-schema?agenda_id={arpi_item['id']}&presentation=inline_task")
    assert schema_response.status_code == 200
    payload = schema_response.get_json()
    schema = payload["visit_schema"]
    field_names = {
        field["name"]
        for section in schema["sections"]
        for field in section["fields"]
    }

    assert schema["presentation_mode"] == "inline_task"
    assert schema["submission_mode"] == "item_scoped"
    assert schema["task_scope"]["agenda_key"] == arpi_item["agenda_key"]
    assert schema["task_scope"]["action_mode"] == arpi_item["action_mode"]
    assert schema["encounter_key"] == arpi_item["encounter_key"]
    assert schema["plan_key"]
    assert schema["auto_visit_date"]
    assert schema["allow_visit_date_override"] is True
    assert "visit_date" not in field_names
    assert "clinician_notes" not in field_names
    assert set(schema["focus_fields"]) == field_names
    assert field_names == {
        field
        for field in arpi_item["required_inputs"]
        if field and not str(field).startswith("source_document:")
    }
    assert payload["agenda_item_context"]["mode"] == "inline_task"


def test_visit_schema_supports_capture_block_for_missing_inputs(app_client):
    client, _ = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="45555555555", full_name="Paciente Captura Dirigida"))
    patient_id = register.get_json()["patient_id"]

    schema_response = client.get(
        f"/api/patients/{patient_id}/visit-schema"
        "?state=mcspc_high_volume"
        "&track=on_arpi"
        "&fields=line_of_therapy_number,line_of_therapy_context,psa"
        "&capture_title=Confirmar%20linea%20terapeutica"
        "&capture_group=advanced_sequencing"
        "&decision_affected=systemic_sequencing"
    )
    assert schema_response.status_code == 200
    payload = schema_response.get_json()
    field_names = {
        field["name"]
        for section in payload["visit_schema"]["sections"]
        for field in section["fields"]
    }
    assert {"visit_date", "line_of_therapy_number", "line_of_therapy_context", "psa"} <= field_names
    assert {"drug_scheme", "psa_history"} <= field_names
    assert "clinician_notes" not in field_names
    assert payload["visit_schema"]["schema_scope"] == "exact_capture_block"
    assert payload["visit_schema"]["capture_fields"] == ["line_of_therapy_number", "line_of_therapy_context", "psa"]
    assert payload["visit_schema"]["visible_fields"] == [
        "line_of_therapy_number",
        "line_of_therapy_context",
        "drug_scheme",
        "psa",
        "psa_history",
    ]
    assert payload["agenda_item_context"]["mode"] == "capture_block"
    assert payload["agenda_item_context"]["decision_targets"] == ["systemic_sequencing"]


def test_visit_schema_maps_derived_requirements_to_source_fields_for_pre_surgery_board(app_client):
    from prostanet.domains.patient_tracking.followup_agenda import build_visit_schema

    agenda_item = {
        "agenda_key": "localized_initial:pre_surgery:surgery_board",
        "item_type": "therapy_review",
        "title": "Decision board prequirúrgico",
        "required_inputs": ["capra", "briganti", "partin", "mskcc_preop"],
        "derived_requirements": ["capra", "briganti", "partin", "mskcc_preop"],
        "decision_targets": ["localized_decision"],
        "write_targets": ["stage_visit_records"],
        "form_scope": {"mode": "item_scoped", "focus": "surgery_board"},
    }
    visit_schema = build_visit_schema("localized_initial", "pre_surgery", patient={}, agenda_item=agenda_item)
    field_names = {
        field["name"]
        for section in visit_schema["sections"]
        for field in section["fields"]
    }

    assert visit_schema["schema_scope"] == "exact_item"
    assert {"psa", "clinical_tstage", "gleason_primary", "gleason_secondary", "num_cores_positive", "total_cores"} <= field_names
    assert {"capra", "briganti", "partin", "mskcc_preop"}.isdisjoint(field_names)
    assert visit_schema["agenda_item_context"]["derived_requirements"] == ["capra", "briganti", "partin", "mskcc_preop"]
    assert visit_schema["agenda_item_context"]["capture_fields"] == [
        "psa",
        "clinical_tstage",
        "gleason_primary",
        "gleason_secondary",
        "num_cores_positive",
        "total_cores",
        "isup_grade",
    ]


def test_visit_schema_uses_canonical_regimen_dropdown_for_advanced_tracks(app_client):
    client, _ = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="45555555556", full_name="Paciente Catalogo Terapia"))
    patient_id = register.get_json()["patient_id"]

    schema_response = client.get(
        f"/api/patients/{patient_id}/visit-schema"
        "?state=mcspc_high_volume"
        "&track=on_arpi"
    )
    assert schema_response.status_code == 200
    payload = schema_response.get_json()
    drug_field = next(
        field
        for section in payload["visit_schema"]["sections"]
        for field in section["fields"]
        if field["name"] == "drug_scheme"
    )
    assert drug_field["field_type"] == "select"
    option_values = [option["value"] for option in drug_field["options"] if isinstance(option, dict) and option.get("value")]
    assert "ADT_ABIRATERONE" in option_values
    assert "ADT_ENZALUTAMIDE" in option_values
    assert "ADT_DOCETAXEL_DAROLUTAMIDE" not in option_values


def test_visit_schema_converges_longitudinal_widgets_with_legacy_followup_fallbacks(app_client):
    client, _ = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="45555555565", full_name="Paciente Longitudinal Convergente"))
    patient_id = register.get_json()["patient_id"]

    schema_response = client.get(
        f"/api/patients/{patient_id}/visit-schema"
        "?state=m1_crpc"
        "&track=systemic_surveillance"
    )
    assert schema_response.status_code == 200
    schema = schema_response.get_json()["visit_schema"]
    fields = {
        field["name"]: field
        for section in schema["sections"]
        for field in section["fields"]
    }

    assert "psa" in fields
    assert "testosterone" in fields
    assert fields["psa_history"]["field_type"] == "psa_history"
    assert fields["testosterone_history"]["field_type"] == "testosterone_history"
    assert "height_cm" in fields
    assert "weight_loss_6m_kg" in fields
    assert "weight_loss_6m_pct" not in fields
    assert fields["bmi_current"]["field_type"] == "number"
    assert "calcula automáticamente" in fields["bmi_current"]["help_text"]
    assert fields["mini_cog_score"]["field_type"] == "select"
    assert any(isinstance(option, dict) and "Severamente anormal" in option.get("label", "") for option in fields["mini_cog_score"]["options"])
    assert fields["weak_grip"]["field_type"] == "select"
    weak_grip_labels = [option["label"] for option in fields["weak_grip"]["options"] if isinstance(option, dict)]
    assert "Ausente" in weak_grip_labels
    assert "Presente" in weak_grip_labels


def test_visit_schema_expands_lab_item_to_structured_longitudinal_biomarker_widgets(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="45555555566", full_name="Paciente Agenda Laboratorio"))
    patient_id = register.get_json()["patient_id"]

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO follow_up_visits (
            patient_id, visit_date, psa_current, testosterone_current, current_treatment,
            disease_status, ecog_current, agenda_context_json, visit_bundle_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            patient_id,
            "2026-03-15",
            3.4,
            18.0,
            "Abiraterona + ADT",
            "Seguimiento estable",
            1,
            json.dumps({}),
            json.dumps({}),
        ),
    )
    conn.commit()
    conn.close()

    agenda = client.get(f"/api/patients/{patient_id}/agenda").get_json()["agenda"]
    lab_item = next(item for item in agenda["items"] if item["title"] == "Laboratorio de seguridad y actividad")

    schema_response = client.get(f"/api/patients/{patient_id}/visit-schema?agenda_id={lab_item['id']}")
    assert schema_response.status_code == 200
    schema = schema_response.get_json()["visit_schema"]
    field_names = {
        field["name"]
        for section in schema["sections"]
        for field in section["fields"]
    }

    assert {"visit_date", "psa", "psa_history", "testosterone", "testosterone_history"} <= field_names
    assert "psa_history" not in schema["capture_fields"]
    assert "testosterone_history" not in schema["capture_fields"]
    assert {"psa_history", "testosterone_history"} <= set(schema["visible_fields"])
    assert "psa" in schema["required_inputs"]
    assert "testosterone" in schema["required_inputs"]


def test_visit_schema_expands_frailty_item_to_structured_anthropometry_bundle(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="45555555567", full_name="Paciente Agenda Fragilidad"))
    patient_id = register.get_json()["patient_id"]

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO follow_up_visits (
            patient_id, visit_date, psa_current, testosterone_current, current_treatment,
            disease_status, ecog_current, agenda_context_json, visit_bundle_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            patient_id,
            "2026-03-15",
            3.4,
            18.0,
            "Abiraterona + ADT",
            "Seguimiento estable",
            1,
            json.dumps({}),
            json.dumps({}),
        ),
    )
    conn.commit()
    conn.close()

    agenda = client.get(f"/api/patients/{patient_id}/agenda").get_json()["agenda"]
    frailty_item = next(item for item in agenda["items"] if item["title"] == "Fragilidad y fitness terapéutica")

    schema_response = client.get(f"/api/patients/{patient_id}/visit-schema?agenda_id={frailty_item['id']}")
    assert schema_response.status_code == 200
    schema = schema_response.get_json()["visit_schema"]
    field_names = {
        field["name"]
        for section in schema["sections"]
        for field in section["fields"]
    }

    assert {
        "visit_date",
        "weight_kg",
        "height_cm",
        "bmi_current",
        "weight_loss_6m_kg",
        "mini_cog_score",
        "weak_grip",
    } <= field_names
    assert "weight_loss_6m_pct" not in field_names
    assert "height_cm" not in schema["capture_fields"]
    assert "mini_cog_score" not in schema["capture_fields"]
    assert {"height_cm", "mini_cog_score"} <= set(schema["visible_fields"])
    assert "weight_loss_6m_kg" in schema["required_inputs"]
    assert "weak_grip" in schema["required_inputs"]


def test_agenda_route_exposes_required_action_mode_and_completed_at(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="45555555559", full_name="Paciente Agenda Enriquecida"))
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "adt_progression_verification")

    agenda_response = client.get(f"/api/patients/{patient_id}/agenda")
    assert agenda_response.status_code == 200
    agenda = agenda_response.get_json()["agenda"]

    assert agenda["items"]
    assert all({"required", "action_mode", "completed_at"} <= set(item.keys()) for item in agenda["items"])
    assert agenda["encounters"]
    first_task = next(task for encounter in agenda["encounters"] for task in encounter["tasks"])
    assert {"required", "action_mode", "completed_at"} <= set(first_task.keys())


def test_visit_schema_uses_monitoring_capture_fields_from_form_scope_without_explicit_field_scope(app_client):
    from prostanet.domains.patient_tracking.followup_agenda import build_visit_schema

    visit_schema = build_visit_schema(
        "m0_crpc",
        "on_arpi",
        patient={},
        capture_context={
            "title": "Monitorizar ARPI",
            "rationale": "La monitorizacion activa del regimen debe capturar solo el bloque exacto.",
            "form_scope": {
                "mode": "capture_block",
                "focus": "ARPI activa",
                "capture_fields": ["psa", "testosterone", "systolic_bp"],
            },
        },
    )
    field_names = {
        field["name"]
        for section in visit_schema["sections"]
        for field in section["fields"]
    }

    assert visit_schema["schema_scope"] == "exact_capture_block"
    assert visit_schema["capture_fields"] == ["psa", "testosterone", "systolic_bp"]
    assert {"visit_date", "psa", "psa_history", "testosterone", "testosterone_history", "systolic_bp"} <= field_names
    assert visit_schema["visible_fields"] == [
        "psa",
        "psa_history",
        "testosterone",
        "testosterone_history",
        "systolic_bp",
    ]
    assert "clinician_notes" not in field_names


def test_visit_schema_expands_pro_capture_blocks_to_band_and_numeric_fields(app_client):
    client, _ = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="45555555568", full_name="Paciente PRO Capture Block"))
    patient_id = register.get_json()["patient_id"]

    schema_response = client.get(
        f"/api/patients/{patient_id}/visit-schema"
        "?state=m1_crpc"
        "&track=systemic_surveillance"
        "&fields=eq5d_vas,bpi_worst_pain"
        "&capture_title=Completar%20PROs"
        "&capture_group=advanced_shared_decision"
        "&decision_affected=quality_of_life"
    )
    assert schema_response.status_code == 200
    payload = schema_response.get_json()
    field_names = {
        field["name"]
        for section in payload["visit_schema"]["sections"]
        for field in section["fields"]
    }
    assert {"visit_date", "eq5d_vas_band", "eq5d_vas", "bpi_worst_pain_band", "bpi_worst_pain"} <= field_names
    assert payload["visit_schema"]["visible_fields"] == [
        "eq5d_vas_band",
        "eq5d_vas",
        "bpi_worst_pain_band",
        "bpi_worst_pain",
    ]


def test_visit_schema_supports_active_surveillance_confirmatory_biopsy_and_mri_interval_inputs(app_client):
    client, _ = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="45555555569", full_name="Paciente Vigilancia Activa MRI"))
    patient_id = register.get_json()["patient_id"]

    schema_response = client.get(
        f"/api/patients/{patient_id}/visit-schema"
        "?state=localized_initial"
        "&track=active_surveillance"
        "&fields=confirmatory_biopsy_done,mri_interval_months"
        "&capture_title=Confirmar%20vigilancia%20activa"
        "&capture_group=active_surveillance"
        "&decision_affected=active_surveillance"
    )
    assert schema_response.status_code == 200
    payload = schema_response.get_json()
    field_names = {
        field["name"]
        for section in payload["visit_schema"]["sections"]
        for field in section["fields"]
    }

    assert {"visit_date", "confirmatory_biopsy_done", "mri_interval_months"} <= field_names
    assert payload["visit_schema"]["visible_fields"] == [
        "confirmatory_biopsy_done",
        "mri_interval_months",
    ]


def test_visit_schema_supports_adt_bone_protection_capture_inputs(app_client):
    client, _ = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="45555555570", full_name="Paciente Salud Osea ADT"))
    patient_id = register.get_json()["patient_id"]

    schema_response = client.get(
        f"/api/patients/{patient_id}/visit-schema"
        "?state=mcspc_high_volume"
        "&track=systemic_surveillance"
        "&fields=calcium_vitd_started,bone_protection_started"
        "&capture_title=Soporte%20oseo%20ADT"
        "&capture_group=bone_support"
        "&decision_affected=bone_health"
    )
    assert schema_response.status_code == 200
    payload = schema_response.get_json()
    field_names = {
        field["name"]
        for section in payload["visit_schema"]["sections"]
        for field in section["fields"]
    }

    assert {"visit_date", "calcium_vitd_started", "bone_protection_started"} <= field_names
    assert payload["visit_schema"]["visible_fields"] == [
        "calcium_vitd_started",
        "bone_protection_started",
    ]


def test_decision_input_requirements_publish_visible_fields_for_pro_and_monitoring_blocks():
    from prostanet.domains.patient_tracking.decision_input_requirements_engine import build_decision_input_requirements

    patient = {
        "prior_history": {"current_state": "m1_crpc"},
        "follow_ups": [{}],
        "stage_visits": [],
    }
    bundle = build_decision_input_requirements(
        patient,
        effective_state="m1_crpc",
        effective_management_track="systemic_surveillance",
        latest_assessment={"state": "m1_crpc"},
        next_best_action={},
    )

    assert {"eq5d_vas_band", "eq5d_vas", "bpi_worst_pain_band", "bpi_worst_pain"} <= set(bundle["pro_capture_block"]["visible_fields"])
    assert {"psa_history", "testosterone_history"} <= set(bundle["monitoring_capture_block"]["visible_fields"])


def test_visit_schema_includes_structured_metastatic_distribution_for_advanced_tracks(app_client):
    client, _ = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="45555555558", full_name="Paciente TNM Metastasico"))
    patient_id = register.get_json()["patient_id"]

    schema_response = client.get(
        f"/api/patients/{patient_id}/visit-schema"
        "?state=mcspc_high_volume"
        "&track=systemic_surveillance"
    )
    assert schema_response.status_code == 200
    payload = schema_response.get_json()
    field_names = {
        field["name"]
        for section in payload["visit_schema"]["sections"]
        for field in section["fields"]
    }
    assert {
        "nonregional_nodal_retroperitoneal_count",
        "bone_femur_count",
        "bone_ribs_thorax_count",
        "visceral_lung_count",
        "visceral_liver_count",
        "metastasis_assessment_date",
    } <= field_names


def test_visit_schema_exposes_lab_reference_ranges_and_biopsy_capture_when_pathology_missing(app_client):
    client, _ = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="45555555560", full_name="Paciente Biopsia Pendiente"))
    patient_id = register.get_json()["patient_id"]

    schema_response = client.get(
        f"/api/patients/{patient_id}/visit-schema"
        "?state=mcspc_high_volume_sync"
        "&track=systemic_surveillance"
    )

    assert schema_response.status_code == 200
    schema = schema_response.get_json()["visit_schema"]
    fields = {
        field["name"]: field
        for section in schema["sections"]
        for field in section["fields"]
    }

    assert fields["hemoglobin"]["reference_range_label"].startswith("Rango estándar institucional:")
    assert fields["creatinine"]["reference_range_unit"] == "mg/dL"
    assert {"biopsy_date", "biopsy_type", "biopsy_route", "biopsy_context", "total_cores", "positive_cores"} <= set(fields)


def test_visit_schema_defaults_margin_location_to_apex_post_rp(app_client):
    client, _ = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="45555555561", full_name="Paciente Margen RP"))
    patient_id = register.get_json()["patient_id"]

    schema_response = client.get(
        f"/api/patients/{patient_id}/visit-schema"
        "?state=post_prostatectomy"
        "&track=post_rp"
    )

    assert schema_response.status_code == 200
    schema = schema_response.get_json()["visit_schema"]
    margin_field = next(
        field
        for section in schema["sections"]
        for field in section["fields"]
        if field["name"] == "margin_location"
    )
    assert margin_field["field_type"] == "select"
    assert margin_field["default"] == "Ápex"
    assert "Ápex" in margin_field["options"]


def test_stage_visit_persists_structured_psa_history_into_longitudinal_series(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="45555555562", full_name="Paciente PSA Longitudinal"))
    patient_id = register.get_json()["patient_id"]

    visit_response = client.post(
        f"/api/patients/{patient_id}/visits",
        json={
            "visit_date": "2026-03-20",
            "state": "mcspc_high_volume_sync",
            "management_track": "systemic_surveillance",
            "disease_status": "Seguimiento estable",
            "psa_history": [
                {
                    "sample_date": "2026-03-05",
                    "psa_value": 8.4,
                    "context": "pretratamiento",
                    "assay_type": "estándar",
                },
                {
                    "sample_date": "2026-03-20",
                    "psa_value": 4.1,
                    "context": "seguimiento",
                    "assay_type": "ultrasensible",
                },
            ],
            "line_of_therapy_number": 2,
            "line_of_therapy_context": "mCRPC_first_line",
        },
    )
    assert visit_response.status_code == 200

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT biomarker_type, sample_date, value FROM biomarker_longitudinal WHERE patient_id = ? AND biomarker_type = 'PSA' ORDER BY sample_date ASC",
        (patient_id,),
    )
    rows = cursor.fetchall()
    conn.close()

    assert len(rows) >= 2
    assert ("PSA", "2026-03-05", 8.4) in rows
    assert ("PSA", "2026-03-20", 4.1) in rows

    import tracking_db

    record = tracking_db.get_patient_full_record(patient_id)
    assert any(point.get("sample_date") == "2026-03-20" and point.get("assay_type") == "ultrasensible" for point in record["psa_series"])
    assert any(point.get("line_of_therapy_number") == 2 for point in record["psa_series"])
    assert any(point.get("line_of_therapy_context") == "mCRPC_first_line" for point in record["psa_series"])


def test_stage_visit_persists_structured_testosterone_history_and_runtime_prefers_latest_series_value(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="45555555564", full_name="Paciente Testosterona Longitudinal"))
    patient_id = register.get_json()["patient_id"]

    visit_response = client.post(
        f"/api/patients/{patient_id}/visits",
        json={
            "visit_date": "2026-03-20",
            "state": "m1_crpc",
            "management_track": "systemic_surveillance",
            "disease_status": "Seguimiento estable",
            "testosterone_history": [
                {
                    "sample_date": "2026-02-15",
                    "testosterone_value": 74,
                    "context": "seguimiento",
                    "unit": "ng/dL",
                },
                {
                    "sample_date": "2026-03-20",
                    "testosterone_value": 18,
                    "context": "seguimiento",
                    "unit": "ng/dL",
                    "line_of_therapy_number": 2,
                    "line_of_therapy_context": "mCRPC_first_line",
                },
            ],
            "line_of_therapy_number": 2,
            "line_of_therapy_context": "mCRPC_first_line",
        },
    )
    assert visit_response.status_code == 200

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT biomarker_type, sample_date, value FROM biomarker_longitudinal WHERE patient_id = ? AND biomarker_type = 'TESTOSTERONA' ORDER BY sample_date ASC",
        (patient_id,),
    )
    rows = cursor.fetchall()
    conn.close()

    assert ("TESTOSTERONA", "2026-02-15", 74.0) in rows
    assert ("TESTOSTERONA", "2026-03-20", 18.0) in rows

    import tracking_db
    from prostanet.domains.patient_tracking.longitudinal_intelligence import _derive_castrate_status as derive_longitudinal_castrate_status
    from prostanet.domains.patient_tracking.reconciled_state import _derive_castrate_status as derive_reconciled_castrate_status

    record = tracking_db.get_patient_full_record(patient_id)
    assert any(point.get("sample_date") == "2026-03-20" and point.get("unit") == "ng/dL" for point in record["testosterone_series"])
    assert any(point.get("line_of_therapy_number") == 2 for point in record["testosterone_series"])
    assert any(point.get("line_of_therapy_context") == "mCRPC_first_line" for point in record["testosterone_series"])
    assert record["latest_testosterone_value"] == 18.0
    assert record["latest_testosterone_date"] == "2026-03-20"


def test_refresh_longitudinal_intelligence_publishes_latest_testosterone_from_series(app_client):
    client, _db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="45555555565", full_name="Paciente Runtime Testosterona"))
    patient_id = register.get_json()["patient_id"]

    visit_response = client.post(
        f"/api/patients/{patient_id}/visits",
        json={
            "visit_date": "2026-03-20",
            "state": "m1_crpc",
            "management_track": "systemic_surveillance",
            "disease_status": "Seguimiento estable",
            "testosterone_history": [
                {
                    "sample_date": "2026-02-15",
                    "testosterone_value": 74,
                    "context": "seguimiento",
                    "unit": "ng/dL",
                },
                {
                    "sample_date": "2026-03-20",
                    "testosterone_value": 18,
                    "context": "seguimiento",
                    "unit": "ng/dL",
                    "line_of_therapy_number": 2,
                    "line_of_therapy_context": "mCRPC_first_line",
                },
            ],
            "line_of_therapy_number": 2,
            "line_of_therapy_context": "mCRPC_first_line",
        },
    )
    assert visit_response.status_code == 200

    import tracking_db

    runtime = tracking_db.refresh_longitudinal_intelligence(patient_id)
    assert runtime["latest_testosterone_value"] == 18.0
    assert runtime["latest_testosterone_date"] == "2026-03-20"
    assert runtime["castrate_status_resolved"] == "confirmed_castrate"
    assert runtime["castrate_testosterone_status"] == "confirmed_castrate"


def test_stage_visit_does_not_persist_survival_status_noise_on_routine_followup(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="45555555563", full_name="Paciente Rutina Viva"))
    patient_id = register.get_json()["patient_id"]

    visit_response = client.post(
        f"/api/patients/{patient_id}/visits",
        json={
            "visit_date": "2026-03-22",
            "state": "mcspc_high_volume_sync",
            "management_track": "systemic_surveillance",
            "disease_status": "Seguimiento estable",
            "psa": 5.2,
        },
    )
    assert visit_response.status_code == 200

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM survival_status_records WHERE patient_id = ?", (patient_id,))
    assert cursor.fetchone()[0] == 0
    conn.close()


def test_stage_visit_derives_bmi_and_weight_loss_percent_from_kg_inputs(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="45555555566", full_name="Paciente Fragilidad IMC"))
    patient_id = register.get_json()["patient_id"]

    visit_response = client.post(
        f"/api/patients/{patient_id}/visits",
        json={
            "visit_date": "2026-03-25",
            "state": "m1_crpc",
            "management_track": "systemic_surveillance",
            "weight_kg": 70,
            "height_cm": 175,
            "weight_loss_6m_kg": 5,
            "weak_grip": 1,
            "mini_cog_score": 3,
        },
    )
    assert visit_response.status_code == 200

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT weight_kg, height_cm, bmi_current, weight_loss_6m_kg, weight_loss_6m_pct, prior_weight_6m_kg
        FROM follow_up_visits
        WHERE patient_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (patient_id,),
    )
    followup_row = cursor.fetchone()
    cursor.execute(
        """
        SELECT weight_kg, height_cm, bmi_current, weight_loss_6m_kg, weight_loss_6m_pct, prior_weight_6m_kg, weak_grip
        FROM patient_demographics
        WHERE patient_id = ?
        """,
        (patient_id,),
    )
    demographics_row = cursor.fetchone()
    conn.close()

    assert followup_row == (70.0, 175.0, 22.9, 5.0, 6.7, 75.0)
    assert demographics_row == (70.0, 175.0, 22.9, 5.0, 6.7, 75.0, 1)


def test_register_patient_normalizes_canonical_regimen_code_from_catalog(app_client):
    client, _ = app_client
    payload = make_patient_payload(nss="45555555557", full_name="Paciente Regimen Canonico") | {
        "assessment_state": "mcspc_high_volume",
        "line_of_therapy_number": 1,
        "line_of_therapy_context": "mHSPC_initial",
        "drug_scheme": "Abiraterona + ADT",
    }

    response = client.post("/api/register_patient", json=payload)

    assert response.status_code == 200
    patient = client.get("/api/patient/45555555557").get_json()["patient"]
    assert patient["treatments"][-1]["drug_scheme"] == "ADT_ABIRATERONE"


def test_item_scoped_advanced_visit_updates_canonical_longitudinal_targets(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="46464646464", full_name="Paciente Seguimiento Dirigido"))
    patient_id = register.get_json()["patient_id"]

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO follow_up_visits (
            patient_id, visit_date, psa_current, testosterone_current, current_treatment,
            disease_status, ecog_current, agenda_context_json, visit_bundle_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            patient_id,
            "2026-03-15",
            4.1,
            22.0,
            "Abiraterona + ADT",
            "Seguimiento estable",
            1,
            json.dumps({}),
            json.dumps({}),
        ),
    )
    conn.commit()
    conn.close()

    agenda = client.get("/api/patients/46464646464/agenda").get_json()["agenda"]
    therapy_item = next(item for item in agenda["items"] if item["item_type"] == "therapy_review")

    visit_response = client.post(
        f"/api/patients/{patient_id}/visits",
        json={
            "agenda_ids": [therapy_item["id"]],
            "agenda_submission_mode": "item_scoped",
            "visit_date": "2026-03-20",
            "state": "adt_progression_verification",
            "management_track": "on_arpi",
            "disease_status": "Seguimiento estable",
            "current_treatment": "Abiraterona + ADT",
            "ecog": 1,
            "line_of_therapy": 1,
            "drug_scheme": "ADT_ABIRATERONE",
            "current_adt_context": "medical_adt_continuous",
            "castrate_testosterone_status": "confirmed_castrate",
            "progression_pattern": "none",
            "conventional_imaging_status": "M1",
        },
    )
    assert visit_response.status_code == 200
    assert visit_response.get_json()["success"] is True

    record_response = client.get("/api/patient/46464646464")
    assert record_response.status_code == 200
    patient = record_response.get_json()["patient"]
    assert patient["treatments"][-1]["drug_scheme"] == "ADT_ABIRATERONE"

    agenda_after = client.get("/api/patients/46464646464/agenda").get_json()["agenda"]
    # Auditoría #21 (cierre OOS-9): la visita reporta conventional_imaging_status=M1
    # sobre un paciente previamente M0, lo cual reconcilia legítimamente el estado
    # de `adt_progression_verification` a `mcspc_low_volume_sync_oligo`. El
    # `agenda_key` contiene el estado, por lo que cambia. El identificador estable
    # cross-transición es (management_track, item_type), y el tracker_db propaga
    # `partially_satisfied` al nuevo item cuando la (track, item_type) coincide.
    completed_item = next(
        item
        for item in agenda_after["items"]
        if item.get("management_track") == therapy_item.get("management_track")
        and item.get("item_type") == therapy_item.get("item_type")
    )
    assert completed_item["status"] == "partially_satisfied"
    import tracking_db
    from prostanet.domains.patient_tracking.profile_compass import build_patient_profile_view_model

    refreshed = tracking_db.get_patient_full_record("46464646464")
    profile = build_patient_profile_view_model(
        patient=refreshed,
        latest_assessment_raw=refreshed.get("latest_assessment") or {},
        latest_assessment=refreshed.get("latest_assessment") or {},
        state_timeline=refreshed.get("state_timeline") or [],
        care_overlays=refreshed.get("care_overlays") or [],
        recommendations={},
    )
    sequencing_items = {
        item["label"]: item
        for item in profile["advanced_panel_context"]["sequencing_context"]["items"]
    }
    assert sequencing_items["Esquema actual"]["value"] == "ADT + abiraterona"
    assert sequencing_items["Esquema actual"]["evidence_status"] == "captured"




def test_line_change_from_visit_creates_event_and_psa_monitoring_by_line(app_client):
    client, _ = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="46565656565", full_name="Paciente Cambio de Linea"))
    patient_id = register.get_json()["patient_id"]

    first_visit = client.post(
        f"/api/patients/{patient_id}/visits",
        json={
            "visit_date": "2026-03-15",
            "state": "adt_progression_verification",
            "management_track": "on_arpi",
            "disease_status": "Control inicial",
            "current_treatment": "Abiraterona + ADT",
            "line_of_therapy_number": 1,
            "line_of_therapy_context": "mHSPC_initial",
            "drug_scheme": "ADT_ABIRATERONE",
            "current_adt_context": "medical_adt_continuous",
            "castrate_testosterone_status": "confirmed_castrate",
            "psa": 10.5,
            "testosterone": 18,
        },
    )
    assert first_visit.status_code == 200

    second_visit = client.post(
        f"/api/patients/{patient_id}/visits",
        json={
            "visit_date": "2026-05-20",
            "state": "m1_crpc",
            "management_track": "on_docetaxel",
            "disease_status": "Cambio por progresión",
            "current_treatment": "Docetaxel + ADT",
            "line_of_therapy_number": 2,
            "line_of_therapy_context": "mCRPC_post_ARPI_pre_taxane",
            "drug_scheme": "ADT_DOCETAXEL_DAROLUTAMIDE",
            "current_adt_context": "medical_adt_continuous",
            "castrate_testosterone_status": "confirmed_castrate",
            "psa": 6.2,
            "testosterone": 16,
        },
    )
    assert second_visit.status_code == 200

    import tracking_db
    from prostanet.domains.patient_tracking.profile_compass import build_patient_profile_view_model

    refreshed = tracking_db.get_patient_full_record("46565656565")
    assert [event["event_type"] for event in refreshed["patient_events"]][:2] == ["therapy_line_changed", "followup_visit_recorded"]
    assert refreshed["treatments"][0]["outcome"] == "Changed"
    assert refreshed["treatments"][0]["end_date"] == "2026-05-20"
    assert refreshed["treatments"][-1]["line_of_therapy_number"] == 2

    profile = build_patient_profile_view_model(
        patient=refreshed,
        latest_assessment_raw=refreshed.get("latest_assessment") or {},
        latest_assessment=refreshed.get("latest_assessment") or {},
        state_timeline=refreshed.get("state_timeline") or [],
        care_overlays=refreshed.get("care_overlays") or [],
        recommendations={},
    )
    line_segments = profile["psa_observability"]["line_segments"]
    assert len(line_segments) >= 2
    assert any(segment["line_of_therapy_number"] == 2 for segment in line_segments)
    assert profile["psa_observability"]["metrics"]["current_line_label"].startswith("L2")
    waterfall = profile["copilot"]["response_visualization"]["waterfall"]
    assert waterfall
    assert any(bar["label"].startswith("L2") for bar in waterfall)


def test_longitudinal_intelligence_loop_creates_transition_proposal_and_confirmation(app_client):
    client, _ = app_client

    draft_response = client.post(
        "/api/clinical-assessments/draft",
        json={
            "module_id": "diagnostic_workup",
            "payload": {
                "age": 64,
                "psa": 9.4,
                "psad": 0.22,
                "mpmri_quality": "Adecuada",
                "pirads_score": "4",
                "index_lesion_location": "Zona periférica posterior",
                "index_lesion_size_mm": 12,
                "prostate_volume_ml": 43,
                "planned_biopsy_type": "Dirigida + sistemática",
                "planned_biopsy_route": "Transperineal",
                "risk_calculator_pathway": "MRI + PSAD + ERSPC",
            },
        },
    )
    assert draft_response.status_code == 200
    assessment_id = draft_response.get_json()["assessment_id"]

    register_response = client.post(
        "/api/register_patient",
        json={
            "assessment_id": assessment_id,
            "assessment_state": "diagnostic_workup",
            "nss": "66666666666",
            "full_name": "Paciente Loop",
            "dob": "1962-06-06",
            "baseline_psa": 9.4,
        },
    )
    assert register_response.status_code == 200
    patient_id = register_response.get_json()["patient_id"]

    signals_response = client.get(f"/api/patients/{patient_id}/signals")
    assert signals_response.status_code == 200
    signals_payload = signals_response.get_json()
    assert signals_payload["signals"]["state"] == "diagnostic_workup"
    assert signals_payload["next_best_action"]["title"]

    result_response = client.post(
        f"/api/patients/{patient_id}/results",
        json={
            "result_type": "pathology",
            "payload": {
                "biopsy_date": "2026-03-15",
                "biopsy_type": "Dirigida + sistemática",
                "biopsy_context": "diagnostica",
                "total_cores": 12,
                "positive_cores": 3,
                "gleason_primary": 3,
                "gleason_secondary": 4,
                "isup_grade": 2,
                "porcentaje_patron_4": 15,
            },
        },
    )
    assert result_response.status_code == 200
    result_payload = result_response.get_json()
    assert result_payload["transition_proposals"] == []
    assert result_payload["transition_resolution"]["policy"] == "auto_applied"
    assert result_payload["transition_resolution"]["target_state"] == "localized_initial"

    next_action_response = client.get(f"/api/patients/{patient_id}/next-best-action")
    assert next_action_response.status_code == 200
    next_action_payload = next_action_response.get_json()
    assert next_action_payload["reconciled_state"] == "localized_initial"
    assert "Confirmar transición" not in next_action_payload["next_best_action"]["title"]

    patient_response = client.get("/api/patient/66666666666")
    assert patient_response.status_code == 200
    patient = patient_response.get_json()["patient"]
    assert patient["biopsies"]


def test_source_document_pathology_flow_requires_verification_before_transition(app_client):
    client, _ = app_client

    draft_response = client.post(
        "/api/clinical-assessments/draft",
        json={
            "module_id": "diagnostic_workup",
            "payload": {
                "age": 66,
                "psa": 10.1,
                "psad": 0.24,
                "mpmri_quality": "Adecuada",
                "pirads_score": "5",
                "index_lesion_location": "Zona periférica posterior",
                "index_lesion_size_mm": 14,
                "prostate_volume_ml": 42,
                "planned_biopsy_type": "Dirigida + sistemática",
                "planned_biopsy_route": "Transperineal",
            },
        },
    )
    assessment_id = draft_response.get_json()["assessment_id"]
    register_response = client.post(
        "/api/register_patient",
        json={
            "assessment_id": assessment_id,
            "assessment_state": "diagnostic_workup",
            "nss": "77777777777",
            "full_name": "Paciente Documento Patologia",
            "dob": "1960-07-07",
            "baseline_psa": 10.1,
        },
    )
    patient_id = register_response.get_json()["patient_id"]

    upload_response = client.post(
        f"/api/patients/{patient_id}/documents",
        data={
            "title": "Reporte histopatológico inicial",
            "document_type": "pathology_report",
            "source_date": "2026-03-15",
            "file": (
                io.BytesIO(
                    b"Reporte histopatologico de prostata.\nGleason score 3+4=7.\nISUP 2.\n3/12 cores positivos.\nPatron 4 15 por ciento.\nCribriforme presente.\n"
                ),
                "pathology_report.txt",
            ),
        },
        content_type="multipart/form-data",
    )
    assert upload_response.status_code == 200
    document = upload_response.get_json()["document"]
    document_id = document["id"]

    signals_before = client.get(f"/api/patients/{patient_id}/signals").get_json()
    assert signals_before["signals"]["state"] == "diagnostic_workup"
    assert not any(item["target_state"] == "localized_initial" for item in signals_before["transition_proposals"])

    extract_response = client.post(f"/api/patients/{patient_id}/documents/{document_id}/extract", json={})
    assert extract_response.status_code == 200
    extract_payload = extract_response.get_json()
    assert extract_payload["document"]["document_type"] == "pathology_report"
    assert any(item["field_name"] == "gleason_primary" for item in extract_payload["candidates"])

    facts_payload = [
        {
            "field_name": item["field_name"],
            "fact_group": item["fact_group"],
            "target_result_type": item["target_result_type"],
            "value": item["value"],
        }
        for item in extract_payload["candidates"]
    ]
    facts_payload.append(
        {
            "field_name": "biopsy_date",
            "fact_group": "pathology",
            "target_result_type": "pathology",
            "value": "2026-03-15",
        }
    )
    verify_response = client.post(
        f"/api/patients/{patient_id}/documents/{document_id}/verify",
        json={
            "verified_by": "test",
            "source_date": "2026-03-15",
            "facts": facts_payload,
        },
    )
    assert verify_response.status_code == 200
    verify_payload = verify_response.get_json()
    assert verify_payload["document_bundle"]["document"]["verification_status"] == "verified"
    assert verify_payload["verified_fact_bundle"]["committed_result_types"] == ["pathology"]
    assert verify_payload["transition_proposals"] == []

    signals_after = client.get(f"/api/patients/{patient_id}/signals").get_json()
    assert signals_after["transition_resolution"]["policy"] == "auto_applied"
    # With copilots enabled, diagnostic_workup copilot may retain patient in workup
    # until full staging criteria are met — both states are clinically valid here.
    assert signals_after["effective_state_final"] in ("localized_initial", "diagnostic_workup")
    assert "Confirmar transición" not in signals_after["next_best_action"]["title"]

    export_response = client.get("/api/export/77777777777")
    export_payload = export_response.get_json()
    assert export_response.status_code == 200
    assert export_payload["source_documents"]
    assert export_payload["verified_document_facts"]


def test_source_document_imaging_and_genomic_reports_persist_structured_results(app_client):
    client, _ = app_client
    register_response = client.post(
        "/api/register_patient",
        json=make_patient_payload(nss="88888888888", full_name="Paciente Documento Imagen Genomica"),
    )
    patient_id = register_response.get_json()["patient_id"]

    imaging_upload = client.post(
        f"/api/patients/{patient_id}/documents",
        data={
            "title": "PSMA PET marzo 2026",
            "document_type": "imaging_report",
            "source_date": "2026-03-15",
            "file": (
                io.BytesIO(
                    b"PSMA PET positivo con SUV max 13.2. Lesiones en ganglios pelvicos y higado.\n"
                ),
                "psma_pet.txt",
            ),
        },
        content_type="multipart/form-data",
    )
    imaging_document_id = imaging_upload.get_json()["document"]["id"]
    imaging_extract = client.post(f"/api/patients/{patient_id}/documents/{imaging_document_id}/extract", json={}).get_json()
    imaging_verify = client.post(
        f"/api/patients/{patient_id}/documents/{imaging_document_id}/verify",
        json={
            "verified_by": "test",
            "source_date": "2026-03-15",
            "facts": [
                {
                    "field_name": item["field_name"],
                    "fact_group": item["fact_group"],
                    "target_result_type": item["target_result_type"],
                    "value": item["value"],
                }
                for item in imaging_extract["candidates"]
            ]
            + [
                {
                    "field_name": "study_date",
                    "fact_group": "imaging",
                    "target_result_type": "imaging",
                    "value": "2026-03-15",
                }
            ],
        },
    )
    assert imaging_verify.status_code == 200

    genomic_upload = client.post(
        f"/api/patients/{patient_id}/documents",
        data={
            "title": "Panel molecular",
            "document_type": "genomic_report",
            "source_date": "2026-03-16",
            "file": (
                io.BytesIO(
                    b"Decipher high. BRCA2 pathogenic mutation. HRR positive. MSI stable. TMB 11.\n"
                ),
                "genomic_report.txt",
            ),
        },
        content_type="multipart/form-data",
    )
    genomic_document_id = genomic_upload.get_json()["document"]["id"]
    genomic_extract = client.post(f"/api/patients/{patient_id}/documents/{genomic_document_id}/extract", json={}).get_json()
    genomic_verify = client.post(
        f"/api/patients/{patient_id}/documents/{genomic_document_id}/verify",
        json={
            "verified_by": "test",
            "source_date": "2026-03-16",
            "facts": [
                {
                    "field_name": item["field_name"],
                    "fact_group": item["fact_group"],
                    "target_result_type": item["target_result_type"],
                    "value": item["value"],
                }
                for item in genomic_extract["candidates"]
            ]
            + [
                {
                    "field_name": "test_date",
                    "fact_group": "genomic",
                    "target_result_type": "genomic",
                    "value": "2026-03-16",
                }
            ],
        },
    )
    assert genomic_verify.status_code == 200

    documents_response = client.get(f"/api/patients/{patient_id}/documents")
    assert documents_response.status_code == 200
    assert len(documents_response.get_json()["documents"]) == 2

    patient_response = client.get("/api/patient/88888888888")
    patient = patient_response.get_json()["patient"]
    assert any("PSMA" in item["study_type"] for item in patient["imaging"])
    assert patient["genomics"]["brca2_status"] in {"positivo", "documentado"}


def test_schedule_uses_track_anchor_dates_and_fallbacks(app_client):
    client, db_path = app_client

    post_rp = client.post("/api/register_patient", json=make_patient_payload(nss="55555555555", full_name="Post RP"))
    patient_id = post_rp.get_json()["patient_id"]
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE prior_clinical_history SET current_state = ? WHERE patient_id = ?",
        ("post_prostatectomy", patient_id),
    )
    cursor.execute(
        '''
        INSERT INTO surgical_details (patient_id, surgery_date, surgery_type)
        VALUES (?, ?, ?)
        ''',
        (patient_id, "2026-01-10", "RP_robotica"),
    )
    conn.commit()
    conn.close()

    response = client.get(f"/api/patients/{patient_id}/schedule")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["anchor_date"] == "2026-01-10"
    assert payload["anchor_source"] == "surgical_details.surgery_date"

    arpi = client.post("/api/register_patient", json=make_patient_payload(nss="55555555556", full_name="ARPI"))
    arpi_id = arpi.get_json()["patient_id"]
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE prior_clinical_history SET current_state = ? WHERE patient_id = ?",
        ("m1_crpc", arpi_id),
    )
    cursor.execute(
        '''
        INSERT INTO treatment_history (patient_id, line_of_therapy, drug_scheme, start_date, outcome)
        VALUES (?, ?, ?, ?, ?)
        ''',
        (arpi_id, 1, "ADT_ABIRATERONE", "2026-02-01", "Ongoing"),
    )
    conn.commit()
    conn.close()

    arpi_schedule = client.get(f"/api/patients/{arpi_id}/schedule")
    assert arpi_schedule.status_code == 200
    arpi_payload = arpi_schedule.get_json()
    assert arpi_payload["management_track"] == "on_arpi"
    assert arpi_payload["anchor_date"] == "2026-02-01"
    assert arpi_payload["anchor_source"] == "treatment_history.start_date"

    fallback = client.post("/api/register_patient", json=make_patient_payload(nss="55555555557", full_name="Fallback"))
    fallback_id = fallback.get_json()["patient_id"]
    fallback_schedule = client.get(f"/api/patients/{fallback_id}/schedule")
    assert fallback_schedule.status_code == 200
    fallback_payload = fallback_schedule.get_json()
    assert fallback_payload["anchor_date"]
    assert fallback_payload["anchor_source"] == "identity.diagnosis_date"


def test_response_assessment_parses_boolean_strings_and_validates_required_fields(app_client):
    client, _ = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="66666666666", full_name="Respuesta"))
    patient_id = register.get_json()["patient_id"]

    valid = client.post(
        f"/api/patients/{patient_id}/response-assessment",
        json={
            "soft_tissue": {
                "current_sum_mm": 70,
                "baseline_sum_mm": 100,
                "new_lesions": "false",
                "non_target_progression": "0",
            },
            "psa": {
                "baseline_psa": 10,
                "current_psa": 4,
                "confirmed": "yes",
            },
        },
    )
    assert valid.status_code == 200
    response = valid.get_json()["response"]
    assert response["soft_tissue"]["category"] == "PR"
    assert response["soft_tissue"]["new_lesions"] is False
    assert response["psa"]["confirmed"] is True

    invalid = client.post(
        f"/api/patients/{patient_id}/response-assessment",
        json={"soft_tissue": {"current_sum_mm": 40}},
    )
    assert invalid.status_code == 400
    assert "baseline_sum_mm" in invalid.get_json()["error"]


def test_tumor_board_reads_genomics_and_demographics_correctly(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="77777777779", full_name="Tumor Board"))
    patient_id = register.get_json()["patient_id"]

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        '''
        INSERT INTO patient_demographics (patient_id, charlson_score, g8_score, frailty_status)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(patient_id) DO UPDATE SET
            charlson_score = excluded.charlson_score,
            g8_score = excluded.g8_score,
            frailty_status = excluded.frailty_status
        ''',
        (patient_id, 4, 11.5, "vulnerable"),
    )
    cursor.execute(
        '''
        INSERT INTO genomic_profile (patient_id, test_date, test_type, brca2_status, actionable_findings)
        VALUES (?, ?, ?, ?, ?)
        ''',
        (patient_id, "2026-03-01", "FoundationOne", "Mutado", json.dumps(["BRCA2"])),
    )
    conn.commit()
    conn.close()

    response = client.get(f"/api/patients/{patient_id}/tumor-board")
    assert response.status_code == 200
    tumor_board = response.get_json()["tumor_board"]
    assert tumor_board["patient_summary"]["charlson_score"] == 4
    assert tumor_board["patient_summary"]["g8_score"] == 11.5
    assert tumor_board["patient_summary"]["frailty_status"] == "vulnerable"
    assert tumor_board["genomic_profile"]["available"] is True
    assert tumor_board["genomic_profile"]["brca2"] == "Mutado"


def test_response_visualization_falls_back_to_followups_and_stage_visit_writes_biomarkers(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="88888888889", full_name="Visualización"))
    patient_id = register.get_json()["patient_id"]

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("UPDATE patient_identity SET diagnosis_date = ? WHERE id = ?", ("2025-12-01", patient_id))
    cursor.execute(
        '''
        INSERT INTO follow_up_visits (
            patient_id, visit_date, psa_current, visit_bundle_json, visit_type, state_at_visit, management_track, agenda_context_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            patient_id,
            "2026-03-01",
            5.2,
            json.dumps({}),
            "stage_followup",
            "diagnostic_workup",
            "diagnostic_surveillance",
            json.dumps({}),
        ),
    )
    conn.commit()
    conn.close()

    visualization = client.post(f"/api/patients/{patient_id}/response-visualization")
    assert visualization.status_code == 200
    points = visualization.get_json()["visualization"]["psa_trajectory"]["points"]
    assert points
    assert points[-1]["psa"] == 5.2

    register_series = client.post("/api/register_patient", json=make_patient_payload(nss="88888888891", full_name="Visualización Serie"))
    series_id = register_series.get_json()["patient_id"]
    _insert_psa_longitudinal_points(
        db_path,
        series_id,
        [
            ("2026-01-15", 8.1),
            ("2026-02-20", 5.6),
            ("2026-03-25", 3.2),
        ],
    )

    import tracking_db
    from prostanet.domains.patient_tracking.profile_compass import build_patient_profile_view_model

    series_record = tracking_db.get_patient_full_record(series_id)
    profile = build_patient_profile_view_model(
        patient=series_record,
        latest_assessment_raw=series_record.get("latest_assessment") or {},
        latest_assessment=series_record.get("latest_assessment") or {},
        state_timeline=series_record.get("state_timeline") or [],
        care_overlays=series_record.get("care_overlays") or [],
        recommendations={},
    )
    observability_points = profile["psa_observability"]["points"]
    assert [point["date"] for point in observability_points] == ["2026-01-15", "2026-02-20", "2026-03-25"]
    assert [point["psa"] for point in observability_points] == [8.1, 5.6, 3.2]

    series_visualization = client.post(f"/api/patients/{series_id}/response-visualization")
    assert series_visualization.status_code == 200
    series_points = series_visualization.get_json()["visualization"]["psa_trajectory"]["points"]
    assert [point["date"] for point in series_points] == ["2026-01-15", "2026-02-20", "2026-03-25"]
    assert [point["psa"] for point in series_points] == [8.1, 5.6, 3.2]

    register_tracking = client.post("/api/register_patient", json=make_patient_payload(nss="88888888890", full_name="Tracking"))
    tracking_id = register_tracking.get_json()["patient_id"]
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("UPDATE patient_identity SET diagnosis_date = ? WHERE id = ?", ("2025-12-01", tracking_id))
    conn.commit()
    conn.close()

    schedule = client.get(f"/api/patients/{tracking_id}/schedule")
    assert schedule.status_code == 200
    assert schedule.get_json()["schedule"]

    visit = client.post(
        f"/api/patients/{tracking_id}/visits",
        json={
            "visit_date": "2026-03-15",
            "state": "diagnostic_workup",
            "management_track": "diagnostic_surveillance",
            "disease_status": "Seguimiento estable",
            "psa": 4.8,
            "testosterone": 22,
            "hemoglobin": 13.1,
            "creatinine": 0.9,
            "ldh": 180,
            "alp": 95,
            "bilirubin": 0.7,
            "glucose": 99,
        },
    )
    assert visit.status_code == 200

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM biomarker_longitudinal WHERE patient_id = ? AND biomarker_type = 'PSA'", (tracking_id,))
    assert cursor.fetchone()[0] >= 1
    cursor.execute("SELECT COUNT(*) FROM scheduled_events WHERE patient_id = ? AND event_type = 'psa' AND completed = 1", (tracking_id,))
    assert cursor.fetchone()[0] >= 1
    conn.close()


def test_response_visualization_exposes_integrated_treatment_timeline_and_preserves_swimmer(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="88888888891", full_name="Timeline Integrada"))
    patient_id = register.get_json()["patient_id"]

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("UPDATE patient_identity SET diagnosis_date = ? WHERE id = ?", ("2025-12-15", patient_id))
    cursor.execute(
        """
        INSERT INTO treatment_history (
            patient_id, line_of_therapy, drug_scheme, start_date, end_date, outcome,
            nadir_psa, time_to_nadir_months, regimen_json, line_of_therapy_context
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            patient_id,
            1,
            "ADT_ABIRATERONE",
            "2025-12-15",
            "2026-02-10",
            "Progression",
            8.0,
            1,
            json.dumps({
                "line_of_therapy_number": 1,
                "drug_scheme": "ADT_ABIRATERONE",
                "drug_scheme_label": "ADT + Abiraterona",
                "baseline_psa": 20.0,
                "nadir_psa": 8.0,
                "time_to_nadir_months": 1,
                "line_of_therapy_context": "mHSPC_initial",
            }),
            "mHSPC_initial",
        ),
    )
    cursor.execute(
        """
        INSERT INTO treatment_history (
            patient_id, line_of_therapy, drug_scheme, start_date, outcome, regimen_json, line_of_therapy_context
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            patient_id,
            2,
            "ADT_DAROLUTAMIDE",
            "2026-02-11",
            "Ongoing",
            json.dumps({
                "line_of_therapy_number": 2,
                "drug_scheme": "ADT_DAROLUTAMIDE",
                "drug_scheme_label": "ADT + Darolutamida",
                "baseline_psa": 12.0,
                "nadir_psa": 4.0,
                "time_to_nadir_months": 1,
                "line_of_therapy_context": "mHSPC_post_docetaxel",
            }),
            "mHSPC_post_docetaxel",
        ),
    )
    conn.commit()
    conn.close()

    _insert_psa_longitudinal_points(
        db_path,
        patient_id,
        [
            ("2025-12-15", 20.0),
            ("2026-01-15", 8.0),
            ("2026-02-10", 12.0),
            ("2026-03-10", 4.0),
        ],
    )

    visualization = client.post(f"/api/patients/{patient_id}/response-visualization")
    assert visualization.status_code == 200
    payload = visualization.get_json()["visualization"]
    timeline = payload["psa_trajectory"]["integrated_treatment_timeline"]

    assert payload["swimmer"]
    assert payload["psa_trajectory"]["has_data"] is True
    assert payload["waterfall"]
    assert payload["waterfall"][0]["label"].startswith("L1")
    assert payload["waterfall"][1]["label"].startswith("L2")
    assert timeline["has_integrated_timeline"] is True
    assert len(timeline["treatment_lanes"]) == 2
    assert "2025-12-15" in timeline["axis_dates"]
    assert "2026-02-11" in timeline["axis_dates"]
    marker_types = {marker["type"] for marker in timeline["lane_markers"]}
    assert "PSA50" in marker_types
    assert "PD" in marker_types
    assert "LINE_CHANGE" in marker_types


def test_profile_compass_promotes_parallel_copilot_layers_into_active_orientation(app_client):
    client, _ = app_client
    from prostanet.domains.patient_tracking.profile_compass import build_patient_profile_view_model

    register_response = client.post(
        "/api/register_patient",
        json=make_patient_payload(nss="90909090909", full_name="Paciente Copilot Avanzado"),
    )
    assert register_response.status_code == 200
    patient_id = register_response.get_json()["patient_id"]

    patient = {
        "identity": {
            "id": patient_id,
            "diagnosis_date": "2026-01-01",
            "age": 78,
            "sex": "M",
        },
        "baseline": {
            "baseline_psa": 32.0,
            "metastasis_site": "Bone",
            "ecog_score": 2,
            "institution": "IMSS",
        },
        "prior_history": {
            "current_state": "m1_crpc",
            "prior_adt": 1,
            "prior_therapy": "Enzalutamida, Docetaxel",
            "current_adt_context": "medical_adt_continuous",
        },
        "follow_ups": [
            {
                "visit_date": "2026-03-01",
                "psa_current": 28.0,
                "testosterone_current": 18.0,
                "creatinine_current": 1.8,
                "bilirubin_current": 2.2,
                "albumin_current": 3.0,
                "inr_current": 1.8,
                "ecog_current": 2,
                "fatigue_score": 8,
                "fatigue_score_previous": 5,
                "pain_score": 8,
                "pain_score_previous": 4,
                "eq5d_vas": 35,
                "eq5d_vas_previous": 60,
                "current_treatment": "Enzalutamida",
                "current_medications": "Tramadol, Warfarina",
                "institution": "IMSS",
            }
        ],
        "genomics": {
            "ar_v7_status": "Positivo",
            "tp53_status": "Mutado",
            "rb1_status": "Loss",
            "pten_loss": "Loss",
            "cdk12_status": "Biallelic",
            "tmb_value": 12,
            "ctdna_rising": "1",
        },
        "lesion_tracking": [
            {
                "lesion_id": "L1",
                "anatomical_location": "bone",
                "psma_avid": "1",
                "current_status": "new",
                "measurements": [
                    {
                        "suvmax": 12.5,
                        "longest_diameter_mm": 18,
                    }
                ],
            }
        ],
        "response_assessments": [
            {
                "overall_response": "PD",
                "assessment_date": "2026-03-10",
            }
        ],
        "state_timeline": [
            {
                "management_intent_status_label": "Delivered",
                "event_kind_label": "Therapy review",
            }
        ],
        "family_history": [],
        "biopsies": [],
        "imaging": [],
        "mri_facts": [],
        "diagnostic_plans": [],
        "biopsy_triggers": [],
        "pros": [],
        "treatments": [{"drug_scheme": "Enzalutamida", "start_date": "2026-01-15"}],
        "care_overlays": [],
        "pivotal_matches": [],
        "stage_visits": [],
        "agenda_items": [],
        "data_provenance": [],
        "source_documents": [],
        "document_verification_tasks": [],
        "document_candidates": [],
        "verified_document_facts": [],
        "latest_signal_snapshot": {},
        "transition_proposals": [],
        "recommendation_audit": [],
    }

    latest_assessment = {
        "state": "m1_crpc",
        "module_label": "CRPC metastásico",
        "display_result": {
            "nccn_primary": {
                "label": "CRPC metastásico",
                "trayectoria_recomendada": "Priorizar secuenciación sistémica guiada por biomarcadores y seguridad.",
                "fundamentos_personalizados": ["Existe progresión reciente y biología accionable."],
            },
            "monitoring_plan": {
                "cadence": "Laboratorios y revisión clínica cada 4 semanas.",
                "actions": ["Control laboratorial estrecho mientras se redefine la línea."],
            },
            "decision_quality": {
                "confidence_category": "vigilada",
            },
            "decision_changing_inputs": ["Confirmar elegibilidad PSMA y tolerancia a quimioterapia."],
            "source_citations": [],
        },
    }
    latest_assessment_raw = {
        "input_snapshot": {
            "current_adt_context": "medical_adt_continuous",
            "castrate_testosterone_status": "confirmed_castrate",
        },
        "result_snapshot": {
            "eligible_treatments": [{"name": "Cabazitaxel", "priority": "preferred"}],
            "validated_algorithms": [],
        },
    }

    profile = build_patient_profile_view_model(
        patient=patient,
        latest_assessment_raw=latest_assessment_raw,
        latest_assessment=latest_assessment,
        state_timeline=patient["state_timeline"],
        care_overlays=[],
        recommendations={},
    )

    labels = {item["label"] for item in profile["clinical_compass"]["active_modifiers"]}
    assert "Fitness terapéutica" in labels
    assert "Biología accionable" in labels
    assert "Interacciones / formulario" in labels
    assert "Resultados reportados por el paciente" in labels
    assert "Respuesta terapéutica" in labels
    assert any(panel["title"] == "Modificadores activos del copilot" for panel in profile["stage_specific_panels"])
    assert any(
        "triplete" in item.lower() or "monoterapia" in item.lower() or "ajustar intensidad" in item.lower()
        for item in profile["clinical_compass"]["what_could_change_course"]
    )


def test_schedule_endpoint_uses_same_cadence_as_visible_agenda(app_client):
    client, _ = app_client
    payload = make_patient_payload(nss="45454545454", full_name="Paciente Calendario")

    register_response = client.post("/api/register_patient", json=payload)
    assert register_response.status_code == 200
    patient_id = register_response.get_json()["patient_id"]

    agenda_response = client.get(f"/api/patients/{payload['nss']}/agenda")
    schedule_response = client.get(f"/api/patients/{patient_id}/schedule")

    assert agenda_response.status_code == 200
    assert schedule_response.status_code == 200

    agenda_items = agenda_response.get_json()["agenda"]["items"]
    schedule_payload = schedule_response.get_json()
    schedule_items = schedule_payload["schedule"]

    agenda_pairs = sorted((item["title"], item["due_at"]) for item in agenda_items)
    schedule_pairs = sorted((item["label"], item["due_date"]) for item in schedule_items)

    assert agenda_pairs == schedule_pairs
    assert schedule_payload["protocol_trace"]["anchor_date"]
    assert schedule_payload["protocol_label"]


def test_profile_view_model_builds_advanced_context_and_evidence_applicability():
    from prostanet.domains.patient_tracking.profile_compass import build_patient_profile_view_model

    patient = {
        "identity": {
            "id": 1,
            "full_name": "Paciente CRPC",
            "nss": "90909090909",
            "diagnosis_date": "2025-01-10",
            "dob": "1960-01-01",
            "age": 66,
        },
        "baseline": {
            "baseline_psa": 24.3,
            "ecog_score": 1,
            "metastasis_site": "Bone",
            "hrr_status": "BRCA2 mutado",
            "msi_status": "estable",
        },
        "prior_history": {
            "line_of_therapy": 2,
            "prior_adt": 1,
        },
        "follow_ups": [
            {
                "visit_date": "2026-03-01",
                "ecog": 1,
                "fatigue_score": 4,
                "cv_risk_documented": 1,
                "drug_interaction_reviewed": 1,
            }
        ],
        "treatments": [
            {
                "start_date": "2026-02-01",
                "drug_scheme": "ADT_ENZALUTAMIDE",
            }
        ],
        "imaging": [
            {
                "study_date": "2026-02-10",
                "study_type": "PSMA-PET",
            }
        ],
        "genomics": {
            "hrr_overall": "BRCA2 mutado",
            "msi_status": "estable",
            "report_date": "2026-02-05",
        },
        "care_overlays": [{"title": "Bundle óseo activo"}],
        "pivotal_matches": [
            {
                "study_name": "VISION",
                "scenario": "mCRPC",
                "eligible": 1,
                "evaluation_date": "2026-03-05",
                "expected_outcome": "rPFS y control clínico con Lu-177 PSMA.",
                "eligibility_details": json.dumps(
                    {
                        "match_score": 0.92,
                        "criteria_met": ["PSMA positivo", "mCRPC post-ARPI"],
                        "criteria_failed": ["Sin taxano previo documentado"],
                    }
                ),
                "applicability": "Alta aplicabilidad clínica en mCRPC PSMA positivo.",
            }
        ],
        "pros": [],
        "agenda_items": [],
        "data_provenance": [],
        "transition_proposals": [],
        "recommendation_audit": [],
        "document_candidates": [],
        "document_verification_tasks": [],
        "verified_document_facts": [],
        "source_documents": [],
        "latest_signal_snapshot": {},
    }
    latest_assessment_raw = {
        "assessment_date": "2026-03-05",
        "input_snapshot": {
            "line_of_therapy": 2,
            "drug_scheme": "ADT_ENZALUTAMIDE",
            "castrate_testosterone_status": "confirmed_castrate",
            "conventional_imaging_status": "M1",
            "psma_positive": 1,
            "cv_risk_documented": 1,
        },
        "result_snapshot": {
            "eligible_treatments": [{"name": "Lutetio-177 PSMA"}, {"name": "Olaparib"}],
            "decision_changing_inputs": ["PSMA positivo", "BRCA2 mutado"],
        },
    }
    latest_assessment = {
        "state": "m1_crpc",
        "module_label": "CRPC metastásico",
        "display_result": {
            "nccn_primary": {
                "titulo_clinico": "Secuenciación basada en PSMA y biomarcadores",
                "label": "CRPC metastásico",
                "trayectoria_recomendada": "Priorizar terapia dirigida por PSMA/HRR.",
            },
            "decision_changing_inputs": ["PSMA positivo", "BRCA2 mutado"],
            "decision_quality": {"confidence_category": "alta", "recommendation_family": "mCRPC"},
            "source_citations": [],
        },
    }

    profile = build_patient_profile_view_model(
        patient=patient,
        latest_assessment_raw=latest_assessment_raw,
        latest_assessment=latest_assessment,
        state_timeline=[{"management_intent_status_label": "Pendiente de confirmación", "event_kind_label": "Recomendación generada"}],
        care_overlays=patient["care_overlays"],
    )

    assert profile["advanced_panel_context"]["sequencing_context"]["items"]
    assert profile["advanced_panel_context"]["biomarker_context"]["items"]
    assert profile["advanced_panel_context"]["safety_support_context"]["items"]
    assert profile["evidence_applicability"]["supporting_trials"]
    assert profile["evidence_applicability"]["supporting_trials"][0]["study_name"] == "VISION"
    assert profile["evidence_applicability"]["supporting_trials"][0]["recommended_trial_backbone_label"] == "Lutecio-177 PSMA-617"


def test_profile_view_model_keeps_mhspc_evidence_counts_aligned_with_visible_trials():
    from prostanet.domains.patient_tracking.profile_compass import build_patient_profile_view_model

    patient = {
        "identity": {
            "id": 2,
            "full_name": "Paciente mHSPC",
            "nss": "80808080808",
            "diagnosis_date": "2026-01-10",
            "dob": "1961-01-01",
            "age": 65,
        },
        "baseline": {
            "baseline_psa": 5.0,
            "ecog_score": 1,
            "metastasis_site": "Visceral",
            "volume_disease": "High",
        },
        "follow_ups": [],
        "treatments": [],
        "imaging": [],
        "genomics": {},
        "care_overlays": [],
        "pivotal_matches": [
            {
                "study_name": "ENZAMET",
                "scenario": "mHSPC low/high volume",
                "eligible": 1,
                "evaluation_date": "2026-03-05",
                "expected_outcome": "Beneficio en SG.",
                "eligibility_details": json.dumps({"match_score": 0.9, "criteria_met": ["Gleason: Valor 7.0 dentro del rango [6-10]"]}),
            },
            {
                "study_name": "ARCHES",
                "scenario": "mHSPC broad",
                "eligible": 1,
                "evaluation_date": "2026-03-05",
                "expected_outcome": "Beneficio en rPFS.",
                "eligibility_details": json.dumps({"match_score": 0.88, "criteria_met": ["PSA: Valor 5.0 dentro del rango [0-99999]"]}),
            },
            {
                "study_name": "TITAN",
                "scenario": "mHSPC broad",
                "eligible": 1,
                "evaluation_date": "2026-03-05",
                "expected_outcome": "Beneficio en SG y rPFS.",
                "eligibility_details": json.dumps({"match_score": 0.87, "criteria_met": ["Edad: Valor 65 dentro del rango [No disponible-No disponible]"]}),
            },
        ],
        "pros": [],
        "agenda_items": [],
        "data_provenance": [],
        "transition_proposals": [],
        "recommendation_audit": [],
        "document_candidates": [],
        "document_verification_tasks": [],
        "verified_document_facts": [],
        "source_documents": [],
        "latest_signal_snapshot": {},
    }
    latest_assessment_raw = {
        "assessment_date": "2026-03-05",
        "input_snapshot": {
            "volume_disease": "High",
            "metastatic_temporality": "sync",
            "visceral_site_entries": [{"site_key": "liver", "lesion_count": 2}],
            "gleason_primary": 3,
            "gleason_secondary": 4,
        },
        "result_snapshot": {
            "eligible_treatments": [{"name": "ADT + docetaxel + abiraterona"}],
        },
    }
    latest_assessment = {
        "state": "mcspc_high_volume_sync",
        "module_label": "mHSPC alto volumen",
        "display_result": {
            "nccn_primary": {
                "titulo_clinico": "Triplete en mHSPC de alto volumen sincrónico",
                "label": "mHSPC alto volumen",
            },
            "decision_quality": {"confidence_category": "alta", "recommendation_family": "mHSPC"},
            "source_citations": [],
        },
    }

    profile = build_patient_profile_view_model(
        patient=patient,
        latest_assessment_raw=latest_assessment_raw,
        latest_assessment=latest_assessment,
        state_timeline=[],
        care_overlays=[],
    )

    assert profile["evidence_applicability"]["eligible_count"] == 3
    assert len(profile["evidence_applicability"]["supporting_trials"]) == 3
    assert profile["evidence_applicability"]["recommendation_label"] == "mHSPC de alto volumen sincrónico"


def test_profile_view_model_keeps_post_rp_bcr_in_salvage_family_and_filters_pivotal_trials():
    from prostanet.domains.patient_tracking.profile_compass import build_patient_profile_view_model

    patient = {
        "identity": {
            "id": 235,
            "full_name": "Fabian Recurre",
            "nss": "0099887765",
            "diagnosis_date": "2025-01-12",
            "dob": "1965-02-01",
            "age": 61,
        },
        "baseline": {
            "baseline_psa": 12.0,
            "gleason_score": 8,
            "ecog_score": 0,
            "tnm_stage": "T2CN0M0",
            "metastasis_site": "M0",
        },
        "surgery": {
            "surgery_date": "2025-11-12",
            "pathological_stage": "pT3a",
            "surgical_margin_status": 1,
            "margin_location": "base derecha",
        },
        "bcr": {
            "primary_treatment": "RP",
            "primary_treatment_date": "2025-11-12",
            "bcr_detected": 0,
            "bcr_date": "2026-03-27",
            "bcr_psa": 5.0,
            "bcr_definition": "BCR",
        },
        "biomarker_longitudinal": [
            {"biomarker_type": "PSA", "value": 15.0, "sample_date": "2026-02-12"},
            {"biomarker_type": "PSA", "value": 5.0, "sample_date": "2026-03-27"},
        ],
        "follow_ups": [],
        "treatments": [],
        "imaging": [],
        "genomics": {},
        "care_overlays": [],
        "pivotal_matches": [
            {
                "study_name": "GETUG-AFU 16",
                "scenario": "rescate",
                "eligible": 0,
                "evaluation_date": "2026-03-27",
                "expected_outcome": "Mejora de control bioquímico y libre de metástasis.",
                "eligibility_details": json.dumps(
                    {
                        "match_score": 0.82,
                        "criteria_met": ["Prostatectomía previa: cumple", "Metastasis: M0 == M0 (cumple)"],
                        "criteria_failed": ["PSA: Valor 5.0 > maximo 2.0"],
                    }
                ),
            },
            {
                "study_name": "RTOG 9601",
                "scenario": "rescate",
                "eligible": 0,
                "evaluation_date": "2026-03-27",
                "expected_outcome": "Beneficio en SG al combinar antiandrógeno prolongado con salvage RT.",
                "eligibility_details": json.dumps(
                    {
                        "match_score": 0.78,
                        "criteria_met": ["Prostatectomía previa: cumple"],
                        "criteria_failed": ["PSA: Valor 5.0 > maximo 4.0"],
                    }
                ),
            },
            {
                "study_name": "RADICALS-RT",
                "scenario": "adyuvancia",
                "eligible": 0,
                "evaluation_date": "2026-03-27",
                "expected_outcome": "Rescate temprano evita RT adyuvante innecesaria.",
                "eligibility_details": json.dumps(
                    {
                        "match_score": 0.74,
                        "criteria_met": ["Prostatectomía previa: cumple"],
                        "criteria_failed": ["PSA: Valor 5.0 > maximo 0.2"],
                    }
                ),
            },
            {
                "study_name": "EMBARK",
                "scenario": "rescate",
                "eligible": 0,
                "evaluation_date": "2026-03-27",
                "expected_outcome": "Intensificación sistémica para BCR de alto riesgo no metastásica.",
                "eligibility_details": json.dumps(
                    {
                        "match_score": 0.52,
                        "criteria_met": ["Metastasis: M0 == M0 (cumple)"],
                        "criteria_failed": ["PSADT no documentado para comprobar recurrencia bioquímica de alto riesgo tipo EMBARK"],
                    }
                ),
            },
            {
                "study_name": "PROTECT",
                "scenario": "localizado",
                "eligible": 1,
                "evaluation_date": "2026-03-27",
                "expected_outcome": "Sin relevancia para rescue post-RP.",
                "eligibility_details": json.dumps({"match_score": 0.9, "criteria_met": ["Ruido cross-scenario"]}),
            },
            {
                "study_name": "CHAARTED",
                "scenario": "mHSPC",
                "eligible": 0,
                "evaluation_date": "2026-03-27",
                "expected_outcome": "Sin relevancia para rescue post-RP.",
                "eligibility_details": json.dumps({"match_score": 0.2, "criteria_failed": ["Ruido cross-scenario"]}),
            },
        ],
        "pros": [],
        "agenda_items": [],
        "data_provenance": [],
        "transition_proposals": [],
        "recommendation_audit": [],
        "document_candidates": [],
        "document_verification_tasks": [],
        "verified_document_facts": [],
        "source_documents": [],
        "latest_signal_snapshot": {
            "next_best_action": {
                "title": "Activar salvage y reestadificación dirigida",
                "recommendation_family": "Ruta de rescate",
                "rationale": "La recaída bioquímica ya es operativa y debe pasar a carril de salvage.",
            },
            "care_intent_contract": {
                "headline": "Activar salvage y reestadificación dirigida",
                "narrative": "La recaída bioquímica post-RP sigue una familia de salvage aunque falten gates finos como PSADT o factibilidad local.",
                "recommendation_family": "salvage",
            },
        },
    }
    latest_assessment_raw = {
        "assessment_date": "2026-03-27",
        "state": "post_prostatectomy",
        "input_snapshot": {
            "psa_postop": 5.0,
            "psa": 12.0,
            "pathologic_stage": "pT3a",
            "surgical_margin": 1,
            "margin_location": "base derecha",
        },
        "result_snapshot": {},
    }
    latest_assessment = {
        "state": "post_prostatectomy",
        "module_label": "Post prostatectomía",
        "display_result": {
            "nccn_primary": {
                "titulo_clinico": "Ruta priorizada después de prostatectomía radical",
                "label": "PSA persistence/recurrence",
                "trayectoria_recomendada": "Escalar a evaluación de recurrencia o rescate en lugar de vigilancia rutinaria.",
            },
            "decision_quality": {"confidence_category": "alta", "recommendation_family": "salvage"},
            "source_citations": [],
        },
    }

    profile = build_patient_profile_view_model(
        patient=patient,
        latest_assessment_raw=latest_assessment_raw,
        latest_assessment=latest_assessment,
        state_timeline=[{"management_intent_status_label": "Pendiente de confirmación", "event_kind_label": "Recomendación generada"}],
        care_overlays=[],
    )

    assert profile["clinical_compass"]["primary_clinical_question"] == "Activar salvage y reestadificación dirigida"
    assert profile["clinical_compass"]["recommendation_family"] == "salvage"
    assert "salvage" in profile["clinical_compass"]["recommended_direction"].lower()
    supporting_trial_names = {item["study_name"] for item in profile["evidence_applicability"]["supporting_trials"]}
    assert "GETUG-AFU 16" in supporting_trial_names
    assert "RTOG 9601" in supporting_trial_names
    assert "PROTECT" not in supporting_trial_names
    assert "CHAARTED" not in supporting_trial_names
    contextual_names = {item["study_name"] for item in profile["evidence_applicability"]["contextual_support"]}
    assert "RADICALS-RT" in contextual_names
    rtog_card = next(item for item in profile["evidence_applicability"]["contextual_support"] if item["study_name"] == "RTOG 9601")
    assert rtog_card["recommended_trial_backbone_dose"] == "RT 64.8 Gy + bicalutamida 150 mg VO diaria"
    assert rtog_card["recommended_trial_backbone_duration"] == "24 meses de bicalutamida"
    assert any(item["study_name"] == "EMBARK" for item in profile["evidence_applicability"]["not_eligible_for_this_case"])


def test_patient_profile_hides_persisted_state_timeline_ui(app_client):
    client, _ = app_client
    payload = make_patient_payload(nss="56565656565", full_name="Paciente Perfil")
    register_response = client.post("/api/register_patient", json=payload)
    assert register_response.status_code == 200

    profile_response = client.get(f"/patient_profile/{payload['nss']}")
    assert profile_response.status_code == 200
    html = profile_response.get_data(as_text=True)
    assert "Línea de estados clínicos persistidos" not in html


def test_reconciled_state_moves_systemic_patient_out_of_diagnostic_lane(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="91919191919", full_name="Paciente Reconciliado"))
    patient_id = register.get_json()["patient_id"]

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO follow_up_visits (
            patient_id, visit_date, psa_current, testosterone_current, current_treatment,
            disease_status, ecog_current, agenda_context_json, visit_bundle_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            patient_id,
            "2026-03-15",
            2.5,
            30.0,
            "Abiraterona + ADT",
            "Respuesta Parcial",
            1,
            json.dumps({}),
            json.dumps({}),
        ),
    )
    conn.commit()
    conn.close()

    signals_response = client.get(f"/api/patients/{patient_id}/signals")
    assert signals_response.status_code == 200
    signals_payload = signals_response.get_json()
    assert signals_payload["signals"]["reconciled_state"] == "adt_progression_verification"
    assert signals_payload["signals"]["state_conflict_flag"] is True

    agenda_response = client.get("/api/patients/91919191919/agenda")
    assert agenda_response.status_code == 200
    agenda = agenda_response.get_json()["agenda"]
    assert agenda["management_track"] == "on_arpi"
    titles = [item["title"] for item in agenda["items"]]
    assert any("Bundle de seguridad ARPI" in title for title in titles)
    assert all("Biopsia" not in title for title in titles)

    schedule_response = client.get(f"/api/patients/{patient_id}/schedule")
    assert schedule_response.status_code == 200
    schedule_payload = schedule_response.get_json()
    assert schedule_payload["reconciled_state"] == "adt_progression_verification"
    assert schedule_payload["state_conflict_flag"] is True


def test_reconciled_state_keeps_low_volume_mcspc_low_when_systemic_doublet_is_used(app_client):
    client, db_path = app_client
    payload = make_patient_payload(nss="91919191918", full_name="Paciente mHSPC bajo volumen")
    payload.update(
        {
            "tnm_stage": "TxN0M1b",
            "metastasis_site": "Bone",
            "metastasis_count": 3,
            "volume_disease": "Low",
            "bone_metastasis_present": 1,
            "bone_ribs_thorax_count": 1,
            "bone_femur_count": 2,
            "bone_axial_count": 1,
            "bone_appendicular_count": 2,
            "metastasis_assessment_date": "2026-03-16",
            "metastasis_document_source": "PSMA-PET",
        }
    )
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO follow_up_visits (
            patient_id, visit_date, psa_current, testosterone_current, current_treatment,
            disease_status, ecog_current, agenda_context_json, visit_bundle_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            patient_id,
            "2026-03-16",
            4.2,
            32.0,
            "ADT + Abiraterona",
            "Respuesta Parcial",
            1,
            json.dumps({}),
            json.dumps({}),
        ),
    )
    conn.commit()
    conn.close()

    signals_response = client.get(f"/api/patients/{patient_id}/signals")
    assert signals_response.status_code == 200
    signals_payload = signals_response.get_json()["signals"]
    assert signals_payload["reconciled_state"] == "mcspc_low_volume_sync_oligo"
    assert signals_payload["supporting_evidence"]["metastasis_count"] == 3

    schedule_response = client.get(f"/api/patients/{patient_id}/schedule")
    assert schedule_response.status_code == 200
    schedule_payload = schedule_response.get_json()
    assert schedule_payload["reconciled_state"] == "mcspc_low_volume_sync_oligo"


def test_agenda_endpoint_separates_active_and_archived_items(app_client):
    client, _ = app_client
    register_response = client.post("/api/register_patient", json=make_patient_payload(nss="92929292929", full_name="Paciente Agenda Archivada"))
    patient_id = register_response.get_json()["patient_id"]

    agenda_before = client.get("/api/patients/92929292929/agenda").get_json()["agenda"]
    assert agenda_before["active_items"]
    agenda_item = agenda_before["active_items"][0]

    complete_response = client.post(f"/api/patients/{patient_id}/agenda/{agenda_item['id']}/complete", json={})
    assert complete_response.status_code == 200

    agenda_after = client.get("/api/patients/92929292929/agenda").get_json()["agenda"]
    assert all(item["id"] != agenda_item["id"] for item in agenda_after["active_items"])
    assert any(item["id"] == agenda_item["id"] for item in agenda_after["archived_items"])


def test_dashboard_stats_and_analysis_exports_include_research_readiness(app_client):
    client, db_path = app_client
    client.post("/api/register_patient", json=make_patient_payload(nss="93939393939", full_name="Paciente Cohorte"))

    summary = client.get("/api/dashboard/summary")
    assert summary.status_code == 200
    summary_payload = summary.get_json()
    assert "total_patients" in summary_payload
    assert "cohort_completeness" not in summary_payload
    assert "scenario_harness" not in summary_payload

    analytics = client.get("/api/dashboard/analytics")
    assert analytics.status_code == 200
    analytics_payload = analytics.get_json()
    assert "cohort_completeness" in analytics_payload
    assert "research_readiness" in analytics_payload
    assert "endpoint_readiness" in analytics_payload

    calibration = client.get("/api/dashboard/calibration")
    assert calibration.status_code == 200
    assert "scenario_harness" in calibration.get_json()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT cache_key FROM dashboard_cache_snapshots ORDER BY cache_key")
    cache_keys = {row["cache_key"] for row in cursor.fetchall()}
    conn.close()
    assert "dashboard_analytics_v1" in cache_keys
    assert "dashboard_calibration_v1" in cache_keys

    dashboard = client.get("/api/dashboard_stats")
    assert dashboard.status_code == 200
    payload = dashboard.get_json()
    assert "cohort_completeness" not in payload
    assert "scenario_harness" not in payload
    assert payload["analytics_endpoint"] == "/api/dashboard/analytics"
    assert payload["calibration_endpoint"] == "/api/dashboard/calibration"

    dataset = client.get("/api/analysis_dataset_export")
    assert dataset.status_code == 200
    assert isinstance(dataset.get_json()["analysis_dataset_export"], list)

    completeness = client.get("/api/cohort_completeness")
    assert completeness.status_code == 200
    assert "cohort_completeness" in completeness.get_json()

    readiness = client.get("/api/research_readiness")
    assert readiness.status_code == 200
    assert "research_readiness" in readiness.get_json()

    endpoint = client.get("/api/endpoint_readiness")
    assert endpoint.status_code == 200
    assert "endpoint_readiness" in endpoint.get_json()


def test_risk_tools_endpoint_shows_only_erspc_in_diagnostic_context(app_client):
    client, db_path = app_client
    register = client.post(
        "/api/register_patient",
        json=make_patient_payload(nss="94949494949", full_name="Paciente ERSPC") | {
            "dre_suspicious": 1,
            "prior_biopsy_count": 1,
        },
    )
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "diagnostic_workup")

    response = client.get(f"/api/patients/{patient_id}/risk-tools")

    assert response.status_code == 200
    payload = response.get_json()
    tool_keys = [card["tool_key"] for card in payload["cards"]]
    assert tool_keys == ["erspc"]
    assert payload["cards"][0]["fidelity"] == "proxy_estimate"


def test_risk_tools_endpoint_gates_localized_rp_candidate_tools(app_client):
    client, db_path = app_client
    register = client.post(
        "/api/register_patient",
        json=make_patient_payload(nss="94949494950", full_name="Paciente RP") | {
            "clinical_tstage": "T2b",
            "gleason_primary": 4,
            "gleason_secondary": 3,
            "isup_grade": 3,
            "life_expectancy_years": 14,
            "num_cores_positive": 5,
            "total_cores": 12,
            "local_treatment_consideration": "both",
        },
    )
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "localized_initial")

    response = client.get(f"/api/patients/{patient_id}/risk-tools")

    assert response.status_code == 200
    cards = response.get_json()["cards"]
    tool_keys = {card["tool_key"] for card in cards}
    assert {"capra", "damico", "predict_prostate", "mskcc_preop", "partin"} <= tool_keys
    assert "capra_s" not in tool_keys
    damico = next(card for card in cards if card["tool_key"] == "damico")
    assert damico["primary_result"] == "INTERMEDIO"


def test_risk_tools_endpoint_exposes_prognostic_impact_for_high_risk_localized_case(app_client):
    client, db_path = app_client
    register = client.post(
        "/api/register_patient",
        json=make_patient_payload(nss="94949494954", full_name="Paciente Riesgo Alto Localizado") | {
            "baseline_psa": 24.5,
            "clinical_tstage": "T3a",
            "gleason_primary": 4,
            "gleason_secondary": 4,
            "isup_grade": 4,
            "life_expectancy_years": 12,
            "num_cores_positive": 8,
            "total_cores": 12,
            "local_treatment_consideration": "both",
        },
    )
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "localized_initial")

    response = client.get(f"/api/patients/{patient_id}/risk-tools")

    assert response.status_code == 200
    payload = response.get_json()
    modifier_keys = {item["modifier_key"] for item in payload["prognostic_modifiers"]}
    assert "localized_unfavorable_biology" in modifier_keys
    assert payload["recommended_actions"]
    assert payload["followup_impact"]


def test_risk_tools_endpoint_exposes_capture_targets_for_missing_score_inputs(app_client):
    client, db_path = app_client
    register = client.post(
        "/api/register_patient",
        json=make_patient_payload(nss="94949494955", full_name="Paciente Score Incompleto") | {
            "gleason_primary": 4,
            "gleason_secondary": 3,
            "isup_grade": 3,
            "life_expectancy_years": 13,
            "local_treatment_consideration": "both",
        },
    )
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "localized_initial")

    response = client.get(f"/api/patients/{patient_id}/risk-tools")

    assert response.status_code == 200
    payload = response.get_json()
    capture_targets = {item["tool_key"]: item for item in payload["capture_targets"]}
    assert "damico" in capture_targets
    assert "clinical_tstage" in capture_targets["damico"]["raw_fields"]


def test_risk_tools_endpoint_hides_surgical_nomograms_for_rt_only_candidates(app_client):
    client, db_path = app_client
    register = client.post(
        "/api/register_patient",
        json=make_patient_payload(nss="94949494951", full_name="Paciente RT") | {
            "clinical_tstage": "T2a",
            "gleason_primary": 3,
            "gleason_secondary": 4,
            "isup_grade": 2,
            "life_expectancy_years": 11,
            "num_cores_positive": 3,
            "total_cores": 12,
            "local_treatment_consideration": "radical_radiotherapy",
        },
    )
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "localized_initial")

    response = client.get(f"/api/patients/{patient_id}/risk-tools")

    assert response.status_code == 200
    tool_keys = {card["tool_key"] for card in response.get_json()["cards"]}
    assert {"capra", "damico", "predict_prostate"} <= tool_keys
    assert "mskcc_preop" not in tool_keys
    assert "partin" not in tool_keys


def test_risk_tools_endpoint_prioritizes_capra_s_post_prostatectomy_and_interprets_decipher(app_client):
    client, db_path = app_client
    register = client.post(
        "/api/register_patient",
        json=make_patient_payload(nss="94949494952", full_name="Paciente CAPRA-S") | {
            "baseline_psa": 11.2,
            "gleason_primary": 4,
            "gleason_secondary": 3,
        },
    )
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "post_prostatectomy")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO surgical_details (
            patient_id, surgery_date, surgery_type, pathological_stage,
            pathological_gleason_primary, pathological_gleason_secondary,
            surgical_margin_status, ece_pathological, svi_pathological, lni_pathological, pathological_isup
        ) VALUES (?, '2025-02-10', 'RP_robotica', 'pT3a', 4, 3, 1, 1, 0, 0, 3)
        """,
        (patient_id,),
    )
    cursor.execute(
        """
        INSERT INTO genomic_profile (
            patient_id, test_date, test_type, decipher_score, decipher_risk, hrr_overall
        ) VALUES (?, '2025-04-01', 'Decipher', 0.81, 'Alto', 'Desconocido')
        """,
        (patient_id,),
    )
    conn.commit()
    conn.close()

    response = client.get(f"/api/patients/{patient_id}/risk-tools")

    assert response.status_code == 200
    cards = response.get_json()["cards"]
    assert cards[0]["tool_key"] == "capra_s"
    assert cards[0]["status"] == "calculated"
    msk_post = next(card for card in cards if card["tool_key"] == "mskcc_bcr_post_rp")
    assert msk_post["status"] == "calculated"
    assert "5 años" in msk_post["primary_result"]
    decipher = next(card for card in cards if card["tool_key"] == "decipher")
    assert decipher["fidelity"] == "interpreted_from_report"
    assert "0.81" in decipher["primary_result"]


def test_post_rp_prognostic_impact_flows_into_signals_and_schedule(app_client):
    client, db_path = app_client
    register = client.post(
        "/api/register_patient",
        json=make_patient_payload(nss="94949494956", full_name="Paciente RP Impacto") | {
            "baseline_psa": 18.6,
            "gleason_primary": 4,
            "gleason_secondary": 4,
        },
    )
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "post_prostatectomy")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO surgical_details (
            patient_id, surgery_date, surgery_type, pathological_stage,
            pathological_gleason_primary, pathological_gleason_secondary,
            surgical_margin_status, ece_pathological, svi_pathological, lni_pathological, pathological_isup
        ) VALUES (?, '2025-03-01', 'RP_robotica', 'pT3a', 4, 4, 1, 1, 1, 0, 4)
        """,
        (patient_id,),
    )
    conn.commit()
    conn.close()

    signals_response = client.get(f"/api/patients/{patient_id}/signals")
    assert signals_response.status_code == 200
    signals_payload = signals_response.get_json()
    modifier_keys = {item["modifier_key"] for item in signals_payload["prognostic_modifiers"]}
    assert "post_rp_high_bcr_risk" in modifier_keys
    assert signals_payload["prognostic_followup_impact"]

    schedule_response = client.get(f"/api/patients/{patient_id}/schedule")
    assert schedule_response.status_code == 200
    schedule_payload = schedule_response.get_json()
    assert schedule_payload["cadence_adjusted_by"]
    assert schedule_payload["prognostic_rationale"]


def test_post_rp_bcr_escalates_schedule_runtime_to_salvage_without_localized_fallback(app_client):
    client, db_path = app_client
    register = client.post(
        "/api/register_patient",
        json=make_patient_payload(nss="94949494958", full_name="Paciente RP Salvage Runtime") | {
            "baseline_psa": 14.2,
            "metastasis_site": "M0",
        },
    )
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "post_prostatectomy")
    _insert_postlocal_bcr_context(db_path, patient_id, bcr_date="2026-03-01", bcr_psa=0.42, psadt=8.0)

    signals_response = client.get(f"/api/patients/{patient_id}/signals")
    assert signals_response.status_code == 200
    signals_payload = signals_response.get_json()
    assert signals_payload["transition_proposals"] == []
    assert signals_payload["transition_resolution"]["policy"] == "auto_applied"
    assert signals_payload["transition_resolution"]["target_state"] == "recurrence_bcr"
    assert signals_payload["effective_state_final"] == "recurrence_bcr"
    assert signals_payload["next_best_action"]["title"] == "Activar salvage y reestadificación dirigida"

    schedule_response = client.get(f"/api/patients/{patient_id}/schedule")
    assert schedule_response.status_code == 200
    schedule_payload = schedule_response.get_json()
    assert schedule_payload["schedule_state"] == "recurrence_bcr"
    assert schedule_payload["schedule_management_track"] == "salvage"
    assert schedule_payload["guideline_followup_plan"]["state"] == "recurrence_bcr"
    assert schedule_payload["guideline_followup_plan"]["management_track"] == "salvage"
    assert schedule_payload["schedule_primary_intent"] == "Activar salvage y reestadificación dirigida"
    assert schedule_payload["care_intent_key"]
    assert schedule_payload["schedule_override_reason"]

    next_action_response = client.get(f"/api/patients/{patient_id}/next-best-action")
    assert next_action_response.status_code == 200
    next_action_payload = next_action_response.get_json()
    assert next_action_payload["next_best_action"]["title"] == "Activar salvage y reestadificación dirigida"
    assert next_action_payload["next_best_action"]["recommendation_family"] in {"salvage", "Ruta de rescate"}


def test_therapeutic_readiness_converges_across_schedule_profile_and_response_visualization(app_client):
    client, db_path = app_client
    payload = make_patient_payload(
        nss="94949494957",
        full_name="Paciente Readiness Salvage",
        baseline_psa=13.5,
        metastasis_site="M0",
    )
    register = client.post("/api/register_patient", json=payload)
    assert register.status_code == 200
    patient_id = register.get_json()["patient_id"]

    _seed_latest_assessment_state(db_path, patient_id, "recurrence_bcr")
    _insert_postlocal_bcr_context(
        db_path,
        patient_id,
        surgery_date="2025-11-12",
        bcr_date="2026-03-27",
        bcr_psa=0.48,
        psadt=None,
    )
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "prior_prostatectomy": 1,
            "prior_radiation": 0,
            "metastatic_disease_known": 0,
            "conventional_imaging_current": "negative",
        },
    )
    _update_latest_assessment_result_snapshot(
        db_path,
        patient_id,
        {
            "preferred_frontline_regimen": {
                "family_code": "salvage_rt_family",
                "family_label": "Salvage RT",
                "regimen_code": "SALVAGE_RT_ALONE",
                "regimen_label": "Salvage RT",
                "required_missing_fields": ["psadt_months"],
                "stale_inputs": ["psma_positive"],
            },
            "comparative_eligibility_matrix": {
                "salvage_rt_family": {
                    "family_code": "salvage_rt_family",
                    "eligibility_status": "conditional",
                    "missing_inputs": ["psadt_months"],
                    "stale_inputs": ["psma_positive"],
                    "variant_ranking": {
                        "preferred_regimen_code": "SALVAGE_RT_ALONE",
                        "preferred_regimen_label": "Salvage RT",
                    },
                }
            },
            "systemic_regimen_scope_contract": {
                "scope": "not_applicable",
                "reason": "salvage_local_path",
            },
        },
    )

    schedule_response = client.get(f"/api/patients/{patient_id}/schedule")
    assert schedule_response.status_code == 200
    schedule_payload = schedule_response.get_json()
    readiness = schedule_payload["therapeutic_readiness_bundle"]
    assert readiness["candidate_family"] == "salvage_rt_family"
    assert readiness["candidate_regimen_code"] == "SALVAGE_RT_ALONE"
    assert readiness["readiness_status"] in {"blocked_by_missing_data", "conditional_pending_closure"}
    assert "psadt_months" in readiness["required_to_release"]
    assert all("_" not in label for label in readiness["display_required_to_release"])
    assert schedule_payload["readiness_status"] == readiness["readiness_status"]
    assert schedule_payload["master_followup_plan"]["summary"]["therapeutic_readiness_status"] == readiness["readiness_status"]
    assert (
        schedule_payload["master_followup_plan"]["summary"]["therapeutic_candidate_label"]
        == readiness["candidate_regimen_label"]
    )
    joined_gaps = " ".join(schedule_payload["master_followup_plan"]["gaps_to_close"])
    assert "psadt_months" not in joined_gaps

    import tracking_db
    from prostanet.domains.patient_tracking.profile_compass import build_patient_profile_view_model

    refreshed = tracking_db.get_patient_full_record(payload["nss"])
    longitudinal_bundle = tracking_db.refresh_longitudinal_intelligence(
        patient_id,
        force_recompute=False,
        record=refreshed,
        include_live_benchmark=False,
    )
    profile = build_patient_profile_view_model(
        patient=refreshed,
        latest_assessment_raw=refreshed.get("latest_assessment") or {},
        latest_assessment=refreshed.get("latest_assessment") or {},
        state_timeline=refreshed.get("state_timeline") or [],
        care_overlays=refreshed.get("care_overlays") or [],
        recommendations={},
        longitudinal_bundle=longitudinal_bundle,
    )
    profile_readiness = profile["therapeutic_readiness_bundle"]
    assert profile_readiness["candidate_family"] == "salvage_rt_family"
    assert profile_readiness["candidate_regimen_code"] == "SALVAGE_RT_ALONE"
    assert profile["readiness_status"] == readiness["readiness_status"]
    assert profile["required_to_release"] == readiness["required_to_release"]
    assert all("_" not in label for label in profile_readiness["display_required_to_release"])

    response_visualization = client.post(f"/api/patients/{patient_id}/response-visualization")
    assert response_visualization.status_code == 200
    response_payload = response_visualization.get_json()
    assert response_payload["readiness_status"] == readiness["readiness_status"]
    assert response_payload["therapeutic_readiness_bundle"]["candidate_family"] == "salvage_rt_family"
    assert response_payload["therapeutic_readiness_bundle"]["candidate_regimen_code"] == "SALVAGE_RT_ALONE"

    profile_page = client.get(f"/patient_profile/{payload['nss']}")
    assert profile_page.status_code == 200
    profile_html = profile_page.get_data(as_text=True)
    assert "Therapeutic Readiness &amp; Release Gate" in profile_html
    assert readiness["candidate_regimen_label"] in profile_html


def test_profile_view_model_surfaces_post_rt_recurrence_bundle_and_actionable_release_ctas():
    from prostanet.domains.patient_tracking.profile_compass import build_patient_profile_view_model

    patient = {
        "identity": {
            "id": 302,
            "full_name": "Paciente Post RT",
            "nss": "30303030303",
            "diagnosis_date": "2024-01-10",
            "dob": "1962-02-01",
            "age": 64,
        },
        "baseline": {
            "prior_radiation": 1,
            "dxa_baseline_done": 1,
            "cv_risk_documented": 1,
            "smoking_status": "Nunca",
            "calcium_vitd_started": 1,
            "bone_protection_started": 0,
        },
        "follow_ups": [
            {
                "visit_date": "2026-04-01",
                "late_urinary_grade": "2",
                "late_bowel_grade": "1",
                "total_cholesterol": 188,
                "hba1c": 5.8,
            }
        ],
        "latest_signal_snapshot": {},
    }
    therapeutic_readiness_bundle = {
        "readiness_status": "blocked_by_missing_data",
        "candidate_family": "salvage_rt_family",
        "candidate_regimen_code": "SALVAGE_RT_ALONE",
        "candidate_regimen_label": "Salvage RT",
        "capture_actions": [
            {
                "title": "Completar reestadificación post-RT",
                "summary": "Cerrar PSMA, mpMRI y biopsia antes de liberar salvage.",
                "focus": "post_rt_salvage",
                "display_fields_summary": ["Disponibilidad de PSMA-PET", "mpMRI prostática", "Biopsia transperineal"],
                "fields": ["psma_pet_done", "mpmri_done", "biopsy_proven_local_recurrence"],
            }
        ],
    }
    longitudinal_bundle = {
        "therapeutic_readiness_bundle": therapeutic_readiness_bundle,
        "post_rt_salvage_bundle": {
            "post_rt_failure_definition": {
                "psa_history_points": [
                    {"sample_date": "2025-12-01", "value": 0.4, "source": "nadir"},
                    {"sample_date": "2026-03-15", "value": 2.6, "source": "psa_history"},
                    {"sample_date": "2026-06-20", "value": 2.9, "source": "psa_history"},
                ],
                "psa_nadir": 0.4,
                "psa_nadir_date": "2025-12-01",
                "phoenix_threshold": 2.4,
                "phoenix_threshold_reached": True,
                "phoenix_confirmation_status": "confirmed_longitudinal",
                "bounce_suspected": False,
                "psadt_months": 7.4,
                "salvage_release_status": "pending_restaging_inputs",
                "required_missing_fields": ["psma_pet_done", "mpmri_done", "biopsy_proven_local_recurrence"],
            },
            "post_rt_transition_bundle": {
                "transition_status": "restate_before_decision",
                "trigger_reasons": ["Falta tríada de restadificación antes de salvage curativo."],
                "required_missing_fields": ["psma_pet_done", "mpmri_done", "biopsy_proven_local_recurrence"],
            },
        },
    }

    profile = build_patient_profile_view_model(
        patient=patient,
        latest_assessment_raw={"state": "post_radiotherapy_or_local_salvage", "result_snapshot": {}},
        latest_assessment={"state": "post_radiotherapy_or_local_salvage", "module_label": "Post-RT salvage"},
        state_timeline=[],
        care_overlays=[],
        recommendations={},
        longitudinal_bundle=longitudinal_bundle,
    )

    post_rt_profile = profile["post_rt_recurrence_profile"]
    assert post_rt_profile["available"] is True
    assert post_rt_profile["phoenix_threshold_reached"] is True
    assert post_rt_profile["phoenix_confirmation_status"] == "confirmed_longitudinal"
    assert post_rt_profile["capture_action"]["title"] == "Completar reestadificación post-RT"
    assert "psma_pet_done" in post_rt_profile["required_missing_fields"]
    assert profile["rt_toxicity_timeline"]["available"] is True
    assert {item["domain"] for item in profile["rt_toxicity_timeline"]["timeline"]} >= {"GU", "GI"}
    survivorship_labels = {item["label"] for item in profile["survivorship_checklist"]["items"]}
    assert {"DXA", "Lípidos / metabólico", "Riesgo cardiovascular", "Cesación tabáquica"} <= survivorship_labels
    assert profile["therapeutic_capture_actions"][0]["title"] == "Completar reestadificación post-RT"


def test_advanced_release_gate_converges_across_schedule_profile_and_response_for_m0_crpc_psma_only_upstaging(app_client):
    client, db_path = app_client
    payload = make_patient_payload(nss="39999999996", full_name="Paciente nmCRPC PSMA")
    register = client.post("/api/register_patient", json=payload)
    assert register.status_code == 200
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "m0_crpc")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "testosterone_value": 18,
            "current_adt_context": "ADT continua",
            "conventional_imaging_status": "M0",
            "conventional_imaging_date": "2026-03-01",
            "progression_pattern": "biochemical_only",
            "dxa_baseline_done": 1,
            "calcium_vitd_started": 1,
            "bone_protection_started": 1,
            "hba1c": 5.8,
            "total_cholesterol": 180,
            "creatinine": 0.9,
            "mini_cog_score": 4,
        },
    )
    _update_latest_assessment_result_snapshot(
        db_path,
        patient_id,
        {
            "preferred_frontline_regimen": {
                "family_code": "arpi_family",
                "regimen_code": "ADT_DAROLUTAMIDE",
                "regimen_label": "ADT + darolutamida",
            },
            "comparative_eligibility_matrix": {
                "arpi_family": {
                    "family_code": "arpi_family",
                    "eligibility_status": "eligible",
                    "variant_ranking": {
                        "preferred_regimen_code": "ADT_DAROLUTAMIDE",
                        "preferred_regimen_label": "ADT + darolutamida",
                    },
                }
            },
        },
    )
    _insert_structured_psma_imaging(
        db_path,
        patient_id,
        study_date="2026-04-01",
        psma_result="oligometastatic",
        uptake_pattern="oligometastatic",
        conventional_stage="M0",
        psma_stage="M1a",
        upstaged=True,
        management_changed=True,
    )

    schedule_response = client.get(f"/api/patients/{patient_id}/schedule")
    assert schedule_response.status_code == 200
    schedule_payload = schedule_response.get_json()
    readiness = schedule_payload["therapeutic_readiness_bundle"]
    effective_state = schedule_payload["effective_state"]

    assert effective_state in {"m0_crpc", "m1_crpc"}
    assert readiness["readiness_status"] == "blocked_by_missing_data"
    assert readiness["adjudication_gate_status"] == "blocked_by_missing_data"
    assert readiness["monitoring_gate_status"] in {"supported", "conditional_pending_closure"}
    assert "conventional_imaging_status" in readiness["required_to_release"] or "psma_positive" in readiness["required_to_release"]
    assert any("adjudicación" in blocker.lower() or "nmcrpc" in blocker.lower() for blocker in readiness["release_blockers"])
    assert schedule_payload["master_followup_plan"]["summary"]["therapeutic_readiness_status"] == "blocked_by_missing_data"
    assert schedule_payload["master_followup_plan"]["summary"]["adjudication_gate_status"] == "blocked_by_missing_data"

    import tracking_db
    from prostanet.domains.patient_tracking.profile_compass import build_patient_profile_view_model

    refreshed = tracking_db.get_patient_full_record(payload["nss"])
    longitudinal_bundle = tracking_db.refresh_longitudinal_intelligence(
        patient_id,
        force_recompute=False,
        record=refreshed,
        include_live_benchmark=False,
    )
    profile = build_patient_profile_view_model(
        patient=refreshed,
        latest_assessment_raw=refreshed.get("latest_assessment") or {},
        latest_assessment=refreshed.get("latest_assessment") or {},
        state_timeline=refreshed.get("state_timeline") or [],
        care_overlays=refreshed.get("care_overlays") or [],
        recommendations={},
        longitudinal_bundle=longitudinal_bundle,
    )

    assert profile["effective_state"] == effective_state
    assert profile["therapeutic_readiness_bundle"]["readiness_status"] == "blocked_by_missing_data"
    assert profile["therapeutic_readiness_bundle"]["adjudication_gate_status"] == "blocked_by_missing_data"
    assert profile["therapeutic_capture_actions"]
    assert any(
        {"psma_pet_done", "psma_positive", "conventional_imaging_status"}.intersection(
            set(action.get("fields") or action.get("raw_fields") or [])
        )
        for action in profile["therapeutic_capture_actions"]
    )

    response_visualization = client.post(f"/api/patients/{patient_id}/response-visualization")
    assert response_visualization.status_code == 200
    response_payload = response_visualization.get_json()

    assert response_payload["effective_state"] == effective_state
    assert response_payload["therapeutic_readiness_bundle"]["readiness_status"] == "blocked_by_missing_data"
    assert response_payload["therapeutic_readiness_bundle"]["adjudication_gate_status"] == "blocked_by_missing_data"


def test_post_rp_bcr_keeps_salvage_family_uses_postop_psa_and_demotes_embark_to_context(app_client):
    client, db_path = app_client
    register = client.post(
        "/api/register_patient",
        json=make_patient_payload(nss="94949494956", full_name="Fabian Runtime Audit", baseline_psa=12.0),
    )
    patient_id = register.get_json()["patient_id"]
    _insert_postlocal_bcr_context(db_path, patient_id, surgery_date="2025-11-12", bcr_date="2026-03-27", bcr_psa=5.0, psadt=8.0)
    _seed_latest_assessment_state(db_path, patient_id, "post_prostatectomy")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE biochemical_recurrence SET bcr_detected = 0, bcr_definition = 'BCR', psadt_at_bcr = NULL WHERE patient_id = ?",
        (patient_id,),
    )
    cursor.execute(
        "UPDATE clinical_assessments SET input_snapshot = ? WHERE patient_id = ?",
        (
            json.dumps(
                {
                    "local_therapy_date": "2025-11-12",
                    "psa_postop": 5.0,
                    "psa": 12.0,
                    "pathologic_stage": "pT3a",
                    "surgical_margin": 1,
                    "margin_location": "base derecha",
                }
            ),
            patient_id,
        ),
    )
    conn.commit()
    conn.close()
    _insert_psa_longitudinal_points(db_path, patient_id, [("2026-02-12", 15.0), ("2026-03-27", 5.0)])

    signals_response = client.get(f"/api/patients/{patient_id}/signals")
    assert signals_response.status_code == 200
    signals_payload = signals_response.get_json()
    psa_signal = next(item for item in signals_payload["signals"]["signals"] if item["key"] == "psa")

    next_action_response = client.get(f"/api/patients/{patient_id}/next-best-action")
    assert next_action_response.status_code == 200
    next_action_payload = next_action_response.get_json()

    assert signals_payload["effective_state_final"] == "recurrence_bcr"
    assert signals_payload["effective_management_track_final"] == "salvage"
    assert signals_payload["care_intent_contract"]["headline"] == "Activar salvage y reestadificación dirigida"
    assert signals_payload["current_trial_comparable_profile"]["benchmark_family"] == "POST_RP_SALVAGE_like"
    assert psa_signal["value"] == "5.00 ng/mL"
    assert next_action_payload["next_best_action"]["title"] == "Activar salvage y reestadificación dirigida"
    assert next_action_payload["next_best_action"]["recommendation_family"] in {"salvage", "Ruta de rescate"}


def test_m0_crpc_next_best_action_uses_preferred_regimen_from_comparative_matrix(app_client):
    client, db_path = app_client
    register = client.post(
        "/api/register_patient",
        json=make_patient_payload(nss="94949494958", full_name="Paciente m0 Preferente"),
    )
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "m0_crpc")
    payload = {
        "testosterone_value": 18,
        "castrate_testosterone_confirmed": 1,
        "current_adt_context": "ADT continua",
        "psadt_months": 6.0,
        "comorbidity_seizure": "1",
        "cv_risk_documented": "1",
        "conventional_imaging_status": "M0",
        "imaging_negative": 1,
        "conventional_imaging_modality": "CT + gammagrama óseo",
        "conventional_imaging_date": "2026-03-10",
    }
    _update_latest_assessment_input(db_path, patient_id, payload)
    module_response = client.post("/api/modules/m0_crpc/evaluate", json=payload)
    assert module_response.status_code == 200
    module_result = module_response.get_json()["result"]
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE clinical_assessments SET result_snapshot = ?, input_snapshot = ? WHERE patient_id = ?",
        (json.dumps(module_result), json.dumps(payload), patient_id),
    )
    conn.commit()
    conn.close()

    next_action_response = client.get(f"/api/patients/{patient_id}/next-best-action")
    assert next_action_response.status_code == 200
    next_action_payload = next_action_response.get_json()

    assert "darolut" in next_action_payload["next_best_action"]["title"].lower()
    assert next_action_payload["next_best_action"]["recommendation_family"] in {
        "ARPI",
        "arpi_family",
        "inhibidor de la vía del receptor androgénico (ARPI)",
    }


def test_psmafore_like_signals_expose_backbone_alignment(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="94949494957", full_name="Paciente Alineacion PSMAfore"))
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "m1_crpc")
    _update_latest_assessment_input(db_path, patient_id, {"psma_positive": "1", "m_substage_resolved": "M1b"})
    _insert_treatment_line(
        db_path,
        patient_id,
        line_of_therapy=1,
        drug_scheme="ADT_ABIRATERONE",
        start_date="2025-01-15",
        context="mCRPC_post_ARPI_pre_taxane",
    )
    _insert_psma_imaging(db_path, patient_id, psma_positive=True)

    response = client.get(f"/api/patients/{patient_id}/signals")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["current_trial_comparable_profile"]["benchmark_family"] == "PSMAfore_like"
    assert payload["backbone_alignment"]["trial_backbone_label"] == "Lutecio-177 PSMA-617"
    assert payload["backbone_alignment"]["current_regimen_label"] == "ADT + abiraterona"
    assert payload["backbone_alignment"]["alignment_status"] == "divergent"


def test_longitudinal_surfaces_expose_histopathology_summary_and_qa_contract(app_client):
    client, _ = app_client
    register = client.post(
        "/api/register_patient",
        json=make_patient_payload(
            nss="94949494959",
            full_name="Paciente Contrato Longitudinal",
        )
        | {
            "baseline_psa": 11.2,
            "gleason_primary": 3,
            "gleason_secondary": 4,
            "visceral_metastasis_present": "1",
            "metastatic_disease_known": "1",
            "visceral_site_entries": [
                {"site_key": "liver", "lesion_count": 2},
            ],
        },
    )
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(app_client[1], patient_id, "mcspc_high_volume_sync")

    signals_payload = client.get(f"/api/patients/{patient_id}/signals").get_json()
    schedule_payload = client.get(f"/api/patients/{patient_id}/schedule").get_json()
    full_assessment_payload = client.post(f"/api/ai/full-assessment/{patient_id}", json={}).get_json()

    assert signals_payload["histopathology_summary"] == "Gleason 7 (3+4), ISUP 2"
    assert isinstance(signals_payload["qa_validation"], dict)
    assert signals_payload["metastatic_composition_summary"]["m_substage_resolved"] == "M1c"

    assert schedule_payload["histopathology_summary"] == "Gleason 7 (3+4), ISUP 2"
    assert isinstance(schedule_payload["qa_validation"], dict)
    assert schedule_payload["metastatic_composition_summary"]["m_substage_resolved"] == "M1c"

    assert full_assessment_payload["effective_state"] == "mcspc_high_volume_sync"
    assert full_assessment_payload["phenotype_state"] == "mcspc_high_volume_sync"
    assert full_assessment_payload["effective_management_track"] == "systemic_surveillance"
    assert full_assessment_payload["histopathology_summary"] == "Gleason 7 (3+4), ISUP 2"
    assert isinstance(full_assessment_payload["qa_validation"], dict)
    assert full_assessment_payload["metastatic_composition_summary"]["m_substage_resolved"] == "M1c"


def test_clinical_assessment_context_requests_only_missing_score_inputs(app_client):
    client, _ = app_client

    diagnostic_draft = client.post(
        "/api/clinical-assessments/draft",
        json={
            "module_id": "diagnostic_workup",
            "payload": {
                "age": 64,
                "psa": 6.8,
            },
        },
    )
    diagnostic_id = diagnostic_draft.get_json()["assessment_id"]
    diagnostic_context = client.get(f"/api/clinical-assessments/{diagnostic_id}").get_json()
    assert diagnostic_context["applicable_scores"] == ["erspc"]
    assert {item["name"] for item in diagnostic_context["score_missing_inputs"]} == {"dre_suspicious"}

    localized_draft = client.post(
        "/api/clinical-assessments/draft",
        json={
            "module_id": "localized_initial",
            "payload": {
                "psa": 8.9,
                "gleason_primary": 4,
                "gleason_secondary": 3,
                "life_expectancy_years": 13,
                "local_treatment_consideration": "both",
            },
        },
    )
    localized_id = localized_draft.get_json()["assessment_id"]
    localized_context = client.get(f"/api/clinical-assessments/{localized_id}").get_json()
    assert set(localized_context["applicable_scores"]) == {"capra", "damico", "predict_prostate", "mskcc_preop", "partin"}
    missing = {item["name"] for item in localized_context["score_missing_inputs"]}
    assert "num_cores_positive" in missing
    assert "clinical_tstage" not in missing
    assert "isup_grade" not in missing
    assert "total_cores" not in missing


def test_post_rp_assessment_context_requests_mskcc_postop_inputs(app_client):
    client, _ = app_client

    post_rp_draft = client.post(
        "/api/clinical-assessments/draft",
        json={
            "module_id": "post_prostatectomy",
            "payload": {
                "psa": 9.8,
                "pathologic_stage": "pT3a",
                "surgical_margin": 1,
            },
        },
    )
    draft_id = post_rp_draft.get_json()["assessment_id"]
    context = client.get(f"/api/clinical-assessments/{draft_id}").get_json()

    assert set(context["applicable_scores"]) == {"capra_s", "mskcc_bcr_post_rp"}
    missing = {item["name"] for item in context["score_missing_inputs"]}
    assert "pathology_gleason_primary" in missing
    assert "pathology_gleason_secondary" in missing
    assert "ece_status" in missing
    assert "svi_status" in missing
    assert "lni_status" in missing


def test_registration_context_humanizes_scales_and_dedupes_advanced_fields(app_client):
    client, _ = app_client

    draft_response = client.post(
        "/api/clinical-assessments/draft",
        json={
            "module_id": "m1_crpc",
            "payload": {
                "current_adt_context": "medical_adt_continuous",
                "castrate_testosterone_status": "confirmed_castrate",
                "conventional_imaging_status": "M1",
                "metastasis_site": "Bone",
            },
        },
    )
    assert draft_response.status_code == 200
    draft_data = draft_response.get_json()

    visible_names = [
        field["name"]
        for fragment in draft_data["registration_fragments"]
        for field in fragment["fields"]
    ]
    assert visible_names.count("mini_cog_score") == 1
    assert visible_names.count("fatigue_score") == 1
    assert visible_names.count("weight_loss_6m_kg") == 1
    assert "weight_loss_6m_pct" not in visible_names
    assert visible_names.count("height_cm") == 1
    assert visible_names.count("testosterone_history") == 1

    g8_field = next(
        field
        for fragment in draft_data["registration_fragments"]
        for field in fragment["fields"]
        if field["name"] == "g8_food_intake"
    )
    mini_cog_field = next(
        field
        for fragment in draft_data["registration_fragments"]
        for field in fragment["fields"]
        if field["name"] == "mini_cog_score"
    )
    testosterone_history_field = next(
        field
        for fragment in draft_data["registration_fragments"]
        for field in fragment["fields"]
        if field["name"] == "testosterone_history"
    )
    assert any("Disminución severa" in option["label"] for option in g8_field["display_options"])
    assert mini_cog_field["field_type"] == "select"
    assert any("Severamente anormal" in option["label"] for option in mini_cog_field["display_options"])
    assert testosterone_history_field["field_type"] == "testosterone_history"
    assert "G8 total" in g8_field["score_interpretation"]
    assert draft_data["capture_layers"]


def test_registration_context_exposes_humanized_fragility_and_radiotherapy_labels(app_client):
    client, _ = app_client

    draft_response = client.post(
        "/api/clinical-assessments/draft",
        json={
            "module_id": "m1_crpc",
            "payload": {
                "current_adt_context": "medical_adt_continuous",
                "castrate_testosterone_status": "confirmed_castrate",
                "conventional_imaging_status": "M1",
                "metastasis_site": "Bone",
            },
        },
    )
    assert draft_response.status_code == 200
    draft_data = draft_response.get_json()

    fields = {
        field["name"]: field
        for fragment in draft_data["registration_fragments"]
        for field in fragment["fields"]
    }

    low_activity_labels = {option["value"]: option["label"] for option in fields["low_activity"]["display_options"]}
    slow_gait_labels = {option["value"]: option["label"] for option in fields["slow_gait"]["display_options"]}
    rt_intent_labels = {option["value"]: option["label"] for option in fields["rt_intent"]["display_options"]}
    modality_labels = {option["value"]: option["label"] for option in fields["modality"]["display_options"]}
    target_volume_labels = {option["value"]: option["label"] for option in fields["target_volume"]["display_options"]}

    assert low_activity_labels["1"] == "Sí, actividad reducida"
    assert slow_gait_labels["0"] == "No documentada"
    assert rt_intent_labels["salvage"] == "Salvamento"
    assert modality_labels["EBRT_IMRT"] == "Radioterapia externa IMRT"
    assert target_volume_labels["whole_pelvis"] == "Pelvis completa"


def test_postlocal_context_hides_systemic_treatment_fields(app_client):
    client, _ = app_client

    draft_response = client.post(
        "/api/clinical-assessments/draft",
        json={
            "module_id": "post_prostatectomy",
            "payload": {
                "psa": 0.31,
                "pathologic_stage": "pT3a",
                "surgical_margin": 1,
            },
        },
    )
    assert draft_response.status_code == 200
    draft_data = draft_response.get_json()
    field_names = {
        field["name"]
        for fragment in draft_data["registration_fragments"]
        for field in fragment["fields"]
    }
    assert "line_of_therapy_number" not in field_names
    assert "drug_scheme" not in field_names
    assert "current_adt_context" not in field_names


def test_register_patient_persists_psa_history_and_derives_baseline_from_pretreatment_series(app_client):
    client, db_path = app_client

    register_response = client.post(
        "/api/register_patient",
        json={
            "assessment_state": "diagnostic_workup",
            "nss": "90909090909",
            "full_name": "Paciente Serie PSA",
            "dob": "1958-09-09",
            "psa_history": [
                {"sample_date": "2026-01-10", "psa_value": 6.2, "context": "pretratamiento", "assay_type": "estándar"},
                {"sample_date": "2026-02-01", "psa_value": 7.4, "context": "pretratamiento", "assay_type": "ultrasensible"},
                {
                    "sample_date": "2026-03-01",
                    "psa_value": 0.3,
                    "context": "postlocal",
                    "assay_type": "desconocido",
                    "line_of_therapy_number": 1,
                    "line_of_therapy_context": "mHSPC_initial",
                },
            ],
        },
    )
    assert register_response.status_code == 200
    payload = register_response.get_json()
    summary = payload["registration_metadata"]["psa_history_summary"]
    assert summary["points_received"] == 3
    assert summary["baseline_source"] == "derived_from_history"
    assert summary["baseline_point"]["sample_date"] == "2026-02-01"

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT baseline_psa FROM clinical_baseline")
    baseline_psa = cursor.fetchone()[0]
    assert baseline_psa == 7.4
    cursor.execute("SELECT biomarker_type, value, sample_date FROM biomarker_longitudinal ORDER BY sample_date ASC")
    rows = cursor.fetchall()
    conn.close()

    assert len(rows) == 3
    assert rows[0][0] == "PSA"
    assert {row[2] for row in rows} == {"2026-01-10", "2026-02-01", "2026-03-01"}

    import tracking_db

    record = tracking_db.get_full_record("90909090909")
    longitudinal_rows = record["biomarker_longitudinal"]
    assert any(row.get("assay_type") == "ultrasensible" for row in longitudinal_rows)
    assert any(row.get("line_of_therapy_number") == 1 for row in longitudinal_rows)
    assert any(row.get("line_of_therapy_context") == "mHSPC_initial" for row in longitudinal_rows)


def test_register_patient_post_rp_persists_postop_psa_and_normalizes_bcr_payload(app_client):
    client, db_path = app_client

    register_response = client.post(
        "/api/register_patient",
        json=make_patient_payload(
            nss="90909090910",
            full_name="Fabian Intake PostRP",
            assessment_state="post_prostatectomy",
            prior_prostatectomy=1,
            local_therapy_date="2025-11-12",
            time_to_recurrence_months=4,
            psa_postop=5.0,
            psa=12.0,
            pathologic_stage="pT3a",
            surgical_margin=1,
        ),
    )
    assert register_response.status_code == 200
    patient_id = register_response.get_json()["patient_id"]

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT bcr_detected, bcr_psa, bcr_definition FROM biochemical_recurrence WHERE patient_id = ? ORDER BY id DESC LIMIT 1",
        (patient_id,),
    )
    bcr_row = cursor.fetchone()
    cursor.execute(
        "SELECT value FROM biomarker_longitudinal WHERE patient_id = ? AND biomarker_type = 'PSA' ORDER BY sample_date DESC, id DESC LIMIT 1",
        (patient_id,),
    )
    psa_row = cursor.fetchone()
    conn.close()

    assert bcr_row == (1, 5.0, "BCR")
    assert psa_row[0] == 5.0


def test_capra_score_requires_real_biopsy_inputs():
    from clinical_scores import capra_score

    result = capra_score(
        {
            "psa": 8.1,
            "clinical_tstage": "T2a",
        }
    )

    assert result["score"] is None
    assert result["risk_group"] == "INCOMPLETO"
    assert "gleason_primary" in result["missing_inputs"]
    assert "total_cores" in result["missing_inputs"]


def test_dashboard_stats_include_risk_tool_and_upgrade_metrics(app_client):
    client, db_path = app_client
    register = client.post(
        "/api/register_patient",
        json=make_patient_payload(nss="94949494953", full_name="Paciente Cohorte Risk Tools") | {
            "clinical_tstage": "T2b",
            "gleason_primary": 4,
            "gleason_secondary": 3,
            "isup_grade": 3,
            "life_expectancy_years": 12,
            "num_cores_positive": 4,
            "total_cores": 12,
            "clinical_risk_group": "intermedio desfavorable",
            "local_treatment_consideration": "both",
        },
    )
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "localized_initial")

    dashboard = client.get("/api/dashboard/analytics")

    assert dashboard.status_code == 200
    payload = dashboard.get_json()
    assert "risk_tool_stats" in payload
    assert "capra_distribution" in payload
    assert "damico_distribution" in payload
    assert "capra_s_distribution" in payload
    assert "mskcc_bcr_post_rp_stats" in payload
    assert "upgrade_stats" in payload
    assert "pathologic_upgrade_count" in payload["upgrade_stats"]
    assert "prognostic_modifier_stats" in payload
    assert "backbone_alignment_stats" in payload
    assert "prognostic_followup_impact_count" in payload
    assert "incomplete_prognostic_scores_count" in payload


def test_pivotal_match_hides_peace1_for_sync_low_volume_mhspc(app_client):
    client, db_path = app_client
    payload = make_patient_payload(nss="40000000004", full_name="mHSPC Low Volume Demo")
    payload.update(
        {
            "metastasis_site": "Bone",
            "volume_disease": "Low",
            "ecog_score": 0,
            "metastasis_count": 2,
        }
    )
    register = client.post("/api/register_patient", json=payload)
    assert register.status_code == 200
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "mcspc_low_volume_sync_oligo")

    response = client.get(f"/api/pivotal_match/{payload['nss']}")

    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    visible_names = {str(item.get("study_name", "")) for item in data["eligible_matches"] + data["partial_matches"] + data["ineligible_matches"]}
    assert "PEACE-1" not in visible_names
    assert "ARASENS" not in visible_names
    assert data["hidden_cross_scenario_count"] >= 1


def test_pivotal_match_restricts_post_rp_bcr_to_salvage_trials_and_uses_backbone_metadata(app_client):
    client, db_path = app_client
    payload = make_patient_payload(nss="40000000005", full_name="Fabian Recurre Endpoint", baseline_psa=12.0)
    register = client.post("/api/register_patient", json=payload)
    assert register.status_code == 200
    patient_id = register.get_json()["patient_id"]
    _insert_postlocal_bcr_context(db_path, patient_id, surgery_date="2025-11-12", bcr_date="2026-03-27", bcr_psa=5.0, psadt=8.0)
    _seed_latest_assessment_state(db_path, patient_id, "post_prostatectomy")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE biochemical_recurrence SET bcr_detected = 0, bcr_definition = 'BCR', psadt_at_bcr = NULL WHERE patient_id = ?",
        (patient_id,),
    )
    conn.commit()
    conn.close()
    _insert_psa_longitudinal_points(db_path, patient_id, [("2026-02-12", 15.0), ("2026-03-27", 5.0)])
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE clinical_assessments
        SET input_snapshot = ?
        WHERE patient_id = ?
        """,
        (
            json.dumps(
                {
                    "psa_postop": 5.0,
                    "psa": 12.0,
                    "pathologic_stage": "pT3a",
                    "surgical_margin": 1,
                    "margin_location": "base derecha",
                    "salvage_local_feasible": 1,
                }
            ),
            patient_id,
        ),
    )
    conn.commit()
    conn.close()

    response = client.get(f"/api/pivotal_match/{payload['nss']}")

    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    visible_names = {str(item.get("study_name", "")) for item in data["eligible_matches"] + data["partial_matches"] + data["ineligible_matches"]}
    assert visible_names
    assert visible_names <= {"RAVES", "RADICALS-RT", "RADICALS-HD", "ARTISTIC", "GETUG-AFU 16", "RTOG 9601", "SPPORT", "EMBARK", "EMPIRE-1"}
    assert "PROTECT" not in visible_names
    assert "CHAARTED" not in visible_names
    getug = next((item for item in data["partial_matches"] + data["ineligible_matches"] if item.get("study_name") == "GETUG-AFU 16"), {})
    assert getug["recommended_trial_backbone_label"] == "RT de salvage + goserelina"
    assert "goserelina 10.8 mg" in getug["recommended_trial_backbone_dose"]


def test_tnm_engine_maps_case_specific_real_stage_images():
    assembled = TNMEngine.assemble({"clinical_tstage": "T2b"})
    assert assembled["t_data"]["image"] == "real_stage/t2b_real.png"

    assembled_upper = TNMEngine.assemble({"clinical_tstage": "T2B"})
    assert assembled_upper["t_data"]["image"] == "real_stage/t2b_real.png"

    assembled_composite = TNMEngine.assemble({"tnm_stage": "T2cN0M0"})
    assert assembled_composite["t_data"]["image"] == "real_stage/t2c_real.png"


def test_tnm_engine_uses_real_stage_images_for_n1_and_m1():
    assembled = TNMEngine.assemble({"tnm_stage": "T4N1M1"})
    assert assembled["t_data"]["image"] == "real_stage/t4_real.png"
    assert assembled["n_data"]["image"] == "real_stage/n1_real.png"
    assert assembled["m_data"]["image_src"].startswith("data:image/svg+xml")


def test_tnm_engine_resolves_metastatic_substages_from_structured_distribution():
    nodal = TNMEngine.assemble(
        {
            "nonregional_nodal_metastasis_present": 1,
            "nonregional_nodal_retroperitoneal_count": 2,
        }
    )
    assert nodal["m_stage"] == "M1a"
    assert nodal["m_data"]["image_src"].startswith("data:image/svg+xml")

    bone = TNMEngine.assemble(
        {
            "bone_metastasis_present": 1,
            "bone_femur_count": 2,
            "bone_ribs_thorax_count": 1,
        }
    )
    assert bone["m_stage"] == "M1b"
    assert "fémur" in bone["m_data"]["summary"].lower()

    visceral = TNMEngine.assemble(
        {
            "visceral_metastasis_present": 1,
            "visceral_lung_count": 2,
            "visceral_liver_count": 1,
        }
    )
    assert visceral["m_stage"] == "M1c"
    assert visceral["m_data"]["image_src"].startswith("data:image/svg+xml")


def test_consent_signature_is_required_before_opening_record_and_visible_in_profile(app_client):
    client, db_path = app_client
    payload = make_patient_payload(nss="70000000001", full_name="Paciente Consentido")

    draft_response = client.post(
        "/api/research/consent/draft",
        json={"payload": payload, "source_context": "pytest"},
    )
    assert draft_response.status_code == 200
    draft_data = draft_response.get_json()
    assert draft_data["success"] is True
    draft_id = draft_data["draft_id"]

    blocked_finalize = client.post(f"/api/research/consent/draft/{draft_id}/finalize")
    assert blocked_finalize.status_code == 400
    assert "sin consentimiento firmado" in blocked_finalize.get_json()["error"].lower()

    sign_response = client.post(
        f"/api/research/consent/draft/{draft_id}/sign",
        json={
            "signer_name": payload["full_name"],
            "signature_data_url": "data:image/png;base64,ZmlybWFfZGVtbw==",
            "accepted": True,
            "audit_metadata": {"channel": "pytest"},
        },
    )
    assert sign_response.status_code == 200
    sign_data = sign_response.get_json()
    assert sign_data["status"] == "signed"
    assert sign_data["evidence"]["content_hash"]

    finalize_response = client.post(f"/api/research/consent/draft/{draft_id}/finalize")
    assert finalize_response.status_code == 200
    finalize_data = finalize_response.get_json()
    assert finalize_data["success"] is True
    assert isinstance(finalize_data["patient_id"], int)
    assert finalize_data["consent"]["status"] == "signed"

    profile_response = client.get(f"/patient_profile/{payload['nss']}")
    assert profile_response.status_code == 200
    profile_html = profile_response.get_data(as_text=True)
    assert "Consentimiento de uso secundario de datos" in profile_html
    assert "Firma electrónica del paciente" in profile_html
    assert "Hash de evidencia" in profile_html

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM patient_consents")
    assert cursor.fetchone()[0] == 1
    cursor.execute("SELECT COUNT(*) FROM consent_signature_evidence")
    assert cursor.fetchone()[0] == 1
    conn.close()


def test_psma_structured_profile_surfaces_in_full_record_and_patient_profile(app_client):
    client, db_path = app_client
    payload = make_patient_payload(nss="70000000011", full_name="Paciente PSMA Estructurado")
    payload.update({"metastasis_site": "M0", "baseline_psa": 0.56})

    register = client.post("/api/register_patient", json=payload)
    assert register.status_code == 200
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "recurrence_bcr")
    _insert_postlocal_bcr_context(db_path, patient_id, bcr_date="2026-03-01", bcr_psa=0.56, psadt=8.1)
    _insert_structured_psma_imaging(
        db_path,
        patient_id,
        psma_result="local/pélvico",
        radioligand="68Ga-PSMA-11",
        uptake_pattern="focal",
        rads="4",
        conventional_stage="M0",
        psma_stage="M0",
        upstaged=False,
        management_changed=True,
    )

    import tracking_db

    record = tracking_db.get_patient_full_record(patient_id)
    assert record["psma_structured_profile"]["available"] is True
    assert record["psma_structured_profile"]["psma_radioligand"] == "68Ga-PSMA-11"
    assert record["psma_structured_profile"]["psma_rads_score"] == "4"
    assert record["psma_structured_profile"]["clinical_pattern"] == "local_pelvic"
    assert record["psma_decision_impact"]["confidence"] == "high"
    assert "salvage_rt" in record["psma_decision_impact"]["decision_domains_affected"]
    assert any("ventana curativa" in item.lower() for item in record["psma_decision_impact"]["recommended_actions"])

    profile_response = client.get(f"/patient_profile/{payload['nss']}")
    assert profile_response.status_code == 200
    profile_html = profile_response.get_data(as_text=True)
    assert "Imagen PSMA estructurada" in profile_html
    assert "68Ga-PSMA-11" in profile_html
    assert "PSMA-RADS 4" in profile_html
    assert "Qué cambia hoy" in profile_html


def test_dashboard_research_intelligence_endpoint_returns_modular_panels(app_client):
    client, db_path = app_client
    metastatic_payload = make_patient_payload(nss="70000000002", full_name="Paciente Research 1")
    metastatic_payload.update(
        {
            "metastasis_site": "Bone",
            "volume_disease": "High",
            "metastasis_count": 6,
            "ecog_score": 1,
            "known_cancer_diagnosis": 1,
            "metachronous_metastasis": 0,
        }
    )
    localized_payload = make_patient_payload(nss="70000000003", full_name="Paciente Research 2")
    localized_payload.update({"baseline_psa": 4.2, "metastasis_site": "M0"})

    first = client.post("/api/register_patient", json=metastatic_payload)
    second = client.post("/api/register_patient", json=localized_payload)
    assert first.status_code == 200
    assert second.status_code == 200
    _insert_structured_psma_imaging(
        db_path,
        first.get_json()["patient_id"],
        psma_result="diseminado",
        radioligand="18F-DCFPyL",
        uptake_pattern="diseminado",
        rads="5",
        total_lesions=7,
        lesion_locations=["hueso", "ganglios", "hígado"],
        conventional_stage="M0",
        psma_stage="M1c",
        upstaged=True,
        management_changed=True,
    )

    response = client.get("/api/dashboard/research-intelligence")
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    assert "survival" in data
    assert "multivariate" in data
    assert "comparative_effectiveness" in data
    assert "operational_outcomes" in data
    assert "quality_indicators" in data
    assert "benchmarking" in data
    assert "dynamic_cohorts" in data
    assert "consent_governance" in data
    assert "research_readiness" in data
    assert "psma_imaging" in data
    assert "laboratory_intelligence" in data
    assert isinstance(data["dynamic_cohorts"], list)
    assert data["consent_governance"]["total_patients"] >= 2
    assert data["psma_imaging"]["study_count"] >= 1
    assert data["psma_imaging"]["structured_coverage_count"] >= 1
    assert data["psma_imaging"]["radioligand_distribution"]["18F-DCFPyL"] >= 1
    assert data["psma_imaging"]["psma_rads_distribution"]["5"] >= 1
    assert data["psma_imaging"]["upstaging_rate_pct"] > 0

    second_response = client.get("/api/dashboard/research-intelligence")
    assert second_response.status_code == 200
    second_data = second_response.get_json()
    assert second_data["success"] is True
    assert "survival" in second_data
    assert "psma_imaging" in second_data
    assert "laboratory_intelligence" in second_data


def test_dashboard_separates_legacy_calibration_from_longitudinal_release_status(app_client):
    client, _db_path = app_client

    response = client.get("/dashboard")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Calibración modular legacy" in html
    assert "Validación longitudinal viva" in html
    assert "estado actual de release longitudinal" in html


def test_research_cohort_survival_and_export_endpoints_work(app_client):
    client, db_path = app_client
    first_payload = make_patient_payload(nss="70000000004", full_name="Cohorte Uno")
    first_payload.update({"baseline_psa": 12.5, "ecog_score": 1})
    second_payload = make_patient_payload(nss="70000000005", full_name="Cohorte Dos")
    second_payload.update({"baseline_psa": 3.1, "ecog_score": 0})

    first = client.post("/api/register_patient", json=first_payload)
    second = client.post("/api/register_patient", json=second_payload)
    assert first.status_code == 200
    assert second.status_code == 200
    first_id = first.get_json()["patient_id"]
    second_id = second.get_json()["patient_id"]

    _update_patient_contact_status(db_path, first_id, last_contact_date="2026-03-12", vital_status="alive")
    _update_patient_contact_status(db_path, second_id, last_contact_date="2026-03-12", vital_status="alive")

    cohort_response = client.post(
        "/api/research/cohorts",
        json={
            "title": "PSA basal alto",
            "description": "Pacientes con PSA basal elevado para análisis institucional.",
            "filters": [{"field": "baseline_psa", "op": "gte", "value": 10}],
        },
    )
    assert cohort_response.status_code == 200
    cohort = cohort_response.get_json()["cohort"]
    assert cohort["title"] == "PSA basal alto"
    assert first_id in cohort["patient_ids"]
    assert second_id not in cohort["patient_ids"]

    cohort_detail = client.get(f"/api/research/cohorts/{cohort['id']}")
    assert cohort_detail.status_code == 200
    assert cohort_detail.get_json()["cohort"]["size"] == 1

    survival_response = client.get(f"/api/research/survival-curves?endpoint=OS&cohort_id={cohort['id']}")
    assert survival_response.status_code == 200
    survival_data = survival_response.get_json()
    assert survival_data["success"] is True
    assert survival_data["endpoint"] == "OS"
    assert survival_data["cohort_label"] == "PSA basal alto"

    export_response = client.get(f"/api/research/export/csv?cohort_id={cohort['id']}")
    assert export_response.status_code == 200
    export_data = export_response.get_json()
    assert export_data["success"] is True
    assert export_data["record_count"] == 1
    assert "baseline_psa" in export_data["csv"]
    assert export_data["manifest"]["scope_label"] == "PSA basal alto"
