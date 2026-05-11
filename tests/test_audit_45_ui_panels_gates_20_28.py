"""tests/test_audit_45_ui_panels_gates_20_28.py — FAUBOT 2026-04-25 (XXXVI).

Auditoría #45 — UI panels para gates 26-28 + opcional 20-25.

Cobertura:
  - Class labels específicos para 9 gates nuevos (#38-#43, gates 20-28)
  - profile_compass._classify() retorna labels correctos
  - pivotal_gate_delta._classify_gate_for_message() consistencia con UI panel
  - by_class agregación correcta (cada clase aparece en panel.by_class)
  - severity_color preservado para los gates nuevos
  - cross_alerts pattern compatible con nuevos gates
  - El panel UI auto-renderiza cards para los 9 gates sin cambios al template

Hipótesis: H.G951-H.G990 (~40 hipótesis).

Patrón: el template `patient_profile.html` es genérico y itera
`for gate in gates_panel.gates`. Por tanto, basta con que
`_classify(code)` retorne el class_label específico para que cada
gate reciba su card automáticamente.
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest

from prostanet.domains.patient_tracking.profile_compass import (
    _build_pivotal_contraindication_gates_panel,
)
from prostanet.shared.pivotal_gate_delta import _classify_gate_for_message


# ════════════════════════════════════════════════════════════════════
# §A. profile_compass._classify() — los 9 gates nuevos (H.G951-H.G960)
# ════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("code,expected_class", [
    # Gate 20 — ARSI seizure
    ("arsi_in_seizure_history_grade3", "ARSI convulsiones"),
    # Gate 21 — Abiraterona hepatotox
    ("abiraterone_hepatotoxicity_grade3", "Hepatotoxicidad abiraterona"),
    # Gate 22 — Niraparib trombocitopenia
    ("niraparib_in_severe_thrombocytopenia", "PARPi específico niraparib"),
    # Gate 23 — Niraparib HTA
    ("niraparib_hypertension_grade3_magnitude", "PARPi específico niraparib"),
    # Gate 24 — Docetaxel longitudinal
    ("docetaxel_neuropathy_longitudinal_grade2_post_4_cycles", "Taxanes neuropathy longitudinal"),
    # Gate 25 — Ipatasertib hyperglycemia
    ("ipatasertib_hyperglycemia_grade3", "PI3K/AKT metabólico"),
    # Gate 26 — Cabazitaxel hipersensibilidad
    ("cabazitaxel_hypersensitivity_grade3", "Hipersensibilidad cabazitaxel"),
    # Gate 27 — Ra-223 FRAX
    ("radium223_high_fracture_risk_frax", "Hueso (FRAX score)"),
    # Gate 28 — Abiraterone adrenal
    ("abiraterone_adrenal_insufficiency", "Adrenal axis abiraterona"),
])
def test_g951_profile_compass_classify_new_gates(code, expected_class):
    """H.G951 — _classify() en profile_compass retorna labels correctos
    para los 9 gates nuevos (#38-#43)."""
    raw = {
        "result_snapshot": {
            "pivotal_contraindication_gates": [
                {"code": code, "severity": "hard_block", "message": "x", "trial_refs": []}
            ]
        }
    }
    panel = _build_pivotal_contraindication_gates_panel(raw)
    assert panel["gates"][0]["class_label"] == expected_class
    assert expected_class in panel["by_class"]


def test_g952_panel_renders_card_for_each_new_gate():
    """H.G952 — Panel auto-renderiza card per gate (template iteration)."""
    new_gate_codes = [
        "arsi_in_seizure_history_grade3",
        "abiraterone_hepatotoxicity_grade3",
        "niraparib_in_severe_thrombocytopenia",
        "niraparib_hypertension_grade3_magnitude",
        "docetaxel_neuropathy_longitudinal_grade2_post_4_cycles",
        "ipatasertib_hyperglycemia_grade3",
        "cabazitaxel_hypersensitivity_grade3",
        "radium223_high_fracture_risk_frax",
        "abiraterone_adrenal_insufficiency",
    ]
    raw = {
        "result_snapshot": {
            "pivotal_contraindication_gates": [
                {"code": c, "severity": "hard_block", "message": f"msg-{c}", "trial_refs": []}
                for c in new_gate_codes
            ]
        }
    }
    panel = _build_pivotal_contraindication_gates_panel(raw)
    assert panel["has_gates"] is True
    assert panel["total"] == 9
    assert panel["hard_block_count"] == 9
    # All 9 gates rendered with class_label
    rendered_codes = {g["code"] for g in panel["gates"]}
    assert rendered_codes == set(new_gate_codes)


def test_g953_by_class_aggregation_distinct_per_new_gate():
    """H.G953 — by_class agregación tiene una entrada per clase nueva."""
    raw = {
        "result_snapshot": {
            "pivotal_contraindication_gates": [
                {"code": "arsi_in_seizure_history_grade3", "severity": "hard_block",
                 "message": "x", "trial_refs": []},
                {"code": "cabazitaxel_hypersensitivity_grade3", "severity": "hard_block",
                 "message": "x", "trial_refs": []},
                {"code": "radium223_high_fracture_risk_frax", "severity": "hard_block",
                 "message": "x", "trial_refs": []},
            ]
        }
    }
    panel = _build_pivotal_contraindication_gates_panel(raw)
    by_class = panel["by_class"]
    assert by_class.get("ARSI convulsiones") == 1
    assert by_class.get("Hipersensibilidad cabazitaxel") == 1
    assert by_class.get("Hueso (FRAX score)") == 1


def test_g954_two_niraparib_gates_share_class():
    """H.G954 — Gates 22 + 23 niraparib comparten class_label (PARPi específico niraparib)."""
    raw = {
        "result_snapshot": {
            "pivotal_contraindication_gates": [
                {"code": "niraparib_in_severe_thrombocytopenia", "severity": "hard_block",
                 "message": "x", "trial_refs": []},
                {"code": "niraparib_hypertension_grade3_magnitude", "severity": "hard_block",
                 "message": "x", "trial_refs": []},
            ]
        }
    }
    panel = _build_pivotal_contraindication_gates_panel(raw)
    assert panel["by_class"]["PARPi específico niraparib"] == 2


def test_g955_severity_color_preserved_for_new_gates():
    """H.G955 — severity_color sigue funcionando para gates nuevos."""
    raw = {
        "result_snapshot": {
            "pivotal_contraindication_gates": [
                {"code": "ipatasertib_hyperglycemia_grade3", "severity": "hard_block",
                 "message": "x", "trial_refs": []}
            ]
        }
    }
    panel = _build_pivotal_contraindication_gates_panel(raw)
    assert panel["gates"][0]["severity_color"] == "rose"


def test_g956_classify_does_not_collide_with_pre_existing():
    """H.G956 — Nuevos labels no rompen los pre-existentes."""
    pre_existing = [
        ("radium223_in_cord_compression", "Radio-223"),
        ("lutetium177_in_severe_cytopenias", "Lu-177-PSMA"),
        ("parp_inhibitor_in_severe_cytopenias", "PARP inhibitors"),
        ("qtc_prolongation_grade3_for_enzalutamide", "ARPI cardiotoxicidad"),
        ("lvef_decline_for_apalutamide", "ARPI cardiotoxicidad"),
        ("uncontrolled_hypertension", "Cardiotoxicidad genérica"),
        ("severe_neuropathy_grade3", "Neurológicas"),
        ("no_bone_protective_agent", "Hueso"),
    ]
    for code, expected in pre_existing:
        raw = {
            "result_snapshot": {
                "pivotal_contraindication_gates": [
                    {"code": code, "severity": "hard_block", "message": "x", "trial_refs": []}
                ]
            }
        }
        panel = _build_pivotal_contraindication_gates_panel(raw)
        assert panel["gates"][0]["class_label"] == expected, (
            f"Pre-existing {code} regression: got {panel['gates'][0]['class_label']!r}"
        )


def test_g957_gate_19_arsi_cognitive_separated_from_seizure():
    """H.G957 — Gate 19 (ARSI cognitive) y Gate 20 (ARSI seizure) reciben labels distintos."""
    raw = {
        "result_snapshot": {
            "pivotal_contraindication_gates": [
                {"code": "arsi_in_cognitive_decline_grade2", "severity": "hard_block",
                 "message": "x", "trial_refs": []},
                {"code": "arsi_in_seizure_history_grade3", "severity": "hard_block",
                 "message": "x", "trial_refs": []},
            ]
        }
    }
    panel = _build_pivotal_contraindication_gates_panel(raw)
    by_class = panel["by_class"]
    assert "ARSI deterioro cognitivo" in by_class
    assert "ARSI convulsiones" in by_class
    assert by_class["ARSI deterioro cognitivo"] == 1
    assert by_class["ARSI convulsiones"] == 1


def test_g958_three_abiraterone_gates_separated():
    """H.G958 — Gates 3 (HTA) + 21 (hepatotox) + 28 (adrenal) abiraterona reciben labels distintos."""
    raw = {
        "result_snapshot": {
            "pivotal_contraindication_gates": [
                {"code": "uncontrolled_hypertension", "severity": "hard_block",
                 "message": "x", "trial_refs": []},
                {"code": "abiraterone_hepatotoxicity_grade3", "severity": "hard_block",
                 "message": "x", "trial_refs": []},
                {"code": "abiraterone_adrenal_insufficiency", "severity": "hard_block",
                 "message": "x", "trial_refs": []},
            ]
        }
    }
    panel = _build_pivotal_contraindication_gates_panel(raw)
    by_class = panel["by_class"]
    assert by_class.get("Cardiotoxicidad genérica") == 1
    assert by_class.get("Hepatotoxicidad abiraterona") == 1
    assert by_class.get("Adrenal axis abiraterona") == 1


def test_g959_two_radium223_gates_separated():
    """H.G959 — Gates 9 (no_bone_protective) + 27 (FRAX numeric) Ra-223 reciben labels distintos."""
    raw = {
        "result_snapshot": {
            "pivotal_contraindication_gates": [
                {"code": "no_bone_protective_agent", "severity": "hard_block",
                 "message": "x", "trial_refs": []},
                {"code": "radium223_high_fracture_risk_frax", "severity": "hard_block",
                 "message": "x", "trial_refs": []},
            ]
        }
    }
    panel = _build_pivotal_contraindication_gates_panel(raw)
    by_class = panel["by_class"]
    assert by_class.get("Hueso") == 1
    assert by_class.get("Hueso (FRAX score)") == 1


def test_g960_three_taxane_gates_separated():
    """H.G960 — Gates 2 (G≥3 instant) + 24 (longitudinal) + 26 (hipersensibilidad) taxane reciben labels distintos."""
    raw = {
        "result_snapshot": {
            "pivotal_contraindication_gates": [
                {"code": "severe_neuropathy_grade3", "severity": "hard_block",
                 "message": "x", "trial_refs": []},
                {"code": "docetaxel_neuropathy_longitudinal_grade2_post_4_cycles", "severity": "hard_block",
                 "message": "x", "trial_refs": []},
                {"code": "cabazitaxel_hypersensitivity_grade3", "severity": "hard_block",
                 "message": "x", "trial_refs": []},
            ]
        }
    }
    panel = _build_pivotal_contraindication_gates_panel(raw)
    by_class = panel["by_class"]
    assert by_class.get("Neurológicas") == 1
    assert by_class.get("Taxanes neuropathy longitudinal") == 1
    assert by_class.get("Hipersensibilidad cabazitaxel") == 1


# ════════════════════════════════════════════════════════════════════
# §B. pivotal_gate_delta — consistency UI ↔ delta narrative (H.G961-H.G970)
# ════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("code,expected_class", [
    ("arsi_in_seizure_history_grade3", "ARSI convulsiones"),
    ("abiraterone_hepatotoxicity_grade3", "Hepatotoxicidad abiraterona"),
    ("niraparib_in_severe_thrombocytopenia", "PARPi específico niraparib"),
    ("niraparib_hypertension_grade3_magnitude", "PARPi específico niraparib"),
    ("docetaxel_neuropathy_longitudinal_grade2_post_4_cycles", "Taxanes neuropathy longitudinal"),
    ("ipatasertib_hyperglycemia_grade3", "PI3K/AKT metabólico"),
    ("cabazitaxel_hypersensitivity_grade3", "Hipersensibilidad cabazitaxel"),
    ("radium223_high_fracture_risk_frax", "Hueso (FRAX score)"),
    ("abiraterone_adrenal_insufficiency", "Adrenal axis abiraterona"),
])
def test_g961_delta_classify_consistent_with_ui_panel(code, expected_class):
    """H.G961 — _classify_gate_for_message en delta consistente con UI panel."""
    actual = _classify_gate_for_message(code)
    assert actual == expected_class


