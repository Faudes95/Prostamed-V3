"""EPIC 19 — Patient Twin OS: True personalized shared decision making.

Orquesta la fusion de:
  1. Preferencias del paciente (goal_of_care, decision_tradeoff)
  2. PROs baseline + longitudinal (EPIC-26, FACT-P, ESAS)
  3. Toxicity tolerance profile (CTCAE thresholds)
  4. AI predictions (4 models: state_transition, treatment_response, deep_surv, anomaly)
  5. Re-decision triggers (umbrales que el paciente eligió)

Output: regimen rankings personalizados + re-decision alerts + readiness score.

Decisión clínica concreta — paciente mCSPC volumen alto:
  Pre-EPIC 19: urólogo presenta 3 opciones genéricas (docetaxel, abiraterona,
    enzalutamide). Paciente decide por intuición o sigue recomendación implícita.
  Post-EPIC 19: Cortana surface ranking personalizado:
    - Abiraterona: 4.5/5 para TU perfil (preserva FACT-P, hepatotox 6%)
    - Docetaxel: 2.8/5 — alerta tolerance mismatch (hematológica G3+ 25% EXCEDE tu umbral)
    - Enzalutamide: 3.9/5 (cognitive G2 18% — no en tu profile previo)

Caveat clínico (honest):
  - Decision SUPPORT, no decision MAKER. El urólogo y paciente deciden juntos.
  - AI predictions vienen de modelos shadow-validated con synthetic data
    (EPIC 16/17). No production-ready para decisiones reales hasta EPIC 20.
  - El scoring usa pesos declarativos del paciente; preserva trazabilidad
    del razonamiento (NO black-box ranking).

Integración:
  - Lee patient_record (formato tracking_db.build_patient_record_derivatives)
  - Lee patient_clinical_facts table para preferences/PROs/toxicity_tolerance
  - Llama PredictionService (prostanet.ai.inference.prediction_service)
  - Retorna dict serializable para UI rendering
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from typing import Any, Mapping

logger = logging.getLogger(__name__)


# ─────────────────── Constants ───────────────────

# Pivotal regimens para mCSPC/mCRPC (subset; expandable)
REGIMEN_CATALOG: dict[int, dict[str, Any]] = {
    1: {
        "regimen_id": 1,
        "regimen_name": "docetaxel",
        "trial_source": "CHAARTED",
        "primary_drug": "docetaxel",
        "typical_aes": {
            "hematologic_g3_plus_pct": 25.0,
            "neuropathy_g2_plus_pct": 18.0,
            "fatigue_g3_plus_pct": 8.0,
            "hepatic_g3_plus_pct": 2.0,
        },
        "expected_os_gain_mo": 13.6,
        "indications": ["mCSPC_high_volume", "mCRPC"],
    },
    2: {
        "regimen_id": 2,
        "regimen_name": "abiraterone",
        "trial_source": "LATITUDE/STAMPEDE",
        "primary_drug": "abiraterone",
        "typical_aes": {
            "hematologic_g3_plus_pct": 4.0,
            "hepatic_g3_plus_pct": 6.0,
            "fatigue_g3_plus_pct": 5.0,
            "cardiovascular_g3_plus_pct": 4.0,
            "hypokalemia_g3_plus_pct": 5.0,
        },
        "expected_os_gain_mo": 16.8,
        "indications": ["mCSPC_high_volume", "mCSPC_low_volume", "mCRPC"],
    },
    3: {
        "regimen_id": 3,
        "regimen_name": "enzalutamide",
        "trial_source": "ARCHES/ENZAMET",
        "primary_drug": "enzalutamide",
        "typical_aes": {
            "fatigue_g3_plus_pct": 6.0,
            "cognitive_g2_plus_pct": 18.0,
            "seizure_g3_plus_pct": 0.4,
            "fall_pct": 12.0,
        },
        "expected_os_gain_mo": 13.0,
        "indications": ["mCSPC_high_volume", "mCSPC_low_volume", "mCRPC"],
    },
    4: {
        "regimen_id": 4,
        "regimen_name": "apalutamide",
        "trial_source": "TITAN/SPARTAN",
        "primary_drug": "apalutamide",
        "typical_aes": {
            "fatigue_g3_plus_pct": 3.0,
            "rash_g3_plus_pct": 6.0,
            "hypothyroid_pct": 8.0,
            "fall_pct": 9.0,
        },
        "expected_os_gain_mo": 14.4,
        "indications": ["mCSPC_high_volume", "mCSPC_low_volume", "M0_CRPC"],
    },
    5: {
        "regimen_id": 5,
        "regimen_name": "darolutamide_docetaxel",
        "trial_source": "ARASENS",
        "primary_drug": "darolutamide",
        "typical_aes": {
            "hematologic_g3_plus_pct": 28.0,
            "fatigue_g3_plus_pct": 5.0,
            "neuropathy_g2_plus_pct": 15.0,
        },
        "expected_os_gain_mo": 19.0,  # Best in class for high-volume mCSPC
        "indications": ["mCSPC_high_volume"],
    },
    # EPIC 25.4 (GodiBot ARBITER-COMPLETENESS-005) — Pembrolizumab for
    # MSI-H/dMMR / Lynch carriers. Pre-EPIC25 the catalog had ZERO
    # immunotherapy entries → Lynch_carrier card surfaced as a pathway
    # but the Twin OS ranking never showed pembro as a real option.
    # KEYNOTE-158 (Lancet Onc 2020) ORR 34.3% tumor-agnostic MSI-H.
    6: {
        "regimen_id": 6,
        "regimen_name": "pembrolizumab",
        "trial_source": "KEYNOTE-158",
        "primary_drug": "pembrolizumab",
        "typical_aes": {
            "immune_related_g3_plus_pct": 18.0,
            "fatigue_g3_plus_pct": 4.0,
            "endocrinopathy_g2_plus_pct": 12.0,
            "colitis_g3_plus_pct": 3.0,
        },
        # EPIC 27.5 (GodiBot G31 HIGH) — KEYNOTE-158 is SINGLE-ARM (no control),
        # so there is no "OS gain vs control" defensible from the data.
        # Marabelle Lancet Oncology 2020 reports median OS 23.5mo in MSI-H
        # non-CRC; the prior 14.0 was a fabricated proxy that biased scoring.
        # Set expected_os_gain_mo=None + flag methodology so score_regimen
        # uses ORR-derived proxy (objective response rate 34.3%) instead.
        "expected_os_gain_mo": None,
        "os_gain_methodology": "single_arm_no_comparator",
        "orr_pct": 34.3,                # KEYNOTE-158 MSI-H non-CRC cohort
        "median_os_responders_mo": 23.5,
        "evidence_citations": ["KEYNOTE-158 Marabelle Lancet Onc 2020 PMID 31682550"],
        "indications": [
            "mcrpc_msi_h_dmmr",
            "lynch_carrier",
            "lynch_advanced",
        ],
    },
    # EPIC 25.5 + 27.5 (GodiBot G31) — Olaparib for HRR+ mCRPC post-ARSI failure.
    7: {
        "regimen_id": 7,
        "regimen_name": "olaparib",
        "trial_source": "PROfound",
        "primary_drug": "olaparib",
        "typical_aes": {
            "anemia_g3_plus_pct": 22.0,
            "nausea_g2_plus_pct": 30.0,
            "fatigue_g3_plus_pct": 4.0,
            "thrombocytopenia_g3_plus_pct": 8.0,
        },
        # EPIC 27.5 (GodiBot G31 HIGH) — corrected from fabricated 6.0 to actual
        # mature OS data from PROfound update (Hussain NEJM 2020 update):
        # median OS olaparib 19.1mo vs control 14.4mo in cohort A (BRCA1/2/ATM)
        # = absolute gain ~4.7mo. HR=0.69 (95% CI 0.50-0.97).
        # rPFS HR=0.34 was the original primary endpoint but inappropriate for
        # OS ranking scoring.
        "expected_os_gain_mo": 4.7,
        "expected_rpfs_hr": 0.34,
        "expected_os_hr": 0.69,
        # EPIC 28.5 (GodiBot G43 HIGH) — corrected PMID. Pre-EPIC28 the
        # second citation used PMID 33571915 which does NOT correspond to
        # PROfound OS update. Only verifiable PROfound citation in
        # CLINICAL_EVIDENCE_2026.md whitelist is Hussain NEJM 2020 (PMID
        # 32343890) — primary publication with rPFS primary endpoint AND
        # interim OS data (cohort A: 18.5 vs 15.1 mo). The 4.7mo OS gain
        # figure derives from Hussain ASCO 2020 (oral abstract LBA5004)
        # and ESMO 2020 mature OS update — both are congress presentations
        # without independent PMIDs. Citing only the validated PMID.
        "evidence_citations": [
            "PROfound primary publication — Hussain NEJM 2020 PMID 32343890",
            "PROfound mature OS — Hussain ASCO 2020 LBA5004 / ESMO 2020 (congress)",
        ],
        "indications": [
            "mcrpc_hrr_positive_parp_naive",
            "brca2_carrier_mcrpc",
            "brca1_carrier_mcrpc",
            "atm_carrier_mcrpc",
        ],
    },
}

# Toxicity tolerance vocabulary
TOLERANCE_LEVELS = {"intolerable": -3.0, "low": -1.5, "tolerable": 0.0, "acceptable": +1.0}

# Default preferences si paciente no completó capture
DEFAULT_PREFERENCES = {
    "goal_of_care": "balanced",
    "decision_tradeoff": {"os_weight": 0.5, "qol_weight": 0.5},
    "toxicity_tolerance": {},
    "redecision_threshold": {"fact_p_drop_pts": 3, "karnofsky_drop_pts": 10},
    "baseline_pro": {},
}


# ─────────────────── Data classes ───────────────────


@dataclass
class PatientPreferenceProfile:
    """Captures patient's stated preferences for shared decision making."""
    goal_of_care: str = "balanced"  # max_os | max_qol | balanced
    os_weight: float = 0.5
    qol_weight: float = 0.5
    toxicity_tolerance: dict[str, str] = field(default_factory=dict)
    redecision_threshold: dict[str, float] = field(default_factory=dict)
    baseline_pro: dict[str, float] = field(default_factory=dict)
    capture_completeness_pct: float = 0.0  # 0-100, how much preference data we have

    def is_minimally_captured(self) -> bool:
        """True si tenemos suficiente info para personalizar el ranking."""
        return self.capture_completeness_pct >= 30.0


