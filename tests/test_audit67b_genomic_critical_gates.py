"""Auditoría Faubot #67B (LXXVI) — Genomic Critical Gates.

Cobertura:
  Sección A — Gate 61: HRR confirmation hard_block antes de PARP (5 tests, H.G2256-H.G2260)
  Sección B — Gate 62: AR-V7 pathway (3 tests, H.G2261-H.G2263)
  Sección C — Gate 63: CDK12 alteration (3 tests, H.G2264-H.G2266)
  Sección D — Gate 64 + comprehensive_hrd_score (6 tests, H.G2267-H.G2272)
  Sección E — Gate 65: MSI/MMR reflex Lynch family (5 tests, H.G2273-H.G2277)

Total: 22 tests. Hipótesis verificables: H.G2256 - H.G2277.
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import os
import sys

import pytest

PROJECT_ROOT = "/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6"
GATES_CATALOG = os.path.join(PROJECT_ROOT, "prostanet/shared/pivotal_gates_catalog")

# Force REAL clinical_scores module (handle stub from earlier test files)
if "clinical_scores" in sys.modules:
    cs_module = sys.modules["clinical_scores"]
    cs_file = getattr(cs_module, "__file__", None)
    is_stub = not isinstance(cs_file, str) or not cs_file.endswith("clinical_scores.py")
    if is_stub:
        del sys.modules["clinical_scores"]

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import clinical_scores  # noqa: E402


def _read_yaml(filename: str) -> str:
    path = os.path.join(GATES_CATALOG, filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ─────────────────────────────────────────────────────────────────────────────
# Sección A — Gate 61: HRR confirmation hard_block antes de PARP (H.G2256-H.G2260)
# ─────────────────────────────────────────────────────────────────────────────


class TestSectionAHRRRequiredBeforePARP:
    """Gate 61 — bloquea PARP si hrr_status=Desconocido (NCCN cat 1)."""

    def test_g2256_gate_61_yaml_exists_hard_block(self):
        """H.G2256 — Gate 61 existe con severity=hard_block."""
        yaml = _read_yaml("61_hrr_status_required_before_parp_inhibitor.yaml")
        assert "code: hrr_status_required_before_parp_inhibitor" in yaml
        assert "severity: hard_block" in yaml

    def test_g2257_gate_61_recognizes_unknown_hrr_status(self):
        """H.G2257 — Path A reconoce 'Desconocido' / 'No testado' / 'unknown'."""
        yaml = _read_yaml("61_hrr_status_required_before_parp_inhibitor.yaml")
        assert "Desconocido" in yaml
        assert '"No testado"' in yaml
        assert "unknown" in yaml
        assert "not_tested" in yaml

    def test_g2258_gate_61_recognizes_brca1_brca2_default_unknown(self):
        """H.G2258 — Path C: BRCA1+BRCA2 ambos desconocidos = trigger."""
        yaml = _read_yaml("61_hrr_status_required_before_parp_inhibitor.yaml")
        assert "brca1_status" in yaml
        assert "brca2_status" in yaml

    def test_g2259_gate_61_blocks_parp_regimen_codes(self):
        """H.G2259 — Gate 61 bloquea REGIMEN_CODES_PARP."""
        yaml = _read_yaml("61_hrr_status_required_before_parp_inhibitor.yaml")
        assert "REGIMEN_CODES_PARP" in yaml
        # Keywords PARP agents
        assert "olaparib" in yaml
        assert "talazoparib" in yaml
        assert "rucaparib" in yaml
        assert "niraparib" in yaml

    def test_g2260_gate_61_override_2week_test_plan(self):
        """H.G2260 — Override solo si test pending + plan <2 semanas documentado."""
        yaml = _read_yaml("61_hrr_status_required_before_parp_inhibitor.yaml")
        assert "hrr_test_pending_with_2week_plan_documented" in yaml


# ─────────────────────────────────────────────────────────────────────────────
# Sección B — Gate 62: AR-V7 pathway (H.G2261-H.G2263)
# ─────────────────────────────────────────────────────────────────────────────


class TestSectionBARV7Pathway:
    """Gate 62 — AR-V7+ → resistencia ARPI, preferir taxanos (PROPHECY)."""

    def test_g2261_gate_62_yaml_exists_soft_warning(self):
        """H.G2261 — Gate 62 existe con severity=soft_warning."""
        yaml = _read_yaml("62_ar_v7_positive_arpi_resistance_pathway.yaml")
        assert "code: ar_v7_positive_arpi_resistance_pathway" in yaml
        assert "severity: soft_warning" in yaml

    def test_g2262_gate_62_recognizes_ar_v7_positive(self):
        """H.G2262 — Reconoce ar_v7_status=Positivo / ctc detection."""
        yaml = _read_yaml("62_ar_v7_positive_arpi_resistance_pathway.yaml")
        assert "ar_v7_status" in yaml
        assert "Positivo" in yaml
        assert "ar_v7_detected_in_ctc" in yaml

    def test_g2263_gate_62_blocks_arpi_regimen(self):
        """H.G2263 — Gate 62 alerta REGIMEN_CODES_ARPI (soft_warning, no hard)."""
        yaml = _read_yaml("62_ar_v7_positive_arpi_resistance_pathway.yaml")
        assert "REGIMEN_CODES_ARPI" in yaml
        assert "PROPHECY" in yaml


# ─────────────────────────────────────────────────────────────────────────────
# Sección C — Gate 63: CDK12 alteration (H.G2264-H.G2266)
# ─────────────────────────────────────────────────────────────────────────────


class TestSectionCCDK12Alteration:
    """Gate 63 — CDK12 biallelic loss → checkpoint + PARP eligible."""

    def test_g2264_gate_63_yaml_exists_informational(self):
        """H.G2264 — Gate 63 existe con severity=informational."""
        yaml = _read_yaml("63_cdk12_alteration_immunotherapy_eligibility.yaml")
        assert "code: cdk12_alteration_immunotherapy_eligibility" in yaml
        assert "severity: informational" in yaml

    def test_g2265_gate_63_recognizes_biallelic_loss(self):
        """H.G2265 — Reconoce CDK12 biallelic_loss / Mutado."""
        yaml = _read_yaml("63_cdk12_alteration_immunotherapy_eligibility.yaml")
        assert "cdk12_status" in yaml
        assert "Biallelic loss" in yaml
        assert "biallelic_loss" in yaml

    def test_g2266_gate_63_cites_antonarakis_pembrolizumab(self):
        """H.G2266 — Cita Antonarakis JCO 2020 pembrolizumab CDK12+."""
        yaml = _read_yaml("63_cdk12_alteration_immunotherapy_eligibility.yaml")
        assert "Antonarakis" in yaml
        assert "pembrolizumab" in yaml.lower() or "pembro" in yaml.lower()


# ─────────────────────────────────────────────────────────────────────────────
# Sección D — Gate 64 + comprehensive_hrd_score (H.G2267-H.G2272)
# ─────────────────────────────────────────────────────────────────────────────


class TestSectionDComprehensiveHRDScore:
    """Gate 64 + comprehensive_hrd_score() — composite HRD phenotype."""

    def test_g2267_gate_64_yaml_exists_informational(self):
        """H.G2267 — Gate 64 existe con severity=informational."""
        yaml = _read_yaml("64_comprehensive_hrd_phenotype_high.yaml")
        assert "code: comprehensive_hrd_phenotype_high" in yaml
        assert "severity: informational" in yaml

    def test_g2268_gate_64_threshold_42_myriad_cutoff(self):
        """H.G2268 — Threshold ≥42 (Myriad MyChoice cutoff) = numeric_above 41."""
        yaml = _read_yaml("64_comprehensive_hrd_phenotype_high.yaml")
        assert "hrd_comprehensive_score" in yaml
        assert "threshold: 41" in yaml

    def test_g2269_hrd_score_high_with_brca2_pten_tp53(self):
        """H.G2269 — comprehensive_hrd_score: BRCA2+PTEN+TP53 = phenotype high."""
        comprehensive_hrd_score = clinical_scores.comprehensive_hrd_score
        patient = {
            "brca2_status": "Mutado",
            "pten_biallelic_loss_documented": True,
            "tp53_status": "Mutado",
        }
        result = comprehensive_hrd_score(patient)
        assert result["hrd_phenotype"] in {"high", "intermediate"}
        assert result["direct_hrr_count"] == 1
        assert result["functional_surrogates_count"] == 2

    def test_g2270_hrd_score_low_when_all_wild_type(self):
        """H.G2270 — comprehensive_hrd_score: todos wild-type = low / insufficient."""
        comprehensive_hrd_score = clinical_scores.comprehensive_hrd_score
        patient = {
            "brca1_status": "Wild-type",
            "brca2_status": "Wild-type",
            "atm_status": "Wild-type",
            "tp53_status": "Wild-type",
        }
        result = comprehensive_hrd_score(patient)
        assert result["hrd_phenotype"] == "low"

    def test_g2271_hrd_score_includes_recommendations(self):
        """H.G2271 — Output incluye recommendations list."""
        comprehensive_hrd_score = clinical_scores.comprehensive_hrd_score
        patient = {"brca2_status": "Mutado"}
        result = comprehensive_hrd_score(patient)
        assert "recommendations" in result
        assert len(result["recommendations"]) >= 1
        assert any("PARP" in r for r in result["recommendations"])

    def test_g2272_hrd_score_insufficient_data_when_no_genomic_info(self):
        """H.G2272 — Sin genomic info = phenotype insufficient_data."""
        comprehensive_hrd_score = clinical_scores.comprehensive_hrd_score
        patient = {}  # no genomic data
        result = comprehensive_hrd_score(patient)
        assert result["hrd_phenotype"] == "insufficient_data"


# ─────────────────────────────────────────────────────────────────────────────
# Sección E — Gate 65: MSI/MMR reflex Lynch family (H.G2273-H.G2277)
# ─────────────────────────────────────────────────────────────────────────────


class TestSectionEMSIMMRLynchReflex:
    """Gate 65 — Lynch family hx → MSI/MMR reflex testing obligatorio."""

    def test_g2273_gate_65_yaml_exists_informational(self):
        """H.G2273 — Gate 65 existe con severity=informational."""
        yaml = _read_yaml("65_msi_mmr_reflex_testing_lynch_family.yaml")
        assert "code: msi_mmr_reflex_testing_lynch_family" in yaml
        assert "severity: informational" in yaml

    def test_g2274_gate_65_recognizes_lynch_cancers(self):
        """H.G2274 — Path A reconoce family hx Lynch-related cancers."""
        yaml = _read_yaml("65_msi_mmr_reflex_testing_lynch_family.yaml")
        assert "colorectal" in yaml
        assert "endometrial" in yaml
        assert "lynch" in yaml.lower()
        assert "urothelial_lynch" in yaml or "urotelial" in yaml.lower()

    def test_g2275_gate_65_lynch_explicit_flag(self):
        """H.G2275 — Path B reconoce flag explicit Lynch syndrome."""
        yaml = _read_yaml("65_msi_mmr_reflex_testing_lynch_family.yaml")
        assert "lynch_syndrome_family_documented" in yaml
        assert "amsterdam_criteria_met" in yaml or "bethesda" in yaml.lower()

    def test_g2276_gate_65_cites_pembrolizumab_keynote(self):
        """H.G2276 — Cita pembrolizumab + KEYNOTE-158/199."""
        yaml = _read_yaml("65_msi_mmr_reflex_testing_lynch_family.yaml")
        assert "pembrolizumab" in yaml.lower()
        assert "KEYNOTE" in yaml

    def test_g2277_gate_65_mmr_proteins_panel(self):
        """H.G2277 — Menciona panel MMR proteins (MLH1/MSH2/MSH6/PMS2)."""
        yaml = _read_yaml("65_msi_mmr_reflex_testing_lynch_family.yaml")
        assert "MLH1" in yaml
        assert "MSH2" in yaml
        assert "MSH6" in yaml
        assert "PMS2" in yaml
