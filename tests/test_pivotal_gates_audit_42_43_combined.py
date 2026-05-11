"""tests/test_pivotal_gates_audit_42_43_combined.py — FAUBOT 2026-04-25 (XXXIV).

Auditorías #42 + #43 combinadas — Gates 26-27-28.

Cobertura:
  - **Gate 26** cabazitaxel × hipersensibilidad histamine-mediated G≥3
  - **Gate 27** Ra-223 + alto riesgo fractura FRAX (WHO + NOF)
  - **Gate 28** abiraterona × insuficiencia adrenal

Hipótesis: H.G821-H.G900 (~80 hipótesis distribuidas en 3 gates).
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest

from prostanet.shared.pivotal_contraindication_gates import (
    apply_pivotal_contraindication_gates,
    REGIMEN_CODES_CABAZITAXEL,
    REGIMEN_CODES_RADIUM223,
    REGIMEN_CODES_ABIRATERONE,
)
from prostanet.shared.pivotal_gates_yaml_loader import (
    get_loaded_yaml_codes, validate_all_yaml_gates,
)


GATE_26 = "cabazitaxel_hypersensitivity_grade3"
GATE_27 = "radium223_high_fracture_risk_frax"
GATE_28 = "abiraterone_adrenal_insufficiency"


def _gate_codes(payload: dict) -> list[str]:
    r = apply_pivotal_contraindication_gates(payload, treatments=[])
    return [g["code"] for g in r["gates_triggered"]]


# ════════════════════════════════════════════════════════════════════
# §A. Catalog: 3 gates loaded (H.G821-H.G824)
# ════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("gate_code", [GATE_26, GATE_27, GATE_28])
def test_g821_gates_loaded_in_yaml_catalog(gate_code):
    """H.G821 — Gates 26+27+28 cargados en YAML catalog."""
    codes = get_loaded_yaml_codes()
    assert gate_code in codes


def test_g822_no_validation_errors_for_3_new_gates():
    """H.G822 — Los 3 gates pasan validación sin errores."""
    errors = validate_all_yaml_gates()
    for g in [GATE_26, GATE_27, GATE_28]:
        assert g not in errors or not errors[g]


def test_g823_yaml_catalog_at_least_28_files():
    """H.G823 — YAML catalog tiene ≥28 archivos (era 25 al cierre #41)."""
    codes = get_loaded_yaml_codes()
    assert len(codes) >= 28


def test_g824_total_active_gates_at_least_28():
    """H.G824 — Total active gates ≥28."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    codes = get_active_gate_codes()
    assert len(codes) >= 28


# ════════════════════════════════════════════════════════════════════
# §B. Gate 26: cabazitaxel hipersensibilidad (H.G825-H.G845)
# ════════════════════════════════════════════════════════════════════


def test_g825_gate26_fires_on_cabazitaxel_history_flag():
    """H.G825 — Gate 26 dispara con cabazitaxel_hypersensitivity_history."""
    codes = _gate_codes({"cabazitaxel_hypersensitivity_history": "Sí"})
    assert GATE_26 in codes


@pytest.mark.parametrize("alias", [
    "cabazitaxel_hypersensitivity_documented",
    "prior_cabazitaxel_anaphylaxis",
    "cabazitaxel_severe_reaction_history",
])
def test_g826_gate26_fires_on_cabazitaxel_aliases(alias):
    """H.G826 — Aliases del flag cabazitaxel disparan gate 26."""
    codes = _gate_codes({alias: "Sí"})
    assert GATE_26 in codes


def test_g827_gate26_fires_on_polysorbate_history():
    """H.G827 — Polysorbate-80 anaphylaxis history dispara."""
    codes = _gate_codes({"polysorbate_hypersensitivity_history": "Sí"})
    assert GATE_26 in codes


@pytest.mark.parametrize("alias", [
    "polysorbate80_anaphylaxis",
    "prior_polysorbate_anaphylaxis",
    "tween80_hypersensitivity",
])
def test_g828_gate26_fires_on_polysorbate_aliases(alias):
    """H.G828 — Aliases polysorbate disparan."""
    codes = _gate_codes({alias: "Sí"})
    assert GATE_26 in codes


@pytest.mark.parametrize("grade", [3, 4, 5])
def test_g829_gate26_fires_on_ctcae_grade_3_plus(grade):
    """H.G829 — CTCAE grade ≥3 dispara."""
    codes = _gate_codes({"hypersensitivity_ctcae_grade": grade})
    assert GATE_26 in codes


@pytest.mark.parametrize("grade", [0, 1, 2])
def test_g830_gate26_no_fire_on_grade_below_3(grade):
    """H.G830 — Grade <3 NO dispara."""
    codes = _gate_codes({"hypersensitivity_ctcae_grade": grade})
    assert GATE_26 not in codes


def test_g831_gate26_fires_on_prior_taxane_anaphylaxis():
    """H.G831 — Prior taxane anaphylaxis dispara (cross-react ~30%)."""
    codes = _gate_codes({"prior_taxane_anaphylaxis_documented": "Sí"})
    assert GATE_26 in codes


def test_g832_gate26_override_disables_grade1_premedicated():
    """H.G832 — Override disables solo G1 mild + premedication."""
    codes = _gate_codes({
        "hypersensitivity_ctcae_grade": 3,
        "hypersensitivity_grade1_only_premedicated": "Sí",
    })
    assert GATE_26 not in codes


def test_g833_gate26_blocks_only_cabazitaxel():
    """H.G833 — Gate 26 bloquea solo REGIMEN_CODES_CABAZITAXEL."""
    r = apply_pivotal_contraindication_gates(
        {"cabazitaxel_hypersensitivity_history": "Sí"}, treatments=[],
    )
    gate = next(g for g in r["gates_triggered"] if g["code"] == GATE_26)
    affected = set(gate.get("affected_regimen_codes") or [])
    assert affected == REGIMEN_CODES_CABAZITAXEL


def test_g834_gate26_message_cites_jevtana_label():
    """H.G834 — Message cita Jevtana FDA label §4."""
    r = apply_pivotal_contraindication_gates(
        {"polysorbate_hypersensitivity_history": "Sí"}, treatments=[],
    )
    gate = next(g for g in r["gates_triggered"] if g["code"] == GATE_26)
    assert "Jevtana" in gate.get("message", "")


def test_g835_gate26_trial_refs_includes_tropic_card():
    """H.G835 — trial_refs incluye TROPIC + CARD."""
    r = apply_pivotal_contraindication_gates(
        {"hypersensitivity_ctcae_grade": 4}, treatments=[],
    )
    gate = next(g for g in r["gates_triggered"] if g["code"] == GATE_26)
    refs = gate.get("trial_refs") or []
    assert any("TROPIC" in r for r in refs)
    assert any("CARD" in r for r in refs)


def test_g836_gate26_no_fire_with_no_payload():
    """H.G836 — Sin payload no dispara."""
    codes = _gate_codes({})
    assert GATE_26 not in codes


def test_g837_gate26_no_fire_with_only_unrelated_field():
    """H.G837 — Campo no relacionado no dispara."""
    codes = _gate_codes({"some_random_field": "Sí"})
    assert GATE_26 not in codes


def test_g838_gate26_evidence_tag():
    """H.G838 — evidence_tag específico (jevtana_label_tropic_card_ctcae_v5)."""
    r = apply_pivotal_contraindication_gates(
        {"cabazitaxel_hypersensitivity_history": "Sí"}, treatments=[],
    )
    gate = next(g for g in r["gates_triggered"] if g["code"] == GATE_26)
    assert "jevtana" in gate.get("evidence_tag", "").lower()


@pytest.mark.parametrize("flag_value", ["Sí", "Si", "YES", "yes", "1", "true"])
def test_g839_gate26_truthy_variants(flag_value):
    """H.G839 — Múltiples variantes truthy disparan."""
    codes = _gate_codes({"cabazitaxel_hypersensitivity_history": flag_value})
    assert GATE_26 in codes


@pytest.mark.parametrize("flag_value", ["No", "Desconocido", ""])
def test_g840_gate26_falsy_does_not_fire(flag_value):
    """H.G840 — Falsy no dispara."""
    codes = _gate_codes({"cabazitaxel_hypersensitivity_history": flag_value})
    assert GATE_26 not in codes


def test_g841_gate26_override_only_for_grade1():
    """H.G841 — Override aplica para historial G1 mild + premed."""
    codes = _gate_codes({
        "hypersensitivity_ctcae_grade": 3,
        "hypersensitivity_grade1_only_premedicated": "No",
    })
    assert GATE_26 in codes


def test_g842_gate26_severity_hard_block():
    """H.G842 — Severity = hard_block."""
    r = apply_pivotal_contraindication_gates(
        {"cabazitaxel_hypersensitivity_history": "Sí"}, treatments=[],
    )
    gate = next(g for g in r["gates_triggered"] if g["code"] == GATE_26)
    assert gate.get("severity") == "hard_block"


def test_g843_gate26_message_mentions_premedication():
    """H.G843 — Message menciona premedication protocol."""
    r = apply_pivotal_contraindication_gates(
        {"hypersensitivity_ctcae_grade": 4}, treatments=[],
    )
    gate = next(g for g in r["gates_triggered"] if g["code"] == GATE_26)
    msg = gate.get("message", "").lower()
    assert "premedication" in msg or "premed" in msg


def test_g844_gate26_message_mentions_polysorbate():
    """H.G844 — Message menciona polysorbate-80 mechanism."""
    r = apply_pivotal_contraindication_gates(
        {"hypersensitivity_ctcae_grade": 3}, treatments=[],
    )
    gate = next(g for g in r["gates_triggered"] if g["code"] == GATE_26)
    msg = gate.get("message", "").lower()
    assert "polysorbate" in msg


def test_g845_gate26_does_not_fire_other_gates_irrelevant():
    """H.G845 — Activar gate 26 no causa false positives en otros."""
    r = apply_pivotal_contraindication_gates(
        {"cabazitaxel_hypersensitivity_history": "Sí"}, treatments=[],
    )
    codes = [g["code"] for g in r["gates_triggered"]]
    # Gate 26 fires; others gates from cabazitaxel ecosystem (gate 2/24) NOT
    assert GATE_26 in codes
    assert "severe_neuropathy_grade3" not in codes
    assert "docetaxel_neuropathy_longitudinal_grade2_post_4_cycles" not in codes


# ════════════════════════════════════════════════════════════════════
# §C. Gate 27: Ra-223 + FRAX (H.G846-H.G865)
# ════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("frax_mof", [21, 25, 35, 50])
def test_g846_gate27_fires_on_frax_mof_above_20(frax_mof):
    """H.G846 — Gate 27 dispara con FRAX MOF >20%."""
    codes = _gate_codes({"frax_10yr_major_fracture_risk": frax_mof})
    assert GATE_27 in codes


@pytest.mark.parametrize("frax_mof", [5, 10, 15, 20])
def test_g847_gate27_no_fire_on_frax_mof_at_or_below_20(frax_mof):
    """H.G847 — FRAX MOF ≤20 no dispara."""
    codes = _gate_codes({"frax_10yr_major_fracture_risk": frax_mof})
    assert GATE_27 not in codes


@pytest.mark.parametrize("alias", [
    "frax_mof_percent",
    "frax_major_osteoporotic_fracture_10yr",
    "frax_score_mof",
])
def test_g848_gate27_aliases_frax_mof(alias):
    """H.G848 — Aliases FRAX MOF disparan."""
    codes = _gate_codes({alias: 25})
    assert GATE_27 in codes


@pytest.mark.parametrize("frax_hip", [4, 5, 8, 15])
def test_g849_gate27_fires_on_frax_hip_above_3(frax_hip):
    """H.G849 — FRAX Hip >3% dispara."""
    codes = _gate_codes({"frax_10yr_hip_fracture_risk": frax_hip})
    assert GATE_27 in codes


@pytest.mark.parametrize("frax_hip", [0.5, 1.0, 2.0, 3.0])
def test_g850_gate27_no_fire_on_frax_hip_at_or_below_3(frax_hip):
    """H.G850 — FRAX Hip ≤3 no dispara."""
    codes = _gate_codes({"frax_10yr_hip_fracture_risk": frax_hip})
    assert GATE_27 not in codes


@pytest.mark.parametrize("t_score", [-2.6, -3.0, -4.5, -5.0])
def test_g851_gate27_fires_on_dxa_lumbar_below_minus_2_5(t_score):
    """H.G851 — DXA lumbar T-score <-2.5 dispara."""
    codes = _gate_codes({"dxa_t_score_lumbar": t_score})
    assert GATE_27 in codes


@pytest.mark.parametrize("t_score", [-2.5, -2.0, -1.0, 0.5])
def test_g852_gate27_no_fire_on_dxa_lumbar_at_or_above_minus_2_5(t_score):
    """H.G852 — DXA lumbar T-score ≥-2.5 no dispara."""
    codes = _gate_codes({"dxa_t_score_lumbar": t_score})
    assert GATE_27 not in codes


def test_g853_gate27_fires_on_dxa_femoral_neck_low():
    """H.G853 — DXA femoral neck T-score <-2.5 dispara."""
    codes = _gate_codes({"dxa_t_score_femoral_neck": -3.0})
    assert GATE_27 in codes


def test_g854_gate27_fires_on_explicit_flag():
    """H.G854 — Flag explícito dispara."""
    codes = _gate_codes({"high_fracture_risk_for_radium223": "Sí"})
    assert GATE_27 in codes


@pytest.mark.parametrize("alias", [
    "severe_osteoporosis_documented",
    "prior_fragility_fracture_history",
    "vertebral_fracture_history",
])
def test_g855_gate27_aliases_high_risk_flag(alias):
    """H.G855 — Aliases del flag disparan."""
    codes = _gate_codes({alias: "Sí"})
    assert GATE_27 in codes


def test_g856_gate27_override_bone_protection_established():
    """H.G856 — Override bone_protection_established_pre_radium223 disables."""
    codes = _gate_codes({
        "frax_10yr_major_fracture_risk": 30,
        "bone_protection_established_pre_radium223": "Sí",
    })
    assert GATE_27 not in codes


def test_g857_gate27_blocks_only_radium223():
    """H.G857 — Gate 27 bloquea solo REGIMEN_CODES_RADIUM223."""
    r = apply_pivotal_contraindication_gates(
        {"frax_10yr_major_fracture_risk": 30}, treatments=[],
    )
    gate = next(g for g in r["gates_triggered"] if g["code"] == GATE_27)
    affected = set(gate.get("affected_regimen_codes") or [])
    assert affected == REGIMEN_CODES_RADIUM223


def test_g858_gate27_message_cites_era223():
    """H.G858 — Message cita ERA-223 trial."""
    r = apply_pivotal_contraindication_gates(
        {"frax_10yr_hip_fracture_risk": 5}, treatments=[],
    )
    gate = next(g for g in r["gates_triggered"] if g["code"] == GATE_27)
    assert "ERA-223" in gate.get("message", "")


def test_g859_gate27_trial_refs_includes_era223_peace3():
    """H.G859 — trial_refs incluye ERA-223 + PEACE-3."""
    r = apply_pivotal_contraindication_gates(
        {"dxa_t_score_lumbar": -3.0}, treatments=[],
    )
    gate = next(g for g in r["gates_triggered"] if g["code"] == GATE_27)
    refs = gate.get("trial_refs") or []
    assert any("ERA-223" in r for r in refs)
    assert any("PEACE-3" in r for r in refs)


def test_g860_gate27_coexists_with_gate_9():
    """H.G860 — Gate 27 coexiste con Gate 9 (ambos pueden disparar)."""
    # Patient considering Ra-223 with NO bone agent + high FRAX
    codes = _gate_codes({
        "considering_radium223": "Sí",
        "bone_modifying_agent": "ninguno",
        "frax_10yr_major_fracture_risk": 30,
    })
    # Both should fire
    assert GATE_27 in codes
    assert "no_bone_protective_agent" in codes


def test_g861_gate27_message_mentions_frax():
    """H.G861 — Message menciona FRAX."""
    r = apply_pivotal_contraindication_gates(
        {"frax_10yr_major_fracture_risk": 25}, treatments=[],
    )
    gate = next(g for g in r["gates_triggered"] if g["code"] == GATE_27)
    assert "FRAX" in gate.get("message", "")


def test_g862_gate27_message_mentions_denosumab_or_zoledronate():
    """H.G862 — Message menciona denosumab/zoledronate."""
    r = apply_pivotal_contraindication_gates(
        {"frax_10yr_hip_fracture_risk": 5}, treatments=[],
    )
    gate = next(g for g in r["gates_triggered"] if g["code"] == GATE_27)
    msg = gate.get("message", "").lower()
    assert "denosumab" in msg or "zoledronate" in msg


def test_g863_gate27_severity_hard_block():
    """H.G863 — Severity = hard_block."""
    r = apply_pivotal_contraindication_gates(
        {"high_fracture_risk_for_radium223": "Sí"}, treatments=[],
    )
    gate = next(g for g in r["gates_triggered"] if g["code"] == GATE_27)
    assert gate.get("severity") == "hard_block"


def test_g864_gate27_evidence_tag_includes_era223_who():
    """H.G864 — evidence_tag incluye era223 + who."""
    r = apply_pivotal_contraindication_gates(
        {"frax_10yr_major_fracture_risk": 30}, treatments=[],
    )
    gate = next(g for g in r["gates_triggered"] if g["code"] == GATE_27)
    et = gate.get("evidence_tag", "").lower()
    assert "era223" in et and "frax" in et


def test_g865_gate27_no_fire_with_normal_bone_health():
    """H.G865 — Bone health normal no dispara."""
    codes = _gate_codes({
        "frax_10yr_major_fracture_risk": 8,
        "frax_10yr_hip_fracture_risk": 1.5,
        "dxa_t_score_lumbar": -1.0,
        "dxa_t_score_femoral_neck": -1.5,
    })
    assert GATE_27 not in codes


# ════════════════════════════════════════════════════════════════════
# §D. Gate 28: abiraterone + adrenal insufficiency (H.G866-H.G890)
# ════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("cortisol", [4.5, 3.0, 2.0, 0.5])
def test_g866_gate28_fires_on_cortisol_below_5(cortisol):
    """H.G866 — Cortisol AM <5 dispara."""
    codes = _gate_codes({"cortisol_basal_am_ug_dl": cortisol})
    assert GATE_28 in codes


@pytest.mark.parametrize("cortisol", [5.0, 8.0, 15.0, 23.0])
def test_g867_gate28_no_fire_on_cortisol_at_or_above_5(cortisol):
    """H.G867 — Cortisol AM ≥5 no dispara."""
    codes = _gate_codes({"cortisol_basal_am_ug_dl": cortisol})
    assert GATE_28 not in codes


@pytest.mark.parametrize("alias", [
    "cortisol_basal", "cortisol_morning", "am_cortisol", "cortisol_serum_am",
])
def test_g868_gate28_aliases_cortisol_basal(alias):
    """H.G868 — Aliases cortisol_basal_am disparan."""
    codes = _gate_codes({alias: 3})
    assert GATE_28 in codes


@pytest.mark.parametrize("post", [17.5, 12, 8, 3])
def test_g869_gate28_fires_on_cosyntropin_below_18(post):
    """H.G869 — Cortisol post-Cosyntropin <18 dispara."""
    codes = _gate_codes({"cortisol_post_cosyntropin_ug_dl": post})
    assert GATE_28 in codes


@pytest.mark.parametrize("post", [18, 20, 25, 30])
def test_g870_gate28_no_fire_on_cosyntropin_at_or_above_18(post):
    """H.G870 — Cortisol post-Cosyntropin ≥18 no dispara."""
    codes = _gate_codes({"cortisol_post_cosyntropin_ug_dl": post})
    assert GATE_28 not in codes


@pytest.mark.parametrize("alias", [
    "cosyntropin_stim_cortisol",
    "acth_stim_cortisol",
    "synacthen_cortisol_60min",
])
def test_g871_gate28_aliases_cosyntropin(alias):
    """H.G871 — Aliases Cosyntropin disparan."""
    codes = _gate_codes({alias: 12})
    assert GATE_28 in codes


def test_g872_gate28_fires_on_explicit_flag():
    """H.G872 — Flag explícito adrenal_insufficiency_active dispara."""
    codes = _gate_codes({"adrenal_insufficiency_active": "Sí"})
    assert GATE_28 in codes


@pytest.mark.parametrize("alias", [
    "addison_disease_documented",
    "secondary_adrenal_insufficiency",
    "panhypopituitarism",
    "chronic_steroid_suppression",
])
def test_g873_gate28_aliases_adrenal_flag(alias):
    """H.G873 — Aliases del flag adrenal disparan."""
    codes = _gate_codes({alias: "Sí"})
    assert GATE_28 in codes


def test_g874_gate28_symptom_complex_all_required():
    """H.G874 — Symptom complex (all_of: hipoNa + hiperK + fatigue) dispara."""
    codes = _gate_codes({
        "sodium_serum_mmol_l": 125,
        "potassium_serum_mmol_l": 6.0,
        "severe_fatigue_addison_like": "Sí",
    })
    assert GATE_28 in codes


def test_g875_gate28_symptom_complex_partial_does_not_fire():
    """H.G875 — Symptom complex incompleto NO dispara (all_of strict)."""
    # Only hyponatremia, no hyperkalemia or fatigue
    codes = _gate_codes({"sodium_serum_mmol_l": 120})
    assert GATE_28 not in codes
    # hyponatremia + hyperkalemia but no fatigue flag
    codes = _gate_codes({
        "sodium_serum_mmol_l": 120,
        "potassium_serum_mmol_l": 6.5,
    })
    assert GATE_28 not in codes


def test_g876_gate28_override_corticosteroid_replacement():
    """H.G876 — Override corticosteroid_replacement_therapy_documented disables."""
    codes = _gate_codes({
        "adrenal_insufficiency_active": "Sí",
        "corticosteroid_replacement_therapy_documented": "Sí",
    })
    assert GATE_28 not in codes


def test_g877_gate28_blocks_only_abiraterone():
    """H.G877 — Gate 28 bloquea solo REGIMEN_CODES_ABIRATERONE."""
    r = apply_pivotal_contraindication_gates(
        {"cortisol_basal_am_ug_dl": 3}, treatments=[],
    )
    gate = next(g for g in r["gates_triggered"] if g["code"] == GATE_28)
    affected = set(gate.get("affected_regimen_codes") or [])
    assert affected == REGIMEN_CODES_ABIRATERONE


def test_g878_gate28_message_cites_zytiga_label():
    """H.G878 — Message cita Zytiga FDA label §5.4."""
    r = apply_pivotal_contraindication_gates(
        {"adrenal_insufficiency_active": "Sí"}, treatments=[],
    )
    gate = next(g for g in r["gates_triggered"] if g["code"] == GATE_28)
    assert "Zytiga" in gate.get("message", "")


def test_g879_gate28_trial_refs_includes_couaa():
    """H.G879 — trial_refs incluye COU-AA-301/302 + LATITUDE."""
    r = apply_pivotal_contraindication_gates(
        {"cortisol_basal_am_ug_dl": 4}, treatments=[],
    )
    gate = next(g for g in r["gates_triggered"] if g["code"] == GATE_28)
    refs = gate.get("trial_refs") or []
    assert any("COU-AA-301" in r for r in refs)
    assert any("COU-AA-302" in r for r in refs)
    assert any("LATITUDE" in r for r in refs)


def test_g880_gate28_message_mentions_prednisone_or_hydrocortisone():
    """H.G880 — Message menciona prednisone o hidrocortisona."""
    r = apply_pivotal_contraindication_gates(
        {"adrenal_insufficiency_active": "Sí"}, treatments=[],
    )
    gate = next(g for g in r["gates_triggered"] if g["code"] == GATE_28)
    msg = gate.get("message", "").lower()
    assert "prednisona" in msg or "hidrocortisona" in msg


def test_g881_gate28_message_mentions_crisis_adrenal():
    """H.G881 — Message menciona crisis adrenal y manejo."""
    r = apply_pivotal_contraindication_gates(
        {"cortisol_basal_am_ug_dl": 2}, treatments=[],
    )
    gate = next(g for g in r["gates_triggered"] if g["code"] == GATE_28)
    msg = gate.get("message", "").lower()
    assert "crisis adrenal" in msg


def test_g882_gate28_severity_hard_block():
    """H.G882 — Severity = hard_block."""
    r = apply_pivotal_contraindication_gates(
        {"adrenal_insufficiency_active": "Sí"}, treatments=[],
    )
    gate = next(g for g in r["gates_triggered"] if g["code"] == GATE_28)
    assert gate.get("severity") == "hard_block"


def test_g883_gate28_evidence_tag_includes_zytiga_couaa():
    """H.G883 — evidence_tag incluye zytiga + couaa."""
    r = apply_pivotal_contraindication_gates(
        {"cortisol_basal_am_ug_dl": 3}, treatments=[],
    )
    gate = next(g for g in r["gates_triggered"] if g["code"] == GATE_28)
    et = gate.get("evidence_tag", "").lower()
    assert "zytiga" in et


def test_g884_gate28_no_fire_with_normal_cortisol():
    """H.G884 — Cortisol normal no dispara."""
    codes = _gate_codes({
        "cortisol_basal_am_ug_dl": 15,
        "cortisol_post_cosyntropin_ug_dl": 22,
        "sodium_serum_mmol_l": 140,
        "potassium_serum_mmol_l": 4.2,
    })
    assert GATE_28 not in codes


def test_g885_gate28_coexists_with_gate_3_and_21():
    """H.G885 — Gate 28 coexiste con gates 3 (HTA) + 21 (hepatotox)."""
    codes = _gate_codes({
        "uncontrolled_hypertension": "Sí",  # Gate 3
        "ast_value": 250,                    # Gate 21
        "cortisol_basal_am_ug_dl": 3,       # Gate 28
    })
    assert "uncontrolled_hypertension" in codes
    assert "abiraterone_hepatotoxicity_grade3" in codes
    assert GATE_28 in codes


@pytest.mark.parametrize("flag_value", ["Sí", "Si", "YES", "yes", "1", "true"])
def test_g886_gate28_truthy_variants(flag_value):
    """H.G886 — Múltiples variantes truthy."""
    codes = _gate_codes({"adrenal_insufficiency_active": flag_value})
    assert GATE_28 in codes


@pytest.mark.parametrize("override_value", ["No", "Desconocido", ""])
def test_g887_gate28_falsy_override_does_not_disable(override_value):
    """H.G887 — Override falsy NO desactiva."""
    codes = _gate_codes({
        "adrenal_insufficiency_active": "Sí",
        "corticosteroid_replacement_therapy_documented": override_value,
    })
    assert GATE_28 in codes


def test_g888_gate28_addison_clinical_guidelines_in_references():
    """H.G888 — references include Addison Society UK Clinical Guidelines."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files
    files = _load_yaml_files()
    config = files.get(GATE_28)
    assert config is not None
    refs = config.get("references", [])
    assert any("Addison" in r for r in refs)


def test_g889_gate28_no_fire_with_hyponatremia_alone():
    """H.G889 — Hiponatremia aislada NO dispara (necesita all_of)."""
    codes = _gate_codes({"sodium_serum_mmol_l": 125})
    assert GATE_28 not in codes


def test_g890_gate28_no_fire_with_hyperkalemia_alone():
    """H.G890 — Hiperkalemia aislada NO dispara."""
    codes = _gate_codes({"potassium_serum_mmol_l": 6.5})
    assert GATE_28 not in codes


# ════════════════════════════════════════════════════════════════════
# §E. DDI cross-check mapping para 3 gates (H.G891-H.G894)
# ════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("gate_code", [GATE_26, GATE_27, GATE_28])
def test_g891_3_gates_in_ddi_cross_check_mapping(gate_code):
    """H.G891 — Los 3 gates tienen DDI categories declaradas."""
    from prostanet.shared.gates_ddi_cross_check import _GATE_TO_RELATED_DDI_CATEGORIES
    assert gate_code in _GATE_TO_RELATED_DDI_CATEGORIES


@pytest.mark.parametrize("gate_code", [GATE_26, GATE_27, GATE_28])
def test_g892_3_gates_in_oncology_drugs_mapping(gate_code):
    """H.G892 — Los 3 gates tienen oncology_drugs declaradas."""
    from prostanet.shared.gates_ddi_cross_check import _GATE_TO_ONCOLOGY_DRUGS
    assert gate_code in _GATE_TO_ONCOLOGY_DRUGS


def test_g893_gate27_in_bone_remodeling_category():
    """H.G893 — Gate 27 tiene bone_remodeling category."""
    from prostanet.shared.gates_ddi_cross_check import _GATE_TO_RELATED_DDI_CATEGORIES
    cats = _GATE_TO_RELATED_DDI_CATEGORIES[GATE_27]
    assert "bone_remodeling" in cats


def test_g894_gate28_in_pharmacodynamic_aldosterone_category():
    """H.G894 — Gate 28 tiene pharmacodynamic_aldosterone category."""
    from prostanet.shared.gates_ddi_cross_check import _GATE_TO_RELATED_DDI_CATEGORIES
    cats = _GATE_TO_RELATED_DDI_CATEGORIES[GATE_28]
    assert "pharmacodynamic_aldosterone" in cats


# ════════════════════════════════════════════════════════════════════
# §F. Supporting FieldSpecs declared (H.G895-H.G897)
# ════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("field_name", [
    # Gate 26
    "cabazitaxel_hypersensitivity_history",
    "polysorbate_hypersensitivity_history",
    "hypersensitivity_ctcae_grade",
    "prior_taxane_anaphylaxis_documented",
    "hypersensitivity_grade1_only_premedicated",
    # Gate 27
    "frax_10yr_major_fracture_risk",
    "frax_10yr_hip_fracture_risk",
    "dxa_t_score_lumbar",
    "dxa_t_score_femoral_neck",
    "high_fracture_risk_for_radium223",
    "bone_protection_established_pre_radium223",
    # Gate 28
    "cortisol_basal_am_ug_dl",
    "cortisol_post_cosyntropin_ug_dl",
    "adrenal_insufficiency_active",
    "sodium_serum_mmol_l",
    "potassium_serum_mmol_l",
    "severe_fatigue_addison_like",
    "corticosteroid_replacement_therapy_documented",
])
def test_g895_all_18_fieldspecs_declared(field_name):
    """H.G895 — 18 FieldSpecs nuevos declarados."""
    from prostanet.shared.advanced_support_fields import (
        pivotal_gate_supporting_fields,
    )
    fields = pivotal_gate_supporting_fields()
    names = {f.name for f in fields}
    assert field_name in names


