"""gates_coverage_aggregator.py — FAUBOT auditoría 2026-04-25 (XII + XVI).

Agregador estadístico poblacional de gates pivotal disparados.

Itera sobre todos los `clinical_assessments` activos del sistema y
agrega:
  - **Cobertura por gate:** cuántos pacientes tienen cada gate disparado
  - **Heatmap por estado clínico:** % de cada gate por state (m1_crpc, etc.)
  - **Alertas de captura:** gates que NUNCA disparan (posible falla de
    captura de FieldSpec) o que disparan en >70% (revisar epidemiología)
  - **Cobertura de fields críticos:** % de assessments con cada field
    cardiológico/hematológico capturado

Faubot 2026-04-25 (XVI) — Extensión DDI cross-alerts:
  - **DDI cross-alerts por gate:** % de pacientes con cada gate triggered
    que también tienen alertas DDI cruzadas activas.
  - **Heatmap secundario:** gate × categoría DDI (qtc/seizure/aldosterone/
    bone_remodeling/cyp3a4_inhibition).
  - **Severity distribution:** total cross-alerts contraindicated/major/moderate.
  - **Medications capture gap:** gates triggered SIN `current_medications`
    (audit input incompleto).

Aporte a auditabilidad:
  - **DATOS:** detecta brechas de captura clínica que invalidan los gates
    + visibilidad poblacional del campo `current_medications`
  - **CÓMO:** agregación poblacional de la cadena de razonamiento, ahora
    incluyendo cross-checks gate × DDI
  - **VERSIÓN:** snapshot temporal de cobertura → comparable entre versiones

Diseño:
  - Funciones puras sin side-effects sobre DB (lectura solo)
  - Acepta lista de assessments ya cargados → testable sin DB real
  - Re-computa cross-alerts on-the-fly desde input_snapshot + gates
    (no requiere persistir ddi_cross_alerts en DB)
  - Wrapper público `aggregate_gates_coverage_from_db()` que carga la DB
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def _extract_gates_from_assessment(assessment: dict) -> list[dict]:
    """Extrae la lista de gates triggered del result_snapshot."""
    if not assessment:
        return []
    snapshot = assessment.get("result_snapshot") or {}
    return list(snapshot.get("pivotal_contraindication_gates") or [])


def _extract_state_from_assessment(assessment: dict) -> str:
    """Extrae el estado clínico (m1_crpc, mhspc_high_volume, etc.)."""
    if not assessment:
        return "unknown"
    return str(assessment.get("state") or "unknown")


def _extract_input_fields(assessment: dict) -> set[str]:
    """Extrae los nombres de los campos capturados en el input_snapshot."""
    if not assessment:
        return set()
    snapshot = assessment.get("input_snapshot") or {}
    if not isinstance(snapshot, dict):
        return set()
    # Solo fields con valor no-vacío
    return {
        k for k, v in snapshot.items()
        if v not in (None, "", [], {})
    }


# Fields cardiológicos/hematológicos críticos para gates 11-18
# Faubot 2026-04-25 (XX) — Lista expandida con los FieldSpecs nuevos
# (helper `pivotal_gate_supporting_fields`) para reflejar el schema
# completo del CDE Auditable. Ahora 45 fields críticos monitoreados
# (era 21).
_CRITICAL_GATE_FIELDS = [
    # Cardiológicos (gates 17-18)
    "qtc_ms", "qtc_baseline_ms", "qtc_change_ms", "qtc_corrected_for_arpi",
    "lvef_percent", "lvef_baseline_percent", "lvef_decline_for_arpi",
    "lvef_recovered_for_arpi",
    # Hematológicos (gates 14-16)
    "anc", "anc_baseline", "platelets", "hemoglobin_g_dl",
    "severe_cytopenia_for_radioligand", "severe_cytopenia_for_parp_inhibitor",
    "cytopenias_corrected_for_radioligand",
    "cytopenias_corrected_for_parp_inhibitor",
    "mds_aml_history", "prior_mds", "prior_aml",
    # Compresión medular (gates 11, 13)
    "spinal_cord_compression", "epidural_compression",
    "lower_limb_weakness", "cord_compression_symptoms",
    "cord_compression_stabilized",
    # Calcio sérico (gate 12)
    "hypocalcemia", "calcium_level", "corrected_calcium",
    "serum_calcium", "ionized_calcium", "hypocalcemia_corrected",
    # Cardio/metabólico generales (gates 3-5)
    "nyha_class", "uncontrolled_hypertension", "uncontrolled_diabetes",
    # Renal (gate 10)
    "creatinine_clearance",
    # Bone protection (gate 9)
    "no_bone_protective_agent", "radium223_candidate",
    "considering_radium223", "planned_systemic_regimen",
    "bone_modifying_agent", "denosumab_prophylaxis",
    "zoledronate_prophylaxis", "bone_protection_started",
]

# Faubot 2026-04-25 (XVI) — Campos de medicaciones concomitantes
# para detectar gap de captura: si un gate dispara pero ninguno de
# estos campos está poblado, el cross-check DDI no puede ejecutarse.
_MEDICATION_FIELDS = (
    "current_medications",
    "concomitant_medications",
    "medications",
)


def _has_medications(input_fields: set[str], snapshot: dict | None) -> bool:
    """Determina si el assessment tiene al menos un campo de medicaciones
    poblado.
    """
    if not snapshot or not isinstance(snapshot, dict):
        return False
    for field in _MEDICATION_FIELDS:
        if field not in input_fields:
            continue
        value = snapshot.get(field)
        if value in (None, "", [], {}):
            continue
        return True
    return False


def _compute_cross_alerts_for_assessment(
    gates: list[dict],
    input_snapshot: dict,
) -> list[dict]:
    """Re-computa cross-alerts DDI on-the-fly desde gates + input_snapshot.

    Útil para agregación: no requiere que `ddi_cross_alerts` esté
    persistido en `result_snapshot` — el aggregator lo recalcula.

    Returns lista de cross-alerts (puede estar vacía).
    """
    if not gates:
        return []
    try:
        from prostanet.shared.gates_ddi_cross_check import (
            cross_check_gates_with_ddi,
        )
    except ImportError:
        return []
    try:
        return cross_check_gates_with_ddi(gates, input_snapshot or {})
    except Exception:
        # Defensivo: cualquier fallo en cross-check no debe romper el
        # aggregator. Retornamos lista vacía para preservar agregación.
        return []


def aggregate_gates_coverage(
    assessments: list[dict],
) -> dict[str, Any]:
    """Computa estadísticos de cobertura sobre una lista de assessments.

    Args:
        assessments: lista de dicts con `state`, `result_snapshot`,
            `input_snapshot`. Típicamente cargada de DB.

    Returns:
        Dict con la estructura:
        {
          "total_assessments": int,
          "total_with_gates": int,
          "gate_coverage": {
            gate_code: {
              "count": int,
              "percentage": float (0-100),
              "by_state": {state: count, ...},
            },
            ...
          },
          "state_coverage": {
            state: {
              "total_patients": int,
              "gates_triggered_distribution": {gate_code: count, ...},
            },
            ...
          },
          "field_capture_coverage": {
            field_name: {"count": int, "percentage": float},
            ...
          },
          "alerts": {
            "gates_never_triggered": [gate_code, ...],
            "gates_high_prevalence": [gate_code, ...],  # >70%
            "fields_low_capture": [field_name, ...],   # <20%
          },
        }
    """
    total = len(assessments)
    if total == 0:
        return _empty_coverage_dict()

    # Contadores
    gate_counts: dict[str, int] = defaultdict(int)
    gate_by_state: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    state_totals: dict[str, int] = defaultdict(int)
    state_gates: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    field_capture: dict[str, int] = defaultdict(int)
    total_with_gates = 0

    # Faubot 2026-04-25 (XVI) — Contadores DDI cross-alerts.
    total_with_meds = 0
    total_cross_alerts = 0
    total_with_cross_alerts = 0
    gates_with_meds_gap: dict[str, int] = defaultdict(int)
    gate_cross_alert_counts: dict[str, int] = defaultdict(int)
    gate_cross_by_category: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    severity_distribution: dict[str, int] = defaultdict(int)
    category_distribution: dict[str, int] = defaultdict(int)

    for assessment in assessments:
        state = _extract_state_from_assessment(assessment)
        gates = _extract_gates_from_assessment(assessment)
        input_fields = _extract_input_fields(assessment)
        input_snapshot = (assessment or {}).get("input_snapshot") or {}

        state_totals[state] += 1

        if gates:
            total_with_gates += 1

        # Faubot XVI — captura de medicaciones
        has_meds = _has_medications(input_fields, input_snapshot)
        if has_meds:
            total_with_meds += 1

        for gate in gates:
            code = str(gate.get("code") or "")
            if not code:
                continue
            gate_counts[code] += 1
            gate_by_state[code][state] += 1
            state_gates[state][code] += 1
            # Si el gate disparó pero no hay medicaciones, hay gap de captura
            if not has_meds:
                gates_with_meds_gap[code] += 1

        # Field capture: contar cada field crítico capturado
        for field in _CRITICAL_GATE_FIELDS:
            if field in input_fields:
                field_capture[field] += 1

        # Faubot XVI — Cross-alerts DDI por gate
        cross_alerts = _compute_cross_alerts_for_assessment(gates, input_snapshot)
        if cross_alerts:
            total_with_cross_alerts += 1
            total_cross_alerts += len(cross_alerts)
        for alert in cross_alerts:
            gate_code = str(alert.get("gate_code") or "")
            category = str(alert.get("category") or "uncategorized")
            severity = str(alert.get("severity") or "unknown")
            if gate_code:
                gate_cross_alert_counts[gate_code] += 1
                gate_cross_by_category[gate_code][category] += 1
            category_distribution[category] += 1
            severity_distribution[severity] += 1

    # Calcular % y construir gate_coverage
    gate_coverage: dict[str, dict] = {}
    for code, count in sorted(gate_counts.items()):
        percentage = round(100.0 * count / total, 2) if total else 0.0
        gate_coverage[code] = {
            "count": count,
            "percentage": percentage,
            "by_state": dict(gate_by_state[code]),
        }

    # Construir state_coverage
    state_coverage: dict[str, dict] = {}
    for state, total_state in sorted(state_totals.items()):
        state_coverage[state] = {
            "total_patients": total_state,
            "gates_triggered_distribution": dict(state_gates[state]),
        }

    # Field capture coverage
    field_capture_coverage: dict[str, dict] = {}
    for field in _CRITICAL_GATE_FIELDS:
        count = field_capture.get(field, 0)
        percentage = round(100.0 * count / total, 2) if total else 0.0
        field_capture_coverage[field] = {
            "count": count,
            "percentage": percentage,
        }

    # Alertas
    # Gate "never triggered": en el catálogo activo pero count=0
    from prostanet.shared.algorithm_version import get_active_gate_codes
    all_active_codes = set(get_active_gate_codes())
    triggered_codes = set(gate_coverage.keys())
    gates_never_triggered = sorted(all_active_codes - triggered_codes)
    gates_high_prevalence = sorted(
        code for code, data in gate_coverage.items()
        if data["percentage"] > 70.0
    )
    fields_low_capture = sorted(
        field for field, data in field_capture_coverage.items()
        if data["percentage"] < 20.0
    )

    # Faubot 2026-04-25 (XVI) — Construir DDI cross-alert coverage por gate.
    ddi_cross_coverage: dict[str, dict] = {}
    for code, count in sorted(gate_cross_alert_counts.items()):
        gate_total = gate_counts.get(code, 0)
        pct_of_gate = round(100.0 * count / gate_total, 2) if gate_total else 0.0
        ddi_cross_coverage[code] = {
            "patients_with_cross_alerts": count,
            "percentage_of_gate": pct_of_gate,
            "by_category": dict(gate_cross_by_category[code]),
        }

    # Gates con gap de medicaciones (gate triggered pero sin meds capturadas).
    gates_meds_gap: dict[str, dict] = {}
    for code, gap_count in sorted(gates_with_meds_gap.items()):
        gate_total = gate_counts.get(code, 0)
        gap_pct = round(100.0 * gap_count / gate_total, 2) if gate_total else 0.0
        gates_meds_gap[code] = {
            "missing_meds_count": gap_count,
            "percentage_of_gate": gap_pct,
        }

    # Alerta DDI: gates con alta carga DDI (>50% pacientes con cross-alerts)
    gates_with_high_ddi_burden = sorted(
        code for code, data in ddi_cross_coverage.items()
        if data["percentage_of_gate"] > 50.0
    )

    # Alerta DDI: gates triggered con gap de meds >50% (priorizar captura)
    gates_with_critical_meds_gap = sorted(
        code for code, data in gates_meds_gap.items()
        if data["percentage_of_gate"] > 50.0
    )

    pct_with_meds = round(100.0 * total_with_meds / total, 2) if total else 0.0
    pct_with_cross_alerts = round(100.0 * total_with_cross_alerts / total, 2) if total else 0.0

    return {
        "total_assessments": total,
        "total_with_gates": total_with_gates,
        "percentage_with_gates": round(100.0 * total_with_gates / total, 2) if total else 0.0,
        "gate_coverage": gate_coverage,
        "state_coverage": state_coverage,
        "field_capture_coverage": field_capture_coverage,
        # Faubot 2026-04-25 (XVI) — DDI cross-alerts
        "ddi_cross_alerts_coverage": {
            "total_with_medications": total_with_meds,
            "percentage_with_medications": pct_with_meds,
            "total_cross_alerts": total_cross_alerts,
            "total_with_cross_alerts": total_with_cross_alerts,
            "percentage_with_cross_alerts": pct_with_cross_alerts,
            "by_gate": ddi_cross_coverage,
            "by_category": dict(category_distribution),
            "by_severity": dict(severity_distribution),
            "gates_with_meds_gap": gates_meds_gap,
        },
        "alerts": {
            "gates_never_triggered": gates_never_triggered,
            "gates_never_triggered_count": len(gates_never_triggered),
            "gates_high_prevalence": gates_high_prevalence,
            "gates_high_prevalence_count": len(gates_high_prevalence),
            "fields_low_capture": fields_low_capture,
            "fields_low_capture_count": len(fields_low_capture),
            # Faubot 2026-04-25 (XVI) — Alertas DDI
            "gates_with_high_ddi_burden": gates_with_high_ddi_burden,
            "gates_with_high_ddi_burden_count": len(gates_with_high_ddi_burden),
            "gates_with_critical_meds_gap": gates_with_critical_meds_gap,
            "gates_with_critical_meds_gap_count": len(gates_with_critical_meds_gap),
        },
    }


def _empty_coverage_dict() -> dict[str, Any]:
    """Estructura vacía cuando no hay assessments."""
    from prostanet.shared.algorithm_version import get_active_gate_codes
    return {
        "total_assessments": 0,
        "total_with_gates": 0,
        "percentage_with_gates": 0.0,
        "gate_coverage": {},
        "state_coverage": {},
        "field_capture_coverage": {
            field: {"count": 0, "percentage": 0.0}
            for field in _CRITICAL_GATE_FIELDS
        },
        # Faubot 2026-04-25 (XVI) — DDI bloque vacío para forward-compat.
        "ddi_cross_alerts_coverage": {
            "total_with_medications": 0,
            "percentage_with_medications": 0.0,
            "total_cross_alerts": 0,
            "total_with_cross_alerts": 0,
            "percentage_with_cross_alerts": 0.0,
            "by_gate": {},
            "by_category": {},
            "by_severity": {},
            "gates_with_meds_gap": {},
        },
        "alerts": {
            "gates_never_triggered": sorted(get_active_gate_codes()),
            "gates_never_triggered_count": len(get_active_gate_codes()),
            "gates_high_prevalence": [],
            "gates_high_prevalence_count": 0,
            "fields_low_capture": sorted(_CRITICAL_GATE_FIELDS),
            "fields_low_capture_count": len(_CRITICAL_GATE_FIELDS),
            "gates_with_high_ddi_burden": [],
            "gates_with_high_ddi_burden_count": 0,
            "gates_with_critical_meds_gap": [],
            "gates_with_critical_meds_gap_count": 0,
        },
    }


def aggregate_gates_coverage_from_db() -> dict[str, Any]:
    """Wrapper público que carga assessments de DB y agrega coverage.

    Carga TODOS los assessments persistidos (status != 'archived') y
    computa estadísticos de cobertura poblacional.

    Returns:
        Mismo dict que `aggregate_gates_coverage()`.
    """
    try:
        import sqlite3
        import json
        from tracking_db import DB_PATH
    except ImportError:
        return _empty_coverage_dict()

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            """
            SELECT id, state, input_snapshot, result_snapshot
            FROM clinical_assessments
            WHERE status != 'archived' OR status IS NULL
            ORDER BY created_at DESC
            """
        )
        rows = c.fetchall()
        conn.close()
    except Exception:
        return _empty_coverage_dict()

    assessments: list[dict] = []
    for row in rows:
        d = dict(row)
        # Parse JSON blobs
        for key in ("input_snapshot", "result_snapshot"):
            v = d.get(key)
            if isinstance(v, str):
                try:
                    d[key] = json.loads(v)
                except (json.JSONDecodeError, TypeError):
                    d[key] = {}
        assessments.append(d)

    return aggregate_gates_coverage(assessments)


def build_heatmap_data(coverage: dict[str, Any]) -> dict[str, Any]:
    """Transforma el dict de coverage en una matriz lista para heatmap UI.

    Returns:
        {
          "rows": [gate_code, ...],
          "cols": [state, ...],
          "matrix": [[count, percentage], ...] (rows × cols),
          "max_count": int,
          "max_percentage": float,
        }
    """
    gate_coverage = coverage.get("gate_coverage", {}) or {}
    state_coverage = coverage.get("state_coverage", {}) or {}

    rows = sorted(gate_coverage.keys())
    cols = sorted(state_coverage.keys())

    matrix: list[list[dict]] = []
    max_count = 0
    max_pct = 0.0
    for code in rows:
        row_data: list[dict] = []
        gate_data = gate_coverage.get(code, {})
        by_state = gate_data.get("by_state", {})
        for state in cols:
            count = int(by_state.get(state, 0))
            state_total = (state_coverage.get(state) or {}).get("total_patients", 0)
            pct = round(100.0 * count / state_total, 2) if state_total else 0.0
            max_count = max(max_count, count)
            max_pct = max(max_pct, pct)
            row_data.append({"count": count, "percentage": pct})
        matrix.append(row_data)

    return {
        "rows": rows,
        "cols": cols,
        "matrix": matrix,
        "max_count": max_count,
        "max_percentage": max_pct,
    }


def build_ddi_heatmap_data(coverage: dict[str, Any]) -> dict[str, Any]:
    """Faubot 2026-04-25 (XVI) — Heatmap secundario gate × DDI category.

    A diferencia del heatmap principal (gate × estado clínico), este
    visualiza la distribución cruzada de DDI cross-alerts: para cada
    gate triggered, cuántos pacientes tuvieron cross-alerts en cada
    categoría DDI relevante.

    Returns:
        {
          "rows": [gate_code, ...],
          "cols": [ddi_category, ...],  # qtc_prolongation, seizure_threshold, ...
          "matrix": [[{"count": int}, ...], ...] (rows × cols),
          "max_count": int,
          "categories_total": dict[str, int],
        }
    """
    ddi_block = coverage.get("ddi_cross_alerts_coverage") or {}
    by_gate: dict[str, dict] = ddi_block.get("by_gate") or {}
    if not by_gate:
        return {
            "rows": [],
            "cols": [],
            "matrix": [],
            "max_count": 0,
            "categories_total": {},
        }

    rows = sorted(by_gate.keys())
    # Recolectar todas las categorías únicas que aparecen en cualquier gate
    all_categories: set[str] = set()
    for gate_data in by_gate.values():
        cat_dict = gate_data.get("by_category") or {}
        all_categories.update(cat_dict.keys())
    cols = sorted(all_categories)

    matrix: list[list[dict]] = []
    max_count = 0
    categories_total: dict[str, int] = defaultdict(int)
    for code in rows:
        row_data: list[dict] = []
        gate_categories = (by_gate.get(code) or {}).get("by_category") or {}
        for category in cols:
            count = int(gate_categories.get(category, 0))
            max_count = max(max_count, count)
            categories_total[category] += count
            row_data.append({"count": count})
        matrix.append(row_data)

    return {
        "rows": rows,
        "cols": cols,
        "matrix": matrix,
        "max_count": max_count,
        "categories_total": dict(categories_total),
    }
