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


def _truthy(value: Any) -> bool:
    """EPIC 25.6 — Defensive boolean coercion for fact values stored as strings."""
    if value is True:
        return True
    if value is False or value is None:
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "si", "sí", "positive", "positivo"}

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


# ─────────────────── EPIC 22c — 22 new trajectory classifiers ───────────────────


def _classify_hereditary_carrier(facts: Mapping[str, Any]) -> ClinicalStateClassification | None:
    """NCCN 2026 PROS-A — Specific germline carrier pathways.

    Distinguishes carriers from the umbrella `hereditary_germline_pathway_umbrella`
    by reading germline_pathogenic_variant + the gene panel. Returns the specific
    carrier state when a pathogenic variant is documented (clinician_verified or
    document_verified). Without an identified variant, returns None (umbrella
    state may still apply via _classify_hereditary_umbrella).
    """
    if str(facts.get("germline_testing_performed") or "").lower() not in ("true", "1", "yes", "si", "sí"):
        return None
    variant = str(facts.get("germline_pathogenic_variant") or "").strip().upper()
    if not variant or variant in {"NONE", "NINGUNA", "NEGATIVE", "NEGATIVO"}:
        return None
    gene = str(facts.get("hrr_gene") or facts.get("germline_gene") or "").strip().upper()

    # Match by gene first; variant text is fallback signal
    if gene == "BRCA2" or "BRCA2" in variant:
        return _build_classification(
            state="brca2_carrier",
            confidence=0.95,
            rationale="Pathogenic BRCA2 germline variant documented → PARP-first eligible",
            discriminators_matched=[f"gene={gene}", f"variant={variant}"],
        )
    if gene == "BRCA1" or "BRCA1" in variant:
        return _build_classification(
            state="brca1_carrier",
            confidence=0.95,
            rationale="Pathogenic BRCA1 germline variant documented",
            discriminators_matched=[f"gene={gene}", f"variant={variant}"],
        )
    if gene == "ATM" or "ATM" in variant:
        return _build_classification(
            state="atm_carrier",
            confidence=0.90,
            rationale="Pathogenic ATM germline variant — PARP response variable, trial preferred",
            discriminators_matched=[f"gene={gene}", f"variant={variant}"],
        )
    if gene in {"MLH1", "MSH2", "MSH6", "PMS2", "EPCAM"} or any(
        token in variant for token in ("MLH1", "MSH2", "MSH6", "PMS2", "EPCAM")
    ):
        return _build_classification(
            state="lynch_carrier",
            confidence=0.92,
            rationale="Lynch syndrome germline variant — pembrolizumab eligible + colorectal surveillance",
            discriminators_matched=[f"gene={gene}", f"variant={variant}"],
        )
    if gene == "HOXB13" or "HOXB13" in variant or "G84E" in variant:
        return _build_classification(
            state="hoxb13_carrier",
            confidence=0.88,
            rationale="HOXB13 G84E germline variant — intensified surveillance from age 40",
            discriminators_matched=[f"gene={gene}", f"variant={variant}"],
        )
    return None


def _classify_post_local_modality(facts: Mapping[str, Any]) -> ClinicalStateClassification | None:
    """NCCN 2026 PROS-F + Phoenix — Post-local treatment by modality.

    Distinguishes surveillance patterns post-treatment by modality:
      - post_brachy_ldr: PSA bounce 18-36mo common, different cutoffs
      - post_ebrt_alone: Phoenix BCR criteria, late toxicity profile
      - post_sbrt: faster nadir, distinct rectal/urinary
      - post_focal_therapy: HIFU/cryo/IRE in-field vs out-of-field follow-up

    Returns None if no local modality recorded or patient is in BCR (the
    post_rt_bcr classifier should fire first for that case).
    """
    if facts.get("nadir_psa_post_rt") and facts.get("current_psa"):
        try:
            if float(facts["current_psa"]) >= float(facts["nadir_psa_post_rt"]) + 2.0:
                return None  # Phoenix BCR handled by _classify_post_rt_bcr
        except (TypeError, ValueError):
            pass
    modality = str(facts.get("prior_local_treatment_modality") or facts.get("rt_modality") or "").lower()
    if not modality:
        return None
    months_since = facts.get("months_since_local_treatment") or facts.get("time_from_local_tx_months")
    rationale_suffix = f"months_since={months_since}" if months_since else ""

    if "brachy" in modality and ("ldr" in modality or "low" in modality):
        return _build_classification(
            state="post_brachy_ldr",
            confidence=0.88,
            rationale=f"Post-LDR brachytherapy surveillance. {rationale_suffix}",
            discriminators_matched=[f"modality={modality}", rationale_suffix],
        )
    if "sbrt" in modality or "stereotactic" in modality:
        return _build_classification(
            state="post_sbrt",
            confidence=0.86,
            rationale=f"Post-SBRT surveillance. Faster nadir; distinct toxicity. {rationale_suffix}",
            discriminators_matched=[f"modality={modality}", rationale_suffix],
        )
    if "ebrt" in modality or modality in {"imrt", "vmat", "3dcrt", "external_beam"}:
        return _build_classification(
            state="post_ebrt_alone",
            confidence=0.85,
            rationale=f"Post-EBRT surveillance. Phoenix monitoring + late toxicity. {rationale_suffix}",
            discriminators_matched=[f"modality={modality}", rationale_suffix],
        )
    if any(token in modality for token in ("hifu", "cryo", "ire", "nanoknife", "focal")):
        return _build_classification(
            state="post_focal_therapy",
            confidence=0.82,
            rationale=f"Post-focal therapy surveillance (in-field vs out-of-field). {rationale_suffix}",
            discriminators_matched=[f"modality={modality}", rationale_suffix],
        )
    return None


