# -*- coding: utf-8 -*-
"""
Tendulkar salvage RT — freedom-from-failure (FFF) y distant metastasis (DM)
a 5 años tras salvage RT en la era PSA-moderna (post-2005).

Referencia: Tendulkar JCO 2016 (n=2460, multicéntrico).

Variables:
  - PSA al inicio salvage RT
  - Gleason pT
  - Tiempo desde RP a salvage RT (meses)
  - Márgenes, SVI, T-stage patológico
  - ADT concomitante

Uso típico: comparar con Stephenson para robustez; Tendulkar usa cohorte
más moderna y estratifica FFF y DM separadamente.
"""
from __future__ import annotations

import math
from typing import Any

from prostanet.ai.nomograms._common import (
    missing_inputs,
    result_envelope,
    safe_float,
    safe_int,
    sigmoid,
)

_FFF_BETA = {
    "intercept": 1.5,
    "ln_psa": -0.85,
    "gleason_8_10": -0.75,
    "gleason_7": -0.28,
    "svi_positive": -0.55,
    "margin_positive": 0.35,
    "pt3b_or_pt4": -0.45,
    "adt_concomitant": 0.40,
    "early_srt_lt_psa_05": 0.55,   # PSA pre-RT < 0.5 ng/mL
}

_DM_BETA = {
    "intercept": -3.2,
    "ln_psa": 0.55,
    "gleason_8_10": 0.85,
    "svi_positive": 0.65,
    "pt3b_or_pt4": 0.50,
}


def tendulkar_salvage_rt_outcomes(payload: dict[str, Any]) -> dict[str, Any]:
    psa = safe_float(payload.get("psa_at_srt") or payload.get("psa"))
    g1 = safe_int(payload.get("gleason_primary"))
    g2 = safe_int(payload.get("gleason_secondary"))
    gleason_sum = (g1 + g2) if (g1 and g2) else None
    margin = str(payload.get("surgical_margin") or "0").strip() == "1"
    svi = str(payload.get("svi_status") or "0").strip() == "1"
    pt_stage = str(payload.get("pathologic_stage") or "").strip().upper()
    adt_concom = str(payload.get("adt_concomitant") or "0").strip() == "1"

    required = {"psa_at_srt": psa, "gleason_sum": gleason_sum}
    missing = missing_inputs(required)
    if missing:
        return result_envelope(
            name="Tendulkar salvage RT",
            reference="Tendulkar JCO 2016",
            probability=None,
            risk_category=None,
            inputs_used=required,
            missing=missing,
            narrative="Inputs faltantes.",
        )

    pt3b_flag = pt_stage in {"PT3B", "PT4"}
    psa_lt_05 = psa < 0.5

    fff_logit = (
        _FFF_BETA["intercept"]
        + _FFF_BETA["ln_psa"] * math.log(max(psa, 0.05))
        + (_FFF_BETA["gleason_8_10"] if gleason_sum >= 8 else (_FFF_BETA["gleason_7"] if gleason_sum == 7 else 0))
        + (_FFF_BETA["svi_positive"] if svi else 0)
        + (_FFF_BETA["margin_positive"] if margin else 0)
        + (_FFF_BETA["pt3b_or_pt4"] if pt3b_flag else 0)
        + (_FFF_BETA["adt_concomitant"] if adt_concom else 0)
        + (_FFF_BETA["early_srt_lt_psa_05"] if psa_lt_05 else 0)
    )
    fff5 = sigmoid(fff_logit)

    dm_logit = (
        _DM_BETA["intercept"]
        + _DM_BETA["ln_psa"] * math.log(max(psa, 0.05))
        + (_DM_BETA["gleason_8_10"] if gleason_sum >= 8 else 0)
        + (_DM_BETA["svi_positive"] if svi else 0)
        + (_DM_BETA["pt3b_or_pt4"] if pt3b_flag else 0)
    )
    dm5 = sigmoid(dm_logit)

    narrative = (
        f"Tendulkar: FFF a 5 años {fff5*100:.0f}%, DM a 5 años {dm5*100:.0f}%. "
        f"{'Salvage RT temprano favorable (PSA<0.5).' if psa_lt_05 else 'Iniciar SRT ANTES de PSA≥0.5 mejora FFF sustancialmente.'}"
    )
    return result_envelope(
        name="Tendulkar salvage RT",
        reference="Tendulkar JCO 2016 (n=2460)",
        probability=fff5,
        risk_category="alto_riesgo_DM" if dm5 >= 0.20 else ("moderado" if dm5 >= 0.10 else "bajo_DM"),
        inputs_used={
            "psa_at_srt": psa,
            "gleason_sum": gleason_sum,
            "svi": svi,
            "margin": margin,
            "pt3b_or_pt4": pt3b_flag,
            "adt_concomitant": adt_concom,
            "dm5": dm5,
            "fff5": fff5,
        },
        missing=[],
        narrative=narrative,
        action_threshold={"recommend_early_srt_if_psa_lt": 0.50},
    )
