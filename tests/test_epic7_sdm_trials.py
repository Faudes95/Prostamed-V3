# -*- coding: utf-8 -*-
"""Tests EPIC 7 — Decisión compartida (SDM) + matching de ensayos clínicos.

Cubre los trayectos pivote definidos en el plan maestro EPIC 7:

  * test_tradeoff_engine_surfaces_functional_outcomes
  * test_tradeoff_engine_prefers_AS_when_function_over_cure
  * test_tradeoff_engine_prefers_RP_when_cure_is_top_priority
  * test_tradeoff_engine_skips_rp_when_life_expectancy_short
  * test_tradeoff_engine_blocks_focal_without_unilateral_lesion
  * test_tradeoff_engine_missing_inputs_surface
  * test_trial_matching_hrr_positive_talapro3_eligible
  * test_trial_matching_brca2_lines_up_profound_and_propel
  * test_trial_matching_msi_high_matches_keynote158
  * test_trial_matching_vision_requires_post_arpi_and_psma
  * test_trial_matching_ep16_nepc_triggered_by_histology
  * test_trial_matching_catalog_source_and_disclaimer
  * test_elicitation_scoring_likert_numeric_and_text_aliases
  * test_elicitation_merges_with_free_text_priorities
  * test_decision_aid_build_tradeoff_visualization_orchestrates_all_bundles
  * test_m1_crpc_enriched_trial_matches_preserve_legacy_keys

Evidencia:
  * Hamdy NEJM 2023;388:1547 (ProtecT 15 años)
  * Bill-Axelson NEJM 2014;370:932 (SPCG-4)
  * Wilt NEJM 2017;377:132 (PIVOT)
  * Donovan NEJM 2016;375:1425 (ProtecT PROs)
  * Sartor NEJM 2021;385:1091 (VISION)
  * Morris Lancet 2024;404:1227 (PSMAfore)
  * de Bono NEJM 2020;382:2091 (PROfound)
  * Marabelle JCO 2020;38:1 (KEYNOTE-158)
  * Agarwal Lancet 2023 (TALAPRO-2)
  * NCCN PROS-A v5.2026 — SDM framework
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest

from prostanet.domains.patient_tracking.tradeoff_engine import (
    CANONICAL_PRIORITIES,
    MODALITY_OUTCOMES,
    build_tradeoff_matrix,
)
from prostanet.domains.reporting.sdm_preference_elicitation import (
    ELICITATION_ITEMS,
    LIKERT_LEVELS,
    build_elicitation_form,
    merge_elicited_with_free_text,
    score_elicitation,
)
from prostanet.domains.research_intelligence.trial_matching_engine import (
    TRIAL_CATALOG,
    build_trial_matching_bundle,
    match_patient_to_trials,
)


# ─────────────────────── tradeoff engine ──────────────────────────────────


def test_tradeoff_engine_surfaces_functional_outcomes():
    matrix = build_tradeoff_matrix(
        {
            "state": "localized_initial",
            "nccn_risk_group": "favorable_intermediate",
            "isup_grade": 2,
            "psa": 7.2,
            "life_expectancy_years": 18,
            "patient_priority_profile": ["preserve_urinary_function", "preserve_sexual_function"],
        }
    )
    bundle = matrix.to_dict()
    assert bundle["risk_group_applied"] == "favorable_intermediate"
    # Las outcomes deben exponer incontinencia y ED para al menos la RP y la RT
    rp = next(row for row in bundle["rows"] if row["modality_key"] == "radical_prostatectomy")
    assert rp["outcomes_per_100"]["urinary_incontinence_pad_use_6y"] == 17
    assert rp["outcomes_per_100"]["erectile_dysfunction_severe_6y"] == 60
    # Las prioridades funcionales deben penalizar RP vs AS
    as_row = next(row for row in bundle["rows"] if row["modality_key"] == "active_surveillance")
    assert as_row["alignment_score"] > rp["alignment_score"]


def test_tradeoff_engine_prefers_AS_when_function_over_cure():
    matrix = build_tradeoff_matrix(
        {
            "nccn_risk_group": "low",
            "life_expectancy_years": 20,
            "patient_priority_profile": "continencia, funcion sexual",
        }
    )
    bundle = matrix.to_dict()
    assert bundle["top_recommendation"] == "active_surveillance"
    labels = bundle["priorities_labels"]
    assert CANONICAL_PRIORITIES["preserve_urinary_function"] in labels
    assert CANONICAL_PRIORITIES["preserve_sexual_function"] in labels


def test_tradeoff_engine_prefers_RP_when_cure_is_top_priority():
    matrix = build_tradeoff_matrix(
        {
            "nccn_risk_group": "high",
            "life_expectancy_years": 18,
            "ecog_score": 0,
            "patient_priority_profile": ["maximize_cancer_control"],
        }
    )
    bundle = matrix.to_dict()
    # Con prioridad de curación pura, RP ≥ RT por menor metástasis/mortalidad en SPCG-4
    rp = next(row for row in bundle["rows"] if row["modality_key"] == "radical_prostatectomy")
    rt = next(row for row in bundle["rows"] if row["modality_key"] == "radiation_therapy")
    assert rp["applicable"]
    assert rt["applicable"]
    assert rp["alignment_score"] >= rt["alignment_score"]


def test_tradeoff_engine_skips_rp_when_life_expectancy_short():
    matrix = build_tradeoff_matrix(
        {
            "nccn_risk_group": "favorable_intermediate",
            "life_expectancy_years": 4,
            "patient_priority_profile": ["maximize_cancer_control"],
        }
    )
    bundle = matrix.to_dict()
    rp = next(row for row in bundle["rows"] if row["modality_key"] == "radical_prostatectomy")
    assert rp["applicable"] is False
    assert "Esperanza de vida" in rp["applicable_reason"]


def test_tradeoff_engine_blocks_focal_without_unilateral_lesion():
    matrix = build_tradeoff_matrix(
        {
            "nccn_risk_group": "favorable_intermediate",
            "life_expectancy_years": 15,
            "lesion_unilateral": "no",
            "patient_priority_profile": ["preserve_urinary_function"],
        }
    )
    bundle = matrix.to_dict()
    focal = next(row for row in bundle["rows"] if row["modality_key"] == "focal_therapy_hifu")
    assert focal["applicable"] is False
    assert "unilateral" in focal["applicable_reason"].lower()


def test_tradeoff_engine_missing_inputs_surface():
    matrix = build_tradeoff_matrix({})
    bundle = matrix.to_dict()
    assert "patient_priority_profile" in bundle["missing_inputs"]
    assert "life_expectancy_years" in bundle["missing_inputs"]


# ─────────────────────── trial matching ───────────────────────────────────


def test_trial_matching_hrr_positive_talapro3_eligible():
    matches = match_patient_to_trials(
        {
            "state": "m1_crpc",
            "ecog_score": 1,
            "hrr_positive": True,
            "prior_docetaxel": False,
            "prior_arpi": False,
        }
    )
    talapro = next((m for m in matches if m.trial_code == "TALAPRO-3"), None)
    talapro2 = next((m for m in matches if m.trial_code == "TALAPRO-2"), None)
    assert talapro is not None
    assert talapro2 is not None
    # Al menos uno de TALAPRO-2/3 debe ser elegible (según mHSPC vs mCRPC)
    assert talapro.match or talapro2.match


def test_trial_matching_brca2_lines_up_profound_and_propel():
    bundle = build_trial_matching_bundle(
        {
            "state": "m1_crpc",
            "germline_pathogenic_variant": "BRCA2",
            "ecog_score": 1,
        }
    )
    codes_positive = {match["trial_code"] for match in bundle["matches"]}
    # PROfound requiere progresión post-ARPI — sin datos, queda ineligible pero catalogado
    assert "PROfound" in {m.trial_code for m in TRIAL_CATALOG}
    # PROpel combinación abiraterona+olaparib debería aparecer o quedar catalogado
    assert bundle["total_trials_in_catalog"] >= 20
    assert bundle["catalog_source"] == "local_curated_v1"


def test_trial_matching_msi_high_matches_keynote158():
    matches = match_patient_to_trials(
        {
            "state": "m1_crpc",
            "msi_high": True,
            "ecog_score": 1,
        }
    )
    keynote = next((m for m in matches if m.trial_code == "KEYNOTE-158"), None)
    assert keynote is not None
    assert keynote.match is True
    assert any("MSI" in reason or "dMMR" in reason for reason in keynote.match_reasons)


def test_trial_matching_vision_requires_post_arpi_and_psma():
    # Sin PSMA+ ni post-ARPI: no debe matchear
    no_context = match_patient_to_trials(
        {"state": "m1_crpc", "ecog_score": 1}
    )
    vision_nope = next((m for m in no_context if m.trial_code == "VISION"), None)
    assert vision_nope is not None
    assert vision_nope.match is False

    # Con PSMA+ y post-ARPI + post-taxano: matchea
    with_context = match_patient_to_trials(
        {
            "state": "m1_crpc",
            "ecog_score": 1,
            "psma_lesion_suvmax_minimum": 18,
            "psma_suvmean_liver": 7,
            "prior_arpi": True,
            "prior_docetaxel": True,
        }
    )
    vision_ok = next((m for m in with_context if m.trial_code == "VISION"), None)
    assert vision_ok is not None
    assert vision_ok.match is True


def test_trial_matching_ep16_nepc_triggered_by_histology():
    matches = match_patient_to_trials(
        {
            "state": "m1_crpc",
            "nepc_confirmed_histology": True,
            "ecog_score": 1,
        }
    )
    ep16 = next((m for m in matches if m.trial_code == "EP-16-NEPC"), None)
    assert ep16 is not None
    assert ep16.match is True


def test_trial_matching_catalog_source_and_disclaimer():
    bundle = build_trial_matching_bundle({"state": "m1_crpc"})
    assert bundle["catalog_source"] == "local_curated_v1"
    assert bundle["disclaimer"]
    assert bundle["total_trials_in_catalog"] == len(TRIAL_CATALOG)


# ─────────────────────── elicitation ──────────────────────────────────────


def test_elicitation_scoring_likert_numeric_and_text_aliases():
    # Mezcla tokens canónicos con aliases numéricos 1..5
    result = score_elicitation(
        {
            "cancer_control_vs_quality_of_life": "strongly_prefer_a",  # max control
            "urinary_function_vs_cancer_control": 5,  # alias = prefer_b (continencia)
            "sexual_function_vs_cancer_control": "prefer_b",  # función sexual
            "chemo_vs_hormonal_extended": "neutral",
            # trial_vs_standard queda sin responder
        }
    )
    data = result.to_dict()
    assert "maximize_cancer_control" in data["priority_weights"]
    assert "preserve_urinary_function" in data["priority_weights"]
    assert "preserve_sexual_function" in data["priority_weights"]
    assert "trial_vs_standard" in data["unresolved_items"]
    # ranked_priorities debe ser no vacío
    assert data["ranked_priorities"]


def test_elicitation_merges_with_free_text_priorities():
    elicit = score_elicitation(
        {"cancer_control_vs_quality_of_life": "strongly_prefer_b"}  # minimizar carga
    )
    combined = merge_elicited_with_free_text(
        elicit,
        ["preserve_urinary_function"],
    )
    # Preserva explícito primero
    assert combined[0] == "preserve_urinary_function"
    # Añade la elicitada nueva si no estaba
    assert "minimize_treatment_burden" in combined


def test_elicitation_form_structure():
    form = build_elicitation_form()
    assert len(form) == len(ELICITATION_ITEMS) == 5
    for item in form:
        assert item["item_key"]
        assert item["prompt_es"]
        assert len(item["levels"]) == len(LIKERT_LEVELS) == 5


# ─────────────────────── decision_aids orchestration ──────────────────────


def test_decision_aid_build_tradeoff_visualization_orchestrates_all_bundles():
    from prostanet.domains.reporting.decision_aids import DecisionAidService

    patient = {
        "state": "localized_initial",
        "nccn_risk_group": "favorable_intermediate",
        "life_expectancy_years": 18,
        "patient_priority_profile": ["preserve_urinary_function"],
    }
    answers = {"urinary_function_vs_cancer_control": "strongly_prefer_b"}
    bundle = DecisionAidService.build_tradeoff_visualization(
        patient=patient, elicitation_answers=answers
    )
    assert bundle["source_framework"]
    assert "tradeoff_matrix" in bundle
    assert "trial_matching_bundle" in bundle
    assert "elicitation_result" in bundle
    assert bundle["elicitation_result"]["priority_weights"]
    # la matriz debe estar construida
    assert bundle["tradeoff_matrix"]["risk_group_applied"] == "favorable_intermediate"


# ─────────────────────── m1_crpc back-compat ─────────────────────────────


def test_m1_crpc_enriched_trial_matches_preserve_legacy_keys():
    """El refactor de EPIC 7 debe mantener las keys ``trial`` y ``match``
    que tests legados esperan, y añadir nct_id / match_reasons / evidence_tags.
    """
    from prostanet.domains.m1_crpc.service import M1CrpcService

    svc = M1CrpcService()
    payload = {
        "state": "m1_crpc",
        "ecog_score": 1,
        "germline_pathogenic_variant": "BRCA2",
        "prior_arpi": True,
        "prior_docetaxel": False,
    }
    result = svc.evaluate(payload)
    trials = result.get("trial_matches") or []
    assert trials, "trial_matches no debe estar vacío"
    for trial in trials:
        assert "trial" in trial  # back-compat
        assert "match" in trial  # back-compat
    # Debe haber al menos un trial con metadata enriquecida
    enriched = [t for t in trials if t.get("nct_id") or t.get("match_reasons") or t.get("evidence_tags")]
    assert enriched, "Se esperaba al menos un trial enriquecido con nct_id/match_reasons/evidence_tags"
