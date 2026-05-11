# -*- coding: utf-8 -*-
"""
Motor de evaluación de respuesta terapéutica.

Implementa criterios estándar:
  - RECIST 1.1 para tejidos blandos
  - PCWG3 para enfermedad ósea
  - Criterios de respuesta PSA (PSA50, PSA90, progresión)
  - Evaluación compuesta

Referencia:
  Eisenhauer EA et al. Eur J Cancer 2009 (RECIST 1.1)
  Scher HI et al. J Clin Oncol 2016 (PCWG3)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SoftTissueResponse:
    """Respuesta RECIST 1.1 en tejidos blandos."""
    category: str  # "CR", "PR", "SD", "PD", "NE"
    sum_target_diameters_mm: float
    baseline_sum_mm: float
    nadir_sum_mm: float
    change_from_baseline_pct: float
    change_from_nadir_pct: float
    new_lesions: bool
    non_target_progression: bool
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BoneResponse:
    """Respuesta PCWG3 en enfermedad ósea."""
    status: str  # "no_new", "new_unconfirmed", "new_confirmed", "flare"
    new_lesion_count: int
    confirmation_scan_needed: bool
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PSAResponse:
    """Respuesta bioquímica (PSA)."""
    category: str  # "PSA90", "PSA50", "PSA30", "no_response", "progression"
    baseline_psa: float
    current_psa: float
    nadir_psa: float
    change_from_baseline_pct: float
    confirmed: bool  # confirmado a ≥4 semanas
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CompositeResponse:
    """Evaluación compuesta de respuesta."""
    overall: str  # "CR", "PR", "SD", "PD", "mixed", "NE"
    soft_tissue: SoftTissueResponse | None
    bone: BoneResponse | None
    psa: PSAResponse | None
    clinical_benefit: bool
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "overall": self.overall,
            "clinical_benefit": self.clinical_benefit,
            "details": self.details,
        }
        if self.soft_tissue:
            d["soft_tissue"] = self.soft_tissue.to_dict()
        if self.bone:
            d["bone"] = self.bone.to_dict()
        if self.psa:
            d["psa"] = self.psa.to_dict()
        return d


class ResponseAssessmentService:
    """Servicio de evaluación de respuesta terapéutica."""

    @staticmethod
    def assess_soft_tissue(
        current_sum_mm: float,
        baseline_sum_mm: float,
        nadir_sum_mm: float | None = None,
        new_lesions: bool = False,
        non_target_progression: bool = False,
    ) -> SoftTissueResponse:
        """
        Evalúa respuesta en tejidos blandos según RECIST 1.1.

        - CR: Desaparición de todas las lesiones target (sum = 0)
        - PR: Disminución ≥30% de la suma respecto a baseline
        - PD: Aumento ≥20% respecto a nadir Y aumento absoluto ≥5mm, o nuevas lesiones
        - SD: Ni PR ni PD
        """
        if baseline_sum_mm <= 0:
            return SoftTissueResponse(
                category="NE", sum_target_diameters_mm=current_sum_mm,
                baseline_sum_mm=baseline_sum_mm, nadir_sum_mm=0,
                change_from_baseline_pct=0, change_from_nadir_pct=0,
                new_lesions=new_lesions, non_target_progression=non_target_progression,
                details="No evaluable: sin mediciones baseline",
            )

        if nadir_sum_mm is None or nadir_sum_mm <= 0:
            nadir_sum_mm = baseline_sum_mm

        change_baseline = ((current_sum_mm - baseline_sum_mm) / baseline_sum_mm) * 100
        change_nadir = ((current_sum_mm - nadir_sum_mm) / nadir_sum_mm) * 100 if nadir_sum_mm > 0 else 0

        # Nuevas lesiones = PD automáticamente
        if new_lesions:
            category = "PD"
            details = "Progresión: nuevas lesiones detectadas."
        elif current_sum_mm == 0:
            category = "CR"
            details = "Respuesta completa: desaparición de todas las lesiones target."
        elif change_baseline <= -30:
            category = "PR"
            details = f"Respuesta parcial: reducción de {abs(change_baseline):.1f}% respecto a baseline."
        elif change_nadir >= 20 and (current_sum_mm - nadir_sum_mm) >= 5:
            category = "PD"
            details = f"Progresión: aumento de {change_nadir:.1f}% respecto a nadir (Δ ≥5mm)."
        elif non_target_progression:
            category = "PD"
            details = "Progresión: progresión inequívoca de lesiones no-target."
        else:
            category = "SD"
            details = f"Enfermedad estable: cambio de {change_baseline:+.1f}% respecto a baseline."

        return SoftTissueResponse(
            category=category,
            sum_target_diameters_mm=current_sum_mm,
            baseline_sum_mm=baseline_sum_mm,
            nadir_sum_mm=nadir_sum_mm,
            change_from_baseline_pct=round(change_baseline, 1),
            change_from_nadir_pct=round(change_nadir, 1),
            new_lesions=new_lesions,
            non_target_progression=non_target_progression,
            details=details,
        )

    @staticmethod
    def assess_bone(
        new_lesion_count: int = 0,
        prior_scan_new_lesions: int = 0,
        is_first_assessment: bool = False,
    ) -> BoneResponse:
        """
        Evalúa respuesta ósea según PCWG3.

        Regla 2+2:
        - Primera evaluación con ≥2 nuevas lesiones: no confirma progresión, requiere scan confirmatorio
        - Scan confirmatorio con ≥2 lesiones adicionales: confirma progresión ósea
        - Si las nuevas lesiones desaparecen en scan confirmatorio: flare
        """
        if new_lesion_count == 0:
            return BoneResponse(
                status="no_new",
                new_lesion_count=0,
                confirmation_scan_needed=False,
                details="Sin nuevas lesiones óseas. No hay progresión ósea.",
            )

        if is_first_assessment and new_lesion_count >= 2:
            return BoneResponse(
                status="new_unconfirmed",
                new_lesion_count=new_lesion_count,
                confirmation_scan_needed=True,
                details=f"{new_lesion_count} nuevas lesiones en primera evaluación. Requiere scan confirmatorio en 6-8 semanas (regla 2+2 PCWG3).",
            )

        if prior_scan_new_lesions >= 2 and new_lesion_count >= 2:
            return BoneResponse(
                status="new_confirmed",
                new_lesion_count=new_lesion_count + prior_scan_new_lesions,
                confirmation_scan_needed=False,
                details=f"Progresión ósea confirmada: {new_lesion_count} lesiones adicionales (regla 2+2 PCWG3 cumplida).",
            )

        if prior_scan_new_lesions >= 2 and new_lesion_count == 0:
            return BoneResponse(
                status="flare",
                new_lesion_count=0,
                confirmation_scan_needed=False,
                details="Posible flare: lesiones previas no confirmadas en scan de seguimiento.",
            )

        return BoneResponse(
            status="new_unconfirmed",
            new_lesion_count=new_lesion_count,
            confirmation_scan_needed=True,
            details=f"{new_lesion_count} nuevas lesiones. Seguimiento con scan confirmatorio recomendado.",
        )

    @staticmethod
    def assess_psa(
        baseline_psa: float,
        current_psa: float,
        nadir_psa: float | None = None,
        confirmed_at_4_weeks: bool = False,
    ) -> PSAResponse:
        """
        Evalúa respuesta de PSA.

        - PSA90: Disminución ≥90% desde baseline
        - PSA50: Disminución ≥50% desde baseline
        - PSA30: Disminución ≥30% desde baseline
        - Progresión: Aumento ≥25% Y ≥2 ng/mL sobre nadir
        """
        if baseline_psa <= 0:
            return PSAResponse(
                category="NE", baseline_psa=baseline_psa, current_psa=current_psa,
                nadir_psa=0, change_from_baseline_pct=0, confirmed=False,
                details="No evaluable: PSA baseline ≤ 0",
            )

        if nadir_psa is None or nadir_psa <= 0:
            nadir_psa = baseline_psa

        change_pct = ((current_psa - baseline_psa) / baseline_psa) * 100

        # Respuesta
        if change_pct <= -90:
            category = "PSA90"
            details = f"Respuesta PSA profunda: {abs(change_pct):.1f}% de reducción."
        elif change_pct <= -50:
            category = "PSA50"
            details = f"Respuesta PSA: {abs(change_pct):.1f}% de reducción."
        elif change_pct <= -30:
            category = "PSA30"
            details = f"Respuesta PSA parcial: {abs(change_pct):.1f}% de reducción."
        else:
            # Evaluar progresión
            rise_from_nadir = current_psa - nadir_psa
            rise_pct_nadir = ((current_psa - nadir_psa) / nadir_psa * 100) if nadir_psa > 0 else 0

            if rise_pct_nadir >= 25 and rise_from_nadir >= 2:
                category = "progression"
                details = f"Progresión PSA: aumento de {rise_pct_nadir:.1f}% sobre nadir ({nadir_psa:.2f} → {current_psa:.2f} ng/mL, Δ={rise_from_nadir:.2f})."
            else:
                category = "no_response"
                details = f"Sin respuesta significativa: cambio de {change_pct:+.1f}% desde baseline."

        return PSAResponse(
            category=category,
            baseline_psa=baseline_psa,
            current_psa=current_psa,
            nadir_psa=nadir_psa,
            change_from_baseline_pct=round(change_pct, 1),
            confirmed=confirmed_at_4_weeks,
            details=details,
        )

    @classmethod
    def composite_response(
        cls,
        soft_tissue: SoftTissueResponse | None = None,
        bone: BoneResponse | None = None,
        psa: PSAResponse | None = None,
    ) -> CompositeResponse:
        """
        Evaluación compuesta de respuesta per PCWG3.

        La progresión ósea o de tejidos blandos prevalece sobre respuesta PSA.
        """
        components: list[str] = []

        has_progression = False
        has_response = False

        if soft_tissue:
            if soft_tissue.category == "PD":
                has_progression = True
            elif soft_tissue.category in ("CR", "PR"):
                has_response = True
            components.append(f"RECIST: {soft_tissue.category}")

        if bone:
            if bone.status == "new_confirmed":
                has_progression = True
            components.append(f"Óseo: {bone.status}")

        if psa:
            if psa.category == "progression":
                # PSA sola no define progresión per PCWG3
                components.append(f"PSA: progresión (no confirmatoria sola)")
            elif psa.category in ("PSA50", "PSA90"):
                has_response = True
                components.append(f"PSA: {psa.category}")
            else:
                components.append(f"PSA: {psa.category}")

        if has_progression:
            overall = "PD"
            clinical_benefit = False
        elif has_response and not has_progression:
            overall = soft_tissue.category if soft_tissue and soft_tissue.category in ("CR", "PR") else "PR"
            clinical_benefit = True
        elif has_response and has_progression:
            overall = "mixed"
            clinical_benefit = False
        else:
            overall = "SD"
            clinical_benefit = True  # SD = beneficio clínico

        details = " | ".join(components) if components else "Sin componentes evaluados"

        return CompositeResponse(
            overall=overall,
            soft_tissue=soft_tissue,
            bone=bone,
            psa=psa,
            clinical_benefit=clinical_benefit,
            details=details,
        )

    @classmethod
    def evaluate_with_survival_context(
        cls,
        patient: dict[str, Any],
        composite: "CompositeResponse",
    ) -> dict[str, Any]:
        """
        Cuando se detecta PD, calcula el endpoint rPFS y enriquece la respuesta
        con contexto de supervivencia para informar decisiones de siguiente línea.
        """
        context: dict[str, Any] = {"progression_detected": composite.overall == "PD"}
        if composite.overall != "PD":
            return context

        try:
            from prostanet.domains.patient_tracking.survival_endpoints import SurvivalEndpointService
            rpfs = SurvivalEndpointService.compute_rpfs(patient)
            if rpfs:
                context["rpfs_endpoint"] = {
                    "start_event": rpfs.start_event,
                    "start_date": rpfs.start_date,
                    "end_event": rpfs.end_event,
                    "end_date": rpfs.end_date,
                    "duration_months": rpfs.duration_months,
                    "censored": rpfs.censored,
                }
            ttpp = SurvivalEndpointService.compute_ttpp(patient)
            if ttpp:
                context["ttpp_endpoint"] = {
                    "duration_months": ttpp.duration_months,
                    "censored": ttpp.censored,
                }
            context["recommended_action"] = (
                "Progresión radiográfica confirmada. Re-estadificación completa indicada. "
                "Discutir siguiente línea de tratamiento en tumor board."
            )
        except Exception:
            pass
        return context
