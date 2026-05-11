from __future__ import annotations

from prostanet.domains.adt_progression_verification.rules_eau import classify_eau
from prostanet.domains.adt_progression_verification.rules_nccn import classify_nccn
from prostanet.domains.adt_progression_verification.schemas import ADT_PROGRESSION_VERIFICATION_SCHEMA
from prostanet.domains.evidence_registry.service import EvidenceRegistryService
from prostanet.domains.guideline_comparison.service import GuidelineComparisonService
from prostanet.shared.contracts import evaluation_result
from prostanet.shared.recommendation_enrichment import enrich_evaluation_result


class AdtProgressionVerificationService:
    module_id = "adt_progression_verification"

    def __init__(self) -> None:
        self.registry = EvidenceRegistryService()
        self.comparison = GuidelineComparisonService()

    def schema(self) -> dict:
        return ADT_PROGRESSION_VERIFICATION_SCHEMA

    def evaluate(self, payload: dict) -> dict:
        nccn = classify_nccn(payload)
        eau = classify_eau(payload)
        comparison = self.comparison.compare(nccn, eau)
        classification = nccn["classification"]
        imaging_status = str(payload.get("conventional_imaging_status", "not_restaged") or "not_restaged").upper()
        psadt = float(payload.get("psadt_months", 0) or 0)
        testosterone_value = payload.get("testosterone_value")

        missing = [
            field
            for field in ["current_adt_context", "castrate_testosterone_status", "conventional_imaging_status", "progression_pattern"]
            if str(payload.get(field, "")).strip() == ""
        ]
        if str(payload.get("castrate_testosterone_status", "unknown")) == "unknown" and testosterone_value in (None, ""):
            missing.append("testosterone_value")
        if imaging_status == "NOT_RESTAGED":
            missing.append("conventional_imaging_status")

        treatments = self._eligible_treatments(classification, psadt, imaging_status)
        not_recommended = self._not_recommended(classification)
        durations = self._durations(classification)
        applicability = "guideline-consistent" if classification in {"confirmed_nmcrpc_candidate", "confirmed_mcrpc_candidate"} else "selected_candidate"

        result = evaluation_result(
            state=self.module_id,
            nccn_primary={
                "guideline": "NCCN",
                "version": "5.2026",
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
            missing_critical_inputs=missing,
            contraindications=[],
            durations_and_conditions=durations,
            evidence_trace=[self.registry.get_module_evidence(self.module_id)],
            trial_matches=[
                {"trial": "SPARTAN", "match": classification == "confirmed_nmcrpc_candidate" and psadt <= 10},
                {"trial": "ARAMIS", "match": classification == "confirmed_nmcrpc_candidate" and psadt <= 10},
                {"trial": "PROSPER", "match": classification == "confirmed_nmcrpc_candidate" and psadt <= 10},
            ],
            applicability_badge=applicability,
            report_sections={"summary": "ADT progression verification pathway."},
            decision_changing_inputs=[
                "La testosterona en rango de castración debe estar documentada antes de etiquetar enfermedad resistente a la castración.",
                "La imagen convencional M0 o M1 define si el caso debe migrar a M0 CRPC o M1 CRPC.",
                "El tiempo de duplicación del antígeno prostático específico ayuda a priorizar intensificación una vez confirmado M0 CRPC.",
            ],
            supportive_evidence_context=[
                "La recomendación principal sigue anclada a la Red Nacional Integral del Cáncer (NCCN) 5.2026 y la Asociación Europea de Urología (EAU) 2026.",
                "Las referencias públicas de CRPC se usan para reforzar la necesidad de testosterona castrada confirmada antes de etiquetar el estado.",
            ],
        )
        result["state_classification_override"] = classification
        result["routing_hint"] = "m1_crpc" if classification == "confirmed_mcrpc_candidate" else "m0_crpc" if classification == "confirmed_nmcrpc_candidate" else ""
        return enrich_evaluation_result(
            result,
            clinical_title="Ruta priorizada de progresión bajo ADT y verificación de castración",
            case_summary=self._case_summary(payload, nccn["label"]),
            recommended_trajectory=nccn["recommendation"],
            personalized_fundamentals=[
                *nccn["reasons"],
                "No debe asignarse CRPC sin testosterona en rango de castración confirmada.",
                "La imagen convencional sigue siendo la base del triage rápido para separar M0 de M1.",
                "La terapia de privación androgénica debe revisarse en adherencia, fecha de última aplicación y mecanismo de castración antes de intensificar.",
            ],
            alternatives=[
                "Optimizar supresión androgénica y repetir testosterona antes de intensificar.",
                "Reestadificar con imagen convencional si aún no está claro si el caso es M0 o M1.",
            ],
            shared_decision_message=(
                "La conversación clínica debe diferenciar progresión bajo ADT de CRPC confirmado, porque etiquetar CRPC de forma prematura puede llevar a intensificación inapropiada."
            ),
            comparison_message=(
                "La comparación con la Asociación Europea de Urología (EAU) 2026 refuerza que primero debe documentarse castración adecuada y reestadificación convencional antes de mover el caso a M0 CRPC o M1 CRPC."
            ),
        )

    @staticmethod
    def _case_summary(payload: dict, label: str) -> str:
        progression_pattern = str(payload.get("progression_pattern", "biochemical_only") or "biochemical_only")
        imaging_status = str(payload.get("conventional_imaging_status", "not_restaged") or "not_restaged").upper()
        testosterone_value = payload.get("testosterone_value")
        testosterone_fragment = (
            f"con testosterona actual de {float(testosterone_value):g} ng/dL"
            if testosterone_value not in (None, "")
            else "sin valor estructurado de testosterona"
        )
        return (
            "El caso corresponde a progresión bajo terapia de privación androgénica, "
            f"con patrón de progresión {progression_pattern}, {testosterone_fragment} "
            f"e imagen convencional {imaging_status}. La clasificación principal actual es {label}."
        )

    @staticmethod
    def _eligible_treatments(classification: str, psadt: float, imaging_status: str) -> list[dict]:
        if classification == "suppression_failure_or_inadequate_castration":
            return [
                {
                    "name": "Optimizar ADT y confirmar testosterona en rango de castración",
                    "priority": "preferente",
                    "notes": "Revisar adherencia, fecha de última aplicación, mecanismo de castración y considerar cambio de estrategia de supresión androgénica.",
                }
            ]
        if classification == "biochemical_progression_on_adt_pending_verification":
            return [
                {
                    "name": "Confirmar testosterona y completar reestadificación convencional",
                    "priority": "preferente",
                    "notes": "La progresión bajo ADT no debe etiquetarse como CRPC hasta confirmar castración adecuada y definir si el caso es M0 o M1.",
                }
            ]
        if classification == "confirmed_nmcrpc_candidate":
            risk_note = (
                "El tiempo de duplicación del antígeno prostático específico es corto y favorece abrir la ruta M0 CRPC con intensificación adaptada al riesgo."
                if psadt and psadt <= 10
                else "El tiempo de duplicación del antígeno prostático específico permite una discusión de observación estrecha dentro de la ruta M0 CRPC."
            )
            return [
                {
                    "name": "Redirigir a M0 CRPC (enfermedad resistente a la castración sin metástasis)",
                    "priority": "preferente",
                    "notes": risk_note,
                }
            ]
        return [
            {
                "name": "Redirigir a M1 CRPC (enfermedad resistente a la castración con metástasis)",
                "priority": "preferente",
                "notes": "La imagen convencional M1 con castración confirmada debe activar la ruta M1 CRPC para secuenciación terapéutica y biomarcadores.",
            }
        ]

    @staticmethod
    def _not_recommended(classification: str) -> list[str]:
        if classification in {"suppression_failure_or_inadequate_castration", "biochemical_progression_on_adt_pending_verification"}:
            return [
                "Evitar intensificar como CRPC sin testosterona en rango de castración confirmada.",
                "Evitar saltar a M0 CRPC o M1 CRPC sin reestadificación convencional suficiente.",
            ]
        return [
            "Evitar mantener el caso en un estado de verificación una vez que ya existe castración confirmada e imagen convencional suficiente para redirigirlo.",
        ]

    @staticmethod
    def _durations(classification: str) -> list[str]:
        if classification in {"suppression_failure_or_inadequate_castration", "biochemical_progression_on_adt_pending_verification"}:
            return [
                "Repetir testosterona y revisar ADT en el corto plazo antes de intensificar.",
                "Completar reestadificación convencional antes de asignar un estado resistente a la castración definitivo.",
            ]
        return [
            "Una vez confirmado el carril M0 o M1 CRPC, mantener la terapia de privación androgénica como base del tratamiento.",
        ]
