# -*- coding: utf-8 -*-
"""
CAPRA-S — estratificación de riesgo post-prostatectomía.

Referencia: Cooperberg J Clin Oncol 2011 (n=3837 CaPSURE).

Puntos:
  PSA preRP: <=6 (0), 6.1-10 (1), 10.1-20 (2), >20 (3)
  Gleason pT: 3+3 (0), 3+4 (1), 4+3 (2), 4+4 o ≥8 (3)
  Margen positivo: 2
  SVI: 2
  ECE: 1
  LNI: 1

Total 0-12:
  0-2: bajo (5y BCR ~10%)
  3-5: intermedio (~45%)
  ≥6: alto (~80%)
"""
from __future__ import annotations

from typing import Any

from prostanet.ai.nomograms._common import (
    missing_inputs,
    result_envelope,
    safe_float,
    safe_int,
)


def _psa_points(psa: float) -> int:
    if psa <= 6:
        return 0
    if psa <= 10:
        return 1
    if psa <= 20:
        return 2
    return 3


def _gleason_points(g1: int, g2: int) -> int:
    if g1 >= 4 and g2 >= 4:
        return 3
    if g1 == 4 and g2 == 3:
        return 2
    if g1 == 3 and g2 == 4:
        return 1
    if g1 + g2 >= 8:
        return 3
    return 0


def capra_s_score(payload: dict[str, Any]) -> dict[str, Any]:
    psa = safe_float(payload.get("psa") or payload.get("psa_preop"))
    g1 = safe_int(payload.get("gleason_primary"))
    g2 = safe_int(payload.get("gleason_secondary"))
    margin = str(payload.get("surgical_margin") or "0").strip() == "1"
    svi = str(payload.get("svi_status") or "0").strip() == "1"
    ece = str(payload.get("ece_status") or "0").strip() == "1"
    lni = str(payload.get("lni_status") or "0").strip() == "1"

    required = {"psa": psa, "gleason_primary": g1, "gleason_secondary": g2}
    missing = missing_inputs(required)
    if missing:
        return result_envelope(
            name="CAPRA-S",
            reference="Cooperberg JCO 2011",
            probability=None,
            risk_category=None,
            inputs_used=required,
            missing=missing,
            narrative="Inputs faltantes.",
        )

    points = (
        _psa_points(psa)
        + _gleason_points(g1, g2)
        + (2 if margin else 0)
        + (2 if svi else 0)
        + (1 if ece else 0)
        + (1 if lni else 0)
    )

    # Probabilidad BCR 5 años (Cooperberg 2011, Tabla 4)
    bcr5_by_score = {0: 0.05, 1: 0.07, 2: 0.10, 3: 0.18, 4: 0.29, 5: 0.38, 6: 0.50, 7: 0.60, 8: 0.74, 9: 0.83, 10: 0.89, 11: 0.92, 12: 0.95}
    prob_bcr5 = bcr5_by_score.get(points, 0.50)

    if points <= 2:
        category = "bajo"
    elif points <= 5:
        category = "intermedio"
    else:
        category = "alto"

    narrative = (
        f"CAPRA-S {points}/12 → riesgo {category}. BCR 5 años estimado: {prob_bcr5*100:.0f}%. "
        f"{'Vigilancia habitual.' if category=='bajo' else ('Considerar salvage RT temprana / ADT.' if category=='alto' else 'Discutir intensificación vs vigilancia PSMA.')}"
    )
    return result_envelope(
        name="CAPRA-S",
        reference="Cooperberg J Clin Oncol 2011",
        probability=prob_bcr5,
        risk_category=category,
        inputs_used={
            "psa": psa,
            "gleason_primary": g1,
            "gleason_secondary": g2,
            "surgical_margin": margin,
            "svi_status": svi,
            "ece_status": ece,
            "lni_status": lni,
            "points": points,
        },
        missing=[],
        narrative=narrative,
        action_threshold={"high_risk_threshold_points": 6, "score_points": points},
    )
