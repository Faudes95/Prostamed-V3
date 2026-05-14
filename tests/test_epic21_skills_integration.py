# IEC 62304 §5.7 — EPIC 21 Skills Integration (7 voice skills applied)
"""Tests for EPIC 21 skills integration:
  /voice         — voice capture pipeline (validated via API)
  /voice-agents  — AGENTS.md formal contract
  /voice-update  — unified_extractor.py (combines legacy + EPIC 20)
  /voice-note-ingest — validated via micro_form_extractor (EPIC 21 base)
  /voice-ai-development — grounding firewall (EPIC 21 base)
  /voice-ai-engine-development — clinical_vocabulary_boost.py (Whisper prompt)
  /writing-voice — tts_phrasing.py (safety-aware TTS responses)
"""
from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent


# ─────────────────── /voice-agents ───────────────────


def test_voice_agents_AGENTS_md_exists():
    path = PROJECT_ROOT / "prostanet" / "voice" / "AGENTS.md"
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    # Key contract sections
    for section in [
        "Agent identity",
        "Capability matrix",
        "Tool contracts",
        "Conversation flow",
        "Voice-specific design rules",
        "Audit + observability",
        "Compliance + safety statements",
    ]:
        assert section in content, f"AGENTS.md missing section: {section}"


def test_voice_agents_documents_grounding_firewall_safety():
    path = PROJECT_ROOT / "prostanet" / "voice" / "AGENTS.md"
    content = path.read_text(encoding="utf-8")
    # Safety mechanisms must be documented
    assert "hallucination" in content.lower() or "firewall" in content.lower()
    assert "audit" in content.lower()
    assert "internal_shadow_observational_validation" in content


# ─────────────────── /voice-update ───────────────────


def test_voice_update_unified_extractor_importable():
    from prostanet.voice.unified_extractor import (
        extract_all_candidates,
        get_extractor_capabilities,
    )
    assert callable(extract_all_candidates)


def test_voice_update_unified_combines_legacy_and_micro_form():
    """Unified extractor returns candidates from both sources."""
    from prostanet.voice.unified_extractor import extract_all_candidates
    transcript = "PSA actual 4 punto 2 Gleason 7 (4+3) ECOG 1 etapa pT3a"
    cands = extract_all_candidates(transcript, moment="bcr_detection")
    # At least micro-form candidates should appear (legacy may or may not, depending on its impl)
    assert isinstance(cands, list)
    mf_cands = [c for c in cands if c.get("source") == "micro_form"]
    assert len(mf_cands) >= 3, f"Expected ≥3 micro_form candidates, got {len(mf_cands)}"


def test_voice_update_unified_no_moment_runs_legacy_only():
    """Without moment param, only legacy extractor runs."""
    from prostanet.voice.unified_extractor import extract_all_candidates
    cands = extract_all_candidates("PSA 4.2", moment=None)
    assert isinstance(cands, list)
    # No micro_form source expected
    mf_cands = [c for c in cands if c.get("source") == "micro_form"]
    assert len(mf_cands) == 0


def test_voice_update_capabilities_reports_both():
    """EPIC 22b.2 added `biopsy_capture` (7th moment). Contract relaxed to
    ≥6 + must include the 6 original EPIC 20 moments so future micro-forms
    can be appended without breaking this regression gate.
    """
    from prostanet.voice.unified_extractor import get_extractor_capabilities
    caps = get_extractor_capabilities()
    assert "legacy_extractor" in caps
    assert "micro_form_extractor" in caps
    assert caps["micro_form_extractor"]["available"] is True
    moments = caps["micro_form_extractor"]["moments_covered"]
    assert len(moments) >= 6
    original_six = {"bcr_detection", "oligoprogression", "crpc_transition",
                    "adt_init", "rt_nadir", "salvage_eligibility"}
    assert original_six.issubset(set(moments)), (
        f"EPIC 21 original moments missing: {original_six - set(moments)}"
    )


# ─────────────────── /voice-ai-engine-development ───────────────────


def test_voice_ai_engine_vocabulary_boost_importable():
    from prostanet.voice.clinical_vocabulary_boost import (
        get_stt_initial_prompt,
        get_vocabulary_stats,
        get_full_vocabulary,
    )
    assert callable(get_stt_initial_prompt)


def test_voice_ai_engine_vocabulary_covers_pivotal_trials():
    from prostanet.voice.clinical_vocabulary_boost import PIVOTAL_TRIAL_ACRONYMS
    must_have = {"CHAARTED", "VISION", "ARASENS", "LATITUDE", "PROfound"}
    missing = must_have - set(PIVOTAL_TRIAL_ACRONYMS)
    assert not missing, f"Vocabulary missing pivotal trials: {missing}"


def test_voice_ai_engine_vocabulary_covers_key_drugs():
    from prostanet.voice.clinical_vocabulary_boost import DRUG_NAMES_ES
    must_have_lower = {"abiraterona", "enzalutamida", "docetaxel", "olaparib", "lutetium-177"}
    actual_lower = {d.lower() for d in DRUG_NAMES_ES}
    missing = must_have_lower - actual_lower
    assert not missing, f"Vocabulary missing drugs: {missing}"


