from __future__ import annotations

from copy import deepcopy

from prostanet.domains.evidence_registry.service import EvidenceRegistryService
from prostanet.domains.guideline_comparison.service import GuidelineComparisonService
from prostanet.domains.patient_tracking.survivorship_longitudinal import (
    build_survivorship_monitoring_package,
    build_survivorship_plan_alias,
    build_survivorship_schedule_overlay,
    build_survivorship_transition_bundle,
)
from prostanet.domains.survivorship_and_toxicity_followup.rules_eau import classify_survivorship_eau
from prostanet.domains.survivorship_and_toxicity_followup.rules_nccn import classify_survivorship_nccn
from prostanet.domains.survivorship_and_toxicity_followup.schemas import SURVIVORSHIP_AND_TOXICITY_FOLLOWUP_SCHEMA
from prostanet.shared.contracts import evaluation_result
from prostanet.shared.recommendation_enrichment import enrich_evaluation_result


TRACK_ACTIONS = {
    "late_effect_intervention": {
        "name": "Intervención dirigida de secuelas tardías",
        "notes": "Priorizar referencias y control estructurado de toxicidad tardía según el dominio dominante.",
    },
    "toxicity_recovery": {
        "name": "Recuperación funcional y rehabilitación",
        "notes": "Mantener metas objetivas de recuperación urinaria, funcional, neurológica o sexual.",
    },
    "survivorship_followup": {
        "name": "Seguimiento protocolizado de survivorship",
        "notes": "Sostener prevención secundaria, calidad de vida y vigilancia estructurada de secuelas.",
    },
}


