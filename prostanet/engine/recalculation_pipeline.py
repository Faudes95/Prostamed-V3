"""
Recalculation Pipeline — event-driven clinical decision cascade.

When ANY new clinical data arrives (lab, imaging, visit, treatment change),
this pipeline:
  1. Loads the patient's full record
  2. Re-classifies the clinical state
  3. Runs all triggered agents
  4. QAA validates every agent output
  5. Computes composite confidence
  6. Generates clinical explanation
  7. Persists audit trail

Properties: idempotent, auditable, event-driven, feature-flag gated.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict
from typing import Any

logger = logging.getLogger(__name__)


class RecalculationPipeline:
    """
    Orchestrates the full agent cascade on each clinical event.

    Usage::

        pipeline = RecalculationPipeline()
        result = pipeline.run(patient_id=29, trigger_event="visit_recorded")
    """

    def __init__(
        self,
        model_registry: Any | None = None,
        module_registry: Any | None = None,
    ) -> None:
        self.model_registry = model_registry
        self.module_registry = module_registry

    def run(
        self,
        patient_id: int,
        trigger_event: str,
        trigger_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Execute the full recalculation pipeline for one patient.

        Returns a dict with: recommendations, confidence, explanation,
        alerts, agent_outputs, audit_ids, timing.
        """
        from prostanet.shared.feature_flags import resolve_feature_flags
        from prostanet.ai.config import get_ai_config

        flags = resolve_feature_flags()
        runtime_mode = get_ai_config().runtime_mode
        if not flags.get("ENABLE_RECALCULATION_ENGINE"):
            return {
                "skipped": True,
                "reason": "ENABLE_RECALCULATION_ENGINE is OFF",
                "runtime_mode": runtime_mode,
                "rule_based_source_of_truth": True,
                "advisory_only": True,
            }

        t0 = time.perf_counter()
        trigger_data = trigger_data or {}
        result: dict[str, Any] = {
            "patient_id": patient_id,
            "trigger_event": trigger_event,
            "runtime_mode": runtime_mode,
            "rule_based_source_of_truth": True,
            "advisory_only": True,
            "agent_outputs": [],
            "qa_validations": [],
            "alerts": [],
            "audit_ids": [],
        }

        # ── Step 1: Load patient record ──
        record = self._load_record(patient_id)
        if not record:
            return {"error": f"Patient {patient_id} not found"}

        state = record.get("reconciled_state", "")
        result["state"] = state
        result["input_snapshot"] = self._build_input_snapshot(record, trigger_event, trigger_data)

        # ── Step 2: Re-classify state ──
        new_state = self._reclassify_state(record)
        if new_state and new_state != state:
            result["state_changed"] = True
            result["previous_state"] = state
            result["state"] = new_state
            record["reconciled_state"] = new_state
            # If state changed, fire a state_transition event recursively
            if trigger_event != "state_transition":
                trigger_data["detected_transition"] = {
                    "from": state,
                    "to": new_state,
                }

        # ── Step 3: Build agent input ──
        from prostanet.agents.contracts import AgentInput
        from datetime import datetime

        agent_input = AgentInput(
            patient_id=patient_id,
            record=record,
            trigger_event=trigger_event,
            trigger_data=trigger_data,
            timestamp=datetime.utcnow().isoformat(),
        )

        # ── Step 4: Run triggered agents ──
        agent_outputs = self._run_agents(agent_input, flags)
        result["agent_outputs"] = agent_outputs
        result["model_outputs"] = self._collect_model_outputs(agent_outputs)

        # ── Step 5: QA validation ──
        qa_results = self._validate_outputs(agent_outputs, record, flags)
        result["qa_validations"] = qa_results
        result["qa_passed"] = bool(qa_results) and all(v.get("approved", False) for v in qa_results)

        # ── Step 6: Confidence scoring ──
        confidence = self._compute_confidence(record, agent_outputs)
        result["confidence"] = confidence

        # ── Step 7: Explanation ──
        explanation = self._generate_explanation(
            record, agent_outputs, confidence
        )
        result["explanation"] = explanation

        # ── Step 8: Collect alerts ──
        for out in agent_outputs:
            result["alerts"].extend(out.get("alerts", []))

        # ── Step 9: Audit log ──
        audit_ids = self._persist_audit(
            patient_id, trigger_event, trigger_data,
            agent_outputs, qa_results
        )
        result["audit_ids"] = audit_ids
        result["final_advisory_recommendation"] = self._build_final_advisory_recommendation(
            agent_outputs,
            qa_results,
            runtime_mode,
        )
        result["degraded_to_rule_based"] = (
            not bool(agent_outputs)
            or (bool(qa_results) and not bool(result["qa_passed"]))
        )

        # ── Timing ──
        result["execution_time_ms"] = int((time.perf_counter() - t0) * 1000)

        return result

    @staticmethod
    def _load_record(patient_id: int) -> dict[str, Any] | None:
        try:
            from tracking_db import get_patient_full_record
            return get_patient_full_record(patient_id)
        except Exception as exc:
            logger.error("Failed to load patient %s: %s", patient_id, exc)
            return None

    @staticmethod
    def _reclassify_state(record: dict) -> str | None:
        try:
            from prostanet.domains.state_classifier.service import (
                StateClassifierService,
            )
            payload: dict[str, Any] = {}
            payload.update(record.get("identity", {}) or {})
            payload.update(record.get("baseline", {}) or {})
            fups = record.get("follow_ups") or record.get("follow_up_visits") or []
            if fups:
                payload.update(fups[-1])
            result = StateClassifierService.classify(payload)
            return result.get("state")
        except Exception as exc:
            logger.debug("State reclassification failed: %s", exc)
            return None

    def _run_agents(
        self, agent_input: Any, flags: dict[str, bool]
    ) -> list[dict[str, Any]]:
        """Instantiate and run each enabled agent."""
        outputs: list[dict[str, Any]] = []

        agent_specs = [
            ("ENABLE_AGENT_CDA", self._run_cda),
            ("ENABLE_AGENT_PSA", self._run_psa),
            ("ENABLE_AGENT_TOA", self._run_toa),
            ("ENABLE_AGENT_RIA", self._run_ria),
        ]

        for flag_key, runner in agent_specs:
            if not flags.get(flag_key):
                continue
            try:
                out = runner(agent_input)
                if out:
                    outputs.append(out)
            except Exception as exc:
                logger.debug("Agent %s failed: %s", flag_key, exc)

        return outputs

    def _run_cda(self, agent_input: Any) -> dict[str, Any] | None:
        from prostanet.agents.clinical_decision_agent import ClinicalDecisionAgent
        agent = ClinicalDecisionAgent(
            model_registry=self.model_registry,
            module_registry=self.module_registry,
        )
        if not agent.should_trigger(agent_input.trigger_event, agent_input.trigger_data):
            return None
        output = agent.evaluate_safe(agent_input)
        return self._output_to_dict(output)

    def _run_psa(self, agent_input: Any) -> dict[str, Any] | None:
        from prostanet.agents.progression_surveillance_agent import (
            ProgressionSurveillanceAgent,
        )
        agent = ProgressionSurveillanceAgent(model_registry=self.model_registry)
        if not agent.should_trigger(agent_input.trigger_event, agent_input.trigger_data):
            return None
        output = agent.evaluate_safe(agent_input)
        return self._output_to_dict(output)

    def _run_toa(self, agent_input: Any) -> dict[str, Any] | None:
        from prostanet.agents.treatment_optimization_agent import (
            TreatmentOptimizationAgent,
        )
        agent = TreatmentOptimizationAgent(model_registry=self.model_registry)
        if not agent.should_trigger(agent_input.trigger_event, agent_input.trigger_data):
            return None
        output = agent.evaluate_safe(agent_input)
        return self._output_to_dict(output)

    def _run_ria(self, agent_input: Any) -> dict[str, Any] | None:
        from prostanet.agents.research_intelligence_agent import (
            ResearchIntelligenceAgent,
        )
        agent = ResearchIntelligenceAgent()
        if not agent.should_trigger(agent_input.trigger_event, agent_input.trigger_data):
            return None
        output = agent.evaluate_safe(agent_input)
        return self._output_to_dict(output)

    @staticmethod
    def _validate_outputs(
        outputs: list[dict], record: dict, flags: dict[str, bool]
    ) -> list[dict[str, Any]]:
        """Run QAA on each CDA output."""
        if not flags.get("ENABLE_AGENT_QAA"):
            return []

        from prostanet.agents.quality_assurance_agent import QualityAssuranceAgent
        from prostanet.agents.contracts import AgentOutput, AgentRecommendation

        qaa = QualityAssuranceAgent()
        validations: list[dict[str, Any]] = []

        for out in outputs:
            if out.get("agent_id") != "clinical_decision_agent":
                continue
            # Reconstruct minimal AgentOutput for validation
            recs = []
            for r in out.get("recommendations", []):
                recs.append(AgentRecommendation(
                    action=r.get("action", ""),
                    category=r.get("category", ""),
                    priority=r.get("priority", "standard"),
                    evidence_basis=r.get("evidence_basis", []),
                ))
            fake_output = AgentOutput(
                agent_id=out.get("agent_id", ""),
                patient_id=out.get("patient_id", 0),
                recommendations=recs,
            )
            try:
                qa = qaa.validate(fake_output, record)
                validations.append(asdict(qa))
            except Exception as exc:
                logger.debug("QAA validation failed: %s", exc)

        return validations

    def _compute_confidence(
        self, record: dict, outputs: list[dict]
    ) -> dict[str, Any]:
        try:
            from prostanet.engine.confidence_scoring import ConfidenceScorer
            scorer = ConfidenceScorer()
            return scorer.score(record, outputs)
        except Exception as exc:
            logger.debug("Confidence scoring failed: %s", exc)
            return {"composite_score": 0, "action_level": "low"}

    @staticmethod
    def _build_input_snapshot(
        record: dict[str, Any],
        trigger_event: str,
        trigger_data: dict[str, Any],
    ) -> dict[str, Any]:
        follow_ups = record.get("follow_ups") or record.get("follow_up_visits") or []
        treatments = record.get("treatments") or record.get("treatment_history") or []
        latest_visit = follow_ups[-1] if follow_ups else {}
        return {
            "trigger_event": trigger_event,
            "trigger_keys": sorted(trigger_data.keys()),
            "state": record.get("reconciled_state", ""),
            "follow_up_count": len(follow_ups),
            "treatment_count": len(treatments),
            "latest_visit_date": latest_visit.get("visit_date") or latest_visit.get("sample_date"),
        }

    @staticmethod
    def _collect_model_outputs(outputs: list[dict[str, Any]]) -> dict[str, Any]:
        collected: dict[str, Any] = {}
        for out in outputs:
            metadata = out.get("metadata", {}) or {}
            ai_predictions = metadata.get("ai_predictions", {}) or {}
            for model_id, payload in ai_predictions.items():
                collected[model_id] = payload
        return collected

    @staticmethod
    def _build_final_advisory_recommendation(
        outputs: list[dict[str, Any]],
        qa_results: list[dict[str, Any]],
        runtime_mode: str,
    ) -> dict[str, Any]:
        cda_output = next(
            (item for item in outputs if item.get("agent_id") == "clinical_decision_agent"),
            None,
        )
        top_recommendation = None
        if cda_output:
            recommendations = cda_output.get("recommendations", []) or []
            if recommendations:
                top_recommendation = recommendations[0]

        qa_passed = bool(qa_results) and all(item.get("approved", False) for item in qa_results)
        return {
            "mode": runtime_mode,
            "qa_passed": qa_passed,
            "can_present_advisory": bool(top_recommendation) and (
                runtime_mode == "advisory" and (qa_passed or not qa_results)
            ),
            "recommendation": top_recommendation,
        }

    @staticmethod
    def _generate_explanation(
        record: dict,
        outputs: list[dict],
        confidence: dict,
    ) -> dict[str, Any]:
        try:
            from prostanet.engine.explanation_engine import ExplanationEngine
            engine = ExplanationEngine()
            return engine.explain_recommendation(record, outputs, confidence)
        except Exception as exc:
            logger.debug("Explanation generation failed: %s", exc)
            return {"narrative": "", "sections": [], "data_gaps": []}

    @staticmethod
    def _persist_audit(
        patient_id: int,
        trigger_event: str,
        trigger_data: dict,
        outputs: list[dict],
        qa_results: list[dict],
    ) -> list[int]:
        try:
            from prostanet.engine.audit_log import AuditLogger
            audit = AuditLogger()
            ids: list[int] = []
            for i, out in enumerate(outputs):
                qa = qa_results[i] if i < len(qa_results) else None
                row_id = audit.log_execution(
                    patient_id=patient_id,
                    agent_id=out.get("agent_id", "unknown"),
                    trigger_event=trigger_event,
                    trigger_data=trigger_data,
                    output=out,
                    confidence_score=out.get("confidence_score"),
                    qa_validation=qa,
                    execution_time_ms=out.get("execution_time_ms"),
                )
                if row_id:
                    ids.append(row_id)
            return ids
        except Exception as exc:
            logger.debug("Audit persistence failed: %s", exc)
            return []

    @staticmethod
    def _output_to_dict(output: Any) -> dict[str, Any]:
        """Convert an AgentOutput dataclass to a plain dict."""
        try:
            return asdict(output)
        except Exception:
            return {}
