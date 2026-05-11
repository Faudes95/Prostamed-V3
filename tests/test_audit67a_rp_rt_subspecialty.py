"""Auditoría Faubot #67A (LXXV) — RP vs RT Subspecialty Refinement.

Cobertura:
  Sección A — Gate 56: anticoag + RP bleeding (4 tests, H.G2231-H.G2234)
  Sección B — Gates 57+58: IBD + prior pelvic RT (5 tests, H.G2235-H.G2239)
  Sección C — Gate 59: TURP brachy contraindication (3 tests, H.G2240-H.G2242)
  Sección D — Gate 60 + SVI nomogram (4 tests, H.G2243-H.G2246)
  Sección E — recommend_rt_modality scoring (5 tests, H.G2247-H.G2251)
  Sección F — nerve_sparing_feasibility_score (4 tests, H.G2252-H.G2255)

Total: 25 tests. Hipótesis verificables: H.G2231 - H.G2255.
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import importlib
import os
import sys
import types

import pytest

PROJECT_ROOT = "/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6"
GATES_CATALOG = os.path.join(PROJECT_ROOT, "prostanet/shared/pivotal_gates_catalog")

# Faubot LXXV #67A — Force REAL clinical_scores module load.
# Otros test files (test_audit63a, etc.) instalan stubs sys.modules para
# clinical_scores via APFS lock workaround. Stubs usan __getattr__ no-op
# que devuelve True a hasattr(), así que detectamos por __file__ (stubs
# no tienen __file__ apuntando a clinical_scores.py real).
if "clinical_scores" in sys.modules:
    cs_module = sys.modules["clinical_scores"]
    cs_file = getattr(cs_module, "__file__", None)
    # Real module has __file__ = string path; stub returns no-op callable
    is_stub = not isinstance(cs_file, str) or not cs_file.endswith("clinical_scores.py")
    if is_stub:
        del sys.modules["clinical_scores"]

# Garantizar PROJECT_ROOT está en sys.path para import directo
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import clinical_scores  # noqa: E402 — forzar import real


def _read_yaml(filename: str) -> str:
    """Read YAML gate file content."""
    path = os.path.join(GATES_CATALOG, filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ─────────────────────────────────────────────────────────────────────────────
# Sección A — Gate 56: anticoag + RP bleeding (H.G2231-H.G2234)
# ─────────────────────────────────────────────────────────────────────────────


class TestSectionAAnticoagulantGate:
    """Gate 56 detecta anticoagulación crónica → soft_warning RP bleeding risk."""

    def test_g2231_gate_56_yaml_exists(self):
        """H.G2231 — YAML gate 56 exists with correct code."""
        yaml = _read_yaml("56_anticoagulant_rp_bleeding_risk.yaml")
        assert "code: anticoagulant_rp_bleeding_risk" in yaml
        assert "severity: soft_warning" in yaml

    def test_g2232_gate_56_recognizes_warfarin(self):
        """H.G2232 — Path A recognizes warfarin in trigger patterns."""
        yaml = _read_yaml("56_anticoagulant_rp_bleeding_risk.yaml")
        assert "warfarin" in yaml
        assert "apixaban" in yaml
        assert "rivaroxaban" in yaml
        assert "dabigatran" in yaml

    def test_g2233_gate_56_recognizes_dual_antiplatelet(self):
        """H.G2233 — Path B recognizes DAPT (aspirin + clopidogrel)."""
        yaml = _read_yaml("56_anticoagulant_rp_bleeding_risk.yaml")
        assert "aspirin" in yaml
        assert "clopidogrel" in yaml
        assert "dual_antiplatelet_therapy" in yaml

    def test_g2234_gate_56_has_override_for_bridging(self):
        """H.G2234 — Override permits if bridging documented + anesthesia clearance."""
        yaml = _read_yaml("56_anticoagulant_rp_bleeding_risk.yaml")
        assert "anticoagulation_bridged_with_anesthesia_clearance" in yaml
        assert "override:" in yaml


# ─────────────────────────────────────────────────────────────────────────────
# Sección B — Gates 57+58: IBD + prior pelvic RT (H.G2235-H.G2239)
# ─────────────────────────────────────────────────────────────────────────────


class TestSectionBIBDPriorRTGates:
    """Gates 57 (IBD active severe) + 58 (prior pelvic RT) hard_block RT pelvis."""

    def test_g2235_gate_57_ibd_active_severe_hard_block(self):
        """H.G2235 — Gate 57 IBD active_severe = hard_block RT pelvis."""
        yaml = _read_yaml("57_ibd_active_pelvic_rt_contraindication.yaml")
        assert "code: ibd_active_pelvic_rt_contraindication" in yaml
        assert "severity: hard_block" in yaml
        assert "active_severe" in yaml

    def test_g2236_gate_57_recognizes_crohn_uc_subtypes(self):
        """H.G2236 — Gate 57 recognizes Crohn + UC subtypes."""
        yaml = _read_yaml("57_ibd_active_pelvic_rt_contraindication.yaml")
        assert "crohn" in yaml
        assert "ulcerative_colitis" in yaml
        assert "ibd_active_flare_documented" in yaml

    def test_g2237_gate_57_override_remission_2yr(self):
        """H.G2237 — Gate 57 override = remission ≥2yr + GI clearance."""
        yaml = _read_yaml("57_ibd_active_pelvic_rt_contraindication.yaml")
        assert "ibd_remission_2yr_with_gi_clearance" in yaml

    def test_g2238_gate_58_prior_pelvic_rt_hard_block(self):
        """H.G2238 — Gate 58 prior pelvic RT = hard_block re-RT curative."""
        yaml = _read_yaml("58_prior_pelvic_rt_re_irradiation_contraindication.yaml")
        assert "code: prior_pelvic_rt_re_irradiation_contraindication" in yaml
        assert "severity: hard_block" in yaml
        assert "prior_pelvic_radiation" in yaml

    def test_g2239_gate_58_palliative_intent_override(self):
        """H.G2239 — Gate 58 override permite RT paliativa (no curativa)."""
        yaml = _read_yaml("58_prior_pelvic_rt_re_irradiation_contraindication.yaml")
        assert "palliative_intent_documented" in yaml
        assert "salvage_re_rt_protocol_documented" in yaml


# ─────────────────────────────────────────────────────────────────────────────
# Sección C — Gate 59: TURP brachy contraindication (H.G2240-H.G2242)
# ─────────────────────────────────────────────────────────────────────────────


class TestSectionCTURPBrachyGate:
    """Gate 59 TURP <5yr + ≥30cc resected → hard_block brachytherapy."""

    def test_g2240_gate_59_yaml_exists_hard_block(self):
        """H.G2240 — Gate 59 exists with hard_block severity."""
        yaml = _read_yaml("59_turp_brachytherapy_contraindication.yaml")
        assert "code: turp_brachytherapy_contraindication" in yaml
        assert "severity: hard_block" in yaml

    def test_g2241_gate_59_volume_threshold_30cc(self):
        """H.G2241 — Threshold volume resected ≥30cc → numeric_above 29."""
        yaml = _read_yaml("59_turp_brachytherapy_contraindication.yaml")
        assert "turp_volume_resected_cc" in yaml
        assert "threshold: 29" in yaml

    def test_g2242_gate_59_expert_protocol_override(self):
        """H.G2242 — Override centro experto post-TURP brachy protocol."""
        yaml = _read_yaml("59_turp_brachytherapy_contraindication.yaml")
        assert "brachy_after_turp_expert_protocol_documented" in yaml


# ─────────────────────────────────────────────────────────────────────────────
# Sección D — Gate 60 + SVI nomogram (H.G2243-H.G2246)
# ─────────────────────────────────────────────────────────────────────────────


class TestSectionDSVINomogram:
    """Gate 60 SVI risk >30% + calculate_svi_risk_nomogram MSKCC."""

    def test_g2243_gate_60_svi_high_risk_soft_warning(self):
        """H.G2243 — Gate 60 SVI >30% = soft_warning."""
        yaml = _read_yaml("60_svi_risk_high_rp_efficiency_warning.yaml")
        assert "code: svi_risk_high_rp_efficiency_warning" in yaml
        assert "severity: soft_warning" in yaml
        assert "threshold: 30" in yaml

    def test_g2244_svi_nomogram_low_risk_calculation(self):
        """H.G2244 — calculate_svi_risk_nomogram low risk patient (<15%)."""
        calculate_svi_risk_nomogram = clinical_scores.calculate_svi_risk_nomogram
        patient = {
            "psa_value": 5.0,
            "gleason_score": 6,
            "clinical_t_stage": "cT1c",
            "percent_positive_cores": 20,
        }
        result = calculate_svi_risk_nomogram(patient)
        assert result["risk_band"] == "low"
        assert result["risk_percent"] < 15

    def test_g2245_svi_nomogram_high_risk_calculation(self):
        """H.G2245 — calculate_svi_risk_nomogram high risk patient (>30%)."""
        calculate_svi_risk_nomogram = clinical_scores.calculate_svi_risk_nomogram
        patient = {
            "psa_value": 35.0,
            "gleason_score": 9,
            "clinical_t_stage": "cT3a",
            "percent_positive_cores": 80,
        }
        result = calculate_svi_risk_nomogram(patient)
        assert result["risk_band"] == "high"
        assert result["risk_percent"] > 30

    def test_g2246_svi_nomogram_insufficient_data(self):
        """H.G2246 — Nomogram retorna insufficient_data si PSA o Gleason missing."""
        calculate_svi_risk_nomogram = clinical_scores.calculate_svi_risk_nomogram
        patient = {"clinical_t_stage": "cT2a"}  # sin PSA ni Gleason
        result = calculate_svi_risk_nomogram(patient)
        assert result["risk_band"] == "insufficient_data"
        assert result["risk_percent"] is None


# ─────────────────────────────────────────────────────────────────────────────
# Sección E — recommend_rt_modality scoring (H.G2247-H.G2251)
# ─────────────────────────────────────────────────────────────────────────────


class TestSectionERTModalityScoring:
    """recommend_rt_modality retorna 4 modalities ranked por scoring."""

    def test_g2247_returns_4_modalities_ranked(self):
        """H.G2247 — Output incluye 4 modalities (LDR/HDR/SBRT/EBRT) ranked."""
        recommend_rt_modality = clinical_scores.recommend_rt_modality
        patient = {
            "prostate_volume_ml": 40, "gleason_score": 6,
            "ipss": 8, "history_of_turp": "none",
        }
        result = recommend_rt_modality(patient)
        assert "modalities_ranked" in result
        assert len(result["modalities_ranked"]) == 4
        modalities = [m["modality"] for m in result["modalities_ranked"]]
        assert set(modalities) == {"LDR_brachy", "HDR_brachy", "SBRT", "EBRT_IMRT"}

    def test_g2248_ldr_brachy_optimal_for_30_50cc(self):
        """H.G2248 — LDR brachy gana score con volume 40cc + Gleason 6 + IPSS 8."""
        recommend_rt_modality = clinical_scores.recommend_rt_modality
        patient = {
            "prostate_volume_ml": 40, "gleason_score": 6,
            "ipss": 8, "history_of_turp": "none",
            "life_expectancy_years": 15,
        }
        result = recommend_rt_modality(patient)
        ldr = next(m for m in result["modalities_ranked"] if m["modality"] == "LDR_brachy")
        assert ldr["score"] > 0
        assert not ldr["blocked"]

    def test_g2249_turp_blocks_brachy_modalities(self):
        """H.G2249 — TURP previo bloquea LDR + HDR brachy."""
        recommend_rt_modality = clinical_scores.recommend_rt_modality
        patient = {
            "prostate_volume_ml": 40, "gleason_score": 6,
            "ipss": 8, "history_of_turp": "yes_recent",
        }
        result = recommend_rt_modality(patient)
        ldr = next(m for m in result["modalities_ranked"] if m["modality"] == "LDR_brachy")
        hdr = next(m for m in result["modalities_ranked"] if m["modality"] == "HDR_brachy")
        assert ldr["blocked"]
        assert hdr["blocked"]

    def test_g2250_high_risk_gleason_favors_ebrt(self):
        """H.G2250 — Gleason ≥8 high-risk → EBRT-IMRT preferido."""
        recommend_rt_modality = clinical_scores.recommend_rt_modality
        patient = {
            "prostate_volume_ml": 50, "gleason_score": 9,
            "ipss": 10, "history_of_turp": "none",
        }
        result = recommend_rt_modality(patient)
        ebrt = next(m for m in result["modalities_ranked"] if m["modality"] == "EBRT_IMRT")
        assert ebrt["score"] >= 50  # base 30 + 25 for Gleason ≥8

    def test_g2251_ibd_blocks_all_pelvic_rt(self):
        """H.G2251 — IBD active_severe blocks all RT modalities (gate 57 hard_block)."""
        recommend_rt_modality = clinical_scores.recommend_rt_modality
        patient = {
            "prostate_volume_ml": 40, "gleason_score": 7,
            "ipss": 8, "history_of_turp": "none",
            "inflammatory_bowel_disease_active": "active_severe",
        }
        result = recommend_rt_modality(patient)
        for m in result["modalities_ranked"]:
            assert m["blocked"], f"Modality {m['modality']} should be blocked by IBD"


# ─────────────────────────────────────────────────────────────────────────────
# Sección F — nerve_sparing_feasibility_score (H.G2252-H.G2255)
# ─────────────────────────────────────────────────────────────────────────────


class TestSectionFNerveSparingFeasibility:
    """nerve_sparing_feasibility_score basado en lesion location + NVB."""

    def test_g2252_anterior_lesion_contralateral_high_success(self):
        """H.G2252 — Anterior lesion + NVB clearance → contralateral feasible_high_success."""
        nerve_sparing_feasibility_score = clinical_scores.nerve_sparing_feasibility_score
        patient = {
            "lesion_location_clockface": "12_3_oclock_anterior",
            "distance_to_neurovascular_bundle_mm": 8,
            "bilateral_lesions": False,
            "age": 60,
            "iief5_baseline": 22,
        }
        result = nerve_sparing_feasibility_score(patient)
        assert result["feasibility_contralateral"] == "feasible_high_success"

    def test_g2253_posterior_close_to_nvb_blocks_ipsilateral_ns(self):
        """H.G2253 — Posterior + NVB <5mm → non_nerve_sparing_recommended ipsilateral."""
        nerve_sparing_feasibility_score = clinical_scores.nerve_sparing_feasibility_score
        patient = {
            "lesion_location_clockface": "6_9_oclock_posterior",
            "distance_to_neurovascular_bundle_mm": 3,
            "bilateral_lesions": False,
            "age": 65,
            "iief5_baseline": 20,
        }
        result = nerve_sparing_feasibility_score(patient)
        assert result["feasibility_ipsilateral"] == "non_nerve_sparing_recommended"

    def test_g2254_age_75_limits_ns_feasibility(self):
        """H.G2254 — Age ≥75 limits NS feasibility bilateral."""
        nerve_sparing_feasibility_score = clinical_scores.nerve_sparing_feasibility_score
        patient = {
            "lesion_location_clockface": "12_3_oclock_anterior",
            "distance_to_neurovascular_bundle_mm": 10,
            "bilateral_lesions": False,
            "age": 78,
            "iief5_baseline": 18,
        }
        result = nerve_sparing_feasibility_score(patient)
        assert result["feasibility_ipsilateral"] == "limited"
        assert result["feasibility_contralateral"] == "limited"

    def test_g2255_bilateral_lesions_limits_both_sides(self):
        """H.G2255 — Bilateral lesions → limited NS bilateral."""
        nerve_sparing_feasibility_score = clinical_scores.nerve_sparing_feasibility_score
        patient = {
            "lesion_location_clockface": "multifocal",
            "distance_to_neurovascular_bundle_mm": 6,
            "bilateral_lesions": True,
            "age": 60,
            "iief5_baseline": 22,
        }
        result = nerve_sparing_feasibility_score(patient)
        assert result["feasibility_ipsilateral"] == "limited"
        assert result["feasibility_contralateral"] == "limited"
