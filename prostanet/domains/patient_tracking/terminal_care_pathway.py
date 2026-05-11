# -*- coding: utf-8 -*-
"""
Terminal Care Pathway — End-Stage Prostate Cancer Management.

Manages the transition from active oncological treatment to palliative/supportive
care for patients with advanced, treatment-refractory prostate cancer.

Covers:
  1. PCWG3 radiographic and clinical progression criteria
  2. Performance status deterioration trajectory
  3. Palliative care triggers and goals-of-care documentation
  4. End-of-life symptom burden mapping (pain, dyspnea, fatigue, urinary)
  5. Hospice eligibility criteria
  6. ASCO/ESMO palliative interventions by symptom cluster
  7. SRE (Skeletal-Related Events) prevention — bone-directed therapy
  8. Spinal cord compression emergency pathway
  9. Multidisciplinary team (MDT) referral triggers
 10. Prognosis communication framework (SPIKES + prognostic anchors)

References:
  - Scher HI, et al. Trial Design and Objectives for Castration-Resistant Prostate
    Cancer: Updated Recommendations From the Prostate Cancer Working Group 3.
    J Clin Oncol. 2016;34(12):1402-1418.
  - ASCO Palliative Care Guidelines 2017
  - ESMO Palliative Care in Advanced Prostate Cancer 2023
  - EAU Guidelines on Prostate Cancer 2026 (Palliative Care section)
  - Hui D, et al. Prognostic signs of impending death in cancer patients.
    Oncologist. 2014;19(6):681-687.

Usage::

    from prostanet.domains.patient_tracking.terminal_care_pathway import TerminalCarePathway
    assessment = TerminalCarePathway.assess(patient)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from prostanet.domains.patient_tracking.clinical_list_normalization import (
    coerce_text,
    normalize_followup_entries,
    normalize_imaging_entries,
    normalize_medication_entries,
)

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# PCWG3 Progression Criteria
# ══════════════════════════════════════════════════════════════════════════════

# PCWG3 PSA progression: ≥25% increase AND ≥2 ng/mL above nadir, confirmed
PCWG3_PSA_MIN_RISE_PERCENT   = 25.0
PCWG3_PSA_MIN_ABSOLUTE_RISE  = 2.0   # ng/mL above nadir

# PCWG3 bone scan progression: ≥2 new lesions on bone scan confirmed at ≥6 weeks
PCWG3_BONE_MIN_NEW_LESIONS   = 2

# Radiographic soft tissue progression: RECIST 1.1 (≥20% increase in sum diameter)
RECIST_PROGRESSION_THRESHOLD = 0.20


# ══════════════════════════════════════════════════════════════════════════════
# Performance Status Thresholds
# ══════════════════════════════════════════════════════════════════════════════

# ECOG thresholds for treatment decisions
ECOG_THRESHOLD_CHEMO     = 2   # ECOG ≤2 for cytotoxic chemotherapy
ECOG_THRESHOLD_NOVEL_ARG = 3   # ECOG ≤3 for novel AR agents (more lenient)
ECOG_THRESHOLD_HOSPICE   = 3   # ECOG ≥3 as one hospice trigger

# Karnofsky performance status (KPS) equivalent
# KPS < 50 → majority time in bed or chair → strong hospice indicator
KPS_HOSPICE_THRESHOLD = 50


# ══════════════════════════════════════════════════════════════════════════════
# Hospice Eligibility Criteria (6-month mortality rule)
# ══════════════════════════════════════════════════════════════════════════════

HOSPICE_CRITERIA = {
    "ecog_ge3": "ECOG ≥3 (limitación funcional severa)",
    "life_expectancy_le6m": "Esperanza de vida estimada ≤6 meses",
    "refractory_to_all_lines": "Progresión a todas las líneas de tratamiento disponibles",
    "visceral_crisis": "Crisis visceral (compromiso hepático o pulmonar extenso)",
    "patient_preference_comfort": "Preferencia del paciente: cuidados de confort",
    "halabi_high_risk": "Grupo Halabi alto riesgo (mediana OS ≤7.3 meses)",
    "declining_albumin": "Hipoalbuminemia progresiva (<3.0 g/dL) sin causa tratable",
    "weight_loss_ge10pct": "Pérdida de peso ≥10% en 6 meses sin otra etiología",
}


# ══════════════════════════════════════════════════════════════════════════════
# Symptom Burden Catalog
# ══════════════════════════════════════════════════════════════════════════════

SYMPTOM_INTERVENTIONS: dict[str, list[dict[str, str]]] = {
    "pain": [
        {"intervention": "Escalada analgésica escalonada (OMS ladder)", "evidence": "IA"},
        {"intervention": "Bifosfonatos IV o denosumab — prevención SRE", "evidence": "IA"},
        {"intervention": "Radioterapia paliativa para lesión ósea dominante", "evidence": "IA"},
        {"intervention": "Lu-177 PSMA en mCRPC PSMA+ refractario", "evidence": "IA"},
        {"intervention": "Ra-223 en mCRPC óseo sin metástasis viscerales", "evidence": "IA"},
        {"intervention": "Corticosteroides para dolor por compresión", "evidence": "IIB"},
        {"intervention": "Bloqueo nervioso / epidural para dolor refractario", "evidence": "IIB"},
    ],
    "urinary_obstruction": [
        {"intervention": "Cateterismo uretral / uretrostomía paliativa", "evidence": "IA"},
        {"intervention": "RTU-P paliativa si estado funcional permite", "evidence": "IIB"},
        {"intervention": "Radioterapia externa pélvica paliativa", "evidence": "IIB"},
        {"intervention": "Nefrostomía percutánea si hidronefrosis bilateral", "evidence": "IIA"},
        {"intervention": "Dexametasona para edema periuretral peritumoral", "evidence": "IIB"},
    ],
    "lymphedema": [
        {"intervention": "Terapia física descompresiva + vendaje multicapa", "evidence": "IA"},
        {"intervention": "Medias de compresión graduada", "evidence": "IIB"},
        {"intervention": "Linfodrenaje manual", "evidence": "IIB"},
    ],
    "spinal_cord_compression": [
        {"intervention": "URGENCIA: Dexametasona 16 mg IV inmediato", "evidence": "IA"},
        {"intervention": "Radioterapia de emergencia (24-48h) o cirugía descompresiva", "evidence": "IA"},
        {"intervention": "Evaluación neurológica urgente + RMN columna", "evidence": "IA"},
        {"intervention": "SBRT columna si enfermedad oligometastásica", "evidence": "IIB"},
    ],
    "fatigue": [
        {"intervention": "Ejercicio aeróbico supervisado (evidencia nivel IA)", "evidence": "IA"},
        {"intervention": "Corrección de anemia si Hgb <10 g/dL", "evidence": "IA"},
        {"intervention": "Terapia cognitivo-conductual", "evidence": "IIA"},
        {"intervention": "Modafinilo / metilfenidato si fatiga severa refractaria", "evidence": "IIB"},
    ],
    "nausea_vomiting": [
        {"intervention": "Ondansetrón 8 mg antes de quimioterapia", "evidence": "IA"},
        {"intervention": "Dexametasona + ondansetrón para náusea quimio", "evidence": "IA"},
        {"intervention": "Metoclopramida para náusea por motilidad alterada", "evidence": "IIA"},
        {"intervention": "Haloperidol dosis bajas si náusea refractaria", "evidence": "IIB"},
    ],
    "dyspnea": [
        {"intervention": "Opiáceos sistémicos (morfina titular) para disnea refractaria", "evidence": "IA"},
        {"intervention": "Oxígeno si SpO2 <90%", "evidence": "IIA"},
        {"intervention": "Benzodiacepinas si componente ansioso", "evidence": "IIB"},
        {"intervention": "Ventilador/fan facial (estimulación nervio trigémino)", "evidence": "IIB"},
    ],
    "bone_health": [
        {"intervention": "Ácido zoledrónico 4 mg IV q4-12 semanas", "evidence": "IA"},
        {"intervention": "Denosumab 120 mg SC q4 semanas (superior en prevención SRE)", "evidence": "IA"},
        {"intervention": "Suplementación calcio + vitamina D con agentes óseos", "evidence": "IA"},
        {"intervention": "Monitoreo función renal con bifosfonatos", "evidence": "IA"},
        {"intervention": "Vigilancia osteonecrosis mandibular (ONJ) — examen dental previo", "evidence": "IA"},
    ],
}


# ══════════════════════════════════════════════════════════════════════════════
# SRE Risk Stratification
# ══════════════════════════════════════════════════════════════════════════════

SRE_HIGH_RISK_CRITERIA = {
    "alp_elevated": "ALP >200 U/L",
    "ldh_elevated": "LDH >300 U/L",
    "multiple_bone_mets": "≥5 metástasis óseas",
    "axial_involvement": "Afectación axial (columna, pelvis)",
    "no_bone_directed_therapy": "Sin terapia ósea dirigida actual",
}


# ══════════════════════════════════════════════════════════════════════════════
# Dataclasses
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class PCWGProgressionStatus:
    """PCWG3 progression assessment."""
    psa_progression:          bool = False
    radiographic_bone:        bool = False
    radiographic_soft_tissue: bool = False
    clinical_progression:     bool = False
    psa_details:              str  = ""
    imaging_details:          str  = ""
    meets_pcwg3_criteria:     bool = False


@dataclass
class SymptomBurdenProfile:
    """Current symptom burden for palliative planning."""
    pain_present:                bool  = False
    pain_score:                  float = 0.0
    requires_opioids:            bool  = False
    urinary_obstruction:         bool  = False
    spinal_cord_compression_risk:bool  = False
    fatigue_grade:               int   = 0
    dyspnea_present:             bool  = False
    lymphedema_present:          bool  = False
    nausea_present:              bool  = False
    active_symptoms:             list[str] = field(default_factory=list)


@dataclass
class HospiceEligibilityAssessment:
    """Hospice eligibility evaluation."""
    is_eligible:            bool       = False
    criteria_met:           list[str]  = field(default_factory=list)
    criteria_not_met:       list[str]  = field(default_factory=list)
    life_expectancy_months: float | None = None
    recommendation:         str        = ""


@dataclass
class TerminalCareAssessment:
    """Complete terminal care pathway assessment."""
    patient_id:            int | None               = None
    current_state:         str                      = ""
    pcwg3_progression:     PCWGProgressionStatus    = field(default_factory=PCWGProgressionStatus)
    symptom_burden:        SymptomBurdenProfile     = field(default_factory=SymptomBurdenProfile)
    hospice_eligibility:   HospiceEligibilityAssessment = field(default_factory=HospiceEligibilityAssessment)
    active_interventions:  dict[str, list[dict]]    = field(default_factory=dict)
    emergency_alerts:      list[str]                = field(default_factory=list)
    mdt_referrals:         list[str]                = field(default_factory=list)
    goals_of_care:         str                      = ""
    prognosis_anchor:      str                      = ""
    clinical_narrative:    str                      = ""
    has_data:              bool                     = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "has_data": self.has_data,
            "patient_id": self.patient_id,
            "current_state": self.current_state,
            "pcwg3_progression": {
                "psa_progression": self.pcwg3_progression.psa_progression,
                "radiographic_bone": self.pcwg3_progression.radiographic_bone,
                "radiographic_soft_tissue": self.pcwg3_progression.radiographic_soft_tissue,
                "clinical_progression": self.pcwg3_progression.clinical_progression,
                "meets_pcwg3_criteria": self.pcwg3_progression.meets_pcwg3_criteria,
                "psa_details": self.pcwg3_progression.psa_details,
                "imaging_details": self.pcwg3_progression.imaging_details,
            },
            "symptom_burden": {
                "pain_present": self.symptom_burden.pain_present,
                "pain_score": self.symptom_burden.pain_score,
                "requires_opioids": self.symptom_burden.requires_opioids,
                "urinary_obstruction": self.symptom_burden.urinary_obstruction,
                "spinal_cord_compression_risk": self.symptom_burden.spinal_cord_compression_risk,
                "fatigue_grade": self.symptom_burden.fatigue_grade,
                "dyspnea_present": self.symptom_burden.dyspnea_present,
                "active_symptoms": self.symptom_burden.active_symptoms,
            },
            "hospice_eligibility": {
                "is_eligible": self.hospice_eligibility.is_eligible,
                "criteria_met": self.hospice_eligibility.criteria_met,
                "life_expectancy_months": self.hospice_eligibility.life_expectancy_months,
                "recommendation": self.hospice_eligibility.recommendation,
            },
            "active_interventions": self.active_interventions,
            "emergency_alerts": self.emergency_alerts,
            "mdt_referrals": self.mdt_referrals,
            "goals_of_care": self.goals_of_care,
            "prognosis_anchor": self.prognosis_anchor,
            "clinical_narrative": self.clinical_narrative,
        }


# ══════════════════════════════════════════════════════════════════════════════
# Terminal Care Pathway Engine
# ══════════════════════════════════════════════════════════════════════════════

class TerminalCarePathway:
    """
    Comprehensive terminal care pathway for end-stage prostate cancer.

    Integrates PCWG3 progression criteria, palliative symptom management,
    hospice eligibility, and prognosis communication frameworks.
    """

    @classmethod
    def assess(cls, patient: dict[str, Any]) -> dict[str, Any]:
        """
        Full terminal care pathway assessment.

        Args:
            patient: Full patient dict from `get_patient_full_record()`.

        Returns:
            TerminalCareAssessment serialized to dict.
        """
        try:
            assessment = TerminalCareAssessment()
            assessment.patient_id = patient.get("id") or patient.get("patient_id")
            assessment.current_state = (
                patient.get("current_state") or patient.get("state") or ""
            )

            # 1. PCWG3 progression
            assessment.pcwg3_progression = cls._assess_pcwg3_progression(patient)

            # 2. Symptom burden
            assessment.symptom_burden = cls._assess_symptom_burden(patient)

            # 3. Emergency alerts (must come before interventions)
            assessment.emergency_alerts = cls._check_emergencies(
                assessment.symptom_burden, patient
            )

            # 4. Active palliative interventions
            assessment.active_interventions = cls._recommend_interventions(
                assessment.symptom_burden
            )

            # 5. Hospice eligibility
            assessment.hospice_eligibility = cls._assess_hospice_eligibility(
                patient, assessment
            )

            # 6. MDT referrals
            assessment.mdt_referrals = cls._build_mdt_referrals(assessment)

            # 7. Goals of care
            assessment.goals_of_care = cls._determine_goals_of_care(assessment)

            # 8. Prognosis anchor (SPIKES framework)
            assessment.prognosis_anchor = cls._build_prognosis_anchor(
                patient, assessment
            )

            # 9. Clinical narrative
            assessment.clinical_narrative = cls._build_narrative(assessment)

            return assessment.to_dict()

        except Exception as exc:
            logger.warning("Terminal care pathway error: %s", exc)
            return {"has_data": False, "error": str(exc)}

    # ── PCWG3 Progression Assessment ────────────────────────────────────────

    @classmethod
    def _assess_pcwg3_progression(
        cls, patient: dict[str, Any]
    ) -> PCWGProgressionStatus:
        """Evaluate PCWG3 radiographic and PSA progression criteria."""
        status = PCWGProgressionStatus()

        # PSA progression
        psa_series = cls._extract_psa_series(patient)
        if len(psa_series) >= 2:
            psa_values = [p for _, p in psa_series]
            psa_nadir = min(psa_values)
            latest_psa = psa_values[-1]

            if psa_nadir > 0 and latest_psa > psa_nadir:
                pct_rise = (latest_psa - psa_nadir) / psa_nadir * 100
                abs_rise = latest_psa - psa_nadir

                if pct_rise >= PCWG3_PSA_MIN_RISE_PERCENT and abs_rise >= PCWG3_PSA_MIN_ABSOLUTE_RISE:
                    status.psa_progression = True
                    status.psa_details = (
                        f"PSA nadir: {psa_nadir:.2f} → actual: {latest_psa:.2f} ng/mL "
                        f"(+{pct_rise:.0f}%, +{abs_rise:.2f} ng/mL) — PCWG3 positivo"
                    )
                else:
                    status.psa_details = (
                        f"PSA nadir: {psa_nadir:.2f} → actual: {latest_psa:.2f} ng/mL "
                        f"(+{pct_rise:.0f}%, +{abs_rise:.2f} ng/mL) — Sin criterio PCWG3"
                    )

        # Radiographic progression
        imaging = normalize_imaging_entries(
            patient.get("imaging_studies") or patient.get("imaging") or []
        )
        new_bone_lesions = 0
        soft_tissue_progression = False

        for img in imaging:
            findings = coerce_text(img.get("findings") or img.get("result")).lower()
            conclusion = coerce_text(img.get("conclusion")).lower()
            combined = findings + " " + conclusion

            # New bone lesions on bone scan
            if any(w in combined for w in ["nueva lesión", "new lesion", "nuevas lesiones", "new bone"]):
                new_bone_lesions += 2  # Conservative: assume ≥2 if mentioned
            if "progresión ósea" in combined or "bone progression" in combined:
                new_bone_lesions += 2

            # Soft tissue RECIST progression
            if any(w in combined for w in ["progresión", "progression", "aumento", "increase"]):
                if any(w in combined for w in ["linfonodo", "nódulo", "visceral", "hígado", "pulmon"]):
                    soft_tissue_progression = True

        if new_bone_lesions >= PCWG3_BONE_MIN_NEW_LESIONS:
            status.radiographic_bone = True
            status.imaging_details += f"≥{new_bone_lesions} nuevas lesiones óseas (PCWG3). "

        if soft_tissue_progression:
            status.radiographic_soft_tissue = True
            status.imaging_details += "Progresión tejido blando (RECIST). "

        # Clinical progression: ECOG decline + symptoms
        ecog = cls._get_ecog(patient)
        if ecog is not None and ecog >= 3:
            status.clinical_progression = True

        status.meets_pcwg3_criteria = (
            status.psa_progression
            or status.radiographic_bone
            or status.radiographic_soft_tissue
        )

        return status

    # ── Symptom Burden Assessment ────────────────────────────────────────────

    @classmethod
    def _assess_symptom_burden(cls, patient: dict[str, Any]) -> SymptomBurdenProfile:
        """Map current symptom burden from patient data."""
        profile = SymptomBurdenProfile()

        # Pain
        pain = (
            patient.get("pain_score")
            or patient.get("pain")
            or cls._get_from_visits(patient, "pain_score")
        )
        if pain is not None:
            try:
                pain_val = float(pain)
                profile.pain_score = pain_val
                if pain_val > 0:
                    profile.pain_present = True
                    profile.active_symptoms.append("pain")
                if pain_val >= 4:
                    profile.requires_opioids = True

            except (TypeError, ValueError):
                pass

        # Opioid use
        meds = normalize_medication_entries(
            patient.get("current_medications")
            or patient.get("medications")
            or []
        )
        _OPIOIDS = {"morfina", "morphine", "oxicodona", "oxycodone", "tramadol",
                    "fentanilo", "fentanyl", "hidrocodona", "codeina", "tapentadol",
                    "buprenorfina", "metadona"}
        for med in meds:
            name = coerce_text(med.get("name") or med.get("drug")).lower()
            if any(op in name for op in _OPIOIDS):
                profile.requires_opioids = True
                profile.pain_present = True
                if "pain" not in profile.active_symptoms:
                    profile.active_symptoms.append("pain")

        # Urinary obstruction
        state = coerce_text(patient.get("current_state")).lower()
        if any(s in state for s in ["obstruccion", "obstruction", "hydroneph"]):
            profile.urinary_obstruction = True
            profile.active_symptoms.append("urinary_obstruction")

        # Check imaging for hydronephrosis
        for img in normalize_imaging_entries(patient.get("imaging_studies") or patient.get("imaging") or []):
            findings = coerce_text(img.get("findings")).lower()
            if "hidronefrosis" in findings or "hydronephrosis" in findings:
                profile.urinary_obstruction = True
                if "urinary_obstruction" not in profile.active_symptoms:
                    profile.active_symptoms.append("urinary_obstruction")

        # Spinal cord compression risk
        for img in normalize_imaging_entries(patient.get("imaging_studies") or patient.get("imaging") or []):
            findings = coerce_text(img.get("findings")).lower()
            if any(w in findings for w in [
                "compresión medular", "cord compression", "epidural",
                "spinal canal", "canal espinal", "mielopatía"
            ]):
                profile.spinal_cord_compression_risk = True
                if "spinal_cord_compression" not in profile.active_symptoms:
                    profile.active_symptoms.append("spinal_cord_compression")

        # Fatigue (from ECOG as proxy)
        ecog = cls._get_ecog(patient)
        if ecog is not None:
            try:
                e = int(ecog)
                if e >= 2:
                    profile.fatigue_grade = e
                    profile.active_symptoms.append("fatigue")
            except (TypeError, ValueError):
                pass

        # Dyspnea
        if any(s in state for s in ["dyspnea", "disnea", "respiratory"]):
            profile.dyspnea_present = True
            profile.active_symptoms.append("dyspnea")

        # Bone health (always relevant in mCRPC with bone mets)
        bone_states = {"m1b_cspc", "m1b_crpc", "m1_crpc", "mcspc", "m1b"}
        if any(s in state for s in bone_states):
            profile.active_symptoms.append("bone_health")

        return profile

    # ── Emergency Alerts ────────────────────────────────────────────────────

    @classmethod
    def _check_emergencies(
        cls,
        symptoms: SymptomBurdenProfile,
        patient: dict[str, Any],
    ) -> list[str]:
        """Generate emergency alerts for oncological urgencies."""
        alerts: list[str] = []

        if symptoms.spinal_cord_compression_risk:
            alerts.append(
                "🚨 URGENCIA ONCOLÓGICA: Riesgo de compresión medular. "
                "Iniciar dexametasona 16 mg IV INMEDIATO. "
                "Solicitar RMN columna urgente y evaluación neurocirugía."
            )

        # Check for severe hypercalcemia (ALP > 400 as proxy if Ca not available)
        alp = cls._get_lab(patient, "alp")
        if alp and alp > 500:
            alerts.append(
                "⚠️ ALERTA: ALP >500 U/L — evaluar hipercalcemia maligna. "
                "Solicitar calcio sérico urgente. Hidratación IV si confirmado."
            )

        # DIC risk in high-burden disease
        ldh = cls._get_lab(patient, "ldh")
        hgb = cls._get_lab(patient, "hemoglobin")
        if ldh and ldh > 500 and hgb and hgb < 8:
            alerts.append(
                "⚠️ ALERTA: LDH >500 + Hgb <8 — evaluar coagulación intravascular "
                "diseminada (CID). Solicitar: TP, TTP, fibrinógeno, dímero-D."
            )

        # Urosepsis risk
        if symptoms.urinary_obstruction:
            alerts.append(
                "⚠️ ALERTA: Obstrucción urinaria documentada — riesgo urosepsis. "
                "Solicitar urocultivo. Considerar cateterismo o nefrostomía urgente "
                "si hidronefrosis bilateral o fiebre."
            )

        # Severe anemia
        if hgb and hgb < 7.0:
            alerts.append(
                f"⚠️ ALERTA: Hemoglobina crítica ({hgb:.1f} g/dL). "
                "Indicación de transfusión eritrocitaria. Evaluar causa (mielosupresión vs hemólisis)."
            )

        return alerts

    # ── Palliative Interventions ─────────────────────────────────────────────

    @classmethod
    def _recommend_interventions(
        cls, symptoms: SymptomBurdenProfile
    ) -> dict[str, list[dict]]:
        """Map active symptoms to evidence-based palliative interventions."""
        interventions: dict[str, list[dict]] = {}
        for symptom in symptoms.active_symptoms:
            if symptom in SYMPTOM_INTERVENTIONS:
                interventions[symptom] = SYMPTOM_INTERVENTIONS[symptom]
        return interventions

    # ── Hospice Eligibility ──────────────────────────────────────────────────

    @classmethod
    def _assess_hospice_eligibility(
        cls,
        patient: dict[str, Any],
        assessment: TerminalCareAssessment,
    ) -> HospiceEligibilityAssessment:
        """Evaluate hospice eligibility criteria."""
        result = HospiceEligibilityAssessment()
        met: list[str] = []
        not_met: list[str] = []

        # ECOG ≥3
        ecog = cls._get_ecog(patient)
        if ecog is not None and ecog >= ECOG_THRESHOLD_HOSPICE:
            met.append(HOSPICE_CRITERIA["ecog_ge3"])
        else:
            not_met.append(HOSPICE_CRITERIA["ecog_ge3"])

        # Refractory to all lines
        tx_history = patient.get("treatment_history") or []
        if len(tx_history) >= 3:
            met.append(HOSPICE_CRITERIA["refractory_to_all_lines"])
        else:
            not_met.append(HOSPICE_CRITERIA["refractory_to_all_lines"])

        # Visceral crisis
        state = coerce_text(assessment.current_state).lower()
        if "visceral" in state or "m1c" in state:
            met.append(HOSPICE_CRITERIA["visceral_crisis"])
        else:
            not_met.append(HOSPICE_CRITERIA["visceral_crisis"])

        # Halabi high risk
        halabi = patient.get("halabi_nomogram") or {}
        if halabi.get("risk_group") == "high":
            met.append(HOSPICE_CRITERIA["halabi_high_risk"])
            result.life_expectancy_months = halabi.get("median_os_months", 7.3)
        else:
            not_met.append(HOSPICE_CRITERIA["halabi_high_risk"])

        # Albumin < 3.0
        albumin = cls._get_lab(patient, "albumin")
        if albumin is not None and albumin < 3.0:
            met.append(HOSPICE_CRITERIA["declining_albumin"])
        else:
            not_met.append(HOSPICE_CRITERIA["declining_albumin"])

        # Weight loss ≥10%
        weight_loss = patient.get("weight_loss_pct") or patient.get("weight_loss")
        if weight_loss is not None:
            try:
                if float(weight_loss) >= 10.0:
                    met.append(HOSPICE_CRITERIA["weight_loss_ge10pct"])
                else:
                    not_met.append(HOSPICE_CRITERIA["weight_loss_ge10pct"])
            except (TypeError, ValueError):
                not_met.append(HOSPICE_CRITERIA["weight_loss_ge10pct"])
        else:
            not_met.append(HOSPICE_CRITERIA["weight_loss_ge10pct"])

        result.criteria_met = met
        result.criteria_not_met = not_met

        # Eligible if ≥2 major criteria met
        result.is_eligible = len(met) >= 2

        if result.is_eligible:
            result.recommendation = (
                "Paciente elegible para cuidados paliativos especializados / hospicio. "
                f"Criterios cumplidos: {len(met)}/{len(HOSPICE_CRITERIA)}. "
                "Recomendar conversación sobre objetivos del cuidado y derivación a equipo de paliativos."
            )
        else:
            result.recommendation = (
                "No cumple criterios de elegibilidad para hospicio en este momento. "
                f"Criterios cumplidos: {len(met)}/{len(HOSPICE_CRITERIA)}. "
                "Continuar tratamiento activo con soporte paliativo integrado."
            )

        return result

    # ── MDT Referrals ────────────────────────────────────────────────────────

    @classmethod
    def _build_mdt_referrals(cls, assessment: TerminalCareAssessment) -> list[str]:
        """Generate multidisciplinary team referral recommendations."""
        referrals: list[str] = []

        if assessment.hospice_eligibility.is_eligible:
            referrals.append(
                "Equipo de Medicina Paliativa — objetivos del cuidado, control sintomático"
            )

        if assessment.symptom_burden.pain_present and assessment.symptom_burden.pain_score >= 6:
            referrals.append("Clínica del Dolor — manejo analgésico refractario")

        if assessment.symptom_burden.spinal_cord_compression_risk:
            referrals.append(
                "Neurocirugía / Radioterapia urgente — compresión medular"
            )

        if assessment.symptom_burden.urinary_obstruction:
            referrals.append("Urología — manejo de obstrucción urinaria")

        if assessment.symptom_burden.lymphedema_present:
            referrals.append("Fisioterapia oncológica — linfedema")

        if assessment.pcwg3_progression.meets_pcwg3_criteria:
            referrals.append(
                "Oncología Nuclear — evaluar Ra-223 o Lu-177 PSMA según fenotipo"
            )

        # Psycho-oncology for all terminal patients
        referrals.append(
            "Psicooncología / Trabajo Social — soporte al paciente y familia"
        )

        return referrals

    # ── Goals of Care ────────────────────────────────────────────────────────

    @classmethod
    def _determine_goals_of_care(cls, assessment: TerminalCareAssessment) -> str:
        """Determine appropriate goals of care tier."""
        if assessment.hospice_eligibility.is_eligible:
            return (
                "CUIDADOS DE CONFORT: Prioridad = alivio del sufrimiento y calidad de vida. "
                "No iniciar nuevas líneas de quimioterapia citotóxica. "
                "Mantener analgesia óptima, hidratación y soporte espiritual/familiar."
            )
        elif assessment.pcwg3_progression.meets_pcwg3_criteria:
            return (
                "CUIDADOS PALIATIVOS INTEGRADOS: Continuar tratamiento activo con intención "
                "de control de enfermedad. Optimizar calidad de vida en paralelo. "
                "Planificar conversación anticipada sobre preferencias al final de vida."
            )
        else:
            return (
                "TRATAMIENTO ACTIVO CON SOPORTE: Prioridad = control de enfermedad y "
                "calidad de vida. Integrar soporte paliativo temprano desde ahora."
            )

    # ── Prognosis Anchor ─────────────────────────────────────────────────────

    @classmethod
    def _build_prognosis_anchor(
        cls,
        patient: dict[str, Any],
        assessment: TerminalCareAssessment,
    ) -> str:
        """
        Build prognosis anchor for SPIKES communication framework.
        Provides clinician with concrete data points for prognostic disclosure.
        """
        # Try to get Halabi estimate
        halabi = patient.get("halabi_nomogram") or {}
        halabi_os = halabi.get("median_os_months")
        halabi_group = halabi.get("risk_group")

        lines = ["Marco pronóstico para comunicación clínica (SPIKES):"]

        if halabi_os and halabi_group:
            lines += [
                f"  • Nómograma Halabi 2014: grupo {halabi_group} — mediana OS {halabi_os} meses",
                f"  • Supervivencia a 12 meses estimada: "
                f"{halabi.get('survival_probabilities', {}).get('os_12m', 'N/D')}",
            ]

        # State-based anchor
        state = coerce_text(assessment.current_state).lower()
        if "m1_crpc" in state or "m1b_crpc" in state:
            lines.append(
                "  • Contexto: mCRPC post-todas-las-líneas — expectativa de vida habitualmente <12 meses"
            )
        elif "crpc" in state:
            lines.append(
                "  • Contexto: CRPC — mediana OS 13-36 meses dependiendo del tratamiento disponible"
            )

        if assessment.hospice_eligibility.is_eligible:
            lines += [
                "",
                "Recomendación de comunicación:",
                "  Usar marco SPIKES para conversación de objetivos del cuidado.",
                "  Explorar valores, miedos y preferencias del paciente antes de definir plan.",
                "  Documentar en expediente: decisiones de resucitación, soporte ventilatorio,",
                "  alimentación artificial, y preferencia de lugar de fallecimiento.",
            ]

        return "\n".join(lines)

    # ── Clinical Narrative ───────────────────────────────────────────────────

    @classmethod
    def _build_narrative(cls, assessment: TerminalCareAssessment) -> str:
        """Generate full Spanish clinical narrative for terminal care."""
        lines = [
            "═══ EVALUACIÓN VÍA CUIDADO TERMINAL ═══",
            f"Estado clínico actual: {assessment.current_state or 'no especificado'}",
            "",
        ]

        # PCWG3
        p = assessment.pcwg3_progression
        lines.append("CRITERIOS PCWG3:")
        if p.meets_pcwg3_criteria:
            lines.append("  ✓ Cumple criterios PCWG3 de progresión radiográfica/PSA")
            if p.psa_progression:
                lines.append(f"    → PSA: {p.psa_details}")
            if p.radiographic_bone:
                lines.append(f"    → Óseo: {p.imaging_details}")
            if p.radiographic_soft_tissue:
                lines.append(f"    → Tejido blando: {p.imaging_details}")
        else:
            lines.append("  Sin criterios PCWG3 activos en este momento")

        # Symptoms
        lines += ["", "CARGA SINTOMÁTICA:"]
        if assessment.symptom_burden.active_symptoms:
            for sym in assessment.symptom_burden.active_symptoms:
                lines.append(f"  • {sym.replace('_', ' ').title()}")
        else:
            lines.append("  Sin síntomas activos documentados")

        # Emergencies
        if assessment.emergency_alerts:
            lines += ["", "⚠️ ALERTAS DE URGENCIA:"]
            for alert in assessment.emergency_alerts:
                lines.append(f"  {alert}")

        # Hospice
        h = assessment.hospice_eligibility
        lines += [
            "",
            "ELEGIBILIDAD HOSPICIO / CUIDADOS PALIATIVOS AVANZADOS:",
            f"  {'ELEGIBLE' if h.is_eligible else 'No elegible en este momento'}",
            f"  Criterios cumplidos: {len(h.criteria_met)}/{len(HOSPICE_CRITERIA)}",
        ]
        if h.criteria_met:
            for c in h.criteria_met[:3]:  # Show top 3
                lines.append(f"    ✓ {c}")

        # MDT
        if assessment.mdt_referrals:
            lines += ["", "DERIVACIONES MDT RECOMENDADAS:"]
            for ref in assessment.mdt_referrals:
                lines.append(f"  → {ref}")

        # Goals
        lines += ["", "OBJETIVOS DEL CUIDADO:", f"  {assessment.goals_of_care}"]

        return "\n".join(lines)

    # ── Utility helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _extract_psa_series(patient: dict[str, Any]) -> list[tuple[str, float]]:
        visits = normalize_followup_entries(
            patient.get("follow_up_visits") or patient.get("follow_ups") or []
        )
        series: list[tuple[str, float]] = []
        for v in visits:
            psa = v.get("psa_current") or v.get("psa")
            date = v.get("visit_date", "")
            if psa is not None:
                try:
                    series.append((str(date), float(psa)))
                except (TypeError, ValueError):
                    pass
        return sorted(series, key=lambda x: x[0])

    @staticmethod
    def _get_ecog(patient: dict[str, Any]) -> float | None:
        ecog = patient.get("ecog") or patient.get("performance_status")
        if ecog is not None:
            try:
                return float(ecog)
            except (TypeError, ValueError):
                pass
        visits = normalize_followup_entries(
            patient.get("follow_up_visits") or patient.get("follow_ups") or []
        )
        for v in sorted(visits, key=lambda x: x.get("visit_date", ""), reverse=True):
            val = v.get("ecog") or v.get("performance_status")
            if val is not None:
                try:
                    return float(val)
                except (TypeError, ValueError):
                    pass
        return None

    @staticmethod
    def _get_lab(patient: dict[str, Any], lab_name: str) -> float | None:
        aliases = {
            "ldh":        ["ldh", "lactate_dehydrogenase"],
            "alp":        ["alp", "alkaline_phosphatase", "fosfatasa_alcalina"],
            "albumin":    ["albumin", "albumina"],
            "hemoglobin": ["hemoglobin", "hgb", "hemoglobina", "hb"],
        }
        for alias in aliases.get(lab_name, [lab_name]):
            val = patient.get(alias)
            if val is not None:
                try:
                    return float(val)
                except (TypeError, ValueError):
                    pass
        labs = patient.get("latest_labs") or {}
        for alias in aliases.get(lab_name, [lab_name]):
            val = labs.get(alias)
            if val is not None:
                try:
                    return float(val)
                except (TypeError, ValueError):
                    pass
        return None

    @staticmethod
    def _get_from_visits(
        patient: dict[str, Any], field: str
    ) -> Any:
        visits = normalize_followup_entries(
            patient.get("follow_up_visits") or patient.get("follow_ups") or []
        )
        for v in sorted(visits, key=lambda x: x.get("visit_date", ""), reverse=True):
            val = v.get(field)
            if val is not None:
                return val
        return None


# ══════════════════════════════════════════════════════════════════════════════
# Convenience function
# ══════════════════════════════════════════════════════════════════════════════

def assess_terminal_care(patient: dict[str, Any]) -> dict[str, Any]:
    """Convenience wrapper for `TerminalCarePathway.assess(patient)`."""
    return TerminalCarePathway.assess(patient)