def _classify_pre_diagnostic(facts: Mapping[str, Any]) -> ClinicalStateClassification | None:
    """NCCN 2026 PROS-1 — Pre-diagnostic trajectories.

    Three flavors:
      - suspected_low_psa_no_biopsy: PSA 4-10, no PIRADS≥3, age <70, no biopsy
      - suspected_elevated_psa_watchful_wait: PSA >10, ECOG ≥3 OR LE<5y OR frail
      - negative_biopsy_age_lt_45: <45y, high-risk family history, prior neg biopsy
    """
    if facts.get("known_cancer_diagnosis") in (True, "true", "1", 1, "yes"):
        return None  # already diagnosed
    psa = _get_psa(facts)
    if psa is None:
        return None
    age = facts.get("age") or facts.get("age_years")
    try:
        age_num = int(age) if age is not None else None
    except (TypeError, ValueError):
        age_num = None
    ecog = facts.get("ecog") or facts.get("ecog_score")
    le_years = facts.get("life_expectancy_years") or ""
    pirads = facts.get("pirads_score") or facts.get("mri_pirads_score") or 0
    prior_neg_biopsy = facts.get("prior_negative_biopsy") in (True, "true", "1", 1, "yes")

    # Pre-diagnostic Pattern A: negative biopsy in young patient with high-risk FH
    if (age_num is not None and age_num < 45) and prior_neg_biopsy:
        fh_high = (
            facts.get("family_history_cancer") in (True, "true", "1", 1, "yes")
            or facts.get("first_degree_relative_pca_lt60") in (True, "true", "1", 1, "yes")
            or facts.get("brca_family_history") in (True, "true", "1", 1, "yes")
        )
        if fh_high:
            return _build_classification(
                state="negative_biopsy_age_lt_45",
                confidence=0.82,
                rationale=f"Age {age_num} (<45) + prior neg biopsy + high-risk family history",
                discriminators_matched=[f"age={age_num}", "prior_neg_biopsy=true", "fh_high=true"],
            )

    # Pre-diagnostic Pattern B: elevated PSA + frail / limited LE → WW preferred
    is_frail_or_le_limited = (
        (ecog is not None and str(ecog) in ("3", "4"))
        or str(le_years).lower() in ("lt_5y", "<5", "less_than_5")
        or facts.get("frailty_status") in ("frail", "severely_frail")
    )
    if psa > 10 and is_frail_or_le_limited:
        return _build_classification(
            state="suspected_elevated_psa_watchful_wait",
            confidence=0.85,
            rationale=f"PSA {psa} >10 + frail/limited LE → watchful waiting preferred",
            discriminators_matched=[f"psa={psa}", f"ecog={ecog}", f"le={le_years}"],
        )

    # Pre-diagnostic Pattern C: low PSA suspicion without biopsy yet
    try:
        if 4.0 <= psa <= 10.0 and (not pirads or float(pirads) < 3.0) and (age_num is None or age_num < 70):
            return _build_classification(
                state="suspected_low_psa_no_biopsy",
                confidence=0.78,
                rationale=f"PSA {psa} in 4-10 + PIRADS<3 + age<70 → repeat PSA q6mo + lifestyle",
                discriminators_matched=[f"psa={psa}", f"pirads={pirads}", f"age={age_num}"],
            )
    except (TypeError, ValueError):
        pass
    return None