@dataclass
class RegimenScore:
    """Personalized score for a single regimen."""
    regimen_id: int
    regimen_name: str
    score: float  # 0-10 scale
    predicted_os_gain_mo: float
    toxicity_warnings: list[str] = field(default_factory=list)
    tolerance_mismatches: list[str] = field(default_factory=list)
    rationale: str = ""
    trial_source: str = ""
    indications_match: bool = True


@dataclass
class RedecisionAlert:
    """Triggered when patient's longitudinal data crosses a self-set threshold."""
    threshold_name: str
    observed_value: float
    threshold_value: float
    severity: str  # info | warning | critical
    message: str


@dataclass
class PatientTwinView:
    """Complete twin view for UI rendering."""
    available: bool
    preferences: PatientPreferenceProfile
    regimen_rankings: list[RegimenScore] = field(default_factory=list)
    redecision_alerts: list[RedecisionAlert] = field(default_factory=list)
    ai_substrate_status: dict[str, bool] = field(default_factory=dict)
    readiness_pct: float = 0.0  # 0-100
    rationale_summary: str = ""
    caveats: list[str] = field(default_factory=list)


# ─────────────────── Preference extraction ───────────────────


def extract_preferences(patient_record: Mapping[str, Any]) -> PatientPreferenceProfile:
    """Read patient_clinical_facts + baseline PROs to build preference profile.

    Patient record may have:
      - clinical_facts (list): individual fact records with keys/values
      - baseline (dict): screening/intake data
      - patient_values (dict): direct preference capture
    """
    profile = PatientPreferenceProfile()
    facts = patient_record.get("clinical_facts") or patient_record.get("patient_clinical_facts") or []
    baseline = patient_record.get("baseline") or {}
    explicit_values = patient_record.get("patient_values") or {}

    captured_count = 0
    total_dimensions = 5  # patient_values + tradeoff + toxicity + redecision + PRO

    # 1. Goal of care + tradeoff (try multiple sources)
    goal = (
        explicit_values.get("goal_of_care")
        or baseline.get("goal_of_care")
        or _find_fact(facts, "goal_of_care")
    )
    if goal:
        profile.goal_of_care = str(goal).lower()
        captured_count += 1

    # 2. Decision tradeoff weights (os_weight / qol_weight)
    tradeoff = (
        explicit_values.get("decision_tradeoff")
        or baseline.get("decision_tradeoff")
        or _find_fact(facts, "decision_tradeoff")
        or {}
    )
    if isinstance(tradeoff, dict) and tradeoff:
        profile.os_weight = float(tradeoff.get("os_weight") or 0.5)
        profile.qol_weight = float(tradeoff.get("qol_weight") or 0.5)
        # Normalize to sum 1.0
        total = profile.os_weight + profile.qol_weight
        if total > 0:
            profile.os_weight /= total
            profile.qol_weight /= total
        captured_count += 1
    else:
        # Infer from goal_of_care
        if profile.goal_of_care == "max_os":
            profile.os_weight = 0.75
            profile.qol_weight = 0.25
        elif profile.goal_of_care == "max_qol":
            profile.os_weight = 0.25
            profile.qol_weight = 0.75
        # balanced → keep 0.5/0.5 default

    # 3. Toxicity tolerance dict
    tolerance = (
        explicit_values.get("toxicity_tolerance")
        or _find_fact(facts, "toxicity_tolerance")
        or {}
    )
    if isinstance(tolerance, dict) and tolerance:
        profile.toxicity_tolerance = dict(tolerance)
        captured_count += 1

    # 4. Re-decision threshold
    redecision = (
        explicit_values.get("redecision_threshold")
        or _find_fact(facts, "redecision_threshold")
        or {}
    )
    if isinstance(redecision, dict) and redecision:
        profile.redecision_threshold = dict(redecision)
        captured_count += 1
    else:
        profile.redecision_threshold = dict(DEFAULT_PREFERENCES["redecision_threshold"])

    # 5. Baseline PROs (EPIC-26, FACT-P, ESAS)
    pros = (
        explicit_values.get("baseline_pro")
        or _find_fact(facts, "baseline_pro")
        or {}
    )
    if not pros:
        # Try direct fields in baseline
        pros = {
            k: v for k, v in (baseline or {}).items()
            if k in ("fact_p", "epic26_urinary", "epic26_bowel", "epic26_sexual", "esas_pain")
            and v is not None
        }
    if pros:
        profile.baseline_pro = {k: float(v) for k, v in pros.items() if isinstance(v, (int, float, str)) and str(v).replace('.', '').isdigit()}
        captured_count += 1

    profile.capture_completeness_pct = round(captured_count / total_dimensions * 100.0, 1)
    return profile