def test_voice_ai_engine_stt_prompt_within_whisper_limits():
    """Whisper recommends initial_prompt ≤ 224 tokens (~1KB)."""
    from prostanet.voice.clinical_vocabulary_boost import get_stt_initial_prompt
    prompt = get_stt_initial_prompt(language="es", max_chars=1024)
    assert len(prompt) <= 1024
    assert "PSA" in prompt or "Gleason" in prompt  # core clinical terms present


def test_voice_ai_engine_stt_prompt_filtered_categories():
    """include_categories filter works."""
    from prostanet.voice.clinical_vocabulary_boost import get_stt_initial_prompt
    drugs_only = get_stt_initial_prompt(include_categories=["drugs"])
    assert "abiraterona" in drugs_only
    assert "PSADT" not in drugs_only  # PSADT is in "clinical" category, not "drugs"


def test_voice_ai_engine_vocabulary_stats():
    from prostanet.voice.clinical_vocabulary_boost import get_vocabulary_stats
    stats = get_vocabulary_stats()
    assert stats["scope"] == "prostate_cancer_oncology"
    assert stats["total_unique_terms"] >= 100  # comprehensive coverage
    assert set(stats["categories"].keys()) >= {"trials", "drugs", "clinical", "genomic"}


# ─────────────────── /writing-voice ───────────────────


def test_writing_voice_tts_phrasing_importable():
    from prostanet.voice.tts_phrasing import (
        build_tts_response,
        build_disambiguation_response,
        build_confirmation_response,
        build_intake_confirmation,
        build_clarification_prompt,
        validate_tts_text,
    )
    assert callable(build_tts_response)


def test_writing_voice_tts_factual_prefixes_date():
    from prostanet.voice.tts_phrasing import build_tts_response
    resp = build_tts_response(
        "El PSA es 4.2 ng/mL",
        record_date="2026-05-13",
        answer_type="factual",
    )
    assert "Según el registro del 2026-05-13" in resp
    assert "4.2" in resp


def test_writing_voice_tts_missing_uses_template():
    from prostanet.voice.tts_phrasing import build_tts_response
    resp = build_tts_response("", answer_type="missing", language="es")
    assert "no tengo ese dato" in resp.lower()


def test_writing_voice_tts_scrubs_forbidden_phrases():
    """'Yo creo que' and 'probablemente' must be removed."""
    from prostanet.voice.tts_phrasing import build_tts_response
    resp = build_tts_response(
        "Yo creo que el PSA es probablemente 4.2",
        record_date="2026-05-13",
    )
    assert "yo creo" not in resp.lower()
    assert "probablemente" not in resp.lower()
    assert "4.2" in resp  # core content preserved


def test_writing_voice_disambiguation_response():
    from prostanet.voice.tts_phrasing import build_disambiguation_response
    resp = build_disambiguation_response(
        candidate_count=2,
        candidates_summary=["Juan García López (NSS 1234)", "Juan García Martín (NSS 5678)"],
    )
    assert "2 pacientes" in resp
    assert "García" in resp
    assert "?" in resp  # ends in question


def test_writing_voice_intake_low_confidence_prompts_confirm():
    """Low confidence triggers explicit confirmation request."""
    from prostanet.voice.tts_phrasing import build_intake_confirmation
    resp = build_intake_confirmation(
        field_label="PSA actual",
        value=4.2,
        unit="ng/mL",
        confidence=0.65,
    )
    assert "Baja confianza" in resp or "low confidence" in resp.lower()
    assert "4.2" in resp


def test_writing_voice_clarification_prompt_pattern():
    from prostanet.voice.tts_phrasing import build_clarification_prompt
    resp = build_clarification_prompt(
        ambiguous_value="4.2",
        candidates=["4 punto 2", "14 punto 2"],
        field_label="PSA",
    )
    assert "PSA" in resp
    assert "4 punto 2" in resp
    assert "14 punto 2" in resp


def test_writing_voice_validate_tts_catches_forbidden():
    """validate_tts_text flags forbidden phrases."""
    from prostanet.voice.tts_phrasing import validate_tts_text
    result = validate_tts_text("Yo creo que probablemente sí.")
    assert result["valid"] is False
    assert len(result["forbidden_phrases_found"]) >= 1


def test_writing_voice_validate_tts_catches_too_many_sentences():
    """Voice attention is limited — flag >2 sentences."""
    from prostanet.voice.tts_phrasing import validate_tts_text
    long = "Frase uno. Frase dos. Frase tres. Frase cuatro."
    result = validate_tts_text(long, max_sentences=2)
    assert result["valid"] is False
    assert any("too_many_sentences" in i for i in result["issues"])


def test_writing_voice_validate_clean_text_passes():
    from prostanet.voice.tts_phrasing import validate_tts_text
    result = validate_tts_text("Según el registro del 13 de mayo: PSA 4.2.")
    assert result["valid"] is True
    assert result["forbidden_phrases_found"] == []
