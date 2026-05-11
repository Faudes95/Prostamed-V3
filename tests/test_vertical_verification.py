# IEC 62304 §5.5 (Unit verification)
from __future__ import annotations

from prostanet.domains.clinical_validation.trajectory_catalog import (
    build_trajectory_catalog,
)
from prostanet.domains.clinical_validation.vertical_verification import (
    _build_treatment_assertions,
    _vertical_from_snapshot,
    run_vertical_verification,
)


def test_run_vertical_verification_returns_seeded_and_live_coverage(app_client):
    client, _ = app_client
    expected_seeded_cases = len(build_trajectory_catalog())

    report = run_vertical_verification(
        app=client.application,
        base_url="http://127.0.0.1:8080",
        visual_mode="textual",
        live_limit_per_vertical=1,
        seed_live_samples_when_missing=True,
    )

    assert report["seeded"]["summary"]["total_cases"] == expected_seeded_cases
    assert report["current_db"]["summary"]["total_cases"] >= 6
    assert report["current_db"]["summary"]["sample_coverage"]["mhspc_first"] >= 1
    assert report["current_db"]["summary"]["sample_coverage"]["diagnostic_to_biopsy_first"] >= 1
    assert report["current_db"]["summary"]["sample_coverage"]["localized_surveillance_first"] >= 1
    assert report["current_db"]["summary"]["sample_coverage"]["post_rt_salvage_first"] >= 1
    assert report["current_db"]["summary"]["sample_coverage"]["crpc_first"] >= 1
    assert report["current_db"]["summary"]["sample_coverage"]["post_rp_salvage_first"] >= 1

    for case in report["current_db"]["cases"]:
        status_checks = {
            item["key"]: item["passed"]
            for item in case.get("api_contract_assertions", [])
            if item["key"] in {
                "signals_status_code",
                "schedule_status_code",
                "full_assessment_status_code",
                "copilot_status_code",
            }
        }
        assert status_checks == {
            "signals_status_code": True,
            "schedule_status_code": True,
            "full_assessment_status_code": True,
            "copilot_status_code": True,
        }


def test_vertical_audit_endpoint_returns_report(app_client):
    client, _ = app_client
    expected_seeded_cases = len(build_trajectory_catalog())

    response = client.post(
        "/api/validation/vertical-audit",
        json={
            "visual_mode": "textual",
            "live_limit_per_vertical": 1,
            "seed_live_samples_when_missing": True,
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["report"]["seeded"]["summary"]["total_cases"] == expected_seeded_cases
    assert payload["report"]["current_db"]["summary"]["sample_coverage"]["mhspc_first"] >= 1


def test_vertical_snapshot_classifies_post_rt_recurrence_as_post_rt_vertical():
    snapshot = {
        "signals": {"effective_state": "recurrence_bcr"},
        "longitudinal_bundle": {
            "crpc_copilot_bundle": {"available": False},
            "post_rp_salvage_bundle": {"available": False},
        },
        "patient_record": {
            "bcr": {"primary_treatment": "RT"},
            "latest_assessment": {"input_snapshot": {"prior_radiation": 1}},
            "prior_history": {"current_state": "recurrence_bcr"},
            "baseline": {},
            "surgery": {},
        },
    }

    assert _vertical_from_snapshot(snapshot) == "post_rt_salvage_first"


def test_vertical_treatment_assertions_keep_persistent_psa_pending_inputs_in_post_prostatectomy():
    snapshot = {"patient_record": {}, "signals": {"effective_state": "post_prostatectomy"}}
    bundle = {
        "post_prostatectomy_course": "persistent_psa",
        "salvage_window_status": "pending_inputs",
        "effective_state": "post_prostatectomy",
    }

    assertions = _build_treatment_assertions(snapshot, bundle=bundle, vertical="post_rp_salvage_first")
    assertion = next(item for item in assertions if item["key"] == "persistent_psa_pending_inputs_stays_post_prostatectomy")

    assert assertion["passed"] is True


def test_vertical_treatment_assertions_promote_persistent_psa_once_salvage_window_is_classified():
    snapshot = {"patient_record": {}, "signals": {"effective_state": "recurrence_bcr"}}
    bundle = {
        "post_prostatectomy_course": "persistent_psa",
        "salvage_window_status": "open_pending_restaging",
        "effective_state": "recurrence_bcr",
    }

    assertions = _build_treatment_assertions(snapshot, bundle=bundle, vertical="post_rp_salvage_first")
    assertion = next(item for item in assertions if item["key"] == "persistent_psa_decisive_context_promotes_bcr")

    assert assertion["passed"] is True
