# IEC 62304 §5.5 (Unit verification)
from __future__ import annotations

import pytest

from prostanet.domains.m1_crpc.rules_nccn import evaluate_m1_crpc
from prostanet.domains.patient_tracking.crpc_copilot_service import CRPCCopilotService
from prostanet.domains.patient_tracking.longitudinal_intelligence import build_next_best_action
from prostanet.domains.patient_tracking.profile_compass import (
    _build_clinical_copy_bundle,
    _refresh_runtime_assessment,
    _structured_decision_candidate,
    build_patient_profile_view_model,
)
from prostanet.domains.patient_tracking.reconciled_state import build_reconciled_state
from prostanet.shared.presentation_text import humanize_assessment

# FAUBOT 2026-04-23 — suite de regresión de superficies con wall-clock >5 min.
# Excluida del ciclo rápido por defecto. Ejecutar con: `pytest -m "slow or not slow"`.
pytestmark = pytest.mark.slow


def test_clinical_copy_bundle_prefers_specific_next_best_action_over_generic_care_intent():
    bundle = _build_clinical_copy_bundle(
        state="m1_crpc",
        clinical_compass={
            "official_diagnosis": "CRPC metastásico",
            "official_diagnosis_source_summary": "",
            "management_intent_status": "Activo",
            "current_stage_label": "CRPC metastásico",
            "effective_state_label": "CRPC metastásico",
            "operational_module_label": "CRPC metastásico",
            "recommendation_family": "ARPI first-line",
        },
        diagnosis_context={},
        care_intent_contract={
            "headline": "Reevaluar secuencia sistémica y seguridad activa",
            "narrative": "Narrativa genérica legacy.",
            "recommendation_family": "Ruta sistémica",
        },
        next_best_action={
            "action_title": "Priorizar Enzalutamide",
            "action_rationale": "La elegibilidad clínica actual favorece ARPI explícito.",
            "recommendation_family": "ARPI first-line",
        },
        triplet_decision={},
        metastatic_state_bundle={},
    )

    assert bundle["decision_today_display"]["headline"] == "Priorizar Enzalutamide"
    assert bundle["decision_today_display"]["source"] == "next_best_action"
    assert bundle["next_best_action_display"]["headline"] == "Priorizar Enzalutamide"
    assert "decision_copy_masks_next_best_action" in bundle["copy_consistency_flags"]
    assert "care_intent_generic_for_closed_module" in bundle["copy_consistency_flags"]


def test_clinical_copy_bundle_uses_effective_state_family_as_operational_headline():
    bundle = _build_clinical_copy_bundle(
        state="localized_initial",
        clinical_compass={
            "official_diagnosis": "Enfermedad localizada o regional N1M0",
            "official_diagnosis_source_summary": "",
            "management_intent_status": "Activo",
            "current_stage_label": "Enfermedad localizada o regional N1M0",
            "effective_state_label": "Enfermedad localizada",
            "operational_module_label": "Enfermedad localizada o regional N1M0",
            "recommendation_family": "local_therapy",
        },
        diagnosis_context={},
        care_intent_contract={},
        next_best_action={
            "action_title": "Priorizar prostatectomía radical",
            "action_rationale": "Paciente apto y con prioridad oncológica.",
            "recommendation_family": "cirugía",
        },
        triplet_decision={},
        metastatic_state_bundle={},
    )

    assert bundle["operational_state_display"]["headline"] == "Enfermedad localizada"
    assert bundle["operational_state_display"]["supporting_text"] == "Enfermedad localizada o regional N1M0"
    assert "operational_state_headline_broader_than_effective_state" in bundle["copy_consistency_flags"]


