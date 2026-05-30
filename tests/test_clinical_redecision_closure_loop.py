from __future__ import annotations

import sqlite3
from pathlib import Path

from prostanet.domains.patient_tracking.clinical_redecision_closure import (
    build_patient_redecision_bundle,
    build_redecision_population,
    validate_closure_request,
)


def _patient(state: str = "diagnostic_workup", *, nss: str = "RD-001"):
    return {
        "identity": {"id": 1, "nss": nss, "full_name": "Paciente ReDecision"},
        "baseline": {},
        "latest_assessment": {"state": state},
        "prior_history": {"current_state": state},
        "treatments": [],
        "patient_events": [],
    }


def _decision_bundle(state: str, missing_fields, *, nss: str = "RD-001", decision_state: str = "redecision_required"):
    return {
        "available": True,
        "source": "clinical_decision_today_fusion_kernel",
        "patient_ref": nss,
        "state": state,
        "state_label": state,
        "decision_state": decision_state,
        "decision_today": {
            "title": "Reabrir decision clinica",
            "status": decision_state,
            "risk_avoided": "Evita continuar una ruta off-track sin reevaluacion.",
        },
        "clinical_rationale": "Clinical Memory o el curso longitudinal exigen nueva decision.",
        "unified_missing_fields": missing_fields,
        "next_safe_action": {
            "title": "Completar dato faltante dominante",
            "action_key": "decision_today:fusion_kernel",
        },
    }


def test_diagnostic_workup_missing_fields_enters_redecision_queue():
    bundle = build_patient_redecision_bundle(
        _patient("diagnostic_workup", nss="RD-DX"),
        decision_today=_decision_bundle(
            "diagnostic_workup",
            ["psa_density", "mri_pirads_score", "biopsy_status"],
            nss="RD-DX",
        ),
        patient_ref="RD-DX",
    )
    population = build_redecision_population([bundle])

    assert bundle["queue_eligible"] is True
    assert bundle["primary_missing_field"]["field"] == "psa_density"
    assert "decision_lane=diagnostic_biopsy_readiness" in bundle["primary_missing_field"]["cta"]["href"]
    assert population["summary"]["queue_count"] == 1


def test_localized_initial_missing_baseline_function_enters_queue():
    bundle = build_patient_redecision_bundle(
        _patient("localized_initial", nss="RD-LOC"),
        decision_today=_decision_bundle(
            "localized_initial",
            [
                {"field": "life_expectancy_years", "readiness_lane": "localized_treatment_readiness"},
                {"field": "ipss_score", "readiness_lane": "localized_treatment_readiness"},
                {"field": "iief5_score", "readiness_lane": "localized_treatment_readiness"},
            ],
            nss="RD-LOC",
        ),
        patient_ref="RD-LOC",
    )

    assert bundle["queue_eligible"] is True
    assert bundle["support_level"] == "v1_supported"
    assert {field["field"] for field in bundle["missing_fields"]} >= {
        "life_expectancy_years",
        "ipss_score",
        "iief5_score",
    }


def test_m1crpc_incomplete_precision_and_line_fields_enters_queue():
    bundle = build_patient_redecision_bundle(
        _patient("m1_crpc", nss="RD-M1"),
        decision_today=_decision_bundle(
            "m1_crpc",
            [
                {"field": "hrr_status", "readiness_lane": "precision_medicine_readiness"},
                {"field": "msi_status", "readiness_lane": "precision_medicine_readiness"},
                {"field": "tmb_status", "readiness_lane": "precision_medicine_readiness"},
                {"field": "real_treatment_line", "readiness_lane": "treatment_line_readiness"},
            ],
            nss="RD-M1",
        ),
        patient_ref="RD-M1",
    )

    assert bundle["queue_eligible"] is True
    assert bundle["state"] == "m1_crpc"
    assert any(item["field"] == "real_treatment_line" for item in bundle["missing_fields"])


