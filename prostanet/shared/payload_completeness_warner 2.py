"""prostanet.shared.payload_completeness_warner — Faubot LXXXI #audit-pre-cortana A3.

Detecta fields críticos faltantes en payloads POST de UI v2 y emite warnings
(NO bloquea la captura — solo informa al médico que faltan datos para
disparar gates específicos según el estado clínico del paciente).

CONTEXTO:
La auditoría pre-Cortana detectó que `POST /api/register_patient` aceptaba
payloads parciales silenciosamente. Si faltan fields críticos para el state
clínico (e.g. paciente mCRPC sin captura de hrr_status), gates importantes
NO disparan y el médico NO sabe que su captura está incompleta.

ESTRATEGIA:
- NO bloquear (compatibilidad backward + workflows clínicos urgentes)
- Sí advertir con `missing_critical_warnings` en respuesta JSON
- Granular por estado clínico (localized vs mCRPC vs BCR vs etc.)

USO:
    from prostanet.shared.payload_completeness_warner import (
        detect_missing_critical_fields,
    )
    warnings = detect_missing_critical_fields(payload, clinical_state="mcrpc")
    # warnings = [{"field": "hrr_status", "gate": "...", "severity": "...", ...}]
"""
from __future__ import annotations

from typing import Any

# ───────────────────────────────────────────────────────────────────────────
# Definición de fields críticos por estado clínico
# ───────────────────────────────────────────────────────────────────────────
# Estructura: STATE → list of {field, gate_code, severity, reason}
# - severity: 'critical' (hard_block sin field) | 'recommended' (soft_warning) |
#             'informational' (informational gate)
# - reason: explicación clínica para el médico

