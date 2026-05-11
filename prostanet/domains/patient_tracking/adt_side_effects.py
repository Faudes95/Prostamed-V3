# -*- coding: utf-8 -*-
"""
Monitoreo de efectos secundarios de ADT (terapia de privación androgénica).

Incluye:
  - Evaluación de riesgo cardiovascular (Framingham simplificado)
  - Detección de síndrome metabólico (ATP III)
  - Tracking longitudinal de densitometría ósea (DXA)
  - Score de riesgo de fractura (FRAX simplificado)
  - Recomendaciones según NCCN Survivorship y EAU 2026

Referencia:
  D'Agostino RB et al. Circulation 2008 (Framingham)
  Grundy SM et al. Circulation 2005 (ATP III)
  NCCN Survivorship Guidelines 2026
  EAU Guidelines on Prostate Cancer 2026 — Metabolic and CV monitoring
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, asdict
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CVRiskAssessment:
    """Evaluación de riesgo cardiovascular bajo ADT."""
    framingham_10y_risk_pct: float
    risk_category: str  # "low" (<10%), "intermediate" (10-20%), "high" (>20%)
    risk_factors_present: list[str]
    risk_factors_absent: list[str]
    adt_additional_risk: str
    recommendations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MetabolicSyndromeAssessment:
    """Evaluación de síndrome metabólico (ATP III)."""
    criteria_met: int
    criteria_total: int
    has_metabolic_syndrome: bool  # ≥3 criterios
    criteria_details: list[dict[str, Any]]
    recommendations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BoneHealthAssessment:
    """Evaluación de salud ósea bajo ADT."""
    dxa_t_score_lumbar: float | None
    dxa_t_score_hip: float | None
    worst_t_score: float | None
    bone_category: str  # "normal", "osteopenia", "osteoporosis"
    fracture_risk: str  # "low", "moderate", "high"
    vitamin_d_level: float | None
    vitamin_d_status: str
    on_bone_protective_agent: bool
    recommendations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ADTSideEffectProfile:
    """Perfil completo de efectos secundarios bajo ADT."""
    cv_risk: CVRiskAssessment
    metabolic_syndrome: MetabolicSyndromeAssessment
    bone_health: BoneHealthAssessment
    adt_duration_months: float | None
    monitoring_schedule: list[dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ADTSideEffectService:
    """Servicio de evaluación de efectos secundarios de ADT."""

    @staticmethod
    def assess_cv_risk(patient: dict[str, Any]) -> CVRiskAssessment:
        """
        Evalúa riesgo cardiovascular usando Framingham simplificado.

        Factores: edad, sexo, tabaco, DM, HTA, colesterol, HDL.
        Ajusta por exposición a ADT.
        """
        age = _safe_float(patient.get("age") or patient.get("edad"), 65)
        systolic_bp = _safe_float(patient.get("systolic_bp"), 0)
        total_chol = _safe_float(patient.get("total_cholesterol"), 0)
        hdl = _safe_float(patient.get("hdl_cholesterol"), 0)
        smoker = _is_true(patient.get("smoker") or patient.get("tobacco_use"))
        dm = _is_true(patient.get("diabetes") or patient.get("comorbidity_diabetes"))
        hta_treated = _is_true(patient.get("hypertension_treated") or patient.get("comorbidity_hypertension"))

        risk_factors: list[str] = []
        absent_factors: list[str] = []

        # Framingham simplified (male, since prostate cancer)
        points = 0

        # Age
        if age >= 70:
            points += 10
        elif age >= 65:
            points += 8
        elif age >= 60:
            points += 7
        elif age >= 55:
            points += 5
        elif age >= 50:
            points += 3
        elif age >= 45:
            points += 2

        # Total cholesterol
        if total_chol > 0:
            if total_chol >= 280:
                points += 3
                risk_factors.append(f"Colesterol total elevado: {total_chol:.0f} mg/dL")
            elif total_chol >= 240:
                points += 2
                risk_factors.append(f"Colesterol total limítrofe: {total_chol:.0f} mg/dL")
            elif total_chol >= 200:
                points += 1
            else:
                absent_factors.append("Colesterol total normal")
        else:
            absent_factors.append("Colesterol total no documentado")

        # HDL
        if hdl > 0:
            if hdl < 40:
                points += 2
                risk_factors.append(f"HDL bajo: {hdl:.0f} mg/dL")
            elif hdl < 50:
                points += 1
                risk_factors.append(f"HDL limítrofe: {hdl:.0f} mg/dL")
            elif hdl >= 60:
                points -= 1
                absent_factors.append(f"HDL protector: {hdl:.0f} mg/dL")
        else:
            absent_factors.append("HDL no documentado")

        # Systolic BP
        if systolic_bp > 0:
            if hta_treated:
                if systolic_bp >= 160:
                    points += 3
                elif systolic_bp >= 140:
                    points += 2
                elif systolic_bp >= 130:
                    points += 1
            else:
                if systolic_bp >= 160:
                    points += 2
                elif systolic_bp >= 140:
                    points += 1
            if systolic_bp >= 140:
                risk_factors.append(f"HTA: {systolic_bp:.0f} mmHg")
        else:
            absent_factors.append("Presión arterial no documentada")

        # Smoking
        if smoker:
            points += 4
            risk_factors.append("Tabaquismo activo")
        else:
            absent_factors.append("No fumador")

        # Diabetes
        if dm:
            points += 3
            risk_factors.append("Diabetes mellitus")
        else:
            absent_factors.append("Sin diabetes")

        # Convert points to approximate 10-year risk
        risk_table = {
            0: 1, 1: 1, 2: 1, 3: 1, 4: 1, 5: 2, 6: 2, 7: 3,
            8: 4, 9: 5, 10: 6, 11: 8, 12: 10, 13: 12, 14: 16,
            15: 20, 16: 25, 17: 30,
        }
        points = max(0, min(17, points))
        base_risk = risk_table.get(points, 30)

        # ADT increases CV risk ~20-30%
        adt_months = _safe_float(patient.get("adt_duration_months"), 0)
        adt_multiplier = 1.0
        if adt_months > 0:
            if adt_months > 24:
                adt_multiplier = 1.3
                adt_note = f"ADT prolongada ({adt_months:.0f} meses) — riesgo CV aumentado ~30%"
            elif adt_months > 12:
                adt_multiplier = 1.2
                adt_note = f"ADT >12 meses ({adt_months:.0f} meses) — riesgo CV aumentado ~20%"
            else:
                adt_multiplier = 1.1
                adt_note = f"ADT ({adt_months:.0f} meses) — riesgo CV marginalmente aumentado"
            risk_factors.append(adt_note)
        else:
            adt_note = "Sin ADT documentada"

        adjusted_risk = round(base_risk * adt_multiplier, 1)

        if adjusted_risk < 10:
            category = "low"
        elif adjusted_risk <= 20:
            category = "intermediate"
        else:
            category = "high"

        recommendations: list[str] = []
        if category == "high":
            recommendations.extend([
                "Referencia a cardiología/cardio-oncología",
                "Control estricto de factores de riesgo modificables",
                "Considerar evaluación cardíaca basal (ECG, ecocardiograma)",
                "Estatina si indicada por riesgo",
            ])
        elif category == "intermediate":
            recommendations.extend([
                "Evaluación CV cada 6 meses",
                "Optimizar control de HTA, dislipidemia y glucosa",
                "Ejercicio aeróbico ≥150 min/semana",
            ])
        else:
            recommendations.extend([
                "Seguimiento CV estándar cada 12 meses",
                "Mantener hábitos de vida saludable",
            ])

        if adt_months > 0:
            recommendations.append("ECG basal y anual durante ADT (vigilar QTc)")

        return CVRiskAssessment(
            framingham_10y_risk_pct=adjusted_risk,
            risk_category=category,
            risk_factors_present=risk_factors,
            risk_factors_absent=absent_factors,
            adt_additional_risk=adt_note,
            recommendations=recommendations,
        )

    @staticmethod
    def assess_metabolic_syndrome(patient: dict[str, Any]) -> MetabolicSyndromeAssessment:
        """
        Evalúa síndrome metabólico según criterios ATP III.

        Criterios (≥3 para diagnóstico):
        1. Perímetro abdominal >102 cm (hombres)
        2. Triglicéridos ≥150 mg/dL
        3. HDL <40 mg/dL (hombres)
        4. PA ≥130/85 mmHg o tratamiento
        5. Glucosa ayuno ≥100 mg/dL o DM
        """
        criteria: list[dict[str, Any]] = []
        met = 0

        # 1. Waist circumference
        waist = _safe_float(patient.get("waist_circumference_cm"), 0)
        if waist > 0:
            waist_met = waist > 102
            criteria.append({"criterion": "Perímetro abdominal >102 cm", "value": f"{waist:.0f} cm", "met": waist_met})
            if waist_met:
                met += 1
        else:
            criteria.append({"criterion": "Perímetro abdominal >102 cm", "value": "No documentado", "met": False})

        # 2. Triglycerides
        tg = _safe_float(patient.get("triglycerides"), 0)
        if tg > 0:
            tg_met = tg >= 150
            criteria.append({"criterion": "Triglicéridos ≥150 mg/dL", "value": f"{tg:.0f} mg/dL", "met": tg_met})
            if tg_met:
                met += 1
        else:
            criteria.append({"criterion": "Triglicéridos ≥150 mg/dL", "value": "No documentado", "met": False})

        # 3. HDL
        hdl = _safe_float(patient.get("hdl_cholesterol"), 0)
        if hdl > 0:
            hdl_met = hdl < 40
            criteria.append({"criterion": "HDL <40 mg/dL", "value": f"{hdl:.0f} mg/dL", "met": hdl_met})
            if hdl_met:
                met += 1
        else:
            criteria.append({"criterion": "HDL <40 mg/dL", "value": "No documentado", "met": False})

        # 4. Blood pressure
        sbp = _safe_float(patient.get("systolic_bp"), 0)
        dbp = _safe_float(patient.get("diastolic_bp"), 0)
        hta = _is_true(patient.get("hypertension_treated") or patient.get("comorbidity_hypertension"))
        if sbp > 0 or hta:
            bp_met = (sbp >= 130 or dbp >= 85 or hta)
            bp_val = f"{sbp:.0f}/{dbp:.0f} mmHg" if sbp > 0 else "En tratamiento"
            criteria.append({"criterion": "PA ≥130/85 mmHg o tratamiento", "value": bp_val, "met": bp_met})
            if bp_met:
                met += 1
        else:
            criteria.append({"criterion": "PA ≥130/85 mmHg o tratamiento", "value": "No documentado", "met": False})

        # 5. Fasting glucose
        glucose = _safe_float(patient.get("fasting_glucose") or patient.get("glucose"), 0)
        hba1c = _safe_float(patient.get("hba1c"), 0)
        dm = _is_true(patient.get("diabetes") or patient.get("comorbidity_diabetes"))
        if glucose > 0 or dm:
            gluc_met = (glucose >= 100 or dm or hba1c >= 5.7)
            gluc_val = f"{glucose:.0f} mg/dL" if glucose > 0 else ("DM conocida" if dm else f"HbA1c {hba1c}%")
            criteria.append({"criterion": "Glucosa ayuno ≥100 mg/dL o DM", "value": gluc_val, "met": gluc_met})
            if gluc_met:
                met += 1
        else:
            criteria.append({"criterion": "Glucosa ayuno ≥100 mg/dL o DM", "value": "No documentado", "met": False})

        has_ms = met >= 3
        recommendations: list[str] = []
        if has_ms:
            recommendations.extend([
                "Síndrome metabólico confirmado — intervención multifactorial",
                "Dieta mediterránea + ejercicio ≥150 min/semana",
                "Control estricto de glucosa, lípidos y presión arterial",
                "Considerar metformina si prediabetes",
                "Reevaluar necesidad de ADT continua vs intermitente si factible",
            ])
        elif met >= 2:
            recommendations.extend([
                "Riesgo de síndrome metabólico — monitorizar cada 3-6 meses",
                "Intervención en estilo de vida",
            ])
        else:
            recommendations.append("Perfil metabólico sin datos preocupantes actuales")

        return MetabolicSyndromeAssessment(
            criteria_met=met,
            criteria_total=5,
            has_metabolic_syndrome=has_ms,
            criteria_details=criteria,
            recommendations=recommendations,
        )

    @staticmethod
    def assess_bone_health(patient: dict[str, Any]) -> BoneHealthAssessment:
        """
        Evalúa salud ósea bajo ADT.

        Clasifica por DXA T-score, vitamina D, y riesgo de fractura.
        """
        t_lumbar = _safe_float(patient.get("dxa_t_score_lumbar"), None)
        t_hip = _safe_float(patient.get("dxa_t_score_hip"), None)

        t_scores = [t for t in [t_lumbar, t_hip] if t is not None]
        worst = min(t_scores) if t_scores else None

        if worst is not None:
            if worst <= -2.5:
                category = "osteoporosis"
            elif worst <= -1.0:
                category = "osteopenia"
            else:
                category = "normal"
        else:
            category = "no_data"

        # Fracture risk
        age = _safe_float(patient.get("age") or patient.get("edad"), 65)
        adt_months = _safe_float(patient.get("adt_duration_months"), 0)
        prior_fracture = _is_true(patient.get("prior_fracture") or patient.get("comorbidity_fracture"))
        steroid_use = _is_true(patient.get("steroid_use") or patient.get("on_prednisone"))

        fracture_risk_score = 0
        if category == "osteoporosis":
            fracture_risk_score += 3
        elif category == "osteopenia":
            fracture_risk_score += 1
        if age >= 75:
            fracture_risk_score += 2
        elif age >= 65:
            fracture_risk_score += 1
        if adt_months > 24:
            fracture_risk_score += 2
        elif adt_months > 12:
            fracture_risk_score += 1
        if prior_fracture:
            fracture_risk_score += 2
        if steroid_use:
            fracture_risk_score += 1

        if fracture_risk_score >= 5:
            fracture_risk = "high"
        elif fracture_risk_score >= 3:
            fracture_risk = "moderate"
        else:
            fracture_risk = "low"

        # Vitamin D
        vit_d = _safe_float(patient.get("vitamin_d_level"), None)
        if vit_d is not None:
            if vit_d < 20:
                vit_d_status = "deficiente"
            elif vit_d < 30:
                vit_d_status = "insuficiente"
            else:
                vit_d_status = "suficiente"
        else:
            vit_d_status = "no_documentado"

        on_bone_agent = _is_true(
            patient.get("on_denosumab") or patient.get("on_zoledronate") or patient.get("bone_protective_agent")
        )

        recommendations: list[str] = []
        if category == "osteoporosis" or fracture_risk == "high":
            recommendations.extend([
                "Iniciar agente óseo-protector (denosumab 60mg q6mo o zoledronato 5mg/año)",
                "Calcio 1200 mg/día + Vitamina D 1000-2000 UI/día",
                "Ejercicio de resistencia y equilibrio",
                "Evaluar riesgo de caídas",
            ])
        elif category == "osteopenia" or fracture_risk == "moderate":
            recommendations.extend([
                "Repetir DXA en 12-24 meses",
                "Calcio + Vitamina D suplementarios",
                "Ejercicio de impacto moderado",
                "Considerar agente óseo-protector si T-score empeora",
            ])
        else:
            recommendations.extend([
                "DXA basal si no realizada; repetir cada 24 meses bajo ADT",
                "Suplementar calcio y vitamina D profilácticamente",
            ])

        if vit_d_status == "deficiente":
            recommendations.append("Corregir deficiencia de vitamina D (50,000 UI/semana × 8 semanas, luego mantenimiento)")

        return BoneHealthAssessment(
            dxa_t_score_lumbar=t_lumbar,
            dxa_t_score_hip=t_hip,
            worst_t_score=worst,
            bone_category=category,
            fracture_risk=fracture_risk,
            vitamin_d_level=vit_d,
            vitamin_d_status=vit_d_status,
            on_bone_protective_agent=on_bone_agent,
            recommendations=recommendations,
        )

    @classmethod
    def full_assessment(cls, patient: dict[str, Any]) -> ADTSideEffectProfile:
        """Evaluación completa de efectos secundarios de ADT."""
        adt_months = _safe_float(patient.get("adt_duration_months"), None)

        monitoring = [
            {"test": "PSA + testosterona", "frequency": "Cada 3 meses"},
            {"test": "Perfil lipídico completo", "frequency": "Cada 6 meses"},
            {"test": "Glucosa/HbA1c", "frequency": "Cada 6 meses"},
            {"test": "BH completa", "frequency": "Cada 6 meses"},
            {"test": "ECG", "frequency": "Anual"},
            {"test": "DXA", "frequency": "Cada 24 meses"},
            {"test": "Vitamina D (25-OH)", "frequency": "Cada 12 meses"},
            {"test": "Evaluación CV (PA, peso, perímetro abdominal)", "frequency": "Cada visita"},
            {"test": "FACIT-Fatigue", "frequency": "Cada visita"},
            {"test": "IIEF-5 (función sexual)", "frequency": "Cada 6 meses"},
        ]

        return ADTSideEffectProfile(
            cv_risk=cls.assess_cv_risk(patient),
            metabolic_syndrome=cls.assess_metabolic_syndrome(patient),
            bone_health=cls.assess_bone_health(patient),
            adt_duration_months=adt_months,
            monitoring_schedule=monitoring,
        )


def _safe_float(val: Any, default: float | None = 0.0) -> float | None:
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _is_true(val: Any) -> bool:
    return str(val).lower() in {"1", "true", "yes", "si", "on"} if val else False
