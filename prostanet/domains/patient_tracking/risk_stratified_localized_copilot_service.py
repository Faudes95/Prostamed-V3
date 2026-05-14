"""EPIC 20 Fase D — Risk-Stratified Localized Copilot Service.

Unifica los 6 risk-tier subtypes en localized:
  - very_low_risk_localized, low_risk_localized
  - favorable_intermediate_risk_localized, unfavorable_intermediate_risk_localized
  - high_risk_localized, very_high_risk_localized

Build bundle con risk_tier + therapeutic alternatives per NCCN 2026 PROS-2/3/4/5.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

logger = logging.getLogger(__name__)


@dataclass
class RiskStratifiedLocalizedBundle:
    available: bool
    risk_tier: str
    confidence: float
    rationale: str
    nccn_reference: str
    therapeutic_preferred: str
    therapeutic_acceptable: list[str] = field(default_factory=list)
    therapeutic_not_recommended: list[str] = field(default_factory=list)
    pivotal_trials_supporting: list[str] = field(default_factory=list)
    surveillance_protocol: dict[str, str] = field(default_factory=dict)
    patient_decision_factors: list[str] = field(default_factory=list)


def build_risk_stratified_localized_bundle(patient_record: Mapping[str, Any]) -> dict[str, Any]:
    """Build bundle for risk-stratified localized prostate cancer."""
    try:
        from prostanet.domains.state_classifier.clinical_state_classifier import (
            classify_clinical_state,
        )
    except ImportError:
        return {"available": False, "reason": "classifier_unavailable"}

    facts = _extract_localized_facts(patient_record)
    classification = classify_clinical_state(facts)
    if not classification or not classification.state.endswith("_risk_localized"):
        return {"available": False, "reason": "not_localized_or_unclassified"}

    risk_tier = classification.state.replace("_risk_localized", "").replace("_", "_")
    bundle = RiskStratifiedLocalizedBundle(
        available=True,
        risk_tier=risk_tier,
        confidence=classification.confidence,
        rationale=classification.rationale,
        nccn_reference=classification.evidence_tag,
        therapeutic_preferred=classification.therapeutic_alternative_preferred,
        therapeutic_acceptable=classification.therapeutic_alternatives_acceptable,
        therapeutic_not_recommended=classification.therapeutic_alternatives_not_recommended,
    )

    # Risk-tier specific
    if "very_low" in risk_tier:
        bundle.pivotal_trials_supporting = ["PRIAS", "Klotz_Toronto_AS_cohort"]
        bundle.surveillance_protocol = {
            "psa": "q6mo x 2y → q12mo",
            "mri": "baseline + q1-2y if stable",
            "biopsy": "q1-3y or per trigger",
        }
        bundle.patient_decision_factors = [
            "AS strongly preferred per NCCN PROS-3",
            "Life expectancy + comorbidities determinan AS feasibility",
        ]
    elif "very_high" in risk_tier:
        bundle.pivotal_trials_supporting = ["STAMPEDE_arm_G", "ASCENDE-RT", "GETUG-AFU-18"]
        bundle.patient_decision_factors = [
            "Triple modality preferred si fit",
            "Considerar STAMPEDE-G abiraterone intensification si N+",
            "AS contraindicated, focal therapy contraindicated",
        ]
    elif "high" in risk_tier and "very" not in risk_tier:
        bundle.pivotal_trials_supporting = ["DART-01-05", "EORTC-22863", "RTOG-8531"]
        bundle.patient_decision_factors = [
            "EBRT+ADT 18-36mo standard",
            "RP+ePLND alternative si low burden + patient choice",
        ]
    elif "unfavorable_intermediate" in risk_tier:
        bundle.pivotal_trials_supporting = ["ProtecT", "RTOG_9408"]
        bundle.patient_decision_factors = [
            "Tx requerido — AS NO recomendada en unfavorable",
            "Primary pattern 4 = consider intensification",
        ]
    elif "favorable_intermediate" in risk_tier:
        bundle.patient_decision_factors = [
            "Patient choice: AS aceptable en selected low-burden",
            "Tx con cualquier modalidad acceptable",
        ]
    elif "low" in risk_tier and "very" not in risk_tier:
        bundle.patient_decision_factors = [
            "AS preferred per NCCN PROS-3",
            "RP, EBRT, brachy LDR aceptables si paciente prefiere tx",
        ]

    return asdict(bundle)


def _extract_localized_facts(patient_record: Mapping[str, Any]) -> dict[str, Any]:
    baseline = patient_record.get("baseline") or {}
    return {
        "baseline_psa": patient_record.get("baseline_psa") or baseline.get("baseline_psa"),
        "gleason_score": patient_record.get("gleason_score") or baseline.get("gleason_score"),
        "gleason_primary_pattern": patient_record.get("gleason_primary_pattern") or baseline.get("gleason_primary_pattern"),
        "clinical_t_stage": patient_record.get("clinical_t_stage") or baseline.get("clinical_t_stage"),
        "percent_positive_cores": patient_record.get("percent_positive_cores"),
        "psa_density": patient_record.get("psa_density"),
        "bone_lesion_count_total": int(patient_record.get("bone_lesion_count_total") or 0),
        "visceral_metastasis_present": bool(patient_record.get("visceral_metastasis_present")),
        "nonregional_nodal_count": int(patient_record.get("nonregional_nodal_count") or 0),
    }


__all__ = ["build_risk_stratified_localized_bundle", "RiskStratifiedLocalizedBundle"]
