from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from typing import Any

from prostanet.agents.contracts import AgentOutput, AgentRecommendation
from prostanet.agents.quality_assurance_agent import QualityAssuranceAgent
from prostanet.ai.config import get_ai_config
from prostanet.domains.adt_progression_verification.service import (
    AdtProgressionVerificationService,
)
from prostanet.domains.m0_crpc.service import M0CrpcService
from prostanet.domains.m1_crpc.service import M1CrpcService
from prostanet.domains.patient_tracking.decision_input_requirements_engine import (
    build_decision_input_requirements,
)
from prostanet.domains.patient_tracking.event_graph import (
    merge_record_into_assessment_payload,
)
from prostanet.domains.patient_tracking.laboratory_intelligence.service import (
    build_laboratory_intelligence_profile,
)
from prostanet.domains.patient_tracking.psma_imaging.service import (
    build_psma_structured_profile,
)
from prostanet.domains.patient_tracking.therapeutic_family_engine import family_label
from prostanet.domains.patient_tracking.therapy_catalog import (
    normalize_regimen_code,
    regimen_metadata_bundle,
)
from prostanet.domains.patient_tracking.treatment_sequencer import TreatmentSequencer
from prostanet.domains.patient_tracking.vertical_runtime import (
    build_blocked_by_overlay,
    build_decision_delta_since_last_visit,
    build_evidence_basis_current_visit,
    build_histopathology_summary,
    build_shared_metastatic_summary,
    enrich_recommendation_with_metastatic_summary,
    prepend_metastatic_context,
)
from prostanet.engine.confidence_scoring import ConfidenceScorer
from prostanet.shared.ddi_engine import DDIEngine
from prostanet.shared.feature_flags import resolve_feature_flags
from prostanet.shared.metastatic_profile import resolve_metastatic_state_context
from prostanet.shared.presentation_text import state_display_label
from prostanet.shared.systemic_regimen_scope import build_systemic_regimen_scope_contract


CRPC_VERTICAL_STATES = {"adt_progression_verification", "m0_crpc", "m1_crpc"}
ARPI_TOKENS = ("enza", "abirater", "apalut", "darolut")
PARP_TOKENS = ("olapar", "rucapar", "nirapar", "talazopar")


def _state_label(state: str) -> str:
    return state_display_label(state)


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No documentado", "Desconocido", "Desconocida")


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _coerce_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return dict(parsed)
    return {}


def _coerce_text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_normalize_text(item) for item in value if _normalize_text(item)]
    if isinstance(value, str):
        return [_normalize_text(item) for item in value.split(",") if _normalize_text(item)]
    return []


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


def _normalize_for_compare(value: str) -> str:
    lowered = value.lower().strip()
    for token in (
        "acetato de ",
        " + adt",
        "+ adt",
        " + terapia de privacion androgenica",
        " + terapia de privación androgénica",
        " + tda",
        " (post-arsi)",
        " (ar-v7 dirigido)",
    ):
        lowered = lowered.replace(token, "")
    lowered = lowered.replace(" ", "").replace("-", "")
    return lowered


def _treatment_family(value: str) -> str:
    lowered = value.lower()
    if any(token in lowered for token in ("enza", "abirater", "apalut", "darolut")):
        return "arpi"
    if any(token in lowered for token in ("docetax", "cabazitax")):
        return "taxane"
    if any(token in lowered for token in ("olapar", "rucapar", "nirapar", "talazopar")):
        return "parp"
    if any(token in lowered for token in ("lu177", "lutec", "pluvicto", "psma")):
        return "psma_rlt"
    if "pembrol" in lowered:
        return "immunotherapy"
    if "radium" in lowered or "radio-223" in lowered:
        return "bone_targeted"
    return "other"


def _structured_recommendation_family(
    preferred_regimen: dict[str, Any] | None,
    sequence_bundle: dict[str, Any] | None,
    fallback: str,
) -> str:
    preferred_regimen = dict(preferred_regimen or {})
    sequence_bundle = dict(sequence_bundle or {})
    family_code = str(
        preferred_regimen.get("family_code")
        or preferred_regimen.get("family_label")
        or sequence_bundle.get("active_family")
        or ""
    ).strip()
    if family_code.endswith("_family"):
        return family_label(family_code)
    return family_code or fallback


def _has_card_sequence_context(payload: dict[str, Any]) -> bool:
    prior_therapy = " ".join(str(item).lower() for item in (payload.get("prior_therapy") or []))
    has_prior_arpi = any(token in prior_therapy for token in ARPI_TOKENS)
    has_prior_taxane = any(token in prior_therapy for token in ("docetax", "cabazitax"))
    return has_prior_arpi and has_prior_taxane


