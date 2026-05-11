from __future__ import annotations

import os
from typing import Any


DEFAULT_FEATURE_FLAGS = {
    # ── Existing clinical flags ──
    "ENABLE_CLINICAL_WIZARDS": True,
    "ENABLE_NCCN_2026_ENGINE": True,
    "ENABLE_EAU_2026_COMPARE": True,
    "ENABLE_BCR2_MODULE": True,
    # ── AI Models (advisory mode — rule-based sigue siendo source of truth) ──
    "ENABLE_AI_STATE_PREDICTION": True,
    "ENABLE_AI_TREATMENT_PREDICTION": True,
    "ENABLE_AI_SURVIVAL_MODEL": True,
    "ENABLE_AI_ANOMALY_DETECTION": True,
    "ENABLE_AI_NLP_EXTRACTION": True,
    # ── AI Agents ──
    "ENABLE_AGENT_CDA": True,
    "ENABLE_AGENT_PSA": True,
    "ENABLE_AGENT_TOA": True,
    "ENABLE_AGENT_QAA": True,
    "ENABLE_AGENT_RIA": True,
    # ── Vertical copiloto clínico (rule-based con overlay AI opcional) ──
    "ENABLE_CRPC_COPILOT": True,
    "ENABLE_POST_RP_SALVAGE_COPILOT": True,
    "ENABLE_MHSPC_COPILOT": True,
    "ENABLE_DIAGNOSTIC_BIOPSY_COPILOT": True,
    "ENABLE_LOCALIZED_SURVEILLANCE_COPILOT": True,
    "ENABLE_POST_RT_SALVAGE_COPILOT": True,
    # ── Engine ──
    "ENABLE_RECALCULATION_ENGINE": True,
    "ENABLE_EVENT_BUS": True,
}


def resolve_feature_flags(config: dict[str, Any] | None = None) -> dict[str, bool]:
    config = config or {}
    flags: dict[str, bool] = {}
    for key, default in DEFAULT_FEATURE_FLAGS.items():
        env_val = os.environ.get(key)
        if key in config:
            flags[key] = bool(config[key])
        elif env_val is not None:
            flags[key] = env_val.lower() in {"1", "true", "yes", "on"}
        else:
            flags[key] = default
    return flags