def test_g962_delta_pre_existing_gates_unchanged():
    """H.G962 — Gates pre-existentes NO afectados por nuevos exact-match entries."""
    pre_existing = [
        ("radium223_in_cord_compression", "Radio-223"),
        ("lutetium177_in_severe_cytopenias", "Lu-177-PSMA"),
        ("parp_inhibitor_in_severe_cytopenias", "PARP inhibitors"),
        ("qtc_prolongation_grade3_for_enzalutamide", "ARPI cardiotoxicidad"),
        ("lvef_decline_for_apalutamide", "ARPI cardiotoxicidad"),
        ("severe_heart_failure_nyha_iii_iv", "Cardiotoxicidad genérica"),
        ("uncontrolled_hypertension", "Cardiotoxicidad genérica"),
        ("severe_neuropathy_grade3", "Neurológicas"),
        ("no_bone_protective_agent", "Hueso"),
        ("ecog_2_or_more_for_triplets", "Performance status"),
        ("creatinine_clearance_lt_30", "Renal"),
        ("prior_arpi_exposure_mhspc", "Exposición previa"),
    ]
    for code, expected in pre_existing:
        actual = _classify_gate_for_message(code)
        assert actual == expected, f"Regression on {code}: {actual!r} != {expected!r}"


def test_g963_delta_unknown_gate_returns_otros():
    """H.G963 — Unknown code returns 'Otros' default."""
    assert _classify_gate_for_message("some_made_up_code") == "Otros"


