from __future__ import annotations

from typing import Any


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def classify_localized_life_expectancy_band(years: Any) -> dict[str, Any]:
    value = _safe_float(years)
    if value is None:
        return {
            "available": False,
            "life_expectancy_years": None,
            "band": "unknown",
            "band_label_es": "No disponible",
            "observation_guidance": "uncertain",
            "observation_preference_strength": "none",
        }
    if value <= 5:
        return {
            "available": True,
            "life_expectancy_years": value,
            "band": "le_5_years",
            "band_label_es": "≤5 años",
            "observation_guidance": "strongly_favor_observation",
            "observation_preference_strength": "very_high",
        }
    if value < 10:
        return {
            "available": True,
            "life_expectancy_years": value,
            "band": "between_5_and_10_years",
            "band_label_es": "5–10 años",
            "observation_guidance": "favor_observation",
            "observation_preference_strength": "high",
        }
    return {
        "available": True,
        "life_expectancy_years": value,
        "band": "gt_10_years",
        "band_label_es": ">10 años",
        "observation_guidance": "curative_discussion_supported",
        "observation_preference_strength": "none",
    }


__all__ = ["classify_localized_life_expectancy_band"]
