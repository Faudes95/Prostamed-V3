"""EPIC 23.fix — Cortana intake extraction regression tests.

Reported by clinician 2026-05-13:
> "Ingresaremos a un paciente con adenocarcinoma intraductal, con diagnóstico
>  de la fecha tal, con antígeno pre biopsia y actual, con tacto rectal..."
> verificar que Cortana entienda todos los campos solicitados al ingreso.

Pre-EPIC 23.fix the extractor missed 5/6 critical fields:
  - histology_subtype (intraductal not in pattern)
  - diagnosis_date (gated by failed positive_diagnosis_match)
  - psa_baseline_ng_ml (regex didn't accept "antígeno" alias)
  - psa (multi-modifier consumption broken)
  - dre_suspicious (no pattern at all)

This module exercises the clinician's reference utterance + 6 edge cases.
"""

from __future__ import annotations

import pytest

from prostanet.voice.intent_extractor import extract_intake_classifier_candidates


def _extract(utterance: str) -> dict:
    candidates = extract_intake_classifier_candidates(utterance, session_key="t")
    return {c["field_name"]: c["value"] for c in candidates}


# ─────────────────── Reference scenario ───────────────────


def test_clinician_reference_utterance_full_coverage():
    """The exact 4-section utterance reported by the clinician."""
    utterance = (
        "Ingresaremos a un paciente con adenocarcinoma intraductal, "
        "con diagnóstico de la fecha 2026-05-10, "
        "con antígeno prebiopsia de 14.5 y antígeno actual de 22.3, "
        "con tacto rectal sospechoso."
    )
    extracted = _extract(utterance)
    # Section 1 — Histology
    assert extracted.get("known_cancer_diagnosis") == "1"
    assert "intraductal" in str(extracted.get("histology_subtype", "")).lower()
    assert extracted.get("histology_aggressive_variant") == "1"
    # Section 2 — Diagnosis date
    assert extracted.get("diagnosis_date") == "2026-05-10"
    # Section 3 — PSA (pre-biopsy + actual)
    assert extracted.get("psa_baseline_ng_ml") == 14.5
    assert extracted.get("psa") == 22.3
    # Section 4 — DRE
    assert extracted.get("dre_suspicious") == "1"


# ─────────────────── Histology variants ───────────────────


def test_intraductal_recognized_as_distinct_subtype():
    extracted = _extract("paciente con adenocarcinoma intraductal confirmado")
    assert "intraductal" in str(extracted.get("histology_subtype", "")).lower()
    assert extracted.get("histology_aggressive_variant") == "1"
    assert extracted.get("known_cancer_diagnosis") == "1"


def test_ductal_recognized_distinct_from_intraductal():
    extracted = _extract("adenocarcinoma ductal confirmado")
    assert extracted.get("histology_subtype") == "Adenocarcinoma ductal"
    # Ductal is NOT aggressive variant (intraductal is the aggressive one)
    assert extracted.get("histology_aggressive_variant") != "1"


def test_acinar_default_when_no_subtype():
    extracted = _extract("adenocarcinoma confirmado por biopsia")
    assert extracted.get("histology_subtype") == "Adenocarcinoma acinar"


# ─────────────────── PSA extraction (multi-alias) ───────────────────


def test_psa_antigen_alias_prebiopsia_routes_to_baseline():
    extracted = _extract("antígeno prebiopsia de 8.5")
    assert extracted.get("psa_baseline_ng_ml") == 8.5


def test_psa_antigen_actual_routes_to_current():
    extracted = _extract("antígeno actual de 12.0")
    assert extracted.get("psa") == 12.0


def test_psa_both_pre_and_actual_in_one_utterance():
    extracted = _extract("antígeno prebiopsia 9.5, antígeno actual 18.3")
    assert extracted.get("psa_baseline_ng_ml") == 9.5
    assert extracted.get("psa") == 18.3


def test_psa_unmodified_with_negative_dx_routes_to_current():
    """EPIC 23.fix: 'sin cáncer confirmado, PSA 6.5' must NOT route PSA to
    baseline (patient has no confirmed Dx; PSA is sospecha/screening).
    """
    extracted = _extract("paciente sin cáncer confirmado, PSA 6.5")
    assert extracted.get("psa") == 6.5
    assert extracted.get("psa_baseline_ng_ml") is None
    assert extracted.get("known_cancer_diagnosis") == "0"


def test_psa_psa_alias_still_works():
    """Legacy 'psa' / 'ape' aliases preserved alongside 'antígeno'."""
    extracted = _extract("PSA actual 15.2")
    assert extracted.get("psa") == 15.2


# ─────────────────── DRE (tacto rectal) ───────────────────


def test_dre_sospechoso_extracted():
    extracted = _extract("tacto rectal sospechoso")
    assert extracted.get("dre_suspicious") == "1"
    assert extracted.get("dre_finding_description") == "sospechoso"


def test_dre_anormal_extracted():
    extracted = _extract("DRE anormal con nódulo")
    assert extracted.get("dre_suspicious") == "1"


def test_dre_normal_extracted():
    extracted = _extract("tacto rectal normal sin alteraciones")
    assert extracted.get("dre_suspicious") == "0"


def test_dre_sin_alteraciones_extracted():
    extracted = _extract("tacto rectal sin alteraciones")
    assert extracted.get("dre_suspicious") == "0"


def test_dre_sospechoso_does_NOT_trigger_negative_diagnosis():
    """EPIC 23.fix: 'tacto rectal sospechoso' must not fire negative
    diagnosis match (the word 'sospechoso' is the DRE finding, not a
    diagnosis-suspicion modifier).
    """
    extracted = _extract(
        "Adenocarcinoma intraductal confirmado, tacto rectal sospechoso"
    )
    # Cancer diagnosis IS confirmed (intraductal) AND dre is suspicious
    assert extracted.get("known_cancer_diagnosis") == "1"
    assert extracted.get("dre_suspicious") == "1"


# ─────────────────── Combined complex scenarios ───────────────────


def test_full_diagnostic_workup_dictation():
    """Realistic clinician dictation covering 4 intake sections at once."""
    utterance = (
        "Paciente nuevo, adenocarcinoma intraductal confirmado por biopsia, "
        "diagnóstico 2026-04-15, Gleason 4 más 3, antígeno prebiopsia 12.8, "
        "antígeno actual 14.2, tacto rectal con nódulo, PI-RADS 5."
    )
    extracted = _extract(utterance)
    assert extracted.get("known_cancer_diagnosis") == "1"
    assert "intraductal" in str(extracted.get("histology_subtype", "")).lower()
    assert extracted.get("histology_aggressive_variant") == "1"
    assert extracted.get("diagnosis_date") == "2026-04-15"
    assert extracted.get("gleason_primary") == "4"
    assert extracted.get("gleason_secondary") == "3"
    assert extracted.get("psa_baseline_ng_ml") == 12.8
    assert extracted.get("psa") == 14.2
    assert extracted.get("dre_suspicious") == "1"
    assert extracted.get("pirads_score") == "5"


def test_screening_scenario_no_diagnosis():
    """Screening dictation should NOT trigger cancer_diagnosis=1."""
    extracted = _extract(
        "Tamizaje anual, PSA 5.8, tacto rectal normal, sin antecedentes familiares"
    )
    assert extracted.get("known_cancer_diagnosis") == "0"
    assert extracted.get("dre_suspicious") == "0"
    assert extracted.get("psa") == 5.8


def test_empty_utterance_returns_no_candidates():
    assert _extract("") == {}
    assert _extract("   ") == {}
