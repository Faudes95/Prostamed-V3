from __future__ import annotations
# IEC 62304 §5.7 (software system testing).

import sqlite3
from pathlib import Path

from prostanet.domains.patient_tracking.clinical_autodrive_command_center import (
    build_patient_autodrive,
)
from prostanet.domains.patient_tracking.clinical_decision_today_fusion_kernel import (
    build_decision_today,
)


def _patient(state: str = "localized_initial", *, nss: str = "DT-001", treatments=None, baseline=None, biomarkers=None):
    return {
        "identity": {"id": 1, "nss": nss, "full_name": "Paciente Decision Today"},
        "baseline": baseline or {},
        "latest_assessment": {"state": state},
        "prior_history": {"current_state": state},
        "treatments": treatments if treatments is not None else [],
        "biomarker_longitudinal": biomarkers if biomarkers is not None else [],
        "patient_events": [],
    }


def _bundle(*, readiness=None, tumor_board=None, care_pathway=None, memory=None, truth=None, facts=None):
    return {
        "signals": {},
        "longitudinal_truth_snapshot": truth or {"field_values": {}},
        "clinical_fact_bundle": facts or {"field_values": {}},
        "clinical_readiness_tower": readiness or {"lanes": []},
        "tumor_board_os": tumor_board or {"options": []},
        "care_pathway_os": care_pathway or {"pathway_actions": []},
        "clinical_memory_os": memory or {"summary": {}, "expected_vs_observed": {}, "redecision_reasons": []},
    }


def test_fusion_localized_incomplete_histopathology_requires_data():
    fusion = build_decision_today(
        _patient("localized_initial"),
        longitudinal_bundle=_bundle(
            readiness={
                "lanes": [
                    {
                        "key": "localized_treatment_readiness",
                        "label": "Tratamiento localizado",
                        "status": "requires_data",
                        "missing_fields": ["histopathology_report"],
                    }
                ]
            }
        ),
        state="localized_initial",
    )

    assert fusion["decision_state"] == "requires_data"
    assert "histopathology_report" in fusion["missing_field_keys"]
    assert fusion["next_safe_action"]["cta"]["href"].startswith("/longitudinal-capture/")


def test_decision_today_surfaces_open_ledger_conflict_quality():
    patient = _patient("m1_crpc")
    patient["latest_assessment"]["input_snapshot"] = {"ecog_score": 1}
    patient["patient_clinical_facts"] = [
        {
            "id": 1,
            "fact_key": "ecog_score",
            "value": 2,
            "is_active": 1,
            "source_record_type": "quick_capture",
            "source_date": "2026-05-01",
            "observed_at": "2026-05-01T10:00:00Z",
        }
    ]

    fusion = build_decision_today(
        patient,
        longitudinal_bundle=_bundle(),
        state="m1_crpc",
    )

    quality = fusion["ledger_quality"]
    assert quality["version"] == "clinical_fact_ledger_decision_quality_v1"
    assert quality["status"] == "blocked_by_critical_conflict"
    assert quality["requires_reconciliation"] is True
    assert quality["critical_conflict_count"] >= 1
    assert quality["open_conflicts"][0]["fact_key"] == "ecog_score"
    assert fusion["source_alignment"]["clinical_fact_ledger"]["status"] == "blocked_by_critical_conflict"
    assert fusion["audit"]["ledger_quality"]["critical_conflict_count"] >= 1
    action = fusion["next_safe_action"]
    assert action["cta"]["action_mode"] == "reconcile_clinical_fact"
    assert action["cta"]["href"] == "/clinical-fact-reconciliation/DT-001"
    assert action["cta"]["decision_field"] == "ecog_score"
    assert "clinical_fact_ledger" in action["source_bundles"]
    assert action["ledger_quality_gate"]["status"] == "blocked_by_critical_conflict"
    assert action["source_clinical_facts_mutated"] is False
    assert action["external_order_created"] is False
    assert action["model_trained"] is False
    assert quality["source_clinical_facts_mutated"] is False
    assert quality["external_order_created"] is False
    assert quality["model_trained"] is False