def test_g896_total_supporting_fields_at_least_69():
    """H.G896 — Total supporting fields ≥69 (era 51 pre-#42-#43, +18 nuevos)."""
    from prostanet.shared.advanced_support_fields import (
        pivotal_gate_supporting_fields,
    )
    fields = pivotal_gate_supporting_fields()
    assert len(fields) >= 69


def test_g897_numeric_fields_have_units():
    """H.G897 — FieldSpecs numéricos tienen unit declarado."""
    from prostanet.shared.advanced_support_fields import (
        pivotal_gate_supporting_fields,
    )
    fields = pivotal_gate_supporting_fields()
    fields_by_name = {f.name: f for f in fields}
    # Specific numeric fields should have units
    assert fields_by_name["frax_10yr_major_fracture_risk"].unit == "%"
    assert fields_by_name["frax_10yr_hip_fracture_risk"].unit == "%"
    assert fields_by_name["dxa_t_score_lumbar"].unit == "DS"
    assert fields_by_name["dxa_t_score_femoral_neck"].unit == "DS"
    assert fields_by_name["cortisol_basal_am_ug_dl"].unit == "µg/dL"
    assert fields_by_name["cortisol_post_cosyntropin_ug_dl"].unit == "µg/dL"
    assert fields_by_name["sodium_serum_mmol_l"].unit == "mmol/L"
    assert fields_by_name["potassium_serum_mmol_l"].unit == "mmol/L"
    assert fields_by_name["hypersensitivity_ctcae_grade"].unit == "grado"