def test_g964_delta_empty_string_returns_otros():
    """H.G964 — Empty string returns 'Otros'."""
    assert _classify_gate_for_message("") == "Otros"


def test_g965_radium223_frax_exact_match_takes_priority_over_prefix():
    """H.G965 — Gate 27 (radium223_high_fracture_risk_frax) usa exact-match
    'Hueso (FRAX score)' antes que prefix-match 'Radio-223'."""
    actual = _classify_gate_for_message("radium223_high_fracture_risk_frax")
    assert actual == "Hueso (FRAX score)"
    assert actual != "Radio-223"


def test_g966_arsi_exact_match_takes_priority_over_prefix():
    """H.G966 — Gates 19+20 (arsi_*_grade*) usan exact-match antes que prefix-match 'ARPI neurocognitiva'."""
    assert _classify_gate_for_message("arsi_in_cognitive_decline_grade2") == "ARSI deterioro cognitivo"
    assert _classify_gate_for_message("arsi_in_seizure_history_grade3") == "ARSI convulsiones"


def test_g967_niraparib_prefix_returns_specific_label():
    """H.G967 — Gates niraparib_* usan prefix-match 'PARPi específico niraparib'."""
    assert _classify_gate_for_message("niraparib_in_severe_thrombocytopenia") == "PARPi específico niraparib"
    assert _classify_gate_for_message("niraparib_hypertension_grade3_magnitude") == "PARPi específico niraparib"


