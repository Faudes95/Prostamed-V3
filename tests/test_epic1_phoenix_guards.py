"""Tests EPIC 1 — Hardening de integridad + Phoenix enforcement.

Cubre:
  * test_phoenix_enforcement_gates_salvage_pathway
  * test_gleason_pattern_guards
  * test_comma_decimal_normalization
  * test_psadt_negative_not_trigger
  * test_tnm_strict_validation
  * test_state_classifier_metachronous_unknown
  * test_recurrence_eau_phoenix_gate
  * test_post_rt_salvage_copilot_phoenix_block

Estas pruebas corresponden a los hallazgos FAUBOT FASE 6 (Phoenix, G-1, GT-1,
IF-1, PSADT-1, DX-1, SC-1) y al criterio Phoenix NCCN PROS-10 (category 1) +
EAU 2026 §6.3.2 (Roach IJROBP 2006).
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest

from prostanet.shared.gleason_profile import (
    derive_gleason_score,
    derive_isup_grade,
    normalize_gleason_profile,
    safe_gleason_pattern,
)
from prostanet.shared.numeric_validation import (
    validate_cores_relationship,
    validate_gleason_pattern,
    validate_psa_range,
    validate_psadt,
)
from prostanet.shared.official_diagnosis import validate_tnm_payload
from prostanet.shared.phoenix import evaluate_phoenix, phoenix_failure
from prostanet.shared.ui_value_normalizer import (
    clamp_numeric,
    normalize_numeric_locale,
)


# ───────────────────────── Phoenix enforcement ────────────────────────────────


def test_phoenix_enforcement_gates_salvage_pathway():
    """Post-RT con PSA 1.2 sobre nadir 0.4 (delta 0.8) NO debe abrir salvage.

    EAU 2026 §6.3.2 / NCCN PROS-10 exigen cumplir Phoenix antes de re-estadificar.
    """
    from prostanet.domains.recurrence_bcr.rules_nccn import classify_recurrence

    payload = {
        "prior_prostatectomy": "0",
        "prior_radiation": "1",
        "bcr2": "0",
        "psa_current": "1.2",
        "psa_nadir": "0.4",
        "salvage_local_feasible": "1",
        "local_salvage_candidate": "1",
    }
    result = classify_recurrence(payload)

    assert result["label"] == "Pre-Phoenix monitoring"
    assert result.get("phoenix_gate_blocked") is True
    assert "PSA" in result["recommendation"]
    phoenix = result.get("phoenix", {})
    assert phoenix.get("phoenix_threshold_reached") is False
    # Phoenix threshold debe estar calculado con base nadir+2.
    assert phoenix.get("phoenix_threshold") == pytest.approx(2.4, abs=1e-3)


def test_phoenix_enforcement_opens_salvage_when_threshold_met():
    """Post-RT con PSA 2.6 sobre nadir 0.4 (delta 2.2) sí debe abrir salvage."""
    from prostanet.domains.recurrence_bcr.rules_nccn import classify_recurrence

    payload = {
        "prior_prostatectomy": "0",
        "prior_radiation": "1",
        "bcr2": "0",
        "psa_current": "2.6",
        "psa_nadir": "0.4",
        "salvage_local_feasible": "1",
        "local_salvage_candidate": "1",
    }
    result = classify_recurrence(payload)

    assert result["label"] != "Pre-Phoenix monitoring"
    assert result["label"].startswith("Post-RT")
    assert result.get("phoenix_gate_blocked") is not True
    assert result.get("phoenix", {}).get("phoenix_threshold_reached") is True


def test_recurrence_eau_phoenix_gate():
    """rules_eau también aplica Phoenix; sin delta suficiente no etiqueta BCR."""
    from prostanet.domains.recurrence_bcr.rules_eau import classify_recurrence_eau

    result = classify_recurrence_eau(
        {
            "prior_prostatectomy": "0",
            "prior_radiation": "1",
            "bcr2": "0",
            "psa_current": "0.9",
            "psa_nadir": "0.2",
        }
    )
    assert result["label"] == "Pre-Phoenix monitoring"
    assert result.get("phoenix_gate_blocked") is True


def test_post_rt_salvage_copilot_phoenix_block_logic():
    """Replica la lógica exacta del gate Phoenix usada por el copiloto post-RT.

    No instancia el servicio completo (requiere fixtures de paciente/DB); en su
    lugar verifica que, para el mismo payload, `evaluate_phoenix` + presencia de
    biopsia/mpMRI determinan el bloqueo tal como lo hace
    `PostRTSalvageCopilotService.evaluate` (líneas 227-241).
    """
    from prostanet.domains.patient_tracking.vertical_runtime import normalize_text

    payload_blocked = {
        "prior_radiation": "1",
        "psa_current": 1.4,
        "psa_nadir": 0.4,
        "biopsy_proven_local_recurrence": "0",
        "mpmri_localized_recurrence": "0",
    }
    phoenix = evaluate_phoenix(payload_blocked)
    biopsy_proven = normalize_text(payload_blocked.get("biopsy_proven_local_recurrence")).lower() in {"1", "true", "yes", "si", "sí"}
    radiographic_local = normalize_text(payload_blocked.get("mpmri_localized_recurrence")).lower() in {"1", "true", "yes", "si", "sí"}
    phoenix_gate_blocked = (
        not phoenix.threshold_reached and not biopsy_proven and not radiographic_local
    )
    assert phoenix_gate_blocked is True

    # Si hay biopsia confirmatoria local, el gate se libera aunque Phoenix siga
    # por debajo del umbral (criterio clínico EAU §6.3.2 — biopsia sustituye).
    payload_biopsy = {**payload_blocked, "biopsy_proven_local_recurrence": "1"}
    biopsy_proven = normalize_text(payload_biopsy.get("biopsy_proven_local_recurrence")).lower() in {"1", "true", "yes", "si", "sí"}
    phoenix_gate_blocked_biopsy = (
        not evaluate_phoenix(payload_biopsy).threshold_reached and not biopsy_proven
    )
    assert phoenix_gate_blocked_biopsy is False


# ───────────────────────── Gleason pattern guards ─────────────────────────────


def test_gleason_pattern_guards():
    """Patrones fuera de [1..5] deben rechazarse; totales fuera de [6..10] también."""
    assert safe_gleason_pattern("3") == 3
    assert safe_gleason_pattern("0") is None
    assert safe_gleason_pattern("6") is None  # pattern = 6 no es válido
    assert safe_gleason_pattern("-1") is None
    assert safe_gleason_pattern("abc") is None

    # Score derivation
    assert derive_gleason_score(3, 4) == 7
    assert derive_gleason_score(3, 2) is None  # total 5 < 6
    assert derive_gleason_score(6, 5) is None  # pattern 6 inválido
    assert derive_gleason_score(7, 7) is None

    # ISUP grade
    assert derive_isup_grade(3, 3) == 1
    assert derive_isup_grade(3, 2) is None  # rechaza total 5


def test_validate_gleason_pattern_returns_error_payload():
    value, error = validate_gleason_pattern("7")
    assert value is None
    assert error is not None and "Gleason" in error

    value, error = validate_gleason_pattern("3")
    assert value == 3
    assert error is None


def test_normalize_gleason_profile_respects_guards():
    profile = normalize_gleason_profile({"gleason_primary": "3", "gleason_secondary": "7"})
    assert profile["gleason_secondary"] is None  # 7 rechazado
    assert profile["gleason_primary"] == 3


# ──────────────────── Normalización numérica y locale IF-1 ────────────────────


def test_comma_decimal_normalization():
    """normalize_numeric_locale convierte coma decimal a punto sin perder datos."""
    assert normalize_numeric_locale("4,5") == "4.5"
    assert normalize_numeric_locale("1.234,56") == "1234.56"
    assert normalize_numeric_locale("3.14") == "3.14"
    assert normalize_numeric_locale(" ") == ""
    assert normalize_numeric_locale(None) is None
    assert normalize_numeric_locale(7.3) == 7.3


def test_clamp_numeric_rejects_negative_psa():
    value, error = clamp_numeric("-0.5", min_value=0, allow_negative=False)
    assert value is None
    assert error and "negativo" in error.lower()


def test_clamp_numeric_accepts_bounded_value():
    value, error = clamp_numeric("4,5", min_value=0, max_value=1000)
    assert value == pytest.approx(4.5)
    assert error is None


def test_validate_psa_range_rejects_negative():
    value, error = validate_psa_range(-1.0)
    assert value is None
    assert error is not None


def test_validate_psa_range_accepts_normal():
    value, error = validate_psa_range("7,8")  # locale español
    assert value == pytest.approx(7.8)
    assert error is None


# ─────────────────────── PSADT negatives (PSADT-1) ────────────────────────────


def test_psadt_negative_not_trigger():
    """PSADT negativo (PSA descendente) no debe considerarse como PSADT válido.

    El validador retorna (value, error). Valores inválidos exponen un error no
    vacío; el consumidor debe descartar la captura y no detonar BCR/PARP gates.
    """
    value, error = validate_psadt(-4)
    assert error is not None
    assert value is None  # allow_negative=False → valor descartado

    # 0 o < 0.1 también inválido (no asumible como PSADT clínico)
    value, error = validate_psadt(0)
    assert error is not None  # PSADT 0 → debajo del mínimo permitido

    value, error = validate_psadt("8,5")
    assert value == pytest.approx(8.5)
    assert error is None


# ─────────────────────── Cores relationship (C-3) ─────────────────────────────


def test_positive_cores_exceed_total_rejected():
    """cores positivos > total debe fallar validación (C-3).

    La función retorna ((positive, total), error). Error no-vacío marca el
    rechazo; el consumidor reporta al clínico y evita persistir el par.
    """
    (pos, total), error = validate_cores_relationship(8, 6)
    assert error is not None and "exceder" in error.lower()
    assert (pos, total) == (8, 6)

    (pos, total), error = validate_cores_relationship(2, 12)
    assert error is None
    assert (pos, total) == (2, 12)


# ─────────────────────── TNM backend (DX-1) ───────────────────────────────────


def test_tnm_strict_validation_rejects_invalid_suffix():
    """'T2Z' no existe en AJCC — debe reportarse como warning."""
    result = validate_tnm_payload({"clinical_tstage": "T2Z", "nodal_status": "N0", "m_substage": "M0"})
    assert result["valid"] is False
    assert any("T" in w for w in result["warnings"])


def test_tnm_strict_validation_accepts_clinical_prefix():
    """cT2b / cN0 / cM0 (prefix clínico) deben ser aceptados."""
    result = validate_tnm_payload({"clinical_tstage": "cT2b", "nodal_status": "cN0", "m_substage": "cM0"})
    assert result["valid"] is True
    assert result["warnings"] == []


def test_tnm_strict_validation_normalizes_m_substages():
    result = validate_tnm_payload({"clinical_tstage": "T3a", "nodal_status": "N1", "m_substage": "M1b"})
    assert result["valid"] is True


# ─────────────────── State classifier metachronous unknown (SC-1) ─────────────


def test_state_classifier_metachronous_unknown_guard():
    """SC-1: _is_metachronous_known debe devolver False cuando ningún campo de
    metacronía fue capturado explícitamente.
    """
    from prostanet.domains.state_classifier.service import StateClassifierService

    # Sin ningún campo → metacronía desconocida
    assert StateClassifierService._is_metachronous_known({}) is False

    # Con un campo de metacronía explícito → conocido
    assert (
        StateClassifierService._is_metachronous_known({"metachronous_metastasis": "1"})
        is True
    )
    assert (
        StateClassifierService._is_metachronous_known({"disease_onset_pattern": "metachronous"})
        is True
    )
    assert (
        StateClassifierService._is_metachronous_known({"synchronous_metastasis": "0"})
        is True
    )


# ─────────────────────── Phoenix helper directo ───────────────────────────────


def test_phoenix_helper_returns_unassessable_when_missing_inputs():
    ev = evaluate_phoenix({"psa_current": None, "psa_nadir": None})
    assert ev.assessable is False
    assert ev.threshold_reached is False


def test_phoenix_failure_helper_returns_threshold_reached():
    # phoenix_failure retorna True cuando PSA cumple Phoenix (nadir+2).
    assert phoenix_failure({"psa_current": 1.0, "psa_nadir": 0.4}) is False
    assert phoenix_failure({"psa_current": 2.5, "psa_nadir": 0.4}) is True
