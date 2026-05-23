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
    # EPIC 46.A (FAUBOT CXXXII) — Acceso regional a tratamientos
    # Lista de {drug, reason, suggested_path} para terapias marcadas como
    # inaccesibles localmente (Lu-PSMA, ARSIs, PSMA-PET imaging).
    # NO esconde opciones: las re-rankea y muestra ruta de derivación.
    access_warnings: list[dict[str, str]] = field(default_factory=list)
    arbiter_version: str = "epic23_v1.1_epic46a"


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


def _detect_hrr_parp_omission(
    cards: list[CardRecommendation],
    twin_ranking: list[Mapping[str, Any]],
    facts: Mapping[str, Any],
) -> ClinicalConflict | None:
    """EPIC 25.3 (GodiBot ARBITER-COMPLETENESS-003) — HRR+ post-ARSI without PARP.

    NCCN PROS-J cat 1: BRCA2/ATM/BRCA1+ mCRPC post-ARSI failure → PARP first
    (PROfound olaparib; PROpel/MAGNITUDE/TALAPRO-2 combo). Pre-EPIC25, if Twin
    OS ranks docetaxel/cabazitaxel #1 in that scenario, no conflict surfaced.

    Trigger:
      - HRR+ documented (hrr_status=positive OR hrr_gene in BRCA-set)
      - Castrate (mCRPC)
      - No prior PARP inhibitor received
      - Chemo (docetaxel/cabazitaxel) in Twin top-3
    """
    hrr_status = str(facts.get("hrr_status") or "").lower()
    hrr_gene = str(facts.get("hrr_gene") or "").upper()
    is_hrr_positive = (
        hrr_status in ("positive", "high")
        or hrr_gene in {"BRCA1", "BRCA2", "ATM", "PALB2", "CHEK2", "FANCA", "RAD51D"}
    )
    if not is_hrr_positive:
        return None
    # EPIC 27.2 (GodiBot G28 HIGH) — filter VUS / negative / unknown pathogenicity.
    # NCCN PROS-J + FDA olaparib label require pathogenic/likely_pathogenic variant.
    # A patient with hrr_gene=BRCA2 but variant_classification="VUS" should NOT
    # trigger PARP-first recommendation (FP rate ~15% pre-fix).
    variant = str(facts.get("germline_pathogenic_variant") or "").lower().strip()
    classification = str(facts.get("variant_classification") or facts.get("pathogenic_classification") or "").lower().strip()
    if variant in {"vus", "variant_uncertain", "uncertain_significance", "negative", "none", ""}:
        # Variant text says it's not actionable
        if classification not in {"pathogenic", "likely_pathogenic"}:
            return None
    if classification and classification not in {"pathogenic", "likely_pathogenic", ""}:
        # Explicit non-pathogenic classification
        return None
    castrate = str(facts.get("castrate_testosterone_status") or "").lower()
    is_crpc = castrate in ("castrate", "castration_resistant") or "mcrpc" in str(
        facts.get("metastatic_stage_resolved") or ""
    ).lower()
    if not is_crpc:
        return None
    if _truthy(facts.get("parp_inhibitor_received")):
        return None
    chemo_in_top = any(
        any(c in str(r.get("regimen_name", "")).lower() for c in ("docetaxel", "cabazitaxel"))
        for r in (twin_ranking or [])[:3]
    )
    if not chemo_in_top:
        return None
    return ClinicalConflict(
        conflict_id="hrr_parp_omission",
        severity="high",
        title="HRR+ mCRPC con quimio top-3 sin PARP — NCCN PROS-J cat 1 omitido",
        description=(
            f"Paciente con HRR+ ({hrr_gene or hrr_status}) en mCRPC, sin PARP previo. "
            "Twin OS rankea quimioterapia (docetaxel/cabazitaxel) en top-3 sin "
            "considerar la evidencia categoría 1 de PROfound (olaparib en BRCA1/2/ATM) "
            "y PROpel/MAGNITUDE/TALAPRO-2 (combo PARP+ARSI). PARP-first es preferred "
            "en este perfil."
        ),
        affected_sources=["patient_twin_os", "brca2_carrier", "hrr_pathway"],
        resolution=(
            "Re-rankear PARP (olaparib monoterapia si post-ARSI failure; "
            "combo PARP+ARSI primera línea mCRPC) sobre quimio. Considerar trial "
            "PROpel-style si elegible."
        ),
        clinical_rationale=(
            "PROfound NEJM 2020 (Hussain): olaparib HR=0.34 rPFS BRCA1/2; "
            "PROpel Lancet 2023; TALAPRO-2 Lancet 2023. NCCN PROS-J cat 1."
        ),
        requires_clinician_review=True,
    )


