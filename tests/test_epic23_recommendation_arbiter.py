"""EPIC 23 — Clinical Recommendation Arbiter tests.

Validates the 4 conflict detectors + re-ranking logic + fusion summary
output contract. These tests are the FDA SaMD audit trail validation
that the arbiter consistently catches the cross-card inconsistencies the
clinician identified on 2026-05-13.

Skills applied:
- /fda-medtech-compliance-auditor: each test maps to a documented conflict class
- /backend-patterns: detector isolation + composition tests
- /ultrareview: edge cases (empty cards, no twin, missing facts)
"""

from __future__ import annotations

import pytest

from prostanet.domains.decision_arbiter import (
    ArbitratedDecision,
    CardRecommendation,
    ClinicalConflict,
    arbitrate_recommendations,
)


# ─────────────────── Fixtures ───────────────────


def _cv_card() -> CardRecommendation:
    return CardRecommendation(
        source_card="comorbidity_cv",
        state_required="",
        preferred_action="enzalutamide_or_apalutamide_+_cardiology_co_management",
        not_recommended=["abiraterone_prednisone_with_active_cv_disease"],
        contraindicated_drugs=["abiraterone"],
        nccn_reference="PROS-K_v2026",
        severity_if_violated="critical",
    )


def _brca2_card() -> CardRecommendation:
    return CardRecommendation(
        source_card="brca2_carrier",
        state_required="mcrpc",
        preferred_action="parp_first_line_in_mcrpc",
        nccn_reference="PROS-A_v2026 + PROS-J_v2026",
        severity_if_violated="moderate",
    )


def _twin_with_abi_top() -> list[dict]:
    return [
        {"rank": 1, "regimen_name": "abiraterone", "primary_drug": "abiraterone",
         "expected_os_gain_mo": 16.8, "score": 6.5},
        {"rank": 2, "regimen_name": "enzalutamide", "primary_drug": "enzalutamide",
         "expected_os_gain_mo": 13.0, "score": 5.8},
        {"rank": 3, "regimen_name": "apalutamide", "primary_drug": "apalutamide",
         "expected_os_gain_mo": 14.4, "score": 5.5},
    ]


# ─────────────────── Conflict A — CV vs abiraterone ───────────────────


def test_cv_severe_excludes_abiraterone_from_top_ranking():
    """The exact clinical scenario reported by the user on 2026-05-13."""
    result = arbitrate_recommendations(
        cards=[_cv_card()],
        twin_ranking=_twin_with_abi_top(),
        facts={"severe_cv_disease": True, "active_cardiac_disease": True},
    )
    assert result.has_conflicts is True
    assert result.severity_max == "critical"
    # Conflict detected
    cv_conflict = next(c for c in result.conflicts if c.conflict_id == "cv_abi_override")
    assert cv_conflict.severity == "critical"
    assert "abiraterona" in cv_conflict.description.lower()
    assert cv_conflict.requires_clinician_review is True
    # Re-ranking applied
    drugs = [str(r.get("primary_drug")).lower() for r in result.arbitrated_ranking]
    assert "abiraterone" not in drugs
    assert result.arbitrated_ranking[0]["primary_drug"] == "enzalutamide"
    assert result.arbitrated_ranking[0]["arbitrated_rank"] == 1
    assert result.arbitrated_ranking[0]["original_rank"] == 2
    # Excluded list populated
    assert len(result.excluded_regimens) == 1
    assert result.excluded_regimens[0]["drug"] == "abiraterone"
    assert "CV" in result.excluded_regimens[0]["reason"]


def test_cv_severe_via_cv_risk_band_high():
    """Alternative CV trigger: cv_risk_band=high (not explicit severe_cv_disease)."""
    result = arbitrate_recommendations(
        cards=[],
        twin_ranking=_twin_with_abi_top(),
        facts={"cv_risk_band": "high"},
    )
    assert result.has_conflicts is True
    assert any(c.conflict_id == "cv_abi_override" for c in result.conflicts)


def test_cv_severe_but_abi_not_in_top_3():
    """If abi is NOT in top-3, no conflict (e.g., chemo-doublet preferred)."""
    twin = [
        {"rank": 1, "regimen_name": "docetaxel", "primary_drug": "docetaxel"},
        {"rank": 2, "regimen_name": "enzalutamide", "primary_drug": "enzalutamide"},
    ]
    result = arbitrate_recommendations(
        cards=[_cv_card()],
        twin_ranking=twin,
        facts={"severe_cv_disease": True},
    )
    cv_conflicts = [c for c in result.conflicts if c.conflict_id == "cv_abi_override"]
    assert len(cv_conflicts) == 0  # arbiter is precise — no false positive


