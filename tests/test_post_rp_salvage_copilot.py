# IEC 62304 §5.5 (Unit verification)
from __future__ import annotations

import json
import sqlite3

import tracking_db


def make_patient_payload(nss="POSTRP-TEST-001", full_name="Paciente post-RP"):
    return {
        "nss": nss,
        "full_name": full_name,
        "dob": "1962-06-01",
        "line_of_therapy": 1,
        "metastasis_site": "M0",
        "volume_disease": "Low",
        "baseline_psa": 7.8,
        "testosterone_baseline": 310,
    }


def _enable_post_rp_copilot(monkeypatch, *, mode="shadow"):
    monkeypatch.setenv("ENABLE_POST_RP_SALVAGE_COPILOT", "1")
    monkeypatch.setenv("PROSTANET_AI_RUNTIME_MODE", mode)
    import prostanet.ai.config as ai_config_module

    monkeypatch.setattr(ai_config_module, "_config", None, raising=False)


def _register_patient(client, *, nss, full_name):
    response = client.post("/api/register_patient", json=make_patient_payload(nss=nss, full_name=full_name))
    assert response.status_code == 200
    return response.get_json()["patient_id"]


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


def _insert_post_rp_surgery(db_path, patient_id, *, surgery_date="2024-01-15", stage="pT2", margin=0):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO surgical_details (
            patient_id, surgery_date, surgery_type, pathological_stage, surgical_margin_status
        ) VALUES (?, ?, 'RP_robotica', ?, ?)
        """,
        (patient_id, surgery_date, stage, margin),
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


def _insert_inconsistent_postlocal_bcr_context(
    db_path,
    patient_id,
    *,
    surgery_date="2025-11-12",
    bcr_date="2026-03-27",
    bcr_psa=5.0,
):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO surgical_details (
            patient_id, surgery_date, surgery_type, pathological_stage, surgical_margin_status
        ) VALUES (?, ?, 'RP_robotica', 'pT3a', 1)
        """,
        (patient_id, surgery_date),
    )
    cursor.execute(
        """
        INSERT INTO biochemical_recurrence (
            patient_id, primary_treatment, primary_treatment_date, bcr_detected,
            bcr_date, bcr_psa, bcr_definition, salvage_treatment
        ) VALUES (?, 'RP', ?, 0, ?, ?, 'BCR', 'observation')
        """,
        (patient_id, surgery_date, bcr_date, bcr_psa),
    )
    conn.commit()
    conn.close()


def _insert_bcr_without_surgery(db_path, patient_id, *, primary_treatment="RP", bcr_date="2026-03-01", bcr_psa=0.42, psadt=8.0):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO biochemical_recurrence (
            patient_id, primary_treatment, bcr_detected, bcr_date, bcr_psa, bcr_definition, psadt_at_bcr
        ) VALUES (?, ?, 1, ?, ?, 'AUA_0.2', ?)
        """,
        (patient_id, primary_treatment, bcr_date, bcr_psa, psadt),
    )
    conn.commit()
    conn.close()


def _insert_passive_bcr_placeholder(db_path, patient_id, *, primary_treatment="RP", bcr_psa=0.02):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO biochemical_recurrence (
            patient_id, primary_treatment, bcr_detected, bcr_date, bcr_psa, bcr_definition, psadt_at_bcr
        ) VALUES (?, ?, 0, '2026-03-01', ?, 'BCR', NULL)
        """,
        (patient_id, primary_treatment, bcr_psa),
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
    uptake_pattern="focal",
    rads="4",
    total_lesions=1,
    lesion_locations=None,
    negative_dominant=False,
    conventional_stage="M0",
    psma_stage="M0",
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
            12.4,
            json.dumps(
                {
                    "lesion_locations": lesion_locations or ["pelvis"],
                    "psma_total_lesions": total_lesions,
                    "psma_negative_dominant_lesions": negative_dominant,
                }
            ),
            radioligand,
            "lesión índice",
            12.4,
            uptake_pattern,
            rads,
            conventional_stage,
            psma_stage,
            0,
            1,
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


def _build_bundle(patient_id):
    payload = tracking_db.refresh_longitudinal_intelligence(patient_id, force_recompute=True)
    assert payload
    return payload["post_rp_salvage_bundle"]


