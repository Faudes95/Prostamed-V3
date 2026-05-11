from __future__ import annotations

from prostanet.domains.evidence_registry.service import EvidenceRegistryService
from prostanet.domains.guideline_comparison.service import GuidelineComparisonService
from prostanet.domains.post_negative_biopsy_followup.rules_eau import classify_post_negative_biopsy_eau
from prostanet.domains.post_negative_biopsy_followup.rules_nccn import classify_post_negative_biopsy
from prostanet.domains.post_negative_biopsy_followup.schemas import POST_NEGATIVE_BIOPSY_SCHEMA
from prostanet.shared.contracts import evaluation_result
from prostanet.shared.recommendation_enrichment import enrich_evaluation_result


class PostNegativeBiopsyFollowupService:
    module_id = "post_negative_biopsy_followup"

    def __init__(self) -> None:
        self.registry = EvidenceRegistryService()
        self.comparison = GuidelineComparisonService()

    def schema(self) -> dict:
        return POST_NEGATIVE_BIOPSY_SCHEMA

    def evaluate(self, payload: dict) -> dict:
        nccn = classify_post_negative_biopsy(payload)
        eau = classify_post_negative_biopsy_eau(payload)
        comparison = self.comparison.compare(nccn, eau)

        psa = float(payload.get("psa", 0) or 0)
        psad = float(payload.get("psad", 0) or 0)
        years_since_biopsy = float(payload.get("years_since_negative_biopsy", 0) or 0)
        erspc_ready = all(
            payload.get(field) not in (None, "")
            for field in ("psa", "dre_suspicious", "prior_biopsy_count")
        )

        treatments = []
        if nccn["reopen_diagnostic_workup"]:
            treatments.append(
                {
                    "name": "Reabrir estudio diagnóstico con resonancia magnética multiparamétrica",
                    "priority": "preferred",
                    "notes": "La sospecha actual es demasiado alta para continuar solo con seguimiento pasivo.",
                }
            )
            treatments.append(
                {
                    "name": "Nueva consideración de biopsia dirigida más biopsia sistemática",
                    "priority": "eligible",
                    "notes": "Se recomienda si la resonancia magnética multiparamétrica o la cinética del antígeno prostático específico sostienen la sospecha.",
                }
            )
        else:
            treatments.append(
                {
                    "name": "Seguimiento de baja intensidad con antígeno prostático específico",
                    "priority": "preferred",
                    "notes": "Adecuado cuando la sospecha clínica sigue siendo baja tras la biopsia benigna inicial.",
                }
            )

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
            not_recommended=[
                "No repetir biopsias en serie sin una nueva señal clínica, de imagen o de densidad del antígeno prostático específico que las justifique."
            ],
            missing_critical_inputs=[field for field in ["psa"] if str(payload.get(field, "")).strip() == ""],
            contraindications=[],
            durations_and_conditions=[
                "Si la sospecha permanece baja, el seguimiento puede mantenerse cada 12 a 24 meses.",
                "Si reaparece una lesión PI-RADS 4 o 5 o la densidad del antígeno prostático específico alcanza 0.15, reabrir el estudio sin retrasos prolongados.",
            ],
            evidence_trace=[self.registry.get_module_evidence(self.module_id)],
            trial_matches=[{"trial": "Palmstedt 2019", "match": not nccn["reopen_diagnostic_workup"]}],
            applicability_badge="guideline-consistent",
            report_sections={
                "summary": (
                    f"Seguimiento tras biopsia benigna con antígeno prostático específico de {psa:g} ng/mL, "
                    f"densidad del antígeno prostático específico de {psad:g} y {years_since_biopsy:g} años desde la biopsia negativa."
                ),
                "validated_algorithms": {
                    "erspc_ready": erspc_ready,
                },
            },
        )
        return enrich_evaluation_result(
            result,
            clinical_title="Ruta priorizada después de biopsia benigna",
            case_summary=(
                f"El caso corresponde a seguimiento tras biopsia benigna inicial, con antígeno prostático específico de {psa:g} ng/mL, "
                f"densidad del antígeno prostático específico de {psad:g} y {years_since_biopsy:g} años desde la biopsia previa. "
                f"La Red Nacional Integral del Cáncer (NCCN) 5.2026 lo orienta como {nccn['label'].lower()} y la Asociación Europea de Urología (EAU) 2026 lo compara de forma concordante o complementaria."
            ),
            recommended_trajectory=nccn["recommendation"],
            personalized_fundamentals=[
                *nccn["reasons"],
                "Una biopsia benigna inicial no elimina la necesidad de seguimiento, pero tampoco justifica una repetición automática de procedimientos invasivos.",
                f"Número de biopsias previas documentadas: {nccn['prior_biopsy_count']}.",
                (
                    "Las entradas permiten correr ERSPC Risk Calculator en contexto de rebiopsia para reforzar la decision de reapertura."
                    if erspc_ready
                    else "Aun faltan entradas para un ERSPC de rebiopsia totalmente trazable."
                ),
            ],
            alternatives=[
                "Repetir resonancia magnética multiparamétrica antes de una nueva biopsia cuando la señal clínica sea incierta.",
                "Mantener seguimiento anual o bianual si la sospecha clínica sigue baja y no aparecen nuevos disparadores.",
            ],
            shared_decision_message=(
                "La intensidad del seguimiento debe equilibrar el riesgo de pasar por alto cáncer clínicamente significativo frente al costo de repetir biopsias y la ansiedad asociada al antígeno prostático específico."
            ),
            comparison_message=(
                "La comparación con la Asociación Europea de Urología (EAU) 2026 ayuda a sostener un seguimiento prudente de baja intensidad y a identificar cuándo la sospecha ya no permite observación simple."
            ),
        )
