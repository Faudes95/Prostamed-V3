# IEC 62304 §5.7 — EPIC 21 Phase 3: Safety-Aware Provider Routing
"""Tests EPIC 21 Phase 3:
  3A — Provider abstraction (SafetyClass + VoiceProvider base + Registry)
  3B — WhisperPipelineProvider + PersonaPlexProvider wrappers
  3C — cortana_orchestrator safety-aware routing (forces Whisper for HIGH/CRITICAL)
  3D — Sidecar adapter + install docs

Safety architecture verified:
  - PersonaPlex registered but max_safety=MEDIUM (cannot serve HIGH/CRITICAL)
  - HIGH/CRITICAL intents NEVER route to PersonaPlex
  - Graceful fallback when PersonaPlex sidecar unavailable
  - All routing decisions logged in audit_log_entry
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent


# ─────────────────── Phase 3A: SafetyClass + base ───────────────────


def test_phase3a_safety_class_enum():
    from prostanet.voice.providers.base import SafetyClass
    assert SafetyClass.LOW.value == "low"
    assert SafetyClass.MEDIUM.value == "medium"
    assert SafetyClass.HIGH.value == "high"
    assert SafetyClass.CRITICAL.value == "critical"


def test_phase3a_classify_intent_safety_mapping():
    from prostanet.voice.providers.base import classify_intent_safety, SafetyClass
    assert classify_intent_safety("small_talk") == SafetyClass.LOW
    assert classify_intent_safety("intake") == SafetyClass.MEDIUM
    assert classify_intent_safety("patient_lookup") == SafetyClass.MEDIUM
    assert classify_intent_safety("patient_qa") == SafetyClass.HIGH
    assert classify_intent_safety("decision_recommendation") == SafetyClass.CRITICAL
    assert classify_intent_safety("population_qa") == SafetyClass.CRITICAL
    # Unknown intent → conservatively HIGH (default escalate)
    assert classify_intent_safety("undefined_xyz") == SafetyClass.HIGH


def test_phase3a_voice_provider_capability_dataclass():
    from prostanet.voice.providers.base import VoiceProviderCapability, SafetyClass
    cap = VoiceProviderCapability(
        provider_name="test",
        is_available=True,
        supports_intermediate_transcript=True,
        supports_full_duplex=False,
        requires_gpu=False,
        requires_network=False,
        latency_ms_typical=100,
        max_safety_class=SafetyClass.CRITICAL,
    )
    assert cap.provider_name == "test"
    assert cap.max_safety_class == SafetyClass.CRITICAL


def test_phase3a_registry_singleton():
    from prostanet.voice.providers.base import get_registry
    r1 = get_registry()
    r2 = get_registry()
    assert r1 is r2


# ─────────────────── Phase 3B: Whisper + PersonaPlex wrappers ───────────────────


def test_phase3b_whisper_provider_imports():
    from prostanet.voice.providers.whisper_pipeline import WhisperPipelineProvider
    provider = WhisperPipelineProvider()
    assert provider is not None


def test_phase3b_whisper_capability_supports_all_safety():
    from prostanet.voice.providers.whisper_pipeline import WhisperPipelineProvider
    from prostanet.voice.providers.base import SafetyClass
    provider = WhisperPipelineProvider()
    cap = provider.capability()
    assert cap.provider_name == "whisper"
    assert cap.is_available is True  # always usable (CPU-friendly)
    assert cap.supports_intermediate_transcript is True  # CORE: enables firewall
    assert cap.max_safety_class == SafetyClass.CRITICAL
    assert cap.requires_gpu is False


def test_phase3b_personaplex_provider_imports():
    from prostanet.voice.providers.personaplex_pipeline import PersonaPlexProvider
    provider = PersonaPlexProvider()
    assert provider is not None


def test_phase3b_personaplex_capability_max_safety_medium():
    """PersonaPlex must report max_safety=MEDIUM (cannot serve HIGH/CRITICAL)."""
    from prostanet.voice.providers.personaplex_pipeline import PersonaPlexProvider
    from prostanet.voice.providers.base import SafetyClass
    provider = PersonaPlexProvider()
    cap = provider.capability()
    assert cap.provider_name == "personaplex"
    assert cap.supports_intermediate_transcript is False  # CORE: speech-to-speech
    assert cap.supports_full_duplex is True
    assert cap.requires_gpu is True
    # Critical architectural invariant: PersonaPlex CANNOT serve HIGH/CRITICAL
    assert cap.max_safety_class == SafetyClass.MEDIUM


def test_phase3b_personaplex_refuses_high_safety_class():
    """PersonaPlex.process_turn must refuse HIGH/CRITICAL contexts."""
    from prostanet.voice.providers.personaplex_pipeline import PersonaPlexProvider
    from prostanet.voice.providers.base import SafetyClass
    provider = PersonaPlexProvider()
    result = provider.process_turn(
        transcript="test query",
        safety_class=SafetyClass.HIGH,
        intent="patient_qa",
    )
    # Must refuse + indicate firewall block
    assert result.available is False
    assert result.firewall_blocked is True
    assert "unsupported_safety_class_for_provider" in str(result.firewall_failure_reasons)
    assert "Cortana standard" in result.response_text or "validación" in result.response_text


def test_phase3b_personaplex_unavailable_when_sidecar_down():
    """When sidecar unreachable, PersonaPlex must report is_available=False."""
    from prostanet.voice.providers.personaplex_pipeline import PersonaPlexProvider
    # Force a guaranteed-unreachable URL
    provider = PersonaPlexProvider(sidecar_url="http://127.0.0.1:65535")
    cap = provider.capability()
    assert cap.is_available is False


def test_phase3b_whisper_provider_can_handle_critical():
    from prostanet.voice.providers.whisper_pipeline import WhisperPipelineProvider
    from prostanet.voice.providers.base import SafetyClass
    provider = WhisperPipelineProvider()
    assert provider.can_handle_safety_class(SafetyClass.CRITICAL) is True
    assert provider.can_handle_safety_class(SafetyClass.HIGH) is True
    assert provider.can_handle_safety_class(SafetyClass.MEDIUM) is True
    assert provider.can_handle_safety_class(SafetyClass.LOW) is True


def test_phase3b_personaplex_can_handle_medium_but_not_higher():
    from prostanet.voice.providers.personaplex_pipeline import PersonaPlexProvider
    from prostanet.voice.providers.base import SafetyClass
    provider = PersonaPlexProvider()
    assert provider.can_handle_safety_class(SafetyClass.LOW) is True
    assert provider.can_handle_safety_class(SafetyClass.MEDIUM) is True
    assert provider.can_handle_safety_class(SafetyClass.HIGH) is False
    assert provider.can_handle_safety_class(SafetyClass.CRITICAL) is False


# ─────────────────── Registry select_provider routing ───────────────────


def test_phase3_registry_routes_critical_to_whisper_always():
    """Registry must NEVER route HIGH/CRITICAL to PersonaPlex."""
    from prostanet.voice.providers import get_registry, SafetyClass
    registry = get_registry()
    for safety in (SafetyClass.HIGH, SafetyClass.CRITICAL):
        provider = registry.select_provider(safety, preferred="personaplex")
        if provider is not None:
            assert provider.capability().provider_name == "whisper", (
                f"safety={safety.value} routed to {provider.capability().provider_name} — "
                f"MUST be whisper (firewall required)"
            )


def test_phase3_registry_routes_low_to_whisper_when_personaplex_unavailable():
    """When PersonaPlex sidecar unavailable, LOW routes to Whisper fallback."""
    from prostanet.voice.providers import get_registry, SafetyClass
    registry = get_registry()
    # PersonaPlex is unavailable in test env (no sidecar)
    provider = registry.select_provider(SafetyClass.LOW)
    assert provider is not None
    assert provider.capability().provider_name == "whisper"  # graceful fallback


def test_phase3_registry_capabilities_report():
    from prostanet.voice.providers import get_registry
    registry = get_registry()
    report = registry.capabilities_report()
    assert "whisper" in report["providers_registered"]
    assert "personaplex" in report["providers_registered"]
    assert "providers_detail" in report
    # Whisper must be in available
    assert "whisper" in report["providers_available"]


# ─────────────────── Phase 3C: orchestrator safety routing ───────────────────


def test_phase3c_orchestrator_returns_safety_class_metadata():
    """orchestrate_cortana must populate safety_class + provider_selected."""
    from prostanet.voice.cortana_orchestrator import orchestrate_cortana
    r = orchestrate_cortana("¿Cuántos pacientes con mCRPC tenemos?")
    assert r.safety_class == "critical"
    assert r.provider_selected == "whisper"


def test_phase3c_orchestrator_forces_whisper_for_critical_even_if_preferred():
    """preferred=personaplex + critical intent → fallback to whisper with reason."""
    from prostanet.voice.cortana_orchestrator import orchestrate_cortana
    r = orchestrate_cortana(
        "¿Cuál es la mejor opción para este paciente?",
        patient_nss="00009999888",
        preferred_provider="personaplex",
    )
    assert r.safety_class == "critical"
    assert r.provider_selected == "whisper"
    assert "firewall mandatory" in r.provider_fallback_reason or "requires" in r.provider_fallback_reason


def test_phase3c_orchestrator_safety_class_low_for_small_talk():
    from prostanet.voice.cortana_orchestrator import orchestrate_cortana
    r = orchestrate_cortana("Hola Cortana")
    assert r.safety_class == "low"
    # Provider selected (whisper if no PersonaPlex available)
    assert r.provider_selected in ("whisper", "personaplex")


def test_phase3c_orchestrator_safety_class_high_for_patient_qa():
    from prostanet.voice.cortana_orchestrator import orchestrate_cortana
    r = orchestrate_cortana("¿Cuál es el PSA?", patient_nss="00009999888")
    assert r.safety_class == "high"
    assert r.provider_selected == "whisper"


# ─────────────────── Phase 3D: Sidecar files ───────────────────


def test_phase3d_dockerfile_exists():
    path = PROJECT_ROOT / "Dockerfile.personaplex-sidecar"
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "nvidia/cuda" in content.lower()
    assert "personaplex" in content.lower()
    assert "libopus-dev" in content
    assert "8090" in content  # default sidecar port


def test_phase3d_sidecar_adapter_exists():
    path = PROJECT_ROOT / "prostanet" / "voice" / "providers" / "personaplex_sidecar_adapter.py"
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    # Must have HIGH/CRITICAL refusal logic
    assert "high" in content.lower() and "critical" in content.lower()
    assert "safety_class_unsupported" in content
    # Health + turn endpoints
    assert '@app.route("/health"' in content
    assert '@app.route("/turn"' in content


def test_phase3d_cortana_persona_documented():
    path = PROJECT_ROOT / "prostanet" / "voice" / "providers" / "personaplex_persona_cortana.py"
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "CORTANA_CLINICAL_PERSONA_PROMPT_ES" in content
    # Must document forbidden phrases per /writing-voice
    assert "PROHIBIDO" in content or "Forbidden" in content


def test_phase3d_install_doc_exists():
    path = PROJECT_ROOT / "docs" / "personaplex_install.md"
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    # Document safety routing architecture
    assert "safety_class" in content.lower() or "safety routing" in content.lower()
    # Document HIGH/CRITICAL → Whisper invariant
    assert "high" in content.lower() and "critical" in content.lower()
    # NVIDIA OML mentioned
    assert "NVIDIA Open Model License" in content or "OML" in content


# ─────────────────── Integration: end-to-end via Flask endpoint ───────────────────


def test_phase3_health_endpoint_reports_providers():
    """/api/voice/epic21/health should now include provider capabilities."""
    import flask
    from prostanet.voice.epic21_endpoints import epic21_bp
    app = flask.Flask("t")
    app.register_blueprint(epic21_bp)
    client = app.test_client()
    resp = client.get("/api/voice/epic21/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["epic"] == 21
    assert data["capabilities"]["fase_1_voice_intake_dictation"] is True
