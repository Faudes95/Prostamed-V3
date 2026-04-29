"""tests/test_gates_coverage_ddi_extension.py — FAUBOT 2026-04-25 (XVI).

Cobertura de la extensión del dashboard `/gates-coverage-dashboard` con
cross-alerts DDI.

Verifica:
  - Agregación de cross-alerts DDI por gate (`ddi_cross_alerts_coverage`).
  - Detección de medicaciones capturadas (`current_medications` /
    `concomitant_medications` / `medications`).
  - Detección de gaps de captura: gates triggered SIN medicaciones.
  - Distribución por categoría DDI (qtc_prolongation, seizure_threshold,
    pharmacodynamic_aldosterone, bone_remodeling, cyp3a4_inhibition).
  - Distribución por severity (contraindicated/major/moderate).
  - Heatmap secundario gate × DDI category (`build_ddi_heatmap_data`).
  - Alertas operativas: `gates_with_high_ddi_burden`,
    `gates_with_critical_meds_gap`.
  - Endpoint Flask: nueva clave `ddi_heatmap` en respuesta JSON.
  - Template HTML: sección "Razonamiento cruzado: Gates × DDI Engine".

Hipótesis cubiertas: H.G204 - H.G228 (25 tests dedicados).
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest

from prostanet.shared.gates_coverage_aggregator import (
    aggregate_gates_coverage,
    build_ddi_heatmap_data,
    build_heatmap_data,
)


# ── Fixtures de assessments sintéticos ──────────────────────────────────


@pytest.fixture
def healthy_assessment():
    return {
        "state": "localized_initial",
        "input_snapshot": {"qtc_ms": 400, "current_medications": "vitamina_d"},
        "result_snapshot": {"pivotal_contraindication_gates": []},
    }


@pytest.fixture
def gate17_with_methadone_assessment():
    """Gate 17 (QTc enzalutamida) + metadona = cross qtc_prolongation."""
    return {
        "state": "m1_crpc",
        "input_snapshot": {"qtc_ms": 520, "current_medications": "metadona, omeprazol"},
        "result_snapshot": {"pivotal_contraindication_gates": [
            {"code": "qtc_prolongation_grade3_for_enzalutamide",
             "triggered": True, "severity": "contraindicated"}
        ]},
    }


@pytest.fixture
def gate17_no_meds_assessment():
    """Gate 17 disparado pero SIN medicaciones (gap de captura)."""
    return {
        "state": "m1_crpc",
        "input_snapshot": {"qtc_ms": 510},
        "result_snapshot": {"pivotal_contraindication_gates": [
            {"code": "qtc_prolongation_grade3_for_enzalutamide",
             "triggered": True, "severity": "contraindicated"}
        ]},
    }


@pytest.fixture
def gate19_with_bupropion_assessment():
    """Gate 19 (cognitive ARSI) + bupropion = cross seizure_threshold."""
    return {
        "state": "mhspc_high_volume",
        "input_snapshot": {
            "cognitive_disturbance_ctcae_grade": 2,
            "current_medications": "bupropion",
        },
        "result_snapshot": {"pivotal_contraindication_gates": [
            {"code": "arsi_in_cognitive_decline_grade2",
             "triggered": True, "severity": "contraindicated"}
        ]},
    }


@pytest.fixture
def gate3_with_spironolactone_assessment():
    """Gate 3 (HTA) + espironolactona = cross pharmacodynamic_aldosterone."""
    return {
        "state": "mhspc_high_volume",
        "input_snapshot": {
            "uncontrolled_hypertension": "Sí",
            "current_medications": "espironolactona",
        },
        "result_snapshot": {"pivotal_contraindication_gates": [
            {"code": "uncontrolled_hypertension",
             "triggered": True, "severity": "contraindicated"}
        ]},
    }


# ──────────────────────────────────────────────────────────────────────
# H.G204 — Estructura del bloque ddi_cross_alerts_coverage
# ──────────────────────────────────────────────────────────────────────


def test_aggregator_includes_ddi_block_with_empty_assessments():
    """H.G204 — Aggregator vacío incluye bloque ddi_cross_alerts_coverage."""
    coverage = aggregate_gates_coverage([])
    assert "ddi_cross_alerts_coverage" in coverage
    block = coverage["ddi_cross_alerts_coverage"]
    for key in ("total_with_medications", "percentage_with_medications",
                "total_cross_alerts", "total_with_cross_alerts",
                "percentage_with_cross_alerts", "by_gate", "by_category",
                "by_severity", "gates_with_meds_gap"):
        assert key in block, f"Falta clave {key} en ddi_cross_alerts_coverage"


def test_empty_assessments_ddi_zeros():
    """H.G204.b — Sin assessments → todos los counters DDI = 0."""
    block = aggregate_gates_coverage([])["ddi_cross_alerts_coverage"]
    assert block["total_with_medications"] == 0
    assert block["total_cross_alerts"] == 0
    assert block["total_with_cross_alerts"] == 0
    assert block["by_gate"] == {}
    assert block["by_category"] == {}
    assert block["by_severity"] == {}


# ──────────────────────────────────────────────────────────────────────
# H.G205 — Detección de medicaciones capturadas
# ──────────────────────────────────────────────────────────────────────


def test_assessment_with_current_medications_counts_as_captured(
    gate17_with_methadone_assessment,
):
    """H.G205 — current_medications poblado → total_with_medications=1."""
    block = aggregate_gates_coverage(
        [gate17_with_methadone_assessment]
    )["ddi_cross_alerts_coverage"]
    assert block["total_with_medications"] == 1
    assert block["percentage_with_medications"] == 100.0


def test_assessment_without_medications_not_counted(
    gate17_no_meds_assessment,
):
    """H.G205.b — Sin medicaciones → total_with_medications=0."""
    block = aggregate_gates_coverage(
        [gate17_no_meds_assessment]
    )["ddi_cross_alerts_coverage"]
    assert block["total_with_medications"] == 0
    assert block["percentage_with_medications"] == 0.0


@pytest.mark.parametrize("med_field", [
    "current_medications", "concomitant_medications", "medications",
])
def test_three_medication_field_aliases_recognized(med_field):
    """H.G206 — Helper acepta los 3 alias del campo medications."""
    a = {
        "state": "m1_crpc",
        "input_snapshot": {"qtc_ms": 520, med_field: "metadona"},
        "result_snapshot": {"pivotal_contraindication_gates": [
            {"code": "qtc_prolongation_grade3_for_enzalutamide",
             "triggered": True, "severity": "contraindicated"}
        ]},
    }
    block = aggregate_gates_coverage([a])["ddi_cross_alerts_coverage"]
    assert block["total_with_medications"] == 1


# ──────────────────────────────────────────────────────────────────────
# H.G207 — Cross-alerts DDI re-computados on-the-fly
# ──────────────────────────────────────────────────────────────────────


def test_cross_alerts_aggregated_for_qtc_with_methadone(
    gate17_with_methadone_assessment,
):
    """H.G207 — Gate 17 + metadona → 1 cross alert qtc_prolongation."""
    block = aggregate_gates_coverage(
        [gate17_with_methadone_assessment]
    )["ddi_cross_alerts_coverage"]
    assert block["total_cross_alerts"] >= 1
    assert block["total_with_cross_alerts"] == 1
    assert "qtc_prolongation" in block["by_category"]
    assert block["by_category"]["qtc_prolongation"] >= 1


def test_cross_alerts_for_cognitive_with_bupropion(
    gate19_with_bupropion_assessment,
):
    """H.G208 — Gate 19 + bupropion → cross seizure_threshold."""
    block = aggregate_gates_coverage(
        [gate19_with_bupropion_assessment]
    )["ddi_cross_alerts_coverage"]
    assert "seizure_threshold" in block["by_category"]
    assert block["by_category"]["seizure_threshold"] >= 1


def test_cross_alerts_for_hta_with_spironolactone(
    gate3_with_spironolactone_assessment,
):
    """H.G209 — Gate 3 + espironolactona → cross pharmacodynamic_aldosterone."""
    block = aggregate_gates_coverage(
        [gate3_with_spironolactone_assessment]
    )["ddi_cross_alerts_coverage"]
    assert "pharmacodynamic_aldosterone" in block["by_category"]
    assert block["by_category"]["pharmacodynamic_aldosterone"] >= 1


def test_no_cross_alerts_for_gate_without_meds(
    gate17_no_meds_assessment,
):
    """H.G210 — Gate triggered sin meds → 0 cross alerts."""
    block = aggregate_gates_coverage(
        [gate17_no_meds_assessment]
    )["ddi_cross_alerts_coverage"]
    assert block["total_cross_alerts"] == 0
    assert block["total_with_cross_alerts"] == 0


# ──────────────────────────────────────────────────────────────────────
# H.G211 — Detección de gap de medicaciones por gate
# ──────────────────────────────────────────────────────────────────────


def test_gates_with_meds_gap_when_triggered_without_meds(
    gate17_no_meds_assessment,
):
    """H.G211 — Gate triggered sin meds → entry en gates_with_meds_gap."""
    block = aggregate_gates_coverage(
        [gate17_no_meds_assessment]
    )["ddi_cross_alerts_coverage"]
    assert "qtc_prolongation_grade3_for_enzalutamide" in block["gates_with_meds_gap"]
    gap = block["gates_with_meds_gap"]["qtc_prolongation_grade3_for_enzalutamide"]
    assert gap["missing_meds_count"] == 1
    assert gap["percentage_of_gate"] == 100.0


def test_no_meds_gap_when_meds_captured(gate17_with_methadone_assessment):
    """H.G211.b — Gate triggered con meds → no entry en gaps."""
    block = aggregate_gates_coverage(
        [gate17_with_methadone_assessment]
    )["ddi_cross_alerts_coverage"]
    assert "qtc_prolongation_grade3_for_enzalutamide" not in block["gates_with_meds_gap"]


def test_partial_meds_gap_percentage(
    gate17_with_methadone_assessment, gate17_no_meds_assessment,
):
    """H.G212 — 1 con meds + 1 sin meds → gap 50% para ese gate."""
    block = aggregate_gates_coverage([
        gate17_with_methadone_assessment, gate17_no_meds_assessment
    ])["ddi_cross_alerts_coverage"]
    gap = block["gates_with_meds_gap"]["qtc_prolongation_grade3_for_enzalutamide"]
    assert gap["missing_meds_count"] == 1
    assert gap["percentage_of_gate"] == 50.0


# ──────────────────────────────────────────────────────────────────────
# H.G213 — Distribución por severity
# ──────────────────────────────────────────────────────────────────────


def test_severity_distribution_aggregated(
    gate17_with_methadone_assessment,
    gate19_with_bupropion_assessment,
    gate3_with_spironolactone_assessment,
):
    """H.G213 — Severity acumulada de varias categorías DDI."""
    block = aggregate_gates_coverage([
        gate17_with_methadone_assessment,
        gate19_with_bupropion_assessment,
        gate3_with_spironolactone_assessment,
    ])["ddi_cross_alerts_coverage"]
    by_sev = block["by_severity"]
    # Sum de cross_alerts por severidad debe ser >= total_cross_alerts
    total_sev = sum(by_sev.values())
    assert total_sev == block["total_cross_alerts"]
    # Esperamos al menos contraindicated (espironolactona)
    assert "contraindicated" in by_sev


# ──────────────────────────────────────────────────────────────────────
# H.G214 — Cross-alerts por gate con breakdown por categoría
# ──────────────────────────────────────────────────────────────────────


def test_by_gate_includes_category_breakdown(
    gate19_with_bupropion_assessment,
):
    """H.G214 — by_gate[gate19] tiene by_category con seizure_threshold."""
    block = aggregate_gates_coverage(
        [gate19_with_bupropion_assessment]
    )["ddi_cross_alerts_coverage"]
    by_gate = block["by_gate"]
    assert "arsi_in_cognitive_decline_grade2" in by_gate
    gate_data = by_gate["arsi_in_cognitive_decline_grade2"]
    assert "by_category" in gate_data
    assert "seizure_threshold" in gate_data["by_category"]


def test_by_gate_percentage_of_gate_calculated(
    gate17_with_methadone_assessment,
):
    """H.G214.b — by_gate[gate17].percentage_of_gate = 100% si todos los
    triggers tienen cross-alerts."""
    block = aggregate_gates_coverage(
        [gate17_with_methadone_assessment]
    )["ddi_cross_alerts_coverage"]
    gate_data = block["by_gate"]["qtc_prolongation_grade3_for_enzalutamide"]
    assert gate_data["percentage_of_gate"] == 100.0


# ──────────────────────────────────────────────────────────────────────
# H.G215 — Alerta gates_with_high_ddi_burden
# ──────────────────────────────────────────────────────────────────────


def test_gate_with_100pct_ddi_appears_in_high_burden(
    gate19_with_bupropion_assessment,
):
    """H.G215 — Gate con 100% cross-alerts aparece en gates_with_high_ddi_burden."""
    coverage = aggregate_gates_coverage([gate19_with_bupropion_assessment])
    assert "arsi_in_cognitive_decline_grade2" in coverage["alerts"]["gates_with_high_ddi_burden"]


def test_gate_without_cross_alerts_not_in_high_burden(
    gate17_no_meds_assessment,
):
    """H.G215.b — Gate sin cross alerts (porque sin meds) NO aparece en
    gates_with_high_ddi_burden."""
    coverage = aggregate_gates_coverage([gate17_no_meds_assessment])
    assert "qtc_prolongation_grade3_for_enzalutamide" not in coverage[
        "alerts"]["gates_with_high_ddi_burden"]


# ──────────────────────────────────────────────────────────────────────
# H.G216 — Alerta gates_with_critical_meds_gap
# ──────────────────────────────────────────────────────────────────────


def test_gate_with_100pct_meds_gap_appears_in_critical(
    gate17_no_meds_assessment,
):
    """H.G216 — Gate con 100% meds gap aparece en gates_with_critical_meds_gap."""
    coverage = aggregate_gates_coverage([gate17_no_meds_assessment])
    assert "qtc_prolongation_grade3_for_enzalutamide" in coverage[
        "alerts"]["gates_with_critical_meds_gap"]


# ──────────────────────────────────────────────────────────────────────
# H.G217 — Heatmap secundario build_ddi_heatmap_data
# ──────────────────────────────────────────────────────────────────────


def test_ddi_heatmap_empty_with_no_cross_alerts():
    """H.G217 — DDI heatmap vacío cuando no hay cross alerts."""
    coverage = aggregate_gates_coverage([])
    hm = build_ddi_heatmap_data(coverage)
    assert hm["rows"] == []
    assert hm["cols"] == []
    assert hm["matrix"] == []
    assert hm["max_count"] == 0


def test_ddi_heatmap_structure_with_cross_alerts(
    gate17_with_methadone_assessment, gate19_with_bupropion_assessment,
):
    """H.G218 — DDI heatmap incluye gates como rows + categorías como cols."""
    coverage = aggregate_gates_coverage([
        gate17_with_methadone_assessment, gate19_with_bupropion_assessment
    ])
    hm = build_ddi_heatmap_data(coverage)
    assert "qtc_prolongation_grade3_for_enzalutamide" in hm["rows"]
    assert "arsi_in_cognitive_decline_grade2" in hm["rows"]
    assert "qtc_prolongation" in hm["cols"]
    assert "seizure_threshold" in hm["cols"]
    assert hm["max_count"] >= 1


def test_ddi_heatmap_categories_total(
    gate17_with_methadone_assessment, gate19_with_bupropion_assessment,
):
    """H.G218.b — categories_total tiene cada categoría con su sumatoria."""
    coverage = aggregate_gates_coverage([
        gate17_with_methadone_assessment, gate19_with_bupropion_assessment
    ])
    hm = build_ddi_heatmap_data(coverage)
    assert "qtc_prolongation" in hm["categories_total"]
    assert "seizure_threshold" in hm["categories_total"]


def test_ddi_heatmap_matrix_shape_consistent(
    gate17_with_methadone_assessment,
):
    """H.G219 — matrix.length == rows.length, matrix[0].length == cols.length."""
    coverage = aggregate_gates_coverage([gate17_with_methadone_assessment])
    hm = build_ddi_heatmap_data(coverage)
    assert len(hm["matrix"]) == len(hm["rows"])
    if hm["matrix"]:
        assert all(len(row) == len(hm["cols"]) for row in hm["matrix"])


# ──────────────────────────────────────────────────────────────────────
# H.G220 — Endpoint Flask /api/gates-coverage-dashboard incluye ddi_heatmap
# ──────────────────────────────────────────────────────────────────────


def test_api_endpoint_returns_ddi_heatmap_key():
    """H.G220 — Endpoint /api/gates-coverage-dashboard incluye ddi_heatmap."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True})
    with flask_app.test_client() as client:
        r = client.get("/api/gates-coverage-dashboard")
        assert r.status_code == 200
        data = r.get_json()
        assert data.get("success") is True
        assert "ddi_heatmap" in data
        assert "ddi_cross_alerts_coverage" in data["coverage"]


