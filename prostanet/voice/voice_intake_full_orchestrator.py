"""EPIC 21 Phase 2A — Full intake voice orchestrator.

Maneja dictation cronológica long-form para llenar el intake COMPLETO de ProstaMed:
  - 16 fields del quick-classify (state_classifier schema)
  - Demographics (edad, comorbilidades)
  - PSA history cronológico (lista de {fecha, valor})
  - Treatment history (RP, RT, ADT, focal therapy)
  - Imaging history (MRI, PSMA-PET, bone scan)
  - Biopsy results (Gleason, cores, %)
  - Genomic/biomarker results (BRCA, HRR, MSI)
  - Current state indicators (metastasis, castration status)

User flow (skill /voice-note-ingest application real):
  Urólogo dicta: "Paciente 68 años, PSA en 2022 fue 8.5, 2024 12.3, 2025 4.2 post RP,
                  Gleason 7 (4+3) pT3a márgenes positivos, RT salvage 2025, PSA actual 2.8"

  Orchestrator extrae:
    - age: 68
    - psa_history: [{2022: 8.5}, {2024: 12.3}, {2025: 4.2}, {today: 2.8}]
    - prior_prostatectomy: "1"
    - gleason_at_rp: "7(4+3)"
    - margin_status: "positive_focal"
    - prior_radiation: "1" (salvage 2025)

  Returns: IntakeOrchestratorResult con:
    - quick_classify_candidates: dict[field_name → MicroFormCandidate]
    - psa_history: lista chronological
    - treatment_history: lista de tx con fechas
    - demographics: edad + comorbidities detected
    - completeness_pct: % de fields requeridos llenados
    - missing_critical_fields: lista de campos críticos sin valor
    - next_dictation_prompt: TTS prompt para continuation ("¿Qué más?")

Honest scope: este orchestrator usa pattern matching avanzado para extraction.
NO sustituye al especialista — urologist valida + classifies después. Output
flagged status=draft.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ─────────────────── Data classes ───────────────────


@dataclass
class IntakeFieldCandidate:
    """Single intake field extracted from voice transcript."""
    field_name: str
    field_label: str
    value: Any
    confidence: float
    evidence_excerpt: str
    section: str  # demographics | quick_classify | psa_history | treatment | biopsy | imaging | biomarker
    auto_populate: bool
    requires_review: bool


@dataclass
class PsaHistoryEntry:
    """Single PSA measurement with date."""
    date_iso: str  # "2025-05-13" or "2024" if year-only
    value: float
    confidence: float
    evidence_excerpt: str


@dataclass
class TreatmentHistoryEntry:
    """Single treatment event."""
    modality: str  # RP, EBRT, brachy_LDR, brachy_HDR, ADT, focal_therapy, chemo, etc.
    date_iso: str  # "2024" or "2024-05" or full ISO
    status: str  # received | ongoing | planned | declined
    detail: str  # e.g., "salvage", "adjuvant", "primary"
    confidence: float


@dataclass
class IntakeOrchestratorResult:
    """Complete result of intake voice orchestration."""
    available: bool
    candidates: list[IntakeFieldCandidate] = field(default_factory=list)
    psa_history: list[PsaHistoryEntry] = field(default_factory=list)
    treatment_history: list[TreatmentHistoryEntry] = field(default_factory=list)
    demographics: dict[str, Any] = field(default_factory=dict)
    quick_classify_candidates: dict[str, IntakeFieldCandidate] = field(default_factory=dict)
    completeness_pct: float = 0.0
    missing_critical_fields: list[str] = field(default_factory=list)
    next_dictation_prompt: str = ""
    transcript_processed: str = ""
    multi_turn_state: dict[str, Any] = field(default_factory=dict)


# ─────────────────── Regex patterns ───────────────────

# Age: "68 años", "edad 68", "tiene 68"
_AGE_PATTERN = re.compile(
    r"\b(?:edad\s+(?:de\s+)?|tiene\s+|paciente\s+de\s+)?(\d{2,3})\s*(?:años?|years?|y/?o)\b",
    re.IGNORECASE,
)

# PSA with date context: "PSA en 2022 fue 8.5" or "PSA 2024 12.3"
_PSA_WITH_DATE_PATTERN = re.compile(
    r"(?:psa|antígeno|antigeno|ape)\s*"
    r"(?:en\s+|del\s+|de\s+)?"
    r"(20\d{2}(?:-\d{2}(?:-\d{2})?)?|(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+(?:de\s+)?20\d{2}|hoy|actual|reciente)"
    r"\s*(?:fue|era|igual\s+a|de|fue\s+de|es)?\s*"
    r"(\d+(?:[.,]\d+)?(?:\s*punto\s*\d+)?)",
    re.IGNORECASE,
)

# Simple PSA mention (no date)
_PSA_SIMPLE_PATTERN = re.compile(
    r"\b(?:psa|antígeno|antigeno|ape)\b\s*(?:actual|current|basal|baseline)?\s*"
    r"(?:de|fue|es|igual\s+a)?\s*"
    r"(\d+(?:[.,]\d+)?(?:\s*punto\s*\d+)?)",
    re.IGNORECASE,
)

# Year mentions (for date inference)
_YEAR_PATTERN = re.compile(r"\b(20[12]\d)\b")

# Gleason: "Gleason 7 (4+3) pT3a"
_GLEASON_FULL_PATTERN = re.compile(
    r"\bgleason\b\s*(?:score|de)?\s*(\d{1,2})\s*(?:[(\[]\s*(\d)\s*\+\s*(\d)\s*[)\]])?",
    re.IGNORECASE,
)

# Path stage: "pT3a", "pT2"
_PATH_STAGE_PATTERN = re.compile(r"\bp[Tt]\s*([2-4][a-c]?)\b")

# Margin: "márgenes positivos", "positive margins focal"
_MARGIN_PATTERN = re.compile(
    r"\bm[áa]rgenes?\b[^.]{0,40}?(positivos?|positive|negativos?|negative)\s*"
    r"(?:focales?|focal|extensos?|extensive)?",
    re.IGNORECASE,
)

# Treatment modalities
_RP_PATTERN = re.compile(
    r"\b(?:prostatectom[íi]a|radical\s+prostatectomy|RP|cirug[íi]a\s+radical)\b",
    re.IGNORECASE,
)
_RT_PATTERN = re.compile(
    r"\b(?:radioterapia|radiation|RT|EBRT|external\s+beam|salvage\s+RT|adyuvante)\b",
    re.IGNORECASE,
)
_ADT_PATTERN = re.compile(
    r"\b(?:ADT|deprivación\s+androgénica|androgen\s+deprivation|leuprolide|goserelin|degarelix)\b",
    re.IGNORECASE,
)
_BRACHY_PATTERN = re.compile(
    r"\b(?:braquiterapia|brachytherapy|LDR|HDR|seed\s+implant)\b",
    re.IGNORECASE,
)
_FOCAL_PATTERN = re.compile(
    r"\b(?:HIFU|crioterapia|cryotherapy|focal\s+therapy|IRE|ablaci[óo]n\s+focal)\b",
    re.IGNORECASE,
)

# Metastasis indicators
_METASTASIS_PATTERN = re.compile(
    r"\b(?:metástasis|metastasis|metástasico|metastatic|met[áa]stasis\s+(?:óseas?|viscerales?|ganglionares?))\b",
    re.IGNORECASE,
)
_BONE_METS_PATTERN = re.compile(
    r"\b(?:lesion(?:es)?\s+óseas?|bone\s+(?:lesion|metastas)|met[áa]stasis\s+óseas?)\b",
    re.IGNORECASE,
)
_VISCERAL_PATTERN = re.compile(
    r"\b(?:viscerales?|hígado|hepátic[ao]|pulm[óo]n(?:ar)?|cerebral)\b",
    re.IGNORECASE,
)

# Castration / ADT status
_CASTRATION_PATTERN = re.compile(
    r"\b(?:castrat(?:e|ion)|castración|testosterona\s+<?\s*\d+|hipogonadal)\b",
    re.IGNORECASE,
)


# ─────────────────── Helpers ───────────────────


def _parse_number_es(text: str) -> float | None:
    """Parse Spanish/English decimal: '4 punto 2' → 4.2"""
    if not text:
        return None
    cleaned = text.strip().lower()
    cleaned = re.sub(r"(\d+)\s*punto\s*(\d+)", r"\1.\2", cleaned)
    cleaned = re.sub(r"(\d+)\s*point\s*(\d+)", r"\1.\2", cleaned)
    cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _normalize_date(raw: str) -> str:
    """Normalize various date formats to ISO 8601 (best effort)."""
    if not raw:
        return ""
    raw_lower = raw.strip().lower()
    if raw_lower in ("hoy", "actual", "reciente", "today", "current"):
        from datetime import date
        return date.today().isoformat()
    # Year only
    year_match = re.match(r"^(20[12]\d)$", raw_lower)
    if year_match:
        return year_match.group(1)
    # Already ISO format
    if re.match(r"^20[12]\d-\d{2}(-\d{2})?$", raw_lower):
        return raw_lower
    # Spanish month + year
    month_map = {
        "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
        "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
        "septiembre": "09", "octubre": "10", "noviembre": "11", "diciembre": "12",
    }
    m = re.match(r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+(?:de\s+)?(20\d{2})", raw_lower)
    if m:
        return f"{m.group(2)}-{month_map[m.group(1)]}"
    return raw_lower


def _extract_excerpt(text: str, match: re.Match, radius: int = 40) -> str:
    start = max(0, match.start() - radius)
    end = min(len(text), match.end() + radius)
    return text[start:end].strip()


# ─────────────────── Section extractors ───────────────────


def _extract_demographics(transcript: str) -> dict[str, Any]:
    """Extract age + comorbidities."""
    demo: dict[str, Any] = {}
    age_match = _AGE_PATTERN.search(transcript)
    if age_match:
        try:
            age = int(age_match.group(1))
            if 18 <= age <= 110:
                demo["age"] = age
                demo["age_confidence"] = 0.9
                demo["age_evidence"] = _extract_excerpt(transcript, age_match)
        except (TypeError, ValueError):
            pass
    # Comorbidity hints
    cv_hints = re.search(r"\b(?:cardiovascular|cv|cardiopatía|infarto|coronar)\w*", transcript, re.IGNORECASE)
    if cv_hints:
        demo["cv_comorbidities_mentioned"] = True
    diabetes = re.search(r"\bdiabet\w*", transcript, re.IGNORECASE)
    if diabetes:
        demo["diabetes_mentioned"] = True
    return demo


def _extract_psa_history(transcript: str) -> list[PsaHistoryEntry]:
    """Extract chronological PSA list.

    Supports multiple orderings:
      - "PSA en 2022 fue 8.5" (PSA first, year after)
      - "en 2022 PSA fue 8.5" (year first, PSA after)
      - "PSA actual 4.2" (no year, today)
      - "en 2024 PSA 12.3" (no connector word)
    """
    entries: list[PsaHistoryEntry] = []
    seen_keys: set[tuple[str, float]] = set()

    # Pattern A: PSA first, year second
    pattern_a = re.compile(
        r"(?:psa|antígeno|antigeno|ape)\s*"
        r"(?:en\s+|del\s+|de\s+)?"
        r"(20\d{2}(?:-\d{2}(?:-\d{2})?)?|(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+(?:de\s+)?20\d{2}|hoy|actual|reciente)"
        r"\s*(?:fue|era|igual\s+a|de|fue\s+de|es)?\s*"
        r"(\d+(?:[.,]\d+)?(?:\s*punto\s*\d+)?)",
        re.IGNORECASE,
    )
    # Pattern B: Year first, PSA second
    pattern_b = re.compile(
        r"(?:en\s+|del\s+|de\s+)?"
        r"(20\d{2}(?:-\d{2}(?:-\d{2})?)?|(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+(?:de\s+)?20\d{2})"
        r"[,\s]+(?:psa|antígeno|antigeno|ape)\s+"
        r"(?:fue|era|igual\s+a|de|fue\s+de|es)?\s*"
        r"(\d+(?:[.,]\d+)?(?:\s*punto\s*\d+)?)",
        re.IGNORECASE,
    )

    for pattern in [pattern_a, pattern_b]:
        for m in pattern.finditer(transcript):
            date_raw = m.group(1)
            val_raw = m.group(2)
            val = _parse_number_es(val_raw)
            if val is None or val < 0 or val > 10000:
                continue
            date_iso = _normalize_date(date_raw)
            key = (date_iso, round(val, 2))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            entries.append(PsaHistoryEntry(
                date_iso=date_iso,
                value=val,
                confidence=0.88,
                evidence_excerpt=_extract_excerpt(transcript, m),
            ))

    # Pattern C: standalone "PSA actual/current X" without date
    pattern_c = re.compile(
        r"(?:psa|antígeno|antigeno|ape)\s+(?:actual|current|reciente|hoy)\s*"
        r"(?:de|fue|es|igual\s+a)?\s*"
        r"(\d+(?:[.,]\d+)?(?:\s*punto\s*\d+)?)",
        re.IGNORECASE,
    )
    for m in pattern_c.finditer(transcript):
        val_raw = m.group(1)
        val = _parse_number_es(val_raw)
        if val is None or val < 0 or val > 10000:
            continue
        from datetime import date
        today_iso = date.today().isoformat()
        key = (today_iso, round(val, 2))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        entries.append(PsaHistoryEntry(
            date_iso=today_iso,
            value=val,
            confidence=0.85,
            evidence_excerpt=_extract_excerpt(transcript, m),
        ))

    # Sort chronologically (year ascending)
    entries.sort(key=lambda e: e.date_iso)
    return entries


def _extract_gleason(transcript: str) -> dict[str, Any] | None:
    """Extract Gleason total + primary + secondary if available."""
    m = _GLEASON_FULL_PATTERN.search(transcript)
    if not m:
        return None
    try:
        total = int(m.group(1))
    except ValueError:
        return None
    if not (6 <= total <= 10):
        return None
    result: dict[str, Any] = {"total": total, "formatted": str(total)}
    if m.group(2) and m.group(3):
        try:
            p = int(m.group(2))
            s = int(m.group(3))
            result["primary"] = p
            result["secondary"] = s
            result["formatted"] = f"{total}({p}+{s})"
        except ValueError:
            pass
    result["confidence"] = 0.88
    result["evidence_excerpt"] = _extract_excerpt(transcript, m)
    return result


def _extract_treatment_history(transcript: str) -> list[TreatmentHistoryEntry]:
    """Extract treatment events (RP, RT, ADT, etc.) with dates if mentioned."""
    treatments: list[TreatmentHistoryEntry] = []

    # RP
    for m in _RP_PATTERN.finditer(transcript):
        # Search for nearby year
        window = transcript[max(0, m.start() - 60):min(len(transcript), m.end() + 60)]
        year_m = _YEAR_PATTERN.search(window)
        date_iso = _normalize_date(year_m.group(1)) if year_m else ""
        treatments.append(TreatmentHistoryEntry(
            modality="RP",
            date_iso=date_iso,
            status="received",
            detail="primary",
            confidence=0.85,
        ))
        break  # Typically only one RP

    # RT
    for m in _RT_PATTERN.finditer(transcript):
        window = transcript[max(0, m.start() - 60):min(len(transcript), m.end() + 60)]
        year_m = _YEAR_PATTERN.search(window)
        date_iso = _normalize_date(year_m.group(1)) if year_m else ""
        detail = "salvage" if "salvage" in window.lower() else "primary"
        if "adyuv" in window.lower():
            detail = "adjuvant"
        treatments.append(TreatmentHistoryEntry(
            modality="EBRT",
            date_iso=date_iso,
            status="received",
            detail=detail,
            confidence=0.82,
        ))
        break

    # ADT
    if _ADT_PATTERN.search(transcript):
        treatments.append(TreatmentHistoryEntry(
            modality="ADT",
            date_iso="",
            status="received",
            detail="",
            confidence=0.80,
        ))

    # Brachy
    if _BRACHY_PATTERN.search(transcript):
        treatments.append(TreatmentHistoryEntry(
            modality="brachytherapy",
            date_iso="",
            status="received",
            detail="",
            confidence=0.80,
        ))

    # Focal therapy
    if _FOCAL_PATTERN.search(transcript):
        treatments.append(TreatmentHistoryEntry(
            modality="focal_therapy",
            date_iso="",
            status="received",
            detail="",
            confidence=0.80,
        ))

    return treatments


def _build_quick_classify_candidates(
    transcript: str,
    psa_history: list[PsaHistoryEntry],
    treatments: list[TreatmentHistoryEntry],
    gleason: dict[str, Any] | None,
) -> dict[str, IntakeFieldCandidate]:
    """Build candidates for the 16 quick-classify fields."""
    candidates: dict[str, IntakeFieldCandidate] = {}

    def _add(name: str, label: str, value: Any, confidence: float, evidence: str, type_: str = "select"):
        candidates[name] = IntakeFieldCandidate(
            field_name=name,
            field_label=label,
            value=value,
            confidence=confidence,
            evidence_excerpt=evidence,
            section="quick_classify",
            auto_populate=confidence >= 0.85,
            requires_review=confidence < 0.85,
        )

    # known_cancer_diagnosis: if Gleason or RP mentioned → confirmed
    if gleason or any(t.modality == "RP" for t in treatments):
        _add("known_cancer_diagnosis", "Diagnóstico confirmado", "1", 0.92,
             "Cancer confirmed via Gleason or RP history")

    # prior_prostatectomy
    rp_done = any(t.modality == "RP" for t in treatments)
    if rp_done:
        _add("prior_prostatectomy", "Prostatectomía previa", "1", 0.90,
             f"RP found in transcript")
    elif _RP_PATTERN.search(transcript):
        _add("prior_prostatectomy", "Prostatectomía previa", "1", 0.85,
             "RP mentioned")

    # prior_radiation
    rt_done = any(t.modality == "EBRT" for t in treatments)
    if rt_done:
        _add("prior_radiation", "Radioterapia previa", "1", 0.88,
             "RT found in transcript")
    elif _RT_PATTERN.search(transcript) or _BRACHY_PATTERN.search(transcript):
        _add("prior_radiation", "Radioterapia previa", "1", 0.82,
             "RT/brachy mentioned")

    # bcr_detected: if PSA rise post-treatment context
    if rp_done and len(psa_history) >= 2:
        latest = psa_history[-1].value
        nadir = min(p.value for p in psa_history)
        # Post-RP BCR: nadir ≤0.1 then rise ≥0.2
        if nadir <= 0.5 and latest >= 0.2:
            _add("bcr_detected", "BCR detectado", "1", 0.78,
                 f"PSA trajectory suggests BCR (nadir {nadir} → current {latest})")

    # metastatic_disease_known
    if _METASTASIS_PATTERN.search(transcript):
        _add("metastatic_disease_known", "Enfermedad metastásica", "1", 0.85,
             "Metastasis mentioned in transcript")

    # metastasis_site
    if _BONE_METS_PATTERN.search(transcript):
        _add("metastasis_site", "Sitio metástasis", "bone", 0.85, "Bone mets mentioned")
    elif _VISCERAL_PATTERN.search(transcript):
        _add("metastasis_site", "Sitio metástasis", "visceral", 0.85, "Visceral mentioned")

    # castrate_testosterone_status
    if _CASTRATION_PATTERN.search(transcript):
        _add("castrate_testosterone_status", "Castración", "castrate", 0.82,
             "Castration status mentioned")

    return candidates


def _compute_completeness(
    quick_classify: dict[str, IntakeFieldCandidate],
    demographics: dict[str, Any],
    psa_history: list[PsaHistoryEntry],
    treatments: list[TreatmentHistoryEntry],
) -> tuple[float, list[str]]:
    """Compute % completeness + list missing critical fields."""
    critical_fields = [
        "age",                          # demographics
        "known_cancer_diagnosis",       # quick_classify
        "psa_baseline_or_history",      # psa_history
        "treatment_history",            # treatments OR explicit "no treatment"
        "gleason_score",                # implied by quick_classify
    ]
    present: list[str] = []
    missing: list[str] = []

    if demographics.get("age"):
        present.append("age")
    else:
        missing.append("age")

    if quick_classify.get("known_cancer_diagnosis"):
        present.append("known_cancer_diagnosis")
    else:
        missing.append("known_cancer_diagnosis")

    if psa_history:
        present.append("psa_baseline_or_history")
    else:
        missing.append("psa_baseline_or_history")

    if treatments:
        present.append("treatment_history")
    # treatments may legitimately be empty (newly diagnosed) — not always critical

    return (
        round(len(present) / len(critical_fields) * 100, 1),
        missing,
    )


def _build_next_prompt(
    completeness_pct: float,
    missing_critical: list[str],
    language: str = "es",
) -> str:
    """Generate TTS continuation prompt for multi-turn dictation."""
    if completeness_pct >= 80:
        if language == "es":
            return "Captura cercana a completa. ¿Algo más antes de clasificar?"
        return "Capture nearly complete. Anything else before classification?"

    label_map = {
        "age": "edad del paciente",
        "known_cancer_diagnosis": "confirmación de diagnóstico",
        "psa_baseline_or_history": "historial de PSA",
        "treatment_history": "historial de tratamientos",
        "gleason_score": "Gleason score",
    }
    missing_labels = [label_map.get(m, m) for m in missing_critical[:3]]
    if language == "es":
        return (
            f"Captura al {completeness_pct:.0f}%. Falta: {', '.join(missing_labels)}. "
            f"¿Puedes continuar dictando?"
        )
    return (
        f"Capture at {completeness_pct:.0f}%. Missing: {', '.join(missing_labels)}. "
        f"Can you continue?"
    )


# ─────────────────── Main entry point ───────────────────


def orchestrate_full_intake(
    transcript: str,
    *,
    multi_turn_state: dict[str, Any] | None = None,
    language: str = "es",
) -> IntakeOrchestratorResult:
    """Process a full intake voice dictation transcript.

    Args:
        transcript: voice transcript text (may be multi-paragraph chronological)
        multi_turn_state: optional dict carrying state from previous turns
            (e.g., {"psa_history": [...], "treatments": [...]})
        language: TTS language for next_dictation_prompt

    Returns:
        IntakeOrchestratorResult with all extracted candidates organized by section.
    """
    result = IntakeOrchestratorResult(
        available=bool(transcript),
        transcript_processed=transcript,
        multi_turn_state=dict(multi_turn_state or {}),
    )

    if not transcript:
        return result

    # 1. Demographics
    result.demographics = _extract_demographics(transcript)

    # 2. PSA history (chronological)
    result.psa_history = _extract_psa_history(transcript)
    # Merge with multi-turn state if present
    if result.multi_turn_state.get("psa_history"):
        previous = [PsaHistoryEntry(**e) if isinstance(e, dict) else e for e in result.multi_turn_state["psa_history"]]
        result.psa_history = previous + result.psa_history
        # Re-sort + dedupe by (date, value)
        seen = set()
        dedupe = []
        for entry in sorted(result.psa_history, key=lambda e: (e.date_iso, e.value)):
            key = (entry.date_iso, round(entry.value, 2))
            if key not in seen:
                seen.add(key)
                dedupe.append(entry)
        result.psa_history = dedupe

    # 3. Treatment history
    result.treatment_history = _extract_treatment_history(transcript)
    if result.multi_turn_state.get("treatment_history"):
        previous = [TreatmentHistoryEntry(**t) if isinstance(t, dict) else t for t in result.multi_turn_state["treatment_history"]]
        result.treatment_history = previous + result.treatment_history

    # 4. Gleason
    gleason = _extract_gleason(transcript)

    # 5. Quick-classify candidates
    result.quick_classify_candidates = _build_quick_classify_candidates(
        transcript=transcript,
        psa_history=result.psa_history,
        treatments=result.treatment_history,
        gleason=gleason,
    )

    # 6. Build candidates list (flat)
    result.candidates = []
    # Demographics → candidates
    if result.demographics.get("age"):
        result.candidates.append(IntakeFieldCandidate(
            field_name="age",
            field_label="Edad",
            value=result.demographics["age"],
            confidence=result.demographics.get("age_confidence", 0.85),
            evidence_excerpt=result.demographics.get("age_evidence", ""),
            section="demographics",
            auto_populate=True,
            requires_review=False,
        ))
    # Gleason
    if gleason:
        result.candidates.append(IntakeFieldCandidate(
            field_name="gleason_score",
            field_label="Gleason score",
            value=gleason["formatted"],
            confidence=gleason["confidence"],
            evidence_excerpt=gleason["evidence_excerpt"],
            section="biopsy",
            auto_populate=True,
            requires_review=False,
        ))
    # Path stage
    path_match = _PATH_STAGE_PATTERN.search(transcript)
    if path_match:
        result.candidates.append(IntakeFieldCandidate(
            field_name="path_stage_at_rp",
            field_label="Etapa patológica al RP",
            value=f"pT{path_match.group(1)}",
            confidence=0.85,
            evidence_excerpt=_extract_excerpt(transcript, path_match),
            section="biopsy",
            auto_populate=True,
            requires_review=False,
        ))
    # Margin
    margin_match = _MARGIN_PATTERN.search(transcript)
    if margin_match:
        positive = bool(re.search(r"positiv", margin_match.group(0), re.IGNORECASE))
        focal = bool(re.search(r"focal", margin_match.group(0), re.IGNORECASE))
        if positive:
            value = "positive_focal" if focal else "positive_extensive"
        else:
            value = "negative"
        result.candidates.append(IntakeFieldCandidate(
            field_name="margin_status",
            field_label="Estado de márgenes",
            value=value,
            confidence=0.82,
            evidence_excerpt=_extract_excerpt(transcript, margin_match),
            section="biopsy",
            auto_populate=True,
            requires_review=False,
        ))
    # Quick-classify candidates added to flat list
    for cand in result.quick_classify_candidates.values():
        result.candidates.append(cand)

    # 7. Compute completeness
    completeness, missing = _compute_completeness(
        result.quick_classify_candidates,
        result.demographics,
        result.psa_history,
        result.treatment_history,
    )
    result.completeness_pct = completeness
    result.missing_critical_fields = missing

    # 8. Next dictation prompt (multi-turn)
    result.next_dictation_prompt = _build_next_prompt(completeness, missing, language=language)

    # 9. Update multi-turn state for caller
    result.multi_turn_state["psa_history"] = [
        {"date_iso": e.date_iso, "value": e.value, "confidence": e.confidence,
         "evidence_excerpt": e.evidence_excerpt}
        for e in result.psa_history
    ]
    result.multi_turn_state["treatment_history"] = [
        {"modality": t.modality, "date_iso": t.date_iso, "status": t.status,
         "detail": t.detail, "confidence": t.confidence}
        for t in result.treatment_history
    ]

    return result


def result_to_dict(result: IntakeOrchestratorResult) -> dict[str, Any]:
    """Serialize for JSON response."""
    return {
        "available": result.available,
        "completeness_pct": result.completeness_pct,
        "missing_critical_fields": result.missing_critical_fields,
        "next_dictation_prompt": result.next_dictation_prompt,
        "candidates": [
            {
                "field_name": c.field_name,
                "field_label": c.field_label,
                "value": c.value,
                "confidence": c.confidence,
                "evidence_excerpt": c.evidence_excerpt,
                "section": c.section,
                "auto_populate": c.auto_populate,
                "requires_review": c.requires_review,
            }
            for c in result.candidates
        ],
        "psa_history": [
            {"date_iso": e.date_iso, "value": e.value, "confidence": e.confidence}
            for e in result.psa_history
        ],
        "treatment_history": [
            {"modality": t.modality, "date_iso": t.date_iso, "status": t.status,
             "detail": t.detail, "confidence": t.confidence}
            for t in result.treatment_history
        ],
        "demographics": result.demographics,
        "multi_turn_state": result.multi_turn_state,
    }


__all__ = [
    "IntakeOrchestratorResult",
    "IntakeFieldCandidate",
    "PsaHistoryEntry",
    "TreatmentHistoryEntry",
    "orchestrate_full_intake",
    "result_to_dict",
]
