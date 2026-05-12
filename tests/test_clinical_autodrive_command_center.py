from __future__ import annotations

import sqlite3
from pathlib import Path

from prostanet.domains.patient_tracking.clinical_autodrive_command_center import (
    build_autodrive_contract_matrix,
    build_patient_autodrive,
    build_population_autodrive,
    summarize_autodrive_contracts,
)


def _patient(state: str = "m1_crpc", *, nss: str = "AD-001", treatments=None, baseline=None):
    return {
        "identity": {"id": 1, "nss": nss, "full_name": "Paciente Autodrive"},
        "baseline": baseline or {},
        "latest_assessment": {"state": state},
        "prior_history": {"current_state": state},
        "treatments": treatments if treatments is not None else [],
        "patient_events": [],
    }


def _bundle(*, readiness=None, tumor_board=None, care_pathway=None, memory=None):
    return {
        "signals": {},
        "clinical_readiness_tower": readiness or {"lanes": []},
        "tumor_board_os": tumor_board or {"options": []},
        "care_pathway_os": care_pathway or {"pathway_actions": []},
        "clinical_memory_os": memory or {"summary": {}, "expected_vs_observed": {}, "redecision_reasons": []},
    }


def test_autodrive_bcr_excludes_crpc_parp_and_rlt_options():
    tumor_board = {
        "options": [
            {"key": "parp_hrr", "label": "PARP si HRR", "status": "releaseable"},
            {"key": "psma_rlt", "label": "PSMA-RLT", "status": "releaseable"},
            {"key": "salvage_local", "label": "Salvage local", "status": "releaseable"},
        ]
    }

    ad = build_patient_autodrive(
        _patient("recurrence_bcr"),
        longitudinal_bundle=_bundle(tumor_board=tumor_board),
        state="recurrence_bcr",
    )
    titles = " ".join(item["title"].lower() for item in ad["today_queue"])

    assert "salvage" in titles
    assert "parp" not in titles
    assert "psma-rlt" not in titles


def test_autodrive_m0crpc_without_testosterone_is_blocked_by_data():
    ad = build_patient_autodrive(
        _patient("m0_crpc", baseline={"psadt_months": 7}),
        longitudinal_bundle=_bundle(),
        state="m0_crpc",
    )

    assert any(item["lane"] == "blocked_by_data" for item in ad["today_queue"])
    assert any("testosterone" in item["missing_fields"] for item in ad["today_queue"])


def test_autodrive_mhspc_without_m1_composition_is_blocked():
    ad = build_patient_autodrive(
        _patient("mcspc_high_volume"),
        longitudinal_bundle=_bundle(),
        state="mcspc_high_volume",
    )

    assert any(item["lane"] == "blocked_by_data" for item in ad["today_queue"])
    assert any("m1_composition" in item["missing_fields"] for item in ad["today_queue"])


def test_autodrive_m1crpc_without_real_line_blocks_sequencing():
    ad = build_patient_autodrive(
        _patient("m1_crpc", treatments=[]),
        longitudinal_bundle=_bundle(),
        state="m1_crpc",
    )

    assert any(item["lane"] == "blocked_by_data" for item in ad["today_queue"])
    assert any("real_treatment_line" in item["missing_fields"] for item in ad["today_queue"])


def test_autodrive_releaseable_tumor_board_generates_operational_cta():
    ad = build_patient_autodrive(
        _patient("localized_initial"),
        longitudinal_bundle=_bundle(
            tumor_board={
                "options": [
                    {"key": "active_surveillance", "label": "Vigilancia activa", "status": "releaseable"}
                ]
            }
        ),
        state="localized_initial",
    )

    ready = [item for item in ad["today_queue"] if item["lane"] == "ready_to_decide"]
    assert ready
    assert ready[0]["cta"]["href"].endswith("#pm2TumorBoardOS")


def test_autodrive_clinical_memory_requires_redecision_and_urgent_safety():
    memory = {
        "summary": {"requires_redecision": True, "dominant_redecision_reason": "Progresion documentada"},
        "expected_vs_observed": {"status": "toxicity_limited", "reason": "Toxicidad grado 3"},
        "redecision_reasons": [{"reason": "Progresion radiografica"}],
    }
    ad = build_patient_autodrive(
        _patient("m1_crpc", treatments=[{"drug_scheme": "ADT + docetaxel"}]),
        longitudinal_bundle=_bundle(memory=memory),
        state="m1_crpc",
    )

    assert any(item["lane"] == "redecision_required" for item in ad["today_queue"])
    assert any(item["lane"] == "urgent_today" for item in ad["today_queue"])


def test_autodrive_population_filters_by_lane():
    pop = build_population_autodrive(
        [
            _patient("m0_crpc", nss="AD-M0", baseline={}),
            _patient("localized_initial", nss="AD-LOC"),
        ],
        longitudinal_bundles={
            "AD-M0": _bundle(),
            "AD-LOC": _bundle(tumor_board={"options": [{"key": "rp", "label": "RP", "status": "releaseable"}]}),
        },
        lane="blocked_by_data",
    )

    assert pop["summary"]["patient_count"] == 2
    assert pop["today_queue"]
    assert all(item["lane"] == "blocked_by_data" for item in pop["today_queue"])


def test_autodrive_contracts_cover_lanes_gates_and_trials():
    matrix = build_autodrive_contract_matrix()
    summary = summarize_autodrive_contracts(matrix)

    assert summary["all_lanes_covered"] is True
    assert summary["gates_total"] >= 100
    assert summary["gates_coverage_ok"] is True
    assert summary["trials_total"] == 47
    assert summary["trials_contract_ok"] is True


def test_autodrive_api_and_ui_contracts_are_registered(app_client):
    client, db_path = app_client
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO patient_identity (nss, full_name, dob, diagnosis_date) VALUES (?, ?, ?, ?)",
        ("AD-API-001", "Paciente API Autodrive", "1958-01-01", "2026-01-01"),
    )
    conn.commit()
    conn.close()

    today = client.get("/api/autodrive/today")
    patient = client.get("/api/patients/AD-API-001/autodrive")

    assert today.status_code == 200
    assert today.get_json()["success"] is True
    assert "today_queue" in today.get_json()
    assert patient.status_code == 200
    assert patient.get_json()["success"] is True
    assert "autodrive" in patient.get_json()

    signals = client.get("/api/patients/AD-API-001/signals")
    assert signals.status_code == 200
    assert "autodrive" in signals.get_json()

    app_source = Path("app.py").read_text(encoding="utf-8")
    profile = Path("templates/patient_profile_v2.html").read_text(encoding="utf-8")
    dashboard = Path("templates/demos/clinical_dashboard_v2_demo.html").read_text(encoding="utf-8")
    patients = Path("templates/patients_v2.html").read_text(encoding="utf-8")
    voice_js = Path("static/js/prostamed_voice_os.js").read_text(encoding="utf-8")

    assert "/api/autodrive/today" in app_source
    assert "/api/patients/<patient_ref>/autodrive" in app_source
    assert "pm2AutodriveCommandCenter" in profile
    assert "Qué debo hacer hoy" in dashboard
    assert "Autodrive" in patients
    assert "/api/patients/${encodeURIComponent(patientRef)}/autodrive" in voice_js
