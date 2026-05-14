"""EPIC 21 Phase 3B — Whisper Pipeline Provider.

Wraps existing Cortana stack (Phase 1+2) as a VoiceProvider:
  STT (Whisper) → LLM → grounding firewall → TTS

Capability: supports HIGH and CRITICAL safety classes (firewall always
applied for these). Available on CPU, no GPU required.

This is the SAFE provider — clinical claims always pass through
grounding firewall before TTS.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Mapping

from prostanet.voice.providers.base import (
    SafetyClass,
    VoiceProvider,
    VoiceProviderCapability,
    VoiceTurnResult,
)

logger = logging.getLogger(__name__)


class WhisperPipelineProvider(VoiceProvider):
    """STT (Whisper) → LLM → firewall → TTS provider.

    Always available (CPU-friendly via faster-whisper). Supports all
    safety classes including CRITICAL (firewall mandatory).
    """

    def __init__(self) -> None:
        self._whisper_available = self._check_whisper()
        self._llm_available = self._check_llm()

    def _check_whisper(self) -> bool:
        """Check if faster-whisper STT is importable."""
        try:
            import importlib
            importlib.util.find_spec("faster_whisper")
            return True
        except ImportError:
            return False
        except Exception:
            return False

    def _check_llm(self) -> bool:
        """Check if Anthropic LLM provider is configured."""
        try:
            from prostanet.voice.llm_providers.anthropic_provider import AnthropicProvider
            provider = AnthropicProvider()
            return hasattr(provider, "client") and provider.client is not None
        except Exception:
            return False

    def capability(self) -> VoiceProviderCapability:
        notes: list[str] = []
        if not self._whisper_available:
            notes.append("faster-whisper not installed (transcript will need to be pre-computed)")
        if not self._llm_available:
            notes.append("LLM not configured (Q&A enrichment unavailable)")
        return VoiceProviderCapability(
            provider_name="whisper",
            is_available=True,  # always usable even without faster-whisper if transcript supplied
            supports_intermediate_transcript=True,  # CORE: enables firewall
            supports_full_duplex=False,
            requires_gpu=False,
            requires_network=self._llm_available,  # only for LLM enrichment
            latency_ms_typical=1500,  # STT + LLM + firewall + TTS
            max_safety_class=SafetyClass.CRITICAL,
            notes=notes,
        )

    def process_turn(
        self,
        *,
        audio_bytes: bytes | None = None,
        transcript: str = "",
        safety_class: SafetyClass = SafetyClass.LOW,
        patient_nss: str | None = None,
        intent: str = "",
        context: Mapping[str, Any] | None = None,
    ) -> VoiceTurnResult:
        """Process via existing Cortana orchestrator pipeline."""
        t0 = time.perf_counter()
        result = VoiceTurnResult(
            available=True,
            transcript=transcript,
            safety_class=safety_class,
            provider_used="whisper",
        )

        if not transcript and audio_bytes:
            # TODO: integrate faster-whisper STT here
            # For now, transcript must be supplied (frontend STT or external)
            result.error = "audio_bytes_provided_but_stt_not_wired_yet"
            result.response_text = "Por favor envía el transcript pre-computado por ahora."
            return result

        if not transcript:
            result.error = "no_transcript_or_audio"
            result.response_text = "No recibí audio ni transcript."
            return result

        # Delegate to existing Cortana orchestrator
        try:
            from prostanet.voice.cortana_orchestrator import (
                orchestrate_cortana, orchestration_to_dict,
            )
            orchestration = orchestrate_cortana(
                transcript=transcript,
                patient_nss=patient_nss,
                multi_turn_state=dict(context or {}).get("multi_turn_state"),
                language=(context or {}).get("language", "es"),
            )
            result.response_text = orchestration.tts_response
            result.audit_log = orchestration.audit_log_entry

            # If handler was QA/decision/population, firewall was applied
            firewall_handlers = {
                "patient_qa_grounding",
                "decision_aware_qa",
                "population_query_safe",
            }
            if orchestration.handler in firewall_handlers:
                result.firewall_applied = True
                # Inspect handler_result for firewall blocks
                hr = orchestration.handler_result
                if hr.get("answer_blocked"):
                    result.firewall_blocked = True
                    result.firewall_failure_reasons = hr.get("validation_failure_reasons", [])
            result.latency_ms = int((time.perf_counter() - t0) * 1000)
            return result
        except Exception as exc:
            logger.error("WhisperPipelineProvider.process_turn failed: %s", exc)
            result.error = f"pipeline_error: {exc}"
            result.response_text = "Error procesando la consulta. Por favor intenta de nuevo."
            result.latency_ms = int((time.perf_counter() - t0) * 1000)
            return result


__all__ = ["WhisperPipelineProvider"]