@dataclass
class CRPCSequenceCandidate:
    line_number: int
    drug: str
    drug_label: str
    regimen_code: str
    regimen_label: str
    evidence_level: str
    expected_os_months: float | None
    expected_pfs_months: float | None
    confidence: float
    is_preferred: bool
    biomarker_driven: bool
    blocked: bool = False
    blocked_by: list[str] = field(default_factory=list)
    rationale: str = ""
    formulary: list[str] = field(default_factory=list)
    component_drugs: list[dict[str, Any]] = field(default_factory=list)
    dose: str = ""
    route: str = ""
    schedule: str = ""
    imss_key: str = ""
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CRPCSafetyGate:
    gate_key: str
    label: str
    status: str
    rationale: str
    candidate_drugs: list[str] = field(default_factory=list)
    failure_family: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CRPCCopilotService:
    service_id = "crpc_copilot"

    def __init__(self) -> None:
        self.adt_service = AdtProgressionVerificationService()
        self.m0_service = M0CrpcService()
        self.m1_service = M1CrpcService()
        self.sequencer = TreatmentSequencer()
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
            if latest_assessment_state in CRPC_VERTICAL_STATES
            else (
                effective_state
                or latest_assessment_state
                or (patient.get("prior_history") or {}).get("current_state")
                or ""
            )
        )
        if not flags.get("ENABLE_CRPC_COPILOT"):
            return self._disabled_bundle(state=state, runtime_mode=runtime_mode, status="disabled")
        if state not in CRPC_VERTICAL_STATES:
            return self._disabled_bundle(state=state, runtime_mode=runtime_mode, status="not_applicable")

        runtime_patient = self._build_runtime_patient(patient, longitudinal_bundle)
        payload = self._build_payload(runtime_patient, latest_assessment, effective_state=state)
        state_family, routing_reason = self._resolve_state_family(state, payload)
        module_result = self._evaluate_rule_based(state_family, payload)
        labs_profile = dict(
            (longitudinal_bundle or {}).get("laboratory_intelligence_profile")
            or build_laboratory_intelligence_profile(
                runtime_patient,
                state=state_family,
                management_track=effective_management_track,
                latest_assessment=latest_assessment or patient.get("latest_assessment"),
            )
        )
        psma_profile = dict(runtime_patient.get("psma_structured_profile") or build_psma_structured_profile(runtime_patient))
        ddi_review = DDIEngine.full_review(self._ddi_patient(runtime_patient, payload))
        requirements = decision_input_requirements or build_decision_input_requirements(
            runtime_patient,
            effective_state=state_family,
            effective_management_track=effective_management_track,
            latest_assessment=latest_assessment or patient.get("latest_assessment"),
            next_best_action=(longitudinal_bundle or {}).get("next_best_action") or {},
        )
        blocking_groups = self._build_blocking_input_groups(requirements)
        safety_gates = self._build_safety_gates(
            payload,
            runtime_patient,
            state_family=state_family,
            psma_profile=psma_profile,
            labs_profile=labs_profile,
        )
        sequence_candidates = self._build_sequence_candidates(
            runtime_patient,
            payload,
            state_family=state_family,
            safety_gates=safety_gates,
            module_result=module_result,
        )
        rule_based_recommendation = self._build_rule_based_recommendation(
            state_family=state_family,
            module_result=module_result,
            routing_reason=routing_reason,
            payload=payload,
        )
        metastatic_composition_summary = build_shared_metastatic_summary(payload)
        histopathology_summary = build_histopathology_summary(payload)
        rule_based_recommendation = enrich_recommendation_with_metastatic_summary(
            rule_based_recommendation,
            metastatic_composition_summary,
        )
        ai_advisory_overlay = self._build_ai_overlay(
            runtime_mode=runtime_mode,
            state_family=state_family,
            rule_based_recommendation=rule_based_recommendation,
            sequence_candidates=sequence_candidates,
            blocking_groups=blocking_groups,
            safety_gates=safety_gates,
            preferred_regimen=dict(module_result.get("preferred_frontline_regimen") or {}),
            sequence_transition_bundle=dict(module_result.get("sequence_transition_bundle") or {}),
        )
        qa_validation = self._run_qa_validation(
            runtime_patient,
            state_family=state_family,
            overlay=ai_advisory_overlay,
            rule_based_recommendation=rule_based_recommendation,
            payload=payload,
        )
        final_presented_recommendation = self._build_final_recommendation(
            runtime_mode=runtime_mode,
            rule_based_recommendation=rule_based_recommendation,
            ai_overlay=ai_advisory_overlay,
            qa_validation=qa_validation,
            blocking_groups=blocking_groups,
        )
        final_presented_recommendation = enrich_recommendation_with_metastatic_summary(
            final_presented_recommendation,
            metastatic_composition_summary,
        )
        model_like_output = {
            "recommendations": [
                {
                    "action": ai_advisory_overlay.get("recommended_action") or rule_based_recommendation.get("recommended_action"),
                }
            ],
            "metadata": {
                "historical_calibration_score": 62.0 if ai_advisory_overlay.get("available") else 50.0,
            },
        }
        confidence = self.confidence_scorer.score(
            runtime_patient,
            agent_outputs=[model_like_output],
            guideline_result=module_result,
        )
        # Faubot 2026-04-25 (IX) — Pre-compute delta de gates pivotal antes
        # de _build_why_changed_today para que la narrativa clínica del
        # delta esté disponible para incluirse en why_changed_today.
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
            state_family=state_family,
            routing_reason=routing_reason,
            safety_gates=safety_gates,
            pivotal_gates_delta=_pivotal_gates_delta_pre,
        )
        why_changed_today = prepend_metastatic_context(why_changed_today, metastatic_composition_summary)
        crpc_schedule_overlay = self._build_schedule_overlay(
            state_family=state_family,
            blocking_groups=blocking_groups,
            safety_gates=safety_gates,
            payload=payload,
        )
        status = self._resolve_status(
            runtime_mode=runtime_mode,
            qa_validation=qa_validation,
            blocking_groups=blocking_groups,
            ai_overlay=ai_advisory_overlay,
        )
        blocked_by_overlay = build_blocked_by_overlay(
            blocking_groups=blocking_groups,
            safety_gates=safety_gates,
        )
        decision_delta_since_last_visit = build_decision_delta_since_last_visit(
            runtime_patient,
            effective_state=state_family,
            phenotype_state=state_family,
            rule_based_recommendation=rule_based_recommendation,
            final_presented_recommendation=final_presented_recommendation,
            blocking_groups=blocking_groups,
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
        sequence_summary = [
            {
                "label": candidate.get("drug_label"),
                "blocked": bool(candidate.get("blocked")),
                "blocked_by": list(candidate.get("blocked_by") or []),
            }
            for candidate in sequence_candidates[:3]
        ]
        return {
            "enabled": True,
            "available": True,
            "show_card": True,
            "service_id": self.service_id,
            "status": status,
            "state_family": state_family,
            "state_family_label": _state_label(state_family),
            "raw_state": state,
            "runtime_mode": runtime_mode,
            "rule_based_source_of_truth": True,
            "effective_state": state_family,
            "effective_management_track": effective_management_track,
            "histopathology_summary": histopathology_summary,
            "routing_reason": routing_reason,
            "metastatic_composition_summary": metastatic_composition_summary,
            "systemic_regimen_scope": str(
                module_result.get("systemic_regimen_scope")
                or build_systemic_regimen_scope_contract(state_family, module_result).get("scope")
                or "not_applicable"
            ),
            "systemic_regimen_scope_contract": dict(
                module_result.get("systemic_regimen_scope_contract")
                or build_systemic_regimen_scope_contract(state_family, module_result)
            ),
            "rule_based_recommendation": rule_based_recommendation,
            "ai_advisory_overlay": ai_advisory_overlay,
            "final_presented_recommendation": final_presented_recommendation,
            "preferred_frontline_regimen": dict(module_result.get("preferred_frontline_regimen") or {}),
            "preferred_regimen_code": str((module_result.get("preferred_frontline_regimen") or {}).get("regimen_code") or ""),
            "eligible_treatments": list(module_result.get("eligible_treatments") or []),
            "alternative_regimens": list(module_result.get("alternative_regimens") or []),
            "comparative_eligibility_matrix": dict(module_result.get("comparative_eligibility_matrix") or {}),
            "therapeutic_family_profiles": dict(module_result.get("comparative_eligibility_matrix") or {}),
            "sequence_transition_bundle": dict(module_result.get("sequence_transition_bundle") or {}),
            "active_regimen_monitoring_package": dict(module_result.get("active_regimen_monitoring_package") or {}),
            "sequence_candidates": sequence_candidates,
            "sequence_summary": sequence_summary,
            "blocking_inputs": blocking_groups,
            "blocked_by_overlay": blocked_by_overlay,
            "safety_gates": safety_gates,
            "qa_validation": qa_validation,
            "guideline_basis": guideline_basis,
            "evidence_basis_current_visit": evidence_basis_current_visit,
            "confidence": confidence,
            "why_changed_today": why_changed_today,
            "decision_delta_since_last_visit": decision_delta_since_last_visit,
            "crpc_schedule_overlay": crpc_schedule_overlay,
            "ddi_review": ddi_review,
            "laboratory_focus": {
                "active_alerts": list(labs_profile.get("active_alerts") or []),
                "therapy_safety_checkpoints": list(labs_profile.get("therapy_safety_checkpoints") or []),
            },
            "psma_profile_summary": {
                "available": bool(psma_profile.get("available")),
                "structured_complete": bool(psma_profile.get("structured_complete")),
                "psma_negative_dominant_lesions": bool(psma_profile.get("psma_negative_dominant_lesions")),
                "clinical_pattern": psma_profile.get("clinical_pattern", ""),
            },
            "trigger_event": trigger_event or "longitudinal_refresh",
            # Faubot 2026-04-24 (III) — propagar trazabilidad de gates pivotal
            # y not_recommended desde los servicios m0_crpc/m1_crpc/adt_progression.
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
            "systemic_regimen_scope": "not_applicable",
            "systemic_regimen_scope_contract": build_systemic_regimen_scope_contract(state, {}),
            "histopathology_summary": "",
            "metastatic_composition_summary": {"available": False},
            "rule_based_recommendation": {},
            "ai_advisory_overlay": {"available": False, "status": status},
            "final_presented_recommendation": {},
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
            "crpc_schedule_overlay": {},
            "sequence_summary": [],
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
        if not runtime_patient.get("genomic_profile") and runtime_patient.get("genomics"):
            runtime_patient["genomic_profile"] = dict(runtime_patient.get("genomics") or {})
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
        latest_followup_payload = dict(((latest_followup.get("visit_bundle") or {}).get("payload")) or {})
        latest_visit_payload = dict(((latest_followup.get("visit_bundle") or {}).get("payload")) or {})
        latest_treatment = dict((patient.get("treatments") or [{}])[-1] or {})
        regimen_json = _coerce_dict(latest_treatment.get("regimen_json"))
        genomics = dict(patient.get("genomics") or patient.get("genomic_profile") or {})
        for source in (truth_values, latest_snapshot, latest_followup, latest_followup_payload, latest_visit_payload, latest_treatment, regimen_json, genomics):
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
            latest_followup_payload,
            latest_visit_payload,
            latest_treatment,
            regimen_json,
            keys={
                "conventional_imaging_status",
                "progression_pattern",
                "testosterone",
                "testosterone_value",
                "testosterone_current",
                "current_adt_context",
                "line_of_therapy_number",
                "line_of_therapy",
                "current_treatment",
                "drug_scheme",
                "psadt_months",
                "psma_pet_done",
                "psma_positive",
                "psma_radioligand",
                "psma_rads_score",
                "psma_uptake_pattern",
                "psma_negative_dominant_lesions",
                "psma_stage_after_psma",
                "hrr_status",
                "hrr_gene",
                "brca2_status",
                "biomarker_source",
                "molecular_report_date",
                "mcrpc_line_context",
            },
        )

        treatments = list(patient.get("treatments") or [])
        prior_therapy = list(dict.fromkeys(_coerce_text_list(payload.get("prior_therapy"))))
        current_line = _safe_int(
            payload.get("line_of_therapy_number")
            or payload.get("line_of_therapy")
            or latest_followup_payload.get("line_of_therapy_number")
            or latest_followup_payload.get("line_of_therapy")
            or latest_treatment.get("line_of_therapy")
            or regimen_json.get("line_of_therapy_number")
        )
        for item in treatments:
            regimen_payload = _coerce_dict(item.get("regimen_json"))
            scheme = _normalize_text(item.get("drug_scheme") or item.get("drug_scheme_label") or regimen_payload.get("drug_scheme_label"))
            line_number = _safe_int(
                item.get("line_of_therapy")
                or regimen_payload.get("line_of_therapy_number")
            )
            ended = bool(item.get("end_date")) or _normalize_text(item.get("outcome")).lower() not in {"", "ongoing", "en curso"}
            prior_line = ended or (
                current_line is not None
                and line_number is not None
                and line_number < current_line
            )
            if scheme and prior_line and scheme not in prior_therapy:
                prior_therapy.append(scheme)
        current_treatment = _normalize_text(
            payload.get("current_treatment")
            or latest_followup.get("current_treatment")
            or latest_followup_payload.get("current_treatment")
            or payload.get("drug_scheme")
            or latest_treatment.get("drug_scheme_label")
        )
        payload["prior_therapy"] = prior_therapy
        payload["current_treatment"] = current_treatment
        payload["drug_scheme"] = (
            payload.get("drug_scheme")
            or latest_followup_payload.get("drug_scheme")
            or latest_treatment.get("drug_scheme")
        )
        payload["line_of_therapy_number"] = (
            payload.get("line_of_therapy_number")
            or payload.get("line_of_therapy")
            or latest_followup_payload.get("line_of_therapy_number")
            or latest_followup_payload.get("line_of_therapy")
            or latest_treatment.get("line_of_therapy")
            or regimen_json.get("line_of_therapy_number")
        )
        explicit_castrate_status = _normalize_text(payload.get("castrate_testosterone_status"))
        explicit_castrate_flag = payload.get("castrate_testosterone_confirmed")
        testosterone_value = _safe_float(
            payload.get("testosterone")
            or payload.get("testosterone_value")
            or payload.get("testosterone_current")
            or latest_followup.get("testosterone")
            or latest_visit_payload.get("testosterone")
            or patient.get("baseline", {}).get("testosterone_baseline")
        )
        if testosterone_value is not None:
            payload["testosterone_value"] = testosterone_value
            payload["testosterone"] = payload.get("testosterone") or testosterone_value
        if not _is_present(payload.get("castrate_testosterone_status")):
            if explicit_castrate_flag not in (None, ""):
                payload["castrate_testosterone_status"] = "confirmed_castrate" if str(explicit_castrate_flag).strip() in {"1", "true", "yes", "si", "sí"} else "not_castrate"
            elif testosterone_value is not None:
                payload["castrate_testosterone_status"] = "confirmed_castrate" if testosterone_value <= 50 else "not_castrate"
        if payload.get("castrate_testosterone_confirmed") in (None, ""):
            if explicit_castrate_status:
                payload["castrate_testosterone_confirmed"] = 1 if explicit_castrate_status == "confirmed_castrate" else 0
            elif testosterone_value is not None:
                payload["castrate_testosterone_confirmed"] = 1 if testosterone_value <= 50 else 0
        payload["current_adt_context"] = payload.get("current_adt_context") or payload.get("drug_scheme") or payload.get("current_treatment") or "ADT en curso"
        payload["progression_pattern"] = payload.get("progression_pattern") or "biochemical_only"
        payload["conventional_imaging_status"] = _normalize_text(payload.get("conventional_imaging_status") or "NOT_RESTAGED").upper()
        payload["psadt_months"] = payload.get("psadt_months") or patient.get("bcr", {}).get("psadt_at_bcr")
        payload["ecog_score"] = payload.get("ecog_score") or payload.get("ecog") or patient.get("baseline", {}).get("ecog_score")
        payload["ast"] = payload.get("ast") or latest_visit_payload.get("ast") or latest_followup.get("ast") or patient.get("baseline", {}).get("ast")
        payload["alt"] = payload.get("alt") or latest_visit_payload.get("alt") or latest_followup.get("alt") or patient.get("baseline", {}).get("alt")
        payload["bilirubin"] = payload.get("bilirubin") or latest_visit_payload.get("bilirubin") or latest_followup.get("bilirubin") or patient.get("baseline", {}).get("bilirubin")
        payload["potassium"] = payload.get("potassium") or latest_visit_payload.get("potassium") or latest_followup.get("potassium") or patient.get("baseline", {}).get("potassium")
        payload["glucose"] = payload.get("glucose") or latest_visit_payload.get("glucose") or latest_followup.get("glucose") or patient.get("baseline", {}).get("glucose")
        payload["systolic_bp"] = payload.get("systolic_bp") or latest_visit_payload.get("systolic_bp") or latest_followup.get("systolic_bp") or patient.get("baseline", {}).get("systolic_bp")
        payload["hemoglobin"] = payload.get("hemoglobin") or latest_visit_payload.get("hemoglobin") or latest_followup.get("hemoglobin") or patient.get("baseline", {}).get("hemoglobin")
        payload["biomarker_source"] = payload.get("biomarker_source") or payload.get("molecular_assay_source") or genomics.get("biomarker_source")
        payload["hrr_gene"] = payload.get("hrr_gene") or genomics.get("hrr_gene")
        payload["molecular_report_date"] = payload.get("molecular_report_date") or genomics.get("test_date")
        payload["effective_state"] = effective_state
        psma_profile = dict(patient.get("psma_structured_profile") or {})
        if psma_profile:
            payload["psma_pet_done"] = payload.get("psma_pet_done") or ("1" if psma_profile.get("available") else "0")
            payload["psma_positive"] = payload.get("psma_positive") or ("1" if psma_profile.get("psma_positive") else "0")
            payload["psma_radioligand"] = payload.get("psma_radioligand") or psma_profile.get("psma_radioligand")
            payload["psma_rads_score"] = payload.get("psma_rads_score") or psma_profile.get("psma_rads_score")
            payload["psma_uptake_pattern"] = payload.get("psma_uptake_pattern") or psma_profile.get("psma_uptake_pattern")
            payload["psma_negative_dominant_lesions"] = payload.get("psma_negative_dominant_lesions")
            if payload["psma_negative_dominant_lesions"] in (None, ""):
                payload["psma_negative_dominant_lesions"] = 1 if psma_profile.get("psma_negative_dominant_lesions") else 0
            payload["psma_stage_after_psma"] = payload.get("psma_stage_after_psma") or psma_profile.get("psma_stage_after_psma")
        metastatic_context = resolve_metastatic_state_context(payload)
        payload["metastatic_stage_resolved"] = (
            payload.get("metastatic_stage_resolved")
            or metastatic_context.get("metastatic_stage_resolved")
            or "M0"
        )
        payload["metastatic_detection_basis"] = (
            payload.get("metastatic_detection_basis")
            or metastatic_context.get("metastatic_detection_basis")
            or "unknown"
        )
        payload["restaging_update_required"] = bool(
            payload.get("restaging_update_required") or metastatic_context.get("restaging_update_required")
        )
        payload["restaging_update_reason"] = (
            payload.get("restaging_update_reason")
            or metastatic_context.get("restaging_update_reason")
            or ""
        )
        return payload

    def _resolve_state_family(self, state: str, payload: dict[str, Any]) -> tuple[str, str]:
        metastatic_context = resolve_metastatic_state_context(payload)
        metastatic_stage_resolved = str(metastatic_context.get("metastatic_stage_resolved") or "M0").strip()
        testosterone = _safe_float(payload.get("testosterone_value"))
        castrate_confirmed = str(payload.get("castrate_testosterone_status") or "").strip() == "confirmed_castrate"
        if testosterone is not None and testosterone <= 50:
            castrate_confirmed = True
        imaging_status = _normalize_text(payload.get("conventional_imaging_status")).upper()
        psma_rads = _normalize_text(payload.get("psma_rads_score"))
        psma_uptake = _normalize_text(payload.get("psma_uptake_pattern")).lower()
        progression_pattern = _normalize_text(payload.get("progression_pattern")).lower()
        if metastatic_stage_resolved != "M0":
            if not castrate_confirmed:
                return "adt_progression_verification", "M1 ya documentado; falta testosterona en rango de castración para cerrar enfermedad resistente."
            if progression_pattern in {"mixed", "discordant"} or psma_rads == "3" or psma_uptake in {"indeterminado", "discordante"}:
                return "adt_progression_verification", "M1 ya documentado, pero la trayectoria sigue discordante y obliga a correlacionar progresión resistente antes de cerrar m1 CRPC."
            return "m1_crpc", "La castración ya está confirmada y el caso ya corresponde a enfermedad metastásica (M1)."
        if state != "adt_progression_verification":
            return state, ""
        if not castrate_confirmed:
            return "adt_progression_verification", "Falta testosterona en rango de castración para salir del carril de verificación."
        if progression_pattern in {"mixed", "discordant"} or psma_rads == "3" or psma_uptake in {"indeterminado", "discordante"}:
            return "adt_progression_verification", "La discordancia entre progresión, PSMA o imagen convencional obliga a correlacionar antes de cerrar M0/M1 CRPC."
        if imaging_status not in {"M0", "M1", "M1A", "M1B", "M1C"}:
            return "adt_progression_verification", "Falta reestadificación convencional suficiente para cerrar M0 vs M1."
        if imaging_status.startswith("M1"):
            return "m1_crpc", "La castración ya está confirmada y la imagen convencional ya define enfermedad metastásica (M1)."
        return "m0_crpc", "La castración ya está confirmada y la imagen convencional sostiene enfermedad no metastásica (M0)."

    def _evaluate_rule_based(self, state_family: str, payload: dict[str, Any]) -> dict[str, Any]:
        if state_family == "adt_progression_verification":
            return self.adt_service.evaluate(payload)
        if state_family == "m0_crpc":
            return self.m0_service.evaluate(payload)
        return self.m1_service.evaluate(payload)

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

    def _build_rule_based_recommendation(
        self,
        *,
        state_family: str,
        module_result: dict[str, Any],
        routing_reason: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        eligible = list(module_result.get("eligible_treatments") or [])
        primary = eligible[0] if eligible else {}
        preferred_regimen = dict(module_result.get("preferred_frontline_regimen") or {})
        sequence_bundle = dict(module_result.get("sequence_transition_bundle") or {})
        action = _normalize_text(primary.get("name") if isinstance(primary, dict) else primary)
        rationale = _normalize_text((primary.get("notes") if isinstance(primary, dict) else "") or module_result.get("recommended_trajectory") or module_result.get("report_sections", {}).get("summary"))
        preferred_label = _normalize_text(preferred_regimen.get("name") or preferred_regimen.get("regimen_label"))
        trigger_status = _normalize_text(sequence_bundle.get("trigger_status"))
        if preferred_label and trigger_status in {"switch", "intensify", "continue", "confirm"}:
            if trigger_status == "continue":
                action = f"Continuar {preferred_label}"
            elif trigger_status == "confirm":
                action = "Completar datos críticos y recalcular secuencia"
            else:
                action = f"Priorizar {preferred_label}"
            rationale = _normalize_text(sequence_bundle.get("line_change_reason") or rationale)
        original_state = _normalize_text(payload.get("effective_state"))
        if original_state == "adt_progression_verification" and state_family in {"m0_crpc", "m1_crpc"}:
            action = (
                "Redirigir a M1 CRPC y abrir secuenciación terapéutica"
                if state_family == "m1_crpc"
                else "Redirigir a M0 CRPC y reevaluar intensificación"
            )
            rationale = routing_reason or rationale
        if state_family == "adt_progression_verification":
            testosterone = _safe_float(payload.get("testosterone_value") or payload.get("testosterone"))
            castrate_confirmed = str(payload.get("castrate_testosterone_status") or "").strip() == "confirmed_castrate"
            if testosterone is not None and testosterone <= 50:
                castrate_confirmed = True
            psma_rads = _normalize_text(payload.get("psma_rads_score"))
            psma_uptake = _normalize_text(payload.get("psma_uptake_pattern")).lower()
            progression_pattern = _normalize_text(payload.get("progression_pattern")).lower()
            if not castrate_confirmed:
                action = "Optimizar ADT y confirmar testosterona en rango de castración"
                rationale = "Sin castración confirmada no debe secuenciarse el caso como CRPC; la prioridad es corregir u optimizar el backbone de ADT."
            elif progression_pattern in {"mixed", "discordant"} or psma_rads == "3" or psma_uptake in {"indeterminado", "discordante"}:
                action = "Correlacionar testosterona, imagen convencional y PSMA antes de cerrar CRPC"
                rationale = routing_reason or "La evidencia actual sigue siendo discordante y requiere correlación clínica/imaging antes de mover el caso a M0/M1 CRPC."
        return {
            "source": "rule_based_primary",
            "state_family": state_family,
            "recommended_action": action or _normalize_text(module_result.get("recommended_trajectory")) or "Sin recomendación estructurada",
            "recommendation_family": _structured_recommendation_family(preferred_regimen, sequence_bundle, _treatment_family(action or state_family)),
            "rationale": rationale,
            "guideline_basis": self._guideline_basis(module_result),
            "routing_reason": routing_reason,
        }

    def _build_sequence_candidates(
        self,
        patient: dict[str, Any],
        payload: dict[str, Any],
        *,
        state_family: str,
        safety_gates: list[dict[str, Any]],
        module_result: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if state_family == "adt_progression_verification":
            requires_correlation = (
                _normalize_text(payload.get("progression_pattern")).lower() in {"mixed", "discordant"}
                or _normalize_text(payload.get("psma_rads_score")) == "3"
                or _normalize_text(payload.get("psma_uptake_pattern")).lower() in {"indeterminado", "discordante"}
            )
            return [
                CRPCSequenceCandidate(
                    line_number=1,
                    drug="verification_pathway",
                    drug_label=(
                        "Correlacionar testosterona, imagen convencional y PSMA"
                        if requires_correlation
                        else "Completar verificación de castración y reestadificación convencional"
                    ),
                    regimen_code="ADT_MONO",
                    regimen_label="ADT sola",
                    evidence_level="guideline",
                    expected_os_months=None,
                    expected_pfs_months=None,
                    confidence=0.72,
                    is_preferred=True,
                    biomarker_driven=False,
                    blocked=False,
                    blocked_by=[],
                    rationale="Antes de secuenciar CRPC debe cerrarse la verificación clínica, de castración e imagen.",
                    formulary=[],
                ).to_dict()
            ]
        psadt = _safe_float(payload.get("psadt_months"))
        if state_family == "m0_crpc" and psadt is not None and psadt > 10:
            return [
                CRPCSequenceCandidate(
                    line_number=1,
                    drug="monitoring_only",
                    drug_label="Vigilancia estrecha con ADT",
                    regimen_code="ADT_MONO",
                    regimen_label="ADT sola",
                    evidence_level="guideline",
                    expected_os_months=None,
                    expected_pfs_months=None,
                    confidence=0.78,
                    is_preferred=True,
                    biomarker_driven=False,
                    blocked=False,
                    blocked_by=[],
                    rationale="PSADT >10 meses favorece observación estrecha antes de intensificar con ARPI.",
                    formulary=["IMSS", "ISSSTE", "privado"],
                ).to_dict()
            ]
        runtime_patient = dict(patient)
        runtime_patient["reconciled_state"] = state_family
        runtime_patient.setdefault("genomic_profile", patient.get("genomic_profile") or patient.get("genomics") or {})
        try:
            plan = self.sequencer.optimize(runtime_patient)
            raw_lines = [line.to_dict() if hasattr(line, "to_dict") else asdict(line) for line in plan.lines]
        except Exception:
            raw_lines = []
        preferred_rule_label = ""
        if module_result.get("eligible_treatments"):
            first = module_result.get("eligible_treatments")[0]
            if isinstance(first, dict):
                preferred_rule_label = _normalize_text(first.get("name"))
        card_context = state_family == "m1_crpc" and _has_card_sequence_context(payload)
        prior_therapy_text = " ".join(str(item).lower() for item in (payload.get("prior_therapy") or []))
        first_line_standard_arpi_context = (
            state_family == "m1_crpc"
            and _normalize_text(payload.get("mcrpc_line_context") or payload.get("line_context")).lower() in {"pre_arpi", "first_line_mcrpc", "first_line", "line_1"}
            and not any(token in prior_therapy_text for token in ARPI_TOKENS)
        )
        candidates: list[CRPCSequenceCandidate] = []
        for item in raw_lines[:5]:
            drug_label = _normalize_text(item.get("drug_label") or item.get("label") or item.get("drug"))
            regimen_code = normalize_regimen_code(item.get("regimen_code") or drug_label or item.get("drug"))
            regimen_bundle = regimen_metadata_bundle(regimen_code)
            blocked_by = self._blocked_by(drug_label, safety_gates)
            if card_context and _treatment_family(drug_label) == "arpi":
                blocked_by = list(dict.fromkeys(blocked_by + ["Evitar ARPI -> ARPI injustificado"]))
            candidates.append(
                CRPCSequenceCandidate(
                    line_number=int(item.get("line_number") or 0),
                    drug=_normalize_text(item.get("drug")),
                    drug_label=drug_label,
                    regimen_code=regimen_bundle.get("regimen_code", regimen_code if regimen_code else ""),
                    regimen_label=regimen_bundle.get("regimen_label", ""),
                    evidence_level=_normalize_text(item.get("evidence_level")),
                    expected_os_months=_safe_float(item.get("expected_os_months")),
                    expected_pfs_months=_safe_float(item.get("expected_pfs_months")),
                    confidence=float(item.get("confidence") or 0),
                    is_preferred=bool(item.get("is_preferred")) or (card_context and _treatment_family(drug_label) == "taxane"),
                    biomarker_driven=bool(item.get("biomarker_driven")),
                    blocked=bool(blocked_by),
                    blocked_by=blocked_by,
                    rationale=_normalize_text(item.get("rationale")),
                    formulary=list(item.get("formulary") or []),
                    component_drugs=list(regimen_bundle.get("component_drugs") or []),
                    dose=str(regimen_bundle.get("dose") or ""),
                    route=str(regimen_bundle.get("route") or ""),
                    schedule=str(regimen_bundle.get("schedule") or ""),
                    imss_key=str(regimen_bundle.get("imss_key") or ""),
                    description=str(regimen_bundle.get("description") or ""),
                )
            )
        if card_context and candidates:
            candidates.sort(
                key=lambda candidate: (
                    0 if "cabazitax" in candidate.drug_label.lower() else 1,
                    0 if _treatment_family(candidate.drug_label) == "taxane" else 1,
                    1 if _treatment_family(candidate.drug_label) == "arpi" else 0,
                    0 if candidate.is_preferred else 1,
                    1 if candidate.blocked else 0,
                    candidate.line_number or 99,
                )
            )
        elif first_line_standard_arpi_context and candidates:
            candidates.sort(
                key=lambda candidate: (
                    0 if "enzalut" in candidate.drug_label.lower() else 1,
                    0 if "abirater" in candidate.drug_label.lower() else 1,
                    0 if candidate.is_preferred else 1,
                    1 if candidate.blocked else 0,
                    candidate.line_number or 99,
                )
            )
        if preferred_rule_label and candidates:
            candidates.sort(
                key=lambda candidate: (
                    0 if self._concordance_label(preferred_rule_label, candidate.drug_label) == "concordant" else 1,
                    0 if card_context and "cabazitax" in candidate.drug_label.lower() else 1,
                    0 if card_context and _treatment_family(candidate.drug_label) == "taxane" else 1,
                    0 if first_line_standard_arpi_context and "enzalut" in candidate.drug_label.lower() else 1,
                    0 if first_line_standard_arpi_context and "abirater" in candidate.drug_label.lower() else 1,
                    1 if card_context and _treatment_family(candidate.drug_label) == "arpi" else 0,
                    0 if candidate.is_preferred else 1,
                    1 if candidate.blocked else 0,
                    candidate.line_number or 99,
                )
            )
        if module_result.get("eligible_treatments"):
            candidates = []
        for index, item in enumerate(module_result.get("eligible_treatments") or [], start=1):
            if not isinstance(item, dict):
                continue
            drug_label = _normalize_text(item.get("name"))
            regimen_code = normalize_regimen_code(item.get("regimen_code") or drug_label)
            regimen_bundle = regimen_metadata_bundle(regimen_code)
            blocked_by = self._blocked_by(drug_label, safety_gates)
            if card_context and _treatment_family(drug_label) == "arpi":
                blocked_by = list(dict.fromkeys(blocked_by + ["Evitar ARPI -> ARPI injustificado"]))
            candidates.append(
                CRPCSequenceCandidate(
                    line_number=index,
                    drug=drug_label.lower().replace(" ", "_"),
                    drug_label=drug_label,
                    regimen_code=regimen_bundle.get("regimen_code", regimen_code if regimen_code else ""),
                    regimen_label=regimen_bundle.get("regimen_label", ""),
                    evidence_level="guideline",
                    expected_os_months=None,
                    expected_pfs_months=None,
                    confidence=0.5,
                    is_preferred=(str(item.get("priority") or "").lower() in {"preferred", "preferente"}) or (card_context and _treatment_family(drug_label) == "taxane"),
                    biomarker_driven=_treatment_family(drug_label) in {"parp", "psma_rlt", "immunotherapy"},
                    blocked=bool(blocked_by),
                    blocked_by=blocked_by,
                    rationale=_normalize_text(item.get("notes")),
                    component_drugs=list(item.get("component_drugs") or regimen_bundle.get("component_drugs") or []),
                    dose=str(item.get("dose") or regimen_bundle.get("dose") or ""),
                    route=str(item.get("route") or regimen_bundle.get("route") or ""),
                    schedule=str(item.get("schedule") or regimen_bundle.get("schedule") or ""),
                    imss_key=str(item.get("imss_key") or regimen_bundle.get("imss_key") or ""),
                    description=str(item.get("description") or regimen_bundle.get("description") or item.get("notes") or ""),
                )
            )
        if candidates:
            if card_context:
                candidates.sort(
                    key=lambda candidate: (
                        0 if "cabazitax" in candidate.drug_label.lower() else 1,
                        0 if _treatment_family(candidate.drug_label) == "taxane" else 1,
                        1 if _treatment_family(candidate.drug_label) == "arpi" else 0,
                        0 if candidate.is_preferred else 1,
                        1 if candidate.blocked else 0,
                        candidate.line_number or 99,
                    )
                )
            elif first_line_standard_arpi_context:
                candidates.sort(
                    key=lambda candidate: (
                        0 if "enzalut" in candidate.drug_label.lower() else 1,
                        0 if "abirater" in candidate.drug_label.lower() else 1,
                        0 if candidate.is_preferred else 1,
                        1 if candidate.blocked else 0,
                        candidate.line_number or 99,
                    )
                )
            if preferred_rule_label:
                candidates.sort(
                    key=lambda candidate: (
                        0 if self._concordance_label(preferred_rule_label, candidate.drug_label) == "concordant" else 1,
                        0 if card_context and "cabazitax" in candidate.drug_label.lower() else 1,
                        0 if card_context and _treatment_family(candidate.drug_label) == "taxane" else 1,
                        0 if first_line_standard_arpi_context and "enzalut" in candidate.drug_label.lower() else 1,
                        0 if first_line_standard_arpi_context and "abirater" in candidate.drug_label.lower() else 1,
                        1 if card_context and _treatment_family(candidate.drug_label) == "arpi" else 0,
                        0 if candidate.is_preferred else 1,
                        1 if candidate.blocked else 0,
                        candidate.line_number or 99,
                    )
                )
            return [candidate.to_dict() for candidate in candidates[:3]]
        if candidates:
            return [candidate.to_dict() for candidate in candidates[:3]]
        return []

    def _build_safety_gates(
        self,
        payload: dict[str, Any],
        patient: dict[str, Any],
        *,
        state_family: str,
        psma_profile: dict[str, Any],
        labs_profile: dict[str, Any],
    ) -> list[dict[str, Any]]:
        gates: list[CRPCSafetyGate] = []
        testosterone = _safe_float(payload.get("testosterone_value"))
        castrate_ok = testosterone is not None and testosterone <= 50
        gates.append(
            CRPCSafetyGate(
                gate_key="castration_confirmed",
                label="Castración confirmada",
                status="pass" if castrate_ok else "blocked",
                rationale="La testosterona ya está en rango de castración." if castrate_ok else "Sin testosterona en rango de castración no debe cerrarse como CRPC.",
                failure_family="castration" if not castrate_ok else "",
            )
        )
        imaging_status = _normalize_text(payload.get("conventional_imaging_status")).upper()
        imaging_ok = imaging_status in {"M0", "M1", "M1A", "M1B", "M1C"} if state_family == "adt_progression_verification" else True
        gates.append(
            CRPCSafetyGate(
                gate_key="conventional_imaging_routed",
                label="Reestadificación convencional",
                status="pass" if imaging_ok else "blocked",
                rationale="La imagen convencional ya define el carril M0/M1." if imaging_ok else "Falta imagen convencional suficiente para definir M0 vs M1.",
                failure_family="imaging" if not imaging_ok else "",
            )
        )
        ast = _safe_float(payload.get("ast"))
        alt = _safe_float(payload.get("alt"))
        bilirubin = _safe_float(payload.get("bilirubin"))
        abiraterone_clear = not (
            (ast is not None and ast > 120)
            or (alt is not None and alt > 120)
            or (bilirubin is not None and bilirubin > 2)
        )
        gates.append(
            CRPCSafetyGate(
                gate_key="abiraterone_hepatic_clearance",
                label="Seguridad hepática para abiraterona",
                status="pass" if abiraterone_clear else "blocked",
                rationale="No hay señal hepática que bloquee abiraterona." if abiraterone_clear else "AST/ALT o bilirrubina elevadas bloquean abiraterona en este ciclo.",
                candidate_drugs=["Abiraterona", "Niraparib + Abiraterona", "Ipatasertib + Abiraterona"],
                failure_family="LFT" if not abiraterone_clear else "",
            )
        )
        psma_ready = bool(psma_profile.get("available")) and bool(psma_profile.get("structured_complete")) and not bool(psma_profile.get("psma_negative_dominant_lesions"))
        gates.append(
            CRPCSafetyGate(
                gate_key="psma_rlt_eligibility",
                label="Elegibilidad PSMA/Lu-177",
                status="pass" if psma_ready else "blocked",
                rationale="PSMA estructurado suficiente y sin lesiones dominantes PSMA-negativas." if psma_ready else "PSMA incompleto, parcial o discordante: no mostrar elegibilidad plena a Lu-177.",
                candidate_drugs=["Lu-177 PSMA-617"],
                failure_family="PSMA" if not psma_ready else "",
            )
        )
        biomarker_source = _normalize_text(payload.get("biomarker_source"))
        hrr_gene = _normalize_text(payload.get("hrr_gene"))
        hrr_positive = _normalize_text(payload.get("hrr_status")).lower() in {"positivo", "positive", "pathogenic"} or _normalize_text(payload.get("brca2_status")).lower() in {"positivo", "positive", "pathogenic"}
        hrr_traceable = (not hrr_positive) or (biomarker_source not in {"", "Desconocido", "Desconocida"} and hrr_gene not in {"", "Desconocido", "Desconocida"})
        gates.append(
            CRPCSafetyGate(
                gate_key="hrr_traceability",
                label="Trazabilidad molecular HRR",
                status="pass" if hrr_traceable else "blocked",
                rationale="El biomarcador HRR es trazable por gen y fuente." if hrr_traceable else "No priorizar PARP sin gen HRR y fuente del biomarcador claramente trazables.",
                candidate_drugs=["Olaparib", "Rucaparib", "Talazoparib + Enzalutamida", "Niraparib + Abiraterona"],
                failure_family="HRR" if not hrr_traceable else "",
            )
        )
        prior_therapy = " ".join(str(item).lower() for item in (payload.get("prior_therapy") or []))
        arpi_rechallenge = any(token in prior_therapy for token in ARPI_TOKENS)
        gates.append(
            CRPCSafetyGate(
                gate_key="arpi_rechallenge_gate",
                label="Evitar ARPI -> ARPI injustificado",
                status="warning" if arpi_rechallenge and state_family == "m1_crpc" else "pass",
                rationale="Ya existe exposición ARPI y debe evitarse un intercambio ARPI-ARPI salvo biomarcador fuerte." if arpi_rechallenge and state_family == "m1_crpc" else "No hay conflicto claro de reutilización ARPI en el carril actual.",
                candidate_drugs=["Enzalutamida", "Abiraterona", "Apalutamida", "Darolutamida"],
                failure_family="sequence_conflict" if arpi_rechallenge and state_family == "m1_crpc" else "",
            )
        )
        for alert in labs_profile.get("active_alerts") or []:
            title = _normalize_text(alert.get("title"))
            if not title:
                continue
            if "hep" in title.lower():
                failure_family = "LFT"
            elif "testoster" in title.lower():
                failure_family = "castration"
            else:
                failure_family = ""
            gates.append(
                CRPCSafetyGate(
                    gate_key=f"lab_alert_{len(gates)}",
                    label=title,
                    status=str(alert.get("severity") or "warning").lower(),
                    rationale=_normalize_text(alert.get("recommended_action") or alert.get("message")),
                    failure_family=failure_family,
                )
            )
        return [gate.to_dict() for gate in gates]

    def _blocked_by(self, drug_label: str, safety_gates: list[dict[str, Any]]) -> list[str]:
        lowered = drug_label.lower()
        blocked = []
        for gate in safety_gates:
            if gate.get("status") not in {"blocked", "warning"}:
                continue
            candidate_drugs = [str(item).lower() for item in gate.get("candidate_drugs") or []]
            applies = not candidate_drugs or any(token in lowered for token in candidate_drugs)
            if gate.get("gate_key") == "arpi_rechallenge_gate" and _treatment_family(drug_label) == "arpi":
                applies = True
            if gate.get("gate_key") == "hrr_traceability" and _treatment_family(drug_label) == "parp":
                applies = True
            if applies:
                blocked.append(gate.get("label") or gate.get("gate_key"))
        return blocked

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
        state_family: str,
        rule_based_recommendation: dict[str, Any],
        sequence_candidates: list[dict[str, Any]],
        blocking_groups: list[dict[str, Any]],
        safety_gates: list[dict[str, Any]],
        preferred_regimen: dict[str, Any],
        sequence_transition_bundle: dict[str, Any],
    ) -> dict[str, Any]:
        unblocked = next((item for item in sequence_candidates if not item.get("blocked")), None)
        top_candidate = unblocked or (sequence_candidates[0] if sequence_candidates else None)
        if not top_candidate:
            return {
                "available": False,
                "status": "unavailable",
                "recommended_action": "",
                "sequence_candidate": {},
                "concordance_label": "rule_only",
                "shadow_reasons": ["No hay candidato terapéutico secuenciado todavía."],
            }
        recommended_action = _normalize_text(top_candidate.get("drug_label"))
        concordance = self._concordance_label(
            rule_based_recommendation.get("recommended_action", ""),
            recommended_action,
        )
        hard_blocked = any(group.get("required_fields") for group in blocking_groups)
        safety_blocked = bool(top_candidate.get("blocked"))
        if top_candidate.get("blocked"):
            status = "shadow-blocked"
        elif runtime_mode == "advisory" and not hard_blocked and concordance != "discordant":
            status = "advisory_candidate"
        else:
            status = "shadow"
        return {
            "available": True,
            "status": status,
            "recommended_action": recommended_action,
            "recommendation_family": _structured_recommendation_family(
                dict(preferred_regimen or {}),
                dict(sequence_transition_bundle or {}),
                _treatment_family(recommended_action),
            ),
            "sequence_candidate": top_candidate,
            "concordance_label": concordance,
            "shadow_reasons": [
                "La recomendación AI permanece en shadow hasta que QA apruebe y no existan blockers duros."
                if runtime_mode == "shadow"
                else "La recomendación AI solo puede presentarse si sigue siendo concordante con la ruta primaria."
            ] + (
                [gate.get("label") for gate in safety_gates if gate.get("status") == "blocked"][:3]
                if safety_blocked else []
            ),
        }

    def _concordance_label(self, rule_action: str, overlay_action: str) -> str:
        if not rule_action or not overlay_action:
            return "rule_only"
        if _normalize_for_compare(rule_action) == _normalize_for_compare(overlay_action):
            return "concordant"
        if _treatment_family(rule_action) == _treatment_family(overlay_action):
            return "adjacent"
        return "discordant"

    def _run_qa_validation(
        self,
        patient: dict[str, Any],
        *,
        state_family: str,
        overlay: dict[str, Any],
        rule_based_recommendation: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        action = overlay.get("recommended_action") or rule_based_recommendation.get("recommended_action")
        recommendation = AgentRecommendation(
            action=action,
            category="treatment",
            priority="high",
            evidence_basis=list(rule_based_recommendation.get("guideline_basis") or []),
        )
        qa_record = dict(patient)
        qa_record["reconciled_state"] = state_family
        baseline = dict(qa_record.get("baseline") or {})
        for key in ("ast", "alt", "bilirubin", "testosterone_baseline", "testosterone", "conventional_imaging_status", "seizure_history", "ecog_score"):
            if _is_present(payload.get(key)):
                target_key = "testosterone_baseline" if key in {"testosterone", "testosterone_baseline"} else key
                baseline[target_key] = payload.get(key)
        qa_record["baseline"] = baseline
        if not qa_record.get("genomic_profile") and qa_record.get("genomics"):
            qa_record["genomic_profile"] = dict(qa_record.get("genomics") or {})
        qa_output = AgentOutput(
            agent_id="crpc_copilot_overlay",
            patient_id=int((patient.get("identity") or {}).get("id") or 0),
            recommendations=[recommendation],
            confidence_score=72.0 if overlay.get("available") else 50.0,
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
                "source": "crpc_copilot_advisory",
                "recommended_action": ai_overlay.get("recommended_action"),
                "recommendation_family": ai_overlay.get("recommendation_family"),
                "rationale": "Overlay AI presentado porque pasó QA, no hay blockers duros y la recomendación sigue siendo concordante con la ruta primaria.",
            }
        return dict(rule_based_recommendation)

    def _build_why_changed_today(
        self,
        payload: dict[str, Any],
        *,
        state_family: str,
        routing_reason: str,
        safety_gates: list[dict[str, Any]],
        pivotal_gates_delta: dict[str, Any] | None = None,
    ) -> list[str]:
        notes = []
        testosterone = _safe_float(payload.get("testosterone_value"))
        if testosterone is not None:
            notes.append(f"Testosterona actual {testosterone:g} ng/dL.")
        psadt = _safe_float(payload.get("psadt_months"))
        if psadt is not None:
            notes.append(f"PSADT actual {psadt:.1f} meses.")
        imaging_status = _normalize_text(payload.get("conventional_imaging_status")).upper()
        if imaging_status:
            notes.append(f"Imagen convencional {imaging_status}.")
        if _normalize_text(payload.get("psma_stage_after_psma")):
            notes.append(f"PSMA estructurado {payload.get('psma_stage_after_psma')}.")
        current_treatment = _normalize_text(payload.get("current_treatment") or payload.get("drug_scheme"))
        if current_treatment:
            notes.append(f"Línea sistémica actual: {current_treatment}.")
        if routing_reason:
            notes.append(routing_reason)
        blocked = [gate.get("label") for gate in safety_gates if gate.get("status") == "blocked"]
        if blocked:
            notes.append(f"Bloqueos de seguridad activos: {', '.join(blocked[:3])}.")
        if state_family == "m1_crpc" and not blocked:
            notes.append("La secuenciación mCRPC puede recalcularse hoy con biomarcadores, línea previa y seguridad.")
        # Faubot 2026-04-25 (IX) — narrativa clínica del delta de gates pivotal.
        if pivotal_gates_delta:
            from prostanet.shared.pivotal_gate_delta import (
                describe_gate_delta_in_clinical_language,
            )
            gate_notes = describe_gate_delta_in_clinical_language(pivotal_gates_delta)
            notes.extend(gate_notes)
        return notes[:8]  # +2 slots por las nuevas narrativas de delta

    def _build_schedule_overlay(
        self,
        *,
        state_family: str,
        blocking_groups: list[dict[str, Any]],
        safety_gates: list[dict[str, Any]],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if state_family == "adt_progression_verification":
            primary_intent = "Confirmar castración y cerrar reestadificación convencional"
            cadence = ["Testosterona sérica en corto plazo", "Imagen convencional para definir M0 vs M1"]
        elif state_family == "m0_crpc":
            primary_intent = "Vigilar cinética PSA/PSADT y decidir intensificación ARPI"
            cadence = ["PSA y PSADT seriados", "Revisión de riesgo neurológico/cardiovascular antes de ARPI"]
        else:
            primary_intent = "Secuenciar tratamiento mCRPC con seguridad activa y biomarcadores"
            cadence = ["Laboratorios de seguridad antes y durante la línea", "PSMA/HRR si cambian elegibilidad terapéutica"]
        blocked_summary = [group.get("group_label") for group in blocking_groups if group.get("required_fields")]
        safety_summary = [gate.get("label") for gate in safety_gates if gate.get("status") == "blocked"]
        return {
            "schedule_primary_intent": primary_intent,
            "cadence_adjustment_reasons": cadence + blocked_summary[:2] + safety_summary[:2],
            "recommended_events": cadence[:3],
            "current_treatment": _normalize_text(payload.get("current_treatment") or payload.get("drug_scheme")),
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

    def _ddi_patient(self, patient: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        current_treatment = _normalize_text(payload.get("current_treatment") or payload.get("drug_scheme"))
        return {
            "current_treatment": current_treatment,
            "oncology_drugs": [current_treatment] if current_treatment else [],
            "current_medications": payload.get("current_medications") or patient.get("current_medications") or "",
            "seizure_history": payload.get("seizure_history") or patient.get("baseline", {}).get("seizure_history"),
            "institution": payload.get("institution") or patient.get("identity", {}).get("institution") or "IMSS",
        }


def build_crpc_copilot_bundle(
    patient: dict[str, Any],
    *,
    effective_state: str = "",
    effective_management_track: str = "",
    latest_assessment: dict[str, Any] | None = None,
    longitudinal_bundle: dict[str, Any] | None = None,
    decision_input_requirements: dict[str, Any] | None = None,
    trigger_event: str = "",
) -> dict[str, Any]:
    service = CRPCCopilotService()
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
    "CRPCCopilotService",
    "build_crpc_copilot_bundle",
    "CRPC_VERTICAL_STATES",
]
