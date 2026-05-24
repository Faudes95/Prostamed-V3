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

    # Faubot LXC (Iteración C) — GodiBot validator REST endpoints
    try:
        from prostanet.presentation.godibot_routes import godibot_bp
        if "godibot" not in app.blueprints:
            app.register_blueprint(godibot_bp)
    except Exception as exc:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            f"godibot_bp registration failed (continuing): "
            f"{type(exc).__name__}: {exc}"
        )

    # EPIC 45 FAUBOT CXXX — Data Integrity REST endpoints (FactSpec alias audit)
    try:
        from prostanet.presentation.data_integrity_routes import data_integrity_bp
        if "data_integrity" not in app.blueprints:
            app.register_blueprint(data_integrity_bp)
    except Exception as exc:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            f"data_integrity_bp registration failed (continuing): "
            f"{type(exc).__name__}: {exc}"
        )

    # EPIC 46.B FAUBOT CXXXIII — ML Inference GET endpoints + view-model
    # helper (materialización de los 4 modelos PyTorch entrenados huérfanos).
    try:
        from prostanet.presentation.ml_inference_routes import ml_inference_bp
        if "ml_inference" not in app.blueprints:
            app.register_blueprint(ml_inference_bp)
    except Exception as exc:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            f"ml_inference_bp registration failed (continuing): "
            f"{type(exc).__name__}: {exc}"
        )

    # EPIC 47 FAUBOT CXXXV — Longitudinal Trajectory Dashboard REST endpoint
    # (GET /api/trajectory/<nss> — bundle completo con PSA + ECOG + ALP +
    # LDH + kinetics + alerts para AJAX refresh sin re-render del perfil).
    try:
        from prostanet.presentation.trajectory_routes import trajectory_bp
        if "trajectory" not in app.blueprints:
            app.register_blueprint(trajectory_bp)
    except Exception as exc:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            f"trajectory_bp registration failed (continuing): "
            f"{type(exc).__name__}: {exc}"
        )
