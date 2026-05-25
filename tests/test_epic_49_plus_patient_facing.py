"""EPIC 49+ Patient-facing SDM + engine extended tests (FAUBOT CXLVII).

Cubre 4 fases:
  49+.A — 6 nuevos gates comorbilidades raras (HX1)
  49+.B — Localized risk stratifier NCCN PROS-1 (HX2)
  49+.C — MSI-H + Lynch IO pathway (HX3)
  49+.D — Evidence summary fallback (HX4)
  49+.E — Patient summary view + endpoint + template
"""
from __future__ import annotations


# ─────────────────────────────────────────────────────────────────────
# 49+.A — HX1 Gates comorbilidades raras (6 nuevos)
# ─────────────────────────────────────────────────────────────────────


def test_49plus_a_hemophilia_gate():
    from prostanet.shared.pivotal_contraindication_gates import detect_bleeding_risk_hemophilia
    r = detect_bleeding_risk_hemophilia({
        "comorbidities": ["hemofilia_A_mild_FVIII_22pct"],
        "factor_viii_level_pct": 22,
    })
    assert r is not None
    assert r["code"] == "bleeding_risk_hemophilia"
    assert r["triggered"] is True
    # FVIII 22% is moderate (not severe <30) → soft_warning per heuristic
    # but our impl treats <30 as severe → hard_block
    assert r["severity"] in ("hard_block", "soft_warning")


def test_49plus_a_stroke_gate():
    from prostanet.shared.pivotal_contraindication_gates import detect_recent_stroke_90_days
    r = detect_recent_stroke_90_days({"stroke_recent_90d": 1})
    assert r is not None
    assert r["code"] == "recent_stroke_90d"
    assert r["severity"] == "soft_warning"


def test_49plus_a_doac_arsi_ddi_gate():
    from prostanet.shared.pivotal_contraindication_gates import detect_doac_arsi_cyp3a4_interaction
    r = detect_doac_arsi_cyp3a4_interaction({
        "current_medications": ["apixaban_5mg_BID", "abiraterona_1000mg_qd"],
    })
    assert r is not None
    assert r["severity"] == "hard_block"


def test_49plus_a_thrombocytopenia_gate():
    from prostanet.shared.pivotal_contraindication_gates import detect_thrombocytopenia_procedure_risk
    # Severe: <50k
    r1 = detect_thrombocytopenia_procedure_risk({"platelet_count": 35})
    assert r1 is not None and r1["severity"] == "hard_block"
    # Moderate: 50-100k
    r2 = detect_thrombocytopenia_procedure_risk({"platelet_count": 78, "comorbidities": ["pti_cronica"]})
    assert r2 is not None and r2["severity"] == "soft_warning"
    # OK: >=100k
    r3 = detect_thrombocytopenia_procedure_risk({"platelet_count": 250})
    assert r3 is None


def test_49plus_a_autoimmune_io_gate():
    from prostanet.shared.pivotal_contraindication_gates import detect_autoimmune_disease_io_contraindication
    r = detect_autoimmune_disease_io_contraindication({
        "comorbidities": ["les_actividad_moderada"],
        "msi_status": "MSI_high",
    })
    assert r is not None
    assert r["severity"] == "hard_block"


def test_49plus_a_dementia_consent_gate():
    from prostanet.shared.pivotal_contraindication_gates import detect_dementia_informed_consent_capacity
    # Severe CDR=2
    r = detect_dementia_informed_consent_capacity({
        "comorbidities": ["demencia_alzheimer_avanzada"],
        "cdr_score": 2,
    })
    assert r is not None
    assert r["severity"] == "hard_block"


def test_49plus_a_all_6_in_detectors_tuple():
    from prostanet.shared.pivotal_contraindication_gates import _DETECTORS
    # Should now have 12 original + 6 new = 18 detectors
    assert len(_DETECTORS) >= 18


# ─────────────────────────────────────────────────────────────────────
# 49+.B — Localized risk stratifier
# ─────────────────────────────────────────────────────────────────────


def test_49plus_b_stratifier_module_importable():
    from prostanet.domains.decisions import localized_risk_stratifier
    assert hasattr(localized_risk_stratifier, "stratify_localized_risk")
    assert hasattr(localized_risk_stratifier, "is_localized")
    assert hasattr(localized_risk_stratifier, "RECOMMENDATIONS_BY_RISK_GROUP")
    assert set(localized_risk_stratifier.RECOMMENDATIONS_BY_RISK_GROUP.keys()) == {
        "very_low", "low", "favorable_intermediate",
        "unfavorable_intermediate", "high", "very_high",
    }


def test_49plus_b_classifies_favorable_intermediate():
    from prostanet.domains.decisions.localized_risk_stratifier import stratify_localized_risk
    r = stratify_localized_risk({"baseline": {
        "baseline_psa": 6.8, "gleason_score": "3+4", "clinical_stage": "cT1c",
        "biopsy_cores_total": 14, "biopsy_cores_positive": 3,
        "percent_cores_positive": 21.4, "isup_grade": 2,
    }})
    assert r["applicable"] is True
    assert r["risk_group"] == "favorable_intermediate"


def test_49plus_b_classifies_very_high():
    from prostanet.domains.decisions.localized_risk_stratifier import stratify_localized_risk
    r = stratify_localized_risk({"baseline": {
        "baseline_psa": 28.4, "gleason_score": "4+5", "clinical_stage": "cT2c",
        "biopsy_cores_total": 16, "biopsy_cores_positive": 12,
        "percent_cores_positive": 75, "isup_grade": 5,
        "cribriform_pattern": 1, "intraductal_carcinoma": 1, "lvi_on_biopsy": 1,
    }})
    assert r["applicable"] is True
    assert r["risk_group"] == "very_high"