def test_post_rp_copilot_keeps_stable_surveillance_when_psa_is_indetectable(app_client, monkeypatch):
    _enable_post_rp_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="POSTRP-STABLE-001", full_name="PostRP Estable")
    _insert_post_rp_surgery(db_path, patient_id, stage="pT2", margin=0)
    _seed_latest_assessment_state(db_path, patient_id, "post_prostatectomy")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {"psa_postop": 0.03, "psa": 0.03, "pathologic_stage": "pT2", "surgical_margin": 0},
    )
    _insert_psa_longitudinal_points(db_path, patient_id, [("2024-03-01", 0.03), ("2025-02-01", 0.02)])

    bundle = _build_bundle(patient_id)

    assert bundle["post_prostatectomy_course"] == "stable_surveillance"
    assert bundle["effective_state"] == "post_prostatectomy"
    assert bundle["salvage_window_status"] == "closed"
    assert "vigilancia" in bundle["rule_based_recommendation"]["recommended_action"].lower()


def test_post_rp_copilot_does_not_promote_placeholder_bcr_row_when_detected_is_false(app_client, monkeypatch):
    _enable_post_rp_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="POSTRP-PLACEHOLDER-001", full_name="PostRP Placeholder")
    _insert_post_rp_surgery(db_path, patient_id, stage="pT2", margin=0)
    _insert_passive_bcr_placeholder(db_path, patient_id, primary_treatment="RP", bcr_psa=0.02)
    _seed_latest_assessment_state(db_path, patient_id, "post_prostatectomy")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {"psa_postop": 0.02, "psa": 0.02, "pathologic_stage": "pT2", "surgical_margin": 0},
    )
    _insert_psa_longitudinal_points(db_path, patient_id, [("2024-03-01", 0.02), ("2025-02-01", 0.01)])

    bundle = _build_bundle(patient_id)

    assert bundle["post_prostatectomy_course"] == "stable_surveillance"
    assert bundle["effective_state"] == "post_prostatectomy"


def test_post_rp_adverse_pathology_keeps_surveillance_but_mentions_salvage_planning(app_client, monkeypatch):
    _enable_post_rp_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="POSTRP-ADVERSE-PLAN-001", full_name="PostRP Adverso Plan")
    _insert_post_rp_surgery(db_path, patient_id, stage="pT3a", margin=1)
    _seed_latest_assessment_state(db_path, patient_id, "post_prostatectomy")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "psa_postop": 0.04,
            "psa": 0.04,
            "pathologic_stage": "pT3a",
            "surgical_margin": 1,
            "decipher_risk": "Alto",
        },
    )

    bundle = _build_bundle(patient_id)

    assert bundle["post_prostatectomy_course"] == "stable_surveillance"
    assert "salvage" in bundle["rule_based_recommendation"]["recommended_action"].lower()
    assert "psa" in bundle["rule_based_recommendation"]["recommended_action"].lower()


def test_post_rp_copilot_keeps_persistent_psa_inside_post_prostatectomy(app_client, monkeypatch):
    _enable_post_rp_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="POSTRP-PERSIST-001", full_name="PostRP Persistente")
    _insert_post_rp_surgery(db_path, patient_id, stage="pT2", margin=0)
    _seed_latest_assessment_state(db_path, patient_id, "post_prostatectomy")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {"psa_postop": 0.18, "psa": 0.18, "pathologic_stage": "pT2", "surgical_margin": 0},
    )
    _insert_psa_longitudinal_points(db_path, patient_id, [("2024-03-01", 0.18), ("2024-04-01", 0.21)])

    bundle = _build_bundle(patient_id)

    assert bundle["post_prostatectomy_course"] == "persistent_psa"
    assert bundle["effective_state"] == "post_prostatectomy"
    assert bundle["effective_management_track"] == "salvage_evaluation"
    assert bundle["salvage_window_status"] == "pending_inputs"