def test_decision_today_surfaces_reconciled_ledger_watch_without_open_conflict():
    patient = _patient("m1_crpc")
    patient["latest_assessment"]["input_snapshot"] = {"ecog_score": 2}
    patient["patient_clinical_facts"] = [
        {
            "id": 2,
            "fact_key": "ecog_score",
            "value": 1,
            "is_active": 1,
            "source_record_type": "ledger_reconciliation",
            "source_date": "2026-05-02",
            "observed_at": "2026-05-02T10:00:00Z",
            "clinician_verified": 1,
        }
    ]

    fusion = build_decision_today(
        patient,
        longitudinal_bundle=_bundle(),
        state="m1_crpc",
    )

    quality = fusion["ledger_quality"]
    assert quality["status"] == "uses_reconciled_facts"
    assert quality["requires_reconciliation"] is False
    assert quality["uses_reconciled_facts"] is True
    assert quality["conflict_count"] == 0
    assert quality["resolved_watch_count"] >= 1
    assert quality["resolved_watch"][0]["fact_key"] == "ecog_score"
    assert fusion["next_safe_action"]["cta"].get("action_mode") != "reconcile_clinical_fact"


def test_fusion_bcr_excludes_crpc_parp_and_rlt():
    fusion = build_decision_today(
        _patient(
            "recurrence_bcr",
            baseline={
                "prior_prostatectomy": 1,
                "bcr_detected": 1,
                "psa_value": 0.42,
                "psa_doubling_time_months": 7,
                "patient_values": "prioriza control oncologico con baja toxicidad",
                "baseline_pro": "PRO basal documentado",
                "toxicity_tolerance": "evitar toxicidad grado 3",
                "decision_tradeoff": "acepta rescate si cambia supervivencia libre de progresion",
                "redecision_threshold": "nueva decision si PSADT acelera o PSMA cambia conducta",
            },
        ),
        longitudinal_bundle=_bundle(
            tumor_board={
                "options": [
                    {"key": "parp_hrr", "label": "PARP si HRR", "status": "releaseable"},
                    {"key": "psma_rlt", "label": "PSMA-RLT", "status": "releaseable"},
                    {"key": "salvage_local", "label": "Salvage local", "status": "releaseable"},
                ]
            }
        ),
        state="recurrence_bcr",
    )

    assert fusion["decision_state"] == "releaseable"
    assert "salvage" in fusion["decision_today"]["title"].lower()
    assert "parp" not in fusion["decision_today"]["title"].lower()
    assert "psma" not in fusion["decision_today"]["title"].lower()


def test_fusion_routes_bcr_salvage_gap_to_bcr_readiness():
    fusion = build_decision_today(
        _patient(
            "recurrence_bcr",
            baseline={
                "prior_prostatectomy": 1,
                "psa_value": 0.31,
            },
        ),
        longitudinal_bundle=_bundle(
            readiness={
                "lanes": [
                    {
                        "key": "bcr_salvage_readiness",
                        "label": "BCR y rescate",
                        "status": "requires_data",
                        "missing_fields": [
                            "psa_doubling_time_months",
                            "salvage_context_marker",
                            "psma_pet_status",
                        ],
                    }
                ],
                "capture_plan": {"missing_fields": ["psa_doubling_time_months"]},
            }
        ),
        state="recurrence_bcr",
    )

    assert fusion["decision_state"] == "requires_data"
    assert "psa_doubling_time_months" in fusion["missing_field_keys"]
    psadt_plan = next(
        item for item in fusion["unified_missing_fields"] if item["field"] == "psa_doubling_time_months"
    )
    assert psadt_plan["readiness_lane"] == "bcr_salvage_readiness"
    assert "decision_lane=bcr_salvage_readiness" in psadt_plan["cta"]["href"]


def test_fusion_m0crpc_without_testosterone_is_blocked():
    fusion = build_decision_today(
        _patient("m0_crpc", baseline={"psadt_months": 8, "m0_conventional_confirmed": "1"}),
        longitudinal_bundle=_bundle(),
        state="m0_crpc",
    )

    assert fusion["decision_state"] == "blocked"
    assert "testosterone" in fusion["missing_field_keys"]


