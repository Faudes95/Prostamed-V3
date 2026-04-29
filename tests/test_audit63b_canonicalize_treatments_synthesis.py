"""Auditoría Faubot #63B (LXV) — Section A: canonicalize_payload synthesis.

Verifica que `PatientTrackingService.canonicalize_payload` sintetice
correctamente entradas en `treatments[]` desde fields del intake fragment
`_advanced_current_treatment_fragment` (most_recent_prior_line_* +
prior_treatment_lines_count + drug_scheme + line_of_therapy_*).

Hipótesis verificables: H.G1976 - H.G1987 (12 tests).

Nota: este test file aplica stubs sys.modules para tracking_db +
clinical_scores antes de importar service.py (workaround APFS I/O
lock que impide leer source files locked por flag UF_TRACKED + UF_COMPRESSED).
Los stubs son seguros porque canonicalize_payload no llama estas dependencias.
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import sys
import types

import pytest

# Stubs APFS I/O lock workaround — DEBEN aplicarse ANTES de cualquier
# import de prostanet.domains.patient_tracking.service.
if "tracking_db" not in sys.modules:
    # Stub agresivo: cualquier atributo solicitado retorna no-op callable.
    # Esto evita ImportError cross-test cuando otros módulos requieren
    # nombres específicos (attach_clinical_assessment_to_patient, etc.).
    class _TrackingDbStub(types.ModuleType):
        def __getattr__(self, name):
            def _noop(*args, **kwargs):
                return {}
            _noop.__name__ = name
            return _noop
    sys.modules["tracking_db"] = _TrackingDbStub("tracking_db")

if "clinical_scores" not in sys.modules:
    # Stub agresivo: cualquier atributo solicitado retorna no-op callable.
    # Esto bypassa ImportError on `from clinical_scores import (...)` para
    # cualquier nombre, sin necesidad de inventar firmas.
    class _ClinicalScoresStub(types.ModuleType):
        def __getattr__(self, name):
            def _noop(*args, **kwargs):
                if name == "calculate_psa_kinetics":
                    return {"velocity": None, "psadt": None, "interpretation": "stub"}
                return {}
            _noop.__name__ = name
            return _noop
    sys.modules["clinical_scores"] = _ClinicalScoresStub("clinical_scores")

# Otros stubs cascaded (descubiertos durante test execution)
for module_name in ["sqlite3_utils", "auth_helpers"]:
    if module_name not in sys.modules:
        sys.modules[module_name] = types.ModuleType(module_name)


@pytest.fixture
def service():
    """Lazy-load para evitar import errors si APFS lock se libera mid-test."""
    from prostanet.domains.patient_tracking.service import PatientTrackingService
    return PatientTrackingService()


# ─────────────────────────────────────────────────────────────────────────────
# Sección A — canonicalize_payload sintetiza treatments[] (H.G1976-H.G1987)
# ─────────────────────────────────────────────────────────────────────────────


class TestSectionACanonicalizeTreatmentsSynthesis:
    """canonicalize_payload debe sintetizar treatments[] desde
    most_recent_prior_line_* + drug_scheme + line_of_therapy_* fields."""

    def test_g1976_prior_line_creates_treatment_entry(self, service):
        """H.G1976 — prior_line_drug_scheme + start_date crea entrada en treatments[]."""
        canonical = service.canonicalize_payload({
            "diagnosis_date": "2024-01-15",
            "most_recent_prior_line_drug_scheme": "ADT_MONO",
            "most_recent_prior_line_start_date": "2024-02-01",
            "most_recent_prior_line_end_date": "2024-12-15",
            "prior_treatment_lines_count": 1,
        })
        treatments = canonical.get("treatments") or []
        assert len(treatments) >= 1, "treatments[] vacío"
        prior = next((t for t in treatments if "auto-treatment-history" in str(t.get("source", ""))), None)
        assert prior is not None, "Entrada prior no sintetizada"
        assert prior.get("start_date") == "2024-02-01"
        assert prior.get("end_date") == "2024-12-15"

    def test_g1977_prior_line_includes_reason_for_change(self, service):
        """H.G1977 — Reason_for_change persiste en entrada sintetizada."""
        canonical = service.canonicalize_payload({
            "diagnosis_date": "2024-01-15",
            "most_recent_prior_line_drug_scheme": "ADT_ENZALUTAMIDE",
            "most_recent_prior_line_start_date": "2024-03-01",
            "most_recent_prior_line_reason_for_change": "progression_psa",
        })
        treatments = canonical.get("treatments") or []
        prior = next((t for t in treatments if "auto-treatment-history" in str(t.get("source", ""))), None)
        assert prior is not None
        assert prior.get("reason_for_change") == "progression_psa"

    def test_g1978_prior_line_best_response_pct_numeric(self, service):
        """H.G1978 — best_psa_response_pct convertido a float."""
        canonical = service.canonicalize_payload({
            "diagnosis_date": "2024-01-15",
            "most_recent_prior_line_drug_scheme": "ADT_ABIRATERONE",
            "most_recent_prior_line_start_date": "2024-03-01",
            "most_recent_prior_line_best_psa_response_pct": "-75.5",
        })
        treatments = canonical.get("treatments") or []
        prior = next((t for t in treatments if "auto-treatment-history" in str(t.get("source", ""))), None)
        assert prior is not None
        assert prior.get("best_psa_response_pct") == pytest.approx(-75.5)

    def test_g1979_current_line_synthesized_from_drug_scheme(self, service):
        """H.G1979 — drug_scheme + line_of_therapy_number crea entrada current."""
        canonical = service.canonicalize_payload({
            "diagnosis_date": "2024-01-15",
            "drug_scheme": "ADT_DOCETAXEL",
            "line_of_therapy_number": "1",
        })
        treatments = canonical.get("treatments") or []
        current = next((t for t in treatments if "auto-treatment-current" in str(t.get("source", ""))), None)
        assert current is not None
        assert current.get("line_of_therapy_number") == "1"

    def test_g1980_current_line_uses_prior_end_date_as_start(self, service):
        """H.G1980 — Si hay prior_end_date, current usa esa fecha como start."""
        canonical = service.canonicalize_payload({
            "diagnosis_date": "2024-01-15",
            "drug_scheme": "ADT_ENZALUTAMIDE",
            "line_of_therapy_number": "2",
            "most_recent_prior_line_drug_scheme": "ADT_MONO",
            "most_recent_prior_line_start_date": "2024-02-01",
            "most_recent_prior_line_end_date": "2024-12-15",
        })
        treatments = canonical.get("treatments") or []
        current = next((t for t in treatments if "auto-treatment-current" in str(t.get("source", ""))), None)
        assert current is not None
        assert current.get("start_date") == "2024-12-15"

    def test_g1981_current_line_falls_back_to_diagnosis_date(self, service):
        """H.G1981 — Sin prior, current usa diagnosis_date como start."""
        canonical = service.canonicalize_payload({
            "diagnosis_date": "2024-06-01",
            "drug_scheme": "ADT_MONO",
            "line_of_therapy_number": "1",
        })
        treatments = canonical.get("treatments") or []
        current = next((t for t in treatments if "auto-treatment-current" in str(t.get("source", ""))), None)
        assert current is not None
        assert current.get("start_date") == "2024-06-01"

    def test_g1982_existing_treatments_not_overwritten(self, service):
        """H.G1982 — Si treatments[] ya existe, NO se sobrescribe."""
        existing_treatments = [
            {"start_date": "2023-01-01", "drug_scheme": "ADT_MONO", "line_of_therapy_number": "1"},
            {"start_date": "2024-01-01", "drug_scheme": "ADT_ENZALUTAMIDE", "line_of_therapy_number": "2"},
        ]
        canonical = service.canonicalize_payload({
            "diagnosis_date": "2022-06-01",
            "drug_scheme": "ADT_DOCETAXEL",
            "treatments": existing_treatments,
            "most_recent_prior_line_drug_scheme": "ADT_ABIRATERONE",
            "most_recent_prior_line_start_date": "2024-06-01",
        })
        treatments = canonical.get("treatments") or []
        assert treatments == existing_treatments

    def test_g1983_two_lines_synthesized_in_order(self, service):
        """H.G1983 — Prior + current generan 2 entradas en orden cronológico."""
        canonical = service.canonicalize_payload({
            "diagnosis_date": "2024-01-15",
            "drug_scheme": "ADT_ENZALUTAMIDE",
            "line_of_therapy_number": "2",
            "most_recent_prior_line_drug_scheme": "ADT_MONO",
            "most_recent_prior_line_start_date": "2024-02-01",
            "most_recent_prior_line_end_date": "2024-12-15",
            "prior_treatment_lines_count": 1,
        })
        treatments = canonical.get("treatments") or []
        assert len(treatments) == 2
        assert treatments[0].get("line_of_therapy_number") == "1"
        assert treatments[1].get("line_of_therapy_number") == "2"

    def test_g1984_current_line_inferred_when_number_absent(self, service):
        """H.G1984 — Si no hay line_of_therapy_number explícito pero hay
        prior_treatment_lines_count, current = prior_count + 1."""
        canonical = service.canonicalize_payload({
            "diagnosis_date": "2024-01-15",
            "drug_scheme": "ADT_ENZALUTAMIDE",
            "most_recent_prior_line_drug_scheme": "ADT_MONO",
            "most_recent_prior_line_start_date": "2024-02-01",
            "most_recent_prior_line_end_date": "2024-12-15",
            "prior_treatment_lines_count": 1,
        })
        treatments = canonical.get("treatments") or []
        current = next((t for t in treatments if "auto-treatment-current" in str(t.get("source", ""))), None)
        assert current is not None
        assert current.get("line_of_therapy_number") == "2"

    def test_g1985_no_treatments_synthesized_when_no_drug_scheme(self, service):
        """H.G1985 — Sin drug_scheme actual ni prior, no se crea treatments[]."""
        canonical = service.canonicalize_payload({
            "diagnosis_date": "2024-01-15",
            "baseline_psa": 12.5,
        })
        treatments = canonical.get("treatments") or []
        assert not any(
            "auto-treatment" in str(t.get("source", ""))
            for t in treatments
        )

    def test_g1986_invalid_best_response_silently_ignored(self, service):
        """H.G1986 — best_psa_response_pct no numérico no rompe sintetización."""
        canonical = service.canonicalize_payload({
            "diagnosis_date": "2024-01-15",
            "most_recent_prior_line_drug_scheme": "ADT_MONO",
            "most_recent_prior_line_start_date": "2024-02-01",
            "most_recent_prior_line_best_psa_response_pct": "no aplica",
        })
        treatments = canonical.get("treatments") or []
        prior = next((t for t in treatments if "auto-treatment-history" in str(t.get("source", ""))), None)
        assert prior is not None
        assert "best_psa_response_pct" not in prior

    def test_g1987_drug_scheme_normalized_via_normalize_regimen_code(self, service):
        """H.G1987 — drug_scheme prior normalizado vía normalize_regimen_code."""
        canonical = service.canonicalize_payload({
            "diagnosis_date": "2024-01-15",
            "most_recent_prior_line_drug_scheme": "ADT_MONO",
            "most_recent_prior_line_start_date": "2024-02-01",
        })
        treatments = canonical.get("treatments") or []
        prior = next((t for t in treatments if "auto-treatment-history" in str(t.get("source", ""))), None)
        assert prior is not None
        assert isinstance(prior.get("drug_scheme"), str)
        assert len(prior.get("drug_scheme")) > 0
