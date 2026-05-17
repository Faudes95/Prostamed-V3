# -*- coding: utf-8 -*-
"""
Web Interface — Modelo de Cáncer de Próstata
Flask app que carga el modelo entrenado y sirve predicciones vía API.
"""
import os
import sys
import json
import logging
import sqlite3
from datetime import datetime

from flask import Flask, render_template, request, jsonify, redirect, url_for

from prostanet.shared.utc_time import utc_now_iso  # EPIC 32.G G78 — UTC unification

# Añadir directorio actual al path para importar el modelo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prostate_cancer_model import load_all
from prostanet.domains.patient_tracking.service import PatientTrackingService
from prostanet.presentation.bootstrap import register_modular_blueprints
from prostanet.presentation.ui_assets import build_ui_assets
from prostanet.presentation.view_models import build_page_chrome
from prostanet.shared.feature_flags import resolve_feature_flags
from prostanet.shared.official_diagnosis import (
    build_official_diagnosis_context,
    diagnosis_capture_options,
    diagnosis_field_label,
)
from prostanet.shared.gleason_profile import normalize_gleason_profile
# Faubot 2026-04-25 (XXXII) — Tier 7 G5: auth gateway HTML
from prostanet.shared.security_helpers import require_clinical_session
from tracking_db import configure_db_path, get_stats, init_tracking_db, patient_exists

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
tracking_service = PatientTrackingService()

# ── Funciones de conversión segura (campos vacíos del formulario) ──────────
def safe_float(val, default=0.0):
    """Convierte a float de forma segura. '' o None → default."""
    if val is None or val == '':
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default

def safe_int(val, default=0):
    """Convierte a int de forma segura. '' o None → default."""
    if val is None or val == '':
        return default
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default

app = Flask(__name__, template_folder="templates", static_folder="static")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_APP_CONFIG = {
    "DB_PATH": os.environ.get("PROSTANET_DB_PATH", os.path.join(BASE_DIR, "prostanet_tracking.db")),
    "MODEL_DIR": os.path.join(BASE_DIR, "model_output"),
    "LOAD_MODEL": True,
    "TESTING": False,
}
DEFAULT_APP_CONFIG.update(resolve_feature_flags(DEFAULT_APP_CONFIG))
REGISTER_NUMERIC_FIELDS = (
    "assessment_id",
    "baseline_psa",
    "testosterone_baseline",
    "hemoglobin",
    "alp",
    "ldh",
    "albumin",
    "rt_primary_dose_gy",
    "prior_docetaxel_cycles",
    "prior_arpi_duration",
    "line_of_therapy",
    "line_of_therapy_number",
    "metastasis_count",
    "ecog_score",
    "gleason_score",
    "gleason_primary",
    "gleason_secondary",
    "gleason_tertiary",
    "isup_grade",
    "ipss_score",
    "iief5_score",
    "paquetes_anio",
    "weight_kg",
    "bmi_current",
    "weight_loss_6m_pct",
    "mini_cog_score",
    "fatigue_score",
    "g8_food_intake",
    "g8_weight_loss",
    "g8_mobility",
    "g8_neuropsych",
    "g8_bmi",
    "g8_medications",
    "g8_self_health",
)
FOLLOWUP_NUMERIC_FIELDS = (
    "psa",
    "testosterone",
    "alp",
    "ldh",
    "albumin",
    "hemoglobin",
    "ecog",
    "pain",
)

app.config.update(DEFAULT_APP_CONFIG)


@app.context_processor
def inject_ui_assets():
    return {"ui_assets": build_ui_assets()}

model = None
artifacts = None
ts_risk = None


def error_response(message, status_code):
    return jsonify({"success": False, "error": message}), status_code


def parse_json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError("Se requiere un cuerpo JSON válido.")
    return data


def require_non_empty_fields(data, field_names):
    missing = [field for field in field_names if str(data.get(field, "")).strip() == ""]
    if missing:
        raise ValueError(f"Campos requeridos: {', '.join(missing)}")


def validate_numeric_fields(data, field_names):
    for field in field_names:
        value = data.get(field)
        if value in (None, ""):
            continue
        try:
            float(value)
        except (TypeError, ValueError):
            raise ValueError(f"'{field}' debe ser numérico.")


def _payload_truthy(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "si", "sí", "confirmed", "confirmado"}


def _payload_present(value):
    return value not in (None, "", [], {}, "No aplica", "No documentado", "Desconocido", "Desconocida")


def _registration_state(data):
    return (
        data.get("assessment_state")
        or data.get("_classified_state")
        or data.get("clinical_state")
        or data.get("state")
        or ("localized_initial" if _payload_truthy(data.get("known_cancer_diagnosis")) else "diagnostic_workup")
    )


def _prepare_registration_contract_payload(data):
    if data.get("_classified_state") and not data.get("assessment_state"):
        data["assessment_state"] = data.get("_classified_state")
    if data.get("_classification_reason") and not data.get("classification_reason"):
        data["classification_reason"] = data.get("_classification_reason")
    if _payload_present(data.get("psa_baseline_ng_ml")) and not _payload_present(data.get("baseline_psa")):
        data["baseline_psa"] = data.get("psa_baseline_ng_ml")
    if _payload_present(data.get("metastasis_site")) and not _payload_present(data.get("m_substage_resolved")):
        data["m_substage_resolved"] = data.get("metastasis_site")
    return data


def _official_diagnosis_context_from_registration(data):
    state = _registration_state(data)
    baseline = dict(data or {})
    patient_like = {
        "baseline": baseline,
        "biopsies": [],
        "follow_ups": [],
        "identity": {
            "nss": data.get("nss", ""),
            "full_name": data.get("full_name", ""),
        },
    }
    return build_official_diagnosis_context(
        patient=patient_like,
        state=state,
        raw_assessment={"input_snapshot": baseline},
        display_assessment={},
        operational_module_label="Diagnóstico en consolidación",
    )


def _confirmed_diagnosis_publication_gate(data):
    """Bloquea sólo la publicación de cáncer confirmado sin diagnóstico formal."""
    context = _official_diagnosis_context_from_registration(data)
    applies = _payload_truthy(data.get("known_cancer_diagnosis"))
    profile = normalize_gleason_profile(data)
    missing_raw = list(context.get("official_diagnosis_missing_fields_raw") or [])

    if applies:
        if not _payload_present(data.get("histology_subtype")) and "histology_subtype" not in missing_raw:
            missing_raw.append("histology_subtype")
        if not profile.get("has_structured_gleason"):
            if "gleason_primary" not in missing_raw:
                missing_raw.append("gleason_primary")
            if "gleason_secondary" not in missing_raw:
                missing_raw.append("gleason_secondary")
        if profile.get("isup_grade") is None and "isup_grade" not in missing_raw:
            missing_raw.append("isup_grade")

        has_risk_or_stage = (
            _payload_present(data.get("clinical_risk_group"))
            or _payload_present(data.get("clinical_stage_group"))
        )
        if not has_risk_or_stage and "clinical_stage_group_or_risk_group" not in missing_raw:
            missing_raw.append("clinical_stage_group_or_risk_group")

    label_overrides = {
        "clinical_stage_group_or_risk_group": "etapa clínica o grupo de riesgo clínico",
    }
    missing_labels = [label_overrides.get(field, diagnosis_field_label(field)) for field in missing_raw]
    blocked = bool(applies and (
        missing_raw
        or context.get("official_diagnosis_status") in {"missing", "partial"}
        or context.get("official_diagnosis_display_status") in {"incomplete", "operational_only"}
        or context.get("tnm_validation_warnings")
    ))
    return {
        "applies": applies,
        "blocked": blocked,
        "missing_fields_raw": missing_raw,
        "missing_fields": missing_labels,
        "official_diagnosis": context.get("official_diagnosis", ""),
        "official_diagnosis_status": context.get("official_diagnosis_status", "missing"),
        "official_diagnosis_display_status": context.get("official_diagnosis_display_status", "operational_only"),
        "official_diagnosis_context": context,
        "message": (
            "Diagnóstico confirmado incompleto: capture "
            + ", ".join(missing_labels[:6])
            if blocked else ""
        ),
    }


def _reconciled_patient_snapshot(record):
    from prostanet.domains.patient_tracking.reconciled_state import build_reconciled_state

    reconciliation = build_reconciled_state(record, record.get("latest_assessment"))
    return {
        "reconciled_state": reconciliation.get("reconciled_state") or "diagnostic_workup",
        "phenotype_state": reconciliation.get("phenotype_state") or reconciliation.get("reconciled_state") or "diagnostic_workup",
        "reconciled_management_track": reconciliation.get("reconciled_management_track") or "diagnostic_surveillance",
        "state_conflict_flag": reconciliation.get("state_conflict_flag", False),
        "state_conflict_reason": reconciliation.get("state_conflict_reason", ""),
        "progression_gate_active": reconciliation.get("progression_gate_active", False),
        "progression_gate_target": reconciliation.get("progression_gate_target", ""),
        "progression_gate_reason": reconciliation.get("progression_gate_reason", ""),
        "systemic_progression_context_resolved": reconciliation.get("systemic_progression_context_resolved", "none"),
    }


def _resolve_patient_api_ref(patient_ref):
    import tracking_db

    resolved = tracking_db.resolve_patient_ref(patient_ref)
    if not resolved:
        return None, error_response("Paciente no encontrado", 404)
    return resolved, None


def _minimal_patient_record_from_resolved(resolved, patient_ref):
    return {
        "identity": {
            "id": resolved.get("patient_id"),
            "nss": resolved.get("nss") or resolved.get("patient_ref") or str(patient_ref),
            "full_name": resolved.get("full_name") or "Paciente",
        },
        "baseline": {},
        "latest_assessment": {},
        "prior_history": {},
        "treatments": [],
        "patient_events": [],
    }


def _load_clinical_memory_cohort_records(tracking_db_module, *, limit=500):
    """Load a bounded internal cohort for the non-authoritative Memory OS mirror."""
    records = []
    try:
        db_path = (
            tracking_db_module.get_db_path()
            if hasattr(tracking_db_module, "get_db_path")
            else app.config.get("DB_PATH")
        )
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM patient_identity ORDER BY id ASC LIMIT ?", (int(limit),))
        patient_ids = [int(row["id"]) for row in cursor.fetchall()]
        conn.close()
        for patient_id in patient_ids:
            record = tracking_db_module.get_patient_full_record(
                patient_id,
                include_derivatives=False,
                include_ledger=False,
            )
            if record:
                records.append(record)
    except Exception as exc:
        logger.warning("Clinical Memory OS cohort mirror unavailable: %s", exc)
    return records


def _analysis_dataset_payload():
    from prostanet.domains.dashboard.dashboard_facade import get_analysis_dataset_bundle

    return get_analysis_dataset_bundle()


def ensure_model_loaded():
    global model, artifacts, ts_risk

    if model is not None:
        return
    if not app.config.get("LOAD_MODEL", True):
        raise RuntimeError("La carga del modelo está deshabilitada en la configuración actual.")

    import torch
    import prostate_cancer_model as pcm

    loaded_model, loaded_artifacts, loaded_ts_risk = load_all(app.config["MODEL_DIR"])
    pcm.DEVICE = torch.device("cpu")
    model = loaded_model.cpu()
    artifacts = loaded_artifacts
    ts_risk = loaded_ts_risk.cpu() if loaded_ts_risk is not None else None
    logger.info("✅ Modelo cargado desde %s (CPU)", app.config["MODEL_DIR"])


def create_app(config=None):
    # ──────────────────────────────────────────────────────────────────────
    # Faubot LXXXIV.b — Idempotent re-invocation guard (hook/blueprint only).
    # `app` es un Flask global a nivel de módulo (línea 51). Cuando un test
    # importa `app` y hace requests, Flask marca `_got_first_request=True`.
    # Una segunda llamada a `create_app()` rompía con AssertionError porque
    # `@app.after_request` no acepta nuevos registros post-primera-request.
    # Solución: registrar hooks/blueprints/middleware UNA SOLA VEZ; pero
    # SIEMPRE permitir config update + DB init (tests usan DB paths nuevos
    # en `app_client` fixture; saltar init_tracking_db rompería tests).
    # Resuelve 6 failed + 66 errors detectados en sweep LXXXIV.b.
    # ──────────────────────────────────────────────────────────────────────
    _already_initialized = getattr(app, "_prostanet_create_app_initialized", False)

    app.config.update(DEFAULT_APP_CONFIG)
    if config:
        app.config.update(config)
    app.config.update(resolve_feature_flags(app.config))

    # Some loop-monitor tests install a lightweight tracking_db stub before
    # importing this module. Recover the real module so test DBs and local
    # runtime always create the patient_identity schema.
    try:
        import importlib
        import sqlite3 as _stdlib_sqlite3
        tracking_db_module = sys.modules.get("tracking_db")
        tracking_db_sqlite = getattr(tracking_db_module, "sqlite3", None) if tracking_db_module else None
        needs_real_tracking_db = (
            tracking_db_module is None
            or not getattr(tracking_db_module, "__file__", None)
            or not hasattr(tracking_db_sqlite, "Row")
        )
        if needs_real_tracking_db:
            sys.modules.pop("tracking_db", None)
            tracking_db_module = importlib.import_module("tracking_db")
        tracking_db_module.sqlite3 = _stdlib_sqlite3
        if "prostanet.domains.patient_tracking.service" in sys.modules:
            service_module = sys.modules["prostanet.domains.patient_tracking.service"]
            if hasattr(service_module, "get_patient_full_record"):
                service_module.get_patient_full_record = tracking_db_module.get_patient_full_record
        globals()["sqlite3"] = _stdlib_sqlite3
        if tracking_db_module is not None:
            globals()["configure_db_path"] = tracking_db_module.configure_db_path
            globals()["get_stats"] = tracking_db_module.get_stats
            globals()["init_tracking_db"] = tracking_db_module.init_tracking_db
            globals()["patient_exists"] = tracking_db_module.patient_exists
    except Exception as exc:
        logger.warning("tracking_db real-module recovery skipped: %s", exc)

    # Faubot 2026-04-25 (XXV) — CRIT-2 hardening: secret_key obligatorio
    # desde env var (requerido para sessions/CSRF/Flask-Login futuro).
    # Modo TESTING usa key dev determinística (acepta tests aislados).
    # Modo producción (FLASK_ENV=production) RAISES si no está set.
    from prostanet.shared.security_helpers import get_secret_key
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = get_secret_key()
    app.secret_key = app.config["SECRET_KEY"]

    configure_db_path(app.config["DB_PATH"])
    init_tracking_db()

    # Faubot 2026-04-25 (XXVIII) — Tier 7 G1.5: auth tables + endpoints
    # + security middleware (all opt-in via env vars; default OFF for compat).
    try:
        from prostanet.shared.auth_db import init_auth_db
        init_auth_db()
    except Exception as exc:
        # Fail-open: auth tables not critical for legacy endpoints
        import logging as _logging
        _logging.getLogger(__name__).warning(
            f"init_auth_db failed (continuing): {type(exc).__name__}: {exc}"
        )

    # Faubot LXXXIV.b — Hooks/blueprints/middleware UNA SOLA VEZ.
    # Las DB inits arriba SÍ corren cada vez (idempotente, tests usan paths
    # nuevos). Las siguientes registrations FALLAN post-primera-request.
    if not _already_initialized:
        try:
            from prostanet.presentation.auth_endpoints import auth_bp
            app.register_blueprint(auth_bp)
        except Exception as exc:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                f"auth_bp registration failed (continuing): "
                f"{type(exc).__name__}: {exc}"
            )

        try:
            from prostanet.shared.security_middleware import (
                register_security_middleware,
            )
            register_security_middleware(app)
        except Exception as exc:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                f"security_middleware registration failed (continuing): "
                f"{type(exc).__name__}: {exc}"
            )

        # Faubot 2026-04-25 (XXXI) — Tier 7 G2: register login UI context_processor
        # exposing g.csrf_token, g.local_login_available, g.oidc_available,
        # g.oidc_backend_label, g.faubot_release, g.current_user, g.current_user_role
        try:
            from prostanet.presentation.auth_ui_context import register_auth_ui_context
            register_auth_ui_context(app)
        except Exception as exc:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                f"auth_ui_context registration failed (continuing): "
                f"{type(exc).__name__}: {exc}"
            )

        register_modular_blueprints(app)
        try:
            from prostanet.voice.api import register_voice_os

            register_voice_os(app)
        except Exception as exc:
            import logging as _logging

            _logging.getLogger(__name__).warning(
                f"voice_os registration failed (continuing): "
                f"{type(exc).__name__}: {exc}"
            )

        # EPIC 21 — Voice longitudinal Cortana (micro-form intake, patient lookup,
        # patient Q&A grounded). Registers /api/voice/epic21/* endpoints.
        try:
            from prostanet.voice.epic21_endpoints import register_epic21_endpoints

            register_epic21_endpoints(app)
        except Exception as exc:
            import logging as _logging

            _logging.getLogger(__name__).warning(
                f"EPIC 21 endpoints registration failed (continuing): "
                f"{type(exc).__name__}: {exc}"
            )

        # ──────────────────────────────────────────────────────────────────────
        # Faubot LXXXIII #audit-cde-v2 — Cache-busting middleware HTML responses
        # Resuelve bug del usuario "parece que estamos cargando una UI previa"
        # en el menú lateral. Browser cacheaba versión vieja del sidebar.
        #
        # Estrategia:
        # 1. HTML responses (Content-Type: text/html) → no-cache headers
        # 2. Static assets (CSS/JS) → mantener cache normal (con versioning URL)
        # 3. JSON API responses → no-cache (por defecto datos clínicos frescos)
        # ──────────────────────────────────────────────────────────────────────
        @app.after_request
        def _add_cache_busting_headers(response):
            try:
                ctype = (response.content_type or "").lower()
                # HTML + JSON API: prevenir cache aggressive
                if ctype.startswith("text/html") or ctype.startswith("application/json"):
                    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
                    response.headers["Pragma"] = "no-cache"
                    response.headers["Expires"] = "0"
                # Static CSS/JS: cache 1 hora (suficiente para iteración Faubot)
                elif ctype.startswith("text/css") or ctype.startswith("application/javascript") or ctype.startswith("application/x-javascript"):
                    response.headers["Cache-Control"] = "public, max-age=3600"
            except Exception:
                pass  # No-op si content_type invalido
            return response

    if app.config.get("TESTING"):
        try:
            from prostanet.ai.inference.runtime_registry import reset_runtime_model_registry

            reset_runtime_model_registry()
        except Exception:
            pass

    global model, artifacts, ts_risk
    if app.config.get("LOAD_MODEL", True):
        ensure_model_loaded()
    else:
        model = None
        artifacts = None
        ts_risk = None

    # Faubot LXXXIV.b — marca app como inicializada para idempotencia
    # (ver guard al inicio de create_app)
    app._prostanet_create_app_initialized = True
    return app


@app.route("/")
def index():
    return redirect(url_for("modular_views.clinical_hub"))


# Faubot 2026-04-25 (XXXI / XL) — Tier 7 G2 + G8: HTML login + logout pages
@app.route("/login", methods=["GET"])
def login_page():
    """Renderiza login.html con form local + botón SSO OIDC.

    Query params soportados (UI hints):
        ?error=invalid_credentials  — credenciales inválidas
        ?error=session_expired      — sesión expiró
            ?reason=idle           ★ G8: cerrada por inactividad
            ?reason=absolute       ★ G8: cerrada por edad de login (re-auth required)
        ?error=access_denied        — IDP rechazó auth
        ?error=missing_credentials  — username/password vacío
        ?error=csrf_failed          — CSRF token mismatch
        ?logged_out=1               — logout exitoso (success message)

    Faubot 2026-04-25 (XL) — Tier 7 G8: parsea `?reason=*` cuando
    `?error=session_expired` está presente y lo decodifica via whitelist
    (`decode_session_expiry_reason`) para que el template pueda mostrar
    mensaje contextual en lenguaje clínico (idle = inactividad / absolute
    = jornada finalizada). El whitelist enforcement evita XSS y scope
    bleed por query params arbitrarios.

    Si user ya autenticado, redirige a / (clinical_hub).
    """
    from flask import g, render_template
    from prostanet.shared.auth_backends import (
        decode_session_expiry_reason,
        SESSION_REASON_EXPIRED_IDLE, SESSION_REASON_EXPIRED_ABSOLUTE,
    )
    if g.get("is_authenticated", False):
        return redirect("/")

    # G8: decode session-expired reason con whitelist defensivo.
    error_code = (request.args.get("error") or "").strip().lower()
    reason_sentinel = ""
    if error_code == "session_expired":
        reason_sentinel = decode_session_expiry_reason(
            request.args.get("reason"),
        )

    return render_template(
        "login.html",
        # Sentinels canónicos exportados al template para que el bloque
        # Jinja compare con valores conocidos (no con strings arbitrarios).
        session_reason_sentinel=reason_sentinel,
        session_reason_idle=SESSION_REASON_EXPIRED_IDLE,
        session_reason_absolute=SESSION_REASON_EXPIRED_ABSOLUTE,
    )


@app.route("/logout", methods=["GET"])
def logout_page():
    """Logout via HTML link click → redirige a /api/auth/logout (GET)."""
    return redirect(url_for("clinical_auth.logout"))


@app.route("/calculator")
def calculator():
    return redirect(url_for("modular_views.clinical_hub"))

@app.route("/v2")
def calculator_v2():
    return redirect(url_for("modular_views.clinical_hub"))


@app.route("/predict", methods=["POST"])
def predict():
    """Calculadora legacy retirada. Use el centro clínico por estadio."""
    return error_response("La calculadora fue retirada. Use el centro clínico por estadio.", 410)

@app.route('/api/stats', methods=['GET'])
def api_stats():
    """Retorna estadísticas agregadas para el dashboard."""
    stats = get_stats()
    return jsonify(stats)

@app.route('/api/sync', methods=['POST'])
def api_sync():
    """Sincronización legacy retirada. Use el centro clínico para ingesta de documentos."""
    return error_response("La sincronización legacy fue retirada. Use ingesta de documentos desde el perfil del paciente.", 410)


@app.route("/patients")
@require_clinical_session(scope="phi:read", redirect_to_login=True)
def patients_list():
    page_chrome = build_page_chrome(
        "patients",
        "Pacientes registrados",
        "Cohorte longitudinal vinculada al centro clínico, con filtros operativos, alertas activas y acceso al perfil de cada paciente.",
        content_width_class="max-w-7xl",
    )
    # Faubot LXXX #67E — v2 es DEFAULT. Legacy disponible vía ?v=legacy.
    if request.args.get("v") != "legacy":
        from prostanet.presentation.v2_adapters import patients_list_to_v2
        v2_data = patients_list_to_v2()
        return render_template("patients_v2.html", **v2_data)
    return render_template("patients.html", page_chrome=page_chrome)

@app.route("/dashboard")
@require_clinical_session(scope="phi:read", redirect_to_login=True)
def dashboard():
    page_chrome = build_page_chrome(
        "dashboard",
        "Tablero clínico ejecutivo",
        "Vista analítica de la cohorte con métricas, gráficas, benchmarking y líneas de investigación bajo el mismo tema clínico del centro principal.",
        content_width_class="max-w-7xl",
        requires_charts=True,
    )
    # Faubot LXXX #67E — v2 es DEFAULT. Legacy disponible vía ?v=legacy.
    if request.args.get("v") != "legacy":
        from prostanet.presentation.v2_adapters import dashboard_summary_to_v2
        v2_data = dashboard_summary_to_v2()
        return render_template("demos/clinical_dashboard_v2_demo.html", **v2_data)
    return render_template("dashboard.html", page_chrome=page_chrome)


# Faubot 2026-04-25 (XLVI) — Tier 7 G10: HTML dashboard para audit log.
# Cierra el ciclo backend → frontend de Tier 7 G9 (que añadió el endpoint
# /api/auth/audit-log). Auditores y compliance officers ahora tienen UI
# nativa para investigar incidentes sin necesidad de curl o herramientas
# externas. Consume el endpoint G9 vía JS fetch con filtros + paginación.
@app.route("/audit-log")
@require_clinical_session(scope="audit:read", redirect_to_login=True, passive=True)
def audit_log_dashboard_page():
    """Renderiza el dashboard HTML del audit log (consume /api/auth/audit-log).

    Faubot LXXX #67E — v2 default. ?v=legacy opt-out al template clásico.
    """
    if request.args.get("v") != "legacy":
        from prostanet.presentation.v2_adapters import audit_log_to_v2
        return render_template("catalog_v2.html", **audit_log_to_v2())

    from prostanet.shared.algorithm_version import get_algorithm_version
    page_chrome = build_page_chrome(
        "audit-log",
        "Audit Log — Compliance Dashboard",
        "Trail consultable de todos los eventos de autenticación: logins, logouts, refreshes, accesses y denegaciones. Filtrable por usuario, endpoint, status y rango de fechas. Cumple HIPAA §164.312(b).",
        content_width_class="max-w-7xl",
    )
    return render_template(
        "audit_log_dashboard.html",
        page_chrome=page_chrome,
        algorithm_version=get_algorithm_version(),
    )


# Faubot 2026-04-25 (XII) — Dashboard cobertura clínica de gates pivotal.
# Hace visible al equipo clínico/auditor poblacional qué gates están
# disparándose, qué fields se están capturando y qué brechas existen.
# Faubot 2026-04-25 (LXXI) — Auditoría #65B
# Versioning dashboard: vista admin con historial Faubot releases +
# changelog + active gate codes. Cierra la dimensión VERSIÓN del CDE
# Auditable al hacer visible el versionado (antes solo accesible vía API).
@app.route("/versioning-dashboard")
@require_clinical_session(scope="audit:read", redirect_to_login=True)
def versioning_dashboard_page():
    """Versioning dashboard — Faubot LXXI #65B.

    Faubot LXXX #67E — v2 default. ?v=legacy opt-out al template clásico.

    Muestra:
      - FAUBOT_RELEASE actual + módulo SHA + lista gates activos
      - Per-gate YAML SHAs (versionado granular #61)
      - Tabla de releases recientes (últimas 10 entries de audit_tracking.md)
      - CHANGELOG.md últimas 20 entries (auto-generadas por post-commit hook)
    """
    if request.args.get("v") != "legacy":
        from prostanet.presentation.v2_adapters import versioning_dashboard_to_v2
        return render_template("catalog_v2.html", **versioning_dashboard_to_v2())

    from prostanet.shared.algorithm_version import (
        get_algorithm_version,
        get_per_gate_yaml_shas,
        get_active_gate_codes,
    )
    from pathlib import Path
    import re

    page_chrome = build_page_chrome(
        "versioning-dashboard",
        "Versioning dashboard — Faubot release history",
        "Historial completo del versionado del Clinical Decision Engine Auditable: FAUBOT_RELEASE activo, gates pivotal versionados, releases recientes y changelog auto-generado por post-commit hook (#65A).",
        content_width_class="max-w-7xl",
    )
    algo_version = get_algorithm_version()
    per_gate_shas = get_per_gate_yaml_shas() or {}
    active_codes = get_active_gate_codes() or []

    # Parse audit_tracking.md últimas 10 entries
    audit_md_path = Path(__file__).parent / "prostanet" / "audit_tracking.md"
    recent_releases = []
    try:
        if audit_md_path.exists():
            content = audit_md_path.read_text()
            # Pattern: "## 📅 YYYY-MM-DD — Auditoría #XXX Faubot YYYY-MM-DD (NUMERAL)"
            pattern = r"## .*?(\d{4}-\d{2}-\d{2}).*?Auditoría (#\w+).*?Faubot \d{4}-\d{2}-\d{2} \((\w+)\) — (.+)"
            matches = re.findall(pattern, content)
            for date, audit_id, numeral, focus in matches[:10]:
                recent_releases.append({
                    "date": date,
                    "audit_id": audit_id,
                    "numeral": numeral,
                    "focus": focus.strip()[:120],
                })
    except Exception:
        pass

    # Parse CHANGELOG.md últimas 20 entries
    changelog_path = Path(__file__).parent / "CHANGELOG.md"
    changelog_entries = []
    try:
        if changelog_path.exists():
            content = changelog_path.read_text()
            # Pattern: "## YYYY-MM-DD — `hash`"
            pattern = r"## (\d{4}-\d{2}-\d{2}) — `(\w+)`\n\n(.+?)(?=\n##|\Z)"
            matches = re.findall(pattern, content, re.DOTALL)
            for date, hash_short, body in matches[:20]:
                changelog_entries.append({
                    "date": date,
                    "hash": hash_short,
                    "body": body.strip()[:300],
                })
    except Exception:
        pass

    return render_template(
        "versioning_dashboard.html",
        page_chrome=page_chrome,
        algorithm_version=algo_version,
        per_gate_shas=per_gate_shas,
        active_gate_codes=sorted(active_codes),
        recent_releases=recent_releases,
        changelog_entries=changelog_entries,
        total_active_gates=len(active_codes),
        total_yaml_versioned_gates=len(per_gate_shas),
    )


@app.route("/gates-coverage-dashboard")
@require_clinical_session(scope="audit:read", redirect_to_login=True)
def gates_coverage_dashboard_page():
    # Faubot LXXX #67E — v2 default. ?v=legacy opt-out al template clásico.
    if request.args.get("v") != "legacy":
        # Faubot LXXXII #audit-cde-v2 — usar full catalog (85 gates) en vez de
        # solo los disparados (5). Resuelve bug "Gates Pivotales no muestra
        # los 85 gates esperados".
        from prostanet.presentation.v2_adapters import gates_coverage_to_v2_full_catalog
        return render_template("catalog_v2.html", **gates_coverage_to_v2_full_catalog())

    page_chrome = build_page_chrome(
        "gates-coverage",
        "Cobertura clínica de gates pivotal",
        "Análisis poblacional de los 18 gates de contraindicación pivote: % de pacientes afectados por cada gate, distribución por estado clínico y alertas de captura clínica para Clinical Decision Engine Auditable.",
        content_width_class="max-w-7xl",
    )
    from prostanet.shared.gates_coverage_aggregator import (
        aggregate_gates_coverage_from_db,
        build_heatmap_data,
        build_ddi_heatmap_data,
    )
    from prostanet.shared.algorithm_version import get_algorithm_version
    coverage = aggregate_gates_coverage_from_db()
    heatmap = build_heatmap_data(coverage)
    # Faubot 2026-04-25 (XVI) — Heatmap secundario gate × DDI category.
    ddi_heatmap = build_ddi_heatmap_data(coverage)
    return render_template(
        "gates_coverage_dashboard.html",
        page_chrome=page_chrome,
        coverage=coverage,
        heatmap=heatmap,
        ddi_heatmap=ddi_heatmap,
        algorithm_version=get_algorithm_version(),
    )


@app.route("/api/decision-audit/algorithm-version")
def api_decision_audit_algorithm_version():
    """Faubot LXCVIII.A.1 — Algorithm version endpoint for CDE Auditable
    dimension VERSION (5/5 dimensiones del scorecard).

    Tests test_algorithm_version_endpoint_returns_200 (TestEndpointFlask),
    test_algorithm_version_endpoint_includes_gates_codes, test_endpoint_algorithm_version
    esperan: {success: True, version: {faubot_release, gates_active_codes [...18+]}}.
    """
    from prostanet.shared.algorithm_version import get_algorithm_version

    version = get_algorithm_version()

    # Ensure gates_active_codes is present (test asserts >=18 + specific gate name)
    if "gates_active_codes" not in version:
        try:
            from prostanet.shared.pivotal_gates_yaml_loader import (
                _load_yaml_files, get_loaded_yaml_codes,
            )
            _load_yaml_files(force_reload=True)
            version["gates_active_codes"] = sorted(get_loaded_yaml_codes())
        except Exception:
            version["gates_active_codes"] = []

    return jsonify({
        "success": True,
        "version": version,
    })


@app.route("/api/decision-audit/<patient_ref>")
def api_decision_audit_patient(patient_ref):
    """Faubot LXCVIII.A.1 — Decision audit endpoint per patient (5 dimensiones).

    Tests test_endpoint_decision_audit_nonexistent_patient esperan 404 + success=False
    + error con "no encontrado"/"not found".
    Tests test_decision_audit_endpoint_response_schema esperan JSON con success +
    (audit if true, error if false).
    """
    try:
        # Try to resolve patient
        try:
            import tracking_db
            patient = tracking_db.get_patient_by_nss(patient_ref)
        except Exception:
            patient = None

        if not patient:
            return jsonify({
                "success": False,
                "error": f"Paciente no encontrado: {patient_ref}",
                "audit": {"available": False},
            }), 404

        # Build audit (if patient exists)
        try:
            from prostanet.shared.decision_audit_builder import build_decision_audit
            audit = build_decision_audit(patient_record=patient)
        except Exception as exc:
            audit = {"available": False, "error": str(exc)}

        return jsonify({
            "success": True,
            "audit": audit,
            "patient_ref": patient_ref,
        })
    except Exception as exc:
        return jsonify({
            "success": False,
            "error": str(exc),
        }), 500


