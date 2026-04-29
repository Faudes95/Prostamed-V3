# IEC 62304 §5.5 (Unit verification)
from __future__ import annotations

import json
import sqlite3

import tracking_db
from prostanet.domains.patient_tracking.decision_input_requirements_engine import (
    build_decision_input_requirements,
)


def make_patient_payload(nss="CRPC-TEST-001", full_name="Paciente CRPC"):
    return {
        "nss": nss,
        "full_name": full_name,
        "dob": "1964-05-01",
        "line_of_therapy": 1,
        "metastasis_site": "M0",
        "volume_disease": "Low",
        "baseline_psa": 9.2,
        "testosterone_baseline": 330,
    }


def _enable_crpc_copilot(monkeypatch, *, mode="shadow"):
    monkeypatch.setenv("ENABLE_CRPC_COPILOT", "1")
    monkeypatch.setenv("PROSTANET_AI_RUNTIME_MODE", mode)
    import prostanet.ai.config as ai_config_module

    monkeypatch.setattr(ai_config_module, "_config", None, raising=False)


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


def _force_regimen_json_as_string(db_path, patient_id):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE treatment_history
        SET regimen_json = ?
        WHERE patient_id = ?
        """,
        (
            json.dumps(
                {
                    "line_of_therapy_number": 1,
                    "drug_scheme": "Enzalutamide",
                    "drug_scheme_label": "Enzalutamide",
                    "line_of_therapy_context": "metastatic",
                }
            ),
            patient_id,
        ),
    )
    conn.commit()
    conn.close()


def _insert_structured_psma_imaging(
    db_path,
    patient_id,
    *,
    study_date="2026-03-07",
    psma_result="diseminado",
    radioligand="68Ga-PSMA-11",
    uptake_pattern="diseminado",
    rads="5",
    total_lesions=3,
    lesion_locations=None,
    negative_dominant=False,
    conventional_stage="M1b",
    psma_stage="M1b",
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
            14.2,
            json.dumps(
                {
                    "lesion_locations": lesion_locations or ["hueso", "ganglios"],
                    "psma_total_lesions": total_lesions,
                    "psma_negative_dominant_lesions": negative_dominant,
                }
            ),
            radioligand,
            "lesión índice",
            14.2,
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


def _build_bundle(patient_id):
    payload = tracking_db.refresh_longitudinal_intelligence(patient_id, force_recompute=True)
    assert payload
    return payload["crpc_copilot_bundle"]


def _build_longitudinal_bundle(patient_id):
    payload = tracking_db.refresh_longitudinal_intelligence(patient_id, force_recompute=True)
    assert payload
    return payload


def _register_patient(client, *, nss, full_name):
    response = client.post("/api/register_patient", json=make_patient_payload(nss=nss, full_name=full_name))
    assert response.status_code == 200
    return response.get_json()["patient_id"]


def test_crpc_copilot_keeps_verification_when_testosterone_is_not_castrate(app_client, monkeypatch):
    _enable_crpc_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="CRPC-ROUTE-001", full_name="CRPC Verificación")
    _seed_latest_assessment_state(db_path, patient_id, "adt_progression_verification")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "testosterone_value": 120,
            "current_adt_context": "ADT continua",
            "conventional_imaging_status": "M0",
            "progression_pattern": "biochemical_only",
        },
    )

    bundle = _build_bundle(patient_id)

    assert bundle["effective_state"] == "adt_progression_verification"
    assert "castración" in bundle["routing_reason"].lower()
    assert bundle["final_presented_recommendation"]["source"] == "rule_based_primary"


def test_crpc_copilot_routes_adt_progression_to_m0_crpc_when_castrate_and_m0(app_client, monkeypatch):
    _enable_crpc_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="CRPC-ROUTE-002", full_name="CRPC M0")
    _seed_latest_assessment_state(db_path, patient_id, "adt_progression_verification")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "testosterone_value": 18,
            "current_adt_context": "ADT continua",
            "conventional_imaging_status": "M0",
            "progression_pattern": "biochemical_only",
            "psadt_months": 8.0,
        },
    )

    bundle = _build_bundle(patient_id)

    assert bundle["effective_state"] == "m0_crpc"
    assert "m0" in bundle["routing_reason"].lower()


def test_crpc_copilot_routes_adt_progression_to_m1_crpc_when_castrate_and_m1(app_client, monkeypatch):
    _enable_crpc_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="CRPC-ROUTE-003", full_name="CRPC M1")
    _seed_latest_assessment_state(db_path, patient_id, "adt_progression_verification")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "testosterone_value": 16,
            "current_adt_context": "ADT continua",
            "conventional_imaging_status": "M1b",
            "progression_pattern": "radiographic",
        },
    )

    bundle = _build_bundle(patient_id)

    assert bundle["effective_state"] == "m1_crpc"
    assert "metast" in bundle["routing_reason"].lower()


def test_crpc_copilot_exits_m0_crpc_when_psma_only_already_documents_m1(app_client, monkeypatch):
    _enable_crpc_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="CRPC-ROUTE-PSMA-001", full_name="CRPC PSMA M1")
    _seed_latest_assessment_state(db_path, patient_id, "m0_crpc")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "current_adt_context": "ADT continua",
            "conventional_imaging_status": "M0",
            "progression_pattern": "biochemical_only",
            "psa": 4.8,
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

    payload = tracking_db.refresh_longitudinal_intelligence(patient_id, force_recompute=True)
    bundle = payload["crpc_copilot_bundle"]

    assert bundle["effective_state"] == "adt_progression_verification"
    assert payload["signals"]["metastatic_stage_resolved"] == "M1b"
    assert payload["signals"]["metastatic_detection_basis"] == "psma_only"
    assert payload["signals"]["nmcrpc_eligible"] is False
    assert "m1" in payload["signals"]["nmcrpc_ineligibility_reason"].lower()


def test_crpc_copilot_prefers_latest_followup_imaging_over_stale_assessment(app_client, monkeypatch):
    _enable_crpc_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="CRPC-ROUTE-LIVE-001", full_name="CRPC Followup Imaging")
    _seed_latest_assessment_state(db_path, patient_id, "adt_progression_verification")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "testosterone_value": 14,
            "castrate_testosterone_confirmed": 1,
            "current_adt_context": "medical_adt_continuous",
            "conventional_imaging_status": "not_restaged",
            "progression_pattern": "radiographic",
        },
    )
    success, _ = tracking_db.save_stage_visit_bundle(
        patient_id,
        {
            "visit_date": "2026-03-21",
            "visit_type": "validation_followup",
            "state": "adt_progression_verification",
            "management_track": "",
            "disease_status": "validation_followup",
            "psa": 2.1,
            "testosterone": 14,
            "current_adt_context": "medical_adt_continuous",
            "progression_pattern": "radiographic",
            "conventional_imaging_status": "M1b",
        },
    )
    assert success is True

    payload = tracking_db.refresh_longitudinal_intelligence(patient_id, force_recompute=True)
    bundle = payload["crpc_copilot_bundle"]

    assert bundle["effective_state"] == "m1_crpc"
    assert payload["signals"]["effective_state"] == "m1_crpc"
    assert "crpc" in bundle["rule_based_recommendation"]["recommended_action"].lower()


def test_crpc_copilot_keeps_discordant_psma_in_verification_and_publishes_same_state_in_signals(app_client, monkeypatch):
    _enable_crpc_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="CRPC-DISCORD-001", full_name="CRPC Discordante")
    _seed_latest_assessment_state(db_path, patient_id, "adt_progression_verification")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "testosterone_value": 24,
            "castrate_testosterone_confirmed": 1,
            "current_adt_context": "medical_adt_continuous",
            "conventional_imaging_status": "M0",
            "progression_pattern": "mixed",
            "psma_pet_done": 1,
            "psma_rads_score": "3",
            "psma_uptake_pattern": "indeterminado",
        },
    )

    payload = tracking_db.refresh_longitudinal_intelligence(patient_id, force_recompute=True)
    bundle = payload["crpc_copilot_bundle"]

    assert bundle["effective_state"] == "adt_progression_verification"
    assert payload["signals"]["effective_state"] == "adt_progression_verification"
    assert "correlacion" in bundle["rule_based_recommendation"]["recommended_action"].lower()


def test_crpc_copilot_handles_stringified_regimen_json_in_longitudinal_refresh(app_client, monkeypatch):
    _enable_crpc_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="CRPC-REGIMEN-JSON-001", full_name="CRPC Regimen JSON")
    _seed_latest_assessment_state(db_path, patient_id, "m0_crpc")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "testosterone_value": 18,
            "castrate_testosterone_confirmed": 1,
            "current_adt_context": "medical_adt_continuous",
            "conventional_imaging_status": "M0",
            "progression_pattern": "biochemical_only",
            "psadt_months": 7.0,
        },
    )
    _insert_treatment_line(
        db_path,
        patient_id,
        line_of_therapy=1,
        drug_scheme="Enzalutamide",
        start_date="2026-01-02",
        context="mCRPC_first_line",
    )
    _force_regimen_json_as_string(db_path, patient_id)

    bundle = _build_bundle(patient_id)

    assert bundle["available"] is True
    assert bundle["effective_state"] == "m0_crpc"
    assert bundle["rule_based_recommendation"]["recommended_action"]


def test_m0_crpc_prioritizes_darolutamide_when_seizure_risk_is_present(app_client, monkeypatch):
    _enable_crpc_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="CRPC-M0-001", full_name="m0 Darolutamida")
    _seed_latest_assessment_state(db_path, patient_id, "m0_crpc")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "testosterone_value": 18,
            "castrate_testosterone_confirmed": 1,
            "current_adt_context": "ADT continua",
            "psadt_months": 6.0,
            "imaging_negative": 1,
            "conventional_imaging_modality": "TC + gammagrama óseo",
            "conventional_imaging_date": "2026-03-10",
            "comorbidity_seizure": "1",
            "seizure_history": 1,
        },
    )

    bundle = _build_bundle(patient_id)

    assert "darolut" in bundle["rule_based_recommendation"]["recommended_action"].lower()
    assert bundle["preferred_frontline_regimen"]["regimen_code"] == "ADT_DAROLUTAMIDE"
    assert bundle["eligible_treatments"][0]["regimen_code"] == "ADT_DAROLUTAMIDE"
    assert bundle["active_regimen_monitoring_package"]["family_code"] == "arpi_family"
    assert bundle["sequence_transition_bundle"]["active_regimen_code"] == "ADT_DAROLUTAMIDE"
    assert "darolut" in bundle["sequence_candidates"][0]["drug_label"].lower()
    assert bundle["sequence_candidates"][0]["regimen_code"] == "ADT_DAROLUTAMIDE"
    assert "Oral" in bundle["sequence_candidates"][0]["route"]
    assert [item["regimen_code"] for item in bundle["sequence_candidates"][:3]] == [
        "ADT_DAROLUTAMIDE",
        "ADT_ENZALUTAMIDE",
        "ADT_APALUTAMIDE",
    ]
    assert bundle["sequence_candidates"][0]["imss_key"]
    assert bundle["sequence_candidates"][1]["imss_key"]


def test_m0_crpc_requires_negative_imaging_before_arpi_intensification(app_client, monkeypatch):
    _enable_crpc_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="CRPC-M0-001B", full_name="m0 Reestadificación")
    _seed_latest_assessment_state(db_path, patient_id, "m0_crpc")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "testosterone_value": 18,
            "castrate_testosterone_confirmed": 1,
            "current_adt_context": "ADT continua",
            "psadt_months": 6.0,
            "comorbidity_seizure": "1",
            "seizure_history": 1,
        },
    )

    bundle = _build_bundle(patient_id)

    assert bundle["systemic_regimen_scope"] == "nmcrpc_arpi"
    assert "reestadific" in bundle["rule_based_recommendation"]["recommended_action"].lower()
    assert bundle["preferred_frontline_regimen"]["regimen_code"] == "RESTAGING"
    assert bundle["sequence_transition_bundle"]["active_family"] == "observation_family"


def test_m0_crpc_with_psadt_above_ten_favors_observation_before_escalation(app_client, monkeypatch):
    _enable_crpc_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="CRPC-M0-002", full_name="m0 Vigilancia")
    _seed_latest_assessment_state(db_path, patient_id, "m0_crpc")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "testosterone_value": 20,
            "castrate_testosterone_confirmed": 1,
            "current_adt_context": "ADT continua",
            "psadt_months": 12.0,
        },
    )

    bundle = _build_bundle(patient_id)

    assert "reestadific" in bundle["rule_based_recommendation"]["recommended_action"].lower()
    assert bundle["preferred_frontline_regimen"]["regimen_code"] == "RESTAGING"


def test_m1_crpc_blocks_abiraterone_when_hepatic_risk_is_relevant(app_client, monkeypatch):
    _enable_crpc_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="CRPC-M1-001", full_name="m1 Hepático")
    _seed_latest_assessment_state(db_path, patient_id, "m1_crpc")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "testosterone_value": 15,
            "castrate_testosterone_confirmed": 1,
            "current_adt_context": "ADT continua",
            "conventional_imaging_status": "M1b",
            "ast": 180,
            "alt": 160,
            "bilirubin": 3.1,
        },
    )

    bundle = _build_bundle(patient_id)
    hepatic_gate = next(gate for gate in bundle["safety_gates"] if gate["gate_key"] == "abiraterone_hepatic_clearance")

    assert hepatic_gate["status"] == "blocked"
    assert hepatic_gate["failure_family"] == "LFT"


def test_m1_crpc_blocks_parp_priority_without_hrr_traceability(app_client, monkeypatch):
    _enable_crpc_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="CRPC-M1-002", full_name="m1 HRR")
    _seed_latest_assessment_state(db_path, patient_id, "m1_crpc")
    _insert_treatment_line(
        db_path,
        patient_id,
        line_of_therapy=1,
        drug_scheme="ENZALUTAMIDE",
        start_date="2025-01-10",
        context="mCRPC_first_line",
    )
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "testosterone_value": 18,
            "castrate_testosterone_confirmed": 1,
            "current_adt_context": "ADT + Enzalutamida",
            "conventional_imaging_status": "M1b",
            "hrr_status": "positive",
            "brca2_status": "positive",
            "biomarker_source": "",
            "hrr_gene": "",
        },
    )

    bundle = _build_bundle(patient_id)
    hrr_gate = next(gate for gate in bundle["safety_gates"] if gate["gate_key"] == "hrr_traceability")

    assert hrr_gate["status"] == "blocked"
    assert hrr_gate["failure_family"] == "HRR"


def test_m1_crpc_blocks_psma_rlt_when_psma_is_partial_or_discordant(app_client, monkeypatch):
    _enable_crpc_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="CRPC-M1-003", full_name="m1 PSMA")
    _seed_latest_assessment_state(db_path, patient_id, "m1_crpc")
    _insert_treatment_line(
        db_path,
        patient_id,
        line_of_therapy=1,
        drug_scheme="ENZALUTAMIDE",
        start_date="2025-01-10",
        context="mCRPC_post_ARPI_pre_taxane",
    )
    _insert_structured_psma_imaging(
        db_path,
        patient_id,
        rads="3",
        negative_dominant=True,
        conventional_stage="M1b",
        psma_stage="M1b",
    )
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "testosterone_value": 14,
            "castrate_testosterone_confirmed": 1,
            "current_adt_context": "ADT + Enzalutamida",
            "conventional_imaging_status": "M1b",
            "psma_positive": "1",
        },
    )

    bundle = _build_bundle(patient_id)
    psma_gate = next(gate for gate in bundle["safety_gates"] if gate["gate_key"] == "psma_rlt_eligibility")

    assert psma_gate["status"] == "blocked"
    assert psma_gate["failure_family"] == "PSMA"


def test_m1_crpc_prioritizes_non_arpi_after_prior_arpi_and_taxane(app_client, monkeypatch):
    _enable_crpc_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="CRPC-M1-CARD-001", full_name="m1 CARD")
    _seed_latest_assessment_state(db_path, patient_id, "m1_crpc")
    _insert_treatment_line(
        db_path,
        patient_id,
        line_of_therapy=1,
        drug_scheme="ABIRATERONE",
        start_date="2024-01-10",
        end_date="2025-01-10",
        context="mCRPC_first_line",
    )
    _insert_treatment_line(
        db_path,
        patient_id,
        line_of_therapy=2,
        drug_scheme="DOCETAXEL",
        start_date="2025-02-10",
        end_date="2025-07-10",
        context="post_taxane",
    )
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "testosterone_value": 12,
            "castrate_testosterone_confirmed": 1,
            "current_adt_context": "ADT continua",
            "conventional_imaging_status": "M1b",
            "progression_pattern": "radiographic",
            "prior_therapy": "Abiraterona, Docetaxel",
            "mcrpc_line_context": "post_taxane",
            "hrr_status": "positive",
            "hrr_gene": "BRCA2",
            "biomarker_source": "ctDNA",
        },
    )

    bundle = _build_bundle(patient_id)

    assert bundle["sequence_candidates"]
    assert bundle["sequence_candidates"][0]["regimen_code"] not in {"ADT_ENZALUTAMIDE", "ADT_ABIRATERONE"}
    assert bundle["sequence_candidates"][0]["route"]
    assert bundle["sequence_candidates"][0]["description"]


def test_m1_crpc_pre_arpi_keeps_standard_arpi_visible_before_biomarker_shortcuts(app_client, monkeypatch):
    _enable_crpc_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="CRPC-M1-PREARPI-001", full_name="m1 pre-ARPI")
    _seed_latest_assessment_state(db_path, patient_id, "m1_crpc")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "testosterone_value": 14,
            "castrate_testosterone_confirmed": 1,
            "current_adt_context": "ADT continua",
            "conventional_imaging_status": "M1b",
            "progression_pattern": "radiographic",
            "mcrpc_line_context": "pre_arpi",
            "prior_therapy": "ADT",
            "hrr_status": "Positivo",
            "hrr_gene": "BRCA2",
            "biomarker_source": "ctDNA",
            "tmb_high": 1,
            "msi_status": "estable",
        },
    )

    bundle = _build_bundle(patient_id)

    assert "enzalut" in bundle["rule_based_recommendation"]["recommended_action"].lower()
    assert "enzalut" in bundle["sequence_candidates"][0]["drug_label"].lower()
    assert bundle["sequence_candidates"][0]["regimen_code"] == "ADT_ENZALUTAMIDE"
    assert "160 mg al día" in bundle["sequence_candidates"][0]["dose"]


def test_m1_crpc_active_first_line_arpi_is_not_counted_as_exhausted_prior_therapy(app_client, monkeypatch):
    _enable_crpc_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="CRPC-M1-ACTIVE-001", full_name="m1 ARPI activa")
    _seed_latest_assessment_state(db_path, patient_id, "m1_crpc")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "testosterone_value": 14,
            "castrate_testosterone_confirmed": 1,
            "current_adt_context": "ADT continua",
            "conventional_imaging_status": "M1b",
            "progression_pattern": "radiographic",
            "mcrpc_line_context": "pre_arpi",
            "prior_therapy": "ADT",
            "hrr_status": "Positivo",
            "hrr_gene": "BRCA2",
            "biomarker_source": "ctDNA",
            "tmb_high": 1,
            "msi_status": "estable",
            "brca2_status": "Positivo",
        },
    )
    success, _ = tracking_db.save_stage_visit_bundle(
        patient_id,
        {
            "visit_date": "2026-04-06",
            "visit_type": "validation_followup",
            "state": "m1_crpc",
            "management_track": "",
            "disease_status": "validation_followup",
            "psa": 8.1,
            "testosterone": 14,
            "line_of_therapy_number": 1,
            "drug_scheme": "ADT_ENZALUTAMIDE",
            "current_treatment": "ADT + enzalutamida",
            "progression_pattern": "radiographic",
        },
    )
    assert success is True

    bundle = _build_bundle(patient_id)

    assert "enzalut" in bundle["rule_based_recommendation"]["recommended_action"].lower()
    assert "niraparib" not in bundle["rule_based_recommendation"]["recommended_action"].lower()


def test_m1_crpc_post_taxane_prioritizes_psma_blockers_over_generic_line_fields(app_client, monkeypatch):
    _enable_crpc_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="CRPC-M1-VISION-001", full_name="m1 PSMA blockers")
    _seed_latest_assessment_state(db_path, patient_id, "m1_crpc")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "testosterone_value": 12,
            "castrate_testosterone_confirmed": 1,
            "mcrpc_line_context": "post_taxane",
            "prior_therapy": "Abiraterona, Docetaxel",
            "psma_positive": 1,
            "hrr_status": "Positivo",
            "hrr_gene": "BRCA2",
            "brca2_status": "Positivo",
            "biomarker_source": "ctDNA",
        },
    )

    patient = tracking_db.get_patient_full_record(patient_id)
    requirements = build_decision_input_requirements(
        patient,
        effective_state="m1_crpc",
        effective_management_track="palliative_overlay",
        latest_assessment=patient.get("latest_assessment") or {},
        next_best_action={},
    )

    assert "psma_rads_score" in requirements["blocking_inputs"]
    assert "psma_uptake_pattern" in requirements["blocking_inputs"]
    assert "line_of_therapy_number" not in requirements["blocking_inputs"]
    assert "drug_scheme" not in requirements["blocking_inputs"]


def test_m0_crpc_high_risk_requirements_request_arpi_safety_package(app_client, monkeypatch):
    _enable_crpc_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="CRPC-M0-SAFETY-001", full_name="m0 safety")
    _seed_latest_assessment_state(db_path, patient_id, "m0_crpc")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "testosterone_value": 18,
            "castrate_testosterone_confirmed": 1,
            "current_adt_context": "ADT continua",
            "psadt_months": 6.2,
            "imaging_negative": 1,
        },
    )

    patient = tracking_db.get_patient_full_record(patient_id)
    requirements = build_decision_input_requirements(
        patient,
        effective_state="m0_crpc",
        effective_management_track="advanced_sequencing",
        latest_assessment=patient.get("latest_assessment") or {},
        next_best_action={},
    )

    assert "ADT_DAROLUTAMIDE" in requirements["candidate_regimens_under_consideration"]
    assert "ADT_ENZALUTAMIDE" in requirements["candidate_regimens_under_consideration"]
    assert "ADT_APALUTAMIDE" in requirements["candidate_regimens_under_consideration"]
    assert "current_medications" in requirements["decision_blocking_inputs"]
    assert "dermatitis_history" in requirements["decision_blocking_inputs"]
    assert "conventional_imaging_modality" in requirements["decision_blocking_inputs"]
    assert "conventional_imaging_date" in requirements["decision_blocking_inputs"]
    assert "NMCRPC_ARPI" in requirements["regimen_specific_blocks"]


def test_m1_crpc_pre_taxane_requirements_request_structured_taxane_and_abiraterone_inputs(app_client, monkeypatch):
    _enable_crpc_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="CRPC-M1-TAXANE-001", full_name="m1 taxane")
    _seed_latest_assessment_state(db_path, patient_id, "m1_crpc")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "testosterone_value": 12,
            "castrate_testosterone_confirmed": 1,
            "mcrpc_line_context": "first_line_mcrpc",
            "prior_therapy": "ADT",
            "current_treatment": "ADT continua",
            "line_of_therapy_number": 1,
            "drug_scheme": "ADT",
            "progression_pattern": "biochemical_only",
        },
    )

    patient = tracking_db.get_patient_full_record(patient_id)
    requirements = build_decision_input_requirements(
        patient,
        effective_state="m1_crpc",
        effective_management_track="advanced_sequencing",
        latest_assessment=patient.get("latest_assessment") or {},
        next_best_action={},
    )

    assert "DOCETAXEL" in requirements["candidate_regimens_under_consideration"]
    assert "ADT_ABIRATERONE" in requirements["candidate_regimens_under_consideration"]
    assert "anc" in requirements["blocking_inputs"]
    assert "platelets" in requirements["blocking_inputs"]
    assert "cbc_date" in requirements["blocking_inputs"]
    assert "ast" in requirements["blocking_inputs"]
    assert "alt" in requirements["blocking_inputs"]
    assert "bilirubin" in requirements["blocking_inputs"]
    assert "potassium" in requirements["blocking_inputs"]
    assert "systolic_bp" in requirements["blocking_inputs"]
    assert "glucose" in requirements["blocking_inputs"]
    assert requirements["regimen_specific_blocks"]["DOCETAXEL"]["verification_status"] in {"pending_labs", "stale_labs", "verified"}


def test_active_regimen_monitoring_requirements_are_exposed_from_result_snapshot(app_client, monkeypatch):
    _enable_crpc_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="CRPC-M0-MONITOR-001", full_name="m0 monitor")
    _seed_latest_assessment_state(db_path, patient_id, "m0_crpc")
    module_result = client.post(
        "/api/modules/m0_crpc/evaluate",
        json={
            "psadt_months": 6,
            "castration_resistant": 1,
            "castrate_testosterone_confirmed": 1,
            "imaging_negative": 1,
            "comorbidity_seizure": 1,
            "current_treatment": "ADT_DAROLUTAMIDE",
            "psa": 1.7,
            "testosterone": 18,
        },
    ).get_json()["result"]
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "psadt_months": 6,
            "castrate_testosterone_confirmed": 1,
            "imaging_negative": 1,
            "current_treatment": "ADT_DAROLUTAMIDE",
            "drug_scheme": "ADT_DAROLUTAMIDE",
        },
    )

    patient = tracking_db.get_patient_full_record(patient_id)
    patient["latest_assessment"]["result_snapshot"] = module_result
    requirements = build_decision_input_requirements(
        patient,
        effective_state="m0_crpc",
        effective_management_track="advanced_sequencing",
        latest_assessment=patient.get("latest_assessment") or {},
        next_best_action={},
    )

    assert {"psa", "testosterone", "systolic_bp"} <= set(requirements["monitoring_required_fields"])
    assert requirements["monitoring_capture_block"]["family_code"] == "arpi_family"
    assert requirements["monitoring_capture_block"]["active_regimen_code"] == "ADT_DAROLUTAMIDE"
    assert "arpi" in requirements["monitoring_capture_block"]["focus"].lower()


def test_low_volume_requirements_do_not_open_docetaxel_capture_by_default(app_client, monkeypatch):
    _enable_crpc_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="MHSPC-LV-REQ-001", full_name="mhspc low volume")
    _seed_latest_assessment_state(db_path, patient_id, "mcspc_low_volume_sync_oligo")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "metastasis_site": "Bone",
            "metastasis_count": 2,
            "ecog_score": 1,
            "bone_distribution_documented": 1,
        },
    )

    patient = tracking_db.get_patient_full_record(patient_id)
    requirements = build_decision_input_requirements(
        patient,
        effective_state="mcspc_low_volume_sync_oligo",
        effective_management_track="restaging",
        latest_assessment=patient.get("latest_assessment") or {},
        next_best_action={},
    )

    assert "DOCETAXEL" not in requirements["candidate_regimens_under_consideration"]
    assert "anc" not in requirements["blocking_inputs"]
    assert "cbc_date" not in requirements["blocking_inputs"]
    assert "comorbidity_seizure" in requirements["decision_blocking_inputs"]
    assert "child_pugh_score" in requirements["decision_blocking_inputs"]


def test_crpc_copilot_endpoints_and_profile_render_bundle_for_patient_ref(app_client, monkeypatch):
    _enable_crpc_copilot(monkeypatch)
    client, db_path = app_client
    patient_ref = "VAL-CRPC-001"
    patient_id = _register_patient(client, nss=patient_ref, full_name="Paciente Ref CRPC")
    _seed_latest_assessment_state(db_path, patient_id, "m0_crpc")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "testosterone_value": 18,
            "castrate_testosterone_confirmed": 1,
            "current_adt_context": "ADT continua",
            "psadt_months": 6.5,
            "comorbidity_seizure": "1",
            "seizure_history": 1,
        },
    )
    bundle = _build_bundle(patient_id)
    assert bundle["status"] in {"shadow", "shadow-blocked"}

    endpoint_response = client.get(f"/api/crpc-copilot/{patient_ref}")
    assert endpoint_response.status_code == 200
    endpoint_payload = endpoint_response.get_json()
    assert endpoint_payload["success"] is True
    assert endpoint_payload["resolved_patient_ref"] == patient_ref
    assert endpoint_payload["crpc_decision_bundle"]["state_family"] == "m0_crpc"

    assessment_response = client.post(f"/api/ai/full-assessment/{patient_ref}", json={})
    assert assessment_response.status_code == 200
    assessment_payload = assessment_response.get_json()
    assert assessment_payload["success"] is True
    assert assessment_payload["crpc_decision_bundle"]["state_family"] == "m0_crpc"
    assert assessment_payload["final_presented_recommendation"]["source"] == "rule_based_primary"

    schedule_response = client.get(f"/api/patients/{patient_ref}/schedule")
    assert schedule_response.status_code == 200
    schedule_payload = schedule_response.get_json()
    assert schedule_payload["crpc_copilot_status"] in {"shadow", "shadow-blocked"}
    assert "crpc_schedule_overlay" in schedule_payload

    profile_response = client.get(f"/patient_profile/{patient_ref}")
    assert profile_response.status_code == 200
    profile_html = profile_response.get_data(as_text=True)
    assert "Copiloto CRPC" in profile_html
    assert "Decisión primaria NCCN/EAU" in profile_html
    assert "Overlay asesor AI" in profile_html
    assert "Tratamiento preferente y otros elegibles" in profile_html
    assert "Darolutamida" in profile_html
    assert "Clave IMSS" in profile_html


def test_dashboard_research_intelligence_exposes_crpc_copilot_summary(app_client, monkeypatch):
    _enable_crpc_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="CRPC-DASH-001", full_name="Paciente Dashboard CRPC")
    _seed_latest_assessment_state(db_path, patient_id, "m1_crpc")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "testosterone_value": 17,
            "castrate_testosterone_confirmed": 1,
            "current_adt_context": "ADT continua",
            "conventional_imaging_status": "M1b",
            "ast": 145,
            "alt": 150,
            "bilirubin": 2.8,
        },
    )
    _build_bundle(patient_id)

    response = client.get("/api/dashboard/research-intelligence")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert "crpc_copilot" in payload
    assert payload["crpc_copilot"]["available"] is True
    assert payload["crpc_copilot"]["total_patients"] >= 1

    dashboard_response = client.get("/dashboard")
    assert dashboard_response.status_code == 200
    dashboard_html = dashboard_response.get_data(as_text=True)
    assert "Copiloto CRPC" in dashboard_html


def test_crpc_runtime_blocks_nmcrpc_release_when_psma_only_upstaging_remains_unadjudicated(app_client, monkeypatch):
    _enable_crpc_copilot(monkeypatch)
    client, db_path = app_client
    patient_id = _register_patient(client, nss="CRPC-ROUTE-PSMA-001", full_name="CRPC PSMA Only")
    _seed_latest_assessment_state(db_path, patient_id, "m0_crpc")
    _update_latest_assessment_input(
        db_path,
        patient_id,
        {
            "testosterone_value": 18,
            "castrate_testosterone_confirmed": 1,
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
    _insert_structured_psma_imaging(
        db_path,
        patient_id,
        study_date="2026-04-02",
        psma_result="oligometastatic",
        conventional_stage="M0",
        psma_stage="M1a",
        uptake_pattern="oligometastatic",
    )

    longitudinal_bundle = _build_longitudinal_bundle(patient_id)
    readiness = longitudinal_bundle["therapeutic_readiness_bundle"]

    assert longitudinal_bundle["effective_state"] in {"m0_crpc", "m1_crpc"}
    assert readiness["readiness_status"] == "blocked_by_missing_data"
    assert readiness["adjudication_gate_status"] == "blocked_by_missing_data"
    assert any("nmcrpc" in blocker.lower() or "adjudicación" in blocker.lower() for blocker in readiness["release_blockers"])
