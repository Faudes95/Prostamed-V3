"""tests/test_audit44_gates_29_30_olaparib_renal_lutetium_fatigue.py — Faubot 2026-04-25 (XLI).

Tests dedicados a Auditoría #44 — Gates 29-30 (olaparib renal G3 + lutetium fatigue G3).

Cubre H.G1093 - H.G1135 (43 hipótesis):

§A — Gate 29 trigger conditions (olaparib renal G3)
  H.G1093: CrCl <30 mL/min dispara gate 29
  H.G1094: CrCl 30 (boundary) NO dispara gate 29
  H.G1095: CrCl 35 (above threshold) NO dispara gate 29
  H.G1096: alias egfr_ml_min funciona como creatinine_clearance
  H.G1097: alias egfr funciona
  H.G1098: alias crcl_ml_min funciona
  H.G1099: alias cockcroft_gault_crcl funciona
  H.G1100: creatinine_ctcae_grade=3 dispara gate 29
  H.G1101: creatinine_ctcae_grade=4 dispara gate 29
  H.G1102: creatinine_ctcae_grade=2 NO dispara gate 29
  H.G1103: end_stage_renal_disease_dialysis=Sí dispara gate 29
  H.G1104: alias esrd_on_dialysis funciona
  H.G1105: alias on_hemodialysis funciona

§B — Gate 29 override (olaparib renal recovered)
  H.G1106: override renal_function_corrected_for_olaparib=Sí desactiva gate 29
  H.G1107: alias olaparib_renal_override funciona
  H.G1108: alias crcl_corrected_for_olaparib funciona
  H.G1109: override=No NO desactiva (debe ser truthy positivo)

§C — Gate 29 regimen scoping
  H.G1110: gate 29 disparado bloquea OLAPARIB en filtered_treatments
  H.G1111: gate 29 disparado bloquea ABIRATERONE_OLAPARIB (PROpel combo)
  H.G1112: NIRAPARIB NO bloqueado por gate 29 (regimen scoping correcto)
  H.G1113: TALAZOPARIB NO bloqueado por gate 29

§D — Gate 30 trigger conditions (lutetium fatigue G3)
  H.G1114: fatigue_ctcae_grade=3 dispara gate 30
  H.G1115: fatigue_ctcae_grade=4 dispara gate 30
  H.G1116: fatigue_ctcae_grade=2 NO dispara gate 30
  H.G1117: ECOG=3 dispara gate 30 (proxy)
  H.G1118: ECOG=4 dispara gate 30
  H.G1119: ECOG=2 NO dispara gate 30
  H.G1120: KPS=40 dispara gate 30 (boundary inclusive)
  H.G1121: KPS=30 dispara gate 30
  H.G1122: KPS=50 NO dispara gate 30
  H.G1123: bedridden_status_documented=Sí dispara gate 30
  H.G1124: alias fatigue_grade funciona
  H.G1125: alias asthenia_ctcae_grade funciona

§E — Gate 30 override
  H.G1126: override fatigue_resolved_for_lutetium=Sí desactiva gate 30
  H.G1127: alias fatigue_corrected_for_lutetium funciona

§F — Gate 30 regimen scoping
  H.G1128: gate 30 bloquea LU177_PSMA617 (Pluvicto)
  H.G1129: gate 30 bloquea PLUVICTO alias
  H.G1130: OLAPARIB NO bloqueado por gate 30 (no es Lu-177)

§G — Catálogo + integración
  H.G1131: 30 YAML gates totales cargados
  H.G1132: gate 29 + 30 expuestos en get_active_gate_codes()
  H.G1133: get_per_gate_yaml_shas() incluye SHAs nuevos
  H.G1134: REGIMEN_CODES_OLAPARIB exporta {OLAPARIB, ABIRATERONE_OLAPARIB}
  H.G1135: 7 nuevos FieldSpecs en pivotal_gate_supporting_fields()
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest


# ════════════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════════════


def _evaluate(payload: dict, treatments: list | None = None) -> dict:
    """Wrapper sobre apply_pivotal_contraindication_gates para tests."""
    from prostanet.shared.pivotal_contraindication_gates import (
        apply_pivotal_contraindication_gates,
    )
    return apply_pivotal_contraindication_gates(payload, treatments or [])


def _gate_codes(result: dict) -> list[str]:
    return [g["code"] for g in result.get("gates_triggered", [])]


def _olaparib_treatments() -> list[dict]:
    return [
        {"regimen_code": "OLAPARIB", "regimen_name": "Olaparib (PROfound mono)"},
        {"regimen_code": "ABIRATERONE_OLAPARIB", "regimen_name": "Abi+Olaparib (PROpel)"},
    ]


def _lutetium_treatments() -> list[dict]:
    return [
        {"regimen_code": "LU177_PSMA617", "regimen_name": "Pluvicto (Lu-177)"},
    ]


# ════════════════════════════════════════════════════════════════════
# §A — Gate 29 trigger conditions
# ════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("crcl", [29, 25, 20, 15, 10, 5])
def test_g1093_gate29_fires_when_crcl_below_30(crcl):
    """H.G1093 — Gate 29 fires when creatinine_clearance < 30."""
    result = _evaluate({"creatinine_clearance": crcl})
    assert "olaparib_renal_dysfunction_grade3" in _gate_codes(result)


def test_g1094_gate29_does_NOT_fire_at_boundary_30(_=None):
    """H.G1094 — CrCl exactly 30 should NOT fire gate 29 (numeric_below strict)."""
    result = _evaluate({"creatinine_clearance": 30})
    assert "olaparib_renal_dysfunction_grade3" not in _gate_codes(result)


@pytest.mark.parametrize("crcl", [31, 35, 50, 80, 120])
def test_g1095_gate29_does_NOT_fire_above_threshold(crcl):
    """H.G1095 — Gate 29 does NOT fire when CrCl >= 30."""
    result = _evaluate({"creatinine_clearance": crcl})
    assert "olaparib_renal_dysfunction_grade3" not in _gate_codes(result)


def test_g1096_gate29_alias_egfr_ml_min():
    """H.G1096 — egfr_ml_min works as alias for creatinine_clearance."""
    result = _evaluate({"egfr_ml_min": 25})
    assert "olaparib_renal_dysfunction_grade3" in _gate_codes(result)


def test_g1097_gate29_alias_egfr():
    """H.G1097 — egfr (short) works as alias."""
    result = _evaluate({"egfr": 20})
    assert "olaparib_renal_dysfunction_grade3" in _gate_codes(result)


def test_g1098_gate29_alias_crcl_ml_min():
    """H.G1098 — crcl_ml_min alias works."""
    result = _evaluate({"crcl_ml_min": 28})
    assert "olaparib_renal_dysfunction_grade3" in _gate_codes(result)


def test_g1099_gate29_alias_cockcroft_gault_crcl():
    """H.G1099 — cockcroft_gault_crcl alias works."""
    result = _evaluate({"cockcroft_gault_crcl": 22})
    assert "olaparib_renal_dysfunction_grade3" in _gate_codes(result)


@pytest.mark.parametrize("grade", [3, 4])
def test_g1100_g1101_gate29_fires_on_aki_grade_3plus(grade):
    """H.G1100/H.G1101 — creatinine_ctcae_grade ≥3 fires gate 29."""
    result = _evaluate({"creatinine_ctcae_grade": grade})
    assert "olaparib_renal_dysfunction_grade3" in _gate_codes(result)


def test_g1102_gate29_does_NOT_fire_on_aki_grade_2():
    """H.G1102 — creatinine_ctcae_grade=2 does NOT fire gate 29."""
    result = _evaluate({"creatinine_ctcae_grade": 2})
    assert "olaparib_renal_dysfunction_grade3" not in _gate_codes(result)


def test_g1103_gate29_fires_on_esrd_dialysis_flag():
    """H.G1103 — end_stage_renal_disease_dialysis=Sí fires gate 29."""
    result = _evaluate({"end_stage_renal_disease_dialysis": "Sí"})
    assert "olaparib_renal_dysfunction_grade3" in _gate_codes(result)


def test_g1104_gate29_alias_esrd_on_dialysis():
    """H.G1104 — esrd_on_dialysis alias fires gate 29."""
    result = _evaluate({"esrd_on_dialysis": "Sí"})
    assert "olaparib_renal_dysfunction_grade3" in _gate_codes(result)


def test_g1105_gate29_alias_on_hemodialysis():
    """H.G1105 — on_hemodialysis alias fires gate 29."""
    result = _evaluate({"on_hemodialysis": "Sí"})
    assert "olaparib_renal_dysfunction_grade3" in _gate_codes(result)


# ════════════════════════════════════════════════════════════════════
# §B — Gate 29 override
# ════════════════════════════════════════════════════════════════════


def test_g1106_gate29_override_canonical():
    """H.G1106 — renal_function_corrected_for_olaparib=Sí overrides gate 29."""
    result = _evaluate({
        "creatinine_clearance": 25,
        "renal_function_corrected_for_olaparib": "Sí",
    })
    assert "olaparib_renal_dysfunction_grade3" not in _gate_codes(result)


def test_g1107_gate29_override_alias_olaparib_renal_override():
    """H.G1107 — olaparib_renal_override alias works."""
    result = _evaluate({
        "creatinine_clearance": 20,
        "olaparib_renal_override": "Sí",
    })
    assert "olaparib_renal_dysfunction_grade3" not in _gate_codes(result)


def test_g1108_gate29_override_alias_crcl_corrected_for_olaparib():
    """H.G1108 — crcl_corrected_for_olaparib alias works."""
    result = _evaluate({
        "creatinine_clearance": 15,
        "crcl_corrected_for_olaparib": "Sí",
    })
    assert "olaparib_renal_dysfunction_grade3" not in _gate_codes(result)


def test_g1109_gate29_override_negative_does_NOT_disable():
    """H.G1109 — override='No' does NOT disable gate (truthy positive only)."""
    result = _evaluate({
        "creatinine_clearance": 20,
        "renal_function_corrected_for_olaparib": "No",
    })
    assert "olaparib_renal_dysfunction_grade3" in _gate_codes(result)


# ════════════════════════════════════════════════════════════════════
# §C — Gate 29 regimen scoping
# ════════════════════════════════════════════════════════════════════


def test_g1110_gate29_blocks_olaparib():
    """H.G1110 — Gate 29 fires + filters OLAPARIB out."""
    result = _evaluate(
        {"creatinine_clearance": 20},
        [{"regimen_code": "OLAPARIB", "regimen_name": "Olaparib"}],
    )
    filtered_codes = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "OLAPARIB" not in filtered_codes


def test_g1111_gate29_blocks_abiraterone_olaparib_combo():
    """H.G1111 — Gate 29 filters ABIRATERONE_OLAPARIB (PROpel combo)."""
    result = _evaluate(
        {"creatinine_clearance": 20},
        [{"regimen_code": "ABIRATERONE_OLAPARIB"}],
    )
    filtered_codes = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "ABIRATERONE_OLAPARIB" not in filtered_codes


def test_g1112_gate29_does_NOT_block_niraparib():
    """H.G1112 — NIRAPARIB NOT blocked by gate 29 (regimen scoped to olaparib)."""
    treatments = [
        {"regimen_code": "NIRAPARIB"},
        {"regimen_code": "NIRAPARIB_ABIRATERONE"},
    ]
    result = _evaluate({"creatinine_clearance": 20}, treatments)
    filtered_codes = [t.get("regimen_code") for t in result["filtered_treatments"]]
    # NIRAPARIB should remain (gate 29 scoped to olaparib only;
    # gate 22 niraparib_severe_thrombocytopenia would NOT trigger here)
    assert "NIRAPARIB" in filtered_codes
    assert "NIRAPARIB_ABIRATERONE" in filtered_codes


def test_g1113_gate29_does_NOT_block_talazoparib():
    """H.G1113 — TALAZOPARIB-related regimens NOT blocked by gate 29."""
    treatments = [
        {"regimen_code": "TALAZOPARIB_ENZALUTAMIDE"},
        {"regimen_code": "ADT_TALAZO_ENZA_HRR"},
    ]
    result = _evaluate({"creatinine_clearance": 20}, treatments)
    filtered_codes = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "TALAZOPARIB_ENZALUTAMIDE" in filtered_codes
    assert "ADT_TALAZO_ENZA_HRR" in filtered_codes


# ════════════════════════════════════════════════════════════════════
# §D — Gate 30 trigger conditions
# ════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("grade", [3, 4])
def test_g1114_g1115_gate30_fires_on_fatigue_grade_3plus(grade):
    """H.G1114/H.G1115 — fatigue_ctcae_grade ≥3 fires gate 30."""
    result = _evaluate({"fatigue_ctcae_grade": grade})
    assert "lutetium177_fatigue_grade3" in _gate_codes(result)


@pytest.mark.parametrize("grade", [0, 1, 2])
def test_g1116_gate30_does_NOT_fire_on_fatigue_grade_0_to_2(grade):
    """H.G1116 — fatigue_ctcae_grade <3 does NOT fire gate 30."""
    result = _evaluate({"fatigue_ctcae_grade": grade})
    assert "lutetium177_fatigue_grade3" not in _gate_codes(result)


@pytest.mark.parametrize("ecog", [3, 4])
def test_g1117_g1118_gate30_fires_on_ecog_3plus(ecog):
    """H.G1117/H.G1118 — ECOG ≥3 fires gate 30 (proxy for severe fatigue)."""
    result = _evaluate({"ecog_score": ecog})
    assert "lutetium177_fatigue_grade3" in _gate_codes(result)


@pytest.mark.parametrize("ecog", [0, 1, 2])
def test_g1119_gate30_does_NOT_fire_on_ecog_below_3(ecog):
    """H.G1119 — ECOG <3 does NOT fire gate 30."""
    result = _evaluate({"ecog_score": ecog})
    assert "lutetium177_fatigue_grade3" not in _gate_codes(result)


def test_g1120_gate30_fires_at_kps_boundary_40():
    """H.G1120 — KPS=40 (boundary) fires gate 30 (numeric_below threshold=41)."""
    result = _evaluate({"karnofsky_performance_status": 40})
    assert "lutetium177_fatigue_grade3" in _gate_codes(result)


@pytest.mark.parametrize("kps", [10, 20, 30])
def test_g1121_gate30_fires_at_kps_below_40(kps):
    """H.G1121 — KPS ≤30 fires gate 30."""
    result = _evaluate({"karnofsky_performance_status": kps})
    assert "lutetium177_fatigue_grade3" in _gate_codes(result)


@pytest.mark.parametrize("kps", [50, 60, 70, 80, 90, 100])
def test_g1122_gate30_does_NOT_fire_above_kps_40(kps):
    """H.G1122 — KPS ≥50 does NOT fire gate 30."""
    result = _evaluate({"karnofsky_performance_status": kps})
    assert "lutetium177_fatigue_grade3" not in _gate_codes(result)


def test_g1123_gate30_fires_on_bedridden_flag():
    """H.G1123 — bedridden_status_documented=Sí fires gate 30."""
    result = _evaluate({"bedridden_status_documented": "Sí"})
    assert "lutetium177_fatigue_grade3" in _gate_codes(result)


def test_g1124_gate30_alias_fatigue_grade():
    """H.G1124 — fatigue_grade alias works."""
    result = _evaluate({"fatigue_grade": 4})
    assert "lutetium177_fatigue_grade3" in _gate_codes(result)


def test_g1125_gate30_alias_asthenia_ctcae_grade():
    """H.G1125 — asthenia_ctcae_grade alias works."""
    result = _evaluate({"asthenia_ctcae_grade": 3})
    assert "lutetium177_fatigue_grade3" in _gate_codes(result)


# ════════════════════════════════════════════════════════════════════
# §E — Gate 30 override
# ════════════════════════════════════════════════════════════════════


def test_g1126_gate30_override_canonical():
    """H.G1126 — fatigue_resolved_for_lutetium=Sí overrides gate 30."""
    result = _evaluate({
        "fatigue_ctcae_grade": 3,
        "fatigue_resolved_for_lutetium": "Sí",
    })
    assert "lutetium177_fatigue_grade3" not in _gate_codes(result)


def test_g1127_gate30_override_alias_fatigue_corrected_for_lutetium():
    """H.G1127 — fatigue_corrected_for_lutetium alias works."""
    result = _evaluate({
        "ecog_score": 3,
        "fatigue_corrected_for_lutetium": "Sí",
    })
    assert "lutetium177_fatigue_grade3" not in _gate_codes(result)


# ════════════════════════════════════════════════════════════════════
# §F — Gate 30 regimen scoping
# ════════════════════════════════════════════════════════════════════


def test_g1128_gate30_blocks_lu177_psma617():
    """H.G1128 — Gate 30 filters LU177_PSMA617 out."""
    result = _evaluate(
        {"fatigue_ctcae_grade": 3},
        [{"regimen_code": "LU177_PSMA617"}],
    )
    filtered_codes = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "LU177_PSMA617" not in filtered_codes


def test_g1129_gate30_blocks_pluvicto_alias():
    """H.G1129 — Gate 30 filters PLUVICTO alias regimen code."""
    result = _evaluate(
        {"fatigue_ctcae_grade": 4},
        [{"regimen_code": "PLUVICTO"}],
    )
    filtered_codes = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "PLUVICTO" not in filtered_codes


def test_g1130_gate30_does_NOT_block_olaparib():
    """H.G1130 — OLAPARIB NOT blocked by gate 30 (Lu-177-only scope)."""
    result = _evaluate(
        {"fatigue_ctcae_grade": 3},
        [{"regimen_code": "OLAPARIB"}, {"regimen_code": "ABIRATERONE_OLAPARIB"}],
    )
    filtered_codes = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "OLAPARIB" in filtered_codes
    assert "ABIRATERONE_OLAPARIB" in filtered_codes


# ════════════════════════════════════════════════════════════════════
# §G — Catálogo + integración
# ════════════════════════════════════════════════════════════════════


def test_g1131_total_yaml_gates_count_is_30():
    """H.G1131 — Catálogo YAML expone 30 gates totales tras audit #44."""
    from prostanet.shared.pivotal_gates_yaml_loader import get_loaded_yaml_codes
    codes = get_loaded_yaml_codes()
    assert len(codes) >= 30, f"Expected ≥30 YAML gates, got {len(codes)}"
    assert "olaparib_renal_dysfunction_grade3" in codes
    assert "lutetium177_fatigue_grade3" in codes