def test_post_rp_copilot_promotes_persistent_psa_to_bcr_when_salvage_is_decisive(app_client, monkeypatch):
    _enable_post_rp_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="POSTRP-PERSIST-OPENPEND-001", full_name="PostRP Persistente Open Pending")
    _insert_post_rp_surgery(db_path, patient_id, stage="pT2", margin=0)
    _seed_latest_assessment_state(db_path, patient_id, "post_prostatectomy")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "psa_postop": 0.21,
            "psa": 0.21,
            "psadt_months": 8.0,
            "salvage_local_feasible": 1,
            "psma_pet_done": 0,
            "pathologic_stage": "pT2",
            "surgical_margin": 0,
        },
    )
    _insert_psa_longitudinal_points(db_path, patient_id, [("2024-03-01", 0.18), ("2024-04-01", 0.21)])

    bundle = _build_bundle(patient_id)

    assert bundle["post_prostatectomy_course"] == "persistent_psa"
    assert bundle["effective_state"] == "recurrence_bcr"
    assert bundle["effective_management_track"] == "salvage"
    assert bundle["salvage_window_status"] == "open_pending_restaging"
    assert bundle["rule_based_recommendation"]["recommended_action"] == "Activar salvage temprano intensificado con ADT y PSMA urgente"
    assert "adt" in bundle["local_salvage_pathway"]["recommended_path"].lower()
    assert bundle["local_salvage_pathway"]["psma_restaging_role"] == "urgent_companion"
    assert bundle["post_rp_schedule_overlay"]["schedule_primary_intent"] == "Salvage temprano intensificado con ADT y PSMA urgente"


def test_post_rp_copilot_keeps_persistent_psa_open_as_bcr_after_restaging(app_client, monkeypatch):
    _enable_post_rp_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="POSTRP-PERSIST-OPEN-001", full_name="PostRP Persistente Open")
    _insert_post_rp_surgery(db_path, patient_id, stage="pT2", margin=0)
    _seed_latest_assessment_state(db_path, patient_id, "post_prostatectomy")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "psa_postop": 0.23,
            "psa": 0.23,
            "psadt_months": 9.0,
            "salvage_local_feasible": 1,
            "psma_pet_done": 1,
            "psma_positive": 0,
            "psma_stage_after_psma": "M0",
            "pathologic_stage": "pT2",
        },
    )
    _insert_psa_longitudinal_points(db_path, patient_id, [("2024-03-01", 0.19), ("2024-04-01", 0.23)])

    bundle = _build_bundle(patient_id)

    assert bundle["post_prostatectomy_course"] == "persistent_psa"
    assert bundle["effective_state"] == "recurrence_bcr"
    assert bundle["effective_management_track"] == "salvage"
    assert bundle["salvage_window_status"] == "open"
    assert bundle["rule_based_recommendation"]["recommended_action"] == "Activar salvage temprano intensificado con ADT"
    assert bundle["local_salvage_pathway"]["visible"] is True
    assert "adt" in bundle["local_salvage_pathway"]["recommended_path"].lower()
    assert bundle["local_salvage_pathway"]["psma_restaging_role"] == "already_completed"


def test_post_rp_copilot_high_risk_early_bcr_promotes_srt_plus_adt_and_pelvic_consideration(app_client, monkeypatch):
    _enable_post_rp_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="POSTRP-HR-BCR-001", full_name="PostRP High Risk BCR")
    _insert_post_rp_surgery(db_path, patient_id, stage="pT3b", margin=1)
    _seed_latest_assessment_state(db_path, patient_id, "recurrence_bcr")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "psa_postop": 1.1,
            "psa": 1.1,
            "psa_current": 1.1,
            "psadt_months": 3.5,
            "time_to_recurrence_months": 3,
            "salvage_local_feasible": 1,
            "eligible_pelvic_therapy": 1,
            "psma_pet_done": 0,
            "conventional_imaging_status": "M0",
            "pathologic_stage": "pT3b",
            "surgical_margin": 1,
            "seminal_vesicle_invasion": 1,
        },
    )
    _insert_psa_longitudinal_points(db_path, patient_id, [("2024-03-01", 0.52), ("2024-04-01", 1.10)])

    bundle = _build_bundle(patient_id)

    assert bundle["effective_state"] == "recurrence_bcr"
    assert bundle["rule_based_recommendation"]["recommended_action"] in {
        "Activar salvage intensificado con ADT, PSMA urgente y decidir lecho versus lecho + pelvis",
        "Activar salvage temprano intensificado con ADT y PSMA urgente",
    }
    assert bundle["post_rp_salvage_intensification_profile"]["high_risk_post_rp_salvage"] is True
    assert bundle["local_salvage_pathway"]["pelvic_rt_role"] in {"consider", "preferred"}
    assert bundle["local_salvage_pathway"]["psma_restaging_role"] == "urgent_companion"
    assert bundle["local_salvage_pathway"]["negative_psma_should_not_delay_salvage"] is True
    assert any(
        "PSMA PET/CT urgente" in item
        for item in bundle["local_salvage_pathway"]["companion_actions_required_for_preferred_regimen"]
    )