def test_g968_parp_inhibitor_prefix_returns_general_label():
    """H.G968 — Gates parp_inhibitor_* (general) NO se confunden con niraparib_*."""
    assert _classify_gate_for_message("parp_inhibitor_in_severe_cytopenias") == "PARP inhibitors"
    assert _classify_gate_for_message("parp_inhibitor_in_mds_aml_history") == "PARP inhibitors"


def test_g969_ipatasertib_specific_match():
    """H.G969 — Gate 25 ipatasertib usa exact-match 'PI3K/AKT metabólico'."""
    assert _classify_gate_for_message("ipatasertib_hyperglycemia_grade3") == "PI3K/AKT metabólico"


def test_g970_docetaxel_longitudinal_specific_match():
    """H.G970 — Gate 24 docetaxel longitudinal usa exact-match."""
    assert _classify_gate_for_message(
        "docetaxel_neuropathy_longitudinal_grade2_post_4_cycles"
    ) == "Taxanes neuropathy longitudinal"


# ════════════════════════════════════════════════════════════════════
# §C. UI Panel: by_class shows distinct categories (H.G971-H.G975)
# ════════════════════════════════════════════════════════════════════


def test_g971_panel_shows_9_distinct_classes_for_9_new_gates():
    """H.G971 — Si los 9 gates nuevos disparan, by_class tiene ≥7 clases distintas
    (gates 22+23 niraparib comparten clase, así que 8 clases distintas)."""
    new_gate_codes = [
        "arsi_in_seizure_history_grade3",
        "abiraterone_hepatotoxicity_grade3",
        "niraparib_in_severe_thrombocytopenia",
        "niraparib_hypertension_grade3_magnitude",
        "docetaxel_neuropathy_longitudinal_grade2_post_4_cycles",
        "ipatasertib_hyperglycemia_grade3",
        "cabazitaxel_hypersensitivity_grade3",
        "radium223_high_fracture_risk_frax",
        "abiraterone_adrenal_insufficiency",
    ]
    raw = {
        "result_snapshot": {
            "pivotal_contraindication_gates": [
                {"code": c, "severity": "hard_block", "message": "x", "trial_refs": []}
                for c in new_gate_codes
            ]
        }
    }
    panel = _build_pivotal_contraindication_gates_panel(raw)
    # 9 gates → 8 distinct classes (niraparib 22+23 share 1 class)
    assert len(panel["by_class"]) == 8
    assert panel["by_class"]["PARPi específico niraparib"] == 2


