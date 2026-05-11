from __future__ import annotations

from copy import deepcopy

from prostanet.domains.evidence_registry.service import EvidenceRegistryService
from prostanet.domains.guideline_comparison.service import GuidelineComparisonService
from prostanet.domains.patient_tracking.psma_imaging import (
    build_psma_decision_impact,
    build_psma_structured_profile_from_payload,
)
from prostanet.domains.patient_tracking.therapeutic_family_engine import (
    build_active_regimen_monitoring_package,
    build_comparative_bundle,
    build_family_profile,
    build_ranked_option,
    build_sequence_transition_bundle,
)
from prostanet.domains.post_radiotherapy_or_local_salvage.logic import (
    _dedupe,
    _is_present,
    _normalize_text,
    build_post_rt_failure_definition,
    build_post_rt_local_salvage_ranking,
    build_post_rt_schedule_overlay,
    build_post_rt_transition_bundle,
)
from prostanet.domains.post_radiotherapy_or_local_salvage.rules_eau import classify_post_rt_eau
from prostanet.domains.post_radiotherapy_or_local_salvage.rules_nccn import classify_post_rt_nccn
from prostanet.domains.post_radiotherapy_or_local_salvage.schemas import POST_RT_LOCAL_SALVAGE_SCHEMA
from prostanet.shared.contracts import evaluation_result
from prostanet.shared.phase7_decision_bundles import build_post_rt_phase7_bundle
from prostanet.shared.recommendation_enrichment import enrich_evaluation_result


