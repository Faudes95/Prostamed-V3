# -*- coding: utf-8 -*-
"""
Módulo de eventos esqueléticos (SRE/SSE) y agentes modificadores óseos.

Captura estructurada de fracturas patológicas, compresión medular,
RT paliativa ósea, cirugía ósea, hipercalcemia y monitoreo de
denosumab/ácido zoledrónico con evaluación de riesgo de ONJ.

Referencia:
  NCCN 2026 Prostate Cancer (Bone Health)
  EAU 2026 Palliation and Bone Health
  Zoledronic acid 039 trial
  Denosumab 103 (vs ZA) / HALT trial
  ALSYMPCA (Radium-223)
  RANK-DENOSUMAB safety guidelines (ONJ prevention)
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

logger = logging.getLogger(__name__)


# ── Constantes ───────────────────────────────────────────────────────────────

SRE_EVENT_TYPES = (
    "pathological_fracture",
    "cord_compression",
    "palliative_bone_rt",
    "bone_surgery",
    "hypercalcemia",
)

BMA_AGENTS = ("denosumab", "zoledronic_acid")

BONE_SITES = (
    "cervical_spine", "thoracic_spine", "lumbar_spine", "sacrum",
    "pelvis", "ribs", "skull",
    "humerus", "femur", "tibia", "other",
)


# ── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class SkeletalRelatedEvent:
    """Evento esquelético relacionado (SRE) individual."""
    event_type: str       # una de SRE_EVENT_TYPES
    event_date: str = ""
    site: str = ""        # localización anatómica
    intervention: str = ""  # "surgery", "rt_palliative", "steroids", "stabilization", "none"
    surgical_intervention: bool = False
    rt_dose_gy: float | None = None
    rt_fractions: int | None = None
    details: str = ""
    severity: str = "standard"  # "urgent" | "standard"
    resolved: bool = False
    evidence_tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BoneModifyingAgentRecord:
    """Registro de agente modificador óseo (denosumab / ácido zoledrónico)."""
    agent: str = ""              # "denosumab" | "zoledronic_acid"
    start_date: str = ""
    end_date: str | None = None
    frequency: str = ""          # "q4w" | "q12w" | "q6m"
    dental_clearance_done: bool = False
    dental_clearance_date: str | None = None
    last_dental_evaluation: str | None = None
    onj_monitoring: bool = False
    onj_detected: bool = False
    calcium_vitamin_d_supplementation: bool = False
    renal_function_adequate: bool | None = None  # relevante para ácido zoledrónico
    last_renal_check_date: str | None = None
    doses_administered: int = 0
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SkeletalEventProfile:
    """Perfil completo de eventos esqueléticos y salud ósea de un paciente."""
    patient_id: int | None = None
    sre_events: list[SkeletalRelatedEvent] = field(default_factory=list)
    bone_modifying_agent: BoneModifyingAgentRecord | None = None
    time_to_first_sre_months: float | None = None
    total_sre_count: int = 0
    has_cord_compression: bool = False
    has_pathological_fracture: bool = False
    sre_free_months: float | None = None  # meses desde diagnóstico metastásico sin SRE
    sre_risk_score: str = "unknown"  # "low" | "moderate" | "high"
    bone_metastasis_count: int | None = None
    recommendations: list[str] = field(default_factory=list)
    bma_compliance_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "patient_id": self.patient_id,
            "sre_events": [e.to_dict() for e in self.sre_events],
            "bone_modifying_agent": self.bone_modifying_agent.to_dict() if self.bone_modifying_agent else None,
            "time_to_first_sre_months": self.time_to_first_sre_months,
            "total_sre_count": self.total_sre_count,
            "has_cord_compression": self.has_cord_compression,
            "has_pathological_fracture": self.has_pathological_fracture,
            "sre_free_months": self.sre_free_months,
            "sre_risk_score": self.sre_risk_score,
            "bone_metastasis_count": self.bone_metastasis_count,
            "recommendations": list(self.recommendations),
            "bma_compliance_warnings": list(self.bma_compliance_warnings),
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


def _parse_date(value: Any) -> date | None:
    if not value or value in ("", "No aplica"):
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _months_between(d1: date, d2: date) -> float:
    return round((d2 - d1).days / 30.44, 1)


# ── Servicio principal ───────────────────────────────────────────────────────

class SkeletalEventService:
    """Servicio de eventos esqueléticos con evaluación de riesgo y monitoreo de BMA."""

    @staticmethod
    def parse_sre_event(data: dict[str, Any]) -> SkeletalRelatedEvent:
        """Parsea un diccionario en un SkeletalRelatedEvent."""
        event_type = data.get("event_type", "")
        severity = "urgent" if event_type == "cord_compression" else data.get("severity", "standard")
        return SkeletalRelatedEvent(
            event_type=event_type,
            event_date=data.get("event_date", ""),
            site=data.get("site", ""),
            intervention=data.get("intervention", ""),
            surgical_intervention=bool(data.get("surgical_intervention", False)),
            rt_dose_gy=_safe_float(data.get("rt_dose_gy")),
            rt_fractions=_safe_int(data.get("rt_fractions")),
            details=data.get("details", ""),
            severity=severity,
            resolved=bool(data.get("resolved", False)),
            evidence_tags=data.get("evidence_tags", []),
        )

    @staticmethod
    def parse_bma_record(data: dict[str, Any]) -> BoneModifyingAgentRecord:
        """Parsea un diccionario en un BoneModifyingAgentRecord."""
        return BoneModifyingAgentRecord(
            agent=data.get("agent", ""),
            start_date=data.get("start_date", ""),
            end_date=data.get("end_date"),
            frequency=data.get("frequency", ""),
            dental_clearance_done=bool(data.get("dental_clearance_done", False)),
            dental_clearance_date=data.get("dental_clearance_date"),
            last_dental_evaluation=data.get("last_dental_evaluation"),
            onj_monitoring=bool(data.get("onj_monitoring", False)),
            onj_detected=bool(data.get("onj_detected", False)),
            calcium_vitamin_d_supplementation=bool(data.get("calcium_vitamin_d_supplementation", False)),
            renal_function_adequate=data.get("renal_function_adequate"),
            last_renal_check_date=data.get("last_renal_check_date"),
            doses_administered=_safe_int(data.get("doses_administered")) or 0,
            notes=data.get("notes", ""),
        )

    @staticmethod
    def compute_sre_risk(
        patient: dict[str, Any],
        bone_health: dict[str, Any] | None = None,
    ) -> str:
        """Calcula score de riesgo de SRE basado en factores clínicos."""
        risk_points = 0

        # Número de metástasis óseas
        bone_count = _safe_int(patient.get("bone_metastasis_count") or patient.get("metastasis_count"))
        if bone_count:
            if bone_count > 5:
                risk_points += 3
            elif bone_count > 2:
                risk_points += 2
            else:
                risk_points += 1

        # ALP elevada
        alp = _safe_float(patient.get("alkaline_phosphatase") or patient.get("alp"))
        if alp and alp > 120:  # UI/L
            risk_points += 2

        # Fractura previa
        sre_data = patient.get("skeletal_events") or []
        prior_fracture = any(
            e.get("event_type") == "pathological_fracture" for e in sre_data if isinstance(e, dict)
        )
        if prior_fracture:
            risk_points += 2

        # T-score bajo (osteoporosis)
        if bone_health:
            t_score = _safe_float(bone_health.get("worst_t_score"))
            if t_score is not None and t_score <= -2.5:
                risk_points += 2
            elif t_score is not None and t_score <= -1.0:
                risk_points += 1

        # Duración de ADT
        adt_months = _safe_float(patient.get("adt_duration_months"))
        if adt_months and adt_months > 24:
            risk_points += 1

        # Sin BMA a pesar de indicación
        bma_data = patient.get("bone_modifying_agent")
        if bone_count and bone_count > 0 and not bma_data:
            risk_points += 1

        if risk_points >= 5:
            return "high"
        if risk_points >= 3:
            return "moderate"
        return "low"

    @staticmethod
    def evaluate_bma_compliance(agent_record: BoneModifyingAgentRecord) -> list[str]:
        """Evalúa cumplimiento y seguridad del agente modificador óseo."""
        warnings: list[str] = []
        today = date.today()

        # Clearance dental antes de iniciar
        if not agent_record.dental_clearance_done:
            warnings.append("Clearance dental no documentado antes de iniciar agente modificador óseo — riesgo de ONJ aumentado")

        # Monitoreo dental periódico (cada 6 meses)
        if agent_record.last_dental_evaluation:
            last_dental = _parse_date(agent_record.last_dental_evaluation)
            if last_dental:
                months_since = _months_between(last_dental, today)
                if months_since > 6:
                    warnings.append(f"Evaluación dental vencida: {months_since:.0f} meses desde última revisión (recomendado: cada 6 meses)")

        # Función renal para ácido zoledrónico
        if agent_record.agent == "zoledronic_acid":
            if agent_record.renal_function_adequate is False:
                warnings.append("Función renal inadecuada documentada — contraindicación relativa para ácido zoledrónico")
            if agent_record.last_renal_check_date:
                last_renal = _parse_date(agent_record.last_renal_check_date)
                if last_renal:
                    months_since = _months_between(last_renal, today)
                    if months_since > 3:
                        warnings.append(f"Función renal no evaluada en {months_since:.0f} meses (recomendado: cada 3 meses para ZA)")

        # Calcio + Vitamina D
        if not agent_record.calcium_vitamin_d_supplementation:
            warnings.append("Suplementación de calcio + vitamina D no documentada — requerida con BMA")

        # ONJ detectada
        if agent_record.onj_detected:
            warnings.append("OSTEONECROSIS MANDIBULAR (ONJ) detectada — evaluar suspensión de BMA y manejo por cirugía maxilofacial")

        return warnings

    @staticmethod
    def build_sre_profile(patient: dict[str, Any], state: str) -> SkeletalEventProfile:
        """Construye perfil completo de eventos esqueléticos."""
        sre_data = patient.get("skeletal_events") or []
        events = [
            SkeletalEventService.parse_sre_event(e)
            for e in sre_data if isinstance(e, dict)
        ]

        bma_data = patient.get("bone_modifying_agent")
        bma_record = SkeletalEventService.parse_bma_record(bma_data) if isinstance(bma_data, dict) else None

        # Bone health cross-reference
        bone_health = patient.get("bone_health") or {}

        # Risk score
        sre_risk = SkeletalEventService.compute_sre_risk(patient, bone_health)

        # Time to first SRE
        diagnosis_date = _parse_date(patient.get("metastatic_diagnosis_date") or patient.get("diagnosis_date"))
        first_sre_date = None
        if events:
            sre_dates = [_parse_date(e.event_date) for e in events]
            valid_dates = [d for d in sre_dates if d is not None]
            if valid_dates:
                first_sre_date = min(valid_dates)

        time_to_first = None
        sre_free = None
        if diagnosis_date:
            if first_sre_date:
                time_to_first = _months_between(diagnosis_date, first_sre_date)
            else:
                sre_free = _months_between(diagnosis_date, date.today())

        # BMA compliance
        bma_warnings = SkeletalEventService.evaluate_bma_compliance(bma_record) if bma_record else []

        # Recommendations
        recommendations: list[str] = []
        bone_count = _safe_int(patient.get("bone_metastasis_count") or patient.get("metastasis_count"))

        if bone_count and bone_count > 0 and not bma_record:
            recommendations.append(
                "Iniciar agente modificador óseo (denosumab 120mg q4w o ácido zoledrónico 4mg q4w IV) "
                "con calcio 1200mg/día + vitamina D 1000-2000 UI/día"
            )
        if any(e.event_type == "cord_compression" for e in events):
            recommendations.append("URGENTE: Evaluar cirugía descompresiva + RT. Dexametasona 16mg/día.")
        if sre_risk == "high":
            recommendations.append("Alto riesgo de SRE: asegurar BMA, optimizar salud ósea, evaluar Ra-223 si elegible")

        has_cord = any(e.event_type == "cord_compression" for e in events)
        has_fracture = any(e.event_type == "pathological_fracture" for e in events)

        return SkeletalEventProfile(
            patient_id=_safe_int(patient.get("patient_id") or patient.get("nss")),
            sre_events=events,
            bone_modifying_agent=bma_record,
            time_to_first_sre_months=time_to_first,
            total_sre_count=len(events),
            has_cord_compression=has_cord,
            has_pathological_fracture=has_fracture,
            sre_free_months=sre_free,
            sre_risk_score=sre_risk,
            bone_metastasis_count=bone_count,
            recommendations=recommendations,
            bma_compliance_warnings=bma_warnings,
        )

    @staticmethod
    def evaluate_sre_alerts(
        patient_id: int,
        profile: SkeletalEventProfile,
    ) -> list[dict[str, Any]]:
        """Genera alertas clínicas basadas en el perfil de eventos esqueléticos."""
        from prostanet.domains.patient_tracking.alert_engine import ClinicalAlert

        alerts: list[ClinicalAlert] = []

        # 1. Compresión medular — URGENTE
        if profile.has_cord_compression:
            unresolved = [
                e for e in profile.sre_events
                if e.event_type == "cord_compression" and not e.resolved
            ]
            if unresolved:
                alerts.append(ClinicalAlert(
                    patient_id=patient_id,
                    alert_type="sre_cord_compression",
                    severity="critical",
                    category="skeletal_event",
                    title="⚠️ COMPRESIÓN MEDULAR — Intervención urgente requerida",
                    message="Compresión medular por metástasis ósea detectada. Riesgo de déficit neurológico irreversible.",
                    recommended_action="1) Dexametasona 16mg/día IV urgente. 2) Evaluación neuroquirúrgica. 3) RT paliativa 30Gy/10fx o 20Gy/5fx. 4) Estabilización si inestabilidad mecánica.",
                    guideline_reference="NCCN 2026 bone metastases; EAU 2026 spinal cord compression",
                    triggering_value="Compresión medular activa",
                    threshold="Cualquier compresión medular",
                ))

        # 2. Fractura patológica
        if profile.has_pathological_fracture:
            alerts.append(ClinicalAlert(
                patient_id=patient_id,
                alert_type="sre_pathological_fracture",
                severity="critical",
                category="skeletal_event",
                title="Fractura patológica documentada",
                message=f"Total de eventos esqueléticos: {profile.total_sre_count}.",
                recommended_action="Evaluación ortopédica. Iniciar BMA si no activo. Considerar RT paliativa al sitio.",
                guideline_reference="NCCN 2026 bone health; Denosumab 103 trial",
                triggering_value="Fractura patológica",
                threshold="Cualquier fractura patológica",
            ))

        # 3. BMA no iniciado con indicación
        if profile.bone_metastasis_count and profile.bone_metastasis_count > 0 and not profile.bone_modifying_agent:
            alerts.append(ClinicalAlert(
                patient_id=patient_id,
                alert_type="sre_bma_not_started",
                severity="warning",
                category="skeletal_event",
                title="Agente modificador óseo no iniciado",
                message=f"{profile.bone_metastasis_count} metástasis óseas documentadas sin BMA activo.",
                recommended_action="Iniciar denosumab 120mg SC q4w o ácido zoledrónico 4mg IV q4w. Clearance dental previo.",
                guideline_reference="NCCN 2026: BMA in bone metastases; Fizazi 2011 (denosumab vs ZA)",
                triggering_value=f"{profile.bone_metastasis_count} lesiones óseas",
                threshold="≥1 metástasis ósea",
            ))

        # 4. Compliance de BMA
        for warning in profile.bma_compliance_warnings:
            severity = "critical" if "ONJ" in warning.upper() else "warning"
            alerts.append(ClinicalAlert(
                patient_id=patient_id,
                alert_type="sre_bma_compliance",
                severity=severity,
                category="skeletal_event",
                title="Alerta de cumplimiento BMA",
                message=warning,
                recommended_action="Verificar cumplimiento de protocolo de seguridad del agente modificador óseo.",
                guideline_reference="AAOMS ONJ guidelines; NCCN 2026 bone health",
                triggering_value=warning[:50],
                threshold="Protocolo BMA",
            ))

        # 5. Alto riesgo SRE sin BMA
        if profile.sre_risk_score == "high" and not profile.bone_modifying_agent:
            alerts.append(ClinicalAlert(
                patient_id=patient_id,
                alert_type="sre_high_risk",
                severity="warning",
                category="skeletal_event",
                title="Alto riesgo de eventos esqueléticos",
                message="Múltiples factores de riesgo para SRE (metástasis óseas, ALP elevada, T-score bajo, fractura previa).",
                recommended_action="Iniciar BMA. Considerar Ra-223 si mCRPC sintomático óseo sin visceral. Optimizar calcio/vitD.",
                guideline_reference="NCCN 2026; ALSYMPCA (Ra-223); Denosumab HALT",
                triggering_value=f"Riesgo: {profile.sre_risk_score}",
                threshold="Alto riesgo",
            ))

        return [a.to_dict() for a in alerts]

    @staticmethod
    def build_sre_summary_for_profile(profile: SkeletalEventProfile) -> dict[str, Any]:
        """Construye resumen de SRE para mostrar en el perfil del paciente."""
        event_summaries = []
        for event in profile.sre_events:
            type_labels = {
                "pathological_fracture": "Fractura patológica",
                "cord_compression": "Compresión medular",
                "palliative_bone_rt": "RT paliativa ósea",
                "bone_surgery": "Cirugía ósea",
                "hypercalcemia": "Hipercalcemia",
            }
            event_summaries.append({
                "type": type_labels.get(event.event_type, event.event_type),
                "date": event.event_date,
                "site": event.site,
                "severity": event.severity,
                "resolved": event.resolved,
            })

        tone = "success" if profile.total_sre_count == 0 else "danger" if profile.has_cord_compression else "warning"

        bma_summary = None
        if profile.bone_modifying_agent:
            agent_labels = {"denosumab": "Denosumab 120mg", "zoledronic_acid": "Ácido Zoledrónico 4mg"}
            bma_summary = {
                "agent": agent_labels.get(profile.bone_modifying_agent.agent, profile.bone_modifying_agent.agent),
                "frequency": profile.bone_modifying_agent.frequency,
                "start_date": profile.bone_modifying_agent.start_date,
                "dental_clearance": profile.bone_modifying_agent.dental_clearance_done,
                "onj_detected": profile.bone_modifying_agent.onj_detected,
                "doses": profile.bone_modifying_agent.doses_administered,
                "compliance_warnings": len(profile.bma_compliance_warnings),
            }

        return {
            "total_sre_count": profile.total_sre_count,
            "has_cord_compression": profile.has_cord_compression,
            "has_fracture": profile.has_pathological_fracture,
            "sre_risk": profile.sre_risk_score,
            "time_to_first_sre": profile.time_to_first_sre_months,
            "sre_free_months": profile.sre_free_months,
            "bone_metastasis_count": profile.bone_metastasis_count,
            "tone": tone,
            "events": event_summaries,
            "bma": bma_summary,
            "recommendations": profile.recommendations,
        }