def _find_fact(facts: list[Mapping[str, Any]], key: str) -> Any:
    """Scan clinical_facts list for a fact whose key matches.

    EPIC 23.fix — bug discovered 2026-05-13: this function was looking for
    `key`/`field`/`name` attributes but the canonical fact rows from
    `patient_clinical_facts` use `fact_key` (column name from tracking_db).
    Result: Twin OS was reading None for ALL preferences and silently
    falling back to defaults (0.5/0.5) — preferences capture was visually
    persisting but never affecting the ranking.

    Also: if multiple active rows exist for the same fact_key (regression
    from EPIC 22e.2 dedup miss), return the value from the MOST RECENT
    row by source_date / observed_at — not the first scan match.

    Also: parse JSON string values into dicts when the value_type is
    a dict (decision_tradeoff, toxicity_tolerance, redecision_threshold,
    baseline_pro).
    """
    import json as _json
    matches: list[Mapping[str, Any]] = []
    for fact in facts or []:
        if not isinstance(fact, Mapping):
            continue
        # EPIC 23.fix: check ALL the alias keys (canonical + legacy)
        fkey = str(
            fact.get("fact_key")
            or fact.get("key")
            or fact.get("field")
            or fact.get("name")
            or ""
        ).lower()
        if fkey == key.lower():
            matches.append(fact)
    if not matches:
        return None
    # EPIC 23.fix bug C — `is_active` filtering. Pre-fix, _find_fact picked
    # the most recent by observed_at regardless of is_active state. After
    # /api/patient/<nss>/preferences was called multiple times, older
    # inactive rows with newer observed_at dates could shadow the actual
    # active row, so the Twin OS kept reading stale preferences.
    # Fix: prefer is_active=True rows first; only fall back to the full
    # match set if NO active row exists (defensive for legacy data).
    active_matches = [f for f in matches if f.get("is_active") in (True, 1, "1")]
    if active_matches:
        matches = active_matches
    # Pick the most recent by id (monotonic, more reliable than dates)
    # falling back to observed_at then source_date.
    def _sort_key(f: Mapping[str, Any]) -> tuple:
        return (
            int(f.get("id") or 0),
            str(f.get("observed_at") or f.get("source_date") or ""),
        )
    matches.sort(key=_sort_key, reverse=True)
    latest = matches[0]
    raw = (
        latest.get("value")
        if latest.get("value") is not None
        else (
            latest.get("normalized_value_text")
            or latest.get("data")
            or latest.get("payload")
        )
    )
    # If it's a JSON string representing a dict, parse it
    if isinstance(raw, str) and raw.strip().startswith("{"):
        try:
            return _json.loads(raw)
        except Exception:
            return raw
    return raw


