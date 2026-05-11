# -*- coding: utf-8 -*-
"""
Módulo de vigilancia activa estructurada para cáncer de próstata localizado.

Implementa motores de elegibilidad multi-protocolo (NCCN, PRIAS, Epstein,
Royal Marsden), calendario protocolizado, detección de reclasificación y
monitoreo de ansiedad del paciente.

Referencia:
  NCCN 2026 Prostate Cancer (Active Surveillance)
  EAU 2026 Active Surveillance Protocol
  PRIAS (Prostate Cancer Research International Active Surveillance)
  ProtecT 15-year outcomes (Hamdy et al. NEJM 2023)
  Canary PASS criteria
  Royal Marsden AS protocol
"""
from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

logger = logging.getLogger(__name__)


# ── Constantes de protocolo ──────────────────────────────────────────────────

AS_PROTOCOLS = {
    "NCCN_very_low": {
        "label": "NCCN Muy bajo riesgo",
        "criteria": {
            "isup_max": 1,
            "cores_positive_max": 2,     # ≤2 cores positivos (o <34% en biopsias ≥10)
            "max_involvement_pct": 50,
            "psa_max": 10,
            "tstage_max": "T2a",         # T1c o T2a
            "psad_max": 0.15,
        },
        "schedule": {
            "psa_interval_months": 6,
            "mri_interval_months": 12,
            "rebiopsy_interval_months": 12,  # confirmatoria a 12 meses
            "rebiopsy_ongoing_months": 24,   # luego cada 2-4 años
            "dre_interval_months": 12,
        },
        "evidence_tags": ["NCCN 2026 AS very low risk"],
    },
    "NCCN_low": {
        "label": "NCCN Bajo riesgo",
        "criteria": {
            "isup_max": 1,
            "cores_positive_max": 3,
            "max_involvement_pct": 50,
            "psa_max": 10,
            "tstage_max": "T2a",
            "psad_max": 0.15,
        },
        "schedule": {
            "psa_interval_months": 6,
            "mri_interval_months": 12,
            "rebiopsy_interval_months": 12,
            "rebiopsy_ongoing_months": 24,
            "dre_interval_months": 12,
        },
        "evidence_tags": ["NCCN 2026 AS low risk"],
    },
    "NCCN_favorable_intermediate": {
        "label": "NCCN Intermedio favorable (VA selectiva)",
        "criteria": {
            "isup_max": 2,
            "cores_positive_max": 3,     # <50% cores
            "max_involvement_pct": 50,
            "psa_max": 20,
            "tstage_max": "T2c",
            "no_cribriform": True,
            "no_intraductal": True,
        },
        "schedule": {
            "psa_interval_months": 3,
            "mri_interval_months": 12,
            "rebiopsy_interval_months": 12,
            "rebiopsy_ongoing_months": 12,  # más frecuente
            "dre_interval_months": 6,
        },
        "evidence_tags": ["NCCN 2026 AS favorable intermediate", "Canary PASS"],
    },
    "PRIAS": {
        "label": "PRIAS",
        "criteria": {
            "isup_max": 1,
            "cores_positive_max": 2,
            "max_involvement_pct": 50,
            "psa_max": 10,
            "tstage_max": "T2a",
            "psad_max": 0.2,
        },
        "schedule": {
            "psa_interval_months": 3,
            "mri_interval_months": 18,
            "rebiopsy_interval_months": 12,
            "rebiopsy_ongoing_months": 36,
            "dre_interval_months": 12,
        },
        "evidence_tags": ["PRIAS protocol Bul 2013"],
    },
    "Royal_Marsden": {
        "label": "Royal Marsden",
        "criteria": {
            "isup_max": 1,
            "cores_positive_max": 2,
            "max_involvement_pct": 50,
            "psa_max": 15,
            "tstage_max": "T2a",
        },
        "schedule": {
            "psa_interval_months": 3,
            "mri_interval_months": 18,
            "rebiopsy_interval_months": 18,
            "rebiopsy_ongoing_months": 36,
            "dre_interval_months": 12,
        },
        "evidence_tags": ["Royal Marsden AS protocol"],
    },
    "Canary_PASS": {
        # Multi-center norteamericano con énfasis en biopsia confirmatoria estructurada
        # y RMmp integrada. Admite ISUP 1 con umbral PSAD 0.15, requiere biopsia
        # confirmatoria a 6-12 meses (no aplazable). Referencia: Newcomb LF et al.
        # J Urol 2016;195:313 (Canary PASS cohort).
        "label": "Canary PASS",
        "criteria": {
            "isup_max": 1,
            "cores_positive_max": 3,
            "max_involvement_pct": 50,
            "psa_max": 15,
            "tstage_max": "T2a",
            "psad_max": 0.15,
        },
        "schedule": {
            "psa_interval_months": 3,
            "mri_interval_months": 12,
            "rebiopsy_interval_months": 6,   # biopsia confirmatoria 6-12m
            "rebiopsy_ongoing_months": 24,
            "dre_interval_months": 12,
        },
        "evidence_tags": ["Canary PASS Newcomb J Urol 2016", "Category 2A NCCN AS"],
    },
    "UCSF": {
        # UCSF AS permite intermedio favorable selecto (GG2 ≤33% pattern 4 y
        # <33% cores) si Decipher bajo/intermedio. Referencia: Welty CJ et al.
        # J Urol 2015;193:807 y Cooperberg MR et al. JCO 2018 (Decipher in AS).
        "label": "UCSF",
        "criteria": {
            "isup_max": 2,               # admite favorable intermediate selecto
            "cores_positive_max": 4,     # hasta 33% cores
            "max_involvement_pct": 50,
            "psa_max": 15,
            "tstage_max": "T2b",
            "psad_max": 0.20,
            "decipher_score_max": 0.60,  # Decipher favorable/intermediate
            "no_cribriform": True,
            "no_intraductal": True,
        },
        "schedule": {
            "psa_interval_months": 3,
            "mri_interval_months": 12,
            "rebiopsy_interval_months": 12,
            "rebiopsy_ongoing_months": 24,
            "dre_interval_months": 6,
        },
        "evidence_tags": [
            "UCSF AS Welty J Urol 2015",
            "Cooperberg Decipher JCO 2018",
            "Category 2A NCCN AS favorable intermediate",
        ],
    },
    "Sunnybrook": {
        # Protocolo dirigido por cinética PSA (Klotz). Umbral PSADT <3 años dispara
        # re-estadificación. Admite PSA hasta 20 y T2c en pacientes seleccionados
        # con esperanza de vida >10 años. Referencia: Klotz L et al. JCO 2015;33:272.
        "label": "Sunnybrook (Klotz)",
        "criteria": {
            "isup_max": 1,
            "cores_positive_max": 3,
            "max_involvement_pct": 50,
            "psa_max": 20,
            "tstage_max": "T2c",
        },
        "schedule": {
            "psa_interval_months": 3,
            "mri_interval_months": 24,   # MRI no obligatoria en protocolo original
            "rebiopsy_interval_months": 12,
            "rebiopsy_ongoing_months": 48,  # cada 3-5 años si PSADT estable
            "dre_interval_months": 6,
        },
        "evidence_tags": [
            "Sunnybrook AS Klotz JCO 2015",
            "PSA kinetics-driven surveillance",
            "Category 2A NCCN AS",
        ],
    },
}