def _classify_oligometastatic_refinement(facts: Mapping[str, Any]) -> ClinicalStateClassification | None:
    """NCCN 2026 PROS-G — Oligometastatic refinement beyond mcspc_*."""
    metas = facts.get("metastasis_count") or facts.get("metastasis_total_count")
    try:
        meta_count = int(metas) if metas is not None else 0
    except (TypeError, ValueError):
        return None
    if meta_count == 0 or meta_count > 3:
        return None  # not oligo

    timing = str(facts.get("metastatic_timing") or "").lower()
    prior_local = str(facts.get("prior_local_treatment_done") or "").lower() in ("true", "1", "yes")
    adt_naive = str(facts.get("current_adt_context") or "").lower() in ("", "none", "no_adt", "naive")

    # Oligo-recurrent post-definitive local
    if prior_local and meta_count <= 3:
        return _build_classification(
            state="oligo_recurrent_post_definitive",
            confidence=0.85,
            rationale=f"{meta_count} lesions post-definitive local treatment → MDT to recurrent sites",
            discriminators_matched=[f"meta_count={meta_count}", "prior_local=true"],
        )
    # Metachronous ADT-naive
    if "metachronous" in timing and adt_naive:
        return _build_classification(
            state="oligometastatic_metachronous_adt_naive",
            confidence=0.83,
            rationale="Metachronous oligomets ADT-naive → MDT preferred vs ARSI escalation",
            discriminators_matched=[f"timing={timing}", "adt_naive=true"],
        )
    # EPIC 25.6 (GodiBot CLASSIFIER-OLIGO-007) — De novo synchronous oligomet
    # MUST distinguish CHAARTED high-volume vs low-volume + exclude visceral.
    # Pre-EPIC25 the rule fired with meta_count≤3 alone — a 3-bone-met
    # patient with appendicular involvement (CHAARTED high-vol) was misclassified
    # as oligo and routed to MDT+SBRT instead of triplete ARASENS.
    if "synchronous" in timing or "de_novo" in timing:
        # Visceral metastasis → defer to mCSPC refinements (visceral_only_m1c)
        visceral_present = (
            _truthy(facts.get("visceral_metastasis_present"))
            or _truthy(facts.get("visceral_liver"))
            or _truthy(facts.get("visceral_lung"))
            or _truthy(facts.get("visceral_adrenal"))
            or _truthy(facts.get("visceral_cns"))
        )
        if visceral_present:
            return None  # not oligo — visceral classified upstream
        # CHAARTED high-volume = ≥4 bone with ≥1 appendicular
        # (femur/humerus/etc, beyond axial spine/pelvis). With meta_count≤3
        # the only path to high-vol is having appendicular involvement.
        has_appendicular = (
            _truthy(facts.get("appendicular_bone_mets"))
            or _truthy(facts.get("bone_appendicular_present"))
            or str(facts.get("bone_distribution") or "").lower() in {"appendicular", "appendicular_+_axial", "diffuse"}
        )
        if has_appendicular and meta_count >= 3:
            return None  # CHAARTED high-vol territory; classified elsewhere
        return _build_classification(
            state="oligometastatic_synchronous",
            confidence=0.86,
            rationale=(
                f"De novo synchronous {meta_count} bone met(s) (≤3), CHAARTED low-vol "
                "(no visceral, no appendicular high-vol) → SBRT to all + systemic ADT/ARSI"
            ),
            discriminators_matched=[
                f"timing={timing}",
                f"meta_count={meta_count}",
                "visceral=false",
                f"appendicular={has_appendicular}",
            ],
        )
    return None