def test_cv_normal_no_conflict():
    """Patient without CV disease + abi in top should NOT trigger conflict."""
    result = arbitrate_recommendations(
        cards=[],
        twin_ranking=_twin_with_abi_top(),
        facts={},
    )
    assert not any(c.conflict_id == "cv_abi_override" for c in result.conflicts)


# ─────────────────── Conflict B — Hepatic vs abiraterone ───────────────────


def test_hepatic_active_excludes_abiraterone():
    result = arbitrate_recommendations(
        cards=[],
        twin_ranking=_twin_with_abi_top(),
        facts={"active_liver_disease": True},
    )
    assert result.has_conflicts is True
    hep_conflict = next(c for c in result.conflicts if c.conflict_id == "hepatic_abi_override")
    assert hep_conflict.severity == "critical"
    drugs = [str(r.get("primary_drug")).lower() for r in result.arbitrated_ranking]
    assert "abiraterone" not in drugs


def test_hepatic_lft_above_3x_uln_triggers():
    """ALT 180 (3x of ULN 60) should trigger contraindication."""
    result = arbitrate_recommendations(
        cards=[],
        twin_ranking=_twin_with_abi_top(),
        facts={"alt_u_l": 180, "ast_u_l": 165},
    )
    assert any(c.conflict_id == "hepatic_abi_override" for c in result.conflicts)


def test_hepatic_mild_lft_no_conflict():
    """LFTs 70 (normal-borderline) should NOT trigger."""
    result = arbitrate_recommendations(
        cards=[],
        twin_ranking=_twin_with_abi_top(),
        facts={"alt_u_l": 70, "ast_u_l": 65},
    )
    assert not any(c.conflict_id == "hepatic_abi_override" for c in result.conflicts)


def test_hepatic_and_cv_both_dedupe_abiraterone_exclusion():
    """When both CV+hepatic fire, abiraterone appears in excluded_regimens ONCE."""
    result = arbitrate_recommendations(
        cards=[_cv_card()],
        twin_ranking=_twin_with_abi_top(),
        facts={"severe_cv_disease": True, "active_liver_disease": True},
    )
    abi_exclusions = [e for e in result.excluded_regimens if e["drug"] == "abiraterone"]
    assert len(abi_exclusions) == 1  # dedup'd, not duplicated


# ─────────────────── Conflict C — BRCA2 mCSPC timing mismatch ───────────────────


def test_brca2_mcspc_timing_warning():
    """BRCA2 carrier + patient is NOT in mCRPC → timing warning."""
    result = arbitrate_recommendations(
        cards=[_brca2_card()],
        twin_ranking=[],
        facts={"castrate_testosterone_status": "not_castrate"},
    )
    timing = next(c for c in result.conflicts if c.conflict_id == "brca2_mcspc_timing")
    assert timing.severity == "moderate"
    assert "mCRPC" in timing.description
    # NOT a safety-critical conflict (warning level)
    assert timing.requires_clinician_review is False


def test_brca2_actual_mcrpc_no_timing_conflict():
    """BRCA2 + patient confirmed mCRPC → no timing conflict (PARP appropriate)."""
    result = arbitrate_recommendations(
        cards=[_brca2_card()],
        twin_ranking=[],
        facts={"castrate_testosterone_status": "castrate", "metastatic_stage_resolved": "mcrpc"},
    )
    assert not any(c.conflict_id == "brca2_mcspc_timing" for c in result.conflicts)


def test_brca2_no_card_no_warning():
    """No BRCA2 card → no timing check needed."""
    result = arbitrate_recommendations(
        cards=[],
        twin_ranking=[],
        facts={"castrate_testosterone_status": "not_castrate"},
    )
    assert not any(c.conflict_id == "brca2_mcspc_timing" for c in result.conflicts)


# ─────────────────── Conflict D — Metastatic stage contradiction ───────────────────


def test_m0_vs_m1b_data_integrity():
    result = arbitrate_recommendations(
        cards=[],
        twin_ranking=[],
        facts={
            "metastatic_stage_resolved": "M0",
            "m_substage_resolved": "M1b",
        },
    )
    integrity = next(
        c for c in result.conflicts if c.conflict_id == "metastatic_stage_contradiction"
    )
    assert integrity.severity == "high"
    # case-insensitive: arbiter uppercases for normalization
    desc_upper = integrity.description.upper()
    assert "M0" in desc_upper and "M1B" in desc_upper
    assert integrity.requires_clinician_review is True
    # Surfaced in dedicated list too
    assert len(result.data_integrity_flags) >= 1


