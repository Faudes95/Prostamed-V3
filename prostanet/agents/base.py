"""
Abstract base class for ProstaNet clinical AI agents.

Every agent implements evaluate() to process clinical events and
produce structured recommendations with confidence scoring.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Any

from prostanet.agents.contracts import AgentInput, AgentOutput

logger = logging.getLogger(__name__)


class AgentBase(ABC):
    """
    Abstract base for all ProstaNet clinical agents.

    Subclasses must implement:
        - evaluate(): Core agent logic
        - should_trigger(): Event filtering
    """

    agent_id: str = "base_agent"
    agent_role: str = "Base clinical agent"
    trigger_events: list[str] = []  # Which events this agent responds to

    @abstractmethod
    def evaluate(self, agent_input: AgentInput) -> AgentOutput:
        """
        Execute the agent's clinical logic.

        Args:
            agent_input: Full patient context + trigger event

        Returns:
            AgentOutput with recommendations, confidence, evidence chain
        """
        ...

    def should_trigger(self, event_type: str, event_data: dict[str, Any] | None = None) -> bool:
        """
        Determine if this agent should run for a given event.

        Default: trigger if event_type is in self.trigger_events.
        Override for more complex logic.
        """
        return event_type in self.trigger_events

    def evaluate_safe(self, agent_input: AgentInput) -> AgentOutput:
        """
        Safe wrapper around evaluate() with timing and error handling.

        Never raises — returns an empty AgentOutput on error.
        """
        start = time.monotonic()
        try:
            output = self.evaluate(agent_input)
            output.execution_time_ms = int((time.monotonic() - start) * 1000)
            return output
        except Exception as exc:
            logger.error(
                "Agent %s failed for patient %d: %s",
                self.agent_id,
                agent_input.patient_id,
                exc,
                exc_info=True,
            )
            return AgentOutput(
                agent_id=self.agent_id,
                patient_id=agent_input.patient_id,
                confidence_score=0.0,
                evidence_chain=[f"Error: {exc}"],
                execution_time_ms=int((time.monotonic() - start) * 1000),
            )

    def explain(self, output: AgentOutput) -> str:
        """
        Generate a clinician-readable explanation of the agent's output.

        Default implementation joins evidence chain.
        """
        if not output.evidence_chain:
            return f"El agente {self.agent_id} no generó cadena de evidencia."
        return "\n→ ".join(output.evidence_chain)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(id={self.agent_id})>"
