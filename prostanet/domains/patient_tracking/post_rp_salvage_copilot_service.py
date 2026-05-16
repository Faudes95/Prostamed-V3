from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from prostanet.agents.contracts import AgentOutput, AgentRecommendation
from prostanet.agents.quality_assurance_agent import QualityAssuranceAgent
from prostanet.ai.config import get_ai_config
from prostanet.domains.patient_tracking.decision_input_requirements_engine import (
    build_decision_input_requirements,
)
from prostanet.domains.patient_tracking.event_graph import (
    merge_record_into_assessment_payload,
)
from prostanet.domains.patient_tracking.prognostic_impact import (
    build_prognostic_impact_bundle,
)
from prostanet.domains.patient_tracking.post_rp_salvage_intensification_builder import (
    build_post_rp_salvage_intensification_profile,
)
from prostanet.domains.patient_tracking.psma_imaging import (
    build_psma_decision_impact,
    build_psma_structured_profile,
    build_psma_structured_profile_from_payload,
)
from prostanet.domains.patient_tracking.reconciled_state import (
    derive_post_prostatectomy_course,
    derive_post_prostatectomy_truth,
)
from prostanet.domains.patient_tracking.risk_tools import build_risk_tools_panel
from prostanet.domains.patient_tracking.vertical_runtime import (
    build_blocked_by_overlay,
    build_decision_delta_since_last_visit,
    build_evidence_basis_current_visit,
    build_histopathology_summary,
    build_shared_metastatic_summary,
    enrich_recommendation_with_metastatic_summary,
    prepend_metastatic_context,
)
from prostanet.domains.post_prostatectomy.service import PostProstatectomyService
from prostanet.domains.recurrence_bcr.service import RecurrenceBCRService
from prostanet.engine.confidence_scoring import ConfidenceScorer
from prostanet.shared.feature_flags import resolve_feature_flags


POST_RP_VERTICAL_STATES = {"post_prostatectomy", "recurrence_bcr"}
YES_VALUES = {"1", "true", "yes", "si", "sí"}
NO_VALUES = {"0", "false", "no"}


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No documentado", "Desconocido", "Desconocida")


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_for_compare(value: str) -> str:
    lowered = value.lower().strip()
    for token in (
        "de rescate",
        "y reestadificación dirigida",
        "post prostatectomía",
        "post prostatectomia",
        "temprana",
    ):
        lowered = lowered.replace(token, "")
    return lowered.replace(" ", "").replace("-", "")


def _has_post_rp_context(patient: dict[str, Any], *, post_rp_course: str = "") -> bool:
    if post_rp_course:
        return True
    if patient.get("surgery"):
        return True
    prior_state = _normalize_text((patient.get("prior_history") or {}).get("current_state"))
    if prior_state == "post_prostatectomy":
        return True
    latest_assessment = patient.get("latest_assessment") or {}
    if _normalize_text(latest_assessment.get("state")) == "post_prostatectomy":
        return True
    bcr = patient.get("bcr") or {}
    primary_treatment = _normalize_text(bcr.get("primary_treatment")).upper()
    if primary_treatment in {"RP", "POST_RP", "RADICAL PROSTATECTOMY", "PROSTATECTOMY"}:
        return True
    for source in (
        patient.get("baseline") or {},
        (patient.get("longitudinal_truth_snapshot") or {}).get("field_values") or {},
        latest_assessment.get("input_snapshot") or {},
        bcr,
    ):
        if not isinstance(source, dict):
            continue
        if str(source.get("prior_prostatectomy", "")).strip().lower() in YES_VALUES:
            return True
        if _is_present(source.get("rp_date")) or _is_present(source.get("prostatectomy_date")):
            return True
        if _is_present(source.get("pathologic_stage")) or _is_present(source.get("pathological_stage")):
            return True
        if _is_present(source.get("surgical_margin")) or _is_present(source.get("surgical_margin_status")):
            return True
    return False


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _parse_date(value: Any) -> datetime | None:
    if not _is_present(value):
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def _overlay_present_values(
    payload: dict[str, Any],
    *sources: dict[str, Any],
    keys: set[str],
) -> None:
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in keys:
            value = source.get(key)
            if _is_present(value):
                payload[key] = value