# ─────────────────── Regimen scoring ───────────────────


def score_regimen(
    regimen: Mapping[str, Any],
    preferences: PatientPreferenceProfile,
    ai_predictions: Mapping[str, Any] | None = None,
    patient_state: str | None = None,
) -> RegimenScore:
    """Compute personalized 0-10 score for one regimen given patient profile.

    Algoritmo transparente:
      base_score = 5.0
      + os_component: weighted by patient.os_weight, scaled to expected_os_gain_mo
      + qol_component: weighted by patient.qol_weight, penalty for AE rates
      - tolerance_penalty: por cada mismatch entre AE rate y patient.tolerance
      - indication_mismatch: -3.0 si patient_state NO está en indications
    """
    base = 5.0

    expected_os = regimen.get("expected_os_gain_mo")
    aes = dict(regimen.get("typical_aes") or {})
    indications = list(regimen.get("indications") or [])

    # EPIC 27.5 (GodiBot G31 HIGH) — handle pembrolizumab single-arm case.
    # When `os_gain_methodology="single_arm_no_comparator"` (KEYNOTE-158),
    # there is no defensible OS gain vs control. Use ORR proxy normalized
    # to 50% (top of typical durable response) as quality signal instead.
    if expected_os is None:
        methodology = str(regimen.get("os_gain_methodology") or "").lower()
        if methodology == "single_arm_no_comparator":
            orr = float(regimen.get("orr_pct") or 0.0)
            # ORR-derived proxy: 50% durable ORR = full os_component contribution
            os_component = min(3.0, (orr / 50.0) * 3.0) * preferences.os_weight * 2.0
        else:
            os_component = 0.0
    else:
        # OS component (max 0-3 contribution, scaled by os_weight).
        # Normalize expected_os against 20mo (top of mCSPC range)
        expected_os = float(expected_os)
        os_component = min(3.0, (expected_os / 20.0) * 3.0) * preferences.os_weight * 2.0

    # QoL component (3 - sum of AE penalties), scaled by qol_weight
    ae_penalty = 0.0
    warnings: list[str] = []
    mismatches: list[str] = []
    for ae_key, ae_pct in aes.items():
        # Map AE key → category for tolerance lookup
        category = _ae_category(ae_key)
        if not category:
            continue
        tol = preferences.toxicity_tolerance.get(category)
        if tol:
            tol_level = TOLERANCE_LEVELS.get(str(tol).lower(), 0.0)
            # If patient declared "intolerable" and rate ≥ 10% → strong mismatch
            if tol_level <= -1.5 and ae_pct >= 10.0:
                mismatches.append(
                    f"{category} G3+ {ae_pct:.0f}% exceeds your declared tolerance ({tol})"
                )
                ae_penalty += 2.5
            elif tol_level <= -1.5 and ae_pct >= 5.0:
                warnings.append(
                    f"{category} G3+ {ae_pct:.0f}% — review against your tolerance ({tol})"
                )
                ae_penalty += 1.0
        else:
            # No tolerance declared — generic penalty for high-rate AEs
            if ae_pct >= 20.0:
                warnings.append(f"{category} G3+ {ae_pct:.0f}% (no patient tolerance declared)")
                ae_penalty += 0.5

    qol_component = max(0.0, 3.0 - ae_penalty) * preferences.qol_weight * 2.0

    # Indication match
    indication_penalty = 0.0
    indication_match = True
    if patient_state and indications:
        if not any(_state_matches_indication(patient_state, ind) for ind in indications):
            indication_penalty = 4.0
            indication_match = False
            warnings.append(f"Regimen typically for {indications}; patient state {patient_state}")

    # AI prediction boost (if treatment_response available for this regimen)
    ai_boost = 0.0
    if ai_predictions:
        tr = ai_predictions.get("treatment_response") or {}
        if isinstance(tr, dict):
            psa50 = float(tr.get("psa50") or tr.get("predicted_psa50") or 0.0)
            # 0.0-1.0 prob → +/-0.5 to score
            if psa50 > 0.6:
                ai_boost = 0.5
            elif psa50 < 0.3:
                ai_boost = -0.5

    # EPIC 19: tolerance_mismatch es señal fuerte — overrides positive contributions.
    # Cada mismatch declarado por el paciente como "intolerable" debe reducir score
    # de forma decisiva (no solo penalizar QoL component).
    mismatch_penalty = len(mismatches) * 2.5

    score = max(
        0.0,
        min(10.0, base + os_component + qol_component + ai_boost - indication_penalty - mismatch_penalty),
    )

    rationale = (
        f"Base 5.0 + OS contrib {os_component:.1f} (your os_weight {preferences.os_weight:.2f}) "
        f"+ QoL contrib {qol_component:.1f} (your qol_weight {preferences.qol_weight:.2f}) "
        f"+ AI boost {ai_boost:+.1f} - indication penalty {indication_penalty:.1f} "
        f"- tolerance mismatch penalty {mismatch_penalty:.1f}"
    )

    return RegimenScore(
        regimen_id=int(regimen.get("regimen_id") or 0),
        regimen_name=str(regimen.get("regimen_name") or "unknown"),
        score=round(score, 2),
        predicted_os_gain_mo=expected_os,
        toxicity_warnings=warnings,
        tolerance_mismatches=mismatches,
        rationale=rationale,
        trial_source=str(regimen.get("trial_source") or ""),
        indications_match=indication_match,
    )