def test_clinical_copy_bundle_promotes_structured_regimen_when_runtime_copy_is_generic():
    bundle = _build_clinical_copy_bundle(
        state="m1_crpc",
        clinical_compass={
            "official_diagnosis": "CRPC metastásico",
            "official_diagnosis_source_summary": "",
            "management_intent_status": "Activo",
            "current_stage_label": "CRPC metastásico",
            "effective_state_label": "CRPC metastásico",
            "operational_module_label": "CRPC metastásico",
            "recommendation_family": "Ruta sistémica",
            "structured_decision_headline": "Priorizar Olaparib",
            "structured_decision_supporting_text": "Biomarcador HRR trazable respalda PARP.",
            "structured_decision_family": "PARP",
        },
        diagnosis_context={},
        care_intent_contract={
            "headline": "Reevaluar secuencia sistémica y seguridad activa",
            "narrative": "Narrativa genérica legacy.",
            "recommendation_family": "Ruta sistémica",
        },
        next_best_action={
            "action_title": "Priorizar Confirm castrate testosterone and optimize ADT",
            "action_rationale": "Fallback genérico.",
            "recommendation_family": "Ruta sistémica",
        },
        triplet_decision={},
        metastatic_state_bundle={},
    )

    assert bundle["decision_today_display"]["headline"] == "Priorizar Olaparib"
    assert bundle["decision_today_display"]["source"] == "structured_regimen"
    assert bundle["next_best_action_display"]["headline"] == "Priorizar Olaparib"
    assert "structured_regimen_promoted" in bundle["copy_consistency_flags"]


def test_structured_decision_candidate_prefers_canonical_molecule_name_over_combo_label():
    candidate = _structured_decision_candidate(
        {
            "preferred_frontline_regimen": {
                "name": "Enzalutamide",
                "regimen_label": "ADT + enzalutamida",
                "display_label": "ADT + enzalutamida",
                "family_label": "ARPI",
            }
        }
    )

    assert candidate["headline"] == "Priorizar Enzalutamide"


def test_clinical_copy_bundle_canonicalizes_post_rt_confirmation_wording():
    bundle = _build_clinical_copy_bundle(
        state="post_radiotherapy_or_local_salvage",
        clinical_compass={
            "official_diagnosis": "Recurrencia post-radioterapia y salvage local",
            "official_diagnosis_source_summary": "",
            "management_intent_status": "Activo",
            "current_stage_label": "Recurrencia post-RT",
            "effective_state_label": "Recurrencia post-RT",
            "operational_module_label": "Recurrencia post-RT",
            "recommendation_family": "Confirmación post-RT",
        },
        diagnosis_context={},
        care_intent_contract={},
        next_best_action={
            "action_title": "Confirmar fallo post-RT antes de abrir salvage",
            "action_rationale": "Todavía falta cerrar el criterio de fallo.",
            "recommendation_family": "Confirmación post-RT",
        },
        triplet_decision={},
        metastatic_state_bundle={},
    )

    assert bundle["decision_today_display"]["headline"] == "Confirmar fallo post-RT antes de salvage"


def test_clinical_copy_bundle_canonicalizes_post_rt_systemic_redirect_wording():
    bundle = _build_clinical_copy_bundle(
        state="post_radiotherapy_or_local_salvage",
        clinical_compass={
            "official_diagnosis": "Recurrencia post-radioterapia y salvage local",
            "official_diagnosis_source_summary": "",
            "management_intent_status": "Activo",
            "current_stage_label": "Recurrencia post-RT",
            "effective_state_label": "Recurrencia post-RT",
            "operational_module_label": "Recurrencia post-RT",
            "recommendation_family": "Ruta sistémica post-RT",
        },
        diagnosis_context={},
        care_intent_contract={},
        next_best_action={
            "action_title": "Redirigir a secuencia sistémica y reestadificación",
            "action_rationale": "La distribución metastásica ya no sostiene salvage local aislado.",
            "recommendation_family": "Ruta sistémica post-RT",
        },
        triplet_decision={},
        metastatic_state_bundle={},
    )

    assert bundle["decision_today_display"]["headline"] == "Redirección sistémica / reestadificación"