def test_resolved_after_recompute_is_rejected_while_decision_still_requires_redecision():
    bundle = build_patient_redecision_bundle(
        _patient("diagnostic_workup", nss="RD-BLOCK"),
        decision_today=_decision_bundle("diagnostic_workup", ["psa_density"], nss="RD-BLOCK"),
        patient_ref="RD-BLOCK",
    )

    ok, message, closure = validate_closure_request(
        {
            "closure_status": "resolved_after_recompute",
            "reviewed_by": "clinician",
            "clinical_note": "Se recalculo pero la decision sigue bloqueada.",
        },
        bundle,
    )

    assert ok is False
    assert "sigue en redecision_required" in message
    assert closure == {}


def test_redecision_api_ui_and_close_contracts(app_client, monkeypatch):
    client, db_path = app_client
    conn = sqlite3.connect(db_path)
    cursor = conn.execute(
        "INSERT INTO patient_identity (nss, full_name, dob, diagnosis_date) VALUES (?, ?, ?, ?)",
        ("RD-API-001", "Paciente API ReDecision", "1958-01-01", "2026-01-01"),
    )
    patient_id = int(cursor.lastrowid)
    conn.commit()
    conn.close()

    import app as app_module
    import tracking_db

    def fake_decision_builder(patient_ref, *, force_recompute=False):
        patient = tracking_db.get_patient_full_record(
            patient_id,
            include_derivatives=False,
            include_ledger=False,
        )
        decision_today = _decision_bundle(
            "diagnostic_workup",
            ["psa_density", "mri_pirads_score", "biopsy_status"],
            nss=str(patient_ref),
        )
        return {
            "patient_id": patient_id,
            "patient": patient,
            "bundle": {"signals": {"effective_management_track_final": "diagnostic_surveillance"}},
            "autodrive": {
                "available": True,
                "source": "clinical_autodrive_command_center",
                "summary": {"priority_status": "critical_today"},
                "today_queue": [
                    {
                        "action_key": "decision_today:fusion_kernel",
                        "lane": "redecision_required",
                        "priority_status": "critical_today",
                    }
                ],
                "decision_today": decision_today,
            },
            "decision_today": decision_today,
            "resolved": {
                "patient_id": patient_id,
                "nss": str(patient_ref),
                "patient_ref": str(patient_ref),
            },
        }, None

    monkeypatch.setattr(app_module, "_build_patient_decision_today_for_api", fake_decision_builder)

    summary = client.get("/api/redecision/today?scope=summary&limit=5")
    full = client.get("/api/redecision/today?scope=full&limit=5&refresh=1")
    patient = client.get("/api/patients/RD-API-001/redecision?refresh=1")
    ui_queue = client.get("/redecision-workbench?refresh=1")
    ui_patient = client.get("/redecision-workbench/RD-API-001?refresh=1")
    rejected = client.post(
        "/api/patients/RD-API-001/redecision/close",
        json={
            "closure_status": "resolved_after_recompute",
            "reviewed_by": "clinician",
            "clinical_note": "Intento de cierre resuelto con Decision Today aun bloqueada.",
        },
    )
    closed = client.post(
        "/api/patients/RD-API-001/redecision/close",
        json={
            "closure_status": "still_blocked",
            "reviewed_by": "clinician",
            "clinical_note": "Se reconoce bloqueo por PSAD, mpMRI y estado de biopsia.",
            "acknowledged_missing_fields": ["psa_density", "mri_pirads_score", "biopsy_status"],
        },
    )

    assert summary.status_code == 200
    assert summary.get_json()["source_clinical_facts_mutated"] is False
    assert "today_queue" in summary.get_json()
    assert full.status_code == 200
    assert full.get_json()["summary"]["queue_count"] == 1
    assert patient.status_code == 200
    assert patient.get_json()["redecision"]["missing_fields"][0]["field"] == "psa_density"
    assert ui_queue.status_code == 200
    assert b"Clinical Re-Decision Closure Loop" in ui_queue.data
    assert ui_patient.status_code == 200
    assert b"Cierre auditable" in ui_patient.data
    assert rejected.status_code == 400
    assert "redecision_required" in rejected.get_json()["error"]
    assert closed.status_code == 200
    assert closed.get_json()["source_clinical_facts_mutated"] is False
    assert closed.get_json()["external_order_created"] is False
    assert closed.get_json()["model_trained"] is False
    assert closed.get_json()["redecision"]["closure_state"]["closure_status"] == "still_blocked"

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT event_type, status, payload_json FROM patient_events WHERE patient_id = ?",
        (patient_id,),
    ).fetchone()
    conn.close()
    assert row[0] == "clinical_redecision_closed"
    assert row[1] == "still_blocked"
    assert "source_clinical_facts_mutated" in row[2]


