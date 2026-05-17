"""EPIC 36 — Voice quick-capture intent extraction (focused).

Wraps the deterministic regex parsing for the 5 quick-capture cards
introduced in EPIC 34.A Phases 2-6 (ECOG, HRR, castration, PSMA-PET).
Each extractor accepts a transcript string and returns a typed payload
ready to POST to the corresponding /api/patients/<nss>/{field}-capture
endpoint, or None if no value detected with sufficient confidence.

Design:
- Spanish-first regexes (clinicians dictate in Spanish), fallback to English.
- Numeric word→digit mapping (cero/uno/dos…) for ECOG and lesion counts.
- Conservative: confidence ≥ 0.70 required to surface, else returns
  `{value: None, transcript_excerpt: "...", confidence: x}` so the UI
  can show "no extraje un valor; revisa el dictado".
- Auto-detects optional fields (testosterone for castration, lesion_count
  for PSMA) and includes when found.

NO ML — pure deterministic patterns. This is the PoC layer; full intent
extraction lives in `intent_extractor.py` for richer voice encounter flows.
"""
from __future__ import annotations

import re
from typing import Any


EXTRACTOR_VERSION = "epic36-quick-capture-v1.0"


# ─────────────────── Spanish numeric word → digit ───────────────────

_SPANISH_DIGITS: dict[str, int] = {
    "cero": 0, "uno": 1, "una": 1, "un": 1,
    "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
}


