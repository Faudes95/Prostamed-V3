# -*- coding: utf-8 -*-
"""
Motor de reglas PRO (Patient-Reported Outcomes) para decisión clínica.

Evalúa umbrales y deltas de PROs que generan alertas y modifican
recomendaciones terapéuticas. Basado en ICHOM Standard Set para
cáncer de próstata y guías ASCO 2025-2026.

Reference:
  ICHOM Standard Set for Localized Prostate Cancer (Martin 2015)
  Basch E et al. JAMA 2017 — PROs in cancer care
  NCCN 5.2026 Survivorship / Supportive Care
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PROAlert:
    """Alerta generada por un PRO que cruza un umbral clínico."""
    alert_type: str
    severity: str  # info | warning | critical
    category: str  # qol | pain | urinary | sexual | fatigue | psychological | composite
    title: str
    message: str
    recommended_action: str
    pro_name: str
    current_value: float | None = None
    previous_value: float | None = None
    threshold: str = ""
    reference: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PRODecisionEngine:
    """Evalúa PROs y genera alertas clínicas accionables."""

    @classmethod
    def evaluate_all(cls, patient_id: int, patient: dict[str, Any]) -> list[PROAlert]:
        alerts: list[PROAlert] = []
        alerts.extend(cls.evaluate_qol(patient))
        alerts.extend(cls.evaluate_pain(patient))
        alerts.extend(cls.evaluate_urinary(patient))
        alerts.extend(cls.evaluate_sexual(patient))
        alerts.extend(cls.evaluate_fatigue(patient))
        alerts.extend(cls.evaluate_psychological(patient))
        alerts.extend(cls.evaluate_composite_delta(patient))
        return alerts

    @staticmethod
    def evaluate_qol(patient: dict[str, Any]) -> list[PROAlert]:
        alerts: list[PROAlert] = []
        eq5d = _safe_float(patient.get("eq5d_vas"))
        eq5d_prev = _safe_float(patient.get("eq5d_vas_previous"))
        if eq5d is not None and eq5d_prev is not None:
            delta = eq5d_prev - eq5d
            if delta >= 20:
                alerts.append(PROAlert(
                    alert_type="qol_severe_decline",
                    severity="critical",
                    category="qol",
                    title=f"Deterioro QoL severo — EQ-5D cayó {delta:.0f} puntos",
                    message=f"EQ-5D VAS: {eq5d_prev:.0f} → {eq5d:.0f}. Caída ≥20 puntos en intervalo entre visitas.",
                    recommended_action="Evaluar causa del deterioro (progresión, toxicidad, comorbilidad). Considerar cambio de manejo y referencia paliativa.",
                    pro_name="EQ-5D VAS",
                    current_value=eq5d, previous_value=eq5d_prev,
                    threshold="Caída ≥20 puntos",
                    reference="Basch E et al. JAMA 2017",
                ))
        if eq5d is not None and eq5d < 40:
            alerts.append(PROAlert(
                alert_type="qol_very_low",
                severity="warning",
                category="qol",
                title=f"QoL muy baja — EQ-5D VAS {eq5d:.0f}/100",
                message="Calidad de vida autoreportada severamente comprometida.",
                recommended_action="Reunión clínica para reevaluar objetivos de tratamiento. Considerar de-escalar a confort.",
                pro_name="EQ-5D VAS",
                current_value=eq5d, threshold="<40/100",
                reference="ICHOM Standard Set",
            ))
        return alerts

    @staticmethod
    def evaluate_pain(patient: dict[str, Any]) -> list[PROAlert]:
        alerts: list[PROAlert] = []
        bpi = _safe_float(patient.get("bpi_worst_pain") or patient.get("pain_score"))
        bpi_prev = _safe_float(patient.get("bpi_worst_pain_previous") or patient.get("pain_score_previous"))
        if bpi is not None and bpi >= 7:
            alerts.append(PROAlert(
                alert_type="pain_severe",
                severity="critical",
                category="pain",
                title=f"Dolor severo — BPI {bpi:.0f}/10",
                message="Dolor peor ≥7/10. Requiere intervención urgente.",
                recommended_action="Escalar manejo del dolor (escalera OMS). Considerar RT paliativa si dolor óseo. Referir cuidados paliativos concurrentes.",
                pro_name="BPI Worst Pain",
                current_value=bpi, threshold="≥7/10",
                reference="NCCN Supportive Care / OMS escalera analgésica",
            ))
        elif bpi is not None and bpi_prev is not None and (bpi - bpi_prev) >= 3:
            alerts.append(PROAlert(
                alert_type="pain_escalation",
                severity="warning",
                category="pain",
                title=f"Dolor en escalada — BPI subió {bpi - bpi_prev:.0f} puntos",
                message=f"BPI: {bpi_prev:.0f} → {bpi:.0f}. Incremento ≥3 puntos entre visitas.",
                recommended_action="Evaluar causa (progresión ósea, fractura, neuropatía). Ajustar analgesia.",
                pro_name="BPI Worst Pain",
                current_value=bpi, previous_value=bpi_prev,
                threshold="Incremento ≥3 puntos",
                reference="NCCN Supportive Care",
            ))
        return alerts

    @staticmethod
    def evaluate_urinary(patient: dict[str, Any]) -> list[PROAlert]:
        alerts: list[PROAlert] = []
        ipss = _safe_float(patient.get("ipss_total"))
        ipss_prev = _safe_float(patient.get("ipss_total_previous"))
        if ipss is not None and ipss > 19:
            alerts.append(PROAlert(
                alert_type="luts_severe",
                severity="warning",
                category="urinary",
                title=f"LUTS severos — IPSS {ipss:.0f}/35",
                message="Sintomatología urinaria severa bajo tratamiento.",
                recommended_action="Considerar alfa-bloqueador. Evaluar 5-ARI. Referir urología funcional si persiste.",
                pro_name="IPSS",
                current_value=ipss, threshold=">19/35",
                reference="NCCN 5.2026 Survivorship",
            ))
        elif ipss is not None and ipss_prev is not None and (ipss - ipss_prev) >= 5:
            alerts.append(PROAlert(
                alert_type="luts_worsening",
                severity="warning",
                category="urinary",
                title=f"LUTS empeorando — IPSS subió {ipss - ipss_prev:.0f} puntos",
                message=f"IPSS: {ipss_prev:.0f} → {ipss:.0f}.",
                recommended_action="Evaluar causa (ADT, ARPI, progresión local). Ajustar manejo urológico.",
                pro_name="IPSS",
                current_value=ipss, previous_value=ipss_prev,
                threshold="Incremento ≥5 puntos",
                reference="ICHOM Standard Set",
            ))
        # Pad usage post-RP
        pads = _safe_float(patient.get("pad_usage"))
        months_post_rp = _safe_float(patient.get("months_since_rp"))
        if pads is not None and pads >= 3 and months_post_rp is not None and months_post_rp >= 12:
            alerts.append(PROAlert(
                alert_type="incontinence_persistent",
                severity="warning",
                category="urinary",
                title=f"Incontinencia persistente — {pads:.0f} paños/día a {months_post_rp:.0f} meses post-RP",
                message="Incontinencia significativa más allá de 12 meses post-prostatectomía.",
                recommended_action="Referir fisioterapia pélvica avanzada. Considerar sling o esfínter artificial.",
                pro_name="Pad count",
                current_value=pads, threshold="≥3 paños/día a ≥12 meses",
                reference="EAU 2026 QoL / NCCN Survivorship",
            ))
        return alerts

    @staticmethod
    def evaluate_sexual(patient: dict[str, Any]) -> list[PROAlert]:
        alerts: list[PROAlert] = []
        iief = _safe_float(patient.get("iief5_score"))
        iief_baseline = _safe_float(patient.get("iief5_baseline"))
        if iief is not None and iief < 10 and iief_baseline is not None and iief_baseline >= 17:
            alerts.append(PROAlert(
                alert_type="ed_severe_decline",
                severity="warning",
                category="sexual",
                title=f"DE severa bajo tratamiento — IIEF-5 {iief:.0f}/25",
                message=f"IIEF-5 cayó de {iief_baseline:.0f} (baseline) a {iief:.0f}. Disfunción eréctil severa.",
                recommended_action="Ofrecer PDE5i. Considerar dispositivo de vacío. Referir sexología oncológica.",
                pro_name="IIEF-5",
                current_value=iief, previous_value=iief_baseline,
                threshold="<10 con baseline ≥17",
                reference="ICHOM Standard Set / NCCN Survivorship",
            ))
        return alerts

    @staticmethod
    def evaluate_fatigue(patient: dict[str, Any]) -> list[PROAlert]:
        alerts: list[PROAlert] = []
        fatigue = _safe_float(patient.get("facit_fatigue") or patient.get("fatigue_score"))
        fatigue_prev = _safe_float(patient.get("facit_fatigue_previous") or patient.get("fatigue_score_previous"))
        # FACIT-Fatigue scale: 0-52, lower = more fatigue
        if fatigue is not None and fatigue < 30 and patient.get("facit_fatigue") is not None:
            alerts.append(PROAlert(
                alert_type="fatigue_disabling",
                severity="warning",
                category="fatigue",
                title=f"Fatiga incapacitante — FACIT-F {fatigue:.0f}/52",
                message="Fatiga severa que limita actividades diarias.",
                recommended_action="Evaluar anemia (Hb), hipotiroidismo (TSH), depresión. Considerar ejercicio estructurado y referir rehabilitación.",
                pro_name="FACIT-Fatigue",
                current_value=fatigue, threshold="<30/52",
                reference="NCCN Cancer-Related Fatigue / Minton O et al. Ann Oncol 2013",
            ))
        # Fatigue score 0-10 scale (higher = worse)
        elif fatigue is not None and fatigue >= 7 and patient.get("fatigue_score") is not None:
            alerts.append(PROAlert(
                alert_type="fatigue_severe",
                severity="warning",
                category="fatigue",
                title=f"Fatiga severa — Score {fatigue:.0f}/10",
                message="Fatiga autoreportada ≥7/10.",
                recommended_action="Evaluar causas reversibles (anemia, hipotiroidismo, depresión). Programa de ejercicio supervisado.",
                pro_name="Fatigue Score",
                current_value=fatigue, threshold="≥7/10",
                reference="NCCN Cancer-Related Fatigue",
            ))
        return alerts

    @staticmethod
    def evaluate_psychological(patient: dict[str, Any]) -> list[PROAlert]:
        alerts: list[PROAlert] = []
        anxiety = _safe_float(patient.get("anxiety_score"))
        if anxiety is not None and anxiety >= 7:
            alerts.append(PROAlert(
                alert_type="distress_high",
                severity="warning" if anxiety < 9 else "critical",
                category="psychological",
                title=f"Distress psicológico elevado — Ansiedad {anxiety:.0f}/10",
                message="Ansiedad autoreportada ≥7/10. Riesgo de no-adherencia y deterioro funcional.",
                recommended_action="Referir psicooncología. Considerar ISRS si ≥2 semanas. Screening de ideación suicida si ≥9.",
                pro_name="Anxiety Score",
                current_value=anxiety, threshold="≥7/10",
                reference="NCCN Distress Management / ASCO 2025",
            ))
        return alerts

    @staticmethod
    def evaluate_composite_delta(patient: dict[str, Any]) -> list[PROAlert]:
        """Detecta deterioro multidimensional: ≥3 PROs empeorando simultáneamente."""
        worsening_count = 0
        worsening_pros: list[str] = []

        checks = [
            ("eq5d_vas", "eq5d_vas_previous", True, 10, "EQ-5D VAS"),
            ("bpi_worst_pain", "bpi_worst_pain_previous", False, 2, "BPI Pain"),
            ("ipss_total", "ipss_total_previous", False, 3, "IPSS"),
            ("fatigue_score", "fatigue_score_previous", False, 2, "Fatigue"),
            ("anxiety_score", "anxiety_score_previous", False, 2, "Anxiety"),
        ]

        for current_key, prev_key, lower_is_worse, threshold, label in checks:
            curr = _safe_float(patient.get(current_key))
            prev = _safe_float(patient.get(prev_key))
            if curr is not None and prev is not None:
                delta = (prev - curr) if lower_is_worse else (curr - prev)
                if delta >= threshold:
                    worsening_count += 1
                    worsening_pros.append(label)

        if worsening_count >= 3:
            return [PROAlert(
                alert_type="composite_deterioration",
                severity="critical",
                category="composite",
                title=f"Deterioro multidimensional — {worsening_count} PROs empeorando",
                message=f"PROs en deterioro simultáneo: {', '.join(worsening_pros)}. Patrón sugiere progresión de enfermedad o toxicidad sistémica.",
                recommended_action="Reunión clínica urgente. Evaluar progresión de enfermedad. Considerar cambio de manejo integral.",
                pro_name="Composite",
                threshold="≥3 PROs empeorando simultáneamente",
                reference="ICHOM Standard Set / Basch E et al. JAMA 2017",
            )]
        return []


def _safe_float(val: Any) -> float | None:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
