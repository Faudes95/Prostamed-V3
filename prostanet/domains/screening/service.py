# -*- coding: utf-8 -*-
"""EPIC 8 — Screening service.

Orquesta NCCN + EAU y retorna una ``evaluation_result`` para integrar con
el módulo de paciente (clinical compass, profile_compass, patient_profile).
"""
from __future__ import annotations

from prostanet.domains.evidence_registry.service import EvidenceRegistryService
from prostanet.domains.guideline_comparison.service import GuidelineComparisonService
from prostanet.domains.screening.rules_eau import classify_screening_eau
from prostanet.domains.screening.rules_nccn import classify_screening_nccn
from prostanet.domains.screening.schemas import SCREENING_SCHEMA
from prostanet.shared.contracts import evaluation_result
from prostanet.shared.recommendation_enrichment import enrich_evaluation_result


class ScreeningService:
    module_id = "screening"

    def __init__(self) -> None:
        self.registry = EvidenceRegistryService()
        self.comparison = GuidelineComparisonService()

    def schema(self) -> dict:
        return SCREENING_SCHEMA

    def evaluate(self, payload: dict) -> dict:
        nccn = classify_screening_nccn(payload)
        eau = classify_screening_eau(payload)
        try:
            comparison = self.comparison.compare(nccn, eau)
        except Exception:
            comparison = {
                "convergence": "neutral",
                "note": "Screening es un dominio preventivo; ambas guías concuerdan en SDM.",
            }

        treatments: list[dict] = []
        if nccn["derive_to_diagnostic_workup"]:
            treatments.append(
                {
                    "name": "Derivar a estudio diagnóstico (mpMRI + densidad PSA ± biopsia selectiva)",
                    "priority": "preferred",
                    "notes": "El PSA o el tacto rectal superaron el umbral de observación rutinaria.",
                }
            )
        if nccn["interval_months"]:
            interval_years = round(nccn["interval_months"] / 12, 1)
            treatments.append(
                {
                    "name": f"Continuar screening con PSA + DRE cada {interval_years:g} año(s)",
                    "priority": "preferred" if nccn["risk_group"].endswith("STANDARD") else "selected_candidate",
                    "notes": nccn["interval_text"],
                }
            )
        if nccn["risk_group"] == "SCREENING_STOP":
            treatments.append(
                {
                    "name": "Suspender screening",
                    "priority": "preferred",
                    "notes": "Esperanza de vida < 10 años o edad ≥ 75 con salud no óptima — USPSTF grado D.",
                }
            )
        if not treatments:
            treatments.append(
                {
                    "name": "Reevaluar indicación de screening en consulta próxima",
                    "priority": "eligible",
                    "notes": "No hay criterios inmediatos para iniciar o suspender.",
                }
            )

        not_recommended = [
            "Screening poblacional rutinario fuera del rango 50-74 años sin factor de riesgo.",
            "PET-PSMA como herramienta de screening poblacional.",
            "Biopsia prostática sin mpMRI previa cuando la MRI está disponible.",
        ]
        durations = [
            f"Si PSA < 1.0 ng/mL en hombre de riesgo estándar, EAU permite re-screening cada 4 años; NCCN recomienda cada 2 años.",
            "Si aparece PSA > 3 ng/mL o DRE sospechoso en cualquier visita, interrumpir el intervalo y derivar a workup diagnóstico.",
        ]

        missing_critical_inputs = [
            field
            for field in ("psa_baseline_ng_ml", "age", "family_history_cluster")
            if str(payload.get(field, "")).strip() == ""
        ]

        case_summary = (
            f"Paciente de {nccn['effective_age']:.0f} años con PSA basal {nccn['psa_baseline']:.2f} ng/mL. "
            f"Categoría NCCN Early Detection: {nccn['category']} — {nccn['label']} "
            f"EAU 2026 comparada: {eau['label']}."
        )

        result = evaluation_result(
            state=self.module_id,
            nccn_primary={
                "guideline": "NCCN Early Detection",
                "version": "v2.2026",
                "label": nccn["label"],
                "risk_group": nccn["risk_group"],
                "recommendation": nccn["recommendation"],
                "reasons": nccn["reasons"],
            },
            eau_comparison={
                "guideline": "EAU",
                "version": "2026",
                "label": eau["label"],
                "risk_group": eau["risk_group"],
                "recommendation": eau["recommendation"],
                "comparison": comparison,
            },
            eligible_treatments=treatments,
            not_recommended=not_recommended,
            missing_critical_inputs=missing_critical_inputs,
            contraindications=[],
            durations_and_conditions=durations,
            evidence_trace=[
                {
                    "source": "NCCN Prostate Cancer Early Detection v2.2026",
                    "reference": "NCCN Clinical Practice Guidelines in Oncology",
                },
                {
                    "source": "USPSTF 2018",
                    "reference": "JAMA 2018;319:1901",
                },
                {
                    "source": "Schroeder et al. ERSPC",
                    "reference": "NEJM 2009;360:1320",
                },
            ],
            trial_matches=[],
            applicability_badge="guideline-consistent",
            report_sections={
                "summary": case_summary,
                "category": nccn["category"],
                "interval_months": nccn["interval_months"],
                "start_age_recommended": nccn["start_age_recommended"],
                "derive_to_diagnostic_workup": nccn["derive_to_diagnostic_workup"],
                "workup_reasons": nccn["workup_reasons"],
            },
        )
        return enrich_evaluation_result(
            result,
            clinical_title="Detección temprana informada",
            case_summary=case_summary,
            recommended_trajectory=nccn["recommendation"],
            personalized_fundamentals=[
                *nccn["reasons"],
                (
                    f"Intervalo recomendado: {nccn['interval_text']}"
                    if nccn["interval_months"]
                    else "No se programa intervalo de screening rutinario."
                ),
                *nccn["workup_reasons"],
            ],
            alternatives=[
                "Diferir screening hasta completar SDM informado si el paciente no ha revisado beneficios/daños.",
                "Usar baseline PSA como referencia prospectiva aunque no se reagende si PSA < 1.0 ng/mL.",
            ],
            shared_decision_message=(
                "La decisión de screening debe ser compartida, considerando factores hereditarios, "
                "expectativa de vida y preferencias del paciente."
            ),
            comparison_message=(
                "NCCN Early Detection v2.2026 y EAU 2026 coinciden en inicio temprano con factor de riesgo "
                "y parada ≥ 75 años con expectativa < 10 años; los intervalos varían ligeramente."
            ),
        )
