# -*- coding: utf-8 -*-
"""
Disease Natural History Tracker — "Historia Natural de la Enfermedad".

Documents and predicts the complete trajectory of prostate cancer from
diagnosis through all clinical states to death, incorporating:

  - Time-based state transitions with observed vs predicted timelines
  - Treatment type × outcome correlation
  - Comorbidity burden (CCI) as transition modifier
  - Ethnicity-based risk modifiers (AAM, Hispanic/Latino, Asian, European)
  - BMI, cardiovascular, metabolic risk stratification
  - Longitudinal PSA kinetics as progression signal
  - Cause-specific vs overall survival modeling

This module answers: "Given everything we know about this patient,
what is the expected remaining disease course?"

Architecture:
  - Pure clinical logic (no PyTorch required) — always available
  - When AI flags are ON, integrates DeepSurv predictions
  - All outputs in Spanish for direct clinical use
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field, asdict
from typing import Any

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# Ethnicity Risk Modifiers
# Source: SEER, CAPSURE, PCa-STAR, PCBaSe
# ══════════════════════════════════════════════════════════════

ETHNICITY_RISK_MODIFIERS: dict[str, dict[str, float]] = {
    "afroamericano": {
        "incidence_rr": 1.73,          # RR vs European
        "mortality_rr": 2.20,
        "gleason_high_risk_rr": 1.45,
        "psa_screening_sensitivity_adj": 0.92,
        "note": "Mayor riesgo de Ca. próstata de alto grado y mortalidad específica",
    },
    "hispano_latino": {
        "incidence_rr": 0.85,
        "mortality_rr": 0.95,
        "gleason_high_risk_rr": 0.90,
        "psa_screening_sensitivity_adj": 1.00,
        "note": "Riesgo ligeramente menor que europeo; acceso a atención puede afectar diagnóstico tardío",
    },
    "asiatico": {
        "incidence_rr": 0.42,
        "mortality_rr": 0.50,
        "gleason_high_risk_rr": 0.75,
        "psa_screening_sensitivity_adj": 1.05,
        "note": "Menor incidencia y mortalidad; menor umbral de PSA recomendado",
    },
    "europeo_caucasico": {
        "incidence_rr": 1.00,
        "mortality_rr": 1.00,
        "gleason_high_risk_rr": 1.00,
        "psa_screening_sensitivity_adj": 1.00,
        "note": "Referencia base para comparación",
    },
    # EPIC 46.A (FAUBOT CXXXII) — Indígena americano (auto-adscrito)
    # Sin datos SEER/PCBaSe robustos; modelado conservadoramente como
    # admixture hispano_latino-base. Flag para validación con cohorte
    # propia (Latin recalibration EPIC H2-H3).
    "indigena_americano": {
        "incidence_rr": 0.82,
        "mortality_rr": 0.98,
        "gleason_high_risk_rr": 0.95,
        "psa_screening_sensitivity_adj": 1.00,
        "note": (
            "Indígena americano auto-adscrito — datos limitados en literatura. "
            "Modelado conservadoramente como variante hispano_latino. "
            "Pendiente recalibración con cohorte propia (EPIC H2-H3)."
        ),
        "data_quality_flag": "model_extrapolated_pending_local_recalibration",
    },
}


# ══════════════════════════════════════════════════════════════
# EPIC 46.A (FAUBOT CXXXII) — Mapping UI → backend ethnicity keys
# ══════════════════════════════════════════════════════════════
# El intake captura `primary_ancestry` con valores UI-friendly
# (mestizo, afro_descendiente, indigena, europeo, asiatico, otro,
# no_declarado). El backend ETHNICITY_RISK_MODIFIERS usa keys
# clínicos derivados de literatura (SEER/PCBaSe). Este mapa hace
# el puente sin romper backwards-compat con el campo `ethnicity`
# legacy que algunos flujos ya escriben.

PRIMARY_ANCESTRY_TO_ETHNICITY_KEY: dict[str, str] = {
    "mestizo": "hispano_latino",
    "afro_descendiente": "afroamericano",
    "indigena": "indigena_americano",
    "europeo": "europeo_caucasico",
    "asiatico": "asiatico",
    "otro": "hispano_latino",       # default conservador para cohorte latina
    "no_declarado": "europeo_caucasico",  # fallback histórico, NO discrimina
}


# Sprint 3 FIX #9 (FAUBOT CXXXIX) — Legacy ethnicity alias normalization.
# patient_demographics.etnia tiene DEFAULT 'hispano' (sin sufijo _latino)
# desde la migración inicial del schema, y la UI legacy también guarda
# 'hispano' / 'caucasico' / 'afro' (cortos). El resolver original solo
# aceptaba keys exactos del ETHNICITY_RISK_MODIFIERS dict, dejando
# 'hispano' sin matching → fallback europeo_caucasico (incorrecto).
# Este mapa normaliza aliases comunes legacy al backend key canónico.
LEGACY_ETHNICITY_ALIAS_NORMALIZER: dict[str, str] = {
    # Hispano/Latino variants
    "hispano": "hispano_latino",
    "latino": "hispano_latino",
    "hispanic": "hispano_latino",
    "hispanic_latino": "hispano_latino",
    "latinoamericano": "hispano_latino",
    "mexicano": "hispano_latino",
    # Afro variants
    "afro": "afroamericano",
    "afroamericano": "afroamericano",
    "africano": "afroamericano",
    "negro": "afroamericano",
    "afrodescendiente": "afroamericano",
    "black": "afroamericano",
    # Europeo/Caucasico variants
    "caucasico": "europeo_caucasico",
    "blanco": "europeo_caucasico",
    "europeo": "europeo_caucasico",
    "white": "europeo_caucasico",
    # Asiatico variants
    "asian": "asiatico",
    "asiatico": "asiatico",
    # Indigena variants
    "indigena": "indigena_americano",
    "indígena": "indigena_americano",
    "indigenous": "indigena_americano",
    "nativo": "indigena_americano",
    "nativo_americano": "indigena_americano",
}


def resolve_ethnicity_key(
    primary_ancestry: str | None = None,
    legacy_ethnicity: str | None = None,
) -> str:
    """Resuelve el ethnicity key canónico de backend desde inputs UI/legacy.

    Precedencia: primary_ancestry (EPIC 46.A) > legacy ethnicity normalizado
    > europeo_caucasico.

    Args:
        primary_ancestry: valor UI del campo `primary_ancestry`
            (mestizo / afro_descendiente / indigena / europeo / asiatico /
             otro / no_declarado)
        legacy_ethnicity: valor legacy de `demographics.ethnicity` /
            `patient_demographics.etnia` / `baseline.ethnicity`. Soporta
            aliases comunes (hispano, latino, afro, caucasico, etc.) vía
            LEGACY_ETHNICITY_ALIAS_NORMALIZER. FIX #9 Sprint 3.

    Returns:
        Backend key válido para ETHNICITY_RISK_MODIFIERS lookup.
    """
    if primary_ancestry:
        key = str(primary_ancestry).strip().lower()
        if key in PRIMARY_ANCESTRY_TO_ETHNICITY_KEY:
            return PRIMARY_ANCESTRY_TO_ETHNICITY_KEY[key]
    if legacy_ethnicity:
        legacy = str(legacy_ethnicity).strip().lower()
        # Match directo en ETHNICITY_RISK_MODIFIERS (exact backend key)
        if legacy in ETHNICITY_RISK_MODIFIERS:
            return legacy
        # FIX #9: Sprint 3 — Normalizar aliases comunes legacy
        if legacy in LEGACY_ETHNICITY_ALIAS_NORMALIZER:
            return LEGACY_ETHNICITY_ALIAS_NORMALIZER[legacy]
    return "europeo_caucasico"


# ══════════════════════════════════════════════════════════════
# Charlson Comorbidity Index transitions modifiers
# Source: Groeben et al., J Urol 2017; Daskivich et al., Cancer 2011
# ══════════════════════════════════════════════════════════════

CCI_TRANSITION_MODIFIER: dict[str, float] = {
    # CCI score → hazard multiplier for OS (relative to CCI=0)
    "0": 1.00,
    "1": 1.22,
    "2": 1.58,
    "3": 2.10,
    "4+": 3.15,
}

CCI_TREATMENT_EXCLUSIONS: dict[str, list[str]] = {
    # CCI ≥3 → avoid certain treatments
    "3+": [
        "radical_prostatectomy",  # High perioperative risk
        "external_beam_rt_hfrt",   # Pelvic toxicity in severe comorbidity
        "docetaxel",               # Cytotoxic — significant toxicity
        "cabazitaxel",
    ],
}


# ══════════════════════════════════════════════════════════════
# Published median survival by state and first-line treatment
# Source: CHAARTED, LATITUDE, TITAN, ARCHES, PROfound, TRITON, VISION
# ══════════════════════════════════════════════════════════════

PUBLISHED_SURVIVAL_MEDIANS: dict[str, dict[str, float]] = {
    "localized_initial": {
        "radical_prostatectomy": 180.0,     # 15-year CSS >90%
        "external_beam_rt": 168.0,
        "active_surveillance": 192.0,       # Low-risk only
        "default": 180.0,
    },
    "recurrence_bcr": {
        "salvage_rt": 84.0,                 # Freedland JCO 2005
        "adt_monotherapy": 60.0,
        "enzalutamide": 78.0,               # EMBARK HR=0.58
        "default": 72.0,
    },
    "mcspc_high_volume_sync": {
        "adt_docetaxel": 57.6,              # CHAARTED: 57.6 mo
        "adt_abiraterone": 53.3,            # LATITUDE: 53.3 mo
        "adt_darolutamide_docetaxel": 62.7, # ARASENS
        "adt_enzalutamide": 67.0,           # ARCHES/ENZAMET OS NR
        "adt_monotherapy": 34.0,            # Historical control
        "default": 51.0,
    },
    "mcspc_low_volume_sync_oligo": {
        "adt_abiraterone": 83.3,
        "adt_enzalutamide": 77.0,
        "adt_rt": 66.0,                     # STAMPEDE RT arm
        "adt_monotherapy": 54.0,
        "default": 72.0,
    },
    "mcspc_oligo_metachronous": {
        "adt_enzalutamide": 84.0,
        "adt_abiraterone": 80.0,
        "sbrt_adt": 90.0,                   # Oligomets MDT
        "default": 78.0,
    },
    "m0_crpc": {
        "enzalutamide": 67.0,               # PROSPER: MFS 36.6 mo
        "apalutamide": 73.9,                # SPARTAN: OS 73.9 mo
        "darolutamide": 71.0,               # ARAMIS: OS HR=0.69
        "default": 44.0,                    # Historical CRPC
    },
    "m1_crpc": {
        "abiraterone": 34.7,                # COU-AA-301
        "enzalutamide": 35.3,               # AFFIRM
        "docetaxel": 18.9,                  # TAX327
        "cabazitaxel": 15.1,                # TROPIC
        "lu177_psma": 15.3,                 # VISION OS
        "olaparib": 19.1,                   # PROfound
        "default": 13.6,
    },
    "post_prostatectomy": {
        "default": 120.0,                   # 10-year OS ~85%
    },
    "diagnostic_workup": {
        "default": 180.0,
    },
}


# ══════════════════════════════════════════════════════════════
# Data Classes
# ══════════════════════════════════════════════════════════════

@dataclass
class TransitionEvent:
    """A single observed or predicted state transition."""
    from_state: str
    to_state: str
    event_date: str
    months_from_diagnosis: float
    driver: str            # "progression" | "treatment_change" | "predicted"
    treatment_at_time: str = ""
    psa_at_time: float = 0.0
    confidence: float = 1.0  # 1.0 for observed, <1 for predicted

    def is_observed(self) -> bool:
        return self.driver != "predicted"


@dataclass
class DiseasePhase:
    """A distinct phase of the disease course."""
    state: str
    start_date: str
    end_date: str | None   # None = current or ongoing
    duration_months: float
    treatment: str
    psa_at_entry: float
    psa_at_exit: float | None
    response: str          # "responding" | "stable" | "progressing" | "unknown"
    phase_label: str       # Human-readable
    risk_level: str        # "low" | "intermediate" | "high" | "very_high"


@dataclass
class NaturalHistoryReport:
    """Complete natural history report for a patient."""
    patient_id: int
    diagnosis_date: str
    current_state: str
    time_since_diagnosis_months: float

    # Historical trajectory
    observed_transitions: list[TransitionEvent]
    disease_phases: list[DiseasePhase]

    # Survival estimates
    expected_os_months: float | None        # From published data for state+treatment
    os_modifier: float                      # Comorbidity + ethnicity combined modifier
    adjusted_os_months: float | None        # expected_os * os_modifier

    # Risk factors summary
    risk_summary: dict[str, Any]
    comorbidity_cci: int | None
    ethnicity: str
    ethnicity_modifier: dict[str, float]

    # Predicted future trajectory
    predicted_next_state: str | None
    predicted_time_to_transition_months: float | None
    transition_confidence: float

    # Treatment response history
    treatment_history: list[dict[str, Any]]
    psa_nadir: float | None
    psa_nadir_date: str | None
    psa_doubling_time_months: float | None

    # Warnings
    flags: list[str]
    narrative: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


# ══════════════════════════════════════════════════════════════
# Main Service
# ══════════════════════════════════════════════════════════════

class NaturalHistoryTracker:
    """
    Analyzes the complete disease natural history for a patient.

    Usage::

        tracker = NaturalHistoryTracker()
        report = tracker.analyze(patient_record)
        report.narrative  # Full Spanish narrative
    """

    def analyze(self, patient: dict[str, Any]) -> NaturalHistoryReport:
        """Build a complete natural history report from a patient record."""
        identity = patient.get("identity", {}) or {}
        baseline = patient.get("baseline", {}) or {}
        follow_ups = patient.get("follow_ups", []) or []
        state_timeline = patient.get("state_timeline", []) or []
        treatments = patient.get("treatments", []) or []

        patient_id = int(identity.get("id", 0))
        diagnosis_date = identity.get("diagnosis_date", "")
        current_state = (
            patient.get("reconciled_state")
            or (patient.get("latest_assessment") or {}).get("state")
            or "diagnostic_workup"
        )

        # ── Time since diagnosis ──
        time_months = self._months_since(diagnosis_date)

        # ── Comorbidity ──
        cci = self._compute_cci(patient)

        # ── Ethnicity (EPIC 46.A: prefiere primary_ancestry sobre legacy) ──
        primary_ancestry = (
            (patient.get("demographics") or {}).get("primary_ancestry")
            or (patient.get("baseline") or {}).get("primary_ancestry")
        )
        legacy_ethnicity = (
            (patient.get("demographics") or {}).get("ethnicity")
            or (patient.get("baseline") or {}).get("ethnicity")
        )
        ethnicity = resolve_ethnicity_key(
            primary_ancestry=primary_ancestry,
            legacy_ethnicity=legacy_ethnicity,
        )
        ethnicity_modifier = ETHNICITY_RISK_MODIFIERS.get(
            ethnicity, ETHNICITY_RISK_MODIFIERS["europeo_caucasico"]
        )

        # ── Build observed transitions ──
        observed_transitions = self._build_transitions(state_timeline, follow_ups, treatments)

        # ── Build disease phases ──
        disease_phases = self._build_phases(state_timeline, treatments, follow_ups)

        # ── PSA kinetics ──
        psa_nadir, psa_nadir_date = self._find_psa_nadir(follow_ups)
        psadt = self._compute_psadt(follow_ups)

        # ── Survival estimate ──
        current_tx = self._get_current_treatment(treatments)
        raw_os = self._lookup_survival_median(current_state, current_tx)

        os_modifier = self._compute_os_modifier(cci, ethnicity_modifier)
        adjusted_os = round(raw_os * os_modifier, 1) if raw_os else None

        # ── Predicted next transition (from AI if available, else rule-based) ──
        pred_next_state, pred_time, pred_conf = self._predict_next_transition(
            patient, current_state, time_months
        )

        # ── Risk summary ──
        risk_summary = self._build_risk_summary(baseline, patient, cci, ethnicity_modifier, psadt)

        # ── Flags ──
        flags = self._build_flags(patient, current_state, psadt, cci, follow_ups)

        # ── Treatment history ──
        tx_history = self._build_treatment_history(treatments, follow_ups)

        # ── Narrative ──
        report = NaturalHistoryReport(
            patient_id=patient_id,
            diagnosis_date=diagnosis_date,
            current_state=current_state,
            time_since_diagnosis_months=round(time_months, 1),
            observed_transitions=observed_transitions,
            disease_phases=disease_phases,
            expected_os_months=raw_os,
            os_modifier=round(os_modifier, 3),
            adjusted_os_months=adjusted_os,
            risk_summary=risk_summary,
            comorbidity_cci=cci,
            ethnicity=ethnicity,
            ethnicity_modifier=ethnicity_modifier,
            predicted_next_state=pred_next_state,
            predicted_time_to_transition_months=pred_time,
            transition_confidence=pred_conf,
            treatment_history=tx_history,
            psa_nadir=psa_nadir,
            psa_nadir_date=psa_nadir_date,
            psa_doubling_time_months=psadt,
            flags=flags,
            narrative="",
        )
        report.narrative = self._build_narrative(report)
        return report

    # ── Internal methods ──

    @staticmethod
    def _months_since(date_str: str | None) -> float:
        if not date_str:
            return 0.0
        try:
            from datetime import date
            d = date.fromisoformat(str(date_str)[:10])
            today = date.today()
            return max(0.0, (today - d).days / 30.44)
        except Exception:
            return 0.0

    @staticmethod
    def _compute_cci(patient: dict[str, Any]) -> int | None:
        """Extract or estimate Charlson Comorbidity Index."""
        # Try direct field first
        cci = (
            (patient.get("demographics") or {}).get("cci_score")
            or (patient.get("baseline") or {}).get("cci_score")
            or (patient.get("demographics") or {}).get("charlson_comorbidity_index")
        )
        if cci is not None:
            try:
                return int(cci)
            except (TypeError, ValueError):
                pass

        # Estimate from known comorbidities
        score = 0
        demographics = patient.get("demographics", {}) or {}
        followups = patient.get("follow_ups", []) or []
        latest = followups[-1] if followups else {}

        conditions = {
            "dm_type2": 1,
            "diabetes": 1,
            "diabetes_complications": 2,
            "chronic_kidney_disease": 1,
            "renal_failure": 2,
            "copd": 1,
            "heart_failure": 1,
            "prior_mi": 1,
            "liver_disease_mild": 1,
            "liver_disease_severe": 3,
            "hiv": 6,
            "cerebrovascular_disease": 1,
            "peptic_ulcer": 1,
            "peripheral_vascular_disease": 1,
        }
        for condition, points in conditions.items():
            if (
                demographics.get(condition)
                or (patient.get("baseline") or {}).get(condition)
                or latest.get(condition)
            ):
                score += points

        # Age contribution
        age = (
            (patient.get("baseline") or {}).get("age")
            or (patient.get("identity") or {}).get("age_at_diagnosis")
        )
        if age:
            try:
                a = int(age)
                if a >= 80:
                    score += 4
                elif a >= 70:
                    score += 3
                elif a >= 60:
                    score += 2
                elif a >= 50:
                    score += 1
            except (TypeError, ValueError):
                pass

        return score if score > 0 else None

    @staticmethod
    def _build_transitions(
        state_timeline: list[dict],
        follow_ups: list[dict],
        treatments: list[dict],
    ) -> list[TransitionEvent]:
        transitions: list[TransitionEvent] = []

        for i in range(len(state_timeline) - 1):
            from_ev = state_timeline[i]
            to_ev = state_timeline[i + 1]

            # Find PSA at transition date
            t_date = to_ev.get("date", "")
            psa_at_t = 0.0
            for fu in reversed(follow_ups):
                if fu.get("visit_date", "") <= t_date:
                    psa_at_t = float(fu.get("psa_current", 0) or 0)
                    break

            # Find treatment at transition time
            tx_at_t = ""
            for tx in reversed(treatments):
                if tx.get("start_date", "") <= t_date:
                    tx_at_t = tx.get("drug_scheme", "")
                    break

            from_date = from_ev.get("date", "")
            try:
                from datetime import date
                d0 = date.fromisoformat(from_date[:10]) if from_date else date.today()
                d1 = date.fromisoformat(t_date[:10]) if t_date else date.today()
                months_from_dx = (d0 - date(2000, 1, 1)).days / 30.44  # approx
            except Exception:
                months_from_dx = 0.0

            transitions.append(TransitionEvent(
                from_state=from_ev.get("state", ""),
                to_state=to_ev.get("state", ""),
                event_date=t_date,
                months_from_diagnosis=months_from_dx,
                driver=to_ev.get("driver", "progression"),
                treatment_at_time=tx_at_t,
                psa_at_time=psa_at_t,
            ))

        return transitions

    @staticmethod
    def _build_phases(
        state_timeline: list[dict],
        treatments: list[dict],
        follow_ups: list[dict],
    ) -> list[DiseasePhase]:
        """Build disease phases with treatment and response labels."""
        phases: list[DiseasePhase] = []
        risk_map = {
            "diagnostic_workup": "intermediate",
            "localized_initial": "intermediate",
            "post_prostatectomy": "intermediate",
            "recurrence_bcr": "high",
            "adt_progression_verification": "high",
            "mcspc_oligo_metachronous": "high",
            "mcspc_low_volume_sync_oligo": "high",
            "mcspc_high_volume_sync": "very_high",
            "mcspc_high_volume_metachronous": "very_high",
            "mcspc_high_volume": "very_high",
            "m0_crpc": "very_high",
            "m1_crpc": "very_high",
        }
        state_labels = {
            "diagnostic_workup": "Evaluación diagnóstica",
            "localized_initial": "Enfermedad localizada",
            "post_prostatectomy": "Post-prostatectomía",
            "recurrence_bcr": "Recurrencia bioquímica",
            "adt_progression_verification": "Verificación de progresión",
            "mcspc_oligo_metachronous": "mCSPC oligo metacrónico",
            "mcspc_low_volume_sync_oligo": "mCSPC bajo volumen sincrónico",
            "mcspc_high_volume_sync": "mCSPC alto volumen sincrónico",
            "mcspc_high_volume_metachronous": "mCSPC alto volumen metacrónico",
            "mcspc_high_volume": "mCSPC alto volumen",
            "m0_crpc": "CPRC no metastásico",
            "m1_crpc": "CPRC metastásico",
        }

        for i, ev in enumerate(state_timeline):
            state = ev.get("state", "")
            start = ev.get("date", "")
            end = state_timeline[i + 1].get("date") if i + 1 < len(state_timeline) else None

            # Duration
            try:
                from datetime import date
                d_start = date.fromisoformat(start[:10]) if start else date.today()
                d_end = date.fromisoformat(end[:10]) if end else date.today()
                duration = max(0.0, (d_end - d_start).days / 30.44)
            except Exception:
                duration = 0.0

            # Treatment during phase
            phase_tx = ""
            for tx in treatments:
                if tx.get("start_date", "") >= start and (not end or tx.get("start_date", "") <= end):
                    phase_tx = tx.get("drug_scheme", "")
                    break

            # PSA at entry/exit
            psa_entry = 0.0
            psa_exit = None
            for fu in follow_ups:
                if fu.get("visit_date", "") >= start:
                    psa_entry = float(fu.get("psa_current", 0) or 0)
                    break
            if end:
                for fu in reversed(follow_ups):
                    if fu.get("visit_date", "") <= end:
                        psa_exit = float(fu.get("psa_current", 0) or 0)
                        break

            # Response
            if psa_exit is not None and psa_entry > 0:
                ratio = psa_exit / psa_entry
                if ratio <= 0.50:
                    response = "responding"
                elif ratio <= 1.25:
                    response = "stable"
                else:
                    response = "progressing"
            else:
                response = "unknown"

            phases.append(DiseasePhase(
                state=state,
                start_date=start,
                end_date=end,
                duration_months=round(duration, 1),
                treatment=phase_tx,
                psa_at_entry=psa_entry,
                psa_at_exit=psa_exit,
                response=response,
                phase_label=state_labels.get(state, state),
                risk_level=risk_map.get(state, "intermediate"),
            ))

        return phases

    @staticmethod
    def _find_psa_nadir(follow_ups: list[dict]) -> tuple[float | None, str | None]:
        if not follow_ups:
            return None, None
        nadir = None
        nadir_date = None
        for fu in follow_ups:
            psa = fu.get("psa_current")
            if psa is not None:
                try:
                    psa_val = float(psa)
                    if nadir is None or psa_val < nadir:
                        nadir = psa_val
                        nadir_date = fu.get("visit_date")
                except (TypeError, ValueError):
                    pass
        return (round(nadir, 3) if nadir is not None else None), nadir_date

    @staticmethod
    def _compute_psadt(follow_ups: list[dict]) -> float | None:
        """Compute PSA doubling time from follow-up series (log2 method)."""
        psa_points: list[tuple[float, float]] = []  # (days, psa)
        from datetime import date

        ref_date = None
        for fu in sorted(follow_ups, key=lambda x: x.get("visit_date", "")):
            psa = fu.get("psa_current")
            vdate = fu.get("visit_date")
            if psa is None or not vdate:
                continue
            try:
                psa_val = float(psa)
                if psa_val <= 0:
                    continue
                d = date.fromisoformat(str(vdate)[:10])
                if ref_date is None:
                    ref_date = d
                days = (d - ref_date).days
                psa_points.append((days, psa_val))
            except Exception:
                continue

        if len(psa_points) < 3:
            return None

        # Simple log-linear fit
        import statistics
        log_psa = [math.log(p) for _, p in psa_points]
        times_days = [t for t, _ in psa_points]
        n = len(psa_points)
        mean_t = statistics.mean(times_days)
        mean_lp = statistics.mean(log_psa)

        numer = sum((t - mean_t) * (lp - mean_lp) for t, lp in zip(times_days, log_psa))
        denom = sum((t - mean_t) ** 2 for t in times_days)

        if abs(denom) < 1e-9:
            return None

        slope_per_day = numer / denom
        if slope_per_day <= 0:
            return None  # PSA declining — no meaningful PSADT

        # DT = ln(2) / slope_per_day → convert to months
        dt_days = math.log(2) / slope_per_day
        dt_months = dt_days / 30.44
        return round(dt_months, 1) if dt_months < 600 else None

    @staticmethod
    def _get_current_treatment(treatments: list[dict]) -> str:
        if not treatments:
            return ""
        active = [t for t in treatments if not t.get("end_date")]
        if active:
            return active[-1].get("drug_scheme", "")
        return treatments[-1].get("drug_scheme", "")

    @staticmethod
    def _lookup_survival_median(state: str, treatment: str) -> float | None:
        state_medians = PUBLISHED_SURVIVAL_MEDIANS.get(state, {})
        if not state_medians:
            return None
        return state_medians.get(treatment) or state_medians.get("default")

    @staticmethod
    def _compute_os_modifier(
        cci: int | None,
        ethnicity_modifier: dict[str, float],
    ) -> float:
        """Combine CCI and ethnicity into a single OS modifier (1.0 = no change)."""
        modifier = 1.0

        # CCI modifier
        if cci is not None:
            cci_key = str(min(cci, 4)) if cci < 4 else "4+"
            cci_mod = CCI_TRANSITION_MODIFIER.get(cci_key, 1.0)
            # CCI increases mortality → reduces expected survival
            modifier = modifier * (1.0 / cci_mod) if cci_mod > 0 else modifier

        # Ethnicity modifier (mortality RR relative to European)
        mortality_rr = ethnicity_modifier.get("mortality_rr", 1.0)
        modifier = modifier * (1.0 / mortality_rr) if mortality_rr > 0 else modifier

        return round(max(0.2, min(2.0, modifier)), 3)

    @staticmethod
    def _predict_next_transition(
        patient: dict[str, Any],
        current_state: str,
        months_in_state: float,
    ) -> tuple[str | None, float | None, float]:
        """Predict next state using AI model if available, else rule-based."""
        # Try AI model first
        try:
            from prostanet.shared.feature_flags import resolve_feature_flags
            if resolve_feature_flags().get("ENABLE_AI_STATE_PREDICTION"):
                from prostanet.ai.inference.runtime_registry import get_runtime_model_registry

                reg = get_runtime_model_registry()
                model = reg.get("state_transition")
                if model:
                    result = model.predict(patient)
                    return (
                        result.values.get("predicted_state"),
                        result.values.get("median_time_months"),
                        result.values.get("model_confidence", 0.7),
                    )
        except Exception:
            pass

        # Rule-based fallback from TRANSITION_MATRIX
        from prostanet.ai.training.synthetic_generator import TRANSITION_MATRIX
        candidates = TRANSITION_MATRIX.get(current_state, [])
        if not candidates:
            return None, None, 0.6

        next_state, prob, (min_m, max_m) = max(candidates, key=lambda x: x[1])
        time_est = (min_m + max_m) / 2.0 - months_in_state
        return (
            next_state if prob > 0.1 else None,
            round(max(3.0, time_est), 1),
            round(prob, 2),
        )

    @staticmethod
    def _build_risk_summary(
        baseline: dict[str, Any],
        patient: dict[str, Any],
        cci: int | None,
        ethnicity_modifier: dict[str, float],
        psadt: float | None,
    ) -> dict[str, Any]:
        psa = baseline.get("baseline_psa")
        gleason = (baseline.get("gleason_primary", 0) or 0) + (baseline.get("gleason_secondary", 0) or 0)
        isup = baseline.get("isup_grade")
        age = baseline.get("age") or (patient.get("identity") or {}).get("age_at_diagnosis")
        hrr = baseline.get("hrr_positive") or (patient.get("genomic_profile") or {}).get("hrr_status")

        risk_factors = []
        if psa and psa > 20:
            risk_factors.append(f"PSA basal elevado ({psa} ng/mL)")
        if isup and isup >= 4:
            risk_factors.append(f"Grado ISUP {isup} (alto grado)")
        if gleason >= 9:
            risk_factors.append(f"Gleason {gleason} (muy alto riesgo)")
        if age and int(age) > 75:
            risk_factors.append(f"Edad avanzada ({age} años)")
        if hrr:
            risk_factors.append("Mutación HRR positiva (mayor riesgo de CPRC)")
        if psadt and psadt < 6:
            risk_factors.append(f"PSADT corto ({psadt} meses) — señal de progresión agresiva")
        if cci and cci >= 3:
            risk_factors.append(f"Comorbilidad alta (CCI={cci})")
        if ethnicity_modifier.get("mortality_rr", 1.0) > 1.3:
            risk_factors.append(
                f"Etnia con mayor mortalidad (RR={ethnicity_modifier['mortality_rr']:.2f})"
            )

        return {
            "risk_factors": risk_factors,
            "risk_factor_count": len(risk_factors),
            "cci": cci,
            "hrr_positive": bool(hrr),
            "psadt_months": psadt,
            "gleason_total": gleason if gleason > 0 else None,
            "isup_grade": isup,
            "age": age,
        }

    @staticmethod
    def _build_flags(
        patient: dict[str, Any],
        state: str,
        psadt: float | None,
        cci: int | None,
        follow_ups: list[dict],
    ) -> list[str]:
        flags = []

        if psadt is not None and psadt < 6:
            flags.append("⚠ PSADT <6 meses: riesgo de progresión rápida a mCPRC")
        if psadt is not None and psadt < 3:
            flags.append("🔴 PSADT <3 meses: altamente agresivo")

        if cci is not None and cci >= 3:
            flags.append(f"⚠ CCI={cci}: comorbilidad significativa — ajustar tratamiento")

        if state in ("m1_crpc",):
            flags.append("🔴 Estado terminal de la historia natural — enfoque paliativo")

        if state in ("m0_crpc", "m1_crpc"):
            flags.append("⚠ Confirmar castración (testosterona <50 ng/dL)")

        # ECOG deterioration
        ecog_values = [
            int(fu.get("ecog", 0)) for fu in follow_ups
            if fu.get("ecog") is not None
        ]
        if len(ecog_values) >= 3 and ecog_values[-1] > ecog_values[-3]:
            flags.append("⚠ ECOG en deterioro — reevaluar capacidad funcional")

        if not follow_ups:
            flags.append("ℹ Sin visitas de seguimiento registradas")

        return flags

    @staticmethod
    def _build_treatment_history(
        treatments: list[dict],
        follow_ups: list[dict],
    ) -> list[dict[str, Any]]:
        history = []
        for tx in treatments:
            scheme = tx.get("drug_scheme", "")
            start = tx.get("start_date", "")
            end = tx.get("end_date")
            outcomes = tx.get("outcomes", {}) or {}

            # Find PSA response
            psa_at_start = None
            psa_nadir_on_tx = None
            for fu in sorted(follow_ups, key=lambda x: x.get("visit_date", "")):
                if fu.get("visit_date", "") >= start:
                    if psa_at_start is None:
                        psa_at_start = fu.get("psa_current")
                    p = fu.get("psa_current")
                    if p is not None:
                        if psa_nadir_on_tx is None or float(p) < float(psa_nadir_on_tx):
                            psa_nadir_on_tx = float(p)
                    if end and fu.get("visit_date", "") > end:
                        break

            psa50 = None
            if psa_at_start and psa_nadir_on_tx is not None:
                psa50 = (float(psa_nadir_on_tx) / float(psa_at_start)) <= 0.5

            history.append({
                "drug_scheme": scheme,
                "start_date": start,
                "end_date": end,
                "psa_at_start": psa_at_start,
                "psa_nadir": psa_nadir_on_tx,
                "psa50_achieved": psa50,
                "outcomes": outcomes,
                "active": not bool(end),
            })

        return history

    def _build_narrative(self, r: NaturalHistoryReport) -> str:
        """Generate a Spanish clinical narrative summarizing the natural history."""
        lines = []

        # Header
        lines.append(
            f"**Historia Natural — Paciente #{r.patient_id}**"
        )
        lines.append(
            f"Diagnóstico: {r.diagnosis_date} | "
            f"Tiempo desde diagnóstico: {r.time_since_diagnosis_months:.0f} meses | "
            f"Estado actual: {r.current_state}"
        )
        lines.append("")

        # Trajectory
        if r.disease_phases:
            lines.append("**Trayectoria de la enfermedad:**")
            for ph in r.disease_phases:
                duration_str = f"{ph.duration_months:.0f} meses" if ph.duration_months > 0 else "en curso"
                response_labels = {
                    "responding": "respondiendo",
                    "stable": "estable",
                    "progressing": "progresando",
                    "unknown": "desconocida",
                }
                lines.append(
                    f"  • {ph.phase_label} ({duration_str})"
                    + (f" — {ph.treatment}" if ph.treatment else "")
                    + f" — Respuesta: {response_labels.get(ph.response, ph.response)}"
                )
            lines.append("")

        # PSA kinetics
        if r.psa_nadir is not None:
            lines.append(
                f"**Nadir de PSA:** {r.psa_nadir} ng/mL"
                + (f" ({r.psa_nadir_date})" if r.psa_nadir_date else "")
            )
        if r.psa_doubling_time_months:
            urgency = "rápida" if r.psa_doubling_time_months < 6 else "moderada" if r.psa_doubling_time_months < 12 else "lenta"
            lines.append(f"**PSADT:** {r.psa_doubling_time_months} meses — cinética {urgency}")
        lines.append("")

        # Survival
        if r.adjusted_os_months:
            lines.append(
                f"**Supervivencia global estimada:** {r.adjusted_os_months} meses "
                f"(publicada: {r.expected_os_months} meses, "
                f"modificador por comorbilidad/etnia: {r.os_modifier:.2f})"
            )
        lines.append("")

        # Risk factors
        if r.risk_summary.get("risk_factors"):
            lines.append("**Factores de riesgo identificados:**")
            for rf in r.risk_summary["risk_factors"]:
                lines.append(f"  • {rf}")
            lines.append("")

        # Predicted next transition
        if r.predicted_next_state:
            conf_label = "alta" if r.transition_confidence >= 0.7 else "moderada" if r.transition_confidence >= 0.4 else "baja"
            lines.append(
                f"**Próxima transición predicha:** {r.predicted_next_state} "
                f"en ~{r.predicted_time_to_transition_months} meses "
                f"(confianza: {conf_label})"
            )
            lines.append("")

        # Flags
        if r.flags:
            lines.append("**Alertas clínicas:**")
            for fl in r.flags:
                lines.append(f"  {fl}")

        return "\n".join(lines)


# ── Convenience function ──

def analyze_natural_history(patient: dict[str, Any]) -> dict[str, Any]:
    """Convenience wrapper — returns serializable dict."""
    tracker = NaturalHistoryTracker()
    report = tracker.analyze(patient)
    return report.to_dict()
