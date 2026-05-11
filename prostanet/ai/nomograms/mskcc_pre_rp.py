# -*- coding: utf-8 -*-
"""
MSKCC pre-RP — riesgo de progresión bioquímica (BCR) a 5 y 10 años.

Basado en nomograma Kattan/MSKCC (Stephenson, Kattan JNCI 2006), que
integra PSA, estadío clínico y Gleason primario/secundario de biopsia.

Aproximación con hazards relativos y baseline survival reportados.
"""
from __future__ import annotations

import math
from typing import Any

from prostanet.ai.nomograms._common import (
    missing_inputs,
    result_envelope,
    risk_band,
    safe_float,
    safe_int,
)

# Baseline probabilidad de estar libre de BCR (Kattan 2006, cohorte MSKCC).
_S0_5Y = 0.78
_S0_10Y = 0.65

# Coeficientes aproximados (log-HR) calibrados a la publicación.
_COEF = {
    "ln_psa": 0.42,      # log(PSA)
    "isup": 0.48,        # por grado ISUP
    "ct_stage": 0.35,    # índice T-stage (T2a=0, T2b=1, T2c=2, T3=3)
}


def _ct_stage_index(stage: str) -> int:
    if not stage:
        return 0
    s = str(stage).strip().upper()
    if s in {"T1", "T1A", "T1B", "T1C", "T2", "T2A"}:
        return 0
    if s == "T2B":
        return 1
    if s == "T2C":
        return 2
    if s.startswith("T3") or s.startswith("T4"):
        return 3
    return 0


def mskcc_pre_rp_bcr_risk(payload: dict[str, Any]) -> dict[str, Any]:
    psa = safe_float(payload.get("psa") or payload.get("psa_preop"))
    isup = safe_int(payload.get("isup_biopsy") or payload.get("isup_grade_group") or payload.get("isup"))
    ct = str(payload.get("clinical_t_stage") or payload.get("ct_stage") or "").strip()

    required = {"psa": psa, "isup_biopsy": isup, "clinical_t_stage": ct or None}
    missing = missing_inputs(required)
    if missing or psa is None or psa <= 0:
        return result_envelope(
            name="MSKCC pre-RP (BCR)",
            reference="Stephenson, Kattan JNCI 2006",
            probability=None,
            risk_category=None,
            inputs_used=required,
            missing=missing or (["psa"] if not psa or psa <= 0 else []),
            narrative="Inputs faltantes para calcular riesgo BCR post-RP.",
        )

    xb = (
        _COEF["ln_psa"] * math.log(max(psa, 0.1))
        + _COEF["isup"] * isup
        + _COEF["ct_stage"] * _ct_stage_index(ct)
    )
    risk_rel = math.exp(xb - 1.3)  # centrado en cohorte mediana
    s5 = max(0.0, min(1.0, _S0_5Y ** risk_rel))
    s10 = max(0.0, min(1.0, _S0_10Y ** risk_rel))
    bcr5 = 1 - s5
    bcr10 = 1 - s10

    category = risk_band(bcr5, thresholds=(0.15, 0.40))
    narrative = (
        f"Riesgo BCR a 5 años: {bcr5*100:.0f}%; a 10 años: {bcr10*100:.0f}% "
        f"(MSKCC Kattan 2006). Categoría: {category}."
    )
    return result_envelope(
        name="MSKCC pre-RP (BCR)",
        reference="Stephenson, Kattan JNCI 2006 (c-index 0.79)",
        probability=bcr5,
        risk_category=category,
        inputs_used={"psa": psa, "isup_biopsy": isup, "clinical_t_stage": ct, "bcr_10y": bcr10},
        missing=[],
        narrative=narrative,
        action_threshold={"high_risk_threshold": 0.40},
    )
