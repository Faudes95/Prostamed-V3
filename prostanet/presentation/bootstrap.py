from __future__ import annotations

from flask import Flask

from prostanet.presentation.api import modular_api
from prostanet.presentation.views import modular_views


def register_modular_blueprints(app: Flask) -> None:
    if "modular_api" not in app.blueprints:
        app.register_blueprint(modular_api)
    if "modular_views" not in app.blueprints:
        app.register_blueprint(modular_views)

    # Faubot LXXXV — Iteración #2: Trial Eligibility Engine REST API + UI
    try:
        from prostanet.presentation.trial_eligibility_routes import trial_eligibility_bp
        if "trial_eligibility" not in app.blueprints:
            app.register_blueprint(trial_eligibility_bp)
    except Exception as exc:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            f"trial_eligibility_bp registration failed (continuing): "
            f"{type(exc).__name__}: {exc}"
        )

    # Faubot LXCV — Iterative Improvement Loop Monitor
    try:
        from prostanet.presentation.loop_monitor import loop_monitor_bp
        if "loop_monitor" not in app.blueprints:
            app.register_blueprint(loop_monitor_bp)
    except Exception as exc:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            f"loop_monitor_bp registration failed (continuing): "
            f"{type(exc).__name__}: {exc}"
        )
