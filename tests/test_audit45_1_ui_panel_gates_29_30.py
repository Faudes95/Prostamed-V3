"""tests/test_audit45_1_ui_panel_gates_29_30.py — Faubot 2026-04-25 (XLII).

Tests dedicados a Auditoría #45.1 — UI panel update para gates 29-30.

Cubre H.G1136 - H.G1142 (7 hipótesis):

§A — pivotal_gate_delta._classify_gate_for_message
  H.G1136: gate 29 mapea a "Renal olaparib (PROfound + Lynparza §2.3)"
  H.G1137: gate 30 mapea a "Fatigue Lu-177 (VISION + Pluvicto §6)"
  H.G1138: exact-match gate 30 PRECEDE prefix-match `lutetium177_` general

§B — profile_compass._build_pivotal_contraindication_gates_panel
  H.G1139: panel HTML genera class_label específico para gate 29
  H.G1140: panel HTML genera class_label específico para gate 30
  H.G1141: by_class agregator separa "Renal olaparib (...)" vs "Lu-177-PSMA"
           genérico cuando ambos gates lutetium están presentes

§C — Backward compat
  H.G1142: gates legacy (10 + 13 + 14 + 28) NO se ven afectados por el
           cambio (regression guard sobre Auditoría #45 mappings)
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest


# ════════════════════════════════════════════════════════════════════
# §A — pivotal_gate_delta._classify_gate_for_message
# ════════════════════════════════════════════════════════════════════


def test_g1136_gate29_classify_olaparib_renal():
    """H.G1136 — gate 29 → 'Renal olaparib (PROfound + Lynparza §2.3)'."""
    from prostanet.shared.pivotal_gate_delta import _classify_gate_for_message
    label = _classify_gate_for_message("olaparib_renal_dysfunction_grade3")
    assert label == "Renal olaparib (PROfound + Lynparza §2.3)"
    # NO debe caer al genérico "Renal" (gate 10 rucaparib)
    assert label != "Renal"


def test_g1137_gate30_classify_lutetium_fatigue():
    """H.G1137 — gate 30 → 'Fatigue Lu-177 (VISION + Pluvicto §6)'."""
    from prostanet.shared.pivotal_gate_delta import _classify_gate_for_message
    label = _classify_gate_for_message("lutetium177_fatigue_grade3")
    assert label == "Fatigue Lu-177 (VISION + Pluvicto §6)"
    # NO debe caer al prefix-match genérico "Lu-177-PSMA"
    assert label != "Lu-177-PSMA"


def test_g1138_gate30_exact_match_takes_precedence_over_lutetium177_prefix():
    """H.G1138 — exact-match gate 30 PRECEDE prefix-match `lutetium177_`.

    El dict `_GATE_EXACT_CLASSES` se consulta ANTES que `_GATE_PREFIX_CLASSES`,
    así que el exact-match para `lutetium177_fatigue_grade3` gana sobre el
    prefix-match `lutetium177_*` → "Lu-177-PSMA" genérico. Esto preserva
    la diferenciación clínica importante: gates 13-14 son safety neurol/hema
    (cord compression + cytopenias) vs gate 30 es safety functional (fatigue).
    """
    from prostanet.shared.pivotal_gate_delta import _classify_gate_for_message
    # Gates 13-14 mantienen "Lu-177-PSMA" (prefix-match)
    assert _classify_gate_for_message("lutetium177_in_cord_compression") == "Lu-177-PSMA"
    assert _classify_gate_for_message("lutetium177_in_severe_cytopenias") == "Lu-177-PSMA"
    # Gate 30 OVERRIDE el prefix-match con exact-match específico
    assert _classify_gate_for_message("lutetium177_fatigue_grade3") == "Fatigue Lu-177 (VISION + Pluvicto §6)"


# ════════════════════════════════════════════════════════════════════
# §B — profile_compass panel rendering
# ════════════════════════════════════════════════════════════════════


def _make_raw_assessment_with_gates(gate_codes: list[str]) -> dict:
    """Build a minimal raw_assessment dict with the given gate codes
    populated in result_snapshot.pivotal_contraindication_gates."""
    return {
        "input_snapshot": {},
        "result_snapshot": {
            "pivotal_contraindication_gates": [
                {
                    "code": code,
                    "severity": "hard_block",
                    "message": f"Test message for {code}",
                    "evidence_tag": "test_evidence",
                    "trial_refs": ["TEST_TRIAL"],
                }
                for code in gate_codes
            ]
        },
    }


def test_g1139_panel_renders_gate29_with_specific_class_label():
    """H.G1139 — Panel HTML genera class_label específico para gate 29."""
    from prostanet.domains.patient_tracking.profile_compass import (
        _build_pivotal_contraindication_gates_panel,
    )
    raw = _make_raw_assessment_with_gates(["olaparib_renal_dysfunction_grade3"])
    panel = _build_pivotal_contraindication_gates_panel(raw)
    assert panel["has_gates"] is True
    assert panel["total"] == 1
    # Inspect first gate's class_label
    gate = panel["gates"][0]
    assert gate["code"] == "olaparib_renal_dysfunction_grade3"
    assert gate["class_label"] == "Renal olaparib (PROfound + Lynparza §2.3)"
    # by_class aggregator usa este label
    assert "Renal olaparib (PROfound + Lynparza §2.3)" in panel["by_class"]
    assert panel["by_class"]["Renal olaparib (PROfound + Lynparza §2.3)"] == 1


def test_g1140_panel_renders_gate30_with_specific_class_label():
    """H.G1140 — Panel HTML genera class_label específico para gate 30."""
    from prostanet.domains.patient_tracking.profile_compass import (
        _build_pivotal_contraindication_gates_panel,
    )
    raw = _make_raw_assessment_with_gates(["lutetium177_fatigue_grade3"])
    panel = _build_pivotal_contraindication_gates_panel(raw)
    assert panel["has_gates"] is True
    gate = panel["gates"][0]
    assert gate["class_label"] == "Fatigue Lu-177 (VISION + Pluvicto §6)"
    # NO debe ser "Lu-177-PSMA" (prefix-match genérico)
    assert gate["class_label"] != "Lu-177-PSMA"
    assert "Fatigue Lu-177 (VISION + Pluvicto §6)" in panel["by_class"]


def test_g1141_panel_separates_lutetium_classes_in_by_class_aggregator():
    """H.G1141 — by_class separa 'Fatigue Lu-177' vs 'Lu-177-PSMA' cuando
    ambos tipos de gates lutetium están presentes simultáneamente.

    Caso: paciente con cord compression + fatigue G3 + cytopenias →
    debería ver 2 buckets distintos en by_class:
      - "Lu-177-PSMA" (gates 13-14: cord compression + cytopenias) = 2
      - "Fatigue Lu-177 (...)" (gate 30) = 1
    """
    from prostanet.domains.patient_tracking.profile_compass import (
        _build_pivotal_contraindication_gates_panel,
    )
    raw = _make_raw_assessment_with_gates([
        "lutetium177_in_cord_compression",
        "lutetium177_in_severe_cytopenias",
        "lutetium177_fatigue_grade3",
    ])
    panel = _build_pivotal_contraindication_gates_panel(raw)
    assert panel["total"] == 3
    by_class = panel["by_class"]
    # 2 buckets distintos para los 3 gates lutetium
    assert by_class.get("Lu-177-PSMA") == 2  # gates 13 + 14
    assert by_class.get("Fatigue Lu-177 (VISION + Pluvicto §6)") == 1  # gate 30


# ════════════════════════════════════════════════════════════════════
# §C — Backward compat
# ════════════════════════════════════════════════════════════════════


def test_g1142_legacy_gates_unaffected_by_audit45_1():
    """H.G1142 — gates legacy NO se ven afectados (regression guard).

    Gates verificados:
      - gate 10 (creatinine_clearance_lt_30 rucaparib) → "Renal" genérico
      - gate 13 (lutetium177_in_cord_compression) → "Lu-177-PSMA" prefix
      - gate 14 (lutetium177_in_severe_cytopenias) → "Lu-177-PSMA" prefix
      - gate 28 (abiraterone_adrenal_insufficiency) → "Adrenal axis abiraterona"
      - gate 27 (radium223_high_fracture_risk_frax) → "Hueso (FRAX score)"
      - gate 21 (abiraterone_hepatotoxicity_grade3) → "Hepatotoxicidad abiraterona"
      - gate 19 (arsi_in_cognitive_decline_grade2) → "ARSI deterioro cognitivo"
      - gate 20 (arsi_in_seizure_history_grade3) → "ARSI convulsiones"
      - gate 25 (ipatasertib_hyperglycemia_grade3) → "PI3K/AKT metabólico"
      - gate 26 (cabazitaxel_hypersensitivity_grade3) → "Hipersensibilidad cabazitaxel"
      - gate 24 (docetaxel_neuropathy_longitudinal_grade2_post_4_cycles) → "Taxanes neuropathy longitudinal"
    """
    from prostanet.shared.pivotal_gate_delta import _classify_gate_for_message
    expected_legacy = {
        "creatinine_clearance_lt_30": "Renal",
        "lutetium177_in_cord_compression": "Lu-177-PSMA",
        "lutetium177_in_severe_cytopenias": "Lu-177-PSMA",
        "abiraterone_adrenal_insufficiency": "Adrenal axis abiraterona",
        "radium223_high_fracture_risk_frax": "Hueso (FRAX score)",
        "abiraterone_hepatotoxicity_grade3": "Hepatotoxicidad abiraterona",
        "arsi_in_cognitive_decline_grade2": "ARSI deterioro cognitivo",
        "arsi_in_seizure_history_grade3": "ARSI convulsiones",
        "ipatasertib_hyperglycemia_grade3": "PI3K/AKT metabólico",
        "cabazitaxel_hypersensitivity_grade3": "Hipersensibilidad cabazitaxel",
        "docetaxel_neuropathy_longitudinal_grade2_post_4_cycles": "Taxanes neuropathy longitudinal",
        # Genéricos prefix
        "radium223_in_cord_compression": "Radio-223",
        "parp_inhibitor_in_severe_cytopenias": "PARP inhibitors",
        "niraparib_hypertension_grade3_magnitude": "PARPi específico niraparib",
        # Cardio + perf status genéricos
        "uncontrolled_hypertension": "Cardiotoxicidad genérica",
        "ecog_2_or_more_for_triplets": "Performance status",
    }
    for code, expected_label in expected_legacy.items():
        actual = _classify_gate_for_message(code)
        assert actual == expected_label, (
            f"REGRESSION: gate '{code}' classified as '{actual}' "
            f"(expected '{expected_label}'). Auditoría #45.1 broke pre-existing mapping."
        )
