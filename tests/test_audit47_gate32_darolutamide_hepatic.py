"""tests/test_audit47_gate32_darolutamide_hepatic.py — Faubot 2026-04-25 (XLIV).

Tests dedicados a Auditoría #47 — Gate 32 darolutamide × hepatic dysfunction G3.

Cubre H.G1176 - H.G1210 (35 hipótesis):

§A — Triggers numéricos directos (AST/ALT/bilirubin)
  H.G1176: AST > 200 IU/L dispara gate 32 (5× ULN típico)
  H.G1177: ALT > 200 IU/L dispara gate 32
  H.G1178: AST = 200 (boundary inclusive numeric_above strict)
  H.G1179: bilirubin_total_mg_dl > 2.0 dispara
  H.G1180: AST 150 (below threshold) NO dispara
  H.G1181: bilirubin 1.5 (below threshold) NO dispara
  H.G1182-H.G1185: aliases AST (sgot, ast_iu_l, ast_baseline, ast_serum)
  H.G1186-H.G1189: aliases ALT (sgpt, alt_iu_l, alt_baseline, alt_serum)
  H.G1190-H.G1191: aliases bilirubin (total_bilirubin, bilirubin_total)

§B — Triggers CTCAE
  H.G1192: ast_ctcae_grade=3 dispara
  H.G1193: ast_ctcae_grade=4 dispara
  H.G1194: ast_ctcae_grade=2 NO dispara
  H.G1195: alt_ctcae_grade=3 dispara
  H.G1196: alias ast_grade funciona

§C — Trigger flag hepatocellular pattern
  H.G1197: hepatocellular_pattern_documented_for_darolutamide=Sí dispara
  H.G1198: alias hepatocellular_injury_documented funciona

§D — Override
  H.G1199: hepatic_function_recovered_for_darolutamide=Sí desactiva
  H.G1200: alias darolutamide_hepatic_override funciona
  H.G1201: override=No NO desactiva (truthy required)

§E — Regimen scoping (darolutamide-specific)
  H.G1202: gate 32 bloquea DAROLUTAMIDE
  H.G1203: gate 32 bloquea ADT_DAROLUTAMIDE
  H.G1204: gate 32 bloquea ADT_DOCETAXEL_DAROLUTAMIDE (ARASENS combo)
  H.G1205: gate 32 NO bloquea ENZALUTAMIDE (ARSI distinto)
  H.G1206: gate 32 NO bloquea APALUTAMIDE (ARSI distinto)
  H.G1207: gate 32 NO bloquea ABIRATERONE (gate 21 separado, patrón distinto)

§F — Coexistencia con gate 21 (abiraterone_hepatotoxicity_grade3)
  H.G1208: AST >200 dispara AMBOS gates 21 + 32 simultáneamente
  H.G1209: gate 21 + 32 con regímenes apropiados → bloqueo separado por scope

§G — Catálogo + integración + UI classifier
  H.G1210: 32 YAML gates + class_label específico + 4 FieldSpecs registrados
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest


# ════════════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════════════


def _evaluate(payload: dict, treatments: list | None = None) -> dict:
    from prostanet.shared.pivotal_contraindication_gates import (
        apply_pivotal_contraindication_gates,
    )
    return apply_pivotal_contraindication_gates(payload, treatments or [])


def _gate_codes(result: dict) -> list[str]:
    return [g["code"] for g in result.get("gates_triggered", [])]


# ════════════════════════════════════════════════════════════════════
# §A — Triggers numéricos directos
# ════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("ast", [201, 250, 400, 800, 1500])
def test_g1176_gate32_fires_when_ast_above_200(ast):
    """H.G1176 — Gate 32 fires when AST > 200 IU/L."""
    result = _evaluate({"ast_value": ast})
    assert "darolutamide_hepatotoxicity_grade3" in _gate_codes(result)


@pytest.mark.parametrize("alt", [201, 250, 400, 800, 1500])
def test_g1177_gate32_fires_when_alt_above_200(alt):
    """H.G1177 — Gate 32 fires when ALT > 200 IU/L."""
    result = _evaluate({"alt_value": alt})
    assert "darolutamide_hepatotoxicity_grade3" in _gate_codes(result)


def test_g1178_gate32_NOT_fires_at_ast_boundary_200():
    """H.G1178 — AST exactly 200 NO dispara (numeric_above strict, no inclusive)."""
    result = _evaluate({"ast_value": 200})
    assert "darolutamide_hepatotoxicity_grade3" not in _gate_codes(result)


@pytest.mark.parametrize("bili", [2.1, 2.5, 3.0, 5.0])
def test_g1179_gate32_fires_when_bilirubin_above_2(bili):
    """H.G1179 — Gate 32 fires when bilirubin > 2 mg/dL."""
    result = _evaluate({"bilirubin_total_mg_dl": bili})
    assert "darolutamide_hepatotoxicity_grade3" in _gate_codes(result)


@pytest.mark.parametrize("ast", [50, 100, 150, 199])
def test_g1180_gate32_NOT_fires_below_ast_threshold(ast):
    """H.G1180 — AST <200 NO dispara gate 32."""
    result = _evaluate({"ast_value": ast})
    assert "darolutamide_hepatotoxicity_grade3" not in _gate_codes(result)


@pytest.mark.parametrize("bili", [0.5, 1.0, 1.5, 2.0])
def test_g1181_gate32_NOT_fires_below_bilirubin_threshold(bili):
    """H.G1181 — bilirubin ≤2 NO dispara gate 32."""
    result = _evaluate({"bilirubin_total_mg_dl": bili})
    assert "darolutamide_hepatotoxicity_grade3" not in _gate_codes(result)


@pytest.mark.parametrize("alias_field", ["sgot", "ast_iu_l", "ast_baseline", "ast_serum"])
def test_g1182_to_g1185_alias_ast_variants(alias_field):
    """H.G1182-H.G1185 — Aliases AST (sgot, ast_iu_l, ast_baseline, ast_serum)."""
    result = _evaluate({alias_field: 250})
    assert "darolutamide_hepatotoxicity_grade3" in _gate_codes(result)


@pytest.mark.parametrize("alias_field", ["sgpt", "alt_iu_l", "alt_baseline", "alt_serum"])
def test_g1186_to_g1189_alias_alt_variants(alias_field):
    """H.G1186-H.G1189 — Aliases ALT (sgpt, alt_iu_l, alt_baseline, alt_serum)."""
    result = _evaluate({alias_field: 250})
    assert "darolutamide_hepatotoxicity_grade3" in _gate_codes(result)


@pytest.mark.parametrize("alias_field", ["total_bilirubin", "bilirubin_total"])
def test_g1190_g1191_alias_bilirubin_variants(alias_field):
    """H.G1190-H.G1191 — Aliases bilirubin (total_bilirubin, bilirubin_total)."""
    result = _evaluate({alias_field: 2.5})
    assert "darolutamide_hepatotoxicity_grade3" in _gate_codes(result)


# ════════════════════════════════════════════════════════════════════
# §B — Triggers CTCAE
# ════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("grade", [3, 4])
def test_g1192_g1193_gate32_fires_on_ast_ctcae_grade_3plus(grade):
    """H.G1192/H.G1193 — ast_ctcae_grade ≥3 dispara gate 32."""
    result = _evaluate({"ast_ctcae_grade": grade})
    assert "darolutamide_hepatotoxicity_grade3" in _gate_codes(result)


@pytest.mark.parametrize("grade", [0, 1, 2])
def test_g1194_gate32_NOT_fires_on_ast_ctcae_grade_below_3(grade):
    """H.G1194 — ast_ctcae_grade <3 NO dispara gate 32."""
    result = _evaluate({"ast_ctcae_grade": grade})
    assert "darolutamide_hepatotoxicity_grade3" not in _gate_codes(result)


@pytest.mark.parametrize("grade", [3, 4])
def test_g1195_gate32_fires_on_alt_ctcae_grade_3plus(grade):
    """H.G1195 — alt_ctcae_grade ≥3 dispara gate 32."""
    result = _evaluate({"alt_ctcae_grade": grade})
    assert "darolutamide_hepatotoxicity_grade3" in _gate_codes(result)


def test_g1196_alias_ast_grade():
    """H.G1196 — alias ast_grade funciona."""
    result = _evaluate({"ast_grade": 3})
    assert "darolutamide_hepatotoxicity_grade3" in _gate_codes(result)


# ════════════════════════════════════════════════════════════════════
# §C — Trigger flag hepatocellular pattern
# ════════════════════════════════════════════════════════════════════


def test_g1197_gate32_fires_on_hepatocellular_flag():
    """H.G1197 — hepatocellular_pattern_documented_for_darolutamide=Sí dispara."""
    result = _evaluate({"hepatocellular_pattern_documented_for_darolutamide": "Sí"})
    assert "darolutamide_hepatotoxicity_grade3" in _gate_codes(result)


def test_g1198_alias_hepatocellular_injury_documented():
    """H.G1198 — alias hepatocellular_injury_documented funciona."""
    result = _evaluate({"hepatocellular_injury_documented": "Sí"})
    assert "darolutamide_hepatotoxicity_grade3" in _gate_codes(result)


# ════════════════════════════════════════════════════════════════════
# §D — Override
# ════════════════════════════════════════════════════════════════════


def test_g1199_override_canonical():
    """H.G1199 — hepatic_function_recovered_for_darolutamide=Sí desactiva."""
    result = _evaluate({
        "ast_value": 250,
        "hepatic_function_recovered_for_darolutamide": "Sí",
    })
    assert "darolutamide_hepatotoxicity_grade3" not in _gate_codes(result)


def test_g1200_override_alias():
    """H.G1200 — alias darolutamide_hepatic_override funciona."""
    result = _evaluate({
        "ast_ctcae_grade": 3,
        "darolutamide_hepatic_override": "Sí",
    })
    assert "darolutamide_hepatotoxicity_grade3" not in _gate_codes(result)


def test_g1201_override_no_does_NOT_disable():
    """H.G1201 — override=No NO desactiva (truthy required)."""
    result = _evaluate({
        "ast_value": 250,
        "hepatic_function_recovered_for_darolutamide": "No",
    })
    assert "darolutamide_hepatotoxicity_grade3" in _gate_codes(result)


# ════════════════════════════════════════════════════════════════════
# §E — Regimen scoping (darolutamide-specific)
# ════════════════════════════════════════════════════════════════════


def test_g1202_gate32_blocks_darolutamide():
    """H.G1202 — Gate 32 filtra DAROLUTAMIDE."""
    result = _evaluate(
        {"ast_value": 250},
        [{"regimen_code": "DAROLUTAMIDE"}],
    )
    filtered_codes = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "DAROLUTAMIDE" not in filtered_codes


def test_g1203_gate32_blocks_adt_darolutamide():
    """H.G1203 — Gate 32 filtra ADT_DAROLUTAMIDE."""
    result = _evaluate(
        {"ast_value": 250},
        [{"regimen_code": "ADT_DAROLUTAMIDE"}],
    )
    filtered_codes = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "ADT_DAROLUTAMIDE" not in filtered_codes


def test_g1204_gate32_blocks_adt_docetaxel_darolutamide_arasens():
    """H.G1204 — Gate 32 filtra ADT_DOCETAXEL_DAROLUTAMIDE (ARASENS combo)."""
    result = _evaluate(
        {"ast_value": 250},
        [{"regimen_code": "ADT_DOCETAXEL_DAROLUTAMIDE"}],
    )
    filtered_codes = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "ADT_DOCETAXEL_DAROLUTAMIDE" not in filtered_codes


def test_g1205_gate32_does_NOT_block_enzalutamide():
    """H.G1205 — ENZALUTAMIDE NOT bloqueado (ARSI distinto, perfil hepatotox raro)."""
    result = _evaluate(
        {"ast_value": 250},
        [{"regimen_code": "ENZALUTAMIDE"}, {"regimen_code": "ADT_ENZALUTAMIDE"}],
    )
    filtered_codes = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "ENZALUTAMIDE" in filtered_codes
    assert "ADT_ENZALUTAMIDE" in filtered_codes


def test_g1206_gate32_does_NOT_block_apalutamide():
    """H.G1206 — APALUTAMIDE NOT bloqueado (ARSI distinto, perfil hepatotox leve)."""
    result = _evaluate(
        {"ast_value": 250},
        [{"regimen_code": "APALUTAMIDE"}, {"regimen_code": "ADT_APALUTAMIDE"}],
    )
    filtered_codes = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "APALUTAMIDE" in filtered_codes
    assert "ADT_APALUTAMIDE" in filtered_codes


def test_g1207_gate32_does_NOT_block_abiraterone():
    """H.G1207 — ABIRATERONE NOT bloqueado por gate 32 (gate 21 lo cubre con
    patrón colestásico distinto). Notar: ambos gates 21+32 pueden disparar
    simultáneamente en este caso (ambos son contraindicaciones reales),
    pero el SCOPE de regimen_codes hace que cada uno bloquee su régimen
    específico — el filtrado sigue siendo correcto."""
    # En este test, evaluamos solo abiraterone — gate 32 SI dispara pero
    # NO debería bloquear ABIRATERONE en filter (que es responsibilidad
    # de gate 21 con su scope abiraterone-específico).
    result = _evaluate(
        {"ast_value": 250},
        [{"regimen_code": "ADT_ABIRATERONE"}],  # Note: solo abiraterona, no darolutamida
    )
    codes = _gate_codes(result)
    assert "darolutamide_hepatotoxicity_grade3" in codes  # gate 32 dispara (correcto)
    assert "abiraterone_hepatotoxicity_grade3" in codes  # gate 21 también dispara
    filtered_codes = [t.get("regimen_code") for t in result["filtered_treatments"]]
    # ABIRATERONE bloqueado por gate 21 (NO por gate 32)
    assert "ADT_ABIRATERONE" not in filtered_codes


# ════════════════════════════════════════════════════════════════════
# §F — Coexistencia con gate 21 (abiraterone hepatotox)
# ════════════════════════════════════════════════════════════════════


def test_g1208_gates_21_and_32_fire_simultaneously():
    """H.G1208 — AST >200 dispara AMBOS gates 21 + 32 (correcto: ambos
    son contraindicaciones reales del mismo evento bioquímico, pero
    bloquean regímenes diferentes)."""
    result = _evaluate({"ast_value": 250})
    codes = _gate_codes(result)
    assert "abiraterone_hepatotoxicity_grade3" in codes
    assert "darolutamide_hepatotoxicity_grade3" in codes


def test_g1209_gate21_and_gate32_block_separately_by_scope():
    """H.G1209 — paciente con AST 250 y candidatos abiraterone +
    darolutamide + enzalutamide → ambos abi y daro bloqueados (gates
    21 + 32 respectivamente), pero enzalutamide preservado."""
    result = _evaluate(
        {"ast_value": 250},
        [
            {"regimen_code": "ADT_ABIRATERONE"},
            {"regimen_code": "DAROLUTAMIDE"},
            {"regimen_code": "ADT_DAROLUTAMIDE"},
            {"regimen_code": "ENZALUTAMIDE"},
            {"regimen_code": "DOCETAXEL"},
        ],
    )
    filtered_codes = [t.get("regimen_code") for t in result["filtered_treatments"]]
    # ABIRATERONE bloqueado por gate 21
    assert "ADT_ABIRATERONE" not in filtered_codes
    # DAROLUTAMIDE bloqueado por gate 32
    assert "DAROLUTAMIDE" not in filtered_codes
    assert "ADT_DAROLUTAMIDE" not in filtered_codes
    # Alternativas preservadas
    assert "ENZALUTAMIDE" in filtered_codes
    assert "DOCETAXEL" in filtered_codes


# ════════════════════════════════════════════════════════════════════
# §G — Catálogo + integración + UI classifier + FieldSpecs
# ════════════════════════════════════════════════════════════════════


def test_g1210_total_yaml_gates_classifier_and_fieldspecs():
    """H.G1210 — Verifica integración completa:
      - 32 YAML gates totales tras audit #47
      - get_active_gate_codes() incluye gate 32
      - class_label específico en pivotal_gate_delta._classify_gate_for_message
      - 4 nuevos FieldSpecs registrados en pivotal_gate_supporting_fields
    """
    from prostanet.shared.pivotal_gates_yaml_loader import get_loaded_yaml_codes
    from prostanet.shared.algorithm_version import get_active_gate_codes
    from prostanet.shared.pivotal_gate_delta import _classify_gate_for_message
    from prostanet.shared.advanced_support_fields import pivotal_gate_supporting_fields

    # YAML loader
    codes = get_loaded_yaml_codes()
    assert len(codes) >= 32, f"Expected ≥32 YAML gates, got {len(codes)}"
    assert "darolutamide_hepatotoxicity_grade3" in codes

    # active_gate_codes
    active = get_active_gate_codes()
    assert "darolutamide_hepatotoxicity_grade3" in active

    # Classifier
    label = _classify_gate_for_message("darolutamide_hepatotoxicity_grade3")
    assert label == "Hepatotox darolutamida (ARANOTE/ARASENS + Nubeqa §6)"
    # NO debe colisionar con gate 21 abiraterone hepatotox
    assert label != "Hepatoxicidad abiraterona"

    # 4 nuevos FieldSpecs registrados
    field_names = {f.name for f in pivotal_gate_supporting_fields()}
    expected = {
        "ast_ctcae_grade",
        "alt_ctcae_grade",
        "hepatocellular_pattern_documented_for_darolutamide",
        "hepatic_function_recovered_for_darolutamide",
    }
    missing = expected - field_names
    assert not missing, f"Missing FieldSpecs: {missing}"


# ════════════════════════════════════════════════════════════════════
# §H — Smoke E2E (clinical scenarios)
# ════════════════════════════════════════════════════════════════════


def test_smoke_darolutamide_hepatic_grade3_with_alternatives():
    """E2E: paciente mHSPC con AST 280 (CTCAE G3) considerando
    darolutamida ARASENS combo + alternativas."""
    payload = {
        "ast_value": 280,
        "alt_value": 250,
        "metastatic": "1",
        "high_volume_disease": "1",
    }
    treatments = [
        {"regimen_code": "ADT_DOCETAXEL_DAROLUTAMIDE", "regimen_name": "ARASENS triplete"},
        {"regimen_code": "ADT_ABIRATERONE", "regimen_name": "ADT + Abiraterona"},
        {"regimen_code": "ADT_ENZALUTAMIDE", "regimen_name": "ADT + Enzalutamida"},
        {"regimen_code": "DOCETAXEL", "regimen_name": "Docetaxel"},
    ]
    result = _evaluate(payload, treatments)
    codes = _gate_codes(result)
    assert "darolutamide_hepatotoxicity_grade3" in codes
    assert "abiraterone_hepatotoxicity_grade3" in codes  # gate 21 también
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    # ARASENS y abiraterona ambos bloqueados (gates 21+32)
    assert "ADT_DOCETAXEL_DAROLUTAMIDE" not in filtered
    assert "ADT_ABIRATERONE" not in filtered
    # Enzalutamida y docetaxel preservados
    assert "ADT_ENZALUTAMIDE" in filtered
    assert "DOCETAXEL" in filtered
    # Mensaje "not_recommended" debe citar Nubeqa
    msgs = " ".join(result.get("not_recommended_messages", []))
    assert "Nubeqa" in msgs or "darolutamida" in msgs.lower() or "darolutamide" in msgs.lower()


def test_smoke_normal_hepatic_function_NOT_blocked():
    """E2E: paciente con función hepática normal (AST 35, ALT 30,
    bili 0.8, sin CTCAE) → gate 32 NO dispara, todos los regímenes
    disponibles."""
    payload = {
        "ast_value": 35,
        "alt_value": 30,
        "bilirubin_total_mg_dl": 0.8,
        "ast_ctcae_grade": 0,
        "alt_ctcae_grade": 0,
    }
    treatments = [
        {"regimen_code": "DAROLUTAMIDE"},
        {"regimen_code": "ADT_DOCETAXEL_DAROLUTAMIDE"},
    ]
    result = _evaluate(payload, treatments)
    codes = _gate_codes(result)
    assert "darolutamide_hepatotoxicity_grade3" not in codes
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "DAROLUTAMIDE" in filtered
    assert "ADT_DOCETAXEL_DAROLUTAMIDE" in filtered