class PostRadiotherapyOrLocalSalvageService:
    module_id = "post_radiotherapy_or_local_salvage"

    def __init__(self) -> None:
        self.registry = EvidenceRegistryService()
        self.comparison = GuidelineComparisonService()

    def schema(self) -> dict:
        return POST_RT_LOCAL_SALVAGE_SCHEMA

    def evaluate(self, payload: dict) -> dict:
        nccn = classify_post_rt_nccn(payload)
        eau = classify_post_rt_eau(payload)
        comparison = self.comparison.compare(nccn, eau)
        psma_profile = (
            build_psma_structured_profile_from_payload(payload)
            if str(payload.get("psma_pet_done", "0")) == "1"
            else {"available": False}
        )
        psma_impact = build_psma_decision_impact(
            psma_profile,
            state=self.module_id,
            patient={"baseline": payload},
        )
        failure_definition = build_post_rt_failure_definition(payload)
        local_salvage_ranking = build_post_rt_local_salvage_ranking(
            payload,
            failure_definition=failure_definition,
            psma_impact=psma_impact,
        )
        transition_bundle = build_post_rt_transition_bundle(
            payload,
            failure_definition=failure_definition,
            local_salvage_ranking=local_salvage_ranking,
        )
        schedule_overlay = build_post_rt_schedule_overlay(transition_bundle)

        family_profiles: dict[str, dict] = {}
        family_order: list[str] = []
        ranked_options = list(local_salvage_ranking.get("ranked_options") or [])
        required_missing_fields = list(local_salvage_ranking.get("required_missing_fields") or [])
        not_recommended: list[str] = []
        durations: list[str] = []
        trials = [
            {"trial": "NCCN 2026 post-RT salvage", "match": True},
            {"trial": "EAU 2026 biochemical recurrence", "match": True},
        ]

        confirmation_option = build_ranked_option(
            name="Confirmar fallo post-RT antes de salvage",
            regimen_code="POST_RT_CONFIRMATION",
            rank=1,
            priority="preferred" if transition_bundle.get("transition_status") in {"pending_confirmation", "restate_before_decision"} else "eligible",
            eligibility_status="preferred" if transition_bundle.get("transition_status") in {"pending_confirmation", "restate_before_decision"} else "eligible_nonpreferred",
            family_code="observation_family",
            molecule_or_backbone="Confirmación Phoenix / local",
            description="Completar definición de fallo post-RT, reestadificación y factibilidad local antes de escoger salvage.",
            route="Imagen / histología / correlación bioquímica",
            schedule="Cierre secuencial de Phoenix, mpMRI/biopsia y PSMA",
            notes=failure_definition.get("rationale") or "No debe abrirse salvage curativo sin definición de fallo post-RT.",
            why_this_rank=[transition_bundle.get("trigger_reasons", [""])[0]],
            required_missing_fields=required_missing_fields,
            preference_confidence="provisional" if required_missing_fields else "definitive",
            stale_inputs=[],
        )

        if transition_bundle.get("transition_status") in {"pending_confirmation", "restate_before_decision", "redirect_systemic"}:
            family_profiles["observation_family"] = build_family_profile(
                family_code="observation_family",
                ordered_regimens=[confirmation_option] + [
                    build_ranked_option(
                        name=item.get("name") or item.get("regimen_code"),
                        regimen_code=item.get("regimen_code"),
                        rank=index + 2,
                        priority="eligible" if item.get("eligibility_status") != "ineligible" else "not_preferred",
                        eligibility_status=item.get("eligibility_status") or "eligible_with_caution",
                        family_code=item.get("family_code") or "observation_family",
                        molecule_or_backbone=item.get("name") or item.get("regimen_code"),
                        description=item.get("description") or "",
                        dose=item.get("dose") or "",
                        route=item.get("route") or "",
                        schedule=item.get("schedule") or "",
                        why_this_rank=item.get("why_this_rank") or [],
                        hard_blocks=item.get("hard_blocks") or [],
                        caution_flags=item.get("caution_flags") or [],
                        required_missing_fields=required_missing_fields,
                        preference_confidence="provisional" if required_missing_fields else "definitive",
                    )
                    for index, item in enumerate(ranked_options[:2])
                    if item.get("regimen_code") == "SYSTEMIC_RESTAGING"
                ],
                context={
                    "eligibility_status": "conditional" if required_missing_fields else "eligible",
                    "missing_inputs": required_missing_fields,
                    "winner_reason": transition_bundle.get("trigger_reasons", [""])[0],
                    "why_not_preferred": "El salvage post-RT no debe subir por encima de la confirmación de falla o de un redirector sistémico ya explícito.",
                },
            )
            family_order.append("observation_family")

        local_options = []
        systemic_option = None
        for index, item in enumerate(ranked_options, start=1):
            option = build_ranked_option(
                name=item.get("name") or item.get("regimen_code"),
                regimen_code=item.get("regimen_code"),
                rank=index,
                priority="preferred" if item.get("eligibility_status") == "preferred" else "eligible",
                eligibility_status=item.get("eligibility_status") or "eligible_nonpreferred",
                family_code=item.get("family_code") or "local_mdt_family",
                molecule_or_backbone=item.get("name") or item.get("regimen_code"),
                description=item.get("description") or "",
                dose=item.get("dose") or "",
                route=item.get("route") or "",
                schedule=item.get("schedule") or "",
                why_this_rank=item.get("why_this_rank") or [],
                hard_blocks=item.get("hard_blocks") or [],
                caution_flags=item.get("caution_flags") or [],
                required_missing_fields=required_missing_fields,
                preference_confidence="provisional" if required_missing_fields else "definitive",
                stale_inputs=[],
            )
            if item.get("regimen_code") == "SYSTEMIC_RESTAGING":
                systemic_option = option
            else:
                local_options.append(option)

        if local_options:
            family_profiles["local_mdt_family"] = build_family_profile(
                family_code="local_mdt_family",
                ordered_regimens=local_options,
                context={
                    "eligibility_status": "eligible" if transition_bundle.get("transition_status") in {"local_salvage_candidate", "mdt_candidate"} and not required_missing_fields else "conditional",
                    "missing_inputs": required_missing_fields,
                    "caution_drivers": ["PSMA estructurada incompleta"] if psma_impact.get("confidence") == "low" else [],
                    "winner_reason": transition_bundle.get("trigger_reasons", [""])[0],
                    "why_not_preferred": "La modalidad local solo lidera si Phoenix/confirmación local, restaging y toxicidad sostienen todavía una vía curativa o dirigida.",
                },
            )
            family_order.append("local_mdt_family")

        if systemic_option and transition_bundle.get("transition_status") == "redirect_systemic":
            family_profiles["observation_family"] = build_family_profile(
                family_code="observation_family",
                ordered_regimens=[systemic_option],
                context={
                    "eligibility_status": "eligible",
                    "winner_reason": transition_bundle.get("trigger_reasons", [""])[0],
                    "why_not_preferred": "El salvage local pierde precedencia cuando la PSMA o la anatomía ya redirigen a sistémico.",
                },
            )
            if "observation_family" not in family_order:
                family_order.insert(0, "observation_family")
            not_recommended.append("No mantener salvage local aislado cuando la PSMA documenta enfermedad diseminada post-RT.")

        if transition_bundle.get("transition_status") == "mdt_candidate":
            durations.append("La MDT/SBRT post-RT requiere discusión multidisciplinaria y correlación completa entre PSMA, mpMRI y carga de toxicidad local previa.")
        if transition_bundle.get("transition_status") == "local_salvage_candidate":
            durations.append("La modalidad local dominante debe confirmarse con anatomía local, toxicidad GU/GI previa, volumen prostático y expertise disponible.")
        if transition_bundle.get("transition_status") in {"pending_confirmation", "restate_before_decision"}:
            not_recommended.append("No abrir salvage curativo post-RT sin Phoenix met o confirmación local equivalente documentada.")

        comparative_bundle = build_comparative_bundle(
            family_profiles=family_profiles,
            family_order=family_order,
        )
        preferred_regimen = dict(comparative_bundle.get("preferred_regimen") or {})
        active_monitoring_package = build_active_regimen_monitoring_package(
            preferred_regimen.get("regimen_code"),
            family_code=preferred_regimen.get("family_code") or "observation_family",
            field_values=payload,
        )
        sequence_transition_bundle = build_sequence_transition_bundle(
            state=self.module_id,
            preferred_regimen=preferred_regimen,
            eligible_treatments=comparative_bundle.get("eligible_treatments") or [],
            current_treatment=payload.get("current_treatment") or "",
            missing_critical_inputs=required_missing_fields,
            progression_pattern=str(payload.get("progression_pattern") or ""),
            line_context="post_rt_salvage",
            field_values=payload,
            monitoring_package=active_monitoring_package,
            comparative_eligibility_matrix=comparative_bundle.get("comparative_eligibility_matrix") or {},
        )
        sequence_transition_bundle["trigger_status"] = {
            "pending_confirmation": "confirm",
            "restate_before_decision": "confirm",
            "local_salvage_candidate": "redirect_local",
            "mdt_candidate": "redirect_local",
            "redirect_systemic": "redirect_systemic",
        }.get(transition_bundle.get("transition_status"), sequence_transition_bundle.get("trigger_status"))
        sequence_transition_bundle["line_change_reason"] = transition_bundle.get("trigger_reasons", [""])[0]

        post_rt_bundle = {
            "phoenix_status": failure_definition.get("phoenix_status"),
            "failure_confirmation_basis": failure_definition.get("failure_confirmation_basis"),
            "dominant_local_option": deepcopy(local_salvage_ranking.get("dominant_local_option") or {}),
            "local_salvage_modality_ranking": deepcopy(ranked_options),
            "required_missing_fields": required_missing_fields,
            "post_rt_course": transition_bundle.get("transition_status"),
            "post_rt_salvage_window_status": transition_bundle.get("transition_status"),
            "reason": transition_bundle.get("trigger_reasons", [""])[0],
        }

        case_summary = (
            "Ruta post-radioterapia: "
            f"Phoenix {failure_definition.get('phoenix_status')} con base de confirmación "
            f"{failure_definition.get('failure_confirmation_basis')}. "
            f"El curso dominante hoy es {transition_bundle.get('transition_status')}."
        )
        title = "Ruta priorizada post-radioterapia / salvage local"
        result = evaluation_result(
            state=self.module_id,
            nccn_primary={
                "guideline": "NCCN",
                "version": "5.2026",
                "label": nccn["label"],
                "recommendation": nccn["recommendation"],
            },
            eau_comparison={
                "guideline": "EAU",
                "version": "2026",
                "label": eau["label"],
                "recommendation": eau["recommendation"],
                "comparison": comparison,
            },
            eligible_treatments=comparative_bundle.get("eligible_treatments") or [],
            not_recommended=_dedupe(not_recommended),
            missing_critical_inputs=required_missing_fields,
            contraindications=[],
            durations_and_conditions=_dedupe(durations),
            evidence_trace=[self.registry.get_module_evidence(self.module_id)],
            trial_matches=trials,
            applicability_badge="selected_candidate" if transition_bundle.get("transition_status") in {"local_salvage_candidate", "mdt_candidate"} else "guideline-consistent",
            report_sections={
                "summary": title,
                "post_rt_failure_definition": failure_definition,
                "post_rt_local_salvage_ranking": ranked_options,
                "post_rt_transition_bundle": transition_bundle,
            },
            decision_quality={
                "recommendation_family": preferred_regimen.get("family_label") or "post_rt_salvage",
                "confidence_category": "vigilada" if required_missing_fields else "alta",
                "requires_human_review": bool(required_missing_fields or psma_impact.get("confidence") == "low"),
            },
        )
        result["comparative_eligibility_matrix"] = comparative_bundle.get("comparative_eligibility_matrix") or {}
        result["therapeutic_family_profiles"] = comparative_bundle.get("comparative_eligibility_matrix") or {}
        result["preferred_frontline_regimen"] = preferred_regimen
        result["preferred_regimen_code"] = preferred_regimen.get("regimen_code", "")
        result["alternative_regimens"] = comparative_bundle.get("alternative_regimens") or []
        result["post_rt_failure_definition"] = failure_definition
        result["post_rt_recurrence_bundle"] = failure_definition
        result["post_rt_local_salvage_ranking"] = ranked_options
        result["post_rt_transition_bundle"] = transition_bundle
        result["post_rt_schedule_overlay"] = schedule_overlay
        result["post_rt_salvage_bundle"] = post_rt_bundle
        result["care_setting_contract"] = {
            "care_setting": transition_bundle.get("transition_status"),
            "family_code": preferred_regimen.get("family_code") or "",
            "family_label": preferred_regimen.get("family_label") or "",
        }
        result["sequence_transition_bundle"] = sequence_transition_bundle
        result["active_regimen_monitoring_package"] = active_monitoring_package
        enriched = enrich_evaluation_result(
            result,
            clinical_title=title,
            case_summary=case_summary,
            recommended_trajectory=nccn["recommendation"],
            personalized_fundamentals=[
                failure_definition.get("rationale"),
                transition_bundle.get("trigger_reasons", [""])[0],
                "La vía local post-RT solo permanece dominante si Phoenix o la confirmación local equivalente ya están cerrados y la reestadificación no redirige a sistémico.",
                "La modalidad de salvage debe depender de anatomía local, toxicidad GU/GI previa, aptitud anestésica y expertise disponible.",
            ],
            alternatives=[
                "MDT/SBRT guiada por PSMA cuando el patrón sea oligorrecurrente y no puramente glandular.",
                "Redirección sistémica cuando la PSMA o la factibilidad local ya cierran la vía curativa local.",
            ],
            shared_decision_message="La decisión debe integrar definición correcta de fallo post-RT, patrón de reestadificación, secuelas funcionales previas y disponibilidad real de expertise local.",
            comparison_message="La comparación NCCN/EAU converge en que la recurrencia post-RT no debe tratarse como salvage curativo sin Phoenix o confirmación local estructurada.",
        )
        enriched["post_rt_failure_definition"] = deepcopy(failure_definition)
        enriched["post_rt_recurrence_bundle"] = deepcopy(failure_definition)
        enriched["post_rt_local_salvage_ranking"] = deepcopy(ranked_options)
        enriched["post_rt_transition_bundle"] = deepcopy(transition_bundle)
        enriched["post_rt_schedule_overlay"] = deepcopy(schedule_overlay)
        enriched["post_rt_salvage_bundle"] = deepcopy(post_rt_bundle)
        if isinstance(enriched.get("report_sections"), dict):
            enriched["report_sections"]["post_rt_failure_definition"] = deepcopy(failure_definition)
            enriched["report_sections"]["post_rt_recurrence_bundle"] = deepcopy(failure_definition)
            enriched["report_sections"]["post_rt_local_salvage_ranking"] = deepcopy(ranked_options)
            enriched["report_sections"]["post_rt_transition_bundle"] = deepcopy(transition_bundle)
        enriched["phase7_advanced_bundle"] = build_post_rt_phase7_bundle(payload)
        return enriched