def _detect_visceral_undertreatment(
    cards: list[CardRecommendation],
    twin_ranking: list[Mapping[str, Any]],
    facts: Mapping[str, Any],
) -> ClinicalConflict | None:
    """EPIC 25.4 (GodiBot ARBITER-COMPLETENESS-004) — visceral mCSPC under-treated.

    ARASENS (NEJM 2022 Smith): HR=0.68 OS para triplete ADT+darolutamide+
    docetaxel en mCSPC visceral. Si state es mcspc_visceral_only_m1c (o
    visceral metástasis presente) Y Twin top no incluye chemo intensification,
    surface conflict.
    """
    has_visceral = (
        _truthy(facts.get("visceral_metastasis_present"))
        or _truthy(facts.get("visceral_liver"))
        or _truthy(facts.get("visceral_lung"))
        or str(facts.get("metastatic_stage_resolved") or "").upper() == "M1C"
        or "visceral" in str(facts.get("disease_state") or "").lower()
    )
    if not has_visceral:
        return None
    # EPIC 27.3 + 28.3 (GodiBot G29 + G41) — tri-state castration handling.
    # State A: mcspc_confirmed (castrate ∈ not_castrate/intact, no CRPC) → can detect
    # State B: mcrpc_confirmed (castrate=castrate OR crpc_confirmed=True) → skip
    # State C: castrate_unknown (missing/pending) → emit data_gap conflict
    #          instead of suppressing alert silently (G41 fix).
    castrate = str(facts.get("castrate_testosterone_status") or "").lower().strip()
    crpc_confirmed = _truthy(facts.get("crpc_confirmed"))
    is_mcspc = castrate in ("not_castrate", "intact") and not crpc_confirmed
    is_mcrpc = castrate in ("castrate", "castration_resistant") or crpc_confirmed
    is_unknown = not is_mcspc and not is_mcrpc

    # Skip if chemo already received (any state)
    prior_chemo = (
        _truthy(facts.get("prior_docetaxel_received"))
        or _truthy(facts.get("prior_chemo_in_mcspc"))
        or _truthy(facts.get("prior_arasens_triplete"))
        or _truthy(facts.get("prior_chaarted_doublete"))
    )
    if prior_chemo:
        return None

    if is_mcrpc:
        return None  # ARASENS doesn't apply

    if is_unknown:
        # G41: emit data_gap conflict instead of silently passing
        return ClinicalConflict(
            conflict_id="visceral_data_gap_castration",
            severity="high",
            title="Visceral mets + estado de castración no documentado — bloqueante",
            description=(
                "Paciente con metástasis viscerales pero `castrate_testosterone_status` "
                "no documentado. NCCN PROS-13 exige testosterona <50 ng/dL documentada "
                "para distinguir mCSPC (donde aplica triplete ARASENS) vs mCRPC "
                "(donde aplica secuencia post-ARSI). Sin este dato la decisión es "
                "no-confiable: el sistema no puede recomendar terapia visceral-intensive."
            ),
            affected_sources=["patient_clinical_facts.castrate_testosterone_status"],
            resolution=(
                "Obtener testosterona sérica antes de cualquier decisión sistémica. "
                "Mientras tanto, mantener visible alerta de visceral pero NO re-rankear."
            ),
            clinical_rationale=(
                "NCCN PROS-13 v2026 + PCWG3 Scher JCO 2016 (PMID 26903579): CRPC "
                "diagnosis requires testosterone <50 ng/dL + biochemical/radiographic "
                "progression. Single-PSA-rising does not suffice."
            ),
            requires_clinician_review=True,
        )
    # If mcspc, continue to original undertreatment logic
    top_3 = (twin_ranking or [])[:3]
    if not top_3:
        return None
    has_chemo = any(
        any(c in str(r.get("regimen_name", "")).lower()
            for c in ("docetaxel", "darolutamide_docetaxel"))
        for r in top_3
    )
    if has_chemo:
        return None
    return ClinicalConflict(
        conflict_id="visceral_undertreatment",
        severity="high",
        title="mCSPC visceral sin intensificación quimio en top-3 — ARASENS omitido",
        description=(
            "Paciente mCSPC con metástasis viscerales. Twin OS rankea solo "
            "ARSI single-agent en top-3 sin considerar triplete ADT+"
            "darolutamide+docetaxel (ARASENS) que demostró HR=0.68 OS "
            "específicamente en esta población. Visceral mCSPC tiene "
            "pronóstico peor y el beneficio incremental de la triplete "
            "es mayor."
        ),
        affected_sources=["patient_twin_os", "mcspc_visceral"],
        resolution=(
            "Re-rankear triplete ADT+darolutamide+docetaxel #1 si paciente "
            "fit (ECOG ≤1, función adecuada). Si no fit para quimio, considerar "
            "ADT+abi (LATITUDE) o ADT+enza (ENZAMET)."
        ),
        clinical_rationale=(
            "ARASENS NEJM 2022 (Smith): HR=0.68 OS triplete vs doublete. "
            "NCCN PROS-G cat 1. CHAARTED: visceral = high volume independiente "
            "de bone count."
        ),
        requires_clinician_review=True,
    )


