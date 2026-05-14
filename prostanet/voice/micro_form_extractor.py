"""EPIC 21 Fase 1 — Micro-form voice extractor.

Extends `intent_extractor.py` to recognize EPIC 20 micro-form field targets
(66 fields across 6 moments) from voice transcript candidates.

Pipeline (called after STT):
  transcript_text → extract_micro_form_candidates(moment, transcript)
  → list[VoiceCandidate{field, value, confidence, evidence_excerpt}]

Each candidate self-gates per voice_required_confidence threshold from
`moment_capture_schemas.py`. Candidates above threshold auto-populate
(visual indicator); below threshold require manual review.

Voice-friendly Spanish/English bilingual patterns:
  - PSA: "PSA actual 4.2", "PSA 4 punto 2", "PSA pre-RP 6", "antígeno prostático 5"
  - Gleason: "Gleason 7 (3+4)", "Gleason siete tres más cuatro", "Gleason score 8"
  - T stage: "cT1c", "cT dos b", "T2a clínico"
  - Dates: "13 de mayo de 2026", "2026-05-13", "hace 3 meses"
  - Booleans: "sí recibió", "no recibió", "presente", "ausente"

Authorization scope: internal_shadow_observational_validation.
All candidates flagged as `status=draft` requiring human review BEFORE commit.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

logger = logging.getLogger(__name__)

# Import schemas
try:
    from prostanet.shared.moment_capture_schemas import (
        MOMENT_CAPTURE_SCHEMAS,
        FieldSpec,
        FormSchema,
    )
except ImportError:
    MOMENT_CAPTURE_SCHEMAS = {}
    FieldSpec = None  # type: ignore
    FormSchema = None  # type: ignore


@dataclass
class MicroFormCandidate:
    """Voice-extracted candidate field for a micro-form."""
    moment: str
    field_name: str
    field_label: str
    value: Any
    confidence: float  # 0.0-1.0
    evidence_excerpt: str
    auto_populate: bool  # True if confidence >= field's voice_required_confidence
    requires_review: bool  # True if confidence < threshold
    field_type: str
    status: str = "draft"  # draft → reviewed → committed


# ─────────────────── Bilingual regex patterns ───────────────────

# Numeric patterns (PSA, doses, counts)
_NUM_PATTERN = re.compile(
    r"(\d+(?:[.,]\d+)?(?:\s*punto\s*\d+)?)", re.IGNORECASE
)

# PSA: "PSA actual 4.2" or "PSA 4 punto 2"
_PSA_PATTERN = re.compile(
    r"\b(?:psa|antígeno|antigeno|ape)\b(?:\s+(?:actual|current|basal|baseline|nadir|pre[\s-]?(?:rt|rp|ry)|post[\s-]?(?:rt|rp))?)?\s*"
    r"(?:de|es|igual\s+a|valor)?\s*"
    r"(\d+(?:[.,]\d+)?(?:\s*punto\s*\d+)?)",
    re.IGNORECASE,
)

# Gleason: "Gleason 7 (3+4)" or "Gleason siete tres más cuatro"
_GLEASON_PATTERN = re.compile(
    r"\bgleason\b\s*(?:score|de)?\s*"
    r"(\d{1,2}|seis|siete|ocho|nueve|diez)"
    r"(?:\s*[(\[]?\s*(\d)\s*[++]\s*(\d)\s*[)\]]?)?",
    re.IGNORECASE,
)

# T-stage: "cT1c", "cT 2 b", "T2a clínico"
_T_STAGE_PATTERN = re.compile(
    r"\bc?[Tt]\s*(\d)(?:\s*([a-c]))?\b",
)

# ECOG: "ECOG 1", "ECOG performance 2"
_ECOG_PATTERN = re.compile(
    r"\becog\b(?:\s+(?:performance|score|de))?\s*(\d)",
    re.IGNORECASE,
)

# Boolean affirmative
_AFFIRMATIVE = re.compile(
    r"\b(s[íi]|yes|positivo|positive|presente|present|recibi[óo]|received|hubo|confirmado|"
    r"detectado|elevated|elevado)\b",
    re.IGNORECASE,
)

# Boolean negative
_NEGATIVE = re.compile(
    r"\b(no|negativo|negative|ausente|absent|sin|none|ninguno|no\s+recibi[óo]|"
    r"not\s+(?:received|present|detected))\b",
    re.IGNORECASE,
)


# ─────────────────── Number parser ───────────────────


def _parse_number_es(text: str) -> float | None:
    """Parse number from Spanish/English with 'punto' / 'point' / decimal comma support."""
    if not text:
        return None
    cleaned = text.strip().lower()
    # Replace "X punto Y" → "X.Y"
    cleaned = re.sub(r"(\d+)\s*punto\s*(\d+)", r"\1.\2", cleaned)
    cleaned = re.sub(r"(\d+)\s*point\s*(\d+)", r"\1.\2", cleaned)
    # Replace comma decimal with dot
    cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        # Try Spanish number words
        word_map = {
            "cero": 0, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4,
            "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
        }
        return word_map.get(cleaned)


def _parse_gleason(match) -> dict[str, Any] | None:
    """Parse Gleason match: returns dict with total + primary + secondary."""
    total_raw = match.group(1)
    primary_raw = match.group(2)
    secondary_raw = match.group(3)

    word_map = {"seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10}
    try:
        total = int(total_raw) if total_raw.isdigit() else word_map.get(total_raw.lower())
    except (ValueError, AttributeError):
        return None
    if total is None or not (6 <= total <= 10):
        return None

    primary = int(primary_raw) if primary_raw and primary_raw.isdigit() else None
    secondary = int(secondary_raw) if secondary_raw and secondary_raw.isdigit() else None

    result = {"total": total}
    if primary and secondary:
        result["primary"] = primary
        result["secondary"] = secondary
        result["formatted"] = f"{total}({primary}+{secondary})"
    else:
        result["formatted"] = str(total)
    return result


# ─────────────────── Field-specific extractors ───────────────────


def _extract_psa(transcript: str, field: "FieldSpec") -> tuple[Any, float, str] | None:
    """Extract PSA value with context awareness (actual vs pre-RP vs nadir).

    Field names guide which PSA context to look for:
      - current_psa, baseline_psa → "PSA actual", "PSA basal"
      - pre_rp_psa → "PSA pre-RP", "PSA antes de cirugía"
      - nadir_psa_value, nadir_psa_post_rt → "PSA nadir", "PSA del nadir"
      - pre_rt_psa → "PSA pre-RT"
    """
    field_name_lower = field.name.lower()
    context_keywords: list[str] = []
    if "pre_rp" in field_name_lower or "pre_rt" in field_name_lower:
        context_keywords = ["pre-rp", "pre rp", "pre-rt", "pre rt", "antes de"]
    elif "nadir" in field_name_lower:
        context_keywords = ["nadir"]
    elif "current" in field_name_lower or "baseline" in field_name_lower:
        context_keywords = ["actual", "current", "basal", "baseline"]

    # Try context-aware search first
    for keyword in context_keywords:
        # Allow connectors: "fue", "era", "de", "es", "igual a", "valor", or NONE (just whitespace)
        pattern = rf"(?:psa|antígeno|antigeno|ape)\s+{re.escape(keyword)}\s+(?:fue|era|de|es|igual\s+a|valor|del)?\s*(\d+(?:[.,]\d+)?(?:\s*punto\s*\d+)?)"
        m = re.search(pattern, transcript, re.IGNORECASE)
        if m:
            num = _parse_number_es(m.group(1))
            if num is not None:
                excerpt = transcript[max(0, m.start() - 30):min(len(transcript), m.end() + 30)]
                return num, 0.9, excerpt

    # Fallback: any PSA mention (lower confidence)
    m = _PSA_PATTERN.search(transcript)
    if m:
        num = _parse_number_es(m.group(1))
        if num is not None:
            excerpt = transcript[max(0, m.start() - 30):min(len(transcript), m.end() + 30)]
            confidence = 0.75 if context_keywords else 0.85
            return num, confidence, excerpt
    return None


def _extract_gleason(transcript: str, field: "FieldSpec") -> tuple[Any, float, str] | None:
    """Extract Gleason score with primary/secondary if available."""
    m = _GLEASON_PATTERN.search(transcript)
    if not m:
        return None
    parsed = _parse_gleason(m)
    if not parsed:
        return None
    excerpt = transcript[max(0, m.start() - 20):min(len(transcript), m.end() + 20)]
    # If field is gleason_at_rp or gleason_score, return formatted
    if field.type == "select":
        return parsed["formatted"], 0.88, excerpt
    return parsed["total"], 0.88, excerpt


def _extract_t_stage(transcript: str, field: "FieldSpec") -> tuple[Any, float, str] | None:
    """Extract clinical T-stage."""
    m = _T_STAGE_PATTERN.search(transcript)
    if not m:
        return None
    t_num = m.group(1)
    t_sub = (m.group(2) or "").lower()
    formatted = f"cT{t_num}{t_sub}" if t_sub else f"cT{t_num}"
    excerpt = transcript[max(0, m.start() - 20):min(len(transcript), m.end() + 20)]
    return formatted, 0.85, excerpt


def _extract_ecog(transcript: str, field: "FieldSpec") -> tuple[Any, float, str] | None:
    """Extract ECOG performance status."""
    m = _ECOG_PATTERN.search(transcript)
    if not m:
        return None
    ecog = m.group(1)
    excerpt = transcript[max(0, m.start() - 20):min(len(transcript), m.end() + 20)]
    return ecog, 0.90, excerpt


def _extract_boolean(transcript: str, field: "FieldSpec") -> tuple[Any, float, str] | None:
    """Extract boolean value based on field name keywords."""
    field_keywords = field.label.lower().split() + field.name.lower().split("_")
    # Search transcript for any keyword from field
    for keyword in field_keywords:
        if len(keyword) < 4:
            continue
        if keyword in transcript.lower():
            # Determine yes/no nearby
            idx = transcript.lower().find(keyword)
            window = transcript[max(0, idx - 30):min(len(transcript), idx + len(keyword) + 50)]
            if _AFFIRMATIVE.search(window):
                return True, 0.80, window
            if _NEGATIVE.search(window):
                return False, 0.80, window
    return None


def _extract_select(transcript: str, field: "FieldSpec") -> tuple[Any, float, str] | None:
    """Extract a select-type value by matching against options."""
    if not field.options:
        return None
    transcript_lower = transcript.lower()
    for option in field.options:
        opt_lower = option.lower().replace("_", " ")
        if opt_lower in transcript_lower or option.lower() in transcript_lower:
            idx = transcript_lower.find(opt_lower) if opt_lower in transcript_lower else transcript_lower.find(option.lower())
            excerpt = transcript[max(0, idx - 20):min(len(transcript), idx + len(option) + 20)]
            return option, 0.85, excerpt
    return None


def _extract_number(transcript: str, field: "FieldSpec") -> tuple[Any, float, str] | None:
    """Generic numeric extraction by field label keyword."""
    # Find a number near the field label keyword
    label_keywords = [kw for kw in field.label.lower().split() if len(kw) >= 4]
    if not label_keywords:
        return None
    for keyword in label_keywords:
        # Pattern: "keyword X.Y" or "keyword es X"
        pattern = rf"{re.escape(keyword)}\s*(?:de|es|igual\s+a|valor)?\s*(\d+(?:[.,]\d+)?(?:\s*punto\s*\d+)?)"
        m = re.search(pattern, transcript, re.IGNORECASE)
        if m:
            num = _parse_number_es(m.group(1))
            if num is not None:
                excerpt = transcript[max(0, m.start() - 20):min(len(transcript), m.end() + 20)]
                return num, 0.80, excerpt
    return None


# ─────────────────── Main entry point ───────────────────


def extract_micro_form_candidates(
    moment: str,
    transcript: str,
) -> list[MicroFormCandidate]:
    """Extract candidates for a specific micro-form moment.

    Args:
        moment: micro-form name (e.g., "bcr_detection", "crpc_transition")
        transcript: voice transcript text

    Returns:
        List of MicroFormCandidate per field, with confidence + auto_populate flag.
    """
    if not transcript or not isinstance(transcript, str):
        return []

    form = MOMENT_CAPTURE_SCHEMAS.get(moment)
    if form is None:
        logger.warning("Unknown moment: %s", moment)
        return []

    candidates: list[MicroFormCandidate] = []
    for fld in form.fields:
        extracted = _extract_field(transcript, fld)
        if extracted is None:
            continue
        value, confidence, excerpt = extracted
        auto_populate = confidence >= fld.voice_required_confidence
        candidates.append(MicroFormCandidate(
            moment=moment,
            field_name=fld.name,
            field_label=fld.label,
            value=value,
            confidence=round(confidence, 2),
            evidence_excerpt=excerpt.strip(),
            auto_populate=auto_populate,
            requires_review=not auto_populate,
            field_type=fld.type,
        ))

    return candidates


def _extract_field(transcript: str, fld: "FieldSpec") -> tuple[Any, float, str] | None:
    """Dispatch to field-specific extractor based on field name and type."""
    name = fld.name.lower()
    # Field-specific extractors (most specific first)
    if "psa" in name and ("current" in name or "baseline" in name or "nadir" in name or "pre_rp" in name or "pre_rt" in name):
        return _extract_psa(transcript, fld)
    if "gleason" in name:
        return _extract_gleason(transcript, fld)
    if "t_stage" in name:
        return _extract_t_stage(transcript, fld)
    if "ecog" in name:
        return _extract_ecog(transcript, fld)
    # Type-based dispatch
    if fld.type == "boolean":
        return _extract_boolean(transcript, fld)
    if fld.type == "select":
        return _extract_select(transcript, fld)
    if fld.type == "number":
        return _extract_number(transcript, fld)
    return None


def candidates_to_dict(candidates: list[MicroFormCandidate]) -> dict[str, Any]:
    """Serialize candidates list to dict for JSON response."""
    return {
        "available": True,
        "moment": candidates[0].moment if candidates else "",
        "total_candidates": len(candidates),
        "auto_populate_count": sum(1 for c in candidates if c.auto_populate),
        "requires_review_count": sum(1 for c in candidates if c.requires_review),
        "candidates": [
            {
                "field_name": c.field_name,
                "field_label": c.field_label,
                "field_type": c.field_type,
                "value": c.value,
                "confidence": c.confidence,
                "evidence_excerpt": c.evidence_excerpt,
                "auto_populate": c.auto_populate,
                "requires_review": c.requires_review,
                "status": c.status,
            }
            for c in candidates
        ],
    }


__all__ = [
    "MicroFormCandidate",
    "extract_micro_form_candidates",
    "candidates_to_dict",
]
