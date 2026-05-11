# -*- coding: utf-8 -*-
"""EPIC 8 — Terapia focal: servicio.

Produce una ``evaluation_result`` para integrar con clinical compass +
profile_compass. Se puede invocar de forma autónoma o desde
``localized_initial`` como refinador.
"""
from __future__ import annotations

from prostanet.domains.evidence_registry.service import EvidenceRegistryService
from prostanet.domains.focal_therapy.rules_nccn import classify_focal_therapy_nccn
from prostanet.domains.focal_therapy.schemas import FOCAL_THERAPY_SCHEMA
from prostanet.shared.contracts import evaluation_result
from prostanet.shared.recommendation_enrichment import enrich_evaluation_result


class FocalTherapyService:
    module_id = "focal_therapy"

    def __init__(self) -> None:
        self.registry = EvidenceRegistryService()

    def schema(self) -> dict:
        return FOCAL_THERAPY_SCHEMA

    def evaluate(self, payload: dict) -> dict:
        nccn = classify_focal_therapy_nccn(payload)

        eligible_treatments: list[dict] = []
        if nccn["eligible"]:
            eligible_treatments.append(
                {
                    "name": "Terapia focal (HIFU / crioablación / TULSA) con monitoreo post-procedimiento",
                    "priority": "preferred",
                    "notes": nccn["recommendation"],
                }
            )
            eligible_treatments.append(
                {
                    "name": "Vigilancia activa estándar como alternativa primaria",
                    "priority": "selected_candidate",
                    "notes": "Opción sin intervención; considerar si el paciente prioriza máxima preservación funcional.",
                }
            )
            eligible_treatments.append(
                {
                    "name": "Prostatectomía radical o radioterapia como alternativa de glándula entera",
                    "priority": "eligible",
                    "notes": "Opciones de tratamiento definitivo con mayor certeza oncológica a 15 años (ProtecT, SPCG-4).",
                }
            )
        else:
            eligible_treatments.append(
                {
                    "name": "Vigilancia activa o tratamiento de glándula entera (RP / RT)",
                    "priority": "preferred",
                    "notes": "Terapia focal no elegible; derivar a pathways estándar.",
                }
            )

        not_recommended = [
            "No usar terapia focal en ISUP ≥ 3 o PSA > 15 ng/mL (fuera de categoría NCCN 2B).",
            "No ofrecer HIFU con lesión apical anterior profunda — riesgo de persistencia tumoral.",
            "No indicar focal sin mpMRI previa que documente lesión índice unilateral.",
        ]

        durations = [
            "Monitoreo post-focal: PSA cada 3 meses (primeros 2 años), luego cada 6 meses.",
            "mpMRI al año + biopsia guiada del área tratada y ipsilateral.",
            "20-30 % requiere re-focal o salvage en 5 años — discutir explícitamente con el paciente.",
        ]

        case_summary = (
            f"Evaluación de candidatura a terapia focal. Estatus: {'ELEGIBLE' if nccn['eligible'] else 'NO ELEGIBLE'} "
            f"— {nccn['label']}."
        )

        contraindications: list[str] = list(nccn["exclusion_reasons"])

        result = evaluation_result(
            state=self.module_id,
            nccn_primary={
                "guideline": "NCCN Prostate",
                "version": "v5.2026",
                "label": nccn["label"],
                "risk_group": nccn["risk_group"],
                "recommendation": nccn["recommendation"],
                "reasons": nccn["reasons"],
            },
            eau_comparison={
                "guideline": "EAU",
                "version": "2026",
                "label": nccn["label"],
                "risk_group": nccn["risk_group"],
                "recommendation": nccn["recommendation"],
                "comparison": {"convergence": "similar", "note": "EAU 2026 §7.5 coincide con categoría 2B."},
            },
            eligible_treatments=eligible_treatments,
            not_recommended=not_recommended,
            missing_critical_inputs=[
                field
                for field in ("psa", "gleason_primary", "gleason_secondary", "lesion_unilateral")
                if str(payload.get(field, "")).strip() == ""
            ],
            contraindications=contraindications,
            durations_and_conditions=durations,
            evidence_trace=[
                {
                    "source": "NCCN Prostate v5.2026 PROS-C",
                    "reference": "NCCN Clinical Practice Guidelines in Oncology",
                },
                {
                    "source": "Stabile A et al. Eur Urol 2019;76:572 (HIFU)",
                    "reference": "HIFU mid-term outcomes",
                },
                {
                    "source": "Guillaumier S et al. Eur Urol 2018;74:422 (HIFU 5y FFS)",
                    "reference": "HIFU failure-free survival 5y",
                },
                {
                    "source": "Ward JF et al. BJU Int 2012;109:1648 (crio)",
                    "reference": "Cryoablation focal outcomes",
                },
                {
                    "source": "Klotz L et al. J Urol 2021;205:769 (TULSA)",
                    "reference": "TULSA-Pro registry",
                },
            ],
            trial_matches=[],
            applicability_badge="guideline-consistent",
            report_sections={
                "summary": case_summary,
                "eligibility": nccn["eligible"],
                "modality_recommended": nccn["modality_recommended"],
                "cautions": nccn["cautions"],
            },
        )
        return enrich_evaluation_result(
            result,
            clinical_title="Terapia focal selectiva",
            case_summary=case_summary,
            recommended_trajectory=nccn["recommendation"],
            personalized_fundamentals=nccn["reasons"] or ["Candidatura a terapia focal revisada contra NCCN PROS-C cat 2B."],
            alternatives=[
                "Vigilancia activa estándar",
                "Prostatectomía radical o radioterapia (glándula entera)",
                "Braquiterapia monoterapia en lesión pequeña y próstata adecuada",
            ],
            shared_decision_message=(
                "La terapia focal ofrece mejor preservación funcional pero mayor tasa de re-tratamiento "
                "(20-30 % en 5 años). El paciente debe ponderar función vs. certeza oncológica."
            ),
            comparison_message=(
                "NCCN y EAU coinciden en ubicar terapia focal como opción categoría 2B para intermedio favorable "
                "unilateral. La evidencia de largo plazo (15+ años) aún es limitada."
            ),
        )
