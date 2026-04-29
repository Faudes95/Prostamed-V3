# -*- coding: utf-8 -*-
"""
Biblioteca de nomogramas clínicos validados para cáncer de próstata.

Incluye:
  - Briganti 2019 — probabilidad LNI pre-RP (indicación ePLND).
  - MSKCC pre-RP — riesgo de progresión bioquímica a 5/10 años.
  - Stephenson post-RP salvage RT — éxito salvage RT a 6 años.
  - Tendulkar salvage RT — FFF y DM a 5 años.
  - CAPRA / CAPRA-S — estratificación de riesgo clínico / post-quirúrgico.
  - Johns Hopkins BCR metástasis — riesgo metastásico por PSADT post-RP.
  - Partin tables — estadio patológico esperado.

Todas las funciones devuelven dicts con probabilidad, categoría de riesgo,
inputs faltantes y referencia bibliográfica.
"""
from prostanet.ai.nomograms.briganti_lni import briganti_2019_lni_risk
from prostanet.ai.nomograms.mskcc_pre_rp import mskcc_pre_rp_bcr_risk
from prostanet.ai.nomograms.stephenson_salvage_rt import stephenson_salvage_rt_success
from prostanet.ai.nomograms.tendulkar_salvage_rt import tendulkar_salvage_rt_outcomes
from prostanet.ai.nomograms.jhu_bcr_metastasis import jhu_bcr_metastasis_risk
from prostanet.ai.nomograms.capra_s import capra_s_score

__all__ = [
    "briganti_2019_lni_risk",
    "mskcc_pre_rp_bcr_risk",
    "stephenson_salvage_rt_success",
    "tendulkar_salvage_rt_outcomes",
    "jhu_bcr_metastasis_risk",
    "capra_s_score",
]