def _ae_category(ae_key: str) -> str | None:
    """Map AE key (hematologic_g3_plus_pct) → tolerance category (hematologic_g3)."""
    if not ae_key:
        return None
    key = ae_key.lower()
    if "hematologic" in key:
        return "hematologic_g3"
    if "hepatic" in key:
        return "hepatic_g3"
    if "cardio" in key:
        return "cardiovascular_g3"
    if "neuro" in key:
        return "neuropathy_g2"
    if "cognitive" in key:
        return "cognitive_g2"
    if "fatigue" in key:
        return "fatigue_g3"
    if "rash" in key or "cutaneous" in key or "skin" in key:
        return "cutaneous_g3"
    if "fall" in key:
        return "falls"
    if "seizure" in key:
        return "seizure"
    if "hypothyroid" in key or "endocrine" in key:
        return "endocrine_g2"
    if "hypokalemia" in key:
        return "hypokalemia_g3"
    return None


def _state_matches_indication(state: str, indication: str) -> bool:
    """State ↔ indication matcher.

    EPIC 26.6 (GodiBot _state_matches_indication-LOW) — pre-EPIC26 the matcher
    used `i in s` which produced false positives (e.g., indication="mcspc"
    would match state="post_mcspc_relapse"). Worse: the split-on-sync/metach
    was ambiguous when both tokens were absent — `"mCSPC_high_volume".split("sync")[0]`
    returns the entire string, and the prefix check would over-match.

    Fix: normalize both sides (lowercase, strip _-), build a set of canonical
    families (mcspc/mcrpc/m0crpc/localized/bcr), and require either:
      - exact normalized equality, OR
      - family-level match (indication family ∈ state families) AND volume
        bucket compatible (high/low/visceral/oligo).

    Returns True only when the indication family + sub-classifier match.
    """
    if not state or not indication:
        return False
    s_norm = state.lower().replace("_", "").replace("-", "")
    i_norm = indication.lower().replace("_", "").replace("-", "")
    if s_norm == i_norm:
        return True
    # Tokenize both into family. Use a canonical map so synonyms collapse
    # (m1crpc, mcrpc, nmcrpc all → "mcrpc" family).
    family_aliases = {
        # mCSPC family
        "mcspc": "mcspc",
        # mCRPC family — m1crpc and nmcrpc both belong here
        "mcrpc": "mcrpc",
        "m1crpc": "mcrpc",
        "nmcrpc": "mcrpc",
        # m0crpc stays distinct (different therapeutic algorithm)
        "m0crpc": "m0crpc",
        # Localized
        "localized": "localized",
        "bcr": "bcr",
        "postprostatectomy": "postprostatectomy",
        "postrt": "postrt",
        "diagnosticworkup": "diagnosticworkup",
        # Hereditary carriers — each is its own family
        "lynch": "lynch",
        "brca1": "brca1",
        "brca2": "brca2",
        "atm": "atm",
        "hoxb13": "hoxb13",
    }
    # EPIC 28.4 (GodiBot G42 HIGH) — multi-family resolution.
    # Pre-fix: `_family_of` returned the FIRST matching token in iteration
    # order. For indication `brca2_carrier_mcrpc` (contains "brca2" AND
    # "mcrpc") `_family_of` returned whichever was first in family_aliases
    # dict insertion order. For state `brca2_carrier` (no stage suffix)
    # `_family_of` returned "brca2". Mismatch → PARP didn't rank for
    # BRCA2 carrier whose state lacked a stage suffix. Fix: collect ALL
    # families and require non-empty set intersection.
    def _families_of(norm: str) -> set[str]:
        return {canonical for tok, canonical in family_aliases.items() if tok in norm}
    s_families = _families_of(s_norm)
    i_families = _families_of(i_norm)
    if not s_families or not i_families:
        return False
    # EPIC 28.4 (GodiBot G42 refined) — carrier-aware family intersection.
    # When indication declares BOTH a carrier family AND a stage family
    # (e.g., "brca2_carrier_mcrpc"), the state must contain the CARRIER
    # family — having only the stage family alone is not sufficient (a
    # generic mcrpc state without carrier context shouldn't match a
    # carrier-specific indication). Without this, m1_crpc state matched
    # brca2_carrier_mcrpc indication via the shared "mcrpc" family alone.
    carrier_families = {"brca1", "brca2", "atm", "hoxb13", "lynch"}
    i_carrier_families = i_families & carrier_families
    if i_carrier_families:
        s_carrier_families = s_families & carrier_families
        # When indication is carrier-specific, state must share the carrier family
        if not (s_carrier_families & i_carrier_families):
            return False
    else:
        # No carrier in indication — require any family intersection
        if not (s_families & i_families):
            return False
    # Both in same family — check sub-signals (volume/sync/etc)
    # EPIC 27.6 + 28.4 (GodiBot G32 + G42) — stage tokens REMOVED from volume_tokens.
    # Originally G32 added "mcrpc"/"mcspc"/"m0crpc" to discriminate indications
    # like "brca2_carrier_mcrpc". But these tokens also match family aliases →
    # produced false positive when both state AND indication shared the same
    # stage substring as both family AND volume signal (e.g.,
    # "mcspc_low_volume" vs "mcspc_high_volume" both matched "mcspc" as
    # subsignal → True wrong). G42 fixed the brca2 case via the
    # carrier-bare-state special-case below — so we can keep volume_tokens
    # focused on TRUE volume/intent discriminators only.
    volume_tokens = ("highvolume", "lowvolume", "visceral", "oligo", "synchronous",
                     "metachronous", "arsifirst", "post arsi", "postarsi",
                     "hrr", "msi", "psma", "naive",
                     "parpnaive", "postparp", "localized")
    # EPIC 28.4 (GodiBot G42 refined v2) — bifurcate sub-signals into two tiers:
    # STRICT (volume/intent, must match) and BIOMARKER (msi/hrr/psma/parp,
    # checked separately by biomarker-specific detectors).
    strict_subsignals = ("highvolume", "lowvolume", "visceral", "oligo",
                         "synchronous", "metachronous", "localized")
    biomarker_subsignals = ("hrr", "msi", "psma", "naive",
                            "parpnaive", "postparp", "arsifirst", "post arsi", "postarsi")
    i_strict = {t for t in strict_subsignals if t in i_norm}
    s_strict = {t for t in strict_subsignals if t in s_norm}
    # Carrier special case (bare carrier state, no stage suffix)
    carrier_families_set = {"brca1", "brca2", "atm", "hoxb13", "lynch"}
    s_is_bare_carrier = bool(s_families & carrier_families_set) and not s_strict
    if s_is_bare_carrier and (s_families & i_families & carrier_families_set):
        return True
    # If indication has STRICT sub-signals, state must share at least one.
    # If indication has only biomarker sub-signals (or none), family match
    # is sufficient — biomarker-specific arbiter detectors validate
    # eligibility downstream.
    if not i_strict:
        return True
    return bool(i_strict & s_strict)