def _normalize_text(text: str) -> str:
    """Lowercase + strip + collapse whitespace; preserves accents."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text).strip().lower())


def _word_to_int(word: str) -> int | None:
    return _SPANISH_DIGITS.get(_normalize_text(word))


def _excerpt(text: str, start: int, end: int, radius: int = 50) -> str:
    left = max(start - radius, 0)
    right = min(end + radius, len(text))
    return " ".join(text[left:right].split())


# ─────────────────── ECOG (EPIC 34.A Phase 2) ───────────────────

# Matches: "ECOG 2", "ECOG de 2", "ECOG: 2", "ECOG dos", "performance status 1",
#          "performance status uno", "estado funcional 0"
_ECOG_NUMERIC = re.compile(
    r"\b(?:ecog|performance\s*status|estado\s*funcional|p\.?s\.?)"
    r"\s*(?:de|=|:)?\s*"
    r"(?P<value>[0-4])\b",
    re.I,
)
_ECOG_WORD = re.compile(
    r"\b(?:ecog|performance\s*status|estado\s*funcional|p\.?s\.?)"
    r"\s*(?:de|=|:)?\s*"
    r"(?P<word>cero|uno|una|un|dos|tres|cuatro)\b",
    re.I,
)


def extract_ecog(transcript: str) -> dict[str, Any]:
    """Returns {value, confidence, transcript_excerpt, source_pattern} or
    {value: None, ...} if not detected."""
    text = _normalize_text(transcript)
    if not text:
        return {"value": None, "confidence": 0.0, "transcript_excerpt": "",
                "source_pattern": None, "extractor_version": EXTRACTOR_VERSION}
    # Numeric pattern first (higher precision)
    m = _ECOG_NUMERIC.search(text)
    if m:
        return {
            "value": int(m.group("value")),
            "confidence": 0.92,
            "transcript_excerpt": _excerpt(text, m.start(), m.end()),
            "source_pattern": "numeric",
            "extractor_version": EXTRACTOR_VERSION,
        }
    m = _ECOG_WORD.search(text)
    if m:
        val = _word_to_int(m.group("word"))
        if val is not None and 0 <= val <= 4:
            return {
                "value": val,
                "confidence": 0.85,
                "transcript_excerpt": _excerpt(text, m.start(), m.end()),
                "source_pattern": "word",
                "extractor_version": EXTRACTOR_VERSION,
            }
    return {"value": None, "confidence": 0.0, "transcript_excerpt": text[:120],
            "source_pattern": None, "extractor_version": EXTRACTOR_VERSION}


# ─────────────────── Castration (EPIC 34.A Phase 5) ───────────────────

# Status keywords (Spanish + EN). IMPORTANTE: orden de evaluación matters —
# _CASTRATE_NON se evalúa ANTES que _CASTRATE_CONFIRMED para evitar que
# "no castrado" sea parseado como "castrado" (substring de confirmed pattern).
_CASTRATE_CONFIRMED = re.compile(
    r"\b(?:castraci[oó]n\s+confirmada|castrate\s+confirmed|"
    r"(?<!no\s)castrado|en\s+castraci[oó]n|"
    r"confirmed\s+castrate|castration\s+achieved)\b", re.I,
)
_CASTRATE_NON = re.compile(
    r"\b(?:no\s+castrado|non[\s-]castrate|sin\s+castraci[oó]n|fuera\s+de\s+castraci[oó]n)\b",
    re.I,
)
_CASTRATE_PENDING = re.compile(
    r"\b(?:pendiente\s+(?:de\s+)?castraci[oó]n|castraci[oó]n\s+pendiente|"
    r"pending\s+castration)\b", re.I,
)
# Testosterone value: "testosterona 18", "testo 22.5", "T 12 ng/dl"
_TESTO_VALUE = re.compile(
    r"\b(?:testosterona|testo|t)\s*(?:de|=|:)?\s*"
    r"(?P<val>\d{1,4}(?:[.,]\d{1,2})?)\s*"
    r"(?P<unit>ng/?d[lL]|nmol/?[lL])?",
    re.I,
)


def extract_castration(transcript: str) -> dict[str, Any]:
    """Returns {status, testosterone_value, testosterone_unit, confidence,
    transcript_excerpt, source_pattern}."""
    text = _normalize_text(transcript)
    if not text:
        return {"status": None, "confidence": 0.0, "transcript_excerpt": "",
                "extractor_version": EXTRACTOR_VERSION}
    status = None
    excerpt = ""
    conf = 0.0
    # Negation FIRST (avoid "no castrado" being matched by confirmed pattern)
    if _CASTRATE_NON.search(text):
        m = _CASTRATE_NON.search(text)
        status = "non_castrate"
        excerpt = _excerpt(text, m.start(), m.end())
        conf = 0.85
    elif _CASTRATE_CONFIRMED.search(text):
        m = _CASTRATE_CONFIRMED.search(text)
        status = "confirmed_castrate"
        excerpt = _excerpt(text, m.start(), m.end())
        conf = 0.88
    elif _CASTRATE_PENDING.search(text):
        m = _CASTRATE_PENDING.search(text)
        status = "pending"
        excerpt = _excerpt(text, m.start(), m.end())
        conf = 0.80

    # Extract optional testosterone
    testo_value = None
    testo_unit = None
    testo_match = _TESTO_VALUE.search(text)
    if testo_match:
        try:
            testo_value = float(testo_match.group("val").replace(",", "."))
            unit_raw = (testo_match.group("unit") or "").lower().replace("/", "/").strip()
            if "nmol" in unit_raw:
                testo_unit = "nmol/L"
            else:
                testo_unit = "ng/dL"
        except (ValueError, TypeError):
            pass
        # If only testo was provided without status, infer from value
        if status is None and testo_value is not None:
            status = "confirmed_castrate" if testo_value < 50 else "non_castrate"
            conf = 0.78
            excerpt = _excerpt(text, testo_match.start(), testo_match.end())
    return {
        "status": status,
        "testosterone_value": testo_value,
        "testosterone_unit": testo_unit,
        "confidence": conf,
        "transcript_excerpt": excerpt or text[:120],
        "extractor_version": EXTRACTOR_VERSION,
    }


# ─────────────────── HRR / Germline (EPIC 34.A Phase 4) ───────────────────

_HRR_POSITIVE = re.compile(
    r"\b(?:hrr\s+positiv[oa]|hrr\s+positive|brca[12]?\s+positiv[oa]|brca[12]?\s+positive|"
    r"variante\s+patog[eé]nica|pathogenic\s+variant|germline\s+positive)\b",
    re.I,
)
_HRR_NEGATIVE = re.compile(
    r"\b(?:hrr\s+negativ[oa]|hrr\s+negative|sin\s+variante|wild[\s-]type|wt\s+(?:hrr|brca))\b",
    re.I,
)
_HRR_NOT_TESTED = re.compile(
    # "no se ha realizado HRR", "no se realizó germline", "sin HRR", "not tested"
    r"\b(?:no\s+(?:se\s+)?(?:ha\s+)?(?:realiz(?:[óo]|ado|ada))?\s*(?:la\s+)?(?:prueba\s+)?(?:hrr|germline)|"
    r"not\s+tested|sin\s+(?:hrr|germline))\b",
    re.I,
)
_HRR_GENE_MATCHER = re.compile(
    r"\b(?P<gene>BRCA[12]|ATM|PALB2|CDK12|CHEK2|FANCA|RAD51[BCD]|BARD1|HOXB13)\b",
    re.I,
)


def extract_hrr(transcript: str) -> dict[str, Any]:
    """Returns {status, gene, confidence, transcript_excerpt}."""
    text = _normalize_text(transcript)
    if not text:
        return {"status": None, "confidence": 0.0, "transcript_excerpt": "",
                "extractor_version": EXTRACTOR_VERSION}
    status = None
    excerpt = ""
    conf = 0.0
    if _HRR_POSITIVE.search(text):
        m = _HRR_POSITIVE.search(text)
        status = "positive"
        excerpt = _excerpt(text, m.start(), m.end())
        conf = 0.88
    elif _HRR_NEGATIVE.search(text):
        m = _HRR_NEGATIVE.search(text)
        status = "negative"
        excerpt = _excerpt(text, m.start(), m.end())
        conf = 0.85
    elif _HRR_NOT_TESTED.search(text):
        m = _HRR_NOT_TESTED.search(text)
        status = "not_tested"
        excerpt = _excerpt(text, m.start(), m.end())
        conf = 0.80
    gene = None
    gm = _HRR_GENE_MATCHER.search(text)
    if gm:
        gene = gm.group("gene").upper()
    return {
        "status": status,
        "gene": gene,
        "confidence": conf,
        "transcript_excerpt": excerpt or text[:120],
        "extractor_version": EXTRACTOR_VERSION,
    }


# ─────────────────── PSMA-PET (EPIC 34.A Phase 6) ───────────────────

_PSMA_POSITIVE_META = re.compile(
    r"\b(?:psma[-\s]?(?:pet)?\s+positiv[oa]\s+(?:metast[aá]sic[oa]|m1|multilesional)|"
    r"psma\s+positive\s+m1|enfermedad\s+psma[-\s]?(?:avida|avid))\b",
    re.I,
)
_PSMA_POSITIVE_OLIGO = re.compile(
    r"\b(?:psma[-\s]?(?:pet)?\s+oligomet[aá]stasico|oligomet[aá]stasico\s+psma|"
    r"psma\s+positive\s+oligo|psma[-\s]+oligo)\b",
    re.I,
)
_PSMA_POSITIVE_LOCAL = re.compile(
    r"\b(?:psma[-\s]?(?:pet)?\s+(?:positivo\s+)?(?:en\s+)?(?:cama\s+prost[aá]tica|local|"
    r"recurrencia\s+local|prostatic\s+bed))\b",
    re.I,
)
_PSMA_NEGATIVE = re.compile(
    r"\b(?:psma[-\s]?(?:pet)?\s+negativ[oa]|sin\s+actividad\s+psma|"
    r"psma\s+negative|no\s+actividad\s+psma)\b",
    re.I,
)
_PSMA_PENDING = re.compile(
    r"\b(?:psma[-\s]?(?:pet)?\s+pendiente|pendiente\s+psma|psma\s+pending|"
    r"orden(?:ado|amos)\s+psma)\b", re.I,
)

_PSMA_LESION_COUNT = re.compile(
    r"\b(?P<count>\d{1,3})\s+lesion(?:es)?\b", re.I,
)
_PSMA_LESION_COUNT_WORD = re.compile(
    r"\b(?P<word>una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+lesion(?:es)?\b",
    re.I,
)
_PSMA_SUVMAX = re.compile(
    r"\b(?:suv\s*max|suvmax|suv)\s*(?:de|=|:)?\s*(?P<val>\d{1,3}(?:[.,]\d{1,2})?)\b",
    re.I,
)


def extract_psma_pet(transcript: str) -> dict[str, Any]:
    """Returns {status, lesion_count, suv_max_value, confidence,
    transcript_excerpt}."""
    text = _normalize_text(transcript)
    if not text:
        return {"status": None, "confidence": 0.0, "transcript_excerpt": "",
                "extractor_version": EXTRACTOR_VERSION}
    status = None
    excerpt = ""
    conf = 0.0
    for pat, label, base_conf in (
        (_PSMA_POSITIVE_META, "positive_metastatic", 0.88),
        (_PSMA_POSITIVE_OLIGO, "positive_oligometastatic", 0.86),
        (_PSMA_POSITIVE_LOCAL, "positive_local_recurrence", 0.82),
        (_PSMA_NEGATIVE, "negative", 0.87),
        (_PSMA_PENDING, "pending", 0.80),
    ):
        m = pat.search(text)
        if m:
            status = label
            excerpt = _excerpt(text, m.start(), m.end())
            conf = base_conf
            break

    lesion_count = None
    lc_match = _PSMA_LESION_COUNT.search(text)
    if lc_match:
        try:
            lesion_count = int(lc_match.group("count"))
        except (ValueError, TypeError):
            pass
    else:
        lcw = _PSMA_LESION_COUNT_WORD.search(text)
        if lcw:
            lesion_count = _word_to_int(lcw.group("word"))

    suv_max = None
    sm = _PSMA_SUVMAX.search(text)
    if sm:
        try:
            suv_max = float(sm.group("val").replace(",", "."))
        except (ValueError, TypeError):
            pass
    # Auto-classify: if lesion_count present but no status keyword, infer
    if status is None and lesion_count is not None:
        if lesion_count <= 5:
            status = "positive_oligometastatic"
            conf = 0.72
        else:
            status = "positive_metastatic"
            conf = 0.72
        excerpt = _excerpt(text, lc_match.start() if lc_match else 0,
                           (lc_match.end() if lc_match else 60))
    return {
        "status": status,
        "lesion_count": lesion_count,
        "suv_max_value": suv_max,
        "confidence": conf,
        "transcript_excerpt": excerpt or text[:120],
        "extractor_version": EXTRACTOR_VERSION,
    }


# ─────────────────── Dispatch table ───────────────────

QUICK_CAPTURE_EXTRACTORS: dict[str, Any] = {
    "ecog": extract_ecog,
    "castration": extract_castration,
    "hrr": extract_hrr,
    "psma_pet": extract_psma_pet,
}


def extract_for_field(transcript: str, field: str) -> dict[str, Any]:
    """Dispatch entrypoint. Raises KeyError if field unknown."""
    if field not in QUICK_CAPTURE_EXTRACTORS:
        raise KeyError(f"Unknown quick-capture field: {field}. "
                       f"Valid: {sorted(QUICK_CAPTURE_EXTRACTORS.keys())}")
    return QUICK_CAPTURE_EXTRACTORS[field](transcript)


__all__ = [
    "EXTRACTOR_VERSION",
    "QUICK_CAPTURE_EXTRACTORS",
    "extract_for_field",
    "extract_ecog",
    "extract_castration",
    "extract_hrr",
    "extract_psma_pet",
]