def test_post_rp_copilot_closes_local_salvage_for_persistent_psa_when_not_feasible(app_client, monkeypatch):
    _enable_post_rp_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="POSTRP-PERSIST-CLOSED-001", full_name="PostRP Persistente Closed")
    _insert_post_rp_surgery(db_path, patient_id, stage="pT2", margin=0)
    _seed_latest_assessment_state(db_path, patient_id, "post_prostatectomy")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "psa_postop": 0.23,
            "psa": 0.23,
            "psadt_months": 7.0,
            "salvage_local_feasible": 0,
            "psma_pet_done": 0,
            "pathologic_stage": "pT2",
        },
    )
    _insert_psa_longitudinal_points(db_path, patient_id, [("2024-03-01", 0.18), ("2024-04-01", 0.23)])

    bundle = _build_bundle(patient_id)

    assert bundle["post_prostatectomy_course"] == "persistent_psa"
    assert bundle["effective_state"] == "recurrence_bcr"
    assert bundle["effective_management_track"] == "systemic_surveillance"
    assert bundle["salvage_window_status"] == "closed"
    assert "cerrar ventana" in bundle["rule_based_recommendation"]["recommended_action"].lower()
    assert bundle["local_salvage_pathway"]["visible"] is False
    assert bundle["post_rp_schedule_overlay"]["schedule_primary_intent"] == "Cerrar ventana de salvage local y redefinir estrategia terapéutica"
    assert any("cerrar ventana" in candidate["label"].lower() for candidate in bundle["sequence_candidates"])


def test_post_rp_copilot_redirects_systemic_for_persistent_psa_with_disseminated_psma(app_client, monkeypatch):
    _enable_post_rp_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="POSTRP-PERSIST-SYS-001", full_name="PostRP Persistente Sistémico")
    _insert_post_rp_surgery(db_path, patient_id, stage="pT2", margin=0)
    _seed_latest_assessment_state(db_path, patient_id, "post_prostatectomy")
    _insert_structured_psma_imaging(
        db_path,
        patient_id,
        psma_result="diseminado",
        uptake_pattern="diseminado",
        rads="5",
        total_lesions=4,
        lesion_locations=["hueso", "ganglios"],
        conventional_stage="M1b",
        psma_stage="M1b",
    )
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "psa_postop": 0.21,
            "psa": 0.21,
            "psadt_months": 6.0,
            "salvage_local_feasible": 0,
            "psma_pet_done": 1,
            "psma_positive": 1,
        },
    )
    _insert_psa_longitudinal_points(db_path, patient_id, [("2024-03-01", 0.18), ("2024-04-01", 0.21)])

    bundle = _build_bundle(patient_id)

    assert bundle["post_prostatectomy_course"] == "persistent_psa"
    assert bundle["effective_state"] == "recurrence_bcr"
    assert bundle["effective_management_track"] == "systemic_surveillance"
    assert bundle["salvage_window_status"] == "redirect_systemic"
    assert "sistém" in bundle["rule_based_recommendation"]["recommended_action"].lower()
    assert bundle["local_salvage_pathway"]["visible"] is False


def test_post_rp_true_bcr_missing_psadt_stays_in_salvage_family_and_derives_truth_from_postop_psa(app_client, monkeypatch):
    _enable_post_rp_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="FABIAN-RECURR-001", full_name="Fabian Recurre")
    _insert_inconsistent_postlocal_bcr_context(db_path, patient_id)
    _seed_latest_assessment_state(db_path, patient_id, "post_prostatectomy")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "local_therapy_date": "2025-11-12",
            "psa_postop": 5.0,
            "psa": 12.0,
            "pathologic_stage": "pT3a",
            "surgical_margin": 1,
            "margin_location": "base derecha",
        },
    )
    _insert_psa_longitudinal_points(
        db_path,
        patient_id,
        [("2026-02-12", 15.0), ("2026-03-27", 5.0)],
    )

    bundle = _build_bundle(patient_id)

    assert bundle["post_prostatectomy_course"] == "true_bcr"
    assert bundle["effective_state"] == "recurrence_bcr"
    assert bundle["effective_management_track"] == "salvage"
    assert bundle["salvage_window_status"] == "pending_inputs"
    assert bundle["rule_based_recommendation"]["recommended_action"] == "Activar salvage y reestadificación dirigida"
    assert bundle["rule_based_recommendation"]["recommendation_family"] == "salvage"
    assert bundle["ai_advisory_overlay"]["recommendation_family"] == "salvage"
    assert any(group.get("required_fields") for group in bundle["blocking_inputs"])