def test_fusion_mhspc_without_m1_composition_is_blocked():
    fusion = build_decision_today(
        _patient("mcspc_high_volume", baseline={"ecog_score": 1}),
        longitudinal_bundle=_bundle(),
        state="mcspc_high_volume",
    )

    assert fusion["decision_state"] == "blocked"
    assert "m1_composition" in fusion["missing_field_keys"]


def test_fusion_m1crpc_without_real_treatment_line_blocks_sequence():
    fusion = build_decision_today(
        _patient("m1_crpc", treatments=[]),
        longitudinal_bundle=_bundle(),
        state="m1_crpc",
    )

    assert fusion["decision_state"] == "blocked"
    assert "real_treatment_line" in fusion["missing_field_keys"]


def test_fusion_routes_localized_function_preference_gap_to_localized_readiness():
    fusion = build_decision_today(
        _patient(
            "localized_initial",
            baseline={
                "clinical_risk_group": "intermediate",
                "life_expectancy_years": 15,
            },
        ),
        longitudinal_bundle=_bundle(),
        state="localized_initial",
    )

    assert fusion["decision_state"] == "requires_data"
    assert "localized_patient_values" in fusion["missing_field_keys"]
    first_cta = fusion["next_safe_action"]["cta"]
    assert first_cta["readiness_lane"] == "localized_treatment_readiness"
    assert "decision_lane=localized_treatment_readiness" in first_cta["href"]


def test_fusion_routes_patient_twin_preference_gap_to_patient_twin_readiness():
    fusion = build_decision_today(
        _patient(
            "recurrence_bcr",
            baseline={
                "prior_prostatectomy": 1,
                "bcr_detected": 1,
                "psa_value": 0.42,
                "psa_doubling_time_months": 7,
            },
        ),
        longitudinal_bundle=_bundle(),
        state="recurrence_bcr",
    )

    assert fusion["decision_state"] == "requires_data"
    assert "patient_values" in fusion["missing_field_keys"]
    patient_values_plan = next(
        item for item in fusion["unified_missing_fields"] if item["field"] == "patient_values"
    )
    assert patient_values_plan["readiness_lane"] == "patient_twin_readiness"
    assert "decision_lane=patient_twin_readiness" in patient_values_plan["cta"]["href"]


def test_fusion_routes_diagnostic_truth_gap_to_diagnostic_readiness():
    fusion = build_decision_today(
        _patient(
            "diagnostic_workup",
            baseline={"psa_value": 6.2},
        ),
        longitudinal_bundle=_bundle(),
        state="diagnostic_workup",
    )

    assert fusion["decision_state"] == "requires_data"
    assert "psa_density" in fusion["missing_field_keys"]
    assert "mri_pirads_score" in fusion["missing_field_keys"]
    psad_plan = next(
        item for item in fusion["unified_missing_fields"] if item["field"] == "psa_density"
    )
    assert psad_plan["readiness_lane"] == "diagnostic_biopsy_readiness"
    assert "decision_lane=diagnostic_biopsy_readiness" in psad_plan["cta"]["href"]


def test_fusion_does_not_treat_optional_repeat_psa_capture_plan_as_blocker():
    fusion = build_decision_today(
        _patient(
            "diagnostic_workup",
            baseline={"psa_value": 6.2},
        ),
        longitudinal_bundle=_bundle(
            readiness={
                "lanes": [
                    {
                        "key": "diagnostic_biopsy_readiness",
                        "label": "Diagnostico y biopsia",
                        "status": "requires_data",
                        "missing_fields": ["psa_density"],
                    }
                ],
                "capture_plan": {
                    "missing_fields": ["repeat_psa_value"],
                    "groups": [
                        {
                            "lane_key": "diagnostic_biopsy_readiness",
                            "fields": ["psa_density", "repeat_psa_value"],
                        }
                    ],
                },
            }
        ),
        state="diagnostic_workup",
    )

    assert fusion["decision_state"] == "requires_data"
    assert "psa_density" in fusion["missing_field_keys"]
    assert "repeat_psa_value" not in fusion["missing_field_keys"]


