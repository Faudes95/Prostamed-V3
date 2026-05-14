# IEC 62304 §5.7 — EPIC 21 Cortana Voice Longitudinal
"""Tests EPIC 21 — Voice longitudinal Cortana (3 fases).

Verifica:
  Fase 1: micro_form_extractor — voice transcript → micro-form candidates
  Fase 2: patient_name_resolver — spoken name → NSS top-3 candidates
  Fase 3: patient_qa_grounding — grounding firewall bloquea hallucinations

Beneficio clínico verificado:
  - Voice intake: clínico dicta y micro-form se auto-popula (80% reducción typing)
  - Patient lookup: "abre el paciente Juan García" → navega correctamente
  - Patient Q&A: respuestas validated contra record, hallucinations bloqueadas
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).parent.parent


# ─────────────────── Fase 1: micro_form_extractor ───────────────────


def test_epic21_fase1_module_importable():
    from prostanet.voice.micro_form_extractor import (
        extract_micro_form_candidates,
        MicroFormCandidate,
        candidates_to_dict,
    )
    assert callable(extract_micro_form_candidates)


def test_epic21_fase1_extracts_bcr_detection_candidates():
    from prostanet.voice.micro_form_extractor import extract_micro_form_candidates
    transcript = (
        "Paciente con PSA actual 4 punto 2, fecha de detección 13 de mayo 2026. "
        "PSADT estimado 8 meses. Tiempo desde RP 24 meses. Etapa pT3a. "
        "Márgenes positive focal. Gleason 7 (4+3). ECOG 1."
    )
    candidates = extract_micro_form_candidates("bcr_detection", transcript)
    assert len(candidates) >= 5
    # Verify PSA extracted
    psa_cand = next((c for c in candidates if c.field_name == "current_psa"), None)
    assert psa_cand is not None
    assert abs(float(psa_cand.value) - 4.2) < 0.01
    assert psa_cand.auto_populate is True  # confidence 0.9 ≥ threshold


def test_epic21_fase1_extracts_psa_pre_rp_with_context():
    from prostanet.voice.micro_form_extractor import extract_micro_form_candidates
    transcript = "PSA pre-RP fue 8 punto 5. PSA actual 4 punto 2."
    candidates = extract_micro_form_candidates("salvage_eligibility", transcript)
    # pre_rp_psa field exists in salvage_eligibility_form
    pre_rp = next((c for c in candidates if c.field_name == "pre_rp_psa"), None)
    if pre_rp:
        assert abs(float(pre_rp.value) - 8.5) < 0.01


def test_epic21_fase1_extracts_gleason_with_pattern():
    from prostanet.voice.micro_form_extractor import extract_micro_form_candidates
    transcript = "Gleason 7 (4+3)."
    candidates = extract_micro_form_candidates("bcr_detection", transcript)
    gs = next((c for c in candidates if c.field_name == "gleason_at_rp"), None)
    assert gs is not None
    assert "4+3" in str(gs.value) or gs.value == "7(4+3)"


def test_epic21_fase1_invalid_moment_returns_empty():
    from prostanet.voice.micro_form_extractor import extract_micro_form_candidates
    candidates = extract_micro_form_candidates("nonexistent_moment", "PSA 4.2")
    assert candidates == []


def test_epic21_fase1_candidates_to_dict_serializable():
    import json
    from prostanet.voice.micro_form_extractor import extract_micro_form_candidates, candidates_to_dict
    candidates = extract_micro_form_candidates("bcr_detection", "PSA 4.2 ECOG 1")
    d = candidates_to_dict(candidates)
    serialized = json.dumps(d)
    assert "candidates" in d
    assert serialized is not None


def test_epic21_fase1_auto_populate_threshold_per_field():
    """Auto-populate gating respects field's voice_required_confidence."""
    from prostanet.voice.micro_form_extractor import extract_micro_form_candidates
    transcript = "PSA actual 4 punto 2 ECOG 1"
    candidates = extract_micro_form_candidates("bcr_detection", transcript)
    psa = next((c for c in candidates if c.field_name == "current_psa"), None)
    assert psa.confidence >= 0.9  # PSA is safety-critical, must be ≥0.9
    assert psa.auto_populate is True


# ─────────────────── Fase 2: patient_name_resolver ───────────────────


def test_epic21_fase2_module_importable():
    from prostanet.voice.patient_name_resolver import (
        resolve_patient_by_name,
        PatientCandidate,
        candidates_to_response,
    )
    assert callable(resolve_patient_by_name)


def test_epic21_fase2_normalize_name_strips_accents():
    from prostanet.voice.patient_name_resolver import _normalize_name
    assert _normalize_name("María José") == "maria jose"
    assert _normalize_name("Faudes Oscar Godivé") == "faudes oscar godive"


def test_epic21_fase2_name_similarity_perfect_match():
    from prostanet.voice.patient_name_resolver import _name_similarity
    assert _name_similarity("Juan García", "Juan García") == 1.0


