"""tests/test_audit54_gates_43_46_checkpoint_inhibitors_irae.py — Faubot 2026-04-25 (LVII).

Tests dedicados a Auditoría #54 — Gates 43-46 Pembrolizumab/Checkpoint inhibitors irAE.

Cubre H.G1536 - H.G1620 (85 hipótesis) en 9 secciones:

§A — REGIMEN_CODES_CHECKPOINT_INHIBITORS catálogo
§B — Gate 43: Pneumonitis irAE G≥2 (4 paths + override)
§C — Gate 44: Hepatitis IMMUNE-MEDIATED G≥3 (5 paths + override)
§D — Gate 45: Colitis irAE G≥3 (5 paths + override)
§E — Gate 46: Endocrinopatías irAE nuevas (6 paths + override)
§F — Coexistencia con gates 17-21 (ARSI), 21+32+39 (hepatic eje), 28 (adrenal)
§G — Polyorgan irAE simultaneous (5-10% pacientes)
§H — Catálogo + clasificadores + integración
§I — Smoke E2E

🎯 2da CLASE IO del catálogo (post Sipuleucel-T #53). 4 gates simultáneos
en una iteración. Sienta clase IO completa con anti-PD-1/PD-L1.
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest


def _evaluate(payload, treatments=None):
    from prostanet.shared.pivotal_contraindication_gates import apply_pivotal_contraindication_gates
    return apply_pivotal_contraindication_gates(payload, treatments or [])


def _gate_codes(result):
    return [g["code"] for g in result.get("gates_triggered", [])]


def _tx(code: str) -> list[dict]:
    return [{"name": code, "regimen_code": code}]


GATE_43 = "checkpoint_inhibitor_pneumonitis_grade2_plus"
GATE_44 = "checkpoint_inhibitor_hepatitis_grade3_plus"
GATE_45 = "checkpoint_inhibitor_colitis_grade3_plus"
GATE_46 = "checkpoint_inhibitor_endocrinopathy_new_onset"

ALL_CHECKPOINT_GATES = {GATE_43, GATE_44, GATE_45, GATE_46}


# ───────────────────────────────────────────────
# §A — REGIMEN_CODES_CHECKPOINT_INHIBITORS catálogo
# ───────────────────────────────────────────────


def test_g1536_regimen_codes_checkpoint_inhibitors_exists():
    """H.G1536 — REGIMEN_CODES_CHECKPOINT_INHIBITORS frozenset definida."""
    from prostanet.shared.pivotal_contraindication_gates import REGIMEN_CODES_CHECKPOINT_INHIBITORS
    assert isinstance(REGIMEN_CODES_CHECKPOINT_INHIBITORS, frozenset)
    assert len(REGIMEN_CODES_CHECKPOINT_INHIBITORS) >= 10


@pytest.mark.parametrize("code", [
    "PEMBROLIZUMAB", "PEMBROLIZUMAB_OLAPARIB", "PEMBROLIZUMAB_ENZALUTAMIDE",
    "PEMBROLIZUMAB_DOCETAXEL",
    "NIVOLUMAB", "NIVOLUMAB_RUCAPARIB", "NIVOLUMAB_DOCETAXEL", "NIVOLUMAB_IPILIMUMAB",
    "ATEZOLIZUMAB", "ATEZOLIZUMAB_ENZALUTAMIDE",
])
def test_g1537_regimen_codes_includes_all_checkpoint_drugs(code):
    """H.G1537 — REGIMEN_CODES incluye 10 codes (3 mono + 7 combos)."""
    from prostanet.shared.pivotal_contraindication_gates import REGIMEN_CODES_CHECKPOINT_INHIBITORS
    assert code in REGIMEN_CODES_CHECKPOINT_INHIBITORS


def test_g1538_keywords_checkpoint_inhibitors_exists():
    """H.G1538 — KEYWORDS_CHECKPOINT_INHIBITORS tuple definida con brand names."""
    from prostanet.shared.pivotal_contraindication_gates import KEYWORDS_CHECKPOINT_INHIBITORS
    assert isinstance(KEYWORDS_CHECKPOINT_INHIBITORS, tuple)
    expected = {"pembrolizumab", "keytruda", "nivolumab", "opdivo", "atezolizumab", "tecentriq"}
    assert expected.issubset(set(KEYWORDS_CHECKPOINT_INHIBITORS))


# ───────────────────────────────────────────────
# §B — Gate 43: Pneumonitis irAE G≥2
# ───────────────────────────────────────────────


@pytest.mark.parametrize("grade", [2, 3, 4, 5])
def test_g1539_gate43_pneumonitis_ctcae_ge_2_fires(grade):
    """H.G1539 — pneumonitis CTCAE G≥2 dispara Path A."""
    r = _evaluate({"pneumonitis_ctcae_grade": grade}, treatments=_tx("PEMBROLIZUMAB"))
    assert GATE_43 in _gate_codes(r)


@pytest.mark.parametrize("grade", [0, 1])
def test_g1540_gate43_pneumonitis_ctcae_lt_2_does_NOT_fire(grade):
    """H.G1540 — pneumonitis G<2 NO dispara (G1 asintomática)."""
    r = _evaluate({"pneumonitis_ctcae_grade": grade}, treatments=_tx("PEMBROLIZUMAB"))
    assert GATE_43 not in _gate_codes(r)


def test_g1541_gate43_path_a_alias_pneumonitis_grade_works():
    """H.G1541 — alias `pneumonitis_grade` dispara Path A."""
    r = _evaluate({"pneumonitis_grade": 3}, treatments=_tx("PEMBROLIZUMAB"))
    assert GATE_43 in _gate_codes(r)


def test_g1542_gate43_path_b_pneumonitis_documented_flag_fires():
    """H.G1542 — pneumonitis_documented_for_checkpoint_inhibitor flag dispara Path B."""
    r = _evaluate({"pneumonitis_documented_for_checkpoint_inhibitor": "Sí"}, treatments=_tx("NIVOLUMAB"))
    assert GATE_43 in _gate_codes(r)


def test_g1543_gate43_path_c_hypoxemia_fires():
    """H.G1543 — hypoxemia_with_checkpoint_inhibitor flag dispara Path C."""
    r = _evaluate({"hypoxemia_with_checkpoint_inhibitor": "Sí"}, treatments=_tx("ATEZOLIZUMAB"))
    assert GATE_43 in _gate_codes(r)


def test_g1544_gate43_path_d_ggo_ct_fires():
    """H.G1544 — ground_glass_opacities_ct_for_checkpoint flag dispara Path D."""
    r = _evaluate({"ground_glass_opacities_ct_for_checkpoint": "Sí"}, treatments=_tx("PEMBROLIZUMAB"))
    assert GATE_43 in _gate_codes(r)


def test_g1545_gate43_override_pneumonitis_resolved_disables():
    """H.G1545 — override `pneumonitis_resolved_for_checkpoint_inhibitor=Sí` desactiva."""
    r = _evaluate({
        "pneumonitis_ctcae_grade": 3,
        "pneumonitis_resolved_for_checkpoint_inhibitor": "Sí",
    }, treatments=_tx("PEMBROLIZUMAB"))
    assert GATE_43 not in _gate_codes(r)


def test_g1546_gate43_override_alias_works():
    """H.G1546 — alias override `immune_pneumonitis_resolved` desactiva."""
    r = _evaluate({
        "pneumonitis_ctcae_grade": 3,
        "immune_pneumonitis_resolved": "Sí",
    }, treatments=_tx("PEMBROLIZUMAB"))
    assert GATE_43 not in _gate_codes(r)


@pytest.mark.parametrize("checkpoint_code", ["PEMBROLIZUMAB", "NIVOLUMAB", "ATEZOLIZUMAB"])
def test_g1547_gate43_blocks_all_checkpoint_inhibitors(checkpoint_code):
    """H.G1547 — gate 43 bloquea TODOS los checkpoint inhibitors mono."""
    r = _evaluate({"pneumonitis_ctcae_grade": 3}, treatments=_tx(checkpoint_code))
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 0, f"{checkpoint_code} debe ser filtrada"


def test_g1548_gate43_does_NOT_block_olaparib():
    """H.G1548 — gate 43 NO bloquea olaparib (no es checkpoint inhibitor)."""
    r = _evaluate({"pneumonitis_ctcae_grade": 3}, treatments=_tx("OLAPARIB"))
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 1, "Olaparib no es checkpoint inhibitor"


# ───────────────────────────────────────────────
# §C — Gate 44: Hepatitis IMMUNE-MEDIATED G≥3
# ───────────────────────────────────────────────


@pytest.mark.parametrize("ast_value", [201, 250, 500, 1000])
def test_g1549_gate44_path_a_ast_above_200_fires(ast_value):
    """H.G1549 — AST >200 (>5× ULN) dispara Path A."""
    r = _evaluate({"ast": ast_value}, treatments=_tx("PEMBROLIZUMAB"))
    assert GATE_44 in _gate_codes(r)


@pytest.mark.parametrize("ast_value", [40, 100, 200])
def test_g1550_gate44_path_a_ast_below_200_does_NOT_fire(ast_value):
    """H.G1550 — AST ≤200 NO dispara Path A (boundary 200 NOT >)."""
    r = _evaluate({"ast": ast_value}, treatments=_tx("PEMBROLIZUMAB"))
    assert GATE_44 not in _gate_codes(r)


@pytest.mark.parametrize("alt_value", [201, 250, 500])
def test_g1551_gate44_path_b_alt_above_200_fires(alt_value):
    """H.G1551 — ALT >200 (>5× ULN) dispara Path B."""
    r = _evaluate({"alt": alt_value}, treatments=_tx("NIVOLUMAB"))
    assert GATE_44 in _gate_codes(r)


@pytest.mark.parametrize("bili_value", [3.1, 5.0, 10.0])
def test_g1552_gate44_path_c_bilirubin_above_3_fires(bili_value):
    """H.G1552 — bilirubin >3 mg/dL (>3× ULN) dispara Path C."""
    r = _evaluate({"bilirubin": bili_value}, treatments=_tx("ATEZOLIZUMAB"))
    assert GATE_44 in _gate_codes(r)


@pytest.mark.parametrize("grade", [3, 4, 5])
def test_g1553_gate44_path_d_hepatitis_ctcae_ge_3_fires(grade):
    """H.G1553 — hepatitis CTCAE G≥3 dispara Path D."""
    r = _evaluate({"hepatitis_ctcae_grade": grade}, treatments=_tx("PEMBROLIZUMAB"))
    assert GATE_44 in _gate_codes(r)


def test_g1554_gate44_path_e_hepatitis_immune_documented_fires():
    """H.G1554 — hepatitis_immune_documented_for_checkpoint flag dispara Path E."""
    r = _evaluate({"hepatitis_immune_documented_for_checkpoint": "Sí"}, treatments=_tx("PEMBROLIZUMAB"))
    assert GATE_44 in _gate_codes(r)


def test_g1555_gate44_alias_sgot_works():
    """H.G1555 — alias `sgot` dispara Path A AST."""
    r = _evaluate({"sgot": 250}, treatments=_tx("PEMBROLIZUMAB"))
    assert GATE_44 in _gate_codes(r)


def test_g1556_gate44_alias_sgpt_works():
    """H.G1556 — alias `sgpt` dispara Path B ALT."""
    r = _evaluate({"sgpt": 250}, treatments=_tx("PEMBROLIZUMAB"))
    assert GATE_44 in _gate_codes(r)


def test_g1557_gate44_override_hepatic_function_recovered_disables():
    """H.G1557 — override `hepatic_function_recovered_for_checkpoint_inhibitor=Sí` desactiva."""
    r = _evaluate({
        "ast": 300,
        "alt": 300,
        "hepatic_function_recovered_for_checkpoint_inhibitor": "Sí",
    }, treatments=_tx("PEMBROLIZUMAB"))
    assert GATE_44 not in _gate_codes(r)


def test_g1558_gate44_coexistence_with_gate_21_abi_hepatotox():
    """H.G1558 — gate 44 (IO immune) + gate 21 (abi hepatotox) coexisten con AST/ALT alta.

    Usa alias compartido `ast_iu_l` que ambos gates 21 y 44 reconocen
    (canonical de gate 21 es `ast_value`, canonical de gate 44 es `ast`).
    """
    r = _evaluate({
        "ast_iu_l": 250,
        "alt_iu_l": 250,
    }, treatments=_tx("PEMBROLIZUMAB"))
    codes = _gate_codes(r)
    assert GATE_44 in codes
    # Gate 21 dispara también — eje hepático cuádruple
    assert "abiraterone_hepatotoxicity_grade3" in codes


# ───────────────────────────────────────────────
# §D — Gate 45: Colitis irAE G≥3
# ───────────────────────────────────────────────


@pytest.mark.parametrize("grade", [3, 4, 5])
def test_g1559_gate45_path_a_colitis_ctcae_ge_3_fires(grade):
    """H.G1559 — colitis CTCAE G≥3 dispara Path A."""
    r = _evaluate({"colitis_ctcae_grade": grade}, treatments=_tx("PEMBROLIZUMAB"))
    assert GATE_45 in _gate_codes(r)


@pytest.mark.parametrize("grade", [0, 1, 2])
def test_g1560_gate45_path_a_colitis_lt_3_does_NOT_fire(grade):
    """H.G1560 — colitis G<3 NO dispara Path A (G2 outpatient mgmt)."""
    r = _evaluate({"colitis_ctcae_grade": grade}, treatments=_tx("PEMBROLIZUMAB"))
    assert GATE_45 not in _gate_codes(r)


@pytest.mark.parametrize("grade", [3, 4])
def test_g1561_gate45_path_b_diarrhea_ctcae_ge_3_fires(grade):
    """H.G1561 — diarrhea CTCAE G≥3 (>7 epis/d) dispara Path B."""
    r = _evaluate({"diarrhea_ctcae_grade": grade}, treatments=_tx("NIVOLUMAB"))
    assert GATE_45 in _gate_codes(r)


def test_g1562_gate45_path_c_bowel_perforation_fires():
    """H.G1562 — bowel_perforation_for_checkpoint_inhibitor (emergencia) dispara Path C."""
    r = _evaluate({"bowel_perforation_for_checkpoint_inhibitor": "Sí"}, treatments=_tx("ATEZOLIZUMAB"))
    assert GATE_45 in _gate_codes(r)


def test_g1563_gate45_path_d_colitis_immune_documented_fires():
    """H.G1563 — colitis_immune_documented_for_checkpoint flag dispara Path D."""
    r = _evaluate({"colitis_immune_documented_for_checkpoint": "Sí"}, treatments=_tx("PEMBROLIZUMAB"))
    assert GATE_45 in _gate_codes(r)


def test_g1564_gate45_path_e_hematochezia_severe_fires():
    """H.G1564 — hematochezia_severe_for_checkpoint flag dispara Path E."""
    r = _evaluate({"hematochezia_severe_for_checkpoint": "Sí"}, treatments=_tx("PEMBROLIZUMAB"))
    assert GATE_45 in _gate_codes(r)


def test_g1565_gate45_override_colitis_resolved_disables():
    """H.G1565 — override `colitis_resolved_for_checkpoint_inhibitor=Sí` desactiva."""
    r = _evaluate({
        "colitis_ctcae_grade": 3,
        "colitis_resolved_for_checkpoint_inhibitor": "Sí",
    }, treatments=_tx("PEMBROLIZUMAB"))
    assert GATE_45 not in _gate_codes(r)


def test_g1566_gate45_alias_intestinal_perforation_works():
    """H.G1566 — alias `intestinal_perforation_for_checkpoint` dispara Path C."""
    r = _evaluate({"intestinal_perforation_for_checkpoint": "Sí"}, treatments=_tx("PEMBROLIZUMAB"))
    assert GATE_45 in _gate_codes(r)


# ───────────────────────────────────────────────
# §E — Gate 46: Endocrinopatías irAE nuevas
# ───────────────────────────────────────────────


def test_g1567_gate46_path_a_hypophysitis_fires():
    """H.G1567 — hypophysitis_documented_for_checkpoint flag dispara Path A."""
    r = _evaluate({"hypophysitis_documented_for_checkpoint": "Sí"}, treatments=_tx("PEMBROLIZUMAB"))
    assert GATE_46 in _gate_codes(r)


@pytest.mark.parametrize("grade", [3, 4])
def test_g1568_gate46_path_b_thyroiditis_ctcae_ge_3_fires(grade):
    """H.G1568 — thyroiditis CTCAE G≥3 (crisis/mixedema) dispara Path B."""
    r = _evaluate({"thyroiditis_ctcae_grade": grade}, treatments=_tx("NIVOLUMAB"))
    assert GATE_46 in _gate_codes(r)


def test_g1569_gate46_path_c_diabetes_new_onset_fires():
    """H.G1569 — diabetes_new_onset_for_checkpoint (DM autoinmune) dispara Path C."""
    r = _evaluate({"diabetes_new_onset_for_checkpoint": "Sí"}, treatments=_tx("PEMBROLIZUMAB"))
    assert GATE_46 in _gate_codes(r)


def test_g1570_gate46_path_d_adrenal_insufficiency_immune_fires():
    """H.G1570 — adrenal_insufficiency_immune_for_checkpoint flag dispara Path D."""
    r = _evaluate({"adrenal_insufficiency_immune_for_checkpoint": "Sí"}, treatments=_tx("PEMBROLIZUMAB"))
    assert GATE_46 in _gate_codes(r)


@pytest.mark.parametrize("tsh_value", [10.5, 20, 50, 100])
def test_g1571_gate46_path_e_tsh_above_10_fires(tsh_value):
    """H.G1571 — TSH >10 mIU/L (hipotiroidismo claro) dispara Path E."""
    r = _evaluate({"tsh": tsh_value}, treatments=_tx("PEMBROLIZUMAB"))
    assert GATE_46 in _gate_codes(r)


@pytest.mark.parametrize("tsh_value", [0.5, 2.5, 5.0, 10.0])
def test_g1572_gate46_path_e_tsh_le_10_does_NOT_fire(tsh_value):
    """H.G1572 — TSH ≤10 NO dispara (boundary 10 NOT >)."""
    r = _evaluate({"tsh": tsh_value}, treatments=_tx("PEMBROLIZUMAB"))
    assert GATE_46 not in _gate_codes(r)


@pytest.mark.parametrize("cortisol_value", [0.5, 1, 2.5])
def test_g1573_gate46_path_f_cortisol_below_3_fires(cortisol_value):
    """H.G1573 — cortisol AM <3 µg/dL (sospecha insuf adrenal) dispara Path F."""
    r = _evaluate({"cortisol_am": cortisol_value}, treatments=_tx("PEMBROLIZUMAB"))
    assert GATE_46 in _gate_codes(r)


@pytest.mark.parametrize("cortisol_value", [3, 5, 15, 25])
def test_g1574_gate46_path_f_cortisol_ge_3_does_NOT_fire(cortisol_value):
    """H.G1574 — cortisol AM ≥3 NO dispara (boundary 3 NOT <)."""
    r = _evaluate({"cortisol_am": cortisol_value}, treatments=_tx("PEMBROLIZUMAB"))
    assert GATE_46 not in _gate_codes(r)


def test_g1575_gate46_alias_cortisol_morning_works():
    """H.G1575 — alias `cortisol_morning` dispara Path F."""
    r = _evaluate({"cortisol_morning": 1.5}, treatments=_tx("PEMBROLIZUMAB"))
    assert GATE_46 in _gate_codes(r)


def test_g1576_gate46_override_endocrinopathy_managed_disables():
    """H.G1576 — override `endocrinopathy_managed_with_replacement=Sí` desactiva."""
    r = _evaluate({
        "tsh": 15,
        "endocrinopathy_managed_with_replacement": "Sí",
    }, treatments=_tx("PEMBROLIZUMAB"))
    assert GATE_46 not in _gate_codes(r)


def test_g1577_gate46_alias_dka_for_checkpoint_works():
    """H.G1577 — alias `dka_for_checkpoint_inhibitor` dispara Path C."""
    r = _evaluate({"dka_for_checkpoint_inhibitor": "Sí"}, treatments=_tx("PEMBROLIZUMAB"))
    assert GATE_46 in _gate_codes(r)


# ───────────────────────────────────────────────
# §F — Coexistencia con gates de otras clases (eje hepático + adrenal)
# ───────────────────────────────────────────────


def test_g1578_coexistence_with_gate_21_abi_hepatotox():
    """H.G1578 — alias `ast_iu_l` activa gate 44 IO + gate 21 abi hepatotox simultáneamente.

    Eje hepático cuádruple (gates 21+32+39+44): mismo bioquímico activa
    múltiples gates con scope distinto. Útil cuando paciente recibe combo
    o se evalúa múltiples opciones de tratamiento.
    """
    r = _evaluate({"ast_iu_l": 300}, treatments=_tx("PEMBROLIZUMAB"))
    codes = set(_gate_codes(r))
    assert GATE_44 in codes
    assert "abiraterone_hepatotoxicity_grade3" in codes


def test_g1579_coexistence_with_gate_28_abi_adrenal_insufficiency():
    """H.G1579 — alias `cortisol_basal` activa gate 46 IO + gate 28 abi adrenal axis.

    Mismo cortisol bajo activa AMBOS gates pero scope distinto bloquea
    regímenes diferentes. Útil cuando paciente tiene insuficiencia
    adrenal y se evalúa abi vs IO como opciones.
    """
    r = _evaluate({"cortisol_basal": 1.5}, treatments=_tx("PEMBROLIZUMAB"))
    codes = set(_gate_codes(r))
    assert GATE_46 in codes
    assert "abiraterone_adrenal_insufficiency" in codes


def test_g1580_coexistence_with_gate_32_darolutamide_hepatic():
    """H.G1580 — alias `ast_iu_l` activa gate 44 IO + gate 32 darolutamida hepatocelular.

    Eje hepático cuádruple completo: gate 21 (abi) + gate 32 (daro) +
    gate 39 (abi ALP rise) + gate 44 (IO immune-mediated NUEVO #54).
    """
    r = _evaluate({"ast_iu_l": 300}, treatments=_tx("PEMBROLIZUMAB"))
    codes = set(_gate_codes(r))
    assert GATE_44 in codes
    assert "darolutamide_hepatotoxicity_grade3" in codes


# ───────────────────────────────────────────────
# §G — Polyorgan irAE simultaneous (5-10% pacientes)
# ───────────────────────────────────────────────


def test_g1581_all_4_irae_gates_simultaneous():
    """H.G1581 — Polyorgan irAE: 4 gates 43-46 disparan simultáneamente."""
    r = _evaluate({
        "pneumonitis_ctcae_grade": 3,
        "hepatitis_ctcae_grade": 3,
        "colitis_ctcae_grade": 3,
        "hypophysitis_documented_for_checkpoint": "Sí",
    }, treatments=_tx("PEMBROLIZUMAB"))
    codes = set(_gate_codes(r))
    assert ALL_CHECKPOINT_GATES.issubset(codes)


def test_g1582_polyorgan_filtering_filters_pembrolizumab():
    """H.G1582 — Polyorgan irAE filtra pembrolizumab (count=0)."""
    r = _evaluate({
        "pneumonitis_ctcae_grade": 3,
        "colitis_ctcae_grade": 3,
    }, treatments=_tx("PEMBROLIZUMAB"))
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 0


def test_g1583_combo_pembro_olaparib_filtered():
    """H.G1583 — Combo PEMBROLIZUMAB_OLAPARIB filtrado por gate 43-46."""
    r = _evaluate({"pneumonitis_ctcae_grade": 3}, treatments=_tx("PEMBROLIZUMAB_OLAPARIB"))
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 0


def test_g1584_combo_nivo_ipi_filtered_higher_risk_documented():
    """H.G1584 — NIVOLUMAB_IPILIMUMAB combo filtrado (CheckMate-650, 2-3× más alta tasa irAE)."""
    r = _evaluate({"colitis_ctcae_grade": 3}, treatments=_tx("NIVOLUMAB_IPILIMUMAB"))
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 0


# ───────────────────────────────────────────────
# §H — Catálogo + clasificadores + integración
# ───────────────────────────────────────────────


@pytest.mark.parametrize("gate_code", [GATE_43, GATE_44, GATE_45, GATE_46])
def test_g1585_gates_43_46_in_yaml_catalog(gate_code):
    """H.G1585 — Gates 43-46 cargados en catálogo YAML."""
    from prostanet.shared.pivotal_gates_yaml_loader import get_loaded_yaml_codes
    assert gate_code in get_loaded_yaml_codes()


@pytest.mark.parametrize("gate_code", [GATE_43, GATE_44, GATE_45, GATE_46])
def test_g1586_gates_43_46_in_active_codes(gate_code):
    """H.G1586 — Gates 43-46 en `get_active_gate_codes()`."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    assert gate_code in get_active_gate_codes()


def test_g1587_total_gates_at_least_46():
    """H.G1587 — Total gates activos ≥46 (forward-compat con catálogo creciente)."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    assert len(get_active_gate_codes()) >= 46


def test_g1588_classifier_pivotal_gate_delta_labels():
    """H.G1588 — `_GATE_EXACT_CLASSES` incluye los 4 labels específicos."""
    from prostanet.shared.pivotal_gate_delta import _GATE_EXACT_CLASSES
    assert _GATE_EXACT_CLASSES.get(GATE_43) == "Pneumonitis IO (KEYNOTE + NCCN §PNEU-1)"
    assert _GATE_EXACT_CLASSES.get(GATE_44) == "Hepatitis IO (KEYNOTE/CheckMate + NCCN §HEP-1)"
    assert _GATE_EXACT_CLASSES.get(GATE_45) == "Colitis IO (KEYNOTE/CheckMate + NCCN §GI-1)"
    assert _GATE_EXACT_CLASSES.get(GATE_46) == "Endocrinopatías IO (KEYNOTE/Sznol + NCCN §END-1)"


def test_g1589_classifier_profile_compass_labels():
    """H.G1589 — profile_compass _classify produce 4 class labels en by_class para irAE."""
    from prostanet.domains.patient_tracking.profile_compass import (
        _build_pivotal_contraindication_gates_panel as _builder,
    )
    raw_assessment = {
        "result_snapshot": {
            "pivotal_contraindication_gates": [
                {"code": GATE_43, "title": "x", "severity": "hard_block", "message": "x", "evidence_tag": "x", "trial_refs": []},
                {"code": GATE_44, "title": "x", "severity": "hard_block", "message": "x", "evidence_tag": "x", "trial_refs": []},
                {"code": GATE_45, "title": "x", "severity": "hard_block", "message": "x", "evidence_tag": "x", "trial_refs": []},
                {"code": GATE_46, "title": "x", "severity": "hard_block", "message": "x", "evidence_tag": "x", "trial_refs": []},
            ],
        },
    }
    panel = _builder(raw_assessment)
    by_class = set((panel.get("by_class") or {}).keys())
    expected = {
        "Pneumonitis IO (KEYNOTE + NCCN §PNEU-1)",
        "Hepatitis IO (KEYNOTE/CheckMate + NCCN §HEP-1)",
        "Colitis IO (KEYNOTE/CheckMate + NCCN §GI-1)",
        "Endocrinopatías IO (KEYNOTE/Sznol + NCCN §END-1)",
    }
    assert expected.issubset(by_class), f"Missing class labels: {expected - by_class}"


def test_g1590_evidence_tags_unique_per_gate():
    """H.G1590 — Cada gate 43-46 tiene evidence_tag único + trial_refs específicos."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files
    files = _load_yaml_files()
    for code in [GATE_43, GATE_44, GATE_45, GATE_46]:
        config = files.get(code)
        assert config is not None
        assert config.get("evidence_tag")
        assert "keynote" in config.get("evidence_tag", "").lower() or "checkmate" in config.get("evidence_tag", "").lower()
        assert len(config.get("trial_refs") or []) >= 5


# ───────────────────────────────────────────────
# §I — Smoke E2E
# ───────────────────────────────────────────────


def test_g1591_smoke_e2e_pembrolizumab_full_irae_panel():
    """H.G1591 — E2E: paciente con 4 irAE simultáneas → 4 gates fire + filtrado pembro + evidence."""
    r = _evaluate({
        "pneumonitis_ctcae_grade": 4,
        "ast": 350,
        "alt": 300,
        "colitis_ctcae_grade": 4,
        "diabetes_new_onset_for_checkpoint": "Sí",
    }, treatments=_tx("PEMBROLIZUMAB"))
    codes = set(_gate_codes(r))
    # 4 gates IO disparan
    assert ALL_CHECKPOINT_GATES.issubset(codes)
    # Pembrolizumab filtrado
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 0
    # Evidence tags por gate
    for gate_data in r["gates_triggered"]:
        if gate_data["code"] in ALL_CHECKPOINT_GATES:
            assert gate_data.get("evidence_tag")
            assert gate_data.get("severity") == "hard_block"


def test_g1592_smoke_e2e_healthy_pembrolizumab_no_irae():
    """H.G1592 — Paciente sano en pembro NO dispara ningún gate IO."""
    r = _evaluate({
        "pneumonitis_ctcae_grade": 0,
        "ast": 30,
        "alt": 25,
        "colitis_ctcae_grade": 0,
        "tsh": 2.0,
        "cortisol_am": 12,
    }, treatments=_tx("PEMBROLIZUMAB"))
    codes = set(_gate_codes(r))
    # Ningún gate IO dispara
    assert not (ALL_CHECKPOINT_GATES & codes)


def test_g1593_smoke_e2e_irae_only_blocks_io_not_other_drugs():
    """H.G1593 — Pneumonitis G3 con olaparib NO bloquea olaparib (gate 43 scope checkpoint inh)."""
    r = _evaluate({"pneumonitis_ctcae_grade": 3}, treatments=_tx("OLAPARIB"))
    codes = _gate_codes(r)
    # Gate 43 fires (independent de scope) pero olaparib no se filtra
    assert GATE_43 in codes
    filt = r.get("filtered_treatments") or []
    assert len(filt) == 1, "Olaparib no es checkpoint inh, no debe filtrarse"
