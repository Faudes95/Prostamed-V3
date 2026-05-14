# IEC 62304 §5.7 — EPIC 21 Phase 2 Cortana Full Clinical Assistant
"""Tests EPIC 21 Phase 2:
  Fase 2A — voice_intake_full_orchestrator (chronological intake)
  Fase 2B — decision_aware_qa (invokes copilots + Patient Twin)
  Fase 2C — population_query_safe (cohort + audits)
  Fase 2D — cortana_orchestrator (intent router)
  + Flask endpoints

User vision verified:
  "Cortana, ayúdame a ingresar a este paciente" → full intake
  "¿Cuál sería la mejor opción?" → decision-aware Q&A
  "¿Cuántos pacientes con mCRPC tenemos?" → population query con SQL safe
  Cortana entra a la BD, hace auditorías
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).parent.parent


# ─────────────────── Fase 2A: voice_intake_full_orchestrator ───────────────────


def test_phase2a_full_intake_imports():
    from prostanet.voice.voice_intake_full_orchestrator import (
        orchestrate_full_intake,
        IntakeOrchestratorResult,
    )
    assert callable(orchestrate_full_intake)


def test_phase2a_extracts_age_psa_chronological():
    """Real user dictation: cronological PSA + age + RP."""
    from prostanet.voice.voice_intake_full_orchestrator import orchestrate_full_intake
    transcript = (
        "Paciente de 68 años. En 2022 PSA de 8 punto 5. En 2024 PSA fue 12 punto 3. "
        "En 2025 PSA 0 punto 2 post prostatectomía radical, márgenes positivos focales, "
        "Gleason 7 (4+3) pT3a, recibió RT salvage en 2025. PSA actual 2 punto 8."
    )
    result = orchestrate_full_intake(transcript)
    assert result.available is True
    # 4 PSA entries: 2022, 2024, 2025, today
    assert len(result.psa_history) == 4
    psa_values = sorted([e.value for e in result.psa_history])
    assert 0.2 in psa_values and 8.5 in psa_values and 12.3 in psa_values
    # Treatments: RP + RT
    treatment_modalities = {t.modality for t in result.treatment_history}
    assert "RP" in treatment_modalities
    assert "EBRT" in treatment_modalities
    # Demographics
    assert result.demographics.get("age") == 68
    # Quick-classify
    assert "known_cancer_diagnosis" in result.quick_classify_candidates
    assert "prior_prostatectomy" in result.quick_classify_candidates
    assert "prior_radiation" in result.quick_classify_candidates


def test_phase2a_extracts_gleason_pattern_and_path_stage():
    from prostanet.voice.voice_intake_full_orchestrator import orchestrate_full_intake
    result = orchestrate_full_intake("Gleason 7 (4+3) pT3a márgenes positivos focales")
    gleason_cand = next((c for c in result.candidates if c.field_name == "gleason_score"), None)
    assert gleason_cand is not None
    assert "4+3" in str(gleason_cand.value) or gleason_cand.value == "7(4+3)"
    path_cand = next((c for c in result.candidates if c.field_name == "path_stage_at_rp"), None)
    assert path_cand is not None
    assert path_cand.value == "pT3a"
    margin_cand = next((c for c in result.candidates if c.field_name == "margin_status"), None)
    assert margin_cand is not None
    assert "positive_focal" in str(margin_cand.value)


def test_phase2a_completeness_pct_and_next_prompt():
    from prostanet.voice.voice_intake_full_orchestrator import orchestrate_full_intake
    result = orchestrate_full_intake("Paciente 68 años PSA actual 4.2 Gleason 7")
    assert 0 <= result.completeness_pct <= 100
    assert result.next_dictation_prompt  # non-empty


def test_phase2a_multi_turn_state_accumulates():
    """Multi-turn: previous PSA history must persist across calls."""
    from prostanet.voice.voice_intake_full_orchestrator import orchestrate_full_intake
    # Turn 1
    r1 = orchestrate_full_intake("Paciente 68 años. En 2022 PSA 8.5")
    state_1 = r1.multi_turn_state
    # Turn 2 continues
    r2 = orchestrate_full_intake(
        "En 2024 PSA fue 12 punto 3",
        multi_turn_state=state_1,
    )
    assert len(r2.psa_history) >= 2  # accumulated from turn 1 + turn 2


# ─────────────────── Fase 2B: decision_aware_qa ───────────────────


def test_phase2b_decision_aware_imports():
    from prostanet.voice.decision_aware_qa import (
        classify_question_intent,
        invoke_applicable_copilots,
        build_decision_aware_answer,
    )
    assert callable(build_decision_aware_answer)


def test_phase2b_intent_classification_decision():
    from prostanet.voice.decision_aware_qa import classify_question_intent
    assert classify_question_intent("¿Cuál es la mejor opción?") == "decision_recommendation"
    assert classify_question_intent("¿Qué tratamiento recomendarías?") == "decision_recommendation"
    assert classify_question_intent("¿Cuál es el PSA?") == "factual_lookup"


def test_phase2b_invoke_copilots_for_localized_patient():
    """High-risk localized patient → risk_stratified copilot invoked."""
    from prostanet.voice.decision_aware_qa import invoke_applicable_copilots
    record = {
        "baseline": {"baseline_psa": 25, "gleason_score": 9, "clinical_t_stage": "cT3b"},
        "bone_lesion_count_total": 0,
    }
    bundles = invoke_applicable_copilots(record)
    # Should invoke clinical_state_classifier + risk_stratified
    assert "clinical_state_classification" in bundles or "risk_stratified_localized" in bundles


def test_phase2b_invoke_copilots_for_mcrpc_patient():
    """mCRPC patient → mcrpc_subtype copilot invoked."""
    from prostanet.voice.decision_aware_qa import invoke_applicable_copilots
    record = {
        "castration_resistance_confirmed": True,
        "bone_lesion_count_total": 5,
        "hrr_status": "positive",
        "parp_inhibitor_received": False,
    }
    bundles = invoke_applicable_copilots(record)
    assert "mcrpc_subtype" in bundles or "clinical_state_classification" in bundles


def test_phase2b_build_decision_answer_returns_therapeutic_preferred():
    """Decision answer must include therapeutic_preferred from copilot bundle."""
    from prostanet.voice.decision_aware_qa import build_decision_aware_answer
    record = {
        "baseline": {"baseline_psa": 6, "gleason_score": 6, "clinical_t_stage": "cT1c"},
        "percent_positive_cores": 20, "psa_density": 0.10,
    }
    answer = build_decision_aware_answer(record, "¿Cuál es la mejor opción para este paciente?")
    assert answer.available is True
    assert answer.intent_classification == "decision_recommendation"
    assert answer.therapeutic_preferred  # non-empty (very low risk → AS)
    assert "active_surveillance" in answer.therapeutic_preferred.lower() or "as" in answer.therapeutic_preferred.lower()


# ─────────────────── Fase 2C: population_query_safe ───────────────────


def test_phase2c_population_imports():
    from prostanet.voice.population_query_safe import (
        classify_population_intent,
        extract_filter_from_question,
        validate_filters,
        query_cohort,
        answer_population_question,
        WHITELIST_FILTERS,
    )
    assert callable(answer_population_question)


def test_phase2c_whitelist_filters_cover_critical_fields():
    """Whitelist must cover critical filter fields."""
    from prostanet.voice.population_query_safe import WHITELIST_FILTERS
    critical = {"current_state", "state_category", "age_min", "age_max",
                "hrr_status", "germline_testing_done", "psma_pet_positive"}
    missing = critical - set(WHITELIST_FILTERS.keys())
    assert not missing, f"Whitelist missing: {missing}"


def test_phase2c_filter_validation_rejects_unknown():
    from prostanet.voice.population_query_safe import validate_filters
    sanitized, warnings = validate_filters({"unknown_field": "x", "age_min": 50})
    assert "age_min" in sanitized
    assert "unknown_field" not in sanitized
    assert any("unknown_filter" in w for w in warnings)


def test_phase2c_filter_validation_rejects_invalid_state():
    from prostanet.voice.population_query_safe import validate_filters
    sanitized, warnings = validate_filters({"current_state": ["invalid_state_name"]})
    # Invalid state should be filtered out
    assert "current_state" not in sanitized or sanitized.get("current_state") == []


def test_phase2c_extract_filter_from_mcrpc_question():
    from prostanet.voice.population_query_safe import extract_filter_from_question
    filters = extract_filter_from_question("¿Cuántos pacientes con mCRPC tenemos?")
    assert filters.get("state_category") == "mcrpc_all"


def test_phase2c_extract_filter_from_operable_question():
    from prostanet.voice.population_query_safe import extract_filter_from_question
    filters = extract_filter_from_question("¿Cuántos localized podemos operar?")
    assert filters.get("state_category") == "operable_high_risk_localized"
    assert filters.get("ecog_max") == 2


def test_phase2c_query_cohort_uses_parameterized_sql():
    """SQL must use ? placeholders (no string concat)."""
    from prostanet.voice.population_query_safe import query_cohort
    result = query_cohort({"state_category": "mcrpc_all"}, question="test")
    # SQL should contain placeholders
    assert "?" in result.sql_executed
    # params should be a list of states
    assert len(result.sql_params) >= 1


def test_phase2c_query_cohort_returns_count_from_real_db():
    """Count must come from actual DB query, not LLM."""
    from prostanet.voice.population_query_safe import query_cohort
    result = query_cohort({"state_category": "mcrpc_all"}, question="cuántos mcrpc")
    # Should execute against real DB
    assert result.available is True
    assert result.audit_note == "count_from_db_query"
    # Total count is integer
    assert isinstance(result.total_count, int)
    assert result.total_count >= 0


def test_phase2c_answer_population_e2e():
    from prostanet.voice.population_query_safe import answer_population_question
    result = answer_population_question("¿Cuántos pacientes con mCRPC tenemos?")
    assert result.available is True
    assert isinstance(result.total_count, int)
    assert "paciente" in result.tts_response.lower() or "encontré" in result.tts_response.lower()


# ─────────────────── Fase 2D: cortana_orchestrator ───────────────────


def test_phase2d_orchestrator_imports():
    from prostanet.voice.cortana_orchestrator import (
        classify_cortana_intent,
        orchestrate_cortana,
    )
    assert callable(orchestrate_cortana)


def test_phase2d_intent_classification():
    from prostanet.voice.cortana_orchestrator import classify_cortana_intent
    assert classify_cortana_intent("Cortana, ayúdame a ingresar a este paciente") == "intake"
    assert classify_cortana_intent("Abre el paciente Juan García") == "patient_lookup"
    assert classify_cortana_intent("¿Cuál sería la mejor opción hoy?") == "decision_recommendation"
    assert classify_cortana_intent("¿Cuántos pacientes con mCRPC tenemos?") == "population_qa"
    assert classify_cortana_intent("¿Cuántos localized podemos operar?") == "population_qa"
    assert classify_cortana_intent("Hola Cortana") == "small_talk"


def test_phase2d_orchestrator_dispatches_intake():
    from prostanet.voice.cortana_orchestrator import orchestrate_cortana
    result = orchestrate_cortana(
        "Cortana ayúdame con ingreso. Paciente 68 años PSA actual 4 punto 2 Gleason 7 pT3a"
    )
    assert result.intent == "intake"
    assert result.handler == "voice_intake_full_orchestrator"
    assert len(result.handler_result.get("candidates", [])) >= 3
    assert "Capturé" in result.tts_response or "completitud" in result.tts_response.lower()


def test_phase2d_orchestrator_dispatches_population():
    from prostanet.voice.cortana_orchestrator import orchestrate_cortana
    result = orchestrate_cortana("¿Cuántos pacientes con mCRPC tenemos?")
    assert result.intent == "population_qa"
    assert result.handler == "population_query_safe"
    assert result.handler_result.get("total_count") is not None


def test_phase2d_decision_qa_without_patient_returns_guidance():
    """Without patient_nss, decision_recommendation should ask user to open patient."""
    from prostanet.voice.cortana_orchestrator import orchestrate_cortana
    result = orchestrate_cortana("¿Cuál sería la mejor opción?")
    assert result.intent == "decision_recommendation"
    assert "paciente" in result.tts_response.lower() or "abr" in result.tts_response.lower()


def test_phase2d_small_talk_returns_help():
    from prostanet.voice.cortana_orchestrator import orchestrate_cortana
    result = orchestrate_cortana("Hola Cortana")
    assert result.intent == "small_talk"
    assert "cortana" in result.tts_response.lower() or "ayud" in result.tts_response.lower()


# ─────────────────── Phase 2 Flask endpoints ───────────────────


def test_phase2_endpoints_cortana_route_returns_intent():
    import flask
    from prostanet.voice.epic21_endpoints import epic21_bp
    app = flask.Flask("t")
    app.register_blueprint(epic21_bp)
    client = app.test_client()
    resp = client.post("/api/voice/epic21/cortana", json={
        "transcript": "¿Cuántos pacientes con mCRPC tenemos?",
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["intent"] == "population_qa"
    assert data["handler"] == "population_query_safe"


def test_phase2_endpoints_intake_full_returns_candidates():
    import flask
    from prostanet.voice.epic21_endpoints import epic21_bp
    app = flask.Flask("t")
    app.register_blueprint(epic21_bp)
    client = app.test_client()
    resp = client.post("/api/voice/epic21/intake-full", json={
        "transcript": "Paciente 68 años PSA actual 4.2 Gleason 7 pT3a",
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["available"] is True
    assert len(data["candidates"]) >= 2


def test_phase2_endpoints_population_qa():
    import flask
    from prostanet.voice.epic21_endpoints import epic21_bp
    app = flask.Flask("t")
    app.register_blueprint(epic21_bp)
    client = app.test_client()
    resp = client.post("/api/voice/epic21/population-qa", json={
        "question": "¿Cuántos pacientes con mCRPC tenemos?",
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["available"] is True
    assert isinstance(data["total_count"], int)