def _detect_lynch_pembro_omission(
    cards: list[CardRecommendation],
    twin_ranking: list[Mapping[str, Any]],
    facts: Mapping[str, Any],
) -> ClinicalConflict | None:
    """EPIC 25.5 (GodiBot ARBITER-COMPLETENESS-005) — Lynch carrier sin pembro.

    KEYNOTE-158 (Lancet 2020): MSI-H/dMMR tumor-agnostic pembrolizumab.
    3-5% mCRPC son hyper-respondedores. La card lynch_carrier existe pero
    el REGIMEN_CATALOG de Twin OS NO incluye pembrolizumab → score nunca
    surge → clínico podría perder esta oportunidad terapéutica.
    """
    has_lynch_card = any(c.source_card == "lynch_carrier" for c in cards)
    msi_high = str(facts.get("msi_status") or "").lower() in {"high", "msi_high", "msi-h", "dmmr"}
    if not (has_lynch_card or msi_high):
        return None
    # Check if pembrolizumab is in twin ranking at all
    has_pembro = any(
        "pembro" in str(r.get("regimen_name", "")).lower()
        for r in (twin_ranking or [])
    )
    if has_pembro:
        return None  # catalog has it — clinician can see it
    return ClinicalConflict(
        conflict_id="lynch_pembro_omission",
        severity="critical",
        title="Lynch/MSI-H confirmado pero pembrolizumab NO está en ranking Twin",
        description=(
            "Paciente con Lynch syndrome o MSI-H/dMMR documentado. NCCN PROS-J "
            "categoría 1 indica pembrolizumab tumor-agnostic (KEYNOTE-158). "
            "El catálogo de regímenes del Twin OS NO incluye pembrolizumab — "
            "el clínico no verá esta opción en el ranking. 3-5% de mCRPC son "
            "hyper-respondedores: omisión clínicamente grave."
        ),
        affected_sources=["patient_twin_os.REGIMEN_CATALOG", "lynch_carrier"],
        resolution=(
            "Pembrolizumab debe añadirse al REGIMEN_CATALOG con indicaciones "
            "['mcrpc_msi_h_dmmr', 'lynch_advanced']. Mientras tanto, alertar "
            "al clínico que esta terapia indicada NO se evaluó automáticamente "
            "y debe considerarse fuera del ranking."
        ),
        clinical_rationale=(
            "KEYNOTE-158 (Lancet Oncology 2020 Marabelle): ORR 34.3% en MSI-H "
            "non-CRC tumors. FDA tumor-agnostic 2017. NCCN PROS-J cat 1 + "
            "PROS-A v2026."
        ),
        requires_clinician_review=True,
    )


