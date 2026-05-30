from __future__ import annotations

from pathlib import Path
import sqlite3


ROOT = Path(__file__).resolve().parents[1]


def _seed_patient(db_path, *, nss="TX-DOSE-001"):
    with sqlite3.connect(str(db_path)) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO patient_identity (nss, full_name, dob, diagnosis_date)
            VALUES (?, ?, ?, ?)
            """,
            (nss, "Paciente Dosis ARPI", "1961-01-01", "2026-05-01"),
        )
        conn.commit()
    return nss


def test_treatment_course_tracks_local_dose_alerts_and_costs(tmp_path):
    import tracking_db

    original = tracking_db.get_db_path()
    db_path = tmp_path / "tracking.db"
    try:
        tracking_db.configure_db_path(str(db_path))
        tracking_db.init_tracking_db()
        nss = _seed_patient(db_path)

        started = tracking_db.start_or_update_treatment_course(
            nss,
            {
                "regimen_code": "ADT_ABIRATERONE",
                "line_of_therapy_number": 1,
                "line_of_therapy_context": "mHSPC_initial",
                "start_date": "2026-05-01",
                "doses_received_before_unit": 2,
                "local_doses_administered": 3,
                "unit_name": "Unidad local",
                "referral_target": "HGZ",
            },
        )
        assert started["success"] is True
        assert started["summary"]["current_course"]["local_dose_count"] == 3
        assert started["summary"]["current_course"]["global_dose_count"] == 5
        assert started["summary"]["current_course"]["intensity"]["intensity"] == "doublet"

        dose_4 = tracking_db.append_treatment_dose_administration(
            nss,
            {
                "treatment_history_id": started["course"]["appended_id"],
                "dose_date": "2026-05-20",
                "unit_name": "Unidad local",
                "referral_target": "HGZ",
            },
        )
        assert dose_4["success"] is True
        assert dose_4["dose_number_local"] == 4
        assert dose_4["dose_number_global"] == 6
        assert dose_4["dose_alert"]["severity"] == "warning"
        assert "HGZ o HGR" in dose_4["dose_alert"]["message"]
        assert dose_4["estimated_cost_mxn"] == 9750.0

        tracking_db.append_treatment_dose_administration(
            nss,
            {"treatment_history_id": started["course"]["appended_id"], "dose_date": "2026-06-10"},
        )
        dose_6 = tracking_db.append_treatment_dose_administration(
            nss,
            {"treatment_history_id": started["course"]["appended_id"], "dose_date": "2026-07-01"},
        )
        assert dose_6["dose_number_local"] == 6
        assert dose_6["dose_alert"]["severity"] == "critical"
        assert "maximo de dosis" in dose_6["dose_alert"]["message"].lower()

        summary = tracking_db.get_patient_treatment_course_summary(nss)
        assert summary["success"] is True
        assert summary["current_course"]["local_dose_count"] == 6
        assert summary["cost_summary"]["estimated_total_spend_mxn"] == 58500.0
        assert summary["cost_summary"]["price_coverage_status"] == "priced_full"

        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            alerts = conn.execute(
                """
                SELECT event_type, status, payload_json
                FROM patient_events
                WHERE event_type = 'treatment_dose_referral_alert'
                ORDER BY id ASC
                """
            ).fetchall()
        assert [row["status"] for row in alerts] == ["warning", "warning", "critical"]
    finally:
        tracking_db.configure_db_path(original)


def test_register_patient_persists_initial_triplet_course_doses_alerts_and_costs(tmp_path):
    import tracking_db

    original = tracking_db.get_db_path()
    db_path = tmp_path / "tracking.db"
    try:
        tracking_db.configure_db_path(str(db_path))
        tracking_db.init_tracking_db()
        nss = "TX-REG-TRIPLET"

        patient_id, message, _meta = tracking_db.register_new_patient(
            {
                "nss": nss,
                "full_name": "Paciente Triplete Inicial",
                "dob": "1961-01-01",
                "assessment_state": "mcspc_high_volume_sync",
                "baseline_psa": "42",
                "ecog_score": "1",
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
        summary = tracking_db.get_patient_treatment_course_summary(nss)
        current = summary["current_course"]
        assert summary["success"] is True
        assert current["regimen_code"] == "ADT_DOCETAXEL_DAROLUTAMIDE"
        assert current["intensity"]["intensity"] == "triplet"
        assert current["local_dose_count"] == 4
        assert current["global_dose_count"] == 6
        assert summary["dose_alert"]["severity"] == "warning"
        assert summary["cost_summary"]["estimated_total_spend_mxn"] == 190000.0
        assert summary["cost_summary"]["estimated_total_medication_spend_mxn"] == 191201.72
        assert summary["cost_summary"]["estimated_arpi_cost_per_dose_mxn"] == 47500.0
        assert summary["cost_summary"]["estimated_cost_per_dose_mxn"] == 47800.43
        assert summary["cost_summary"]["medication_total_coverage_status"] == "partial"
        assert summary["cost_summary"]["unpriced_backbone_components"] == ["ADT"]

        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            treatment = conn.execute(
                """
                SELECT drug_scheme, start_date, regimen_json
                FROM treatment_history
                WHERE patient_id = ?
                """,
                (patient_id,),
            ).fetchone()
            dose_rows = conn.execute(
                """
                SELECT COUNT(*) AS n, MAX(dose_number_global) AS max_global
                FROM treatment_dose_administrations
                WHERE patient_id = ?
                """,
                (patient_id,),
            ).fetchone()
            alerts = conn.execute(
                """
                SELECT status
                FROM patient_events
                WHERE event_type = 'treatment_dose_referral_alert'
                ORDER BY id ASC
                """
            ).fetchall()

        assert treatment["drug_scheme"] == "ADT_DOCETAXEL_DAROLUTAMIDE"
        assert treatment["start_date"] == "2026-05-02"
        assert dose_rows["n"] == 4
        assert dose_rows["max_global"] == 6
        assert [row["status"] for row in alerts] == ["warning"]
    finally:
        tracking_db.configure_db_path(original)


def test_arpi_price_catalog_governance_tracks_required_agents(tmp_path):
    import tracking_db
    from prostanet.domains.patient_tracking.treatment_course_tracker import (
        build_price_catalog_audit,
        estimate_regimen_cost,
    )

    original = tracking_db.get_db_path()
    db_path = tmp_path / "tracking.db"
    try:
        tracking_db.configure_db_path(str(db_path))
        tracking_db.init_tracking_db()

        catalog = tracking_db.get_medication_price_catalog()
        agent_codes = {row["agent_code"] for row in catalog}
        assert {"ABIRATERONE", "ENZALUTAMIDE", "APALUTAMIDE", "DAROLUTAMIDE", "DOCETAXEL"} <= agent_codes

        audit = build_price_catalog_audit(catalog, as_of="2026-05-27")
        assert audit["coverage_count"] == 4
        assert audit["required_count"] == 4
        assert audit["missing_agents"] == []
        assert audit["catalog_status"] == "complete_with_stale_or_unknown_sources"
        assert "ENZALUTAMIDE" in audit["stale_agents"]
        assert "APALUTAMIDE" in audit["stale_agents"]

        triplet_cost = estimate_regimen_cost("ADT_DOCETAXEL_DAROLUTAMIDE", catalog)
        assert triplet_cost["estimated_arpi_cost_mxn"] == 47500.0
        assert triplet_cost["estimated_cost_mxn"] == 47800.43
        assert triplet_cost["coverage_status"] == "priced_full"
        assert [item["agent_code"] for item in triplet_cost["priced_non_arpi_components"]] == ["DOCETAXEL"]
        assert triplet_cost["non_arpi_components_excluded"] == ["ADT"]
        assert triplet_cost["medication_total_coverage_status"] == "partial"
        assert triplet_cost["cost_scope"].startswith("Auditable medication component spend")
    finally:
        tracking_db.configure_db_path(original)


def test_patient_intake_exposes_optional_initial_treatment_capture():
    template = (ROOT / "templates/patient_intake.html").read_text()
    longitudinal_template = (ROOT / "templates/demos/longitudinal_capture_v2_demo.html").read_text()

    assert "Tratamiento sistémico al ingreso" in template
    assert 'id="initialTreatmentEnabled"' in template
    assert 'name="drug_scheme"' in template
    assert 'name="current_treatment_start_date"' in template
    assert 'name="doses_received_before_unit"' in template
    assert 'name="local_doses_administered"' in template
    assert 'data-agent-count="{{ agents|length }}"' in template
    assert "Realizar envio a HGZ o HGR" in template
    assert "Paciente con maximo de dosis otorgadas en esta unidad" in template
    assert 'data-testid="treatment-economic-impact-panel"' in longitudinal_template
    assert "function pm2RenderTreatmentEconomicImpact" in longitudinal_template
    assert "body.treatment_economic_impact" in longitudinal_template


def test_treatment_course_api_and_monthly_arpi_spend(app_client):
    client, db_path = app_client
    nss = _seed_patient(db_path, nss="TX-DOSE-API")

    regimens = client.get("/api/treatment-regimens?state=mcspc_high_volume_sync")
    assert regimens.status_code == 200
    assert any(item["value"] == "ADT_ABIRATERONE" for item in regimens.get_json()["options"])

    start = client.post(
        f"/api/patients/{nss}/treatment-course",
        json={
            "regimen_code": "ADT_ABIRATERONE",
            "line_of_therapy_number": 1,
            "line_of_therapy_context": "mHSPC_initial",
            "start_date": "2026-05-01",
            "doses_received_before_unit": 1,
            "local_doses_administered": 3,
            "unit_name": "Unidad local",
            "referral_target": "HGR",
        },
    )
    assert start.status_code == 200
    course_id = start.get_json()["course"]["appended_id"]

    dose = client.post(
        f"/api/patients/{nss}/treatment-course/{course_id}/dose",
        json={"dose_date": "2026-05-28", "unit_name": "Unidad local", "referral_target": "HGR"},
    )
    assert dose.status_code == 200
    dose_payload = dose.get_json()
    assert dose_payload["dose_alert"]["severity"] == "warning"
    impact = dose_payload["treatment_economic_impact"]
    assert impact["version"] == "treatment_economic_capture_impact_v1"
    assert impact["append_success"] is True
    assert impact["local_dose_delta"] == 1
    assert impact["arpi_spend_delta_mxn"] == 9750.0
    assert impact["after"]["current_course"]["local_dose_count"] == 4
    assert impact["after"]["dose_alert"]["severity"] == "warning"
    assert "patient_profile_v2_treatment_course" in impact["refreshed_surfaces"]
    assert impact["source_clinical_facts_mutated"] is False
    assert impact["external_order_created"] is False
    assert impact["model_trained"] is False

    current = client.get(f"/api/patients/{nss}/treatment-course/current")
    assert current.status_code == 200
    assert current.get_json()["current_course"]["local_dose_count"] == 4

    impact_current = client.get(f"/api/patients/{nss}/treatment-economic-impact")
    assert impact_current.status_code == 200
    assert impact_current.get_json()["snapshot"]["current_course"]["local_dose_count"] == 4

    spend = client.get("/api/analytics/arpi-spend?month=2026-05")
    assert spend.status_code == 200
    payload = spend.get_json()
    assert payload["arpi_dose_count"] == 4
    assert payload["estimated_arpi_spend_mxn"] == 39000.0
    assert payload["price_catalog_audit"]["coverage_pct"] == 100.0
    assert payload["rows"][0]["price_coverage_status"] == "priced_full"

    catalog = client.get("/api/analytics/price-catalog-audit")
    assert catalog.status_code == 200
    assert catalog.get_json()["audit"]["coverage_count"] == 4


def test_triplet_dose_impact_reaches_critical_alert_and_285k_arpi_spend(app_client):
    client, db_path = app_client
    nss = _seed_patient(db_path, nss="TX-DOSE-IMPACT")

    start = client.post(
        f"/api/patients/{nss}/treatment-course",
        json={
            "regimen_code": "ADT_DOCETAXEL_DAROLUTAMIDE",
            "line_of_therapy_number": 1,
            "line_of_therapy_context": "mHSPC_initial",
            "start_date": "2026-05-01",
            "doses_received_before_unit": 2,
            "local_doses_administered": 4,
            "unit_name": "Unidad local",
            "referral_target": "HGZ",
        },
    )
    assert start.status_code == 200
    start_payload = start.get_json()
    course_id = start_payload["course"]["appended_id"]
    start_impact = start_payload["treatment_economic_impact"]
    assert start_impact["after"]["current_course"]["local_dose_count"] == 4
    assert start_impact["after"]["current_course"]["global_dose_count"] == 6
    assert start_impact["after"]["dose_alert"]["severity"] == "warning"
    assert start_impact["after"]["cost_summary"]["estimated_total_spend_mxn"] == 190000.0

    dose_5 = client.post(
        f"/api/patients/{nss}/treatment-course/{course_id}/dose",
        json={"dose_date": "2026-06-01", "unit_name": "Unidad local", "referral_target": "HGZ"},
    )
    assert dose_5.status_code == 200
    assert dose_5.get_json()["treatment_economic_impact"]["after"]["current_course"]["local_dose_count"] == 5

    dose_6 = client.post(
        f"/api/patients/{nss}/treatment-course/{course_id}/dose",
        json={"dose_date": "2026-06-22", "unit_name": "Unidad local", "referral_target": "HGZ"},
    )
    assert dose_6.status_code == 200
    payload = dose_6.get_json()
    impact = payload["treatment_economic_impact"]
    assert payload["dose_alert"]["severity"] == "critical"
    assert impact["critical_alert_now"] is True
    assert impact["after"]["current_course"]["local_dose_count"] == 6
    assert impact["after"]["current_course"]["global_dose_count"] == 8
    assert impact["after"]["cost_summary"]["estimated_total_spend_mxn"] == 285000.0
    assert "maximo de dosis" in impact["clinical_message"].lower()
    assert impact["next_surfaces"]["profile_v2"] == f"/patient_profile/{nss}?v=2"


def test_treatment_course_start_is_idempotent_for_imported_local_doses(tmp_path):
    import tracking_db

    original = tracking_db.get_db_path()
    db_path = tmp_path / "tracking.db"
    try:
        tracking_db.configure_db_path(str(db_path))
        tracking_db.init_tracking_db()
        nss = _seed_patient(db_path, nss="TX-DOSE-IDEMP")
        payload = {
            "regimen_code": "ADT_ABIRATERONE",
            "line_of_therapy_number": 1,
            "line_of_therapy_context": "mHSPC_initial",
            "start_date": "2026-05-01",
            "doses_received_before_unit": 1,
            "local_doses_administered": 3,
            "unit_name": "Unidad local",
            "referral_target": "HGZ",
        }

        first = tracking_db.start_or_update_treatment_course(nss, payload)
        second = tracking_db.start_or_update_treatment_course(nss, payload)

        assert first["success"] is True
        assert first["local_doses_imported_now"] == 3
        assert second["success"] is True
        assert second["course"]["duplicate_reused"] is True
        assert second["existing_local_dose_count"] == 3
        assert second["local_doses_imported_now"] == 0

        with sqlite3.connect(str(db_path)) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM treatment_dose_administrations WHERE patient_id = 1"
            ).fetchone()[0]
        assert count == 3
    finally:
        tracking_db.configure_db_path(original)