# ─────────────────── Re-decision alerts ───────────────────


def detect_redecision_alerts(
    patient_record: Mapping[str, Any],
    preferences: PatientPreferenceProfile,
) -> list[RedecisionAlert]:
    """Compare current PROs vs patient-set thresholds.

    Triggers:
      - fact_p_drop_pts: actual FACT-P drop vs baseline > threshold
      - karnofsky_drop_pts: Karnofsky drop > threshold
      - psa_doubling: PSA doubled in < threshold months
    """
    alerts: list[RedecisionAlert] = []
    follow_ups = patient_record.get("follow_ups") or []
    if not follow_ups:
        return alerts

    latest = follow_ups[-1] if follow_ups else {}
    baseline_pro = preferences.baseline_pro

    # FACT-P drop
    fact_p_threshold = preferences.redecision_threshold.get("fact_p_drop_pts")
    if fact_p_threshold and "fact_p" in baseline_pro:
        current_fact_p = latest.get("fact_p")
        if current_fact_p is not None:
            drop = baseline_pro["fact_p"] - float(current_fact_p)
            if drop > fact_p_threshold:
                alerts.append(RedecisionAlert(
                    threshold_name="fact_p_drop",
                    observed_value=round(drop, 1),
                    threshold_value=fact_p_threshold,
                    severity="warning",
                    message=(
                        f"FACT-P dropped {drop:.1f} pts vs baseline (your threshold: {fact_p_threshold} pts). "
                        f"Consider re-discussing treatment goals."
                    ),
                ))

    # Karnofsky drop
    karnofsky_threshold = preferences.redecision_threshold.get("karnofsky_drop_pts")
    if karnofsky_threshold:
        baseline_karnofsky = (patient_record.get("baseline") or {}).get("karnofsky")
        current_karnofsky = latest.get("karnofsky") or latest.get("functional_status")
        if baseline_karnofsky and current_karnofsky:
            drop = float(baseline_karnofsky) - float(current_karnofsky)
            if drop > karnofsky_threshold:
                alerts.append(RedecisionAlert(
                    threshold_name="karnofsky_drop",
                    observed_value=round(drop, 1),
                    threshold_value=karnofsky_threshold,
                    severity="critical" if drop > 20 else "warning",
                    message=(
                        f"Karnofsky dropped {drop:.0f} pts (your threshold: {karnofsky_threshold}). "
                        f"Goal-of-care re-discussion strongly recommended."
                    ),
                ))

    return alerts


