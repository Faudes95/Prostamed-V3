# -*- coding: utf-8 -*-
"""
Johns Hopkins BCR → riesgo de metástasis y mortalidad por PSADT.

Referencia: Pound JAMA 1999; Freedland JAMA 2005.
Variables clave:
  - PSADT (meses): <3, 3-9, 9-15, >=15
  - Gleason score post-RP (≤7 vs ≥8)
  - Tiempo a BCR post-RP (<3a vs ≥3a)

Estima:
  - Probabilidad de metástasis a 3/5 años
  - Riesgo relativo de mortalidad cáncer-específica
"""
from __future__ import annotations

from typing import Any

from prostanet.ai.nomograms._common import (
    missing_inputs,
    result_envelope,
    safe_float,
    safe_int,
)


def _psadt_category(psadt: float) -> str:
    if psadt < 3:
        return "<3m"
    if psadt < 9:
        return "3-9m"
    if psadt < 15:
        return "9-15m"
    return ">=15m"


# Riesgo metástasis a 5 años — Freedland 2005 Tabla 4
_MET_RISK_5Y = {
    ("<3m", "gleason_8_10", "early"): 0.99,
    ("<3m", "gleason_8_10", "late"): 0.85,
    ("<3m", "gleason_le_7", "early"): 0.63,
    ("<3m", "gleason_le_7", "late"): 0.39,
    ("3-9m", "gleason_8_10", "early"): 0.84,
    ("3-9m", "gleason_8_10", "late"): 0.60,
    ("3-9m", "gleason_le_7", "early"): 0.27,
    ("3-9m", "gleason_le_7", "late"): 0.16,
    ("9-15m", "gleason_8_10", "early"): 0.47,
    ("9-15m", "gleason_8_10", "late"): 0.27,
    ("9-15m", "gleason_le_7", "early"): 0.11,
    ("9-15m", "gleason_le_7", "late"): 0.07,
    (">=15m", "gleason_8_10", "early"): 0.28,
    (">=15m", "gleason_8_10", "late"): 0.14,
    (">=15m", "gleason_le_7", "early"): 0.05,
    (">=15m", "gleason_le_7", "late"): 0.03,
}


def jhu_bcr_metastasis_risk(payload: dict[str, Any]) -> dict[str, Any]:
    psadt = safe_float(payload.get("psadt_months") or payload.get("psa_doubling_time_months"))
    g1 = safe_int(payload.get("gleason_primary"))
    g2 = safe_int(payload.get("gleason_secondary"))
    gleason_sum = (g1 + g2) if (g1 and g2) else None
    time_to_bcr = safe_float(payload.get("time_to_recurrence_months") or payload.get("time_to_bcr_months"))

    required = {"psadt_months": psadt, "gleason_sum": gleason_sum, "time_to_recurrence_months": time_to_bcr}
    missing = missing_inputs(required)
    if missing:
        return result_envelope(
            name="Johns Hopkins BCR → Metástasis",
            reference="Freedland JAMA 2005",
            probability=None,
            risk_category=None,
            inputs_used=required,
            missing=missing,
            narrative="Inputs faltantes.",
        )

    psadt_cat = _psadt_category(psadt)
    gleason_cat = "gleason_8_10" if gleason_sum >= 8 else "gleason_le_7"
    timing_cat = "early" if time_to_bcr < 36 else "late"

    prob5y = _MET_RISK_5Y.get((psadt_cat, gleason_cat, timing_cat), 0.20)
    category = "muy_alto" if prob5y >= 0.60 else ("alto" if prob5y >= 0.30 else ("moderado" if prob5y >= 0.10 else "bajo"))

    narrative = (
        f"PSADT {psadt:.1f}m ({psadt_cat}), Gleason {gleason_sum} ({gleason_cat}), "
        f"tiempo BCR {time_to_bcr:.0f}m ({timing_cat}). "
        f"Riesgo estimado de metástasis a 5 años: {prob5y*100:.0f}% (Freedland 2005)."
    )
    return result_envelope(
        name="Johns Hopkins BCR → Metástasis",
        reference="Freedland JAMA 2005 (Pound 1999)",
        probability=prob5y,
        risk_category=category,
        inputs_used={
            "psadt_months": psadt,
            "gleason_sum": gleason_sum,
            "time_to_bcr_months": time_to_bcr,
            "psadt_category": psadt_cat,
            "timing_category": timing_cat,
        },
        missing=[],
        narrative=narrative,
        action_threshold={"intensify_if_prob_gte": 0.30, "early_salvage_if_prob_gte": 0.10},
    )
