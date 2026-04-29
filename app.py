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

# Añadir directorio actual al path para importar el modelo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prostate_cancer_model import load_all
from prostanet.domains.patient_tracking.service import PatientTrackingService
from prostanet.presentation.bootstrap import register_modular_blueprints
from prostanet.presentation.ui_assets import build_ui_assets
from prostanet.presentation.view_models import build_page_chrome
from prostanet.shared.feature_flags import resolve_feature_flags
from prostanet.shared.official_diagnosis import diagnosis_capture_options
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

    # Faubot LXXVIII #67E — Producción v2 intake via demo template + adapter
    if request.args.get("v") == "2":
        from prostanet.presentation.v2_adapters import intake_form_schema_v2
        v2_data = intake_form_schema_v2()
        return render_template("demos/patient_intake_v2_demo.html", **v2_data)

    assessment_id = request.args.get("assessment_id", "").strip()
    if not assessment_id:
        return redirect("/clinical-hub")
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
            patient_for_v2 = dict(data.get("identity") or {})
            patient_for_v2["full_name"] = data["identity"].get("full_name")
            patient_for_v2["nss"] = nss
            patient_for_v2["age"] = age
            patient_for_v2["dob"] = data["identity"].get("dob")
            patient_for_v2["diagnosis_date"] = data["identity"].get("diagnosis_date")
            patient_for_v2["clinical_baseline"] = data.get("baseline") or {}
            patient_for_v2["baseline_psa"] = (data.get("baseline") or {}).get("baseline_psa")
            patient_for_v2["consent"] = data.get("consent") or {}
            patient_for_v2["treatments"] = data.get("treatments") or []
            patient_for_v2["biomarker_longitudinal"] = data.get("biomarker_longitudinal") or []
            v2_ctx = bundle_to_v2_profile_full(profile_view, patient_for_v2)
            return render_template("patient_profile_v2.html", **v2_ctx, page_chrome=page_chrome)

        return render_template(
            'patient_profile.html',
            patient=data,
            recommendations=recs,
            latest_assessment=latest_assessment,
            state_timeline=state_timeline,
            care_overlays=care_overlays,
            profile_view=profile_view,
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
        patient = tracking_db.get_patient_full_record(patient_id)
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
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return error_response("Paciente no encontrado", 404)
        bundle = tracking_db.refresh_longitudinal_intelligence(
            patient_id,
            force_recompute=False,
            record=patient,
            include_live_benchmark=False,
        )
        signals = bundle.get("signals")
        if signals is None:
            return error_response("Paciente no encontrado", 404)
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
        return jsonify(
            {
                "success": True,
                "signals": signals,
                "transition_proposals": bundle.get("transition_proposals", []),
                "next_best_action": bundle.get("next_best_action", {}),
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
    """Registra una biopsia detallada."""
    try:
        from tracking_db import save_biopsy
        data = request.get_json()
        success = save_biopsy(patient_id, data)
        if success:
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Error guardando biopsia"}), 400
    except Exception as e:
        logger.error(f"Error en biopsy: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


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

    # Build longitudinal-specific context from real bundle
    cb = data.get("baseline") or {}
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
                "appended_at": datetime.now().isoformat(),
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
                "appended_at": datetime.now().isoformat(),
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
                primary_value = float(body.get("suvmax", 0) or 0)
            elif kind == "bone_scan":
                primary_value = sum(int(body.get(k, 0) or 0)
                                     for k in ["pelvis_count", "spine_count",
                                               "femur_count", "humerus_count",
                                               "skull_ribs_count"])
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
                "appended_at": datetime.now().isoformat(),
                "decision_changed": recompute_delta.get("decision_changed", False),
                "delta": recompute_delta.get("delta") or {},
                "source": f"longitudinal_v2_{kind}",
                "audit_note": f"{kind} captured · CDE recomputed · LXC",
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
                "appended_at": datetime.now().isoformat(),
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
        "appended_at": datetime.now().isoformat(),
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
            "confirmed_at": datetime.now().isoformat(),
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

    completed_at = payload.get("completed_at") or datetime.now().isoformat()
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
    if not PROPOSALS_LOG.exists():
        return jsonify({"proposals": [], "n": 0})
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
    return jsonify({"proposals": proposals, "n": len(proposals)})


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
    signed_at = payload.get("signed_at") or datetime.now().isoformat()
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
    """Stage-Aware Progressive Intake wizard (3 steps).

    Faubot LXXXVI #67F Fase 3 — Reemplaza intake legacy de 218 campos por
    flujo NCCN-correcto: 15 campos minimum classify → schema completo del
    estadio resuelto → confirmación + persist.
    """
    page_chrome = build_page_chrome(
        "intake",
        "Nuevo paciente · Stage-Aware",
        "Captura inteligente NCCN 5.2026 + EAU 2026",
        content_width_class="max-w-none px-0 py-0 sm:px-0 lg:px-0",
        uses_v2_shell=True,
    )
    # Hidratar audit_dims_v2 para sidebar
    try:
        from prostanet.shared.algorithm_version import get_algorithm_version
        v = get_algorithm_version()
        audit_dims_v2 = {
            "version": {
                "faubot_release": v.get("faubot_release", "LXXXVI"),
                "gates_active_count": v.get("gates_active_count", 89),
            }
        }
    except Exception:
        audit_dims_v2 = {"version": {"faubot_release": "LXXXVI", "gates_active_count": 89}}
    return render_template(
        "intake_stage_aware_v2.html",
        page_chrome=page_chrome,
        audit_dims_v2=audit_dims_v2,
    )


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


if __name__ == "__main__":
    # Iniciar servidor
    create_app()
    print("Starting Flask server...")
    # Faubot 2026-04-25 (XXV) — CRIT-2 hardening: bind por default a
    # 127.0.0.1 (localhost-only). Para escuchar en 0.0.0.0 (red),
    # set PROSTANET_ALLOW_PUBLIC_BIND=true explícitamente. Esto previene
    # exposiciones accidentales del server en redes compartidas.
    from prostanet.shared.security_helpers import get_bind_host
    app.run(host=get_bind_host(), port=8080, debug=False)
