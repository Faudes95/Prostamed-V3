"""EPIC 35 — Classifier alignment tests.

Verifica que el clinical_state_classifier reconoce M1+ + confirmed_castrate +
progression signal como m1_crpc (regla inferencial conservadora) sin
over-classify mHSPC en respuesta a ADT.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from prostanet.domains.state_classifier.clinical_state_classifier import (
    _get_castration_resistance,
    _get_metastasis_flags,
    classify_clinical_state,
)


def _today_iso() -> str:
    return date.today().isoformat()


def _stale_iso(days: int = 200) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


class TestMetastasisFlagsSubstageRecognition:
    """EPIC 35 — _get_metastasis_flags reconoce m_substage_resolved."""

    @pytest.mark.parametrize("substage", ["M1", "M1a", "M1b", "M1c", "m1", "m1b"])
    def test_m1_substage_indicates_distant(self, substage):
        flags = _get_metastasis_flags({"m_substage_resolved": substage})
        assert flags["m_substage_indicates_distant"] is True
        assert flags["m_substage_raw"] == substage.upper()

    @pytest.mark.parametrize("substage", ["M0", "MX", "", None, "unknown"])
    def test_non_m1_substage_does_not_indicate_distant(self, substage):
        flags = _get_metastasis_flags({"m_substage_resolved": substage})
        assert flags["m_substage_indicates_distant"] is False

    def test_metastatic_stage_resolved_alias_recognized(self):
        flags = _get_metastasis_flags({"metastatic_stage_resolved": "M1b"})
        assert flags["m_substage_indicates_distant"] is True


class TestCastrationResistanceInference:
    """EPIC 35 — _get_castration_resistance infers from M1+ + castrate + progression."""

    def test_explicit_crpc_flag_wins(self):
        assert _get_castration_resistance({
            "castration_resistance_confirmed": True,
        }) is True

    def test_m1b_castrate_progressing_infers_crpc(self):
        facts = {
            "m_substage_resolved": "M1b",
            "castrate_testosterone_status": "confirmed_castrate",
            "testosterone_sample_date": _today_iso(),
            "current_adt_context": "enzalutamide_progressing",
        }
        assert _get_castration_resistance(facts) is True

    def test_m1b_castrate_psa_rising_via_psadt_phoenix(self):
        facts = {
            "m_substage_resolved": "M1b",
            "castrate_testosterone_status": "confirmed_castrate",
            "testosterone_sample_date": _today_iso(),
            "phoenix_delta": 2.5,
        }
        assert _get_castration_resistance(facts) is True

    def test_m1b_castrate_psa_doubles_from_nadir(self):
        facts = {
            "m_substage_resolved": "M1b",
            "castrate_testosterone_status": "confirmed_castrate",
            "testosterone_sample_date": _today_iso(),
            "current_psa": 8.0,
            "psa_nadir": 3.0,  # 8.0 >= 2*3.0 and delta 5 >= 2
        }
        assert _get_castration_resistance(facts) is True

    def test_m1b_non_castrate_does_not_infer_crpc(self):
        """mHSPC: M1+ + ADT initiated but not yet castrate."""
        facts = {
            "m_substage_resolved": "M1b",
            "castrate_testosterone_status": "non_castrate",
            "testosterone_sample_date": _today_iso(),
            "current_adt_context": "enzalutamide_progressing",
        }
        assert _get_castration_resistance(facts) is False

    def test_m1b_castrate_responding_does_not_infer_crpc(self):
        """mHSPC en respuesta: castrate + low PSA + no progression."""
        facts = {
            "m_substage_resolved": "M1b",
            "castrate_testosterone_status": "confirmed_castrate",
            "testosterone_sample_date": _today_iso(),
            "current_psa": 0.3,
            "psa_nadir": 0.2,
            "current_adt_context": "enzalutamide_responding",
        }
        assert _get_castration_resistance(facts) is False

    def test_stale_testosterone_blocks_crpc_inference(self):
        """Safety: testosterona >180d stale no debe inferir castration."""
        facts = {
            "m_substage_resolved": "M1b",
            "castrate_testosterone_status": "confirmed_castrate",
            "testosterone_sample_date": _stale_iso(200),
            "current_psa": 12.0,
            "psa_nadir": 4.0,
        }
        assert _get_castration_resistance(facts) is False

    def test_m0_castrate_progressing_does_not_infer_m1_crpc(self):
        """M0 substage + castrate + progressing → m0CRPC (not m1CRPC) — debería
        ser False aquí porque has_distant=False, dejando a baseline classifier
        manejar m0CRPC."""
        facts = {
            "m_substage_resolved": "M0",
            "castrate_testosterone_status": "confirmed_castrate",
            "testosterone_sample_date": _today_iso(),
            "current_adt_context": "progressing",
        }
        # Sin lesiones distantes (M0), inferencia NO retorna True
        # — caso M0 CRPC se maneja por baseline classifier vía otros flags
        assert _get_castration_resistance(facts) is False


class TestClassifyClinicalStatePromotesToCRPC:
    """EPIC 35 — classify_clinical_state ahora clasifica M1+ + CRPC inferido."""

    def test_m1b_castrate_progressing_arsi_naive_returns_mcrpc(self):
        facts = {
            "m_substage_resolved": "M1b",
            "castrate_testosterone_status": "confirmed_castrate",
            "testosterone_sample_date": _today_iso(),
            "current_adt_context": "enzalutamide_progressing",
            "current_psa": 12.0,
            "psa_nadir": 4.0,
        }
        result = classify_clinical_state(facts)
        assert result is not None
        assert result.state == "mcrpc_arsi_naive"
        assert "first-line ARSI" in result.rationale

    def test_m1b_castrate_progressing_post_arsi_returns_mcrpc_post_arsi(self):
        facts = {
            "m_substage_resolved": "M1b",
            "castrate_testosterone_status": "confirmed_castrate",
            "testosterone_sample_date": _today_iso(),
            "current_adt_context": "progressing",
            "phoenix_delta": 3.0,
            "prior_arsi_in_mcspc": True,
        }
        result = classify_clinical_state(facts)
        assert result is not None
        assert result.state == "mcrpc_post_arsi"

    def test_m1b_non_castrate_falls_through(self):
        """No-CRPC pathway → baseline classifier (or None from extended rules)."""
        facts = {
            "m_substage_resolved": "M1b",
            "castrate_testosterone_status": "non_castrate",
            "testosterone_sample_date": _today_iso(),
        }
        result = classify_clinical_state(facts)
        # No matching extended rule — falls through to baseline
        assert result is None or result.state != "mcrpc_arsi_naive"

    def test_psma_positive_promotes_to_lu177_subtype(self):
        """EPIC 35 + Phase 6 compound: M1b + castrate + PSMA-PET positive →
        mcrpc_psma_eligible_lu177."""
        facts = {
            "m_substage_resolved": "M1b",
            "castrate_testosterone_status": "confirmed_castrate",
            "testosterone_sample_date": _today_iso(),
            "current_adt_context": "progressing",
            "psma_pet_positive": True,
            "psma_pet_uptake_intensity": "intense",
        }
        result = classify_clinical_state(facts)
        assert result is not None
        assert result.state == "mcrpc_psma_eligible_lu177"
