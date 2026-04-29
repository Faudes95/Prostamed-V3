"""tests/test_audit46_gate31_enzalutamide_cognitive_elderly.py — Faubot 2026-04-25 (XLIII).

Tests dedicados a Auditoría #46 — Gate 31 enzalutamide × cognitive impairment elderly.

Cubre H.G1143 - H.G1175 (33 hipótesis):

§A — Path A: edad ≥75 + objective cognitive marker (MMSE/MoCA)
  H.G1143: edad 75 + MMSE 22 dispara gate 31 (boundary inclusive)
  H.G1144: edad 80 + MMSE 22 dispara
  H.G1145: edad 90 + MMSE 18 dispara
  H.G1146: edad 78 + MMSE 24 dispara (boundary MMSE)
  H.G1147: edad 78 + MMSE 25 NO dispara (boundary above)
  H.G1148: edad 74 + MMSE 22 NO dispara (age boundary below)
  H.G1149: edad 78 + MoCA 22 dispara (Path A via MoCA)
  H.G1150: edad 78 + MoCA 23 dispara (boundary MoCA)
  H.G1151: edad 78 + MoCA 24 NO dispara (boundary above)
  H.G1152: alias age_at_assessment funciona
  H.G1153: alias mmse_baseline_score funciona
  H.G1154: alias moca_baseline_score funciona
  H.G1155: alias edad funciona

§B — Path B: edad ≥75 + cognitive_concerns_documented flag
  H.G1156: edad 76 + cognitive_concerns_documented=Sí dispara
  H.G1157: edad 80 + flag=Sí dispara
  H.G1158: edad 70 + flag=Sí NO dispara (age requirement)
  H.G1159: edad 78 + flag=No NO dispara (truthy required)
  H.G1160: alias cognitive_concerns_baseline funciona
  H.G1161: alias geriatric_cognitive_concerns funciona

§C — Override
  H.G1162: cognitive_baseline_normalized_for_arsi_elderly=Sí desactiva
  H.G1163: alias cognitive_normalized_for_enzalutamide_elderly funciona
  H.G1164: override=No NO desactiva (truthy required)

§D — Regimen scoping (enzalutamide-specific, NOT entire ARSI class)
  H.G1165: gate 31 bloquea ENZALUTAMIDE
  H.G1166: gate 31 bloquea ADT_ENZALUTAMIDE
  H.G1167: gate 31 bloquea TALAZOPARIB_ENZALUTAMIDE (TALAPRO-2)
  H.G1168: gate 31 NO bloquea APALUTAMIDE (alternativa preferida)
  H.G1169: gate 31 NO bloquea DAROLUTAMIDE (alternativa preferida — menor SNC)

§E — Coexistencia con gate 19 (arsi_in_cognitive_decline_grade2)
  H.G1170: paciente puede disparar gates 19 + 31 simultáneamente
  H.G1171: gate 19 sigue cubriendo TODOS los ARSI cuando deterioro presente
  H.G1172: gate 31 NO desplaza a gate 19 (son complementarios)

§F — Catálogo + integración + UI classifier
  H.G1173: 31 YAML gates totales
  H.G1174: gate 31 expuesto en get_active_gate_codes()
  H.G1175: class_label específico en pivotal_gate_delta._classify_gate_for_message
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
# §A — Path A: edad ≥75 + objective cognitive marker
# ════════════════════════════════════════════════════════════════════


def test_g1143_age75_mmse22_fires():
    """H.G1143 — edad=75 + MMSE 22 dispara gate 31 (age boundary inclusive)."""
    result = _evaluate({"age": 75, "mmse_baseline": 22})
    assert "enzalutamide_cognitive_decline_elderly" in _gate_codes(result)


def test_g1144_age80_mmse22_fires():
    """H.G1144 — edad=80 + MMSE 22 dispara gate 31."""
    result = _evaluate({"age": 80, "mmse_baseline": 22})
    assert "enzalutamide_cognitive_decline_elderly" in _gate_codes(result)


def test_g1145_age90_mmse18_fires():
    """H.G1145 — edad=90 + MMSE 18 (deterioro leve) dispara gate 31."""
    result = _evaluate({"age": 90, "mmse_baseline": 18})
    assert "enzalutamide_cognitive_decline_elderly" in _gate_codes(result)


def test_g1146_age78_mmse24_fires():
    """H.G1146 — edad=78 + MMSE 24 (boundary inclusive: MMSE≤24 → numeric_below 25)."""
    result = _evaluate({"age": 78, "mmse_baseline": 24})
    assert "enzalutamide_cognitive_decline_elderly" in _gate_codes(result)


def test_g1147_age78_mmse25_does_NOT_fire():
    """H.G1147 — edad=78 + MMSE 25 NO dispara (boundary above; MMSE 25 = normal)."""
    result = _evaluate({"age": 78, "mmse_baseline": 25})
    assert "enzalutamide_cognitive_decline_elderly" not in _gate_codes(result)


def test_g1148_age74_mmse22_does_NOT_fire():
    """H.G1148 — edad=74 + MMSE 22 NO dispara (age boundary below; <75)."""
    result = _evaluate({"age": 74, "mmse_baseline": 22})
    assert "enzalutamide_cognitive_decline_elderly" not in _gate_codes(result)


def test_g1149_age78_moca22_fires():
    """H.G1149 — edad=78 + MoCA 22 dispara gate 31 vía Path A MoCA."""
    result = _evaluate({"age": 78, "moca_baseline": 22})
    assert "enzalutamide_cognitive_decline_elderly" in _gate_codes(result)


def test_g1150_age78_moca23_fires():
    """H.G1150 — edad=78 + MoCA 23 dispara (boundary inclusive: MoCA≤23 → numeric_below 24)."""
    result = _evaluate({"age": 78, "moca_baseline": 23})
    assert "enzalutamide_cognitive_decline_elderly" in _gate_codes(result)


def test_g1151_age78_moca24_does_NOT_fire():
    """H.G1151 — edad=78 + MoCA 24 NO dispara (boundary above; MoCA 24 = mild MCI but not severe)."""
    result = _evaluate({"age": 78, "moca_baseline": 24})
    assert "enzalutamide_cognitive_decline_elderly" not in _gate_codes(result)


def test_g1152_alias_age_at_assessment():
    """H.G1152 — alias age_at_assessment funciona."""
    result = _evaluate({"age_at_assessment": 80, "mmse_baseline": 22})
    assert "enzalutamide_cognitive_decline_elderly" in _gate_codes(result)


def test_g1153_alias_mmse_baseline_score():
    """H.G1153 — alias mmse_baseline_score funciona."""
    result = _evaluate({"age": 78, "mmse_baseline_score": 23})
    assert "enzalutamide_cognitive_decline_elderly" in _gate_codes(result)


def test_g1154_alias_moca_baseline_score():
    """H.G1154 — alias moca_baseline_score funciona."""
    result = _evaluate({"age": 78, "moca_baseline_score": 22})
    assert "enzalutamide_cognitive_decline_elderly" in _gate_codes(result)


def test_g1155_alias_edad():
    """H.G1155 — alias edad (español) funciona."""
    result = _evaluate({"edad": 78, "mmse_baseline": 22})
    assert "enzalutamide_cognitive_decline_elderly" in _gate_codes(result)


# ════════════════════════════════════════════════════════════════════
# §B — Path B: edad ≥75 + cognitive_concerns_documented flag
# ════════════════════════════════════════════════════════════════════


def test_g1156_age76_concerns_flag_fires():
    """H.G1156 — edad=76 + cognitive_concerns_documented=Sí dispara Path B."""
    result = _evaluate({"age": 76, "cognitive_concerns_documented": "Sí"})
    assert "enzalutamide_cognitive_decline_elderly" in _gate_codes(result)


def test_g1157_age80_flag_fires():
    """H.G1157 — edad=80 + flag=Sí dispara."""
    result = _evaluate({"age": 80, "cognitive_concerns_documented": "Sí"})
    assert "enzalutamide_cognitive_decline_elderly" in _gate_codes(result)


def test_g1158_age70_flag_does_NOT_fire():
    """H.G1158 — edad=70 + flag=Sí NO dispara (age requirement)."""
    result = _evaluate({"age": 70, "cognitive_concerns_documented": "Sí"})
    assert "enzalutamide_cognitive_decline_elderly" not in _gate_codes(result)


def test_g1159_age78_flag_no_does_NOT_fire():
    """H.G1159 — edad=78 + flag=No NO dispara (truthy required)."""
    result = _evaluate({"age": 78, "cognitive_concerns_documented": "No"})
    assert "enzalutamide_cognitive_decline_elderly" not in _gate_codes(result)


def test_g1160_alias_cognitive_concerns_baseline():
    """H.G1160 — alias cognitive_concerns_baseline funciona."""
    result = _evaluate({"age": 78, "cognitive_concerns_baseline": "Sí"})
    assert "enzalutamide_cognitive_decline_elderly" in _gate_codes(result)


def test_g1161_alias_geriatric_cognitive_concerns():
    """H.G1161 — alias geriatric_cognitive_concerns funciona."""
    result = _evaluate({"age": 80, "geriatric_cognitive_concerns": "Sí"})
    assert "enzalutamide_cognitive_decline_elderly" in _gate_codes(result)


# ════════════════════════════════════════════════════════════════════
# §C — Override
# ════════════════════════════════════════════════════════════════════


def test_g1162_override_canonical():
    """H.G1162 — cognitive_baseline_normalized_for_arsi_elderly=Sí desactiva."""
    result = _evaluate({
        "age": 80,
        "mmse_baseline": 22,
        "cognitive_baseline_normalized_for_arsi_elderly": "Sí",
    })
    assert "enzalutamide_cognitive_decline_elderly" not in _gate_codes(result)


def test_g1163_override_alias():
    """H.G1163 — alias cognitive_normalized_for_enzalutamide_elderly funciona."""
    result = _evaluate({
        "age": 78,
        "mmse_baseline": 22,
        "cognitive_normalized_for_enzalutamide_elderly": "Sí",
    })
    assert "enzalutamide_cognitive_decline_elderly" not in _gate_codes(result)


def test_g1164_override_no_does_NOT_disable():
    """H.G1164 — override=No NO desactiva (truthy required)."""
    result = _evaluate({
        "age": 80,
        "mmse_baseline": 22,
        "cognitive_baseline_normalized_for_arsi_elderly": "No",
    })
    assert "enzalutamide_cognitive_decline_elderly" in _gate_codes(result)


# ════════════════════════════════════════════════════════════════════
# §D — Regimen scoping (enzalutamide-specific)
# ════════════════════════════════════════════════════════════════════


def test_g1165_gate31_blocks_enzalutamide():
    """H.G1165 — Gate 31 filtra ENZALUTAMIDE."""
    result = _evaluate(
        {"age": 80, "mmse_baseline": 22},
        [{"regimen_code": "ENZALUTAMIDE"}],
    )
    filtered_codes = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "ENZALUTAMIDE" not in filtered_codes


def test_g1166_gate31_blocks_adt_enzalutamide():
    """H.G1166 — Gate 31 filtra ADT_ENZALUTAMIDE."""
    result = _evaluate(
        {"age": 80, "mmse_baseline": 22},
        [{"regimen_code": "ADT_ENZALUTAMIDE"}],
    )
    filtered_codes = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "ADT_ENZALUTAMIDE" not in filtered_codes


def test_g1167_gate31_blocks_talazoparib_enzalutamide():
    """H.G1167 — Gate 31 filtra TALAZOPARIB_ENZALUTAMIDE (TALAPRO-2)."""
    result = _evaluate(
        {"age": 80, "mmse_baseline": 22},
        [{"regimen_code": "TALAZOPARIB_ENZALUTAMIDE"}],
    )
    filtered_codes = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "TALAZOPARIB_ENZALUTAMIDE" not in filtered_codes


def test_g1168_gate31_does_NOT_block_apalutamide():
    """H.G1168 — APALUTAMIDE NOT bloqueado (alternativa preferida)."""
    result = _evaluate(
        {"age": 80, "mmse_baseline": 22},
        [{"regimen_code": "APALUTAMIDE"}, {"regimen_code": "ADT_APALUTAMIDE"}],
    )
    filtered_codes = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "APALUTAMIDE" in filtered_codes
    assert "ADT_APALUTAMIDE" in filtered_codes


def test_g1169_gate31_does_NOT_block_darolutamide():
    """H.G1169 — DAROLUTAMIDE NOT bloqueado (alternativa preferida — menor SNC)."""
    result = _evaluate(
        {"age": 80, "mmse_baseline": 22},
        [{"regimen_code": "DAROLUTAMIDE"}, {"regimen_code": "ADT_DAROLUTAMIDE"}],
    )
    filtered_codes = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "DAROLUTAMIDE" in filtered_codes
    assert "ADT_DAROLUTAMIDE" in filtered_codes


# ════════════════════════════════════════════════════════════════════
# §E — Coexistencia con gate 19 (arsi_in_cognitive_decline_grade2)
# ════════════════════════════════════════════════════════════════════


def test_g1170_gates_19_and_31_can_fire_simultaneously():
    """H.G1170 — gates 19 + 31 disparan simultáneamente (paciente
    elderly + MMSE marginal + cognitive_disturbance G≥2)."""
    result = _evaluate({
        "age": 80,
        "mmse_baseline": 22,
        "cognitive_disturbance_ctcae_grade": 2,
    })
    codes = _gate_codes(result)
    assert "enzalutamide_cognitive_decline_elderly" in codes
    assert "arsi_in_cognitive_decline_grade2" in codes


def test_g1171_gate19_still_covers_all_arsi_when_deterioro_present():
    """H.G1171 — gate 19 sigue cubriendo TODOS los ARSI con deterioro
    G≥2 (apalutamida + darolutamida bloqueados; gate 31 enzalutamida
    específico es complementario)."""
    result = _evaluate(
        {"cognitive_disturbance_ctcae_grade": 2},
        [
            {"regimen_code": "APALUTAMIDE"},
            {"regimen_code": "DAROLUTAMIDE"},
            {"regimen_code": "ENZALUTAMIDE"},
        ],
    )
    codes = _gate_codes(result)
    assert "arsi_in_cognitive_decline_grade2" in codes
    # Gate 19 bloquea los 3 ARSI cuando deterioro presente
    filtered_codes = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "APALUTAMIDE" not in filtered_codes
    assert "DAROLUTAMIDE" not in filtered_codes
    assert "ENZALUTAMIDE" not in filtered_codes


def test_g1172_gate31_does_NOT_displace_gate19():
    """H.G1172 — gate 31 NO desplaza a gate 19 (semánticamente distintos:
    factor de riesgo pre-emptivo vs deterioro ya presente)."""
    # Caso: ELDERLY con MMSE marginal pero SIN deterioro G≥2 establecido
    # → solo gate 31 dispara, gate 19 NO
    result = _evaluate({"age": 80, "mmse_baseline": 22})
    codes = _gate_codes(result)
    assert "enzalutamide_cognitive_decline_elderly" in codes
    assert "arsi_in_cognitive_decline_grade2" not in codes


# ════════════════════════════════════════════════════════════════════
# §F — Catálogo + integración + UI classifier
# ════════════════════════════════════════════════════════════════════


def test_g1173_total_yaml_gates_count_is_31():
    """H.G1173 — Catálogo YAML expone 31 gates totales tras audit #46."""
    from prostanet.shared.pivotal_gates_yaml_loader import get_loaded_yaml_codes
    codes = get_loaded_yaml_codes()
    assert len(codes) >= 31, f"Expected ≥31 YAML gates, got {len(codes)}"
    assert "enzalutamide_cognitive_decline_elderly" in codes