def test_clinical_copy_bundle_keeps_nmcrpc_reclassification_copy_over_structured_backbone():
    bundle = _build_clinical_copy_bundle(
        state="m0_crpc",
        clinical_compass={
            "official_diagnosis": "CRPC sin metástasis",
            "official_diagnosis_source_summary": "",
            "management_intent_status": "Activo",
            "current_stage_label": "CRPC sin metástasis",
            "effective_state_label": "CRPC sin metástasis",
            "operational_module_label": "CRPC sin metástasis",
            "recommendation_family": "Reclasificación nmCRPC",
            "structured_decision_headline": "Priorizar Optimizar ADT y confirmar testosterona en rango de castración",
            "structured_decision_supporting_text": "Este mensaje funciona como soporte del backbone, no como decisión visible principal.",
            "structured_decision_family": "Observación / backbone",
        },
        diagnosis_context={},
        care_intent_contract={
            "headline": "Priorizar Completar reestadificación y reclasificar fuera de nmCRPC",
            "narrative": "No debe intensificarse como nmCRPC hasta confirmar que sigue siendo M0.",
            "recommendation_family": "Reclasificación nmCRPC",
        },
        next_best_action={
            "action_title": "Priorizar Completar reestadificación y reclasificar fuera de nmCRPC",
            "action_rationale": "No debe intensificarse como nmCRPC hasta confirmar que sigue siendo M0.",
            "recommendation_family": "Reclasificación nmCRPC",
        },
        triplet_decision={},
        metastatic_state_bundle={},
    )

    assert bundle["decision_today_display"]["headline"] == "Priorizar Completar reestadificación y reclasificar fuera de nmCRPC"
    assert bundle["decision_today_display"]["source"] == "care_intent_contract"


def test_clinical_copy_bundle_surfaces_rt_primary_as_structured_local_adjunct():
    bundle = _build_clinical_copy_bundle(
        state="mcspc_low_volume_sync_oligo",
        clinical_compass={
            "official_diagnosis": "mHSPC bajo volumen",
            "official_diagnosis_source_summary": "",
            "management_intent_status": "Activo",
            "current_stage_label": "mHSPC bajo volumen",
            "effective_state_label": "mHSPC bajo volumen",
            "operational_module_label": "mHSPC bajo volumen",
            "recommendation_family": "ARPI",
        },
        diagnosis_context={},
        care_intent_contract={},
        next_best_action={
            "action_title": "Priorizar ADT + enzalutamida",
            "action_rationale": "El backbone sistémico sigue siendo la recomendación principal.",
            "recommendation_family": "ARPI",
        },
        triplet_decision={},
        metastatic_state_bundle={},
        signal_snapshot={"mhspc_copilot_bundle": {"rt_primary_candidate": True}},
    )

    labels = [item["label"] for item in bundle["local_adjuncts_visible"]]
    assert "RT al primario" in labels
    assert bundle["local_adjuncts_display"]["visible"] is True


def test_clinical_copy_bundle_surfaces_mdt_as_structured_local_adjunct():
    bundle = _build_clinical_copy_bundle(
        state="mcspc_oligo_metachronous",
        clinical_compass={
            "official_diagnosis": "mHSPC oligometastásico metacrónico",
            "official_diagnosis_source_summary": "",
            "management_intent_status": "Activo",
            "current_stage_label": "mHSPC oligometastásico metacrónico",
            "effective_state_label": "mHSPC oligometastásico metacrónico",
            "operational_module_label": "mHSPC oligometastásico metacrónico",
            "recommendation_family": "ARPI",
        },
        diagnosis_context={},
        care_intent_contract={},
        next_best_action={
            "action_title": "Priorizar ADT + enzalutamida",
            "action_rationale": "La intensificación sistémica sigue siendo el headline correcto.",
            "recommendation_family": "ARPI",
        },
        triplet_decision={},
        metastatic_state_bundle={},
        signal_snapshot={"mhspc_copilot_bundle": {"mdt_candidate": True}},
    )

    labels = [item["label"] for item in bundle["local_adjuncts_visible"]]
    assert "MDT" in labels
    assert bundle["local_adjuncts_display"]["visible"] is True