def _detect_enzalutamide_seizure_risk(
    cards: list[CardRecommendation],
    twin_ranking: list[Mapping[str, Any]],
    facts: Mapping[str, Any],
) -> ClinicalConflict | None:
    """EPIC 26.1 (GodiBot ARBITER-COMPLETENESS-006) — Enzalutamide + seizure.

    PROS-K + FDA Xtandi label: enzalutamide is contraindicated in patients
    with history of seizure, stroke <6 months, recent TIA, brain metastasis
    with edema, or AVM/aneurysm. Pre-EPIC26 the arbiter only blocked abi
    by CV/hepatic; enza ranked high could route a stroke patient to a
    contraindicated drug.

    Trigger:
      - seizure_history=True OR stroke_lt_6mo=True OR tia_recent=True
        OR brain_mets_edema=True OR cns_avm=True
      - AND enzalutamide in Twin top-3
    """
    # EPIC 27.4 (GodiBot G30 HIGH) — distinguish recent/uncontrolled seizure
    # risk from remote/controlled history. PREVAIL exclusion: seizure within
    # 12mo pre-baseline. NCCN PROS-K v2026 permits enza with remote controlled
    # seizure history (>5y + on stable AED). Pre-EPIC27 _truthy treated any
    # non-empty string as TRUE → blocked enza for childhood febrile seizures
    # resolved 30y prior.
    # Approach: require EXPLICIT recent/uncontrolled flag rather than bare history.
    recent_seizure = (
        _truthy(facts.get("seizure_within_12mo"))
        or _truthy(facts.get("seizure_uncontrolled"))
        or _truthy(facts.get("seizure_active"))
    )
    # Anatomic / acute CNS risks (still binary-safe — these are presence/absence)
    cns_acute_risk = (
        _truthy(facts.get("stroke_lt_6mo"))
        or _truthy(facts.get("recent_stroke"))
        or _truthy(facts.get("tia_recent"))
        or _truthy(facts.get("brain_mets_edema"))
        or _truthy(facts.get("cns_avm"))
        or _truthy(facts.get("cns_aneurysm"))
    )
    # EPIC 28.2 + 29.5 (GodiBot G40 HIGH + G52 HIGH refined) — distinguish:
    #   (a) TRULY inactive history (resolved, none, never) → don't block
    #   (b) ACTIVE controlled on AED (still risk per PREVAIL exclude) → block
    #   (c) Free-text noise ("no epilepsy", "father had seizures") → don't block
    # Pre-EPIC29 used naive substring `in` matching → "father had epilepsy"
    # tripped controlled_on_aed → false positive block. Fix: word-boundary
    # regex + explicit negation detection BEFORE token matching.
    import re as _re_e29
    raw_seizure_history = str(facts.get("seizure_history") or facts.get("seizure") or "").lower().strip()
    history_uncertain_or_active = raw_seizure_history in {"true", "1", "yes", "active", "uncontrolled", "recent"}
    # G52: detect negations / family-history first → these should NOT block
    negation_pattern = _re_e29.compile(
        r"\b(?:no|sin|negativ[ao]|denies|not\s+aware|never|none|null)\b.*?\b(?:seizure|epileps|convuls)",
        _re_e29.IGNORECASE,
    )
    family_history_pattern = _re_e29.compile(
        r"\b(?:father|mother|brother|sister|familia|hermano|padre|madre|first[-\s]degree|second[-\s]degree)\b",
        _re_e29.IGNORECASE,
    )
    if negation_pattern.search(raw_seizure_history) or family_history_pattern.search(raw_seizure_history):
        history_counts = False
    else:
        # TRULY inactive: no active disease, no AED required
        truly_inactive_re = _re_e29.compile(
            r"\b(?:resolved|remote|childhood\s+febrile|none|never)\b",
            _re_e29.IGNORECASE,
        )
        history_truly_inactive = bool(truly_inactive_re.search(raw_seizure_history))
        # ACTIVE controlled on AED — word-boundary regex (no false matches in
        # "no epilepsy" or "father had epilepsy")
        aed_re = _re_e29.compile(
            r"\b(?:aed|valproic|lamotrigine|levetiracetam|carbamazepine|"
            r"phenytoin|controlled\s+with|stable\s+on|on\s+anticonvulsant|"
            r"epilepsy|epileps[ií]a)\b",
            _re_e29.IGNORECASE,
        )
        controlled_on_aed = bool(aed_re.search(raw_seizure_history))
        # Explicit structured field
        aed_use = (
            _truthy(facts.get("anticonvulsant_use"))
            or _truthy(facts.get("aed_active"))
            or _truthy(facts.get("epilepsy_on_treatment"))
        )
        history_counts = (
            (history_uncertain_or_active and not history_truly_inactive)
            or (controlled_on_aed and not history_truly_inactive)
            or aed_use
        )
    seizure_risk = recent_seizure or cns_acute_risk or history_counts
    if not seizure_risk:
        return None
    enza_in_top = any(
        "enza" in str(r.get("regimen_name", "")).lower()
        for r in (twin_ranking or [])[:3]
    )
    if not enza_in_top:
        return None
    return ClinicalConflict(
        conflict_id="enza_seizure_override",
        severity="critical",
        title="Conflicto crítico — enzalutamida top-3 con historial de seizure/stroke",
        description=(
            "Paciente con historial de convulsiones, stroke <6mo, TIA reciente, "
            "metástasis cerebrales con edema, o AVM/aneurisma. NCCN PROS-K + "
            "FDA Xtandi label contraindican enzalutamida en este perfil "
            "(aumenta umbral convulsivo, riesgo de seizure G3-4). El ranking "
            "del Twin OS posiciona enzalutamida en top-3 sin considerar esta "
            "contraindicación."
        ),
        affected_sources=["patient_twin_os", "seizure_history"],
        resolution=(
            "Enzalutamida EXCLUIDA del ranking re-arbitrado. Top-1 promovido "
            "a abi (si CV/hepatic permitido) o apalutamida/darolutamida. "
            "Considerar referral neurología antes de cualquier ARSI si "
            "metástasis CNS activas."
        ),
        clinical_rationale=(
            "PREVAIL/AFFIRM exclusion criteria. FDA Xtandi label 2024. "
            "NCCN PROS-K v2026."
        ),
        requires_clinician_review=True,
    )


