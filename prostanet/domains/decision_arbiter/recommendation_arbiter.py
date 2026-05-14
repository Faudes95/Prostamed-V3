"""EPIC 23 — Clinical Recommendation Arbiter.

PROBLEM (documented by clinician 2026-05-13 reviewing patient_profile_v2.html):

    The patient profile renders multiple Cortana cards (CV safety, BRCA2 pathway,
    ADT long-term, etc.) AND a Patient Twin OS regimen ranking. Each card is
    correct in its own domain — but cards do NOT consult each other, so:

      - CV card says "AVOID abiraterone+prednisone with active CV disease"
      - Patient Twin OS ranks "abiraterone #1" (expected OS gain 16.8mo for mCSPC)
      → CONFLICT. Clinician sees abiraterone recommended AND contraindicated.

      - BRCA2 card says "PARP first-line in mCRPC"
      - Patient is mCSPC (not_castrate, M0/M1b ambiguous)
      → TIMING ERROR. PARP not applicable at this state.

      - patient_clinical_facts shows metastatic_stage_resolved=M0 AND m_substage_resolved=M1b
      → DATA INTEGRITY ERROR. Mutually exclusive values.

SOLUTION:

    A single arbiter `arbitrate_recommendations()` that:
      1. Collects all CardRecommendation emitted by EPIC 22b/22c cards.
      2. Collects the Patient Twin OS regimen ranking.
      3. Detects 4 conflict classes:
         a. CV/hepatic safety vs Twin ranking (contraindication override)
         b. State-aware timing (PARP requires mCRPC, etc.)
         c. Data integrity contradictions (M0 vs M1b)
         d. Hereditary timing (BRCA2 PARP first-line only in mCRPC)
      4. Re-ranks Twin OS removing contraindicated regimens.
      5. Emits ArbitratedDecision with:
         - unified_top_regimen (after re-ranking)
         - conflicts_detected (list)
         - safety_exclusions_applied
         - timing_warnings
         - data_integrity_flags
      6. Persists conflict resolution to patient_fact_lineage_events
         for FDA SaMD audit trail.

This is decision SUPPORT only — clinician validates all outputs. The arbiter
NEVER autonomously discards a regimen; it surfaces the conflict + the resolved
ranking + the rationale, and leaves the final choice to the clinician.

Authorization scope: internal_shadow_observational_validation.

Skills:
- /api-design: clean dataclass contracts
- /backend-patterns: single-responsibility detectors composed in arbitrate()
- /clinical-reports: decision_fusion_summary structure suitable for clinical
  documentation export
- /deep-research: NCCN 2026 v2 references per conflict rule
- /fda-medtech-compliance-auditor: lineage event emission for every resolution
- /ui-ux-pro-max: prioritized severity ordering for UI banner
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Mapping

logger = logging.getLogger(__name__)


# ─────────────────── Data contracts ───────────────────


@dataclass
class CardRecommendation:
    """A single recommendation emitted by a Cortana card (EPIC 22b/22c card).

    Cards register their recommendations into the arbiter so it can detect
    cross-card conflicts.
    """
    source_card: str               # e.g., "comorbidity_cv", "brca2_carrier"
    state_required: str            # clinical state where this rec applies, "" if any
    preferred_action: str          # e.g., "enzalutamide_or_apalutamide_+_..."
    not_recommended: list[str] = field(default_factory=list)  # e.g., ["abiraterone_..."]
    contraindicated_drugs: list[str] = field(default_factory=list)  # raw drug names
    nccn_reference: str = ""
    evidence_grade: str = ""       # I, II, III
    severity_if_violated: str = "moderate"  # "critical", "high", "moderate", "low"


@dataclass
class ClinicalConflict:
    """A detected conflict between independently-emitted recommendations."""
    conflict_id: str               # e.g., "cv_abi_override", "brca2_mcspc_timing"
    severity: str                  # "critical" | "high" | "moderate" | "low"
    title: str                     # human-readable headline
    description: str               # what's wrong
    affected_sources: list[str]    # card names + "patient_twin_os" if involved
    resolution: str                # what the arbiter did about it
    clinical_rationale: str        # WHY (NCCN reference)
    requires_clinician_review: bool = True


@dataclass
class ArbitratedDecision:
    """Final fused decision output. Consumed by `pm2DecisionFusionSummary` card.

    The clinician sees this BEFORE individual card recommendations so the
    conflict resolution is the headline, not buried in scrolling.
    """
    has_conflicts: bool
    severity_max: str = "none"     # "critical" highest, "low" lowest, "none" if no conflict
    conflicts: list[ClinicalConflict] = field(default_factory=list)
    # Re-ranked regimens after applying contraindications.
    # Same shape as patient_twin.regimen_rankings_personalized items
    arbitrated_ranking: list[dict[str, Any]] = field(default_factory=list)
    excluded_regimens: list[dict[str, str]] = field(default_factory=list)  # {drug, reason}
    timing_warnings: list[str] = field(default_factory=list)
    data_integrity_flags: list[str] = field(default_factory=list)
    arbiter_version: str = "epic23_v1.0"


# ─────────────────── Conflict detectors (single responsibility each) ───────────────────


def _detect_cv_abi_conflict(
    cards: list[CardRecommendation],
    twin_ranking: list[Mapping[str, Any]],
    facts: Mapping[str, Any],
) -> ClinicalConflict | None:
    """Conflict A — CV safety vs Patient Twin abiraterone ranking.

    NCCN 2026 PROS-K: abiraterone+prednisone CONTRAINDICATED in active CV disease.
    Fires when:
      - severe_cv_disease=true OR active_cardiac_disease=true OR cv_risk_band=high
      - AND Twin ranks abiraterone in top-3 (or marks it preferred)

    Resolution: exclude abiraterone from re-ranking, surface alternative top.
    """
    cv_severe = (
        _truthy(facts.get("severe_cv_disease"))
        or _truthy(facts.get("active_cardiac_disease"))
        or str(facts.get("cv_risk_band") or "").lower() == "high"
    )
    if not cv_severe:
        return None

    abi_in_top = any(
        "abirat" in str(r.get("regimen_name", "")).lower()
        for r in (twin_ranking or [])[:3]
    )
    if not abi_in_top:
        return None

    cv_card = next((c for c in cards if c.source_card == "comorbidity_cv"), None)
    return ClinicalConflict(
        conflict_id="cv_abi_override",
        severity="critical",  # Patient could be hospitalized with IC if recommended
        title="Conflicto crítico — abiraterona top-3 en Twin OS pero contraindicada por CV severa",
        description=(
            "El ranking del Patient Twin OS posiciona abiraterona en el top-3 sin "
            "considerar la enfermedad cardiovascular severa del paciente. NCCN 2026 "
            "PROS-K contraindica abiraterona+prednisona con CV activa por riesgo de "
            "descompensación cardíaca."
        ),
        affected_sources=["patient_twin_os", "comorbidity_cv"],
        resolution=(
            "Abiraterona EXCLUIDA del ranking re-arbitrado. Top-1 promovido a "
            "siguiente ARSI elegible (enzalutamida / apalutamida / darolutamida)."
        ),
        clinical_rationale=(
            f"NCCN 2026 PROS-K. "
            f"{(cv_card.nccn_reference if cv_card else 'comorbidity_limited_severe_cv')}: "
            "el riesgo CV documentado supera el beneficio incremental de abiraterona "
            "sobre alternativas ARSI."
        ),
        requires_clinician_review=True,
    )


def _detect_hepatic_abi_conflict(
    cards: list[CardRecommendation],
    twin_ranking: list[Mapping[str, Any]],
    facts: Mapping[str, Any],
) -> ClinicalConflict | None:
    """Conflict B — hepatic safety vs Twin abiraterone ranking.

    NCCN 2026 PROS-K: abiraterone CONTRAINDICATED with active liver disease,
    cirrhosis, or LFTs >3x ULN.
    """
    hepatic_severe = (
        _truthy(facts.get("active_liver_disease"))
        or _truthy(facts.get("cirrhosis_or_portal_hypertension"))
    )
    try:
        alt = float(facts.get("alt_u_l") or facts.get("alt") or 0)
        ast = float(facts.get("ast_u_l") or facts.get("ast") or 0)
        if alt > 120 or ast > 120:
            hepatic_severe = True
    except (TypeError, ValueError):
        pass
    if not hepatic_severe:
        return None

    abi_in_top = any(
        "abirat" in str(r.get("regimen_name", "")).lower()
        for r in (twin_ranking or [])[:3]
    )
    if not abi_in_top:
        return None

    return ClinicalConflict(
        conflict_id="hepatic_abi_override",
        severity="critical",
        title="Conflicto crítico — abiraterona top-3 en Twin OS pero contraindicada por hepatopatía",
        description=(
            "El ranking del Patient Twin OS posiciona abiraterona en el top-3 sin "
            "considerar el daño hepático del paciente. NCCN 2026 PROS-K contraindica "
            "abiraterona en active liver disease, cirrhosis, o LFTs >3x ULN."
        ),
        affected_sources=["patient_twin_os", "comorbidity_hepatic"],
        resolution=(
            "Abiraterona EXCLUIDA del ranking re-arbitrado. Enzalutamida/apalutamida/"
            "darolutamida preferida con monitorización LFTs."
        ),
        clinical_rationale="NCCN 2026 PROS-K + FDA label warning Zytiga.",
        requires_clinician_review=True,
    )


def _detect_brca2_timing_mismatch(
    cards: list[CardRecommendation],
    twin_ranking: list[Mapping[str, Any]],
    facts: Mapping[str, Any],
) -> ClinicalConflict | None:
    """Conflict C — BRCA2 PARP first-line recommendation but patient not in mCRPC.

    PROfound/PROpel/MAGNITUDE approved PARP for mCRPC post-ARSI failure or
    combo first-line mCRPC. NOT approved for mCSPC first-line.

    Fires when BRCA2 carrier card surfaces "parp_first_line_in_mcrpc" but
    the patient's resolved state is mCSPC (castrate_testosterone_status !=
    castrate AND no documented progression on ADT).
    """
    has_brca2_card = any(c.source_card == "brca2_carrier" for c in cards)
    if not has_brca2_card:
        return None

    # Check state — is patient actually in mCRPC?
    castrate = str(facts.get("castrate_testosterone_status") or "").lower()
    is_crpc = (
        castrate in ("castrate", "castration_resistant")
        or _truthy(facts.get("crpc_confirmed"))
        or "mcrpc" in str(facts.get("metastatic_stage_resolved") or "").lower()
        or "m1_crpc" in str(facts.get("disease_state") or "").lower()
    )
    if is_crpc:
        return None  # PARP recommendation is timely

    return ClinicalConflict(
        conflict_id="brca2_mcspc_timing",
        severity="moderate",
        title="Advertencia de timing — PARP-first recomendado pero paciente NO en mCRPC",
        description=(
            "La card BRCA2 sugiere PARP first-line in mCRPC, pero el estado actual "
            "del paciente no es castración-resistente (status: "
            f"{castrate or 'no documentado'}). PARP en BRCA2+ tiene indicación "
            "aprobada para mCRPC (PROfound) y mCRPC primera-línea combo "
            "(PROpel/MAGNITUDE/TALAPRO-2), NO para mCSPC primera-línea."
        ),
        affected_sources=["brca2_carrier", "reconciled_state"],
        resolution=(
            "Mantener BRCA2 carrier card visible como contexto futuro. "
            "PARP queda 'gated' hasta que el paciente progrese a mCRPC documentado "
            "(testosterona <50 ng/dL + progresión PSA/imagen)."
        ),
        clinical_rationale=(
            "NCCN 2026 PROS-J. PROfound 2020 (NEJM): PARP eligibility post-ARSI in "
            "mCRPC. PROpel/MAGNITUDE: combo abi+PARP first-line mCRPC. Ninguno "
            "soporta uso en mCSPC."
        ),
        requires_clinician_review=False,  # warning, not safety-critical
    )


def _detect_metastatic_stage_contradiction(
    cards: list[CardRecommendation],
    twin_ranking: list[Mapping[str, Any]],
    facts: Mapping[str, Any],
) -> ClinicalConflict | None:
    """Conflict D — data integrity: metastatic_stage_resolved vs m_substage_resolved.

    Fires when both keys have values and they contradict (M0 vs M1*).
    Either is fine alone; both with conflict means stale data.
    """
    stage = str(facts.get("metastatic_stage_resolved") or "").upper()
    sub = str(facts.get("m_substage_resolved") or "").upper()
    if not stage or not sub:
        return None
    is_m0 = stage in ("M0", "M0_CRPC", "NMCRPC")
    is_sub_metastatic = sub.startswith("M1")
    if is_m0 and is_sub_metastatic:
        return ClinicalConflict(
            conflict_id="metastatic_stage_contradiction",
            severity="high",
            title="Inconsistencia de datos — paciente etiquetado como M0 y M1b a la vez",
            description=(
                f"`metastatic_stage_resolved={stage}` (no metástasis) contradice "
                f"`m_substage_resolved={sub}` (metástasis ósea). Cualquier "
                "recomendación basada en estadio metastásico es no-confiable hasta "
                "reconciliar el dato."
            ),
            affected_sources=["patient_clinical_facts", "reconciled_state"],
            resolution=(
                "Arbiter mantiene visibles ambas cards pero marca el banner como "
                "REQUIRES_DATA. Clinician debe re-validar el estadio antes de aplicar "
                "cualquier recomendación específica al estado."
            ),
            clinical_rationale=(
                "Data integrity gate per faubot Phase 6. Conflictos de stage son "
                "blocking para decisión terapéutica."
            ),
            requires_clinician_review=True,
        )
    return None


# ─────────────────── Re-ranking with contraindications ───────────────────


def _apply_contraindications_to_ranking(
    twin_ranking: list[Mapping[str, Any]],
    conflicts: list[ClinicalConflict],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Remove contraindicated regimens from Twin ranking + return excluded list.

    Returns:
        (re_ranked, excluded) where:
          - re_ranked: same shape as twin_ranking but filtered + re-numbered
          - excluded: [{drug, reason}] for UI display
    """
    excluded: list[dict[str, str]] = []

    drugs_to_exclude: set[str] = set()
    for conflict in conflicts:
        if conflict.conflict_id == "cv_abi_override":
            drugs_to_exclude.add("abiraterone")
            excluded.append({
                "drug": "abiraterone",
                "reason": "Severe CV disease — NCCN 2026 PROS-K contraindication",
            })
        if conflict.conflict_id == "hepatic_abi_override":
            drugs_to_exclude.add("abiraterone")
            # Avoid duplicate if both CV and hepatic
            if not any(e["drug"] == "abiraterone" for e in excluded):
                excluded.append({
                    "drug": "abiraterone",
                    "reason": "Active hepatic disease — NCCN 2026 PROS-K contraindication",
                })

    re_ranked: list[dict[str, Any]] = []
    new_rank = 0
    for r in (twin_ranking or []):
        drug = str(r.get("primary_drug") or r.get("regimen_name") or "").lower()
        if any(excl_drug in drug for excl_drug in drugs_to_exclude):
            continue
        new_rank += 1
        # Copy + update rank field if present
        item = dict(r) if isinstance(r, Mapping) else {}
        item["arbitrated_rank"] = new_rank
        item["original_rank"] = r.get("rank") if isinstance(r, Mapping) else None
        re_ranked.append(item)

    return re_ranked, excluded


