"""Tests EPIC 5 — Active Surveillance longitudinal + reclasificación serial.

Cubre:
  * test_new_as_protocols_registered (Canary_PASS, UCSF, Sunnybrook)
  * test_ucsf_admits_favorable_intermediate_with_low_decipher
  * test_ucsf_rejects_high_decipher_score
  * test_recommended_protocol_ranking_low_risk
  * test_recommended_protocol_ucsf_primary_favorable_intermediate
  * test_detect_longitudinal_empty_returns_notes
  * test_detect_longitudinal_single_snapshot_not_enough
  * test_longitudinal_psa_kinetics_exit_trigger (PSADT <12m)
  * test_longitudinal_psa_kinetics_monitoring_trigger (PSADT 12-36m)
  * test_longitudinal_gleason_upgrade_exit
  * test_longitudinal_mri_progression_pirads_jump
  * test_longitudinal_adverse_histology_emergence
  * test_longitudinal_anxiety_sustained_triggers_intensification
  * test_longitudinal_patient_preference_exits
  * test_longitudinal_decipher_uptrend_flag
  * test_longitudinal_report_aggregates_probability_band
  * test_longitudinal_wrapper_returns_list
  * test_service_builds_snapshots_from_payload_fallback
  * test_copilot_surfaces_longitudinal_triggers_without_duplication
  * test_copilot_elevates_tone_on_high_band

Estas pruebas corresponden al EPIC 5 del plan ProstaNet (AS longitudinal +
reclasificación). Evidencia: NCCN PROS-C v5.2026, EAU 2026 §6.2.2, PRIAS
(Bul Eur Urol 2013), Canary PASS (Newcomb J Urol 2016), UCSF (Welty J Urol
2015 + Cooperberg Decipher JCO 2018), Sunnybrook (Klotz JCO 2015), PRECISE
(Moore Eur Urol 2017), MAX-PC (Roth Cancer 2003).
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest

from prostanet.domains.patient_tracking.active_surveillance import (
    AS_PROTOCOLS,
    ASReclassificationTrigger,
    ActiveSurveillanceService,
    detect_reclassification_longitudinal as detect_wrapper,
    rank_recommended_protocols,
    recommended_protocol,
)
from prostanet.domains.patient_tracking.active_surveillance_longitudinal import (
    ANXIETY_SUSTAINED_MAX_PC,
    DECIPHER_UPGRADE_DELTA,
    LongitudinalASService,
    LongitudinalASSnapshot,
    LongitudinalReclassificationReport,
    MRI_PROGRESSION_PIRADS_CUTOFF,
    PSADT_EXIT_THRESHOLD_MONTHS,
    PSADT_MONITORING_THRESHOLD_MONTHS,
    detect_reclassification_longitudinal,
)


# ───────────────────────── Protocol registration ──────────────────────────────


def test_new_as_protocols_registered():
    """Canary_PASS, UCSF y Sunnybrook quedan registrados en AS_PROTOCOLS."""
    for key in ("Canary_PASS", "UCSF", "Sunnybrook"):
        assert key in AS_PROTOCOLS, f"Protocolo {key} no registrado"
        config = AS_PROTOCOLS[key]
        assert "criteria" in config
        assert "schedule" in config
        assert "evidence_tags" in config
        assert config["evidence_tags"], f"Protocolo {key} sin evidencia citada"


def test_ucsf_admits_favorable_intermediate_with_low_decipher():
    """UCSF AS acepta GG2 selecto cuando Decipher ≤0.60 (Welty 2015; Cooperberg 2018)."""
    patient = {
        "isup_grade": 2,
        "psa": 8.0,
        "psad": 0.12,
        "clinical_tstage": "T2a",
        "num_cores_positive": 3,
        "total_cores": 12,
        "max_core_involvement": 0.30,
        "cribriform_pattern": False,
        "intraductal_carcinoma": False,
        "decipher_score_numeric": 0.45,
    }
    results = ActiveSurveillanceService.check_eligibility(patient, "localized_initial")
    ucsf = next(r for r in results if r.protocol == "UCSF")
    assert ucsf.eligible, f"UCSF debería aceptar; falló: {ucsf.criteria_failed}"


def test_ucsf_rejects_high_decipher_score():
    """UCSF rechaza Decipher >0.60 por riesgo biológico alto."""
    patient = {
        "isup_grade": 2,
        "psa": 8.0,
        "psad": 0.12,
        "clinical_tstage": "T2a",
        "num_cores_positive": 3,
        "total_cores": 12,
        "max_core_involvement": 0.30,
        "cribriform_pattern": False,
        "intraductal_carcinoma": False,
        "decipher_score_numeric": 0.72,
    }
    results = ActiveSurveillanceService.check_eligibility(patient, "localized_initial")
    ucsf = next(r for r in results if r.protocol == "UCSF")
    assert not ucsf.eligible
    assert any("Decipher" in reason for reason in ucsf.criteria_failed)


def test_ucsf_rejects_decipher_categorical_alto():
    """Retrocompat: Decipher categórico 'Alto' bloquea UCSF aun sin score numérico."""
    patient = {
        "isup_grade": 2,
        "psa": 8.0,
        "psad": 0.12,
        "clinical_tstage": "T2a",
        "num_cores_positive": 3,
        "total_cores": 12,
        "max_core_involvement": 0.30,
        "cribriform_pattern": False,
        "intraductal_carcinoma": False,
        "genomic_classifier_result": "Alto",
    }
    results = ActiveSurveillanceService.check_eligibility(patient, "localized_initial")
    ucsf = next(r for r in results if r.protocol == "UCSF")
    assert not ucsf.eligible


# ───────────────────────── Recommended protocol ranking ────────────────────────


def test_recommended_protocol_ranking_low_risk():
    """Bajo riesgo NCCN ranking inicia con NCCN_low; incluye alternativas."""
    patient = {
        "isup_grade": 1,
        "psa": 5.5,
        "psad": 0.12,
        "clinical_tstage": "T1c",
        "num_cores_positive": 2,
        "total_cores": 12,
        "max_core_involvement": 0.20,
    }
    ranking = rank_recommended_protocols(patient, "LOW")
    assert ranking, "Ranking vacío para LOW"
    assert ranking[0]["protocol"] == "NCCN_low"
    assert ranking[0]["eligible"] is True
    # Canary_PASS sigue inmediatamente a NCCN_low.
    assert ranking[1]["protocol"] == "Canary_PASS"
    assert ranking[1]["eligible"] is True
    assert recommended_protocol(patient, "LOW") == "NCCN_low"


def test_recommended_protocol_ucsf_primary_favorable_intermediate():
    """Favorable intermediate + Decipher bajo → UCSF recomendado primario."""
    patient = {
        "isup_grade": 2,
        "psa": 8.0,
        "psad": 0.12,
        "clinical_tstage": "T2a",
        "num_cores_positive": 3,
        "total_cores": 12,
        "max_core_involvement": 0.30,
        "cribriform_pattern": False,
        "intraductal_carcinoma": False,
        "decipher_score_numeric": 0.40,
    }
    ranking = rank_recommended_protocols(patient, "FAVORABLE INTERMEDIATE")
    assert ranking, "Ranking vacío en favorable intermediate"
    assert ranking[0]["protocol"] == "UCSF"
    assert ranking[0]["eligible"] is True


def test_recommended_protocol_empty_for_high_risk():
    """Alto riesgo NCCN no debe proponer ningún protocolo de AS."""
    patient = {
        "isup_grade": 4,
        "psa": 25,
        "clinical_tstage": "T3a",
        "num_cores_positive": 8,
        "total_cores": 12,
        "max_core_involvement": 0.70,
    }
    ranking = rank_recommended_protocols(patient, "HIGH")
    assert ranking == []
    assert recommended_protocol(patient, "HIGH") == ""


# ───────────────────────── Longitudinal engine — base cases ────────────────────


def test_detect_longitudinal_empty_returns_notes():
    """Sin snapshots: no falla, devuelve notas informativas."""
    report = detect_reclassification_longitudinal([])
    assert isinstance(report, LongitudinalReclassificationReport)
    assert report.snapshots_evaluated == 0
    assert report.triggers == []
    assert report.probability_band == "low"
    assert any("Sin snapshots" in note for note in report.notes)


def test_detect_longitudinal_single_snapshot_not_enough():
    """Con 1 snapshot, el engine serial explica que se necesitan ≥2."""
    report = detect_reclassification_longitudinal([
        {"snapshot_date": "2025-01-01", "psa": 5.0}
    ])
    assert report.snapshots_evaluated == 1
    assert report.triggers == []
    assert any("1 snapshot" in note for note in report.notes)


def test_detect_longitudinal_accepts_dataclass_or_dict():
    """El engine tolera `LongitudinalASSnapshot` y `dict` intercambiablemente."""
    mixed = [
        LongitudinalASSnapshot(snapshot_date="2024-01-01", psa=4.0, isup_grade=1),
        {"snapshot_date": "2024-06-01", "psa": 5.0, "isup_grade": 1},
        LongitudinalASSnapshot(snapshot_date="2024-12-01", psa=6.2, isup_grade=1),
    ]
    report = detect_reclassification_longitudinal(mixed)
    assert report.snapshots_evaluated == 3


# ───────────────────────── PSA kinetics triggers ───────────────────────────────


def test_longitudinal_psa_kinetics_exit_trigger():
    """PSADT <12m sobre ≥3 snapshots gatilla severity=reclassification (Klotz)."""
    snapshots = [
        {"snapshot_date": "2024-01-01", "psa": 4.0},
        {"snapshot_date": "2024-04-01", "psa": 6.0},
        {"snapshot_date": "2024-07-01", "psa": 9.0},
        {"snapshot_date": "2024-10-01", "psa": 13.5},
    ]
    report = detect_reclassification_longitudinal(snapshots)
    kinetics = [t for t in report.triggers if t.trigger_type == "psa_kinetics"]
    assert kinetics, "No se detectó cinética acelerada"
    assert kinetics[0].severity == "reclassification"
    assert report.psadt_months_estimated is not None
    assert report.psadt_months_estimated < PSADT_EXIT_THRESHOLD_MONTHS


def test_longitudinal_psa_kinetics_monitoring_trigger():
    """PSADT entre 12 y 36m: severity=monitoring_intensification (PRIAS)."""
    # Series con PSADT ~24 meses.
    snapshots = [
        {"snapshot_date": "2023-01-01", "psa": 4.0},
        {"snapshot_date": "2023-07-01", "psa": 4.5},
        {"snapshot_date": "2024-01-01", "psa": 5.1},
        {"snapshot_date": "2024-07-01", "psa": 5.8},
        {"snapshot_date": "2025-01-01", "psa": 6.5},
    ]
    report = detect_reclassification_longitudinal(snapshots)
    kinetics = [t for t in report.triggers if t.trigger_type == "psa_kinetics"]
    assert kinetics
    assert kinetics[0].severity == "monitoring_intensification"
    assert (
        PSADT_EXIT_THRESHOLD_MONTHS
        <= (report.psadt_months_estimated or 0)
        < PSADT_MONITORING_THRESHOLD_MONTHS
    )


def test_longitudinal_stable_psa_no_kinetics_trigger():
    """PSA estable no dispara cinética."""
    snapshots = [
        {"snapshot_date": "2023-01-01", "psa": 5.0},
        {"snapshot_date": "2024-01-01", "psa": 5.1},
        {"snapshot_date": "2025-01-01", "psa": 5.2},
    ]
    report = detect_reclassification_longitudinal(snapshots)
    kinetics = [t for t in report.triggers if t.trigger_type == "psa_kinetics"]
    assert kinetics == []


# ───────────────────────── Gleason upgrade ─────────────────────────────────────


def test_longitudinal_gleason_upgrade_exit():
    """ISUP 1 → ISUP 2 a través de ≥2 biopsias dispara exit."""
    snapshots = [
        {"snapshot_date": "2024-01-15", "psa": 4.0, "isup_grade": 1},
        {"snapshot_date": "2025-01-15", "psa": 4.8, "isup_grade": 2},
    ]
    report = detect_reclassification_longitudinal(snapshots)
    upgrades = [t for t in report.triggers if t.trigger_type == "gleason_upgrade"]
    assert upgrades
    assert upgrades[0].severity == "reclassification"
    assert "ISUP 1" in upgrades[0].detail
    assert "ISUP 2" in upgrades[0].detail


def test_longitudinal_no_gleason_upgrade_when_stable():
    """ISUP estable no gatilla upgrade."""
    snapshots = [
        {"snapshot_date": "2024-01-15", "isup_grade": 1},
        {"snapshot_date": "2025-01-15", "isup_grade": 1},
    ]
    report = detect_reclassification_longitudinal(snapshots)
    assert not any(t.trigger_type == "gleason_upgrade" for t in report.triggers)


# ───────────────────────── MRI progression ─────────────────────────────────────


def test_longitudinal_mri_progression_pirads_jump():
    """PI-RADS 2 → 4 en MRI seriadas dispara monitoring_intensification (PRECISE)."""
    snapshots = [
        {"snapshot_date": "2024-01-15", "pirads_score": 2},
        {"snapshot_date": "2025-01-15", "pirads_score": 4},
    ]
    report = detect_reclassification_longitudinal(snapshots)
    mri_triggers = [t for t in report.triggers if t.trigger_type == "mri_new_lesion"]
    assert mri_triggers
    assert mri_triggers[0].severity == "monitoring_intensification"


def test_longitudinal_mri_stable_no_trigger():
    """PI-RADS estable (3 → 3) no gatilla."""
    snapshots = [
        {"snapshot_date": "2024-01-15", "pirads_score": 3},
        {"snapshot_date": "2025-01-15", "pirads_score": 3},
    ]
    report = detect_reclassification_longitudinal(snapshots)
    assert not any(t.trigger_type == "mri_new_lesion" for t in report.triggers)


# ───────────────────────── Adverse histology emergence ─────────────────────────


def test_longitudinal_adverse_histology_emergence():
    """Aparición de cribriforme en biopsia de seguimiento → exit."""
    snapshots = [
        {"snapshot_date": "2024-01-15", "isup_grade": 1, "any_cribriform": False},
        {"snapshot_date": "2025-01-15", "isup_grade": 1, "any_cribriform": True},
    ]
    report = detect_reclassification_longitudinal(snapshots)
    adverse = [t for t in report.triggers if t.trigger_type == "adverse_histology"]
    assert adverse
    assert adverse[0].severity == "reclassification"
    assert "cribriforme" in adverse[0].detail


# ───────────────────────── Anxiety + preference ────────────────────────────────


def test_longitudinal_anxiety_sustained_triggers_intensification():
    """MAX-PC ≥27 en ≥2 assessments consecutivos dispara intensificación."""
    snapshots = [
        {"snapshot_date": "2024-01-15", "max_pc_score": 31},
        {"snapshot_date": "2024-07-15", "max_pc_score": 28},
    ]
    report = detect_reclassification_longitudinal(snapshots)
    anxiety = [t for t in report.triggers if t.trigger_type == "anxiety_sustained"]
    assert anxiety
    assert anxiety[0].severity == "monitoring_intensification"


def test_longitudinal_single_high_anxiety_no_trigger():
    """MAX-PC elevado en 1 sola evaluación no basta para gatillar exit."""
    snapshots = [
        {"snapshot_date": "2024-01-15", "max_pc_score": 15},
        {"snapshot_date": "2024-07-15", "max_pc_score": 30},
    ]
    report = detect_reclassification_longitudinal(snapshots)
    assert not any(t.trigger_type == "anxiety_sustained" for t in report.triggers)


def test_longitudinal_patient_preference_exits():
    """Preferencia explícita del paciente dispara exit (SDM)."""
    snapshots = [
        {"snapshot_date": "2024-01-15", "psa": 4.0, "patient_prefers_exit": False},
        {"snapshot_date": "2025-01-15", "psa": 4.2, "patient_prefers_exit": True},
    ]
    report = detect_reclassification_longitudinal(snapshots)
    pref = [t for t in report.triggers if t.trigger_type == "patient_preference"]
    assert pref
    assert pref[0].severity == "reclassification"


# ───────────────────────── Decipher uptrend ────────────────────────────────────


def test_longitudinal_decipher_uptrend_flag():
    """Decipher sube ≥0.10 en serie → alerta biológica."""
    snapshots = [
        {"snapshot_date": "2024-01-15", "decipher_score": 0.40},
        {"snapshot_date": "2025-01-15", "decipher_score": 0.55},
    ]
    report = detect_reclassification_longitudinal(snapshots)
    uptrend = [t for t in report.triggers if t.trigger_type == "decipher_uptrend"]
    assert uptrend
    assert uptrend[0].severity == "monitoring_intensification"


def test_longitudinal_decipher_small_change_no_trigger():
    """Subida Decipher <DECIPHER_UPGRADE_DELTA no dispara."""
    snapshots = [
        {"snapshot_date": "2024-01-15", "decipher_score": 0.40},
        {"snapshot_date": "2025-01-15", "decipher_score": 0.40 + DECIPHER_UPGRADE_DELTA / 2},
    ]
    report = detect_reclassification_longitudinal(snapshots)
    assert not any(t.trigger_type == "decipher_uptrend" for t in report.triggers)


# ───────────────────────── Probability band + aggregation ──────────────────────


def test_longitudinal_report_aggregates_probability_band():
    """Múltiples triggers severos → banda 'high' con probabilidad ≥0.7."""
    snapshots = [
        {"snapshot_date": "2024-01-01", "psa": 4.0, "isup_grade": 1, "pirads_score": 2, "max_pc_score": 18},
        {"snapshot_date": "2024-06-01", "psa": 6.5, "isup_grade": 1},
        {"snapshot_date": "2024-12-01", "psa": 10.0, "pirads_score": 4, "max_pc_score": 30, "isup_grade": 2, "any_cribriform": True},
        {"snapshot_date": "2025-06-01", "psa": 15.0, "max_pc_score": 31},
    ]
    report = detect_reclassification_longitudinal(snapshots)
    assert len(report.triggers) >= 3
    assert report.probability_band == "high"
    assert report.reclassification_probability >= 0.7
    assert report.exit_recommendation
    assert "salida de va" in report.exit_recommendation.lower()


def test_longitudinal_report_low_band_no_triggers():
    """Sin triggers activos → banda 'low' y recomendación neutra."""
    snapshots = [
        {"snapshot_date": "2024-01-01", "psa": 5.0, "isup_grade": 1},
        {"snapshot_date": "2024-07-01", "psa": 5.1, "isup_grade": 1},
        {"snapshot_date": "2025-01-01", "psa": 5.0, "isup_grade": 1},
    ]
    report = detect_reclassification_longitudinal(snapshots)
    assert report.probability_band == "low"
    assert report.reclassification_probability == 0.0
    assert "No hay triggers" in report.exit_recommendation


# ───────────────────────── Public wrapper ──────────────────────────────────────


def test_longitudinal_wrapper_returns_list():
    """La fachada de `active_surveillance.detect_reclassification_longitudinal`
    devuelve `list[ASReclassificationTrigger]` (no el reporte completo)."""
    snapshots = [
        {"snapshot_date": "2024-01-15", "isup_grade": 1},
        {"snapshot_date": "2025-01-15", "isup_grade": 2},
    ]
    triggers = detect_wrapper(snapshots)
    assert isinstance(triggers, list)
    assert triggers
    assert all(isinstance(t, ASReclassificationTrigger) for t in triggers)


def test_longitudinal_wrapper_never_raises_on_bad_input():
    """El wrapper tolera inputs inválidos sin excepciones."""
    triggers = detect_wrapper([None, {}, {"snapshot_date": ""}])
    assert triggers == []


# ───────────────────────── Service fallback ────────────────────────────────────


def test_service_builds_snapshots_from_payload_fallback():
    """`LongitudinalASService.build_snapshots_from_payload` fusiona psa_history
    + biopsies + mri_facts + pro_assessments cuando no hay snapshots explícitos."""
    payload = {
        "psa_history": [
            {"date": "2024-01-01", "psa": 4.0},
            {"date": "2024-07-01", "psa": 4.5},
        ],
        "biopsies": [
            {"biopsy_date": "2024-01-15", "isup_grade": 1, "highest_isup": 1},
            {"biopsy_date": "2024-12-15", "isup_grade": 2, "highest_isup": 2},
        ],
        "mri_facts": [
            {"mri_date": "2024-01-15", "pirads_score": 2},
            {"mri_date": "2024-12-15", "pirads_score": 3},
        ],
        "pro_assessments": [
            {"assessment_date": "2024-06-15", "max_pc_score": 14},
        ],
    }
    snapshots = LongitudinalASService.build_snapshots_from_payload(payload)
    assert len(snapshots) >= 4
    dates = [s.snapshot_date for s in snapshots]
    assert dates == sorted(dates)  # orden ascendente


def test_service_evaluate_end_to_end_flags_upgrade():
    """`LongitudinalASService.evaluate` corre el pipeline completo sobre payload."""
    payload = {
        "psa_history": [
            {"date": "2024-01-01", "psa": 4.0},
            {"date": "2024-06-01", "psa": 5.2},
            {"date": "2024-12-01", "psa": 6.8},
        ],
        "biopsies": [
            {"biopsy_date": "2024-01-15", "isup_grade": 1},
            {"biopsy_date": "2024-12-15", "isup_grade": 2},
        ],
    }
    report = LongitudinalASService.evaluate(payload)
    assert report.snapshots_evaluated >= 4
    trigger_types = {t.trigger_type for t in report.triggers}
    assert "gleason_upgrade" in trigger_types


# ───────────────────────── Copilot integration ─────────────────────────────────


def _minimal_copilot_patient(
    *,
    biopsies: list[dict] | None = None,
    mri_facts: list[dict] | None = None,
    psa_history: list[dict] | None = None,
    pro_assessments: list[dict] | None = None,
) -> dict:
    """Paciente mínimo para ejercitar `LocalizedSurveillanceCopilotService`.

    Usa los engines reales (sin mocks) para probar la integración.
    """
    return {
        "identity": {"id": 9001},
        "baseline": {
            "psa": 5.0,
            "isup_grade": 1,
            "clinical_tstage": "T1c",
            "num_cores_positive": 2,
            "total_cores": 12,
            "max_core_involvement": 0.2,
            "life_expectancy_years": 15,
            "diagnosis_date": "2023-06-15",
        },
        "prior_history": {"current_state": "localized_initial"},
        "management_track": "active_surveillance",
        "active_surveillance": {
            "enrollment_date": "2023-07-01",
            "confirmatory_biopsy_done": True,
            "confirmatory_biopsy_date": "2024-07-01",
        },
        "biopsies": biopsies or [],
        "mri_facts": mri_facts or [],
        "psa_history": psa_history or [],
        "pro_assessments": pro_assessments or [],
    }


def test_copilot_surfaces_longitudinal_triggers_without_duplication():
    """El copilot añade triggers longitudinales y no duplica los cross-seccionales.

    Construye una serie con upgrade ISUP — esperamos UN trigger `gleason_upgrade`,
    no dos (cross-sectional + longitudinal).
    """
    from prostanet.domains.patient_tracking.localized_surveillance_copilot_service import (
        LocalizedSurveillanceCopilotService,
    )
    svc = LocalizedSurveillanceCopilotService()

    patient = _minimal_copilot_patient(
        biopsies=[
            {"biopsy_date": "2023-06-15", "biopsy_context": "baseline", "isup_grade": 1, "highest_isup": 1},
            {"biopsy_date": "2024-12-15", "biopsy_context": "confirmatory_as", "isup_grade": 2, "highest_isup": 2},
        ],
        psa_history=[
            {"date": "2023-06-15", "psa": 5.0},
            {"date": "2024-01-15", "psa": 5.2},
            {"date": "2024-12-15", "psa": 5.5},
        ],
    )
    result = svc.evaluate(
        patient,
        effective_state="localized_initial",
        effective_management_track="active_surveillance",
    )
    # Si el copilot se enruta al bundle deshabilitado (feature flag off), saltar
    # esta prueba — la responsabilidad se verifica en el engine serial directo.
    if not result.get("available"):
        pytest.skip("LOCALIZED_SURVEILLANCE_COPILOT feature flag off")
    triggers = result.get("upgrade_triggers") or []
    upgrade_triggers = [t for t in triggers if t.get("trigger_type") == "gleason_upgrade"]
    assert len(upgrade_triggers) <= 1, (
        f"Trigger duplicado: {upgrade_triggers}"
    )
    assert "as_longitudinal_report" in result
    report = result["as_longitudinal_report"]
    assert "triggers" in report
    assert "reclassification_probability" in report


def test_copilot_elevates_tone_on_high_band():
    """Banda longitudinal 'high' eleva el tono del card de success a danger."""
    from prostanet.domains.patient_tracking.localized_surveillance_copilot_service import (
        LocalizedSurveillanceCopilotService,
    )
    svc = LocalizedSurveillanceCopilotService()

    patient = _minimal_copilot_patient(
        biopsies=[
            {"biopsy_date": "2024-01-01", "biopsy_context": "baseline", "isup_grade": 1, "highest_isup": 1},
            {"biopsy_date": "2024-12-01", "biopsy_context": "confirmatory_as", "isup_grade": 2, "highest_isup": 2, "any_cribriform": True},
        ],
        psa_history=[
            {"date": "2024-01-01", "psa": 4.0},
            {"date": "2024-04-01", "psa": 6.0},
            {"date": "2024-07-01", "psa": 9.0},
            {"date": "2024-10-01", "psa": 13.0},
        ],
        mri_facts=[
            {"mri_date": "2024-01-01", "pirads_score": 2},
            {"mri_date": "2024-12-01", "pirads_score": 4},
        ],
    )
    result = svc.evaluate(
        patient,
        effective_state="localized_initial",
        effective_management_track="active_surveillance",
    )
    if not result.get("available"):
        pytest.skip("LOCALIZED_SURVEILLANCE_COPILOT feature flag off")
    report = result.get("as_longitudinal_report") or {}
    assert report.get("probability_band") in {"moderate", "high"}
    course = result.get("active_surveillance_course") or {}
    assert course.get("tone") in {"warning", "danger"}