def test_fusion_toxicity_or_progression_dominates_elective_decision():
    fusion = build_decision_today(
        _patient("localized_initial"),
        longitudinal_bundle=_bundle(
            tumor_board={"options": [{"key": "rp", "label": "Prostatectomia", "status": "releaseable"}]},
            memory={
                "summary": {"dominant_redecision_reason": "Toxicidad grado 3"},
                "expected_vs_observed": {"status": "toxicity_limited", "reason": "Toxicidad limitante"},
            },
        ),
        state="localized_initial",
    )

    assert fusion["decision_state"] == "urgent_safety"
    assert "toxicidad" in fusion["clinical_rationale"].lower()


def test_fusion_does_not_invent_treatment_biomarkers_or_trials():
    fusion = build_decision_today(
        _patient("m1_crpc", treatments=[], biomarkers=[]),
        longitudinal_bundle=_bundle(),
        state="m1_crpc",
    )
    checks = fusion["audit"]["anti_fallback_checks"]

    assert fusion["audit"]["no_fabricated_treatment"] is True
    assert fusion["audit"]["no_fabricated_biomarkers"] is True
    assert fusion["audit"]["no_fabricated_trial_eligibility"] is True
    assert checks["has_real_treatment_line"] is False
    assert checks["has_real_psa_or_ape"] is False
    assert checks["has_real_testosterone"] is False


def test_autodrive_uses_fusion_kernel_as_canonical_top_action():
    ad = build_patient_autodrive(
        _patient("m0_crpc", baseline={"psadt_months": 7}),
        longitudinal_bundle=_bundle(),
        state="m0_crpc",
    )

    assert ad["decision_today"]["source"] == "clinical_decision_today_fusion_kernel"
    assert ad["today_queue"][0]["action_key"] == "decision_today:fusion_kernel"
    assert ad["summary"]["top_action_key"] == "decision_today:fusion_kernel"


def test_decision_today_api_signals_and_ui_contracts_are_registered(app_client):
    client, db_path = app_client
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO patient_identity (nss, full_name, dob, diagnosis_date) VALUES (?, ?, ?, ?)",
        ("DT-API-001", "Paciente API Decision", "1959-01-01", "2026-01-01"),
    )
    conn.commit()
    conn.close()

    decision = client.get("/api/patients/DT-API-001/decision-today")
    recompute = client.post("/api/patients/DT-API-001/decision-today/recompute", json={})
    signals = client.get("/api/patients/DT-API-001/signals")
    autodrive = client.get("/api/patients/DT-API-001/autodrive")

    assert decision.status_code == 200
    assert decision.get_json()["success"] is True
    assert decision.get_json()["source"] == "clinical_decision_today_fusion_kernel"
    assert decision.get_json()["ledger_quality"]["version"] == "clinical_fact_ledger_decision_quality_v1"
    assert decision.get_json()["ledger_quality"]["source_clinical_facts_mutated"] is False
    assert decision.get_json()["ledger_quality"]["external_order_created"] is False
    assert decision.get_json()["ledger_quality"]["model_trained"] is False
    assert recompute.status_code == 200
    assert recompute.get_json()["source_clinical_facts_mutated"] is False
    assert signals.status_code == 200
    assert "decision_today" in signals.get_json()
    assert "decision_today" in signals.get_json()["signals"]
    assert autodrive.status_code == 200
    assert autodrive.get_json()["decision_today"]["source"] == "clinical_decision_today_fusion_kernel"

    app_source = Path("app.py").read_text(encoding="utf-8")
    profile = Path("templates/patient_profile_v2.html").read_text(encoding="utf-8")
    dashboard = Path("templates/demos/clinical_dashboard_v2_demo.html").read_text(encoding="utf-8")
    patients = Path("templates/patients_v2.html").read_text(encoding="utf-8")
    voice_js = Path("static/js/prostamed_voice_os.js").read_text(encoding="utf-8")
    hub_js = Path("static/js/clinical_hub_quick_classifier.js").read_text(encoding="utf-8")

    assert "/api/patients/<patient_ref>/decision-today" in app_source
    assert "DECISIÓN HOY" in profile
    assert "DECISIÓN HOY" in dashboard
    assert "Decisión hoy" in patients
    assert "/decision-today" in voice_js
    assert "DECISIÓN HOY preliminar" in hub_js
