from __future__ import annotations

from typing import Any

from prostanet.ai.config import get_ai_config
from prostanet.agents.quality_assurance_agent import QualityAssuranceAgent
from prostanet.domains.diagnostic_workup.service import DiagnosticWorkupService
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
    guideline_basis_from_result,
    normalize_text,
    resolve_vertical_status,
    run_vertical_qa_validation,
    safe_float,
)
from prostanet.domains.post_negative_biopsy_followup.service import (
    PostNegativeBiopsyFollowupService,
)
from prostanet.engine.confidence_scoring import ConfidenceScorer
from prostanet.shared.feature_flags import resolve_feature_flags


DIAGNOSTIC_VERTICAL_STATES = {"diagnostic_workup", "post_negative_biopsy_followup"}


def _concordance_label(rule_action: str, overlay_action: str) -> str:
    rule_text = normalize_text(rule_action).lower()
    overlay_text = normalize_text(overlay_action).lower()
    if not rule_text or not overlay_text:
        return "rule_only"
    if rule_text == overlay_text:
        return "concordant"
    # Guard M-1 (FAUBOT): la detección de "adjacent" debe soportar recomendaciones
    # en inglés y español (rule-based y overlay pueden emitir en cualquier idioma).
    biopsy_tokens = ("biops",)  # "biopsy" y "biopsia" comparten raíz
    mri_tokens = ("mri", "resonancia", "mpmri")
    followup_tokens = ("seguimiento", "follow-up", "follow up", "followup", "vigilanc")
    rebiopsy_tokens = ("rebiops", "re-biops", "re biops", "reabr")  # "rebiopsy"/"rebiopsia"/"reabrir"
    if any(tok in rule_text for tok in biopsy_tokens) and any(tok in overlay_text for tok in biopsy_tokens):
        return "adjacent"
    if any(tok in rule_text for tok in mri_tokens) and any(tok in overlay_text for tok in mri_tokens):
        return "adjacent"
    if any(tok in rule_text for tok in followup_tokens) and any(tok in overlay_text for tok in followup_tokens):
        return "adjacent"
    if any(tok in rule_text for tok in rebiopsy_tokens) and any(tok in overlay_text for tok in rebiopsy_tokens):
        return "adjacent"
    return "discordant"


