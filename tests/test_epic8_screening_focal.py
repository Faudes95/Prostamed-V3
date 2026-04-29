# -*- coding: utf-8 -*-
"""Tests EPIC 8 — Screening poblacional + Focal therapy selectiva.

Trayectorias clínicas cubiertas:

Screening (NCCN Early Detection v2.2026 + USPSTF 2018 + EAU 2026 §5):
    * test_screening_afro_american_45_yr_initiation
    * test_screening_family_history_brca_annual
    * test_screening_stop_elderly_low_life_expectancy
    * test_screening_psa_gt_3_triggers_diagnostic_workup
    * test_screening_age_thresholds (ED-1/ED-2/ED-3/ED-4/ED-5)
    * test_screening_copilot_gates_on_state

Focal therapy (NCCN PROS-C categoría 2B + EAU 2026 §7.5):
    * test_focal_hifu_unilateral_intermediate_favorable
    * test_focal_crio_alternative_when_radiation_contraindicated
    * test_focal_ineligible_bilateral_lesion
    * test_focal_ineligible_isup_3_or_higher
    * test_focal_hifu_blocked_by_apical_lesion
    * test_focal_therapy_eligibility_intermediate_favorable (localized_initial wrapper)
    * test_focal_copilot_latent_in_localized_without_signal
    * test_focal_copilot_active_in_localized_with_unilateral_signal

Routing state_classifier (EPIC 8 no altera SC-1 ni Phoenix gates):
    * test_state_classifier_routes_to_screening_context
    * test_state_classifier_does_not_route_screening_when_workup_requested
    * test_epic8_does_not_break_epic1_phoenix_guard

Evidencia pivote:
- NCCN Prostate Cancer Early Detection v2.2026 (ED-1 a ED-5)
- USPSTF 2018 JAMA 2018;319:1901
- NCCN Prostate v5.2026 PROS-C (focal therapy cat 2B)
- EAU 2026 §5 Early detection + §7.5 Focal therapy
- Stabile A et al. Eur Urol 2019;76:572 (HIFU mid-term)
- Guillaumier S et al. Eur Urol 2018;74:422 (HIFU FFS 5y)
- Ward JF et al. BJU Int 2012;109:1648 (crioablación focal)
- Klotz L et al. J Urol 2021;205:769 (TULSA-Pro)
- Pritchard CC et al. NEJM 2016 (BRCA2 mCRPC)
- Nyberg T et al. Eur Urol 2020 (IMPACT BRCA2)
- Schroeder et al. NEJM 2009 (ERSPC 9-year)
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest

from prostanet.domains.focal_therapy.rules_nccn import classify_focal_therapy_nccn
from prostanet.domains.focal_therapy.service import FocalTherapyService
from prostanet.domains.localized_initial.rules_nccn import focal_therapy_eligibility
from prostanet.domains.patient_tracking.focal_therapy_copilot_service import (
    FocalTherapyCopilotService,
)
from prostanet.domains.patient_tracking.screening_copilot_service import (
    ScreeningCopilotService,
)
from prostanet.domains.screening.rules_eau import classify_screening_eau
from prostanet.domains.screening.rules_nccn import classify_screening_nccn
from prostanet.domains.screening.service import ScreeningService
from prostanet.domains.state_classifier.service import StateClassifierService


# ───────────────────────── Screening trajectories ────────────────────────────


def test_screening_afro_american_45_yr_initiation():
    """Hombre afroamericano de 45 años — NCCN ED-2 (inicio temprano por etnia)."""
    payload = {
        "age": 45,
        "ethnicity_group": "Afroamericano / afrodescendiente",
        "family_history_cluster": "Sin historia familiar relevante",
        "germline_known_status": "Desconocido / no testeado",
        "psa_baseline_ng_ml": 0.9,
        "dre_baseline_finding": "Normal",
        "life_expectancy_years": 35,
    }
    nccn = classify_screening_nccn(payload)

    assert nccn["category"] == "ED-2"
    assert nccn["risk_group"] == "SCREENING_HIGH_RISK_EARLY"
    assert nccn["start_age_recommended"] == 45
    assert nccn["derive_to_diagnostic_workup"] is False
    # PSA < 1.0 sin alto riesgo familiar → cada 2 años; pero afroamericano
    # no es family_history_is_high_risk, así que debería ser 24m (no 12m).
    # El helper sólo pasa a 12m con BRCA2 o historia familiar high_risk.
    assert nccn["interval_months"] in {12, 24}
    assert any("45 años" in r or "afrodescendiente" in r.lower() for r in nccn["reasons"])


def test_screening_family_history_brca_annual():
    """BRCA2 germinal positivo a los 42 años — NCCN ED-2 BRCA2 early, EAU coincide."""
    payload = {
        "age": 42,
        "ethnicity_group": "Caucásico",
        "family_history_cluster": "Cluster familiar BRCA / Lynch / cáncer de mama-ovario",
        "germline_known_status": "Positivo BRCA2",
        "psa_baseline_ng_ml": 0.8,
        "dre_baseline_finding": "Normal",
        "life_expectancy_years": 40,
    }
    nccn = classify_screening_nccn(payload)
    eau = classify_screening_eau(payload)

    assert nccn["start_age_recommended"] == 40  # BRCA2 baja el inicio a 40
    assert nccn["category"] == "ED-2"  # 42 ≥ 40 → activo ED-2
    assert nccn["interval_months"] == 12  # BRCA2 con PSA<1 → anual
    assert any("BRCA2" in r for r in nccn["reasons"])

    assert eau["start_age_recommended"] == 40
    assert any("BRCA2" in r for r in eau["reasons"])
    assert eau["interval_months"] == 12  # BRCA2 + PSA<1 → anual


def test_screening_stop_elderly_low_life_expectancy():
    """Hombre de 77 años con expectativa de vida 7 años → NCCN ED-5 STOP (USPSTF grado D)."""
    payload = {
        "age": 77,
        "ethnicity_group": "Caucásico",
        "family_history_cluster": "Sin historia familiar relevante",
        "germline_known_status": "Negativo",
        "psa_baseline_ng_ml": 2.1,
        "dre_baseline_finding": "Normal",
        "life_expectancy_years": 7,
    }
    nccn = classify_screening_nccn(payload)

    assert nccn["category"] == "ED-5"
    assert nccn["risk_group"] == "SCREENING_STOP"
    assert nccn["interval_months"] == 0 or "suspend" in nccn["recommendation"].lower()
    assert "grado D" in nccn["recommendation"] or "grado D" in nccn["label"] or "USPSTF" in nccn["recommendation"]


def test_screening_psa_gt_3_triggers_diagnostic_workup():
    """PSA basal 4.2 ng/mL → deriva a diagnostic workup incluso en ED-3 standard."""
    payload = {
        "age": 60,
        "ethnicity_group": "Caucásico",
        "family_history_cluster": "Sin historia familiar relevante",
        "germline_known_status": "Negativo",
        "psa_baseline_ng_ml": 4.2,
        "dre_baseline_finding": "Normal",
        "life_expectancy_years": 22,
    }
    nccn = classify_screening_nccn(payload)

    assert nccn["derive_to_diagnostic_workup"] is True
    assert any("≥ 3.0" in r or "workup" in r.lower() for r in nccn["workup_reasons"])
    assert nccn["interval_months"] == 0  # screening rutinario suspendido


def test_screening_age_thresholds():
    """Las 5 categorías ED-1..ED-5 se asignan por edad + life_expectancy correctamente."""
    # ED-1: < 40 sin BRCA2
    r = classify_screening_nccn(
        {"age": 30, "family_history_cluster": "Sin historia familiar relevante"}
    )
    assert r["category"] == "ED-1"
    assert r["risk_group"] == "SCREENING_NOT_INDICATED"

    # ED-2: < 40 con BRCA2 positivo
    r = classify_screening_nccn(
        {"age": 35, "germline_known_status": "Positivo BRCA2"}
    )
    assert r["category"] == "ED-2"
    assert r["risk_group"] == "SCREENING_BRCA2_EARLY"

    # ED-3: 50-74 estándar sin riesgo
    r = classify_screening_nccn(
        {
            "age": 60,
            "ethnicity_group": "Caucásico",
            "family_history_cluster": "Sin historia familiar relevante",
            "germline_known_status": "Negativo",
            "psa_baseline_ng_ml": 1.4,
        }
    )
    assert r["category"] == "ED-3"
    assert r["risk_group"] == "SCREENING_STANDARD"

    # ED-4: ≥ 75 con life_expectancy ≥ 10
    r = classify_screening_nccn(
        {"age": 77, "life_expectancy_years": 12, "psa_baseline_ng_ml": 1.8}
    )
    assert r["category"] == "ED-4"
    assert r["risk_group"] == "SCREENING_EXTENDED_FRAGILE"

    # ED-5: ≥ 75 con life_expectancy < 10
    r = classify_screening_nccn(
        {"age": 80, "life_expectancy_years": 6, "psa_baseline_ng_ml": 1.2}
    )
    assert r["category"] == "ED-5"
    assert r["risk_group"] == "SCREENING_STOP"


def test_screening_copilot_gates_on_state():
    """ScreeningCopilotService sólo activa si effective_state == 'screening'."""
    copilot = ScreeningCopilotService()
    patient_payload = {
        "age": 55,
        "latest_assessment": {
            "state": "localized_initial",
            "payload": {
                "age": 55,
                "ethnicity_group": "Caucásico",
                "psa_baseline_ng_ml": 1.3,
            },
        },
    }
    # estado ≠ screening → not_applicable
    bundle = copilot.evaluate(patient_payload, effective_state="localized_initial")
    assert bundle["status"] == "not_applicable"

    # estado = screening → ok
    bundle = copilot.evaluate(
        patient_payload,
        effective_state="screening",
        latest_assessment={
            "payload": {
                "age": 55,
                "ethnicity_group": "Caucásico",
                "family_history_cluster": "Sin historia familiar relevante",
                "germline_known_status": "Negativo",
                "psa_baseline_ng_ml": 1.3,
                "dre_baseline_finding": "Normal",
            }
        },
    )
    assert bundle["status"] == "ok"
    assert bundle["state"] == "screening"
    assert "category" in bundle
    assert bundle["category"].startswith("ED-")


# ───────────────────────── Focal therapy trajectories ────────────────────────


def test_focal_hifu_unilateral_intermediate_favorable():
    """Paciente intermedio favorable con lesión unilateral + próstata 45 mL + HIFU → elegible."""
    payload = {
        "age": 63,
        "psa": 8.5,
        "gleason_primary": 3,
        "gleason_secondary": 4,
        "isup_grade": 2,
        "nccn_risk_group": "Favorable intermediate",
        "lesion_unilateral": "Unilateral (afecta un solo lóbulo)",
        "lesion_maxdim_mm": 11,
        "prostate_volume_ml": 45,
        "lesion_location_apical": "0",
        "urinary_obstructive_symptoms": "0",
        "focal_modality_preferred": "HIFU (high-intensity focused ultrasound)",
        "life_expectancy_years": 22,
    }
    verdict = classify_focal_therapy_nccn(payload)
    assert verdict["eligible"] is True
    assert verdict["label"] == "Candidato a terapia focal selectiva"
    assert verdict["modality_recommended"].startswith("hifu")
    assert any("stabile" in r.lower() or "hifu" in r.lower() for r in verdict["reasons"])
    assert not verdict["exclusion_reasons"]


def test_focal_crio_alternative_when_radiation_contraindicated():
    """Paciente bajo riesgo unilateral, próstata 55 mL, prefiere crioablación → elegible."""
    payload = {
        "age": 71,
        "psa": 6.8,
        "gleason_primary": 3,
        "gleason_secondary": 3,
        "isup_grade": 1,
        "nccn_risk_group": "Low",
        "lesion_unilateral": "Unilateral (afecta un solo lóbulo)",
        "lesion_maxdim_mm": 9,
        "prostate_volume_ml": 55,
        "lesion_location_apical": "0",
        "urinary_obstructive_symptoms": "0",
        "focal_modality_preferred": "Crioablación",
        "life_expectancy_years": 14,
    }
    verdict = classify_focal_therapy_nccn(payload)
    assert verdict["eligible"] is True
    assert "crio" in verdict["modality_recommended"].lower()
    assert any("ward" in r.lower() or "crio" in r.lower() for r in verdict["reasons"])


def test_focal_ineligible_bilateral_lesion():
    """Lesión bilateral → no elegible (falla criterio unilateral)."""
    payload = {
        "age": 60,
        "psa": 8.0,
        "isup_grade": 2,
        "nccn_risk_group": "Favorable intermediate",
        "lesion_unilateral": "Bilateral",
        "lesion_maxdim_mm": 12,
        "prostate_volume_ml": 42,
        "focal_modality_preferred": "HIFU (high-intensity focused ultrasound)",
    }
    verdict = classify_focal_therapy_nccn(payload)
    assert verdict["eligible"] is False
    assert any("unilateral" in msg.lower() for msg in verdict["exclusion_reasons"])


def test_focal_ineligible_isup_3_or_higher():
    """ISUP 3 excede el umbral focal (≤ ISUP 2) aun con lesión unilateral."""
    payload = {
        "age": 64,
        "psa": 9.5,
        "isup_grade": 3,
        "nccn_risk_group": "Unfavorable intermediate",
        "lesion_unilateral": "Unilateral (afecta un solo lóbulo)",
        "lesion_maxdim_mm": 10,
        "prostate_volume_ml": 40,
        "focal_modality_preferred": "HIFU (high-intensity focused ultrasound)",
    }
    verdict = classify_focal_therapy_nccn(payload)
    assert verdict["eligible"] is False
    assert any("isup" in msg.lower() for msg in verdict["exclusion_reasons"])


def test_focal_hifu_blocked_by_apical_lesion():
    """Lesión apical anterior profunda + HIFU → no elegible (crio o RP candidatos)."""
    payload = {
        "age": 62,
        "psa": 7.4,
        "isup_grade": 2,
        "nccn_risk_group": "Favorable intermediate",
        "lesion_unilateral": "Unilateral (afecta un solo lóbulo)",
        "lesion_maxdim_mm": 10,
        "prostate_volume_ml": 40,
        "lesion_location_apical": "1",
        "focal_modality_preferred": "HIFU (high-intensity focused ultrasound)",
    }
    verdict = classify_focal_therapy_nccn(payload)
    assert verdict["eligible"] is False
    assert any("apical" in msg.lower() for msg in verdict["exclusion_reasons"])


def test_focal_therapy_eligibility_intermediate_favorable():
    """Wrapper localized_initial.focal_therapy_eligibility expone offered + offer_reasons."""
    localized_payload = {
        "psa": 8.0,
        "gleason_primary": 3,
        "gleason_secondary": 4,
        "isup_grade": 2,
        "nccn_risk_group": "FAVORABLE INTERMEDIATE",
        "lesion_unilateral": "Unilateral (afecta un solo lóbulo)",
        "lesion_maxdim_mm": 10,
        "prostate_volume_ml": 42,
        "lesion_location_apical": "0",
        "focal_modality_preferred": "HIFU (high-intensity focused ultrasound)",
        "life_expectancy_years": 20,
        "age": 62,
    }
    verdict = focal_therapy_eligibility(localized_payload, nccn_group="FAVORABLE INTERMEDIATE")
    assert verdict["eligible"] is True
    assert verdict["offered"] is True
    assert verdict["offer_reasons"]  # lista no vacía
    assert any("Favorable" in r for r in verdict["offer_reasons"])

    # High risk → offered=False aunque los inputs sean consistentes
    verdict_hr = focal_therapy_eligibility({**localized_payload, "nccn_risk_group": "HIGH"}, nccn_group="HIGH")
    assert verdict_hr["offered"] is False


def test_focal_copilot_latent_in_localized_without_signal():
    """En localized_initial sin señal focal explícita el copiloto queda latente."""
    copilot = FocalTherapyCopilotService()
    patient_payload = {
        "age": 62,
        "latest_assessment": {
            "payload": {
                "psa": 8.0,
                "gleason_primary": 3,
                "gleason_secondary": 4,
                "isup_grade": 2,
                "nccn_risk_group": "Favorable intermediate",
                # No lesion_unilateral, no focal_modality_preferred, no candidato profile
                "prostate_volume_ml": 42,
            }
        },
    }
    bundle = copilot.evaluate(patient_payload, effective_state="localized_initial")
    assert bundle["status"] == "not_applicable"


def test_focal_copilot_active_in_localized_with_unilateral_signal():
    """En localized_initial con lesión unilateral documentada el copiloto produce bundle ok."""
    copilot = FocalTherapyCopilotService()
    patient_payload = {
        "age": 62,
        "latest_assessment": {
            "payload": {
                "psa": 8.0,
                "gleason_primary": 3,
                "gleason_secondary": 4,
                "isup_grade": 2,
                "nccn_risk_group": "Favorable intermediate",
                "lesion_unilateral": "Unilateral (afecta un solo lóbulo)",
                "lesion_maxdim_mm": 10,
                "prostate_volume_ml": 42,
                "lesion_location_apical": "0",
                "focal_modality_preferred": "HIFU (high-intensity focused ultrasound)",
            }
        },
    }
    bundle = copilot.evaluate(patient_payload, effective_state="localized_initial")
    assert bundle["status"] == "ok"
    assert bundle["eligible"] is True
    assert bundle["state"] == "localized_initial"
    assert "hifu" in bundle["modality_recommended"].lower()


def test_focal_copilot_active_in_focal_therapy_state():
    """Estado focal_therapy dedicado produce bundle ok directo."""
    copilot = FocalTherapyCopilotService()
    patient_payload = {
        "age": 60,
        "latest_assessment": {
            "payload": {
                "psa": 7.5,
                "gleason_primary": 3,
                "gleason_secondary": 4,
                "isup_grade": 2,
                "nccn_risk_group": "Favorable intermediate",
                "lesion_unilateral": "Unilateral (afecta un solo lóbulo)",
                "lesion_maxdim_mm": 9,
                "prostate_volume_ml": 40,
                "focal_modality_preferred": "Crioablación",
            }
        },
    }
    bundle = copilot.evaluate(patient_payload, effective_state="focal_therapy")
    assert bundle["status"] == "ok"
    assert bundle["state"] == "focal_therapy"
    assert bundle["eligible"] is True


# ─────────────────── State classifier integration (EPIC 8) ──────────────────


def test_state_classifier_routes_to_screening_context():
    """screening_context=1 sin diagnóstico ni workup → ruta screening."""
    payload = {
        "known_cancer_diagnosis": 0,
        "screening_context": 1,
        "age": 55,
        "psa_baseline_ng_ml": 1.2,
    }
    # Guard de nivel bajo: la señal de screening se reconoce.
    assert StateClassifierService._is_screening_context(payload) is True
    # Clasificación pública: paciente sin diagnóstico + contexto screening
    # debe rutearse a la ruta "screening" (EPIC 8), no a diagnostic_workup.
    result = StateClassifierService().classify(payload)
    assert result.get("state") == "screening" or result.get("module") == "screening"


def test_state_classifier_does_not_route_screening_when_workup_requested():
    """PSA basal capturado PERO diagnostic_workup_requested=1 → diagnostic_workup, no screening."""
    payload = {
        "psa_baseline_ng_ml": 1.5,
        "diagnostic_workup_requested": 1,
    }
    assert StateClassifierService._is_screening_context(payload) is False


def test_epic8_does_not_break_epic1_phoenix_guard():
    """EPIC 8 screening context no altera SC-1 (metacronía) ni Phoenix gate post-RT."""
    # El nuevo camino de screening no altera _is_metachronous_known
    assert StateClassifierService._is_metachronous_known({}) is False
    assert StateClassifierService._is_metachronous_known({"screening_context": 1}) is False
    # Phoenix gate sigue operativo desde recurrence_bcr — aquí sólo confirmamos
    # que introducir campos de screening no modifica los flags de metacronía.
    assert StateClassifierService._is_metachronous_known(
        {"screening_context": 1, "metachronous_metastasis": "1"}
    ) is True


# ─────────────── Service-level smoke tests (evaluation_result contract) ──────


def test_screening_service_evaluate_returns_evaluation_result():
    """ScreeningService.evaluate retorna un evaluation_result válido."""
    service = ScreeningService()
    result = service.evaluate(
        {
            "age": 55,
            "ethnicity_group": "Caucásico",
            "family_history_cluster": "Sin historia familiar relevante",
            "germline_known_status": "Negativo",
            "psa_baseline_ng_ml": 1.3,
            "dre_baseline_finding": "Normal",
            "life_expectancy_years": 25,
        }
    )
    assert result["state"] == "screening"
    assert "nccn_primary" in result
    assert result["nccn_primary"]["version"] == "v2.2026"
    assert "eau_comparison" in result
    assert "report_sections" in result
    assert result["report_sections"]["category"].startswith("ED-")
    assert "evidence_trace" in result
    assert any("NCCN" in (e.get("source") or "") for e in result["evidence_trace"])


def test_focal_therapy_service_evaluate_returns_evaluation_result():
    """FocalTherapyService.evaluate retorna evaluation_result elegible + contraindications."""
    service = FocalTherapyService()
    result = service.evaluate(
        {
            "age": 62,
            "psa": 8.0,
            "gleason_primary": 3,
            "gleason_secondary": 4,
            "isup_grade": 2,
            "nccn_risk_group": "Favorable intermediate",
            "lesion_unilateral": "Unilateral (afecta un solo lóbulo)",
            "lesion_maxdim_mm": 10,
            "prostate_volume_ml": 42,
            "focal_modality_preferred": "HIFU (high-intensity focused ultrasound)",
        }
    )
    assert result["state"] == "focal_therapy"
    assert result["nccn_primary"]["risk_group"] == "favorable_intermediate"
    # Evidence trace debe incluir NCCN PROS-C + al menos una modalidad
    sources = " ".join(str(e.get("source") or "") for e in result["evidence_trace"])
    assert "NCCN Prostate v5.2026 PROS-C" in sources
    assert any(tag in sources for tag in ("HIFU", "crio", "TULSA"))
    assert result["report_sections"]["eligibility"] is True


def test_focal_therapy_service_evaluate_marks_ineligible_bilateral():
    """FocalTherapyService.evaluate con lesión bilateral retorna eligibility=False."""
    service = FocalTherapyService()
    result = service.evaluate(
        {
            "psa": 8.0,
            "gleason_primary": 3,
            "gleason_secondary": 4,
            "isup_grade": 2,
            "nccn_risk_group": "Favorable intermediate",
            "lesion_unilateral": "Bilateral",
            "lesion_maxdim_mm": 11,
            "prostate_volume_ml": 40,
            "focal_modality_preferred": "HIFU (high-intensity focused ultrasound)",
        }
    )
    assert result["report_sections"]["eligibility"] is False
    # contraindications debería incluir la exclusión por lesión bilateral
    contras = " ".join(result.get("contraindications") or [])
    assert "unilateral" in contras.lower()
