"""EPIC 22c — v2 adapter integration tests.

End-to-end verification that EPIC 22c Cortana card data binding flows
correctly from a synthetic patient_record (with the documented fact_keys)
through the v2 adapter helpers to the bundle returned by
`bundle_to_v2_profile`.

Confirms the contract documented in tests/test_epic22d_ui_data_concordance.py
Gate 3b: every Cortana card with data binding has its key populated by
the adapter when the trigger conditions are met.
"""

from __future__ import annotations

import pytest

from prostanet.presentation.v2_adapters import (
    bundle_to_v2_profile,
    _brca2_carrier_summary,
    _lynch_carrier_summary,
    _geriatric_frail_summary,
    _young_onset_summary,
    _adt_long_term_summary,
    _survivorship_5y_summary,
    _comorbidity_cv_summary,
)


# ─────────────────── Helpers ───────────────────


def _patient_with_facts(facts: list[dict]) -> dict:
    """Build a minimal patient_record with a clinical_facts list."""
    return {
        "identity": {"id": 1, "diagnosis_date": "2026-05-13"},
        "baseline": {"age": 65},
        "clinical_facts": facts,
    }


# ─────────────────── BRCA2 carrier ───────────────────


def test_brca2_summary_available_when_germline_pathogenic():
    pt = _patient_with_facts([
        {"fact_key": "hrr_gene", "value": "BRCA2"},
        {"fact_key": "germline_pathogenic_variant", "value": "BRCA2:c.5946delT"},
    ])
    summary = _brca2_carrier_summary({}, pt)
    assert summary["available"] is True
    assert summary["gene"] == "BRCA2"
    assert summary["therapeutic_preferred"]
    assert "PROfound" in summary.get("pivotal_trials", []) or summary["pivotal_trials"]


def test_brca2_summary_unavailable_when_no_brca2_signal():
    pt = _patient_with_facts([
        {"fact_key": "hrr_gene", "value": "ATM"},
    ])
    summary = _brca2_carrier_summary({}, pt)
    assert summary["available"] is False


# ─────────────────── Lynch carrier ───────────────────


def test_lynch_summary_via_msh2():
    pt = _patient_with_facts([
        {"fact_key": "hrr_gene", "value": "MSH2"},
    ])
    summary = _lynch_carrier_summary({}, pt)
    assert summary["available"] is True
    assert summary["gene"] == "MSH2"


def test_lynch_summary_via_msi_high_somatic():
    """Somatic MSI-H/dMMR also triggers Lynch state (pembrolizumab eligibility)."""
    pt = _patient_with_facts([
        {"fact_key": "msi_status", "value": "high"},
    ])
    summary = _lynch_carrier_summary({}, pt)
    assert summary["available"] is True


def test_lynch_summary_unavailable_when_no_signal():
    pt = _patient_with_facts([])
    summary = _lynch_carrier_summary({}, pt)
    assert summary["available"] is False


# ─────────────────── Geriatric frail ───────────────────


def test_geriatric_summary_via_age_plus_g8():
    pt = _patient_with_facts([{"fact_key": "g8_score", "value": "12"}])
    pt["baseline"]["age"] = 80
    summary = _geriatric_frail_summary({}, pt)
    assert summary["available"] is True
    assert summary["age"] == 80
    assert summary["g8_score"] == 12.0


def test_geriatric_summary_unavailable_when_fit():
    """Age > 75 but G8 > 14 → NOT geriatric_frail."""
    pt = _patient_with_facts([{"fact_key": "g8_score", "value": "16"}])
    pt["baseline"]["age"] = 80
    summary = _geriatric_frail_summary({}, pt)
    assert summary["available"] is False


def test_geriatric_summary_unavailable_when_younger():
    """Age <= 75 → not geriatric state regardless of G8."""
    pt = _patient_with_facts([{"fact_key": "g8_score", "value": "10"}])
    pt["baseline"]["age"] = 72
    summary = _geriatric_frail_summary({}, pt)
    assert summary["available"] is False


# ─────────────────── Young onset ───────────────────


