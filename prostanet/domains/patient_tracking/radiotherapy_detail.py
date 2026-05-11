# -*- coding: utf-8 -*-
"""
Módulo de radioterapia detallada para cáncer de próstata.

Captura estructurada de modalidad, dosis, fraccionamiento, campo,
distinción adyuvante/salvamento, terapia metástasis-dirigida (MDT),
contexto de ADT concurrente y toxicidad GU/GI específica.

Referencia:
  NCCN 2026 Prostate Cancer (Radiation Therapy)
  EAU 2026 Localized Prostate Cancer
  RADICALS-RT / RAVES (adjuvant vs salvage RT)
  CHHiP (hypofractionation)
  PACE-B (SBRT)
  STAMPEDE RT arm
  GETUG-AFU 16 (salvage RT + ADT)
  STOMP / ORIOLE / SABR-COMET (MDT)
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

from prostanet.shared.presentation_text import resolve_option_label

logger = logging.getLogger(__name__)


# ── Constantes ───────────────────────────────────────────────────────────────

RT_INTENTS = ("definitive", "adjuvant", "salvage", "palliative", "MDT")
RT_MODALITIES = ("EBRT_IMRT", "EBRT_VMAT", "SBRT", "LDR_brachy", "HDR_brachy", "protons", "combined")
RT_TARGET_VOLUMES = (
    "prostate_only", "prostate_sv", "whole_pelvis",
    "boost_dominant", "metastasis_directed", "prostate_pelvis_boost",
)

# Rangos de dosis estándar aceptados (Gy) por modalidad
STANDARD_FRACTIONATION = {
    "EBRT_IMRT": {"total_gy_range": (74, 81), "fraction_gy_range": (1.8, 2.0), "fractions_range": (37, 45)},
    "EBRT_VMAT": {"total_gy_range": (74, 81), "fraction_gy_range": (1.8, 2.0), "fractions_range": (37, 45)},
    "SBRT": {"total_gy_range": (35, 40), "fraction_gy_range": (7.0, 8.0), "fractions_range": (5, 5)},
    "LDR_brachy": {"total_gy_range": (140, 160), "fraction_gy_range": (140, 160), "fractions_range": (1, 1)},
    "HDR_brachy": {"total_gy_range": (13.5, 27), "fraction_gy_range": (6.5, 13.5), "fractions_range": (2, 4)},
    "protons": {"total_gy_range": (74, 82), "fraction_gy_range": (1.8, 2.2), "fractions_range": (37, 44)},
}

# Hipofraccionamiento moderado aceptado
MODERATE_HYPOFRACTIONATION = {
    "CHHiP": {"total_gy": 60, "fractions": 20, "fraction_gy": 3.0},
    "PROFIT": {"total_gy": 60, "fractions": 20, "fraction_gy": 3.0},
    "RTOG_0415": {"total_gy": 70, "fractions": 28, "fraction_gy": 2.5},
}

# Duración ADT recomendada por grupo de riesgo (meses)
ADT_DURATION_BY_RISK = {
    "intermediate_unfavorable": {"min_months": 4, "max_months": 6, "reference": "NCCN 2026: ADT 4-6mo"},
    "high": {"min_months": 18, "max_months": 36, "reference": "NCCN 2026: ADT 18-36mo; STAMPEDE"},
    "very_high": {"min_months": 24, "max_months": 36, "reference": "NCCN 2026: ADT 24-36mo; STAMPEDE"},
}


# ── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class RTToxicityRecord:
    """Registro de toxicidad específica de radioterapia (RTOG/CTCAE)."""
    domain: str  # "GU" | "GI"
    phase: str   # "acute" (≤90 días) | "late" (>90 días)
    grade: int   # 0-4 (RTOG/CTCAE)
    details: str = ""
    onset_date: str = ""
    evidence_tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MDTSiteDetail:
    """Detalle de un sitio tratado con terapia metástasis-dirigida."""
    site_location: str  # "vertebra_L3", "iliac_bone", "retroperitoneal_node", etc.
    modality: str       # "SBRT", "IMRT", etc.
    dose_gy: float = 0.0
    fractions: int = 0
    dose_per_fraction_gy: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DetailedRadiotherapyCourse:
    """Curso completo de radioterapia con todos los detalles técnicos y clínicos."""
    rt_id: int | None = None
    rt_intent: str = ""         # una de RT_INTENTS
    modality: str = ""          # una de RT_MODALITIES
    target_volume: str = ""     # una de RT_TARGET_VOLUMES
    total_dose_gy: float = 0.0
    fractions: int = 0
    dose_per_fraction_gy: float = 0.0
    boost_dose_gy: float | None = None
    boost_technique: str | None = None
    rt_start_date: str = ""
    rt_end_date: str = ""
    # ── Contexto ADT ──
    concurrent_adt: bool = False
    adt_neoadjuvant_months: float | None = None
    adt_concurrent: bool = False
    adt_adjuvant_months: float | None = None
    adt_total_planned_months: float | None = None
    # ── Salvamento específico ──
    salvage_psa_at_start: float | None = None
    salvage_pre_imaging: str | None = None  # "conventional", "PSMA-PET", "none"
    salvage_nodal_coverage: bool | None = None
    # ── MDT específico ──
    mdt_sites_treated: int | None = None
    mdt_site_details: list[MDTSiteDetail] = field(default_factory=list)
    # ── Toxicidad ──
    toxicity: list[RTToxicityRecord] = field(default_factory=list)
    # ── Evidencia ──
    evidence_tags: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rt_id": self.rt_id,
            "rt_intent": self.rt_intent,
            "modality": self.modality,
            "target_volume": self.target_volume,
            "total_dose_gy": self.total_dose_gy,
            "fractions": self.fractions,
            "dose_per_fraction_gy": self.dose_per_fraction_gy,
            "boost_dose_gy": self.boost_dose_gy,
            "boost_technique": self.boost_technique,
            "rt_start_date": self.rt_start_date,
            "rt_end_date": self.rt_end_date,
            "concurrent_adt": self.concurrent_adt,
            "adt_neoadjuvant_months": self.adt_neoadjuvant_months,
            "adt_concurrent": self.adt_concurrent,
            "adt_adjuvant_months": self.adt_adjuvant_months,
            "adt_total_planned_months": self.adt_total_planned_months,
            "salvage_psa_at_start": self.salvage_psa_at_start,
            "salvage_pre_imaging": self.salvage_pre_imaging,
            "salvage_nodal_coverage": self.salvage_nodal_coverage,
            "mdt_sites_treated": self.mdt_sites_treated,
            "mdt_site_details": [s.to_dict() for s in self.mdt_site_details],
            "toxicity": [t.to_dict() for t in self.toxicity],
            "evidence_tags": list(self.evidence_tags),
            "notes": self.notes,
        }


@dataclass
class RTHistorySummary:
    """Resumen consolidado de toda la historia de radioterapia del paciente."""
    patient_id: int | None = None
    courses: list[DetailedRadiotherapyCourse] = field(default_factory=list)
    total_courses: int = 0
    has_definitive_rt: bool = False
    has_adjuvant_rt: bool = False
    has_salvage_rt: bool = False
    has_palliative_rt: bool = False
    has_mdt: bool = False
    cumulative_gu_toxicity_max: int = 0
    cumulative_gi_toxicity_max: int = 0
    prior_pelvic_rt: bool = False
    cumulative_pelvic_dose_gy: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "patient_id": self.patient_id,
            "courses": [c.to_dict() for c in self.courses],
            "total_courses": self.total_courses,
            "has_definitive_rt": self.has_definitive_rt,
            "has_adjuvant_rt": self.has_adjuvant_rt,
            "has_salvage_rt": self.has_salvage_rt,
            "has_palliative_rt": self.has_palliative_rt,
            "has_mdt": self.has_mdt,
            "cumulative_gu_toxicity_max": self.cumulative_gu_toxicity_max,
            "cumulative_gi_toxicity_max": self.cumulative_gi_toxicity_max,
            "prior_pelvic_rt": self.prior_pelvic_rt,
            "cumulative_pelvic_dose_gy": self.cumulative_pelvic_dose_gy,
        }


# ── Funciones auxiliares ─────────────────────────────────────────────────────

def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, "", "No aplica"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, "", "No aplica"):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


# ── Servicio principal ───────────────────────────────────────────────────────

class RadiotherapyDetailService:
    """Servicio de radioterapia detallada con validación clínica e integración al ecosistema."""

    @staticmethod
    def parse_rt_course(data: dict[str, Any]) -> DetailedRadiotherapyCourse:
        """Parsea datos crudos de un curso de RT en una estructura detallada."""
        toxicity_data = data.get("toxicity", [])
        toxicity_records = [
            RTToxicityRecord(
                domain=t.get("domain", ""),
                phase=t.get("phase", ""),
                grade=_safe_int(t.get("grade")) or 0,
                details=t.get("details", ""),
                onset_date=t.get("onset_date", ""),
            )
            for t in toxicity_data
        ]

        mdt_details_data = data.get("mdt_site_details", [])
        mdt_details = [
            MDTSiteDetail(
                site_location=s.get("site_location", ""),
                modality=s.get("modality", ""),
                dose_gy=_safe_float(s.get("dose_gy")) or 0.0,
                fractions=_safe_int(s.get("fractions")) or 0,
                dose_per_fraction_gy=_safe_float(s.get("dose_per_fraction_gy")) or 0.0,
            )
            for s in mdt_details_data
        ]

        total_dose = _safe_float(data.get("total_dose_gy")) or 0.0
        fractions = _safe_int(data.get("fractions")) or 0
        dose_per_fraction = _safe_float(data.get("dose_per_fraction_gy"))
        if dose_per_fraction is None and total_dose > 0 and fractions > 0:
            dose_per_fraction = round(total_dose / fractions, 2)

        return DetailedRadiotherapyCourse(
            rt_id=_safe_int(data.get("rt_id")),
            rt_intent=data.get("rt_intent", ""),
            modality=data.get("modality", ""),
            target_volume=data.get("target_volume", ""),
            total_dose_gy=total_dose,
            fractions=fractions,
            dose_per_fraction_gy=dose_per_fraction or 0.0,
            boost_dose_gy=_safe_float(data.get("boost_dose_gy")),
            boost_technique=data.get("boost_technique"),
            rt_start_date=data.get("rt_start_date", ""),
            rt_end_date=data.get("rt_end_date", ""),
            concurrent_adt=bool(data.get("concurrent_adt", False)),
            adt_neoadjuvant_months=_safe_float(data.get("adt_neoadjuvant_months")),
            adt_concurrent=bool(data.get("adt_concurrent", False)),
            adt_adjuvant_months=_safe_float(data.get("adt_adjuvant_months")),
            adt_total_planned_months=_safe_float(data.get("adt_total_planned_months")),
            salvage_psa_at_start=_safe_float(data.get("salvage_psa_at_start")),
            salvage_pre_imaging=data.get("salvage_pre_imaging"),
            salvage_nodal_coverage=data.get("salvage_nodal_coverage"),
            mdt_sites_treated=_safe_int(data.get("mdt_sites_treated")),
            mdt_site_details=mdt_details,
            toxicity=toxicity_records,
            evidence_tags=data.get("evidence_tags", []),
            notes=data.get("notes", ""),
        )

    @staticmethod
    def build_rt_history(patient: dict[str, Any]) -> RTHistorySummary:
        """Construye resumen consolidado de toda la historia de RT del paciente."""
        rt_records = patient.get("radiation_details") or patient.get("radiation") or []
        if isinstance(rt_records, dict):
            rt_records = [rt_records]

        courses: list[DetailedRadiotherapyCourse] = []
        for record in rt_records:
            if isinstance(record, dict):
                courses.append(RadiotherapyDetailService.parse_rt_course(record))

        intents = {c.rt_intent for c in courses}
        pelvic_volumes = {"prostate_only", "prostate_sv", "whole_pelvis", "prostate_pelvis_boost"}
        pelvic_courses = [c for c in courses if c.target_volume in pelvic_volumes]

        # Toxicidad acumulada
        gu_max = 0
        gi_max = 0
        for course in courses:
            for tox in course.toxicity:
                if tox.domain == "GU":
                    gu_max = max(gu_max, tox.grade)
                elif tox.domain == "GI":
                    gi_max = max(gi_max, tox.grade)

        return RTHistorySummary(
            patient_id=_safe_int(patient.get("patient_id") or patient.get("nss")),
            courses=courses,
            total_courses=len(courses),
            has_definitive_rt="definitive" in intents,
            has_adjuvant_rt="adjuvant" in intents,
            has_salvage_rt="salvage" in intents,
            has_palliative_rt="palliative" in intents,
            has_mdt="MDT" in intents,
            cumulative_gu_toxicity_max=gu_max,
            cumulative_gi_toxicity_max=gi_max,
            prior_pelvic_rt=len(pelvic_courses) > 0,
            cumulative_pelvic_dose_gy=sum(c.total_dose_gy for c in pelvic_courses),
        )

    @staticmethod
    def classify_rt_intent(
        patient: dict[str, Any],
        state: str,
        rt_context: str = "",
    ) -> str:
        """Clasifica la intención de RT basándose en contexto clínico."""
        if state == "localized_initial":
            return "definitive"
        if state == "post_prostatectomy":
            psa_postop = _safe_float(patient.get("psa_postop"))
            if psa_postop is not None and psa_postop < 0.1:
                return "adjuvant"  # PSA indetectable → adyuvante
            return "salvage"       # PSA detectable → salvamento
        if state == "recurrence_bcr":
            return "salvage"
        if state in ("mcspc_oligo_metachronous",):
            return "MDT"
        if rt_context == "palliative" or state in ("m1_crpc",):
            return "palliative"
        return rt_context or "definitive"

    @staticmethod
    def validate_fractionation(course: DetailedRadiotherapyCourse) -> list[str]:
        """Valida que el fraccionamiento esté dentro de rangos estándar publicados."""
        warnings: list[str] = []
        modality = course.modality

        if not modality or modality not in STANDARD_FRACTIONATION:
            return warnings

        std = STANDARD_FRACTIONATION[modality]

        # Verificar hipofraccionamiento moderado aceptado
        for hypo_name, hypo in MODERATE_HYPOFRACTIONATION.items():
            if (abs(course.total_dose_gy - hypo["total_gy"]) < 2
                    and abs(course.fractions - hypo["fractions"]) <= 1):
                return []  # Esquema reconocido

        total_range = std["total_gy_range"]
        if course.total_dose_gy > 0 and not (total_range[0] <= course.total_dose_gy <= total_range[1]):
            # Permitir tolerancia para MDT/palliativo
            if course.rt_intent not in ("palliative", "MDT"):
                warnings.append(
                    f"Dosis total {course.total_dose_gy} Gy fuera del rango estándar "
                    f"({total_range[0]}-{total_range[1]} Gy) para {modality}"
                )

        fraction_range = std["fraction_gy_range"]
        if course.dose_per_fraction_gy > 0 and not (fraction_range[0] <= course.dose_per_fraction_gy <= fraction_range[1]):
            if course.rt_intent not in ("palliative", "MDT"):
                warnings.append(
                    f"Dosis por fracción {course.dose_per_fraction_gy} Gy fuera del rango "
                    f"({fraction_range[0]}-{fraction_range[1]} Gy) para {modality}"
                )

        return warnings

    @staticmethod
    def evaluate_rt_alerts(
        patient_id: int,
        summary: RTHistorySummary,
        patient: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Genera alertas clínicas basadas en la historia de RT."""
        from prostanet.domains.patient_tracking.alert_engine import ClinicalAlert

        alerts: list[ClinicalAlert] = []

        for course in summary.courses:
            # 1. RT salvamento con PSA > 0.5 ng/mL
            if course.rt_intent == "salvage" and course.salvage_psa_at_start is not None:
                if course.salvage_psa_at_start > 0.5:
                    alerts.append(ClinicalAlert(
                        patient_id=patient_id,
                        alert_type="rt_salvage_psa_high",
                        severity="warning",
                        category="radiation_therapy",
                        title=f"PSA al salvamento: {course.salvage_psa_at_start:.2f} ng/mL",
                        message="El beneficio de la RT de salvamento decrece significativamente con PSA >0.5 ng/mL. Ventana óptima: PSA <0.2 ng/mL.",
                        recommended_action="Considerar inicio urgente de RT si no iniciada. Agregar ADT corto (6 meses) si PSA >0.5.",
                        guideline_reference="RAVES 2017; GETUG-AFU 16; NCCN 2026 BCR salvage RT",
                        triggering_value=f"{course.salvage_psa_at_start:.2f} ng/mL",
                        threshold=">0.5 ng/mL (óptimo <0.2)",
                    ))

            # 2. RT adyuvante sin factores adversos (potencialmente innecesaria)
            if course.rt_intent == "adjuvant" and patient:
                has_adverse = (
                    patient.get("surgical_margin") in ("positive", "Positivo", True, "1")
                    or patient.get("ece_status") in ("positive", "Positivo", True, "1")
                    or patient.get("svi_status") in ("positive", "Positivo", True, "1")
                    or patient.get("pathologic_stage") in ("pT3a", "pT3b", "pT4")
                )
                if not has_adverse:
                    alerts.append(ClinicalAlert(
                        patient_id=patient_id,
                        alert_type="rt_adjuvant_without_adverse",
                        severity="info",
                        category="radiation_therapy",
                        title="RT adyuvante sin factores adversos documentados",
                        message="Ensayos recientes (RADICALS-RT, RAVES) sugieren que la observación con RT de salvamento temprano no es inferior a la RT adyuvante en ausencia de factores adversos.",
                        recommended_action="Considerar observación con RT de salvamento temprano como alternativa.",
                        guideline_reference="RADICALS-RT 2020; RAVES 2019; ARTISTIC meta-analysis",
                        triggering_value="RT adyuvante",
                        threshold="Sin márgenes+, ECE, SVI documentados",
                    ))

            # 3. Validación de fraccionamiento
            fractionation_warnings = RadiotherapyDetailService.validate_fractionation(course)
            for warning in fractionation_warnings:
                alerts.append(ClinicalAlert(
                    patient_id=patient_id,
                    alert_type="rt_nonstandard_fractionation",
                    severity="warning",
                    category="radiation_therapy",
                    title="Fraccionamiento fuera de rango estándar",
                    message=warning,
                    recommended_action="Verificar prescripción. Si hipofraccionamiento intencional, documentar protocolo seguido.",
                    guideline_reference="CHHiP; PROFIT; RTOG 0415; PACE-B; NCCN 2026 RT",
                    triggering_value=f"{course.total_dose_gy} Gy / {course.fractions} fx",
                    threshold="Rangos publicados",
                ))

            # 4. Toxicidad tardía significativa
            for tox in course.toxicity:
                if tox.phase == "late" and tox.grade >= 2:
                    severity = "critical" if tox.grade >= 3 else "warning"
                    alerts.append(ClinicalAlert(
                        patient_id=patient_id,
                        alert_type=f"rt_late_toxicity_{tox.domain.lower()}",
                        severity=severity,
                        category="radiation_therapy",
                        title=f"Toxicidad {tox.domain} tardía grado {tox.grade}",
                        message=f"Toxicidad {tox.domain} tardía grado {tox.grade}: {tox.details}",
                        recommended_action=(
                            f"Referir gastroenterología. Considerar argon plasma o hialuronato." if tox.domain == "GI"
                            else f"Evaluación urológica. Considerar instilaciones intravesicales."
                        ),
                        guideline_reference="NCCN 2026 Survivorship; RTOG toxicity grading",
                        triggering_value=f"Grado {tox.grade}",
                        threshold="≥2 tardía",
                    ))

        # 5. Re-irradiación pélvica
        if summary.prior_pelvic_rt and summary.cumulative_pelvic_dose_gy > 70:
            new_pelvic = [c for c in summary.courses if c.target_volume in ("prostate_only", "prostate_sv", "whole_pelvis", "prostate_pelvis_boost")]
            if len(new_pelvic) > 1:
                alerts.append(ClinicalAlert(
                    patient_id=patient_id,
                    alert_type="rt_pelvic_reirradiation",
                    severity="critical",
                    category="radiation_therapy",
                    title=f"Re-irradiación pélvica — Dosis acumulada: {summary.cumulative_pelvic_dose_gy:.0f} Gy",
                    message="Múltiples cursos de RT pélvica documentados. Alto riesgo de toxicidad GU/GI tardía severa.",
                    recommended_action="Requiere discusión en tumor board. Evaluar técnicas de precisión (SBRT, protones).",
                    guideline_reference="NCCN 2026; EAU 2026 re-irradiation",
                    triggering_value=f"{summary.cumulative_pelvic_dose_gy:.0f} Gy acumulados",
                    threshold=">1 curso pélvico",
                ))

        # 6. ADT subóptima para RT definitiva de alto riesgo
        for course in summary.courses:
            if course.rt_intent == "definitive" and course.concurrent_adt and patient:
                risk_group = (patient.get("risk_group", "") or patient.get("clinical_risk_group", "")).lower()
                adt_total = course.adt_total_planned_months
                for risk_key, adt_config in ADT_DURATION_BY_RISK.items():
                    if risk_key in risk_group and adt_total is not None:
                        if adt_total < adt_config["min_months"]:
                            alerts.append(ClinicalAlert(
                                patient_id=patient_id,
                                alert_type="rt_adt_suboptimal_duration",
                                severity="warning",
                                category="radiation_therapy",
                                title=f"ADT planificada {adt_total:.0f}mo — subóptima para {risk_key}",
                                message=f"Para riesgo {risk_key}, las guías recomiendan ADT {adt_config['min_months']}-{adt_config['max_months']} meses.",
                                recommended_action=f"Considerar extender ADT a {adt_config['min_months']}-{adt_config['max_months']} meses.",
                                guideline_reference=adt_config["reference"],
                                triggering_value=f"{adt_total:.0f} meses",
                                threshold=f"{adt_config['min_months']}-{adt_config['max_months']} meses",
                            ))

        return [a.to_dict() for a in alerts]

    @staticmethod
    def build_rt_regimen_for_catalog(course: DetailedRadiotherapyCourse) -> dict[str, Any]:
        """Genera entrada de catálogo terapéutico compatible con therapy_catalog."""
        intent_labels = {
            "definitive": "RT definitiva",
            "adjuvant": "RT adyuvante post-PR",
            "salvage": "RT de salvamento",
            "palliative": "RT paliativa",
            "MDT": "RT metástasis-dirigida (MDT)",
        }
        modality_labels = {
            "EBRT_IMRT": "IMRT", "EBRT_VMAT": "VMAT", "SBRT": "SBRT",
            "LDR_brachy": "Braquiterapia LDR", "HDR_brachy": "Braquiterapia HDR",
            "protons": "Protones", "combined": "Combinada",
        }

        label = intent_labels.get(course.rt_intent, course.rt_intent)
        modality_label = modality_labels.get(course.modality, course.modality)
        dose_label = f"{course.total_dose_gy}Gy/{course.fractions}fx" if course.fractions else ""

        return {
            "regimen_code": f"RT_{course.rt_intent.upper()}_{course.modality}",
            "label_clinico": f"{label} — {modality_label} {dose_label}".strip(),
            "therapy_class": "radiation",
            "agents": [modality_label],
            "intent": course.rt_intent,
            "dose_summary": dose_label,
            "evidence_tags": course.evidence_tags,
        }

    @staticmethod
    def build_rt_summary_for_profile(summary: RTHistorySummary) -> dict[str, Any]:
        """Construye resumen de RT para mostrar en el perfil del paciente."""
        course_summaries = []
        for course in summary.courses:
            modality_label = {
                "EBRT_IMRT": "IMRT", "EBRT_VMAT": "VMAT", "SBRT": "SBRT",
                "LDR_brachy": "Braquiterapia LDR", "HDR_brachy": "Braquiterapia HDR",
                "protons": "Protones",
            }.get(course.modality, course.modality)
            intent_label = {
                "definitive": "Definitiva", "adjuvant": "Adyuvante",
                "salvage": "Salvamento", "palliative": "Paliativa", "MDT": "MDT",
            }.get(course.rt_intent, course.rt_intent)
            target_label = resolve_option_label(
                "target_volume",
                course.target_volume,
                ["", "prostate_only", "prostate_sv", "whole_pelvis", "boost_dominant", "metastasis_directed", "prostate_pelvis_boost"],
            )
            salvage_pre_imaging_label = resolve_option_label(
                "salvage_pre_imaging",
                course.salvage_pre_imaging,
                ["", "none", "ct_bone_scan", "psma_pet", "mpmri"],
            ) if course.salvage_pre_imaging else ""

            course_summaries.append({
                "intent": intent_label,
                "modality": modality_label,
                "dose": f"{course.total_dose_gy} Gy / {course.fractions} fx" if course.fractions else "",
                "target": target_label,
                "dates": f"{course.rt_start_date} — {course.rt_end_date}" if course.rt_start_date else "",
                "concurrent_adt": course.concurrent_adt,
                "adt_planned_months": course.adt_total_planned_months,
                "salvage_psa": course.salvage_psa_at_start,
                "salvage_pre_imaging": salvage_pre_imaging_label,
                "mdt_sites": course.mdt_sites_treated,
            })

        tone = "success"
        if summary.cumulative_gu_toxicity_max >= 3 or summary.cumulative_gi_toxicity_max >= 3:
            tone = "danger"
        elif summary.cumulative_gu_toxicity_max >= 2 or summary.cumulative_gi_toxicity_max >= 2:
            tone = "warning"

        return {
            "total_courses": summary.total_courses,
            "has_definitive": summary.has_definitive_rt,
            "has_adjuvant": summary.has_adjuvant_rt,
            "has_salvage": summary.has_salvage_rt,
            "has_palliative": summary.has_palliative_rt,
            "has_mdt": summary.has_mdt,
            "prior_pelvic_rt": summary.prior_pelvic_rt,
            "cumulative_pelvic_dose_gy": summary.cumulative_pelvic_dose_gy,
            "gu_toxicity_max": summary.cumulative_gu_toxicity_max,
            "gi_toxicity_max": summary.cumulative_gi_toxicity_max,
            "tone": tone,
            "courses": course_summaries,
        }
