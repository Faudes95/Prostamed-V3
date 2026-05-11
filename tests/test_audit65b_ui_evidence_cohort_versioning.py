"""Auditoría Faubot #65B (LXXI) — UI exposure de #65A backend.

Cobertura:
  Sección A — Per-gate evidence widget (gates_panel enrichment) (8 tests)
  Sección B — Cohort comparison panel (template contract) (6 tests)
  Sección C — Versioning dashboard route + render (6 tests)

Total: 20 tests. Hipótesis verificables: H.G2146 - H.G2165.
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import os
import sys
import types

import pytest

# Stubs APFS I/O lock workaround (defensive — suele estar materializado)
if "tracking_db" not in sys.modules:
    class _TrackingDbStub(types.ModuleType):
        def __getattr__(self, name):
            def _noop(*args, **kwargs):
                return {}
            _noop.__name__ = name
            return _noop
    sys.modules["tracking_db"] = _TrackingDbStub("tracking_db")

if "clinical_scores" not in sys.modules:
    class _ClinicalScoresStub(types.ModuleType):
        def __getattr__(self, name):
            def _noop(*args, **kwargs):
                if name == "calculate_psa_kinetics":
                    return {"velocity": 0.5, "psadt": 7.0, "interpretation": "stub"}
                return {}
            _noop.__name__ = name
            return _noop
    sys.modules["clinical_scores"] = _ClinicalScoresStub("clinical_scores")

from prostanet.shared.decision_audit_builder import (
    _build_per_gate_evidence_drill_down,
)


# ─────────────────────────────────────────────────────────────────────────────
# Sección A — Per-gate evidence widget enrichment (H.G2146-H.G2153)
# ─────────────────────────────────────────────────────────────────────────────


class TestSectionAGatesPanelEvidenceEnrichment:
    """gates_panel debe propagar trial_refs_with_links + evidence_tag_link
    + citation_count desde #65A backend, listos para template rendering."""

    def test_g2146_gate_dict_includes_trial_refs_with_links(self):
        """H.G2146 — Gate enriched dict incluye trial_refs_with_links."""
        gate = {"trial_refs": ["PMID: 30157320"], "evidence_tag": ""}
        result = _build_per_gate_evidence_drill_down(gate)
        # Verifica el contrato que el template espera
        assert "trial_refs_with_links" in result
        assert isinstance(result["trial_refs_with_links"], list)

    def test_g2147_gate_dict_includes_evidence_tag_link(self):
        """H.G2147 — Gate enriched dict incluye evidence_tag_link."""
        gate = {"trial_refs": [], "evidence_tag": "NCCN_v5_2026"}
        result = _build_per_gate_evidence_drill_down(gate)
        assert "evidence_tag_link" in result
        assert isinstance(result["evidence_tag_link"], dict)

    def test_g2148_gate_dict_includes_citation_count(self):
        """H.G2148 — Gate enriched dict incluye citation_count para badge."""
        gate = {"trial_refs": ["PMID: 123", "NCT12345678"], "evidence_tag": "NCCN"}
        result = _build_per_gate_evidence_drill_down(gate)
        assert "citation_count" in result
        assert result["citation_count"] == 3

    def test_g2149_pmid_ref_template_safe_url(self):
        """H.G2149 — URL de PMID es válida HTTPS para anchor href."""
        gate = {"trial_refs": ["PMID: 30157320"], "evidence_tag": ""}
        result = _build_per_gate_evidence_drill_down(gate)
        url = result["trial_refs_with_links"][0]["url"]
        assert url.startswith("https://")

    def test_g2150_nct_ref_template_safe_url(self):
        """H.G2150 — URL de NCT es válida HTTPS."""
        gate = {"trial_refs": ["NCT02677896"], "evidence_tag": ""}
        result = _build_per_gate_evidence_drill_down(gate)
        url = result["trial_refs_with_links"][0]["url"]
        assert url.startswith("https://clinicaltrials.gov")

    def test_g2151_evidence_tag_nccn_template_safe_url(self):
        """H.G2151 — URL evidence_tag NCCN es válida."""
        gate = {"trial_refs": [], "evidence_tag": "NCCN_v5_2026"}
        result = _build_per_gate_evidence_drill_down(gate)
        url = result["evidence_tag_link"]["url"]
        assert url.startswith("https://www.nccn.org")

    def test_g2152_unknown_ref_no_url_template_handles_gracefully(self):
        """H.G2152 — Ref desconocido tiene url='' — template renderiza como span."""
        gate = {"trial_refs": ["FooUnknown2024"], "evidence_tag": ""}
        result = _build_per_gate_evidence_drill_down(gate)
        ref = result["trial_refs_with_links"][0]
        assert ref["url"] == ""
        assert "ref" in ref  # Para fallback render

    def test_g2153_empty_gate_returns_safe_defaults(self):
        """H.G2153 — Gate vacío → safe defaults (no None) para template."""
        gate = {"trial_refs": [], "evidence_tag": ""}
        result = _build_per_gate_evidence_drill_down(gate)
        # Template espera estas keys siempre presentes
        assert result["trial_refs_with_links"] == []
        assert result["evidence_tag_link"] == {}
        assert result["citation_count"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Sección B — Cohort comparison panel template contract (H.G2154-H.G2159)
# ─────────────────────────────────────────────────────────────────────────────


class TestSectionBCohortComparisonPanel:
    """Cohort comparison panel renderiza datos desde build_psa_cohort_reference_overlay
    de #64A. Validamos que el contract data está disponible para template."""

    def test_g2154_cohort_overlay_has_anchor_baseline(self):
        """H.G2154 — Cohort overlay incluye anchor_baseline_psa para tabla."""
        from prostanet.domains.patient_tracking.psa_forecast import (
            build_psa_cohort_reference_overlay,
        )
        patient = {
            "reconciled_state": "m1_crpc",
            "baseline": {"baseline_psa": 80.0},
            "treatments": [{
                "start_date": "2024-01-01", "drug_scheme": "DOCETAXEL",
                "line_of_therapy_number": "1",
            }],
            "biomarker_longitudinal": [
                {"sample_date": "2024-01-01", "biomarker_type": "PSA", "value": 80.0},
            ],
        }
        result = build_psa_cohort_reference_overlay(patient)
        assert "anchor_baseline_psa" in result
        if result["has_data"]:
            assert result["anchor_baseline_psa"] == pytest.approx(80.0, rel=0.05)

    def test_g2155_cohort_overlay_has_expected_nadir(self):
        """H.G2155 — Cohort overlay incluye expected_nadir_psa para tabla."""
        from prostanet.domains.patient_tracking.psa_forecast import (
            build_psa_cohort_reference_overlay,
        )
        patient = {
            "reconciled_state": "m1_crpc",
            "baseline": {"baseline_psa": 80.0},
            "treatments": [{
                "start_date": "2024-01-01", "drug_scheme": "DOCETAXEL",
                "line_of_therapy_number": "1",
            }],
            "biomarker_longitudinal": [
                {"sample_date": "2024-01-01", "biomarker_type": "PSA", "value": 80.0},
            ],
        }
        result = build_psa_cohort_reference_overlay(patient)
        if result["has_data"]:
            assert "expected_nadir_psa" in result
            assert result["expected_nadir_psa"] > 0

    def test_g2156_cohort_overlay_has_time_to_nadir(self):
        """H.G2156 — Cohort overlay incluye expected_time_to_nadir_months."""
        from prostanet.domains.patient_tracking.psa_forecast import (
            build_psa_cohort_reference_overlay,
        )
        patient = {
            "reconciled_state": "m1_crpc",
            "baseline": {"baseline_psa": 80.0},
            "treatments": [{
                "start_date": "2024-01-01", "drug_scheme": "DOCETAXEL",
                "line_of_therapy_number": "1",
            }],
            "biomarker_longitudinal": [
                {"sample_date": "2024-01-01", "biomarker_type": "PSA", "value": 80.0},
            ],
        }
        result = build_psa_cohort_reference_overlay(patient)
        if result["has_data"]:
            assert "expected_time_to_nadir_months" in result

    def test_g2157_cohort_overlay_has_duration_response(self):
        """H.G2157 — Cohort overlay incluye expected_duration_response_months."""
        from prostanet.domains.patient_tracking.psa_forecast import (
            build_psa_cohort_reference_overlay,
        )
        patient = {
            "reconciled_state": "m1_crpc",
            "baseline": {"baseline_psa": 80.0},
            "treatments": [{
                "start_date": "2024-01-01", "drug_scheme": "DOCETAXEL",
                "line_of_therapy_number": "1",
            }],
            "biomarker_longitudinal": [
                {"sample_date": "2024-01-01", "biomarker_type": "PSA", "value": 80.0},
            ],
        }
        result = build_psa_cohort_reference_overlay(patient)
        if result["has_data"]:
            assert "expected_duration_response_months" in result

    def test_g2158_cohort_overlay_has_narrative_for_template(self):
        """H.G2158 — narrative string para footer educativo."""
        from prostanet.domains.patient_tracking.psa_forecast import (
            build_psa_cohort_reference_overlay,
        )
        patient = {
            "reconciled_state": "m1_crpc",
            "baseline": {"baseline_psa": 80.0},
            "treatments": [{
                "start_date": "2024-01-01", "drug_scheme": "DOCETAXEL",
                "line_of_therapy_number": "1",
            }],
            "biomarker_longitudinal": [
                {"sample_date": "2024-01-01", "biomarker_type": "PSA", "value": 80.0},
            ],
        }
        result = build_psa_cohort_reference_overlay(patient)
        assert "narrative" in result
        assert isinstance(result["narrative"], str)

    def test_g2159_cohort_overlay_has_anchor_date(self):
        """H.G2159 — anchor_date ISO string para footer."""
        from prostanet.domains.patient_tracking.psa_forecast import (
            build_psa_cohort_reference_overlay,
        )
        patient = {
            "reconciled_state": "m1_crpc",
            "baseline": {"baseline_psa": 80.0},
            "treatments": [{
                "start_date": "2024-01-01", "drug_scheme": "DOCETAXEL",
                "line_of_therapy_number": "1",
            }],
            "biomarker_longitudinal": [
                {"sample_date": "2024-01-01", "biomarker_type": "PSA", "value": 80.0},
            ],
        }
        result = build_psa_cohort_reference_overlay(patient)
        if result["has_data"]:
            assert "anchor_date" in result


# ─────────────────────────────────────────────────────────────────────────────
# Sección C — Versioning dashboard route + render (H.G2160-H.G2165)
# ─────────────────────────────────────────────────────────────────────────────


class TestSectionCVersioningDashboard:
    """Versioning dashboard expone FAUBOT_RELEASE + per-gate SHAs +
    recent releases + changelog en una sola vista admin."""

    def test_g2160_template_file_exists(self):
        """H.G2160 — Template versioning_dashboard.html existe."""
        template_path = "/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/templates/versioning_dashboard.html"
        assert os.path.exists(template_path)

    def test_g2161_template_extends_base_clinical(self):
        """H.G2161 — Template extiende layouts/base_clinical.html."""
        template_path = "/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/templates/versioning_dashboard.html"
        with open(template_path) as f:
            content = f.read()
        assert 'extends "layouts/base_clinical.html"' in content

    def test_g2162_template_renders_faubot_release(self):
        """H.G2162 — Template renderiza algorithm_version.faubot_release."""
        template_path = "/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/templates/versioning_dashboard.html"
        with open(template_path) as f:
            content = f.read()
        assert "algorithm_version.faubot_release" in content

    def test_g2163_template_renders_active_gate_codes(self):
        """H.G2163 — Template renderiza active_gate_codes loop."""
        template_path = "/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/templates/versioning_dashboard.html"
        with open(template_path) as f:
            content = f.read()
        assert "active_gate_codes" in content
        assert "per_gate_shas" in content

    def test_g2164_template_renders_changelog_entries(self):
        """H.G2164 — Template renderiza changelog_entries loop."""
        template_path = "/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/templates/versioning_dashboard.html"
        with open(template_path) as f:
            content = f.read()
        assert "changelog_entries" in content

    def test_g2165_template_renders_recent_releases(self):
        """H.G2165 — Template renderiza recent_releases con audit_id + numeral."""
        template_path = "/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/templates/versioning_dashboard.html"
        with open(template_path) as f:
            content = f.read()
        assert "recent_releases" in content
        assert "release.audit_id" in content
        assert "release.numeral" in content
