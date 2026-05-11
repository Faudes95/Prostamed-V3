# -*- coding: utf-8 -*-
"""Utilidades compartidas para nomogramas."""
from __future__ import annotations

import math
from typing import Any


def safe_float(value) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_int(value) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def sigmoid(x: float) -> float:
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except OverflowError:
        return 0.0 if x < 0 else 1.0


def risk_band(probability: float, thresholds: tuple[float, float] = (0.10, 0.25)) -> str:
    low, high = thresholds
    if probability < low:
        return "bajo"
    if probability < high:
        return "intermedio"
    return "alto"


def missing_inputs(required_map: dict[str, Any]) -> list[str]:
    missing = []
    for key, value in required_map.items():
        if value is None:
            missing.append(key)
    return missing


def result_envelope(
    *,
    name: str,
    reference: str,
    probability: float | None,
    risk_category: str | None,
    inputs_used: dict[str, Any],
    missing: list[str],
    narrative: str,
    action_threshold: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "nomogram": name,
        "reference": reference,
        "probability": probability,
        "probability_pct": None if probability is None else round(probability * 100, 1),
        "risk_category": risk_category,
        "inputs_used": inputs_used,
        "missing_inputs": missing,
        "narrative": narrative,
        "action_threshold": action_threshold or {},
        "applicable": probability is not None,
    }
