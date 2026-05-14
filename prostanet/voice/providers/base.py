"""EPIC 21 Phase 3A — Voice Provider abstraction + Safety Classes.

Defines the contract for voice providers (Whisper-based pipeline,
PersonaPlex full-duplex, or future alternatives) and the safety-aware
routing logic that determines WHICH provider can handle WHICH intent.

Architecture rationale:
  PersonaPlex is speech-to-speech direct (no transcript intermediate) →
  cannot pass through grounding firewall → unsafe for clinical claims.

  Whisper pipeline produces transcript → LLM → firewall validation →
  TTS → safe for clinical claims.

Solution: ROUTING POR SAFETY_CLASS:
  - low/medium → either provider acceptable
  - high/critical → Whisper pipeline MANDATORY (firewall required)

This module is provider-agnostic infrastructure. Concrete providers in:
  - whisper_pipeline.py  (existing Cortana stack)
  - personaplex_pipeline.py (NEW — NVIDIA full-duplex, GPU)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

logger = logging.getLogger(__name__)


# ─────────────────── Safety classification ───────────────────


class SafetyClass(str, Enum):
    """Safety level for a voice interaction context.

    Determines whether grounding firewall is REQUIRED before TTS.

    Definitions:
      LOW       — Casual / orientational. No clinical claims.
                  Examples: greetings, "¿cómo te uso?", small talk.
      MEDIUM    — Operational. Some clinical context but no factual claims
                  about specific patient. Clinician validates result manually.
                  Examples: intake field auto-population (clinician confirms),
                  patient name lookup disambiguation.
      HIGH      — Factual claims about specific patient. Hallucination
                  could lead to clinical decision based on wrong data.
                  Examples: "¿cuál es el PSA actual?", "¿qué tratamientos
                  ha recibido?", any factual patient_record retrieval.
      CRITICAL  — Therapeutic recommendation OR cohort/population claims.
                  Hallucination affects clinical decision OR audit metrics.
                  Examples: "¿cuál es la mejor opción?", "¿cuántos mCRPC?",
                  audit queries.

    Routing rule:
      LOW/MEDIUM → PersonaPlex acceptable (UX preferred if available)
      HIGH/CRITICAL → Whisper pipeline ONLY (firewall MANDATORY)
    """
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


def classify_intent_safety(intent: str) -> SafetyClass:
    """Map Cortana orchestrator intent → SafetyClass.

    Conservative mapping: when in doubt, escalate to HIGH.
    """
    intent_lower = (intent or "").lower()
    mapping = {
        "small_talk": SafetyClass.LOW,
        "unknown": SafetyClass.LOW,  # fallback help message, no clinical content
        "intake": SafetyClass.MEDIUM,  # clinician validates each field before commit
        "patient_lookup": SafetyClass.MEDIUM,  # name disambiguation, no PHI claims
        "patient_qa": SafetyClass.HIGH,  # factual claims about patient
        "patient_qa_missing_context": SafetyClass.LOW,  # asks user to open patient
        "decision_recommendation": SafetyClass.CRITICAL,  # therapeutic claims
        "decision_recommendation_missing_context": SafetyClass.LOW,
        "population_qa": SafetyClass.CRITICAL,  # cohort claims affect audit
    }
    return mapping.get(intent_lower, SafetyClass.HIGH)  # default escalate


# ─────────────────── Provider base classes ───────────────────


@dataclass
class VoiceProviderCapability:
    """Reports what a provider can/cannot do."""
    provider_name: str
    is_available: bool
    supports_intermediate_transcript: bool  # required for firewall
    supports_full_duplex: bool  # simultaneous listen+speak
    requires_gpu: bool
    requires_network: bool
    latency_ms_typical: int
    max_safety_class: SafetyClass  # highest safety this provider can serve
    notes: list[str] = field(default_factory=list)


@dataclass
class VoiceTurnResult:
    """Result of a single voice interaction turn (request/response)."""
    available: bool
    transcript: str = ""  # what user said (may be empty for full-duplex)
    response_text: str = ""  # what to speak (validated text)
    response_audio_bytes: bytes | None = None  # optional pre-rendered TTS
    safety_class: SafetyClass = SafetyClass.LOW
    provider_used: str = ""
    firewall_applied: bool = False
    firewall_blocked: bool = False
    firewall_failure_reasons: list[str] = field(default_factory=list)
    audit_log: dict[str, Any] = field(default_factory=dict)
    latency_ms: int = 0
    error: str = ""


class VoiceProvider(ABC):
    """Abstract base for voice providers.

    Concrete subclasses:
      - WhisperPipelineProvider (STT + LLM + firewall + TTS, supports HIGH/CRITICAL)
      - PersonaPlexProvider (full-duplex speech-to-speech, LOW/MEDIUM only)
    """

    @abstractmethod
    def capability(self) -> VoiceProviderCapability:
        """Report provider capabilities + availability."""
        ...

    @abstractmethod
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
        """Process one voice interaction turn.

        Args:
            audio_bytes: raw audio (optional, depends on provider)
            transcript: pre-computed transcript (if STT done separately)
            safety_class: routing decision (must match this provider's max_safety_class)
            patient_nss: optional patient context
            intent: classified intent (informational, may affect provider behavior)
            context: additional context (multi-turn state, etc.)

        Returns:
            VoiceTurnResult with validated response or graceful error.
        """
        ...

    def can_handle_safety_class(self, safety_class: SafetyClass) -> bool:
        """Check if this provider can serve the given safety class."""
        cap = self.capability()
        order = {SafetyClass.LOW: 0, SafetyClass.MEDIUM: 1, SafetyClass.HIGH: 2, SafetyClass.CRITICAL: 3}
        return order.get(safety_class, 99) <= order.get(cap.max_safety_class, 0)


# ─────────────────── Provider registry ───────────────────


class VoiceProviderRegistry:
    """Singleton registry of available providers.

    Routes requests to the best provider that satisfies safety_class +
    is currently available.
    """

    _instance: "VoiceProviderRegistry | None" = None

    def __new__(cls) -> "VoiceProviderRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._providers = {}
            cls._instance._preference_order = []
        return cls._instance

    def register(self, name: str, provider: VoiceProvider, preference: int = 50) -> None:
        """Register a provider with a preference score (higher = preferred for UX-better routes)."""
        self._providers[name] = provider
        # Maintain sorted preference order (descending)
        self._preference_order = sorted(
            [(p, n) for n, p in [(n, preference if n == name else self._provider_pref(n)) for n in self._providers]],
            reverse=True,
        )

    def _provider_pref(self, name: str) -> int:
        # Defaults: PersonaPlex=80 (preferred when safe), Whisper=70 (reliable, always safe)
        defaults = {"personaplex": 80, "whisper": 70}
        return defaults.get(name, 50)

    def get(self, name: str) -> VoiceProvider | None:
        return self._providers.get(name)

    def list_available(self) -> list[str]:
        """Return names of providers that report is_available=True."""
        return [name for name, p in self._providers.items() if p.capability().is_available]

    def select_provider(
        self,
        safety_class: SafetyClass,
        preferred: str | None = None,
    ) -> VoiceProvider | None:
        """Select best provider for the given safety class.

        Strategy:
          1. If `preferred` named provider available AND can handle safety_class → use it
          2. For LOW/MEDIUM: prefer PersonaPlex (UX better), fallback Whisper
          3. For HIGH/CRITICAL: ONLY Whisper (firewall required)
        """
        # CRITICAL gate: high safety classes REQUIRE intermediate transcript
        if safety_class in (SafetyClass.HIGH, SafetyClass.CRITICAL):
            whisper = self._providers.get("whisper")
            if whisper and whisper.capability().is_available:
                cap = whisper.capability()
                if cap.supports_intermediate_transcript:
                    return whisper
            return None  # No safe provider available

        # Preferred name override
        if preferred and preferred in self._providers:
            p = self._providers[preferred]
            if p.capability().is_available and p.can_handle_safety_class(safety_class):
                return p

        # LOW/MEDIUM: try in preference order
        for name in ["personaplex", "whisper"]:
            p = self._providers.get(name)
            if p and p.capability().is_available and p.can_handle_safety_class(safety_class):
                return p
        return None

    def capabilities_report(self) -> dict[str, Any]:
        """Report capabilities of all registered providers."""
        report = {
            "providers_registered": list(self._providers.keys()),
            "providers_available": self.list_available(),
            "safety_routing_rules": {
                "low": "PersonaPlex preferred, Whisper fallback",
                "medium": "PersonaPlex preferred, Whisper fallback",
                "high": "Whisper ONLY (firewall required)",
                "critical": "Whisper ONLY (firewall + copilots required)",
            },
            "providers_detail": {},
        }
        for name, p in self._providers.items():
            try:
                cap = p.capability()
                report["providers_detail"][name] = {
                    "is_available": cap.is_available,
                    "supports_intermediate_transcript": cap.supports_intermediate_transcript,
                    "supports_full_duplex": cap.supports_full_duplex,
                    "requires_gpu": cap.requires_gpu,
                    "max_safety_class": cap.max_safety_class.value,
                    "latency_ms_typical": cap.latency_ms_typical,
                    "notes": cap.notes,
                }
            except Exception as exc:
                report["providers_detail"][name] = {"is_available": False, "error": str(exc)}
        return report


def get_registry() -> VoiceProviderRegistry:
    """Singleton accessor."""
    return VoiceProviderRegistry()


__all__ = [
    "SafetyClass",
    "VoiceProviderCapability",
    "VoiceTurnResult",
    "VoiceProvider",
    "VoiceProviderRegistry",
    "classify_intent_safety",
    "get_registry",
]
