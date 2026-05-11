# -*- coding: utf-8 -*-
"""
Plan de cuidado de sobrevivencia para cáncer de próstata.

Genera un plan personalizado de vigilancia post-tratamiento que incluye:
  - Calendario de seguimiento según track de manejo
  - Monitoreo de efectos tardíos (cardiovascular, óseo, metabólico, sexual, urinario)
  - Recomendaciones de estilo de vida
  - Screening de segundas neoplasias
  - Soporte psicosocial

Referencia:
  NCCN Survivorship Guidelines 2026
  ASCO Cancer Survivorship Care Planning
  ICHOM Standard Set for Localized Prostate Cancer
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)


# ── Efectos tardíos por tratamiento ──────────────────────────────────────────

LATE_EFFECTS: dict[str, list[dict[str, str]]] = {
    "prostatectomy": [
        {"effect": "Incontinencia urinaria", "monitoring": "IPSS, pad count cada 3-6 meses primer año", "intervention": "Kegel, fisioterapia pélvica, sling/esfínter si persiste >12 meses"},
        {"effect": "Disfunción eréctil", "monitoring": "IIEF-5 cada 3-6 meses", "intervention": "PDE5i temprano, dispositivos de vacío, inyecciones intracavernosas, prótesis"},
        {"effect": "Estenosis anastomótica", "monitoring": "Uroflujometría si síntomas obstructivos", "intervention": "Dilatación o uretrotomía"},
    ],
    "radiation": [
        {"effect": "Proctitis/sangrado rectal", "monitoring": "Evaluación de síntomas GI cada visita", "intervention": "Sucrosa, argon plasma si persiste"},
        {"effect": "Cistitis actínica", "monitoring": "Uroanálisis, IPSS", "intervention": "Hialuronato intravesical, oxigenoterapia hiperbárica"},
        {"effect": "Disfunción eréctil", "monitoring": "IIEF-5 cada 6 meses", "intervention": "PDE5i, terapia combinada"},
        {"effect": "Segundas neoplasias (recto, vejiga)", "monitoring": "Screening según síntomas, colonoscopía según edad", "intervention": "Referencia a especialista"},
    ],
    "adt": [
        {"effect": "Osteoporosis / fracturas", "monitoring": "DXA cada 24 meses, calcio/vitamina D", "intervention": "Denosumab o zoledronato si T-score ≤-2.5 o fractura"},
        {"effect": "Síndrome metabólico", "monitoring": "Glucosa, HbA1c, perfil lipídico, perímetro abdominal cada 6 meses", "intervention": "Ejercicio, dieta, metformina/estatina según criterio"},
        {"effect": "Riesgo cardiovascular", "monitoring": "Evaluación CV cada 6-12 meses, ECG anual", "intervention": "Control factores de riesgo, referencia cardiología si alto riesgo"},
        {"effect": "Deterioro cognitivo", "monitoring": "Screening cognitivo si síntomas", "intervention": "Ejercicio aeróbico, evaluación neuropsicológica"},
        {"effect": "Fatiga", "monitoring": "FACIT-Fatigue cada visita", "intervention": "Ejercicio estructurado, evaluar anemia y depresión"},
        {"effect": "Bochornos", "monitoring": "Evaluación de QoL", "intervention": "Venlafaxina, gabapentina, acupuntura"},
        {"effect": "Sarcopenia / pérdida muscular", "monitoring": "Fuerza de prensión, composición corporal", "intervention": "Ejercicio de resistencia supervisado"},
    ],
    "chemotherapy": [
        {"effect": "Neuropatía periférica", "monitoring": "Evaluación sensitiva cada visita", "intervention": "Duloxetina, gabapentina, fisioterapia"},
        {"effect": "Fatiga persistente", "monitoring": "FACIT-Fatigue", "intervention": "Ejercicio gradual, screening de depresión"},
        {"effect": "Inmunodepresión residual", "monitoring": "BH completa cada 3-6 meses primer año", "intervention": "Vacunación actualizada según esquema"},
    ],
}

LIFESTYLE_RECOMMENDATIONS: list[dict[str, str]] = [
    {"area": "Ejercicio", "recommendation": "≥150 min/semana de actividad aeróbica moderada + 2-3 sesiones/semana de resistencia (NCCN Survivorship)", "evidence": "Nivel 1"},
    {"area": "Dieta", "recommendation": "Dieta mediterránea o basada en plantas. Limitar carnes rojas procesadas, grasas saturadas. Calcio 1200mg/día + Vitamina D 1000-2000 UI/día", "evidence": "Nivel 2"},
    {"area": "Peso", "recommendation": "Mantener IMC 18.5-24.9. Reducción de peso si IMC >25, especialmente bajo ADT", "evidence": "Nivel 2"},
    {"area": "Alcohol", "recommendation": "Limitar a ≤2 bebidas/día", "evidence": "Nivel 2"},
    {"area": "Tabaco", "recommendation": "Cesación completa. Referir a programa de cesación si fumador activo", "evidence": "Nivel 1"},
    {"area": "Salud ósea", "recommendation": "Ejercicio de impacto, calcio + vitamina D, evitar caídas", "evidence": "Nivel 1"},
    {"area": "Salud mental", "recommendation": "Screening de depresión y ansiedad (PHQ-9, GAD-7). Referir a psico-oncología si positivo", "evidence": "Nivel 2"},
]


class SurvivorshipCarePlan:
    """Genera un plan de cuidado de sobrevivencia personalizado."""

    @classmethod
    def generate(cls, patient: dict[str, Any], state: str, management_track: str) -> dict[str, Any]:
        """
        Genera plan de sobrevivencia basado en tratamientos recibidos y estado actual.

        Args:
            patient: Registro completo del paciente.
            state: Estado clínico actual.
            management_track: Track de manejo actual.

        Returns:
            Dict con plan de sobrevivencia estructurado.
        """
        identity = patient.get("identity", {})
        prior = patient.get("prior_history", {}) or {}
        baseline = patient.get("baseline", {}) or {}
        followups = patient.get("follow_ups", []) or []

        treatments_received = cls._identify_treatments(prior)
        late_effects = cls._applicable_late_effects(treatments_received)

        # Enrich with RT-specific toxicity data from radiotherapy_detail module
        try:
            from prostanet.domains.patient_tracking.radiotherapy_detail import RadiotherapyDetailService
            rt_summary = RadiotherapyDetailService.build_rt_history(patient)
            if rt_summary and rt_summary.courses:
                for course in rt_summary.courses:
                    for tox in course.toxicity:
                        if tox.phase == "late" and tox.grade >= 2:
                            late_effects.append({
                                "effect": f"Toxicidad {tox.domain} tardía grado {tox.grade} — curso {course.modality}",
                                "monitoring": f"Evaluación {tox.domain} cada 3-6 meses",
                                "intervention": tox.details or "Según protocolo institucional",
                                "treatment_source": "radiation_detail",
                                "documented_grade": tox.grade,
                            })
        except Exception:
            pass

        return {
            "generated_date": date.today().isoformat(),
            "patient_age": identity.get("age") or identity.get("edad"),
            "clinical_state": state,
            "management_track": management_track,
            "treatments_received": treatments_received,
            "surveillance_schedule": cls._surveillance_schedule(management_track),
            "late_effects_monitoring": late_effects,
            "cardiovascular_risk": cls._cv_risk_assessment(prior, followups, baseline),
            "bone_health": cls._bone_health_assessment(prior, followups, baseline),
            "sexual_health": cls._sexual_health(prior, followups),
            "urinary_function": cls._urinary_function(prior, followups),
            "psychosocial": cls._psychosocial_screening(followups),
            "lifestyle_recommendations": LIFESTYLE_RECOMMENDATIONS,
            "secondary_cancer_screening": cls._secondary_screening(treatments_received, identity),
            "immunization_status": cls._immunization_notes(treatments_received),
        }

    @staticmethod
    def _identify_treatments(prior: dict) -> list[str]:
        treatments: list[str] = []
        if prior.get("prior_rp"):
            treatments.append("prostatectomy")
        if prior.get("prior_rt"):
            treatments.append("radiation")
        if prior.get("prior_adt"):
            treatments.append("adt")
        if prior.get("prior_docetaxel") or prior.get("prior_cabazitaxel"):
            treatments.append("chemotherapy")
        return treatments

    @classmethod
    def _applicable_late_effects(cls, treatments: list[str]) -> list[dict[str, str]]:
        effects: list[dict[str, str]] = []
        seen = set()
        for tx in treatments:
            for effect in LATE_EFFECTS.get(tx, []):
                key = effect["effect"]
                if key not in seen:
                    seen.add(key)
                    effects.append({**effect, "treatment_source": tx})
        return effects

    @staticmethod
    def _surveillance_schedule(track: str) -> dict[str, Any]:
        from prostanet.domains.patient_tracking.schedule_engine import SURVEILLANCE_PROTOCOLS
        protocols = SURVEILLANCE_PROTOCOLS.get(track, [])
        return {
            "management_track": track,
            "protocol_events": [
                {"event": p["label"], "guideline": p.get("guideline", "")}
                for p in protocols
            ],
        }

    @staticmethod
    def _cv_risk_assessment(prior: dict, followups: list, baseline: dict) -> dict[str, Any]:
        last_fu = followups[-1] if followups else {}
        on_adt = bool(prior.get("prior_adt"))
        return {
            "adt_exposure": on_adt,
            "adt_duration_months": prior.get("adt_duration_months"),
            "systolic_bp": last_fu.get("systolic_bp"),
            "hba1c": last_fu.get("hba1c"),
            "total_cholesterol": last_fu.get("total_cholesterol"),
            "hdl_cholesterol": last_fu.get("hdl_cholesterol"),
            "triglycerides": last_fu.get("triglycerides"),
            "waist_circumference_cm": last_fu.get("waist_circumference_cm"),
            "recommendations": [
                "Evaluación CV basal y cada 6-12 meses bajo ADT",
                "Perfil lipídico y glucosa cada 6 meses",
                "ECG anual si ADT prolongada",
                "Referencia a cardiología si ≥2 factores de riesgo CV",
            ] if on_adt else [
                "Seguimiento CV según riesgo basal",
            ],
        }

    @staticmethod
    def _bone_health_assessment(prior: dict, followups: list, baseline: dict) -> dict[str, Any]:
        last_fu = followups[-1] if followups else {}
        on_adt = bool(prior.get("prior_adt"))
        return {
            "adt_exposure": on_adt,
            "dxa_t_score_lumbar": last_fu.get("dxa_t_score_lumbar"),
            "dxa_t_score_hip": last_fu.get("dxa_t_score_hip"),
            "vitamin_d_level": last_fu.get("vitamin_d_level"),
            "calcium_level": last_fu.get("calcium_level"),
            "on_bone_protective_agent": prior.get("on_denosumab") or prior.get("on_zoledronate"),
            "recommendations": [
                "DXA basal y cada 24 meses bajo ADT",
                "Calcio 1200 mg/día + Vitamina D 1000-2000 UI/día",
                "Evaluación riesgo FRAX",
                "Denosumab/zoledronato si T-score ≤-2.5 o fractura por fragilidad",
            ] if on_adt else [
                "DXA según edad y factores de riesgo",
            ],
        }

    @staticmethod
    def _sexual_health(prior: dict, followups: list) -> dict[str, Any]:
        last_fu = followups[-1] if followups else {}
        had_rp = bool(prior.get("prior_rp"))
        had_rt = bool(prior.get("prior_rt"))
        had_adt = bool(prior.get("prior_adt"))
        return {
            "risk_factors": [
                t for t, cond in [
                    ("Prostatectomía radical", had_rp),
                    ("Radioterapia", had_rt),
                    ("ADT", had_adt),
                ] if cond
            ],
            "iief5_score": last_fu.get("iief5_score"),
            "nerve_sparing": prior.get("nerve_sparing", ""),
            "recommendations": [
                "Rehabilitación peneana temprana post-RP (PDE5i diario desde catéter)",
                "IIEF-5 cada 3-6 meses primer año",
                "Escalar: PDE5i → inyecciones intracavernosas → prótesis",
            ] if had_rp else [
                "Evaluación función sexual periódica",
                "PDE5i si disfunción bajo ADT/RT",
            ],
        }

    @staticmethod
    def _urinary_function(prior: dict, followups: list) -> dict[str, Any]:
        last_fu = followups[-1] if followups else {}
        return {
            "ipss_score": last_fu.get("ipss_score"),
            "continence_status": prior.get("continence_status", ""),
            "pad_count_daily": last_fu.get("pad_count"),
            "recommendations": [
                "IPSS cada visita de seguimiento",
                "Ejercicios de Kegel supervisados",
                "Referencia a fisioterapia pélvica si incontinencia persiste >6 meses post-RP",
            ],
        }

    @staticmethod
    def _psychosocial_screening(followups: list) -> dict[str, Any]:
        last_fu = followups[-1] if followups else {}
        return {
            "phq9_score": last_fu.get("phq9_score"),
            "gad7_score": last_fu.get("gad7_score"),
            "distress_score": last_fu.get("distress_score"),
            "recommendations": [
                "Screening de distress con termómetro NCCN cada visita",
                "PHQ-9 y GAD-7 al menos cada 6 meses",
                "Referir a psico-oncología si PHQ-9 ≥10 o GAD-7 ≥10",
                "Considerar grupos de apoyo entre pares",
                "Evaluar impacto en pareja/familia",
            ],
        }

    @staticmethod
    def _secondary_screening(treatments: list[str], identity: dict) -> list[dict[str, str]]:
        screenings: list[dict[str, str]] = []
        age = identity.get("age") or identity.get("edad") or 0
        try:
            age = int(age)
        except (ValueError, TypeError):
            age = 0

        if "radiation" in treatments:
            screenings.append({
                "screening": "Cáncer de recto/vejiga",
                "rationale": "Riesgo aumentado post-RT pélvica",
                "recommendation": "Colonoscopía según guías de edad; uroanálisis anual",
            })

        screenings.append({
            "screening": "Cáncer colorrectal",
            "rationale": "Screening por edad ≥45",
            "recommendation": "Colonoscopía cada 10 años (o según historial familiar)",
        })

        if age >= 55:
            screenings.append({
                "screening": "Cáncer de pulmón",
                "rationale": "Si historial de tabaquismo ≥20 paq-año",
                "recommendation": "TC de baja dosis anual si criterios NLST",
            })

        return screenings

    @staticmethod
    def _immunization_notes(treatments: list[str]) -> list[str]:
        notes = [
            "Influenza anual",
            "COVID-19 según esquema vigente",
            "Neumococo (PCV20 o PCV15+PPSV23) si >65 años o inmunocompromiso",
            "Herpes zóster (Shingrix) si >50 años",
        ]
        if "chemotherapy" in treatments:
            notes.append("Verificar inmunidad post-quimioterapia; considerar revacunación 3-6 meses post-tratamiento")
        return notes