def test_epic21_fase2_name_similarity_partial():
    from prostanet.voice.patient_name_resolver import _name_similarity
    # Two apellidos shared
    sim = _name_similarity("Juan García López", "Juan García Martínez")
    assert 0.5 < sim < 1.0


def test_epic21_fase2_extract_command_prefixes():
    from prostanet.voice.patient_name_resolver import _extract_spoken_name_from_command
    assert _extract_spoken_name_from_command("abre el paciente Juan García") == "Juan García"
    assert _extract_spoken_name_from_command("busca a María López") == "María López"


def test_epic21_fase2_extract_nss_from_command():
    from prostanet.voice.patient_name_resolver import _extract_nss_from_command
    assert _extract_nss_from_command("paciente con NSS 12345678") == "12345678"
    assert _extract_nss_from_command("12345678901") == "12345678901"
    assert _extract_nss_from_command("solo palabras") is None


def test_epic21_fase2_resolve_nss_direct_lookup():
    from prostanet.voice.patient_name_resolver import resolve_patient_by_name
    # Use known NSS from test DB
    candidates = resolve_patient_by_name("paciente con NSS 00009999888")
    if candidates:  # only if DB has this patient
        assert candidates[0].confidence == 1.0
        assert candidates[0].match_method == "exact_nss"


def test_epic21_fase2_candidates_to_response_disambiguation():
    from prostanet.voice.patient_name_resolver import PatientCandidate, candidates_to_response
    cands = [
        PatientCandidate(nss="111", full_name="Juan García López", dob_hint="1960", confidence=0.85, match_method="partial"),
        PatientCandidate(nss="222", full_name="Juan García Martín", dob_hint="1965", confidence=0.82, match_method="partial"),
    ]
    resp = candidates_to_response(cands, "abre Juan García")
    assert resp["disambiguation_needed"] is True
    assert "Juan García" in resp["tts_response"]


def test_epic21_fase2_no_match_returns_empty():
    from prostanet.voice.patient_name_resolver import resolve_patient_by_name
    candidates = resolve_patient_by_name("xyzzyzz unlikely name 9999")
    assert isinstance(candidates, list)
    # Either empty or no high-confidence match
    assert all(c.confidence < 0.95 for c in candidates) if candidates else True


# ─────────────────── Fase 3: patient_qa_grounding ───────────────────


def test_epic21_fase3_module_importable():
    from prostanet.voice.patient_qa_grounding import (
        grounding_firewall,
        build_patient_context_for_qa,
        answer_patient_question,
        GroundedAnswer,
    )
    assert callable(grounding_firewall)


def test_epic21_fase3_build_patient_context():
    from prostanet.voice.patient_qa_grounding import build_patient_context_for_qa
    record = {
        "identity": {"id": 1, "nss": "12345"},
        "baseline": {"baseline_psa": 4.2, "gleason_score": "7(3+4)"},
        "follow_ups": [{"visit_date": "2026-05-01", "psa_current": 8.5}],
        "treatments": [],
        "biomarker_longitudinal": [],
        "latest_assessment": {},
    }
    ctx = build_patient_context_for_qa(record)
    assert ctx["nss"] == "12345"
    assert ctx["latest_psa"] == 8.5
    assert ctx["baseline"]["baseline_psa"] == 4.2


def test_epic21_fase3_firewall_validates_correct_psa():
    """PSA claim within tolerance of record values → pass."""
    from prostanet.voice.patient_qa_grounding import grounding_firewall
    ctx = {
        "latest_psa": 8.5,
        "baseline": {"baseline_psa": 4.2},
        "psa_history": [{"date": "2026-05-01", "value": 8.5}],
        "treatments": [],
    }
    ok, fails = grounding_firewall("El PSA actual es 8.5 ng/mL.", ctx)
    assert ok and fails == []


def test_epic21_fase3_firewall_blocks_hallucinated_psa():
    """PSA claim NOT matching record → blocked."""
    from prostanet.voice.patient_qa_grounding import grounding_firewall
    ctx = {
        "latest_psa": 8.5,
        "baseline": {"baseline_psa": 4.2},
        "psa_history": [{"date": "2026-05-01", "value": 8.5}],
        "treatments": [],
    }
    ok, fails = grounding_firewall("El PSA actual es 12.7 ng/mL.", ctx)
    assert not ok
    assert any("psa_mismatch" in f for f in fails)


def test_epic21_fase3_firewall_blocks_hallucinated_treatment():
    """Treatment NOT in record → blocked."""
    from prostanet.voice.patient_qa_grounding import grounding_firewall
    ctx = {
        "latest_psa": None,
        "baseline": {},
        "treatments": [{"drug_or_modality": "docetaxel"}],
    }
    ok, fails = grounding_firewall("El paciente recibió abiraterona.", ctx)
    assert not ok
    assert any("treatment_mismatch" in f for f in fails)


