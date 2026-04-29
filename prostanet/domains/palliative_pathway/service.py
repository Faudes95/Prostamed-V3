# -*- coding: utf-8 -*-
"""
Módulo de vía paliativa para cáncer de próstata avanzado.

Implementa:
  - Criterios de transición a mejor soporte de cuidado
  - Protocolo de manejo del dolor (escalera OMS adaptada a enfermedad ósea)
  - Indicaciones de radioterapia paliativa
  - Evaluación de cuidados paliativos concurrentes
  - Prompts de planificación anticipada de cuidados

Referencia:
  NCCN Palliative Care Guidelines 2026
  WHO Pain Relief Ladder (adapted)
  EAU 2026 — Best Supportive Care in mCRPC
  Temel JS et al. NEJM 2010 (Early palliative care)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PalliativeAssessment:
    """Evaluación paliativa integral."""
    transition_criteria_met: list[str]
    should_transition_to_bsc: bool
    pain_assessment: PainAssessment
    palliative_rt_indications: list[dict[str, str]]
    advance_care_planning: dict[str, Any]
    symptom_burden: dict[str, Any]
    concurrent_palliative_care: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


@dataclass
class PainAssessment:
    """Evaluación de dolor según escalera OMS adaptada."""
    pain_score: int | None  # 0-10 NRS
    pain_category: str  # "none", "mild", "moderate", "severe"
    bone_pain: bool
    neuropathic_component: bool
    current_analgesics: list[str]
    who_ladder_step: int  # 1-3
    recommendations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Criterios de transición a mejor soporte de cuidado ────────────────────

TRANSITION_CRITERIA = [
    {"criterion": "ecog_3_plus", "label": "ECOG ≥3", "check": lambda p: _safe_int(p.get("ecog") or p.get("ecog_score"), 0) >= 3},
    {"criterion": "lines_exhausted", "label": "≥3 líneas sistémicas agotadas", "check": lambda p: _safe_int(p.get("treatment_lines_exhausted") or p.get("prior_systemic_lines"), 0) >= 3},
    {"criterion": "patient_preference", "label": "Preferencia del paciente por confort", "check": lambda p: _is_true(p.get("patient_prefers_comfort") or p.get("preference_comfort_over_treatment"))},
    {"criterion": "refractory_pain", "label": "Dolor refractario a manejo estándar", "check": lambda p: _is_true(p.get("refractory_pain"))},
    {"criterion": "rapid_decline", "label": "Deterioro funcional rápido (ECOG +2 en <3 meses)", "check": lambda p: _safe_int(p.get("ecog_delta_3mo"), 0) >= 2},
    {"criterion": "visceral_crisis", "label": "Crisis visceral", "check": lambda p: _is_true(p.get("visceral_crisis"))},
]


class PalliativePathwayService:
    """Servicio de evaluación paliativa para cáncer de próstata avanzado."""

    @classmethod
    def full_assessment(cls, patient: dict[str, Any]) -> PalliativeAssessment:
        """Evaluación paliativa completa."""
        transition_criteria = cls._check_transition_criteria(patient)
        should_transition = len(transition_criteria) >= 2 or any(
            c in ("visceral_crisis", "patient_preference") for c in [t["criterion"] for t in transition_criteria]
        )

        return PalliativeAssessment(
            transition_criteria_met=[t["label"] for t in transition_criteria],
            should_transition_to_bsc=should_transition,
            pain_assessment=cls.assess_pain(patient),
            palliative_rt_indications=cls.palliative_rt_indications(patient),
            advance_care_planning=cls.advance_care_planning(patient),
            symptom_burden=cls.symptom_burden(patient),
            concurrent_palliative_care=cls.concurrent_palliative_recommendations(patient),
        )

    @staticmethod
    def _check_transition_criteria(patient: dict[str, Any]) -> list[dict[str, str]]:
        met: list[dict[str, str]] = []
        for crit in TRANSITION_CRITERIA:
            if crit["check"](patient):
                met.append({"criterion": crit["criterion"], "label": crit["label"]})
        return met

    @staticmethod
    def assess_pain(patient: dict[str, Any]) -> PainAssessment:
        """
        Evaluación de dolor con escalera OMS adaptada a enfermedad ósea.

        Paso 1: No opioides (paracetamol, AINEs)
        Paso 2: Opioides débiles (tramadol, codeína) ± adyuvantes
        Paso 3: Opioides fuertes (morfina, oxicodona, fentanilo) ± adyuvantes

        Adyuvantes para dolor óseo: denosumab, zoledronato, RT paliativa
        Adyuvantes para dolor neuropático: gabapentina, pregabalina, duloxetina
        """
        pain = _safe_int(patient.get("pain_score") or patient.get("bpi_worst_pain"), None)
        bone_pain = _is_true(patient.get("bone_pain") or patient.get("osseous_pain"))
        neuropathic = _is_true(patient.get("neuropathic_pain"))

        current_meds: list[str] = []
        for med_field in ("current_analgesics", "pain_medications", "analgesic_regimen"):
            val = patient.get(med_field)
            if val:
                if isinstance(val, list):
                    current_meds.extend(val)
                else:
                    current_meds.append(str(val))

        if pain is None:
            category = "not_assessed"
            step = 0
        elif pain == 0:
            category = "none"
            step = 0
        elif pain <= 3:
            category = "mild"
            step = 1
        elif pain <= 6:
            category = "moderate"
            step = 2
        else:
            category = "severe"
            step = 3

        recs: list[str] = []
        if category == "none":
            recs.append("Sin dolor actual — mantener vigilancia")
        elif category == "mild":
            recs.extend([
                "Paso 1 OMS: Paracetamol 1g c/6-8h ± AINE (ibuprofeno, diclofenaco)",
                "Precaución con AINEs si función renal comprometida o riesgo GI",
            ])
        elif category == "moderate":
            recs.extend([
                "Paso 2 OMS: Tramadol 50-100mg c/6-8h o codeína 30-60mg c/4-6h",
                "Mantener no opioides como base",
                "Considerar escalamiento a opioides fuertes si no hay respuesta en 48-72h",
            ])
        elif category == "severe":
            recs.extend([
                "Paso 3 OMS: Morfina oral 10-30mg c/4h (ajustar según respuesta)",
                "Alternativas: oxicodona, fentanilo transdérmico (en dolor estable)",
                "Rescates con morfina de liberación inmediata: 10-15% de la dosis diaria total",
                "Antiemético profiláctico las primeras 72h de opioides",
                "Laxante profiláctico obligatorio con opioides",
            ])

        if bone_pain:
            recs.extend([
                "Adyuvante óseo: considerar denosumab/zoledronato si no iniciado",
                "Evaluar RT paliativa para lesión ósea sintomática (8 Gy dosis única o 30 Gy/10 fx)",
                # Faubot 2026-04-24 — guardar consistencia con el gate
                # `no_bone_protective_agent` de pivotal_contraindication_gates:
                # ERA-223 (Smith Lancet Oncol 2019;20:408) demostró exceso de
                # fracturas con Ra-223 + abiraterona sin agente óseo (28% vs
                # 12%). PEACE-3 (Tombal ESMO 2024) volvió obligatorio el agente
                # óseo concomitante. Reflejamos ambos prerrequisitos en el
                # texto para que la rama paliativa no contradiga el filtro.
                (
                    "Considerar Ra-223 si metástasis óseas sintomáticas sin "
                    "metástasis viscerales — verificar agente protector óseo "
                    "(denosumab/zoledronato) iniciado ≥6 sem antes o concomitante "
                    "y NO combinar con abiraterona (ERA-223 / PEACE-3: exceso de "
                    "fracturas)"
                ),
            ])

        if neuropathic:
            recs.extend([
                "Componente neuropático: gabapentina 300mg nocturno, titular hasta 900-1800mg/día",
                "Alternativa: pregabalina 75mg c/12h, titular hasta 300mg/día",
                "Considerar duloxetina 30-60mg/día si componente mixto",
            ])

        if category == "not_assessed":
            recs.append("Evaluar dolor con escala NRS (0-10) o BPI-SF en cada visita")

        return PainAssessment(
            pain_score=pain,
            pain_category=category,
            bone_pain=bone_pain,
            neuropathic_component=neuropathic,
            current_analgesics=current_meds,
            who_ladder_step=step,
            recommendations=recs,
        )

    @staticmethod
    def palliative_rt_indications(patient: dict[str, Any]) -> list[dict[str, str]]:
        """Evaluación de indicaciones de RT paliativa."""
        indications: list[dict[str, str]] = []

        if _is_true(patient.get("bone_pain")):
            indications.append({
                "indication": "Dolor óseo localizado",
                "regimen": "8 Gy dosis única (equivalente a fraccionado para paliación)",
                "evidence": "Chow E et al. ASTRO 2017",
            })

        if _is_true(patient.get("spinal_cord_compression")) or _is_true(patient.get("epidural_compression")):
            indications.append({
                "indication": "Compresión medular — URGENCIA ONCOLÓGICA",
                "regimen": "Dexametasona IV urgente + RT 30 Gy/10 fx o cirugía descompresiva + RT",
                "evidence": "NCCN Oncologic Emergencies 2026",
            })

        if _is_true(patient.get("pathological_fracture_risk")):
            indications.append({
                "indication": "Riesgo de fractura patológica",
                "regimen": "RT profiláctica + evaluación ortopédica para fijación",
                "evidence": "NCCN Bone Health 2026",
            })

        if _is_true(patient.get("brain_metastasis")):
            indications.append({
                "indication": "Metástasis cerebrales",
                "regimen": "SRS si ≤4 lesiones, WBRT si múltiples",
                "evidence": "NCCN CNS Cancers 2026",
            })

        if _is_true(patient.get("obstructive_uropathy")):
            indications.append({
                "indication": "Obstrucción ureteral/urinaria por tumor local",
                "regimen": "RT paliativa local 30-45 Gy + stent si requiere descompresión urgente",
                "evidence": "EAU 2026",
            })

        if _is_true(patient.get("hematuria_severe")):
            indications.append({
                "indication": "Hematuria severa de origen prostático",
                "regimen": "RT hemostática 20-30 Gy/5-10 fx",
                "evidence": "Din OS et al. Int J Radiat Oncol 2013",
            })

        return indications

    @staticmethod
    def advance_care_planning(patient: dict[str, Any]) -> dict[str, Any]:
        """Evaluación de planificación anticipada de cuidados."""
        acp_documented = _is_true(patient.get("advance_directive_documented"))
        goals_discussed = _is_true(patient.get("goals_of_care_discussed"))
        surrogate_designated = _is_true(patient.get("healthcare_surrogate_designated"))

        completeness = sum([acp_documented, goals_discussed, surrogate_designated])

        prompts: list[str] = []
        if not goals_discussed:
            prompts.append(
                "Iniciar conversación de objetivos de cuidado: '¿Qué es lo más importante para usted en este momento de su tratamiento?'"
            )
        if not acp_documented:
            prompts.append(
                "Documentar voluntades anticipadas: preferencias sobre reanimación, ventilación mecánica, hospitalización"
            )
        if not surrogate_designated:
            prompts.append(
                "Designar un representante de salud que pueda tomar decisiones si usted no pudiera hacerlo"
            )

        if completeness == 3:
            prompts.append("Planificación anticipada completa — revisar y actualizar periódicamente según evolución clínica")

        return {
            "advance_directive_documented": acp_documented,
            "goals_of_care_discussed": goals_discussed,
            "healthcare_surrogate_designated": surrogate_designated,
            "completeness_score": f"{completeness}/3",
            "conversation_prompts": prompts,
        }

    @staticmethod
    def symptom_burden(patient: dict[str, Any]) -> dict[str, Any]:
        """Evaluación de carga sintomática."""
        symptoms: list[dict[str, Any]] = []

        symptom_fields = [
            ("pain_score", "Dolor", 4),
            ("fatigue_score", "Fatiga", 4),
            ("nausea_score", "Náusea", 3),
            ("appetite_loss", "Anorexia", 3),
            ("insomnia_score", "Insomnio", 4),
            ("dyspnea_score", "Disnea", 3),
            ("depression_score", "Depresión", 4),
            ("anxiety_score", "Ansiedad", 4),
            ("constipation_score", "Estreñimiento", 3),
        ]

        total_burden = 0
        assessed = 0

        for field, label, threshold_moderate in symptom_fields:
            val = patient.get(field)
            if val is not None:
                try:
                    score = int(float(val))
                    assessed += 1
                    total_burden += score
                    if score >= 7:
                        severity = "severe"
                    elif score >= threshold_moderate:
                        severity = "moderate"
                    elif score > 0:
                        severity = "mild"
                    else:
                        severity = "none"
                    symptoms.append({"symptom": label, "score": score, "severity": severity})
                except (ValueError, TypeError):
                    pass

        return {
            "symptoms_assessed": assessed,
            "total_symptom_burden": total_burden,
            "symptom_details": symptoms,
            "high_burden_symptoms": [s for s in symptoms if s["severity"] in ("moderate", "severe")],
            "recommendation": (
                "Alta carga sintomática — considerar referencia a cuidados paliativos especializados"
                if any(s["severity"] == "severe" for s in symptoms)
                else "Monitoreo continuo de síntomas con ESAS o Edmonton"
            ),
        }

    @staticmethod
    def concurrent_palliative_recommendations(patient: dict[str, Any]) -> dict[str, Any]:
        """
        Recomendaciones de cuidados paliativos concurrentes.
        Basado en Temel et al. NEJM 2010 — integración temprana mejora QoL y supervivencia.
        """
        ecog = _safe_int(patient.get("ecog") or patient.get("ecog_score"), 0)
        lines = _safe_int(patient.get("treatment_lines_exhausted") or patient.get("prior_systemic_lines"), 0)
        metastatic = _is_true(patient.get("metastatic") or patient.get("has_metastasis"))

        integration_level = "standard"
        triggers: list[str] = []
        actions: list[str] = []

        if ecog >= 3 or lines >= 3:
            integration_level = "full"
            triggers.append("ECOG ≥3 o ≥3 líneas agotadas")
            actions.extend([
                "Referencia formal a equipo de cuidados paliativos",
                "Discusión activa de objetivos de cuidado",
                "Evaluación de hospice si pronóstico <6 meses",
            ])
        elif ecog >= 2 or lines >= 2 or metastatic:
            integration_level = "enhanced"
            triggers.append("Enfermedad avanzada con carga sintomática")
            actions.extend([
                "Cuidados paliativos concurrentes con tratamiento oncológico activo",
                "ESAS (Edmonton Symptom Assessment Scale) cada visita",
                "Soporte psicosocial activo",
                "Discusión proactiva de planificación anticipada",
            ])
        else:
            actions.extend([
                "Screening de síntomas con termómetro de distress NCCN",
                "Soporte básico de QoL",
            ])

        return {
            "integration_level": integration_level,
            "triggers": triggers,
            "recommended_actions": actions,
            "evidence": "Temel JS et al. NEJM 2010: La integración temprana de CP mejora QoL, reduce depresión y puede prolongar supervivencia",
        }


def _safe_int(val: Any, default: int | None = 0) -> int | None:
    if val is None or val == "":
        return default
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default


def _is_true(val: Any) -> bool:
    return str(val).lower() in {"1", "true", "yes", "si", "on"} if val else False