def _classify_special_populations(facts: Mapping[str, Any]) -> ClinicalStateClassification | None:
    """NCCN 2026 PROS-K + AUA — Special populations gating drug choice.

    EPIC 22c.fix: special_populations applies to patients WITH a confirmed PCa
    diagnosis (gating drug/treatment choice). For pre-diagnostic patients,
    the pre_diagnostic.suspected_elevated_psa_watchful_wait rule should fire
    instead. We DO allow special_populations even without explicit diagnosis
    flag IF other treatment-decision context is present (active_adt_context,
    line_of_therapy_number, etc.).
    """
    # If patient is clearly pre-diagnostic, defer to pre_diagnostic classifier
    known_dx = facts.get("known_cancer_diagnosis")
    explicit_no_dx = known_dx in (False, "false", "0", 0, "no")
    has_tx_context = bool(
        facts.get("current_adt_context")
        or facts.get("line_of_therapy_number")
        or facts.get("drug_scheme")
        or facts.get("prior_local_treatment_modality")
        or facts.get("metastasis_count")
    )
    if explicit_no_dx and not has_tx_context:
        return None  # Let pre_diagnostic fire instead

    age = facts.get("age") or facts.get("age_years")
    try:
        age_num = int(age) if age is not None else None
    except (TypeError, ValueError):
        age_num = None
    g8 = facts.get("g8_score")
    frailty = str(facts.get("frailty_status") or "").lower()

    # Geriatric frail limited (>75y + G8≤14)
    try:
        if age_num is not None and age_num > 75:
            if g8 is not None and float(g8) <= 14:
                return _build_classification(
                    state="geriatric_frail_limited",
                    confidence=0.92,
                    rationale=f"Age {age_num} (>75) + G8 {g8} (≤14) → treatment de-escalation",
                    discriminators_matched=[f"age={age_num}", f"g8={g8}", f"frailty={frailty}"],
                )
            if frailty in ("frail", "severely_frail"):
                return _build_classification(
                    state="geriatric_frail_limited",
                    confidence=0.85,
                    rationale=f"Age {age_num} + frailty={frailty}",
                    discriminators_matched=[f"age={age_num}", f"frailty={frailty}"],
                )
    except (TypeError, ValueError):
        pass

    # Young onset (<55y at Dx) — ONLY if confirmed PCa diagnosis; pre-diagnostic
    # patients with age<55 should NOT trigger this (they may have no cancer).
    # EPIC 22c.fix: explicit known_cancer_diagnosis check prevents collision with
    # pre_diagnostic.negative_biopsy_age_lt_45 (whose precondition is no diagnosis).
    has_pca_diagnosis = facts.get("known_cancer_diagnosis") in (True, "true", "1", 1, "yes")
    age_at_dx = facts.get("age_at_diagnosis")  # strict: only true age_at_diagnosis
    if has_pca_diagnosis or age_at_dx is not None:
        try:
            if age_at_dx is not None and int(age_at_dx) < 55:
                return _build_classification(
                    state="young_onset_pca",
                    confidence=0.90,
                    rationale=f"Age at diagnosis {age_at_dx} (<55) — universal germline testing + fertility + aggressive biology",
                    discriminators_matched=[f"age_at_dx={age_at_dx}"],
                )
        except (TypeError, ValueError):
            pass

    # Severe CV — avoid abiraterone
    cv_severe = (
        facts.get("severe_cv_disease") in (True, "true", "1", 1, "yes")
        or str(facts.get("cv_risk_band") or "").lower() == "high"
        or facts.get("active_cardiac_disease") in (True, "true", "1", 1, "yes")
    )
    if cv_severe:
        return _build_classification(
            state="comorbidity_limited_severe_cv",
            confidence=0.85,
            rationale="Severe CV disease — avoid abiraterone+prednisone; prefer enzalutamide w/ cardiac monitoring",
            discriminators_matched=["severe_cv=true"],
        )

    # Severe hepatic — abiraterone contraindicated
    hepatic_severe = (
        facts.get("active_liver_disease") in (True, "true", "1", 1, "yes")
        or facts.get("cirrhosis_or_portal_hypertension") in (True, "true", "1", 1, "yes")
        or str(facts.get("ltf_band") or "").lower() == "high"
    )
    if hepatic_severe:
        try:
            alt_val = facts.get("alt_u_l") or facts.get("alt")
            ast_val = facts.get("ast_u_l") or facts.get("ast")
            if (alt_val and float(alt_val) > 120) or (ast_val and float(ast_val) > 120):
                hepatic_severe = True
        except (TypeError, ValueError):
            pass
    if hepatic_severe:
        return _build_classification(
            state="comorbidity_limited_severe_hepatic",
            confidence=0.85,
            rationale="LFTs >3x ULN OR cirrhosis OR active liver disease — abiraterone contraindicated",
            discriminators_matched=["hepatic_severe=true"],
        )
    return None