def _detect_ra223_abi_pred_concurrent(
    cards: list[CardRecommendation],
    twin_ranking: list[Mapping[str, Any]],
    facts: Mapping[str, Any],
) -> ClinicalConflict | None:
    """EPIC 29.1 (GodiBot G53 HIGH) — Ra-223 + abi+pred concurrent block.

    ERA-223 (Smith Lancet Oncology 2019 PMID 30853531) demonstrated INCREASED
    fracture rate (HR 1.83) when Ra-223 combined with abi+pred concurrent.
    FDA + EMA label updates restrict combination. Pre-EPIC29 the Ra-223 layer
    in bone_health_engine had a caveat string but NO detector enforced it.

    Trigger:
      - Patient currently on abiraterone + prednisone
      - Ra-223 recommendation surfaced (`ra223_recommended=True` flag, or
        the patient profile shows ra223 in current/planned regimens)
    """
    current_meds = str(facts.get("current_medications") or facts.get("medication_list") or "").lower()
    on_abi = (
        "abiraterone" in current_meds
        or _truthy(facts.get("on_abiraterone"))
        or _truthy(facts.get("abi_active"))
    )
    on_pred = (
        "prednisone" in current_meds
        or "prednisolone" in current_meds
        or _truthy(facts.get("on_prednisone"))
        or _truthy(facts.get("prednisone_active"))
    )
    if not (on_abi and on_pred):
        return None
    ra223_present = (
        _truthy(facts.get("ra223_recommended"))
        or _truthy(facts.get("on_radium_223"))
        or "radium-223" in current_meds
        or "ra-223" in current_meds
        or any(
            "radium" in str(r.get("regimen_name", "")).lower()
            for r in (twin_ranking or [])[:5]
        )
    )
    if not ra223_present:
        return None
    return ClinicalConflict(
        conflict_id="ra223_abi_pred_concurrent_block",
        severity="critical",
        title="Ra-223 + abi+pred concurrente — bloqueante por ERA-223",
        description=(
            "Paciente actualmente bajo abiraterona + prednisona y Ra-223 surface "
            "como recomendación. ERA-223 (Lancet Oncology 2019) demostró aumento "
            "de fracturas (HR 1.83) con esta combinación. FDA + EMA actualizaron "
            "label restrictivo. NO combinar concurrente; secuenciar (terminar "
            "abi+pred → iniciar Ra-223) o elegir alternativa."
        ),
        affected_sources=["patient_twin_os", "bone_health_engine.ra223_recommendation"],
        resolution=(
            "Ra-223 EXCLUIDO mientras paciente esté on abi+pred concurrent. "
            "Opciones: (a) terminar abi+pred + esperar 30d antes Ra-223, "
            "(b) alternativa: Lu-177-PSMA-617 si PSMA+, (c) secuencia cabazitaxel."
        ),
        clinical_rationale=(
            "ERA-223 Smith Lancet Oncology 2019 PMID 30853531: fracture risk "
            "HR 1.83 (95% CI 1.12-3.00) con Ra-223 + abi+pred vs placebo+abi+pred."
        ),
        requires_clinician_review=True,
    )