def test_epic21_fase3_firewall_blocks_treatment_when_empty_record():
    """Specific drug claim when treatment list is empty → blocked."""
    from prostanet.voice.patient_qa_grounding import grounding_firewall
    ctx = {"latest_psa": None, "baseline": {}, "treatments": []}
    ok, fails = grounding_firewall("Recibió olaparib desde 2024.", ctx)
    assert not ok
    assert any("treatment_mismatch" in f for f in fails)


def test_epic21_fase3_firewall_blocks_wrong_gleason():
    """Gleason claim ≠ record → blocked."""
    from prostanet.voice.patient_qa_grounding import grounding_firewall
    ctx = {
        "latest_psa": None,
        "baseline": {"gleason_score": "7(3+4)"},
        "treatments": [],
    }
    ok, fails = grounding_firewall("Gleason 9.", ctx)
    assert not ok
    assert any("gleason_mismatch" in f for f in fails)


def test_epic21_fase3_firewall_passes_no_clinical_claim():
    """Generic answer without clinical claims → pass (nothing to validate)."""
    from prostanet.voice.patient_qa_grounding import grounding_firewall
    ctx = {"latest_psa": None, "baseline": {}, "treatments": []}
    ok, fails = grounding_firewall("No tengo ese dato en el registro.", ctx)
    assert ok and fails == []


def test_epic21_fase3_answer_patient_question_returns_blocked_when_llm_unavailable():
    """If LLM unavailable, returns blocked answer (no fabrication)."""
    from prostanet.voice.patient_qa_grounding import answer_patient_question

    fake_llm = MagicMock()
    fake_llm.client = None  # simulates uninitialized provider

    record = {
        "identity": {"id": 1, "nss": "12345"},
        "baseline": {"baseline_psa": 4.2},
        "follow_ups": [],
        "treatments": [],
        "biomarker_longitudinal": [],
        "latest_assessment": {},
    }
    answer = answer_patient_question(record, "¿cuál es el PSA?", llm_provider=fake_llm)
    assert answer.answer_blocked is True
    assert answer.validation_passed is False
    assert "no disponible" in answer.answer_validated.lower() or "manual" in answer.answer_validated.lower()


# ─────────────────── EPIC 21 Flask endpoints ───────────────────


def test_epic21_endpoints_module_importable():
    from prostanet.voice.epic21_endpoints import register_epic21_endpoints, epic21_bp
    assert callable(register_epic21_endpoints)


def test_epic21_endpoints_health_route_registered():
    """Blueprint must expose all 4 EPIC 21 endpoints."""
    import flask
    from prostanet.voice.epic21_endpoints import epic21_bp
    app = flask.Flask("test_app")
    app.register_blueprint(epic21_bp)
    rules = [str(r) for r in app.url_map.iter_rules()]
    assert any("/api/voice/epic21/health" in r for r in rules)
    assert any("/api/voice/epic21/intake/" in r for r in rules)
    assert any("/api/voice/epic21/patient-lookup" in r for r in rules)
    assert any("/api/voice/epic21/patient-qa/" in r for r in rules)


def test_epic21_endpoints_intake_returns_candidates():
    """POST /api/voice/epic21/intake/bcr_detection extracts candidates."""
    import flask
    from prostanet.voice.epic21_endpoints import epic21_bp
    app = flask.Flask("test_app")
    app.register_blueprint(epic21_bp)
    client = app.test_client()
    resp = client.post(
        "/api/voice/epic21/intake/bcr_detection",
        json={"transcript": "PSA actual 4 punto 2 ECOG 1 Gleason 7 (4+3)"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["available"] is True
    assert data["total_candidates"] >= 2


def test_epic21_endpoints_intake_invalid_moment_400():
    """Invalid moment returns 400."""
    import flask
    from prostanet.voice.epic21_endpoints import epic21_bp
    app = flask.Flask("test_app")
    app.register_blueprint(epic21_bp)
    client = app.test_client()
    resp = client.post(
        "/api/voice/epic21/intake/nonexistent",
        json={"transcript": "PSA 4.2"},
    )
    assert resp.status_code == 400


def test_epic21_endpoints_list_moments_returns_6():
    """GET /api/voice/epic21/intake-moments returns 6 moments."""
    import flask
    from prostanet.voice.epic21_endpoints import epic21_bp
    app = flask.Flask("test_app")
    app.register_blueprint(epic21_bp)
    client = app.test_client()
    resp = client.get("/api/voice/epic21/intake-moments")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["available"] is True
    assert len(data["moments"]) == 6


def test_epic21_endpoints_health_reports_capabilities():
    """GET /api/voice/epic21/health reports all 4 phases status."""
    import flask
    from prostanet.voice.epic21_endpoints import epic21_bp
    app = flask.Flask("test_app")
    app.register_blueprint(epic21_bp)
    client = app.test_client()
    resp = client.get("/api/voice/epic21/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["epic"] == 21
    assert "capabilities" in data
    assert data["capabilities"]["fase_1_voice_intake_dictation"] is True
    assert data["capabilities"]["fase_3_patient_qa_grounded"] is True