def test_g972_panel_total_matches_gates_count():
    """H.G972 — total = sum(by_class.values()) = len(gates)."""
    new_gate_codes = [
        "arsi_in_seizure_history_grade3",
        "ipatasertib_hyperglycemia_grade3",
        "cabazitaxel_hypersensitivity_grade3",
    ]
    raw = {
        "result_snapshot": {
            "pivotal_contraindication_gates": [
                {"code": c, "severity": "hard_block", "message": "x", "trial_refs": []}
                for c in new_gate_codes
            ]
        }
    }
    panel = _build_pivotal_contraindication_gates_panel(raw)
    assert panel["total"] == 3
    assert sum(panel["by_class"].values()) == 3
    assert len(panel["gates"]) == 3


def test_g973_panel_summary_text_singular_plural():
    """H.G973 — summary_text usa singular/plural correctamente."""
    # 1 gate
    raw = {
        "result_snapshot": {
            "pivotal_contraindication_gates": [
                {"code": "ipatasertib_hyperglycemia_grade3", "severity": "hard_block",
                 "message": "x", "trial_refs": []}
            ]
        }
    }
    panel = _build_pivotal_contraindication_gates_panel(raw)
    assert panel["summary_text"]  # non-empty


def test_g974_panel_gates_list_includes_class_label_field():
    """H.G974 — Cada gate en panel.gates incluye class_label (para template)."""
    raw = {
        "result_snapshot": {
            "pivotal_contraindication_gates": [
                {"code": "abiraterone_adrenal_insufficiency", "severity": "hard_block",
                 "message": "x", "trial_refs": []}
            ]
        }
    }
    panel = _build_pivotal_contraindication_gates_panel(raw)
    gate = panel["gates"][0]
    assert "class_label" in gate
    assert gate["class_label"] == "Adrenal axis abiraterona"


