# -*- coding: utf-8 -*-
"""
Ensambla bundles de decisión Fase 7 para services existentes.

Cada función es opt-in: se llama desde el service correspondiente y devuelve
un dict listo para incorporarse al result sin romper contratos.

Integraciones:
  - build_m1_crpc_phase7_bundle: rules_parp + rules_radium223 + decisional alerts
  - build_post_rp_phase7_bundle: nomogramas CAPRA-S, JHU mets, Stephenson/Tendulkar
  - build_pre_rp_phase7_bundle: nomograma Briganti LNI + MSKCC pre-RP
  - build_post_rt_phase7_bundle: opciones de rescate local (HIFU/crio/RP/braqui/SBRT)
"""
from __future__ import annotations

from typing import Any


def build_m1_crpc_phase7_bundle(payload: dict, *, m1_context: dict | None = None) -> dict[str, Any]:
    """Compila decisiones avanzadas mCRPC: PARP, Ra-223, alertas."""
    from prostanet.domains.m1_crpc.rules_parp import evaluate_parp_options
    from prostanet.domains.m1_crpc.rules_radium223 import evaluate_radium223_eligibility
    from prostanet.domains.patient_tracking.alert_decisional import evaluate_decisional_alerts

    return {
        "parp_bundle": evaluate_parp_options(payload, m1_context=m1_context),
        "radium223_bundle": evaluate_radium223_eligibility(payload, m1_context=m1_context),
        "decisional_alerts": evaluate_decisional_alerts(payload),
        "version": "phase7.1",
    }


def build_post_rp_phase7_bundle(payload: dict) -> dict[str, Any]:
    """Compila nomogramas post-RP: CAPRA-S, JHU BCR→mets, Stephenson/Tendulkar salvage RT."""
    from prostanet.ai.nomograms import (
        capra_s_score,
        jhu_bcr_metastasis_risk,
        stephenson_salvage_rt_success,
        tendulkar_salvage_rt_outcomes,
    )
    from prostanet.domains.patient_tracking.alert_decisional import evaluate_decisional_alerts

    return {
        "capra_s": capra_s_score(payload),
        "jhu_bcr_metastasis": jhu_bcr_metastasis_risk(payload),
        "stephenson_salvage_rt": stephenson_salvage_rt_success(payload),
        "tendulkar_salvage_rt": tendulkar_salvage_rt_outcomes(payload),
        "decisional_alerts": evaluate_decisional_alerts({**payload, "post_prostatectomy": "1"}),
        "version": "phase7.4",
    }


def build_pre_rp_phase7_bundle(payload: dict) -> dict[str, Any]:
    """Compila nomogramas pre-RP: Briganti LNI + MSKCC BCR."""
    from prostanet.ai.nomograms import briganti_2019_lni_risk, mskcc_pre_rp_bcr_risk

    return {
        "briganti_lni": briganti_2019_lni_risk(payload),
        "mskcc_pre_rp": mskcc_pre_rp_bcr_risk(payload),
        "version": "phase7.4",
    }


def build_post_rt_phase7_bundle(payload: dict) -> dict[str, Any]:
    """Compila opciones de salvage local post-RT."""
    from prostanet.domains.post_radiotherapy_or_local_salvage.rules_local_salvage import (
        evaluate_local_salvage_options,
    )
    from prostanet.domains.patient_tracking.alert_decisional import evaluate_decisional_alerts

    return {
        "local_salvage": evaluate_local_salvage_options(payload),
        "decisional_alerts": evaluate_decisional_alerts(payload),
        "version": "phase7.2",
    }