class SurvivorshipAndToxicityFollowupService:
    module_id = "survivorship_and_toxicity_followup"

    def __init__(self) -> None:
        self.registry = EvidenceRegistryService()
        self.comparison = GuidelineComparisonService()

    def schema(self) -> dict:
        return SURVIVORSHIP_AND_TOXICITY_FOLLOWUP_SCHEMA

    def evaluate(self, payload: dict) -> dict:
        state = str(payload.get("oncologic_state_context") or "post_prostatectomy")
        management_track = str(payload.get("effective_management_track") or "survivorship_followup")
        patient = {
            "identity": {"age": payload.get("age"), "id": payload.get("patient_id")},
            "baseline": deepcopy(payload),
            "prior_history": deepcopy(payload),
            "follow_ups": [dict(payload, visit_date=payload.get("visit_date") or "")],
            "follow_up_visits": [dict(payload, visit_date=payload.get("visit_date") or "")],
        }

        transition_bundle = build_survivorship_transition_bundle(
            patient,
            state=state,
            management_track=management_track,
            field_values=payload,
        )
        monitoring_package = build_survivorship_monitoring_package(
            patient,
            state=state,
            management_track=management_track,
            field_values=payload,
            transition_bundle=transition_bundle,
        )
        schedule_overlay = build_survivorship_schedule_overlay(transition_bundle, monitoring_package)
        survivorship_plan = build_survivorship_plan_alias(transition_bundle, monitoring_package)

        nccn = classify_survivorship_nccn(payload, transition_bundle=transition_bundle)
        eau = classify_survivorship_eau(payload, transition_bundle=transition_bundle)
        comparison = self.comparison.compare(nccn, eau)

        dominant_track = str(transition_bundle.get("survivorship_track") or "survivorship_followup")
        dominant_action = TRACK_ACTIONS.get(dominant_track, TRACK_ACTIONS["survivorship_followup"])
        referrals = list(transition_bundle.get("recommended_referrals") or [])
        interventions = list(transition_bundle.get("recommended_interventions") or [])
        eligible_treatments = [
            {
                "name": dominant_action["name"],
                "priority": "preferred",
                "is_preferred": True,
                "notes": " ".join(
                    part
                    for part in [
                        dominant_action["notes"],
                        " · ".join(list(transition_bundle.get("trigger_reasons") or [])[:3]),
                    ]
                    if part
                ).strip(),
            }
        ]
        for referral in referrals[:3]:
            eligible_treatments.append(
                {
                    "name": f"Referencia: {referral}",
                    "priority": "eligible",
                    "notes": "Referencia específica sugerida por el bundle canónico de survivorship.",
                }
            )
        for intervention in interventions[:3]:
            eligible_treatments.append(
                {
                    "name": intervention,
                    "priority": "eligible",
                    "notes": "Intervención clínica priorizada por toxicidad tardía y recuperación funcional.",
                }
            )

        late_effects_profile = {
            "dominant_late_effect_domain": transition_bundle.get("dominant_late_effect_domain"),
            "active_late_effect_alerts": list(transition_bundle.get("active_late_effect_alerts") or []),
            "recommended_referrals": referrals,
            "recommended_interventions": interventions,
            "adt_side_effects_profile": deepcopy(transition_bundle.get("adt_side_effects_profile") or {}),
            "radiotherapy_detail_profile": deepcopy(transition_bundle.get("radiotherapy_detail_profile") or {}),
            "skeletal_event_profile": deepcopy(transition_bundle.get("skeletal_event_profile") or {}),
            "pro_alerts": deepcopy(transition_bundle.get("pro_alerts") or []),
        }
        functional_recovery_profile = {
            "survivorship_track": transition_bundle.get("survivorship_track"),
            "functional_recovery_status": transition_bundle.get("functional_recovery_status"),
            "psychosexual_status": transition_bundle.get("psychosexual_status"),
            "secondary_prevention_status": transition_bundle.get("secondary_prevention_status"),
            "patient_reported_outcomes_expected": list(monitoring_package.get("patient_reported_outcomes_expected") or []),
            "rehab_checks": list(monitoring_package.get("rehab_checks") or []),
        }

        title = "Ruta priorizada de survivorship y toxicidad"
        case_summary = (
            "El caso se interpreta desde survivorship como "
            f"{transition_bundle.get('survivorship_track_label') or dominant_track}, "
            f"con dominio tardío dominante {transition_bundle.get('dominant_late_effect_domain') or 'general_survivorship'}."
        )
        result = evaluation_result(
            state=self.module_id,
            nccn_primary={
                "guideline": "NCCN",
                "version": "5.2026",
                "label": nccn["label"],
                "recommendation": nccn["recommendation"],
                "reasons": nccn["reasons"],
            },
            eau_comparison={
                "guideline": "EAU",
                "version": "2026",
                "label": eau["label"],
                "recommendation": eau["recommendation"],
                "comparison": comparison,
            },
            eligible_treatments=eligible_treatments,
            not_recommended=[
                "No reducir survivorship a PSA y nota libre cuando existen secuelas tardías activas o exposición terapéutica acumulada."
            ],
            missing_critical_inputs=list(monitoring_package.get("missing_inputs") or []),
            contraindications=[],
            durations_and_conditions=[
                str(monitoring_package.get("recommended_cadence") or ""),
                "La intensidad del seguimiento depende del dominio tardío dominante y de si la secuela reabre una decisión oncológica.",
            ],
            evidence_trace=[self.registry.get_module_evidence(self.module_id)],
            trial_matches=[
                {"trial": "NCCN Survivorship 2026", "match": True},
                {"trial": "EAU QoL / survivorship 2026", "match": True},
            ],
            applicability_badge="guideline-consistent",
            report_sections={
                "summary": title,
                "survivorship_transition_bundle": transition_bundle,
                "survivorship_monitoring_package": monitoring_package,
                "late_effects_profile": late_effects_profile,
                "functional_recovery_profile": functional_recovery_profile,
            },
            decision_quality={
                "recommendation_family": dominant_track,
                "confidence_category": "vigilada"
                if (monitoring_package.get("missing_inputs") or monitoring_package.get("stale_inputs"))
                else "alta",
                "requires_human_review": bool(
                    transition_bundle.get("trigger_status") == "reenter_oncologic_decision"
                    or monitoring_package.get("missing_inputs")
                ),
            },
        )
        result["survivorship_transition_bundle"] = deepcopy(transition_bundle)
        result["survivorship_monitoring_package"] = deepcopy(monitoring_package)
        result["late_effects_profile"] = deepcopy(late_effects_profile)
        result["functional_recovery_profile"] = deepcopy(functional_recovery_profile)
        result["survivorship_schedule_overlay"] = deepcopy(schedule_overlay)
        result["survivorship_plan"] = deepcopy(survivorship_plan)

        enriched = enrich_evaluation_result(
            result,
            clinical_title=title,
            case_summary=case_summary,
            recommended_trajectory=nccn["recommendation"],
            personalized_fundamentals=[
                *list(nccn.get("reasons") or [])[:3],
                "La exposición terapéutica previa determina qué bundles de survivorship deben abrirse en cada visita.",
                "El carril de survivorship no reemplaza el estado oncológico; solo domina cuando la conducta principal es secuela, rehabilitación o prevención secundaria.",
            ],
            alternatives=[
                "Escalar a referencias específicas si predomina toxicidad urinaria, sexual, cardiometabólica, ósea o neuropática.",
                "Reingresar a la decisión oncológica cuando la secuela tardía ya modifica elegibilidad o seguridad del tratamiento.",
            ],
            shared_decision_message="El seguimiento de survivorship debe priorizar la secuela dominante del paciente y convertirla en una ruta visible con captura estructurada.",
            comparison_message="NCCN y EAU convergen en que las secuelas tardías, la recuperación funcional y la prevención secundaria deben gobernar un carril longitudinal propio cuando dominan la visita.",
        )
        enriched["survivorship_transition_bundle"] = deepcopy(transition_bundle)
        enriched["survivorship_monitoring_package"] = deepcopy(monitoring_package)
        enriched["late_effects_profile"] = deepcopy(late_effects_profile)
        enriched["functional_recovery_profile"] = deepcopy(functional_recovery_profile)
        enriched["survivorship_schedule_overlay"] = deepcopy(schedule_overlay)
        enriched["survivorship_plan"] = deepcopy(survivorship_plan)
        return enriched