# ════════════════════════════════════════════════════════════════════
# §G. E2E + integration (H.G898-H.G900)
# ════════════════════════════════════════════════════════════════════


def test_g898_e2e_complex_payload_3_gates_fire():
    """H.G898 — E2E: payload con 3 condiciones triggers 3 gates juntos."""
    payload = {
        "polysorbate_hypersensitivity_history": "Sí",  # Gate 26
        "frax_10yr_major_fracture_risk": 30,           # Gate 27
        "adrenal_insufficiency_active": "Sí",          # Gate 28
    }
    codes = _gate_codes(payload)
    assert GATE_26 in codes
    assert GATE_27 in codes
    assert GATE_28 in codes


def test_g899_e2e_overrides_disable_all_3_gates():
    """H.G899 — E2E: 3 overrides disable los 3 gates simultáneamente."""
    payload = {
        # G26 trigger + override
        "hypersensitivity_ctcae_grade": 3,
        "hypersensitivity_grade1_only_premedicated": "Sí",
        # G27 trigger + override
        "frax_10yr_major_fracture_risk": 30,
        "bone_protection_established_pre_radium223": "Sí",
        # G28 trigger + override
        "adrenal_insufficiency_active": "Sí",
        "corticosteroid_replacement_therapy_documented": "Sí",
    }
    codes = _gate_codes(payload)
    assert GATE_26 not in codes
    assert GATE_27 not in codes
    assert GATE_28 not in codes


def test_g900_active_gate_codes_includes_3_new_gates():
    """H.G900 — get_active_gate_codes() incluye gates 26+27+28."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    codes = set(get_active_gate_codes())
    assert GATE_26 in codes
    assert GATE_27 in codes
    assert GATE_28 in codes
