from __future__ import annotations

from typing import Any

_CRITICAL_FIELDS_BY_STATE = {'diagnostic_workup': [{'field': 'psa_value', 'gate_code': '_baseline', 'severity': 'critical'},
                       {'field': 'phi_score_value',
                        'gate_code': 'pre_biopsy_risk_calculators_phi_4kscore',
                        'reason': 'PHI reduce biopsias innecesarias 25-30%',
                        'severity': 'informational'},
                       {'field': 'fourkscore_value',
                        'gate_code': 'pre_biopsy_risk_calculators_phi_4kscore',
                        'reason': '4Kscore reduce biopsias innecesarias 30-40%',
                        'severity': 'informational'},
                       {'field': 'psa_density',
                        'gate_code': 'pre_biopsy_risk_calculators_phi_4kscore',
                        'reason': 'PSAD ≥0.15 indica biopsia (EAU 2026)',
                        'severity': 'informational'}],
 'localized_initial': [{'field': 'gleason_primary',
                        'gate_code': '_baseline',
                        'reason': 'Necesario para risk stratification NCCN/EAU',
                        'severity': 'critical'},
                       {'field': 'gleason_secondary',
                        'gate_code': '_baseline',
                        'reason': 'Necesario para risk stratification NCCN/EAU',
                        'severity': 'critical'},
                       {'field': 'psa_value',
                        'gate_code': '_baseline',
                        'reason': 'PSA es input fundamental para todos los nomogramas',
                        'severity': 'critical'},
                       {'field': 'clinical_t_stage',
                        'gate_code': '_baseline',
                        'reason': 'Estadío clínico T necesario para staging TNM',
                        'severity': 'critical'},
                       {'field': 'ecog_current',
                        'gate_code': '_baseline',
                        'reason': 'Performance status afecta elegibilidad tratamientos',
                        'severity': 'recommended'},
                       {'field': 'anticoagulant_agent',
                        'gate_code': 'anticoagulant_rp_bleeding_risk',
                        'reason': 'Sin captura, gate 56 no detectará riesgo bleed RP+PLND ↑4×',
                        'severity': 'recommended'},
                       {'field': 'history_of_turp',
                        'gate_code': 'turp_brachytherapy_contraindication',
                        'reason': 'Sin captura, gate 59 no detectará contraindicación brachy '
                                  'LDR/HDR',
                        'severity': 'recommended'},
                       {'field': 'svi_risk_nomogram_percent',
                        'gate_code': 'svi_risk_high_rp_efficiency_warning',
                        'reason': 'Calcular MSKCC nomogram para detectar SVI risk >30% (RP '
                                  'sub-óptima)',
                        'severity': 'informational'}],
 'm0_crpc': [{'field': 'psa_doubling_time_months',
              'gate_code': 'psa_doubling_time_progressive',
              'reason': 'PSADT define elegibilidad ARPI (SPARTAN/PROSPER/ARAMIS)',
              'severity': 'critical'},
             {'field': 'castrate_testosterone_status_confirmed',
              'gate_code': '_baseline',
              'reason': 'Castración confirmada criterio definicional m0CRPC',
              'severity': 'critical'},
             {'field': 'hrr_status',
              'gate_code': 'hrr_status_required_before_parp_inhibitor',
              'reason': 'Pre-emptive HRR testing si PARP futuro considerado',
              'severity': 'recommended'}],
 'm1_crpc': [{'field': 'hrr_status',
              'gate_code': 'hrr_status_required_before_parp_inhibitor',
              'reason': 'HRR confirmation OBLIGATORIA pre-PARP (response rate <15% sin)',
              'severity': 'critical'},
             {'field': 'ar_v7_status',
              'gate_code': 'ar_v7_positive_arpi_resistance_pathway',
              'reason': 'AR-V7+ predice resistencia ARPI — switch taxane temprano',
              'severity': 'recommended'},
             {'field': 'ecog_current',
              'gate_code': 'ecog_decline_alert',
              'reason': 'ECOG decline determina pathway palliative vs activo',
              'severity': 'critical'},
             {'field': 'psma_pet_progression_documented',
              'gate_code': 'psma_pet_progression_auto_trigger',
              'reason': 'PSMA progression dispara rPFS event PCWG3',
              'severity': 'recommended'},
             {'field': 'esas_pain_score',
              'gate_code': 'esas_severity_alert',
              'reason': 'ESAS multi-síntoma identifica distress + palliative referral',
              'severity': 'informational'}],
 'mcspc_high_volume': [{'field': 'hrr_status',
                        'gate_code': 'hrr_status_required_before_parp_inhibitor',
                        'reason': 'HRR confirmation OBLIGATORIA antes de cualquier PARP inhibitor',
                        'severity': 'critical'},
                       {'field': 'ecog_current',
                        'gate_code': '_baseline',
                        'reason': 'Performance status define elegibilidad chemo (docetaxel)',
                        'severity': 'critical'},
                       {'field': 'histology_subtype',
                        'gate_code': 'atypical_histology_escalation_nepc_intraductal',
                        'reason': 'Detectar NEPC/intraductal/cribriform — peor pronóstico, manejo '
                                  'distinto',
                        'severity': 'recommended'}],
 'mcspc_low_volume_sync_oligo': [{'field': 'hrr_status',
                                  'gate_code': 'hrr_status_required_before_parp_inhibitor',
                                  'reason': 'HRR confirmation antes PARP inhibitor',
                                  'severity': 'critical'},
                                 {'field': 'total_metastases_count',
                                  'gate_code': 'oligometastatic_sbrt_eligibility',
                                  'reason': 'Determinar oligometastatic eligibility para SBRT '
                                            '(STOMP/ORIOLE)',
                                  'severity': 'recommended'}],
 'post_prostatectomy': [{'field': 'psa_value',
                         'gate_code': '_baseline',
                         'reason': 'PSA post-RP necesario para detectar BCR',
                         'severity': 'critical'},
                        {'field': 'psa_doubling_time_months',
                         'gate_code': 'psa_velocity_bcr_aggressive',
                         'reason': 'PSADT post-RP detecta BCR agresivo (Stephenson)',
                         'severity': 'recommended'},
                        {'field': 'salvage_rt_consideration_active',
                         'gate_code': 'localized_bcr_adjuvant_trials_completion',
                         'reason': 'Activa info de RAVES/ARTISTIC/RTOG 9601 trials',
                         'severity': 'informational'}],
 'recurrence_bcr': [{'field': 'psa_value', 'gate_code': '_baseline', 'severity': 'critical'},
                    {'field': 'psa_doubling_time_months',
                     'gate_code': 'psa_velocity_bcr_aggressive',
                     'reason': 'PSADT define BCR aggressive vs indolent → elegibilidad salvage',
                     'severity': 'critical'}]}

