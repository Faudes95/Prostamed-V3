"""Tests del panel UI `pivotal_contraindication_gates_panel`.

Faubot 2026-04-25 (VIII) — Cierra la brecha de UI documentada desde
2026-04-24 III. La cadena de razonamiento clínico (CÓMO + POR QUÉ) que
viven en `result_snapshot.pivotal_contraindication_gates` ahora se
expone al clínico vía `profile.pivotal_contraindication_gates_panel` en
`patient_profile.html`.

Cobertura del test:
  A) Helper `_build_pivotal_contraindication_gates_panel` — empty + populated
  B) Clasificación por clase farmacológica (4 clases pivote + extras)
  C) Severity color-coding (hard_block → rose, soft → amber)
  D) Ordenamiento (hard_block primero, luego por clase y código)
  E) Métricas agregadas (total, hard_block_count, by_class)
  F) Texto resumen (singular/plural correcto)
  G) Integración con `build_patient_profile_view_model`
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest

from prostanet.domains.patient_tracking.profile_compass import (
    _build_pivotal_contraindication_gates_panel,
)


# ── Sección A — Helper builder: empty + populated ─────────────────────────


def test_panel_empty_when_no_raw_assessment():
    """Sin raw_assessment, el panel debe estar vacío y ocultar la card."""
    panel = _build_pivotal_contraindication_gates_panel(None)
    assert panel["has_gates"] is False
    assert panel["total"] == 0
    assert panel["hard_block_count"] == 0
    assert panel["gates"] == []
    assert "Sin contraindicaciones" in panel["summary_text"]


def test_panel_empty_when_raw_assessment_has_no_gates():
    """raw_assessment sin gates en result_snapshot → panel vacío."""
    panel = _build_pivotal_contraindication_gates_panel(
        {"result_snapshot": {"pivotal_contraindication_gates": []}}
    )
    assert panel["has_gates"] is False


def test_panel_empty_when_result_snapshot_missing():
    """raw_assessment sin result_snapshot → panel vacío sin error."""
    panel = _build_pivotal_contraindication_gates_panel({"foo": "bar"})
    assert panel["has_gates"] is False


def test_panel_populated_with_single_gate():
    raw = {
        "result_snapshot": {
            "pivotal_contraindication_gates": [
                {
                    "code": "severe_heart_failure_nyha_iii_iv",
                    "severity": "hard_block",
                    "message": "Abiraterona NO recomendada con NYHA III-IV",
                    "evidence_tag": "latitude_couaa301_couaa302",
                    "trial_refs": ["LATITUDE", "PEACE-1", "COU-AA-301", "COU-AA-302"],
                }
            ]
        }
    }
    panel = _build_pivotal_contraindication_gates_panel(raw)
    assert panel["has_gates"] is True
    assert panel["total"] == 1
    assert panel["hard_block_count"] == 1
    assert len(panel["gates"]) == 1
    g = panel["gates"][0]
    assert g["code"] == "severe_heart_failure_nyha_iii_iv"
    assert g["severity"] == "hard_block"
    assert g["severity_label"] == "Bloqueo absoluto"
    assert g["severity_color"] == "rose"
    assert "LATITUDE" in g["trial_refs"]
    assert g["trial_refs_label"] == "LATITUDE · PEACE-1 · COU-AA-301 · COU-AA-302"


# ── Sección B — Clasificación por clase farmacológica ─────────────────────


@pytest.mark.parametrize(
    "code,expected_class",
    [
        ("radium223_in_cord_compression", "Radio-223"),
        ("radium223_in_hypocalcemia", "Radio-223"),
        ("lutetium177_in_cord_compression", "Lu-177-PSMA"),
        ("lutetium177_in_severe_cytopenias", "Lu-177-PSMA"),
        ("parp_inhibitor_in_severe_cytopenias", "PARP inhibitors"),
        ("parp_inhibitor_in_mds_aml_history", "PARP inhibitors"),
        ("qtc_prolongation_grade3_for_enzalutamide", "ARPI cardiotoxicidad"),
        ("lvef_decline_for_apalutamide", "ARPI cardiotoxicidad"),
        ("severe_heart_failure_nyha_iii_iv", "Cardiotoxicidad genérica"),
        ("uncontrolled_hypertension", "Cardiotoxicidad genérica"),
        ("uncontrolled_diabetes", "Metabólicas"),
        ("severe_neuropathy_grade3", "Neurológicas"),
        ("no_bone_protective_agent", "Hueso"),
        ("ecog_2_or_more_for_triplets", "Performance status"),
        ("creatinine_clearance_lt_30", "Renal"),
        ("darolutamide_hypersensitivity", "Hipersensibilidad"),
        ("polysorbate_hypersensitivity", "Hipersensibilidad"),
        ("prior_arpi_exposure_mhspc", "Exposición previa"),
    ],
)
def test_classification_by_pharmaceutical_class(code, expected_class):
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


def test_unknown_code_classified_as_otros():
    raw = {
        "result_snapshot": {
            "pivotal_contraindication_gates": [
                {"code": "unknown_code_for_future_gate", "severity": "soft"}
            ]
        }
    }
    panel = _build_pivotal_contraindication_gates_panel(raw)
    assert panel["gates"][0]["class_label"] == "Otros"


# ── Sección C — Severity color-coding ─────────────────────────────────────


@pytest.mark.parametrize(
    "severity,expected_color",
    [
        ("hard_block", "rose"),
        ("soft", "amber"),
        ("high", "orange"),
        ("low", "slate"),
        ("", "slate"),
    ],
)
def test_severity_color_coding(severity, expected_color):
    raw = {
        "result_snapshot": {
            "pivotal_contraindication_gates": [
                {"code": "x", "severity": severity}
            ]
        }
    }
    panel = _build_pivotal_contraindication_gates_panel(raw)
    assert panel["gates"][0]["severity_color"] == expected_color


def test_severity_label_humanized():
    raw = {
        "result_snapshot": {
            "pivotal_contraindication_gates": [
                {"code": "x", "severity": "hard_block"},
                {"code": "y", "severity": "soft"},
                {"code": "z", "severity": ""},
            ]
        }
    }
    panel = _build_pivotal_contraindication_gates_panel(raw)
    severities = {g["severity_label"] for g in panel["gates"]}
    assert "Bloqueo absoluto" in severities
    assert "Precaución" in severities
    assert "—" in severities


# ── Sección D — Ordenamiento ──────────────────────────────────────────────


def test_hard_block_gates_sorted_first():
    raw = {
        "result_snapshot": {
            "pivotal_contraindication_gates": [
                {"code": "soft_gate", "severity": "soft"},
                {"code": "hard_a", "severity": "hard_block"},
                {"code": "soft_other", "severity": "soft"},
                {"code": "hard_b", "severity": "hard_block"},
            ]
        }
    }
    panel = _build_pivotal_contraindication_gates_panel(raw)
    severities = [g["severity"] for g in panel["gates"]]
    # Los 2 hard_block deben venir primero
    assert severities[:2] == ["hard_block", "hard_block"]
    assert severities[2:] == ["soft", "soft"]


# ── Sección E — Métricas agregadas ────────────────────────────────────────


def test_metrics_with_multiple_gates():
    raw = {
        "result_snapshot": {
            "pivotal_contraindication_gates": [
                {"code": "radium223_in_cord_compression", "severity": "hard_block"},
                {"code": "radium223_in_hypocalcemia", "severity": "hard_block"},
                {"code": "lutetium177_in_severe_cytopenias", "severity": "hard_block"},
                {"code": "parp_inhibitor_in_mds_aml_history", "severity": "hard_block"},
            ]
        }
    }
    panel = _build_pivotal_contraindication_gates_panel(raw)
    assert panel["total"] == 4
    assert panel["hard_block_count"] == 4
    # 3 clases distintas: Ra-223 (2), Lu-177 (1), PARPi (1)
    assert panel["by_class"]["Radio-223"] == 2
    assert panel["by_class"]["Lu-177-PSMA"] == 1
    assert panel["by_class"]["PARP inhibitors"] == 1


# ── Sección F — Texto resumen (singular/plural) ───────────────────────────


def test_summary_text_singular_one_hard_block():
    raw = {
        "result_snapshot": {
            "pivotal_contraindication_gates": [
                {"code": "radium223_in_cord_compression", "severity": "hard_block"},
            ]
        }
    }
    panel = _build_pivotal_contraindication_gates_panel(raw)
    assert "1 bloqueo absoluto" in panel["summary_text"]
    assert "bloqueos" not in panel["summary_text"]


def test_summary_text_plural_multiple_hard_blocks():
    raw = {
        "result_snapshot": {
            "pivotal_contraindication_gates": [
                {"code": "radium223_in_cord_compression", "severity": "hard_block"},
                {"code": "radium223_in_hypocalcemia", "severity": "hard_block"},
            ]
        }
    }
    panel = _build_pivotal_contraindication_gates_panel(raw)
    assert "2 bloqueos absolutos" in panel["summary_text"]


def test_summary_text_with_mixed_severities():
    raw = {
        "result_snapshot": {
            "pivotal_contraindication_gates": [
                {"code": "x", "severity": "hard_block"},
                {"code": "y", "severity": "soft"},
            ]
        }
    }
    panel = _build_pivotal_contraindication_gates_panel(raw)
    assert "1 bloqueo absoluto" in panel["summary_text"]
    assert "1 precaución/otra" in panel["summary_text"]


def test_summary_text_when_empty():
    panel = _build_pivotal_contraindication_gates_panel(None)
    assert "Sin contraindicaciones pivote activas" in panel["summary_text"]


# ── Sección G — Integración con build_patient_profile_view_model ──────────


def test_view_model_exposes_pivotal_contraindication_gates_panel_key():
    """El view model debe exponer la nueva clave para que el template
    pueda consumirla sin errores incluso cuando no hay gates."""
    from prostanet.domains.patient_tracking.profile_compass import (
        build_patient_profile_view_model,
    )

    minimal_patient = {
        "identity": {"full_name": "Test Patient", "id": 1},
        "baseline": {"psa": 6, "age": 65},
    }
    profile_view = build_patient_profile_view_model(
        patient=minimal_patient,
        latest_assessment_raw=None,
        latest_assessment={},
        state_timeline=[],
        care_overlays=[],
        longitudinal_bundle={},
    )
    assert "pivotal_contraindication_gates_panel" in profile_view
    panel = profile_view["pivotal_contraindication_gates_panel"]
    assert "has_gates" in panel
    assert "total" in panel
    assert "gates" in panel


def test_view_model_panel_populated_when_gates_present():
    """Si raw_assessment contiene gates, el view model los expone correctamente."""
    from prostanet.domains.patient_tracking.profile_compass import (
        build_patient_profile_view_model,
    )

    minimal_patient = {
        "identity": {"full_name": "Test Patient", "id": 1},
        "baseline": {"psa": 30, "age": 70},
    }
    raw_assessment = {
        "result_snapshot": {
            "pivotal_contraindication_gates": [
                {
                    "code": "qtc_prolongation_grade3_for_enzalutamide",
                    "severity": "hard_block",
                    "message": "Enzalutamida NO debe iniciarse con QTc 520 ms",
                    "evidence_tag": "xtandi_label_enzamet_ctcae_v5",
                    "trial_refs": ["ENZAMET", "Xtandi label", "CTCAE v5", "ICH E14"],
                }
            ]
        },
        "input_snapshot": {"qtc_ms": 520},
    }
    profile_view = build_patient_profile_view_model(
        patient=minimal_patient,
        latest_assessment_raw=raw_assessment,
        latest_assessment={},
        state_timeline=[],
        care_overlays=[],
        longitudinal_bundle={},
    )
    panel = profile_view["pivotal_contraindication_gates_panel"]
    assert panel["has_gates"] is True
    assert panel["total"] == 1
    assert panel["hard_block_count"] == 1
    assert panel["gates"][0]["class_label"] == "ARPI cardiotoxicidad"
    assert "ENZAMET" in panel["gates"][0]["trial_refs"]


# ── Sección H — Smoke end-to-end con paciente real ────────────────────────


def test_simulated_complex_patient_with_multiple_gates():
    """Simula un paciente m1_crpc que cumple criterios de varios gates
    simultáneamente (cord compression + hipocalcemia + cytopenias + QTc + LVEF).
    Verifica que el panel los expone todos correctamente clasificados y
    ordenados por severity."""
    raw = {
        "result_snapshot": {
            "pivotal_contraindication_gates": [
                {
                    "code": "radium223_in_cord_compression",
                    "severity": "hard_block",
                    "message": "Ra-223 cord compression block",
                    "trial_refs": ["ALSYMPCA", "Xofigo label", "Loblaw 2012"],
                },
                {
                    "code": "radium223_in_hypocalcemia",
                    "severity": "hard_block",
                    "message": "Ra-223 hypocalcemia block",
                    "trial_refs": ["ALSYMPCA", "Xofigo label"],
                },
                {
                    "code": "lutetium177_in_cord_compression",
                    "severity": "hard_block",
                    "message": "Lu-177 cord compression block",
                    "trial_refs": ["VISION", "PSMAfore", "TheraP", "Pluvicto label"],
                },
                {
                    "code": "lutetium177_in_severe_cytopenias",
                    "severity": "hard_block",
                    "message": "Lu-177 cytopenias block",
                    "trial_refs": ["VISION", "Pluvicto label"],
                },
                {
                    "code": "parp_inhibitor_in_severe_cytopenias",
                    "severity": "hard_block",
                    "message": "PARPi cytopenias block",
                    "trial_refs": ["PROfound", "MAGNITUDE", "TALAPRO-2"],
                },
                {
                    "code": "qtc_prolongation_grade3_for_enzalutamide",
                    "severity": "hard_block",
                    "message": "Enzalutamida QTc block",
                    "trial_refs": ["ENZAMET", "Xtandi label"],
                },
            ]
        }
    }
    panel = _build_pivotal_contraindication_gates_panel(raw)
    assert panel["has_gates"] is True
    assert panel["total"] == 6
    assert panel["hard_block_count"] == 6
    # 4 clases farmacológicas representadas
    assert set(panel["by_class"].keys()) == {
        "Radio-223",
        "Lu-177-PSMA",
        "PARP inhibitors",
        "ARPI cardiotoxicidad",
    }
    # Todos hard_block → todos color rose
    assert all(g["severity_color"] == "rose" for g in panel["gates"])
    # Ordenamiento: hard_block primero (todos), luego alfabético por clase
    classes_in_order = [g["class_label"] for g in panel["gates"]]
    # No debe haber duplicados desordenados (clases agrupadas)
    assert classes_in_order == sorted(classes_in_order)
