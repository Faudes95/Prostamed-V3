# IEC 62304 §5.7 (software system testing).

def _option(bundle, key):
    for option in bundle["options"]:
        if option["key"] == key:
            return option
    raise AssertionError(f"option not found: {key}")


def test_tumor_board_bcr_excludes_crpc_precision_options():
    from prostanet.domains.patient_tracking.tumor_board_os import build_tumor_board_os

    bundle = build_tumor_board_os(
        {
            "identity": {"nss": "TB-BCR-001"},
            "baseline": {
                "prior_prostatectomy": 1,
                "bcr_detected": 1,
                "psa_value": 0.42,
                "psa_doubling_time_months": 7.0,
            },
            "latest_assessment": {"state": "recurrence_bcr"},
            "treatments": [],
        },
        state="recurrence_bcr",
    )

    keys = {option["key"] for option in bundle["options"] if option["status"] != "not_applicable"}
    assert "bcr_restage_salvage_window" in keys
    assert "parp_hrr" not in keys
    assert "psma_rlt" not in keys
    assert "mcrpc_sequence" not in keys


def test_tumor_board_m0crpc_blocks_arpi_without_testosterone_psadt_m0():
    from prostanet.domains.patient_tracking.tumor_board_os import build_tumor_board_os

    bundle = build_tumor_board_os(
        {
            "identity": {"nss": "TB-M0-001"},
            "baseline": {"psa_value": 8.0},
            "latest_assessment": {"state": "m0_crpc"},
            "treatments": [],
        },
        state="m0_crpc",
    )

    option = _option(bundle, "m0crpc_arpi")
    assert option["status"] == "requires_data"
    assert "testosterone_value" in option["missing_fields"]
    assert "psa_doubling_time_months" in option["missing_fields"]
    assert "conventional_imaging_status" in option["missing_fields"]


def test_tumor_board_m1crpc_without_real_line_blocks_sequence_and_does_not_invent_line():
    from prostanet.domains.patient_tracking.tumor_board_os import build_tumor_board_os

    bundle = build_tumor_board_os(
        {
            "identity": {"nss": "TB-M1-EMPTY"},
            "baseline": {
                "metastasis_site": "M1b",
                "psa_value": 14.0,
                "testosterone_value": 22,
                "progression_pattern": "psa",
                "ecog_score": 1,
            },
            "latest_assessment": {"state": "m1_crpc"},
            "treatments": [],
        },
        state="m1_crpc",
    )

    sequence = _option(bundle, "mcrpc_sequence")
    assert sequence["status"] == "requires_data"
    assert "real_treatment_line" in sequence["missing_fields"]
    assert bundle["summary"]["real_treatment_line_count"] == 0
    assert bundle["summary"]["has_real_treatment_line"] is False


def test_tumor_board_mhspc_blocks_intensification_without_m1_composition():
    from prostanet.domains.patient_tracking.tumor_board_os import build_tumor_board_os

    bundle = build_tumor_board_os(
        {
            "identity": {"nss": "TB-MHSPC-001"},
            "baseline": {"psa_value": 28.0, "ecog_score": 1},
            "latest_assessment": {"state": "mcspc_high_volume"},
            "treatments": [],
        },
        state="mcspc_high_volume",
    )

    doublet = _option(bundle, "arpi_doublet")
    triplet = _option(bundle, "triplet_docetaxel_arpi")
    assert doublet["status"] == "requires_data"
    assert triplet["status"] == "requires_data"
    assert "m1_composition" in doublet["missing_fields"]
    assert "m1_composition" in triplet["missing_fields"]


def test_tumor_board_m1crpc_with_one_real_line_reports_exactly_one_line():
    from prostanet.domains.patient_tracking.tumor_board_os import build_tumor_board_os

    bundle = build_tumor_board_os(
        {
            "identity": {"nss": "TB-M1-LINE"},
            "baseline": {
                "metastasis_site": "M1b",
                "psa_value": 14.0,
                "testosterone_value": 22,
                "progression_pattern": "psa",
                "ecog_score": 1,
                "prior_docetaxel_exposure": 1,
                "prior_arpi_exposure": 1,
            },
            "latest_assessment": {"state": "m1_crpc"},
            "treatments": [
                {"line_of_therapy": 1, "drug_scheme": "ADT + docetaxel", "start_date": "2025-01-01"}
            ],
        },
        state="m1_crpc",
    )

    sequence = _option(bundle, "mcrpc_sequence")
    assert bundle["summary"]["real_treatment_line_count"] == 1
    assert "real_treatment_line" not in sequence["missing_fields"]


def test_tumor_board_trial_and_gate_contracts_are_audited():
    from prostanet.domains.patient_tracking.tumor_board_os import build_tumor_board_os

    bundle = build_tumor_board_os({"identity": {"nss": "TB-EMPTY"}})

    assert bundle["audit"]["gate_contract_total"] == 103
    assert bundle["audit"]["gate_contract_covered"] == 103
    assert bundle["audit"]["trials_evaluated"] == 47
    assert bundle["audit"]["trial_contract_summary"]["empty_payload_guard_ok"] is True


def test_tumor_board_what_if_delta_is_no_write_and_reports_option_delta():
    from prostanet.domains.patient_tracking.tumor_board_os import (
        build_tumor_board_os,
        build_tumor_board_what_if_delta,
    )

    patient = {
        "identity": {"nss": "TB-WHATIF"},
        "baseline": {"psa_value": 8.0},
        "latest_assessment": {"state": "m0_crpc"},
        "treatments": [],
    }
    real = build_tumor_board_os(patient, state="m0_crpc")
    hypo = build_tumor_board_os(
        patient,
        state="m0_crpc",
        hypothetical_changes={
            "testosterone_value": 18,
            "psa_doubling_time_months": 7,
            "conventional_imaging_status": "M0",
            "arpi_safety_baseline": "documented",
        },
    )
    delta = build_tumor_board_what_if_delta(
        real_board=real,
        hypothetical_board=hypo,
        hypothetical_changes={"testosterone_value": 18},
    )

    assert delta["success"] is True
    assert delta["no_db_write"] is True
    assert isinstance(delta["options_changed"], list)


def test_tumor_board_os_api_routes_are_registered_contractually():
    from pathlib import Path

    source = Path("app.py").read_text(encoding="utf-8")

    assert "/api/patients/<patient_ref>/tumor-board-os" in source
    assert "/api/patient/<patient_ref>/tumor-board-os" in source
    assert "/api/patients/<patient_ref>/tumor-board-os/what-if" in source
    assert "build_tumor_board_what_if_delta" in source


def test_patient_profile_v2_renders_tumor_board_os_panel():
    from pathlib import Path

    template = Path("templates/patient_profile_v2.html").read_text(encoding="utf-8")

    assert "Tumor Board OS" in template
    assert "/tumor-board-os/what-if" in template
    assert "option.trials_impacted" in template