# ─────────────────── Main entry point ───────────────────


def build_patient_twin_view(
    patient_record: Mapping[str, Any],
    *,
    prediction_service: Any | None = None,
    model_registry: Any | None = None,
) -> dict[str, Any]:
    """Main entry point — build complete Patient Twin OS view.

    Args:
        patient_record: tracking_db.build_patient_record_derivatives output
        prediction_service: optional pre-built PredictionService; if None, lazy-create
        model_registry: optional ModelRegistry instance; passed to prediction_service

    Returns:
        Serializable dict (PatientTwinView.asdict-style) for UI rendering.
    """
    # 1. Extract preferences
    preferences = extract_preferences(patient_record)

    # 2. Determine patient state for indication matching
    patient_state = ""
    latest_assessment = patient_record.get("latest_assessment") or {}
    if isinstance(latest_assessment, dict):
        patient_state = str(latest_assessment.get("reconciled_state") or latest_assessment.get("state") or "")
    if not patient_state:
        baseline = patient_record.get("baseline") or {}
        patient_state = str(baseline.get("clinical_state") or "")

    # 3. AI predictions (graceful if PredictionService unavailable)
    ai_predictions: dict[str, Any] = {}
    ai_substrate_status = {
        "state_transition": False,
        "treatment_response": False,
        "deep_surv": False,
        "anomaly_detector": False,
    }
    try:
        if prediction_service is None:
            from prostanet.ai.inference.prediction_service import PredictionService
            prediction_service = PredictionService(model_registry=model_registry)

        patient_id = int(
            (patient_record.get("identity") or {}).get("id")
            or patient_record.get("id")
            or 0
        )
        if patient_id:
            try:
                st = prediction_service.predict_state_transition(patient_id, dict(patient_record))
                if st:
                    ai_predictions["state_transition"] = st
                    ai_substrate_status["state_transition"] = True
            except Exception as exc:
                logger.debug("State transition prediction failed: %s", exc)
            try:
                tr = prediction_service.predict_treatment_response(patient_id, dict(patient_record))
                if tr:
                    ai_predictions["treatment_response"] = tr
                    ai_substrate_status["treatment_response"] = True
            except Exception as exc:
                logger.debug("Treatment response prediction failed: %s", exc)
    except Exception as exc:
        logger.debug("PredictionService unavailable: %s", exc)

    # 4. Score each regimen
    rankings: list[RegimenScore] = []
    for regimen in REGIMEN_CATALOG.values():
        score = score_regimen(
            regimen=regimen,
            preferences=preferences,
            ai_predictions=ai_predictions,
            patient_state=patient_state,
        )
        rankings.append(score)
    # Sort descending by score
    rankings.sort(key=lambda r: r.score, reverse=True)

    # 5. Detect re-decision alerts
    alerts = detect_redecision_alerts(patient_record, preferences)

    # 6. Compute overall readiness percentage
    readiness = _compute_readiness(preferences, ai_substrate_status, alerts)

    # 7. Rationale + caveats
    rationale = _build_rationale(preferences, rankings[:3], alerts)
    caveats = _build_caveats(preferences, ai_substrate_status)

    twin = PatientTwinView(
        available=True,
        preferences=preferences,
        regimen_rankings=rankings,
        redecision_alerts=alerts,
        ai_substrate_status=ai_substrate_status,
        readiness_pct=readiness,
        rationale_summary=rationale,
        caveats=caveats,
    )
    return _twin_to_dict(twin)


