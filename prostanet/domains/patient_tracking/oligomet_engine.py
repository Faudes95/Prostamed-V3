# -*- coding: utf-8 -*-
"""
Motor de decisión oligometastásica: SBRT eligibility, oligoprogresión y MDT vs sistémico.

Evalúa candidatura a terapia dirigida a metástasis (MDT) y genera
recomendaciones de SBRT por sitio anatómico con dosis y fraccionamiento.

Reference:
  ORIOLE (Phillips 2020) — SBRT in oligometastatic PCa
  STOMP (Ost 2018) — Surveillance vs MDT in oligorecurrent PCa
  SABR-COMET (Palma 2019) — SABR for oligometastatic cancers
  PEACE-V/STORM — MDT + systemic in oligometastatic mHSPC
  NCCN 5.2026 / ASTRO-ESTRO 2023 consensus
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SBRTDoseRecommendation:
    """Recomendación de dosis SBRT por sitio anatómico."""
    site: str
    dose_primary: str
    dose_alternative: str
    fractions: str
    oar_constraints: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Dosis SBRT por sitio (ASTRO/ESTRO 2023)
SBRT_DOSE_BY_SITE: dict[str, SBRTDoseRecommendation] = {
    "bone": SBRTDoseRecommendation("Hueso", "24 Gy / 3 fx", "35 Gy / 5 fx", "3-5", "Médula espinal <18 Gy (3 fx)"),
    "spine": SBRTDoseRecommendation("Columna", "24 Gy / 3 fx", "30 Gy / 5 fx", "3-5", "Médula espinal <18 Gy, esófago <27 Gy"),
    "lymph_node": SBRTDoseRecommendation("Ganglio", "30-36 Gy / 3-5 fx", "24 Gy / 3 fx", "3-5", "Intestino <25 Gy, vasos <37 Gy"),
    "liver": SBRTDoseRecommendation("Hígado", "45-60 Gy / 3-5 fx", "50 Gy / 5 fx", "3-5", "Hígado sano >700 cc <15 Gy, estómago <25 Gy"),
    "lung": SBRTDoseRecommendation("Pulmón", "48-54 Gy / 3 fx", "50 Gy / 5 fx", "3-5", "Pulmón sano V20 <10%, esófago <27 Gy"),
    "adrenal": SBRTDoseRecommendation("Suprarrenal", "36-40 Gy / 5 fx", "24 Gy / 3 fx", "3-5", "Riñón ipsilateral <18 Gy, intestino <25 Gy"),
}


class OligometDecisionEngine:
    """Motor de decisión para enfermedad oligometastásica."""

    @classmethod
    def evaluate(cls, patient: dict[str, Any]) -> dict[str, Any]:
        """Evalúa candidatura oligometastásica completa."""
        lesions = patient.get("lesions") or []
        lesion_count = len(lesions) if lesions else int(patient.get("metastasis_count") or patient.get("lesion_count") or 0)
        volume_disease = str(
            patient.get("volume_disease")
            or patient.get("metastasis_volume_context")
            or ""
        ).strip().lower()
        psma_profile = dict(patient.get("psma_structured_profile") or {})
        psma_avid = bool(psma_profile.get("psma_positive")) if psma_profile else str(patient.get("psma_positive", "0")) == "1"
        psma_pattern = str(psma_profile.get("psma_uptake_pattern") or "")
        psma_rads = str(psma_profile.get("psma_rads_score") or "")
        psma_negative_dominant = bool(psma_profile.get("psma_negative_dominant_lesions")) or str(patient.get("psma_negative_dominant_lesions", "0")) == "1"
        has_visceral = any(
            str(l.get("anatomical_location", "")).lower() in {"liver", "hígado", "lung", "pulmón", "brain", "cerebro"}
            for l in lesions
        ) if lesions else str(patient.get("metastasis_site", "")).lower() in {"visceral", "liver", "lung"}
        is_oligometastatic = lesion_count <= 5 and lesion_count > 0 and not has_visceral and volume_disease != "high"

        result: dict[str, Any] = {
            "lesion_count": lesion_count,
            "is_oligometastatic": is_oligometastatic,
            "psma_avid": psma_avid,
            "psma_pattern": psma_pattern,
            "psma_rads_score": psma_rads,
            "has_visceral": has_visceral,
            "volume_disease": volume_disease,
        }

        # SBRT eligibility
        result["sbrt_eligibility"] = cls._evaluate_sbrt_eligibility(
            lesions,
            lesion_count,
            psma_avid,
            has_visceral,
            psma_pattern,
            psma_rads,
            psma_negative_dominant,
            high_volume=volume_disease == "high",
        )

        # Oligoprogression detection
        result["oligoprogression"] = cls._detect_oligoprogression(patient, lesions)

        # MDT vs systemic decision
        result["mdt_decision"] = cls._mdt_vs_systemic(patient, lesions, lesion_count, psma_avid, has_visceral, psma_pattern, psma_rads, psma_negative_dominant)

        # SBRT dose recommendations per lesion
        result["sbrt_doses"] = cls._sbrt_dose_recommendations(lesions)

        result["has_data"] = bool(result["is_oligometastatic"] or result["oligoprogression"].get("detected"))

        return result

    @staticmethod
    def _evaluate_sbrt_eligibility(lesions: list, lesion_count: int,
                                    psma_avid: bool, has_visceral: bool, psma_pattern: str, psma_rads: str,
                                    psma_negative_dominant: bool, high_volume: bool = False) -> dict[str, Any]:
        eligible = True
        reasons: list[str] = []
        disqualifiers: list[str] = []

        if lesion_count > 5:
            eligible = False
            disqualifiers.append(f">{5} lesiones ({lesion_count}) — excede definición oligometastásica")
        if lesion_count == 0:
            eligible = False
            disqualifiers.append("Sin lesiones documentadas")
        if has_visceral:
            eligible = False
            disqualifiers.append("Metástasis viscerales documentadas — no sostener etiqueta oligometastásica/SBRT como vía principal")
        if high_volume:
            eligible = False
            disqualifiers.append("Fenotipo de alto volumen — priorizar intensificación sistémica sobre vía oligometastásica")

        # Check individual lesion size
        oversized: list[str] = []
        for l in lesions:
            size = l.get("longest_diameter_mm") or l.get("size_mm")
            if size:
                try:
                    if float(size) > 50:
                        oversized.append(f"{l.get('anatomical_location', '?')}: {size}mm")
                except (ValueError, TypeError):
                    pass
        if oversized:
            eligible = False
            disqualifiers.append(f"Lesión(es) >5cm: {', '.join(oversized)}")

        if not psma_avid:
            reasons.append("PSMA no confirmado — elegibilidad reducida")
        if psma_pattern == "diseminado":
            eligible = False
            disqualifiers.append("Patrón PSMA diseminado — no sostener etiqueta oligometastásica fuerte")
        if psma_rads == "3":
            reasons.append("PSMA-RADS 3 — confianza intermedia, MDT solo como contexto discutible")
        if psma_negative_dominant:
            reasons.append("Lesiones dominantes PSMA-negativas — confianza reducida para MDT basado solo en PET")

        if eligible:
            if psma_avid:
                reasons.append("Candidato SBRT: ≤5 lesiones PSMA-avid, cada ≤5cm")
            else:
                reasons.append("Posible candidato SBRT, pero confirmar PSMA-PET")

        return {
            "eligible": eligible,
            "reasons": reasons,
            "disqualifiers": disqualifiers,
            "trial_reference": "ORIOLE (Phillips 2020), STOMP (Ost 2018), SABR-COMET (Palma 2019)",
        }

    @staticmethod
    def _detect_oligoprogression(patient: dict[str, Any], lesions: list) -> dict[str, Any]:
        """Detecta oligoprogresión: ≤3 nuevas lesiones mientras resto controlado."""
        new_lesions = [l for l in lesions if str(l.get("current_status", "")).lower() in {"new", "nueva", "progressing", "progresando"}]
        stable_lesions = [l for l in lesions if str(l.get("current_status", "")).lower() in {"stable", "estable", "responding", "respondiendo", "controlled"}]

        is_oligoprogression = (
            1 <= len(new_lesions) <= 3
            and len(stable_lesions) >= 1
            and str(patient.get("overall_response", "")).lower() not in {"pd", "progressive_disease"}
        )

        recommendation = ""
        if is_oligoprogression:
            recommendation = "Oligoprogresión detectada: considerar SBRT focal a lesiones nuevas + continuar línea sistémica actual. Evitar cambio sistémico prematuro."

        return {
            "detected": is_oligoprogression,
            "new_lesion_count": len(new_lesions),
            "stable_lesion_count": len(stable_lesions),
            "recommendation": recommendation,
            "reference": "NCCN 2026, Gillessen expert consensus 2022",
        }

    @staticmethod
    def _mdt_vs_systemic(patient: dict[str, Any], lesions: list,
                          lesion_count: int, psma_avid: bool, has_visceral: bool, psma_pattern: str,
                          psma_rads: str, psma_negative_dominant: bool) -> dict[str, Any]:
        """Algoritmo de decisión MDT vs sistémico."""
        if lesion_count == 0 or lesion_count > 5:
            return {"decision": "systemic_only", "rationale": "No oligometastásico — sistémico estándar"}

        if has_visceral:
            return {
                "decision": "systemic_primary",
                "rationale": "Metástasis visceral presente — sistémico prioritario. MDT solo en contexto de oligoprogresión focal.",
                "reference": "NCCN 2026",
            }
        if psma_pattern == "diseminado":
            return {
                "decision": "systemic_primary",
                "rationale": "Patrón PSMA diseminado — degradar la vía oligometastásica fuerte y priorizar sistémico.",
                "reference": "NCCN 2026 / PSMA contextual",
            }

        if psma_avid:
            if psma_rads == "3":
                return {
                    "decision": "contextual_mdt_only",
                    "rationale": "PSMA-RADS 3 mantiene incertidumbre; MDT solo debe discutirse con correlación adicional.",
                    "reference": "PSMA-RADS contextual",
                }
            non_psma = [l for l in lesions if str(l.get("psma_avid", "1")) == "0"]
            if non_psma or psma_negative_dominant:
                return {
                    "decision": "biopsy_then_decide",
                    "rationale": f"Lesión(es) no PSMA-avid o dominantes PSMA-negativas detectada(s) ({max(len(non_psma), 1)}). Biopsia recomendada antes de MDT para descartar histología discordante.",
                    "reference": "PEACE-V trial design",
                }
            return {
                "decision": "mdt_plus_systemic",
                "rationale": "Oligometastásico PSMA-avid confirmado → MDT (SBRT) + continuar sistémico.",
                "reference": "ORIOLE, STOMP, SABR-COMET",
            }

        return {
            "decision": "confirm_psma",
            "rationale": "Oligometastásico sin PSMA-PET — confirmar con imagen funcional antes de decidir MDT.",
        }

    @staticmethod
    def _sbrt_dose_recommendations(lesions: list) -> list[dict[str, Any]]:
        """Genera recomendaciones de dosis SBRT por sitio para cada lesión."""
        doses: list[dict[str, Any]] = []
        for l in lesions:
            location = str(l.get("anatomical_location", "")).lower()
            # Map to dose category
            if any(k in location for k in ("spine", "columna", "vertebr")):
                dose = SBRT_DOSE_BY_SITE["spine"]
            elif any(k in location for k in ("bone", "hueso", "pelv", "femur", "iliac", "sacr", "cost")):
                dose = SBRT_DOSE_BY_SITE["bone"]
            elif any(k in location for k in ("lymph", "gangli", "node")):
                dose = SBRT_DOSE_BY_SITE["lymph_node"]
            elif any(k in location for k in ("liver", "hígado", "hepat")):
                dose = SBRT_DOSE_BY_SITE["liver"]
            elif any(k in location for k in ("lung", "pulmón", "pulmon")):
                dose = SBRT_DOSE_BY_SITE["lung"]
            elif any(k in location for k in ("adrenal", "supraren")):
                dose = SBRT_DOSE_BY_SITE["adrenal"]
            else:
                dose = SBRT_DOSE_BY_SITE["bone"]  # Default

            doses.append({
                "lesion_id": l.get("lesion_id", "?"),
                "location": l.get("anatomical_location", "Desconocido"),
                "dose": dose.to_dict(),
            })
        return doses
