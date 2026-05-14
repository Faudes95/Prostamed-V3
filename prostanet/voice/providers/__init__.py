"""EPIC 21 Phase 3 — Voice Providers package.

Registers Whisper + PersonaPlex providers on import.

Usage:
    from prostanet.voice.providers import get_registry, SafetyClass
    registry = get_registry()
    provider = registry.select_provider(SafetyClass.HIGH)
    result = provider.process_turn(transcript="...", safety_class=SafetyClass.HIGH)
"""

from __future__ import annotations

import logging

from prostanet.voice.providers.base import (
    SafetyClass,
    VoiceProvider,
    VoiceProviderCapability,
    VoiceProviderRegistry,
    VoiceTurnResult,
    classify_intent_safety,
    get_registry,
)

logger = logging.getLogger(__name__)


def _register_default_providers() -> None:
    """Register Whisper + PersonaPlex on package import."""
    registry = get_registry()
    # Whisper: always register (works on CPU, supports all safety classes)
    try:
        from prostanet.voice.providers.whisper_pipeline import WhisperPipelineProvider
        if "whisper" not in registry._providers:
            registry.register("whisper", WhisperPipelineProvider(), preference=70)
    except Exception as exc:
        logger.warning("Whisper provider registration failed: %s", exc)

    # PersonaPlex: register but is_available depends on sidecar health
    try:
        from prostanet.voice.providers.personaplex_pipeline import PersonaPlexProvider
        if "personaplex" not in registry._providers:
            registry.register("personaplex", PersonaPlexProvider(), preference=80)
    except Exception as exc:
        logger.warning("PersonaPlex provider registration failed: %s", exc)


_register_default_providers()


__all__ = [
    "SafetyClass",
    "VoiceProvider",
    "VoiceProviderCapability",
    "VoiceProviderRegistry",
    "VoiceTurnResult",
    "classify_intent_safety",
    "get_registry",
]