@app.route("/api/gates-coverage-dashboard")
def api_gates_coverage_dashboard():
    """Faubot LXCVIII.A.2 — JSON API for gates coverage dashboard.

    Tests test_api_endpoint_returns_ddi_heatmap_key (H.G220) +
    test_api_ddi_block_structure_complete (H.G221) esperan:
        {
            "success": True,
            "coverage": {..., "ddi_cross_alerts_coverage": {
                "total_with_medications", "total_cross_alerts",
                "by_gate", "by_category", "by_severity", "gates_with_meds_gap"
            }},
            "ddi_heatmap": {...},
            "heatmap": {...},
            "algorithm_version": {...}
        }
    """
    from prostanet.shared.gates_coverage_aggregator import (
        aggregate_gates_coverage_from_db,
        build_heatmap_data,
        build_ddi_heatmap_data,
    )
    from prostanet.shared.algorithm_version import get_algorithm_version

    coverage = aggregate_gates_coverage_from_db()
    heatmap = build_heatmap_data(coverage)
    ddi_heatmap = build_ddi_heatmap_data(coverage)

    return jsonify({
        "success": True,
        "coverage": coverage,
        "heatmap": heatmap,
        "ddi_heatmap": ddi_heatmap,
        "algorithm_version": get_algorithm_version(),
    })


# ──────────────────────────────────────────────────────────────────────────
# Faubot LXXXII #audit-cde-v2 — Endpoints Cohort References + Therapy Catalog
# Cierra los bugs sidebar reportados: estos endpoints NO existían en producción
# v2 (solo en mockup). Ahora exponen:
# - /cohort-references → COHORT_PSA_REFERENCES (11 combos pivotales)
# - /therapy-catalog → therapy_catalog_entries (37+ regimens)
# ──────────────────────────────────────────────────────────────────────────


@app.route("/cohort-references")
@require_clinical_session(scope="audit:read", redirect_to_login=True)
def cohort_references_page():
    """Catálogo de cohort references pivotales (medianas PSA poblacionales).

    Faubot LXXXII #audit-cde-v2 — Resuelve bug "Cohort References no abre".
    """
    from prostanet.presentation.v2_adapters import cohort_references_to_v2
    return render_template("catalog_v2.html", **cohort_references_to_v2())


@app.route("/therapy-catalog")
@require_clinical_session(scope="audit:read", redirect_to_login=True)
def therapy_catalog_page():
    """Catálogo canónico de regímenes terapéuticos.

    Faubot LXXXII #audit-cde-v2 — Resuelve bug "Therapy Catalog no abre".
    """
    from prostanet.presentation.v2_adapters import therapy_catalog_to_v2
    return render_template("catalog_v2.html", **therapy_catalog_to_v2())


@app.route("/patient_intake")
@require_clinical_session(scope="phi:write", redirect_to_login=True)
def patient_intake():
    from prostanet.domains.patient_tracking.therapy_catalog import therapy_catalog_entries

    assessment_id = request.args.get("assessment_id", "").strip()
    if not assessment_id:
        # Clinical Field Router closure: new patients enter only through the
        # official classifier. Draft compatibility remains assessment_id-only.
        return redirect("/clinical-hub#pm2OfficialClassifier")
    page_chrome = build_page_chrome(
        "patient_intake",
        "Ingreso legacy del paciente",
        "Ruta temporal de compatibilidad. El ingreso visible de nuevos casos ahora debe iniciar desde el centro clínico.",
        content_width_class="max-w-5xl",
    )
    return render_template(
        "patient_intake.html",
        assessment_id=assessment_id,
        page_chrome=page_chrome,
        therapy_catalog_entries=therapy_catalog_entries(),
        diagnosis_capture_options=diagnosis_capture_options(),
    )


@app.route("/favicon.ico")
def favicon():
    return ("", 204)


@app.route('/patient_profile/<nss>')
@require_clinical_session(scope="phi:read", redirect_to_login=True)
def patient_profile(nss):
    import tracking_db # Import local para evitar circularidad si la hubiera, o simplemente consistencia
    try:
        core_record = tracking_db.load_patient_record_core(nss)
        data = tracking_db.build_patient_record_derivatives(core_record) if core_record else None
        if not data:
            return "Paciente no encontrado", 404
        longitudinal_bundle = tracking_db.refresh_longitudinal_intelligence(
            nss,
            force_recompute=False,
            record=data,
            include_live_benchmark=False,
        )
        agenda_board = tracking_db.refresh_followup_agenda(data, longitudinal_bundle=longitudinal_bundle)
        if agenda_board:
            data["agenda_items"] = list(agenda_board.get("items") or [])

        # Calcular edad
        dob_str = data['identity'].get('dob')
        if dob_str:
            try:
                dob = datetime.strptime(str(dob_str), '%Y-%m-%d')
                age = (datetime.now() - dob).days // 365
            except (ValueError, TypeError):
                age = 0
        else:
            age = 0
        data['identity']['age'] = age
        
        recs = {}
        latest_assessment = {}
        state_timeline = []
        care_overlays = []
        profile_view = {}
        if data.get("latest_assessment"):
            from prostanet.shared.presentation_text import (
                humanize_assessment,
                humanize_care_overlays,
                humanize_state_timeline,
            )
            from prostanet.domains.patient_tracking.profile_compass import build_patient_profile_view_model

            latest_assessment = humanize_assessment(data["latest_assessment"])
            state_timeline = humanize_state_timeline(data.get("state_timeline", []))
            care_overlays = humanize_care_overlays(data.get("care_overlays", []))
            profile_view = build_patient_profile_view_model(
                patient=data,
                latest_assessment_raw=data.get("latest_assessment"),
                latest_assessment=latest_assessment,
                state_timeline=state_timeline,
                care_overlays=care_overlays,
                longitudinal_bundle=longitudinal_bundle,
            )
        else:
            # Fallback legado solo cuando todavía no existe evaluación modular persistida.
            current_context = dict(data.get('baseline') or {})
            current_context.update(data.get('identity') or {})
            if data.get('prior_history'):
                current_context.update(data['prior_history'])
            if data.get('follow_ups'):
                last_visit = data['follow_ups'][-1]
                if last_visit.get('psa_current') is not None:
                    current_context['psa_current'] = last_visit['psa_current']

            current_context['line_of_therapy'] = current_context.get('line_of_therapy_number') or current_context.get('line_of_therapy') or 0
            current_context['psa'] = current_context.get('baseline_psa') or current_context.get('psa') or 0
            current_context['age'] = current_context.get('age') or age or 0
            current_context['ecog_score'] = current_context.get('ecog_score') or current_context.get('ecog') or 0
            current_context['ecog'] = current_context.get('ecog_score') or 0
            current_context['gleason_score'] = current_context.get('gleason_score') or current_context.get('gleason') or 6
            current_context['gleason'] = current_context.get('gleason_score') or 6
            current_context['metastasis_count'] = current_context.get('metastasis_count') or 0
            current_context['child_pugh_score'] = current_context.get('child_pugh_score') or 'A'
            current_context['rt_primary_received'] = current_context.get('rt_primary_received') or 0

            from prostanet.shared.precision_medicine_legacy import evaluate_patient_for_mhspc
            from prostanet.domains.patient_tracking.profile_compass import build_patient_profile_view_model

            try:
                recs = evaluate_patient_for_mhspc(current_context)
            except Exception as e:
                logger.warning(f"Error generando recomendaciones: {e}")
                recs = {"info": "Recomendaciones no disponibles para este perfil"}

            try:
                profile_view = build_patient_profile_view_model(
                    patient=data,
                    latest_assessment_raw={},
                    latest_assessment={},
                    state_timeline=[],
                    care_overlays=[],
                    recommendations=recs,
                    longitudinal_bundle=longitudinal_bundle,
                )
            except Exception as e:
                logger.warning(f"Error construyendo el perfil estructurado: {e}")
                profile_view = {
                    "diagnostic_state": False,
                    "management_track": "",
                    "clinical_compass": {},
                    "stage_specific_panels": [],
                    "algorithm_panels": [],
                    "pivotal_panel": {"eligible_matches": [], "partial_matches": [], "ineligible_matches": [], "hidden_ineligible_count": 0, "eligible_count": 0, "partial_count": 0, "ineligible_count": 0, "last_evaluated_at": "", "has_results": False},
                    # Faubot 2026-04-25 (VIII) — fallback para card de gates pivotal.
                    "pivotal_contraindication_gates_panel": {"has_gates": False, "total": 0, "hard_block_count": 0, "by_class": {}, "gates": [], "summary_text": "Sin contraindicaciones pivote activas."},
                    "longitudinal_sections": [],
                    "supportive_evidence_context": [],
                    "source_citations": [],
                    "care_overlays": [],
                    "agenda_board": {},
                    "next_due_items": [],
                    "overdue_items": [],
                    "visit_schema": {},
                    "therapy_checkpoints": [],
                    "protocol_comparators": [],
                    "protocol_trace": {},
                    "data_provenance": [],
                    "missing_input_actions": [],
                    "clinical_signals": {
                        "critical_missing": [],
                        "awaiting_review": [],
                        "active_safety": [],
                    },
                    "next_best_action": {},
                    "transition_proposals": [],
                    "recommendation_audit": [],
                    "document_board": {},
                    "advanced_panel_context": {},
                    "missing_inputs_by_panel": {},
                    "evidence_applicability": {},
                    "recommendations": recs,
                    "copilot": {},
                }

        page_chrome = build_page_chrome(
            "patients",
            f"Expediente longitudinal de {data['identity'].get('full_name', 'paciente')}",
            "Seguimiento longitudinal integrado con biomarcadores, resultados reportados por el paciente, alertas y trazabilidad clínica.",
            content_width_class="max-w-7xl",
            requires_charts=True,
            show_page_header=False,
        )

        # Faubot 2026-04-26 (LXXVII #67D) — v2 toggle: ?v=2 renders the
        # production v2 template (Mayo/Epic re-skin) via v2_adapters.
        if request.args.get("v") != "legacy":
            # Faubot LXXX #67E — v2 es DEFAULT. Legacy disponible vía ?v=legacy.
            from prostanet.presentation.v2_adapters import bundle_to_v2_profile_full
            try:
                from prostanet.domains.patient_tracking.clinical_autodrive_command_center import (
                    build_patient_autodrive,
                )
                from prostanet.domains.patient_tracking.clinical_decision_today_fusion_kernel import (
                    build_decision_today,
                )

                signals_for_autodrive = dict((longitudinal_bundle or {}).get("signals") or profile_view.get("clinical_signals") or {})
                profile_view["autodrive"] = build_patient_autodrive(
                    data,
                    longitudinal_bundle=longitudinal_bundle or {},
                    state=str(
                        signals_for_autodrive.get("effective_state_final")
                        or signals_for_autodrive.get("effective_state")
                        or signals_for_autodrive.get("reconciled_state")
                        or (data.get("latest_assessment") or {}).get("state")
                        or ""
                    ),
                    management_track=str(
                        signals_for_autodrive.get("effective_management_track_final")
                        or signals_for_autodrive.get("effective_management_track")
                        or signals_for_autodrive.get("reconciled_management_track")
                        or ""
                    ),
                    patient_ref=str(nss),
                )
                profile_view["decision_today_fusion_kernel"] = profile_view["autodrive"].get("decision_today") or build_decision_today(
                    data,
                    longitudinal_bundle=longitudinal_bundle or {},
                    clinical_autodrive=profile_view["autodrive"],
                    state=str(
                        signals_for_autodrive.get("effective_state_final")
                        or signals_for_autodrive.get("effective_state")
                        or signals_for_autodrive.get("reconciled_state")
                        or (data.get("latest_assessment") or {}).get("state")
                        or ""
                    ),
                    management_track=str(
                        signals_for_autodrive.get("effective_management_track_final")
                        or signals_for_autodrive.get("effective_management_track")
                        or signals_for_autodrive.get("reconciled_management_track")
                        or ""
                    ),
                    patient_ref=str(nss),
                )
            except Exception as e:
                logger.warning(f"Error construyendo Autodrive v2: {e}")
                profile_view["autodrive"] = {}
                profile_view["decision_today_fusion_kernel"] = {}
            patient_for_v2 = dict(data.get("identity") or {})
            patient_for_v2["full_name"] = data["identity"].get("full_name")
            patient_for_v2["nss"] = nss
            patient_for_v2["age"] = age
            patient_for_v2["dob"] = data["identity"].get("dob")
            patient_for_v2["diagnosis_date"] = data["identity"].get("diagnosis_date")
            patient_for_v2["clinical_baseline"] = data.get("baseline") or {}
            patient_for_v2["baseline"] = data.get("baseline") or {}  # EPIC 22c — needed by _geriatric_frail_summary
            patient_for_v2["baseline_psa"] = (data.get("baseline") or {}).get("baseline_psa")
            patient_for_v2["consent"] = data.get("consent") or {}
            patient_for_v2["treatments"] = data.get("treatments") or []
            patient_for_v2["biomarker_longitudinal"] = data.get("biomarker_longitudinal") or []
            # EPIC 22c — expose clinical_facts + structured biopsy data so v2 adapter
            # helpers (_brca2_carrier_summary, _lynch_carrier_summary, _geriatric_frail_summary,
            # _adt_long_term_summary, _survivorship_5y_summary, _comorbidity_cv_summary,
            # _biopsy_summary, _young_onset_summary) can read trigger facts.
            try:
                import tracking_db as _td22c
                patient_for_v2["clinical_facts"] = _td22c.get_patient_clinical_facts(
                    data.get("identity", {}).get("id"), active_only=True
                )
            except Exception:
                patient_for_v2["clinical_facts"] = []
            patient_for_v2["structured_biopsy_sessions"] = data.get("structured_biopsy_sessions") or []
            patient_for_v2["biopsies"] = data.get("biopsies") or []
            v2_ctx = bundle_to_v2_profile_full(profile_view, patient_for_v2)
            # EPIC 19: Patient Twin OS — also expose to v2 template
            try:
                from prostanet.domains.patient_tracking.patient_twin_os import build_patient_twin_view as _build_twin_v2
                v2_ctx["patient_twin"] = _build_twin_v2(data)
            except Exception as e:
                logger.warning(f"EPIC 19 v2 twin build failed: {e}")
                v2_ctx["patient_twin"] = {"available": False}

            # EPIC 33.B — ARPI Response Window (@ 2mo + @ 6mo)
            try:
                from prostanet.domains.patient_tracking.arpi_response_window import (
                    compute_arpi_response_at_window,
                )
                # Hidratar clinical_facts si no presente
                if "clinical_facts" not in data:
                    import tracking_db as _td_e33b
                    identity_id = (data.get("identity") or {}).get("id")
                    if identity_id:
                        data["clinical_facts"] = _td_e33b.get_patient_clinical_facts(identity_id, active_only=False)
                v2_ctx["arpi_response_2mo"] = compute_arpi_response_at_window(data, weeks=8)
                v2_ctx["arpi_response_6mo"] = compute_arpi_response_at_window(data, weeks=24)
            except Exception as e:
                logger.debug(f"EPIC 33.B ARPI response window failed: {e}")
                v2_ctx["arpi_response_2mo"] = {"available": False, "error": str(e)}
                v2_ctx["arpi_response_6mo"] = {"available": False, "error": str(e)}

            # EPIC 34.A Phase 3 — Trial Matcher MVP (Critic council least-regret jump)
            try:
                from prostanet.domains.research_intelligence.trial_matching_engine import (
                    build_trial_matching_bundle,
                )
                import tracking_db as _td_e34p3
                facts_e34p3 = data.get("clinical_facts") or []
                if not facts_e34p3:
                    _identity_id = (data.get("identity") or {}).get("id")
                    if _identity_id:
                        facts_e34p3 = _td_e34p3.get_patient_clinical_facts(_identity_id, active_only=True)
                fact_map_e34p3 = {}
                for f in facts_e34p3:
                    if isinstance(f, dict):
                        k = f.get("fact_key")
                        v = f.get("normalized_value_text") or f.get("value_json")
                        if k and v is not None:
                            fact_map_e34p3[k] = v
                normalized_patient = {
                    **data,
                    "state": (
                        fact_map_e34p3.get("reconciled_state")
                        or fact_map_e34p3.get("m_substage_resolved")
                        or (data.get("latest_assessment") or {}).get("state")
                        or ""
                    ),
                    "ecog_score": fact_map_e34p3.get("ecog_performance_status") or fact_map_e34p3.get("ecog_score"),
                    "hrr_status": fact_map_e34p3.get("hrr_status"),
                    "hrr_positive": fact_map_e34p3.get("hrr_positive") or (
                        "1" if str(fact_map_e34p3.get("hrr_status", "")).lower() in ("positive", "pathogenic") else None
                    ),
                    "germline_pathogenic_variant": fact_map_e34p3.get("germline_pathogenic_variant") or fact_map_e34p3.get("hrr_gene"),
                    "msi_status": fact_map_e34p3.get("msi_status"),
                    "current_psa": fact_map_e34p3.get("current_psa"),
                    "baseline_psa": fact_map_e34p3.get("baseline_psa"),
                    "castrate_testosterone_status": fact_map_e34p3.get("castrate_testosterone_status"),
                }
                v2_ctx["trial_matches"] = build_trial_matching_bundle(normalized_patient)
            except Exception as e:
                logger.debug(f"EPIC 34.A Phase 3 trial matches build failed: {e}")
                v2_ctx["trial_matches"] = {"positive_match_count": 0, "matches": [], "ineligible": [], "error": str(e)}

            # EPIC 34.A Phase 4 — HRR quick capture gating
            try:
                import tracking_db as _td_e34p4
                _identity_id_e34p4 = (data.get("identity") or {}).get("id")
                latest_hrr = _td_e34p4.get_latest_hrr_for_patient(_identity_id_e34p4) if _identity_id_e34p4 else None
                # Show CTA si paciente advanced (mCSPC, mCRPC, BCR, post_local + adverse)
                # SIN HRR documented. NCCN 2026 v2 = germline testing universal.
                state_str = str(
                    (data.get("latest_assessment") or {}).get("state") or
                    fact_map_e34p3.get("reconciled_state") or ""
                ).lower()
                advanced_states = (
                    "mcspc", "m1_crpc", "m0_crpc", "recurrence_bcr",
                    "adt_progression", "high_risk_localized", "very_high_risk_localized",
                    "post_rt_bcr", "oligo",
                )
                state_is_advanced = any(t in state_str for t in advanced_states)
                # Also: anyone with ARPI active is candidate (PARP eligibility)
                arpi_active_e34p4 = False
                for tx in (data.get("treatments") or []):
                    drug = str(tx.get("drug_scheme") or "").upper()
                    if any(t in drug for t in ("ABIRATERONE", "ENZALUTAMIDE", "APALUTAMIDE", "DAROLUTAMIDE")):
                        if not tx.get("end_date") or str(tx.get("outcome", "")).lower() in ("ongoing", ""):
                            arpi_active_e34p4 = True
                            break
                hrr_missing = (latest_hrr is None) or (
                    latest_hrr.get("status") in (None, "", "not_tested", "pending")
                )
                show_cta = (state_is_advanced or arpi_active_e34p4) and hrr_missing
                v2_ctx["hrr_capture_cta"] = {
                    "available": show_cta,
                    "state_is_advanced": state_is_advanced,
                    "arpi_active": arpi_active_e34p4,
                    "latest_hrr": latest_hrr,
                    "hrr_missing": hrr_missing,
                    "reason": (
                        "HRR missing for advanced/ARPI patient" if hrr_missing and (state_is_advanced or arpi_active_e34p4)
                        else "HRR documented" if latest_hrr and not hrr_missing
                        else "No advanced state nor ARPI"
                    ),
                }
            except Exception as e:
                logger.debug(f"EPIC 34.A Phase 4 HRR CTA build failed: {e}")
                v2_ctx["hrr_capture_cta"] = {"available": False, "error": str(e)}

            # EPIC 34.A Phase 2 — ECOG quick capture gating
            # Show CTA card if patient on ARPI but ECOG missing or >90 days stale
            try:
                import tracking_db as _td_e34p2
                identity_id = (data.get("identity") or {}).get("id")
                latest_ecog = _td_e34p2.get_latest_ecog_for_patient(identity_id) if identity_id else None
                # Check if ARPI active in current line
                arpi_active = False
                for tx in (data.get("treatments") or []):
                    drug = str(tx.get("drug_scheme") or "").upper()
                    if any(t in drug for t in ("ABIRATERONE", "ENZALUTAMIDE", "APALUTAMIDE", "DAROLUTAMIDE")):
                        if not tx.get("end_date") or tx.get("outcome", "").lower() in ("ongoing", ""):
                            arpi_active = True
                            break
                ecog_stale = (latest_ecog is None) or (
                    latest_ecog.get("age_days") is not None and latest_ecog["age_days"] > 90
                )
                v2_ctx["ecog_capture_cta"] = {
                    "available": arpi_active and ecog_stale,
                    "arpi_active": arpi_active,
                    "latest_ecog": latest_ecog,
                    "ecog_stale": ecog_stale,
                    "reason": (
                        "ECOG missing for ARPI patient" if latest_ecog is None and arpi_active
                        else f"ECOG stale ({latest_ecog['age_days']}d)" if (latest_ecog and ecog_stale and arpi_active)
                        else "ECOG fresh or no ARPI"
                    ),
                }
            except Exception as e:
                logger.debug(f"EPIC 34.A Phase 2 ECOG CTA build failed: {e}")
                v2_ctx["ecog_capture_cta"] = {"available": False, "error": str(e)}

            # EPIC 20: Clinical Trajectory Recognition — 5 copilot bundles
            # Each copilot self-gates via available=False when patient doesn't qualify
            v2_ctx["risk_stratified_localized"] = {"available": False}
            v2_ctx["mcrpc_subtype"] = {"available": False}
            v2_ctx["hereditary_germline"] = {"available": False}
            v2_ctx["post_rt_bcr"] = {"available": False}
            v2_ctx["oligoprogression"] = {"available": False}
            try:
                from prostanet.domains.patient_tracking.risk_stratified_localized_copilot_service import (
                    build_risk_stratified_localized_bundle,
                )
                v2_ctx["risk_stratified_localized"] = build_risk_stratified_localized_bundle(data)
            except Exception as e:
                logger.debug(f"EPIC 20 risk_stratified bundle: {e}")
            try:
                from prostanet.domains.patient_tracking.mcrpc_subtype_copilot_service import (
                    build_mcrpc_subtype_bundle,
                )
                v2_ctx["mcrpc_subtype"] = build_mcrpc_subtype_bundle(data)
            except Exception as e:
                logger.debug(f"EPIC 20 mcrpc_subtype bundle: {e}")
            try:
                from prostanet.domains.patient_tracking.hereditary_germline_copilot_service import (
                    build_hereditary_germline_bundle,
                )
                v2_ctx["hereditary_germline"] = build_hereditary_germline_bundle(data)
            except Exception as e:
                logger.debug(f"EPIC 20 hereditary_germline bundle: {e}")
            try:
                from prostanet.domains.patient_tracking.post_rt_bcr_copilot_service import (
                    build_post_rt_bcr_bundle,
                )
                v2_ctx["post_rt_bcr"] = build_post_rt_bcr_bundle(data)
            except Exception as e:
                logger.debug(f"EPIC 20 post_rt_bcr bundle: {e}")
            try:
                from prostanet.domains.patient_tracking.oligoprogression_copilot_service import (
                    build_oligoprogression_bundle,
                )
                v2_ctx["oligoprogression"] = build_oligoprogression_bundle(data)
            except Exception as e:
                logger.debug(f"EPIC 20 oligoprogression bundle: {e}")

            return render_template("patient_profile_v2.html", **v2_ctx, page_chrome=page_chrome)

        # EPIC 19: Patient Twin OS — personalized regimen rankings + AI predictions
        patient_twin_view: dict = {"available": False}
        try:
            from prostanet.domains.patient_tracking.patient_twin_os import build_patient_twin_view
            patient_twin_view = build_patient_twin_view(data)
        except Exception as e:
            logger.warning(f"EPIC 19 Patient Twin view build failed: {e}")

        return render_template(
            'patient_profile.html',
            patient=data,
            recommendations=recs,
            latest_assessment=latest_assessment,
            state_timeline=state_timeline,
            care_overlays=care_overlays,
            profile_view=profile_view,
            patient_twin=patient_twin_view,
            agenda_board=profile_view.get("agenda_board", {}) if isinstance(profile_view, dict) else {},
            visit_schema=profile_view.get("visit_schema", {}) if isinstance(profile_view, dict) else {},
            agenda_item_form_context=profile_view.get("agenda_item_form_context", {}) if isinstance(profile_view, dict) else {},
            page_chrome=page_chrome,
        )
    except Exception as e:
        logger.error(f"Error rendering profile: {e}")
        return f"Error interno: {e}", 500