_CRITICAL_FIELDS_BY_STATE: dict[str, list[dict[str, Any]]] = {
    # ─── LOCALIZED ──────────────────────────────────────────────
    "localized_initial": [
        {"field": "gleason_primary", "gate_code": "_baseline", "severity": "critical",
         "reason": "Necesario para risk stratification NCCN/EAU"},
        {"field": "gleason_secondary", "gate_code": "_baseline", "severity": "critical",
         "reason": "Necesario para risk stratification NCCN/EAU"},
        {"field": "psa_value", "gate_code": "_baseline", "severity": "critical",
         "reason": "PSA es input fundamental para todos los nomogramas"},
        {"field": "clinical_t_stage", "gate_code": "_baseline", "severity": "critical",
         "reason": "Estadío clínico T necesario para staging TNM"},
        {"field": "ecog_current", "gate_code": "_baseline", "severity": "recommended",
         "reason": "Performance status afecta elegibilidad tratamientos"},
        {"field": "anticoagulant_agent", "gate_code": "anticoagulant_rp_bleeding_risk",
         "severity": "recommended",
         "reason": "Sin captura, gate 56 no detectará riesgo bleed RP+PLND ↑4×"},
        {"field": "history_of_turp", "gate_code": "turp_brachytherapy_contraindication",
         "severity": "recommended",
         "reason": "Sin captura, gate 59 no detectará contraindicación brachy LDR/HDR"},
        {"field": "svi_risk_nomogram_percent", "gate_code": "svi_risk_high_rp_efficiency_warning",
         "severity": "informational",
         "reason": "Calcular MSKCC nomogram para detectar SVI risk >30% (RP sub-óptima)"},
    ],
    # ─── mCSPC ──────────────────────────────────────────────────
    "mcspc_high_volume": [
        {"field": "hrr_status", "gate_code": "hrr_status_required_before_parp_inhibitor",
         "severity": "critical",
         "reason": "HRR confirmation OBLIGATORIA antes de cualquier PARP inhibitor"},
        {"field": "ecog_current", "gate_code": "_baseline", "severity": "critical",
         "reason": "Performance status define elegibilidad chemo (docetaxel)"},
        {"field": "histology_subtype", "gate_code": "atypical_histology_escalation_nepc_intraductal",
         "severity": "recommended",
         "reason": "Detectar NEPC/intraductal/cribriform — peor pronóstico, manejo distinto"},
    ],
    "mcspc_low_volume_sync_oligo": [
        {"field": "hrr_status", "gate_code": "hrr_status_required_before_parp_inhibitor",
         "severity": "critical",
         "reason": "HRR confirmation antes PARP inhibitor"},
        {"field": "total_metastases_count", "gate_code": "oligometastatic_sbrt_eligibility",
         "severity": "recommended",
         "reason": "Determinar oligometastatic eligibility para SBRT (STOMP/ORIOLE)"},
    ],
    # ─── mCRPC ──────────────────────────────────────────────────
    "m1_crpc": [
        {"field": "hrr_status", "gate_code": "hrr_status_required_before_parp_inhibitor",
         "severity": "critical",
         "reason": "HRR confirmation OBLIGATORIA pre-PARP (response rate <15% sin)"},
        {"field": "ar_v7_status", "gate_code": "ar_v7_positive_arpi_resistance_pathway",
         "severity": "recommended",
         "reason": "AR-V7+ predice resistencia ARPI — switch taxane temprano"},
        {"field": "ecog_current", "gate_code": "ecog_decline_alert", "severity": "critical",
         "reason": "ECOG decline determina pathway palliative vs activo"},
        {"field": "psma_pet_progression_documented", "gate_code": "psma_pet_progression_auto_trigger",
         "severity": "recommended",
         "reason": "PSMA progression dispara rPFS event PCWG3"},
        {"field": "esas_pain_score", "gate_code": "esas_severity_alert", "severity": "informational",
         "reason": "ESAS multi-síntoma identifica distress + palliative referral"},
    ],
    # ─── m0CRPC ─────────────────────────────────────────────────
    "m0_crpc": [
        {"field": "psa_doubling_time_months", "gate_code": "psa_doubling_time_progressive",
         "severity": "critical",
         "reason": "PSADT define elegibilidad ARPI (SPARTAN/PROSPER/ARAMIS)"},
        {"field": "castrate_testosterone_status_confirmed", "gate_code": "_baseline",
         "severity": "critical",
         "reason": "Castración confirmada criterio definicional m0CRPC"},
        {"field": "hrr_status", "gate_code": "hrr_status_required_before_parp_inhibitor",
         "severity": "recommended",
         "reason": "Pre-emptive HRR testing si PARP futuro considerado"},
    ],
    # ─── Post-RP / BCR ──────────────────────────────────────────
    "post_prostatectomy": [
        {"field": "psa_value", "gate_code": "_baseline", "severity": "critical",
         "reason": "PSA post-RP necesario para detectar BCR"},
        {"field": "psa_doubling_time_months", "gate_code": "psa_velocity_bcr_aggressive",
         "severity": "recommended",
         "reason": "PSADT post-RP detecta BCR agresivo (Stephenson)"},
        {"field": "salvage_rt_consideration_active", "gate_code": "localized_bcr_adjuvant_trials_completion",
         "severity": "informational",
         "reason": "Activa info de RAVES/ARTISTIC/RTOG 9601 trials"},
    ],
    "recurrence_bcr": [
        {"field": "psa_value", "gate_code": "_baseline", "severity": "critical"},
        {"field": "psa_doubling_time_months", "gate_code": "psa_velocity_bcr_aggressive",
         "severity": "critical",
         "reason": "PSADT define BCR aggressive vs indolent → elegibilidad salvage"},
    ],
    # ─── Diagnostic workup ──────────────────────────────────────
    "diagnostic_workup": [
        {"field": "psa_value", "gate_code": "_baseline", "severity": "critical"},
        {"field": "phi_score_value", "gate_code": "pre_biopsy_risk_calculators_phi_4kscore",
         "severity": "informational",
         "reason": "PHI reduce biopsias innecesarias 25-30%"},
        {"field": "fourkscore_value", "gate_code": "pre_biopsy_risk_calculators_phi_4kscore",
         "severity": "informational",
         "reason": "4Kscore reduce biopsias innecesarias 30-40%"},
        {"field": "psa_density", "gate_code": "pre_biopsy_risk_calculators_phi_4kscore",
         "severity": "informational",
         "reason": "PSAD ≥0.15 indica biopsia (EAU 2026)"},
    ],
}