def test_young_onset_summary_age_dx_lt_55():
    pt = {"identity": {"age_at_diagnosis": 48}}
    summary = _young_onset_summary({}, pt)
    assert summary["available"] is True
    assert summary["age_at_diagnosis"] == 48


def test_young_onset_unavailable_age_dx_ge_55():
    pt = {"identity": {"age_at_diagnosis": 60}}
    summary = _young_onset_summary({}, pt)
    assert summary["available"] is False


# ─────────────────── ADT long-term ───────────────────


def test_adt_long_term_via_explicit_duration():
    pt = _patient_with_facts([
        {"fact_key": "adt_total_duration_months", "value": "36"},
    ])
    summary = _adt_long_term_summary({}, pt)
    assert summary["available"] is True
    assert summary["adt_duration_months"] == 36


def test_adt_long_term_unavailable_under_24mo():
    pt = _patient_with_facts([
        {"fact_key": "adt_total_duration_months", "value": "18"},
    ])
    summary = _adt_long_term_summary({}, pt)
    assert summary["available"] is False


# ─────────────────── Survivorship 5y+ ───────────────────


def test_survivorship_5y_via_years_NED():
    pt = _patient_with_facts([
        {"fact_key": "years_NED", "value": "7"},
    ])
    summary = _survivorship_5y_summary({}, pt)
    assert summary["available"] is True
    assert summary["years_ned"] == 7.0


def test_survivorship_5y_unavailable_under_5y():
    pt = _patient_with_facts([
        {"fact_key": "years_since_curative_tx", "value": "3"},
    ])
    summary = _survivorship_5y_summary({}, pt)
    assert summary["available"] is False


# ─────────────────── Comorbidity CV ───────────────────


def test_comorbidity_cv_via_severe_cv_disease():
    pt = _patient_with_facts([
        {"fact_key": "severe_cv_disease", "value": "true"},
    ])
    summary = _comorbidity_cv_summary({}, pt)
    assert summary["available"] is True


def test_comorbidity_cv_via_cv_risk_band_high():
    pt = _patient_with_facts([
        {"fact_key": "cv_risk_band", "value": "high"},
    ])
    summary = _comorbidity_cv_summary({}, pt)
    assert summary["available"] is True


def test_comorbidity_cv_unavailable_when_no_signal():
    pt = _patient_with_facts([])
    summary = _comorbidity_cv_summary({}, pt)
    assert summary["available"] is False


# ─────────────────── bundle_to_v2_profile (end-to-end) ───────────────────


def test_bundle_includes_all_epic22c_keys():
    """All 7 EPIC 22c bundle keys must be present (even if available=False)."""
    bundle = bundle_to_v2_profile({}, {"identity": {"id": 1}})
    for key in (
        "brca2_carrier", "lynch_carrier", "geriatric_frail",
        "young_onset", "adt_long_term", "survivorship_5y", "comorbidity_cv",
    ):
        assert key in bundle, f"EPIC 22c key {key!r} missing from bundle"


def test_bundle_brca2_carrier_available_with_brca2_facts():
    pt = _patient_with_facts([
        {"fact_key": "hrr_gene", "value": "BRCA2"},
    ])
    bundle = bundle_to_v2_profile({}, pt)
    assert bundle["brca2_carrier"]["available"] is True


def test_bundle_multiple_states_coexist():
    """A patient can match multiple EPIC 22c states simultaneously."""
    pt = {
        "identity": {"age_at_diagnosis": 48},
        "baseline": {"age": 48},
        "clinical_facts": [
            {"fact_key": "hrr_gene", "value": "BRCA2"},
            {"fact_key": "adt_total_duration_months", "value": "36"},
        ],
    }
    bundle = bundle_to_v2_profile({}, pt)
    # All three should be available
    assert bundle["brca2_carrier"]["available"] is True
    assert bundle["young_onset"]["available"] is True
    assert bundle["adt_long_term"]["available"] is True


def test_bundle_biopsy_summary_also_present():
    """EPIC 22b.4 biopsy_summary should still be exposed alongside 22c keys."""
    bundle = bundle_to_v2_profile({}, {"identity": {"id": 1}})
    assert "biopsy_summary" in bundle