def test_profile_view_model_prefers_reconciled_recurrence_label_over_legacy_module_label():
    patient = {
        "identity": {"id": 2},
        "baseline": {"prior_prostatectomy": 1},
        "prior_history": {"current_state": "recurrence_bcr"},
        "bcr": {"bcr_detected": 1, "bcr_psa": 0.32, "bcr_date": "2026-03-27"},
        "latest_assessment": {
            "module_id": "post_prostatectomy",
            "state": "recurrence_bcr",
            "input_snapshot": {
                "bcr_detected": 1,
                "bcr_psa": 0.32,
            },
            "result_snapshot": {
                "state": "recurrence_bcr",
                "eligible_treatments": [
                    {"name": "Radioterapia de rescate temprana", "priority": "preferred"}
                ],
            },
            "guideline_versions": {},
        },
    }

    profile = build_patient_profile_view_model(
        patient=patient,
        latest_assessment_raw=patient["latest_assessment"],
        latest_assessment={
            **humanize_assessment(patient["latest_assessment"]),
            "module_label": "Seguimiento posprostatectomía",
        },
        state_timeline=[],
        care_overlays=[],
    )

    assert profile["clinical_compass"]["current_stage_label"] == "Recurrencia bioquímica"


def test_refresh_runtime_assessment_rehydrates_stale_m1_crpc_snapshot():
    raw_assessment = {
        "module_id": "m1_crpc",
        "state": "m1_crpc",
        "input_snapshot": {
            "hrr_status": "Negativo",
            "hrr_gene": "Desconocido",
            "biomarker_source": "Biopsia metastásica",
            "molecular_report_date": "2026-03-01",
            "msi_status": "estable",
            "metastasis_site": "Bone",
            "prior_therapy": "Enzalutamida",
            "prior_docetaxel_cycles": 0,
            "castrate_testosterone_status": "confirmed_castrate",
            "mcrpc_line_context": "post_arpi_pre_taxane",
            "docetaxel_fit": 0,
            "chemotherapy_delay_candidate": 1,
            "pain_symptoms": "Leve",
            "ecog_performance_status": 1,
            "psma_positive": 1,
            "psma_pet_done": 1,
            "psma_negative_dominant_lesions": 1,
            "psma_radioligand": "18F-PSMA-1007",
            "psma_uptake_pattern": "multifocal",
            "psma_rads_score": "3",
            "psma_total_lesions": 3,
            "child_pugh_score": "A",
        },
        "result_snapshot": {
            "eligible_treatments": [
                {
                    "name": "Confirm castrate testosterone and optimize ADT",
                    "priority": "preferred",
                }
            ]
        },
        "guideline_versions": {},
    }

    refreshed_raw, refreshed_display = _refresh_runtime_assessment(
        patient={"baseline": {}, "latest_assessment": raw_assessment},
        raw_assessment=raw_assessment,
        display_assessment={},
    )

    preferred = refreshed_raw["result_snapshot"]["preferred_frontline_regimen"]

    assert preferred["name"] == "Olaparib"
    assert refreshed_display["display_result"]["state"] == "m1_crpc"


def test_reconciled_state_keeps_localized_lane_when_only_local_intensification_is_documented():
    patient = {
        "latest_assessment": {"state": "localized_initial", "input_snapshot": {}},
        "longitudinal_truth_snapshot": {
            "field_values": {
                "current_treatment": "ADT + abiraterona",
                "metastasis_site": "M0",
            }
        },
        "baseline": {"metastasis_site": "M0"},
    }

    reconciliation = build_reconciled_state(patient, patient["latest_assessment"])

    assert reconciliation["reconciled_state"] == "localized_initial"


def test_reconciled_state_keeps_postlocal_lane_despite_systemic_redirect_signals():
    patient = {
        "latest_assessment": {"state": "recurrence_bcr", "input_snapshot": {}},
        "prior_history": {"current_state": "recurrence_bcr"},
        "longitudinal_truth_snapshot": {
            "field_values": {
                "current_treatment": "Enzalutamida + leuprorelina",
                "psma_stage_after_psma": "M1b",
                "psma_uptake_pattern": "diseminado",
                "metastasis_site": "Bone",
            }
        },
        "baseline": {"prior_prostatectomy": 1},
        "bcr": {"bcr_detected": 1, "bcr_psa": 0.7, "bcr_date": "2026-03-27"},
    }

    reconciliation = build_reconciled_state(patient, patient["latest_assessment"])

    assert reconciliation["reconciled_state"] == "recurrence_bcr"


def test_reconciled_state_preserves_explicit_oligo_metachronous_mhspc_subtype():
    patient = {
        "latest_assessment": {"state": "mcspc_oligo_metachronous", "input_snapshot": {}},
        "baseline": {
            "metastasis_site": "Bone",
            "metastasis_count": 2,
            "volume_disease": "Low",
        },
    }

    reconciliation = build_reconciled_state(patient, patient["latest_assessment"])

    assert reconciliation["reconciled_state"] == "mcspc_oligo_metachronous"


