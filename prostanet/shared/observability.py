"""observability.py — Sprint 7.C (FAUBOT CXLV).

Rate limiting + Prometheus metrics exporter para los endpoints REST clínicos.

Diseño defensive: los imports de `flask_limiter` y `prometheus_client` son
condicionales — si las libs no están instaladas, todo degrada gracefully a
no-op. Esto permite que el código existente siga corriendo en dev sin pip
install + activación selectiva en producción.

Activación producción:
  pip install flask-limiter prometheus_client
  PROSTANET_RATE_LIMIT_ENABLED=1 PROSTANET_METRICS_ENABLED=1 python3 app.py

Métricas expuestas en GET /metrics:
  - prostanet_api_requests_total{endpoint, method, status_class}        — counter
  - prostanet_api_request_duration_seconds{endpoint, method}            — histogram
  - prostanet_ml_inference_total{model, status}                         — counter
  - prostanet_ml_inference_duration_seconds{model}                      — histogram
  - prostanet_godibot_findings_total{status}                            — counter
  - prostanet_audit_log_failures_total{section_key}                     — counter
  - prostanet_auth_attempts_total{backend, outcome}                     — counter
  - prostanet_oidc_provisions_total                                     — counter
  - prostanet_active_sessions                                           — gauge
  - prostanet_db_query_duration_seconds{query_kind}                     — histogram

Rate limits default (configurable):
  - Auth endpoints: 10/min/IP
  - GET endpoints clinician: 200/min/user_id
  - POST endpoints clinician: 30/min/user_id
  - Admin endpoints: 60/min/user_id

Beneficio operativo:
  - Detección temprana degradación performance (Grafana SLO alerts)
  - Bloqueo de abuse intencional/accidental (loop infinito de polling)
  - Capacity planning con métricas temporales reales
  - SaMD post-market surveillance automatizada (FDA aprecia)
"""
from __future__ import annotations

import logging
import os
import time
from functools import wraps
from typing import Callable

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Feature flags
# ─────────────────────────────────────────────────────────────────────


def is_metrics_enabled() -> bool:
    return os.environ.get("PROSTANET_METRICS_ENABLED", "0").strip() in (
        "1", "true", "yes", "on"
    )


def is_rate_limit_enabled() -> bool:
    return os.environ.get("PROSTANET_RATE_LIMIT_ENABLED", "0").strip() in (
        "1", "true", "yes", "on"
    )


# ─────────────────────────────────────────────────────────────────────
# Prometheus metrics — conditional import
# ─────────────────────────────────────────────────────────────────────


_PROMETHEUS_AVAILABLE = False
_metrics: dict = {}

try:
    if is_metrics_enabled():
        from prometheus_client import (
            Counter, Histogram, Gauge, CollectorRegistry,
            generate_latest, CONTENT_TYPE_LATEST,
        )
        _PROMETHEUS_AVAILABLE = True

        # Registry dedicado (no usar default — evita collisions con tests)
        _registry = CollectorRegistry()

        _metrics["api_requests"] = Counter(
            "prostanet_api_requests_total",
            "Total API requests by endpoint, method, status class",
            ["endpoint", "method", "status_class"],
            registry=_registry,
        )
        _metrics["api_duration"] = Histogram(
            "prostanet_api_request_duration_seconds",
            "API request duration by endpoint, method",
            ["endpoint", "method"],
            buckets=(0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
            registry=_registry,
        )
        _metrics["ml_inference"] = Counter(
            "prostanet_ml_inference_total",
            "ML inference calls by model + status",
            ["model", "status"],
            registry=_registry,
        )
        _metrics["ml_duration"] = Histogram(
            "prostanet_ml_inference_duration_seconds",
            "ML inference duration by model",
            ["model"],
            buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0),
            registry=_registry,
        )
        _metrics["godibot_findings"] = Counter(
            "prostanet_godibot_findings_total",
            "GodiBot findings by status (approved/warnings_only/blocked_hard)",
            ["status"],
            registry=_registry,
        )
        _metrics["audit_failures"] = Counter(
            "prostanet_audit_log_failures_total",
            "Audit log insert failures by section_key (REGULATORY signal)",
            ["section_key"],
            registry=_registry,
        )
        _metrics["auth_attempts"] = Counter(
            "prostanet_auth_attempts_total",
            "Auth attempts by backend + outcome",
            ["backend", "outcome"],
            registry=_registry,
        )
        _metrics["oidc_provisions"] = Counter(
            "prostanet_oidc_provisions_total",
            "OIDC JIT provisions (new clinical_users created via OIDC)",
            registry=_registry,
        )
        _metrics["active_sessions"] = Gauge(
            "prostanet_active_sessions",
            "Active authenticated sessions (refreshed on /api/auth/whoami)",
            registry=_registry,
        )
        _metrics["db_duration"] = Histogram(
            "prostanet_db_query_duration_seconds",
            "DB query duration by kind (cohort_audit, patient_load, etc.)",
            ["query_kind"],
            buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 5.0),
            registry=_registry,
        )
        logger.info("Prometheus metrics enabled (10 instruments registered)")