def test_post_rp_copilot_promotes_true_bcr_and_keeps_salvage_window_visible(app_client, monkeypatch):
    _enable_post_rp_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="POSTRP-BCR-001", full_name="PostRP BCR")
    _insert_postlocal_bcr_context(db_path, patient_id, bcr_psa=0.42, psadt=8.0)
    _seed_latest_assessment_state(db_path, patient_id, "post_prostatectomy")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {"psa_current": 0.42, "psadt_months": 8.0, "salvage_local_feasible": 1, "pathologic_stage": "pT2"},
    )

    bundle = _build_bundle(patient_id)

    assert bundle["post_prostatectomy_course"] == "true_bcr"
    assert bundle["effective_state"] == "recurrence_bcr"
    assert bundle["salvage_window_status"] == "open_pending_restaging"
    assert "salvage" in bundle["rule_based_recommendation"]["recommended_action"].lower()


def test_post_rp_copilot_recovers_post_rp_course_from_bcr_and_assessment_context_without_surgery_row(app_client, monkeypatch):
    _enable_post_rp_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="POSTRP-BCR-CTX-001", full_name="PostRP BCR Contexto")
    _insert_bcr_without_surgery(db_path, patient_id, primary_treatment="RP", bcr_psa=0.42, psadt=8.0)
    _seed_latest_assessment_state(db_path, patient_id, "recurrence_bcr")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "prior_prostatectomy": 1,
            "psa_current": 0.42,
            "psadt_months": 8.0,
            "salvage_local_feasible": 1,
            "pathologic_stage": "pT2",
        },
    )

    bundle = _build_bundle(patient_id)

    assert bundle["available"] is True
    assert bundle["post_prostatectomy_course"] == "true_bcr"
    assert bundle["effective_state"] == "recurrence_bcr"


def test_post_rp_copilot_is_not_applicable_for_post_rt_recurrence(app_client, monkeypatch):
    _enable_post_rp_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="POSTRT-NOT-APPLICABLE-001", full_name="PostRT No Aplicable")
    _insert_bcr_without_surgery(db_path, patient_id, primary_treatment="RT", bcr_psa=0.45, psadt=8.0)
    _seed_latest_assessment_state(db_path, patient_id, "recurrence_bcr")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "prior_radiation": 1,
            "psa_current": 0.45,
            "psadt_months": 8.0,
            "salvage_local_feasible": 1,
        },
    )

    bundle = _build_bundle(patient_id)

    assert bundle["available"] is False
    assert bundle["status"] == "not_applicable"


def test_post_rp_copilot_does_not_convert_adverse_pathology_only_into_bcr(app_client, monkeypatch):
    _enable_post_rp_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="POSTRP-ADVERSE-001", full_name="PostRP Adverso")
    _insert_post_rp_surgery(db_path, patient_id, stage="pT3a", margin=1)
    _seed_latest_assessment_state(db_path, patient_id, "post_prostatectomy")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "psa_postop": 0.05,
            "psa": 0.05,
            "pathologic_stage": "pT3a",
            "surgical_margin": 1,
            "decipher_risk": "Alto",
        },
    )

    bundle = _build_bundle(patient_id)
    gate = next(item for item in bundle["safety_gates"] if item["gate_key"] == "adverse_pathology_modifier")

    assert bundle["post_prostatectomy_course"] == "stable_surveillance"
    assert bundle["effective_state"] == "post_prostatectomy"
    assert gate["status"] == "warning"


def test_post_rp_copilot_keeps_local_salvage_visible_when_psma_is_local(app_client, monkeypatch):
    _enable_post_rp_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="POSTRP-LOCAL-001", full_name="PostRP Local")
    _insert_postlocal_bcr_context(db_path, patient_id, bcr_psa=0.46, psadt=8.0)
    _seed_latest_assessment_state(db_path, patient_id, "recurrence_bcr")
    _insert_structured_psma_imaging(
        db_path,
        patient_id,
        psma_result="local/pélvico",
        uptake_pattern="focal",
        rads="4",
        conventional_stage="M0",
        psma_stage="M0",
    )
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {"psa_current": 0.46, "psadt_months": 8.0, "salvage_local_feasible": 1, "psma_pet_done": 1},
    )

    bundle = _build_bundle(patient_id)

    assert bundle["salvage_window_status"] == "open"
    assert bundle["local_salvage_pathway"]["visible"] is True
    assert "salvage" in bundle["local_salvage_pathway"]["recommended_path"].lower()


