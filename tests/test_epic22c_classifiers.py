"""EPIC 22c — Unit tests for the 6 new clinical state classifiers.

Each classifier is exercised with a representative synthetic patient
that should activate the rule + a counter-case that should NOT.

Tests are deterministic (no model invocation) — they validate that the
NCCN 2026 v2 rules implemented in `clinical_state_classifier.py` map
the documented discriminators to the correct state.
"""

from __future__ import annotations

import pytest

from prostanet.domains.state_classifier.clinical_state_classifier import (
    classify_clinical_state,
    _classify_hereditary_carrier,
    _classify_post_local_modality,
    _classify_pre_diagnostic,
    _classify_oligometastatic_refinement,
    _classify_special_populations,
    _classify_survivorship,
)


# ─────────────────── Hereditary carriers ───────────────────


def test_brca2_carrier_classified_correctly():
    """BRCA2 germline pathogenic variant → brca2_carrier state."""
    result = _classify_hereditary_carrier({
        "germline_testing_performed": True,
        "hrr_gene": "BRCA2",
        "germline_pathogenic_variant": "BRCA2:c.5946delT",
    })
    assert result is not None
    assert result.state == "brca2_carrier"
    assert result.confidence >= 0.90
    assert result.therapeutic_alternative_preferred  # registry-driven, non-empty


def test_brca1_carrier_classified_correctly():
    result = _classify_hereditary_carrier({
        "germline_testing_performed": True,
        "hrr_gene": "BRCA1",
        "germline_pathogenic_variant": "BRCA1:185delAG",
    })
    assert result is not None
    assert result.state == "brca1_carrier"


def test_atm_carrier_classified_correctly():
    result = _classify_hereditary_carrier({
        "germline_testing_performed": True,
        "hrr_gene": "ATM",
        "germline_pathogenic_variant": "ATM:c.7271T>G",
    })
    assert result is not None
    assert result.state == "atm_carrier"


def test_lynch_carrier_via_msh2():
    result = _classify_hereditary_carrier({
        "germline_testing_performed": True,
        "hrr_gene": "MSH2",
        "germline_pathogenic_variant": "MSH2:c.1226_1227delAG",
    })
    assert result is not None
    assert result.state == "lynch_carrier"


def test_hoxb13_carrier_via_g84e():
    result = _classify_hereditary_carrier({
        "germline_testing_performed": True,
        "hrr_gene": "HOXB13",
        "germline_pathogenic_variant": "HOXB13:G84E",
    })
    assert result is not None
    assert result.state == "hoxb13_carrier"


def test_hereditary_carrier_negative_returns_none():
    """No germline testing performed → no specific carrier state."""
    result = _classify_hereditary_carrier({
        "germline_testing_performed": False,
    })
    assert result is None


def test_hereditary_carrier_negative_variant_returns_none():
    """Germline testing done but no pathogenic variant → no carrier state."""
    result = _classify_hereditary_carrier({
        "germline_testing_performed": True,
        "germline_pathogenic_variant": "none",
    })
    assert result is None


# ─────────────────── Post-local by modality ───────────────────


def test_post_brachy_ldr_classified():
    result = _classify_post_local_modality({
        "prior_local_treatment_modality": "brachytherapy_ldr",
        "months_since_local_treatment": 12,
    })
    assert result is not None
    assert result.state == "post_brachy_ldr"


def test_post_ebrt_alone_classified():
    result = _classify_post_local_modality({
        "rt_modality": "imrt",
        "months_since_local_treatment": 24,
    })
    assert result is not None
    assert result.state == "post_ebrt_alone"


def test_post_sbrt_classified():
    result = _classify_post_local_modality({
        "prior_local_treatment_modality": "sbrt",
        "months_since_local_treatment": 8,
    })
    assert result is not None
    assert result.state == "post_sbrt"


def test_post_focal_therapy_classified():
    result = _classify_post_local_modality({
        "prior_local_treatment_modality": "hifu",
        "months_since_local_treatment": 12,
    })
    assert result is not None
    assert result.state == "post_focal_therapy"


def test_post_local_modality_with_bcr_returns_none():
    """Phoenix BCR signature should NOT route to post-local — that's post_rt_bcr."""
    result = _classify_post_local_modality({
        "prior_local_treatment_modality": "ebrt",
        "nadir_psa_post_rt": 0.5,
        "current_psa": 5.0,  # exceeds nadir+2 → BCR
    })
    assert result is None  # post_rt_bcr should fire elsewhere


# ─────────────────── Pre-diagnostic ───────────────────


def test_suspected_low_psa_no_biopsy():
    result = _classify_pre_diagnostic({
        "known_cancer_diagnosis": False,
        "baseline_psa": 6.5,
        "pirads_score": 2,
        "age": 60,
    })
    assert result is not None
    assert result.state == "suspected_low_psa_no_biopsy"


def test_suspected_elevated_psa_watchful_wait():
    result = _classify_pre_diagnostic({
        "known_cancer_diagnosis": False,
        "baseline_psa": 25.0,
        "ecog": "3",
        "frailty_status": "frail",
    })
    assert result is not None
    assert result.state == "suspected_elevated_psa_watchful_wait"