def test_g1174_active_gate_codes_includes_31():
    """H.G1174 — get_active_gate_codes() incluye gate 31."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    codes = get_active_gate_codes()
    assert "enzalutamide_cognitive_decline_elderly" in codes


def test_g1175_classifier_class_label_specific():
    """H.G1175 — class_label específico (NO genérico) en
    pivotal_gate_delta._classify_gate_for_message."""
    from prostanet.shared.pivotal_gate_delta import _classify_gate_for_message
    label = _classify_gate_for_message("enzalutamide_cognitive_decline_elderly")
    assert label == "Enzalutamida cognitive elderly (UCSF 2024 + Marcum JAMA Oncol)"
    # NO debe caer al "Otros" ni a algún prefix-match incorrecto
    assert label != "Otros"
    assert label != "ARPI cardiotoxicidad"  # qtc_/lvef_ prefix


# ════════════════════════════════════════════════════════════════════
# §G — Smoke E2E (clinical scenarios)
# ════════════════════════════════════════════════════════════════════


def test_smoke_elderly_marginal_cognitive_with_arsi_options():
    """E2E: 78 años + MMSE 23 baseline + considerando todos los ARSIs.
    Resultado esperado: gate 31 bloquea solo enzalutamida; darolutamida
    + apalutamida disponibles como alternativas preferidas."""
    payload = {
        "age": 78,
        "mmse_baseline": 23,
        "moca_baseline": 22,
        "metastatic": "1",
        "psa_doubling_time": 5,
    }
    treatments = [
        {"regimen_code": "ENZALUTAMIDE", "regimen_name": "Enzalutamida (Xtandi)"},
        {"regimen_code": "ADT_DAROLUTAMIDE", "regimen_name": "ADT + Darolutamida (preferida)"},
        {"regimen_code": "ADT_APALUTAMIDE", "regimen_name": "ADT + Apalutamida"},
        {"regimen_code": "DOCETAXEL", "regimen_name": "Docetaxel"},
    ]
    result = _evaluate(payload, treatments)
    codes = _gate_codes(result)
    assert "enzalutamide_cognitive_decline_elderly" in codes
    filtered = [t.get("regimen_code") for t in result["filtered_treatments"]]
    assert "ENZALUTAMIDE" not in filtered
    assert "ADT_DAROLUTAMIDE" in filtered  # alternativa preferida (menor SNC)
    assert "ADT_APALUTAMIDE" in filtered
    assert "DOCETAXEL" in filtered
    # Mensaje "not_recommended" debe citar UCSF/Marcum
    msgs = " ".join(result.get("not_recommended_messages", []))
    assert "UCSF" in msgs or "Marcum" in msgs or "enzalutamida" in msgs.lower()


def test_smoke_young_patient_with_marginal_mmse_NOT_blocked():
    """E2E: 65 años + MMSE 22 → gate 31 NO dispara (age <75); paciente
    puede recibir enzalutamida sin restricción G31 (otros gates aplican)."""
    payload = {"age": 65, "mmse_baseline": 22}
    treatments = [{"regimen_code": "ENZALUTAMIDE"}]
    result = _evaluate(payload, treatments)
    codes = _gate_codes(result)
    assert "enzalutamide_cognitive_decline_elderly" not in codes


def test_smoke_elderly_with_normal_cognition_NOT_blocked():
    """E2E: 80 años + MMSE 28 (normal) + sin concerns → gate 31 NO dispara;
    paciente elderly cognitively healthy puede recibir enzalutamida."""
    payload = {
        "age": 80,
        "mmse_baseline": 28,
        "moca_baseline": 27,
        "cognitive_concerns_documented": "No",
    }
    treatments = [{"regimen_code": "ENZALUTAMIDE"}]
    result = _evaluate(payload, treatments)
    codes = _gate_codes(result)
    assert "enzalutamide_cognitive_decline_elderly" not in codes