_UNIVERSAL_CRITICAL_FIELDS = [{'field': 'given_name', 'reason': 'Identificación del paciente', 'severity': 'critical'},
 {'field': 'family_name', 'reason': 'Identificación del paciente', 'severity': 'critical'},
 {'field': 'biological_sex',
  'reason': 'ProstaMed solo procesa pacientes con próstata',
  'severity': 'critical'}]


def _is_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in {"", "none", "null", "unknown", "desconocido", "no documentado"}
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def detect_missing_critical_fields(
    payload: dict[str, Any],
    clinical_state: str | None = None,
) -> list[dict[str, Any]]:
    """Retorna warnings de campos críticos missing.

    LXCIX.3: `clinical_state` ahora es opcional. Si se omite, sólo evalúa
    universal critical fields (given_name, family_name, biological_sex).
    """
    payload = payload or {}
    warnings: list[dict[str, Any]] = []
    expected = list(_UNIVERSAL_CRITICAL_FIELDS)
    if clinical_state:
        expected += list(_CRITICAL_FIELDS_BY_STATE.get(str(clinical_state or ""), []))
    for spec in expected:
        field = spec.get("field")
        if field and not _is_present(payload.get(field)):
            warnings.append({**spec, "field": field, "missing": True})
    return warnings


def _grade(coverage: float) -> str:
    """Legacy descriptive grade (LXXXI)."""
    if coverage >= 0.95:
        return "excellent"
    if coverage >= 0.8:
        return "good"
    if coverage >= 0.6:
        return "partial"
    return "insufficient"


def _letter_grade(coverage_percent: float) -> str:
    """LXCIX.3: A-F letter grade based on coverage percent (0-100).

    A: >=90%, B: >=80%, C: >=65%, D: >=50%, F: <50%.
    """
    if coverage_percent >= 90:
        return "A"
    if coverage_percent >= 80:
        return "B"
    if coverage_percent >= 65:
        return "C"
    if coverage_percent >= 50:
        return "D"
    return "F"


def summarize_completeness(
    payload: dict[str, Any],
    clinical_state: str | None = None,
) -> dict[str, Any]:
    """Resumen de completeness con dual API (legacy + LXCIX.3 keys).

    Returns dict with:
      - `state` + `clinical_state` (LXCIX.3 alias)
      - `coverage` (0.0-1.0) + `gate_coverage_percent` (0-100, LXCIX.3)
      - `grade` (legacy descriptive) + `completeness_grade` (A-F, LXCIX.3)
      - `missing_count`, `expected_count`, `missing_fields`, `by_severity`
    """
    expected = list(_UNIVERSAL_CRITICAL_FIELDS)
    if clinical_state:
        expected += list(_CRITICAL_FIELDS_BY_STATE.get(str(clinical_state or ""), []))
    warnings = detect_missing_critical_fields(payload or {}, clinical_state)
    total = len(expected)
    missing = len(warnings)
    coverage = 1.0 if total == 0 else max(0.0, (total - missing) / total)
    coverage_percent = round(coverage * 100, 1)
    by_severity: dict[str, int] = {}
    for warning in warnings:
        severity = str(warning.get("severity") or "recommended")
        by_severity[severity] = by_severity.get(severity, 0) + 1
    return {
        "clinical_state": clinical_state,
        "state": clinical_state,  # LXCIX.3 alias
        "coverage": coverage,
        "gate_coverage_percent": coverage_percent,  # LXCIX.3
        "grade": _grade(coverage),
        "completeness_grade": _letter_grade(coverage_percent),  # LXCIX.3
        "missing_count": missing,
        "expected_count": total,
        "missing_fields": warnings,
        "by_severity": by_severity,
    }


__all__ = ["detect_missing_critical_fields", "summarize_completeness"]