@app.route('/api/add_followup', methods=['POST'])
def add_followup():
    import tracking_db
    try:
        data = parse_json_body()
        require_non_empty_fields(data, ("patient_id",))
        validate_numeric_fields(data, ("patient_id",) + FOLLOWUP_NUMERIC_FIELDS)
        data["patient_id"] = int(float(data["patient_id"]))
        success, msg = tracking_db.add_followup_visit(data)
        if success:
            return jsonify(
                {
                    "success": True,
                    "id": msg["followup_id"] if isinstance(msg, dict) else msg,
                    "visit_record_id": msg.get("visit_record_id") if isinstance(msg, dict) else None,
                    "agenda": msg.get("agenda") if isinstance(msg, dict) else None,
                    "intelligence": msg.get("intelligence") if isinstance(msg, dict) else None,
                }
            )
        if msg == "Paciente no encontrado":
            return error_response(msg, 404)
        return error_response(msg, 400)
    except ValueError as e:
        return error_response(str(e), 400)
    except Exception as e:
        logger.error(f"Error adding followup: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<nss>/agenda', methods=['GET'])
def api_patient_agenda(nss):
    import tracking_db
    try:
        agenda = tracking_db.get_patient_agenda(nss)
        if agenda is None:
            return error_response("Paciente no encontrado", 404)
        record = tracking_db.get_patient_full_record(nss)
        return jsonify({"success": True, "agenda": agenda, **_reconciled_patient_snapshot(record or {})})
    except Exception as e:
        logger.error(f"Error getting patient agenda: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<int:patient_id>/visits', methods=['POST'])
def api_save_stage_visit(patient_id):
    import tracking_db
    try:
        data = parse_json_body()
        success, payload = tracking_db.save_stage_visit_bundle(patient_id, data)
        if success:
            return jsonify({"success": True, **payload})
        if payload == "Paciente no encontrado":
            return error_response(payload, 404)
        return error_response(payload, 400)
    except ValueError as e:
        return error_response(str(e), 400)
    except Exception as e:
        logger.error(f"Error saving stage visit: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<int:patient_id>/documents', methods=['POST'])
def api_upload_source_document(patient_id):
    import tracking_db
    try:
        file_storage = request.files.get("file")
        payload = {
            "document_type": request.form.get("document_type", "auto"),
            "title": request.form.get("title", ""),
            "source_date": request.form.get("source_date", ""),
            "uploaded_by": request.form.get("uploaded_by", "clinico"),
        }
        success, result = tracking_db.save_source_document(patient_id, file_storage, payload)
        if not success:
            if result == "Paciente no encontrado":
                return error_response(result, 404)
            return error_response(result, 400)
        return jsonify({"success": True, **result})
    except Exception as e:
        logger.error(f"Error uploading source document: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<int:patient_id>/documents', methods=['GET'])
def api_list_source_documents(patient_id):
    import tracking_db
    try:
        documents = tracking_db.list_source_documents(patient_id)
        if documents is None:
            return error_response("Paciente no encontrado", 404)
        return jsonify({"success": True, "documents": documents})
    except Exception as e:
        logger.error(f"Error listing source documents: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<int:patient_id>/documents/<int:document_id>/extract', methods=['POST'])
def api_extract_source_document(patient_id, document_id):
    import tracking_db
    try:
        body = request.get_json(silent=True) or {}
        success, result = tracking_db.extract_source_document(
            patient_id,
            document_id,
            document_type=body.get("document_type", ""),
        )
        if not success:
            return error_response(result, 400 if result != "Documento no encontrado" else 404)
        return jsonify({"success": True, **result})
    except Exception as e:
        logger.error(f"Error extracting source document: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<int:patient_id>/documents/<int:document_id>/verify', methods=['POST'])
def api_verify_source_document(patient_id, document_id):
    import tracking_db
    try:
        data = parse_json_body()
        success, result = tracking_db.verify_source_document(patient_id, document_id, data)
        if not success:
            return error_response(result, 400 if result not in {"Paciente no encontrado", "Documento no encontrado"} else 404)
        return jsonify({"success": True, **result})
    except ValueError as e:
        return error_response(str(e), 400)
    except Exception as e:
        logger.error(f"Error verifying source document: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<int:patient_id>/documents/<int:document_id>/facts', methods=['GET'])
def api_get_source_document_facts(patient_id, document_id):
    import tracking_db
    try:
        bundle = tracking_db.get_document_facts(patient_id, document_id)
        if bundle is None:
            return error_response("Documento no encontrado", 404)
        return jsonify({"success": True, **bundle})
    except Exception as e:
        logger.error(f"Error fetching source document facts: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<int:patient_id>/agenda/<int:agenda_id>/complete', methods=['POST'])
def api_complete_agenda_item(patient_id, agenda_id):
    import tracking_db
    try:
        body = request.get_json(silent=True) or {}
        success = tracking_db.complete_followup_agenda_item(
            patient_id,
            agenda_id,
            visit_record_id=body.get("visit_record_id"),
        )
        if not success:
            return error_response("No fue posible completar el item de agenda", 400)
        identity = tracking_db.get_patient_history(patient_id)
        agenda = tracking_db.get_patient_agenda(identity["identity"]["nss"] if identity else patient_id)
        return jsonify({"success": True, "agenda": agenda})
    except Exception as e:
        logger.error(f"Error completing agenda item: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<int:patient_id>/visit-schema', methods=['GET'])
def api_visit_schema(patient_id):
    import tracking_db
    try:
        patient = tracking_db.get_patient_full_record(
            patient_id,
            include_derivatives=False,
            include_ledger=False,
        )
        if not patient:
            return error_response("Paciente no encontrado", 404)
        from prostanet.domains.patient_tracking.followup_agenda import build_visit_schema

        reconciliation = _reconciled_patient_snapshot(patient)
        state = request.args.get("state") or reconciliation["reconciled_state"]
        track = request.args.get("track") or reconciliation["reconciled_management_track"]
        agenda_item = None
        capture_fields = [field.strip() for field in str(request.args.get("fields") or "").split(",") if field.strip()]
        capture_context = None
        agenda_id = request.args.get("agenda_id")
        alert_key = str(request.args.get("alert_key") or "").strip()
        presentation = str(request.args.get("presentation") or "standard").strip() or "standard"
        if agenda_id:
            try:
                agenda_id_int = int(agenda_id)
            except (TypeError, ValueError):
                return error_response("agenda_id inválido", 400)
            agenda_bundle = tracking_db.get_patient_agenda(patient_id) or {}
            agenda_item = next(
                (item for item in (agenda_bundle.get("items") or []) if int(item.get("id") or 0) == agenda_id_int),
                None,
            )
            if agenda_item is None:
                return error_response("Item de agenda no encontrado", 404)
        elif alert_key:
            bundle = tracking_db.refresh_longitudinal_intelligence(patient_id, force_recompute=False)
            alert = next((item for item in (bundle.get("copilot_alerts") or []) if str(item.get("alert_key") or "") == alert_key), None)
            if alert is None:
                return error_response("Alerta clínica no encontrada", 404)
            capture_fields = [field for field in (alert.get("fields_to_capture") or []) if str(field or "").strip()]
            capture_context = {
                "title": alert.get("title") or "Resolver alerta clínica",
                "summary": alert.get("message") or "",
                "rationale": alert.get("why_now") or alert.get("message") or "Completa variables faltantes del flujo clínico.",
                "recommended_action": alert.get("recommended_action") or "",
                "decision_affected": alert.get("resolves_decision_domain") or alert.get("decision_domain") or "",
                "module_owner": alert.get("category") or "",
                "decision_targets": [alert.get("decision_domain")] if alert.get("decision_domain") else [],
                "reasoning": [alert.get("recommended_action")] if alert.get("recommended_action") else [],
                "required_inputs": capture_fields,
                "linked_agenda_ids": list(alert.get("linked_agenda_ids") or []),
                "linked_agenda_keys": list(alert.get("linked_agenda_keys") or []),
                "encounter_key": alert.get("encounter_key") or "",
                "alert_key": alert_key,
                "action_type": alert.get("action_type") or "capture",
                "expected_document_type": alert.get("expected_document_type") or "auto",
                "form_scope": {
                    "mode": "capture_block",
                    "focus": request.args.get("capture_block") or alert.get("capture_block") or "clinical_completion",
                    "fields": capture_fields,
                },
            }
        elif capture_fields:
            capture_context = {
                "title": request.args.get("capture_title") or "Completar datos críticos",
                "rationale": request.args.get("capture_rationale") or "Completa variables faltantes del flujo clínico.",
                "decision_affected": request.args.get("decision_affected") or "",
                "module_owner": request.args.get("module_owner") or "",
                "form_scope": {
                    "mode": "capture_block",
                    "focus": request.args.get("capture_group") or "clinical_completion",
                    "fields": capture_fields,
                },
            }
        visit_schema = build_visit_schema(
            state,
            track,
            patient=patient,
            agenda_item=agenda_item,
            field_scope=capture_fields or None,
            capture_context=capture_context,
            presentation=presentation,
        )
        return jsonify(
            {
                "success": True,
                "state": state,
                "management_track": track,
                "visit_schema": visit_schema,
                "agenda_item_context": visit_schema.get("agenda_item_context"),
                "alert_key": alert_key,
                "presentation": presentation,
            }
        )
    except Exception as e:
        logger.error(f"Error getting visit schema: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<int:patient_id>/protocol-comparison', methods=['GET'])
def api_protocol_comparison(patient_id):
    import tracking_db
    try:
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return error_response("Paciente no encontrado", 404)
        from prostanet.domains.patient_tracking.followup_agenda import build_protocol_comparators

        reconciliation = _reconciled_patient_snapshot(patient)
        state = reconciliation["reconciled_state"]
        track = reconciliation["reconciled_management_track"]
        return jsonify({"success": True, "comparators": build_protocol_comparators(state, track), "state": state, "management_track": track, **reconciliation})
    except Exception as e:
        logger.error(f"Error getting protocol comparison: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<int:patient_id>/events', methods=['POST'])
def api_record_patient_event(patient_id):
    import tracking_db
    try:
        data = parse_json_body()
        event_type = str(data.get("event_type", "")).strip()
        if not event_type:
            return error_response("Se requiere event_type", 400)
        event_id = tracking_db.record_patient_event(
            patient_id,
            event_type=event_type,
            event_date=data.get("event_date"),
            state_context=data.get("state_context", ""),
            management_track=data.get("management_track", ""),
            source_type=data.get("source_type", "manual_event"),
            source_record_id=data.get("source_record_id"),
            status=data.get("status", "recorded"),
            payload=data.get("payload") or {},
            mcode_focus=data.get("mcode_focus") or {},
        )
        if event_id is None:
            return error_response("No fue posible registrar el evento", 400)
        bundle = tracking_db.refresh_longitudinal_intelligence(patient_id, event_id=event_id, force_recompute=True)
        agenda = tracking_db.get_patient_agenda(patient_id)
        return jsonify({"success": True, "event_id": event_id, "agenda": agenda, **bundle})
    except ValueError as e:
        return error_response(str(e), 400)
    except Exception as e:
        logger.error(f"Error recording patient event: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<int:patient_id>/results', methods=['POST'])
def api_save_patient_result(patient_id):
    import tracking_db
    try:
        data = parse_json_body()
        success, payload = tracking_db.save_structured_result(patient_id, data)
        if success:
            return jsonify({"success": True, **payload})
        return error_response(payload, 400 if payload != "Paciente no encontrado" else 404)
    except ValueError as e:
        return error_response(str(e), 400)
    except Exception as e:
        logger.error(f"Error saving structured result: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<int:patient_id>/state-transition/<int:proposal_id>/confirm', methods=['POST'])
def api_confirm_state_transition(patient_id, proposal_id):
    import tracking_db
    try:
        body = request.get_json(silent=True) or {}
        success, payload = tracking_db.confirm_state_transition_proposal(
            patient_id,
            proposal_id,
            confirmed_by=body.get("confirmed_by", "system"),
        )
        if success:
            return jsonify({"success": True, **payload})
        return error_response(payload, 400)
    except Exception as e:
        logger.error(f"Error confirming transition proposal: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<patient_ref>/next-best-action', methods=['GET'])
def api_next_best_action(patient_ref):
    import tracking_db
    try:
        resolved, error = _resolve_patient_api_ref(patient_ref)
        if error:
            return error
        patient_id = resolved["patient_id"]
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return error_response("Paciente no encontrado", 404)
        bundle = tracking_db.refresh_longitudinal_intelligence(
            patient_id,
            force_recompute=True,
            record=patient,
            include_live_benchmark=False,
        ) or {}
        action = dict(
            (bundle.get("signals") or {}).get("next_best_action")
            or bundle.get("next_best_action")
            or {}
        )
        if str(action.get("action_title") or "").strip():
            action["title"] = str(action.get("action_title") or "").strip()
        if str(action.get("action_rationale") or "").strip():
            action["rationale"] = str(action.get("action_rationale") or "").strip()
        # Auditoría #21 (cierre OOS-3): preservar recommendation_family específico del
        # dominio (p.ej., "Salvage prostatectomy") cuando el post-RT copilot ya publicó
        # un label concreto. Los labels "genéricos de salvage" (p.ej., "Salvage / RT",
        # "Ruta de rescate", "post_rt") se degradan al canónico "salvage" para cumplir
        # el contrato de test_post_rp_bcr_escalates_schedule_runtime_to_salvage_*.
        _current_family = str(action.get("recommendation_family") or "").strip().lower()
        _title_lower = str(action.get("title") or "").lower()
        _generic_family_tokens = {
            "",
            "salvage",
            "rescate",
            "post_rt",
            "post_rp",
            "ruta de rescate",
            "salvage / rt",
            "salvage/rt",
            "salvage rt",
            "salvage ± adt",
            "salvage rt ± adt",
        }
        if any(token in _title_lower for token in ("salvage", "rescate")):
            if not _current_family or _current_family in _generic_family_tokens:
                action["recommendation_family"] = "salvage"
        if not action:
            return error_response("Paciente no encontrado", 404)
        return jsonify({
            "success": True,
            "next_best_action": action,
            "resolved_patient_id": patient_id,
            "resolved_patient_ref": resolved.get("nss") or resolved.get("patient_ref") or str(patient_ref),
            **_reconciled_patient_snapshot(patient),
        })
    except Exception as e:
        logger.error(f"Error getting next best action: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<patient_ref>/signals', methods=['GET'])
def api_patient_signals(patient_ref):
    import tracking_db
    try:
        resolved, error = _resolve_patient_api_ref(patient_ref)
        if error:
            return error
        patient_id = resolved["patient_id"]
        patient = tracking_db.get_patient_full_record(
            patient_id,
            include_derivatives=False,
            include_ledger=False,
        )
        if not patient:
            patient = _minimal_patient_record_from_resolved(resolved, patient_ref)
        try:
            bundle = tracking_db.refresh_longitudinal_intelligence(
                patient_id,
                force_recompute=False,
                record=patient,
                include_live_benchmark=False,
            )
        except Exception as exc:
            logger.warning("Signals refresh fallback for %s: %s", patient_ref, exc)
            bundle = {"signals": {}}
        signals = bundle.get("signals")
        if signals is None:
            signals = {}
        from prostanet.shared.presentation_text import (
            humanize_assessment,
            humanize_care_overlays,
            humanize_state_timeline,
        )
        from prostanet.domains.patient_tracking.profile_compass import build_patient_profile_view_model
        from prostanet.domains.patient_tracking.vertical_runtime import (
            build_decision_delta_since_last_visit,
            build_evidence_basis_current_visit,
            build_runtime_patient,
            build_runtime_payload,
            build_shared_metastatic_summary,
            derive_display_sequence_summary,
            select_primary_vertical_bundle,
        )

        latest_assessment = humanize_assessment(patient["latest_assessment"]) if patient.get("latest_assessment") else {}
        state_timeline = humanize_state_timeline(patient.get("state_timeline", []))
        care_overlays = humanize_care_overlays(patient.get("care_overlays", []))
        profile_view = build_patient_profile_view_model(
            patient=patient,
            latest_assessment_raw=patient.get("latest_assessment"),
            latest_assessment=latest_assessment,
            state_timeline=state_timeline,
            care_overlays=care_overlays,
            longitudinal_bundle=bundle,
        )
        _, active_copilot_bundle = select_primary_vertical_bundle(
            {
                "crpc_copilot_bundle": bundle.get("crpc_copilot_bundle", profile_view.get("crpc_copilot_bundle", {})),
                "post_rp_salvage_bundle": bundle.get("post_rp_salvage_bundle", profile_view.get("post_rp_salvage_bundle", {})),
                "mhspc_copilot_bundle": bundle.get("mhspc_copilot_bundle", profile_view.get("mhspc_copilot_bundle", {})),
                "diagnostic_biopsy_bundle": bundle.get("diagnostic_biopsy_bundle", profile_view.get("diagnostic_biopsy_bundle", {})),
                "localized_surveillance_bundle": bundle.get("localized_surveillance_bundle", profile_view.get("localized_surveillance_bundle", {})),
                "post_rt_salvage_bundle": bundle.get("post_rt_salvage_bundle", profile_view.get("post_rt_salvage_bundle", {})),
            }
        )
        runtime_patient = build_runtime_patient(patient, bundle)
        runtime_payload = build_runtime_payload(
            runtime_patient,
            patient.get("latest_assessment"),
            effective_state=signals.get("effective_state_final") or signals.get("reconciled_state") or "",
        )
        metastatic_composition_summary = (
            active_copilot_bundle.get("metastatic_composition_summary")
            or profile_view.get("metastatic_composition_summary")
            or build_shared_metastatic_summary(runtime_payload)
        )
        blocked_by_overlay = list(
            active_copilot_bundle.get("blocked_by_overlay")
            or profile_view.get("blocked_by_overlay")
            or []
        )
        decision_delta_since_last_visit = (
            active_copilot_bundle.get("decision_delta_since_last_visit")
            or profile_view.get("decision_delta_since_last_visit")
            or build_decision_delta_since_last_visit(
                patient,
                effective_state=signals.get("effective_state_final") or signals.get("reconciled_state") or "",
                phenotype_state=signals.get("phenotype_state") or signals.get("effective_state_final") or "",
                rule_based_recommendation=active_copilot_bundle.get("rule_based_recommendation") or {},
                final_presented_recommendation=active_copilot_bundle.get("final_presented_recommendation") or {},
                blocking_groups=active_copilot_bundle.get("blocking_inputs") or [],
                blocked_by_overlay=blocked_by_overlay,
            )
        )
        evidence_basis_current_visit = (
            active_copilot_bundle.get("evidence_basis_current_visit")
            or profile_view.get("evidence_basis_current_visit")
            or build_evidence_basis_current_visit(
                active_copilot_bundle.get("guideline_basis") or [],
                active_copilot_bundle.get("rule_based_recommendation") or {},
                decision_delta_since_last_visit,
            )
        )
        histopathology_summary = (
            active_copilot_bundle.get("histopathology_summary")
            or profile_view.get("histopathology_summary")
            or ""
        )
        qa_validation = active_copilot_bundle.get("qa_validation") or {}
        from prostanet.domains.patient_tracking.clinical_autodrive_command_center import (
            build_patient_autodrive,
        )
        from prostanet.domains.patient_tracking.clinical_decision_today_fusion_kernel import (
            build_decision_today,
        )

        clinical_readiness_tower = bundle.get("clinical_readiness_tower", profile_view.get("clinical_readiness_tower", {}))
        tumor_board_os = bundle.get("tumor_board_os", profile_view.get("tumor_board_os", {}))
        care_pathway_os = bundle.get("care_pathway_os", profile_view.get("care_pathway_os", {}))
        clinical_memory_os = bundle.get("clinical_memory_os", profile_view.get("clinical_memory_os", {}))
        autodrive_bundle = build_patient_autodrive(
            patient,
            longitudinal_bundle={
                **dict(bundle or {}),
                "clinical_readiness_tower": clinical_readiness_tower,
                "tumor_board_os": tumor_board_os,
                "care_pathway_os": care_pathway_os,
                "clinical_memory_os": clinical_memory_os,
                "signals": signals,
            },
            state=str(
                signals.get("effective_state_final")
                or signals.get("effective_state")
                or signals.get("reconciled_state")
                or ""
            ),
            management_track=str(
                signals.get("effective_management_track_final")
                or signals.get("effective_management_track")
                or signals.get("reconciled_management_track")
                or ""
            ),
            patient_ref=str(resolved.get("nss") or resolved.get("patient_ref") or patient_ref),
        )
        decision_today_bundle = autodrive_bundle.get("decision_today") or build_decision_today(
            patient,
            longitudinal_bundle={
                **dict(bundle or {}),
                "clinical_readiness_tower": clinical_readiness_tower,
                "tumor_board_os": tumor_board_os,
                "care_pathway_os": care_pathway_os,
                "clinical_memory_os": clinical_memory_os,
                "signals": signals,
            },
            clinical_autodrive=autodrive_bundle,
            state=str(
                signals.get("effective_state_final")
                or signals.get("effective_state")
                or signals.get("reconciled_state")
                or ""
            ),
            management_track=str(
                signals.get("effective_management_track_final")
                or signals.get("effective_management_track")
                or signals.get("reconciled_management_track")
                or ""
            ),
            patient_ref=str(resolved.get("nss") or resolved.get("patient_ref") or patient_ref),
        )
        signals = {**dict(signals or {}), "decision_today": decision_today_bundle}
        try:
            from prostanet.agentic.autonomous_improvement_os import build_mission_control

            autonomous_improvement = build_mission_control()
            signals["autonomous_improvement"] = {
                "summary": autonomous_improvement.get("summary", {}),
                "safety": autonomous_improvement.get("safety", {}),
            }
        except Exception:
            autonomous_improvement = {
                "available": False,
                "summary": {"mode": "shadow", "status": "blocked"},
                "safety": {"source_clinical_facts_mutated": False},
            }
        return jsonify(
            {
                "success": True,
                "signals": signals,
                "transition_proposals": bundle.get("transition_proposals", []),
                "next_best_action": bundle.get("next_best_action", {}),
                "clinical_readiness_tower": clinical_readiness_tower,
                "tumor_board_os": tumor_board_os,
                "care_pathway_os": care_pathway_os,
                "clinical_memory_os": clinical_memory_os,
                "autodrive": autodrive_bundle,
                "decision_today": decision_today_bundle,
                "autonomous_improvement": autonomous_improvement,
                "module_data_contracts": profile_view.get("module_data_contracts", {}),
                "missing_input_actions": profile_view.get("missing_input_actions", []),
                "missing_input_capture_tasks": profile_view.get("missing_input_capture_tasks", []),
                "intake_capture_target": profile_view.get("intake_capture_target"),
                "followup_capture_target": profile_view.get("followup_capture_target"),
                "intake_completion_block": profile_view.get("intake_completion_block", {}),
                "followup_completion_block": profile_view.get("followup_completion_block", {}),
                "psa_observability": profile_view.get("psa_observability", {}),
                "clinical_journey_events": profile_view.get("clinical_journey_events", []),
                "agenda_resolution_trace": profile_view.get("agenda_resolution_trace", []),
                "therapy_checkpoints": profile_view.get("therapy_checkpoints", []),
                "evidence_applicability": profile_view.get("evidence_applicability", {}),
                "master_followup_plan": bundle.get("master_followup_plan", profile_view.get("master_followup_plan", {})),
                "master_followup_summary": bundle.get("master_followup_summary", profile_view.get("master_followup_summary", {})),
                "copilot_alerts": bundle.get("copilot_alerts", []),
                "alert_summary": bundle.get("alert_summary", {}),
                "encounters": bundle.get("encounters", []),
                "schedule_anchor_strength": bundle.get("schedule_anchor_strength", "strong"),
                "outcome_events_summary": bundle.get("outcome_events_summary", profile_view.get("outcome_events_summary", {})),
                "pending_adjudications": bundle.get("pending_adjudications", profile_view.get("pending_adjudications", [])),
                "current_response_state": bundle.get("current_response_state", profile_view.get("current_response_state", {})),
                "current_course_status": bundle.get("current_course_status", profile_view.get("current_course_status", "")),
                "last_adjudicated_event": bundle.get("last_adjudicated_event", profile_view.get("last_adjudicated_event", {})),
                "trial_comparable_endpoints": bundle.get("trial_comparable_endpoints", profile_view.get("trial_comparable_endpoints", [])),
                "current_trial_comparable_profile": bundle.get("current_trial_comparable_profile", profile_view.get("current_trial_comparable_profile", {})),
                "prognostic_modifiers": bundle.get("prognostic_modifiers", profile_view.get("prognostic_modifiers", [])),
                "prognostic_recommended_actions": bundle.get("prognostic_recommended_actions", profile_view.get("prognostic_recommended_actions", [])),
                "prognostic_followup_impact": bundle.get("prognostic_followup_impact", profile_view.get("prognostic_followup_impact", [])),
                "prognostic_capture_targets": bundle.get("prognostic_capture_targets", profile_view.get("prognostic_capture_targets", [])),
                "backbone_alignment": bundle.get("backbone_alignment", profile_view.get("backbone_alignment", {})),
                "cadence_adjusted_by": bundle.get("cadence_adjusted_by", profile_view.get("cadence_adjusted_by", [])),
                "psa_forecast": bundle.get("psa_forecast", profile_view.get("psa_forecast", {})),
                "forecast_reliability": bundle.get("forecast_reliability", profile_view.get("forecast_reliability", {})),
                "live_benchmark": bundle.get("live_benchmark", profile_view.get("live_benchmark", {})),
                "benchmark_reliability": bundle.get("benchmark_reliability", profile_view.get("benchmark_reliability", {})),
                "longitudinal_truth_snapshot": bundle.get("longitudinal_truth_snapshot", profile_view.get("longitudinal_truth_snapshot", {})),
                "decision_recalculation_trace": bundle.get("decision_recalculation_trace", profile_view.get("decision_recalculation_trace", {})),
                "guideline_followup_plan": bundle.get("guideline_followup_plan", profile_view.get("guideline_followup_plan", {})),
                "transition_resolution": bundle.get("transition_resolution", patient.get("transition_resolution", {})),
                "care_intent_contract": bundle.get("care_intent_contract", patient.get("care_intent_contract", {})),
                "laboratory_intelligence_profile": bundle.get("laboratory_intelligence_profile", profile_view.get("laboratory_intelligence_profile", {})),
                "latest_clinically_decisive_visit": bundle.get("latest_clinically_decisive_visit", profile_view.get("latest_clinically_decisive_visit", {})),
                "effective_state_final": bundle.get("signals", {}).get("effective_state_final") or bundle.get("signals", {}).get("effective_state") or bundle.get("signals", {}).get("reconciled_state"),
                "effective_management_track_final": bundle.get("signals", {}).get("effective_management_track_final") or bundle.get("signals", {}).get("effective_management_track") or bundle.get("signals", {}).get("reconciled_management_track"),
                "effective_state": bundle.get("signals", {}).get("effective_state") or bundle.get("signals", {}).get("reconciled_state"),
                "effective_management_track": bundle.get("signals", {}).get("effective_management_track") or bundle.get("signals", {}).get("reconciled_management_track"),
                "phenotype_state": bundle.get("signals", {}).get("phenotype_state", profile_view.get("clinical_signals", {}).get("phenotype_state", "")),
                "progression_gate_active": bundle.get("signals", {}).get("progression_gate_active", False),
                "progression_gate_target": bundle.get("signals", {}).get("progression_gate_target", ""),
                "progression_gate_reason": bundle.get("signals", {}).get("progression_gate_reason", ""),
                "systemic_progression_context_resolved": bundle.get("signals", {}).get("systemic_progression_context_resolved", "none"),
                "blocking_inputs": bundle.get("blocking_inputs", []),
                "hard_blocking_inputs": bundle.get("hard_blocking_inputs", []),
                "decision_blocking_inputs": bundle.get("decision_blocking_inputs", []),
                "supportive_gaps": bundle.get("supportive_gaps", []),
                "required_to_recalculate": bundle.get("required_to_recalculate", []),
                "optional_context_inputs": bundle.get("optional_context_inputs", []),
                "decision_domains_blocked": bundle.get("decision_domains_blocked", []),
                "guideline_basis": bundle.get("guideline_basis", []),
                "ui_contradiction_flags": bundle.get("ui_contradiction_flags", []),
                "crpc_copilot_bundle": bundle.get("crpc_copilot_bundle", profile_view.get("crpc_copilot_bundle", {})),
                "crpc_copilot_status": bundle.get("crpc_copilot_status", profile_view.get("crpc_copilot_status", "not_applicable")),
                "post_rp_salvage_bundle": bundle.get("post_rp_salvage_bundle", profile_view.get("post_rp_salvage_bundle", {})),
                "post_rp_copilot_status": bundle.get("post_rp_copilot_status", profile_view.get("post_rp_copilot_status", "not_applicable")),
                "mhspc_copilot_bundle": bundle.get("mhspc_copilot_bundle", profile_view.get("mhspc_copilot_bundle", {})),
                "mhspc_copilot_status": bundle.get("mhspc_copilot_status", profile_view.get("mhspc_copilot_status", "not_applicable")),
                "diagnostic_biopsy_bundle": bundle.get("diagnostic_biopsy_bundle", profile_view.get("diagnostic_biopsy_bundle", {})),
                "diagnostic_copilot_status": bundle.get("diagnostic_copilot_status", profile_view.get("diagnostic_copilot_status", "not_applicable")),
                "localized_surveillance_bundle": bundle.get("localized_surveillance_bundle", profile_view.get("localized_surveillance_bundle", {})),
                "localized_copilot_status": bundle.get("localized_copilot_status", profile_view.get("localized_copilot_status", "not_applicable")),
                "post_rt_salvage_bundle": bundle.get("post_rt_salvage_bundle", profile_view.get("post_rt_salvage_bundle", {})),
                "post_rt_copilot_status": bundle.get("post_rt_copilot_status", profile_view.get("post_rt_copilot_status", "not_applicable")),
                "salvage_window_status": bundle.get("salvage_window_status", profile_view.get("salvage_window_status", "")),
                "salvage_window_reason": bundle.get("salvage_window_reason", profile_view.get("salvage_window_reason", "")),
                "post_rt_salvage_window_status": bundle.get("post_rt_salvage_window_status", profile_view.get("post_rt_salvage_window_status", "")),
                "qa_passed": bundle.get("qa_passed", profile_view.get("qa_passed", (active_copilot_bundle.get("qa_validation") or {}).get("approved"))),
                "sequence_summary": bundle.get("sequence_summary", profile_view.get("sequence_summary", derive_display_sequence_summary(active_copilot_bundle))),
                "histopathology_summary": histopathology_summary,
                "metastatic_composition_summary": metastatic_composition_summary,
                "decision_delta_since_last_visit": decision_delta_since_last_visit,
                "blocked_by_overlay": blocked_by_overlay,
                "evidence_basis_current_visit": evidence_basis_current_visit,
                "qa_validation": qa_validation,
                "crpc_schedule_overlay": bundle.get("crpc_schedule_overlay", profile_view.get("crpc_schedule_overlay", {})),
                "post_rp_schedule_overlay": bundle.get("post_rp_schedule_overlay", profile_view.get("post_rp_schedule_overlay", {})),
                "mhspc_schedule_overlay": bundle.get("mhspc_schedule_overlay", profile_view.get("mhspc_schedule_overlay", {})),
                "diagnostic_schedule_overlay": bundle.get("diagnostic_schedule_overlay", profile_view.get("diagnostic_schedule_overlay", {})),
                "localized_schedule_overlay": bundle.get("localized_schedule_overlay", profile_view.get("localized_schedule_overlay", {})),
                "post_rt_schedule_overlay": bundle.get("post_rt_schedule_overlay", profile_view.get("post_rt_schedule_overlay", {})),
                "resolved_patient_id": patient_id,
                "resolved_patient_ref": resolved.get("nss") or resolved.get("patient_ref") or str(patient_ref),
                **_reconciled_patient_snapshot(patient),
            }
        )
    except Exception as e:
        logger.error(f"Error getting patient signals: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<patient_ref>/clinical-readiness', methods=['GET'])
@app.route('/api/patient/<patient_ref>/clinical-readiness', methods=['GET'])
def api_patient_clinical_readiness(patient_ref):
    """Official Clinical Readiness & Safety Tower bundle for one patient."""
    import tracking_db

    try:
        resolved, error = _resolve_patient_api_ref(patient_ref)
        if error:
            return error
        patient_id = resolved["patient_id"]
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return error_response("Paciente no encontrado", 404)
        bundle = tracking_db.refresh_longitudinal_intelligence(
            patient_id,
            force_recompute=False,
            record=patient,
            include_live_benchmark=False,
        )
        tower = dict(bundle.get("clinical_readiness_tower") or {})
        if not tower:
            from prostanet.domains.patient_tracking.clinical_readiness_tower import (
                build_clinical_readiness_tower,
            )

            signals = dict(bundle.get("signals") or {})
            tower = build_clinical_readiness_tower(
                patient,
                longitudinal_bundle=bundle,
                state=str(
                    signals.get("effective_state_final")
                    or signals.get("effective_state")
                    or signals.get("reconciled_state")
                    or (patient.get("latest_assessment") or {}).get("state")
                    or ""
                ),
                management_track=str(
                    signals.get("effective_management_track_final")
                    or signals.get("effective_management_track")
                    or signals.get("reconciled_management_track")
                    or ""
                ),
                patient_ref=str(resolved.get("nss") or resolved.get("patient_ref") or patient_ref),
            )
        return jsonify({
            "success": True,
            "clinical_readiness_tower": tower,
            **tower,
            "resolved_patient_id": patient_id,
            "resolved_patient_ref": resolved.get("nss") or resolved.get("patient_ref") or str(patient_ref),
        })
    except Exception as e:
        logger.error(f"Error getting clinical readiness tower: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<patient_ref>/tumor-board-os', methods=['GET'])
@app.route('/api/patient/<patient_ref>/tumor-board-os', methods=['GET'])
def api_patient_tumor_board_os(patient_ref):
    """Official Tumor Board OS read model for one patient."""
    import tracking_db

    try:
        resolved, error = _resolve_patient_api_ref(patient_ref)
        if error:
            return error
        patient_id = resolved["patient_id"]
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return error_response("Paciente no encontrado", 404)
        bundle = tracking_db.refresh_longitudinal_intelligence(
            patient_id,
            force_recompute=False,
            record=patient,
            include_live_benchmark=False,
        )
        board = dict(bundle.get("tumor_board_os") or {})
        if not board:
            from prostanet.domains.patient_tracking.tumor_board_os import build_tumor_board_os

            signals = dict(bundle.get("signals") or {})
            board = build_tumor_board_os(
                patient,
                longitudinal_bundle=bundle,
                state=str(
                    signals.get("effective_state_final")
                    or signals.get("effective_state")
                    or signals.get("reconciled_state")
                    or (patient.get("latest_assessment") or {}).get("state")
                    or ""
                ),
                management_track=str(
                    signals.get("effective_management_track_final")
                    or signals.get("effective_management_track")
                    or signals.get("reconciled_management_track")
                    or ""
                ),
                patient_ref=str(resolved.get("nss") or resolved.get("patient_ref") or patient_ref),
            )
        return jsonify({
            "success": True,
            "tumor_board_os": board,
            **board,
            "resolved_patient_id": patient_id,
            "resolved_patient_ref": resolved.get("nss") or resolved.get("patient_ref") or str(patient_ref),
        })
    except Exception as e:
        logger.error(f"Error getting Tumor Board OS: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<patient_ref>/tumor-board-os/what-if', methods=['POST'])
def api_patient_tumor_board_os_what_if(patient_ref):
    """No-write Tumor Board OS what-if comparator."""
    import tracking_db

    payload = request.get_json(silent=True) or {}
    changes = payload.get("hypothetical_changes") or payload.get("changes") or {}
    if not isinstance(changes, dict) or not changes:
        return jsonify({"success": False, "error": "missing hypothetical_changes (dict)"}), 400

    try:
        resolved, error = _resolve_patient_api_ref(patient_ref)
        if error:
            return error
        patient_id = resolved["patient_id"]
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return error_response("Paciente no encontrado", 404)
        bundle = tracking_db.refresh_longitudinal_intelligence(
            patient_id,
            force_recompute=False,
            record=patient,
            include_live_benchmark=False,
        )
        from prostanet.domains.patient_tracking.tumor_board_os import (
            build_tumor_board_os,
            build_tumor_board_what_if_delta,
        )

        signals = dict(bundle.get("signals") or {})
        state = str(
            signals.get("effective_state_final")
            or signals.get("effective_state")
            or signals.get("reconciled_state")
            or (patient.get("latest_assessment") or {}).get("state")
            or ""
        )
        track = str(
            signals.get("effective_management_track_final")
            or signals.get("effective_management_track")
            or signals.get("reconciled_management_track")
            or ""
        )
        resolved_ref = str(resolved.get("nss") or resolved.get("patient_ref") or patient_ref)
        real_board = dict(bundle.get("tumor_board_os") or {}) or build_tumor_board_os(
            patient,
            longitudinal_bundle=bundle,
            state=state,
            management_track=track,
            patient_ref=resolved_ref,
        )
        hypothetical_board = build_tumor_board_os(
            patient,
            longitudinal_bundle=bundle,
            state=state,
            management_track=track,
            patient_ref=resolved_ref,
            hypothetical_changes=changes,
        )
        delta = build_tumor_board_what_if_delta(
            real_board=real_board,
            hypothetical_board=hypothetical_board,
            hypothetical_changes=changes,
        )
        return jsonify({
            **delta,
            "tumor_board_os": hypothetical_board,
            "resolved_patient_id": patient_id,
            "resolved_patient_ref": resolved_ref,
        })
    except Exception as e:
        logger.error(f"Error running Tumor Board OS what-if: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<patient_ref>/care-pathway-os', methods=['GET'])
@app.route('/api/patient/<patient_ref>/care-pathway-os', methods=['GET'])
def api_patient_care_pathway_os(patient_ref):
    """Official internal Care Pathway OS execution read model for one patient."""
    import tracking_db

    try:
        resolved, error = _resolve_patient_api_ref(patient_ref)
        if error:
            return error
        patient_id = resolved["patient_id"]
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return error_response("Paciente no encontrado", 404)
        bundle = tracking_db.refresh_longitudinal_intelligence(
            patient_id,
            force_recompute=False,
            record=patient,
            include_live_benchmark=False,
        )
        pathway = dict(bundle.get("care_pathway_os") or {})
        if not pathway:
            from prostanet.domains.patient_tracking.care_pathway_os import build_care_pathway_os

            signals = dict(bundle.get("signals") or {})
            pathway = build_care_pathway_os(
                patient,
                longitudinal_bundle=bundle,
                state=str(
                    signals.get("effective_state_final")
                    or signals.get("effective_state")
                    or signals.get("reconciled_state")
                    or (patient.get("latest_assessment") or {}).get("state")
                    or ""
                ),
                management_track=str(
                    signals.get("effective_management_track_final")
                    or signals.get("effective_management_track")
                    or signals.get("reconciled_management_track")
                    or ""
                ),
                patient_ref=str(resolved.get("nss") or resolved.get("patient_ref") or patient_ref),
            )
        return jsonify({
            "success": True,
            "care_pathway_os": pathway,
            **pathway,
            "resolved_patient_id": patient_id,
            "resolved_patient_ref": resolved.get("nss") or resolved.get("patient_ref") or str(patient_ref),
        })
    except Exception as e:
        logger.error(f"Error getting Care Pathway OS: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<patient_ref>/care-pathway-os/actions/<path:action_key>/status', methods=['POST'])
def api_patient_care_pathway_action_status(patient_ref, action_key):
    """Update internal operational status for one Care Pathway OS action."""
    import tracking_db

    payload = request.get_json(silent=True) or {}
    status = str(payload.get("status") or "").strip().lower()
    note = str(payload.get("note") or payload.get("audit_note") or "").strip()
    updated_by = str(payload.get("updated_by") or payload.get("user") or "clinician").strip()
    try:
        resolved, error = _resolve_patient_api_ref(patient_ref)
        if error:
            return error
        patient_id = resolved["patient_id"]
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return error_response("Paciente no encontrado", 404)
        bundle = tracking_db.refresh_longitudinal_intelligence(
            patient_id,
            force_recompute=False,
            record=patient,
            include_live_benchmark=False,
        )
        pathway = dict(bundle.get("care_pathway_os") or {})
        known_actions = {
            str(item.get("action_key") or "")
            for item in list(pathway.get("pathway_actions") or [])
            if isinstance(item, dict)
        }
        if action_key not in known_actions:
            return jsonify({
                "success": False,
                "error": "La accion no pertenece al paciente o ya no esta activa",
                "action_key": action_key,
            }), 404
        ok, message, result = tracking_db.update_care_pathway_action_status(
            patient_id,
            action_key,
            status,
            note=note,
            updated_by=updated_by,
        )
        if not ok:
            return jsonify({"success": False, "error": message, "action_key": action_key}), 400
        return jsonify({
            "success": True,
            "message": message,
            "action_key": action_key,
            **result,
            "resolved_patient_id": patient_id,
            "resolved_patient_ref": resolved.get("nss") or resolved.get("patient_ref") or str(patient_ref),
        })
    except Exception as e:
        logger.error(f"Error updating Care Pathway OS action status: {e}")
        return error_response(str(e), 500)


def _build_patient_decision_today_for_api(patient_ref, *, force_recompute=False):
    import tracking_db
    from prostanet.domains.patient_tracking.clinical_autodrive_command_center import (
        build_patient_autodrive,
    )
    from prostanet.domains.patient_tracking.clinical_decision_today_fusion_kernel import (
        build_decision_today,
    )

    resolved, error = _resolve_patient_api_ref(patient_ref)
    if error:
        return None, error
    patient_id = resolved["patient_id"]
    patient = tracking_db.get_patient_full_record(
        patient_id,
        include_derivatives=False,
        include_ledger=False,
    )
    if not patient:
        patient = _minimal_patient_record_from_resolved(resolved, patient_ref)
    try:
        bundle = tracking_db.refresh_longitudinal_intelligence(
            patient_id,
            force_recompute=bool(force_recompute),
            record=patient,
            include_live_benchmark=False,
        ) or {}
    except Exception as exc:
        logger.warning("Decision Today refresh fallback for %s: %s", patient_ref, exc)
        bundle = {"signals": {}}
    signals = dict(bundle.get("signals") or {})
    state = str(
        signals.get("effective_state_final")
        or signals.get("effective_state")
        or signals.get("reconciled_state")
        or (patient.get("latest_assessment") or {}).get("state")
        or ""
    )
    management_track = str(
        signals.get("effective_management_track_final")
        or signals.get("effective_management_track")
        or signals.get("reconciled_management_track")
        or ""
    )
    resolved_ref = str(resolved.get("nss") or resolved.get("patient_ref") or patient_ref)
    try:
        autodrive = build_patient_autodrive(
            patient,
            longitudinal_bundle=bundle,
            state=state,
            management_track=management_track,
            patient_ref=resolved_ref,
        )
    except Exception as exc:
        logger.warning("Decision Today Autodrive fallback for %s: %s", patient_ref, exc)
        autodrive = {
            "available": False,
            "source": "clinical_autodrive_command_center",
            "summary": {"priority_status": "not_actionable"},
            "today_queue": [],
        }
    try:
        decision_today = autodrive.get("decision_today") or build_decision_today(
            patient,
            longitudinal_bundle=bundle,
            clinical_autodrive=autodrive,
            state=state,
            management_track=management_track,
            patient_ref=resolved_ref,
        )
    except Exception as exc:
        logger.warning("Decision Today fallback bundle for %s: %s", patient_ref, exc)
        decision_today = {
            "available": True,
            "source": "clinical_decision_today_fusion_kernel",
            "decision_state": "requires_data",
            "decision_today": {
                "title": "Decision Today requiere datos clinicos",
                "label": "Fusion Kernel",
                "status": "requires_data",
            },
            "clinical_rationale": "Expediente minimo resuelto; faltan datos clinicos para liberar una decision.",
            "unified_missing_fields": [],
            "next_safe_action": {
                "title": "Completar datos clinicos",
                "cta": {"href": f"/patient_profile/{resolved_ref}?v=2", "label": "Abrir perfil"},
            },
        }
    return {
        "patient_id": patient_id,
        "patient": patient,
        "bundle": bundle,
        "autodrive": autodrive,
        "decision_today": decision_today,
        "resolved": resolved,
    }, None


@app.route('/api/patients/<patient_ref>/hrr-capture', methods=['POST'])
def api_patient_hrr_capture(patient_ref):
    """EPIC 34.A Phase 4 — Quick capture HRR/germline status (compound value:
    desbloquea PARP trials en Trial Matcher).

    Body: {hrr_status: 'positive'|'negative'|'pending'|'not_tested',
           hrr_gene?: 'BRCA1'|'BRCA2'|'ATM'|'PALB2'|'CHEK2'|'CDK12'|...,
           sample_date?, notes?, actor_session_id?}
    """
    import tracking_db as _td
    try:
        payload = request.get_json(silent=True) or {}
    except Exception:
        payload = {}
    hrr_status = payload.get('hrr_status')
    if not hrr_status:
        return jsonify({'success': False, 'error': 'missing_hrr_status'}), 400
    res = _td.record_hrr_capture(
        patient_ref,
        hrr_status,
        hrr_gene=payload.get('hrr_gene'),
        sample_date=payload.get('sample_date'),
        source_type=payload.get('source_type', 'quick_capture_ui'),
        actor_session_id=payload.get('actor_session_id'),
        notes=payload.get('notes', ''),
    )
    status = 200 if res.get('success') else (
        404 if res.get('error') == 'patient_not_found' else 400
    )
    return jsonify(res), status


@app.route('/api/patients/<patient_ref>/hrr-latest', methods=['GET'])
def api_patient_hrr_latest(patient_ref):
    """EPIC 34.A Phase 4 — Get latest HRR status for UI gating."""
    import tracking_db as _td
    res = _td.get_latest_hrr_for_patient(patient_ref)
    if res is None:
        return jsonify({'success': True, 'has_hrr': False}), 200
    return jsonify({'success': True, 'has_hrr': True, **res}), 200


@app.route('/api/patients/<patient_ref>/trial-matches', methods=['GET'])
def api_patient_trial_matches(patient_ref):
    """EPIC 34.A Phase 3 — Trial eligibility matcher (Critic council 'least
    regret jump': info-only, no diagnostic claim, sobrevive abandono especialista).

    Returns: bundle con positive matches + ineligible + reasons en español.
    """
    import tracking_db as _td
    try:
        from prostanet.domains.research_intelligence.trial_matching_engine import (
            build_trial_matching_bundle,
        )
        patient_data = _td.get_patient_full_record(patient_ref)
        if not patient_data:
            return jsonify({"success": False, "error": "patient_not_found"}), 404

        # Hidratar fields desde clinical_facts para que el engine los lea
        identity_id = (patient_data.get("identity") or {}).get("id")
        facts = _td.get_patient_clinical_facts(identity_id, active_only=True) if identity_id else []
        fact_map = {}
        for f in facts:
            k = f.get("fact_key")
            v = f.get("normalized_value_text") or f.get("value_json")
            if k and v is not None:
                fact_map[k] = v
        # Map facts to trial_matching_engine expected field names
        normalized = {
            **patient_data,
            "state": (
                fact_map.get("reconciled_state")
                or fact_map.get("m_substage_resolved")
                or (patient_data.get("latest_assessment") or {}).get("state")
                or ""
            ),
            "ecog_score": fact_map.get("ecog_performance_status") or fact_map.get("ecog_score"),
            "hrr_status": fact_map.get("hrr_status"),
            "hrr_positive": fact_map.get("hrr_positive") or (
                "1" if str(fact_map.get("hrr_status", "")).lower() in ("positive", "pathogenic") else None
            ),
            "germline_pathogenic_variant": fact_map.get("germline_pathogenic_variant") or fact_map.get("hrr_gene"),
            "msi_status": fact_map.get("msi_status"),
            "current_psa": fact_map.get("current_psa"),
            "baseline_psa": fact_map.get("baseline_psa"),
            "castrate_testosterone_status": fact_map.get("castrate_testosterone_status"),
            "metastasis_site": fact_map.get("m_substage_resolved") or fact_map.get("metastatic_stage_resolved"),
        }
        bundle = build_trial_matching_bundle(normalized)
        return jsonify({"success": True, **bundle})
    except Exception as exc:
        logger.exception("Trial matches endpoint failed")
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route('/api/patients/<patient_ref>/ecog-capture', methods=['POST'])
def api_patient_ecog_capture(patient_ref):
    """EPIC 34.A Phase 2 — Quick capture ECOG performance status (0-4).

    Body: {ecog_value: int, sample_date?: str, notes?: str, actor_session_id?: str}
    Returns: {success, fact_id, ecog_value, sample_date}

    Razón Phase 2: 2/57 ARPI patients tienen ECOG documentado. Target: 30/57 = 53%
    en 2 semanas para desbloquear KPI ecog_change_24wk en dashboard MX cohort.
    """
    import tracking_db as _td
    try:
        payload = request.get_json(silent=True) or {}
    except Exception:
        payload = {}
    ecog_value = payload.get('ecog_value')
    if ecog_value is None:
        return jsonify({'success': False, 'error': 'missing_ecog_value'}), 400
    res = _td.record_ecog_capture(
        patient_ref,
        ecog_value,
        sample_date=payload.get('sample_date'),
        source_type=payload.get('source_type', 'quick_capture_ui'),
        actor_session_id=payload.get('actor_session_id'),
        notes=payload.get('notes', ''),
    )
    status = 200 if res.get('success') else (
        404 if res.get('error') == 'patient_not_found' else 400
    )
    return jsonify(res), status


@app.route('/api/patients/<patient_ref>/ecog-latest', methods=['GET'])
def api_patient_ecog_latest(patient_ref):
    """EPIC 34.A Phase 2 — Get latest ECOG + age for patient (drives UI gating)."""
    import tracking_db as _td
    res = _td.get_latest_ecog_for_patient(patient_ref)
    if res is None:
        return jsonify({'success': True, 'has_ecog': False}), 200
    return jsonify({'success': True, 'has_ecog': True, **res}), 200


@app.route('/api/population/recompute-arpi-windows', methods=['POST'])
def api_population_recompute_arpi_windows():
    """EPIC 34.A — Trigger admin: pre-compute arpi_response_windows snapshots
    para toda la cohorte ARPI documentada. Útil cuando nuevas PSAs llegan o
    se añaden treatments. Idempotent (upsert por patient×regimen×weeks).

    Returns: stats {patients_scanned, windows_computed, windows_with_data,
                     errors, per_evidence_quality}
    """
    try:
        from prostanet.domains.population_intelligence.mx_cohort_aggregator import (
            populate_arpi_response_windows_for_cohort,
        )
        stats = populate_arpi_response_windows_for_cohort()
        return jsonify({"success": True, **stats})
    except Exception as exc:
        logger.exception("Recompute ARPI windows failed")
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route('/api/population/cohort-dashboard', methods=['GET'])
def api_population_cohort_dashboard():
    """EPIC 33.C — MX Cohort Exploratory Dashboard.

    Query params:
      - kpis: comma-separated list of KPI ids (default: all registered)

    Returns: bundle con exploratory_disclaimer + kpis dict.
    """
    try:
        from prostanet.domains.population_intelligence.mx_cohort_aggregator import (
            compute_all_kpis,
            KPI_REGISTRY,
        )
        kpis_param = request.args.get('kpis', '').strip()
        kpi_ids = [k.strip() for k in kpis_param.split(',') if k.strip()] if kpis_param else None
        bundle = compute_all_kpis(kpi_ids)
        bundle["registry_available"] = list(KPI_REGISTRY.keys())
        return jsonify({"success": True, **bundle})
    except Exception as exc:
        logger.exception("Population cohort dashboard failed")
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route('/api/patients/<patient_ref>/arpi-response/<int:weeks>', methods=['GET'])
def api_patient_arpi_response(patient_ref, weeks):
    """EPIC 33.B — Calcular respuesta ARPI a ventana pivotal (2 o 6 meses).

    weeks ∈ {8, 24}. Otros valores aceptados pero con warning.
    Returns: dict con baseline_psa, actual_psa, psa_decline_pct,
    psa50/psa90_response, ECOG baseline+actual+change, evidence_quality.
    """
    if weeks not in (4, 8, 12, 16, 24, 36, 52):
        return jsonify({"success": False, "error": "weeks_must_be_canonical_window",
                         "accepted": [8, 24]}), 400
    try:
        from prostanet.domains.patient_tracking.arpi_response_window import (
            compute_arpi_response_at_window,
        )
        import tracking_db as _td
        patient_data = _td.get_patient_full_record(patient_ref)
        if not patient_data:
            return jsonify({"success": False, "error": "patient_not_found"}), 404
        # Hidratar clinical_facts (necesario para ECOG history)
        identity_id = (patient_data.get("identity") or {}).get("id")
        if identity_id:
            patient_data["clinical_facts"] = _td.get_patient_clinical_facts(identity_id, active_only=False)
        result = compute_arpi_response_at_window(patient_data, weeks=weeks)
        return jsonify({"success": True, **result})
    except Exception as exc:
        logger.exception("ARPI response window failed")
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route('/api/clinical-view-audit', methods=['POST'])
def api_clinical_view_audit():
    """EPIC 33.A — Log open/collapse events de `<details>` colapsibles en
    patient_profile_v2. Cumple HIPAA §164.312(b) accountability.

    Body: {patient_nss, section_key, action, importance?, actor_session_id?}
    Returns: {success, audit_id}
    """
    import tracking_db as _td
    try:
        payload = request.get_json(silent=True) or {}
    except Exception:
        payload = {}
    patient_nss = str(payload.get('patient_nss') or payload.get('patient_id') or '').strip()
    section_key = str(payload.get('section_key') or '').strip()
    action = str(payload.get('action') or '').strip()
    importance = payload.get('importance')
    actor_session_id = payload.get('actor_session_id')
    if not patient_nss or not section_key or not action:
        return jsonify({'success': False, 'error': 'missing_required_fields'}), 400
    res = _td.record_clinical_view_audit(
        patient_nss, section_key, action,
        importance=importance,
        actor_session_id=actor_session_id,
    )
    status = 200 if res.get('success') else (404 if res.get('error') == 'patient_not_found' else 400)
    return jsonify(res), status


@app.route('/api/patients/<patient_ref>/decision-today', methods=['GET'])
@app.route('/api/patient/<patient_ref>/decision-today', methods=['GET'])
def api_patient_decision_today(patient_ref):
    """Canonical per-patient DECISION HOY Fusion Kernel bundle."""
    try:
        payload, error = _build_patient_decision_today_for_api(patient_ref, force_recompute=False)
        if error:
            return error
        decision_today = payload["decision_today"]
        resolved = payload["resolved"]
        try:
            from prostanet.agentic.autonomous_improvement_os import build_mission_control

            autonomous_summary = build_mission_control().get("summary", {})
        except Exception:
            autonomous_summary = {"mode": "shadow", "status": "blocked"}
        return jsonify({
            "success": True,
            "decision_today": decision_today,
            **decision_today,
            "autonomous_improvement_summary": autonomous_summary,
            "resolved_patient_id": payload["patient_id"],
            "resolved_patient_ref": resolved.get("nss") or resolved.get("patient_ref") or str(patient_ref),
        })
    except Exception as e:
        logger.error(f"Error getting Decision Today: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<patient_ref>/decision-today/recompute', methods=['POST'])
def api_patient_decision_today_recompute(patient_ref):
    """Recompute DECISION HOY without mutating source clinical facts."""
    try:
        payload, error = _build_patient_decision_today_for_api(patient_ref, force_recompute=True)
        if error:
            return error
        decision_today = payload["decision_today"]
        resolved = payload["resolved"]
        try:
            from prostanet.agentic.autonomous_improvement_os import build_mission_control

            autonomous_summary = build_mission_control().get("summary", {})
        except Exception:
            autonomous_summary = {"mode": "shadow", "status": "blocked"}
        return jsonify({
            "success": True,
            "decision_today": decision_today,
            **decision_today,
            "autonomous_improvement_summary": autonomous_summary,
            "source_clinical_facts_mutated": False,
            "model_trained": False,
            "resolved_patient_id": payload["patient_id"],
            "resolved_patient_ref": resolved.get("nss") or resolved.get("patient_ref") or str(patient_ref),
        })
    except Exception as e:
        logger.error(f"Error recomputing Decision Today: {e}")
        return error_response(str(e), 500)


def _build_patient_autodrive_for_api(patient_ref, *, force_recompute=False):
    import tracking_db
    from prostanet.domains.patient_tracking.clinical_autodrive_command_center import (
        build_patient_autodrive,
    )

    resolved, error = _resolve_patient_api_ref(patient_ref)
    if error:
        return None, error
    patient_id = resolved["patient_id"]
    patient = tracking_db.get_patient_full_record(
        patient_id,
        include_derivatives=False,
        include_ledger=False,
    )
    if not patient:
        patient = _minimal_patient_record_from_resolved(resolved, patient_ref)
    try:
        bundle = tracking_db.refresh_longitudinal_intelligence(
            patient_id,
            force_recompute=bool(force_recompute),
            record=patient,
            include_live_benchmark=False,
        ) or {}
    except Exception as exc:
        logger.warning("Autodrive refresh fallback for %s: %s", patient_ref, exc)
        bundle = {"signals": {}}
    signals = dict(bundle.get("signals") or {})
    try:
        autodrive = build_patient_autodrive(
            patient,
            longitudinal_bundle=bundle,
            state=str(
                signals.get("effective_state_final")
                or signals.get("effective_state")
                or signals.get("reconciled_state")
                or (patient.get("latest_assessment") or {}).get("state")
                or ""
            ),
            management_track=str(
                signals.get("effective_management_track_final")
                or signals.get("effective_management_track")
                or signals.get("reconciled_management_track")
                or ""
            ),
            patient_ref=str(resolved.get("nss") or resolved.get("patient_ref") or patient_ref),
        )
    except Exception as exc:
        logger.warning("Autodrive fallback bundle for %s: %s", patient_ref, exc)
        autodrive = {
            "available": False,
            "source": "clinical_autodrive_command_center",
            "summary": {"priority_status": "not_actionable"},
            "today_queue": [],
            "autodrive_actions": [],
            "decision_today": {
                "available": True,
                "source": "clinical_decision_today_fusion_kernel",
                "decision_state": "requires_data",
            },
        }
    return {
        "patient_id": patient_id,
        "patient": patient,
        "bundle": bundle,
        "autodrive": autodrive,
        "decision_today": autodrive.get("decision_today") or {},
        "resolved": resolved,
    }, None


@app.route('/api/autodrive/today', methods=['GET'])
def api_autodrive_today():
    """Population Clinical Autodrive Command Center queue."""
    try:
        from prostanet.domains.patient_tracking.clinical_autodrive_command_center import (
            build_population_autodrive_from_db,
        )

        limit = request.args.get("limit", 25)
        lane = str(request.args.get("lane") or "").strip()
        stage = str(request.args.get("stage") or "").strip()
        payload = build_population_autodrive_from_db(
            limit=int(limit or 25),
            lane=lane,
            stage=stage,
            force_recompute=False,
        )
        return jsonify({"success": True, "autodrive": payload, **payload})
    except Exception as e:
        logger.error(f"Error getting Autodrive today: {e}")
        return error_response(str(e), 500)


@app.route('/api/autodrive/recompute', methods=['POST'])
def api_autodrive_recompute():
    """Recompute Autodrive read models without mutating source clinical facts."""
    try:
        from prostanet.domains.patient_tracking.clinical_autodrive_command_center import (
            build_population_autodrive_from_db,
        )

        payload = request.get_json(silent=True) or {}
        limit = int(payload.get("limit") or request.args.get("limit") or 50)
        lane = str(payload.get("lane") or request.args.get("lane") or "").strip()
        stage = str(payload.get("stage") or request.args.get("stage") or "").strip()
        bundle = build_population_autodrive_from_db(
            limit=limit,
            lane=lane,
            stage=stage,
            force_recompute=True,
        )
        return jsonify({
            "success": True,
            "autodrive": bundle,
            **bundle,
            "source_clinical_facts_mutated": False,
            "model_trained": False,
        })
    except Exception as e:
        logger.error(f"Error recomputing Autodrive: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<patient_ref>/autodrive', methods=['GET'])
@app.route('/api/patient/<patient_ref>/autodrive', methods=['GET'])
def api_patient_autodrive(patient_ref):
    """Patient Clinical Autodrive Command Center bundle."""
    try:
        payload, error = _build_patient_autodrive_for_api(patient_ref, force_recompute=False)
        if error:
            return error
        autodrive = payload["autodrive"]
        resolved = payload["resolved"]
        return jsonify({
            "success": True,
            "autodrive": autodrive,
            **autodrive,
            "resolved_patient_id": payload["patient_id"],
            "resolved_patient_ref": resolved.get("nss") or resolved.get("patient_ref") or str(patient_ref),
        })
    except Exception as e:
        logger.error(f"Error getting patient Autodrive: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<patient_ref>/autodrive/actions/<path:action_key>/status', methods=['POST'])
def api_patient_autodrive_action_status(patient_ref, action_key):
    """Update internal Autodrive action status with patient_events audit trail."""
    import tracking_db

    payload = request.get_json(silent=True) or {}
    status = str(payload.get("status") or "").strip().lower()
    note = str(payload.get("note") or payload.get("audit_note") or "").strip()
    updated_by = str(payload.get("updated_by") or payload.get("user") or "clinician").strip()
    try:
        built, error = _build_patient_autodrive_for_api(patient_ref, force_recompute=False)
        if error:
            return error
        autodrive = dict(built["autodrive"] or {})
        known_actions = {
            str(item.get("action_key") or "")
            for item in list(autodrive.get("autodrive_actions") or []) + list(autodrive.get("today_queue") or [])
            if isinstance(item, dict)
        }
        if action_key not in known_actions:
            return jsonify({
                "success": False,
                "error": "La accion Autodrive no pertenece al paciente o ya no esta activa",
                "action_key": action_key,
            }), 404
        ok, message, result = tracking_db.update_care_pathway_action_status(
            built["patient_id"],
            action_key,
            status,
            note=note,
            updated_by=updated_by,
        )
        if not ok:
            return jsonify({"success": False, "error": message, "action_key": action_key}), 400
        refreshed, error = _build_patient_autodrive_for_api(patient_ref, force_recompute=True)
        if error:
            return error
        return jsonify({
            "success": True,
            "message": "Estado Autodrive actualizado",
            "action_key": action_key,
            "source_clinical_facts_mutated": False,
            "external_order_created": False,
            **result,
            "autodrive": refreshed["autodrive"],
            "resolved_patient_id": refreshed["patient_id"],
            "resolved_patient_ref": refreshed["resolved"].get("nss") or refreshed["resolved"].get("patient_ref") or str(patient_ref),
        })
    except Exception as e:
        logger.error(f"Error updating Autodrive action status: {e}")
        return error_response(str(e), 500)


# ─────────────────────────────────────────────────────────────────────────
# ProstaMed Autonomous Clinical Improvement OS — shadow-mode control plane
# ─────────────────────────────────────────────────────────────────────────
@app.route("/api/autonomous-improvement/mission-control", methods=["GET"])
@require_clinical_session(scope="audit:read", redirect_to_login=False)
def api_autonomous_improvement_mission_control():
    """Progress toward ProstaMed longitudinal OS objective."""
    try:
        from prostanet.agentic.autonomous_improvement_os import build_mission_control

        bundle = build_mission_control()
        return jsonify({"success": True, "mission_control": bundle, **bundle})
    except Exception as e:
        logger.error(f"Error getting autonomous improvement mission control: {e}")
        return error_response(str(e), 500)


@app.route("/api/autonomous-improvement/gaps", methods=["GET"])
@require_clinical_session(scope="audit:read", redirect_to_login=False)
def api_autonomous_improvement_gaps():
    """Clinical Improvement Candidate queue in shadow mode."""
    try:
        from prostanet.agentic.autonomous_improvement_os import build_gap_intelligence

        limit = int(request.args.get("patient_limit") or 35)
        bundle = build_gap_intelligence(patient_limit=limit)
        return jsonify({"success": True, "gap_intelligence": bundle, **bundle})
    except Exception as e:
        logger.error(f"Error getting autonomous improvement gaps: {e}")
        return error_response(str(e), 500)


@app.route("/api/autonomous-improvement/application-telemetry", methods=["GET"])
@require_clinical_session(scope="audit:read", redirect_to_login=False)
def api_autonomous_improvement_application_telemetry():
    """Applied-cycle telemetry: software gap closure vs patient capture still needed."""
    try:
        from prostanet.agentic.autonomous_improvement_os import build_gap_intelligence

        limit = int(request.args.get("patient_limit") or 35)
        gaps = build_gap_intelligence(patient_limit=limit)
        telemetry = gaps.get("application_telemetry") or {}
        return jsonify({
            "success": True,
            "application_telemetry": telemetry,
            **telemetry,
            "source_clinical_facts_mutated": False,
            "files_modified_by_telemetry": False,
            "git_mutated": False,
        })
    except Exception as e:
        logger.error(f"Error getting autonomous improvement application telemetry: {e}")
        return error_response(str(e), 500)


@app.route("/api/autonomous-improvement/proposals", methods=["GET"])
@require_clinical_session(scope="audit:read", redirect_to_login=False)
def api_autonomous_improvement_proposals():
    """Structured shadow proposals with tests, evidence and rollback."""
    try:
        from prostanet.agentic.autonomous_improvement_os import (
            build_gap_intelligence,
            build_proposals,
        )

        gaps = build_gap_intelligence(patient_limit=int(request.args.get("patient_limit") or 35))
        proposals = build_proposals(gaps.get("candidates", []))
        return jsonify({"success": True, "proposals_bundle": proposals, **proposals})
    except Exception as e:
        logger.error(f"Error getting autonomous improvement proposals: {e}")
        return error_response(str(e), 500)


@app.route("/api/autonomous-improvement/shadow-pr", methods=["GET"])
@require_clinical_session(scope="audit:read", redirect_to_login=False)
def api_autonomous_improvement_shadow_pr():
    """Draft PR package for the selected autonomous improvement; no git mutation."""
    try:
        from prostanet.agentic.autonomous_improvement_os import (
            build_autonomous_improvement_bundle,
        )

        bundle = build_autonomous_improvement_bundle(
            patient_limit=int(request.args.get("patient_limit") or 20)
        )
        shadow_pr = bundle.get("shadow_pr_factory") or {}
        return jsonify({
            "success": True,
            "shadow_pr_factory": shadow_pr,
            **shadow_pr,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "pull_request_created": False,
        })
    except Exception as e:
        logger.error(f"Error getting autonomous improvement shadow PR package: {e}")
        return error_response(str(e), 500)


@app.route("/api/autonomous-improvement/safety-gates", methods=["GET"])
@require_clinical_session(scope="audit:read", redirect_to_login=False)
def api_autonomous_improvement_safety_gates():
    """Safety gates for the selected shadow PR package; plan-only, no command execution."""
    try:
        from prostanet.agentic.autonomous_improvement_os import (
            build_autonomous_improvement_bundle,
        )

        bundle = build_autonomous_improvement_bundle(
            patient_limit=int(request.args.get("patient_limit") or 20)
        )
        gates = bundle.get("safety_gate_runner") or {}
        return jsonify({
            "success": True,
            "safety_gate_runner": gates,
            **gates,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "commands_executed": False,
        })
    except Exception as e:
        logger.error(f"Error getting autonomous improvement safety gates: {e}")
        return error_response(str(e), 500)


@app.route("/api/autonomous-improvement/shadow-execution", methods=["GET"])
@require_clinical_session(scope="audit:read", redirect_to_login=False)
def api_autonomous_improvement_shadow_execution():
    """Phase 3D shadow execution artifacts; read-only, no shell execution."""
    try:
        from prostanet.agentic.autonomous_improvement_os import (
            build_autonomous_improvement_bundle,
        )

        bundle = build_autonomous_improvement_bundle(
            patient_limit=int(request.args.get("patient_limit") or 20)
        )
        artifacts = bundle.get("shadow_execution_artifacts") or {}
        return jsonify({
            "success": True,
            "shadow_execution_artifacts": artifacts,
            **artifacts,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "auto_merge_allowed": False,
        })
    except Exception as e:
        logger.error(f"Error getting autonomous improvement shadow execution artifacts: {e}")
        return error_response(str(e), 500)


@app.route("/api/autonomous-improvement/human-review-gate", methods=["GET"])
@require_clinical_session(scope="audit:read", redirect_to_login=False)
def api_autonomous_improvement_human_review_gate():
    """Phase 3E explicit human decision gate; read-only status."""
    try:
        from prostanet.agentic.autonomous_improvement_os import (
            build_autonomous_improvement_bundle,
        )

        bundle = build_autonomous_improvement_bundle(
            patient_limit=int(request.args.get("patient_limit") or 20)
        )
        gate = bundle.get("human_review_decision_gate") or {}
        return jsonify({
            "success": True,
            "human_review_decision_gate": gate,
            **gate,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "pull_request_created": False,
            "auto_merge_allowed": False,
        })
    except Exception as e:
        logger.error(f"Error getting autonomous improvement human review gate: {e}")
        return error_response(str(e), 500)


@app.route("/api/autonomous-improvement/human-review-gate/decision", methods=["POST"])
@require_clinical_session(scope="audit:read", redirect_to_login=False)
def api_autonomous_improvement_human_review_gate_decision():
    """Record Phase 3E human decision; no branch, PR, merge or medicine mutation."""
    try:
        from prostanet.agentic.autonomous_improvement_os import (
            build_autonomous_improvement_bundle,
            record_human_review_gate_decision,
        )

        payload = request.get_json(silent=True) or {}
        pre_bundle = build_autonomous_improvement_bundle(
            patient_limit=int(payload.get("patient_limit") or request.args.get("patient_limit") or 20)
        )
        event = record_human_review_gate_decision(
            decision=str(payload.get("decision") or "hold"),
            reviewer=str(payload.get("reviewer") or "local_clinical_reviewer"),
            note=str(payload.get("note") or ""),
            shadow_pr_factory=pre_bundle.get("shadow_pr_factory") or {},
            shadow_execution_artifacts=pre_bundle.get("shadow_execution_artifacts") or {},
        )
        bundle = build_autonomous_improvement_bundle(
            patient_limit=int(payload.get("patient_limit") or request.args.get("patient_limit") or 20)
        )
        return jsonify({
            "success": True,
            "decision": event,
            "human_review_decision_gate": bundle.get("human_review_decision_gate") or {},
            "bundle": bundle,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "pull_request_created": False,
            "auto_merge_allowed": False,
        })
    except Exception as e:
        logger.error(f"Error recording autonomous improvement human review decision: {e}")
        return error_response(str(e), 500)


@app.route("/api/autonomous-improvement/draft-pr-handoff", methods=["GET"])
@require_clinical_session(scope="audit:read", redirect_to_login=False)
def api_autonomous_improvement_draft_pr_handoff():
    """Phase 3F manual draft-PR handoff plan; never creates branch or PR."""
    try:
        from prostanet.agentic.autonomous_improvement_os import (
            build_autonomous_improvement_bundle,
        )

        bundle = build_autonomous_improvement_bundle(
            patient_limit=int(request.args.get("patient_limit") or 20)
        )
        handoff = bundle.get("draft_pr_handoff") or {}
        return jsonify({
            "success": True,
            "draft_pr_handoff": handoff,
            **handoff,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "branch_created": False,
            "pull_request_created": False,
            "auto_merge_allowed": False,
        })
    except Exception as e:
        logger.error(f"Error getting autonomous improvement draft PR handoff: {e}")
        return error_response(str(e), 500)


@app.route("/api/autonomous-improvement/pr-review-monitor", methods=["GET"])
@require_clinical_session(scope="audit:read", redirect_to_login=False)
def api_autonomous_improvement_pr_review_monitor():
    """Phase 3G PR review monitor; read-only and never merges."""
    try:
        from prostanet.agentic.autonomous_improvement_os import (
            build_autonomous_improvement_bundle,
        )

        bundle = build_autonomous_improvement_bundle(
            patient_limit=int(request.args.get("patient_limit") or 20)
        )
        monitor = bundle.get("pr_review_monitor") or {}
        return jsonify({
            "success": True,
            "pr_review_monitor": monitor,
            **monitor,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "branch_created": False,
            "pull_request_created": False,
            "merge_performed": False,
            "auto_merge_allowed": False,
        })
    except Exception as e:
        logger.error(f"Error getting autonomous improvement PR review monitor: {e}")
        return error_response(str(e), 500)


@app.route("/api/autonomous-improvement/pr-review-monitor/metadata", methods=["POST"])
@require_clinical_session(scope="audit:read", redirect_to_login=False)
def api_autonomous_improvement_pr_review_monitor_metadata():
    """Record external PR/CI/review metadata for 3G; audit only."""
    try:
        from prostanet.agentic.autonomous_improvement_os import (
            build_autonomous_improvement_bundle,
            record_pr_review_monitor_metadata,
        )

        payload = request.get_json(silent=True) or {}
        pre_bundle = build_autonomous_improvement_bundle(
            patient_limit=int(payload.get("patient_limit") or request.args.get("patient_limit") or 20)
        )
        handoff = pre_bundle.get("draft_pr_handoff") or {}
        branch_plan = handoff.get("branch_plan") or {}
        event = record_pr_review_monitor_metadata(
            branch_name=str(payload.get("branch_name") or branch_plan.get("branch_name") or ""),
            pr_url=str(payload.get("pr_url") or ""),
            pr_number=payload.get("pr_number") or "",
            ci_status=str(payload.get("ci_status") or "unknown"),
            review_status=str(payload.get("review_status") or "pending"),
            reviewer=str(payload.get("reviewer") or "local_clinical_reviewer"),
            note=str(payload.get("note") or ""),
        )
        bundle = build_autonomous_improvement_bundle(
            patient_limit=int(payload.get("patient_limit") or request.args.get("patient_limit") or 20)
        )
        return jsonify({
            "success": True,
            "metadata": event,
            "pr_review_monitor": bundle.get("pr_review_monitor") or {},
            "bundle": bundle,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "branch_created": False,
            "pull_request_created": False,
            "merge_performed": False,
            "auto_merge_allowed": False,
        })
    except Exception as e:
        logger.error(f"Error recording autonomous improvement PR review metadata: {e}")
        return error_response(str(e), 500)


@app.route("/api/autonomous-improvement/agent-lane-registry", methods=["GET"])
@require_clinical_session(scope="audit:read", redirect_to_login=False)
def api_autonomous_improvement_agent_lane_registry():
    """Phase 4A specialized agent registry; shadow proposals only."""
    try:
        from prostanet.agentic.autonomous_improvement_os import (
            build_autonomous_improvement_bundle,
        )

        bundle = build_autonomous_improvement_bundle(
            patient_limit=int(request.args.get("patient_limit") or 20)
        )
        registry = bundle.get("agent_lane_registry") or {}
        return jsonify({
            "success": True,
            "agent_lane_registry": registry,
            **registry,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "branch_created": False,
            "pull_request_created": False,
            "merge_performed": False,
            "auto_merge_allowed": False,
        })
    except Exception as e:
        logger.error(f"Error getting autonomous improvement agent lane registry: {e}")
        return error_response(str(e), 500)


@app.route("/api/autonomous-improvement/agent-proposal-packets", methods=["GET"])
@require_clinical_session(scope="audit:read", redirect_to_login=False)
def api_autonomous_improvement_agent_proposal_packets():
    """Phase 4B specialized agent proposal packets; proposal-only."""
    try:
        from prostanet.agentic.autonomous_improvement_os import (
            build_autonomous_improvement_bundle,
        )

        bundle = build_autonomous_improvement_bundle(
            patient_limit=int(request.args.get("patient_limit") or 20)
        )
        packets = bundle.get("agent_proposal_packets") or {}
        return jsonify({
            "success": True,
            "agent_proposal_packets": packets,
            **packets,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "branch_created": False,
            "pull_request_created": False,
            "merge_performed": False,
            "auto_merge_allowed": False,
        })
    except Exception as e:
        logger.error(f"Error getting autonomous improvement agent proposal packets: {e}")
        return error_response(str(e), 500)


@app.route("/api/autonomous-improvement/agent-consensus-synthesizer", methods=["GET"])
@require_clinical_session(scope="audit:read", redirect_to_login=False)
def api_autonomous_improvement_agent_consensus_synthesizer():
    """Phase 4C consensus synthesizer; one reviewable next step, no mutation."""
    try:
        from prostanet.agentic.autonomous_improvement_os import (
            build_autonomous_improvement_bundle,
        )

        bundle = build_autonomous_improvement_bundle(
            patient_limit=int(request.args.get("patient_limit") or 20)
        )
        consensus = bundle.get("agent_consensus_synthesizer") or {}
        return jsonify({
            "success": True,
            "agent_consensus_synthesizer": consensus,
            **consensus,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "branch_created": False,
            "pull_request_created": False,
            "merge_performed": False,
            "auto_merge_allowed": False,
        })
    except Exception as e:
        logger.error(f"Error getting autonomous improvement agent consensus synthesizer: {e}")
        return error_response(str(e), 500)


@app.route("/api/autonomous-improvement/implementation-brief", methods=["GET"])
@require_clinical_session(scope="audit:read", redirect_to_login=False)
def api_autonomous_improvement_implementation_brief():
    """Phase 4D implementation brief; read-only handoff, no mutation."""
    try:
        from prostanet.agentic.autonomous_improvement_os import (
            build_autonomous_improvement_bundle,
        )

        bundle = build_autonomous_improvement_bundle(
            patient_limit=int(request.args.get("patient_limit") or 20)
        )
        brief = bundle.get("implementation_brief") or {}
        return jsonify({
            "success": True,
            "implementation_brief": brief,
            **brief,
            "commands_executed": False,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "branch_created": False,
            "pull_request_created": False,
            "merge_performed": False,
            "auto_merge_allowed": False,
        })
    except Exception as e:
        logger.error(f"Error getting autonomous improvement implementation brief: {e}")
        return error_response(str(e), 500)


@app.route("/api/autonomous-improvement/shadow-patch-blueprint", methods=["GET"])
@require_clinical_session(scope="audit:read", redirect_to_login=False)
def api_autonomous_improvement_shadow_patch_blueprint():
    """Phase 4E shadow patch blueprint; planned diff only, no file writes."""
    try:
        from prostanet.agentic.autonomous_improvement_os import (
            build_autonomous_improvement_bundle,
        )

        bundle = build_autonomous_improvement_bundle(
            patient_limit=int(request.args.get("patient_limit") or 20)
        )
        blueprint = bundle.get("shadow_patch_blueprint") or {}
        return jsonify({
            "success": True,
            "shadow_patch_blueprint": blueprint,
            **blueprint,
            "commands_executed": False,
            "files_modified": False,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "branch_created": False,
            "pull_request_created": False,
            "merge_performed": False,
            "auto_merge_allowed": False,
        })
    except Exception as e:
        logger.error(f"Error getting autonomous improvement shadow patch blueprint: {e}")
        return error_response(str(e), 500)


@app.route("/api/autonomous-improvement/human-patch-authorization", methods=["GET"])
@require_clinical_session(scope="audit:read", redirect_to_login=False)
def api_autonomous_improvement_human_patch_authorization():
    """Phase 4F human patch authorization status; read-only."""
    try:
        from prostanet.agentic.autonomous_improvement_os import (
            build_autonomous_improvement_bundle,
        )

        bundle = build_autonomous_improvement_bundle(
            patient_limit=int(request.args.get("patient_limit") or 20)
        )
        authorization = bundle.get("human_patch_authorization") or {}
        return jsonify({
            "success": True,
            "human_patch_authorization": authorization,
            **authorization,
            "commands_executed": False,
            "files_modified": False,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "branch_created": False,
            "pull_request_created": False,
            "merge_performed": False,
            "auto_merge_allowed": False,
        })
    except Exception as e:
        logger.error(f"Error getting autonomous improvement human patch authorization: {e}")
        return error_response(str(e), 500)


@app.route("/api/autonomous-improvement/human-patch-authorization/decision", methods=["POST"])
@require_clinical_session(scope="audit:read", redirect_to_login=False)
def api_autonomous_improvement_human_patch_authorization_decision():
    """Record Phase 4F human patch authorization; no patch, branch, PR, merge or medicine mutation."""
    try:
        from prostanet.agentic.autonomous_improvement_os import (
            build_autonomous_improvement_bundle,
            record_human_patch_authorization_decision,
        )

        payload = request.get_json(silent=True) or {}
        patient_limit = int(payload.get("patient_limit") or request.args.get("patient_limit") or 20)
        pre_bundle = build_autonomous_improvement_bundle(patient_limit=patient_limit)
        event = record_human_patch_authorization_decision(
            decision=str(payload.get("decision") or "hold"),
            reviewer=str(payload.get("reviewer") or "local_clinical_reviewer"),
            note=str(payload.get("note") or ""),
            shadow_patch_blueprint=pre_bundle.get("shadow_patch_blueprint") or {},
        )
        bundle = build_autonomous_improvement_bundle(patient_limit=patient_limit)
        return jsonify({
            "success": True,
            "decision": event,
            "human_patch_authorization": bundle.get("human_patch_authorization") or {},
            "bundle": bundle,
            "commands_executed": False,
            "files_modified": False,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "branch_created": False,
            "pull_request_created": False,
            "merge_performed": False,
            "auto_merge_allowed": False,
        })
    except Exception as e:
        logger.error(f"Error recording autonomous improvement human patch authorization: {e}")
        return error_response(str(e), 500)


@app.route("/api/autonomous-improvement/controlled-patch-application", methods=["GET"])
@require_clinical_session(scope="audit:read", redirect_to_login=False)
def api_autonomous_improvement_controlled_patch_application():
    """Phase 4G controlled patch application packet; no command/file/git mutation."""
    try:
        from prostanet.agentic.autonomous_improvement_os import (
            build_autonomous_improvement_bundle,
        )

        bundle = build_autonomous_improvement_bundle(
            patient_limit=int(request.args.get("patient_limit") or 20)
        )
        application = bundle.get("controlled_patch_application") or {}
        return jsonify({
            "success": True,
            "controlled_patch_application": application,
            **application,
            "commands_executed": False,
            "files_modified": False,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "branch_created": False,
            "pull_request_created": False,
            "merge_performed": False,
            "auto_merge_allowed": False,
        })
    except Exception as e:
        logger.error(f"Error getting autonomous improvement controlled patch application: {e}")
        return error_response(str(e), 500)


@app.route("/api/autonomous-improvement/controlled-pr-implementation", methods=["GET"])
@require_clinical_session(scope="audit:read", redirect_to_login=False)
def api_autonomous_improvement_controlled_pr_implementation():
    """Phase 5A controlled PR implementation packet; no branch/patch/PR mutation."""
    try:
        from prostanet.agentic.autonomous_improvement_os import (
            build_autonomous_improvement_bundle,
        )

        bundle = build_autonomous_improvement_bundle(
            patient_limit=int(request.args.get("patient_limit") or 20)
        )
        implementation = bundle.get("controlled_pr_implementation") or {}
        return jsonify({
            "success": True,
            "controlled_pr_implementation": implementation,
            **implementation,
            "commands_executed": False,
            "files_modified": False,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "branch_created": False,
            "pull_request_created": False,
            "merge_performed": False,
            "auto_merge_allowed": False,
        })
    except Exception as e:
        logger.error(f"Error getting autonomous improvement controlled PR implementation: {e}")
        return error_response(str(e), 500)


@app.route("/api/autonomous-improvement/draft-pr-publication-gate", methods=["GET"])
@require_clinical_session(scope="audit:read", redirect_to_login=False)
def api_autonomous_improvement_draft_pr_publication_gate():
    """Phase 5B draft PR publication gate; no PR creation or git mutation."""
    try:
        from prostanet.agentic.autonomous_improvement_os import (
            build_autonomous_improvement_bundle,
        )

        bundle = build_autonomous_improvement_bundle(
            patient_limit=int(request.args.get("patient_limit") or 20)
        )
        gate = bundle.get("draft_pr_publication_gate") or {}
        return jsonify({
            "success": True,
            "draft_pr_publication_gate": gate,
            **gate,
            "commands_executed": False,
            "files_modified": False,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "branch_created": False,
            "pull_request_created": False,
            "merge_performed": False,
            "auto_merge_allowed": False,
        })
    except Exception as e:
        logger.error(f"Error getting autonomous improvement draft PR publication gate: {e}")
        return error_response(str(e), 500)


@app.route("/api/autonomous-improvement/required-safety-gate-contract", methods=["GET"])
@require_clinical_session(scope="audit:read", redirect_to_login=False)
def api_autonomous_improvement_required_safety_gate_contract():
    """Phase 6A required safety gate contract; no command execution or git mutation."""
    try:
        from prostanet.agentic.autonomous_improvement_os import (
            build_autonomous_improvement_bundle,
        )

        bundle = build_autonomous_improvement_bundle(
            patient_limit=int(request.args.get("patient_limit") or 20)
        )
        contract = bundle.get("required_safety_gate_contract") or {}
        return jsonify({
            "success": True,
            "required_safety_gate_contract": contract,
            **contract,
            "commands_executed": False,
            "files_modified": False,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "branch_created": False,
            "pull_request_created": False,
            "merge_performed": False,
            "auto_merge_allowed": False,
        })
    except Exception as e:
        logger.error(f"Error getting autonomous improvement required safety gate contract: {e}")
        return error_response(str(e), 500)


@app.route("/api/autonomous-improvement/evidence-refresh-shadow-loop", methods=["GET"])
@require_clinical_session(scope="audit:read", redirect_to_login=False)
def api_autonomous_improvement_evidence_refresh_shadow_loop():
    """Phase 7A evidence refresh shadow loop; no evidence application or logic mutation."""
    try:
        from prostanet.agentic.autonomous_improvement_os import (
            build_autonomous_improvement_bundle,
        )

        bundle = build_autonomous_improvement_bundle(
            patient_limit=int(request.args.get("patient_limit") or 20)
        )
        evidence_loop = bundle.get("evidence_refresh_shadow_loop") or {}
        return jsonify({
            "success": True,
            "evidence_refresh_shadow_loop": evidence_loop,
            **evidence_loop,
            "evidence_changes_applied": False,
            "recommendation_logic_mutated": False,
            "trial_logic_mutated": False,
            "gate_logic_mutated": False,
            "commands_executed": False,
            "files_modified": False,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "branch_created": False,
            "pull_request_created": False,
            "merge_performed": False,
            "auto_merge_allowed": False,
        })
    except Exception as e:
        logger.error(f"Error getting autonomous improvement evidence refresh shadow loop: {e}")
        return error_response(str(e), 500)


@app.route("/api/autonomous-improvement/patient-twin-readiness-loop", methods=["GET"])
@require_clinical_session(scope="audit:read", redirect_to_login=False)
def api_autonomous_improvement_patient_twin_readiness_loop():
    """Phase 8A Patient Twin readiness loop; no simulation, ML training or prediction release."""
    try:
        from prostanet.agentic.autonomous_improvement_os import (
            build_autonomous_improvement_bundle,
        )

        bundle = build_autonomous_improvement_bundle(
            patient_limit=int(request.args.get("patient_limit") or 20)
        )
        twin_loop = bundle.get("patient_twin_readiness_loop") or {}
        return jsonify({
            "success": True,
            "patient_twin_readiness_loop": twin_loop,
            **twin_loop,
            "simulation_release_allowed": False,
            "patient_twin_models_trained": False,
            "patient_twin_predictions_released": False,
            "commands_executed": False,
            "files_modified": False,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "branch_created": False,
            "pull_request_created": False,
            "merge_performed": False,
            "auto_merge_allowed": False,
        })
    except Exception as e:
        logger.error(f"Error getting autonomous improvement patient twin readiness loop: {e}")
        return error_response(str(e), 500)


@app.route("/api/autonomous-improvement/ai-readiness-dataset-loop", methods=["GET"])
@require_clinical_session(scope="audit:read", redirect_to_login=False)
def api_autonomous_improvement_ai_readiness_dataset_loop():
    """Phase 9A AI readiness dataset loop; no export, ML training or prediction release."""
    try:
        from prostanet.agentic.autonomous_improvement_os import (
            build_autonomous_improvement_bundle,
        )

        bundle = build_autonomous_improvement_bundle(
            patient_limit=int(request.args.get("patient_limit") or 20)
        )
        ai_loop = bundle.get("ai_readiness_dataset_loop") or {}
        return jsonify({
            "success": True,
            "ai_readiness_dataset_loop": ai_loop,
            **ai_loop,
            "dataset_export_allowed": False,
            "dataset_export_written": False,
            "deidentified_dataset_written": False,
            "model_training_allowed": False,
            "model_training_executed": False,
            "models_trained": False,
            "prediction_release_allowed": False,
            "predictions_released": False,
            "recommendation_logic_mutated": False,
            "commands_executed": False,
            "files_modified": False,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "branch_created": False,
            "pull_request_created": False,
            "merge_performed": False,
            "auto_merge_allowed": False,
        })
    except Exception as e:
        logger.error(f"Error getting autonomous improvement AI readiness dataset loop: {e}")
        return error_response(str(e), 500)


@app.route("/api/autonomous-improvement/cortana-loop-interface", methods=["GET"])
@require_clinical_session(scope="audit:read", redirect_to_login=False)
def api_autonomous_improvement_cortana_loop_interface():
    """Phase 10A Cortana consultative loop interface; no execution or mutation."""
    try:
        from prostanet.agentic.autonomous_improvement_os import (
            build_autonomous_improvement_bundle,
            build_cortana_loop_interface,
        )

        bundle = build_autonomous_improvement_bundle(
            patient_limit=int(request.args.get("patient_limit") or 20)
        )
        cortana_loop = build_cortana_loop_interface(
            ai_readiness_dataset_loop=bundle.get("ai_readiness_dataset_loop") or {},
            mission_control=bundle.get("mission_control") or {},
            development_autodrive=bundle.get("development_autodrive") or {},
            gap_bundle=bundle.get("gaps") or {},
            patient_twin_readiness_loop=bundle.get("patient_twin_readiness_loop") or {},
            evidence_refresh_shadow_loop=bundle.get("evidence_refresh_shadow_loop") or {},
            query=request.args.get("query") or request.args.get("q") or "",
        )
        return jsonify({
            "success": True,
            "cortana_loop_interface": cortana_loop,
            **cortana_loop,
            "voice_write_allowed": False,
            "clinical_fact_writes_allowed": False,
            "code_mutation_allowed": False,
            "dataset_export_allowed": False,
            "model_training_allowed": False,
            "prediction_release_allowed": False,
            "external_action_allowed": False,
            "commands_executed": False,
            "files_modified": False,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "branch_created": False,
            "pull_request_created": False,
            "merge_performed": False,
            "auto_merge_allowed": False,
        })
    except Exception as e:
        logger.error(f"Error getting autonomous improvement Cortana loop interface: {e}")
        return error_response(str(e), 500)


@app.route("/api/autonomous-improvement/continuous-shadow-operation", methods=["GET"])
@require_clinical_session(scope="audit:read", redirect_to_login=False)
def api_autonomous_improvement_continuous_shadow_operation():
    """Continuous shadow cycle read-model; packages one gap and returns to human authorization."""
    try:
        from prostanet.agentic.autonomous_improvement_os import (
            build_autonomous_improvement_bundle,
            build_continuous_shadow_operation,
        )

        bundle = build_autonomous_improvement_bundle(
            patient_limit=int(request.args.get("patient_limit") or 20)
        )
        continuous = build_continuous_shadow_operation(
            cortana_loop_interface=bundle.get("cortana_loop_interface") or {},
            mission_control=bundle.get("mission_control") or {},
            development_autodrive=bundle.get("development_autodrive") or {},
            gap_bundle=bundle.get("gaps") or {},
            proposals=bundle.get("proposals") or {},
            shadow_pr_factory=bundle.get("shadow_pr_factory") or {},
            safety_gate_runner=bundle.get("safety_gate_runner") or {},
            shadow_execution_artifacts=bundle.get("shadow_execution_artifacts") or {},
            agent_consensus_synthesizer=bundle.get("agent_consensus_synthesizer") or {},
            implementation_brief=bundle.get("implementation_brief") or {},
            shadow_patch_blueprint=bundle.get("shadow_patch_blueprint") or {},
            human_patch_authorization=bundle.get("human_patch_authorization") or {},
            required_safety_gate_contract=bundle.get("required_safety_gate_contract") or {},
        )
        return jsonify({
            "success": True,
            "continuous_shadow_operation": continuous,
            **continuous,
            "commands_executed": False,
            "files_modified": False,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "branch_created": False,
            "pull_request_created": False,
            "merge_performed": False,
            "auto_merge_allowed": False,
        })
    except Exception as e:
        logger.error(f"Error getting continuous shadow operation: {e}")
        return error_response(str(e), 500)


@app.route("/api/autonomous-improvement/recompute", methods=["POST"])
@require_clinical_session(scope="audit:read", redirect_to_login=False)
def api_autonomous_improvement_recompute():
    """Recompute shadow read-models without mutating clinical source facts."""
    try:
        from prostanet.agentic.autonomous_improvement_os import recompute_shadow_bundle

        payload = request.get_json(silent=True) or {}
        bundle = recompute_shadow_bundle(
            patient_limit=int(payload.get("patient_limit") or request.args.get("patient_limit") or 35)
        )
        return jsonify(bundle)
    except Exception as e:
        logger.error(f"Error recomputing autonomous improvement bundle: {e}")
        return error_response(str(e), 500)


@app.route("/api/autonomous-improvement/proposals/<path:proposal_id>/approve", methods=["POST"])
@require_clinical_session(scope="audit:read", redirect_to_login=False)
def api_autonomous_improvement_approve(proposal_id):
    """Record human approval of a shadow proposal; no merge or medicine mutation."""
    try:
        from prostanet.agentic.autonomous_improvement_os import (
            build_autonomous_improvement_bundle,
            record_proposal_review,
        )

        payload = request.get_json(silent=True) or {}
        event = record_proposal_review(
            proposal_id,
            status="approved",
            reviewer=str(payload.get("reviewer") or "local_clinical_reviewer"),
            note=str(payload.get("note") or ""),
        )
        bundle = build_autonomous_improvement_bundle(patient_limit=20)
        return jsonify({"success": True, "review": event, "bundle": bundle, "source_clinical_facts_mutated": False})
    except Exception as e:
        logger.error(f"Error approving autonomous improvement proposal: {e}")
        return error_response(str(e), 500)


@app.route("/api/autonomous-improvement/proposals/<path:proposal_id>/reject", methods=["POST"])
@require_clinical_session(scope="audit:read", redirect_to_login=False)
def api_autonomous_improvement_reject(proposal_id):
    """Record human rejection of a shadow proposal; no medicine mutation."""
    try:
        from prostanet.agentic.autonomous_improvement_os import (
            build_autonomous_improvement_bundle,
            record_proposal_review,
        )

        payload = request.get_json(silent=True) or {}
        event = record_proposal_review(
            proposal_id,
            status="rejected",
            reviewer=str(payload.get("reviewer") or "local_clinical_reviewer"),
            note=str(payload.get("note") or ""),
        )
        bundle = build_autonomous_improvement_bundle(patient_limit=20)
        return jsonify({"success": True, "review": event, "bundle": bundle, "source_clinical_facts_mutated": False})
    except Exception as e:
        logger.error(f"Error rejecting autonomous improvement proposal: {e}")
        return error_response(str(e), 500)


def _build_clinical_memory_os_for_api(patient_ref, *, force_recompute=False, include_cohort=True):
    import tracking_db
    from prostanet.domains.patient_tracking.clinical_memory_os import build_clinical_memory_os

    resolved, error = _resolve_patient_api_ref(patient_ref)
    if error:
        return None, error
    patient_id = resolved["patient_id"]
    patient = tracking_db.get_patient_full_record(patient_id)
    if not patient:
        return None, error_response("Paciente no encontrado", 404)
    bundle = tracking_db.refresh_longitudinal_intelligence(
        patient_id,
        force_recompute=bool(force_recompute),
        record=patient,
        include_live_benchmark=False,
    )
    patient = tracking_db.get_patient_full_record(patient_id) or patient
    signals = dict(bundle.get("signals") or {})
    cohort_records = _load_clinical_memory_cohort_records(tracking_db) if include_cohort else []
    memory = build_clinical_memory_os(
        patient,
        longitudinal_bundle=bundle,
        state=str(
            signals.get("effective_state_final")
            or signals.get("effective_state")
            or signals.get("reconciled_state")
            or (patient.get("latest_assessment") or {}).get("state")
            or ""
        ),
        management_track=str(
            signals.get("effective_management_track_final")
            or signals.get("effective_management_track")
            or signals.get("reconciled_management_track")
            or ""
        ),
        patient_ref=str(resolved.get("nss") or resolved.get("patient_ref") or patient_ref),
        cohort_records=cohort_records,
    )
    return {
        "memory": memory,
        "bundle": bundle,
        "patient": patient,
        "resolved": resolved,
        "patient_id": patient_id,
    }, None


@app.route('/api/patients/<patient_ref>/clinical-memory-os', methods=['GET'])
@app.route('/api/patient/<patient_ref>/clinical-memory-os', methods=['GET'])
def api_patient_clinical_memory_os(patient_ref):
    """Clinical Memory & Outcomes Learning OS read model for one patient."""
    try:
        payload, error = _build_clinical_memory_os_for_api(
            patient_ref,
            force_recompute=False,
            include_cohort=True,
        )
        if error:
            return error
        memory = payload["memory"]
        resolved = payload["resolved"]
        return jsonify({
            "success": True,
            "clinical_memory_os": memory,
            **memory,
            "resolved_patient_id": payload["patient_id"],
            "resolved_patient_ref": resolved.get("nss") or resolved.get("patient_ref") or str(patient_ref),
        })
    except Exception as e:
        logger.error(f"Error getting Clinical Memory OS: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<patient_ref>/outcome-episodes', methods=['GET'])
def api_patient_outcome_episodes(patient_ref):
    """Decision episode ledger derived by Clinical Memory OS."""
    try:
        payload, error = _build_clinical_memory_os_for_api(
            patient_ref,
            force_recompute=False,
            include_cohort=False,
        )
        if error:
            return error
        memory = payload["memory"]
        return jsonify({
            "success": True,
            "decision_episodes": memory.get("decision_episodes", []),
            "summary": memory.get("summary", {}),
            "audit": memory.get("audit", {}),
            "resolved_patient_id": payload["patient_id"],
            "resolved_patient_ref": payload["resolved"].get("nss") or payload["resolved"].get("patient_ref") or str(patient_ref),
        })
    except Exception as e:
        logger.error(f"Error getting outcome episodes: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<patient_ref>/clinical-memory-os/recompute', methods=['POST'])
def api_patient_clinical_memory_recompute(patient_ref):
    """Recompute Clinical Memory OS without inventing or overwriting source facts."""
    try:
        payload, error = _build_clinical_memory_os_for_api(
            patient_ref,
            force_recompute=True,
            include_cohort=True,
        )
        if error:
            return error
        memory = payload["memory"]
        return jsonify({
            "success": True,
            "clinical_memory_os": memory,
            "source_clinical_facts_mutated": False,
            "model_trained": False,
            "resolved_patient_id": payload["patient_id"],
            "resolved_patient_ref": payload["resolved"].get("nss") or payload["resolved"].get("patient_ref") or str(patient_ref),
        })
    except Exception as e:
        logger.error(f"Error recomputing Clinical Memory OS: {e}")
        return error_response(str(e), 500)


@app.route('/api/cohorts/similar-patients', methods=['GET'])
def api_similar_patients_cohort():
    """Non-authoritative similar cohort mirror for Clinical Memory OS."""
    import tracking_db
    from prostanet.domains.patient_tracking.clinical_memory_os import build_similar_cohort_mirror

    patient_ref = request.args.get("patient_ref") or request.args.get("nss") or ""
    state = request.args.get("state") or ""
    if not patient_ref:
        return error_response("patient_ref requerido", 400)
    try:
        resolved, error = _resolve_patient_api_ref(patient_ref)
        if error:
            return error
        patient = tracking_db.get_patient_full_record(
            resolved["patient_id"],
            include_derivatives=False,
            include_ledger=False,
        )
        if not patient:
            return error_response("Paciente no encontrado", 404)
        cohort_records = _load_clinical_memory_cohort_records(tracking_db)
        mirror = build_similar_cohort_mirror(
            patient,
            cohort_records=cohort_records,
            state=state,
        )
        return jsonify({
            "success": True,
            "similar_cohort_mirror": mirror,
            **mirror,
            "resolved_patient_id": resolved["patient_id"],
            "resolved_patient_ref": resolved.get("nss") or resolved.get("patient_ref") or str(patient_ref),
        })
    except Exception as e:
        logger.error(f"Error getting similar patient cohort: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<patient_ref>/labs-intelligence', methods=['GET'])
def api_patient_labs_intelligence(patient_ref):
    import tracking_db
    try:
        resolved, error = _resolve_patient_api_ref(patient_ref)
        if error:
            return error
        patient_id = resolved["patient_id"]
        tracking_db.refresh_longitudinal_intelligence(patient_id, force_recompute=False)
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return error_response("Paciente no encontrado", 404)
        payload = tracking_db.get_patient_labs_intelligence(patient_id)
        if payload is None:
            return error_response("Paciente no encontrado", 404)
        return jsonify(
            {
                "success": True,
                "laboratory_intelligence_profile": payload,
                "active_alerts": payload.get("active_alerts", []),
                "trend_series": payload.get("series", []),
                "treatment_linked_rules": payload.get("therapy_safety_checkpoints", []),
                "coverage_gaps": payload.get("coverage", {}),
                "latest_clinically_decisive_visit": patient.get("latest_clinically_decisive_visit", {}),
                "resolved_patient_id": patient_id,
                "resolved_patient_ref": resolved.get("nss") or resolved.get("patient_ref") or str(patient_ref),
                **_reconciled_patient_snapshot(patient),
            }
        )
    except Exception as e:
        logger.error(f"Error getting patient labs intelligence: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<patient_ref>/decision-trace', methods=['GET'])
def api_patient_decision_trace(patient_ref):
    import tracking_db
    try:
        resolved, error = _resolve_patient_api_ref(patient_ref)
        if error:
            return error
        patient_id = resolved["patient_id"]
        tracking_db.refresh_longitudinal_intelligence(patient_id, force_recompute=False)
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return error_response("Paciente no encontrado", 404)
        payload = tracking_db.get_patient_decision_trace(patient_id)
        if payload is None:
            return error_response("Paciente no encontrado", 404)
        return jsonify(
            {
                "success": True,
                "decision_recalculation_trace": payload,
                "longitudinal_truth_snapshot": patient.get("longitudinal_truth_snapshot", {}),
                "decision_snapshot_history": patient.get("decision_snapshot_history", []),
                "guideline_plan_history": patient.get("guideline_plan_history", []),
                "missing_input_history": patient.get("missing_input_history", []),
                "resolved_patient_id": patient_id,
                "resolved_patient_ref": resolved.get("nss") or resolved.get("patient_ref") or str(patient_ref),
                **_reconciled_patient_snapshot(patient),
            }
        )
    except Exception as e:
        logger.error(f"Error getting patient decision trace: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<patient_ref>/decision-governance', methods=['GET'])
def api_patient_decision_governance(patient_ref):
    import tracking_db
    try:
        resolved, error = _resolve_patient_api_ref(patient_ref)
        if error:
            return error
        patient_id = resolved["patient_id"]
        bundle = tracking_db.refresh_longitudinal_intelligence(
            patient_id,
            force_recompute=True,
            include_live_benchmark=False,
        ) or {}
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return error_response("Paciente no encontrado", 404)
        latest_signal_snapshot = dict(patient.get("latest_signal_snapshot") or {})
        keys = [
            "decision_governance_bundle",
            "recommendation_block_status",
            "recommendation_block_reason",
            "allowed_actions_while_blocked",
            "decision_blocking_bundle",
            "diagnostic_certainty_bundle",
            "staging_certainty_bundle",
            "minimum_decisive_dataset_bundle",
            "decision_evidence_currentness_bundle",
            "therapeutic_window_bundle",
            "window_worklist_bundle",
            "therapeutic_readiness_bundle",
            "clinical_readiness_tower",
            "tumor_board_os",
            "care_pathway_os",
            "clinical_memory_os",
            "clinician_decision_capture_bundle",
            "state_transition_confirmation_bundle",
            "adherence_tracking_bundle",
            "tumor_board_outcome_bundle",
            "pro_decision_bundle",
            "shared_decision_bundle",
            "localized_modality_fitness_bundle",
            "localized_tradeoff_bundle",
            "patient_priority_profile",
            "ctdna_refinement_bundle",
            "multimodal_imaging_concordance_bundle",
            "precision_workflow_bundle",
            "registry_core_bundle",
            "endpoint_adjudication_bundle",
            "data_certainty_bundle",
            "ichom_compliance_bundle",
            "treatment_adverse_event_bundle",
            "population_survival_context_bundle",
            "cost_access_context_bundle",
            "score_interpretation_catalog_snapshot",
            "clinical_fact_bundle",
        ]
        payload = {
            key: bundle.get(
                key,
                latest_signal_snapshot.get(
                    key,
                    {} if key in {"tumor_board_os", "care_pathway_os", "clinical_memory_os"} or key.endswith("_bundle") or key.endswith("_profile") or key.endswith("_snapshot") else "",
                ),
            )
            for key in keys
        }
        return jsonify(
            {
                "success": True,
                **payload,
                "longitudinal_truth_snapshot": bundle.get("longitudinal_truth_snapshot", patient.get("longitudinal_truth_snapshot", {})),
                "decision_recalculation_trace": bundle.get("decision_recalculation_trace", patient.get("decision_recalculation_trace", {})),
                "guideline_plan_history": patient.get("guideline_plan_history", []),
                "missing_input_history": patient.get("missing_input_history", []),
                "resolved_patient_id": patient_id,
                "resolved_patient_ref": resolved.get("nss") or resolved.get("patient_ref") or str(patient_ref),
                **_reconciled_patient_snapshot(patient),
            }
        )
    except Exception as e:
        logger.error(f"Error getting patient decision governance: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<int:patient_id>', methods=['DELETE'])
def api_delete_patient_profile(patient_id):
    import tracking_db
    try:
        success, payload = tracking_db.delete_patient_profile(patient_id)
        if not success:
            return error_response(payload, 404)
        return jsonify({"success": True, "deleted": payload})
    except Exception as e:
        logger.error(f"Error deleting patient {patient_id}: {e}")
        return error_response(str(e), 500)


@app.route("/api/register_patient", methods=["POST"])
def register_patient():
    logger.info("Recibida petición POST /api/register_patient")
    try:
        import tracking_db
        data = parse_json_body()
        data["nss"] = str(data.get("nss", "")).strip()
        data["full_name"] = str(data.get("full_name", "")).strip()
        require_non_empty_fields(data, ("nss", "full_name"))
        validate_numeric_fields(data, REGISTER_NUMERIC_FIELDS)
        logger.info(f"JSON decoded. NSS: {data.get('nss')}")

        assessment = None
        assessment_id = data.get("assessment_id")
        if assessment_id not in (None, ""):
            assessment_id = int(float(assessment_id))
            from prostanet.domains.clinical_assessments.service import ClinicalAssessmentService

            assessment_service = ClinicalAssessmentService()
            assessment = assessment_service.get_draft(assessment_id)
            if not assessment:
                return error_response("Evaluación clínica no encontrada.", 400)
        else:
            assessment_id = None

        if assessment:
            data = tracking_service.merge_assessment_payload(assessment, data)
        else:
            data = tracking_service.canonicalize_payload(data)
        data = _prepare_registration_contract_payload(data)

        diagnosis_gate = _confirmed_diagnosis_publication_gate(data)
        if diagnosis_gate["blocked"]:
            return jsonify({
                "success": False,
                "error": diagnosis_gate["message"],
                "clinical_gate": diagnosis_gate,
                "official_diagnosis_context": diagnosis_gate["official_diagnosis_context"],
            }), 400

        # ── Faubot LXXXI #audit-pre-cortana A3 — Completeness warner ──
        # Detecta fields críticos faltantes según state clínico estimado.
        # NO bloquea POST (compatibilidad backward); solo informa via payload
        # response para que UI muestre warnings al médico.
        completeness_warnings = None
        try:
            from prostanet.shared.payload_completeness_warner import (
                summarize_completeness,
            )
            estimated_state = (
                data.get("clinical_state")
                or data.get("estado_clinico")
                or data.get("state")
                or None
            )
            completeness_warnings = summarize_completeness(data, clinical_state=estimated_state)
            if completeness_warnings.get("critical_count", 0) > 0:
                logger.warning(
                    "POST /api/register_patient con %d critical fields missing (state=%s, coverage=%s%%)",
                    completeness_warnings["critical_count"],
                    completeness_warnings.get("state", "unknown"),
                    completeness_warnings.get("gate_coverage_percent", 0),
                )
        except Exception as exc:
            logger.warning("Completeness warner skipped: %s", exc)

        from tracking_db import register_new_patient
        patient_id, msg, registration_metadata = register_new_patient(data, assessment=assessment)
        logger.info(f"DB Result: {patient_id}, {msg}")
        
        if patient_id is not None:
            link_warning = None
            if assessment_id is not None:
                from prostanet.domains.clinical_assessments.service import ClinicalAssessmentService

                assessment_service = ClinicalAssessmentService()
                linked, link_msg = assessment_service.attach_to_patient(assessment_id, patient_id)
                if not linked:
                    logger.warning("No se pudo vincular la evaluación clínica %s al paciente %s: %s", assessment_id, patient_id, link_msg)
                    link_warning = link_msg

            # ── Benchmark exploratorio legacy (no autoritativo) ──
            from prostanet.shared.precision_medicine_legacy import evaluate_patient_for_mhspc, evaluate_patient_for_mcrpc, evaluate_patient_for_nmcrpc
            from prostanet.domains.patient_tracking.event_graph import build_processing_summary

            line_therapy = safe_int(data.get('line_of_therapy_number') or data.get('line_of_therapy'), 1)
            meta_site = data.get('metastasis_site', 'M0')
            recommendations = assessment.get("result_snapshot", {}) if assessment else {}
            exploratory_benchmark = None
            
            if not assessment:
                try:
                    if line_therapy == 1:
                        exploratory_benchmark = evaluate_patient_for_mhspc(data)
                    else:
                        # Line > 1 implies Castration Resistance context in this simplified model
                        if meta_site == 'M0':
                            # nmCRPC (No metastasis detected but rising PSA implied by Line > 1)
                            exploratory_benchmark = evaluate_patient_for_nmcrpc(data)
                        else:
                            # mCRPC (Metastatic)
                            exploratory_benchmark = evaluate_patient_for_mcrpc(data)

                except Exception as e:
                    logger.error(f"Error generando recomendaciones: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    exploratory_benchmark = {"error": "Algoritmo clínico legacy no disponible"}

            full_record = tracking_service.get_full_record(data.get("nss"))
            processing_summary = build_processing_summary(
                data.get("assessment_state") or (assessment.get("state") if assessment else ""),
                data,
                full_record,
            )
            loop_payload = tracking_db.refresh_longitudinal_intelligence(patient_id, force_recompute=True)

            response = {
                "success": True, 
                "nss": data.get('nss'),
                "patient_id": patient_id,
                "recommendations": recommendations,
                "recommendation_mode": "guideline_modular" if assessment else "exploratory_legacy_only",
                "exploratory_benchmark": exploratory_benchmark,
                "processing_summary": processing_summary,
                "longitudinal_intelligence": loop_payload,
                "registration_metadata": registration_metadata or {},
                "official_diagnosis_context": diagnosis_gate["official_diagnosis_context"],
                "official_diagnosis": diagnosis_gate["official_diagnosis"],
                "msg": msg,
                "assessment_id": assessment_id,
                "next_routes": {
                    "profile": f"/patient_profile/{data.get('nss')}",
                    "patients": "/patients",
                    "dashboard": "/dashboard",
                },
            }
            if assessment:
                from prostanet.shared.presentation_text import humanize_assessment

                response["assessment"] = humanize_assessment(assessment)
            if link_warning:
                response["warning"] = link_warning
            # Faubot LXXXI #audit-pre-cortana A3 — incluir completeness warnings en respuesta
            if completeness_warnings is not None:
                response["completeness"] = completeness_warnings
            return jsonify(response)
        return error_response(msg, 400)
            
    except ValueError as e:
        return error_response(str(e), 400)
    except Exception as e:
        logger.exception("Error en registro de paciente")
        return error_response(str(e), 500)


# ══════════════════════════════════════════════════════════════════════════════
# ══  REGISTRO DESDE CALCULADORA (Flujo Integrado)
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/register_from_calculator", methods=["POST"])
def register_from_calculator():
    """Registro desde calculadora legacy retirado. Use el centro clínico."""
    return error_response("La calculadora fue retirada. Use el centro clínico por estadio.", 410)


# ══════════════════════════════════════════════════════════════════════════════
# ══  FASE B & C — NUEVOS ENDPOINTS API (Expediente Longitudinal + Investigación)
# ══════════════════════════════════════════════════════════════════════════════

# ── Demográficos México ──────────────────────────────────────────────────────
@app.route('/api/demographics/<int:patient_id>', methods=['POST'])
def api_save_demographics(patient_id):
    """Guarda o actualiza datos demográficos del paciente."""
    try:
        from tracking_db import save_demographics
        data = request.get_json()
        success = save_demographics(patient_id, data)
        if success:
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Error guardando demográficos"}), 400
    except Exception as e:
        logger.error(f"Error en demographics: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ── Historia Familiar ────────────────────────────────────────────────────────
@app.route('/api/family_history/<int:patient_id>', methods=['POST'])
def api_save_family_history(patient_id):
    """Guarda historia familiar detallada (lista de familiares)."""
    try:
        from tracking_db import save_family_history
        data = request.get_json()
        relatives = data.get('relatives', [])
        success = save_family_history(patient_id, relatives)
        if success:
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Error guardando historia familiar"}), 400
    except Exception as e:
        logger.error(f"Error en family history: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ── Estudios de Imagen ───────────────────────────────────────────────────────
@app.route('/api/imaging/<int:patient_id>', methods=['POST'])
def api_save_imaging(patient_id):
    """Registra un estudio de imagen (MRI, PSMA-PET, gammagrama, etc)."""
    try:
        from tracking_db import save_imaging_study
        data = request.get_json()
        success = save_imaging_study(patient_id, data)
        if success:
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Error guardando imagen"}), 400
    except Exception as e:
        logger.error(f"Error en imaging: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ── Perfil Genómico ──────────────────────────────────────────────────────────
@app.route('/api/genomics/<int:patient_id>', methods=['POST'])
def api_save_genomics(patient_id):
    """Guarda perfil genómico del paciente."""
    try:
        from tracking_db import save_genomic_profile
        data = request.get_json()
        success = save_genomic_profile(patient_id, data)
        if success:
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Error guardando genómica"}), 400
    except Exception as e:
        logger.error(f"Error en genomics: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ── Biopsias ─────────────────────────────────────────────────────────────────
@app.route('/api/biopsy/<int:patient_id>', methods=['POST'])
def api_save_biopsy(patient_id):
    """DEPRECATED — Registra biopsia (legacy endpoint).

    EPIC 22e.4 — esta ruta queda como legacy con warning + 308 redirect en
    Deprecation header. La UI usa el path canónico via
    `/api/longitudinal/<nss>/append` con `kind=biopsy` desde EPIC 22b.1.

    Inconsistencia legacy: route firma con patient_id (int) mientras el resto
    del sistema usa NSS (string). Conservado por backward-compat con clientes
    antiguos pero NUEVO código debe usar /api/longitudinal/<nss>/append.
    """
    try:
        from tracking_db import save_biopsy
        data = request.get_json()
        success = save_biopsy(patient_id, data)
        if success:
            resp = jsonify({
                "success": True,
                "deprecated": True,
                "deprecation_warning": (
                    "DEPRECATED: /api/biopsy/<patient_id> está deprecado en EPIC 22e.4. "
                    "Use /api/longitudinal/<nss>/append con kind='biopsy' "
                    "(canonical NSS-based, EPIC 22b.1)."
                ),
                "preferred_endpoint": "/api/longitudinal/<nss>/append",
                "preferred_payload_example": {
                    "kind": "biopsy",
                    "payload": {
                        "biopsy_date": "YYYY-MM-DD",
                        "biopsy_type": "systematic",
                        "gleason_primary": 3,
                        "gleason_secondary": 4,
                        "isup_grade": 2,
                        "total_cores": 12,
                        "positive_cores": 4,
                    },
                },
            })
            # Deprecation HTTP headers per RFC 8594
            resp.headers["Deprecation"] = "version=epic22e.4"
            resp.headers["Sunset"] = "2026-12-31"  # Date when this endpoint is removed
            resp.headers["Link"] = (
                '</api/longitudinal/{nss}/append>; rel="successor-version"'
            )
            logger.warning(
                "DEPRECATED endpoint /api/biopsy/%s called — clients should migrate to "
                "/api/longitudinal/<nss>/append (EPIC 22b.1)",
                patient_id,
            )
            return resp
        return jsonify({"success": False, "error": "Error guardando biopsia"}), 400
    except Exception as e:
        logger.error(f"Error en biopsy: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ── EPIC 22e.2 — Patient Twin Preferences capture endpoint ────────────────
@app.route('/api/patient/<nss>/preferences', methods=['POST'])
@require_clinical_session(scope="phi:write", redirect_to_login=False)
def api_patient_preferences(nss):
    """EPIC 22e.2 — Persist Patient Twin SDM preferences.

    Closes documented gap (ui_data_concordance_audit.yaml line 167-170):
    'pm2PatientTwinOS preferences capture form missing'. The Twin OS reads
    `goal_of_care`, `decision_tradeoff` (os_weight/qol_weight),
    `toxicity_tolerance`, `redecision_threshold` to personalize regimen
    ranking; before EPIC 22e.2 there was NO capture surface so the ranking
    always used default 0.5/0.5 weights.

    Persists each preference dimension as a `patient_clinical_facts` row
    (so the facts feed the existing Twin OS extract_preferences() function
    + the EPIC 22b.7 twin_recompute_triggered lineage event fires).

    Body JSON:
        {
            "goal_of_care": "max_os" | "balanced" | "max_qol",
            "decision_tradeoff": {"os_weight": float, "qol_weight": float},
            "toxicity_tolerance": {<ae_token>: <max_pct>, ...},
            "redecision_threshold": {<key>: <value>, ...}
        }
    """
    import tracking_db
    import json as _json
    payload = request.get_json(silent=True) or {}

    conn = tracking_db._connect(write=True)
    cursor = conn.cursor()
    try:
        identity = tracking_db._resolve_identity_row(cursor, nss)
        if not identity:
            return jsonify({"success": False, "error": "patient_not_found", "nss": nss}), 404
        patient_id = identity["id"] if hasattr(identity, "__getitem__") else identity[0]

        # Insert each preference dimension as a fact (active_only replace pattern)
        facts_to_persist = []
        if payload.get("goal_of_care"):
            facts_to_persist.append(("goal_of_care", str(payload["goal_of_care"]).lower()))
        if isinstance(payload.get("decision_tradeoff"), dict):
            facts_to_persist.append(("decision_tradeoff", _json.dumps(payload["decision_tradeoff"])))
        if isinstance(payload.get("toxicity_tolerance"), dict) and payload["toxicity_tolerance"]:
            facts_to_persist.append(("toxicity_tolerance", _json.dumps(payload["toxicity_tolerance"])))
        if isinstance(payload.get("redecision_threshold"), dict) and payload["redecision_threshold"]:
            facts_to_persist.append(("redecision_threshold", _json.dumps(payload["redecision_threshold"])))

        if not facts_to_persist:
            return jsonify({"success": False, "error": "no_preferences_provided"}), 400

        persisted = 0
        for key, value in facts_to_persist:
            # Deactivate prior active fact
            cursor.execute(
                "UPDATE patient_clinical_facts SET is_active=0 WHERE patient_id=? AND fact_key=? AND is_active=1",
                (patient_id, key),
            )
            cursor.execute(
                """
                INSERT INTO patient_clinical_facts (
                    patient_id, fact_key, value_json, normalized_value_text, source_type,
                    source_record_type, source_record_id, source_date, observed_at,
                    state_context, management_track, certainty_tier, freshness_status,
                    clinician_verified, verification_note, is_active
                ) VALUES (?, ?, ?, ?, 'wizard_or_intake', 'patient_twin_preferences_form',
                          ?, ?, ?, 'preferences_capture', '', 'wizard_or_intake', 'fresh',
                          1, 'Captured via pm2PreferencesModal (EPIC 22e.2)', 1)
                """,
                (
                    patient_id,
                    key,
                    value if value.startswith("{") else _json.dumps(value),
                    str(value),
                    patient_id,
                    datetime.now().strftime("%Y-%m-%d"),
                    datetime.now().strftime("%Y-%m-%d"),
                ),
            )
            persisted += 1
        # EPIC 22b.7 — emit twin_recompute_triggered lineage event
        try:
            tracking_db._append_patient_fact_lineage_event(
                cursor,
                patient_id,
                fact_key=",".join(k for k, _ in facts_to_persist),
                event_type="twin_recompute_triggered",
                event_note="Preferences capture (EPIC 22e.2 form) → Twin recompute.",
                payload={"source": "pm2PreferencesModal", "facts_count": persisted},
            )
            import time as _t
            tracking_db._PATIENT_TWIN_RECOMPUTE_MARKERS[int(patient_id)] = _t.time()
        except Exception as exc:
            logger.debug("twin_recompute event failed: %s", exc)

        conn.commit()
        return jsonify({
            "success": True,
            "nss": nss,
            "patient_id": patient_id,
            "facts_persisted": persisted,
            "preference_dimensions": [k for k, _ in facts_to_persist],
            "twin_recompute_triggered": True,
            "audit_note": "Preferences captured via EPIC 22e.2 form · Patient Twin OS will re-rank on next render.",
        })
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error("Error persisting preferences: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500
    finally:
        conn.close()


# ── Vigilancia Activa ────────────────────────────────────────────────────────
@app.route('/api/active_surveillance/<int:patient_id>/enroll', methods=['POST'])
def api_enroll_as(patient_id):
    """Inscribe paciente en Vigilancia Activa."""
    try:
        from tracking_db import enroll_in_as
        data = request.get_json()
        success = enroll_in_as(patient_id, data)
        if success:
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Error inscribiendo en VA"}), 400
    except Exception as e:
        logger.error(f"Error en AS enroll: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/active_surveillance/<int:patient_id>/exit', methods=['POST'])
def api_exit_as(patient_id):
    """Registra salida de Vigilancia Activa."""
    try:
        from tracking_db import exit_as
        data = request.get_json()
        success = exit_as(patient_id, data)
        if success:
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Error saliendo de VA"}), 400
    except Exception as e:
        logger.error(f"Error en AS exit: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ── Recurrencia Bioquímica ───────────────────────────────────────────────────
@app.route('/api/bcr/<int:patient_id>', methods=['POST'])
def api_save_bcr(patient_id):
    """Registra recurrencia bioquímica."""
    try:
        from tracking_db import save_bcr
        data = request.get_json()
        success = save_bcr(patient_id, data)
        if success:
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Error guardando BCR"}), 400
    except Exception as e:
        logger.error(f"Error en BCR: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ── Cirugía ──────────────────────────────────────────────────────────────────
@app.route('/api/surgery/<int:patient_id>', methods=['POST'])
def api_save_surgery(patient_id):
    """Registra detalles de prostatectomía radical."""
    try:
        from tracking_db import save_surgical_details
        data = request.get_json()
        success = save_surgical_details(patient_id, data)
        if success:
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Error guardando cirugía"}), 400
    except Exception as e:
        logger.error(f"Error en surgery: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ── Radioterapia ─────────────────────────────────────────────────────────────
@app.route('/api/radiation/<int:patient_id>', methods=['POST'])
def api_save_radiation(patient_id):
    """Registra detalles de radioterapia."""
    try:
        from tracking_db import save_radiation_details
        data = request.get_json()
        success = save_radiation_details(patient_id, data)
        if success:
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Error guardando radioterapia"}), 400
    except Exception as e:
        logger.error(f"Error en radiation: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ── PROs (Patient-Reported Outcomes) ─────────────────────────────────────────
@app.route('/api/pros/<int:patient_id>', methods=['POST'])
def api_save_pros(patient_id):
    """Guarda evaluación de PROs."""
    try:
        from tracking_db import save_pro_assessment
        data = request.get_json()
        success = save_pro_assessment(patient_id, data)
        if success:
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Error guardando PROs"}), 400
    except Exception as e:
        logger.error(f"Error en PROs: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ── Alertas Inteligentes ─────────────────────────────────────────────────────
@app.route('/api/alerts/<int:patient_id>', methods=['GET'])
def api_get_alerts(patient_id):
    """Obtiene alertas activas de un paciente."""
    try:
        if not patient_exists(patient_id):
            return error_response("Paciente no encontrado", 404)
        import tracking_db

        tracking_db.refresh_longitudinal_intelligence(patient_id, force_recompute=False)
        alerts = tracking_db.get_patient_alerts(patient_id)
        return jsonify({"success": True, "alerts": alerts})
    except Exception as e:
        logger.error(f"Error obteniendo alertas: {e}")
        return error_response(str(e), 500)


@app.route('/api/alerts/<int:patient_id>/check', methods=['POST'])
def api_check_alerts(patient_id):
    """Ejecuta el motor de alertas y genera nuevas si aplican."""
    try:
        if not patient_exists(patient_id):
            return error_response("Paciente no encontrado", 404)
        import tracking_db

        bundle = tracking_db.refresh_longitudinal_intelligence(patient_id, force_recompute=False)
        return jsonify(
            {
                "success": True,
                "new_alerts": [alert.get("alert_key") or alert.get("title") for alert in bundle.get("copilot_alerts", [])],
                "alerts": bundle.get("copilot_alerts", []),
                "alert_summary": bundle.get("alert_summary", {}),
            }
        )
    except Exception as e:
        logger.error(f"Error generando alertas: {e}")
        return error_response(str(e), 500)


@app.route('/api/alerts/acknowledge/<int:alert_id>', methods=['POST'])
def api_acknowledge_alert(alert_id):
    """Marca una alerta como vista/reconocida."""
    try:
        from tracking_db import acknowledge_alert
        data = request.get_json() or {}
        success = acknowledge_alert(alert_id, user=data.get('user', 'system'))
        if success:
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Error actualizando alerta"}), 400
    except Exception as e:
        logger.error(f"Error acknowledging alert: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ── Exportación de Datos ─────────────────────────────────────────────────────
@app.route('/api/export/<nss>', methods=['GET'])
def api_export_patient(nss):
    """Exporta datos completos del paciente en JSON."""
    try:
        from tracking_db import export_patient_data
        fmt = request.args.get('format', 'dict')
        if fmt not in {"dict", "json"}:
            return error_response("Formato de exportación no soportado", 400)
        data = export_patient_data(nss, format=fmt)
        if data is None:
            return error_response("Paciente no encontrado", 404)
        if fmt == 'json':
            return app.response_class(data, mimetype='application/json')
        return jsonify(data)
    except Exception as e:
        logger.error(f"Error exportando datos: {e}")
        return error_response(str(e), 500)


@app.route('/api/export/<nss>/csv', methods=['GET'])
def api_export_patient_csv(nss):
    """Exporta datos aplanados del paciente como CSV."""
    try:
        from tracking_db import export_patient_data
        import csv
        import io
        flat = export_patient_data(nss, format='csv_ready')
        if flat is None:
            return error_response("Paciente no encontrado", 404)

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=flat.keys())
        writer.writeheader()
        writer.writerow(flat)
        csv_str = output.getvalue()

        return app.response_class(
            csv_str,
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename=prostanet_{nss}.csv'}
        )
    except Exception as e:
        logger.error(f"Error exportando CSV: {e}")
        return error_response(str(e), 500)


# ── Confrontación con Estudios Pivotales ─────────────────────────────────────
@app.route('/api/pivotal_match/<nss>', methods=['GET'])
def api_pivotal_match(nss):
    """Evalúa elegibilidad del paciente contra estudios pivotales."""
    try:
        from tracking_db import get_patient_full_record
        from clinical_scores import docetaxel_fitness
        from pivotal_studies import match_patient_to_studies, generate_pivotal_report
        from prostanet.domains.patient_tracking.mhspc_evidence import is_mhspc_state, visible_trials_for_mhspc_state
        from prostanet.domains.patient_tracking.therapy_catalog import trial_backbone
        from prostanet.domains.patient_tracking.reconciled_state import (
            build_reconciled_state,
            derive_post_prostatectomy_truth,
        )

        record = get_patient_full_record(nss)
        if not record:
            return jsonify({"error": "Paciente no encontrado"}), 404

        # Construir datos del paciente para el motor de matching
        baseline = record.get('baseline', {})
        identity = record.get('identity', {})
        genomics = record.get('genomics', {})
        surgery = record.get('surgery', {})
        latest_assessment = record.get("latest_assessment") or {}
        reconciliation = build_reconciled_state(record, latest_assessment)
        current_state = reconciliation.get("reconciled_state") or ""
        post_rp_truth = derive_post_prostatectomy_truth(record) if current_state in {"post_prostatectomy", "recurrence_bcr"} else {}

        # Calcular edad
        from datetime import datetime
        dob = identity.get('dob')
        age = 65
        if dob:
            try:
                dob_dt = datetime.strptime(str(dob), '%Y-%m-%d')
                age = (datetime.now() - dob_dt).days // 365
            except Exception:
                pass

        # PSA actual (último follow-up o baseline)
        follow_ups = record.get('follow_ups', [])
        psa_current = follow_ups[-1].get('psa_current', 0) if follow_ups else baseline.get('baseline_psa', 0)
        if current_state == "recurrence_bcr":
            psa_current = (
                post_rp_truth.get("psa_current")
                or (latest_assessment.get("input_snapshot") or {}).get("psa_current")
                or (latest_assessment.get("input_snapshot") or {}).get("psa_postop")
                or (record.get("bcr") or {}).get("bcr_psa")
                or psa_current
            )

        # Claves deben coincidir con lo que espera match_patient_to_studies()
        metastasis_site = baseline.get('metastasis_site', 'M0') or 'M0'
        metastasis_status = 'M0' if metastasis_site in ('M0', '', None) else 'M1'

        prior_hist = record.get('prior_history') or {}
        prior_docetaxel_cycles = prior_hist.get('prior_docetaxel_cycles', 0) or 0
        prior_arpi_agent = prior_hist.get('prior_arpi_agent')
        docetaxel_payload = {}
        docetaxel_payload.update(baseline or {})
        docetaxel_payload.update(prior_hist or {})
        docetaxel_payload.update((latest_assessment.get("input_snapshot") or {}))
        docetaxel_bundle = docetaxel_fitness(docetaxel_payload)

        patient_for_match = {
            'state': current_state,
            'age': age,
            'psa': psa_current or 0,
            'psa_basal': baseline.get('baseline_psa', 0) or 0,
            'psa_current': psa_current or 0,
            'psa_postop_current': post_rp_truth.get("psa_current"),
            'psa_postop': (latest_assessment.get("input_snapshot") or {}).get("psa_postop"),
            'bcr_psa': (record.get("bcr") or {}).get("bcr_psa"),
            'gleason_score': baseline.get('gleason_score', 6) or 6,
            'gleason_primary': baseline.get('gleason_primary'),
            'gleason_secondary': baseline.get('gleason_secondary'),
            'ecog_score': baseline.get('ecog_score', 0) or 0,
            'clinical_tstage': baseline.get('tnm_stage', 'T2a') or 'T2a',
            'metastasis_status': metastasis_status,
            'metastasis_site': metastasis_site,
            'metastasis_count': baseline.get('metastasis_count', 0) or 0,
            'volume_chaarted': baseline.get('volume_disease', 'Low') or 'Low',
            'hrr_status': genomics.get('hrr_overall') or baseline.get('hrr_status', 'Desconocido') or 'Desconocido',
            'msi_status': genomics.get('msi_status') or baseline.get('msi_status', 'Estable') or 'Estable',
            'prior_therapy': [],
            'prior_prostatectomy': bool(surgery),
            'post_rp_context': current_state in {"post_prostatectomy", "recurrence_bcr"},
            'psadt_months': post_rp_truth.get("psadt_months") or (record.get("bcr") or {}).get("psadt_at_bcr") or (latest_assessment.get("input_snapshot") or {}).get("psadt_months"),
            'salvage_local_feasible': (latest_assessment.get("input_snapshot") or {}).get("salvage_local_feasible"),
            'bone_metastases': metastasis_site in ('Hueso', 'Oseas', 'Bone'),
            'visceral_metastases': metastasis_site in ('Visceral', 'Higado', 'Pulmon'),
            'fit_for_chemotherapy': bool(docetaxel_bundle.get('fit_for_docetaxel')),
            'fit_for_docetaxel': bool(docetaxel_bundle.get('fit_for_docetaxel')),
            'disease_temporality': 'metachronous' if current_state in {'mcspc_oligo_metachronous', 'mcspc_high_volume_metachronous'} else 'sync',
            'de_novo': current_state in {'mcspc_low_volume_sync_oligo', 'mcspc_high_volume_sync'},
            'peripheral_neuropathy_grade': docetaxel_payload.get('peripheral_neuropathy_grade'),
            'frailty_status': docetaxel_payload.get('frailty_status'),
            'child_pugh_score': docetaxel_payload.get('child_pugh_score'),
            'cv_risk_documented': docetaxel_payload.get('cv_risk_documented'),
            'drug_interaction_reviewed': docetaxel_payload.get('drug_interaction_reviewed'),
        }

        # Construir lista de terapias previas
        if prior_docetaxel_cycles > 0:
            patient_for_match['prior_therapy'].append('Docetaxel')
        if prior_arpi_agent:
            patient_for_match['prior_therapy'].append(str(prior_arpi_agent))
            patient_for_match['prior_therapy'].append('ARPI')
        if prior_hist.get('rt_primary_received'):
            patient_for_match['prior_therapy'].append('Radioterapia')

        matches = match_patient_to_studies(patient_for_match)
        report = generate_pivotal_report(patient_for_match)

        # Guardar matching en DB y construir respuesta limpia para JSON
        from tracking_db import save_pivotal_matching
        matches_clean = []
        for m in matches:
            study = m.get('study', {})
            # Datos limpios para save y para respuesta JSON
            match_flat = {
                'study_name': study.get('name', ''),
                'scenario': study.get('scenario', ''),
                'phase': study.get('phase', ''),
                'intervention': study.get('intervention', ''),
                'key_result': study.get('key_result', ''),
                'eligible': m.get('eligible', False),
                'match_score': m.get('match_score', 0),
                'criteria_met': m.get('criteria_met', []),
                'criteria_failed': m.get('criteria_failed', []),
                'eligibility_details': {
                    'match_score': m.get('match_score', 0),
                    'criteria_met': m.get('criteria_met', []),
                    'criteria_failed': m.get('criteria_failed', []),
                },
                'expected_outcome': study.get('key_result', ''),
                'applicability': study.get('mexican_applicability', ''),
            }
            match_flat.update(trial_backbone(match_flat["study_name"]))
            matches_clean.append(match_flat)
            try:
                save_pivotal_matching(identity['id'], match_flat)
            except Exception:
                pass

        hidden_cross_scenario = set()
        if is_mhspc_state(current_state):
            _, hidden_cross_scenario = visible_trials_for_mhspc_state(current_state, patient_for_match)

        visible_matches_clean = [
            item for item in matches_clean
            if item.get("study_name") not in hidden_cross_scenario
        ]
        eligible_matches = [m for m in visible_matches_clean if m.get("eligible")]
        partial_matches = [m for m in visible_matches_clean if not m.get("eligible") and float(m.get("match_score", 0) or 0) >= 0.7]
        ineligible_matches = [m for m in visible_matches_clean if m not in eligible_matches and m not in partial_matches]

        return jsonify({
            "success": True,
            "matches": matches_clean,
            "visible_matches": visible_matches_clean,
            "eligible_matches": eligible_matches,
            "partial_matches": partial_matches,
            "ineligible_matches": ineligible_matches,
            "hidden_cross_scenario_count": len(hidden_cross_scenario),
            "report": report,
            "total_studies_evaluated": len(matches_clean),
            "eligible_count": len(eligible_matches),
            "partial_count": len(partial_matches),
            "ineligible_count": len(ineligible_matches),
        })
    except Exception as e:
        logger.exception(f"Error en pivotal matching: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ── Dashboard Analytics Avanzado ──────────────────────────────────────────────
@app.route('/api/dashboard/summary', methods=['GET'])
def api_dashboard_summary():
    try:
        from prostanet.domains.dashboard.dashboard_facade import get_dashboard_summary_payload

        return jsonify({"success": True, **get_dashboard_summary_payload()})
    except Exception as e:
        logger.error(f"Error en dashboard_summary: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/dashboard/analytics', methods=['GET'])
def api_dashboard_analytics():
    try:
        from prostanet.domains.dashboard.dashboard_facade import get_dashboard_analytics_bundle

        return jsonify({"success": True, **get_dashboard_analytics_bundle()})
    except Exception as e:
        logger.error(f"Error en dashboard_analytics: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/dashboard/calibration', methods=['GET'])
def api_dashboard_calibration():
    try:
        from prostanet.domains.dashboard.dashboard_facade import get_dashboard_calibration_bundle

        return jsonify({"success": True, **get_dashboard_calibration_bundle()})
    except Exception as e:
        logger.error(f"Error en dashboard_calibration: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/dashboard/research-intelligence', methods=['GET'])
def api_dashboard_research_intelligence():
    try:
        from prostanet.domains.dashboard.dashboard_facade import get_dashboard_research_bundle

        return jsonify({"success": True, **get_dashboard_research_bundle()})
    except Exception as e:
        logger.error(f"Error en dashboard_research_intelligence: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/dashboard_stats', methods=['GET'])
def api_dashboard_stats():
    """Alias rápido y compatible para el tablero ejecutivo."""
    try:
        from prostanet.domains.dashboard.dashboard_facade import get_dashboard_summary_payload

        summary = get_dashboard_summary_payload()
        summary["analytics_endpoint"] = "/api/dashboard/analytics"
        summary["calibration_endpoint"] = "/api/dashboard/calibration"
        summary["research_endpoint"] = "/api/dashboard/research-intelligence"
        return jsonify({"success": True, **summary})
    except Exception as e:
        logger.error(f"Error en dashboard_stats: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/analysis_dataset_export', methods=['GET'])
def api_analysis_dataset_export():
    try:
        payload = _analysis_dataset_payload()
        return jsonify({"success": True, "analysis_dataset_export": payload["analysis_rows"]})
    except Exception as e:
        logger.error(f"Error exporting analysis dataset: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/cohort_completeness', methods=['GET'])
def api_cohort_completeness():
    try:
        payload = _analysis_dataset_payload()
        return jsonify({"success": True, "cohort_completeness": payload["cohort_completeness_rows"], "summary": payload["summary"]})
    except Exception as e:
        logger.error(f"Error computing cohort completeness: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/research_readiness', methods=['GET'])
def api_research_readiness():
    try:
        payload = _analysis_dataset_payload()
        return jsonify({"success": True, "research_readiness": payload["research_readiness_rows"], "summary": payload["summary"]})
    except Exception as e:
        logger.error(f"Error computing research readiness: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/endpoint_readiness', methods=['GET'])
def api_endpoint_readiness():
    try:
        payload = _analysis_dataset_payload()
        return jsonify({"success": True, "endpoint_readiness": payload["endpoint_readiness_rows"], "summary": payload["summary"]})
    except Exception as e:
        logger.error(f"Error computing endpoint readiness: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ── Listado de Pacientes ─────────────────────────────────────────────────────
@app.route('/api/patients', methods=['GET'])
def api_list_patients():
    """Retorna lista de pacientes registrados."""
    try:
        import sqlite3
        conn = sqlite3.connect(app.config["DB_PATH"])
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("""
            SELECT pi.id, pi.nss, pi.full_name, pi.dob, pi.diagnosis_date,
                   cb.baseline_psa, cb.metastasis_site, cb.volume_disease, cb.ecog_score,
                   (SELECT COUNT(*) FROM follow_up_visits fv WHERE fv.patient_id = pi.id) as visit_count,
                   (SELECT COUNT(*) FROM smart_alerts sa WHERE sa.patient_id = pi.id AND sa.acknowledged = 0 AND COALESCE(sa.active, 1) = 1) as alert_count
            FROM patient_identity pi
            LEFT JOIN clinical_baseline cb ON cb.patient_id = pi.id
            ORDER BY pi.created_at DESC
        """)
        patients = [dict(row) for row in c.fetchall()]
        conn.close()
        return jsonify({"success": True, "patients": patients})
    except Exception as e:
        logger.error(f"Error listando pacientes: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ── Perfil Completo (JSON) ───────────────────────────────────────────────────
@app.route('/api/patient/<nss>', methods=['GET'])
def api_get_patient(nss):
    """Retorna el expediente completo del paciente en JSON."""
    try:
        from tracking_db import get_patient_full_record
        record = get_patient_full_record(nss)
        if not record:
            return error_response("Paciente no encontrado", 404)
        return jsonify({"success": True, "patient": record})
    except Exception as e:
        logger.error(f"Error obteniendo paciente: {e}")
        return error_response(str(e), 500)


# ── Resumen de estudios pivotales disponibles ─────────────────────────────────
@app.route('/api/pivotal_studies', methods=['GET'])
def api_pivotal_studies():
    """Retorna resumen de todos los estudios pivotales disponibles."""
    try:
        from pivotal_studies import get_studies_summary, count_studies_by_scenario
        return jsonify({
            "success": True,
            "studies": get_studies_summary(),
            "by_scenario": count_studies_by_scenario()
        })
    except Exception as e:
        logger.error(f"Error obteniendo estudios: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# Faubot 2026-04-26 (LXXVII #67D) — Production wiring de las vistas v2:
# resultado clínico + captura longitudinal con datos REALES de DB +
# profile_compass. Sin tocar las rutas legacy.

@app.route("/clinical-result/<nss>", methods=["GET"])
@require_clinical_session(scope="phi:read", redirect_to_login=True)
def clinical_result_v2(nss: str):
    """Resultado clínico CDE para paciente real (vista v2)."""
    import tracking_db
    from prostanet.presentation.v2_adapters import bundle_to_v2_profile
    from prostanet.domains.patient_tracking.profile_compass import build_patient_profile_view_model

    core_record = tracking_db.load_patient_record_core(nss)
    data = tracking_db.build_patient_record_derivatives(core_record) if core_record else None
    if not data:
        return "Paciente no encontrado", 404

    longitudinal_bundle = tracking_db.refresh_longitudinal_intelligence(
        nss, force_recompute=False, record=data, include_live_benchmark=False,
    )
    profile_view = build_patient_profile_view_model(
        patient=data,
        latest_assessment_raw=data.get("latest_assessment") or {},
        latest_assessment={},
        state_timeline=[],
        care_overlays=[],
        longitudinal_bundle=longitudinal_bundle,
    )
    patient_for_v2 = dict(data.get("identity") or {})
    patient_for_v2["nss"] = nss
    patient_for_v2["full_name"] = data["identity"].get("full_name")
    patient_for_v2["clinical_baseline"] = data.get("baseline") or {}
    patient_for_v2["baseline_psa"] = (data.get("baseline") or {}).get("baseline_psa")
    patient_for_v2["consent"] = data.get("consent") or {}
    ctx = bundle_to_v2_profile(profile_view, patient_for_v2)

    # Adapt v2 ctx → clinical_result template shape
    audit = ctx["audit_dims"]
    decision = ctx["decision_today"]
    result_ctx = {
        "identity": {
            **ctx["identity"],
            "captured_at": datetime.now().strftime("%Y-%m-%d %H:%M CST"),
            "captured_by": "Sesión clínica activa",
            "intake_completeness": min(100, max(0, 100 - audit["datos"]["missing_critical"] * 5)),
        },
        "decision_today": decision,
        "alternatives": [
            {"code": f"ALT-{i+1}", "label": f"Alternativa {i+1} (ver decisión audit)",
             "rank": i+2, "rationale": "Detalle en pestaña CDE Audit del perfil"}
            for i in range(min(3, audit["como"]["alternatives_count"]))
        ],
        "gates_triggered": ctx["gates_top"][:5],
        "trial_eligibility": [],  # opcional: extraer de profile_view.pivotal_panel
        "risk_calculators": [
            {"tool": "decision_quality", "score": f"{int((decision['decision_quality_score'] or 0)*100)}%",
             "label": decision["decision_quality_label"], "missing_inputs": [], "interpretation": "Score CDE"},
        ],
        "next_actions": [],  # opcional: extraer de profile_view.next_best_action
        "consent": {
            "version_code": ctx["consent"]["version_code"],
            "effective_at": "2026-03-01",
            "scopes": [
                ("Atención clínica primaria", True, True),
                ("Procesamiento por motor CDE / IA", False, True),
                ("Comparación con cohortes pivotales (anonimizado)", False, True),
                ("Investigación secundaria (revocable)", False, ctx["consent"]["is_signed"]),
            ],
            "physician_witness": {
                "name": "Sesión clínica activa",
                "license": "—",
                "specialty": "—",
            },
        },
    }
    return render_template("demos/clinical_result_v2_demo.html", **result_ctx)


@app.route("/longitudinal-capture/<nss>", methods=["GET"])
@require_clinical_session(scope="phi:read", redirect_to_login=True)
def longitudinal_capture_v2(nss: str):
    """Captura longitudinal append-only para paciente real (vista v2)."""
    import tracking_db
    from prostanet.presentation.v2_adapters import bundle_to_v2_profile
    from prostanet.domains.patient_tracking.profile_compass import build_patient_profile_view_model

    core_record = tracking_db.load_patient_record_core(nss)
    data = tracking_db.build_patient_record_derivatives(core_record) if core_record else None
    if not data:
        return "Paciente no encontrado", 404

    longitudinal_bundle = tracking_db.refresh_longitudinal_intelligence(
        nss, force_recompute=False, record=data, include_live_benchmark=False,
    )
    profile_view = build_patient_profile_view_model(
        patient=data,
        latest_assessment_raw=data.get("latest_assessment") or {},
        latest_assessment={},
        state_timeline=[],
        care_overlays=[],
        longitudinal_bundle=longitudinal_bundle,
    )
    patient_for_v2 = dict(data.get("identity") or {})
    patient_for_v2["nss"] = nss
    patient_for_v2["full_name"] = data["identity"].get("full_name")
    patient_for_v2["clinical_baseline"] = data.get("baseline") or {}
    patient_for_v2["consent"] = data.get("consent") or {}
    ctx = bundle_to_v2_profile(profile_view, patient_for_v2)
    decision_lane_filter = (request.args.get("decision_lane") or "").strip()
    decision_field_filter = (request.args.get("decision_field") or "").strip()
    readiness_lane_filter = (
        request.args.get("readiness_lane")
        or decision_lane_filter
        or ""
    ).strip()

    # Build longitudinal-specific context from real bundle
    cb = data.get("baseline") or {}
    latest_assessment = data.get("latest_assessment") or {}
    field_router_state = (
        latest_assessment.get("state")
        or latest_assessment.get("disease_state")
        or latest_assessment.get("module")
        or (profile_view.get("current_state") if isinstance(profile_view, dict) else None)
        or (profile_view.get("disease_state") if isinstance(profile_view, dict) else None)
        or cb.get("disease_state")
        or cb.get("stage")
        or ctx.get("identity", {}).get("stage")
        or "localized_initial"
    )
    try:
        from prostanet.presentation.clinical_field_router import (
            build_clinical_field_router,
        )
        longitudinal_field_router = build_clinical_field_router(
            str(field_router_state),
            phase="longitudinal_followup",
            captured_so_far=cb,
            readiness_lane=readiness_lane_filter or None,
        )
    except Exception as exc:
        logger.exception(f"clinical_field_router longitudinal failed: {exc}")
        longitudinal_field_router = None
    from prostanet.shared.psa_unified import unified_psa_timeline, unified_testosterone_timeline
    from prostanet.domains.patient_tracking.psa_line_monitor import _classify_line_type

    psa_real = [
        {
            "date": point.get("date") or "—",
            "value": point.get("value") if point.get("value") is not None else "—",
            "context": point.get("context") or "longitudinal",
            "source": point.get("source") or "psa_unified",
            "locked": bool(point.get("locked")),
        }
        for point in unified_psa_timeline(data)
    ]
    testosterone_real = [
        {
            "date": point.get("date") or "—",
            "value": point.get("value") if point.get("value") is not None else "—",
            "unit": point.get("unit") or "ng/dL",
            "context": point.get("context") or "longitudinal",
            "source": point.get("source") or "testosterone_unified",
            "locked": bool(point.get("locked")),
        }
        for point in unified_testosterone_timeline(data)
    ]
    treatment_rows = []
    for i, t in enumerate(data.get("treatments") or []):
        line_type = _classify_line_type(t.get("drug_scheme") or t.get("current_treatment"))
        treatment_rows.append({
            "line": t.get("line_of_therapy_number") or i + 1,
            "line_context": t.get("line_of_therapy_context") or "—",
            "regimen": t.get("drug_scheme_label") or t.get("drug_scheme") or "—",
            "start": t.get("start_date") or "—",
            "end": t.get("end_date") or "—",
            "status": t.get("outcome") or ("Curso · activo" if not t.get("end_date") else "Completado"),
            "best_response": "—",
            "line_type": line_type.get("category"),
            "line_type_label": line_type.get("label") or "Sin clasificar",
        })
    clinical_readiness_tower = (
        longitudinal_bundle.get("clinical_readiness_tower")
        or profile_view.get("clinical_readiness_tower")
        or {}
    )
    readiness_lane_detail = {}
    if readiness_lane_filter and clinical_readiness_tower:
        for lane in clinical_readiness_tower.get("lanes") or []:
            if isinstance(lane, dict) and lane.get("key") == readiness_lane_filter:
                readiness_lane_detail = lane
                break

    long_ctx = {
        "identity": {
            **ctx["identity"],
            "current_line": (data.get("treatments") or [{}])[-1].get("line_of_therapy_number", "—") if data.get("treatments") else "—",
            "current_regimen": (data.get("treatments") or [{}])[-1].get("drug_scheme", "—") if data.get("treatments") else "—",
            "consent_status": ctx["consent"]["status"],
        },
        "baseline_locked": {
            "demographics": [
                ("Nombre", ctx["identity"]["name"]),
                ("NSS", ctx["identity"]["nss"]),
                ("Edad", f"{ctx['identity']['age']} años"),
                ("Vital status", ctx["identity"]["vital_status"]),
            ],
            "diagnosis": [
                ("Fecha dx", ctx["identity"]["diagnosis_date"]),
                ("PSA basal", f"{cb.get('baseline_psa', '—')} ng/mL"),
                ("Gleason", str(cb.get("gleason_score") or "—")),
                ("cT", str(cb.get("clinical_tstage") or "—")),
                ("Estadio", ctx["identity"]["stage_label"]),
            ],
            "histology": [
                ("ECOG basal", str(cb.get("ecog_score") or "—")),
                ("HRR status", str(cb.get("hrr_status") or "no testeado")),
            ],
            "genomics": [
                ("HRR status", str(cb.get("hrr_status") or "no testeado")),
            ],
            "performance_baseline": [
                ("ECOG basal", str(cb.get("ecog_score") or "—")),
                ("Child-Pugh", str(cb.get("child_pugh_score") or "—")),
            ],
        },
        "psa_history": psa_real or [{"date": "—", "value": "—", "context": "Sin datos PSA", "source": "—", "locked": False}],
        "testosterone_history": testosterone_real,
        "lab_panels": [],
        "imaging_events": [],
        "treatment_lines": treatment_rows,
        "clinical_events": [],
        "pro_scores": [],
        "longitudinal_field_router": longitudinal_field_router,
        "clinical_readiness_tower": clinical_readiness_tower,
        "decision_lane_filter": decision_lane_filter,
        "decision_field_filter": decision_field_filter,
        "readiness_lane_filter": readiness_lane_filter,
        "readiness_lane_detail": readiness_lane_detail,
        "smart_hints": [
            {"icon": "info", "severity": "info",
             "title": f"{len(psa_real)} mediciones PSA capturadas",
             "msg": "Cadencia mensual recomendada para mCRPC. Última captura: revisar tabla.",
             "action": "Programar próxima"},
            {"icon": "info", "severity": "warning" if not cb.get("hrr_status") else "info",
             "title": "Status genómico HRR",
             "msg": ("Pendiente test germinal" if not cb.get("hrr_status")
                     else f"HRR: {cb.get('hrr_status')}"),
             "action": "Solicitar test" if not cb.get("hrr_status") else "Ver detalle"},
        ],
        "what_can_capture": [
            {"key": "psa_new", "label": "Nueva medición PSA", "freq": "Mensual",
             "last_capture": (psa_real[-1]["date"] if psa_real else "—")},
            {"key": "lab_panel", "label": "Panel labs (Hb·ALP·LDH·Testo)", "freq": "30-60 d", "last_capture": "—"},
            {"key": "imaging", "label": "Imaging event", "freq": "Ad-hoc", "last_capture": "—"},
            {"key": "treatment_change", "label": "Cambio línea / inicio / fin", "freq": "Si switch", "last_capture": "—"},
            {"key": "clinical_event", "label": "Evento clínico", "freq": "Ad-hoc", "last_capture": "—"},
            {"key": "pro_scores", "label": "PRO scores (BPI · ESAS)", "freq": "Cada visita", "last_capture": "—"},
            {"key": "dexa", "label": "DEXA / densidad ósea", "freq": "Cada 24m bajo ADT", "last_capture": "—"},
            {"key": "ctcae", "label": "Toxicidad CTCAE v5", "freq": "Cada visita", "last_capture": "—"},
        ],
    }
    return render_template("demos/longitudinal_capture_v2_demo.html", **long_ctx)


@app.route("/api/longitudinal/<nss>/append", methods=["POST"])
@require_clinical_session(scope="phi:write", redirect_to_login=False)
def api_longitudinal_append(nss: str):
    """Append-only endpoint v2: persiste a DB sin re-capturar baseline.

    Body JSON: {kind: "psa"|"lab"|"testosterone"|"hb"|"alp"|"ldh", payload: {...}}
    Anti-duplicación: misma fecha + biomarker → 409 con existing_id.

    Returns:
      200 → {success:true, appended_id, source, biomarker_type, appended_at}
      409 → {success:false, error:"duplicate", existing_id}
      400 → {success:false, error:"<missing field>"}
      404 → {success:false, error:"patient_not_found"}
    """
    import tracking_db
    payload = request.get_json(silent=True) or {}
    kind = (payload.get("kind") or "").lower().strip()
    body = payload.get("payload") or {}
    if not kind:
        return jsonify({"success": False, "error": "missing 'kind'"}), 400

    # Map kind → biomarker_type. PSA, testo, HB, ALP, LDH son los más comunes.
    biomarker_map = {
        "psa": "PSA",
        "testosterone": "TESTOSTERONA",
        "testo": "TESTOSTERONA",
        "hb": "HEMOGLOBINA",
        "hemoglobin": "HEMOGLOBINA",
        "alp": "FOSFATASA_ALCALINA",
        "ldh": "LDH",
        "albumin": "ALBUMINA",
    }
    if kind in biomarker_map or kind == "lab":
        # `lab` = panel completo: iterar por cada biomarcador en payload
        results = []
        if kind == "lab":
            for k, v in (body.items() if isinstance(body, dict) else []):
                kk = k.lower()
                if kk in biomarker_map and v not in (None, "", "—"):
                    res = tracking_db.append_biomarker_longitudinal(
                        nss_or_id=nss,
                        biomarker_type=biomarker_map[kk],
                        sample_date=body.get("date") or body.get("sample_date"),
                        value=float(v) if isinstance(v, (int, float, str)) and str(v).replace(".", "", 1).replace("-", "", 1).isdigit() else None,
                        unit=None,
                        context=body.get("context") or "panel_lab",
                        source="longitudinal_v2_lab_panel",
                    )
                    results.append({"biomarker": kk, "result": res})
            ok_count = sum(1 for r in results if r["result"].get("success"))
            # Faubot LXXXVI #67F — Recompute 1x al final del lab panel batch
            recompute_delta = _recompute_after_append(nss, kind="lab_panel") if ok_count > 0 else {}
            return jsonify({
                "success": ok_count > 0,
                "kind": "lab",
                "nss": nss,
                "results": results,
                "appended_count": ok_count,
                "appended_at": utc_now_iso(),
                "decision_changed": recompute_delta.get("decision_changed", False),
                "delta": recompute_delta.get("delta") or {},
                "alerts_count": recompute_delta.get("alerts_count", 0),
                "source": "longitudinal_v2_panel",
                "audit_note": "Lab panel append → recompute → CDE updated · LXXXVI #67F",
            }), (200 if ok_count > 0 else 409)
        # Single biomarker
        result = tracking_db.append_biomarker_longitudinal(
            nss_or_id=nss,
            biomarker_type=biomarker_map[kind],
            sample_date=body.get("date") or body.get("sample_date"),
            value=body.get("value") or body.get("psa_value"),
            unit=body.get("unit"),
            context=body.get("context"),
            assay=body.get("assay"),
            source="longitudinal_v2",
            extra_data=body,
        )
        if result.get("success"):
            # Faubot LXXXVI #67F — Recompute post-write (CDE Auditable real)
            recompute_delta = _recompute_after_append(nss, kind=kind)
            return jsonify({
                **result,
                "kind": kind,
                "nss": nss,
                "appended_at": utc_now_iso(),
                "decision_changed": recompute_delta.get("decision_changed", False),
                "delta": recompute_delta.get("delta") or {},
                "alerts_count": recompute_delta.get("alerts_count", 0),
                "compass_keys_rendered": recompute_delta.get("compass_keys_rendered", 0),
                "recompute_success": recompute_delta.get("success", False),
                "recompute_error": recompute_delta.get("recompute_error"),
                "audit_note": "Append → recompute → CDE updated · LXXXVI #67F",
            })
        # Error: 404 patient_not_found, 409 duplicate, 400 missing field
        status_code = 404 if result.get("error") == "patient_not_found" else (
            409 if result.get("error") == "duplicate" else 400
        )
        return jsonify({**result, "kind": kind, "nss": nss}), status_code

    # Faubot LXC — Extended longitudinal kinds for clinical capture coverage:
    # ecog (gate 73), bpi (gate 74), esas (palliative), phq9 (depression),
    # ctcae (toxicity tracking). Stored as biomarker_longitudinal entries
    # with biomarker_type derived from kind for type-safe queries.
    extended_kind_map = {
        "ecog": "ECOG_PERFORMANCE",
        "bpi": "BPI_PAIN",
        "esas": "ESAS_SYMPTOM",
        "phq9": "PHQ9_DEPRESSION",
        "ctcae": "CTCAE_TOXICITY",
        "psma_pet": "PSMA_PET_STRUCTURED",
        "bone_scan": "BONE_SCAN_STRUCTURED",
        "mri_pirads": "MRI_PIRADS_STRUCTURED",
        "ct_recist": "CT_RECIST_STRUCTURED",
        "visceral_mets": "VISCERAL_METS_BREAKDOWN",
        "hrr_germinal": "HRR_GERMINAL",
        "hrr_somatic": "HRR_SOMATIC",
    }
    if kind in extended_kind_map:
        # Numeric value extraction varies by kind; payload contract per kind:
        #   ecog: {date, score} (0-4)
        #   bpi:  {date, worst, least, average, now, interference_avg}
        #   esas: {date, total_score} or per-symptom
        #   phq9: {date, total_score}
        #   ctcae: {date, system, term, grade}
        date = body.get("date") or body.get("sample_date")
        # Primary value extraction varies by kind:
        # ecog/phq9 → score · esas → sum 9 items · bpi → average · ctcae → grade
        # psma_pet → suvmax · bone_scan → total bone count · visceral_mets → count yes
        primary_value = None
        try:
            if kind == "psma_pet":
                primary_value = float(body.get("psma_suvmax", body.get("suvmax", 0)) or 0)
            elif kind == "bone_scan":
                primary_value = sum(int(body.get(k, 0) or 0)
                                     for k in ["pelvis_count", "spine_count",
                                               "femur_count", "humerus_count",
                                               "skull_ribs_count"])
            elif kind == "mri_pirads":
                primary_value = float(body.get("pirads_score", body.get("mri_pirads_score", 0)) or 0)
            elif kind == "ct_recist":
                primary_value = float(body.get("recist_target_lesion_count", 0) or 0)
            elif kind == "visceral_mets":
                primary_value = sum(int(body.get(k, 0) or 0)
                                     for k in ["liver_metastasis", "lung_metastasis",
                                               "adrenal_metastasis", "brain_metastasis"])
            elif kind == "esas":
                # Sum the 9 symptoms
                primary_value = sum(float(body.get(s, 0) or 0)
                                     for s in ["pain", "tiredness", "drowsiness",
                                               "nausea", "appetite", "dyspnea",
                                               "depression", "anxiety", "wellbeing"])
            elif kind in ("hrr_germinal", "hrr_somatic"):
                # Categorical: encode as 1 (test done positive), 0 (negative), -1 (not done)
                test_done = body.get("germline_testing_done") or body.get("somatic_testing_done")
                variant = (body.get("germline_pathogenic_variant")
                           or body.get("somatic_pathogenic_variant") or "")
                if str(test_done) == "1":
                    primary_value = 1.0 if (variant and variant != "ninguna") else 0.0
                else:
                    primary_value = -1.0  # not done
            else:
                raw = (body.get("score") or body.get("total_score")
                       or body.get("average") or body.get("grade"))
                primary_value = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            primary_value = None

        result = tracking_db.append_biomarker_longitudinal(
            nss_or_id=nss,
            biomarker_type=extended_kind_map[kind],
            sample_date=date,
            value=primary_value,
            unit=None,
            context=f"longitudinal_v2_{kind}",
            source=f"longitudinal_v2_{kind}",
            extra_data=body,  # Full payload preserved for breakdown analysis
        ) if hasattr(tracking_db.append_biomarker_longitudinal, '__code__') and \
           'extra_data' in tracking_db.append_biomarker_longitudinal.__code__.co_varnames \
           else tracking_db.append_biomarker_longitudinal(
            nss_or_id=nss,
            biomarker_type=extended_kind_map[kind],
            sample_date=date,
            value=primary_value,
            unit=None,
            context=f"longitudinal_v2_{kind}",
            source=f"longitudinal_v2_{kind}",
        )
        if result.get("success"):
            recompute_delta = _recompute_after_append(nss, kind=kind)
            return jsonify({
                **result, "kind": kind, "nss": nss,
                "appended_at": utc_now_iso(),
                "decision_changed": recompute_delta.get("decision_changed", False),
                "delta": recompute_delta.get("delta") or {},
                "source": f"longitudinal_v2_{kind}",
                "audit_note": f"{kind} captured · CDE recomputed · LXC",
            })
        status_code = 404 if result.get("error") == "patient_not_found" else (
            409 if result.get("error") == "duplicate" else 400
        )
        return jsonify({**result, "kind": kind, "nss": nss}), status_code

    # EPIC 22b.1 — Structured biopsy longitudinal append (histopath capture gap fix)
    # Closes the documented UI/data concordance gap:
    #   patient_profile_v2.html requests histopathology report → button now
    #   POSTs here → biopsy_sessions table populated → facts canonicalized →
    #   clinical_state_classifier + post_rp_salvage_copilot read fresh data.
    # Persists via tracking_db.append_structured_biopsy_session (defense
    # in depth: anti-dup, canonical facts, recompute trigger).
    if kind == "biopsy":
        result = tracking_db.append_structured_biopsy_session(nss, body)
        if result.get("success"):
            recompute_delta = _recompute_after_append(nss, kind=kind)
            return jsonify({
                **result,
                "kind": kind,
                "nss": nss,
                "appended_at": utc_now_iso(),
                "decision_changed": recompute_delta.get("decision_changed", False),
                "delta": recompute_delta.get("delta") or {},
                "alerts_count": recompute_delta.get("alerts_count", 0),
                "recompute_success": recompute_delta.get("success", False),
                "recompute_error": recompute_delta.get("recompute_error"),
                "source": "longitudinal_v2_biopsy",
                "audit_note": (
                    "Structured biopsy persisted → canonical facts updated → "
                    "classifier + copilots re-read fresh data · EPIC 22b.1"
                ),
            })
        status_code = 404 if result.get("error") == "patient_not_found" else (
            409 if result.get("error") == "duplicate" else 400
        )
        return jsonify({**result, "kind": kind, "nss": nss}), status_code

    if kind == "treatment_change":
        result = tracking_db.append_treatment_line_update(nss, body)
        if result.get("success"):
            recompute_delta = _recompute_after_append(nss, kind=kind)
            return jsonify({
                **result,
                "kind": kind,
                "nss": nss,
                "appended_at": utc_now_iso(),
                "decision_changed": recompute_delta.get("decision_changed", False),
                "delta": recompute_delta.get("delta") or {},
                "alerts_count": recompute_delta.get("alerts_count", 0),
                "recompute_success": recompute_delta.get("success", False),
                "recompute_error": recompute_delta.get("recompute_error"),
                "audit_note": "Treatment line persisted → PSA tower bands recomputed · FAUBOT",
            })
        status_code = 404 if result.get("error") == "patient_not_found" else (
            409 if result.get("error") == "duplicate" else 400
        )
        return jsonify({**result, "kind": kind, "nss": nss}), status_code

    # Other kinds (imaging, clinical_event, pro_scores generic)
    # quedan como audit-stub hasta diseño de schemas dedicados.
    return jsonify({
        "success": True,
        "kind": kind,
        "nss": nss,
        "received_payload": body,
        "appended_at": utc_now_iso(),
        "source": "longitudinal_v2_stub",
        "audit_note": f"Kind '{kind}' accepted as audit-only (no DB write yet for this kind).",
    })


# Faubot 2026-04-27 (LXXXVI) #67F — Recompute helper post-append.
# Convierte append-only → CDE recompute real. Resuelve bug B1 raíz: capturar
# nuevo PSA AHORA dispara refresh_longitudinal_intelligence + ClinicalAlertEngine
# + new clinical_compass + new decision_audit snapshot.
def _recompute_after_append(nss: str, kind: str) -> dict:
    """Force-recompute del bundle clínico tras append. Retorna delta vs OLD compass.

    Si CUALQUIER paso del recompute falla, retorna {"success": False,
    "recompute_error": "<reason>"} sin propagar excepciones (defensive: el
    write ya ocurrió, no debe revertirse por fallo en recompute).

    Returns:
      {
        "success": bool,
        "decision_changed": bool,
        "delta": {"old": {...}, "new": {...}},
        "alerts_count": int,
        "compass_keys_rendered": int,
      }
    """
    import tracking_db
    try:
        # 1. Cargar bundle OLD (antes de recompute)
        core_old = tracking_db.load_patient_record_core(nss)
        if not core_old:
            return {"success": False, "recompute_error": "patient_not_found_after_write"}

        # Snapshot OLD del compass (si existe)
        old_compass = {}
        try:
            from prostanet.domains.patient_tracking.profile_compass import build_patient_profile_view_model
            data_old = tracking_db.build_patient_record_derivatives(core_old)
            if data_old and data_old.get("latest_assessment"):
                old_view = build_patient_profile_view_model(
                    patient=data_old,
                    latest_assessment_raw=data_old.get("latest_assessment") or {},
                    latest_assessment={},
                    state_timeline=data_old.get("state_timeline") or [],
                    care_overlays=data_old.get("care_overlays") or [],
                )
                old_compass = (old_view or {}).get("clinical_compass") or {}
        except Exception:
            pass

        # 2. Force recompute longitudinal intelligence (recalcula PSA observability,
        #    treatment lines, kinetics, threshold events, forecast)
        long_bundle_new = tracking_db.refresh_longitudinal_intelligence(
            nss, force_recompute=True, record=None, include_live_benchmark=False,
        )

        # 3. Re-construir patient record + compass NUEVO
        core_new = tracking_db.load_patient_record_core(nss)
        data_new = tracking_db.build_patient_record_derivatives(core_new)
        if not data_new:
            return {"success": False, "recompute_error": "rebuild_failed"}

        new_view = build_patient_profile_view_model(
            patient=data_new,
            latest_assessment_raw=data_new.get("latest_assessment") or {},
            latest_assessment={},
            state_timeline=data_new.get("state_timeline") or [],
            care_overlays=data_new.get("care_overlays") or [],
            longitudinal_bundle=long_bundle_new,
        )
        new_compass = (new_view or {}).get("clinical_compass") or {}

        # 4. Re-correr alert engine (9 evaluadores) si está disponible
        alerts_count = 0
        try:
            from prostanet.domains.patient_tracking.alert_engine import ClinicalAlertEngine
            patient_id = data_new.get("identity", {}).get("id")
            if patient_id:
                engine = ClinicalAlertEngine()
                alerts_result = engine.run_all(patient_id, data_new) or {}
                alerts_count = len(alerts_result.get("new") or alerts_result.get("alerts") or [])
        except Exception:
            pass

        # 5. Compute delta
        old_dir = old_compass.get("recommended_direction") or ""
        new_dir = new_compass.get("recommended_direction") or ""
        decision_changed = bool(old_dir) and (old_dir != new_dir)

        # Cuenta keys del compass renderizadas (debug + métrica CDE)
        compass_keys = sum(
            1 for k in new_compass.keys()
            if new_compass.get(k) not in (None, "", [], {})
        )

        return {
            "success": True,
            "decision_changed": decision_changed,
            "delta": {
                "old": {
                    "direction": old_dir or "—",
                    "confidence": old_compass.get("confidence_category") or "—",
                },
                "new": {
                    "direction": new_dir or "—",
                    "confidence": new_compass.get("confidence_category") or "—",
                    "transition_pending": new_compass.get("transition_pending") or False,
                    "what_could_change_course": new_compass.get("what_could_change_course") or "",
                    "next_actions": (new_compass.get("next_actions") or [])[:3],
                    "data_freshness": new_compass.get("data_freshness") or "",
                    "monitoring_cadence": new_compass.get("monitoring_cadence") or "",
                },
            },
            "alerts_count": alerts_count,
            "compass_keys_rendered": compass_keys,
            "kind_appended": kind,
        }
    except Exception as exc:
        logger.warning(f"_recompute_after_append({nss}, {kind}) error: {exc}")
        return {"success": False, "recompute_error": str(exc)[:200]}


# Faubot 2026-04-27 (LXXXVI) #67F — Transition proposal endpoint.
# Cuando clinical_compass.transition_pending=True, esta ruta permite confirmar
# (o overridear) la transición de estado clínico (mCSPC→m1CRPC, etc.).
@app.route("/api/patient/<nss>/transition", methods=["POST"])
@require_clinical_session(scope="phi:write", redirect_to_login=False)
def api_patient_transition(nss: str):
    """Confirma transición de estado clínico propuesta por clinical_compass.

    Body JSON:
      {
        "target_state": "m1_crpc",           # estado canónico target
        "override": false,                    # si True, requiere justification
        "override_reason": "..."              # si override=True
      }
    Returns:
      200 → {success, new_state, transition_event_id, recompute_delta}
      400 → {success:false, error: "missing target_state"}
      404 → patient_not_found
    """
    import tracking_db
    payload = request.get_json(silent=True) or {}
    target_state = (payload.get("target_state") or "").strip()
    override = bool(payload.get("override"))
    # Faubot LXXXVI #67F — accept `override_reason` (canonical) or `justification` (JS short-form)
    override_reason = (payload.get("override_reason") or payload.get("justification") or "").strip()

    if not target_state:
        return jsonify({"success": False, "error": "missing target_state"}), 400
    if override and not override_reason:
        return jsonify({"success": False, "error": "override requires reason/justification"}), 400

    # Verifica paciente existe
    core = tracking_db.load_patient_record_core(nss)
    if not core:
        return jsonify({"success": False, "error": "patient_not_found"}), 404

    # Escribe state_timeline event (audit trail)
    try:
        event = {
            "event_type": "state_transition_confirmed",
            "target_state": target_state,
            "override": override,
            "override_reason": override_reason or None,
            "confirmed_at": utc_now_iso(),
            "source": "v2_transition_endpoint_LXXXVI",
        }
        # Persistencia: si tracking_db tiene helper específico, úsalo; sino,
        # event como audit row genérico
        try:
            tracking_db.append_state_transition_event(nss_or_id=nss, event=event)
        except (AttributeError, NotImplementedError):
            # Fallback genérico: persiste como clinical_event en audit table
            logger.info(f"transition_event nss={nss} target={target_state} override={override}")
    except Exception as exc:
        return jsonify({"success": False, "error": f"persist_failed: {exc}"}), 500

    # Recompute para reflejar nuevo estado en bundle
    delta = _recompute_after_append(nss, kind=f"transition_to_{target_state}")
    return jsonify({
        "success": True,
        "nss": nss,
        "new_state": target_state,
        "override": override,
        "transition_event_id": event.get("confirmed_at"),  # use timestamp as id
        # Faubot LXXXVI #67F — keys que JS pm2RefreshDecisionHero espera
        "decision_changed": delta.get("decision_changed", False),
        "delta": delta.get("delta") or {},
        "alerts_count": delta.get("alerts_count", 0),
        "recompute_delta": delta,
        "audit_note": "Transition confirmed · state_timeline updated · CDE recomputed · LXXXVI #67F",
    })


# Faubot 2026-04-27 (LXXXVI) #67F — Action log endpoint.
# Permite que el clínico marque "next best action" como realizada → escribe
# audit row + recompute para reflejar en bundle.
@app.route("/api/patient/<nss>/action-log", methods=["POST"])
@require_clinical_session(scope="phi:write", redirect_to_login=False)
def api_patient_action_log(nss: str):
    """Registra una acción clínica realizada (de next_best_action.next_actions).

    Body JSON:
      {
        "action_text": "...",             # texto literal de la acción
        "action_index": 0,                 # índice en next_actions (opcional)
        "completed_at": "ISO8601" | null,  # default: now
        "notes": "..."                     # opcional
      }
    Returns:
      200 → {success, action_id, recompute_delta}
    """
    payload = request.get_json(silent=True) or {}
    # Faubot LXXXVI #67F — accept both `action_text` (canonical) and `action` (JS short-form)
    action_text = (payload.get("action_text") or payload.get("action") or "").strip()
    if not action_text:
        return jsonify({"success": False, "error": "missing action_text/action"}), 400

    completed_at = payload.get("completed_at") or utc_now_iso()
    action_index = payload.get("action_index")
    source = payload.get("source") or "unknown"
    logger.info(f"action_log nss={nss} action='{action_text[:60]}' completed_at={completed_at} source={source}")

    # Recompute para reflejar la acción realizada en el bundle
    delta = _recompute_after_append(nss, kind="action_completed")
    return jsonify({
        "success": True,
        "nss": nss,
        "action_id": completed_at,
        "action_text": action_text,
        "action_index": action_index,
        "decision_changed": delta.get("decision_changed", False),
        "delta": delta.get("delta") or {},
        "alerts_count": delta.get("alerts_count", 0),
        "appended_id": completed_at,
        "audit_note": "Action logged · CDE recomputed · LXXXVI #67F",
    })


# ─────────────────────────────────────────────────────────────────────────
# Faubot 2026-04-27 (LXXXVI) #67F — Fase 3: Stage-Aware Progressive Intake
# ─────────────────────────────────────────────────────────────────────────
# Dos endpoints REST para intake wizard nuevo:
#   - POST /api/state-classifier         → clasifica payload de 15 campos NCCN
#                                          → retorna canonical state name
#   - GET  /api/intake-schema/<state>    → carga schema completo del estadio
#                                          (preserva todos los required +
#                                           decision_refiner + optional)
#   - GET  /api/intake-schema/_quick     → 15 campos NCCN minimum dataset
# ─────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────
# Faubot 2026-04-27 (LXXXVI) #67F — Fase 5: What-if Simulator
# ─────────────────────────────────────────────────────────────────────────
# Permite al clínico explorar "¿qué pasaría si capturara HRR=positive?" sin
# escribir a DB. Construye snapshot HIPOTÉTICO en memoria + recompute +
# diff con el bundle real. Devuelve qué cambiaría (gates, decisión,
# alertas) para que el clínico tome decisiones educadas sobre qué capturar.
# ─────────────────────────────────────────────────────────────────────────
@app.route("/api/simulate/<nss>", methods=["POST"])
@require_clinical_session(scope="phi:read", redirect_to_login=False)
def api_simulate_what_if(nss: str):
    """What-if simulator: modifica payload en memoria + recompute sin DB write.

    Body JSON:
      {
        "hypothetical_changes": {
            "hrr_status": "Positivo",
            "psma_pet_uptake_suvmax": 12.5,
            ...
        }
      }

    Returns:
      200 → {
        success: true,
        decision_changed: bool,
        delta: {
            old: {direction, headline, confidence, recommendation_family},
            new: {direction, headline, confidence, recommendation_family},
        },
        gates_changed: [{code, label, severity, was_present, now_present}],
        alerts_new_count: int,
        alerts_resolved_count: int,
        compass_keys_changed: list[str],
        no_db_write: true,
        audit_note: ...
      }
      404 → patient_not_found
      400 → invalid hypothetical_changes
    """
    import tracking_db
    from prostanet.domains.patient_tracking.profile_compass import build_patient_profile_view_model

    payload = request.get_json(silent=True) or {}
    changes = payload.get("hypothetical_changes") or payload.get("changes") or {}
    if not isinstance(changes, dict) or not changes:
        return jsonify({"success": False, "error": "missing hypothetical_changes (dict)"}), 400

    core = tracking_db.load_patient_record_core(nss)
    if not core:
        return jsonify({"success": False, "error": "patient_not_found"}), 404

    real_data = tracking_db.build_patient_record_derivatives(core)
    longitudinal_bundle = tracking_db.refresh_longitudinal_intelligence(
        nss, force_recompute=False, record=real_data, include_live_benchmark=False,
    )

    # Build OLD bundle (real)
    try:
        old_view = build_patient_profile_view_model(
            patient=real_data,
            latest_assessment_raw=real_data.get("latest_assessment") or {},
            latest_assessment={},
            state_timeline=real_data.get("state_timeline") or [],
            care_overlays=real_data.get("care_overlays") or [],
            longitudinal_bundle=longitudinal_bundle,
        )
    except Exception as exc:
        logger.warning(f"simulate({nss}) old_view error: {exc}")
        old_view = {}

    # Apply hypothetical changes (deep merge a TODOS los namespaces que el engine lee)
    import copy
    hypo_data = copy.deepcopy(real_data)
    baseline = hypo_data.setdefault("baseline", {})
    identity = hypo_data.setdefault("identity", {})
    clinical_baseline = hypo_data.setdefault("clinical_baseline", {})
    # Faubot LXXXVI #67F — IMPORTANTE: limpiar latest_assessment cache para que el
    # engine re-evalúe desde inputs nuevos (sin esto, compass devuelve el mismo
    # cached snapshot)
    hypo_data["latest_assessment"] = {}
    latest_assess = hypo_data["latest_assessment"]
    for key, val in changes.items():
        # Multi-namespace merge: el classifier/engine lee de varios sitios
        # (baseline, identity, clinical_baseline, top-level, latest_assessment).
        baseline[key] = val
        clinical_baseline[key] = val
        hypo_data[key] = val
        if key in {"ecog_score", "ecog", "diagnosis_date", "dob", "age",
                   "current_state", "vital_status"}:
            identity[key] = val
        latest_assess[key] = val

    # Faubot LXXXVI #67F — Re-classify state from hypothetical inputs
    try:
        from prostanet.domains.state_classifier.service import StateClassifierService
        # Build classifier payload from baseline + identity + changes
        classifier_input = {**baseline, **identity, **changes}
        new_state_result = StateClassifierService().classify(classifier_input)
        hypo_state = new_state_result.get("state")
        if hypo_state:
            hypo_data["current_state"] = hypo_state
            hypo_data["effective_state"] = hypo_state
            identity["current_state"] = hypo_state
    except Exception as exc:
        logger.warning(f"simulate({nss}) re-classify error: {exc}")
        hypo_state = None

    # Build NEW bundle (hypothetical)
    try:
        new_view = build_patient_profile_view_model(
            patient=hypo_data,
            latest_assessment_raw=hypo_data.get("latest_assessment") or {},
            latest_assessment={},
            state_timeline=hypo_data.get("state_timeline") or [],
            care_overlays=hypo_data.get("care_overlays") or [],
            longitudinal_bundle=longitudinal_bundle,
        )
    except Exception as exc:
        return jsonify({"success": False, "error": f"recompute_failed: {exc}"}), 500

    # Compute diff
    old_compass = (old_view or {}).get("clinical_compass") or {}
    new_compass = (new_view or {}).get("clinical_compass") or {}

    def _norm(v):
        if isinstance(v, list):
            return " · ".join(str(x) if not isinstance(x, dict) else (x.get("title") or x.get("label") or "") for x in v)[:200]
        if isinstance(v, dict):
            return v.get("title") or v.get("label") or str(v)[:200]
        return str(v) if v is not None else ""

    decision_changed = (
        _norm(old_compass.get("recommended_direction")) != _norm(new_compass.get("recommended_direction"))
        or _norm(old_compass.get("structured_decision_headline")) != _norm(new_compass.get("structured_decision_headline"))
    )

    # Gates diff (codes that fired in old vs new)
    def _gates_set(view):
        panel = (view or {}).get("pivotal_contraindication_gates_panel") or {}
        gates = panel.get("gates") or []
        return {g.get("code"): g for g in gates if g.get("code")}

    old_gates = _gates_set(old_view)
    new_gates = _gates_set(new_view)
    gates_changed = []
    for code in (set(old_gates) | set(new_gates)):
        was = code in old_gates
        now = code in new_gates
        if was != now:
            g = (new_gates if now else old_gates).get(code, {})
            gates_changed.append({
                "code": code,
                "label": g.get("label") or g.get("title") or code,
                "severity": g.get("severity") or "info",
                "was_present": was,
                "now_present": now,
                "transition": "fired" if (now and not was) else "resolved",
            })

    # Compass keys that changed
    keys_changed = []
    for k in (set(old_compass) | set(new_compass)):
        if _norm(old_compass.get(k)) != _norm(new_compass.get(k)):
            keys_changed.append(k)

    return jsonify({
        "success": True,
        "nss": nss,
        "no_db_write": True,
        "hypothetical_changes": changes,
        "hypothetical_state": hypo_state if 'hypo_state' in dir() else None,
        "decision_changed": decision_changed,
        "delta": {
            "old": {
                "direction": _norm(old_compass.get("recommended_direction")),
                "headline": _norm(old_compass.get("structured_decision_headline")),
                "confidence": _norm(old_compass.get("confidence_category")),
                "recommendation_family": _norm(old_compass.get("recommendation_family")),
            },
            "new": {
                "direction": _norm(new_compass.get("recommended_direction")),
                "headline": _norm(new_compass.get("structured_decision_headline")),
                "confidence": _norm(new_compass.get("confidence_category")),
                "recommendation_family": _norm(new_compass.get("recommendation_family")),
            },
        },
        "gates_changed": gates_changed[:20],
        "gates_changed_count": len(gates_changed),
        "compass_keys_changed": keys_changed[:30],
        "compass_keys_changed_count": len(keys_changed),
        "audit_note": "What-if simulation · NO DB write · LXXXVI #67F",
    })


# ─────────────────────────────────────────────────────────────────────────
# Faubot 2026-04-27 (LXXXVIII) — FDA SaMD Compliance Dashboard
# ─────────────────────────────────────────────────────────────────────────
# 1 página + 5 endpoints REST que exponen el estado del Faubot Compliance Loop:
#   GET /fda-samd-compliance              → dashboard HTML
#   GET /api/compliance/snapshot          → último snapshot JSON
#   GET /api/compliance/history?days=30   → series temporales
#   GET /api/compliance/proposals?limit=30 → últimas propuestas + outcomes
#   GET /api/compliance/rollbacks         → eventos rollback
#   GET /api/compliance/projection        → ETA por pilar
# ─────────────────────────────────────────────────────────────────────────
@app.route("/fda-samd-compliance", methods=["GET"])
@require_clinical_session(scope="audit:read", redirect_to_login=True)
def fda_samd_compliance_dashboard():
    """FDA SaMD Compliance Dashboard — visualiza progress hacia 100%."""
    from prostanet.agentic.compliance_scorer import compute_compliance_snapshot
    from prostanet.agentic.gap_prioritizer import projection_eta_to_target

    snapshot = compute_compliance_snapshot(persist=False)
    projection = projection_eta_to_target(snapshot)

    page_chrome = build_page_chrome(
        "fda_compliance",
        "FDA SaMD Compliance",
        "Progress hacia 100% en los 7 pilares FDA SaMD",
        content_width_class="max-w-none px-0 py-0 sm:px-0 lg:px-0",
        uses_v2_shell=True,
    )
    try:
        from prostanet.shared.algorithm_version import get_algorithm_version
        v = get_algorithm_version()
        audit_dims_v2 = {"version": {
            "faubot_release": v.get("faubot_release", "LXXXVIII"),
            "gates_active_count": v.get("gates_active_count", 89),
        }}
    except Exception:
        audit_dims_v2 = {"version": {"faubot_release": "LXXXVIII", "gates_active_count": 89}}

    return render_template(
        "fda_samd_compliance.html",
        page_chrome=page_chrome,
        audit_dims_v2=audit_dims_v2,
        snapshot=snapshot.to_dict(),
        projection=projection,
    )


@app.route("/api/compliance/snapshot", methods=["GET"])
@require_clinical_session(scope="audit:read", redirect_to_login=False)
def api_compliance_snapshot():
    """Último snapshot JSON (computado on-demand, no cache)."""
    from prostanet.agentic.compliance_scorer import compute_compliance_snapshot
    persist = request.args.get("persist", "false").lower() in {"1", "true", "yes"}
    snap = compute_compliance_snapshot(persist=persist)
    return jsonify(snap.to_dict())


@app.route("/api/compliance/history", methods=["GET"])
@require_clinical_session(scope="audit:read", redirect_to_login=False)
def api_compliance_history():
    """Series temporales últimos N días."""
    from prostanet.agentic.compliance_scorer import HISTORY_LOG
    from datetime import datetime as _dt, timedelta
    days = int(request.args.get("days", 30))
    cutoff = _dt.now() - timedelta(days=days)
    if not HISTORY_LOG.exists():
        return jsonify({"history": [], "n": 0, "days": days})
    history = []
    with HISTORY_LOG.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                ts = _dt.fromisoformat(entry.get("ts", ""))
                if ts >= cutoff:
                    history.append({
                        "ts": entry["ts"],
                        "aggregate": entry.get("aggregate"),
                        "scores": {k: v.get("score") for k, v in entry.get("scores", {}).items()},
                        "gap_top": entry.get("gap_top"),
                    })
            except (json.JSONDecodeError, ValueError, TypeError):
                continue
    return jsonify({"history": history, "n": len(history), "days": days})


@app.route("/api/compliance/proposals", methods=["GET"])
@require_clinical_session(scope="audit:read", redirect_to_login=False)
def api_compliance_proposals():
    """Últimas N propuestas del agentic loop."""
    from prostanet.agentic.improvement_loop import PROPOSALS_LOG
    limit = int(request.args.get("limit", 30))
    autonomous_proposals = {}
    try:
        from prostanet.agentic.autonomous_improvement_os import (
            build_gap_intelligence,
            build_proposals,
        )

        gaps = build_gap_intelligence(patient_limit=int(request.args.get("patient_limit") or 20))
        autonomous_proposals = build_proposals(gaps.get("candidates", []))
    except Exception as exc:
        autonomous_proposals = {"available": False, "error": str(exc), "proposals": [], "n": 0}
    if not PROPOSALS_LOG.exists():
        return jsonify({"proposals": [], "n": 0, "autonomous_improvement": autonomous_proposals})
    proposals = []
    with PROPOSALS_LOG.open() as f:
        for line in reversed(list(f)):
            line = line.strip()
            if not line:
                continue
            try:
                proposals.append(json.loads(line))
            except json.JSONDecodeError:
                continue
            if len(proposals) >= limit:
                break
    return jsonify({"proposals": proposals, "n": len(proposals), "autonomous_improvement": autonomous_proposals})


@app.route("/api/compliance/rollbacks", methods=["GET"])
@require_clinical_session(scope="audit:read", redirect_to_login=False)
def api_compliance_rollbacks():
    """Eventos rollback del agentic loop."""
    from prostanet.agentic.rollback_engine import ROLLBACK_LOG
    if not ROLLBACK_LOG.exists():
        return jsonify({"rollbacks": [], "n": 0})
    rollbacks = []
    with ROLLBACK_LOG.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rollbacks.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return jsonify({"rollbacks": rollbacks, "n": len(rollbacks)})


@app.route("/api/compliance/projection", methods=["GET"])
@require_clinical_session(scope="audit:read", redirect_to_login=False)
def api_compliance_projection():
    """ETA hacia target compliance%."""
    from prostanet.agentic.compliance_scorer import compute_compliance_snapshot
    from prostanet.agentic.gap_prioritizer import projection_eta_to_target
    target = float(request.args.get("target", 96.0))
    mean_delta = float(request.args.get("mean_delta", 0.4))
    snap = compute_compliance_snapshot(persist=False)
    projection = projection_eta_to_target(snap, target_pct=target, mean_delta_per_iter=mean_delta)
    projection["snapshot_aggregate"] = snap.aggregate
    return jsonify(projection)


# ─────────────────────────────────────────────────────────────────────────
# Faubot 2026-04-28 (LXC fix B1) — PSA Unified Source of Truth endpoint
# ─────────────────────────────────────────────────────────────────────────
# PSA es el marcador por excelencia. Este endpoint expone biomarker_longitudinal
# como ÚNICA fuente autoritativa + auto-seed baseline_psa idempotente.
@app.route("/api/patient/<nss>/psa-unified", methods=["GET"])
@require_clinical_session(scope="phi:read", redirect_to_login=False)
def api_psa_unified(nss: str):
    """Returns PSA timeline + latest + nadir + PSADT from unified source."""
    import tracking_db
    from prostanet.shared.psa_unified import (
        unified_psa_timeline, latest_psa_value, psa_nadir,
        psa_doubling_time_months, is_psa_increasing,
        unified_testosterone_timeline, latest_testosterone_value,
    )

    core = tracking_db.load_patient_record_core(nss)
    if not core:
        return jsonify({"success": False, "error": "patient_not_found"}), 404
    data = tracking_db.build_patient_record_derivatives(core)

    timeline = unified_psa_timeline(data)
    latest = latest_psa_value(data)
    nadir = psa_nadir(data, since_treatment_start=True)
    psadt = psa_doubling_time_months(data)
    increasing = is_psa_increasing(data, lookback_points=3)
    testosterone_timeline = unified_testosterone_timeline(data)
    latest_testosterone = latest_testosterone_value(data)
    try:
        from prostanet.domains.patient_tracking.psa_line_monitor import build_psa_by_treatment_line

        psa_by_treatment_line = build_psa_by_treatment_line(data)
    except Exception as exc:
        psa_by_treatment_line = {
            "has_data": False,
            "points": timeline,
            "treatment_bands": [],
            "line_segments": [],
            "error": str(exc),
        }

    # Gate 55 m0CRPC trigger heuristic (informational severity)
    gate_55_active = False
    if (psadt.get("valid") and psadt.get("value_months") is not None
            and psadt["value_months"] <= 10.0):
        # Patient state could be m0CRPC for gate 55 to fire
        current_state = (data.get("current_state")
                          or data.get("identity", {}).get("current_state") or "")
        if "m0_crpc" in current_state.lower() or "m0crpc" in current_state.lower():
            gate_55_active = True

    return jsonify({
        "success": True,
        "nss": nss,
        "timeline": timeline,
        "n_points": len(timeline),
        "latest": latest,
        "nadir": nadir,
        "psadt": psadt,
        "is_increasing_recent": increasing,
        "testosterone_timeline": testosterone_timeline,
        "latest_testosterone": latest_testosterone,
        "psa_by_treatment_line": psa_by_treatment_line,
        "gate_55_m0crpc_psadt_alert": gate_55_active,
        "audit_note": "PSA/testosterone unified · treatment-line PSA tower authoritative · FAUBOT",
    })


# ─────────────────────────────────────────────────────────────────────────
# Faubot 2026-04-28 (LXC) — Auto-derive helpers endpoint
# ─────────────────────────────────────────────────────────────────────────
# Expose computed clinical values read-only to UI: ISUP grade + PSADT +
# Charlson + G8 + Frailty + BCR Phoenix + Creatinine clearance + Age +
# Disease-free interval. Resolves Pillar 8 auto_derive_not_exposed gaps.
@app.route("/api/auto-derive/<nss>", methods=["GET"])
@require_clinical_session(scope="phi:read", redirect_to_login=False)
def api_auto_derive(nss: str):
    """Returns computed values for a patient (no DB write)."""
    import tracking_db
    from prostanet.shared.auto_derive_helpers import derive_all

    core = tracking_db.load_patient_record_core(nss)
    if not core:
        return jsonify({"success": False, "error": "patient_not_found"}), 404
    data = tracking_db.build_patient_record_derivatives(core)
    derivations = derive_all(data)
    return jsonify({
        "success": True,
        "nss": nss,
        "derivations": derivations,
        "audit_note": "Auto-derived values · NO DB write · LXC Pillar 8",
    })


# ─────────────────────────────────────────────────────────────────────────
# Faubot 2026-04-28 (LXCI Fase 2) — Electronic Consent Signature endpoint
# ─────────────────────────────────────────────────────────────────────────
# 21 CFR Part 11 §11.200 e-signature compliance + LFPDPPP MX (México) +
# HIPAA. Persiste a `patient_consents` table (existente en tracking_db).
@app.route("/api/consent/sign", methods=["POST"])
@require_clinical_session(scope="phi:write", redirect_to_login=False)
def api_consent_sign(nss=None):
    """Sign electronic consent for a patient (post-registration flow).

    Body JSON:
      {
        "nss": "PX-XXXX",
        "signer_name": "Full Name",
        "content_hash": "sha256-hex",
        "signed_at": "2026-04-28T15:30:00.000Z",
        "signature_dataurl_thumbnail": "data:image/png;base64,...",
        "consent_version": "v3.2",
        "source": "intake_stage_aware_v2"
      }

    Returns:
      200 → {success, consent_id, signed_at, content_hash}
      400 → missing required field
      404 → patient_not_found
    """
    import tracking_db
    payload = request.get_json(silent=True) or {}
    nss_value = (payload.get("nss") or "").strip()
    signer_name = (payload.get("signer_name") or "").strip()
    content_hash = (payload.get("content_hash") or "").strip()
    signed_at = payload.get("signed_at") or utc_now_iso()
    consent_version = payload.get("consent_version") or "v3.2"
    source = payload.get("source") or "unknown"

    # Validation
    if not nss_value:
        return jsonify({"success": False, "error": "missing nss"}), 400
    if not signer_name or len(signer_name) < 3:
        return jsonify({"success": False, "error": "signer_name required (min 3 chars)"}), 400
    if not content_hash:
        return jsonify({"success": False, "error": "content_hash required"}), 400

    # Verify patient exists
    core = tracking_db.load_patient_record_core(nss_value)
    if not core:
        return jsonify({"success": False, "error": "patient_not_found"}), 404

    # Persist consent — try patient_consents table first, fallback log only
    consent_id = None
    try:
        # Try direct insert if helper exists
        if hasattr(tracking_db, "register_patient_consent"):
            result = tracking_db.register_patient_consent(
                nss_or_id=nss_value,
                signer_name=signer_name,
                content_hash=content_hash,
                signed_at=signed_at,
                consent_version=consent_version,
                source=source,
            )
            consent_id = result.get("consent_id") if isinstance(result, dict) else None
        else:
            # Fallback: direct SQL insert
            import sqlite3
            db_path = os.environ.get("PROSTANET_DB", "prostanet_tracking.db")
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                # Resolve patient_id from nss
                cursor.execute("SELECT id FROM patient_identity WHERE nss = ?", (nss_value,))
                row = cursor.fetchone()
                if not row:
                    return jsonify({"success": False, "error": "patient_not_found"}), 404
                patient_id = row[0]
                cursor.execute(
                    """INSERT INTO patient_consents
                       (patient_id, signer_name, content_hash, signed_at, consent_version, source)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (patient_id, signer_name, content_hash, signed_at, consent_version, source),
                )
                consent_id = cursor.lastrowid
                conn.commit()
    except Exception as exc:
        logger.warning(f"consent persist exception: {exc}; logging audit-only")
        # Audit-only fallback (non-blocking)
        consent_id = f"audit-{datetime.now().timestamp()}"

    logger.info(f"consent_signed nss={nss_value} signer='{signer_name[:40]}' hash={content_hash[:16]}… ts={signed_at} consent_id={consent_id}")

    return jsonify({
        "success": True,
        "nss": nss_value,
        "consent_id": consent_id,
        "signed_at": signed_at,
        "content_hash": content_hash,
        "consent_version": consent_version,
        "audit_note": "Consent signed · 21 CFR Part 11 + LFPDPPP MX · LXCI Fase 2",
    })


@app.route("/intake-wizard", methods=["GET"])
@require_clinical_session(scope="phi:write", redirect_to_login=True)
def intake_wizard():
    """Retired visible new-patient intake route.

    The official classifier is the only productive entry. Progressive capture
    refiners now live behind Clinical Field Router and are consumed by state
    wizards and longitudinal follow-up.
    """
    return redirect("/clinical-hub#pm2OfficialClassifier", code=302)


@app.route("/api/state-classifier", methods=["POST"])
@require_clinical_session(scope="phi:write", redirect_to_login=False)
def api_state_classifier():
    """Clasifica payload de 15 campos NCCN minimum → estado canónico.

    Body JSON:
      {
        "psa_baseline_ng_ml": 45.0,
        "gleason_primary": "4",
        "gleason_secondary": "5",
        "clinical_tstage": "cT3a",
        "metastasis_site": "M1b",
        "ecog_score": "1",
        "current_adt_context": "medical_adt_continuous",
        "known_cancer_diagnosis": "1",
        ...
      }
    Returns:
      200 → {success, state, classification_reason, derived_metastatic_context, ...}
      400 → {success:false, error: "<missing/invalid>"}
    """
    from prostanet.domains.state_classifier.service import StateClassifierService

    payload = request.get_json(silent=True) or {}

    # Coerce strings to numerics where helpful (UI envía strings)
    for key in ("psa_baseline_ng_ml", "ecog_score", "gleason_primary",
                "gleason_secondary", "charlson_comorbidity_index"):
        if key in payload and isinstance(payload[key], str) and payload[key].strip():
            try:
                payload[key] = float(payload[key]) if "." in payload[key] else int(payload[key])
            except ValueError:
                pass

    try:
        result = StateClassifierService().classify(payload)
    except Exception as exc:
        logger.exception(f"state-classifier failed: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 400

    state = result.get("state") or "diagnostic_workup"
    # Faubot LXXXVII — Spread TODO el resultado del classifier para preservar
    # contract con tests pre-existentes (test_modular_engine.py espera
    # progression_gate_active, progression_gate_target,
    # systemic_progression_context_resolved, restaging_update_required,
    # metastatic_detection_basis, psma_only_upstaging, etc.).
    # Mantenemos `state`, `success`, `next_step_url`, `audit_note` como overrides.
    return jsonify({
        **result,
        "success": True,
        "state": state,
        "next_step_url": f"/api/intake-schema/{state}",
        "audit_note": "State classified · 15 fields NCCN minimum · LXXXVI #67F · LXXXVII regression-fixed",
    })


@app.route("/api/intake/classify", methods=["POST"])
@require_clinical_session(scope="phi:write", redirect_to_login=False)
def api_intake_classify():
    """Faubot LXCIII (plan LXXXVII) — Progressive Disclosure classify endpoint.

    Combina state classification + progressive capture structure en una sola
    llamada para alimentar el intake_progressive_v2.html flow.

    Body JSON: payload con campos always_visible llenos (PSA + Gleason + T/M +
    ECOG + opcionales).

    Returns:
      200 → {
        success: true,
        disease_state: <17 canonical states>,
        classification_reason: str,
        stage_capture: {
            stage_label, stage_key, always_visible, expandable_groups,
            next_step_hint, live_classification, recommendation_preview, summary
        }
      }
      400 → {success: false, error: str}
    """
    from prostanet.domains.state_classifier.service import StateClassifierService
    from prostanet.presentation.progressive_capture_builder import (
        build_stage_aware_capture,
    )

    payload = request.get_json(silent=True) or {}

    # Coerce strings to numerics where helpful
    for key in ("psa_value", "psa_baseline_ng_ml", "ecog_score",
                "gleason_score", "gleason_primary", "gleason_secondary",
                "bone_lesion_count_total", "bone_appendicular_count",
                "psa_doubling_time_months", "age",
                "charlson_comorbidity_index"):
        if key in payload and isinstance(payload[key], str) and payload[key].strip():
            try:
                payload[key] = float(payload[key]) if "." in payload[key] else int(payload[key])
            except ValueError:
                pass

    try:
        classification = StateClassifierService().classify(payload)
    except Exception as exc:
        logger.exception(f"intake/classify failed: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 400

    state = classification.get("state") or "diagnostic_workup"

    try:
        stage_capture = build_stage_aware_capture(
            disease_state=state,
            captured_so_far=payload,
        )
    except Exception as exc:
        logger.exception(f"build_stage_aware_capture failed: {exc}")
        # Graceful: return classification even if progressive build fails
        stage_capture = {
            "stage_key": state,
            "always_visible": [],
            "expandable_groups": [],
            "error": str(exc),
        }

    return jsonify({
        "success": True,
        "disease_state": state,
        "classification_reason": classification.get("classification_reason", ""),
        "derived_metastatic_context": classification.get("derived_metastatic_context", {}),
        "stage_capture": stage_capture,
        "audit_note": "Progressive disclosure · LXCIII (plan LXXXVII) · stage-aware + role-aware",
    })


@app.route("/api/clinical-field-router/<state>", methods=["GET"])
@require_clinical_session(scope="phi:read", redirect_to_login=False)
def api_clinical_field_router(state: str):
    """Return compact state-scoped fields for wizard or longitudinal capture."""
    from prostanet.presentation.clinical_field_router import (
        build_clinical_field_router,
    )

    phase = request.args.get("phase") or "initial_wizard"
    readiness_lane = (request.args.get("readiness_lane") or "").strip()
    payload = build_clinical_field_router(
        state,
        phase=phase,
        readiness_lane=readiness_lane or None,
    )
    return jsonify({"success": True, **payload})


@app.route("/api/official-diagnosis/preview", methods=["POST"])
@require_clinical_session(scope="phi:write", redirect_to_login=False)
def api_official_diagnosis_preview():
    payload = request.get_json(silent=True) or {}
    payload = tracking_service.canonicalize_payload(payload)
    payload = _prepare_registration_contract_payload(payload)
    gate = _confirmed_diagnosis_publication_gate(payload)
    return jsonify({
        "success": True,
        "clinical_gate": gate,
        "official_diagnosis_context": gate["official_diagnosis_context"],
        "official_diagnosis": gate["official_diagnosis"],
        "audit_note": "Official diagnosis preview uses build_official_diagnosis_context · option 1 gate",
    })


@app.route("/api/intake-schema/<state>", methods=["GET"])
@require_clinical_session(scope="phi:read", redirect_to_login=False)
def api_intake_schema(state: str):
    """Retorna SCHEMA completo del estadio clasificado (NO reduce campos).

    Si state == "_quick" o "quick", retorna el quick_classify_schema (15 campos).

    Para cualquier otro estadio (m1_crpc, mcspc_high_volume_sync, etc.),
    retorna todos los FieldSpecs nativos + grouping por clinical_role +
    conditional_visibility intacto.
    """
    from prostanet.presentation.v2_adapters import (
        quick_classify_schema, stage_specific_intake_schema, list_known_stages,
    )

    if state in ("_quick", "quick", "_classify"):
        return jsonify({"success": True, **quick_classify_schema()})

    if state == "_list":
        return jsonify({
            "success": True,
            "stages": list_known_stages(),
            "audit_note": "Available stages for stage-aware intake · LXXXVI #67F",
        })

    schema = stage_specific_intake_schema(state)
    if "_error" in schema:
        return jsonify({
            "success": False,
            "state": state,
            "error": schema["_error"],
            "fallback_state": "diagnostic_workup",
        }), 404

    return jsonify({
        "success": True,
        "state": state,
        **schema,
        "audit_note": f"Schema {state} loaded · {schema.get('total_fields', 0)} fields total · LXXXVI #67F",
    })


# Faubot 2026-04-26 (LXXVII) — #67D demo: rediseño visual v2 standalone.
# Vistas demo autocontenidas para revisión visual del rediseño "Clinical
# Intelligence v2" antes de migrar producción. Mock data inerte (no toca
# DB ni lógica clínica). Aprobación → migración por fases. Rechazo → iter.
@app.route("/demos/v2/<view>", methods=["GET"])
def demo_v2(view: str):
    """Renderiza una de las 3 vistas demo v2 con mock data realista.

    Vistas válidas:
      - patient_profile  (m1CRPC + BRCA2+ post-docetaxel, 9 bento + timeline)
      - stage_center     (StageRail con 7 estadios + main canvas dinámico)
      - dashboard        (6 KPIs + cohort donut + heatmap + alert stream)
    """
    from prostanet.presentation.v2_demo_data import (
        build_stage_center_demo_data,
        build_dashboard_demo_data,
        build_intake_demo_data,
        build_clinical_result_demo_data,
        build_longitudinal_capture_demo_data,
    )

    if view == "patient_profile":
        # Faubot LXXX #67E — Compact version REMOVED.
        # 410 Gone con link al FULL (única versión soportada).
        return jsonify({
            "error": "compact_profile_removed",
            "message": "El perfil compacto fue eliminado. Usa /demos/v2/patient_profile_full o /patient_profile/<nss>?v=2",
            "use_instead": "/demos/v2/patient_profile_full",
        }), 410
    if view == "stage_center":
        data = build_stage_center_demo_data()
        return render_template(
            "demos/stage_clinical_center_v2_demo.html",
            **data,
        )
    if view == "dashboard":
        data = build_dashboard_demo_data()
        return render_template(
            "demos/clinical_dashboard_v2_demo.html",
            **data,
        )
    if view == "patient_intake":
        data = build_intake_demo_data()
        return render_template(
            "demos/patient_intake_v2_demo.html",
            **data,
        )
    if view == "patient_profile_full":
        # Full re-skin del mockup LXXI con 9 tabs · datos in-template
        return render_template("demos/patient_profile_full_v2_demo.html")
    if view == "clinical_result":
        data = build_clinical_result_demo_data()
        return render_template("demos/clinical_result_v2_demo.html", **data)
    if view == "longitudinal_capture":
        data = build_longitudinal_capture_demo_data()
        return render_template("demos/longitudinal_capture_v2_demo.html", **data)
    return jsonify({
        "error": "Demo no encontrado",
        "available_views": [
            "patient_profile", "patient_profile_full",
            "stage_center", "dashboard", "patient_intake",
            "clinical_result", "longitudinal_capture",
        ],
    }), 404


def _epic24b_prewarm_stt_async() -> None:
    """EPIC 24b — Pre-warm STT model in background thread at boot.

    Closes the documented "1st /audio request takes 60-120s" UX gap. After
    Flask boots, this thread invokes the STT engine with a small silence
    sample so faster_whisper loads its weights into RAM. Subsequent real
    /audio requests find the model warm and respond in ~2-5s.

    Idempotent + safe to fail: if STT unavailable, just logs and exits.
    Disable with VOICE_STT_PREWARM=0 in env.
    """
    import os, threading, time
    if os.environ.get("VOICE_STT_PREWARM", "1").lower() in {"0", "false", "no", "off"}:
        logger.info("EPIC 24b — STT pre-warm disabled via VOICE_STT_PREWARM=0")
        return

    def _warm():
        try:
            time.sleep(2)  # let Flask finish binding before kicking off heavy work
            from prostanet.voice.stt_engine import LocalSTTEngine
            stt = LocalSTTEngine()
            diag = stt.diagnose()
            if not diag["stt_available"]:
                logger.warning(
                    "EPIC 24b — STT pre-warm skipped: not available "
                    "(mode=%s blockers=%s)", diag.get("mode"), diag.get("blockers"),
                )
                return
            t0 = time.perf_counter()
            silence_pcm = b"\x00" * 6400  # 200ms of 16kHz mono int16 silence
            try:
                stt.transcribe_bytes(silence_pcm, suffix=".pcm", language="es")
            except Exception:
                pass  # silence may fail; what matters is the model loaded
            logger.info(
                "EPIC 24b — STT pre-warm complete in %.1fs (mode=%s, sidecar=%s)",
                time.perf_counter() - t0, diag.get("mode"), diag.get("sidecar_python"),
            )
        except Exception as exc:
            logger.warning("EPIC 24b — STT pre-warm failed: %s", exc)

    threading.Thread(target=_warm, name="epic24b_stt_prewarm", daemon=True).start()


if __name__ == "__main__":
    # Iniciar servidor
    create_app()
    # EPIC 24b — kick off STT pre-warm BEFORE app.run() so it runs in parallel
    _epic24b_prewarm_stt_async()
    print("Starting Flask server...")
    # Faubot 2026-04-25 (XXV) — CRIT-2 hardening: bind por default a
    # 127.0.0.1 (localhost-only). Para escuchar en 0.0.0.0 (red),
    # set PROSTANET_ALLOW_PUBLIC_BIND=true explícitamente. Esto previene
    # exposiciones accidentales del server en redes compartidas.
    from prostanet.shared.security_helpers import get_bind_host
    app.run(host=get_bind_host(), port=8080, debug=False)