except ImportError:
    logger.info(
        "prometheus_client not installed — metrics disabled "
        "(pip install prometheus_client to enable)"
    )


# ─────────────────────────────────────────────────────────────────────
# Public API — metric incrementers (no-op si Prometheus disabled)
# ─────────────────────────────────────────────────────────────────────


def inc_api_request(endpoint: str, method: str, status_class: str) -> None:
    """status_class: '2xx', '4xx', '5xx', etc."""
    if not _PROMETHEUS_AVAILABLE:
        return
    try:
        _metrics["api_requests"].labels(
            endpoint=endpoint[:80], method=method, status_class=status_class
        ).inc()
    except Exception:
        pass


def observe_api_duration(endpoint: str, method: str, seconds: float) -> None:
    if not _PROMETHEUS_AVAILABLE:
        return
    try:
        _metrics["api_duration"].labels(
            endpoint=endpoint[:80], method=method
        ).observe(seconds)
    except Exception:
        pass


def inc_ml_inference(model: str, status: str) -> None:
    """status: 'success', 'load_error', 'model_error', 'unavailable'"""
    if not _PROMETHEUS_AVAILABLE:
        return
    try:
        _metrics["ml_inference"].labels(model=model, status=status).inc()
    except Exception:
        pass


def observe_ml_duration(model: str, seconds: float) -> None:
    if not _PROMETHEUS_AVAILABLE:
        return
    try:
        _metrics["ml_duration"].labels(model=model).observe(seconds)
    except Exception:
        pass


def inc_godibot_finding(status: str) -> None:
    if not _PROMETHEUS_AVAILABLE:
        return
    try:
        _metrics["godibot_findings"].labels(status=status).inc()
    except Exception:
        pass


def inc_audit_failure(section_key: str) -> None:
    if not _PROMETHEUS_AVAILABLE:
        return
    try:
        _metrics["audit_failures"].labels(section_key=section_key).inc()
    except Exception:
        pass


def inc_auth_attempt(backend: str, outcome: str) -> None:
    """outcome: 'success', 'denied_invalid_credentials', 'denied_locked', ..."""
    if not _PROMETHEUS_AVAILABLE:
        return
    try:
        _metrics["auth_attempts"].labels(backend=backend, outcome=outcome).inc()
    except Exception:
        pass


def inc_oidc_provision() -> None:
    if not _PROMETHEUS_AVAILABLE:
        return
    try:
        _metrics["oidc_provisions"].inc()
    except Exception:
        pass


def observe_db_duration(query_kind: str, seconds: float) -> None:
    if not _PROMETHEUS_AVAILABLE:
        return
    try:
        _metrics["db_duration"].labels(query_kind=query_kind).observe(seconds)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────
# Decorator: instrument cualquier handler con metrics
# ─────────────────────────────────────────────────────────────────────


