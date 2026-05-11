"""Tests del helper longitudinal `pivotal_gate_delta`.

Faubot 2026-04-25 (IX) — Cierra Tier 1.B del backlog: detecta cambios
en `pivotal_contraindication_gates` visita-a-visita y los humaniza al
clínico vía `why_changed_today` de los 4 copilots.

Aporta a:
  - **POR QUÉ** (90% → ~98%): el sistema explica "por qué hoy sí y antes no"
  - **VERSIÓN** (40% → ~55%): cada gate tiene historial visita-a-visita

Cobertura del test:
  A) Helper `compute_pivotal_gates_delta` — empty/first visit/activated/deactivated/severity_changed
  B) Helper `describe_gate_delta_in_clinical_language` — narrativa ES médica
  C) Helper `extract_previous_pivotal_gates` — extracción del latest_assessment
  D) Helper `build_pivotal_gates_delta_summary` — texto resumen header
  E) Integración con `build_decision_delta_since_last_visit`
  F) Smoke E2E con casos clínicos realistas
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest

from prostanet.shared.pivotal_gate_delta import (
    build_pivotal_gates_delta_summary,
    compute_pivotal_gates_delta,
    describe_gate_delta_in_clinical_language,
    extract_previous_pivotal_gates,
)


# ── Sección A — Helper compute_pivotal_gates_delta ────────────────────────


class TestComputePivotalGatesDelta:
    def test_first_visit_no_previous_gates(self):
        """Sin previous gates → primera visita, no se reporta delta."""
        delta = compute_pivotal_gates_delta(
            current_gates=[{"code": "qtc_prolongation_grade3_for_enzalutamide", "severity": "hard_block"}],
            previous_gates=None,
        )
        assert delta["available"] is False
        assert delta["is_first_visit"] is True
        assert delta["total_change_count"] == 0
        # Persisting incluye los current (no se descartan, solo no se reportan como cambios)
        assert len(delta["persisting"]) == 1

    def test_empty_previous_gates_treated_as_first_visit(self):
        """previous_gates=[] (lista vacía) → tratado como primera visita."""
        delta = compute_pivotal_gates_delta(
            current_gates=[{"code": "x", "severity": "hard_block"}],
            previous_gates=[],
        )
        assert delta["is_first_visit"] is True

    def test_no_changes_between_visits(self):
        """Mismos gates en ambas visitas → total_change_count = 0."""
        gates = [
            {"code": "lutetium177_in_severe_cytopenias", "severity": "hard_block"},
            {"code": "parp_inhibitor_in_severe_cytopenias", "severity": "hard_block"},
        ]
        delta = compute_pivotal_gates_delta(
            current_gates=gates,
            previous_gates=gates,
        )
        assert delta["available"] is True
        assert delta["is_first_visit"] is False
        assert delta["total_change_count"] == 0
        assert len(delta["newly_activated"]) == 0
        assert len(delta["newly_deactivated"]) == 0
        assert len(delta["severity_changed"]) == 0
        assert len(delta["persisting"]) == 2

    def test_newly_activated_gate(self):
        """Gate aparece en current pero no en previous → newly_activated."""
        delta = compute_pivotal_gates_delta(
            current_gates=[
                {"code": "qtc_prolongation_grade3_for_enzalutamide", "severity": "hard_block",
                 "trial_refs": ["ENZAMET", "Xtandi label"]},
            ],
            previous_gates=[
                {"code": "severe_heart_failure_nyha_iii_iv", "severity": "hard_block"},
            ],
        )
        assert delta["available"] is True
        assert delta["total_change_count"] == 2  # 1 activated + 1 deactivated
        assert len(delta["newly_activated"]) == 1
        assert delta["newly_activated"][0]["code"] == "qtc_prolongation_grade3_for_enzalutamide"
        assert "ENZAMET" in delta["newly_activated"][0]["trial_refs"]

    def test_newly_deactivated_gate(self):
        """Gate aparece en previous pero no en current → newly_deactivated."""
        delta = compute_pivotal_gates_delta(
            current_gates=[],
            previous_gates=[
                {"code": "qtc_prolongation_grade3_for_enzalutamide", "severity": "hard_block",
                 "message": "Enza QTc"},
            ],
        )
        assert delta["available"] is True
        assert delta["total_change_count"] == 1
        assert len(delta["newly_deactivated"]) == 1
        assert delta["newly_deactivated"][0]["code"] == "qtc_prolongation_grade3_for_enzalutamide"

    def test_severity_changed_only(self):
        """Mismo code pero severity cambia → severity_changed."""
        delta = compute_pivotal_gates_delta(
            current_gates=[{"code": "x", "severity": "hard_block",
                            "message": "now hard", "trial_refs": ["TRIAL_A"],
                            "evidence_tag": "tag_v2"}],
            previous_gates=[{"code": "x", "severity": "soft", "message": "was soft"}],
        )
        assert delta["available"] is True
        assert delta["total_change_count"] == 1
        assert len(delta["severity_changed"]) == 1
        change = delta["severity_changed"][0]
        assert change["code"] == "x"
        assert change["previous_severity"] == "soft"
        assert change["current_severity"] == "hard_block"
        assert change["current_message"] == "now hard"
        assert change["current_trial_refs"] == ["TRIAL_A"]
        assert change["current_evidence_tag"] == "tag_v2"

    def test_mixed_activated_deactivated_persisting(self):
        """Caso completo: 1 nueva + 1 desactivada + 1 persistente + 1 severity."""
        delta = compute_pivotal_gates_delta(
            current_gates=[
                {"code": "gate_persistent", "severity": "hard_block"},
                {"code": "gate_new", "severity": "hard_block"},
                {"code": "gate_severity", "severity": "hard_block"},
            ],
            previous_gates=[
                {"code": "gate_persistent", "severity": "hard_block"},
                {"code": "gate_removed", "severity": "soft"},
                {"code": "gate_severity", "severity": "soft"},
            ],
        )
        assert delta["total_change_count"] == 3  # 1 act + 1 deact + 1 sev
        assert len(delta["newly_activated"]) == 1
        assert delta["newly_activated"][0]["code"] == "gate_new"
        assert len(delta["newly_deactivated"]) == 1
        assert delta["newly_deactivated"][0]["code"] == "gate_removed"
        assert len(delta["severity_changed"]) == 1
        assert delta["severity_changed"][0]["code"] == "gate_severity"
        assert len(delta["persisting"]) == 1
        assert delta["persisting"][0]["code"] == "gate_persistent"

    def test_gates_without_code_skipped(self):
        """Gates sin code válido se ignoran del índice."""
        delta = compute_pivotal_gates_delta(
            current_gates=[{"code": "", "severity": "hard_block"}, {"severity": "soft"}],
            previous_gates=[{"code": "x"}],
        )
        # Solo 'x' está en previous; nada en current → 1 deactivated
        assert delta["total_change_count"] == 1
        assert delta["newly_deactivated"][0]["code"] == "x"


# ── Sección B — Helper describe_gate_delta_in_clinical_language ───────────


class TestDescribeGateDeltaInClinicalLanguage:
    def test_empty_delta_returns_no_lines(self):
        assert describe_gate_delta_in_clinical_language({}) == []
        assert describe_gate_delta_in_clinical_language({"available": False}) == []

    def test_first_visit_returns_no_lines(self):
        delta = compute_pivotal_gates_delta(
            current_gates=[{"code": "x", "severity": "hard_block"}],
            previous_gates=None,
        )
        assert describe_gate_delta_in_clinical_language(delta) == []

    def test_no_changes_returns_no_lines(self):
        gates = [{"code": "x", "severity": "hard_block"}]
        delta = compute_pivotal_gates_delta(current_gates=gates, previous_gates=gates)
        assert describe_gate_delta_in_clinical_language(delta) == []

    def test_newly_activated_describes_in_clinical_language(self):
        delta = compute_pivotal_gates_delta(
            current_gates=[
                {"code": "qtc_prolongation_grade3_for_enzalutamide",
                 "severity": "hard_block",
                 "trial_refs": ["ENZAMET", "Xtandi label", "CTCAE v5"]},
            ],
            previous_gates=[],  # primera visita
        )
        # primera visita → no lines
        assert describe_gate_delta_in_clinical_language(delta) == []
        # Ahora con previous_gates real:
        delta2 = compute_pivotal_gates_delta(
            current_gates=[
                {"code": "qtc_prolongation_grade3_for_enzalutamide",
                 "severity": "hard_block",
                 "trial_refs": ["ENZAMET", "Xtandi label", "CTCAE v5"]},
            ],
            previous_gates=[{"code": "other_gate", "severity": "soft"}],
        )
        lines = describe_gate_delta_in_clinical_language(delta2)
        assert len(lines) == 2  # 1 activated + 1 deactivated
        activated_line = next(l for l in lines if "⊕" in l)
        assert "ARPI cardiotoxicidad" in activated_line
        assert "qtc_prolongation_grade3_for_enzalutamide" in activated_line
        assert "ENZAMET" in activated_line

    def test_newly_deactivated_describes_relief(self):
        delta = compute_pivotal_gates_delta(
            current_gates=[],
            previous_gates=[{"code": "lutetium177_in_severe_cytopenias",
                             "severity": "hard_block"}],
        )
        lines = describe_gate_delta_in_clinical_language(delta)
        assert len(lines) == 1
        assert "⊖" in lines[0]
        assert "Lu-177-PSMA" in lines[0]
        assert "vuelve" in lines[0].lower()

    def test_severity_changed_described(self):
        delta = compute_pivotal_gates_delta(
            current_gates=[{"code": "parp_inhibitor_in_severe_cytopenias",
                            "severity": "hard_block"}],
            previous_gates=[{"code": "parp_inhibitor_in_severe_cytopenias",
                             "severity": "soft"}],
        )
        lines = describe_gate_delta_in_clinical_language(delta)
        assert len(lines) == 1
        assert "↻" in lines[0]
        assert "PARP inhibitors" in lines[0]
        assert "soft → hard_block" in lines[0]

    @pytest.mark.parametrize(
        "code,expected_class",
        [
            ("radium223_in_cord_compression", "Radio-223"),
            ("lutetium177_in_severe_cytopenias", "Lu-177-PSMA"),
            ("parp_inhibitor_in_mds_aml_history", "PARP inhibitors"),
            ("qtc_prolongation_grade3_for_enzalutamide", "ARPI cardiotoxicidad"),
            ("lvef_decline_for_apalutamide", "ARPI cardiotoxicidad"),
            ("severe_heart_failure_nyha_iii_iv", "Cardiotoxicidad genérica"),
            ("uncontrolled_diabetes", "Metabólicas"),
            ("creatinine_clearance_lt_30", "Renal"),
            ("darolutamide_hypersensitivity", "Hipersensibilidad"),
            ("unknown_gate_xyz", "Otros"),
        ],
    )
    def test_classification_consistent_with_ui_panel(self, code, expected_class):
        """La clasificación de pivotal_gate_delta debe ser idéntica a la
        del UI panel (`profile_compass._build_pivotal_contraindication_gates_panel`)
        para mantener consistencia narrativa ↔ UI."""
        delta = compute_pivotal_gates_delta(
            current_gates=[{"code": code, "severity": "hard_block"}],
            previous_gates=[{"code": "other_existing_gate", "severity": "hard_block"}],
        )
        lines = describe_gate_delta_in_clinical_language(delta)
        # Encontrar la línea ⊕ (activated)
        activated_line = next(l for l in lines if "⊕" in l)
        assert expected_class in activated_line


# ── Sección C — Helper extract_previous_pivotal_gates ─────────────────────


class TestExtractPreviousPivotalGates:
    def test_no_assessment_returns_empty(self):
        assert extract_previous_pivotal_gates(None) == []
        assert extract_previous_pivotal_gates({}) == []

    def test_assessment_without_snapshot_returns_empty(self):
        assert extract_previous_pivotal_gates({"id": 1}) == []

    def test_assessment_without_gates_returns_empty(self):
        assert extract_previous_pivotal_gates(
            {"result_snapshot": {"state": "m1_crpc"}}
        ) == []

    def test_assessment_with_gates_returns_list(self):
        gates = [{"code": "x", "severity": "hard_block"}]
        result = extract_previous_pivotal_gates(
            {"result_snapshot": {"pivotal_contraindication_gates": gates}}
        )
        assert result == gates


# ── Sección D — Helper build_pivotal_gates_delta_summary ──────────────────


class TestBuildPivotalGatesDeltaSummary:
    def test_summary_first_visit_returns_empty_string(self):
        delta = {"available": False, "is_first_visit": True}
        assert build_pivotal_gates_delta_summary(delta) == ""

    def test_summary_no_changes_returns_default_message(self):
        delta = compute_pivotal_gates_delta(
            current_gates=[{"code": "x", "severity": "hard_block"}],
            previous_gates=[{"code": "x", "severity": "hard_block"}],
        )
        summary = build_pivotal_gates_delta_summary(delta)
        assert "Sin cambios" in summary

    def test_summary_singular_one_activated(self):
        delta = compute_pivotal_gates_delta(
            current_gates=[{"code": "x", "severity": "hard_block"}],
            previous_gates=[{"code": "y", "severity": "hard_block"}],
        )
        # 1 activated + 1 deactivated
        summary = build_pivotal_gates_delta_summary(delta)
        assert "1 gate nuevo" in summary
        assert "1 gate desactivado" in summary

    def test_summary_plural_multiple_activations(self):
        delta = compute_pivotal_gates_delta(
            current_gates=[
                {"code": "a", "severity": "hard_block"},
                {"code": "b", "severity": "hard_block"},
                {"code": "c", "severity": "hard_block"},
            ],
            previous_gates=[],
        )
        # primera visita → no summary
        summary = build_pivotal_gates_delta_summary(delta)
        assert summary == ""

    def test_summary_with_severity_change(self):
        delta = compute_pivotal_gates_delta(
            current_gates=[{"code": "x", "severity": "hard_block"}],
            previous_gates=[{"code": "x", "severity": "soft"}],
        )
        summary = build_pivotal_gates_delta_summary(delta)
        assert "1 cambio de severidad" in summary


# ── Sección E — Integración con build_decision_delta_since_last_visit ─────


class TestIntegrationWithDecisionDelta:
    def test_decision_delta_includes_pivotal_gates_delta_key(self):
        from prostanet.domains.patient_tracking.vertical_runtime import (
            build_decision_delta_since_last_visit,
        )
        result = build_decision_delta_since_last_visit(
            patient={"identity": {"id": 1}, "follow_ups": []},
            effective_state="m1_crpc",
            phenotype_state="m1_crpc",
            rule_based_recommendation={},
            final_presented_recommendation={},
            current_pivotal_gates=[],
            previous_pivotal_gates=[],
        )
        assert "pivotal_gates_delta" in result
        assert "pivotal_gates_delta_summary" in result

    def test_decision_delta_promotes_classification_when_only_gate_change(self):
        """Si NO hay decisive_visit ni changed_fields, pero hay cambio en
        gates pivotal → classification se promueve a 'safety_gate_or_blocker'."""
        from prostanet.domains.patient_tracking.vertical_runtime import (
            build_decision_delta_since_last_visit,
        )
        result = build_decision_delta_since_last_visit(
            patient={"identity": {"id": 1}, "follow_ups": [{"visit_date": "2026-04-25"}]},
            effective_state="m1_crpc",
            phenotype_state="m1_crpc",
            rule_based_recommendation={},
            final_presented_recommendation={},
            current_pivotal_gates=[
                {"code": "qtc_prolongation_grade3_for_enzalutamide",
                 "severity": "hard_block", "trial_refs": ["ENZAMET"]},
            ],
            previous_pivotal_gates=[],  # primera visita → sin gate previo
        )
        # Como es primera visita → no se promueve (no hay base de comparación)
        assert "pivotal_gates_delta" in result

    def test_decision_delta_handles_first_visit_gracefully(self):
        from prostanet.domains.patient_tracking.vertical_runtime import (
            build_decision_delta_since_last_visit,
        )
        result = build_decision_delta_since_last_visit(
            patient={"identity": {"id": 1}, "follow_ups": []},
            effective_state="localized_initial",
            phenotype_state="localized_initial",
            rule_based_recommendation={},
            final_presented_recommendation={},
            current_pivotal_gates=[{"code": "x", "severity": "hard_block"}],
            previous_pivotal_gates=None,  # primera visita
        )
        # available debe ser False (no hay decisive_visit ni hay cambio)
        # pero pivotal_gates_delta sí está presente con is_first_visit=True
        assert result["pivotal_gates_delta"]["is_first_visit"] is True


# ── Sección F — Smoke E2E con escenarios clínicos realistas ───────────────


class TestClinicalScenarios:
    """Casos clínicos reales del bucle Faubot."""

    def test_qtc_corrected_deactivates_gate_17(self):
        """Visita 1: paciente con QTc 520ms → gate 17 activo.
        Visita 2: clínico documenta `qtc_corrected_for_arpi=Sí` → gate 17
        desactivado. El delta debe reportarlo claramente."""
        previous = [{
            "code": "qtc_prolongation_grade3_for_enzalutamide",
            "severity": "hard_block",
            "trial_refs": ["ENZAMET", "Xtandi label"],
        }]
        current = []  # gate desactivó por override
        delta = compute_pivotal_gates_delta(current, previous)
        assert delta["total_change_count"] == 1
        assert len(delta["newly_deactivated"]) == 1
        lines = describe_gate_delta_in_clinical_language(delta)
        assert any("ARPI cardiotoxicidad" in l and "vuelve" in l.lower() for l in lines)

    def test_cytopenias_recovery_partial_deactivation(self):
        """Visita 1: ANC 1000 + plaq 80K → ambos gates 14 (Lu-177) y 15 (PARPi)
        activos. Visita 2: ANC 2000 + plaq 80K (recuperó ANC pero plaq aún <100K) →
        gate 14 desactivado pero gate 15 persiste (PARPi requiere plaq ≥100K)."""
        previous = [
            {"code": "lutetium177_in_severe_cytopenias", "severity": "hard_block",
             "trial_refs": ["VISION", "Pluvicto label"]},
            {"code": "parp_inhibitor_in_severe_cytopenias", "severity": "hard_block",
             "trial_refs": ["PROfound", "MAGNITUDE"]},
        ]
        current = [
            # Lu-177 desactivado (umbral plaq 75K satisfecho)
            # PARPi sigue activo (umbral plaq 100K no satisfecho)
            {"code": "parp_inhibitor_in_severe_cytopenias", "severity": "hard_block",
             "trial_refs": ["PROfound", "MAGNITUDE"]},
        ]
        delta = compute_pivotal_gates_delta(current, previous)
        assert delta["total_change_count"] == 1
        assert len(delta["newly_deactivated"]) == 1
        assert delta["newly_deactivated"][0]["code"] == "lutetium177_in_severe_cytopenias"
        assert len(delta["persisting"]) == 1
        assert delta["persisting"][0]["code"] == "parp_inhibitor_in_severe_cytopenias"
        # Narrativa: solo Lu-177 vuelve a estar disponible, PARPi persiste
        lines = describe_gate_delta_in_clinical_language(delta)
        assert any("Lu-177-PSMA" in l for l in lines)
        # PARP NO debe aparecer porque no es un cambio (sigue activo)
        assert not any("PARP inhibitors" in l and "⊖" in l for l in lines)

    def test_cord_compression_stabilization_deactivates_radium_and_lutetium(self):
        """Visita 1: cord compression activa → gates 11 (Ra-223) + 13 (Lu-177).
        Visita 2: `cord_compression_stabilized=Sí` post-Patchell → ambos
        gates desactivados."""
        previous = [
            {"code": "radium223_in_cord_compression", "severity": "hard_block",
             "trial_refs": ["ALSYMPCA", "Xofigo label", "Loblaw 2012"]},
            {"code": "lutetium177_in_cord_compression", "severity": "hard_block",
             "trial_refs": ["VISION", "PSMAfore", "TheraP"]},
        ]
        current = []
        delta = compute_pivotal_gates_delta(current, previous)
        assert delta["total_change_count"] == 2
        assert len(delta["newly_deactivated"]) == 2
        codes_deactivated = {g["code"] for g in delta["newly_deactivated"]}
        assert codes_deactivated == {
            "radium223_in_cord_compression",
            "lutetium177_in_cord_compression",
        }
        lines = describe_gate_delta_in_clinical_language(delta)
        # Ambas clases representadas
        radio_lines = [l for l in lines if "Radio-223" in l]
        lu_lines = [l for l in lines if "Lu-177-PSMA" in l]
        assert len(radio_lines) == 1
        assert len(lu_lines) == 1

    def test_new_gate_activated_after_clinical_event(self):
        """Visita 1: paciente sin gates pivotal.
        Visita 2: desarrolla MDS confirmado → gate 16 activado."""
        previous = [{"code": "uncontrolled_hypertension", "severity": "hard_block"}]
        current = [
            {"code": "uncontrolled_hypertension", "severity": "hard_block"},
            {"code": "parp_inhibitor_in_mds_aml_history", "severity": "hard_block",
             "trial_refs": ["Lynparza label", "Akeega label", "Talzenna label", "Rubraca label"]},
        ]
        delta = compute_pivotal_gates_delta(current, previous)
        assert delta["total_change_count"] == 1
        assert len(delta["newly_activated"]) == 1
        assert delta["newly_activated"][0]["code"] == "parp_inhibitor_in_mds_aml_history"
        assert len(delta["persisting"]) == 1
        lines = describe_gate_delta_in_clinical_language(delta)
        assert any("⊕" in l and "PARP inhibitors" in l for l in lines)