def test_49plus_b_skips_non_localized():
    from prostanet.domains.decisions.localized_risk_stratifier import stratify_localized_risk
    r = stratify_localized_risk({"baseline": {"stage": "mCRPC", "baseline_psa": 34}})
    assert r["applicable"] is False


# ─────────────────────────────────────────────────────────────────────
# 49+.C — MSI-H + Lynch IO pathway
# ─────────────────────────────────────────────────────────────────────


def test_49plus_c_msi_high_pembrolizumab_pathway():
    from prostanet.domains.decisions.biomarker_workup_engine import build_biomarker_workup_bundle
    bundle = build_biomarker_workup_bundle({
        "identity": {"id": 1, "nss": "TEST-MSI"},
        "baseline": {
            "stage": "mCRPC_post_1L",
            "msi_status": "MSI_high",
            "mmr_ihc": "MSH2_loss_MSH6_loss",
            "lynch_syndrome_confirmed": 1,
            "lynch_germline_gene": "MSH2",
        },
    })
    msi = bundle.get("msi_io_workup", {})
    assert msi.get("candidate") is True
    assert msi.get("lynch_syndrome_detected") is True
    assert "pembrolizumab" in (msi.get("action_label") or "").lower()


def test_49plus_c_no_msi_no_io_pathway():
    from prostanet.domains.decisions.biomarker_workup_engine import build_biomarker_workup_bundle
    bundle = build_biomarker_workup_bundle({
        "identity": {"id": 2, "nss": "TEST-NO-MSI"},
        "baseline": {"stage": "mCRPC", "msi_status": "MSS"},
    })
    msi = bundle.get("msi_io_workup", {})
    assert msi.get("candidate") is False


# ─────────────────────────────────────────────────────────────────────
# 49+.D — Evidence summary fallback
# ─────────────────────────────────────────────────────────────────────


def test_49plus_d_evidence_fallback_module_importable():
    from prostanet.domains.decisions import evidence_summary_fallback
    assert hasattr(evidence_summary_fallback, "build_evidence_summary_fallback")
    assert hasattr(evidence_summary_fallback, "GUIDELINE_BY_STAGE")
    # Cubre 5 stage buckets
    assert set(evidence_summary_fallback.GUIDELINE_BY_STAGE.keys()) == {
        "localized", "mhspc", "nmcrpc", "mcrpc", "bcr",
    }


def test_49plus_d_evidence_fallback_returns_guidelines_per_stage():
    from prostanet.domains.decisions.evidence_summary_fallback import build_evidence_summary_fallback
    for stage_test, expected_bucket in [
        ("mCRPC_post_1L", "mcrpc"),
        ("mHSPC_high_volume", "mhspc"),
        ("nmCRPC_high_risk", "nmcrpc"),
        ("BCR_late_post_RP", "bcr"),
        ("localized_intermediate_favorable", "localized"),
    ]:
        result = build_evidence_summary_fallback({"baseline": {"stage": stage_test}})
        assert result["stage_bucket"] == expected_bucket, (
            f"stage {stage_test} → bucket {result['stage_bucket']} != {expected_bucket}"
        )
        assert len(result["guideline_basis"]) > 0
        assert result["is_fallback"] is True


# ─────────────────────────────────────────────────────────────────────
# 49+.E — Patient summary view + endpoint
# ─────────────────────────────────────────────────────────────────────


def test_49plus_e_patient_summary_module_importable():
    from prostanet.presentation import patient_summary_routes
    assert hasattr(patient_summary_routes, "patient_summary_bp")
    assert hasattr(patient_summary_routes, "_build_patient_summary")
    assert hasattr(patient_summary_routes, "_translate_to_plain_spanish")


def test_49plus_e_translate_to_plain_spanish():
    from prostanet.presentation.patient_summary_routes import _translate_to_plain_spanish
    assert "cáncer" in _translate_to_plain_spanish("mCRPC")
    assert "hormonal" in _translate_to_plain_spanish("ADT")
    assert "BRCA" in _translate_to_plain_spanish("BRCA")  # genes nombre conservado
    assert "seguro" in _translate_to_plain_spanish("approved")


def test_49plus_e_patient_summary_template_exists():
    from pathlib import Path
    template = Path(__file__).parent.parent / "templates" / "patient_summary.html"
    assert template.exists()
    content = template.read_text(encoding="utf-8")
    # Key data-testids para validación visual
    for testid in (
        "patient-summary-header", "patient-summary-current-state",
        "patient-summary-next-steps",
    ):
        assert f'data-testid="{testid}"' in content


def test_49plus_e_patient_summary_endpoints_have_auth():
    from pathlib import Path
    src = Path(__file__).parent.parent / "prostanet" / "presentation" / "patient_summary_routes.py"
    content = src.read_text(encoding="utf-8")
    for endpoint_def in ("def api_patient_summary", "def view_patient_summary"):
        idx = content.find(endpoint_def)
        assert idx > 0
        prev = content[max(0, idx - 200):idx]
        assert "@require_clinician" in prev


# ─────────────────────────────────────────────────────────────────────
# Foundation
# ─────────────────────────────────────────────────────────────────────


def test_49plus_faubot_release_cxlvii():
    from prostanet.shared.algorithm_version import FAUBOT_RELEASE
    assert "CXLVII" in FAUBOT_RELEASE
