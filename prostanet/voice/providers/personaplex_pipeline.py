"""EPIC 21 Phase 3B — PersonaPlex Pipeline Provider.

Wraps NVIDIA PersonaPlex (Moshi-based) full-duplex speech-to-speech.

Architecture:
  - PersonaPlex runs as SIDECAR (Docker container with GPU access)
  - This provider TALKS TO the sidecar via HTTP/WebSocket
  - Local Mac CPU dev: sidecar typically unavailable → graceful is_available=False
  - GPU cloud deployment: sidecar wired → full-duplex enabled

Safety constraint:
  PersonaPlex is speech-to-speech WITHOUT exposed transcript. This means
  grounding firewall CANNOT validate factual claims. Therefore:
    max_safety_class = MEDIUM (NEVER HIGH or CRITICAL)

  Routing in VoiceProviderRegistry enforces this.

Sidecar contract:
  POST {SIDECAR_URL}/health → {available, gpu_info, model_loaded}
  POST {SIDECAR_URL}/turn  → {response_text, response_audio_b64, latency_ms}

  Headers: Authorization: Bearer <PERSONAPLEX_API_KEY> (internal sidecar token)

Install (GPU host):
  See Dockerfile.personaplex-sidecar + docs/personaplex_install.md
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from typing import Any, Mapping
from urllib import error as urllib_error
from urllib import request as urllib_request

from prostanet.voice.providers.base import (
    SafetyClass,
    VoiceProvider,
    VoiceProviderCapability,
    VoiceTurnResult,
)

logger = logging.getLogger(__name__)

# Sidecar config
SIDECAR_URL = os.environ.get("PERSONAPLEX_SIDECAR_URL", "http://127.0.0.1:8090")
SIDECAR_AUTH_TOKEN = os.environ.get("PERSONAPLEX_AUTH_TOKEN", "")
SIDECAR_TIMEOUT_SEC = int(os.environ.get("PERSONAPLEX_TIMEOUT_SEC", "30"))


class PersonaPlexProvider(VoiceProvider):
    """Full-duplex speech-to-speech via PersonaPlex sidecar.

    LIMITED TO LOW/MEDIUM safety classes (no transcript exposed → no firewall).
    """

    def __init__(self, sidecar_url: str | None = None) -> None:
        self.sidecar_url = sidecar_url or SIDECAR_URL
        self._last_health_check = 0.0
        self._cached_is_available = False
        self._cached_gpu_info: dict[str, Any] = {}

    def _check_sidecar_health(self, force: bool = False) -> tuple[bool, dict[str, Any]]:
        """Probe sidecar health endpoint. Cached 60s."""
        now = time.time()
        if not force and (now - self._last_health_check) < 60.0:
            return self._cached_is_available, self._cached_gpu_info

        try:
            req = urllib_request.Request(
                f"{self.sidecar_url}/health",
                headers={"User-Agent": "ProstaMed-Cortana/1.0"},
            )
            if SIDECAR_AUTH_TOKEN:
                req.add_header("Authorization", f"Bearer {SIDECAR_AUTH_TOKEN}")
            with urllib_request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                self._cached_is_available = bool(data.get("available"))
                self._cached_gpu_info = dict(data.get("gpu_info") or {})
        except (urllib_error.URLError, urllib_error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            logger.debug("PersonaPlex sidecar health check failed: %s", exc)
            self._cached_is_available = False
            self._cached_gpu_info = {}

        self._last_health_check = now
        return self._cached_is_available, self._cached_gpu_info

    def capability(self) -> VoiceProviderCapability:
        is_available, gpu_info = self._check_sidecar_health()
        notes: list[str] = []
        if not is_available:
            notes.append(
                f"PersonaPlex sidecar not reachable at {self.sidecar_url}. "
                "Install + start sidecar per docs/personaplex_install.md"
            )
        else:
            notes.append(f"GPU: {gpu_info.get('name', 'unknown')}, VRAM: {gpu_info.get('vram_gb', '?')}GB")
        return VoiceProviderCapability(
            provider_name="personaplex",
            is_available=is_available,
            # CRITICAL: PersonaPlex is speech-to-speech WITHOUT exposed transcript.
            # This is the architectural reason it CANNOT handle HIGH/CRITICAL.
            supports_intermediate_transcript=False,
            supports_full_duplex=True,
            requires_gpu=True,
            requires_network=True,  # to sidecar
            latency_ms_typical=300 if is_available else 0,
            max_safety_class=SafetyClass.MEDIUM,
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
        """Send turn to PersonaPlex sidecar, return audio + best-effort text.

        Refuses HIGH/CRITICAL by design (registry should never route here).
        """
        t0 = time.perf_counter()
        result = VoiceTurnResult(
            available=True,
            transcript=transcript,
            safety_class=safety_class,
            provider_used="personaplex",
        )

        # SAFETY ENFORCEMENT: refuse high-safety contexts
        if safety_class in (SafetyClass.HIGH, SafetyClass.CRITICAL):
            result.available = False
            result.error = (
                "personaplex_refused_high_safety: PersonaPlex cannot serve HIGH/CRITICAL "
                "contexts (no transcript = no firewall). Use Whisper pipeline."
            )
            result.firewall_blocked = True
            result.firewall_failure_reasons = ["unsupported_safety_class_for_provider"]
            result.response_text = (
                "Esta consulta requiere validación clínica completa. Cambiando a Cortana standard."
            )
            return result

        # Check sidecar availability
        is_available, _ = self._check_sidecar_health()
        if not is_available:
            result.available = False
            result.error = "personaplex_sidecar_unavailable"
            result.response_text = "Servicio de voz realtime no disponible. Usando Cortana standard."
            result.latency_ms = int((time.perf_counter() - t0) * 1000)
            return result

        # Call sidecar
        payload: dict[str, Any] = {
            "intent": intent,
            "safety_class": safety_class.value,
            "patient_nss": patient_nss,  # context only; sidecar should NOT use for factual claims
            "persona": "cortana_clinical_es",  # system-defined persona
            "language": (context or {}).get("language", "es"),
        }
        if transcript:
            payload["transcript"] = transcript
        if audio_bytes:
            payload["audio_b64"] = base64.b64encode(audio_bytes).decode("ascii")

        try:
            body = json.dumps(payload).encode("utf-8")
            req = urllib_request.Request(
                f"{self.sidecar_url}/turn",
                data=body,
                headers={
                    "User-Agent": "ProstaMed-Cortana/1.0",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            if SIDECAR_AUTH_TOKEN:
                req.add_header("Authorization", f"Bearer {SIDECAR_AUTH_TOKEN}")
            with urllib_request.urlopen(req, timeout=SIDECAR_TIMEOUT_SEC) as resp:
                response_data = json.loads(resp.read().decode("utf-8"))
            result.response_text = str(response_data.get("response_text") or "")
            audio_b64 = response_data.get("response_audio_b64")
            if audio_b64:
                try:
                    result.response_audio_bytes = base64.b64decode(audio_b64)
                except Exception:
                    pass
            result.audit_log = {
                "personaplex_session_id": response_data.get("session_id"),
                "personaplex_persona": "cortana_clinical_es",
                "transcript_supplied": bool(transcript),
                "audio_supplied": bool(audio_bytes),
                "response_text": result.response_text,
                "safety_class": safety_class.value,
                "provider_latency_ms": response_data.get("latency_ms"),
            }
        except (urllib_error.URLError, urllib_error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            logger.error("PersonaPlex sidecar call failed: %s", exc)
            result.available = False
            result.error = f"personaplex_sidecar_error: {exc}"
            result.response_text = "Error en servicio realtime. Cambiando a Cortana standard."

        result.latency_ms = int((time.perf_counter() - t0) * 1000)
        return result


__all__ = ["PersonaPlexProvider", "SIDECAR_URL", "SIDECAR_TIMEOUT_SEC"]