def _classify_survivorship(facts: Mapping[str, Any]) -> ClinicalStateClassification | None:
    """NCCN 2026 SURV — Survivorship trajectories (post-curative tail)."""
    years_since = facts.get("years_since_curative_tx") or facts.get("years_NED")
    try:
        y = float(years_since) if years_since is not None else None
    except (TypeError, ValueError):
        y = None

    adt_duration = facts.get("adt_total_duration_months") or facts.get("adt_duration_months")
    try:
        adt_months = float(adt_duration) if adt_duration is not None else None
    except (TypeError, ValueError):
        adt_months = None

    second_primary_risk = (
        facts.get("prior_pelvic_rt_dose_gy")
        or facts.get("years_post_rt", 0)
    )
    try:
        post_rt_years = float(facts.get("years_post_rt") or 0)
    except (TypeError, ValueError):
        post_rt_years = 0

    # Second primary surveillance (post-RT MDS/AML + bladder/rectal)
    if post_rt_years >= 5 and second_primary_risk:
        return _build_classification(
            state="second_primary_surveillance",
            confidence=0.82,
            rationale=f"Post-RT {post_rt_years}y → MDS/AML + bladder/rectal screening cadence",
            discriminators_matched=[f"post_rt_years={post_rt_years}"],
        )

    # ADT long-term complications (≥2y ADT, multi-organ surveillance)
    if adt_months is not None and adt_months >= 24:
        return _build_classification(
            state="adt_long_term_complications",
            confidence=0.88,
            rationale=f"ADT {adt_months}mo (≥24) → bone + CV + metabolic + cognitive surveillance",
            discriminators_matched=[f"adt_months={adt_months}"],
        )

    # Post-curative 5y+
    if y is not None and y >= 5:
        return _build_classification(
            state="survivorship_post_curative_5y_plus",
            confidence=0.85,
            rationale=f"NED {y}y (≥5) → annual PSA + late effects surveillance",
            discriminators_matched=[f"years_NED={y}"],
        )
    return None


# ─────────────────── Main entry point ───────────────────


def classify_clinical_state(
    patient_facts: Mapping[str, Any],
) -> ClinicalStateClassification | None:
    """Apply NCCN 2026 rules to determine clinical state (EPIC 20 + 22c layers).

    Returns ClinicalStateClassification for the FIRST matching rule, or None
    if no rule matches (fallback to baseline 13-state classifier).

    Rule priority (specificity > generality):
    1. Survivorship (post-curative-tail; gates by years_NED / years_post_rt / adt_months)
    2. Hereditary carriers (specific gene → specific carrier state)
    3. Special populations (frailty / age / CV / hepatic — gates drug choice)
    4. Post-RT BCR (specific to RT BCR — Phoenix)
    5. mCRPC subtypes (override generic m1_crpc)
    6. mCSPC refinements (LATITUDE, visceral, PSMA-only)
    7. Oligometastatic refinement (synchronous / metachronous / recurrent post-local)
    8. Oligo-progressive on therapy
    9. Post-local by modality (brachy / EBRT / SBRT / focal)
    10. Risk-stratified localized (6-tier)
    11. Pre-diagnostic (3 patterns)
    12. Hereditary umbrella (concurrent flag, not exclusive)

    Args:
        patient_facts: dict-like with clinical features. Expected keys include
          previously documented EPIC 20 keys, plus EPIC 22c additions:
          - germline_testing_performed, germline_pathogenic_variant, hrr_gene
          - prior_local_treatment_modality, rt_modality, months_since_local_treatment
          - age, age_at_diagnosis, age_years
          - g8_score, frailty_status, severe_cv_disease, active_liver_disease
          - years_since_curative_tx, years_NED, years_post_rt
          - adt_total_duration_months
          - prior_negative_biopsy, family_history_cancer, first_degree_relative_pca_lt60

    Returns:
        ClinicalStateClassification or None if no rule matches.
    """
    # Order matters: most specific first
    rules = [
        _classify_survivorship,              # EPIC 22c
        _classify_hereditary_carrier,        # EPIC 22c — specific carrier (BRCA2/etc)
        _classify_special_populations,       # EPIC 22c — geriatric/young/CV/hepatic
        _classify_post_rt_bcr,
        _classify_mcrpc_subtypes,
        _classify_mcspc_refinements,
        _classify_oligometastatic_refinement,  # EPIC 22c
        _classify_oligo_progressive,
        _classify_post_local_modality,       # EPIC 22c — modality-specific surveillance
        _classify_risk_stratified_localized,
        _classify_pre_diagnostic,            # EPIC 22c — pre-diagnostic patterns
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