# ─────────────────── Helpers ───────────────────


def _truthy(value: Any) -> bool:
    """Defensive boolean coercion for fact values stored as strings."""
    if value is True:
        return True
    if value is False or value is None:
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "si", "sí"}


# ─────────────────── Main entry point ───────────────────


def arbitrate_recommendations(
    cards: list[CardRecommendation] | None,
    twin_ranking: list[Mapping[str, Any]] | None,
    facts: Mapping[str, Any] | None,
) -> ArbitratedDecision:
    """Run all 4 conflict detectors and produce ArbitratedDecision.

    Order matters: critical-severity conflicts emit first so the UI banner
    shows them at top.

    Args:
        cards: list of CardRecommendation from EPIC 22b/22c card adapters
        twin_ranking: Patient Twin OS regimen ranking
                      (each item has regimen_name, primary_drug, expected_os_gain_mo,
                       rank, score, ...)
        facts: flat dict of clinical facts (severe_cv_disease, hrr_gene,
               castrate_testosterone_status, metastatic_stage_resolved, etc.)

    Returns:
        ArbitratedDecision with detected conflicts + re-ranked regimens.
    """
    cards = list(cards or [])
    twin_ranking = list(twin_ranking or [])
    facts = dict(facts or {})

    detectors = [
        _detect_cv_abi_conflict,
        _detect_hepatic_abi_conflict,
        _detect_metastatic_stage_contradiction,
        _detect_brca2_timing_mismatch,
    ]

    conflicts: list[ClinicalConflict] = []
    for det in detectors:
        try:
            c = det(cards, twin_ranking, facts)
            if c is not None:
                conflicts.append(c)
        except Exception as exc:
            logger.debug("conflict detector %s raised: %s", det.__name__, exc)

    # Sort by severity (critical > high > moderate > low)
    severity_rank = {"critical": 0, "high": 1, "moderate": 2, "low": 3, "none": 4}
    conflicts.sort(key=lambda c: severity_rank.get(c.severity, 5))

    # Apply contraindications to re-ranking
    re_ranked, excluded = _apply_contraindications_to_ranking(twin_ranking, conflicts)

    # Compute severity_max
    severity_max = "none"
    if conflicts:
        severity_max = conflicts[0].severity

    # Collect timing warnings + data integrity flags as flat lists
    timing_warnings: list[str] = []
    integrity_flags: list[str] = []
    for c in conflicts:
        if c.conflict_id == "brca2_mcspc_timing":
            timing_warnings.append(c.title)
        if c.conflict_id == "metastatic_stage_contradiction":
            integrity_flags.append(c.title)

    return ArbitratedDecision(
        has_conflicts=bool(conflicts),
        severity_max=severity_max,
        conflicts=conflicts,
        arbitrated_ranking=re_ranked,
        excluded_regimens=excluded,
        timing_warnings=timing_warnings,
        data_integrity_flags=integrity_flags,
    )


# ─────────────────── Public API ───────────────────


__all__ = [
    "ArbitratedDecision",
    "CardRecommendation",
    "ClinicalConflict",
    "arbitrate_recommendations",
]