def test_negative_biopsy_age_lt_45():
    result = _classify_pre_diagnostic({
        "known_cancer_diagnosis": False,
        "baseline_psa": 5.0,
        "age": 42,
        "prior_negative_biopsy": True,
        "first_degree_relative_pca_lt60": True,
    })
    assert result is not None
    assert result.state == "negative_biopsy_age_lt_45"


def test_pre_diagnostic_known_cancer_returns_none():
    """Patient with known PCa diagnosis is not a pre-diagnostic state."""
    result = _classify_pre_diagnostic({
        "known_cancer_diagnosis": True,
        "baseline_psa": 6.5,
    })
    assert result is None


# ─────────────────── Oligometastatic refinement ───────────────────


def test_oligometastatic_synchronous():
    result = _classify_oligometastatic_refinement({
        "metastasis_count": 2,
        "metastatic_timing": "synchronous",
    })
    assert result is not None
    assert result.state == "oligometastatic_synchronous"


def test_oligo_recurrent_post_definitive():
    result = _classify_oligometastatic_refinement({
        "metastasis_count": 2,
        "prior_local_treatment_done": True,
        "metastatic_timing": "metachronous",
    })
    assert result is not None
    assert result.state == "oligo_recurrent_post_definitive"


def test_oligometastatic_too_many_lesions_returns_none():
    """More than 3 lesions is not oligometastatic."""
    result = _classify_oligometastatic_refinement({
        "metastasis_count": 8,
        "metastatic_timing": "synchronous",
    })
    assert result is None


# ─────────────────── Special populations ───────────────────


def test_geriatric_frail_limited_via_g8():
    result = _classify_special_populations({
        "age": 80,
        "g8_score": 12,
    })
    assert result is not None
    assert result.state == "geriatric_frail_limited"


def test_geriatric_fit_returns_none_or_other():
    """Age >75 but G8 high should NOT be geriatric_frail_limited."""
    result = _classify_special_populations({
        "age": 80,
        "g8_score": 16,
    })
    # Should not match geriatric_frail_limited specifically
    if result is not None:
        assert result.state != "geriatric_frail_limited"


def test_young_onset_pca():
    result = _classify_special_populations({
        "age_at_diagnosis": 48,
    })
    assert result is not None
    assert result.state == "young_onset_pca"


def test_comorbidity_severe_cv():
    result = _classify_special_populations({
        "severe_cv_disease": True,
    })
    assert result is not None
    assert result.state == "comorbidity_limited_severe_cv"


def test_comorbidity_severe_hepatic():
    result = _classify_special_populations({
        "active_liver_disease": True,
    })
    assert result is not None
    assert result.state == "comorbidity_limited_severe_hepatic"


# ─────────────────── Survivorship ───────────────────


def test_survivorship_post_curative_5y_plus():
    result = _classify_survivorship({
        "years_since_curative_tx": 7,
    })
    assert result is not None
    assert result.state == "survivorship_post_curative_5y_plus"


def test_adt_long_term_complications():
    result = _classify_survivorship({
        "adt_total_duration_months": 36,
    })
    assert result is not None
    assert result.state == "adt_long_term_complications"


def test_second_primary_surveillance():
    result = _classify_survivorship({
        "years_post_rt": 7,
        "prior_pelvic_rt_dose_gy": 78,
    })
    assert result is not None
    assert result.state == "second_primary_surveillance"


def test_survivorship_early_returns_none():
    """Less than 5y NED is not in survivorship state yet."""
    result = _classify_survivorship({
        "years_since_curative_tx": 2,
    })
    assert result is None


# ─────────────────── End-to-end via classify_clinical_state ───────────────────


def test_classify_clinical_state_routes_brca2_correctly():
    """The main entrypoint should dispatch to hereditary_carrier first."""
    result = classify_clinical_state({
        "germline_testing_performed": True,
        "hrr_gene": "BRCA2",
        "germline_pathogenic_variant": "BRCA2:c.5946delT",
    })
    assert result is not None
    assert result.state == "brca2_carrier"


def test_classify_clinical_state_routes_geriatric_correctly():
    result = classify_clinical_state({
        "age": 82,
        "g8_score": 11,
    })
    assert result is not None
    assert result.state == "geriatric_frail_limited"


def test_classify_clinical_state_routes_survivorship_correctly():
    result = classify_clinical_state({
        "years_since_curative_tx": 7,
    })
    assert result is not None
    assert result.state == "survivorship_post_curative_5y_plus"


def test_classify_clinical_state_priority_survivorship_over_special():
    """Survivorship fires BEFORE special_populations (priority order matters)."""
    # 82-year-old surveillance 7y NED — should be survivorship_5y, not geriatric_frail
    result = classify_clinical_state({
        "age": 82,
        "g8_score": 11,
        "years_since_curative_tx": 7,
    })
    assert result is not None
    assert result.state == "survivorship_post_curative_5y_plus"
