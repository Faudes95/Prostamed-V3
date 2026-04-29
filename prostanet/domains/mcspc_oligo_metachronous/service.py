from __future__ import annotations

from typing import Any

from prostanet.shared.precision_medicine_legacy import evaluate_patient_for_mhspc

from prostanet.domains.evidence_registry.service import EvidenceRegistryService
from prostanet.domains.guideline_comparison.service import GuidelineComparisonService
from prostanet.domains.mcspc_oligo_metachronous.rules_eau import evaluate_mcspc_oligo_metachronous_eau
from prostanet.domains.mcspc_oligo_metachronous.rules_nccn import evaluate_mcspc_oligo_metachronous
from prostanet.domains.mcspc_oligo_metachronous.schemas import MCSPC_OLIGO_METACHRONOUS_SCHEMA
from prostanet.domains.patient_tracking.mhspc_evidence import (
    build_triplet_decision,
    build_visible_mhspc_trial_matches,
)
from prostanet.domains.patient_tracking.mhspc_regimen_selector import (
    select_mhspc_frontline_regimens,
)
from prostanet.domains.patient_tracking.primary_rt_eligibility import evaluate_primary_rt
from prostanet.domains.patient_tracking.therapeutic_family_engine import (
    build_active_regimen_monitoring_package,
    build_comparative_bundle,
    build_family_profile,
    build_ranked_option,
    build_sequence_transition_bundle,
)
from prostanet.shared.advanced_support_normalizer import resolve_child_pugh_bc
from prostanet.shared.contracts import evaluation_result
from prostanet.shared.metastatic_profile import (
    build_metastatic_composition_summary,
    has_bone_metastatic_component,
)
from prostanet.shared.pivotal_contraindication_gates import (
    apply_pivotal_contraindication_gates,
)
from prostanet.shared.presentation_text import (
    abiraterone_hepatic_contraindication_note,
)
from prostanet.shared.recommendation_enrichment import enrich_evaluation_result
from prostanet.shared.systemic_regimen_scope import build_systemic_regimen_scope_contract
from copy import deepcopy


def _flag_truthy_mhspc(value: Any) -> bool:
    """Auditoría Pacientes Insignia 2026-04-21 (§D.4) — normaliza flags
    booleans ES-médica y legacy a bool real para aplicar gates."""
    return str(value or "").strip().lower() in {"sí", "si", "1", "yes", "true"}


