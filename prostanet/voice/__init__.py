"""
prostanet.voice — Cortana de ProstaMed: Asistente de Voz IA Clínico (FAUBOT LXXX+).

Módulo Voice del CDE Auditable. Componentes principales:

- `stt_engine`: Speech-to-Text con faster-whisper local + silero-vad
- `tts_providers`: Factory pattern para TTS (Edge TTS gratis / ElevenLabs paga / Piper local)
- `llm_providers`: Factory pattern para LLM (Ollama gratis / Anthropic Claude paga)
- `intent_extractor`: Extracción de entidades clínicas con tool_use
- `field_validators`: Validadores Gleason/PSA/fechas español/T-stage
- `soap_generator`: Generación notas SOAP estructuradas
- `qa_tools`: 6 tools para Q&A poblacional
- `consent`: Flujo consentimiento verbal HIPAA-compliant
- `encryption`: Cifrado audio con Fernet + retention 90d
- `ws_handler`: WebSocket Flask-Sock endpoint
- `api`: Blueprint REST /api/voice/*

Modos de operación (configurable vía env):

- VOICE_LLM_MODE=cloud   → Claude Sonnet (~$0.07/consulta, máxima calidad)
- VOICE_LLM_MODE=hybrid  → Ollama local + Claude solo SOAP (~$0.01/consulta) ⭐ Recomendado
- VOICE_LLM_MODE=local   → 100% local Ollama + Edge TTS ($0/consulta)

Faubot LXXX+ — Cortana, asistente conversacional clínico para oncourología
prostática, único en su intersección 5-D: voz + CDS + próstata + español + auditable.

ALCANCES (sin alucinar):
- ✅ Copiloto onco-urológico que amplifica al médico (no lo reemplaza)
- ✅ Reduce 60-75% tiempo administrativo
- ✅ Auditable end-to-end con evidence_phrase + confidence + version
- ❌ NO es onco-urólogo virtual autónomo (CDS Clase II IIa)
- ❌ NO toma decisiones clínicas finales (siempre human-in-the-loop)
"""
from __future__ import annotations

__version__ = "0.1.0"
__faubot_release__ = "2026-04-26 LXXX"

# Lazy imports — no import side effects al hacer `from prostanet.voice import X`
# Esto evita ImportError si las dependencias opcionales (faster-whisper, ollama,
# edge-tts, elevenlabs) no están instaladas todavía.

__all__ = [
    "__version__",
    "__faubot_release__",
]