def test_g1132_active_gate_codes_includes_29_30():
    """H.G1132 — get_active_gate_codes() incluye los nuevos gates."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    codes = get_active_gate_codes()
    assert "olaparib_renal_dysfunction_grade3" in codes
    assert "lutetium177_fatigue_grade3" in codes


def test_g1133_per_gate_yaml_shas_includes_29_30():
    """H.G1133 — get_per_gate_yaml_shas() expone SHA de gates 29 + 30."""
    from prostanet.shared.algorithm_version import get_per_gate_yaml_shas
    shas = get_per_gate_yaml_shas()
    assert "olaparib_renal_dysfunction_grade3" in shas
    assert "lutetium177_fatigue_grade3" in shas
    # SHAs deben ser strings no vacíos (12 chars hex)
    assert len(shas["olaparib_renal_dysfunction_grade3"]) == 12
    assert len(shas["lutetium177_fatigue_grade3"]) == 12


def test_g1134_regimen_codes_olaparib_exports():
    """H.G1134 — REGIMEN_CODES_OLAPARIB exporta los regímenes esperados."""
    from prostanet.shared.pivotal_contraindication_gates import (
        REGIMEN_CODES_OLAPARIB, KEYWORDS_OLAPARIB,
    )
    assert "OLAPARIB" in REGIMEN_CODES_OLAPARIB
    assert "ABIRATERONE_OLAPARIB" in REGIMEN_CODES_OLAPARIB
    # No debe contener rucaparib (gate 10 separado)
    assert "RUCAPARIB" not in REGIMEN_CODES_OLAPARIB
    assert "olaparib" in KEYWORDS_OLAPARIB
    assert "lynparza" in KEYWORDS_OLAPARIB


def test_g1135_seven_new_fieldspecs_registered():
    """H.G1135 — 7 nuevos FieldSpecs gates 29-30 registrados."""
    from prostanet.shared.advanced_support_fields import pivotal_gate_supporting_fields
    fields = pivotal_gate_supporting_fields()
    field_names = {f.name for f in fields}
    expected = {
        "creatinine_ctcae_grade",
        "end_stage_renal_disease_dialysis",
        "renal_function_corrected_for_olaparib",
        "fatigue_ctcae_grade",
        "karnofsky_performance_status",
        "bedridden_status_documented",
        "fatigue_resolved_for_lutetium",
    }
    missing = expected - field_names
    assert not missing, f"Missing FieldSpecs: {missing}"


# ════════════════════════════════════════════════════════════════════
# §H — Smoke E2E (end-to-end with realistic clinical scenarios)
# ════════════════════════════════════════════════════════════════════


def test_smoke_end_to_end_olaparib_renal_failure_patient():
    """E2E: paciente HRR+ con AKI grado 3 + olaparib en consideración."""
    payload = {
        "creatinine_clearance": 22,
        "creatinine_ctcae_grade": 3,
        "brca_mutation_documented": "Sí",
    }
    treatments = [
        {"regimen_code": "OLAPARIB", "regimen_name": "Olaparib (PROfound)"},
        {"regimen_code": "NIRAPARIB", "regimen_name": "Niraparib"},
        {"regimen_code": "DOCETAXEL", "regimen_name": "Docetaxel"},
    ]
    result = _evaluate(payload, treatments)
    codes = _gate_codes(result)
    assert "olaparib_renal_dysfunction_grade3" in codes
    # Olaparib filtrado, niraparib + docetaxel disponibles
    filtered_codes = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "OLAPARIB" not in filtered_codes
    assert "NIRAPARIB" in filtered_codes
    assert "DOCETAXEL" in filtered_codes
    # Mensaje "not_recommended" debe contener cita Lynparza
    msgs = result.get("not_recommended_messages", [])
    msg_text = " ".join(msgs)
    assert "Lynparza" in msg_text or "olaparib" in msg_text.lower()


def test_smoke_end_to_end_lutetium_severe_fatigue_patient():
    """E2E: paciente PSMA-positive con ECOG 3 + fatigue G3."""
    payload = {
        "fatigue_ctcae_grade": 3,
        "ecog_score": 3,
        "psma_pet_positive": "Sí",
    }
    treatments = [
        {"regimen_code": "LU177_PSMA617"},
        {"regimen_code": "DOCETAXEL"},
        {"regimen_code": "CABAZITAXEL"},
    ]
    result = _evaluate(payload, treatments)
    codes = _gate_codes(result)
    assert "lutetium177_fatigue_grade3" in codes
    filtered_codes = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "LU177_PSMA617" not in filtered_codes
    # Docetaxel debe estar disponible
    assert "DOCETAXEL" in filtered_codes


def test_smoke_healthy_payload_does_NOT_fire_either_gate():
    """E2E: paciente saludable NO dispara gates 29-30."""
    payload = {
        "creatinine_clearance": 90,
        "creatinine_ctcae_grade": 0,
        "fatigue_ctcae_grade": 1,
        "ecog_score": 1,
        "karnofsky_performance_status": 90,
    }
    treatments = [
        {"regimen_code": "OLAPARIB"},
        {"regimen_code": "LU177_PSMA617"},
    ]
    result = _evaluate(payload, treatments)
    codes = _gate_codes(result)
    assert "olaparib_renal_dysfunction_grade3" not in codes
    assert "lutetium177_fatigue_grade3" not in codes
    filtered_codes = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "OLAPARIB" in filtered_codes
    assert "LU177_PSMA617" in filtered_codes