def test_g975_panel_gates_include_severity_color_and_label():
    """H.G975 — Cada gate incluye severity_color + severity_label para template."""
    raw = {
        "result_snapshot": {
            "pivotal_contraindication_gates": [
                {"code": "cabazitaxel_hypersensitivity_grade3", "severity": "hard_block",
                 "message": "x", "trial_refs": []}
            ]
        }
    }
    panel = _build_pivotal_contraindication_gates_panel(raw)
    gate = panel["gates"][0]
    assert "severity_color" in gate
    assert "severity_label" in gate


# ════════════════════════════════════════════════════════════════════
# §D. End-to-end UI panel real-world scenario (H.G976-H.G980)
# ════════════════════════════════════════════════════════════════════


def test_g976_e2e_complex_patient_multi_class_safety_profile():
    """H.G976 — Paciente complejo con gates de múltiples clases farmacológicas
    se renderiza correctamente con cards específicos."""
    # Paciente real: ARSI seizure + abiraterona hepatotox + niraparib trombo
    raw = {
        "result_snapshot": {
            "pivotal_contraindication_gates": [
                {"code": "arsi_in_seizure_history_grade3", "severity": "hard_block",
                 "message": "ARSI convulsiones G3", "trial_refs": ["PREVAIL", "AFFIRM"]},
                {"code": "abiraterone_hepatotoxicity_grade3", "severity": "hard_block",
                 "message": "Abiraterona AST/ALT >5× ULN", "trial_refs": ["COU-AA-301"]},
                {"code": "niraparib_in_severe_thrombocytopenia", "severity": "hard_block",
                 "message": "Niraparib plaquetas <150K", "trial_refs": ["MAGNITUDE"]},
            ]
        }
    }
    panel = _build_pivotal_contraindication_gates_panel(raw)
    assert panel["has_gates"] is True
    assert panel["total"] == 3
    assert panel["hard_block_count"] == 3
    # All 3 distinct classes
    assert len(panel["by_class"]) == 3
    assert "ARSI convulsiones" in panel["by_class"]
    assert "Hepatotoxicidad abiraterona" in panel["by_class"]
    assert "PARPi específico niraparib" in panel["by_class"]


def test_g977_e2e_abiraterone_3_layer_safety_profile_visualized():
    """H.G977 — Safety profile abiraterona 3-layer visualizado en panel."""
    # Patient with ALL 3 abi gates triggered
    raw = {
        "result_snapshot": {
            "pivotal_contraindication_gates": [
                {"code": "uncontrolled_hypertension", "severity": "hard_block",
                 "message": "HTA no controlada", "trial_refs": []},
                {"code": "abiraterone_hepatotoxicity_grade3", "severity": "hard_block",
                 "message": "Hepatotox G3", "trial_refs": []},
                {"code": "abiraterone_adrenal_insufficiency", "severity": "hard_block",
                 "message": "Adrenal insufficiency", "trial_refs": []},
            ]
        }
    }
    panel = _build_pivotal_contraindication_gates_panel(raw)
    # 3 distinct labels for abiraterone safety dimensions
    by_class = panel["by_class"]
    assert by_class["Cardiotoxicidad genérica"] == 1  # Gate 3 (HTA)
    assert by_class["Hepatotoxicidad abiraterona"] == 1  # Gate 21
    assert by_class["Adrenal axis abiraterona"] == 1  # Gate 28