def _compute_readiness(
    preferences: PatientPreferenceProfile,
    ai_substrate_status: Mapping[str, bool],
    alerts: list[RedecisionAlert],
) -> float:
    """0-100 readiness score combining preference capture + AI substrate + alerts."""
    # Preferences component (0-60)
    prefs_pct = preferences.capture_completeness_pct * 0.6
    # AI substrate component (0-30)
    ai_pct = (sum(1 for v in ai_substrate_status.values() if v) / max(1, len(ai_substrate_status))) * 30
    # Alerts contribution: NOT penalty per se (alerts are valuable), but presence
    # indicates re-decision in progress → reduce 0-10 if critical alert active
    critical_alerts = [a for a in alerts if a.severity == "critical"]
    alert_pct = 10.0 - min(10.0, len(critical_alerts) * 5.0)
    return round(min(100.0, prefs_pct + ai_pct + alert_pct), 1)


def _build_rationale(
    preferences: PatientPreferenceProfile,
    top_regimens: list[RegimenScore],
    alerts: list[RedecisionAlert],
) -> str:
    parts: list[str] = []
    if not top_regimens:
        return "Patient Twin OS: insufficient data for personalized ranking."
    if not preferences.is_minimally_captured():
        parts.append(
            f"Generic ranking (preference capture {preferences.capture_completeness_pct:.0f}% — "
            f"complete patient_values/tradeoff/tolerance for full personalization)."
        )
    else:
        parts.append(
            f"Personalized ranking based on your goal_of_care='{preferences.goal_of_care}' "
            f"(OS weight {preferences.os_weight:.2f}, QoL weight {preferences.qol_weight:.2f})."
        )
    top = top_regimens[0]
    parts.append(
        f"Top regimen: {top.regimen_name} (score {top.score:.1f}/10, expected OS gain "
        f"{top.predicted_os_gain_mo:.1f}mo from {top.trial_source})."
    )
    if top.tolerance_mismatches:
        parts.append(f"⚠ Tolerance mismatches noted: {len(top.tolerance_mismatches)}")
    if alerts:
        parts.append(f"Re-decision alerts active: {len(alerts)}.")
    return " ".join(parts)


def _build_caveats(
    preferences: PatientPreferenceProfile,
    ai_substrate_status: Mapping[str, bool],
) -> list[str]:
    caveats: list[str] = []
    caveats.append(
        "Shadow validation: AI predictions trained on synthetic data (EPIC 16/17). "
        "Not production-ready for real clinical decisions until EPIC 20 real-data validation."
    )
    if not preferences.is_minimally_captured():
        caveats.append(
            f"Limited preference capture ({preferences.capture_completeness_pct:.0f}%). "
            f"Ranking uses default 0.5/0.5 OS/QoL weights — capture patient_values for full personalization."
        )
    inactive = [k for k, v in ai_substrate_status.items() if not v]
    if inactive:
        caveats.append(f"AI models not delivering predictions for this run: {inactive}.")
    return caveats


def _twin_to_dict(twin: PatientTwinView) -> dict[str, Any]:
    """Serialize dataclass tree to plain dict for JSON/template rendering."""
    return {
        "available": twin.available,
        "preferences": asdict(twin.preferences),
        "regimen_rankings": [asdict(r) for r in twin.regimen_rankings],
        "redecision_alerts": [asdict(a) for a in twin.redecision_alerts],
        "ai_substrate_status": dict(twin.ai_substrate_status),
        "readiness_pct": twin.readiness_pct,
        "rationale_summary": twin.rationale_summary,
        "caveats": twin.caveats,
    }


# ─────────────────── Module marker ───────────────────

# EPIC 19: Existence of this module signals that Patient Twin OS is wired.
# Loop Monitor _patient_twin_readiness_value reads this via context flag.
PATIENT_TWIN_OS_VERSION = "0.1.0"
PATIENT_TWIN_OS_EPIC = 19