def test_api_ddi_block_structure_complete():
    """H.G221 — La respuesta JSON tiene la estructura DDI completa."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True})
    with flask_app.test_client() as client:
        r = client.get("/api/gates-coverage-dashboard")
        assert r.status_code == 200
        ddi = r.get_json()["coverage"]["ddi_cross_alerts_coverage"]
        for key in ("total_with_medications", "total_cross_alerts",
                    "by_gate", "by_category", "by_severity", "gates_with_meds_gap"):
            assert key in ddi


# ──────────────────────────────────────────────────────────────────────
# H.G222 — Página HTML renderiza la sección Razonamiento cruzado
# ──────────────────────────────────────────────────────────────────────


def test_html_page_includes_razonamiento_cruzado_section():
    """H.G222 — Template HTML expone secciones del catálogo expandido (LXXXII enriqueció el dashboard a 89 gates).

    Faubot LXXXIV.b: el dashboard fue overhauled en LXXXII; "Razonamiento cruzado" + "Faubot XVI"
    fueron reemplazados por el catálogo completo (89 gates LXXXIV.b). Asertamos las secciones
    actuales que confirman la cobertura clínica de los gates pivotal.
    """
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True})
    with flask_app.test_client() as client:
        r = client.get("/gates-coverage-dashboard")
        assert r.status_code == 200
        html = r.data.decode("utf-8")
        assert "Cobertura clínica de gates pivotal" in html
        assert "Catálogo completo" in html
        assert "gates pivotal" in html
        # Faubot label persiste (formato actual: "Faubot · YYYY-MM-DD ROMAN")
        assert "Faubot" in html


# ──────────────────────────────────────────────────────────────────────
# H.G223 — Backward-compat: heatmap principal sigue funcionando
# ──────────────────────────────────────────────────────────────────────


def test_main_heatmap_unchanged_by_ddi_extension(
    gate17_with_methadone_assessment, gate19_with_bupropion_assessment,
):
    """H.G223 — build_heatmap_data (principal) sigue funcionando sin cambios."""
    coverage = aggregate_gates_coverage([
        gate17_with_methadone_assessment, gate19_with_bupropion_assessment
    ])
    hm = build_heatmap_data(coverage)
    # Estructura clásica intacta
    for key in ("rows", "cols", "matrix", "max_count", "max_percentage"):
        assert key in hm


def test_classic_coverage_block_intact(
    gate17_with_methadone_assessment, healthy_assessment,
):
    """H.G223.b — Bloques originales (gate_coverage, state_coverage,
    field_capture_coverage) siguen presentes con la estructura previa."""
    coverage = aggregate_gates_coverage([
        gate17_with_methadone_assessment, healthy_assessment
    ])
    assert "gate_coverage" in coverage
    assert "state_coverage" in coverage
    assert "field_capture_coverage" in coverage
    assert "alerts" in coverage


# ──────────────────────────────────────────────────────────────────────
# H.G224 — Cohorte mixta: agregación end-to-end completa
# ──────────────────────────────────────────────────────────────────────


def test_mixed_cohort_aggregation_end_to_end(
    healthy_assessment,
    gate17_with_methadone_assessment,
    gate17_no_meds_assessment,
    gate19_with_bupropion_assessment,
    gate3_with_spironolactone_assessment,
):
    """H.G224 — Cohorte mixta de 5 pacientes produce agregación coherente."""
    cohort = [
        healthy_assessment,
        gate17_with_methadone_assessment,
        gate17_no_meds_assessment,
        gate19_with_bupropion_assessment,
        gate3_with_spironolactone_assessment,
    ]
    coverage = aggregate_gates_coverage(cohort)
    assert coverage["total_assessments"] == 5
    assert coverage["total_with_gates"] == 4

    ddi = coverage["ddi_cross_alerts_coverage"]
    # 4 con meds (healthy, gate17_with_meth, gate19_bupr, gate3_spiro)
    assert ddi["total_with_medications"] == 4
    # 3 con cross-alerts (gate17_meth, gate19_bupr, gate3_spiro)
    assert ddi["total_with_cross_alerts"] == 3
    # Al menos 3 categorías diferentes activas
    assert len(ddi["by_category"]) >= 3
    # Gap de meds en gate17 (1 sin meds)
    gap = ddi["gates_with_meds_gap"].get("qtc_prolongation_grade3_for_enzalutamide", {})
    assert gap.get("missing_meds_count", 0) == 1


# ──────────────────────────────────────────────────────────────────────
# H.G225 — Filtrado: cross-alerts respeta categoría relevante por gate
# ──────────────────────────────────────────────────────────────────────


def test_qtc_gate_excludes_cyp3a4_meds_from_cross():
    """H.G225 — Gate 17 (qtc_prolongation) NO genera cross con apixaban
    (cyp3a4_induction)."""
    a = {
        "state": "m1_crpc",
        "input_snapshot": {"qtc_ms": 520, "current_medications": "apixaban"},
        "result_snapshot": {"pivotal_contraindication_gates": [
            {"code": "qtc_prolongation_grade3_for_enzalutamide",
             "triggered": True, "severity": "contraindicated"}
        ]},
    }
    block = aggregate_gates_coverage([a])["ddi_cross_alerts_coverage"]
    # apixaban+enzalutamida es cyp3a4_induction, NO qtc_prolongation
    # Por tanto el cross-check filtra y NO reporta nada.
    assert block["total_cross_alerts"] == 0


# ──────────────────────────────────────────────────────────────────────
# H.G226 — Categorías totales coherentes con suma celda a celda
# ──────────────────────────────────────────────────────────────────────


def test_categories_total_equals_sum_of_matrix_cells(
    gate17_with_methadone_assessment, gate19_with_bupropion_assessment,
    gate3_with_spironolactone_assessment,
):
    """H.G226 — categories_total[cat] == sum de matrix cells por columna."""
    coverage = aggregate_gates_coverage([
        gate17_with_methadone_assessment,
        gate19_with_bupropion_assessment,
        gate3_with_spironolactone_assessment,
    ])
    hm = build_ddi_heatmap_data(coverage)
    for col_idx, cat in enumerate(hm["cols"]):
        sum_col = sum(row[col_idx]["count"] for row in hm["matrix"])
        assert sum_col == hm["categories_total"][cat], (
            f"Inconsistencia en categoría {cat}: "
            f"matrix sum={sum_col} vs categories_total={hm['categories_total'][cat]}"
        )


# ──────────────────────────────────────────────────────────────────────
# H.G227 — Robustez: input_snapshot None no rompe agregación
# ──────────────────────────────────────────────────────────────────────


def test_assessment_with_missing_input_snapshot():
    """H.G227 — assessment sin input_snapshot no rompe la agregación."""
    a = {
        "state": "m1_crpc",
        "result_snapshot": {"pivotal_contraindication_gates": []},
    }
    coverage = aggregate_gates_coverage([a])
    assert coverage["total_assessments"] == 1
    assert coverage["ddi_cross_alerts_coverage"]["total_cross_alerts"] == 0


# ──────────────────────────────────────────────────────────────────────
# H.G228 — Métricas porcentuales correctas
# ──────────────────────────────────────────────────────────────────────


def test_percentage_with_medications_calculated_correctly():
    """H.G228 — % medicaciones calculado sobre total de assessments."""
    cohort = [
        {"state": "m1_crpc", "input_snapshot": {"current_medications": "metadona"},
         "result_snapshot": {"pivotal_contraindication_gates": []}},
        {"state": "m1_crpc", "input_snapshot": {},
         "result_snapshot": {"pivotal_contraindication_gates": []}},
    ]
    block = aggregate_gates_coverage(cohort)["ddi_cross_alerts_coverage"]
    assert block["total_with_medications"] == 1
    assert block["percentage_with_medications"] == 50.0