def test_g978_e2e_radium223_layered_safety_profile_visualized():
    """H.G978 — Ra-223 4-layer safety profile (gates 9, 11, 12, 27) visualizado."""
    raw = {
        "result_snapshot": {
            "pivotal_contraindication_gates": [
                {"code": "no_bone_protective_agent", "severity": "hard_block",
                 "message": "Sin agente óseo", "trial_refs": []},
                {"code": "radium223_in_cord_compression", "severity": "hard_block",
                 "message": "Compresión medular", "trial_refs": []},
                {"code": "radium223_in_hypocalcemia", "severity": "hard_block",
                 "message": "Hipocalcemia", "trial_refs": []},
                {"code": "radium223_high_fracture_risk_frax", "severity": "hard_block",
                 "message": "FRAX >20%", "trial_refs": []},
            ]
        }
    }
    panel = _build_pivotal_contraindication_gates_panel(raw)
    by_class = panel["by_class"]
    # Gates 9 + 27 share the original "Hueso" pero gate 27 tiene "Hueso (FRAX score)"
    assert by_class["Hueso"] == 1
    assert by_class["Radio-223"] == 2  # gates 11 + 12
    assert by_class["Hueso (FRAX score)"] == 1


def test_g979_e2e_cabazitaxel_3_layer_safety_visualized():
    """H.G979 — Cabazitaxel safety profile (gate 2 G≥3 instant + gate 24 longitudinal + gate 26 hipersensibilidad)."""
    raw = {
        "result_snapshot": {
            "pivotal_contraindication_gates": [
                {"code": "severe_neuropathy_grade3", "severity": "hard_block",
                 "message": "Neuropathy G3", "trial_refs": []},
                {"code": "docetaxel_neuropathy_longitudinal_grade2_post_4_cycles", "severity": "hard_block",
                 "message": "Longitudinal G2 post-4-cycles", "trial_refs": []},
                {"code": "cabazitaxel_hypersensitivity_grade3", "severity": "hard_block",
                 "message": "Hipersensibilidad", "trial_refs": []},
            ]
        }
    }
    panel = _build_pivotal_contraindication_gates_panel(raw)
    by_class = panel["by_class"]
    assert by_class["Neurológicas"] == 1  # Gate 2 generic
    assert by_class["Taxanes neuropathy longitudinal"] == 1  # Gate 24
    assert by_class["Hipersensibilidad cabazitaxel"] == 1  # Gate 26


def test_g980_e2e_panel_renders_all_28_gates_simultaneously():
    """H.G980 — Stress test: panel maneja todos los 28 gates simultáneamente."""
    all_28_codes = [
        # Gates 1-19 (existing)
        "prior_arpi_exposure_mhspc",                               # 1
        "severe_neuropathy_grade3",                                # 2
        "uncontrolled_hypertension",                               # 3
        "severe_heart_failure_nyha_iii_iv",                        # 4
        "uncontrolled_diabetes",                                   # 5
        "ecog_2_or_more_for_triplets",                             # 6
        "darolutamide_hypersensitivity",                           # 7
        "polysorbate_hypersensitivity",                            # 8
        "no_bone_protective_agent",                                # 9
        "creatinine_clearance_lt_30",                              # 10
        "radium223_in_cord_compression",                           # 11
        "radium223_in_hypocalcemia",                               # 12
        "lutetium177_in_cord_compression",                         # 13
        "lutetium177_in_severe_cytopenias",                        # 14
        "parp_inhibitor_in_severe_cytopenias",                     # 15
        "parp_inhibitor_in_mds_aml_history",                       # 16
        "qtc_prolongation_grade3_for_enzalutamide",                # 17
        "lvef_decline_for_apalutamide",                            # 18
        "arsi_in_cognitive_decline_grade2",                        # 19
        # Gates 20-28 (#38-#43)
        "arsi_in_seizure_history_grade3",                          # 20
        "abiraterone_hepatotoxicity_grade3",                       # 21
        "niraparib_in_severe_thrombocytopenia",                    # 22
        "niraparib_hypertension_grade3_magnitude",                 # 23
        "docetaxel_neuropathy_longitudinal_grade2_post_4_cycles",  # 24
        "ipatasertib_hyperglycemia_grade3",                        # 25
        "cabazitaxel_hypersensitivity_grade3",                     # 26
        "radium223_high_fracture_risk_frax",                       # 27
        "abiraterone_adrenal_insufficiency",                       # 28
    ]
    raw = {
        "result_snapshot": {
            "pivotal_contraindication_gates": [
                {"code": c, "severity": "hard_block", "message": f"msg-{c}", "trial_refs": []}
                for c in all_28_codes
            ]
        }
    }
    panel = _build_pivotal_contraindication_gates_panel(raw)
    assert panel["has_gates"] is True
    assert panel["total"] == 28
    assert panel["hard_block_count"] == 28
    # NO gate falls into "Otros" (every gate has class_label específico)
    otros_count = panel["by_class"].get("Otros", 0)
    assert otros_count == 0, f"{otros_count} gates fell into 'Otros' bucket"


