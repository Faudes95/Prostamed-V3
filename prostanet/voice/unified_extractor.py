"""EPIC 21 — Unified Voice Extractor (`/voice-update` skill applied).

Combines legacy `intent_extractor.extract_voice_candidates` (general clinical
fields) with new EPIC 20 `micro_form_extractor.extract_micro_form_candidates`
(moment-specific fields) into a single entry point.

Callers no longer need to choose between extractors. The unified pipeline:
  1. Runs both extractors on the same transcript
  2. Deduplicates by (field_name, value) — preserves highest confidence
  3. Returns combined `list[VoiceCandidate-like dict]`

Voice-update integration principle: NO modification of existing
`intent_extractor.py` — preserves backward compat for non-EPIC-20 callers.
EPIC 20 callers opt-in via `moment` parameter.

Usage:
    from prostanet.voice.unified_extractor import extract_all_candidates
    candidates = extract_all_candidates(
        transcript="PSA actual 4.2 ECOG 1 ...",
        moment="bcr_detection",  # optional, enables EPIC 20 micro-form targets
    )
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def extract_all_candidates(
    transcript: str,
    *,
    moment: str | None = None,
    vocabulary: Any | None = None,
) -> list[dict[str, Any]]:
    """Unified extraction combining legacy + EPIC 20 micro-form extractors.

    Args:
        transcript: voice transcript text
        moment: optional EPIC 20 micro-form moment (e.g., "bcr_detection",
            "crpc_transition"). If provided, micro-form targets are extracted.
            If None, only legacy extractor runs.
        vocabulary: optional ClinicalVocabulary for legacy extractor

    Returns:
        Unified list of candidate dicts with keys:
          - source: "legacy" | "micro_form"
          - field_name, value, confidence, evidence_excerpt
          - moment (only if source=micro_form)
          - auto_populate, requires_review (only if source=micro_form)
    """
    if not transcript or not isinstance(transcript, str):
        return []

    combined: list[dict[str, Any]] = []

    # 1. Legacy extractor (general clinical fields)
    try:
        from prostanet.voice.intent_extractor import extract_voice_candidates
        legacy = extract_voice_candidates(transcript, vocabulary=vocabulary)
        for item in legacy or []:
            if isinstance(item, dict):
                item_copy = dict(item)
                item_copy["source"] = "legacy"
                combined.append(item_copy)
    except Exception as exc:
        logger.debug("Legacy extractor failed: %s", exc)

    # 2. EPIC 20 micro-form extractor (moment-specific)
    if moment:
        try:
            from prostanet.voice.micro_form_extractor import extract_micro_form_candidates
            mf_candidates = extract_micro_form_candidates(moment, transcript)
            for c in mf_candidates:
                combined.append({
                    "source": "micro_form",
                    "moment": c.moment,
                    "field_name": c.field_name,
                    "field_label": c.field_label,
                    "field_type": c.field_type,
                    "value": c.value,
                    "confidence": c.confidence,
                    "evidence_excerpt": c.evidence_excerpt,
                    "auto_populate": c.auto_populate,
                    "requires_review": c.requires_review,
                    "status": c.status,
                })
        except Exception as exc:
            logger.debug("Micro-form extractor failed: %s", exc)

    # 3. Deduplicate by (field_name, value) — keep highest confidence
    return _dedupe_candidates(combined)


def _dedupe_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate candidates by (field_name, normalized_value).

    Strategy: micro_form source wins over legacy when same field+value,
    because EPIC 20 field targets have richer metadata (auto_populate flag,
    voice_required_confidence threshold).
    """
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for item in items:
        field = str(item.get("field_name") or "")
        value_str = str(item.get("value") or "")
        if not field:
            continue
        key = (field, value_str)
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = item
            continue
        # Prefer micro_form over legacy
        if item.get("source") == "micro_form" and existing.get("source") == "legacy":
            by_key[key] = item
            continue
        # Otherwise keep highest confidence
        if float(item.get("confidence") or 0) > float(existing.get("confidence") or 0):
            by_key[key] = item
    return list(by_key.values())


def get_extractor_capabilities() -> dict[str, Any]:
    """Report which extractors are available + their field/moment coverage."""
    capabilities = {
        "legacy_extractor": {"available": False, "fields_covered": []},
        "micro_form_extractor": {"available": False, "moments_covered": []},
    }
    try:
        from prostanet.voice.intent_extractor import extract_voice_candidates  # noqa
        capabilities["legacy_extractor"]["available"] = True
        # Legacy covers general fields like PSA, T-stage, Gleason, ECOG, etc.
        capabilities["legacy_extractor"]["fields_covered"] = [
            "psa_baseline_or_current",
            "gleason_score",
            "clinical_t_stage",
            "ecog_performance",
            "diagnosis_date",
            "biomarker_psa_with_date",
        ]
    except ImportError:
        pass
    try:
        from prostanet.shared.moment_capture_schemas import MOMENT_CAPTURE_SCHEMAS
        capabilities["micro_form_extractor"]["available"] = True
        capabilities["micro_form_extractor"]["moments_covered"] = list(MOMENT_CAPTURE_SCHEMAS.keys())
        capabilities["micro_form_extractor"]["total_field_targets"] = sum(
            len(form.fields) for form in MOMENT_CAPTURE_SCHEMAS.values()
        )
    except ImportError:
        pass
    return capabilities


__all__ = [
    "extract_all_candidates",
    "get_extractor_capabilities",
]
