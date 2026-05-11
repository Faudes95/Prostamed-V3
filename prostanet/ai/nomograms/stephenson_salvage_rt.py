# -*- coding: utf-8 -*-
"""
Stephenson salvage RT — probabilidad de éxito (freedom-from-progression a 6 años)
tras radioterapia de rescate post-prostatectomía.

Variables (Stephenson JCO 2007):
  - PSA al inicio de la salvage RT (ng/mL)
  - Gleason pT (primario + secundario)
  - Márgenes quirúrgicos (positivo/negativo)
  - Invasión vesículas seminales (SVI)
  - Tiempo a recurrencia (meses)
  - PSADT (meses)
  - Dosis salvage RT (Gy)
  - ADT concomitante (sí/no)
"""
from __future__ import annotations

from typing import Any

from prostanet.ai.nomograms._common import (
    missing_inputs,
    result_envelope,
    risk_band,
    safe_float,
    safe_int,
    sigmoid,
)

_BETA = {
    "intercept": 1.1,
    "ln_psa_srt": -0.95,          # log(PSA pre-RT); menor PSA → mejor
    "gleason_8_10": -0.78,
    "gleason_7": -0.30,
    "margin_positive": 0.45,      # margen+ paradójicamente mejora respuesta SRT
    "svi_positive": -0.52,
    "time_to_bcr_months": 0.011,  # más tiempo hasta BCR → mejor
    "psadt_lt_10m": -0.58,
    "dose_ge_66gy": 0.35,
    "adt_concomitant": 0.42,
}


def stephenson_salvage_rt_success(payload: dict[str, Any]) -> dict[str, Any]:
    psa = safe_float(payload.get("psa_at_srt") or payload.get("psa"))
    gleason_sum = None
    g1 = safe_int(payload.get("gleason_primary"))
    g2 = safe_int(payload.get("gleason_secondary"))
    if g1 and g2:
        gleason_sum = g1 + g2
    margin = str(payload.get("surgical_margin") or "0").strip() == "1"
    svi = str(payload.get("svi_status") or "0").strip() == "1"
    time_to_bcr = safe_float(payload.get("time_to_recurrence_months") or payload.get("time_to_bcr_months"))
    psadt = safe_float(payload.get("psadt_months") or payload.get("psa_doubling_time_months"))
    srt_dose = safe_float(payload.get("srt_dose_gy") or payload.get("salvage_rt_dose_gy"))
    adt_concom = str(payload.get("adt_concomitant") or "0").strip() == "1"

    required = {
        "psa_at_srt": psa,
        "gleason_sum": gleason_sum,
        "time_to_recurrence_months": time_to_bcr,
    }
    missing = missing_inputs(required)
    if missing:
        return result_envelope(
            name="Stephenson salvage RT",
            reference="Stephenson, Scardino JCO 2007",
            probability=None,
            risk_category=None,
            inputs_used=required,
            missing=missing,
            narrative="Inputs faltantes para calcular probabilidad de éxito salvage RT.",
            action_threshold={"srt_benefit_if_prob_gte": 0.50},
        )

    import math

    logit = (
        _BETA["intercept"]
        + _BETA["ln_psa_srt"] * math.log(max(psa, 0.05))
        + (_BETA["gleason_8_10"] if gleason_sum >= 8 else (_BETA["gleason_7"] if gleason_sum == 7 else 0))
        + (_BETA["margin_positive"] if margin else 0)
        + (_BETA["svi_positive"] if svi else 0)
        + _BETA["time_to_bcr_months"] * (time_to_bcr or 0)
        + (_BETA["psadt_lt_10m"] if (psadt is not None and psadt < 10) else 0)
        + (_BETA["dose_ge_66gy"] if (srt_dose is not None and srt_dose >= 66) else 0)
        + (_BETA["adt_concomitant"] if adt_concom else 0)
    )
    prob_success = sigmoid(logit)
    category = "alto_beneficio" if prob_success >= 0.60 else ("beneficio_intermedio" if prob_success >= 0.40 else "bajo_beneficio")

    narrative = (
        f"Probabilidad de control libre de progresión a 6 años con salvage RT: {prob_success*100:.0f}%. "
        f"{'Beneficio favorable, proceder' if prob_success >= 0.50 else 'Beneficio limitado, discutir alternativas (sistémica, MDT)'}."
    )
    return result_envelope(
        name="Stephenson salvage RT",
        reference="Stephenson, Scardino JCO 2007 (c-index 0.69)",
        probability=prob_success,
        risk_category=category,
        inputs_used={
            "psa_at_srt": psa,
            "gleason_sum": gleason_sum,
            "margin_positive": margin,
            "svi_positive": svi,
            "time_to_bcr_months": time_to_bcr,
            "psadt_months": psadt,
            "srt_dose_gy": srt_dose,
            "adt_concomitant": adt_concom,
        },
        missing=[],
        narrative=narrative,
        action_threshold={"srt_recommended_if_prob_gte": 0.50},
    )