def test_m0_alone_no_contradiction():
    result = arbitrate_recommendations(
        cards=[],
        twin_ranking=[],
        facts={"metastatic_stage_resolved": "M0"},
    )
    assert not any(c.conflict_id == "metastatic_stage_contradiction" for c in result.conflicts)


def test_m1_consistent_no_contradiction():
    result = arbitrate_recommendations(
        cards=[],
        twin_ranking=[],
        facts={"metastatic_stage_resolved": "M1", "m_substage_resolved": "M1b"},
    )
    assert not any(c.conflict_id == "metastatic_stage_contradiction" for c in result.conflicts)


# ─────────────────── Composite / ordering ───────────────────


def test_severity_max_takes_highest():
    """When critical + high + moderate fire together, severity_max = critical."""
    result = arbitrate_recommendations(
        cards=[_cv_card(), _brca2_card()],
        twin_ranking=_twin_with_abi_top(),
        facts={
            "severe_cv_disease": True,
            "castrate_testosterone_status": "not_castrate",
            "metastatic_stage_resolved": "M0",
            "m_substage_resolved": "M1b",
        },
    )
    assert result.severity_max == "critical"
    # All 3 detected
    ids = {c.conflict_id for c in result.conflicts}
    assert "cv_abi_override" in ids
    assert "brca2_mcspc_timing" in ids
    assert "metastatic_stage_contradiction" in ids
    # Order: critical first
    assert result.conflicts[0].severity == "critical"


def test_no_conflicts_returns_clean_result():
    """Healthy state: no conflict, no exclusions, no flags."""
    result = arbitrate_recommendations(
        cards=[],
        twin_ranking=_twin_with_abi_top(),
        facts={"castrate_testosterone_status": "castrate"},
    )
    assert result.has_conflicts is False
    assert result.severity_max == "none"
    assert result.conflicts == []
    assert result.excluded_regimens == []
    # arbitrated_ranking still populated (just passes through Twin order)
    assert len(result.arbitrated_ranking) == 3


def test_empty_inputs_safe():
    """Defensive: None inputs do not crash."""
    result = arbitrate_recommendations(cards=None, twin_ranking=None, facts=None)
    assert result.has_conflicts is False
    assert isinstance(result, ArbitratedDecision)


def test_arbitrated_decision_structure_complete():
    """Output schema has all documented fields."""
    result = arbitrate_recommendations(cards=[], twin_ranking=[], facts={})
    assert hasattr(result, "has_conflicts")
    assert hasattr(result, "severity_max")
    assert hasattr(result, "conflicts")
    assert hasattr(result, "arbitrated_ranking")
    assert hasattr(result, "excluded_regimens")
    assert hasattr(result, "timing_warnings")
    assert hasattr(result, "data_integrity_flags")
    assert result.arbiter_version.startswith("epic23_")


# ─────────────────── End-to-end via v2_adapters ───────────────────


def test_decision_fusion_summary_in_bundle():
    """`decision_fusion` key is exposed by bundle_to_v2_profile_full."""
    from prostanet.presentation.v2_adapters import bundle_to_v2_profile_full
    pt = {
        "identity": {"id": 1},
        "baseline": {"age": 65},
        "clinical_facts": [
            {"fact_key": "severe_cv_disease", "value": "true"},
            {"fact_key": "hrr_gene", "value": "BRCA2"},
        ],
    }
    pv = {
        "patient_twin": {
            "regimen_rankings_personalized": [
                {"rank": 1, "regimen_name": "abiraterone", "primary_drug": "abiraterone",
                 "expected_os_gain_mo": 16.8},
                {"rank": 2, "regimen_name": "enzalutamide", "primary_drug": "enzalutamide",
                 "expected_os_gain_mo": 13.0},
            ],
        },
    }
    bundle = bundle_to_v2_profile_full(pv, pt)
    assert "decision_fusion" in bundle
    df = bundle["decision_fusion"]
    assert df["available"] is True
    assert df["has_conflicts"] is True
    assert df["severity_max"] == "critical"
    # CV vs abi conflict surfaces
    ids = {c["id"] for c in df["conflicts"]}
    assert "cv_abi_override" in ids


def test_decision_fusion_silent_when_no_conflict():
    """Healthy patient → decision_fusion.has_conflicts=False → UI hides banner."""
    from prostanet.presentation.v2_adapters import bundle_to_v2_profile_full
    pt = {"identity": {"id": 1}, "baseline": {"age": 60}, "clinical_facts": []}
    pv = {"patient_twin": {"regimen_rankings_personalized": []}}
    bundle = bundle_to_v2_profile_full(pv, pt)
    df = bundle["decision_fusion"]
    assert df.get("has_conflicts") is False