T_STAGE_ORDER = {
    "T1a": 1, "T1b": 2, "T1c": 3,
    "T2a": 4, "T2b": 5, "T2c": 6,
    "T3a": 7, "T3b": 8, "T4": 9,
}


# ── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class ASEligibilityCriteria:
    """Resultado de evaluación de elegibilidad para un protocolo de VA."""
    protocol: str
    protocol_label: str
    eligible: bool
    criteria_met: dict[str, bool] = field(default_factory=dict)
    criteria_failed: list[str] = field(default_factory=list)
    evidence_tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ASScheduleItem:
    """Item de agenda programada para protocolo de VA."""
    item_type: str  # "psa", "mri", "rebiopsy", "dre", "pro_assessment"
    title: str
    due_date: str
    interval_months: int
    status: str = "scheduled"  # "scheduled", "completed", "overdue", "missed"
    evidence_basis: list[str] = field(default_factory=list)
    priority: str = "routine"  # "routine", "mandatory", "urgent"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ASReclassificationTrigger:
    """Trigger de reclasificación detectado durante vigilancia activa."""
    trigger_type: str  # "gleason_upgrade", "volume_increase", "mri_new_lesion", "psa_kinetics", "adverse_histology"
    detected: bool
    detail: str
    severity: str  # "reclassification" (salida de VA) | "monitoring_intensification"
    recommended_action: str
    evidence_tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ActiveSurveillanceProtocol:
    """Estado completo del protocolo de vigilancia activa de un paciente."""
    patient_id: int | None = None
    enrollment_date: str = ""
    enrollment_protocol: str = ""
    baseline_biopsy_ref: int | None = None
    eligibility: list[ASEligibilityCriteria] = field(default_factory=list)
    schedule: list[ASScheduleItem] = field(default_factory=list)
    reclassification_triggers: list[ASReclassificationTrigger] = field(default_factory=list)
    confirmatory_biopsy_done: bool = False
    confirmatory_biopsy_date: str | None = None
    confirmatory_biopsy_due: str | None = None
    months_on_as: float = 0.0
    total_biopsies_on_as: int = 0
    total_mris_on_as: int = 0
    exit_reason: str | None = None  # "gleason_upgrade", "volume_increase", "patient_preference", "psa_kinetics", "mri_progression"
    exit_date: str | None = None
    exit_treatment: str | None = None  # "prostatectomy", "radiation", "focal_therapy"
    anxiety_monitoring: dict[str, Any] = field(default_factory=dict)
    conversion_rate_context: dict[str, Any] = field(default_factory=dict)
    status: str = "active"  # "active", "exited", "reclassified"

    def to_dict(self) -> dict[str, Any]:
        return {
            "patient_id": self.patient_id,
            "enrollment_date": self.enrollment_date,
            "enrollment_protocol": self.enrollment_protocol,
            "baseline_biopsy_ref": self.baseline_biopsy_ref,
            "eligibility": [e.to_dict() for e in self.eligibility],
            "schedule": [s.to_dict() for s in self.schedule],
            "reclassification_triggers": [t.to_dict() for t in self.reclassification_triggers],
            "confirmatory_biopsy_done": self.confirmatory_biopsy_done,
            "confirmatory_biopsy_date": self.confirmatory_biopsy_date,
            "confirmatory_biopsy_due": self.confirmatory_biopsy_due,
            "months_on_as": self.months_on_as,
            "total_biopsies_on_as": self.total_biopsies_on_as,
            "total_mris_on_as": self.total_mris_on_as,
            "exit_reason": self.exit_reason,
            "exit_date": self.exit_date,
            "exit_treatment": self.exit_treatment,
            "anxiety_monitoring": dict(self.anxiety_monitoring),
            "conversion_rate_context": dict(self.conversion_rate_context),
            "status": self.status,
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


def _tstage_leq(patient_tstage: str, max_tstage: str) -> bool:
    """Retorna True si el T-stage del paciente es ≤ max_tstage."""
    return T_STAGE_ORDER.get(patient_tstage, 99) <= T_STAGE_ORDER.get(max_tstage, 99)


# ── Servicio principal ───────────────────────────────────────────────────────

class ActiveSurveillanceService:
    """Motor de vigilancia activa con elegibilidad multi-protocolo y detección de reclasificación."""

    @staticmethod
    def check_eligibility(patient: dict[str, Any], state: str) -> list[ASEligibilityCriteria]:
        """Evalúa elegibilidad del paciente para todos los protocolos de VA."""
        results: list[ASEligibilityCriteria] = []

        isup = _safe_int(patient.get("isup_grade"))
        psa = _safe_float(patient.get("psa"))
        psad = _safe_float(patient.get("psad"))
        tstage = patient.get("clinical_tstage", "")
        cores_positive = _safe_int(patient.get("num_cores_positive"))
        total_cores = _safe_int(patient.get("total_cores"))
        max_involvement = _safe_float(patient.get("max_core_involvement"))
        # Convertir proporción a porcentaje si es necesario
        if max_involvement is not None and max_involvement <= 1.0:
            max_involvement = max_involvement * 100
        cribriform = patient.get("cribriform_pattern", False)
        intraductal = patient.get("intraductal_carcinoma", False)
        if isinstance(cribriform, str):
            cribriform = cribriform.lower() in ("true", "1", "si", "sí", "yes")
        if isinstance(intraductal, str):
            intraductal = intraductal.lower() in ("true", "1", "si", "sí", "yes")
        # Decipher score numérico (UCSF requiere ≤0.60); retrocompat con categórico.
        decipher_score = _safe_float(
            patient.get("decipher_score_numeric")
            or patient.get("decipher_score")
        )
        decipher_categorical = str(patient.get("genomic_classifier_result", "") or "").lower()

        for protocol_id, protocol in AS_PROTOCOLS.items():
            criteria = protocol["criteria"]
            met: dict[str, bool] = {}
            failed: list[str] = []

            # ISUP Grade Group
            if isup is not None:
                met["isup"] = isup <= criteria["isup_max"]
                if not met["isup"]:
                    failed.append(f"ISUP {isup} > máximo permitido {criteria['isup_max']}")
            else:
                met["isup"] = False
                failed.append("ISUP no documentado")

            # PSA
            if psa is not None:
                met["psa"] = psa <= criteria["psa_max"]
                if not met["psa"]:
                    failed.append(f"PSA {psa:.1f} > máximo {criteria['psa_max']}")
            else:
                met["psa"] = False
                failed.append("PSA no documentado")

            # T-stage
            if tstage:
                met["tstage"] = _tstage_leq(tstage, criteria["tstage_max"])
                if not met["tstage"]:
                    failed.append(f"T-stage {tstage} > máximo {criteria['tstage_max']}")
            else:
                met["tstage"] = False
                failed.append("T-stage no documentado")

            # Cores positivos
            if cores_positive is not None:
                met["cores_positive"] = cores_positive <= criteria["cores_positive_max"]
                if not met["cores_positive"]:
                    failed.append(f"{cores_positive} cores+ > máximo {criteria['cores_positive_max']}")
            else:
                met["cores_positive"] = True  # si no documentado, no falla por esto

            # Máximo involvement
            if max_involvement is not None:
                met["max_involvement"] = max_involvement <= criteria["max_involvement_pct"]
                if not met["max_involvement"]:
                    failed.append(f"Involucramiento {max_involvement:.0f}% > máximo {criteria['max_involvement_pct']}%")
            else:
                met["max_involvement"] = True

            # PSAD (solo algunos protocolos)
            if "psad_max" in criteria:
                if psad is not None:
                    met["psad"] = psad <= criteria["psad_max"]
                    if not met["psad"]:
                        failed.append(f"PSAD {psad:.2f} > máximo {criteria['psad_max']}")
                else:
                    met["psad"] = True  # no falla si no disponible

            # Cribriforme / Intraductal (solo protocolos que lo exigen)
            if criteria.get("no_cribriform"):
                met["no_cribriform"] = not cribriform
                if not met["no_cribriform"]:
                    failed.append("Patrón cribriforme presente — excluye de este protocolo")
            if criteria.get("no_intraductal"):
                met["no_intraductal"] = not intraductal
                if not met["no_intraductal"]:
                    failed.append("Carcinoma intraductal presente — excluye de este protocolo")

            # Decipher score (UCSF exige ≤0.60). Retrocompat: si no hay score numérico,
            # usar categórico — "Alto" bloquea, cualquier otro valor (o ausencia) pasa.
            if "decipher_score_max" in criteria:
                if decipher_score is not None:
                    met["decipher"] = decipher_score <= criteria["decipher_score_max"]
                    if not met["decipher"]:
                        failed.append(
                            f"Decipher {decipher_score:.2f} > máximo {criteria['decipher_score_max']} "
                            "(alto riesgo biológico)"
                        )
                elif decipher_categorical == "alto":
                    met["decipher"] = False
                    failed.append("Decipher categórico 'Alto' — excluye de UCSF AS")
                else:
                    met["decipher"] = True  # no falla si no disponible

            eligible = all(met.values())
            results.append(ASEligibilityCriteria(
                protocol=protocol_id,
                protocol_label=protocol["label"],
                eligible=eligible,
                criteria_met=met,
                criteria_failed=failed,
                evidence_tags=protocol["evidence_tags"],
            ))

        return results

    @staticmethod
    def build_as_schedule(
        enrollment_date: str,
        protocol: str,
        confirmatory_done: bool = False,
        payload: dict | None = None,
    ) -> list[ASScheduleItem]:
        """Construye calendario de seguimiento para el protocolo de VA seleccionado."""
        protocol_config = AS_PROTOCOLS.get(protocol)
        if not protocol_config:
            return []

        schedule_config = protocol_config["schedule"]
        enrollment = _parse_date(enrollment_date)
        if not enrollment:
            return []

        payload = payload or {}
        items: list[ASScheduleItem] = []
        today = date.today()

        # PSA periódico (primer año cada 3-6 meses, luego según protocolo)
        psa_interval = schedule_config["psa_interval_months"]
        for i in range(1, 13):  # 12 periodos de seguimiento (~3-6 años)
            months_offset = psa_interval * i
            due = date(
                enrollment.year + (enrollment.month + months_offset - 1) // 12,
                (enrollment.month + months_offset - 1) % 12 + 1,
                min(enrollment.day, 28),
            )
            status = "completed" if due < today else "scheduled"
            items.append(ASScheduleItem(
                item_type="psa",
                title=f"PSA #{i}",
                due_date=due.isoformat(),
                interval_months=psa_interval,
                status=status,
                evidence_basis=protocol_config["evidence_tags"],
                priority="routine",
            ))

        # Biopsia confirmatoria (12 meses)
        if not confirmatory_done:
            confirm_months = schedule_config["rebiopsy_interval_months"]
            confirm_due = date(
                enrollment.year + (enrollment.month + confirm_months - 1) // 12,
                (enrollment.month + confirm_months - 1) % 12 + 1,
                min(enrollment.day, 28),
            )
            overdue = confirm_due < today
            items.append(ASScheduleItem(
                item_type="rebiopsy",
                title="Biopsia confirmatoria (obligatoria)",
                due_date=confirm_due.isoformat(),
                interval_months=confirm_months,
                status="overdue" if overdue else "scheduled",
                evidence_basis=protocol_config["evidence_tags"] + ["Canary PASS confirmatory"],
                priority="mandatory",
            ))

        # MRI periódica — ajuste dinámico por PI-RADS (NCCN 2026 / PRECISE)
        latest_pirads = int(payload.get("latest_pirads", 0) or 0) if isinstance(payload, dict) else 0
        if latest_pirads >= 4:
            # PI-RADS 4-5: biopsia dirigida urgente, no esperar MRI de rutina
            items.append(ASScheduleItem(
                item_type="mri",
                title="RMmp + biopsia dirigida URGENTE (PI-RADS ≥4)",
                due_date=date(
                    enrollment.year + (enrollment.month + 2) // 12,
                    (enrollment.month + 2) % 12 + 1,
                    min(enrollment.day, 28),
                ).isoformat(),
                interval_months=3,
                status="scheduled",
                evidence_basis=protocol_config["evidence_tags"] + ["PRECISE recommendations", "PI-RADS ≥4 mandates targeted biopsy"],
                priority="urgent",
            ))
        mri_interval = 6 if latest_pirads == 3 else schedule_config["mri_interval_months"]
        for i in range(1, 6):  # 5 MRIs
            months_offset = mri_interval * i
            due = date(
                enrollment.year + (enrollment.month + months_offset - 1) // 12,
                (enrollment.month + months_offset - 1) % 12 + 1,
                min(enrollment.day, 28),
            )
            status = "completed" if due < today else "scheduled"
            items.append(ASScheduleItem(
                item_type="mri",
                title=f"RMmp #{i}" + (" (intervalo acortado por PI-RADS 3)" if latest_pirads == 3 else ""),
                due_date=due.isoformat(),
                interval_months=mri_interval,
                status=status,
                evidence_basis=protocol_config["evidence_tags"] + ["PRECISE recommendations"],
                priority="routine" if latest_pirads < 3 else "high",
            ))

        # DRE periódico
        dre_interval = schedule_config["dre_interval_months"]
        for i in range(1, 6):
            months_offset = dre_interval * i
            due = date(
                enrollment.year + (enrollment.month + months_offset - 1) // 12,
                (enrollment.month + months_offset - 1) % 12 + 1,
                min(enrollment.day, 28),
            )
            items.append(ASScheduleItem(
                item_type="dre",
                title=f"Tacto rectal #{i}",
                due_date=due.isoformat(),
                interval_months=dre_interval,
                status="completed" if due < today else "scheduled",
                evidence_basis=protocol_config["evidence_tags"],
                priority="routine",
            ))

        # Re-biopsias subsecuentes (después de la confirmatoria)
        ongoing_interval = schedule_config["rebiopsy_ongoing_months"]
        confirm_months = schedule_config["rebiopsy_interval_months"]
        for i in range(1, 4):  # 3 rebiopsias adicionales
            months_offset = confirm_months + (ongoing_interval * i)
            due = date(
                enrollment.year + (enrollment.month + months_offset - 1) // 12,
                (enrollment.month + months_offset - 1) % 12 + 1,
                min(enrollment.day, 28),
            )
            items.append(ASScheduleItem(
                item_type="rebiopsy",
                title=f"Rebiopsia de seguimiento #{i + 1}",
                due_date=due.isoformat(),
                interval_months=ongoing_interval,
                status="completed" if due < today else "scheduled",
                evidence_basis=protocol_config["evidence_tags"],
                priority="routine",
            ))

        # Evaluación PROs / ansiedad cada 6 meses
        for i in range(1, 11):
            months_offset = 6 * i
            due = date(
                enrollment.year + (enrollment.month + months_offset - 1) // 12,
                (enrollment.month + months_offset - 1) % 12 + 1,
                min(enrollment.day, 28),
            )
            items.append(ASScheduleItem(
                item_type="pro_assessment",
                title=f"Evaluación QoL/ansiedad #{i}",
                due_date=due.isoformat(),
                interval_months=6,
                status="completed" if due < today else "scheduled",
                evidence_basis=["ICHOM localized prostate cancer", "MAX-PC anxiety"],
                priority="routine",
            ))

        return sorted(items, key=lambda x: x.due_date)

    @staticmethod
    def evaluate_reclassification(
        patient: dict[str, Any],
        current_biopsy: dict[str, Any] | None = None,
        previous_biopsy: dict[str, Any] | None = None,
        latest_mri: dict[str, Any] | None = None,
    ) -> list[ASReclassificationTrigger]:
        """Evalúa triggers de reclasificación durante la vigilancia activa."""
        triggers: list[ASReclassificationTrigger] = []

        # 1. Upgrade Gleason
        if current_biopsy and previous_biopsy:
            from prostanet.domains.patient_tracking.structured_biopsy import StructuredBiopsyService, StructuredBiopsyResult
            if isinstance(current_biopsy, StructuredBiopsyResult):
                upgrade = StructuredBiopsyService.evaluate_upgrade_from_previous(current_biopsy, previous_biopsy)
            else:
                curr_isup = _safe_int(current_biopsy.get("highest_isup") or current_biopsy.get("isup_grade"))
                prev_isup = _safe_int(previous_biopsy.get("highest_isup") or previous_biopsy.get("isup_grade"))
                upgrade_detected = (curr_isup or 0) > (prev_isup or 0) if curr_isup and prev_isup else False
                upgrade = {"upgrade": upgrade_detected, "from_isup": prev_isup, "to_isup": curr_isup}

            if upgrade.get("upgrade"):
                to_isup = upgrade.get("to_isup", 0)
                severity = "reclassification" if (to_isup or 0) >= 2 else "monitoring_intensification"
                triggers.append(ASReclassificationTrigger(
                    trigger_type="gleason_upgrade",
                    detected=True,
                    detail=f"Upgrade histológico: ISUP {upgrade.get('from_isup')} → {upgrade.get('to_isup')}",
                    severity=severity,
                    recommended_action="Salida de VA y discusión de tratamiento definitivo" if severity == "reclassification" else "Intensificar seguimiento, considerar tratamiento definitivo",
                    evidence_tags=["NCCN 2026 AS reclassification", "EAU 2026 AS"],
                ))

        # 2. Aumento de volumen (>50% cores positivos o involvement máximo >70%)
        if current_biopsy:
            pct_cores = _safe_float(current_biopsy.get("percent_positive_cores"))
            max_inv = _safe_float(current_biopsy.get("max_involvement_pct"))
            if pct_cores and pct_cores > 50:
                triggers.append(ASReclassificationTrigger(
                    trigger_type="volume_increase",
                    detected=True,
                    detail=f"{pct_cores:.0f}% cores positivos (umbral: ≤50%)",
                    severity="reclassification",
                    recommended_action="Alto volumen tumoral. Evaluar prostatectomía o radioterapia definitiva.",
                    evidence_tags=["NCCN 2026 AS volume criteria"],
                ))
            elif max_inv and max_inv > 70:
                triggers.append(ASReclassificationTrigger(
                    trigger_type="volume_increase",
                    detected=True,
                    detail=f"Involucramiento máximo por cilindro: {max_inv:.0f}% (umbral: ≤50-70%)",
                    severity="monitoring_intensification",
                    recommended_action="Considerar acortar intervalo de rebiopsia. Discutir tratamiento definitivo.",
                    evidence_tags=["EAU 2026 AS volume criteria"],
                ))

        # 3. Nueva lesión MRI PI-RADS ≥4
        if latest_mri:
            pirads = _safe_int(latest_mri.get("pirads_score"))
            if pirads and pirads >= 4:
                triggers.append(ASReclassificationTrigger(
                    trigger_type="mri_new_lesion",
                    detected=True,
                    detail=f"Lesión PI-RADS {pirads} detectada en RMmp",
                    severity="monitoring_intensification",
                    recommended_action="Biopsia dirigida indicada dentro de 3 meses. Si upgrade histológico: salida de VA.",
                    evidence_tags=["PI-RADS v2.1", "PRECISE recommendations"],
                ))

        # 4. Cinética de PSA desfavorable
        psadt_months = _safe_float(patient.get("psadt_months") or patient.get("psa_doubling_time"))
        if psadt_months is not None and 0 < psadt_months < 36:
            severity = "reclassification" if psadt_months < 12 else "monitoring_intensification"
            triggers.append(ASReclassificationTrigger(
                trigger_type="psa_kinetics",
                detected=True,
                detail=f"PSADT: {psadt_months:.1f} meses (umbral orientativo: >36 meses favorable)",
                severity=severity,
                recommended_action="Considerar biopsia de re-estadificación y MRI si no reciente" if severity == "monitoring_intensification" else "Cinética PSA muy rápida, evaluar salida de VA",
                evidence_tags=["PRIAS PSA kinetics", "EAU 2026 PSA kinetics in AS"],
            ))

        # 5. Histología adversa (cribriforme / intraductal)
        if current_biopsy:
            cribriform = current_biopsy.get("any_cribriform", False)
            intraductal = current_biopsy.get("any_intraductal", False)
            if cribriform or intraductal:
                patterns = []
                if cribriform:
                    patterns.append("cribriforme")
                if intraductal:
                    patterns.append("intraductal")
                triggers.append(ASReclassificationTrigger(
                    trigger_type="adverse_histology",
                    detected=True,
                    detail=f"Patrón histológico adverso: {', '.join(patterns)}",
                    severity="reclassification",
                    recommended_action="Estos patrones se asocian con mayor riesgo de progresión. Evaluar salida de VA.",
                    evidence_tags=["Kweldam 2016 cribriform", "EAU 2026 IDC exclusion"],
                ))

        return triggers

    @staticmethod
    def build_as_protocol(patient: dict[str, Any], state: str) -> ActiveSurveillanceProtocol:
        """Construye el protocolo completo de vigilancia activa para un paciente."""
        eligibility = ActiveSurveillanceService.check_eligibility(patient, state)

        # Determinar mejor protocolo elegible
        best_protocol = ""
        for elig in eligibility:
            if elig.eligible:
                best_protocol = elig.protocol
                break

        as_data = patient.get("active_surveillance") or {}
        enrollment_date = as_data.get("enrollment_date", patient.get("diagnosis_date", ""))
        confirmatory_done = bool(as_data.get("confirmatory_biopsy_done", False))

        # Calcular meses en VA
        enrollment = _parse_date(enrollment_date)
        months_on_as = _months_between(enrollment, date.today()) if enrollment else 0.0

        # Construir schedule
        schedule = ActiveSurveillanceService.build_as_schedule(
            enrollment_date, best_protocol or "NCCN_low", confirmatory_done,
        )

        # Confirmatory biopsy status
        confirmatory_due = None
        if not confirmatory_done and enrollment:
            confirm_date = date(
                enrollment.year + (enrollment.month + 11) // 12,
                (enrollment.month + 11) % 12 + 1,
                min(enrollment.day, 28),
            )
            confirmatory_due = confirm_date.isoformat()

        # Evaluar reclasificación
        biopsies = patient.get("biopsies") or []
        current_biopsy = biopsies[-1] if biopsies else None
        previous_biopsy = biopsies[-2] if len(biopsies) >= 2 else None
        latest_mri_data = None
        mri_facts = patient.get("mri_facts") or []
        if mri_facts:
            latest_mri_data = mri_facts[-1] if isinstance(mri_facts[-1], dict) else None

        reclassification_triggers = ActiveSurveillanceService.evaluate_reclassification(
            patient, current_biopsy, previous_biopsy, latest_mri_data,
        )

        # Monitoreo de ansiedad
        anxiety_monitoring = {
            "instrument": "MAX-PC / Memorial Anxiety Scale for Prostate Cancer",
            "last_score": _safe_float(as_data.get("anxiety_score")),
            "last_date": as_data.get("anxiety_date"),
            "threshold_referral": 27,  # MAX-PC ≥27 → referir psico-oncología
            "status": "not_assessed",
        }
        if anxiety_monitoring["last_score"] is not None:
            anxiety_monitoring["status"] = "elevated" if anxiety_monitoring["last_score"] >= 27 else "normal"

        # Tasa de conversión contextual
        conversion_rate_context = {
            "published_5y_conversion_rate_pct": 27,  # ProtecT: ~27% a 5 años
            "published_10y_conversion_rate_pct": 44,  # ProtecT: ~44% a 10 años
            "reference": "ProtecT 15-year outcomes (Hamdy NEJM 2023)",
        }

        exit_reason = as_data.get("exit_reason")
        exit_date = as_data.get("exit_date")
        status = "exited" if exit_reason else "reclassified" if any(t.severity == "reclassification" for t in reclassification_triggers) else "active"

        return ActiveSurveillanceProtocol(
            patient_id=_safe_int(patient.get("patient_id") or patient.get("nss")),
            enrollment_date=enrollment_date,
            enrollment_protocol=best_protocol,
            baseline_biopsy_ref=_safe_int(as_data.get("baseline_biopsy_id")),
            eligibility=eligibility,
            schedule=schedule,
            reclassification_triggers=reclassification_triggers,
            confirmatory_biopsy_done=confirmatory_done,
            confirmatory_biopsy_date=as_data.get("confirmatory_biopsy_date"),
            confirmatory_biopsy_due=confirmatory_due,
            months_on_as=months_on_as,
            total_biopsies_on_as=len([b for b in biopsies if b.get("biopsy_context") in ("confirmatory_as", "followup_as")]),
            total_mris_on_as=len(mri_facts),
            exit_reason=exit_reason,
            exit_date=exit_date,
            exit_treatment=as_data.get("exit_treatment"),
            anxiety_monitoring=anxiety_monitoring,
            conversion_rate_context=conversion_rate_context,
            status=status,
        )

    @staticmethod
    def evaluate_as_alerts(
        patient_id: int,
        protocol: ActiveSurveillanceProtocol,
    ) -> list[dict[str, Any]]:
        """Genera alertas clínicas basadas en el estado de la vigilancia activa."""
        from prostanet.domains.patient_tracking.alert_engine import ClinicalAlert

        alerts: list[ClinicalAlert] = []

        # 1. Triggers de reclasificación
        for trigger in protocol.reclassification_triggers:
            if not trigger.detected:
                continue
            severity = "critical" if trigger.severity == "reclassification" else "warning"
            alerts.append(ClinicalAlert(
                patient_id=patient_id,
                alert_type=f"as_{trigger.trigger_type}",
                severity=severity,
                category="active_surveillance",
                title=f"VA — {trigger.detail}",
                message=trigger.recommended_action,
                recommended_action=trigger.recommended_action,
                guideline_reference="; ".join(trigger.evidence_tags),
                triggering_value=trigger.detail,
                threshold=trigger.severity,
            ))

        # 2. Biopsia confirmatoria vencida
        if not protocol.confirmatory_biopsy_done and protocol.confirmatory_biopsy_due:
            due = _parse_date(protocol.confirmatory_biopsy_due)
            if due and due < date.today():
                delay_months = _months_between(due, date.today())
                alerts.append(ClinicalAlert(
                    patient_id=patient_id,
                    alert_type="as_confirmatory_overdue",
                    severity="critical",
                    category="active_surveillance",
                    title=f"Biopsia confirmatoria vencida ({delay_months:.0f} meses de retraso)",
                    message=f"La biopsia confirmatoria era obligatoria a los 12 meses de enrollment. Llevan {delay_months:.0f} meses de retraso.",
                    recommended_action="Programar biopsia confirmatoria de forma urgente.",
                    guideline_reference="NCCN 2026 AS; Canary PASS confirmatory biopsy",
                    triggering_value=f"{delay_months:.0f} meses de retraso",
                    threshold="12 meses desde enrollment",
                ))

        # 3. Items de agenda vencidos
        overdue_mris = [s for s in protocol.schedule if s.item_type == "mri" and s.status == "overdue"]
        if overdue_mris:
            alerts.append(ClinicalAlert(
                patient_id=patient_id,
                alert_type="as_mri_overdue",
                severity="warning",
                category="active_surveillance",
                title=f"RMmp de seguimiento vencida ({len(overdue_mris)} pendientes)",
                message="La resonancia magnética multiparamétrica está vencida según protocolo de VA.",
                recommended_action="Programar RMmp dentro de las próximas 4 semanas.",
                guideline_reference="PRECISE recommendations; NCCN 2026 AS imaging",
                triggering_value=f"{len(overdue_mris)} MRI pendientes",
                threshold="Protocolo de VA",
            ))

        # 4. Ansiedad elevada
        anxiety = protocol.anxiety_monitoring
        if anxiety.get("status") == "elevated":
            alerts.append(ClinicalAlert(
                patient_id=patient_id,
                alert_type="as_anxiety_elevated",
                severity="info",
                category="active_surveillance",
                title="Ansiedad elevada en paciente bajo vigilancia activa",
                message=f"Score MAX-PC: {anxiety.get('last_score')}. Umbral para referencia: ≥{anxiety.get('threshold_referral')}.",
                recommended_action="Referir a psico-oncología. Discutir si la ansiedad afecta la adherencia al protocolo de VA.",
                guideline_reference="MAX-PC Scale; NCCN Survivorship anxiety screening",
                triggering_value=str(anxiety.get("last_score", "")),
                threshold=f"≥{anxiety.get('threshold_referral')}",
            ))

        # 5. Milestone positivo: >10 años estable
        if protocol.months_on_as > 120 and protocol.status == "active":
            alerts.append(ClinicalAlert(
                patient_id=patient_id,
                alert_type="as_stable_10y",
                severity="info",
                category="active_surveillance",
                title=f"Milestone: {protocol.months_on_as / 12:.0f} años estable en vigilancia activa",
                message="Paciente con >10 años en VA sin reclasificación. Excelente resultado oncológico.",
                recommended_action="Mantener protocolo de VA. Considerar espaciar intervalos de biopsia según edad y comorbilidades.",
                guideline_reference="ProtecT 15-year outcomes; EAU 2026 AS long-term",
                triggering_value=f"{protocol.months_on_as:.0f} meses",
                threshold="120 meses",
            ))

        return [a.to_dict() for a in alerts]

    @staticmethod
    def build_as_summary_for_profile(protocol: ActiveSurveillanceProtocol) -> dict[str, Any]:
        """Construye resumen de VA para mostrar en el perfil del paciente."""
        eligible_protocols = [e.protocol_label for e in protocol.eligibility if e.eligible]
        next_scheduled = [s for s in protocol.schedule if s.status == "scheduled"]
        overdue = [s for s in protocol.schedule if s.status == "overdue"]
        active_triggers = [t for t in protocol.reclassification_triggers if t.detected]

        tone = "success"
        if any(t.severity == "reclassification" for t in active_triggers):
            tone = "danger"
        elif overdue or any(t.severity == "monitoring_intensification" for t in active_triggers):
            tone = "warning"

        # EPIC 9 hardening / Auditoría #21 (cierre OOS-2): `has_data` también debe
        # ser True cuando el paciente documenta signos de AS reales (biopsia
        # confirmatoria completada, MRIs registradas, eligibilidad evaluada)
        # aunque `enrollment_protocol` esté vacío por falta de enrollment_date.
        # Esto refleja la realidad clínica: un paciente con confirmatory biopsy
        # hecha + MRI está en AS aunque el seed/EHR no incluya la fecha exacta
        # de inicio del protocolo.
        has_data = bool(
            protocol.enrollment_protocol
            or protocol.schedule
            or protocol.reclassification_triggers
            or protocol.confirmatory_biopsy_done
            or protocol.total_mris_on_as
            or protocol.total_biopsies_on_as
            or eligible_protocols
        )
        return {
            "has_data": has_data,
            "status": protocol.status,
            "tone": tone,
            "enrollment_date": protocol.enrollment_date,
            "enrollment_protocol": protocol.enrollment_protocol,
            "months_on_as": protocol.months_on_as,
            "years_on_as": round(protocol.months_on_as / 12, 1),
            "eligible_protocols": eligible_protocols,
            "confirmatory_biopsy_done": protocol.confirmatory_biopsy_done,
            "confirmatory_biopsy_due": protocol.confirmatory_biopsy_due,
            "total_biopsies": protocol.total_biopsies_on_as,
            "total_mris": protocol.total_mris_on_as,
            "active_triggers": [t.to_dict() for t in active_triggers],
            "trigger_count": len(active_triggers),
            "next_scheduled": [s.to_dict() for s in next_scheduled[:3]],
            "overdue_count": len(overdue),
            "anxiety_status": protocol.anxiety_monitoring.get("status", "not_assessed"),
            "exit_reason": protocol.exit_reason,
            "exit_treatment": protocol.exit_treatment,
            "conversion_rate_context": protocol.conversion_rate_context,
        }


# ── Wrapper longitudinal (EPIC 5) ────────────────────────────────────────────

def detect_reclassification_longitudinal(
    snapshots: Any,
) -> list[ASReclassificationTrigger]:
    """Fachada retrocompat: devuelve sólo la lista de triggers longitudinales.

    El engine completo (probabilidad, cinética, siguiente acción) vive en
    `prostanet.domains.patient_tracking.active_surveillance_longitudinal`.
    Importar de ahí directamente si se necesita el reporte enriquecido.
    """
    from prostanet.domains.patient_tracking.active_surveillance_longitudinal import (
        detect_reclassification_longitudinal as _engine,
    )
    return _engine(snapshots).triggers


# ── Ranking de protocolos por grupo de riesgo NCCN (EPIC 5) ──────────────────

# Prioridad de protocolo según grupo NCCN. El primer elegible de la lista es el
# "recommended_protocol". NCCN PROS-C v5.2026 enumera AS como cat 1 en muy bajo
# y bajo; cat 2A para intermedio favorable selecto. Referencias por protocolo
# embebidas en AS_PROTOCOLS[*]["evidence_tags"].
_PROTOCOL_RANKING_BY_NCCN_GROUP: dict[str, list[str]] = {
    "VERY LOW": ["NCCN_very_low", "PRIAS", "Canary_PASS", "Royal_Marsden", "Sunnybrook"],
    "LOW": ["NCCN_low", "Canary_PASS", "PRIAS", "Royal_Marsden", "Sunnybrook"],
    "FAVORABLE INTERMEDIATE": ["UCSF", "NCCN_favorable_intermediate"],
    # UNFAVORABLE+/HIGH/VERY HIGH no son candidatos a AS como 1a línea.
}


def rank_recommended_protocols(
    patient: dict[str, Any],
    nccn_group: str,
) -> list[dict[str, Any]]:
    """Ranking de protocolos de VA para el paciente según grupo NCCN.

    Devuelve lista ordenada con `{protocol, label, eligible, rank, reasons}`.
    El primero elegible es el `recommended_protocol`; consumidores downstream
    (UI, profile_compass) muestran alternativas para transparencia.
    """
    normalized_group = (nccn_group or "").upper().strip()
    preferred_order = _PROTOCOL_RANKING_BY_NCCN_GROUP.get(normalized_group, [])
    if not preferred_order:
        return []

    eligibility_results = ActiveSurveillanceService.check_eligibility(patient, "")
    eligibility_by_id = {e.protocol: e for e in eligibility_results}

    ranking: list[dict[str, Any]] = []
    for idx, protocol_id in enumerate(preferred_order):
        e = eligibility_by_id.get(protocol_id)
        config = AS_PROTOCOLS.get(protocol_id, {})
        ranking.append({
            "protocol": protocol_id,
            "label": config.get("label", protocol_id),
            "rank": idx + 1,
            "eligible": bool(e and e.eligible),
            "evidence_tags": list(config.get("evidence_tags", [])),
            "reasons_not_eligible": list(e.criteria_failed) if e and not e.eligible else [],
        })
    return ranking


def recommended_protocol(
    patient: dict[str, Any],
    nccn_group: str,
) -> str:
    """Atajo: ID del primer protocolo elegible en el ranking, o '' si ninguno."""
    for item in rank_recommended_protocols(patient, nccn_group):
        if item["eligible"]:
            return item["protocol"]
    return ""
