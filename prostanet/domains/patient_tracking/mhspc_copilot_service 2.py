from __future__ import annotations

from typing import Any

from prostanet.ai.config import get_ai_config
from prostanet.agents.quality_assurance_agent import QualityAssuranceAgent
from prostanet.domains.mcspc_high_volume.service import (
    McspcHighVolumeMetachronousService,
    McspcHighVolumeService,
    McspcHighVolumeSyncService,
)
from prostanet.domains.mcspc_low_volume_sync_oligo.service import (
    McspcLowVolumeSyncOligoService,
)
from prostanet.domains.mcspc_oligo_metachronous.service import (
    McspcOligoMetachronousService,
)
from prostanet.domains.patient_tracking.decision_input_requirements_engine import (
    build_decision_input_requirements,
)
from prostanet.domains.patient_tracking.vertical_runtime import (
    build_blocking_input_groups,
    build_blocked_by_overlay,
    build_decision_delta_since_last_visit,
    build_evidence_basis_current_visit,
    build_final_presented_recommendation,
    build_histopathology_summary,
    build_model_like_confidence,
    build_runtime_patient,
    build_runtime_payload,
    build_shared_metastatic_summary,
    enrich_recommendation_with_metastatic_summary,
    guideline_basis_from_result,
    is_present,
    normalize_text,
    prepend_metastatic_context,
    resolve_vertical_status,
    run_vertical_qa_validation,
    safe_float,
)
from prostanet.shared.presentation_text import state_display_label, translate_text
from prostanet.engine.confidence_scoring import ConfidenceScorer
from prostanet.shared.advanced_support_normalizer import resolve_docetaxel_fit_override
from prostanet.shared.feature_flags import resolve_feature_flags
from prostanet.shared.metastatic_profile import derive_mhspc_burden_context
from prostanet.shared.systemic_regimen_scope import build_systemic_regimen_scope_contract


MHSPC_VERTICAL_STATES = {
    "mcspc_low_volume_sync_oligo",
    "mcspc_oligo_metachronous",
    "mcspc_high_volume",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
}


def _concordance_label(rule_action: str, overlay_action: str) -> str:
    rule_text = normalize_text(rule_action).lower()
    overlay_text = normalize_text(overlay_action).lower()
    if not rule_text or not overlay_text:
        return "rule_only"
    if rule_text == overlay_text:
        return "concordant"
    if "triplet" in rule_text and "triplet" in overlay_text:
        return "adjacent"
    if "radioterapia" in rule_text and "radioterapia" in overlay_text:
        return "adjacent"
    if any(token in rule_text and token in overlay_text for token in ("darolut", "enzalut", "apalut", "abirater")):
        return "adjacent"
    return "discordant"


def _state_label(state: str) -> str:
    return state_display_label(state)


def _volume_label(volume: str) -> str:
    normalized = normalize_text(volume).lower()
    if normalized == "high":
        return "alto volumen"
    if normalized == "low":
        return "bajo volumen"
    return normalize_text(volume) or "volumen no visible"


def _temporality_label(temporality: str) -> str:
    normalized = normalize_text(temporality).lower()
    if normalized in {"sync", "synchronous", "sincronico", "sincrónico"}:
        return "sincrónico / de novo"
    if normalized in {"metachronous", "metachronous ", "metacronico", "metacrónico"}:
        return "metacrónico"
    return normalize_text(temporality) or "temporalidad no visible"