def test_post_rp_copilot_keeps_oligometastatic_psma_as_mdt_multimodal_pathway(app_client, monkeypatch):
    _enable_post_rp_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="POSTRP-OLIGO-001", full_name="PostRP Oligomet")
    _insert_postlocal_bcr_context(db_path, patient_id, bcr_psa=0.69, psadt=6.0)
    _seed_latest_assessment_state(db_path, patient_id, "recurrence_bcr")
    _insert_structured_psma_imaging(
        db_path,
        patient_id,
        psma_result="oligometastatic",
        uptake_pattern="multifocal",
        rads="4",
        total_lesions=2,
        lesion_locations=["pelvis", "ganglio iliaco"],
        conventional_stage="M0",
        psma_stage="M1a",
    )
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "psa_current": 0.69,
            "psadt_months": 6.0,
            "salvage_local_feasible": 0,
            "psma_pet_done": 1,
            "psma_positive": 1,
            "psma_radioligand": "68Ga-PSMA-11",
            "psma_rads_score": "4",
            "psma_uptake_pattern": "multifocal",
            "psma_stage_after_psma": "M1a",
            "psma_negative_dominant_lesions": 0,
        },
    )

    bundle = _build_bundle(patient_id)

    assert bundle["salvage_window_status"] == "open"
    assert "mdt" in bundle["rule_based_recommendation"]["recommended_action"].lower()
    assert "mdt" in bundle["sequence_candidates"][0]["label"].lower()


def test_post_rp_followup_psma_payload_reopens_window_as_mdt_even_if_baseline_feasibility_was_closed(app_client, monkeypatch):
    _enable_post_rp_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="POSTRP-MDT-LIVE-001", full_name="PostRP MDT payload")
    _insert_postlocal_bcr_context(db_path, patient_id, bcr_psa=0.62, psadt=6.0)
    _seed_latest_assessment_state(db_path, patient_id, "recurrence_bcr")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "prior_prostatectomy": 1,
            "psa_current": 0.62,
            "psadt_months": 6.0,
            "conventional_imaging_status": "M0",
            "salvage_local_feasible": 0,
        },
    )
    success, _ = tracking_db.save_stage_visit_bundle(
        patient_id,
        {
            "visit_date": "2026-04-01",
            "visit_type": "validation_followup",
            "state": "recurrence_bcr",
            "management_track": "",
            "disease_status": "validation_followup",
            "psa": 0.69,
            "psadt_months": 6.0,
            "psma_pet_done": 1,
            "psma_positive": 1,
            "psma_radioligand": "68Ga-PSMA-11",
            "psma_rads_score": "4",
            "psma_uptake_pattern": "multifocal",
            "psma_stage_after_psma": "M1a",
            "psma_negative_dominant_lesions": 0,
        },
    )
    assert success is True

    bundle = _build_bundle(patient_id)

    assert bundle["salvage_window_status"] == "open"
    assert "mdt" in bundle["rule_based_recommendation"]["recommended_action"].lower()


def test_post_rp_copilot_redirects_systemic_when_psma_is_disseminated(app_client, monkeypatch):
    _enable_post_rp_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="POSTRP-SYS-001", full_name="PostRP Sistémico")
    _insert_postlocal_bcr_context(db_path, patient_id, bcr_psa=0.95, psadt=5.0)
    _seed_latest_assessment_state(db_path, patient_id, "recurrence_bcr")
    _insert_structured_psma_imaging(
        db_path,
        patient_id,
        psma_result="diseminado",
        uptake_pattern="diseminado",
        rads="5",
        total_lesions=4,
        lesion_locations=["hueso", "ganglios"],
        conventional_stage="M1b",
        psma_stage="M1b",
    )
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {"psa_current": 0.95, "psadt_months": 5.0, "salvage_local_feasible": 0, "psma_pet_done": 1},
    )

    bundle = _build_bundle(patient_id)

    assert bundle["salvage_window_status"] == "redirect_systemic"
    assert bundle["local_salvage_pathway"]["visible"] is False
    assert "sistém" in bundle["rule_based_recommendation"]["recommended_action"].lower()