def test_reconciled_state_preserves_explicit_high_volume_mhspc_subtype():
    patient = {
        "latest_assessment": {"state": "mcspc_high_volume_sync", "input_snapshot": {}},
        "baseline": {
            "metastasis_site": "Bone",
            "metastasis_count": 6,
            "volume_disease": "low",
        },
    }

    reconciliation = build_reconciled_state(patient, patient["latest_assessment"])

    assert reconciliation["reconciled_state"] == "mcspc_high_volume_sync"


def test_profile_view_model_ignores_auto_applied_transition_that_breaks_postlocal_family():
    patient = {
        "identity": {"id": 1},
        "baseline": {"prior_prostatectomy": 1, "metastasis_site": "M1", "metastasis_count": 1},
        "prior_history": {"current_state": "recurrence_bcr"},
        "bcr": {"bcr_detected": 1, "bcr_psa": 0.45, "bcr_date": "2026-03-27"},
        "latest_assessment": {
            "module_id": "recurrence_bcr",
            "state": "recurrence_bcr",
            "input_snapshot": {
                "psma_stage_after_psma": "M1a",
                "psma_uptake_pattern": "focal",
                "bcr_detected": 1,
                "bcr_psa": 0.45,
            },
            "result_snapshot": {
                "state": "recurrence_bcr",
                "eligible_treatments": [
                    {"name": "Radioterapia de rescate temprana", "priority": "preferred"}
                ],
                "preferred_frontline_regimen": {
                    "name": "Radioterapia de rescate temprana",
                    "regimen_label": "Radioterapia de rescate temprana",
                    "regimen_code": "EARLY_SALVAGE_RT",
                    "family_code": "salvage_family",
                    "family_label": "Salvage",
                    "notes": "Use los umbrales de persistencia o recurrencia del antígeno prostático específico y el riesgo clínico.",
                },
            },
            "guideline_versions": {},
        },
    }
    longitudinal_bundle = {
        "signals": {
            "reconciled_state": "recurrence_bcr",
            "effective_state": "recurrence_bcr",
            "effective_state_final": "recurrence_bcr",
            "next_best_action": {
                "title": "Activar salvage y reestadificación dirigida",
                "recommendation_family": "salvage",
            },
        },
        "transition_resolution": {
            "policy": "auto_applied",
            "target_state": "mcspc_low_volume_sync_oligo",
            "target_management_track": "systemic_surveillance",
        },
    }

    profile = build_patient_profile_view_model(
        patient=patient,
        latest_assessment_raw=patient["latest_assessment"],
        latest_assessment=humanize_assessment(patient["latest_assessment"]),
        state_timeline=[],
        care_overlays=[],
        longitudinal_bundle=longitudinal_bundle,
    )

    assert profile["reconciled_state"] == "recurrence_bcr"
    assert profile["management_track"] == "salvage"


def test_profile_view_model_ignores_auto_applied_transition_that_demotes_postlocal_recurrence():
    patient = {
        "identity": {"id": 3},
        "baseline": {"prior_prostatectomy": 1},
        "prior_history": {"current_state": "recurrence_bcr"},
        "bcr": {"bcr_detected": 1, "bcr_psa": 0.28, "bcr_date": "2026-03-27"},
        "latest_assessment": {
            "module_id": "recurrence_bcr",
            "state": "recurrence_bcr",
            "input_snapshot": {
                "bcr_detected": 1,
                "bcr_psa": 0.28,
            },
            "result_snapshot": {
                "state": "recurrence_bcr",
                "eligible_treatments": [
                    {"name": "Radioterapia de rescate temprana", "priority": "preferred"}
                ],
            },
            "guideline_versions": {},
        },
    }
    longitudinal_bundle = {
        "signals": {
            "reconciled_state": "recurrence_bcr",
            "effective_state": "recurrence_bcr",
            "effective_state_final": "recurrence_bcr",
            "next_best_action": {
                "title": "Activar salvage y reestadificación dirigida",
                "recommendation_family": "salvage",
            },
        },
        "transition_resolution": {
            "policy": "auto_applied",
            "target_state": "post_prostatectomy",
            "target_management_track": "post_rp",
        },
    }

    profile = build_patient_profile_view_model(
        patient=patient,
        latest_assessment_raw=patient["latest_assessment"],
        latest_assessment=humanize_assessment(patient["latest_assessment"]),
        state_timeline=[],
        care_overlays=[],
        longitudinal_bundle=longitudinal_bundle,
    )

    assert profile["reconciled_state"] == "recurrence_bcr"
    assert profile["clinical_compass"]["effective_state_label"] == "Recurrencia bioquímica"
    assert profile["clinical_copy_bundle"]["operational_state_display"]["headline"] == "Recurrencia bioquímica"


