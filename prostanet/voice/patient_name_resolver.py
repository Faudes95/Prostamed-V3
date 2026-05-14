"""EPIC 21 Fase 2 — Patient name resolver (voice → NSS).

Fuzzy matching de spoken patient name → NSS list (top-3 candidates).
Uses stdlib `difflib.SequenceMatcher` (no rapidfuzz dependency needed).

Pipeline (after STT):
  spoken_name → resolve_patient_by_name(spoken_name)
  → list[PatientCandidate{nss, full_name, dob_hint, confidence}]

Disambiguation flow:
  - If single match ≥0.85 confidence → return as primary
  - If 2-3 close matches → return all for disambiguation UI
  - If no match ≥0.6 → return empty (require manual entry)

Voice patterns supported (Spanish):
  - "Abre el paciente Juan García López"
  - "Busca a María Hernández"
  - "Paciente con NSS 12345" (direct NSS lookup)

Authorization scope: phi:read required (clinical_session check upstream).
Caller must verify scope before exposing names.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PatientCandidate:
    """Single patient match result for voice lookup."""
    nss: str
    full_name: str
    dob_hint: str  # e.g., "1958-05" (year-month only, PHI minimization)
    confidence: float
    match_method: str  # "exact_nss", "exact_name", "fuzzy_name", "partial"


# ─────────────────── Helpers ───────────────────


def _normalize_name(name: str) -> str:
    """Normalize name for fuzzy matching: lowercase, strip accents, single spaces."""
    if not name:
        return ""
    import unicodedata
    s = name.strip().lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _name_similarity(a: str, b: str) -> float:
    """Compute similarity using stdlib SequenceMatcher (0.0-1.0)."""
    na = _normalize_name(a)
    nb = _normalize_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    # SequenceMatcher returns a ratio considering longest common subsequences
    base = SequenceMatcher(None, na, nb).ratio()
    # Token-level boost: count matching tokens
    tokens_a = set(na.split())
    tokens_b = set(nb.split())
    if tokens_a and tokens_b:
        token_overlap = len(tokens_a & tokens_b) / max(len(tokens_a), len(tokens_b))
        # Weighted average
        return 0.6 * base + 0.4 * token_overlap
    return base


def _extract_spoken_name_from_command(spoken: str) -> str:
    """Strip command prefixes like 'abre el paciente' or 'busca a'."""
    if not spoken:
        return ""
    prefixes = [
        r"abr[ae]\s+(?:el\s+|al\s+)?(?:paciente|expediente)\s+(?:de\s+)?",
        r"busca?\s+(?:a\s+|al\s+|el\s+|la\s+)?(?:paciente|persona|enfermo)?\s*(?:de\s+|a\s+|al\s+)?",
        r"qui[eé]n\s+es\s+",
        r"muestra(?:me)?\s+(?:el\s+|al\s+)?(?:perfil|paciente)\s+(?:de\s+)?",
        r"open\s+(?:patient|profile)\s+(?:of\s+|for\s+)?",
        r"find\s+(?:patient\s+)?",
    ]
    cleaned = spoken.strip()
    for pat in prefixes:
        cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned


def _extract_nss_from_command(spoken: str) -> str | None:
    """Direct NSS extraction: 'paciente con NSS 12345' or just digits."""
    if not spoken:
        return None
    # NSS pattern: "NSS XXXXXXX" or "número 12345"
    m = re.search(r"\b(?:nss|n[uú]mero|id|expediente)\s*[:=]?\s*(\d{4,})", spoken, re.IGNORECASE)
    if m:
        return m.group(1)
    # Pure digit sequence (8+ digits suggests NSS)
    digits = re.findall(r"\d+", spoken)
    for d in digits:
        if len(d) >= 8:
            return d
    return None


# ─────────────────── Database access ───────────────────


def _load_patient_registry() -> list[dict[str, Any]]:
    """Load all patients from tracking_db with full_name + nss + dob.

    Returns list of dicts: {nss, full_name, dob, patient_id}.
    """
    try:
        import sqlite3
        from tracking_db import DB_PATH

        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT id, nss, full_name, dob FROM patient_identity "
            "WHERE nss IS NOT NULL AND full_name IS NOT NULL"
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception as exc:
        logger.error("Patient registry load failed: %s", exc)
        return []


def _dob_hint(dob: str | None) -> str:
    """Convert DOB to year-only hint for PHI minimization in voice context."""
    if not dob:
        return ""
    try:
        return str(dob)[:4]  # year only
    except (TypeError, IndexError):
        return ""


# ─────────────────── Main entry point ───────────────────


def resolve_patient_by_name(
    spoken_input: str,
    *,
    max_candidates: int = 3,
    min_confidence: float = 0.6,
) -> list[PatientCandidate]:
    """Resolve spoken patient name (or NSS) to candidate list.

    Args:
        spoken_input: raw STT transcript (may include command prefix)
        max_candidates: top-N candidates to return (default 3)
        min_confidence: minimum match confidence to include (default 0.6)

    Returns:
        Sorted list of PatientCandidate (highest confidence first).
        Empty if no matches above min_confidence.
    """
    if not spoken_input or not isinstance(spoken_input, str):
        return []

    # 1. Try NSS direct lookup first
    nss_direct = _extract_nss_from_command(spoken_input)
    if nss_direct:
        registry = _load_patient_registry()
        for row in registry:
            if str(row.get("nss") or "") == nss_direct:
                return [PatientCandidate(
                    nss=str(row["nss"]),
                    full_name=str(row.get("full_name") or ""),
                    dob_hint=_dob_hint(row.get("dob")),
                    confidence=1.0,
                    match_method="exact_nss",
                )]

    # 2. Extract spoken name (strip command prefixes)
    name_query = _extract_spoken_name_from_command(spoken_input)
    if not name_query or len(name_query) < 3:
        return []

    # 3. Fuzzy match against all patients
    registry = _load_patient_registry()
    if not registry:
        return []

    scored: list[tuple[float, dict[str, Any], str]] = []
    name_query_normalized = _normalize_name(name_query)
    for row in registry:
        full_name = str(row.get("full_name") or "")
        sim = _name_similarity(name_query, full_name)
        method = "fuzzy_name"
        # Exact normalized match
        if _normalize_name(full_name) == name_query_normalized:
            sim = 1.0
            method = "exact_name"
        # Partial match (query contained in name, e.g., one apellido)
        elif name_query_normalized in _normalize_name(full_name):
            sim = max(sim, 0.85)
            method = "partial"
        if sim >= min_confidence:
            scored.append((sim, row, method))

    scored.sort(key=lambda x: x[0], reverse=True)

    return [
        PatientCandidate(
            nss=str(row.get("nss") or ""),
            full_name=str(row.get("full_name") or ""),
            dob_hint=_dob_hint(row.get("dob")),
            confidence=round(sim, 3),
            match_method=method,
        )
        for sim, row, method in scored[:max_candidates]
    ]


def candidates_to_response(
    candidates: list[PatientCandidate],
    spoken_input: str,
) -> dict[str, Any]:
    """Format response for voice/UI consumption with disambiguation guidance."""
    if not candidates:
        return {
            "available": False,
            "reason": "no_match",
            "spoken_input": spoken_input,
            "candidates": [],
            "disambiguation_needed": False,
            "tts_response": (
                "No encontré ningún paciente con ese nombre o NSS. "
                "¿Puedes deletrear el nombre o decir el NSS completo?"
            ),
        }

    top = candidates[0]
    # Single high-confidence match
    if len(candidates) == 1 or (top.confidence >= 0.95 and (len(candidates) < 2 or candidates[1].confidence < 0.80)):
        return {
            "available": True,
            "spoken_input": spoken_input,
            "primary_match": _candidate_to_dict(top),
            "candidates": [_candidate_to_dict(c) for c in candidates],
            "disambiguation_needed": False,
            "tts_response": (
                f"Encontré a {top.full_name} con NSS {top.nss}. "
                f"¿Abro su perfil?"
            ),
        }

    # Multiple candidates → disambiguation
    names_list = ", ".join(
        f"{c.full_name} (NSS {c.nss[:4]}...)"
        for c in candidates[:3]
    )
    return {
        "available": True,
        "spoken_input": spoken_input,
        "candidates": [_candidate_to_dict(c) for c in candidates],
        "disambiguation_needed": True,
        "tts_response": (
            f"Encontré {len(candidates)} pacientes con nombre similar: "
            f"{names_list}. ¿Cuál de ellos?"
        ),
    }


def _candidate_to_dict(c: PatientCandidate) -> dict[str, Any]:
    return {
        "nss": c.nss,
        "full_name": c.full_name,
        "dob_hint": c.dob_hint,
        "confidence": c.confidence,
        "match_method": c.match_method,
    }


__all__ = [
    "PatientCandidate",
    "resolve_patient_by_name",
    "candidates_to_response",
]
