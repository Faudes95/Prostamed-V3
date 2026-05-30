"""
Agent Registry — Lifecycle management for clinical AI agents.

Manages registration, lookup, and event routing for all agents.
Integrates with the event bus to automatically dispatch events
to the correct agents.
"""

from __future__ import annotations

import logging
from typing import Any

from prostanet.agents.base import AgentBase
from prostanet.agents.contracts import AgentInput, AgentOutput
from prostanet.agents.event_bus import ClinicalEventBus, get_event_bus

logger = logging.getLogger(__name__)


class AgentRegistry:
    """
    Central registry for all ProstaNet clinical agents.

    Handles:
        - Agent registration and lookup
        - Event routing to appropriate agents
        - Agent lifecycle (enable/disable)
    """

    def __init__(self, event_bus: ClinicalEventBus | None = None) -> None:
        self._agents: dict[str, AgentBase] = {}
        self._enabled_agents: set[str] = set()
        self._event_bus = event_bus or get_event_bus()

    def register(self, agent: AgentBase, enabled: bool = True) -> None:
        """
        Register an agent and optionally subscribe it to events.

        Args:
            agent: Agent instance
            enabled: Whether to enable and subscribe immediately
        """
        self._agents[agent.agent_id] = agent
        logger.info("Registered agent: %s (%s)", agent.agent_id, agent.agent_role)

        if enabled:
            self.enable_agent(agent.agent_id)

    def enable_agent(self, agent_id: str) -> None:
        """Enable an agent and subscribe it to its trigger events."""
        agent = self._agents.get(agent_id)
        if not agent:
            logger.warning("Cannot enable unknown agent: %s", agent_id)
            return

        self._enabled_agents.add(agent_id)

        # Subscribe to event bus
        for event_type in agent.trigger_events:
            self._event_bus.subscribe(
                event_type,
                lambda evt, payload, a=agent: self._dispatch_to_agent(a, evt, payload),
            )

        logger.info("Enabled agent: %s (events: %s)", agent_id, agent.trigger_events)

    def disable_agent(self, agent_id: str) -> None:
        """Disable an agent (stops receiving events)."""
        self._enabled_agents.discard(agent_id)
        logger.info("Disabled agent: %s", agent_id)

    def get(self, agent_id: str) -> AgentBase | None:
        """Get agent by ID."""
        return self._agents.get(agent_id)

    def get_triggered_agents(self, event_type: str) -> list[AgentBase]:
        """Get all enabled agents that should trigger for an event type."""
        triggered = []
        for agent_id in self._enabled_agents:
            agent = self._agents.get(agent_id)
            if agent and agent.should_trigger(event_type):
                triggered.append(agent)
        return triggered

    def run_agent(
        self,
        agent_id: str,
        agent_input: AgentInput,
    ) -> AgentOutput | None:
        """
        Manually run a specific agent.

        Returns None if agent not found.
        """
        agent = self._agents.get(agent_id)
        if not agent:
            logger.warning("Agent not found: %s", agent_id)
            return None

        return agent.evaluate_safe(agent_input)

    def run_all_triggered(
        self,
        event_type: str,
        agent_input: AgentInput,
    ) -> list[AgentOutput]:
        """Run all agents triggered by an event type."""
        outputs: list[AgentOutput] = []
        for agent in self.get_triggered_agents(event_type):
            output = agent.evaluate_safe(agent_input)
            outputs.append(output)
        return outputs

    def _dispatch_to_agent(
        self,
        agent: AgentBase,
        event_type: str,
        payload: dict[str, Any],
    ) -> AgentOutput | None:
        """Event bus callback — dispatch to agent."""
        if agent.agent_id not in self._enabled_agents:
            return None

        agent_input = AgentInput(
            patient_id=payload.get("patient_id", 0),
            record=payload.get("record", {}),
            trigger_event=event_type,
            trigger_data=payload,
        )
        return agent.evaluate_safe(agent_input)

    def orchestrate_all(
        self,
        agent_input: "AgentInput",
        *,
        run_qaa: bool = True,
    ) -> dict[str, Any]:
        """
        Full orchestration pipeline — runs ALL five agents in sequence.

        Order:
          1. ClinicalDecisionAgent       — primary recommendation
          2. ProgressionSurveillanceAgent — PSA kinetics + anomaly alerts
          3. TreatmentOptimizationAgent   — ranked treatment options
          4. ResearchIntelligenceAgent    — trial eligibility + cohort
          5. QualityAssuranceAgent        — validates CDA output (QA gate)

        Returns:
            Orchestration result with:
              - agent_outputs: dict[agent_id → AgentOutput.to_dict()]
              - qaa_validation: QAValidation result (if run_qaa=True)
              - consolidated_recommendations: merged recommendation list
              - consolidated_alerts: merged alert list (deduplicated)
              - overall_confidence: weighted average confidence
              - narrative: Spanish clinical summary
        """
        from prostanet.agents.clinical_decision_agent import ClinicalDecisionAgent
        from prostanet.agents.progression_surveillance_agent import ProgressionSurveillanceAgent
        from prostanet.agents.treatment_optimization_agent import TreatmentOptimizationAgent
        from prostanet.agents.research_intelligence_agent import ResearchIntelligenceAgent
        from prostanet.agents.quality_assurance_agent import QualityAssuranceAgent
        from prostanet.agents.godibot import GodiBotValidator

        _AGENTS = [
            ("cda", ClinicalDecisionAgent),
            ("psa", ProgressionSurveillanceAgent),
            ("toa", TreatmentOptimizationAgent),
            ("ria", ResearchIntelligenceAgent),
        ]

        agent_outputs: dict[str, Any] = {}
        all_recommendations: list[Any] = []
        all_alerts: list[Any] = []
        confidence_scores: list[float] = []
        cda_output_obj: Any = None  # keep original for QAA

        for agent_id, agent_cls in _AGENTS:
            try:
                agent = agent_cls()
                output = agent.evaluate_safe(agent_input)
                agent_outputs[agent_id] = output.to_dict() if hasattr(output, "to_dict") else vars(output)
                all_recommendations.extend(output.recommendations or [])
                all_alerts.extend(output.alerts or [])
                if output.confidence_score and output.confidence_score > 0:
                    confidence_scores.append(output.confidence_score)
                if agent_id == "cda":
                    cda_output_obj = output
            except Exception as exc:
                logger.warning("Agent %s failed: %s", agent_id, exc)
                agent_outputs[agent_id] = {"error": str(exc)}

        # QAA validates CDA output using original AgentOutput object
        qaa_result: dict[str, Any] = {}
        if run_qaa and cda_output_obj is not None:
            try:
                qaa = QualityAssuranceAgent()
                qaa_validation = qaa.validate(cda_output_obj, agent_input.record)
                qaa_result = vars(qaa_validation) if hasattr(qaa_validation, "__dict__") else {}
                agent_outputs["qaa"] = qaa_result
            except Exception as exc:
                logger.warning("QAA failed: %s", exc)
                agent_outputs["qaa"] = {"error": str(exc)}

        # GodiBot — segunda opinión adversarial (Iteración C). Corre DESPUÉS
        # de QAA porque necesita el compass/recommendation ya construido en
        # agent_input.record["clinical_compass"]. Si el record no contiene
        # compass, GodiBot devuelve approved sin discrepancias.
        try:
            godibot = GodiBotValidator(enable_llm_adversarial=False)
            godibot_output = godibot.evaluate_safe(agent_input)
            agent_outputs["godibot"] = godibot_output.to_dict() if hasattr(
                godibot_output, "to_dict"
            ) else vars(godibot_output)
            # Add godibot alerts so they participate in dedup downstream
            for a in (godibot_output.alerts or []):
                all_alerts.append(a)
            # Bubble the review dict up at top-level for UI convenience
            review = (godibot_output.metadata or {}).get("godibot_review")
            if review:
                agent_outputs["godibot_review"] = review
        except Exception as exc:
            logger.warning("GodiBot validator failed: %s", exc)
            agent_outputs["godibot"] = {"error": str(exc)}

        # Deduplicate alerts by message (handle both dataclasses and dicts)
        seen_alerts: set[str] = set()
        unique_alerts = []
        for a in all_alerts:
            key = (getattr(a, "message", None) or (a.get("message") if isinstance(a, dict) else None) or str(a))
            if key not in seen_alerts:
                seen_alerts.add(key)
                unique_alerts.append(a)

        # Build narrative
        try:
            from prostanet.ai.explanations.clinical_narrative import ClinicalNarrativeEngine
            narrator = ClinicalNarrativeEngine()
            rec_texts: list[str] = []
            for r in all_recommendations[:5]:
                if isinstance(r, dict):
                    rec_texts.append(r.get("text") or r.get("action") or r.get("recommendation") or "")
                else:
                    rec_texts.append(getattr(r, "action", "") or "")
            narrative = narrator.generate_full_summary(
                agent_input.record,
                agent_outputs=list(agent_outputs.values()),
                recommendations=rec_texts,
            )
        except Exception:
            narrative = ""

        overall_confidence = round(
            sum(confidence_scores) / len(confidence_scores), 1
        ) if confidence_scores else 0.0

        return {
            "agent_outputs": agent_outputs,
            "qaa_validation": qaa_result,
            "consolidated_recommendations": all_recommendations,
            "consolidated_alerts": unique_alerts,
            "overall_confidence": overall_confidence,
            "narrative": narrative,
            "agents_run": [
                k for k in agent_outputs.keys() if k != "godibot_review"
            ],
        }

    @property
    def registered_agents(self) -> dict[str, dict[str, Any]]:
        """Summary of all registered agents."""
        return {
            agent_id: {
                "role": agent.agent_role,
                "enabled": agent_id in self._enabled_agents,
                "trigger_events": agent.trigger_events,
            }
            for agent_id, agent in self._agents.items()
        }

    @property
    def enabled_count(self) -> int:
        return len(self._enabled_agents)


# ── Singleton ────────────────────────────────────────────────────────────

_registry: AgentRegistry | None = None


def get_agent_registry() -> AgentRegistry:
    """Get or create the global agent registry."""
    global _registry
    if _registry is None:
        _registry = AgentRegistry()
    return _registry