def test_crpc_copilot_payload_preserves_explicit_castration_confirmation():
    service = CRPCCopilotService()
    patient = {
        "baseline": {"testosterone_baseline": 330},
        "latest_assessment": {
            "state": "m1_crpc",
            "input_snapshot": {
                "castrate_testosterone_confirmed": 1,
                "current_adt_context": "ADT continua",
                "conventional_imaging_status": "M1b",
            },
        },
    }

    payload = service._build_payload(
        patient,
        patient["latest_assessment"],
        effective_state="m1_crpc",
    )

    assert payload["castrate_testosterone_confirmed"] == 1
    assert payload["castrate_testosterone_status"] == "confirmed_castrate"


def test_m1_crpc_rules_accept_castration_from_status_or_testosterone_even_without_flag():
    result = evaluate_m1_crpc(
        {
            "prior_therapy": "Enzalutamida",
            "prior_docetaxel_cycles": 0,
            "castrate_testosterone_confirmed": "",
            "castrate_testosterone_status": "confirmed_castrate",
            "testosterone_value": 18,
            "mcrpc_line_context": "post_arpi_pre_taxane",
            "metastasis_site": "Bone",
            "hrr_status": "Negativo",
            "msi_status": "estable",
        }
    )

    assert result["castrate_confirmed"] is True


def test_build_next_best_action_localized_uses_specific_observation_copy():
    patient = {
        "latest_assessment": {
            "state": "localized_initial",
            "input_snapshot": {
                "frailty_status": "Frail",
                "life_expectancy_years": 6,
                "isup_grade": 1,
                "clinical_tstage": "T1c",
                "num_cores_positive": 2,
                "max_core_involvement": 0.15,
            },
            "result_snapshot": {
                "eligible_treatments": [{"name": "Observación clínica"}],
                "decision_quality": {"recommendation_family": "watchful_waiting"},
            },
        },
        "longitudinal_truth_snapshot": {"field_values": {}},
    }

    action = build_next_best_action(
        patient,
        {"reconciled_state": "localized_initial", "reconciled_management_track": "localized_decision"},
        [],
        patient["latest_assessment"],
    )

    assert "observación clínica" in action["title"].lower()


def test_build_next_best_action_post_rp_uses_specific_systemic_redirect_copy_when_option_is_explicit():
    patient = {
        "latest_assessment": {
            "state": "recurrence_bcr",
            "input_snapshot": {
                "psma_stage_after_psma": "M1b",
                "psma_uptake_pattern": "diseminado",
            },
            "result_snapshot": {
                "eligible_treatments": [{"name": "Enzalutamida con o sin leuprorelina"}],
                "decision_quality": {"recommendation_family": "salvage"},
            },
        },
        "prior_history": {"current_state": "recurrence_bcr"},
        "baseline": {"prior_prostatectomy": 1},
        "bcr": {"bcr_detected": 1, "bcr_psa": 0.7, "bcr_date": "2026-03-27"},
        "longitudinal_truth_snapshot": {
            "field_values": {
                "psma_stage_after_psma": "M1b",
                "psma_uptake_pattern": "diseminado",
            }
        },
    }

    action = build_next_best_action(
        patient,
        {"reconciled_state": "recurrence_bcr", "reconciled_management_track": "salvage"},
        [],
        patient["latest_assessment"],
    )

    assert "enzalutamida" in action["title"].lower()