class McspcOligoMetachronousService:
    module_id = "mcspc_oligo_metachronous"

    def __init__(self) -> None:
        self.registry = EvidenceRegistryService()
        self.comparison = GuidelineComparisonService()

    def schema(self) -> dict:
        return MCSPC_OLIGO_METACHRONOUS_SCHEMA

    def evaluate(self, payload: dict) -> dict:
        nccn = evaluate_mcspc_oligo_metachronous(payload)
        eau = evaluate_mcspc_oligo_metachronous_eau(payload)
        comparison = self.comparison.compare(nccn, eau)
        normalized = dict(payload)
        normalized["comorbidities"] = {
            "seizure": str(payload.get("comorbidity_seizure", "0")) == "1",
            "cardio": str(payload.get("comorbidity_cardio", "0")) == "1",
        }
        legacy = evaluate_patient_for_mhspc(normalized)
        selector_bundle = select_mhspc_frontline_regimens(self.module_id, payload)
        # EPIC 9 Group D (GAP-6) — evaluación estructurada de RT al tumor
        # primario. En metacrónico, metachronous_metastasis=True genera
        # caution (no hard-block; STAMPEDE-H enroló ambos contextos).
        primary_rt_bundle = evaluate_primary_rt(payload)
        triplet_decision = build_triplet_decision(self.module_id, payload, selector_bundle=selector_bundle)
        visible_trial_matches, hidden_trial_count = build_visible_mhspc_trial_matches(
            self.module_id,
            payload,
            triplet_decision=triplet_decision,
        )
        family_profiles = deepcopy(selector_bundle.get("comparative_eligibility_matrix") or {})
        if nccn["mdt_candidate"]:
            local_options = list(((family_profiles.get("local_mdt_family") or {}).get("variant_ranking") or {}).get("eligible_regimens_ranked") or [])
            local_options.append(
                build_ranked_option(
                    name="Metastasis-directed therapy",
                    regimen_code="LOCAL_MDT",
                    rank=len(local_options) + 1,
                    priority="eligible",
                    eligibility_status="eligible_with_caution",
                    family_code="local_mdt_family",
                    molecule_or_backbone="MDT",
                    description="Burden metacrónico limitado que habilita MDT en comité oncológico.",
                    route="RT estereotáxica / ablación",
                    schedule="Discusión multidisciplinaria y tratamiento dirigido",
                    metadata_source="guideline_backbone",
                    notes="Limited metachronous burden supports MDT discussion in tumor board.",
                    why_this_rank=["La MDT es contextual en enfermedad metacrónica limitada y no sustituye la intensificación sistémica dominante."],
                )
            )
            family_profiles["local_mdt_family"] = build_family_profile(
                family_code="local_mdt_family",
                ordered_regimens=local_options,
                context={
                    "eligibility_status": "conditional",
                    "winner_reason": "La MDT se mantiene visible como complemento en oligometástasis metacrónicas seleccionadas.",
                },
            )
        if nccn["prefer_akeega"]:
            parp_options = list(((family_profiles.get("parp_family") or {}).get("variant_ranking") or {}).get("eligible_regimens_ranked") or [])
            parp_options.append(
                build_ranked_option(
                    name="ADT + Niraparib + Abiraterone",
                    regimen_code="NIRAPARIB_ABIRATERONE",
                    rank=len(parp_options) + 1,
                    priority="eligible",
                    eligibility_status="eligible_with_caution",
                    family_code="parp_family",
                    molecule_or_backbone="Niraparib + abiraterona",
                    notes="Ruta de precisión para BRCA2 trazable en enfermedad sensible a la castración.",
                    why_this_rank=["La precisión BRCA2 sigue visible como overlay y no reemplaza automáticamente el backbone sistémico del carril metacrónico."],
                )
            )
            family_profiles["parp_family"] = build_family_profile(
                family_code="parp_family",
                ordered_regimens=parp_options,
                context={
                    "eligibility_status": "conditional",
                    "missing_inputs": [
                        field
                        for field in ["molecular_assay_source", "molecular_assay_date"]
                        if str(payload.get(field, "")).strip() == ""
                    ],
                    "winner_reason": "La vía BRCA2 permanece contextual mientras no sustituya la intensificación sistémica estándar del escenario.",
                },
            )
        family_order = ["arpi_family", "abiraterone_steroid_family", "local_mdt_family", "parp_family", "observation_family"]
        comparative_bundle = build_comparative_bundle(
            family_profiles=family_profiles,
            family_order=family_order,
        )
        preferred_regimen = dict(comparative_bundle.get("preferred_regimen") or selector_bundle.get("preferred_frontline_regimen") or {})
        sequence_transition_bundle = build_sequence_transition_bundle(
            state=self.module_id,
            preferred_regimen=preferred_regimen,
            eligible_treatments=comparative_bundle.get("eligible_treatments") or [],
            current_treatment=payload.get("current_treatment") or "",
            missing_critical_inputs=list(dict.fromkeys(
                [
                    field
                    for field in ["molecular_assay_source", "molecular_assay_date"]
                    if nccn["prefer_akeega"] and str(payload.get(field, "")).strip() == ""
                ]
                + list(selector_bundle.get("arpi_decision_missing_inputs") or [])
                + list(selector_bundle.get("arpi_decision_stale_inputs") or [])
            )),
            progression_pattern=str(payload.get("progression_pattern") or ""),
            line_context="mHSPC_initial",
            field_values=payload,
            comparative_eligibility_matrix=comparative_bundle.get("comparative_eligibility_matrix") or {},
        )
        active_monitoring_package = build_active_regimen_monitoring_package(
            preferred_regimen.get("regimen_code"),
            family_code=preferred_regimen.get("family_code") or "arpi_family",
            field_values=payload,
        )
        metastatic_summary = build_metastatic_composition_summary(payload)
        case_summary = (
            "El caso corresponde a enfermedad metastásica sensible a la castración, oligometastásica y metacrónica. "
            f"La Red Nacional Integral del Cáncer (NCCN) 5.2026 la sitúa como {nccn['label']} "
            f"y la Asociación Europea de Urología (EAU) 2026 la compara con {eau['label']}."
        )
        if metastatic_summary.get("available"):
            case_summary = f"{case_summary} {metastatic_summary.get('narrative')}"

        # Auditoría Pacientes Insignia 2026-04-21 (§B.2/§D.4) — gates compartidos
        # para mHSPC oligometastásico metacrónico:
        #   1) Abiraterona (AKEEGA niraparib+abi metacrónico): Child-Pugh B/C
        #      hard-block → enzalutamida/darolutamida como ARPI alternativa.
        #   2) Docetaxel / cabazitaxel: neutropenia G4 activa aplaza el taxano
        #      hasta recuperación (ANC >1000/µL).
        severe_neutropenia_active = _flag_truthy_mhspc(
            payload.get("severe_neutropenia_grade4")
        )
        child_pugh_bc = resolve_child_pugh_bc(payload)
        abiraterone_gate_messages: list[str] = []
        neutropenia_gate_messages: list[str] = []
        treatments_raw = list(
            comparative_bundle.get("eligible_treatments")
            or selector_bundle.get("eligible_treatments")
            or []
        )
        filtered_treatments: list[dict[str, Any]] = []
        for tx in treatments_raw:
            tx_name_lower = str(tx.get("name") or "").lower()
            tx_regimen_code = str(tx.get("regimen_code") or "").upper()
            contains_abi = (
                "abirater" in tx_name_lower
                or tx_regimen_code in {
                    "ADT_ABIRATERONE",
                    "ADT_DOCETAXEL_ABIRATERONE",
                    "ADT_ABIRATERONE_NIRAPARIB",
                    "NIRAPARIB_ABIRATERONE",
                }
            )
            contains_taxane = (
                "docetaxel" in tx_name_lower
                or "cabazitaxel" in tx_name_lower
                or tx_regimen_code in {
                    "ADT_DOCETAXEL",
                    "ADT_DOCETAXEL_DAROLUTAMIDE",
                    "ADT_DOCETAXEL_ABIRATERONE",
                    "DOCETAXEL",
                    "CABAZITAXEL",
                }
            )
            if child_pugh_bc and contains_abi:
                continue
            if severe_neutropenia_active and contains_taxane:
                continue
            filtered_treatments.append(tx)
        # ── FAUBOT Pivotal coverage 2026-04-23 ────────────────────────
        # Aplica los 10 gates centralizados (ARANOTE, IPATential150,
        # ARASENS, TROPIC/CARD, ERA-223/PEACE-3, TRITON-3, NCCN cardio).
        pivotal_bundle = apply_pivotal_contraindication_gates(payload, filtered_treatments)
        filtered_treatments = pivotal_bundle["filtered_treatments"]
        pivotal_gate_messages = pivotal_bundle["not_recommended_messages"]
        pivotal_gates_oligo_meta = pivotal_bundle["gates_triggered"]
        if child_pugh_bc:
            abiraterone_gate_messages.append(
                abiraterone_hepatic_contraindication_note(
                    "AKEEGA metacrónico (ADT+abiraterona±niraparib)"
                )
            )
        if severe_neutropenia_active:
            neutropenia_gate_messages.append(
                "Docetaxel/cabazitaxel aplazado hasta resolución de neutropenia "
                "grado 4 activa (ANC <500/µL). Reanudar con ANC >1000/µL y "
                "considerar G-CSF profiláctico para los ciclos siguientes."
            )

        base_not_recommended = [
            "Evitar reclasificar la enfermedad metastásica metacrónica como recurrencia localizada únicamente.",
            "No omitir la terapia sistémica por el solo hecho de que la carga tumoral sea limitada.",
            "No presentar la terapia dirigida a metástasis como estándar de atención fuera de un contexto de ensayo o discusión multidisciplinaria.",
        ]
        for _msg in abiraterone_gate_messages + neutropenia_gate_messages + pivotal_gate_messages:
            if _msg and _msg not in base_not_recommended:
                base_not_recommended.append(_msg)

        result = evaluation_result(
            state=self.module_id,
            nccn_primary={"guideline": "NCCN", "version": "5.2026", "label": nccn["label"], "recommendation": "Combine systemic intensification with MDT discussion when disease is limited."},
            eau_comparison={"guideline": "EAU", "version": "2026", "label": eau["label"], "recommendation": eau["recommendation"], "comparison": comparison},
            eligible_treatments=filtered_treatments,
            not_recommended=base_not_recommended,
            missing_critical_inputs=list(dict.fromkeys(
                [
                    field
                    for field in ["molecular_assay_source", "molecular_assay_date"]
                    if nccn["prefer_akeega"] and str(payload.get(field, "")).strip() == ""
                ]
                + list(selector_bundle.get("arpi_decision_missing_inputs") or [])
                + list(selector_bundle.get("arpi_decision_stale_inputs") or [])
            )),
            contraindications=legacy.get("contraindications", []),
            durations_and_conditions=[
                "Mantener el backbone ADT junto con el ARPI seleccionado hasta progresión o intolerancia.",
                "Usar terapia dirigida a metástasis sólo tras revisión multidisciplinaria.",
            ],
            evidence_trace=[self.registry.get_module_evidence(self.module_id)],
            trial_matches=visible_trial_matches,
            applicability_badge="selected_candidate" if nccn["mdt_candidate"] else "guideline-consistent",
            report_sections={
                "summary": (
                    f"Ruta metastásica hormono-sensible oligometastásica metacrónica. {metastatic_summary.get('narrative')}".strip()
                    if metastatic_summary.get("available")
                    else "Ruta metastásica hormono-sensible oligometastásica metacrónica."
                ),
                "triplet_decision": triplet_decision,
                "frontline_regimen_rankings": selector_bundle["frontline_regimen_rankings"],
                "frontline_ranking_trace": selector_bundle.get("ranking_trace", {}),
            },
        )
        result["triplet_decision"] = triplet_decision
        result["triplet_decision_card"] = triplet_decision
        result["visible_trial_matches"] = visible_trial_matches
        result["hidden_cross_scenario_trial_count"] = hidden_trial_count
        result["preferred_frontline_regimen"] = preferred_regimen
        result["preferred_regimen_code"] = preferred_regimen.get("regimen_code", "")
        result["candidate_regimens_under_consideration"] = [
            str(item.get("regimen_code") or "")
            for item in list(result.get("eligible_treatments") or [])
            if str(item.get("regimen_code") or "")
        ]
        result["alternative_regimens"] = comparative_bundle.get("alternative_regimens") or selector_bundle.get("alternative_regimens") or []
        result["frontline_regimen_rankings"] = selector_bundle["frontline_regimen_rankings"]
        result["frontline_regimen_rejections"] = selector_bundle["frontline_regimen_rejections"]
        result["frontline_ranking_trace"] = selector_bundle.get("ranking_trace", {})
        result["ranking_policy_version"] = selector_bundle.get("ranking_policy_version", "")
        result["pivotal_trial_fit"] = selector_bundle["pivotal_trial_fit"]
        result["drug_component_metadata"] = selector_bundle["drug_component_metadata"]
        result["patient_specific_modifiers"] = selector_bundle["patient_specific_modifiers"]
        result["eligibility_gates"] = selector_bundle["eligibility_gates"]
        result["comparative_eligibility_matrix"] = comparative_bundle.get("comparative_eligibility_matrix") or family_profiles
        result["therapeutic_family_profiles"] = comparative_bundle.get("comparative_eligibility_matrix") or family_profiles
        result["care_setting_contract"] = {
            "care_setting": "systemic_intensification",
            "family_code": preferred_regimen.get("family_code") or "",
            "family_label": preferred_regimen.get("family_label") or "",
        }
        result["decision_quality"] = {
            "recommendation_family": preferred_regimen.get("family_label") or "ARPI",
            "confidence_category": "vigilada" if result.get("missing_critical_inputs") else "alta",
            "requires_human_review": bool(result.get("missing_critical_inputs")),
        }
        result["sequence_transition_bundle"] = sequence_transition_bundle
        result["active_regimen_monitoring_package"] = active_monitoring_package
        result["arpi_required_fields"] = list(selector_bundle.get("arpi_required_fields") or [])
        result["arpi_missing_inputs"] = list(selector_bundle.get("arpi_missing_inputs") or [])
        result["arpi_stale_inputs"] = list(selector_bundle.get("arpi_stale_inputs") or [])
        result["arpi_decision_required_fields"] = list(selector_bundle.get("arpi_decision_required_fields") or [])
        result["arpi_monitoring_required_fields"] = list(selector_bundle.get("arpi_monitoring_required_fields") or [])
        result["arpi_decision_missing_inputs"] = list(selector_bundle.get("arpi_decision_missing_inputs") or [])
        result["arpi_decision_stale_inputs"] = list(selector_bundle.get("arpi_decision_stale_inputs") or [])
        result["arpi_monitoring_missing_inputs"] = list(selector_bundle.get("arpi_monitoring_missing_inputs") or [])
        result["arpi_monitoring_stale_inputs"] = list(selector_bundle.get("arpi_monitoring_stale_inputs") or [])
        result["missing_monitoring_inputs"] = list(dict.fromkeys(
            list(selector_bundle.get("arpi_monitoring_missing_inputs") or [])
            + list(selector_bundle.get("arpi_monitoring_stale_inputs") or [])
        ))
        result["fallback_status"] = str(selector_bundle.get("fallback_status") or "normal")
        result["no_preferred_reason"] = str(selector_bundle.get("no_preferred_reason") or "")
        result["supportive_care_bundle"] = {
            "bone_health": [
                "Mantener calcio y vitamina D como soporte basal de salud ósea.",
            ] if has_bone_metastatic_component(payload) else [],
            "bone_protection_agents": [
                "Considerar denosumab o ácido zoledrónico según riesgo estructural y carga ósea.",
            ] if has_bone_metastatic_component(payload) and not nccn["bone_protection_started"] else [],
        }
        result["arpi_profile_completeness"] = str(selector_bundle.get("arpi_profile_completeness") or "")
        result["arpi_preference_readiness"] = str(selector_bundle.get("arpi_preference_readiness") or "")
        result["arpi_selection_contract"] = dict(selector_bundle.get("arpi_selection_contract") or {})
        scope_contract = build_systemic_regimen_scope_contract(self.module_id, result)
        result["systemic_regimen_scope"] = scope_contract["scope"]
        result["systemic_regimen_scope_contract"] = scope_contract
        # EPIC 9 Group D (GAP-6) — expose primary_rt_bundle + readiness.
        result["primary_rt_bundle"] = primary_rt_bundle
        result["primary_rt_priority"] = primary_rt_bundle.get("priority", "not_eligible")
        result["primary_rt_eligible"] = bool(primary_rt_bundle.get("eligible"))
        result["therapeutic_readiness_status"] = {
            **(result.get("therapeutic_readiness_status") or {}),
            "primary_rt": {
                "eligible": bool(primary_rt_bundle.get("eligible")),
                "priority": primary_rt_bundle.get("priority", "not_eligible"),
                "hard_blocks": list(primary_rt_bundle.get("hard_blocks") or []),
                "missing_inputs": list(primary_rt_bundle.get("missing_inputs") or []),
                "evidence_tier": primary_rt_bundle.get("evidence_tier", "N/A"),
            },
        }
        # Faubot 2026-04-24 (III) — exponer trazabilidad de gates pivotal.
        if pivotal_gates_oligo_meta:
            result["pivotal_contraindication_gates"] = [
                {
                    "code": g.get("code"),
                    "severity": g.get("severity"),
                    "message": g.get("message"),
                    "evidence_tag": g.get("evidence_tag"),
                    "trial_refs": list(g.get("trial_refs") or ()),
                }
                for g in pivotal_gates_oligo_meta
            ]
        return enrich_evaluation_result(
            result,
            clinical_title="Ruta priorizada de enfermedad oligometastásica metacrónica",
            case_summary=case_summary,
            recommended_trajectory="Combinar intensificación sistémica con discusión estructurada de terapia dirigida a metástasis cuando la carga de enfermedad siga siendo limitada.",
            personalized_fundamentals=[
                f"Candidato a terapia dirigida a metástasis: {'sí' if nccn['mdt_candidate'] else 'no'}.",
                f"Aptitud para intensificación sistémica: {'sí' if nccn['fit_for_intensification'] else 'no'}.",
                "La carga limitada de enfermedad no debe reclasificarse como recurrencia localizada simple, porque sigue siendo enfermedad metastásica sensible a la castración.",
                "ADT + darolutamida debe quedar visible como doblete de referencia cuando se busca intensificación con mejor tolerabilidad relativa.",
                "La discusión de terapia dirigida a metástasis solo debe sostenerse si existe contexto de ensayo, cohorte prospectiva o comité multidisciplinario.",
            ],
            alternatives=[
                "Doblete sistémico con inhibidor del receptor androgénico cuando la terapia dirigida a metástasis no es factible o no cambia la estrategia principal.",
                "Discusión multidisciplinaria para decidir si la terapia dirigida a metástasis puede retrasar otras escaladas sin comprometer control oncológico.",
            ],
            shared_decision_message=(
                "La decisión final debe integrar número y sitio de metástasis, factibilidad técnica de tratamiento dirigido, tolerancia a intensificación sistémica y objetivos del paciente."
            ),
            comparison_message=(
                "La comparación con la Asociación Europea de Urología (EAU) 2026 es especialmente útil para decidir el peso relativo de la terapia dirigida a metástasis frente a la intensificación sistémica."
            ),
        )

    @staticmethod
    def _note_for(legacy: dict, drug_label: str) -> str:
        for item in legacy.get("recommendations", []):
            if drug_label.lower() in item.get("combination", "").lower():
                return item.get("evidence", "")
        return ""