# Fields críticos UNIVERSALES (siempre advertir si faltan independiente del state)
_UNIVERSAL_CRITICAL_FIELDS = [
    {"field": "given_name", "severity": "critical", "reason": "Identificación del paciente"},
    {"field": "family_name", "severity": "critical", "reason": "Identificación del paciente"},
    {"field": "biological_sex", "severity": "critical", "reason": "ProstaMed solo procesa pacientes con próstata"},
]


def detect_missing_critical_fields(
    payload: dict[str, Any],
    clinical_state: str | None = None,
) -> list[dict[str, Any]]:
    """Detecta fields críticos faltantes según el estado clínico del paciente.

    Args:
        payload: Dict con datos capturados desde UI v2.
        clinical_state: Estado clínico estimado (e.g. 'localized_initial',
                        'm1_crpc', 'recurrence_bcr'). Si None, solo aplica
                        UNIVERSAL_CRITICAL_FIELDS.

    Returns:
        Lista de warnings:
        [
            {
                "field": "hrr_status",
                "gate_code": "hrr_status_required_before_parp_inhibitor",
                "severity": "critical|recommended|informational",
                "reason": "...",
                "clinical_state": "m1_crpc",
            },
            ...
        ]

    NOTA: Este detector NO bloquea el POST. Solo informa al médico
    qué gates clínicos NO podrán dispararse hasta que capture estos fields.
    """
    warnings: list[dict[str, Any]] = []

    # Fields universales
    for spec in _UNIVERSAL_CRITICAL_FIELDS:
        fname = spec["field"]
        if not _is_present(payload.get(fname)):
            warnings.append({
                **spec,
                "clinical_state": clinical_state or "any",
                "gate_code": spec.get("gate_code", "_universal"),
            })

    # Fields críticos por state
    if clinical_state and clinical_state in _CRITICAL_FIELDS_BY_STATE:
        for spec in _CRITICAL_FIELDS_BY_STATE[clinical_state]:
            fname = spec["field"]
            if not _is_present(payload.get(fname)):
                warnings.append({
                    **spec,
                    "clinical_state": clinical_state,
                })

    return warnings


def summarize_completeness(
    payload: dict[str, Any],
    clinical_state: str | None = None,
) -> dict[str, Any]:
    """Retorna resumen completo de completeness para mostrar en UI/respuesta API.

    Returns:
        {
            "state": "m1_crpc",
            "total_warnings": 5,
            "critical_count": 2,
            "recommended_count": 2,
            "informational_count": 1,
            "warnings": [...],
            "gate_coverage_percent": 65,  # de gates aplicables al state, cuántos pueden disparar
        }
    """
    warnings = detect_missing_critical_fields(payload, clinical_state)
    by_severity = {"critical": 0, "recommended": 0, "informational": 0}
    for w in warnings:
        by_severity[w.get("severity", "informational")] += 1

    # Gate coverage: % de fields críticos del state que SÍ están presentes
    state_specs = _CRITICAL_FIELDS_BY_STATE.get(clinical_state or "", [])
    state_total = len(state_specs)
    state_present = sum(
        1 for spec in state_specs if _is_present(payload.get(spec["field"]))
    )
    coverage = (state_present / state_total * 100) if state_total > 0 else 100

    return {
        "state": clinical_state or "unknown",
        "total_warnings": len(warnings),
        "critical_count": by_severity["critical"],
        "recommended_count": by_severity["recommended"],
        "informational_count": by_severity["informational"],
        "warnings": warnings,
        "gate_coverage_percent": round(coverage, 1),
        "completeness_grade": _grade(coverage),
    }


def _grade(coverage: float) -> str:
    """Grade letter para coverage percent."""
    if coverage >= 90:
        return "A"
    if coverage >= 75:
        return "B"
    if coverage >= 60:
        return "C"
    if coverage >= 40:
        return "D"
    return "F"


def _is_present(value: Any) -> bool:
    """Determina si un valor está presente (not None, not empty, not 'Desconocido')."""
    if value is None:
        return False
    if isinstance(value, str):
        v = value.strip().lower()
        return v not in ("", "desconocido", "unknown", "none", "n/a")
    if isinstance(value, (list, dict)):
        return len(value) > 0
    return True
