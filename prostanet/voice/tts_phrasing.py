"""EPIC 21 — TTS Phrasing Helper (`/writing-voice` skill applied).

Produces clinical safety-aware TTS responses for Cortana voice agent.
Enforces the "writing-voice" rules:

  ✅ ALWAYS:
    - Cite date when fact has temporal context: "Según el registro del [fecha]..."
    - Acknowledge gaps explicitly: "No tengo ese dato en el registro"
    - Use concrete numbers: "PSA 4.2 ng/mL" (not "aproximadamente 4")
    - Sub-2-sentence responses (voice attention is limited)

  ❌ NEVER:
    - "Yo creo que..." (suggests fabrication)
    - "Probablemente..." (uncertainty without grounding)
    - "Aproximadamente X" (unless record itself is approximate)
    - Run-on sentences (>2 clauses per response)

All TTS responses are validated by `grounding_firewall` BEFORE this module is
called. This module only formats validated content.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# ─────────────────── Safety prefix templates ───────────────────

SAFETY_PREFIX_TEMPLATES = {
    "es": {
        "with_date": "Según el registro del {date}: ",
        "no_date": "Según el registro: ",
        "uncertain": "Requiere revisión del especialista: ",
        "missing": "No tengo ese dato en el registro. ",
        "blocked": "Datos en desacuerdo, requiere revisión manual. ",
    },
    "en": {
        "with_date": "Per the record dated {date}: ",
        "no_date": "Per the record: ",
        "uncertain": "Requires specialist review: ",
        "missing": "I don't have that information in the record. ",
        "blocked": "Data mismatch detected, manual review required. ",
    },
}


# Forbidden phrases (signal fabrication risk)
FORBIDDEN_PHRASES = [
    re.compile(r"\b(yo\s+creo|i\s+think|i\s+believe)\b", re.IGNORECASE),
    re.compile(r"\b(probablemente|probably|likely)\b", re.IGNORECASE),
    re.compile(r"\baproximadamente\b", re.IGNORECASE),
    re.compile(r"\bapproximately\b", re.IGNORECASE),
    re.compile(r"\b(quizás|quizas|maybe|perhaps)\b", re.IGNORECASE),
    re.compile(r"\b(parece\s+que|seems\s+(like|to\s+be))\b", re.IGNORECASE),
]


# ─────────────────── Response builders ───────────────────


def build_tts_response(
    validated_answer: str,
    *,
    record_date: str | None = None,
    language: str = "es",
    answer_type: str = "factual",  # factual | uncertain | missing | blocked
) -> str:
    """Build a safety-prefixed TTS response from validated answer text.

    Args:
        validated_answer: text that passed grounding firewall
        record_date: ISO date of the fact (e.g., "2026-05-13")
        language: "es" or "en"
        answer_type: factual | uncertain | missing | blocked

    Returns:
        TTS-ready text with safety prefix, scrubbed of forbidden phrases.
    """
    if not validated_answer or not isinstance(validated_answer, str):
        return _missing_response(language)

    templates = SAFETY_PREFIX_TEMPLATES.get(language, SAFETY_PREFIX_TEMPLATES["es"])

    # Scrub forbidden phrases
    scrubbed = _scrub_forbidden(validated_answer)

    # If answer already has temporal context, skip prefix
    if "según el registro" in scrubbed.lower() or "per the record" in scrubbed.lower():
        return scrubbed

    # Build prefix based on type
    if answer_type == "missing":
        return _missing_response(language) + scrubbed
    if answer_type == "blocked":
        return templates["blocked"] + scrubbed
    if answer_type == "uncertain":
        return templates["uncertain"] + scrubbed

    # Factual with date
    if record_date:
        return templates["with_date"].format(date=record_date) + scrubbed
    return templates["no_date"] + scrubbed


def build_disambiguation_response(
    candidate_count: int,
    candidates_summary: list[str],
    language: str = "es",
) -> str:
    """Build TTS disambiguation prompt for multiple patient matches."""
    if not candidates_summary:
        return _missing_response(language)
    summary_text = ", ".join(candidates_summary[:3])
    if language == "es":
        return (
            f"Encontré {candidate_count} pacientes con nombre similar: "
            f"{summary_text}. ¿Cuál de ellos?"
        )
    return (
        f"Found {candidate_count} patients with similar names: "
        f"{summary_text}. Which one?"
    )


def build_confirmation_response(
    primary_match_name: str,
    primary_match_nss: str,
    language: str = "es",
) -> str:
    """Build TTS confirmation for single high-confidence patient match."""
    if language == "es":
        return f"Encontré a {primary_match_name} con NSS {primary_match_nss}. ¿Abro su perfil?"
    return f"Found {primary_match_name} with ID {primary_match_nss}. Open profile?"


def build_intake_confirmation(
    field_label: str,
    value: Any,
    unit: str = "",
    confidence: float = 0.0,
    language: str = "es",
) -> str:
    """Build TTS confirmation prompt for intake field auto-population.

    Used when confidence < voice_required_confidence threshold.
    """
    value_str = str(value)
    if unit:
        value_str = f"{value_str} {unit}"
    if language == "es":
        if confidence < 0.7:
            return f"Escuché {field_label}: {value_str}. ¿Es correcto? (Baja confianza, requiere confirmación)"
        return f"Confirmé {field_label}: {value_str}. ¿Aplico?"
    if confidence < 0.7:
        return f"I heard {field_label}: {value_str}. Correct? (Low confidence, please confirm)"
    return f"Set {field_label}: {value_str}. Apply?"


def build_clarification_prompt(
    ambiguous_value: str,
    candidates: list[str],
    field_label: str,
    language: str = "es",
) -> str:
    """Build TTS clarification prompt for ambiguous voice input.

    Example: "¿Dijo PSA 4 punto 2 o PSA 14 punto 2?"
    """
    if not candidates:
        return _missing_response(language)
    if language == "es":
        options_text = " o ".join(candidates)
        return f"¿Dijo {field_label} {options_text}?"
    options_text = " or ".join(candidates)
    return f"Did you say {field_label} {options_text}?"


# ─────────────────── Validation helpers ───────────────────


def _scrub_forbidden(text: str) -> str:
    """Remove forbidden phrases that suggest fabrication."""
    cleaned = text
    for pattern in FORBIDDEN_PHRASES:
        cleaned = pattern.sub("", cleaned)
    # Clean up double spaces
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned


def _missing_response(language: str) -> str:
    """Standard missing-data response."""
    return SAFETY_PREFIX_TEMPLATES.get(language, SAFETY_PREFIX_TEMPLATES["es"])["missing"]


def validate_tts_text(text: str, *, max_sentences: int = 2) -> dict[str, Any]:
    """Validate TTS text per `/writing-voice` rules.

    Returns dict with:
      - valid (bool)
      - issues (list[str])
      - sentence_count
      - forbidden_phrases_found
    """
    issues: list[str] = []
    if not text or not isinstance(text, str):
        return {"valid": False, "issues": ["empty"], "sentence_count": 0, "forbidden_phrases_found": []}

    # Sentence count (rough)
    sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    if len(sentences) > max_sentences:
        issues.append(f"too_many_sentences: {len(sentences)} > {max_sentences}")

    # Forbidden phrases
    forbidden_found: list[str] = []
    for pattern in FORBIDDEN_PHRASES:
        m = pattern.search(text)
        if m:
            forbidden_found.append(m.group(0))

    if forbidden_found:
        issues.append(f"forbidden_phrases: {forbidden_found}")

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "sentence_count": len(sentences),
        "forbidden_phrases_found": forbidden_found,
    }


__all__ = [
    "build_tts_response",
    "build_disambiguation_response",
    "build_confirmation_response",
    "build_intake_confirmation",
    "build_clarification_prompt",
    "validate_tts_text",
    "SAFETY_PREFIX_TEMPLATES",
]