def instrument_handler(endpoint_label: str | None = None):
    """Decorator que mide latencia + cuenta requests por status_class.

    Usage:
        @bp.route("/api/foo")
        @instrument_handler("api_foo")
        def my_handler():
            ...
    """
    def wrapper(func: Callable) -> Callable:
        @wraps(func)
        def inner(*args, **kwargs):
            label = endpoint_label or func.__name__
            try:
                from flask import request
                method = request.method
            except Exception:
                method = "UNKNOWN"

            start = time.monotonic()
            try:
                response = func(*args, **kwargs)
                # Extraer status_code de tuple/Response
                status_code = 200
                if isinstance(response, tuple) and len(response) >= 2:
                    status_code = response[1]
                elif hasattr(response, "status_code"):
                    status_code = response.status_code
                status_class = f"{status_code // 100}xx"
                inc_api_request(label, method, status_class)
                return response
            except Exception:
                inc_api_request(label, method, "5xx")
                raise
            finally:
                observe_api_duration(label, method, time.monotonic() - start)

        return inner
    return wrapper


# ─────────────────────────────────────────────────────────────────────
# Flask integration — register /metrics + Flask-Limiter
# ─────────────────────────────────────────────────────────────────────


def register_observability(app) -> None:
    """Registra /metrics endpoint + rate limiter en la Flask app.

    Llamar UNA vez en bootstrap antes de register_blueprint:
        from prostanet.shared.observability import register_observability
        register_observability(app)
    """
    if _PROMETHEUS_AVAILABLE:
        @app.route("/metrics", methods=["GET"])
        def metrics_endpoint():
            from flask import Response
            return Response(
                generate_latest(_registry),
                mimetype=CONTENT_TYPE_LATEST,
            )
        logger.info("Prometheus /metrics endpoint registered")

    if is_rate_limit_enabled():
        try:
            from flask_limiter import Limiter
            from flask_limiter.util import get_remote_address

            def _key_func():
                """Per-user_id si auth, sino per-IP."""
                try:
                    from flask import session
                    from prostanet.shared.auth_backends import session_user_id
                    uid = session_user_id(session)
                    if uid is not None:
                        return f"user_{uid}"
                except Exception:
                    pass
                return f"ip_{get_remote_address()}"

            limiter = Limiter(
                app=app,
                key_func=_key_func,
                default_limits=["1000 per minute", "10000 per hour"],
                storage_uri=os.environ.get(
                    "PROSTANET_RATE_LIMIT_STORAGE", "memory://"
                ),
            )
            # Expose limiter para que blueprints lo importen
            app.extensions["prostanet_limiter"] = limiter
            logger.info(
                "Rate limiter enabled (default: 1000/min/user, 10k/hour)"
            )
        except ImportError:
            logger.warning(
                "flask-limiter not installed but PROSTANET_RATE_LIMIT_ENABLED=1; "
                "rate limiting INACTIVE. pip install flask-limiter"
            )

    # Health check endpoint (always available, no metrics dep)
    @app.route("/health", methods=["GET"])
    def health_check():
        from flask import jsonify
        return jsonify({
            "status": "healthy",
            "metrics_enabled": _PROMETHEUS_AVAILABLE and is_metrics_enabled(),
            "rate_limit_enabled": is_rate_limit_enabled(),
            "faubot_release": _faubot_release(),
        }), 200


def _faubot_release() -> str:
    try:
        from prostanet.shared.algorithm_version import FAUBOT_RELEASE
        return str(FAUBOT_RELEASE)
    except Exception:
        return "unknown"


__all__ = [
    "register_observability",
    "instrument_handler",
    "inc_api_request",
    "observe_api_duration",
    "inc_ml_inference",
    "observe_ml_duration",
    "inc_godibot_finding",
    "inc_audit_failure",
    "inc_auth_attempt",
    "inc_oidc_provision",
    "observe_db_duration",
    "is_metrics_enabled",
    "is_rate_limit_enabled",
]