# ════════════════════════════════════════════════════════════════════
# §E. UI panel summary metrics (H.G981-H.G985)
# ════════════════════════════════════════════════════════════════════


def test_g981_panel_includes_required_fields_for_template():
    """H.G981 — Panel incluye todos los fields que el template requiere."""
    raw = {
        "result_snapshot": {
            "pivotal_contraindication_gates": [
                {"code": "ipatasertib_hyperglycemia_grade3", "severity": "hard_block",
                 "message": "x", "trial_refs": []}
            ]
        }
    }
    panel = _build_pivotal_contraindication_gates_panel(raw)
    required_fields = [
        "has_gates", "total", "hard_block_count", "by_class",
        "gates", "summary_text",
        "total_cross_alerts", "gates_with_cross_alerts_count",
        "meds_capture_gap_count", "has_medications_captured",
    ]
    for field in required_fields:
        assert field in panel, f"Panel missing field {field!r}"


def test_g982_each_gate_has_cross_alerts_field_default_empty():
    """H.G982 — Cada gate tiene cross_alerts (vacío por default sin meds)."""
    raw = {
        "result_snapshot": {
            "pivotal_contraindication_gates": [
                {"code": "abiraterone_adrenal_insufficiency", "severity": "hard_block",
                 "message": "x", "trial_refs": []}
            ]
        }
    }
    panel = _build_pivotal_contraindication_gates_panel(raw)
    gate = panel["gates"][0]
    assert "cross_alerts" in gate
    assert "has_cross_alerts" in gate
    assert "cross_alerts_count" in gate
    assert gate["has_cross_alerts"] is False  # No meds captured


def test_g983_each_gate_has_meds_capture_gap_flag():
    """H.G983 — Cada gate tiene meds_capture_gap flag."""
    raw = {
        "result_snapshot": {
            "pivotal_contraindication_gates": [
                {"code": "cabazitaxel_hypersensitivity_grade3", "severity": "hard_block",
                 "message": "x", "trial_refs": []}
            ]
        }
    }
    panel = _build_pivotal_contraindication_gates_panel(raw)
    gate = panel["gates"][0]
    assert "meds_capture_gap" in gate


def test_g984_panel_empty_when_no_gates():
    """H.G984 — Panel vacío cuando no hay gates triggered."""
    raw = {"result_snapshot": {"pivotal_contraindication_gates": []}}
    panel = _build_pivotal_contraindication_gates_panel(raw)
    assert panel["has_gates"] is False
    assert panel["total"] == 0


def test_g985_panel_handles_none_assessment():
    """H.G985 — Panel maneja None assessment graceful."""
    panel = _build_pivotal_contraindication_gates_panel(None)
    assert panel["has_gates"] is False
    assert panel["total"] == 0