class MhspcCopilotService:
    service_id = "mhspc_copilot"

    def __init__(self) -> None:
        self.low_volume_service = McspcLowVolumeSyncOligoService()
        self.oligo_service = McspcOligoMetachronousService()
        self.high_volume_service = McspcHighVolumeService()
        self.high_volume_sync_service = McspcHighVolumeSyncService()
        self.high_volume_metachronous_service = McspcHighVolumeMetachronousService()
        self.qa_agent = QualityAssuranceAgent()
        self.confidence_scorer = ConfidenceScorer()

    def evaluate(
        self,
        patient: dict[str, Any],
        *,
        effective_state: str = "",
        effective_management_track: str = "",
        latest_assessment: dict[str, Any] | None = None,
        longitudinal_bundle: dict[str, Any] | None = None,
        decision_input_requirements: dict[str, Any] | None = None,
        trigger_event: str = "",
    ) -> dict[str, Any]:
        flags = resolve_feature_flags()
        runtime_mode = get_ai_config().runtime_mode
        latest_state = normalize_text(
            effective_state
            or (longitudinal_bundle or {}).get("signals", {}).get("effective_state_final")
            or (longitudinal_bundle or {}).get("signals", {}).get("effective_state")
            or (longitudinal_bundle or {}).get("signals", {}).get("reconciled_state")
            or (longitudinal_bundle or {}).get("signals", {}).get("phenotype_state")
            or (latest_assessment or {}).get("state")
            or (patient.get("latest_assessment") or {}).get("state")
            or (patient.get("prior_history") or {}).get("current_state")
        )
        if not flags.get("ENABLE_MHSPC_COPILOT"):
            return self._disabled_bundle(state=latest_state, runtime_mode=runtime_mode, status="disabled")
        if latest_state not in MHSPC_VERTICAL_STATES:
            return self._disabled_bundle(state=latest_state, runtime_mode=runtime_mode, status="not_applicable")

        runtime_patient = build_runtime_patient(patient, longitudinal_bundle)
        payload = build_runtime_payload(
            runtime_patient,
            latest_assessment,
            effective_state=latest_state,
            overlay_keys={
                "volume_disease",
                "metastasis_count",
                "metastatic_temporality",
                "metastasis_site",
                "ecog",
                "ecog_score",
                "docetaxel_fit",
                "frailty_status",
                "dxa_baseline_done",
                "calcium_vitd_started",
                "bone_protection_started",
                "psma_pet_done",
                "psma_uptake_pattern",
                "psma_rads_score",
            },
        )
        normalized_state = self._normalize_state_family(latest_state, payload)
        module_result = self._evaluate_rule_based(normalized_state, payload)
        effective_state_final = self._normalize_state_family(
            module_result.get("state") or normalized_state,
            {
                **payload,
                "metastatic_temporality": module_result.get("disease_temporality") or payload.get("metastatic_temporality"),
            },
        )
        requirements = decision_input_requirements or build_decision_input_requirements(
            runtime_patient,
            effective_state=effective_state_final,
            effective_management_track=effective_management_track,
            latest_assessment=latest_assessment or patient.get("latest_assessment"),
            next_best_action=(longitudinal_bundle or {}).get("next_best_action") or {},
        )
        blocking_inputs = build_blocking_input_groups(requirements)
        signal_snapshot = dict((longitudinal_bundle or {}).get("signals") or patient.get("latest_signal_snapshot") or {})
        progression_gate_active = bool(signal_snapshot.get("progression_gate_active"))
        progression_gate_target = normalize_text(signal_snapshot.get("progression_gate_target") or "adt_progression_verification")
        progression_gate_reason = normalize_text(signal_snapshot.get("progression_gate_reason"))
        systemic_progression_context_resolved = normalize_text(signal_snapshot.get("systemic_progression_context_resolved") or "none")
        phenotype_summary = self._build_phenotype_summary(payload, effective_state_final, module_result)
        metastatic_composition_summary = build_shared_metastatic_summary(payload)
        histopathology_summary = build_histopathology_summary(payload)
        guideline_basis = guideline_basis_from_result(module_result)
        rule_based_recommendation = enrich_recommendation_with_metastatic_summary(
            self._build_rule_based_recommendation(
            module_result,
            phenotype_summary=phenotype_summary,
            ),
            metastatic_composition_summary,
        )
        ai_advisory_overlay = self._build_ai_overlay(
            module_result,
            runtime_mode=runtime_mode,
            blocking_inputs=blocking_inputs,
            phenotype_summary=phenotype_summary,
        )
        qa_validation = run_vertical_qa_validation(
            self.qa_agent,
            runtime_patient,
            reconciled_state=effective_state_final,
            action=ai_advisory_overlay.get("recommended_action") or rule_based_recommendation.get("recommended_action"),
            evidence_basis=guideline_basis,
            agent_id="mhspc_copilot_overlay",
            confidence_score=72.0 if ai_advisory_overlay.get("available") else 50.0,
        )
        confidence = build_model_like_confidence(
            self.confidence_scorer,
            runtime_patient,
            action=ai_advisory_overlay.get("recommended_action") or rule_based_recommendation.get("recommended_action"),
            guideline_result=module_result,
        )
        docetaxel_fitness = dict(module_result.get("docetaxel_fitness") or {})
        docetaxel_fitness.setdefault("eligible", not phenotype_summary.get("docetaxel_unfit", False))
        progression_gate_recommendation = {
            "source": progression_gate_target or "adt_progression_verification",
            "recommended_action": "Cerrar progresión bajo ADT con testosterona en rango de castración y reestadificación convencional antes de intensificar.",
            "recommendation_family": "systemic_progression_gate",
            "rationale": progression_gate_reason or "La enfermedad metastásica ya está fenotipada, pero la intensificación resistente sigue bloqueada hasta confirmar castración y restaging suficiente.",
            "guideline_basis": [
                "NCCN 2026 CRPC workup",
                "EAU 2026 CRPC workup",
            ],
        }
        progression_gate_recommendation = enrich_recommendation_with_metastatic_summary(
            progression_gate_recommendation,
            metastatic_composition_summary,
        )
        if progression_gate_active:
            final_presented_recommendation = progression_gate_recommendation
        else:
            final_presented_recommendation = build_final_presented_recommendation(
                runtime_mode=runtime_mode,
                rule_based_recommendation=rule_based_recommendation,
                ai_overlay=ai_advisory_overlay,
                qa_validation=qa_validation,
                blocking_groups=blocking_inputs,
                advisory_source="mhspc_copilot_advisory",
                rationale="Overlay AI presentado porque pasó QA, no hay blockers duros y la recomendación sigue siendo concordante con la ruta primaria mHSPC.",
            )
            final_presented_recommendation = enrich_recommendation_with_metastatic_summary(
                final_presented_recommendation,
                metastatic_composition_summary,
            )
        blocked_by_overlay = build_blocked_by_overlay(
            blocking_groups=blocking_inputs,
            progression_gate_active=progression_gate_active,
            progression_gate_target=progression_gate_target,
            progression_gate_reason=progression_gate_reason,
        )
        # Faubot 2026-04-25 (IX) — Delta longitudinal de gates pivotal.
        # Compara los gates actuales (del module_result) con los del
        # latest_assessment previo (persistido) → detecta gates activados,
        # desactivados o con cambio de severity desde la visita anterior.
        from prostanet.shared.pivotal_gate_delta import (
            extract_previous_pivotal_gates,
        )
        _current_pivotal_gates = list(module_result.get("pivotal_contraindication_gates") or [])
        _previous_pivotal_gates = extract_previous_pivotal_gates(latest_assessment)
        decision_delta_since_last_visit = build_decision_delta_since_last_visit(
            runtime_patient,
            effective_state=effective_state_final,
            phenotype_state=signal_snapshot.get("phenotype_state") or effective_state_final,
            rule_based_recommendation=rule_based_recommendation,
            final_presented_recommendation=final_presented_recommendation,
            blocking_groups=blocking_inputs,
            blocked_by_overlay=blocked_by_overlay,
            current_pivotal_gates=_current_pivotal_gates,
            previous_pivotal_gates=_previous_pivotal_gates,
        )
        evidence_basis_current_visit = build_evidence_basis_current_visit(
            guideline_basis,
            rule_based_recommendation,
            decision_delta_since_last_visit,
        )
        status = resolve_vertical_status(
            runtime_mode=runtime_mode,
            qa_validation=qa_validation,
            blocking_groups=blocking_inputs,
            ai_overlay=ai_advisory_overlay,
        )
        return {
            "enabled": True,
            "available": True,
            "show_card": True,
            "service_id": self.service_id,
            "status": status,
            "state_family": effective_state_final,
            "state_family_label": _state_label(effective_state_final),
            "raw_state": latest_state,
            "runtime_mode": runtime_mode,
            "rule_based_source_of_truth": True,
            "effective_state": effective_state_final,
            "phenotype_state": signal_snapshot.get("phenotype_state") or effective_state_final,
            "effective_management_track": effective_management_track or "systemic_surveillance",
            "histopathology_summary": histopathology_summary,
            "phenotype_summary": phenotype_summary,
            "volume_disease": phenotype_summary.get("volume_disease", ""),
            "temporality": phenotype_summary.get("temporality", ""),
            "oligometastatic_operational": phenotype_summary.get("oligometastatic_operational", False),
            "rt_primary_candidate": phenotype_summary.get("rt_primary_candidate", False),
            "mdt_candidate": phenotype_summary.get("mdt_candidate", False),
            "docetaxel_fitness": docetaxel_fitness,
            "metastatic_composition_summary": metastatic_composition_summary,
            "systemic_regimen_scope": str(module_result.get("systemic_regimen_scope") or "mhspc_doublet_triplet"),
            "systemic_regimen_scope_contract": dict(
                module_result.get("systemic_regimen_scope_contract")
                or build_systemic_regimen_scope_contract(effective_state_final, module_result)
            ),
            "preferred_frontline_regimen": dict(module_result.get("preferred_frontline_regimen") or {}),
            "overall_preferred_frontline_regimen": dict(
                module_result.get("overall_preferred_frontline_regimen")
                or module_result.get("preferred_frontline_regimen")
                or {}
            ),
            "frontline_regimen_rankings": list(module_result.get("frontline_regimen_rankings") or []),
            "frontline_regimen_rejections": list(module_result.get("frontline_regimen_rejections") or []),
            "frontline_ranking_trace": dict(module_result.get("frontline_ranking_trace") or {}),
            "ranking_policy_version": normalize_text(module_result.get("ranking_policy_version") or ""),
            "triplet_decision": dict(module_result.get("triplet_decision") or {}),
            "bone_health_bundle": self._bone_health_bundle(module_result, payload),
            "rule_based_recommendation": rule_based_recommendation,
            "progression_gate_active": progression_gate_active,
            "progression_gate_target": progression_gate_target,
            "progression_gate_reason": progression_gate_reason,
            "systemic_progression_context_resolved": systemic_progression_context_resolved,
            "progression_gate_recommendation": progression_gate_recommendation if progression_gate_active else {},
            "ai_advisory_overlay": ai_advisory_overlay,
            "final_presented_recommendation": final_presented_recommendation,
            "blocking_inputs": blocking_inputs,
            "blocked_by_overlay": blocked_by_overlay,
            "qa_validation": qa_validation,
            "guideline_basis": guideline_basis,
            "evidence_basis_current_visit": evidence_basis_current_visit,
            "confidence": confidence,
            "why_changed_today": prepend_metastatic_context(
                self._build_why_changed_today(
                    payload, phenotype_summary, module_result,
                    pivotal_gates_delta=decision_delta_since_last_visit.get("pivotal_gates_delta"),
                ),
                metastatic_composition_summary,
            ),
            "decision_delta_since_last_visit": decision_delta_since_last_visit,
            "mhspc_schedule_overlay": self._build_schedule_overlay(phenotype_summary, blocking_inputs, module_result, progression_gate_active=progression_gate_active),
            "trigger_event": trigger_event or "longitudinal_refresh",
            # Faubot 2026-04-24 (III) — propagar trazabilidad de gates pivotal
            # y not_recommended desde el módulo. Sin estas claves, la UI y los
            # auditores no pueden ver QUÉ régimen fue filtrado y POR QUÉ desde
            # el output del copilot. El módulo (mcspc_*_service) ya filtra
            # `eligible_treatments`; aquí simplemente surface el rastro.
            "pivotal_contraindication_gates": list(
                module_result.get("pivotal_contraindication_gates") or []
            ),
            "not_recommended": list(module_result.get("not_recommended") or []),
        }

    def _disabled_bundle(self, *, state: str, runtime_mode: str, status: str) -> dict[str, Any]:
        return {
            "enabled": False,
            "available": False,
            "show_card": False,
            "status": status,
            "state_family": state,
            "state_family_label": _state_label(state),
            "runtime_mode": runtime_mode,
            "rule_based_source_of_truth": True,
            "effective_management_track": "",
            "histopathology_summary": "",
            "phenotype_state": state,
            "phenotype_summary": {},
            "volume_disease": "",
            "systemic_regimen_scope": "not_applicable",
            "systemic_regimen_scope_contract": build_systemic_regimen_scope_contract(state, {}),
            "temporality": "",
            "oligometastatic_operational": False,
            "rt_primary_candidate": False,
            "mdt_candidate": False,
            "docetaxel_fitness": {},
            "metastatic_composition_summary": {"available": False},
            "progression_gate_active": False,
            "progression_gate_target": "",
            "progression_gate_reason": "",
            "systemic_progression_context_resolved": "none",
            "progression_gate_recommendation": {},
            "preferred_frontline_regimen": {},
            "frontline_regimen_rankings": [],
            "frontline_regimen_rejections": [],
            "frontline_ranking_trace": {},
            "ranking_policy_version": "",
            "triplet_decision": {},
            "bone_health_bundle": {},
            "rule_based_recommendation": {},
            "ai_advisory_overlay": {"available": False, "status": status},
            "final_presented_recommendation": {},
            "blocking_inputs": [],
            "blocked_by_overlay": [],
            "qa_validation": {"approved": False, "flags": [], "missing_data_alerts": []},
            "guideline_basis": [],
            "evidence_basis_current_visit": [],
            "confidence": {"composite_score": 0.0, "components": {}, "weights_used": {}},
            "why_changed_today": [],
            "decision_delta_since_last_visit": {"available": False},
            "mhspc_schedule_overlay": {},
            # Faubot 2026-04-24 (III) — paridad con bundle activo.
            "pivotal_contraindication_gates": [],
            "not_recommended": [],
        }

    def _normalize_state_family(self, state: str, payload: dict[str, Any]) -> str:
        burden_context = derive_mhspc_burden_context(payload)
        temporality = normalize_text(
            burden_context.get("temporality")
            or payload.get("metastatic_temporality")
            or payload.get("disease_temporality")
        ).lower()
        if (
            burden_context.get("volume_disease") == "High"
            or burden_context.get("visceral_present")
        ):
            return "mcspc_high_volume_metachronous" if temporality.startswith("meta") else "mcspc_high_volume_sync"
        if state != "mcspc_high_volume":
            return state
        if temporality.startswith("meta"):
            return "mcspc_high_volume_metachronous"
        return "mcspc_high_volume_sync"

    def _evaluate_rule_based(self, state_family: str, payload: dict[str, Any]) -> dict[str, Any]:
        if state_family == "mcspc_low_volume_sync_oligo":
            return self.low_volume_service.evaluate(payload)
        if state_family == "mcspc_oligo_metachronous":
            return self.oligo_service.evaluate(payload)
        if state_family == "mcspc_high_volume_sync":
            return self.high_volume_sync_service.evaluate(payload)
        if state_family == "mcspc_high_volume_metachronous":
            return self.high_volume_metachronous_service.evaluate(payload)
        return self.high_volume_service.evaluate(payload)

    def _build_phenotype_summary(
        self,
        payload: dict[str, Any],
        state_family: str,
        module_result: dict[str, Any],
    ) -> dict[str, Any]:
        burden_context = derive_mhspc_burden_context(payload)
        eligible_treatments = list(module_result.get("eligible_treatments") or [])
        volume_disease = normalize_text(
            burden_context.get("volume_disease")
            or payload.get("volume_disease")
            or ("High" if "high_volume" in state_family else "Low")
        )
        temporality = normalize_text(module_result.get("disease_temporality") or payload.get("metastatic_temporality") or ("metachronous" if "metachronous" in state_family else "sync"))
        metastasis_count = safe_float(burden_context.get("metastasis_count")) or safe_float(payload.get("metastasis_count")) or 0.0
        rt_primary_candidate = any("rt al primario" in normalize_text(item.get("name")).lower() for item in eligible_treatments)
        mdt_candidate = any("metastasis-directed" in normalize_text(item.get("name")).lower() or "mdt" in normalize_text(item.get("name")).lower() for item in eligible_treatments)
        oligometastatic_operational = bool(
            burden_context.get("oligometastatic_operational")
            or state_family == "mcspc_oligo_metachronous"
        )
        return {
            "state_family": state_family,
            "label": _state_label(state_family),
            "volume_disease": volume_disease or "Low",
            "volume_disease_label": _volume_label(volume_disease or "Low"),
            "temporality": temporality or "sync",
            "temporality_label": _temporality_label(temporality or "sync"),
            "oligometastatic_operational": oligometastatic_operational,
            "rt_primary_candidate": rt_primary_candidate,
            "mdt_candidate": mdt_candidate,
            "metastasis_count": metastasis_count,
            "m_substage_resolved": normalize_text(burden_context.get("m_substage_resolved") or ""),
            "bone_present": bool(burden_context.get("bone_present")),
            "visceral_present": bool(burden_context.get("visceral_present")),
            "nonregional_nodal_present": bool(burden_context.get("nonregional_nodal_present")),
            "has_mixed_metastatic_sites": bool(burden_context.get("has_mixed_metastatic_sites")),
            "metastatic_components": list(burden_context.get("metastatic_components") or []),
            "metastatic_profile_summary": normalize_text(burden_context.get("metastatic_profile_summary") or ""),
            "bone_distribution_summary": normalize_text(burden_context.get("bone_distribution_summary") or ""),
            "visceral_distribution_summary": normalize_text(burden_context.get("visceral_distribution_summary") or ""),
            "visceral_sites": list(burden_context.get("visceral_sites") or []),
            # Auditoría Pacientes Insignia 2026-04-21 (§E.1) — normalización
            # canónica de docetaxel_fit vía `resolve_docetaxel_fit_override`
            # (acepta alias `taxane_fitness`, `fit_for_docetaxel`,
            # `chemotherapy_fitness`, y valores ES-médica
            # "Apto (fit)"/"No apto"/"Marginal"/"Desconocido"). `override is
            # False` implica decisión explícita de no apto; si hay
            # `docetaxel_fit_summary` ya computado por el rules engine,
            # respetarlo (no marcar unfit).
            "docetaxel_unfit": (
                not bool((module_result.get("docetaxel_fitness") or {}).get("docetaxel_fit_summary", ""))
                and resolve_docetaxel_fit_override(payload) is False
            ),
        }

    def _build_rule_based_recommendation(
        self,
        module_result: dict[str, Any],
        *,
        phenotype_summary: dict[str, Any],
    ) -> dict[str, Any]:
        nccn = dict(module_result.get("nccn_primary") or {})
        structured = dict((module_result.get("report_sections") or {}).get("structured_summary") or {})
        action = translate_text(normalize_text(nccn.get("recommendation") or structured.get("trayectoria_recomendada")))
        rationale_bits = [translate_text(item) for item in list(structured.get("fundamentos_personalizados") or [])[:3]]
        if phenotype_summary.get("rt_primary_candidate"):
            rationale_bits.append("RT al primario sigue visible para este fenotipo.")
        if phenotype_summary.get("mdt_candidate"):
            rationale_bits.append("La discusión de MDT se mantiene como candidata, no como obligación automática.")
        if phenotype_summary.get("has_mixed_metastatic_sites"):
            rationale_bits.append(
                f"Existe compromiso metastásico mixto: {phenotype_summary.get('metastatic_profile_summary') or 'componente visceral y óseo/nodal concomitante'}."
            )
        return {
            "source": "rule_based_primary",
            "recommended_action": action,
            "recommendation_family": "systemic_intensification",
            "rationale": " ".join(normalize_text(item) for item in rationale_bits if normalize_text(item)) or "La capa rule-based sigue siendo la fuente primaria de verdad clínica.",
            "guideline_basis": guideline_basis_from_result(module_result),
        }

    def _build_ai_overlay(
        self,
        module_result: dict[str, Any],
        *,
        runtime_mode: str,
        blocking_inputs: list[dict[str, Any]],
        phenotype_summary: dict[str, Any],
    ) -> dict[str, Any]:
        preferred = dict(module_result.get("preferred_frontline_regimen") or {})
        if not preferred:
            return {
                "available": False,
                "status": "unavailable",
                "recommended_action": "",
                "concordance_label": "rule_only",
                "shadow_reasons": ["No hay régimen frontline individualizado disponible todavía."],
            }
        label = normalize_text(preferred.get("regimen_label") or preferred.get("label") or preferred.get("regimen_code"))
        if phenotype_summary.get("rt_primary_candidate"):
            recommended_action = f"{label} + RT al primario"
        elif phenotype_summary.get("mdt_candidate"):
            recommended_action = f"{label} + discusión MDT"
        else:
            recommended_action = label
        hard_blocked = any(group.get("required_fields") for group in blocking_inputs)
        concordance = _concordance_label(
            normalize_text((module_result.get("nccn_primary") or {}).get("recommendation")),
            recommended_action,
        )
        status = "shadow-blocked" if hard_blocked else "advisory_candidate" if runtime_mode == "advisory" and concordance != "discordant" else "shadow"
        reasons = [
            "La recomendación AI permanece en shadow hasta que QA apruebe y no existan blockers duros."
            if runtime_mode == "shadow"
            else "La recomendación AI solo puede presentarse si sigue siendo concordante con la ruta primaria."
        ]
        if phenotype_summary.get("rt_primary_candidate"):
            reasons.append("El fenotipo bajo volumen sincrónico mantiene visible RT al primario.")
        if phenotype_summary.get("mdt_candidate"):
            reasons.append("La MDT sigue siendo una candidata contextual y no una obligación estándar.")
        if phenotype_summary.get("has_mixed_metastatic_sites"):
            reasons.append("La composición metastásica mixta conserva el fenotipo sistémico y mantiene visibles los componentes específicos, incluido soporte óseo si hay hueso.")
        return {
            "available": True,
            "status": status,
            "recommended_action": recommended_action,
            "recommendation_family": "frontline_regimen",
            "sequence_candidate": preferred,
            "concordance_label": concordance,
            "shadow_reasons": reasons,
        }

    def _bone_health_bundle(self, module_result: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        bundle = dict((module_result.get("report_sections") or {}).get("bone_health_bundle") or {})
        if bundle:
            return bundle
        return {
            "dxa_baseline_done": str(payload.get("dxa_baseline_done", "0")) == "1",
            "calcium_vitd_started": str(payload.get("calcium_vitd_started", "0")) == "1",
            "bone_protection_started": str(payload.get("bone_protection_started", "0")) == "1",
        }

    def _build_why_changed_today(
        self,
        payload: dict[str, Any],
        phenotype_summary: dict[str, Any],
        module_result: dict[str, Any],
        pivotal_gates_delta: dict[str, Any] | None = None,
    ) -> list[str]:
        notes = [
            f"Volumen derivado: {phenotype_summary.get('volume_disease', 'Low')}.",
            f"Temporalidad: {phenotype_summary.get('temporality', 'sync')}.",
        ]
        if phenotype_summary.get("has_mixed_metastatic_sites"):
            notes.append(
                f"Composición metastásica mixta: {phenotype_summary.get('metastatic_profile_summary') or 'visceral + hueso/nodos'}."
            )
        elif phenotype_summary.get("metastatic_profile_summary"):
            notes.append(phenotype_summary.get("metastatic_profile_summary"))
        metastasis_count = safe_float(payload.get("metastasis_count"))
        if metastasis_count is not None:
            notes.append(f"Carga metastásica actual: {metastasis_count:g} lesiones.")
        ecog = normalize_text(payload.get("ecog_score") or payload.get("ecog"))
        if ecog:
            notes.append(f"ECOG actual {ecog}.")
        preferred = normalize_text(((module_result.get("preferred_frontline_regimen") or {}).get("regimen_label")))
        if preferred:
            notes.append(f"Régimen frontline preferente: {preferred}.")
        winner_reason = normalize_text(((module_result.get("frontline_ranking_trace") or {}).get("winner_reason")))
        if winner_reason:
            notes.append(winner_reason)
        if normalize_text((module_result.get("triplet_decision") or {}).get("summary")):
            notes.append(normalize_text((module_result.get("triplet_decision") or {}).get("summary")))
        # Faubot 2026-04-25 (IX) — narrativa clínica del delta de gates.
        # Las notas de gates van AL FINAL para no desplazar el contexto
        # mHSPC esencial; truncamos a 6 mensajes total.
        if pivotal_gates_delta:
            from prostanet.shared.pivotal_gate_delta import (
                describe_gate_delta_in_clinical_language,
            )
            gate_notes = describe_gate_delta_in_clinical_language(pivotal_gates_delta)
            notes.extend(gate_notes)
        return notes[:8]  # +2 slots vs. 6 anterior por las nuevas narrativas

    def _build_schedule_overlay(
        self,
        phenotype_summary: dict[str, Any],
        blocking_inputs: list[dict[str, Any]],
        module_result: dict[str, Any],
        *,
        progression_gate_active: bool = False,
    ) -> dict[str, Any]:
        if progression_gate_active:
            cadence = ["Testosterona sérica actual", "Imagen convencional para cerrar si el caso sigue sensible o ya migró a CRPC"]
            primary_intent = "Fenotipo metastásico resuelto con gate activo de progresión bajo ADT"
        elif phenotype_summary.get("state_family") == "mcspc_low_volume_sync_oligo":
            cadence = ["PSA y tolerancia sistémica", "RT al primario cuando aplique"]
            primary_intent = "Doblete + evaluación local al primario"
        elif phenotype_summary.get("state_family") == "mcspc_oligo_metachronous":
            cadence = ["PSA / reestadificación", "Comité para MDT si cambia conducta"]
            primary_intent = "Intensificación sistémica con MDT contextual"
        elif phenotype_summary.get("temporality") == "sync":
            cadence = ["Labs y tolerancia a docetaxel/ARPI", "Bundle de salud ósea"]
            primary_intent = "Triplete o doblete intensificado de alto volumen"
        else:
            cadence = ["Revisión de fitness y comorbilidades", "Reestadificación sistémica"]
            primary_intent = "Doblete o triplete adaptado al alto volumen metacrónico"
        blockers = [group.get("group_label") for group in blocking_inputs if group.get("required_fields")]
        return {
            "schedule_primary_intent": primary_intent,
            "cadence_adjustment_reasons": cadence + blockers[:2],
            "recommended_events": cadence[:3],
            "triplet_summary": normalize_text((module_result.get("triplet_decision") or {}).get("summary")),
        }


def build_mhspc_copilot_bundle(
    patient: dict[str, Any],
    *,
    effective_state: str = "",
    effective_management_track: str = "",
    latest_assessment: dict[str, Any] | None = None,
    longitudinal_bundle: dict[str, Any] | None = None,
    decision_input_requirements: dict[str, Any] | None = None,
    trigger_event: str = "",
) -> dict[str, Any]:
    return MhspcCopilotService().evaluate(
        patient,
        effective_state=effective_state,
        effective_management_track=effective_management_track,
        latest_assessment=latest_assessment,
        longitudinal_bundle=longitudinal_bundle,
        decision_input_requirements=decision_input_requirements,
        trigger_event=trigger_event,
    )


__all__ = ["MhspcCopilotService", "build_mhspc_copilot_bundle", "MHSPC_VERTICAL_STATES"]