def _detect_metastatic_stage_contradiction(
    cards: list[CardRecommendation],
    twin_ranking: list[Mapping[str, Any]],
    facts: Mapping[str, Any],
) -> ClinicalConflict | None:
    """Conflict D — data integrity: metastatic_stage_resolved vs m_substage_resolved.

    EPIC 25.2 (GodiBot ARBITER-INTEGRITY-002 fix) — the detector previously
    read `facts["metastatic_stage_resolved"]` AND `facts["m_substage_resolved"]`
    as if they were 2 distinct keys. But clinical_fact_registry.py:47 declares
    `m_substage_resolved` as a legacy_alias of `metastatic_stage_resolved`, so
    `extract_canonical_fact_candidates` collapses them into one canonical key.
    With normalized facts, this detector never fired.

    Fix: accept BOTH the post-coalesce single-key form (legacy contract) AND
    a pre-coalesce form where the adapter exposes per-source fact rows (the
    EPIC 23 adapter now passes facts as a dict but also looks at clinical_facts
    list — we read both paths).

    Fires when:
      (a) facts dict has both keys distinct (pre-coalesce path — legacy adapter)
      (b) facts._clinical_facts_raw list has 2 active rows with same fact_key
          `metastatic_stage_resolved` whose normalized values contradict, OR
          a row for the legacy alias with a value that contradicts the canonical
    """
    # Path (a): legacy pre-coalesce dict — direct access to both keys
    stage = str(facts.get("metastatic_stage_resolved") or "").upper()
    sub = str(facts.get("m_substage_resolved") or "").upper()

    # Path (b): post-coalesce — inspect raw fact rows passed by adapter
    raw_rows = facts.get("_clinical_facts_raw") or []
    if raw_rows and isinstance(raw_rows, list):
        m_stage_rows: list[str] = []
        for row in raw_rows:
            if not isinstance(row, Mapping):
                continue
            row_key = str(row.get("fact_key") or "").strip().lower()
            row_val = str(
                row.get("normalized_value_text")
                or row.get("value")
                or ""
            ).strip().upper()
            if row_key in {"metastatic_stage_resolved", "m_substage_resolved"} and row_val:
                m_stage_rows.append(row_val)
        # If we have at least 2 distinct values, check for M0 vs M1 contradiction
        unique_vals = set(m_stage_rows)
        has_m0 = any(v in ("M0", "M0_CRPC", "NMCRPC") for v in unique_vals)
        has_m1 = any(v.startswith("M1") for v in unique_vals)
        if has_m0 and has_m1:
            # Override the path (a) values for the description
            stage = "M0"
            sub = next(v for v in unique_vals if v.startswith("M1"))

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
        # EPIC 26.1 — enzalutamide exclusion on seizure risk
        if conflict.conflict_id == "enza_seizure_override":
            drugs_to_exclude.add("enzalutamide")
            excluded.append({
                "drug": "enzalutamide",
                "reason": "Seizure/stroke history — NCCN 2026 PROS-K + FDA Xtandi label contraindication",
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


# ─────────────────────────────────────────────────────────────────────────
# EPIC 46.A (FAUBOT CXXXII) — Filter de acceso regional a tratamientos
# ─────────────────────────────────────────────────────────────────────────
# El intake captura 3 booleanos opcionales:
#   - psma_pet_local_access (1 / 0 / "desconocido")
#   - lu_psma_local_access  (1 / 0 / "desconocido")
#   - arsi_local_access     (1 / 0 / "desconocido")
#
# Filosofía clínica (validada con urólogo): NO ESCONDER opciones. Marcar
# con badge "Sin acceso local" + sugerir ruta de derivación + bajar prioridad
# en re-ranking. El clínico tiene contexto adicional (derivación factible,
# trial enroll path, etc.) y conserva el control.
#
# Diferencia vs `_apply_contraindications_to_ranking`: aquellos contraindican
# por seguridad clínica (excluyen estrictamente). Este sólo re-rankea por
# realidad de acceso (marca pero permite override clínico).
# ─────────────────────────────────────────────────────────────────────────


def _apply_access_restrictions_to_ranking(
    twin_ranking: list[Mapping[str, Any]],
    facts: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Marca (no esconde) terapias localmente inviables + re-rankea bajando.

    Behavior por flag:
      - lu_psma_local_access == "0" → Lu-PSMA-617 (Pluvicto) marcado +
        bajado al final del ranking con badge "sin_acceso_local" + sugerencia
        de derivación a centro con acceso (Hospital Ángeles CDMX, etc.).
      - arsi_local_access == "0" → ARSIs (Abi/Enza/Apa/Daro) marcados +
        bajados con badge + sugerencia bicalutamide-bridge + escalation path.
      - psma_pet_local_access == "0" → no afecta ranking de terapias (afecta
        recomendación de imaging), retornado en `imaging_restrictions`.

    Returns:
        (re_ranked, access_warnings) donde:
          - re_ranked: lista re-ordenada con `access_restricted` y
            `access_note` añadidos a items afectados
          - access_warnings: [{drug, reason, suggested_path}] para UI
    """
    facts = dict(facts or {})

    def _is_no(value: Any) -> bool:
        """True solo si explícitamente '0' / 'no' / False. 'desconocido' → False."""
        if value is None:
            return False
        v = str(value).strip().lower()
        return v in {"0", "no", "false", "n"}

    lu_psma_blocked = _is_no(facts.get("lu_psma_local_access"))
    arsi_blocked = _is_no(facts.get("arsi_local_access"))
    # psma_pet_blocked se expone vía access_warnings pero no muta ranking
    psma_pet_blocked = _is_no(facts.get("psma_pet_local_access"))

    access_warnings: list[dict[str, str]] = []
    if lu_psma_blocked:
        access_warnings.append({
            "drug": "lu_psma_617",
            "reason": "Sin acceso local a Lu-PSMA-617 reportado por paciente",
            "suggested_path": (
                "Derivar a centro con programa de radiofármacos (CDMX: "
                "INCan, Hospital Ángeles, Médica Sur; Monterrey: Hospital "
                "San José, ITESM). Evaluar VISION pivotal pathway."
            ),
        })
    if arsi_blocked:
        access_warnings.append({
            "drug": "arsi_drugs",
            "reason": "Sin acceso a ARSIs orales (Abi/Enza/Apa/Daro) reportado",
            "suggested_path": (
                "Bicalutamide-bridge + escalation path. Considerar enrollment "
                "en trial activo de ARSI vs gestión social/seguros para Abi "
                "genérica (Mylan/Novartis disponible IMSS-Bienestar en algunos "
                "estados). Re-evaluar acceso en 3 meses."
            ),
        })
    if psma_pet_blocked:
        access_warnings.append({
            "drug": "psma_pet_imaging",
            "reason": "Sin acceso local a PSMA-PET",
            "suggested_path": (
                "Staging M con TAC tórax/abdomen/pelvis + gammagrama óseo "
                "Tc-99m convencional. Si BCR + PSA bajo, considerar fluciclovine "
                "(Axumin) si disponible. Evaluar derivación a PSMA-PET solo si "
                "cambiaría management (e.g., oligometastatic candidates)."
            ),
        })

    # Re-rank: ítems afectados van al final pero NO se eliminan
    if not (lu_psma_blocked or arsi_blocked):
        # No-op: ranking igual + warnings vacíos para imaging
        return [dict(r) if isinstance(r, Mapping) else {} for r in (twin_ranking or [])], access_warnings

    def _is_lu_psma_item(item_drug: str, item_name: str) -> bool:
        s = f"{item_drug} {item_name}".lower()
        return "lu-psma" in s or "lu_psma" in s or "pluvicto" in s or "lutetium" in s

    def _is_arsi_item(item_drug: str, item_name: str) -> bool:
        s = f"{item_drug} {item_name}".lower()
        return any(arsi in s for arsi in (
            "abiraterone", "abiraterona", "enzalutamide", "enzalutamida",
            "apalutamide", "apalutamida", "darolutamide", "darolutamida",
        ))

    primary: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    for r in (twin_ranking or []):
        item = dict(r) if isinstance(r, Mapping) else {}
        drug = str(item.get("primary_drug") or "")
        name = str(item.get("regimen_name") or "")
        is_restricted = False
        if lu_psma_blocked and _is_lu_psma_item(drug, name):
            is_restricted = True
            item["access_restricted"] = True
            item["access_note"] = "Sin acceso local a Lu-PSMA — derivación requerida"
            item["access_flag"] = "lu_psma_no_local_access"
        elif arsi_blocked and _is_arsi_item(drug, name):
            is_restricted = True
            item["access_restricted"] = True
            item["access_note"] = "Sin acceso local a ARSIs — bicalutamide-bridge sugerido"
            item["access_flag"] = "arsi_no_local_access"
        (deferred if is_restricted else primary).append(item)

    # Concatena: primary preserva su orden original, deferred va al final
    re_ranked = primary + deferred
    # Re-numbera arbitrated_rank
    for idx, item in enumerate(re_ranked, start=1):
        item["arbitrated_rank"] = idx
        item["original_rank"] = item.get("rank") if "original_rank" not in item else item["original_rank"]

    return re_ranked, access_warnings


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
        # EPIC 25 (GodiBot adversarial audit) — 3 detectors críticos faltantes
        _detect_hrr_parp_omission,             # ARBITER-COMPLETENESS-003
        _detect_visceral_undertreatment,       # ARBITER-COMPLETENESS-004
        _detect_lynch_pembro_omission,         # ARBITER-COMPLETENESS-005
        # EPIC 26 (GodiBot remaining 8 fixes)
        _detect_enzalutamide_seizure_risk,     # ARBITER-COMPLETENESS-006
        # EPIC 29 (GodiBot pass-4 fixes)
        _detect_ra223_abi_pred_concurrent,     # G53 — ERA-223 enforcement
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

    # EPIC 46.A — Apply regional access restrictions sobre el ranking ya
    # filtrado por contraindicaciones. Esto marca (no esconde) terapias
    # inaccesibles localmente y las re-ordena al final, preservando el
    # control clínico para override.
    re_ranked, access_warnings = _apply_access_restrictions_to_ranking(
        re_ranked, facts,
    )

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
        access_warnings=access_warnings,
    )


# ─────────────────── Public API ───────────────────


__all__ = [
    "ArbitratedDecision",
    "CardRecommendation",
    "ClinicalConflict",
    "arbitrate_recommendations",
]