def test_redecision_summary_fast_path_uses_signal_snapshot_without_patient_rebuild(app_client, monkeypatch):
    client, db_path = app_client
    conn = sqlite3.connect(db_path)
    cursor = conn.execute(
        "INSERT INTO patient_identity (nss, full_name, dob, diagnosis_date, created_at) VALUES (?, ?, ?, ?, ?)",
        ("RD-FAST-001", "Paciente Fast ReDecision", "1959-01-01", "2026-01-01", "2026-05-27T00:00:00"),
    )
    patient_id = int(cursor.lastrowid)
    conn.execute(
        """
        INSERT INTO clinical_signal_snapshots (
            patient_id, state, next_best_action_json, critical_missing_json,
            awaiting_review_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            patient_id,
            "localized_initial",
            '{"title":"Confirmar transición a Enfermedad localizada o regional N1M0","recommendation_family":"Decisión local activa","rationale":"Existe evidencia longitudinal de cáncer confirmado fuera del carril diagnóstico.","governance_status":"hard_stop","immediate_actions":["La decisión actual necesita datos complementarios antes de cerrar la recomendación."],"data_that_could_change_course":["risk_group"]}',
            "[]",
            "[]",
            "2026-05-27T00:00:00",
            "2026-05-27T00:00:00",
        ),
    )
    conn.commit()
    conn.close()

    import app as app_module

    def fail_patient_rebuild(*args, **kwargs):  # pragma: no cover - failure path only
        raise AssertionError("summary scope must not rebuild patient decision bundles")

    monkeypatch.setattr(app_module, "_build_patient_decision_today_for_api", fail_patient_rebuild)

    response = client.get("/api/redecision/today?scope=summary&limit=5&refresh=1")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["audit"]["summary_fast_path"] is True
    assert payload["source_clinical_facts_mutated"] is False
    assert payload["model_trained"] is False
    assert any(item["patient_ref"] == "RD-FAST-001" for item in payload["today_queue"])
    fast_row = next(item for item in payload["today_queue"] if item["patient_ref"] == "RD-FAST-001")
    assert fast_row["decision_state"] == "redecision_required"
    assert fast_row["missing_field"] == "risk_group"
    assert "decision_lane=localized_treatment_readiness" in fast_row["cta"]["href"]


def test_redecision_contracts_are_registered_in_app_and_profile():
    app_source = Path("app.py").read_text(encoding="utf-8")
    profile = Path("templates/patient_profile_v2.html").read_text(encoding="utf-8")
    queue_template = Path("templates/redecision_workbench.html").read_text(encoding="utf-8")
    patient_template = Path("templates/redecision_patient_workbench.html").read_text(encoding="utf-8")

    assert "/api/redecision/today" in app_source
    assert "/api/patients/<patient_ref>/redecision" in app_source
    assert "/api/patients/<patient_ref>/redecision/close" in app_source
    assert "REDECISION_CLOSURE_EVENT_TYPE" in app_source
    assert "Cerrar re-decisión" in profile
    assert "data-testid=\"redecision-workbench\"" in queue_template
    assert "decision_lane" in queue_template
    assert "clinical_note" in patient_template
    assert "source_clinical_facts_mutated" in patient_template


def test_autodrive_fast_path_classifies_reopen_titles_as_redecision_required():
    from app import _autodrive_lane_from_title

    lane, label = _autodrive_lane_from_title(
        "Reabrir decision clinica",
        "Clinical Memory",
        "Nueva decision requerida por progresion documentada",
    )

    assert lane == "redecision_required"
    assert "decisión" in label
