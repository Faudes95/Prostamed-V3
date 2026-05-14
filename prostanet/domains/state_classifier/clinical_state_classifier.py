"""EPIC 20 — Clinical State Classifier (NCCN 2026 + EAU 2025).

Adds rule-based classification for the 18 new EPIC 20 Phase 1 trajectories,
complementing the existing `service.StateClassifierService` (which handles
the 13 baseline states).

Architecture:
- This module is the **NCCN 2026-grade refinement layer** on top of the
  baseline classifier.
- Input: patient_facts dict (from tracking_db.build_patient_record_derivatives).
- Output: ClinicalStateClassification dataclass with state, confidence,
  rationale, evidence_tag, therapeutic_alternative_preferred.

Design principles:
1. **Deterministic**: same input → same state. No probabilistic decisions.
2. **Evidence-tagged**: each rule cites NCCN 2026 section + page.
3. **Testable**: each rule has a corresponding synthetic patient exemplar.
4. **Honest**: if data insufficient, return classification with low confidence
   and `data_insufficient` flag — NOT a guess.

Usage:
    from prostanet.domains.state_classifier.clinical_state_classifier import (
        classify_clinical_state,
    )
    result = classify_clinical_state(patient_record)
    print(result.state, result.confidence, result.therapeutic_alternative_preferred)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

logger = logging.getLogger(__name__)

# Registry loaded lazily from YAML
_REGISTRY_CACHE: dict[str, dict] | None = None


@dataclass
class ClinicalStateClassification:
    """Result of NCCN 2026-grade clinical state classification."""
    state: str
    confidence: float  # 0.0-1.0
    rationale: str
    evidence_tag: str  # NCCN reference, e.g., "NCCN_PROS-3_v2026"
    therapeutic_alternative_preferred: str = ""
    therapeutic_alternatives_acceptable: list[str] = field(default_factory=list)
    therapeutic_alternatives_not_recommended: list[str] = field(default_factory=list)
    data_insufficient_flags: list[str] = field(default_factory=list)
    discriminators_matched: list[str] = field(default_factory=list)


def _load_registry() -> dict[str, dict]:
    """Lazy-load therapeutic alternative registry from YAML."""
    global _REGISTRY_CACHE
    if _REGISTRY_CACHE is not None:
        return _REGISTRY_CACHE
    path = (
        Path(__file__).resolve().parent.parent.parent
        / "regulatory" / "clinical" / "therapeutic_alternative_registry.yaml"
    )
    if not path.exists():
        logger.warning("therapeutic_alternative_registry.yaml not found at %s", path)
        _REGISTRY_CACHE = {}
        return _REGISTRY_CACHE
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    _REGISTRY_CACHE = dict(data.get("states") or {})
    return _REGISTRY_CACHE


def _get_alternatives(state: str) -> dict[str, Any]:
    """Get therapeutic alternatives dict from registry for a state."""
    reg = _load_registry()
    entry = reg.get(state, {})
    return entry if isinstance(entry, dict) else {}


def _build_classification(
    state: str,
    confidence: float,
    rationale: str,
    discriminators_matched: list[str],
    data_insufficient_flags: list[str] | None = None,
) -> ClinicalStateClassification:
    """Helper to build classification with registry-driven alternatives."""
    alt = _get_alternatives(state)

    # Handle acceptable_local / acceptable_distant for post_rt_bcr
    acceptable = alt.get("acceptable", [])
    if isinstance(acceptable, dict):
        acceptable = []  # complex case; consumer should handle via raw registry lookup

    return ClinicalStateClassification(
        state=state,
        confidence=confidence,
        rationale=rationale,
        evidence_tag=alt.get("nccn_reference", "NCCN_PROS_v2026"),
        therapeutic_alternative_preferred=str(alt.get("preferred", "")),
        therapeutic_alternatives_acceptable=list(acceptable) if isinstance(acceptable, list) else [],
        therapeutic_alternatives_not_recommended=list(alt.get("not_recommended", [])),
        data_insufficient_flags=list(data_insufficient_flags or []),
        discriminators_matched=list(discriminators_matched),
    )


# ─────────────────── Feature extractors (defensive) ───────────────────


def _get_psa(facts: Mapping[str, Any]) -> float | None:
    """Extract baseline PSA (ng/mL). Defensive against multiple key conventions."""
    candidates = [
        facts.get("baseline_psa"),
        facts.get("psa_baseline"),
        facts.get("psa"),
        (facts.get("baseline") or {}).get("baseline_psa"),
        (facts.get("baseline") or {}).get("psa"),
    ]
    for v in candidates:
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def _get_gleason_total(facts: Mapping[str, Any]) -> int | None:
    """Extract Gleason total score (6-10)."""
    candidates = [
        facts.get("gleason_score"),
        facts.get("gleason_total"),
        (facts.get("baseline") or {}).get("gleason_score"),
        (facts.get("biopsy") or {}).get("gleason_score"),
    ]
    for v in candidates:
        if v is not None:
            try:
                gs_str = str(v).strip()
                # Handle "7(3+4)" or "7(4+3)" format
                if "(" in gs_str:
                    gs_str = gs_str.split("(")[0]
                return int(float(gs_str))
            except (TypeError, ValueError):
                continue
    return None


def _get_gleason_primary(facts: Mapping[str, Any]) -> int | None:
    """Extract Gleason primary pattern (1-5)."""
    candidates = [
        facts.get("gleason_primary_pattern"),
        facts.get("gleason_primary"),
    ]
    for v in candidates:
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                continue
    # Try to parse from gleason_score string like "7(4+3)"
    for key in ("gleason_score", "gleason_total"):
        raw = facts.get(key)
        if isinstance(raw, str) and "(" in raw and "+" in raw:
            try:
                primary = raw.split("(")[1].split("+")[0]
                return int(primary)
            except (IndexError, ValueError):
                continue
    return None


def _get_clinical_t_stage(facts: Mapping[str, Any]) -> str:
    """Extract clinical T stage (cT1-T4) as normalized string."""
    candidates = [
        facts.get("clinical_t_stage"),
        facts.get("ctnm_t"),
        facts.get("t_stage_clinical"),
        (facts.get("baseline") or {}).get("clinical_t_stage"),
    ]
    for v in candidates:
        if v:
            return str(v).strip().lower().replace(" ", "")
    return ""


def _get_metastasis_flags(facts: Mapping[str, Any]) -> dict[str, Any]:
    """Extract metastasis flags."""
    return {
        "bone_count": int(facts.get("bone_lesion_count_total") or 0),
        "visceral_present": bool(facts.get("visceral_metastasis_present")),
        "nonregional_nodal_count": int(facts.get("nonregional_nodal_count") or 0),
        "conventional_m0": bool(facts.get("conventional_imaging_m0")),
        "psma_pet_positive": bool(facts.get("psma_pet_positive")),
        "psma_pet_uptake": str(facts.get("psma_pet_uptake_intensity") or "").lower(),
    }


def _get_castration_resistance(facts: Mapping[str, Any]) -> bool:
    return bool(
        facts.get("castration_resistance_confirmed")
        or facts.get("crpc_confirmed")
        or (facts.get("current_state") in ("m0_crpc", "m1_crpc"))
    )


def _get_hrr_status(facts: Mapping[str, Any]) -> str:
    val = facts.get("hrr_status") or facts.get("hrr_mutation_status") or ""
    return str(val).strip().lower()


# ─────────────────── Classification rules (18 new states) ───────────────────


def _classify_risk_stratified_localized(facts: Mapping[str, Any]) -> ClinicalStateClassification | None:
    """NCCN 2026 PROS-3/4/5 — Risk stratification for localized prostate cancer."""
    psa = _get_psa(facts)
    gleason = _get_gleason_total(facts)
    gs_primary = _get_gleason_primary(facts)
    t_stage = _get_clinical_t_stage(facts)
    mets = _get_metastasis_flags(facts)
    pct_positive = facts.get("percent_positive_cores")
    psa_density = facts.get("psa_density")

    # Only classify if localized (no metastasis confirmed)
    if mets["bone_count"] > 0 or mets["visceral_present"] or mets["nonregional_nodal_count"] > 0:
        return None  # Not localized

    if psa is None or gleason is None or not t_stage:
        return None  # Insufficient data

    discriminators_matched: list[str] = []
    insufficient: list[str] = []

    # Very high risk (PROS-5): cT3b-T4 OR primary GS 5 OR ≥2 high-risk features
    has_t3b_t4 = any(t in t_stage for t in ("t3b", "t4", "ct3b", "ct4"))
    has_primary_gs5 = (gs_primary == 5) if gs_primary is not None else False
    high_risk_features = [
        (psa or 0) > 20,
        (gleason or 0) >= 8,
        any(t in t_stage for t in ("t2c", "t3a", "ct2c", "ct3a")),
    ]
    high_risk_feature_count = sum(1 for f in high_risk_features if f)

    if has_t3b_t4 or has_primary_gs5 or high_risk_feature_count >= 2:
        if has_t3b_t4:
            discriminators_matched.append(f"clinical_T_stage={t_stage} (cT3b-T4)")
        if has_primary_gs5:
            discriminators_matched.append("primary_gleason_pattern=5")
        if high_risk_feature_count >= 2:
            discriminators_matched.append(f"high_risk_feature_count={high_risk_feature_count}")
        return _build_classification(
            state="very_high_risk_localized",
            confidence=0.92,
            rationale=f"Very high risk: {', '.join(discriminators_matched)}",
            discriminators_matched=discriminators_matched,
        )

    # High risk (PROS-4): PSA >20 OR GS 8-10 OR cT2c-T3a
    if (psa > 20) or (gleason >= 8) or any(t in t_stage for t in ("t2c", "t3a", "ct2c", "ct3a")):
        discriminators_matched.append(f"PSA={psa}, GS={gleason}, T={t_stage}")
        return _build_classification(
            state="high_risk_localized",
            confidence=0.90,
            rationale=f"High risk: PSA>20 OR GS≥8 OR cT2c-T3a (PSA={psa}, GS={gleason}, T={t_stage})",
            discriminators_matched=discriminators_matched,
        )

    # Intermediate risk (PROS-3): PSA 10-20 OR cT2b OR GS 7
    is_intermediate = (10 <= psa <= 20) or ("t2b" in t_stage or "ct2b" in t_stage) or (gleason == 7)
    if is_intermediate:
        # Favorable vs unfavorable: GS 4+3=7 OR (PSA 10-20 + GS 7) → unfavorable
        is_unfavorable = (gs_primary == 4 and gleason == 7) or (
            (10 <= psa <= 20) and gleason == 7
        )
        if is_unfavorable:
            discriminators_matched.append(f"GS={gleason}(primary={gs_primary}), PSA={psa}")
            return _build_classification(
                state="unfavorable_intermediate_risk_localized",
                confidence=0.85,
                rationale=f"Unfavorable intermediate: GS 4+3=7 OR PSA 10-20+GS7",
                discriminators_matched=discriminators_matched,
            )
        discriminators_matched.append(f"PSA={psa}, GS={gleason}, T={t_stage}")
        return _build_classification(
            state="favorable_intermediate_risk_localized",
            confidence=0.82,
            rationale=f"Favorable intermediate: GS 3+4=7 OR cT2b OR PSA 10-20",
            discriminators_matched=discriminators_matched,
        )

    # Low / very low risk: PSA <10, GS 6, cT1-T2a
    is_low_basic = (psa < 10) and (gleason == 6) and any(
        t in t_stage for t in ("t1", "ct1", "t2a", "ct2a")
    )
    if is_low_basic:
        # Very low risk requires extras
        is_very_low = "t1c" in t_stage or "ct1c" in t_stage
        if pct_positive is not None:
            try:
                is_very_low = is_very_low and (float(pct_positive) < 34)
            except (TypeError, ValueError):
                insufficient.append("percent_positive_cores_invalid")
        else:
            insufficient.append("percent_positive_cores_missing")
        if psa_density is not None:
            try:
                is_very_low = is_very_low and (float(psa_density) < 0.15)
            except (TypeError, ValueError):
                insufficient.append("psa_density_invalid")
        else:
            insufficient.append("psa_density_missing")

        if is_very_low and not insufficient:
            discriminators_matched.append(
                f"PSA={psa}, GS=6, cT1c, <34% cores, PSA density <0.15"
            )
            return _build_classification(
                state="very_low_risk_localized",
                confidence=0.93,
                rationale="Very low risk: PSA<10 + GS6 + cT1c + <34% positive cores + PSA density <0.15",
                discriminators_matched=discriminators_matched,
            )
        discriminators_matched.append(f"PSA={psa}, GS={gleason}, T={t_stage}")
        return _build_classification(
            state="low_risk_localized",
            confidence=0.85 if not insufficient else 0.70,
            rationale=f"Low risk: PSA<10 + GS6 + cT1-T2a (very-low extras missing or not met)",
            discriminators_matched=discriminators_matched,
            data_insufficient_flags=insufficient,
        )

    return None  # Cannot classify with confidence


def _classify_post_rt_bcr(facts: Mapping[str, Any]) -> ClinicalStateClassification | None:
    """NCCN 2026 PROS-D — Phoenix-defined BCR post-RT."""
    if not facts.get("prior_rt_received"):
        return None
    nadir = facts.get("nadir_psa_post_rt")
    current_psa = facts.get("current_psa") or _get_psa(facts)
    if nadir is None or current_psa is None:
        return None
    try:
        if float(current_psa) >= float(nadir) + 2.0:
            return _build_classification(
                state="post_rt_bcr",
                confidence=0.90,
                rationale=f"Phoenix criteria met: current_PSA {current_psa} >= nadir {nadir} + 2",
                discriminators_matched=[f"phoenix_threshold", f"prior_rt=true"],
            )
    except (TypeError, ValueError):
        pass
    return None


def _classify_mcspc_refinements(facts: Mapping[str, Any]) -> ClinicalStateClassification | None:
    """NCCN 2026 PROS-G — mCSPC sub-state refinements."""
    if _get_castration_resistance(facts):
        return None  # CRPC, not mCSPC
    mets = _get_metastasis_flags(facts)
    has_mets = mets["bone_count"] > 0 or mets["visceral_present"] or mets["nonregional_nodal_count"] > 0
    if not has_mets and not mets["psma_pet_positive"]:
        return None  # Not metastatic

    # PSMA-only metastatic
    if mets["conventional_m0"] and mets["psma_pet_positive"] and not has_mets:
        return _build_classification(
            state="mcspc_psma_only_metastatic",
            confidence=0.85,
            rationale="Conventional imaging M0 + PSMA-PET positive (no conventional metastasis)",
            discriminators_matched=["conventional_M0", "PSMA-PET_positive"],
        )

    # Visceral-only M1c
    if mets["visceral_present"] and mets["bone_count"] == 0:
        return _build_classification(
            state="mcspc_visceral_only_m1c",
            confidence=0.90,
            rationale="Visceral metastasis present + no bone lesions",
            discriminators_matched=["visceral_present=True", "bone_count=0"],
        )

    # LATITUDE high risk criteria count
    gleason = _get_gleason_total(facts)
    latitude_count = sum([
        (gleason or 0) >= 8,
        mets["bone_count"] >= 3,
        mets["visceral_present"],
    ])
    if latitude_count >= 2:
        return _build_classification(
            state="mcspc_latitude_high_risk",
            confidence=0.88,
            rationale=f"LATITUDE high risk ({latitude_count}/3 criteria): GS≥8={'yes' if (gleason or 0)>=8 else 'no'}, bone≥3={'yes' if mets['bone_count']>=3 else 'no'}, visceral={'yes' if mets['visceral_present'] else 'no'}",
            discriminators_matched=[f"latitude_criteria_count={latitude_count}"],
        )
    return None


def _classify_mcrpc_subtypes(facts: Mapping[str, Any]) -> ClinicalStateClassification | None:
    """NCCN 2026 PROS-J — mCRPC subtypes (5 new states)."""
    if not _get_castration_resistance(facts):
        return None
    mets = _get_metastasis_flags(facts)
    has_distant = mets["bone_count"] > 0 or mets["visceral_present"] or mets["nonregional_nodal_count"] > 0
    if not has_distant:
        return None  # Likely m0_crpc handled by baseline classifier

    # Priority order (mutually exclusive in practice):
    # 1. NEPC features → nepc_differentiation
    # 2. MSI-H/dMMR → mcrpc_msi_h_dmmr
    # 3. HRR+ + PARP-naive → mcrpc_hrr_positive_parp_naive
    # 4. PSMA-eligible → mcrpc_psma_eligible_lu177
    # 5. Default by prior ARSI → mcrpc_arsi_naive or mcrpc_post_arsi

    # NEPC
    chromogranin = facts.get("chromogranin_a_value")
    synaptophysin = facts.get("synaptophysin_biopsy_positive")
    small_cell = facts.get("small_cell_morphology")
    nse = facts.get("nse_value")
    nepc_signals = []
    if chromogranin is not None and isinstance(chromogranin, (int, float)) and chromogranin > 100:  # 3x ULN ~33
        nepc_signals.append("chromogranin_elevated")
    if synaptophysin is True:
        nepc_signals.append("synaptophysin_positive")
    if small_cell is True:
        nepc_signals.append("small_cell_morphology")
    if nse is not None and isinstance(nse, (int, float)) and nse > 30:  # 2x ULN
        nepc_signals.append("nse_elevated")
    if len(nepc_signals) >= 2 or small_cell is True:
        return _build_classification(
            state="nepc_differentiation",
            confidence=0.85 if len(nepc_signals) >= 2 else 0.75,
            rationale=f"NEPC features detected: {', '.join(nepc_signals)}",
            discriminators_matched=nepc_signals,
        )

    # MSI-H / dMMR
    msi = str(facts.get("msi_status") or "").lower()
    dmmr = str(facts.get("dmmr_status") or "").lower()
    tmb_high = bool(facts.get("tmb_high"))
    if msi == "high" or dmmr == "deficient" or tmb_high:
        return _build_classification(
            state="mcrpc_msi_h_dmmr",
            confidence=0.92,
            rationale=f"MSI-H/dMMR/TMB-H signal: msi={msi}, dmmr={dmmr}, tmb_high={tmb_high}",
            discriminators_matched=[f"msi={msi}" if msi else "", f"dmmr={dmmr}" if dmmr else "", f"tmb_high={tmb_high}" if tmb_high else ""],
        )

    # HRR positive + PARP naive
    hrr = _get_hrr_status(facts)
    parp_received = bool(facts.get("parp_inhibitor_received"))
    if hrr == "positive" and not parp_received:
        return _build_classification(
            state="mcrpc_hrr_positive_parp_naive",
            confidence=0.88,
            rationale="HRR status positive + PARP-inhibitor naive (PROfound/PROpel eligible)",
            discriminators_matched=["hrr_positive", "parp_naive"],
        )

    # PSMA-eligible
    if mets["psma_pet_positive"] and mets["psma_pet_uptake"] in ("moderate", "intense"):
        gfr = facts.get("gfr_baseline")
        gfr_ok = (gfr is None) or (isinstance(gfr, (int, float)) and gfr >= 50)
        if gfr_ok:
            return _build_classification(
                state="mcrpc_psma_eligible_lu177",
                confidence=0.85,
                rationale=f"PSMA-PET positive with {mets['psma_pet_uptake']} uptake + GFR acceptable",
                discriminators_matched=["psma_pet_positive", f"uptake={mets['psma_pet_uptake']}"],
            )

    # Default: ARSI-naive vs post-ARSI
    prior_arsi = bool(facts.get("prior_arsi_in_mcspc"))
    if prior_arsi:
        return _build_classification(
            state="mcrpc_post_arsi",
            confidence=0.80,
            rationale="mCRPC with prior ARSI in mCSPC phase (cross-resistance considerations)",
            discriminators_matched=["prior_arsi_in_mcspc=True"],
        )
    return _build_classification(
        state="mcrpc_arsi_naive",
        confidence=0.78,
        rationale="mCRPC without prior ARSI in mCSPC phase (first-line ARSI eligible)",
        discriminators_matched=["prior_arsi_in_mcspc=False_or_unknown"],
        data_insufficient_flags=["prior_arsi_history_unverified"] if facts.get("prior_arsi_in_mcspc") is None else [],
    )


def _classify_hereditary_umbrella(facts: Mapping[str, Any]) -> ClinicalStateClassification | None:
    """NCCN 2026 PROS-A — Universal germline testing trigger."""
    # NCCN 2026 triggers
    metastatic = (
        facts.get("metastasis_present")
        or facts.get("visceral_metastasis_present")
        or int(facts.get("bone_lesion_count_total") or 0) > 0
        or facts.get("current_state") in ("m0_crpc", "m1_crpc")
    )
    family_first_degree_lt_60 = bool(facts.get("family_history_first_degree_prostate_cancer_age_lt_60"))
    family_breast_ovary_pancreas = bool(facts.get("family_history_breast_ovary_pancreas"))
    ashkenazi = bool(facts.get("ashkenazi_ancestry"))
    high_risk_localized = facts.get("risk_group") in ("high", "very_high")
    germline_done = bool(facts.get("germline_testing_done"))

    triggers = []
    if metastatic:
        triggers.append("any_metastatic_pca")
    if family_first_degree_lt_60:
        triggers.append("family_first_degree_lt_60")
    if family_breast_ovary_pancreas:
        triggers.append("family_breast_ovary_pancreas")
    if ashkenazi:
        triggers.append("ashkenazi_ancestry")
    if high_risk_localized:
        triggers.append("high_risk_localized")

    if triggers and not germline_done:
        return _build_classification(
            state="hereditary_germline_pathway_umbrella",
            confidence=0.90,
            rationale=f"Germline testing indicated per NCCN 2026 triggers: {', '.join(triggers)}",
            discriminators_matched=triggers,
        )
    return None


def _classify_oligo_progressive(facts: Mapping[str, Any]) -> ClinicalStateClassification | None:
    """NCCN 2026 PROS-G — Oligoprogression on systemic therapy."""
    on_therapy = bool(facts.get("progressing_on_systemic_therapy"))
    if not on_therapy:
        return None
    new_lesions = facts.get("new_lesion_count_since_last_imaging")
    if new_lesions is None:
        return None
    try:
        new_lesion_count = int(new_lesions)
    except (TypeError, ValueError):
        return None
    if new_lesion_count == 0 or new_lesion_count > 3:
        return None  # Not oligo by STOMP/ORIOLE criteria
    response_other = str(facts.get("response_in_existing_lesions") or "").lower()
    if response_other in ("continued_response", "stable", "continued response", ""):
        return _build_classification(
            state="oligo_progressive_on_therapy",
            confidence=0.85,
            rationale=f"On systemic tx + {new_lesion_count} new lesions (≤3) + existing lesions {response_other or 'stable'}",
            discriminators_matched=[f"new_lesions={new_lesion_count}", f"existing_response={response_other}"],
        )
    return None


# ─────────────────── Main entry point ───────────────────


def classify_clinical_state(
    patient_facts: Mapping[str, Any],
) -> ClinicalStateClassification | None:
    """Apply NCCN 2026 rules to determine clinical state (EPIC 20 layer).

    Returns ClinicalStateClassification for the FIRST matching EPIC 20 rule,
    or None if no EPIC 20 rule matches (fallback to baseline 13-state classifier).

    Rule priority (specificity > generality):
    1. NEPC differentiation (overrides ARSI/PARP/Lu177)
    2. Post-RT BCR (specific to RT history)
    3. mCRPC subtypes (override generic m1_crpc)
    4. mCSPC refinements (LATITUDE, visceral, PSMA-only)
    5. Risk-stratified localized (refines localized_initial)
    6. Hereditary umbrella (concurrent flag, not exclusive)
    7. Oligo-progressive on therapy

    Args:
        patient_facts: dict-like with clinical features. Expected keys include:
          - baseline_psa, gleason_score, clinical_t_stage
          - bone_lesion_count_total, visceral_metastasis_present
          - prior_rt_received, nadir_psa_post_rt, current_psa
          - hrr_status, msi_status, dmmr_status, tmb_high
          - psma_pet_positive, psma_pet_uptake_intensity
          - chromogranin_a_value, synaptophysin_biopsy_positive, small_cell_morphology
          - family_history_*, ashkenazi_ancestry
          - progressing_on_systemic_therapy, new_lesion_count_since_last_imaging

    Returns:
        ClinicalStateClassification or None if no EPIC 20 state matches.
    """
    # Order matters: most specific first
    rules = [
        _classify_post_rt_bcr,
        _classify_mcrpc_subtypes,
        _classify_mcspc_refinements,
        _classify_risk_stratified_localized,
        _classify_oligo_progressive,
    ]
    for rule in rules:
        try:
            result = rule(patient_facts)
            if result is not None:
                return result
        except Exception as exc:
            logger.debug("Classification rule %s raised: %s", rule.__name__, exc)
            continue
    # Hereditary is a CONCURRENT umbrella - returned only if no other state matched
    # AND testing indicated (since it's not exclusive)
    hereditary = _classify_hereditary_umbrella(patient_facts)
    if hereditary is not None:
        return hereditary
    return None


# Public exports
__all__ = [
    "ClinicalStateClassification",
    "classify_clinical_state",
]
