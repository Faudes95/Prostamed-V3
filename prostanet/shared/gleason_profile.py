from __future__ import annotations

from typing import Any

# Gleason patterns válidos por definición histológica (ISUP 2014/2019).
_GLEASON_PATTERN_MIN = 1
_GLEASON_PATTERN_MAX = 5
# Suma mínima clínicamente oncológica. Gleason ≤5 corresponde a histología
# benigna/atrofia y NO debe clasificarse como cáncer (guard GT-1 FAUBOT).
_GLEASON_SCORE_MIN = 6
_GLEASON_SCORE_MAX = 10


def safe_int(value: Any) -> int | None:
    try:
        if value in (None, "", "No aplica", "No documentado"):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def safe_gleason_pattern(value: Any) -> int | None:
    # Guard G-1: patrón individual debe estar en [1..5].
    parsed = safe_int(value)
    if parsed is None:
        return None
    if parsed < _GLEASON_PATTERN_MIN or parsed > _GLEASON_PATTERN_MAX:
        return None
    return parsed


def safe_gleason_score(value: Any) -> int | None:
    # Guard GT-1: suma total debe estar en [6..10].
    parsed = safe_int(value)
    if parsed is None:
        return None
    if parsed < _GLEASON_SCORE_MIN or parsed > _GLEASON_SCORE_MAX:
        return None
    return parsed


def derive_gleason_score(primary: int | None, secondary: int | None) -> int | None:
    if primary is None or secondary is None:
        return None
    total = primary + secondary
    # Rechazo explícito GT-1: total < 6 no es cáncer en clasificación ISUP.
    if total < _GLEASON_SCORE_MIN or total > _GLEASON_SCORE_MAX:
        return None
    return total


def derive_isup_grade(primary: int | None, secondary: int | None) -> int | None:
    if primary is None or secondary is None:
        return None
    total = primary + secondary
    if total < _GLEASON_SCORE_MIN or total > _GLEASON_SCORE_MAX:
        return None
    if total == 6:
        return 1
    if total == 7:
        return 2 if primary == 3 else 3
    if total == 8:
        return 4
    return 5


def normalize_gleason_profile(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = dict(payload or {})
    # Patterns 1..5 (G-1). Totales ≥6 (GT-1). Invalid values drop silently so
    # downstream pipeline does not mis-classify benign tissue as cancer.
    primary = safe_gleason_pattern(source.get("gleason_primary"))
    secondary = safe_gleason_pattern(source.get("gleason_secondary"))
    tertiary = safe_gleason_pattern(source.get("gleason_tertiary"))
    if primary is None:
        primary = safe_gleason_pattern(source.get("gleason_score_primary"))
    if secondary is None:
        secondary = safe_gleason_pattern(source.get("gleason_score_secondary"))

    derived_score = derive_gleason_score(primary, secondary)
    derived_isup = derive_isup_grade(primary, secondary)
    legacy_score = safe_gleason_score(source.get("gleason_score"))
    explicit_isup = safe_int(source.get("isup_grade"))

    gleason_score = derived_score if derived_score is not None else legacy_score
    isup_grade = derived_isup if derived_isup is not None else explicit_isup
    has_adverse_tertiary_pattern = tertiary is not None and tertiary >= 5

    summary = ""
    if primary is not None and secondary is not None and gleason_score is not None:
        summary = f"Gleason {gleason_score} ({primary}+{secondary})"
        if isup_grade is not None:
            summary += f", ISUP {isup_grade}"
    elif isup_grade is not None:
        summary = f"ISUP {isup_grade}"
    elif gleason_score is not None:
        summary = f"Gleason {gleason_score}"

    tertiary_note = ""
    if tertiary is not None:
        tertiary_note = f"patrón terciario {tertiary}"
        summary = f"{summary}, con patrón terciario {tertiary}" if summary else f"Patrón terciario {tertiary}"

    return {
        "gleason_primary": primary,
        "gleason_secondary": secondary,
        "gleason_tertiary": tertiary,
        "gleason_score": gleason_score,
        "isup_grade": isup_grade,
        "has_structured_gleason": primary is not None and secondary is not None,
        "has_adverse_tertiary_pattern": has_adverse_tertiary_pattern,
        "summary": summary,
        "tertiary_note": tertiary_note,
    }


def apply_gleason_profile(payload: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(payload or {})
    profile = normalize_gleason_profile(merged)
    for key in ("gleason_primary", "gleason_secondary", "gleason_tertiary", "gleason_score", "isup_grade"):
        if profile.get(key) is not None:
            merged[key] = profile[key]
    if profile.get("summary"):
        merged["histopathology_summary"] = profile["summary"]
    merged["has_adverse_tertiary_pattern"] = profile["has_adverse_tertiary_pattern"]
    return merged