class DiagnosticBiopsyCopilotService:
    service_id = "diagnostic_biopsy_copilot"

    def __init__(self) -> None:
        self.diagnostic_service = DiagnosticWorkupService()
        self.post_negative_service = PostNegativeBiopsyFollowupService()
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
            (latest_assessment or {}).get("state")
            or (patient.get("latest_assessment") or {}).get("state")
            or effective_state
            or (patient.get("prior_history") or {}).get("current_state")
        )
        if not flags.get("ENABLE_DIAGNOSTIC_BIOPSY_COPILOT"):
            return self._disabled_bundle(state=latest_state, runtime_mode=runtime_mode, status="disabled")
        if latest_state not in DIAGNOSTIC_VERTICAL_STATES:
            return self._disabled_bundle(state=latest_state, runtime_mode=runtime_mode, status="not_applicable")

        runtime_patient = build_runtime_patient(patient, longitudinal_bundle)
        payload = build_runtime_payload(
            runtime_patient,
            latest_assessment,
            effective_state=latest_state,
            overlay_keys={
                "psa",
                "psad",
                "pirads_score",
                "dre_suspicious",
                "family_history_positive",
                "germline_risk_mutation",
                "phi_score",
                "prior_biopsy_count",
                "years_since_negative_biopsy",
                "persistent_lesion_signal",
            },
        )
        module_result = self._evaluate_rule_based(latest_state, payload)
        requirements = decision_input_requirements or build_decision_input_requirements(
            runtime_patient,
            effective_state=latest_state,
            effective_management_track=effective_management_track or "diagnostic_surveillance",
            latest_assessment=latest_assessment or patient.get("latest_assessment"),
            next_best_action=(longitudinal_bundle or {}).get("next_best_action") or {},
        )
        blocking_inputs = build_blocking_input_groups(requirements)
        diagnostic_track = self._diagnostic_track(latest_state, module_result, payload)
        guideline_basis = guideline_basis_from_result(module_result)
        histopathology_summary = build_histopathology_summary(payload)
        rule_based_recommendation = self._build_rule_based_recommendation(module_result, diagnostic_track)
        ai_advisory_overlay = self._build_ai_overlay(
            runtime_mode=runtime_mode,
            module_result=module_result,
            diagnostic_track=diagnostic_track,
            blocking_inputs=blocking_inputs,
        )
        qa_validation = run_vertical_qa_validation(
            self.qa_agent,
            runtime_patient,
            reconciled_state=latest_state,
            action=ai_advisory_overlay.get("recommended_action") or rule_based_recommendation.get("recommended_action"),
            evidence_basis=guideline_basis,
            agent_id="diagnostic_biopsy_copilot_overlay",
            category="diagnostic",
            confidence_score=68.0 if ai_advisory_overlay.get("available") else 50.0,
        )
        confidence = build_model_like_confidence(
            self.confidence_scorer,
            runtime_patient,
            action=ai_advisory_overlay.get("recommended_action") or rule_based_recommendation.get("recommended_action"),
            guideline_result=module_result,
            historical_calibration_score=58.0,
        )
        final_presented_recommendation = build_final_presented_recommendation(
            runtime_mode=runtime_mode,
            rule_based_recommendation=rule_based_recommendation,
            ai_overlay=ai_advisory_overlay,
            qa_validation=qa_validation,
            blocking_groups=blocking_inputs,
            advisory_source="diagnostic_biopsy_copilot_advisory",
            rationale="Overlay AI presentado porque pasó QA, no hay blockers duros y la recomendación sigue siendo concordante con la ruta diagnóstica primaria.",
        )
        status = resolve_vertical_status(
            runtime_mode=runtime_mode,
            qa_validation=qa_validation,
            blocking_groups=blocking_inputs,
            ai_overlay=ai_advisory_overlay,
        )
        blocked_by_overlay = build_blocked_by_overlay(blocking_groups=blocking_inputs)
        decision_delta_since_last_visit = build_decision_delta_since_last_visit(
            runtime_patient,
            effective_state=latest_state,
            phenotype_state=latest_state,
            rule_based_recommendation=rule_based_recommendation,
            final_presented_recommendation=final_presented_recommendation,
            blocking_groups=blocking_inputs,
            blocked_by_overlay=blocked_by_overlay,
        )
        evidence_basis_current_visit = build_evidence_basis_current_visit(
            guideline_basis,
            rule_based_recommendation,
            decision_delta_since_last_visit,
        )
        return {
            "enabled": True,
            "available": True,
            "show_card": True,
            "service_id": self.service_id,
            "status": status,
            "state_family": latest_state,
            "raw_state": latest_state,
            "runtime_mode": runtime_mode,
            "rule_based_source_of_truth": True,
            "effective_state": latest_state,
            "effective_management_track": effective_management_track or ("rebiopsy_surveillance" if latest_state == "post_negative_biopsy_followup" else "diagnostic_surveillance"),
            "histopathology_summary": histopathology_summary,
            "diagnostic_track": diagnostic_track,
            "biopsy_readiness": self._biopsy_readiness(module_result, blocking_inputs),
            "reopen_signal_after_negative_biopsy": latest_state == "post_negative_biopsy_followup" and diagnostic_track == "reopen_after_negative_biopsy",
            "mri_quality_or_repeat_need": self._mri_quality_need(module_result),
            "risk_refiners": self._risk_refiners(payload, module_result),
            "metastatic_composition_summary": build_shared_metastatic_summary(payload),
            "rule_based_recommendation": rule_based_recommendation,
            "ai_advisory_overlay": ai_advisory_overlay,
            "final_presented_recommendation": final_presented_recommendation,
            "blocking_inputs": blocking_inputs,
            "blocked_by_overlay": blocked_by_overlay,
            "qa_validation": qa_validation,
            "guideline_basis": guideline_basis,
            "evidence_basis_current_visit": evidence_basis_current_visit,
            "confidence": confidence,
            "why_changed_today": self._why_changed_today(payload, diagnostic_track),
            "decision_delta_since_last_visit": decision_delta_since_last_visit,
            "diagnostic_schedule_overlay": self._schedule_overlay(diagnostic_track, blocking_inputs),
            "trigger_event": trigger_event or "longitudinal_refresh",
        }

    def _disabled_bundle(self, *, state: str, runtime_mode: str, status: str) -> dict[str, Any]:
        return {
            "enabled": False,
            "available": False,
            "show_card": False,
            "status": status,
            "state_family": state,
            "runtime_mode": runtime_mode,
            "rule_based_source_of_truth": True,
            "effective_management_track": "",
            "histopathology_summary": "",
            "diagnostic_track": "",
            "biopsy_readiness": {},
            "reopen_signal_after_negative_biopsy": False,
            "mri_quality_or_repeat_need": {},
            "risk_refiners": [],
            "metastatic_composition_summary": {"available": False},
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
            "diagnostic_schedule_overlay": {},
        }

    def _evaluate_rule_based(self, state_family: str, payload: dict[str, Any]) -> dict[str, Any]:
        if state_family == "post_negative_biopsy_followup":
            return self.post_negative_service.evaluate(payload)
        return self.diagnostic_service.evaluate(payload)

    def _diagnostic_track(self, state_family: str, module_result: dict[str, Any], payload: dict[str, Any]) -> str:
        action = normalize_text((module_result.get("nccn_primary") or {}).get("recommendation")).lower()
        if state_family == "post_negative_biopsy_followup":
            if "biops" in action or "reabr" in action:
                return "reopen_after_negative_biopsy"
            return "low_suspicion_surveillance"
        if normalize_text(payload.get("germline_risk_mutation")) in {"1", "true", "True"} or safe_float(payload.get("phi_score")):
            if "biops" not in action:
                return "hereditary_or_precision_refinement"
        if "biops" in action:
            return "targeted_biopsy_ready"
        if "mri" in action or "resonancia" in action:
            return "repeat_mri_then_decide"
        return "low_suspicion_surveillance"

    def _build_rule_based_recommendation(self, module_result: dict[str, Any], diagnostic_track: str) -> dict[str, Any]:
        nccn = dict(module_result.get("nccn_primary") or {})
        structured = dict((module_result.get("report_sections") or {}).get("structured_summary") or {})
        rationale_bits = list(structured.get("fundamentos_personalizados") or [])[:3]
        if diagnostic_track == "reopen_after_negative_biopsy":
            rationale_bits.append("Una biopsia benigna previa no apaga la sospecha si MRI, PSAD o DRE la reabren.")
        return {
            "source": "rule_based_primary",
            "recommended_action": normalize_text(nccn.get("recommendation") or structured.get("trayectoria_recomendada")),
            "recommendation_family": "diagnostic",
            "rationale": " ".join(normalize_text(item) for item in rationale_bits if normalize_text(item)) or "La capa rule-based sigue siendo la fuente primaria de verdad clínica.",
            "guideline_basis": guideline_basis_from_result(module_result),
        }

    def _build_ai_overlay(
        self,
        *,
        runtime_mode: str,
        module_result: dict[str, Any],
        diagnostic_track: str,
        blocking_inputs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        rule_action = normalize_text((module_result.get("nccn_primary") or {}).get("recommendation"))
        if not rule_action:
            return {
                "available": False,
                "status": "unavailable",
                "recommended_action": "",
                "concordance_label": "rule_only",
                "shadow_reasons": ["No hay ruta diagnóstica estructurada disponible todavía."],
            }
        if diagnostic_track == "reopen_after_negative_biopsy":
            recommended_action = "Reabrir estudio diagnóstico con MRI de alta calidad y nueva biopsia dirigida si se confirma la señal"
        elif diagnostic_track == "repeat_mri_then_decide":
            recommended_action = "Repetir MRI de alta calidad antes de cerrar la decisión de biopsia"
        elif diagnostic_track == "hereditary_or_precision_refinement":
            recommended_action = "Completar refinadores hereditarios o prebiopsia antes de decidir la siguiente intervención"
        else:
            recommended_action = rule_action
        hard_blocked = any(group.get("required_fields") for group in blocking_inputs)
        concordance = _concordance_label(rule_action, recommended_action)
        status = "shadow-blocked" if hard_blocked else "advisory_candidate" if runtime_mode == "advisory" and concordance != "discordant" else "shadow"
        return {
            "available": True,
            "status": status,
            "recommended_action": recommended_action,
            "recommendation_family": "diagnostic",
            "concordance_label": concordance,
            "shadow_reasons": [
                "La recomendación AI permanece en shadow hasta que QA apruebe y no existan blockers duros."
                if runtime_mode == "shadow"
                else "La recomendación AI solo puede presentarse si sigue siendo concordante con la ruta primaria."
            ],
        }

    def _biopsy_readiness(self, module_result: dict[str, Any], blocking_inputs: list[dict[str, Any]]) -> dict[str, Any]:
        action = normalize_text((module_result.get("nccn_primary") or {}).get("recommendation")).lower()
        return {
            "ready": "biops" in action and not any(group.get("required_fields") for group in blocking_inputs),
            "reason": normalize_text((module_result.get("nccn_primary") or {}).get("label")),
        }

    def _mri_quality_need(self, module_result: dict[str, Any]) -> dict[str, Any]:
        treatments = list(module_result.get("eligible_treatments") or [])
        repeat_needed = any("resonancia" in normalize_text(item.get("name")).lower() for item in treatments)
        return {
            "repeat_needed": repeat_needed,
            "reason": "MRI de alta calidad antes de cerrar la decisión." if repeat_needed else "",
        }

    def _risk_refiners(self, payload: dict[str, Any], module_result: dict[str, Any]) -> list[str]:
        refiners = []
        if safe_float(payload.get("psad")) is not None:
            refiners.append("PSAD")
        if normalize_text(payload.get("pirads_score")):
            refiners.append("PI-RADS")
        if normalize_text(payload.get("family_history_positive")) in {"1", "true", "True"}:
            refiners.append("riesgo hereditario")
        if safe_float(payload.get("phi_score")) is not None:
            refiners.append("biomarcador prebiopsia")
        if bool(((module_result.get("report_sections") or {}).get("validated_algorithms") or {}).get("erspc_ready")):
            refiners.append("ERSPC ready")
        return refiners

    def _why_changed_today(self, payload: dict[str, Any], diagnostic_track: str) -> list[str]:
        notes = []
        psa = safe_float(payload.get("psa"))
        psad = safe_float(payload.get("psad"))
        if psa is not None:
            notes.append(f"PSA actual {psa:g} ng/mL.")
        if psad is not None:
            notes.append(f"PSAD actual {psad:g}.")
        if normalize_text(payload.get("pirads_score")):
            notes.append(f"PI-RADS {payload.get('pirads_score')}.")
        if normalize_text(payload.get("dre_suspicious")) in {"1", "true", "True"}:
            notes.append("DRE sospechoso.")
        notes.append(f"Track diagnóstico: {diagnostic_track}.")
        return notes[:5]

    def _schedule_overlay(self, diagnostic_track: str, blocking_inputs: list[dict[str, Any]]) -> dict[str, Any]:
        if diagnostic_track == "targeted_biopsy_ready":
            cadence = ["Biopsia dirigida + sistemática", "MRI de soporte si cambia targeting"]
            primary_intent = "Cerrar confirmación histológica"
        elif diagnostic_track == "reopen_after_negative_biopsy":
            cadence = ["MRI de reapertura", "Nueva biopsia solo si la señal persiste"]
            primary_intent = "Reabrir estudio tras biopsia benigna"
        else:
            cadence = ["PSA/PSAD estructurados", "MRI o DRE según señal clínica"]
            primary_intent = "Evitar biopsias innecesarias sin perder sospecha relevante"
        blockers = [group.get("group_label") for group in blocking_inputs if group.get("required_fields")]
        return {
            "schedule_primary_intent": primary_intent,
            "cadence_adjustment_reasons": cadence + blockers[:2],
            "recommended_events": cadence[:3],
        }


def build_diagnostic_biopsy_bundle(
    patient: dict[str, Any],
    *,
    effective_state: str = "",
    effective_management_track: str = "",
    latest_assessment: dict[str, Any] | None = None,
    longitudinal_bundle: dict[str, Any] | None = None,
    decision_input_requirements: dict[str, Any] | None = None,
    trigger_event: str = "",
) -> dict[str, Any]:
    return DiagnosticBiopsyCopilotService().evaluate(
        patient,
        effective_state=effective_state,
        effective_management_track=effective_management_track,
        latest_assessment=latest_assessment,
        longitudinal_bundle=longitudinal_bundle,
        decision_input_requirements=decision_input_requirements,
        trigger_event=trigger_event,
    )


__all__ = [
    "DiagnosticBiopsyCopilotService",
    "build_diagnostic_biopsy_bundle",
    "DIAGNOSTIC_VERTICAL_STATES",
]