@dataclass
class PostRPSafetyGate:
    gate_key: str
    label: str
    status: str
    rationale: str
    failure_family: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PostRPSequenceCandidate:
    pathway_key: str
    label: str
    confidence: float
    blocked: bool = False
    blocked_by: list[str] = field(default_factory=list)
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PostRPSalvageCopilotService:
    service_id = "post_rp_salvage_copilot"

    def __init__(self) -> None:
        self.post_rp_service = PostProstatectomyService()
        self.recurrence_service = RecurrenceBCRService()
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
        latest_assessment_state = str(
            (latest_assessment or {}).get("state")
            or (patient.get("latest_assessment") or {}).get("state")
            or ""
        )
        state = str(
            latest_assessment_state
            if latest_assessment_state in POST_RP_VERTICAL_STATES
            else (
                effective_state
                or latest_assessment_state
                or (patient.get("prior_history") or {}).get("current_state")
                or ""
            )
        )
        runtime_patient = self._build_runtime_patient(patient, longitudinal_bundle)
        post_rp_course = derive_post_prostatectomy_course(runtime_patient)
        post_rp_applicable = _has_post_rp_context(runtime_patient, post_rp_course=post_rp_course)

        if not flags.get("ENABLE_POST_RP_SALVAGE_COPILOT"):
            return self._disabled_bundle(
                state=state,
                runtime_mode=runtime_mode,
                status="disabled",
                post_rp_course=post_rp_course,
            )
        if not post_rp_applicable:
            return self._disabled_bundle(
                state=state,
                runtime_mode=runtime_mode,
                status="not_applicable",
                post_rp_course=post_rp_course,
            )

        payload = self._build_payload(
            runtime_patient,
            latest_assessment,
            effective_state=state or "post_prostatectomy",
        )
        histopathology_summary = build_histopathology_summary(payload)
        psma_profile = (
            build_psma_structured_profile_from_payload(payload)
            if any(
                _is_present(payload.get(key))
                for key in (
                    "psma_pet_done",
                    "psma_positive",
                    "psma_stage_after_psma",
                    "psma_rads_score",
                    "psma_uptake_pattern",
                )
            )
            else dict(runtime_patient.get("psma_structured_profile") or build_psma_structured_profile(runtime_patient))
        )
        psma_impact = build_psma_decision_impact(
            psma_profile,
            state=state or "post_prostatectomy",
            management_track=effective_management_track,
            patient=runtime_patient,
        )
        intensification_profile = build_post_rp_salvage_intensification_profile(
            payload,
            psma_impact=psma_impact,
        )
        (
            resolved_state,
            resolved_track,
            salvage_window_status,
            salvage_window_reason,
        ) = self._resolve_context(
            state=state,
            post_rp_course=post_rp_course,
            payload=payload,
            psma_impact=psma_impact,
        )
        module_result = self._evaluate_rule_based(resolved_state, payload)
        requirements = dict(decision_input_requirements or {})
        if (
            not requirements
            or _normalize_text(requirements.get("effective_state")) != resolved_state
            or _normalize_text(requirements.get("effective_management_track")) != resolved_track
        ):
            # Recompute blockers after the post-RP copilot resolves the operative state.
            requirements = build_decision_input_requirements(
                runtime_patient,
                effective_state=resolved_state,
                effective_management_track=resolved_track,
                latest_assessment=latest_assessment or patient.get("latest_assessment"),
                next_best_action=(longitudinal_bundle or {}).get("next_best_action") or {},
            )
        blocking_inputs = self._build_blocking_input_groups(requirements)
        safety_gates = self._build_safety_gates(
            payload,
            resolved_state=resolved_state,
            post_rp_course=post_rp_course,
            salvage_window_status=salvage_window_status,
            psma_profile=psma_profile,
            psma_impact=psma_impact,
        )
        risk_tools_bundle = build_risk_tools_panel(
            patient=runtime_patient,
            state=resolved_state,
            raw_assessment=latest_assessment or patient.get("latest_assessment"),
            display_assessment={},
        )
        prognostic_bundle = build_prognostic_impact_bundle(
            patient=runtime_patient,
            state=resolved_state,
            management_track=resolved_track,
            raw_assessment=latest_assessment or patient.get("latest_assessment"),
            risk_tools_bundle=risk_tools_bundle,
            current_trial_profile=(longitudinal_bundle or {}).get("current_trial_comparable_profile", {}),
        )
        rule_based_recommendation = self._build_rule_based_recommendation(
            post_rp_course=post_rp_course,
            resolved_state=resolved_state,
            salvage_window_status=salvage_window_status,
            salvage_window_reason=salvage_window_reason,
            module_result=module_result,
            payload=payload,
            psma_impact=psma_impact,
            intensification_profile=intensification_profile,
        )
        metastatic_composition_summary = build_shared_metastatic_summary(payload)
        rule_based_recommendation = enrich_recommendation_with_metastatic_summary(
            rule_based_recommendation,
            metastatic_composition_summary,
        )
        restaging_strategy = self._build_restaging_strategy(
            salvage_window_status=salvage_window_status,
            psma_profile=psma_profile,
            psma_impact=psma_impact,
            payload=payload,
        )
        local_salvage_pathway = self._build_local_salvage_pathway(
            resolved_state=resolved_state,
            post_rp_course=post_rp_course,
            salvage_window_status=salvage_window_status,
            psma_impact=psma_impact,
            intensification_profile=intensification_profile,
        )
        sequence_candidates = self._build_sequence_candidates(
            post_rp_course=post_rp_course,
            salvage_window_status=salvage_window_status,
            local_salvage_pathway=local_salvage_pathway,
            safety_gates=safety_gates,
            psma_impact=psma_impact,
        )
        ai_advisory_overlay = self._build_ai_overlay(
            runtime_mode=runtime_mode,
            rule_based_recommendation=rule_based_recommendation,
            sequence_candidates=sequence_candidates,
            blocking_inputs=blocking_inputs,
            safety_gates=safety_gates,
        )
        qa_validation = self._run_qa_validation(
            runtime_patient,
            resolved_state=resolved_state,
            overlay=ai_advisory_overlay,
            rule_based_recommendation=rule_based_recommendation,
        )
        final_presented_recommendation = self._build_final_recommendation(
            runtime_mode=runtime_mode,
            rule_based_recommendation=rule_based_recommendation,
            ai_overlay=ai_advisory_overlay,
            qa_validation=qa_validation,
            blocking_groups=blocking_inputs,
        )
        final_presented_recommendation = enrich_recommendation_with_metastatic_summary(
            final_presented_recommendation,
            metastatic_composition_summary,
        )
        model_like_output = {
            "recommendations": [
                {
                    "action": ai_advisory_overlay.get("recommended_action")
                    or rule_based_recommendation.get("recommended_action"),
                }
            ],
            "metadata": {"historical_calibration_score": 62.0 if ai_advisory_overlay.get("available") else 50.0},
        }
        confidence = self.confidence_scorer.score(
            runtime_patient,
            agent_outputs=[model_like_output],
            guideline_result=module_result,
        )
        # Faubot 2026-04-25 (IX) — Pre-compute delta de gates pivotal antes
        # de _build_why_changed_today para incluir narrativa clínica del delta.
        from prostanet.shared.pivotal_gate_delta import (
            compute_pivotal_gates_delta,
            extract_previous_pivotal_gates,
        )
        _current_pivotal_gates = list(module_result.get("pivotal_contraindication_gates") or [])
        _previous_pivotal_gates = extract_previous_pivotal_gates(latest_assessment)
        _pivotal_gates_delta_pre = compute_pivotal_gates_delta(
            _current_pivotal_gates, _previous_pivotal_gates
        )
        why_changed_today = self._build_why_changed_today(
            payload,
            post_rp_course=post_rp_course,
            salvage_window_status=salvage_window_status,
            salvage_window_reason=salvage_window_reason,
            psma_impact=psma_impact,
            intensification_profile=intensification_profile,
            pivotal_gates_delta=_pivotal_gates_delta_pre,
        )
        why_changed_today = prepend_metastatic_context(why_changed_today, metastatic_composition_summary)
        post_rp_schedule_overlay = self._build_schedule_overlay(
            resolved_state=resolved_state,
            post_rp_course=post_rp_course,
            salvage_window_status=salvage_window_status,
            blocking_groups=blocking_inputs,
            payload=payload,
            intensification_profile=intensification_profile,
        )
        status = self._resolve_status(
            runtime_mode=runtime_mode,
            qa_validation=qa_validation,
            blocking_groups=blocking_inputs,
            ai_overlay=ai_advisory_overlay,
        )
        blocked_by_overlay = build_blocked_by_overlay(
            blocking_groups=blocking_inputs,
            safety_gates=safety_gates,
        )
        decision_delta_since_last_visit = build_decision_delta_since_last_visit(
            runtime_patient,
            effective_state=resolved_state,
            phenotype_state=resolved_state,
            rule_based_recommendation=rule_based_recommendation,
            final_presented_recommendation=final_presented_recommendation,
            blocking_groups=blocking_inputs,
            blocked_by_overlay=blocked_by_overlay,
            current_pivotal_gates=_current_pivotal_gates,
            previous_pivotal_gates=_previous_pivotal_gates,
        )
        guideline_basis = self._guideline_basis(module_result)
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
            "state_family": resolved_state,
            "raw_state": state,
            "runtime_mode": runtime_mode,
            "rule_based_source_of_truth": True,
            "post_prostatectomy_course": post_rp_course,
            "effective_state": resolved_state,
            "effective_management_track": resolved_track,
            "histopathology_summary": histopathology_summary,
            "salvage_window_status": salvage_window_status,
            "salvage_window_reason": salvage_window_reason,
            "metastatic_composition_summary": metastatic_composition_summary,
            "rule_based_recommendation": rule_based_recommendation,
            "ai_advisory_overlay": ai_advisory_overlay,
            "final_presented_recommendation": final_presented_recommendation,
            "restaging_strategy": restaging_strategy,
            "local_salvage_pathway": local_salvage_pathway,
            "sequence_candidates": sequence_candidates,
            "blocking_inputs": blocking_inputs,
            "blocked_by_overlay": blocked_by_overlay,
            "safety_gates": safety_gates,
            "qa_validation": qa_validation,
            "guideline_basis": guideline_basis,
            "evidence_basis_current_visit": evidence_basis_current_visit,
            "confidence": confidence,
            "why_changed_today": why_changed_today,
            "decision_delta_since_last_visit": decision_delta_since_last_visit,
            "post_rp_schedule_overlay": post_rp_schedule_overlay,
            "risk_tools_summary": self._risk_tools_summary(risk_tools_bundle),
            "prognostic_summary": {
                "modifier_keys": [
                    item.get("modifier_key")
                    for item in (prognostic_bundle.get("prognostic_modifiers") or [])
                    if item.get("modifier_key")
                ][:6],
                "recommended_actions": list(prognostic_bundle.get("recommended_actions") or [])[:4],
            },
            "psma_profile_summary": {
                "available": bool(psma_profile.get("available")),
                "structured_complete": bool(psma_profile.get("structured_complete")),
                "clinical_pattern": psma_profile.get("clinical_pattern", ""),
                "psma_stage_after_psma": psma_profile.get("psma_stage_after_psma", ""),
                "psma_negative_dominant_lesions": bool(psma_profile.get("psma_negative_dominant_lesions")),
            },
            "post_rp_salvage_intensification_profile": intensification_profile,
            "trigger_event": trigger_event or "longitudinal_refresh",
            # Faubot 2026-04-24 (III) — propagar trazabilidad de gates pivotal
            # y not_recommended desde recurrence_bcr (PRESTO triplet con
            # abiraterona) y post_prostatectomy (sin gates pero campo neutro
            # para uniformidad de contrato downstream).
            "pivotal_contraindication_gates": list(
                module_result.get("pivotal_contraindication_gates") or []
            ),
            "not_recommended": list(module_result.get("not_recommended") or []),
        }

    def _disabled_bundle(
        self,
        *,
        state: str,
        runtime_mode: str,
        status: str,
        post_rp_course: str,
    ) -> dict[str, Any]:
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
            "metastatic_composition_summary": {"available": False},
            "post_prostatectomy_course": post_rp_course,
            "salvage_window_status": "closed",
            "salvage_window_reason": "",
            "rule_based_recommendation": {},
            "ai_advisory_overlay": {"available": False, "status": status},
            "final_presented_recommendation": {},
            "restaging_strategy": {},
            "local_salvage_pathway": {},
            "sequence_candidates": [],
            "blocking_inputs": [],
            "blocked_by_overlay": [],
            "safety_gates": [],
            "qa_validation": {"approved": False, "flags": [], "missing_data_alerts": []},
            "guideline_basis": [],
            "evidence_basis_current_visit": [],
            "confidence": {"composite_score": 0.0, "components": {}, "weights_used": {}},
            "why_changed_today": [],
            "decision_delta_since_last_visit": {"available": False},
            "post_rp_schedule_overlay": {},
            "risk_tools_summary": {},
            "prognostic_summary": {"modifier_keys": [], "recommended_actions": []},
            # Faubot 2026-04-24 (III) — paridad con bundle activo.
            "pivotal_contraindication_gates": [],
            "not_recommended": [],
        }

    def _build_runtime_patient(
        self,
        patient: dict[str, Any],
        longitudinal_bundle: dict[str, Any] | None,
    ) -> dict[str, Any]:
        runtime_patient = dict(patient or {})
        if not runtime_patient.get("psma_structured_profile"):
            runtime_patient["psma_structured_profile"] = build_psma_structured_profile(runtime_patient)
        if longitudinal_bundle and longitudinal_bundle.get("longitudinal_truth_snapshot"):
            runtime_patient["longitudinal_truth_snapshot"] = dict(longitudinal_bundle.get("longitudinal_truth_snapshot") or {})
        return runtime_patient

    def _build_payload(
        self,
        patient: dict[str, Any],
        latest_assessment: dict[str, Any] | None,
        *,
        effective_state: str,
    ) -> dict[str, Any]:
        assessment_input = dict(((latest_assessment or patient.get("latest_assessment") or {}).get("input_snapshot") or {}))
        payload = merge_record_into_assessment_payload(assessment_input, patient)
        truth_values = dict((patient.get("longitudinal_truth_snapshot") or {}).get("field_values") or {})
        latest_snapshot = dict(patient.get("latest_signal_snapshot") or {})
        latest_followup = dict((patient.get("follow_ups") or [{}])[-1] or {})
        latest_visit_payload = dict(((latest_followup.get("visit_bundle") or {}).get("payload")) or {})
        bcr = dict(patient.get("bcr") or {})
        surgery = dict(patient.get("surgery") or {})
        baseline = dict(patient.get("baseline") or {})
        genomics = dict(patient.get("genomics") or patient.get("genomic_profile") or {})
        for source in (
            baseline,
            truth_values,
            latest_snapshot,
            latest_followup,
            latest_visit_payload,
            bcr,
            surgery,
            genomics,
        ):
            if not isinstance(source, dict):
                continue
            for key, value in source.items():
                if _is_present(value) and not _is_present(payload.get(key)):
                    payload[key] = value

        _overlay_present_values(
            payload,
            truth_values,
            latest_snapshot,
            latest_followup,
            latest_visit_payload,
            bcr,
            surgery,
            keys={
                "psa",
                "psa_current",
                "psa_postop",
                "psadt_months",
                "salvage_local_feasible",
                "conventional_imaging_status",
                "psma_pet_done",
                "psma_positive",
                "psma_stage_after_psma",
                "psma_uptake_pattern",
                "psma_rads_score",
                "psma_negative_dominant_lesions",
                "psma_radioligand",
                "rp_date",
                "prostatectomy_date",
                "pathologic_stage",
                "surgical_margin",
                "decipher_risk",
            },
        )

        if not _is_present(payload.get("psa")):
            payload["psa"] = payload.get("psa_postop") or payload.get("psa_current") or bcr.get("bcr_psa")
        if not _is_present(payload.get("psa_postop")):
            payload["psa_postop"] = bcr.get("bcr_psa") or latest_followup.get("psa_postop") or latest_followup.get("psa_current")
        if not _is_present(payload.get("psa_current")):
            payload["psa_current"] = bcr.get("bcr_psa") or latest_followup.get("psa_current") or payload.get("psa")
        post_rp_truth = derive_post_prostatectomy_truth(patient) if _has_post_rp_context(patient) else {}
        if not _is_present(payload.get("psa_current")) and _is_present(post_rp_truth.get("psa_current")):
            payload["psa_current"] = post_rp_truth.get("psa_current")
        if not _is_present(payload.get("psa_postop")) and _is_present(post_rp_truth.get("psa_current")):
            payload["psa_postop"] = post_rp_truth.get("psa_current")
        if not _is_present(payload.get("psa")):
            payload["psa"] = payload.get("psa_postop") or payload.get("psa_current") or post_rp_truth.get("psa_current")
        if not _is_present(payload.get("psadt_months")):
            payload["psadt_months"] = post_rp_truth.get("psadt_months") or bcr.get("psadt_at_bcr")
        if post_rp_truth:
            payload["post_rp_bcr_truth"] = post_rp_truth
        if not _is_present(payload.get("rp_date")):
            payload["rp_date"] = surgery.get("surgery_date") or (patient.get("prior_history") or {}).get("rp_date")
        if not _is_present(payload.get("prostatectomy_date")):
            payload["prostatectomy_date"] = payload.get("rp_date")
        if not _is_present(payload.get("surgical_margin")):
            payload["surgical_margin"] = surgery.get("surgical_margin_status")
        if not _is_present(payload.get("decipher_risk")):
            payload["decipher_risk"] = genomics.get("decipher_risk")
        payload["prior_prostatectomy"] = 1 if _has_post_rp_context(patient) else payload.get("prior_prostatectomy", 0)
        payload["effective_state"] = effective_state
        surgery_date = _parse_date(payload.get("rp_date") or payload.get("prostatectomy_date"))
        bcr_date = _parse_date(bcr.get("bcr_date"))
        if surgery_date and bcr_date and not _is_present(payload.get("time_to_recurrence_months")):
            payload["time_to_recurrence_months"] = round(max((bcr_date - surgery_date).days, 0) / 30.4, 1)
        psma_profile = dict(patient.get("psma_structured_profile") or {})
        if psma_profile:
            payload["psma_pet_done"] = payload.get("psma_pet_done") or ("1" if psma_profile.get("available") else "0")
            payload["psma_positive"] = payload.get("psma_positive") or ("1" if psma_profile.get("psma_positive") else "0")
            payload["psma_stage_after_psma"] = payload.get("psma_stage_after_psma") or psma_profile.get("psma_stage_after_psma")
            payload["psma_uptake_pattern"] = payload.get("psma_uptake_pattern") or psma_profile.get("psma_uptake_pattern")
            payload["psma_rads_score"] = payload.get("psma_rads_score") or psma_profile.get("psma_rads_score")
            if payload.get("psma_negative_dominant_lesions") in (None, ""):
                payload["psma_negative_dominant_lesions"] = 1 if psma_profile.get("psma_negative_dominant_lesions") else 0
            payload["imaging_modality"] = payload.get("imaging_modality") or ("PSMA-PET" if psma_profile.get("available") else payload.get("imaging_modality"))
        payload["conventional_imaging_status"] = _normalize_text(payload.get("conventional_imaging_status")).upper() or "NOT_RESTAGED"
        return payload

    def _resolve_context(
        self,
        *,
        state: str,
        post_rp_course: str,
        payload: dict[str, Any],
        psma_impact: dict[str, Any],
    ) -> tuple[str, str, str, str]:
        latest_psa = _safe_float(payload.get("psa_current") or payload.get("psa_postop") or payload.get("psa"))
        psadt = _safe_float(payload.get("psadt_months"))
        salvage_value = _normalize_text(payload.get("salvage_local_feasible")).lower()
        salvage_known = salvage_value in YES_VALUES | NO_VALUES
        salvage_feasible = salvage_value in YES_VALUES
        psma_done = _normalize_text(payload.get("psma_pet_done")).lower() in YES_VALUES
        psma_stage = _normalize_text(payload.get("psma_stage_after_psma"))
        conventional_stage = _normalize_text(payload.get("conventional_imaging_status")).upper()
        clinical_pattern = _normalize_text(psma_impact.get("clinical_pattern")).lower()
        disseminated_pattern = clinical_pattern == "diseminado"
        oligometastatic_pattern = clinical_pattern == "oligometastatic"
        conventional_systemic = conventional_stage in {"M1", "M1B", "M1C"}
        psma_systemic = psma_stage in {"M1b", "M1c"}
        systemic_redirect = disseminated_pattern or conventional_systemic or psma_systemic

        if post_rp_course == "stable_surveillance":
            return (
                "post_prostatectomy",
                "post_rp",
                "closed",
                "El PSA posoperatorio sigue sin patrón suficiente de recurrencia; la ruta dominante sigue siendo vigilancia post-RP.",
            )

        effective_state = "recurrence_bcr" if state == "recurrence_bcr" or post_rp_course == "true_bcr" else "post_prostatectomy"

        if systemic_redirect:
            return (
                "recurrence_bcr",
                "systemic_surveillance",
                "redirect_systemic",
                "La imagen estructurada ya sugiere patrón no compatible con rescate local aislado; conviene redirigir fuera del salvage exclusivamente local.",
            )
        if oligometastatic_pattern and psma_done:
            return (
                "recurrence_bcr",
                "salvage",
                "open",
                "La PSMA de bajo burden mantiene visible una ruta MDT/salvage multimodal y no obliga todavía a cerrar la ventana local.",
            )

        missing_for_window = []
        if post_rp_course == "persistent_psa":
            if psadt is None:
                missing_for_window.append("PSADT")
            if not salvage_known:
                missing_for_window.append("factibilidad local")
            if missing_for_window:
                return (
                    "post_prostatectomy",
                    "salvage_evaluation",
                    "pending_inputs",
                    f"Persisten vacíos decisivos para cerrar la ventana de salvage: {', '.join(missing_for_window)}.",
                )
            # EPIC 28.8 (GodiBot G46 HIGH) — AUA-ASTRO 2024 + EAU 2026 §5.2 require
            # TWO PSA values ≥0.2 (confirmatory) separated ≥3 weeks. A single
            # PSA ≥0.2 may reflect lab variability, hemorrhage transient, or
            # processing artifact — not diagnostic of BCR alone.
            # Pre-EPIC28: `latest_psa >= 0.2` alone promoted to BCR → premature
            # salvage planning.
            # EPIC 29.8 (GodiBot G54 MOD) — añadir cota superior 180 días entre
            # las dos PSA confirmatorias. Pacientes con >6 meses entre PSAs
            # representan una trayectoria diferente (persistentemente elevada
            # vs nuevo episodio bioquímico) y requieren contexto temporal
            # distinto (re-evaluación de adherencia, posible nueva línea
            # sistémica, no necesariamente salvage local).
            # Accept promotion if: (a) state already recurrence_bcr (upstream
            # confirmed), OR (b) `bcr_confirmed_by_two_psa=True` explicit flag,
            # OR (c) ≥2 PSA values in psa_history both ≥0.2 separated 21-180 días.
            bcr_two_psa_confirmed = bool(safe_state_payload.get("bcr_confirmed_by_two_psa"))
            psa_history = safe_state_payload.get("psa_history") or []
            confirmatory_psa_count = 0
            bcr_window_audit: dict | None = None
            if not bcr_two_psa_confirmed and isinstance(psa_history, list):
                # Count consecutive PSAs ≥0.2 (most recent first)
                elevated = [
                    (p.get("psa_value") or p.get("value"), p.get("sample_date") or p.get("date"))
                    for p in psa_history
                    if isinstance(p, dict)
                    and (p.get("psa_value") or p.get("value")) is not None
                ]
                from datetime import date as _date_e28
                try:
                    elevated_dates = [
                        (_date_e28.fromisoformat(str(d)[:10]), float(v))
                        for v, d in elevated if d and v is not None
                    ]
                    elevated_dates.sort(key=lambda x: x[0], reverse=True)
                    if len(elevated_dates) >= 2:
                        v1, d1 = elevated_dates[0][1], elevated_dates[0][0]
                        v2, d2 = elevated_dates[1][1], elevated_dates[1][0]
                        gap_days = (d1 - d2).days
                        if v1 >= 0.2 and v2 >= 0.2 and 21 <= gap_days <= 180:
                            bcr_two_psa_confirmed = True
                            confirmatory_psa_count = 2
                        elif v1 >= 0.2 and v2 >= 0.2 and gap_days > 180:
                            # Persistently elevated > 6 months → trayectoria
                            # distinta. NO promover automáticamente; surfacear
                            # señal de auditoría para downstream consumers.
                            bcr_window_audit = {
                                "status": "psa_window_exceeded",
                                "gap_days": gap_days,
                                "max_window_days": 180,
                                "rationale": (
                                    "Dos PSAs ≥0.2 pero separados > 180 días "
                                    "sugiere persistencia bioquímica de larga "
                                    "data, no episodio nuevo de salvage. "
                                    "Re-evaluar adherencia ADT y contexto sistémico."
                                ),
                                "recommended_action": "obtain_recent_psa_within_window",
                            }
                except Exception:
                    pass
            # Persist audit for downstream telemetry / UI (no-op if None)
            if bcr_window_audit is not None:
                try:
                    safe_state_payload.setdefault("audit", {})["bcr_psa_window"] = bcr_window_audit
                except Exception:
                    pass
            promote_to_bcr = (
                effective_state == "recurrence_bcr"
                or bcr_two_psa_confirmed
            )
            if salvage_feasible and not psma_done and promote_to_bcr:
                return (
                    "recurrence_bcr",
                    "salvage",
                    "open_pending_restaging",
                    "El rescate temprano sigue siendo plausible, pero falta imagen dirigida para afinar extensión y factibilidad real.",
                )
            if salvage_feasible and promote_to_bcr:
                return (
                    "recurrence_bcr",
                    "salvage",
                    "open",
                    "El PSA persistente mantiene una ventana de salvage local todavía plausible y debe acelerarse la evaluación temprana.",
                )
            if salvage_feasible:
                return (
                    "post_prostatectomy",
                    "salvage_evaluation",
                    "open",
                    "El PSA persistente sigue en evaluación temprana y todavía no cumple un umbral operativo suficiente para reclasificarlo como recurrencia bioquímica.",
                )
            return (
                "recurrence_bcr",
                "systemic_surveillance",
                "closed",
                "La factibilidad de salvage local ya no está documentada como viable y la estrategia debe redefinirse fuera de una vía curativa exclusivamente local.",
            )

        missing_for_window = []
        if psadt is None:
            missing_for_window.append("PSADT")
        if not salvage_known:
            missing_for_window.append("factibilidad local")
        if missing_for_window:
            return (
                "recurrence_bcr",
                "salvage",
                "pending_inputs",
                f"La recaída bioquímica ya es operativa, pero faltan datos para decidir si la ventana de salvage sigue abierta: {', '.join(missing_for_window)}.",
            )
        if salvage_feasible and not psma_done:
            return (
                "recurrence_bcr",
                "salvage",
                "open_pending_restaging",
                "La BCR verdadera mantiene opción de rescate local, aunque falta reestadificación dirigida para cerrarlo con confianza.",
            )
        if salvage_feasible:
            return (
                "recurrence_bcr",
                "salvage",
                "open",
                "La BCR verdadera conserva una ventana de salvage local visible con intención aún potencialmente curativa.",
            )
        return (
            "recurrence_bcr",
            "systemic_surveillance",
            "closed",
            "La ventana de salvage local ya no se sostiene como ruta dominante con la información acumulada actual.",
        )

    def _evaluate_rule_based(self, resolved_state: str, payload: dict[str, Any]) -> dict[str, Any]:
        if resolved_state == "recurrence_bcr":
            return self.recurrence_service.evaluate(payload)
        return self.post_rp_service.evaluate(payload)

    def _guideline_basis(self, module_result: dict[str, Any]) -> list[str]:
        basis = []
        primary = dict(module_result.get("nccn_primary") or {})
        if primary:
            basis.append(f"{primary.get('guideline', 'NCCN')} {primary.get('version', '')}: {primary.get('label', '')}".strip(": "))
        eau = dict(module_result.get("eau_comparison") or {})
        if eau:
            basis.append(f"{eau.get('guideline', 'EAU')} {eau.get('version', '')}: {eau.get('label', '')}".strip(": "))
        for item in module_result.get("supportive_evidence_context") or []:
            text = _normalize_text(item)
            if text and text not in basis:
                basis.append(text)
        return basis[:8]

    def _rule_based_title(
        self,
        *,
        resolved_state: str,
        post_rp_course: str,
        salvage_window_status: str,
    ) -> str:
        if resolved_state == "post_prostatectomy" and post_rp_course == "stable_surveillance":
            return "Mantener vigilancia post prostatectomía y control bioquímico"
        if resolved_state == "post_prostatectomy" and post_rp_course == "persistent_psa":
            return "Iniciar evaluación temprana de salvage por PSA persistente"
        if salvage_window_status in {"open", "open_pending_restaging", "pending_inputs"}:
            return "Activar salvage y reestadificación dirigida"
        if salvage_window_status == "redirect_systemic":
            return "Redirigir a intensificación sistémica y staging avanzado"
        if salvage_window_status == "closed":
            return "Cerrar ventana de salvage local y redefinir estrategia terapéutica"
        return "Completar datos decisivos para definir salvage post-RP"

    def _build_rule_based_recommendation(
        self,
        *,
        post_rp_course: str,
        resolved_state: str,
        salvage_window_status: str,
        salvage_window_reason: str,
        module_result: dict[str, Any],
        payload: dict[str, Any],
        psma_impact: dict[str, Any],
        intensification_profile: dict[str, Any],
    ) -> dict[str, Any]:
        action = self._rule_based_title(
            resolved_state=resolved_state,
            post_rp_course=post_rp_course,
            salvage_window_status=salvage_window_status,
        )
        rationale = _normalize_text(salvage_window_reason or module_result.get("recommended_trajectory") or module_result.get("report_sections", {}).get("summary"))
        pathologic_stage = _normalize_text(payload.get("pathologic_stage")).lower()
        positive_margin = _normalize_text(payload.get("surgical_margin")).lower() in {"1", "positive", "positivo"}
        decipher_high = "alto" in _normalize_text(payload.get("decipher_risk")).lower()
        nccn_label = _normalize_text((module_result.get("nccn_primary") or {}).get("label"))
        first_treatment = next((item for item in (module_result.get("eligible_treatments") or []) if isinstance(item, dict) and _normalize_text(item.get("name"))), {})
        high_risk = bool(intensification_profile.get("high_risk_post_rp_salvage"))
        pelvic_rt_role = _normalize_text(intensification_profile.get("pelvic_rt_role"))
        adt_duration_band = _normalize_text(intensification_profile.get("adt_duration_band"))
        psma_restaging_role = _normalize_text(intensification_profile.get("psma_restaging_role"))
        risk_features = list(intensification_profile.get("high_risk_feature_keys") or [])
        if post_rp_course == "stable_surveillance" and (positive_margin or decipher_high or pathologic_stage.startswith("pt3")):
            action = "Vigilancia estrecha con PSA ultrasensible y planificación temprana de salvage"
            rationale = "La patología adversa aumenta la urgencia de vigilancia y discusión temprana de salvage, aunque no redefine por sí sola una BCR verdadera."
        # Auditoría #21 (cierre OOS-5): el override de intensificación temprana
        # NO debe dispararse cuando `salvage_window_status == "pending_inputs"`.
        # `pending_inputs` significa que faltan datos decisivos (ej. PSADT) sin
        # los cuales no se puede sustentar la decisión SRT+ADT vs SRT sola per
        # AUA/ASTRO/SUO Salvage 2024. En ese estado debemos mantener el título
        # por default ("Activar salvage y reestadificación dirigida") para que
        # el operador primero complete los inputs en lugar de saltar a la
        # intensificación como si la ventana estuviera abierta. Las ramas
        # {"open", "open_pending_restaging"} siguen disparando el override
        # cuando la biología es high-risk y los datos decisivos ya están en el
        # perfil.
        if (
            resolved_state == "recurrence_bcr"
            and salvage_window_status in {"open", "open_pending_restaging"}
            and high_risk
        ):
            action = (
                "Activar salvage temprano intensificado con ADT y PSMA urgente"
                if psma_restaging_role == "urgent_companion"
                else "Activar salvage temprano intensificado con ADT"
            )
            rationale = (
                "El salvage post-RP sigue siendo curativo, pero los high-risk features ya favorecen SRT + ADT sobre RT sola."
            )
            if pelvic_rt_role in {"consider", "preferred"}:
                action = (
                    "Activar salvage intensificado con ADT y decidir lecho versus lecho + pelvis"
                    if psma_restaging_role != "urgent_companion"
                    else "Activar salvage intensificado con ADT, PSMA urgente y decidir lecho versus lecho + pelvis"
                )
                rationale = (
                    "La biología y/o la imagen sugieren que la discusión de pelvis electiva debe entrar junto con ADT concomitante."
                )
            if psma_restaging_role == "urgent_companion":
                rationale = (
                    f"{rationale} La PSMA debe hacerse de forma urgente para moldear el campo, pero un estudio negativo no debe retrasar la SRT."
                )
        if _normalize_text(psma_impact.get("clinical_pattern")).lower() == "oligometastatic" and salvage_window_status == "open":
            action = "Considerar MDT o salvage multimodal guiado por PSMA"
            rationale = psma_impact.get("rationale") or "La distribución oligometastásica mantiene visible una ruta MDT/salvage multimodal."
        elif salvage_window_status in {"redirect_systemic", "closed"} and "BCR2" in nccn_label and first_treatment:
            action = _normalize_text(first_treatment.get("name")) or action
            rationale = _normalize_text(first_treatment.get("notes")) or rationale
        recommendation_family = "surveillance"
        if salvage_window_status in {"open", "open_pending_restaging", "pending_inputs"} or (
            resolved_state == "recurrence_bcr" and salvage_window_status not in {"redirect_systemic", "closed"}
        ):
            recommendation_family = "salvage"
        return {
            "source": "rule_based_primary",
            "state_family": resolved_state,
            "recommended_action": action,
            "recommendation_family": recommendation_family,
            "rationale": rationale,
            "guideline_basis": self._guideline_basis(module_result),
            "high_risk_feature_keys": risk_features,
            "pelvic_rt_role": pelvic_rt_role,
            "adt_duration_band": adt_duration_band,
            "psma_restaging_role": psma_restaging_role,
        }

    def _build_restaging_strategy(
        self,
        *,
        salvage_window_status: str,
        psma_profile: dict[str, Any],
        psma_impact: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if salvage_window_status == "redirect_systemic":
            return {
                "status": "systemic_redirect",
                "recommended_action": "Completar staging sistémico y descartar rescate local aislado.",
                "rationale": psma_impact.get("rationale") or "La imagen ya desplazó el peso clínico fuera del rescate local exclusivo.",
            }
        if salvage_window_status == "open_pending_restaging":
            return {
                "status": "pending_psma",
                "recommended_action": "Completar PSMA o imagen dirigida para moldear la ruta de salvage.",
                "rationale": "La ventana de salvage sigue siendo plausible; la PSMA debe afinar alcance/campo sin convertirse en excusa para retrasar una SRT temprana si sigue siendo curativa.",
            }
        if salvage_window_status == "pending_inputs":
            return {
                "status": "need_core_inputs",
                "recommended_action": "Completar cinética bioquímica y factibilidad local antes de reestadificar.",
                "rationale": "La ventana de salvage no puede clasificarse con seguridad sin datos decisivos adicionales.",
            }
        if psma_profile.get("available"):
            return {
                "status": "restaged",
                "recommended_action": "Usar el PSMA estructurado ya disponible para sostener la ruta de salvage.",
                "rationale": psma_impact.get("rationale") or "La reestadificación dirigida ya está documentada.",
            }
        return {
            "status": "not_required",
            "recommended_action": "No hay reestadificación adicional obligada en este ciclo.",
            "rationale": "El contexto actual no exige imagen dirigida adicional para sostener la conducta dominante.",
        }

    def _build_local_salvage_pathway(
        self,
        *,
        resolved_state: str,
        post_rp_course: str,
        salvage_window_status: str,
        psma_impact: dict[str, Any],
        intensification_profile: dict[str, Any],
    ) -> dict[str, Any]:
        visible = salvage_window_status in {"open", "open_pending_restaging", "pending_inputs"}
        if not visible:
            return {
                "visible": False,
                "status": salvage_window_status,
                "recommended_path": "",
                "rationale": "La ruta local aislada no es la dominante en este momento.",
            }
        pelvic_rt_role = _normalize_text(intensification_profile.get("pelvic_rt_role"))
        adt_duration_band = _normalize_text(intensification_profile.get("adt_duration_band"))
        psma_restaging_role = _normalize_text(intensification_profile.get("psma_restaging_role"))
        companion_actions = list(
            intensification_profile.get("companion_actions_required_for_preferred_regimen") or []
        )
        high_risk_features = list(intensification_profile.get("high_risk_feature_keys") or [])
        if resolved_state == "post_prostatectomy" and post_rp_course == "persistent_psa":
            path = "Evaluación temprana de RT de salvage por PSA persistente"
        elif _normalize_text(psma_impact.get("clinical_pattern")).lower() == "oligometastatic":
            path = "MDT / salvage multimodal guiado por PSMA"
        elif resolved_state == "post_prostatectomy" and salvage_window_status == "pending_inputs":
            path = "Salvage post-RP pendiente de completar PSADT / factibilidad local"
        elif _normalize_text(intensification_profile.get("salvage_intensification_preference")) == "rt_pelvic_short_adt":
            path = "SRT al lecho + pelvis electiva + ADT concomitante"
        elif bool(intensification_profile.get("high_risk_post_rp_salvage")):
            path = "SRT temprana intensificada con ADT concomitante"
        else:
            path = "RT de salvage y staging dirigido por recurrencia bioquímica"
        return {
            "visible": True,
            "status": salvage_window_status,
            "recommended_path": path,
            "rationale": psma_impact.get("rationale") or "La ventana curativa sigue siendo visible y debe sostenerse en la agenda.",
            "local_salvage_scope": _normalize_text(intensification_profile.get("local_salvage_scope")),
            "pelvic_rt_role": pelvic_rt_role,
            "adt_duration_band": adt_duration_band,
            "psma_restaging_role": psma_restaging_role,
            "high_risk_feature_keys": high_risk_features,
            "negative_psma_should_not_delay_salvage": bool(
                intensification_profile.get("negative_psma_should_not_delay_salvage")
            ),
            "companion_actions_required_for_preferred_regimen": companion_actions,
        }

    def _build_sequence_candidates(
        self,
        *,
        post_rp_course: str,
        salvage_window_status: str,
        local_salvage_pathway: dict[str, Any],
        safety_gates: list[dict[str, Any]],
        psma_impact: dict[str, Any],
    ) -> list[dict[str, Any]]:
        candidates: list[PostRPSequenceCandidate] = []
        blocked_labels = [gate.get("label") for gate in safety_gates if gate.get("status") == "blocked"]
        if local_salvage_pathway.get("visible"):
            candidates.append(
                PostRPSequenceCandidate(
                    pathway_key="local_salvage",
                    label=local_salvage_pathway.get("recommended_path") or "Ruta local de salvage",
                    confidence=0.74 if salvage_window_status == "open" else 0.68,
                    blocked=False,
                    rationale=local_salvage_pathway.get("rationale", ""),
                )
            )
        if salvage_window_status == "redirect_systemic":
            candidates.append(
                PostRPSequenceCandidate(
                    pathway_key="systemic_redirect",
                    label="Redirección sistémica fuera de salvage local aislado",
                    confidence=0.78,
                    blocked=False,
                    rationale="La imagen y el contexto clínico ya reducen el peso de una ruta exclusivamente local.",
                )
            )
        if _normalize_text(psma_impact.get("clinical_pattern")).lower() == "oligometastatic":
            candidates.insert(
                0,
                PostRPSequenceCandidate(
                    pathway_key="mdt_multimodal",
                    label="MDT / salvage multimodal guiado por PSMA",
                    confidence=0.76,
                    blocked=False,
                    rationale=psma_impact.get("rationale") or "La PSMA de bajo burden mantiene visible una ruta metastasis-directed o multimodal.",
                ),
            )
        if salvage_window_status == "pending_inputs":
            candidates.append(
                PostRPSequenceCandidate(
                    pathway_key="complete_missing_inputs",
                    label="Completar datos decisivos antes de definir salvage",
                    confidence=0.7,
                    blocked=False,
                    rationale="Sin cinética y factibilidad local la ruta de salvage no puede cerrarse todavía.",
                )
            )
        if salvage_window_status == "closed":
            candidates.append(
                PostRPSequenceCandidate(
                    pathway_key="postlocal_redefinition",
                    label="Cerrar ventana de salvage local y redefinir estrategia terapéutica",
                    confidence=0.74,
                    blocked=False,
                    rationale="La ruta curativa local dejó de ser dominante y ahora corresponde una redefinición terapéutica postlocal.",
                )
            )
        if not candidates:
            candidates.append(
                PostRPSequenceCandidate(
                    pathway_key="surveillance",
                    label="Vigilancia bioquímica y funcional post-RP",
                    confidence=0.7,
                    blocked=False,
                    rationale="No hay una ruta de salvage dominante visible en este ciclo.",
                )
            )
        if blocked_labels:
            candidates[0].blocked = True
            candidates[0].blocked_by = blocked_labels[:3]
        return [item.to_dict() for item in candidates[:3]]

    def _build_safety_gates(
        self,
        payload: dict[str, Any],
        *,
        resolved_state: str,
        post_rp_course: str,
        salvage_window_status: str,
        psma_profile: dict[str, Any],
        psma_impact: dict[str, Any],
    ) -> list[dict[str, Any]]:
        gates: list[PostRPSafetyGate] = []
        if post_rp_course == "persistent_psa":
            gates.append(
                PostRPSafetyGate(
                    gate_key="persistent_psa_pending_confirmation"
                    if resolved_state == "post_prostatectomy"
                    else "persistent_psa_provenance_preserved",
                    label="PSA persistente aún en evaluación postoperatoria"
                    if resolved_state == "post_prostatectomy"
                    else "PSA persistente reconocido como origen post-RP",
                    status="pass",
                    rationale="La plataforma conserva PSA persistente dentro del carril postoperatorio mientras falten datos decisivos para cerrar la ventana de salvage."
                    if resolved_state == "post_prostatectomy"
                    else "El course de PSA persistente se conserva como provenance, pero la decisión operativa ya funciona como recurrencia bioquímica.",
                )
            )
        margins = _normalize_text(payload.get("surgical_margin"))
        decipher = _normalize_text(payload.get("decipher_risk")).lower()
        if margins in {"1", "positive", "positivo"} or "alto" in decipher:
            gates.append(
                PostRPSafetyGate(
                    gate_key="adverse_pathology_modifier",
                    label="Patología adversa / Decipher alto",
                    status="warning",
                    rationale="La urgencia de vigilancia o salvage aumenta, pero esto no redefine por sí solo a BCR verdadera.",
                    failure_family="state_misclassification",
                )
            )
        if salvage_window_status == "redirect_systemic":
            gates.append(
                PostRPSafetyGate(
                    gate_key="systemic_redirect_gate",
                    label="Rescate local aislado bloqueado",
                    status="blocked",
                    rationale="La distribución por imagen ya no sostiene una estrategia exclusivamente local.",
                    failure_family="psma_restaging",
                )
            )
        if psma_profile.get("available") and psma_impact.get("clinical_pattern") == "diseminado":
            gates.append(
                PostRPSafetyGate(
                    gate_key="psma_distributed_pattern",
                    label="PSMA diseminado",
                    status="blocked",
                    rationale=psma_impact.get("rationale") or "El PSMA diseminado desplaza el peso clínico fuera del salvage local aislado.",
                    failure_family="psma_restaging",
                )
            )
        if not _is_present(payload.get("psadt_months")) and post_rp_course in {"persistent_psa", "true_bcr"}:
            gates.append(
                PostRPSafetyGate(
                    gate_key="psadt_missing",
                    label="PSADT no documentado",
                    status="blocked",
                    rationale="La cinética bioquímica sigue faltando para dimensionar urgencia y ventana real de salvage.",
                    failure_family="psadt_missing",
                )
            )
        if not _is_present(payload.get("salvage_local_feasible")) and post_rp_course in {"persistent_psa", "true_bcr"}:
            gates.append(
                PostRPSafetyGate(
                    gate_key="salvage_feasibility_missing",
                    label="Factibilidad de salvage no documentada",
                    status="blocked",
                    rationale="La ventana de salvage no puede etiquetarse como abierta sin una evaluación local explícita.",
                    failure_family="salvage_feasibility",
                )
            )
        return [item.to_dict() for item in gates]

    def _build_blocking_input_groups(self, requirements: dict[str, Any]) -> list[dict[str, Any]]:
        descriptors = list(requirements.get("blocking_input_descriptors") or [])
        grouped: dict[str, dict[str, Any]] = {}
        for item in descriptors:
            field_name = str(item.get("field_name") or "")
            bucket = str(item.get("bucket") or "decision_blocking_inputs")
            if field_name not in set(requirements.get("blocking_inputs") or []) | set(requirements.get("supportive_gaps") or []):
                continue
            group_key = str(item.get("display_group") or bucket)
            group = grouped.setdefault(
                group_key,
                {
                    "group_key": group_key,
                    "group_label": item.get("display_group") or "Captura clínica",
                    "fields": [],
                    "required_fields": [],
                    "why_now": item.get("display_why_now") or item.get("why") or "",
                    "impact": item.get("display_impact") or "Completar este grupo puede cambiar la conducta hoy.",
                    "capture_target": item.get("display_capture_target") or item.get("capture_target") or "",
                },
            )
            label = item.get("display_label") or item.get("field_name")
            if label and label not in group["fields"]:
                group["fields"].append(label)
            if bucket in {"hard_blocking_inputs", "decision_blocking_inputs"} and label not in group["required_fields"]:
                group["required_fields"].append(label)
        if grouped:
            return list(grouped.values())
        plain_groups = []
        for field_name in requirements.get("blocking_inputs") or []:
            plain_groups.append(
                {
                    "group_key": field_name,
                    "group_label": "Dato decisivo",
                    "fields": [field_name],
                    "required_fields": [field_name],
                    "why_now": "La decisión clínica actual no se cierra sin este dato.",
                    "impact": "Completarlo hoy puede recalcular la conducta.",
                    "capture_target": "followup",
                }
            )
        return plain_groups

    def _build_ai_overlay(
        self,
        *,
        runtime_mode: str,
        rule_based_recommendation: dict[str, Any],
        sequence_candidates: list[dict[str, Any]],
        blocking_inputs: list[dict[str, Any]],
        safety_gates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        top_candidate = sequence_candidates[0] if sequence_candidates else None
        if not top_candidate:
            return {
                "available": False,
                "status": "unavailable",
                "recommended_action": "",
                "concordance_label": "rule_only",
                "shadow_reasons": ["No hay vía post-RP priorizada todavía."],
            }
        recommended_action = _normalize_text(top_candidate.get("label"))
        concordance = self._concordance_label(
            rule_based_recommendation.get("recommended_action", ""),
            recommended_action,
        )
        has_required_blockers = any(group.get("required_fields") for group in blocking_inputs)
        has_safety_blocks = any(str(gate.get("status") or "").lower() == "blocked" for gate in safety_gates)
        if has_required_blockers or has_safety_blocks or top_candidate.get("blocked"):
            status = "shadow-blocked"
        elif runtime_mode == "advisory" and concordance != "discordant":
            status = "advisory_candidate"
        else:
            status = "shadow"
        return {
            "available": True,
            "status": status,
            "recommended_action": recommended_action,
            "recommendation_family": str(rule_based_recommendation.get("recommendation_family") or "salvage"),
            "sequence_candidate": top_candidate,
            "concordance_label": concordance,
            "shadow_reasons": [
                "La recomendación AI permanece en shadow hasta que QA apruebe y no existan blockers duros."
                if runtime_mode == "shadow"
                else "La recomendación AI solo puede presentarse si sigue siendo concordante con la ruta primaria."
            ] + [gate.get("label") for gate in safety_gates if gate.get("status") == "blocked"][:3],
        }

    def _concordance_label(self, rule_action: str, overlay_action: str) -> str:
        if not rule_action or not overlay_action:
            return "rule_only"
        if _normalize_for_compare(rule_action) == _normalize_for_compare(overlay_action):
            return "concordant"
        if "salvage" in rule_action.lower() and "salvage" in overlay_action.lower():
            return "adjacent"
        if "vigil" in rule_action.lower() and "vigil" in overlay_action.lower():
            return "adjacent"
        return "discordant"

    def _run_qa_validation(
        self,
        patient: dict[str, Any],
        *,
        resolved_state: str,
        overlay: dict[str, Any],
        rule_based_recommendation: dict[str, Any],
    ) -> dict[str, Any]:
        action = overlay.get("recommended_action") or rule_based_recommendation.get("recommended_action")
        recommendation = AgentRecommendation(
            action=action,
            category="treatment",
            priority="high",
            evidence_basis=list(rule_based_recommendation.get("guideline_basis") or []),
        )
        qa_record = dict(patient)
        qa_record["reconciled_state"] = resolved_state
        qa_output = AgentOutput(
            agent_id="post_rp_salvage_copilot_overlay",
            patient_id=int((patient.get("identity") or {}).get("id") or 0),
            recommendations=[recommendation],
            confidence_score=70.0 if overlay.get("available") else 50.0,
        )
        return self.qa_agent.validate(qa_output, qa_record).to_dict()

    def _build_final_recommendation(
        self,
        *,
        runtime_mode: str,
        rule_based_recommendation: dict[str, Any],
        ai_overlay: dict[str, Any],
        qa_validation: dict[str, Any],
        blocking_groups: list[dict[str, Any]],
    ) -> dict[str, Any]:
        has_required_blockers = any(group.get("required_fields") for group in blocking_groups)
        if (
            runtime_mode == "advisory"
            and ai_overlay.get("available")
            and ai_overlay.get("concordance_label") != "discordant"
            and ai_overlay.get("status") != "shadow-blocked"
            and qa_validation.get("approved")
            and not has_required_blockers
        ):
            return {
                "source": "post_rp_salvage_copilot_advisory",
                "recommended_action": ai_overlay.get("recommended_action"),
                "recommendation_family": ai_overlay.get("recommendation_family"),
                "rationale": "Overlay AI presentado porque pasó QA, no hay blockers duros y la recomendación sigue siendo concordante con la ruta primaria post-RP.",
            }
        return dict(rule_based_recommendation)

    def _build_why_changed_today(
        self,
        payload: dict[str, Any],
        *,
        post_rp_course: str,
        salvage_window_status: str,
        salvage_window_reason: str,
        psma_impact: dict[str, Any],
        intensification_profile: dict[str, Any],
        pivotal_gates_delta: dict[str, Any] | None = None,
    ) -> list[str]:
        notes = []
        latest_psa = _safe_float(payload.get("psa_current") or payload.get("psa_postop") or payload.get("psa"))
        if latest_psa is not None:
            notes.append(f"PSA actual {latest_psa:g} ng/mL.")
        psadt = _safe_float(payload.get("psadt_months"))
        if psadt is not None:
            notes.append(f"PSADT actual {psadt:.1f} meses.")
        if _normalize_text(payload.get("decipher_risk")):
            notes.append(f"Decipher {payload.get('decipher_risk')}.")
        if _normalize_text(payload.get("psma_stage_after_psma")):
            notes.append(f"PSMA estructurado {payload.get('psma_stage_after_psma')}.")
        if intensification_profile.get("high_risk_feature_keys"):
            notes.append(
                "High-risk salvage: " + ", ".join(list(intensification_profile.get("high_risk_feature_keys") or [])[:4]) + "."
            )
        notes.append(f"Curso post-RP: {post_rp_course or 'no definido'}.")
        notes.append(f"Ventana de salvage: {salvage_window_status}.")
        if salvage_window_reason:
            notes.append(salvage_window_reason)
        if psma_impact.get("clinical_pattern") == "diseminado":
            notes.append("El PSMA diseminado reduce el peso de rescate local aislado.")
        # Faubot 2026-04-25 (IX) — narrativa clínica del delta de gates pivotal.
        if pivotal_gates_delta:
            from prostanet.shared.pivotal_gate_delta import (
                describe_gate_delta_in_clinical_language,
            )
            gate_notes = describe_gate_delta_in_clinical_language(pivotal_gates_delta)
            notes.extend(gate_notes)
        return notes[:8]

    def _build_schedule_overlay(
        self,
        *,
        resolved_state: str,
        post_rp_course: str,
        salvage_window_status: str,
        blocking_groups: list[dict[str, Any]],
        payload: dict[str, Any],
        intensification_profile: dict[str, Any],
    ) -> dict[str, Any]:
        high_risk = bool(intensification_profile.get("high_risk_post_rp_salvage"))
        pelvic_rt_role = _normalize_text(intensification_profile.get("pelvic_rt_role"))
        psma_restaging_role = _normalize_text(intensification_profile.get("psma_restaging_role"))
        if post_rp_course == "stable_surveillance":
            primary_intent = "PSA seriado y vigilancia funcional post prostatectomía"
            cadence = ["PSA ultrasensible seriado", "Revisión funcional urinaria y sexual"]
        elif post_rp_course == "persistent_psa" and resolved_state == "post_prostatectomy":
            primary_intent = "Evaluación temprana de salvage por PSA persistente"
            cadence = ["PSA ultrasensible y PSADT", "Definir factibilidad local e imagen dirigida"]
        elif salvage_window_status == "redirect_systemic":
            primary_intent = "Redirección fuera de salvage local aislado"
            cadence = ["Staging sistémico", "Discusión de intensificación terapéutica"]
        elif salvage_window_status == "closed":
            primary_intent = "Cerrar ventana de salvage local y redefinir estrategia terapéutica"
            cadence = ["Reestadificación integral", "Discusión terapéutica postlocal no curativa"]
        elif high_risk:
            primary_intent = (
                "Salvage temprano intensificado con ADT y PSMA urgente"
                if psma_restaging_role == "urgent_companion"
                else "Salvage temprano intensificado con ADT"
            )
            cadence = [
                "SRT temprana con ADT concomitante",
                "Definir duración de ADT según riesgo",
            ]
            if psma_restaging_role == "urgent_companion":
                cadence.insert(1, "PSMA urgente para decidir lecho versus lecho + pelvis")
            if pelvic_rt_role in {"consider", "preferred"}:
                cadence.append("Discutir campo pélvico electivo")
        else:
            primary_intent = "Salvage y reestadificación dirigida"
            cadence = ["RT de salvage / evaluación local", "PSMA o imagen dirigida según contexto"]
        blockers = [group.get("group_label") for group in blocking_groups if group.get("required_fields")]
        return {
            "schedule_primary_intent": primary_intent,
            "cadence_adjustment_reasons": cadence + blockers[:2],
            "recommended_events": cadence[:3],
            "salvage_window_status": salvage_window_status,
            "current_psa": _safe_float(payload.get("psa_current") or payload.get("psa_postop") or payload.get("psa")),
        }

    def _resolve_status(
        self,
        *,
        runtime_mode: str,
        qa_validation: dict[str, Any],
        blocking_groups: list[dict[str, Any]],
        ai_overlay: dict[str, Any],
    ) -> str:
        if not ai_overlay.get("available"):
            return "rule_only"
        if runtime_mode == "shadow":
            return "shadow-blocked" if ai_overlay.get("status") == "shadow-blocked" else "shadow"
        has_required_blockers = any(group.get("required_fields") for group in blocking_groups)
        if qa_validation.get("approved") and not has_required_blockers and ai_overlay.get("concordance_label") != "discordant":
            return "advisory"
        return "shadow-blocked"

    def _risk_tools_summary(self, risk_tools_bundle: dict[str, Any]) -> dict[str, Any]:
        cards = list(risk_tools_bundle.get("cards") or [])
        selected = [
            {
                "tool_key": item.get("tool_key"),
                "label": item.get("label"),
                "primary_result": item.get("primary_result"),
            }
            for item in cards
            if item.get("tool_key") in {"capra_s", "mskcc_bcr_post_rp", "decipher_post_rp"}
        ]
        return {
            "cards": selected[:4],
            "missing_inputs": list(risk_tools_bundle.get("missing_inputs") or [])[:6],
        }


def build_post_rp_salvage_bundle(
    patient: dict[str, Any],
    *,
    effective_state: str = "",
    effective_management_track: str = "",
    latest_assessment: dict[str, Any] | None = None,
    longitudinal_bundle: dict[str, Any] | None = None,
    decision_input_requirements: dict[str, Any] | None = None,
    trigger_event: str = "",
) -> dict[str, Any]:
    service = PostRPSalvageCopilotService()
    return service.evaluate(
        patient,
        effective_state=effective_state,
        effective_management_track=effective_management_track,
        latest_assessment=latest_assessment,
        longitudinal_bundle=longitudinal_bundle,
        decision_input_requirements=decision_input_requirements,
        trigger_event=trigger_event,
    )


__all__ = [
    "POST_RP_VERTICAL_STATES",
    "PostRPSalvageCopilotService",
    "build_post_rp_salvage_bundle",
]