def test_post_rp_true_bcr_open_pending_restaging_keeps_psma_as_decisive_blocker(app_client, monkeypatch):
    _enable_post_rp_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="POSTRP-BLOCKER-001", full_name="PostRP Blocker")
    _insert_postlocal_bcr_context(db_path, patient_id, bcr_psa=0.31, psadt=9.0)
    _seed_latest_assessment_state(db_path, patient_id, "recurrence_bcr")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {"psa_current": 0.31, "psadt_months": 9.0, "salvage_local_feasible": 1, "psma_pet_done": 0},
    )

    bundle = _build_bundle(patient_id)
    blocker_fields = {field for group in bundle["blocking_inputs"] for field in group.get("required_fields", [])}

    assert bundle["salvage_window_status"] == "open_pending_restaging"
    assert any("psma" in field.lower() for field in blocker_fields)


def test_post_rp_copilot_endpoints_and_profile_render_bundle_for_patient_ref(app_client, monkeypatch):
    _enable_post_rp_copilot(monkeypatch)
    client, db_path = app_client
    patient_ref = "VAL-POSTRP-001"
    patient_id = _register_patient(client, nss=patient_ref, full_name="Paciente Ref post-RP")
    _insert_postlocal_bcr_context(db_path, patient_id, bcr_psa=0.42, psadt=8.0)
    _seed_latest_assessment_state(db_path, patient_id, "post_prostatectomy")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {"psa_current": 0.42, "psadt_months": 8.0, "salvage_local_feasible": 1, "pathologic_stage": "pT2"},
    )
    bundle = _build_bundle(patient_id)
    assert bundle["status"] in {"shadow", "shadow-blocked"}

    endpoint_response = client.get(f"/api/post-rp-copilot/{patient_ref}")
    assert endpoint_response.status_code == 200
    endpoint_payload = endpoint_response.get_json()
    assert endpoint_payload["success"] is True
    assert endpoint_payload["resolved_patient_ref"] == patient_ref
    assert endpoint_payload["post_rp_decision_bundle"]["post_prostatectomy_course"] == "true_bcr"

    assessment_response = client.post(f"/api/ai/full-assessment/{patient_ref}", json={})
    assert assessment_response.status_code == 200
    assessment_payload = assessment_response.get_json()
    assert assessment_payload["success"] is True
    assert assessment_payload["post_rp_decision_bundle"]["salvage_window_status"] == "open_pending_restaging"
    assert assessment_payload["final_presented_recommendation"]["source"] == "rule_based_primary"

    schedule_response = client.get(f"/api/patients/{patient_ref}/schedule")
    assert schedule_response.status_code == 200
    schedule_payload = schedule_response.get_json()
    assert schedule_payload["post_rp_copilot_status"] in {"shadow", "shadow-blocked"}
    assert schedule_payload["salvage_window_status"] == "open_pending_restaging"
    assert "post_rp_schedule_overlay" in schedule_payload

    profile_response = client.get(f"/patient_profile/{patient_ref}")
    assert profile_response.status_code == 200
    profile_html = profile_response.get_data(as_text=True)
    assert "Copiloto post-RP" in profile_html
    assert "Ventana de salvage" in profile_html
    assert "Decisión primaria NCCN/EAU" in profile_html


def test_dashboard_research_intelligence_exposes_post_rp_summary(app_client, monkeypatch):
    _enable_post_rp_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="POSTRP-DASH-001", full_name="Paciente Dashboard post-RP")
    _insert_postlocal_bcr_context(db_path, patient_id, bcr_psa=0.44, psadt=8.0)
    _seed_latest_assessment_state(db_path, patient_id, "recurrence_bcr")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {"psa_current": 0.44, "psadt_months": 8.0, "salvage_local_feasible": 1, "psma_pet_done": 0},
    )
    _build_bundle(patient_id)

    response = client.get("/api/dashboard/research-intelligence")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert "post_rp_salvage_copilot" in payload
    assert payload["post_rp_salvage_copilot"]["available"] is True
    assert payload["post_rp_salvage_copilot"]["total_patients"] >= 1

    dashboard_response = client.get("/dashboard")
    assert dashboard_response.status_code == 200
    dashboard_html = dashboard_response.get_data(as_text=True)
    assert "Copiloto post-RP" in dashboard_html
