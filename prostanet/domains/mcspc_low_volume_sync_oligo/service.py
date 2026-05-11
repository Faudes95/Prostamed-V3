from __future__ import annotations

from typing import Any

from prostanet.shared.precision_medicine_legacy import evaluate_patient_for_mhspc

from prostanet.domains.evidence_registry.service import EvidenceRegistryService
from prostanet.domains.guideline_comparison.service import GuidelineComparisonService
from prostanet.domains.mcspc_low_volume_sync_oligo.rules_eau import evaluate_mcspc_low_volume_eau
from prostanet.domains.mcspc_low_volume_sync_oligo.rules_nccn import evaluate_mcspc_low_volume
from prostanet.domains.mcspc_low_volume_sync_oligo.schemas import MCSPC_LOW_VOLUME_SCHEMA
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


class McspcLowVolumeSyncOligoService:
    module_id = "mcspc_low_volume_sync_oligo"

    def __init__(self) -> None:
        self.registry = EvidenceRegistryService()
        self.comparison = GuidelineComparisonService()

    def schema(self) -> dict:
        return MCSPC_LOW_VOLUME_SCHEMA

    def evaluate(self, payload: dict) -> dict:
        nccn = evaluate_mcspc_low_volume(payload)
        eau = evaluate_mcspc_low_volume_eau(payload)
        comparison = self.comparison.compare(nccn, eau)
        normalized = dict(payload)
        normalized["comorbidities"] = {
            "seizure": str(payload.get("comorbidity_seizure", "0")) == "1",
            "cardio": str(payload.get("comorbidity_cardio", "0")) == "1",
        }
        legacy = evaluate_patient_for_mhspc(normalized)
        selector_bundle = select_mhspc_frontline_regimens(self.module_id, payload)
        # EPIC 9 Group D (GAP-6) — evaluación estructurada de RT al tumor
        # primario (STAMPEDE-H / PEACE-1). El resultado alimenta
        # therapeutic_readiness_status y profile_compass.
        primary_rt_bundle = evaluate_primary_rt(payload)
        triplet_decision = build_triplet_decision(self.module_id, payload, selector_bundle=selector_bundle)
        visible_trial_matches, hidden_trial_count = build_visible_mhspc_trial_matches(
            self.module_id,
            payload,
            triplet_decision=triplet_decision,
        )
        family_profiles = deepcopy(selector_bundle.get("comparative_eligibility_matrix") or {})
        if nccn["rt_primary_candidate"]:
            local_options = list(((family_profiles.get("local_mdt_family") or {}).get("variant_ranking") or {}).get("eligible_regimens_ranked") or [])
            local_options.append(
                build_ranked_option(
                    name="RT al primario",
                    regimen_code="RT_TO_PRIMARY",
                    rank=len(local_options) + 1,
                    priority="eligible",
                    eligibility_status="eligible_nonpreferred",
                    family_code="local_mdt_family",
                    molecule_or_backbone="Radioterapia al primario",
                    description="Control local del tumor primario en mHSPC de bajo volumen sincrónico.",
                    route="Radioterapia externa",
                    schedule="Integrada con ADT/doblete",
                    metadata_source="guideline_backbone",
                    notes=self._note_for(legacy, "Radioterapia al Primario"),
                    why_this_rank=["El control local del primario añade valor en bajo volumen, pero no sustituye la intensificación sistémica dominante."],
                )
            )
            family_profiles["local_mdt_family"] = build_family_profile(
                family_code="local_mdt_family",
                ordered_regimens=local_options,
                context={
                    "eligibility_status": "eligible",
                    "winner_reason": "El control local del primario compite formalmente en bajo volumen, pero suele quedar detrás del doblete sistémico preferente.",
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
                    notes="Ruta de precisión para BRCA2 trazable en mCSPC.",
                    why_this_rank=["La vía de precisión BRCA2 sigue visible, pero no debe ocultar el backbone sistémico dominante del escenario."],
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
                    "winner_reason": "La precisión BRCA2 queda visible como overlay, no como reemplazo automático del doblete basal.",
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
            "El caso corresponde a enfermedad metastásica sensible a la castración de bajo volumen u oligometastásica sincrónica. "
            f"La Red Nacional Integral del Cáncer (NCCN) 5.2026 la describe como {nccn['label']} "
            f"y la Asociación Europea de Urología (EAU) 2026 la compara con {eau['label']}."
        )
        if metastatic_summary.get("available"):
            case_summary = f"{case_summary} {metastatic_summary.get('narrative')}"

        # Auditoría Pacientes Insignia 2026-04-21 (§B.2/§D.4) — gates compartidos
        # para mHSPC bajo volumen:
        #   1) Abiraterona (LATITUDE bajo volumen / AKEEGA): Child-Pugh B/C dispara
        #      hard-block y se prefiere enzalutamida/darolutamida.
        #   2) Docetaxel (CHAARTED/STAMPEDE bajo volumen): neutropenia G4 activa
        #      aplaza el taxano hasta recuperación (ANC >1000/µL).
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
        pivotal_gates_low_volume = pivotal_bundle["gates_triggered"]
        if child_pugh_bc:
            abiraterone_gate_messages.append(
                abiraterone_hepatic_contraindication_note(
                    "LATITUDE bajo volumen / AKEEGA (ADT+abiraterona±niraparib)"
                )
            )
        if severe_neutropenia_active:
            neutropenia_gate_messages.append(
                "Docetaxel/cabazitaxel aplazado hasta resolución de neutropenia "
                "grado 4 activa (ANC <500/µL). Reanudar con ANC >1000/µL y "
                "considerar G-CSF profiláctico para los ciclos siguientes "
                "(CHAARTED / STAMPEDE bajo volumen)."
            )

        base_not_recommended = [
            "No posicionar docetaxel en monoterapia como opción por defecto en enfermedad de bajo volumen.",
            "No presentar la enfermedad de bajo volumen como equivalente a la enfermedad de alto volumen con triplete como primera línea.",
        ]
        for _msg in abiraterone_gate_messages + neutropenia_gate_messages + pivotal_gate_messages:
            if _msg and _msg not in base_not_recommended:
                base_not_recommended.append(_msg)

        result = evaluation_result(
            state=self.module_id,
            nccn_primary={"guideline": "NCCN", "version": "5.2026", "label": nccn["label"], "recommendation": nccn["recommendation"]},
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
                "Mantener el backbone ADT de forma continua junto con el ARPI seleccionado.",
                "Si se elige RT al primario, integrarla con el timing de la terapia sistémica.",
                "Mantener calcio y vitamina D como soporte basal de salud ósea." if has_bone_metastatic_component(payload) else "",
                "Considerar denosumab o ácido zoledrónico si la carga ósea y el riesgo estructural lo justifican." if has_bone_metastatic_component(payload) and not nccn["bone_protection_started"] else "",
            ],
            evidence_trace=[self.registry.get_module_evidence(self.module_id)],
            trial_matches=visible_trial_matches,
            applicability_badge="guideline-consistent",
            report_sections={
                "summary": (
                    f"Ruta metastásica hormono-sensible de bajo volumen. {metastatic_summary.get('narrative')}".strip()
                    if metastatic_summary.get("available")
                    else "Ruta metastásica hormono-sensible de bajo volumen."
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
                "Considerar denosumab o ácido zoledrónico si la carga ósea y el riesgo estructural lo justifican.",
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
        if pivotal_gates_low_volume:
            result["pivotal_contraindication_gates"] = [
                {
                    "code": g.get("code"),
                    "severity": g.get("severity"),
                    "message": g.get("message"),
                    "evidence_tag": g.get("evidence_tag"),
                    "trial_refs": list(g.get("trial_refs") or ()),
                }
                for g in pivotal_gates_low_volume
            ]
        return enrich_evaluation_result(
            result,
            clinical_title="Ruta priorizada de enfermedad metastásica sensible a la castración de bajo volumen",
            case_summary=case_summary,
            recommended_trajectory=nccn["recommendation"],
            personalized_fundamentals=[
                "El bajo volumen no equivale a enfermedad localizada; sigue requiriendo intensificación sistémica adecuada al contexto.",
                f"Candidato a radioterapia al tumor primario: {'sí' if nccn['rt_primary_candidate'] else 'no'}.",
                "La salud ósea basal debe documentarse antes de prolongar terapia sistémica en enfermedad metastásica.",
                "La selección entre darolutamida, enzalutamida, apalutamida y abiraterona se ajusta por comorbilidades neurológicas, cardiovasculares y hepáticas.",
            ],
            alternatives=[
                "Radioterapia al tumor primario cuando la próstata no ha recibido tratamiento local y el escenario sigue siendo de bajo volumen.",
                "Doblete sistémico individualizado según riesgo de convulsiones, tolerancia hepática y preferencias del paciente.",
            ],
            shared_decision_message=(
                "La conducta final debe integrar volumen metastásico real, estado funcional, toxicidad esperada y la conveniencia de añadir o no tratamiento local al primario."
            ),
            comparison_message=(
                "La comparación con la Asociación Europea de Urología (EAU) 2026 ayuda a confirmar cuándo la radioterapia al primario agrega valor y cómo priorizar el doblete sistémico."
            ),
        )

    @staticmethod
    def _note_for(legacy: dict, drug_label: str) -> str:
        for item in legacy.get("recommendations", []):
            if drug_label.lower() in item.get("combination", "").lower():
                return item.get("evidence", "")
        return ""
