"""
Clinical Event Bus — In-process publish/subscribe for agent coordination.

Events are published when clinical data changes (new visit, lab value,
imaging study, treatment change, etc.) and agents subscribe to react.

Event types are aligned with tracking_db.py write operations.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Callable

from prostanet.agents.contracts import AgentOutput

logger = logging.getLogger(__name__)


# Type alias for event handlers
EventHandler = Callable[[str, dict[str, Any]], AgentOutput | None]


class BaseEventTransport:
    """Minimal transport contract for clinical event delivery."""

    def enable(self) -> None:
        raise NotImplementedError

    def disable(self) -> None:
        raise NotImplementedError

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        raise NotImplementedError

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        raise NotImplementedError

    def publish(self, event_type: str, payload: dict[str, Any]) -> list[AgentOutput]:
        raise NotImplementedError


class InProcessEventBus(BaseEventTransport):
    """
    In-process pub/sub for clinical events.

    Thread-safe for single-threaded Flask context. For async/multi-worker
    setups, this would need to be backed by Redis/RabbitMQ.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[EventHandler]] = defaultdict(list)
        self._enabled: bool = False
        self._event_log: list[dict[str, Any]] = []
        self._max_log_size: int = 1000

    @property
    def enabled(self) -> bool:
        return self._enabled

    def enable(self) -> None:
        """Enable event publishing."""
        self._enabled = True
        logger.info("ClinicalEventBus enabled")

    def disable(self) -> None:
        """Disable event publishing (no events will be dispatched)."""
        self._enabled = False
        logger.info("ClinicalEventBus disabled")

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """
        Register a handler for an event type.

        Args:
            event_type: One of CLINICAL_EVENT_TYPES
            handler: Callable(event_type, payload) → AgentOutput | None
        """
        self._subscribers[event_type].append(handler)
        logger.debug("Subscribed handler to '%s'", event_type)

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        """Remove a handler from an event type."""
        handlers = self._subscribers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)

    def publish(
        self,
        event_type: str,
        payload: dict[str, Any],
    ) -> list[AgentOutput]:
        """
        Publish a clinical event and collect agent outputs.

        Args:
            event_type: Type of clinical event
            payload: Event data (must include patient_id)

        Returns:
            List of AgentOutput from all triggered handlers
        """
        if not self._enabled:
            return []

        # Log event
        self._log_event(event_type, payload)

        handlers = self._subscribers.get(event_type, [])
        if not handlers:
            return []

        outputs: list[AgentOutput] = []
        for handler in handlers:
            try:
                result = handler(event_type, payload)
                if result is not None:
                    outputs.append(result)
            except Exception as exc:
                logger.error(
                    "Handler error for event '%s': %s",
                    event_type,
                    exc,
                    exc_info=True,
                )

        logger.info(
            "Published '%s' for patient %s → %d outputs",
            event_type,
            payload.get("patient_id", "?"),
            len(outputs),
        )
        return outputs

    def _log_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Keep a bounded in-memory event log for debugging."""
        self._event_log.append({
            "event_type": event_type,
            "patient_id": payload.get("patient_id"),
        })
        if len(self._event_log) > self._max_log_size:
            self._event_log = self._event_log[-self._max_log_size // 2 :]

    @property
    def subscriber_count(self) -> dict[str, int]:
        """Number of subscribers per event type."""
        return {k: len(v) for k, v in self._subscribers.items()}

    @property
    def recent_events(self) -> list[dict[str, Any]]:
        """Last 50 events for debugging."""
        return self._event_log[-50:]


class DurableEventTransport(BaseEventTransport):
    """
    Placeholder durable transport abstraction for multi-worker deployments.

    Today this class only records intent to publish and safely degrades without
    dispatching. It exists so the runtime can distinguish between local/dev
    in-process delivery and future durable backends.
    """

    def __init__(self) -> None:
        self._enabled = False
        self._pending_events: list[dict[str, Any]] = []

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        logger.debug(
            "DurableEventTransport subscribe called for '%s'; durable backend not configured",
            event_type,
        )

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        return None

    def publish(self, event_type: str, payload: dict[str, Any]) -> list[AgentOutput]:
        if not self._enabled:
            return []
        self._pending_events.append(
            {
                "event_type": event_type,
                "patient_id": payload.get("patient_id"),
                "delivery_mode": "durable_deferred",
            }
        )
        logger.info(
            "Queued '%s' for patient %s in durable transport placeholder",
            event_type,
            payload.get("patient_id", "?"),
        )
        return []

    @property
    def pending_events(self) -> list[dict[str, Any]]:
        return list(self._pending_events)


class ClinicalEventBus(InProcessEventBus):
    """Backward-compatible alias for the development in-process transport."""
    pass


# ── Singleton ────────────────────────────────────────────────────────────

_bus: ClinicalEventBus | None = None


def get_event_bus() -> ClinicalEventBus:
    """Get or create the global clinical event bus."""
    global _bus
    if _bus is None:
        _bus = ClinicalEventBus()
    return _bus


def get_event_transport(mode: str = "in_process") -> BaseEventTransport:
    """Factory for event transport selection."""
    if str(mode).strip().lower() == "durable":
        return DurableEventTransport()
    return get_event_bus()
