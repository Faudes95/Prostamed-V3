from __future__ import annotations

from datetime import date, timedelta

from prostanet.domains.patient_tracking.care_pathway_os import build_care_pathway_os


def _patient(state: str = "localized_initial") -> dict:
    return {
        "identity": {"id": 1, "nss": "TEST-CPOS"},
        "latest_assessment": {"state": state},
        "prior_history": {"current_state": state},
        "patient_events": [],
    }


def test_releaseable_tumor_board_option_creates_executable_internal_action():
    bundle = {
        "tumor_board_os": {
            "summary": {
                "board_status": "released",
                "winner_option_key": "salvage_local_therapy",
                "winner_option_label": "Salvage local / RT de rescate",
            },
            "recommendation": {"finality": "released"},
            "options": [
                {
                    "key": "salvage_local_therapy",
                    "label": "Salvage local / RT de rescate",
                    "clinical_role": "bcr_salvage",
                    "status": "releaseable",
                    "why": ["Ventana de rescate documentada."],
                }
            ],
        },
        "clinical_readiness_tower": {"summary": {}, "lanes": []},
    }

    pathway = build_care_pathway_os(_patient("recurrence_bcr"), longitudinal_bundle=bundle)

    actions = pathway["pathway_actions"]
    assert actions[0]["action_key"] == "tb:salvage_local_therapy"
    assert actions[0]["action_mode"] == "internal_execution"
    assert actions[0]["status"] == "pending"
    assert pathway["summary"]["winner_option_key"] == "salvage_local_therapy"


def test_requires_data_tumor_board_option_creates_capture_action_not_treatment_release():
    bundle = {
        "tumor_board_os": {
            "summary": {"board_status": "requires_data", "dominant_blocker": "Falta PSADT."},
            "options": [
                {
                    "key": "m0crpc_arpi",
                    "label": "ARPI para m0CRPC",
                    "clinical_role": "m0crpc_treatment",
                    "family_code": "arpi_family",
                    "status": "requires_data",
                    "missing_fields": [
                        "testosterone_value",
                        "psa_doubling_time_months",
                        "conventional_imaging_status",
                    ],
                }
            ],
        },
        "clinical_readiness_tower": {"summary": {"dominant_blocker": "Falta PSADT."}, "lanes": []},
    }

    pathway = build_care_pathway_os(_patient("m0_crpc"), longitudinal_bundle=bundle)
    action_keys = {action["action_key"] for action in pathway["pathway_actions"]}

    assert "tb:m0crpc_arpi" not in action_keys
    assert "tb-data:m0crpc_arpi" in action_keys
    data_action = next(action for action in pathway["pathway_actions"] if action["action_key"] == "tb-data:m0crpc_arpi")
    assert data_action["action_mode"] == "capture"
    assert "testosterone_value" in data_action["missing_fields"]


def test_bcr_pathway_does_not_activate_crpc_parp_or_psma_rlt_without_transition():
    bundle = {
        "tumor_board_os": {
            "summary": {"board_status": "requires_data"},
            "options": [
                {
                    "key": "bcr_restage_salvage_window",
                    "label": "Reestadificar y abrir ventana de salvage",
                    "clinical_role": "bcr_salvage",
                    "status": "requires_data",
                    "missing_fields": ["psa_doubling_time_months"],
                }
            ],
        },
        "clinical_readiness_tower": {
            "summary": {},
            "lanes": [
                {
                    "key": "bcr_salvage_readiness",
                    "label": "BCR y rescate",
                    "status": "requires_data",
                    "missing_fields": ["psa_doubling_time_months"],
                }
            ],
        },
    }

    pathway = build_care_pathway_os(_patient("recurrence_bcr"), longitudinal_bundle=bundle)
    serialized = " ".join(action["title"].lower() for action in pathway["pathway_actions"])

    assert "parp" not in serialized
    assert "psma-rlt" not in serialized
    assert "crpc" not in serialized
    assert any(action["family"] == "localized_treatment" for action in pathway["pathway_actions"])


def test_m1crpc_sequence_requires_real_treatment_line_before_execution():
    bundle = {
        "tumor_board_os": {
            "summary": {"board_status": "requires_data"},
            "options": [
                {
                    "key": "mcrpc_sequence",
                    "label": "Secuenciacion sistemica m1CRPC",
                    "clinical_role": "m1crpc_sequence",
                    "status": "requires_data",
                    "missing_fields": ["real_treatment_line"],
                }
            ],
        },
        "clinical_readiness_tower": {"summary": {}, "lanes": []},
    }

    pathway = build_care_pathway_os(_patient("m1_crpc"), longitudinal_bundle=bundle)
    action = pathway["pathway_actions"][0]

    assert action["action_key"] == "tb-data:mcrpc_sequence"
    assert action["status"] == "pending"
    assert "real_treatment_line" in action["missing_fields"]


def test_completed_schedule_event_marks_action_completed():
    bundle = {
        "tumor_board_os": {"summary": {}, "options": []},
        "clinical_readiness_tower": {"summary": {}, "lanes": []},
        "scheduled_items": [
            {
                "id": 9,
                "schedule_key": "psa-followup",
                "event_type": "psa",
                "label": "APE / PSA",
                "due_date": date.today().isoformat(),
                "completed": 1,
                "completed_date": date.today().isoformat(),
            }
        ],
    }

    pathway = build_care_pathway_os(_patient(), longitudinal_bundle=bundle)

    assert pathway["pathway_actions"][0]["action_key"] == "schedule:psa-followup"
    assert pathway["pathway_actions"][0]["status"] == "completed"
    assert pathway["summary"]["completed_count"] == 1


def test_overdue_schedule_event_creates_redecision_trigger_without_fabricated_data():
    overdue_date = (date.today() - timedelta(days=12)).isoformat()
    bundle = {
        "tumor_board_os": {"summary": {}, "options": []},
        "clinical_readiness_tower": {"summary": {}, "lanes": []},
        "scheduled_items": [
            {
                "id": 10,
                "schedule_key": "testosterone-followup",
                "event_type": "testosterone",
                "label": "Testosterona",
                "due_date": overdue_date,
                "completed": 0,
            }
        ],
    }

    pathway = build_care_pathway_os(_patient("m0_crpc"), longitudinal_bundle=bundle)

    assert pathway["pathway_actions"][0]["status"] == "overdue"
    assert pathway["summary"]["overdue_count"] == 1
    assert pathway["redecision_triggers"]
    assert pathway["audit"]["anti_fabrication_checks"]["no_psa_or_testosterone_created"] is True
